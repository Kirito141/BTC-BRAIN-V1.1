"""
=============================================================================
 DATA_FETCHER.PY — Fetches Data from All Sources
=============================================================================
 Handles:
   • Delta Exchange  — candles, ticker (price/OI/funding), orderbook
   • Binance          — BTC price feed (reference)
   • Alternative.me   — Fear & Greed Index
   • CoinGecko        — BTC dominance & 24h volume

 Design:
   • Each source has its own function with try/except
   • If any single source fails, bot continues with reduced data
   • CoinGecko responses are cached (10 min) to respect rate limits
=============================================================================
"""

import time
import requests
import pandas as pd
from datetime import datetime, timedelta
import config

# ── Module-level cache for CoinGecko ────────────────────────────────────────
_coingecko_cache = {"data": None, "timestamp": 0}


def _safe_request(url, params=None, timeout=10, source_name="API"):
    """
    Makes an HTTP GET request with error handling.
    Returns JSON dict on success, None on failure.
    Logs errors but never crashes the bot.
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
    
    Args:
        resolution: candle interval — "1m", "3m", "5m", "15m", etc.
        count: number of candles to fetch
    
    Returns:
        pandas DataFrame with columns [time, open, high, low, close, volume]
        or None on failure.
    """
    # Delta expects unix timestamps for start/end
    end_ts = int(time.time())

    # Map resolution string to seconds
    res_map = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}
    interval_secs = res_map.get(resolution, 300)
    start_ts = end_ts - (count * interval_secs) - interval_secs  # extra buffer

    url = f"{config.DELTA_BASE_URL}/v2/history/candles"
    params = {
        "symbol": config.DELTA_SYMBOL,
        "resolution": resolution.replace("m", "").replace("h", ""),  # Delta uses "5" not "5m"
        "start": start_ts,
        "end": end_ts,
    }

    # Delta's resolution format: "1", "3", "5", "15", "30", "60" for minutes
    # and "1D", "1W" for daily/weekly
    if "h" in resolution:
        hours = int(resolution.replace("h", ""))
        params["resolution"] = str(hours * 60)
    else:
        params["resolution"] = resolution.replace("m", "")

    data = _safe_request(url, params=params, source_name="Delta Candles")
    if data is None or not data.get("success"):
        return None

    candles = data.get("result", [])
    if not candles:
        return None

    # Delta returns: [{"time":..., "open":..., "high":..., "low":..., "close":..., "volume":...}]
    df = pd.DataFrame(candles)

    # Ensure numeric types
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Sort by time ascending (oldest first)
    if "time" in df.columns:
        df["time"] = pd.to_numeric(df["time"], errors="coerce")
        df = df.sort_values("time").reset_index(drop=True)

    return df


def fetch_delta_ticker():
    """
    Fetch current ticker for BTCUSD from Delta Exchange.
    Returns dict with keys: mark_price, open_interest, funding_rate, volume, etc.
    or None on failure.
    """
    url = f"{config.DELTA_BASE_URL}/v2/tickers/{config.DELTA_SYMBOL}"
    data = _safe_request(url, source_name="Delta Ticker")

    if data is None or not data.get("success"):
        return None

    result = data.get("result", {})

    ticker = {
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
    }

    return ticker


def fetch_delta_orderbook(depth=10):
    """
    Fetch L2 orderbook for BTCUSD. Returns dict with 'buy' and 'sell' lists.
    Each entry: {"price": ..., "size": ...}
    """
    url = f"{config.DELTA_BASE_URL}/v2/l2orderbook/{config.DELTA_SYMBOL}"
    data = _safe_request(url, source_name="Delta Orderbook")

    if data is None or not data.get("success"):
        return None

    result = data.get("result", {})
    return {
        "buy": result.get("buy", [])[:depth],
        "sell": result.get("sell", [])[:depth],
    }


# =============================================================================
#  BINANCE — Reference Price Feed
# =============================================================================

def fetch_binance_price():
    """
    Fetch current BTC price from Binance (higher liquidity reference).
    Returns float price or None.
    """
    url = f"{config.BINANCE_BASE_URL}/api/v3/ticker/price"
    params = {"symbol": config.BINANCE_SYMBOL}
    data = _safe_request(url, params=params, source_name="Binance Price")

    if data is None:
        return None

    return float(data.get("price", 0))


def fetch_binance_klines(interval="5m", limit=50):
    """
    Fetch candles from Binance for trend confirmation.
    Returns DataFrame with OHLCV data or None.
    """
    url = f"{config.BINANCE_BASE_URL}/api/v3/klines"
    params = {
        "symbol": config.BINANCE_SYMBOL,
        "interval": interval,
        "limit": limit,
    }
    data = _safe_request(url, params=params, source_name="Binance Klines")

    if data is None or not isinstance(data, list) or len(data) == 0:
        return None

    # Binance klines: [open_time, O, H, L, C, volume, close_time, ...]
    # Verify each row has at least 6 columns before parsing
    expected_cols = ["time", "open", "high", "low", "close", "volume",
                     "close_time", "quote_vol", "trades", "taker_buy_base",
                     "taker_buy_quote", "ignore"]
    
    # Filter out malformed rows
    valid_rows = [row for row in data if isinstance(row, list) and len(row) >= 6]
    if not valid_rows:
        return None

    df = pd.DataFrame(valid_rows, columns=expected_cols[:len(valid_rows[0])])

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df[["time", "open", "high", "low", "close", "volume"]]


# =============================================================================
#  FEAR & GREED INDEX — Alternative.me
# =============================================================================

def fetch_fear_greed_index():
    """
    Fetch current Bitcoin Fear & Greed Index (0–100).
    Returns dict: {"value": int, "classification": str} or None.
    
    Classification: Extreme Fear / Fear / Neutral / Greed / Extreme Greed
    """
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
    """
    Fetch global crypto market data from CoinGecko.
    Returns dict: {"btc_dominance": float, "total_volume_usd": float} or None.
    
    CACHED for 10 minutes to respect CoinGecko free tier limits.
    """
    global _coingecko_cache

    # Check cache freshness
    now = time.time()
    if (_coingecko_cache["data"] is not None
            and (now - _coingecko_cache["timestamp"]) < config.COINGECKO_CACHE_SECONDS):
        return _coingecko_cache["data"]

    data = _safe_request(config.COINGECKO_GLOBAL_URL, source_name="CoinGecko Global")

    if data is None or "data" not in data:
        # Return stale cache if available
        return _coingecko_cache["data"]

    market = data["data"]
    result = {
        "btc_dominance": round(market.get("market_cap_percentage", {}).get("btc", 0), 2),
        "total_volume_usd": market.get("total_volume", {}).get("usd", 0),
        "total_market_cap_usd": market.get("total_market_cap", {}).get("usd", 0),
        "active_cryptocurrencies": market.get("active_cryptocurrencies", 0),
    }

    # Update cache
    _coingecko_cache = {"data": result, "timestamp": now}
    return result


# =============================================================================
#  AGGREGATE FETCHER — one call to get everything
# =============================================================================

def fetch_all_data():
    """
    Master function that fetches data from ALL sources in one call.
    Returns a dict with all available data. Missing sources = None.
    
    This is the main entry point called by the bot each cycle.
    """
    print("  Fetching Delta Exchange candles (5m)...")
    delta_candles_5m = fetch_delta_candles(
        resolution=config.EMA_CANDLE_INTERVAL,
        count=config.EMA_CANDLES_NEEDED
    )

    print("  Fetching Delta Exchange candles (3m)...")
    delta_candles_3m = fetch_delta_candles(
        resolution=config.RSI_CANDLE_INTERVAL,
        count=config.RSI_CANDLES_NEEDED
    )

    print("  Fetching Delta Exchange ticker...")
    delta_ticker = fetch_delta_ticker()

    print("  Fetching Delta Exchange orderbook...")
    delta_orderbook = fetch_delta_orderbook()

    print("  Fetching Binance BTC price...")
    binance_price = fetch_binance_price()

    print("  Fetching Binance klines (5m)...")
    binance_klines = fetch_binance_klines(interval="5m", limit=30)

    print("  Fetching Fear & Greed Index...")
    fear_greed = fetch_fear_greed_index()

    print("  Fetching CoinGecko global data...")
    coingecko = fetch_coingecko_global()

    return {
        "delta_candles_5m": delta_candles_5m,
        "delta_candles_3m": delta_candles_3m,
        "delta_ticker": delta_ticker,
        "delta_orderbook": delta_orderbook,
        "binance_price": binance_price,
        "binance_klines": binance_klines,
        "fear_greed": fear_greed,
        "coingecko": coingecko,
    }
