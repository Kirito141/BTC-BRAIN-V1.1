"""
=============================================================================
 DATA_FETCHER.PY — Fetches Data from All Sources
=============================================================================
 Handles:
   • Delta Exchange  — candles (3m/5m/15m/1h), ticker, orderbook
   • Binance          — price, klines, long/short ratio, top trader
                        positions, taker buy/sell volume, open interest
   • Alternative.me   — Fear & Greed Index
   • CoinGecko        — BTC dominance & 24h volume

 Design:
   • Each source has its own function with try/except
   • If any single source fails, bot continues with reduced data
   • CoinGecko cached (10 min), Binance futures data cached (3 min)
=============================================================================
"""

import time
import requests
import pandas as pd
from datetime import datetime, timedelta
import config

# ── Module-level caches ─────────────────────────────────────────────────────
_coingecko_cache = {"data": None, "timestamp": 0}
_binance_futures_cache = {"data": None, "timestamp": 0}
BINANCE_FUTURES_CACHE_SECONDS = 180  # 3 min cache for futures data


def _safe_request(url, params=None, timeout=10, source_name="API"):
    """
    Makes an HTTP GET request with error handling.
    Returns JSON dict on success, None on failure.
    """
    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        print(f"  [WARN] {source_name} request timed out")
        return None
    except requests.exceptions.ConnectionError:
        print(f"  [WARN] {source_name} connection failed")
        return None
    except requests.exceptions.HTTPError as e:
        print(f"  [WARN] {source_name} HTTP error: {e}")
        return None
    except Exception as e:
        print(f"  [WARN] {source_name} unexpected error: {e}")
        return None


# =============================================================================
#  DELTA EXCHANGE — Market Data
# =============================================================================

def fetch_delta_candles(resolution="5m", count=50):
    """
    Fetch OHLCV candles from Delta Exchange for BTCUSD perpetual.
    Returns DataFrame or None.
    """
    end_ts = int(time.time())
    res_map = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}
    interval_secs = res_map.get(resolution, 300)
    start_ts = end_ts - (count * interval_secs) - interval_secs

    url = f"{config.DELTA_BASE_URL}/v2/history/candles"
    params = {
        "symbol": config.DELTA_SYMBOL,
        "resolution": resolution,
        "start": start_ts,
        "end": end_ts,
    }

    data = _safe_request(url, params=params, source_name=f"Delta Candles ({resolution})")

    # Retry with numeric format if string format fails
    if data is None or not data.get("success") or not data.get("result"):
        if "h" in resolution:
            hours = int(resolution.replace("h", ""))
            params["resolution"] = str(hours * 60)
        else:
            params["resolution"] = resolution.replace("m", "")
        data = _safe_request(url, params=params, source_name=f"Delta Candles retry ({resolution})")

    if data is None or not data.get("success"):
        return None

    candles = data.get("result", [])
    if not candles:
        return None

    df = pd.DataFrame(candles)
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "time" in df.columns:
        df["time"] = pd.to_numeric(df["time"], errors="coerce")
        df = df.sort_values("time").reset_index(drop=True)

    return df


def fetch_delta_ticker():
    """Fetch current ticker for BTCUSD from Delta Exchange."""
    url = f"{config.DELTA_BASE_URL}/v2/tickers/{config.DELTA_SYMBOL}"
    data = _safe_request(url, source_name="Delta Ticker")

    if data is None or not data.get("success"):
        return None

    result = data.get("result", {})
    return {
        "mark_price": float(result.get("mark_price", 0)),
        "close": float(result.get("close", 0)),
        "high": float(result.get("high", 0)),
        "low": float(result.get("low", 0)),
        "open": float(result.get("open", 0)),
        "volume": float(result.get("volume", 0)),
        "turnover": float(result.get("turnover", 0)),
        "open_interest": float(result.get("oi", 0)),
        "funding_rate": float(result.get("funding_rate", 0) or 0),
        "product_id": result.get("product_id", config.DELTA_PRODUCT_ID),
        "symbol": result.get("symbol", config.DELTA_SYMBOL),
        # Price bands — exchange-enforced limits
        "price_band_upper": float(result.get("price_band", {}).get("upper_limit", 0) or 0),
        "price_band_lower": float(result.get("price_band", {}).get("lower_limit", 0) or 0),
        # Spot/index price
        "spot_price": float(result.get("spot_price", 0) or 0),
    }


def fetch_delta_orderbook(depth=20):
    """Fetch L2 orderbook for BTCUSD (top 20 levels)."""
    url = f"{config.DELTA_BASE_URL}/v2/l2orderbook/{config.DELTA_SYMBOL}"
    data = _safe_request(url, source_name="Delta Orderbook")

    if data is None or not data.get("success"):
        return None

    result = data.get("result", {})
    return {
        "buy": result.get("buy", [])[:depth],
        "sell": result.get("sell", [])[:depth],
    }


def fetch_delta_recent_trades():
    """
    Fetch recent public trades for BTCUSD from Delta Exchange.
    Shows actual executed trades — who's buying/selling aggressively.
    
    Each trade has: price, size, side (buy/sell), timestamp.
    This is like watching the tape — large sell trades hitting the
    bid = institutional selling pressure.
    
    Returns:
        dict with trade analysis summary, or None on failure
    """
    url = f"{config.DELTA_BASE_URL}/v2/trades/{config.DELTA_SYMBOL}"
    data = _safe_request(url, source_name="Delta Recent Trades")

    if data is None or not data.get("success"):
        return None

    trades = data.get("result", [])
    if not trades:
        return None

    # Analyze the trade flow
    buy_count = 0
    sell_count = 0
    buy_volume = 0
    sell_volume = 0
    large_trades = []  # trades with above-average size

    sizes = [float(t.get("size", 0)) for t in trades if t.get("size")]
    avg_size = sum(sizes) / len(sizes) if sizes else 0

    for t in trades:
        side = t.get("buyer_role", "").lower()  # "taker" means aggressive buyer
        size = float(t.get("size", 0))
        price = float(t.get("price", 0))

        # Delta uses "buyer_role" — if buyer is taker, it's a buy aggression
        # If seller is taker, it's sell aggression
        if side == "taker":
            buy_count += 1
            buy_volume += size
        else:
            sell_count += 1
            sell_volume += size

        # Track large trades (>2x average)
        if size > avg_size * 2 and price > 0:
            large_trades.append({
                "price": price,
                "size": size,
                "side": "BUY" if side == "taker" else "SELL",
            })

    total_count = buy_count + sell_count
    total_volume = buy_volume + sell_volume

    return {
        "total_trades": len(trades),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "buy_volume": round(buy_volume, 2),
        "sell_volume": round(sell_volume, 2),
        "buy_pct": round(buy_count / total_count * 100, 1) if total_count > 0 else 50,
        "sell_pct": round(sell_count / total_count * 100, 1) if total_count > 0 else 50,
        "volume_imbalance_pct": round((buy_volume - sell_volume) / total_volume * 100, 1) if total_volume > 0 else 0,
        "avg_trade_size": round(avg_size, 2),
        "large_trades": large_trades[:5],  # top 5 large trades
        "raw_trades": trades[:20],  # last 20 raw trades for Claude
    }


# =============================================================================
#  BINANCE — Reference Price Feed + Futures Intelligence
# =============================================================================

def fetch_binance_price():
    """Fetch current BTC spot price from Binance."""
    url = f"{config.BINANCE_BASE_URL}/api/v3/ticker/price"
    params = {"symbol": config.BINANCE_SYMBOL}
    data = _safe_request(url, params=params, source_name="Binance Price")
    if data is None:
        return None
    return float(data.get("price", 0))


def fetch_binance_klines(interval="5m", limit=50):
    """Fetch candles from Binance. Returns DataFrame or None."""
    url = f"{config.BINANCE_BASE_URL}/api/v3/klines"
    params = {"symbol": config.BINANCE_SYMBOL, "interval": interval, "limit": limit}
    data = _safe_request(url, params=params, source_name=f"Binance Klines ({interval})")

    if data is None or not isinstance(data, list) or len(data) == 0:
        return None

    expected_cols = ["time", "open", "high", "low", "close", "volume",
                     "close_time", "quote_vol", "trades", "taker_buy_base",
                     "taker_buy_quote", "ignore"]
    valid_rows = [row for row in data if isinstance(row, list) and len(row) >= 6]
    if not valid_rows:
        return None

    df = pd.DataFrame(valid_rows, columns=expected_cols[:len(valid_rows[0])])
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[["time", "open", "high", "low", "close", "volume"]]


def fetch_binance_long_short_ratio(period="5m", limit=5):
    """
    Fetch global long/short account ratio from Binance Futures.
    Shows what % of ALL traders are long vs short.
    Free, no API key needed.
    """
    url = "https://fapi.binance.com/futures/data/globalLongShortAccountRatio"
    params = {"symbol": config.BINANCE_SYMBOL, "period": period, "limit": limit}
    data = _safe_request(url, params=params, source_name="Binance L/S Ratio")

    if data is None or not isinstance(data, list) or len(data) == 0:
        return None

    latest = data[0]
    return {
        "long_short_ratio": float(latest.get("longShortRatio", 1.0)),
        "long_account_pct": float(latest.get("longAccount", 0.5)) * 100,
        "short_account_pct": float(latest.get("shortAccount", 0.5)) * 100,
        "timestamp": latest.get("timestamp", 0),
    }


def fetch_binance_top_trader_positions(period="5m", limit=5):
    """
    Fetch top trader long/short POSITION ratio from Binance Futures.
    Shows what the whales are doing (by position size, not account count).
    """
    url = "https://fapi.binance.com/futures/data/topLongShortPositionRatio"
    params = {"symbol": config.BINANCE_SYMBOL, "period": period, "limit": limit}
    data = _safe_request(url, params=params, source_name="Binance Top Trader Positions")

    if data is None or not isinstance(data, list) or len(data) == 0:
        return None

    latest = data[0]
    return {
        "long_short_ratio": float(latest.get("longShortRatio", 1.0)),
        "long_pct": float(latest.get("longAccount", 0.5)) * 100,
        "short_pct": float(latest.get("shortAccount", 0.5)) * 100,
        "timestamp": latest.get("timestamp", 0),
    }


def fetch_binance_taker_buy_sell(period="5m", limit=5):
    """
    Fetch taker buy/sell volume ratio from Binance Futures.
    Shows aggressive buying vs selling pressure.
    """
    url = "https://fapi.binance.com/futures/data/takerlongshortRatio"
    params = {"symbol": config.BINANCE_SYMBOL, "period": period, "limit": limit}
    data = _safe_request(url, params=params, source_name="Binance Taker Buy/Sell")

    if data is None or not isinstance(data, list) or len(data) == 0:
        return None

    latest = data[0]
    return {
        "buy_sell_ratio": float(latest.get("buySellRatio", 1.0)),
        "buy_volume": float(latest.get("buyVol", 0)),
        "sell_volume": float(latest.get("sellVol", 0)),
        "timestamp": latest.get("timestamp", 0),
    }


def fetch_binance_open_interest():
    """
    Fetch current open interest from Binance Futures for BTCUSDT.
    Higher OI = more conviction in current positions.
    """
    url = "https://fapi.binance.com/fapi/v1/openInterest"
    params = {"symbol": config.BINANCE_SYMBOL}
    data = _safe_request(url, params=params, source_name="Binance OI")

    if data is None:
        return None

    return {
        "open_interest": float(data.get("openInterest", 0)),
        "symbol": data.get("symbol", ""),
        "timestamp": data.get("time", 0),
    }


def fetch_binance_futures_data():
    """
    Fetch ALL Binance futures intelligence in one call (cached 3 min).
    Returns dict with long/short, top trader, taker buy/sell, OI.
    """
    global _binance_futures_cache

    now = time.time()
    if (_binance_futures_cache["data"] is not None
            and (now - _binance_futures_cache["timestamp"]) < BINANCE_FUTURES_CACHE_SECONDS):
        return _binance_futures_cache["data"]

    result = {
        "long_short_ratio": fetch_binance_long_short_ratio(),
        "top_trader_positions": fetch_binance_top_trader_positions(),
        "taker_buy_sell": fetch_binance_taker_buy_sell(),
        "open_interest": fetch_binance_open_interest(),
    }

    _binance_futures_cache = {"data": result, "timestamp": now}
    return result


# =============================================================================
#  FEAR & GREED INDEX — Alternative.me
# =============================================================================

def fetch_fear_greed_index():
    """Fetch current Bitcoin Fear & Greed Index (0–100)."""
    data = _safe_request(config.FEAR_GREED_URL, source_name="Fear & Greed")
    if data is None or "data" not in data:
        return None
    entries = data["data"]
    if not entries or len(entries) == 0:
        return None
    entry = entries[0]
    return {
        "value": int(entry.get("value", 50)),
        "classification": entry.get("value_classification", "Neutral"),
    }


# =============================================================================
#  COINGECKO — BTC Dominance & Volume (cached)
# =============================================================================

def fetch_coingecko_global():
    """Fetch global crypto market data from CoinGecko (cached 10 min)."""
    global _coingecko_cache

    now = time.time()
    if (_coingecko_cache["data"] is not None
            and (now - _coingecko_cache["timestamp"]) < config.COINGECKO_CACHE_SECONDS):
        return _coingecko_cache["data"]

    data = _safe_request(config.COINGECKO_GLOBAL_URL, source_name="CoinGecko Global")
    if data is None or "data" not in data:
        return _coingecko_cache["data"]

    market = data["data"]
    result = {
        "btc_dominance": round(market.get("market_cap_percentage", {}).get("btc", 0), 2),
        "total_volume_usd": market.get("total_volume", {}).get("usd", 0),
        "total_market_cap_usd": market.get("total_market_cap", {}).get("usd", 0),
        "active_cryptocurrencies": market.get("active_cryptocurrencies", 0),
    }
    _coingecko_cache = {"data": result, "timestamp": now}
    return result


# =============================================================================
#  AGGREGATE FETCHER — one call to get everything
# =============================================================================

def fetch_all_data():
    """
    Master function that fetches data from ALL sources in one call.
    Returns a dict with all available data. Missing sources = None.
    """
    print("  Fetching Delta candles (5m)...")
    delta_candles_5m = fetch_delta_candles(resolution=config.EMA_CANDLE_INTERVAL, count=config.EMA_CANDLES_NEEDED)

    print("  Fetching Delta candles (3m)...")
    delta_candles_3m = fetch_delta_candles(resolution=config.RSI_CANDLE_INTERVAL, count=config.RSI_CANDLES_NEEDED)

    print("  Fetching Delta candles (15m)...")
    delta_candles_15m = fetch_delta_candles(resolution="15m", count=50)

    print("  Fetching Delta candles (1h)...")
    delta_candles_1h = fetch_delta_candles(resolution="1h", count=30)

    print("  Fetching Delta ticker...")
    delta_ticker = fetch_delta_ticker()

    print("  Fetching Delta orderbook...")
    delta_orderbook = fetch_delta_orderbook()

    print("  Fetching Delta recent trades...")
    delta_trades = fetch_delta_recent_trades()

    print("  Fetching Binance spot price...")
    binance_price = fetch_binance_price()

    print("  Fetching Binance klines (5m)...")
    binance_klines = fetch_binance_klines(interval="5m", limit=30)

    print("  Fetching Binance futures intelligence...")
    binance_futures = fetch_binance_futures_data()

    print("  Fetching Fear & Greed Index...")
    fear_greed = fetch_fear_greed_index()

    print("  Fetching CoinGecko global data...")
    coingecko = fetch_coingecko_global()

    return {
        "delta_candles_5m": delta_candles_5m,
        "delta_candles_3m": delta_candles_3m,
        "delta_candles_15m": delta_candles_15m,
        "delta_candles_1h": delta_candles_1h,
        "delta_ticker": delta_ticker,
        "delta_orderbook": delta_orderbook,
        "delta_trades": delta_trades,
        "binance_price": binance_price,
        "binance_klines": binance_klines,
        "binance_futures": binance_futures,
        "fear_greed": fear_greed,
        "coingecko": coingecko,
    }
