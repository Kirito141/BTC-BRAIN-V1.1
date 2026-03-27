"""
=============================================================================
 DATA_FETCHER.PY v3 — Multi-Source Data Aggregator
=============================================================================
 Same sources as v2 with:
   • Better cache management (120s for Binance futures)
   • Delta-Binance spread monitoring
   • Order flow delta from trade tape
=============================================================================
"""

import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import config

# ── Caches ──────────────────────────────────────────────────────────────
_coingecko_cache = {"data": None, "timestamp": 0}
_binance_futures_cache = {"data": None, "timestamp": 0}
_fear_greed_cache = {"data": None, "timestamp": 0}


def _safe_request(url, params=None, timeout=10, source_name="API"):
    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        print(f"  [WARN] {source_name} timed out")
    except requests.exceptions.ConnectionError:
        print(f"  [WARN] {source_name} connection failed")
    except requests.exceptions.HTTPError as e:
        print(f"  [WARN] {source_name} HTTP error: {e}")
    except Exception as e:
        print(f"  [WARN] {source_name} error: {e}")
    return None


# =============================================================================
#  DELTA EXCHANGE
# =============================================================================

def fetch_delta_candles(resolution="5m", count=100):
    end_ts = int(time.time())
    res_map = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400}
    interval_secs = res_map.get(resolution, 300)
    start_ts = end_ts - (count * interval_secs) - interval_secs

    url = f"{config.DELTA_BASE_URL}/v2/history/candles"
    params = {"symbol": config.DELTA_SYMBOL, "resolution": resolution, "start": start_ts, "end": end_ts}

    data = _safe_request(url, params=params, source_name=f"Delta {resolution}")
    if data is None or not data.get("success") or not data.get("result"):
        if "h" in resolution:
            params["resolution"] = str(int(resolution.replace("h", "")) * 60)
        else:
            params["resolution"] = resolution.replace("m", "")
        data = _safe_request(url, params=params, source_name=f"Delta {resolution} retry")

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
    url = f"{config.DELTA_BASE_URL}/v2/tickers/{config.DELTA_SYMBOL}"
    data = _safe_request(url, source_name="Delta Ticker")
    if data is None or not data.get("success"):
        return None
    r = data.get("result", {})
    return {
        "mark_price": float(r.get("mark_price", 0)),
        "close": float(r.get("close", 0)),
        "high": float(r.get("high", 0)),
        "low": float(r.get("low", 0)),
        "open": float(r.get("open", 0)),
        "volume": float(r.get("volume", 0)),
        "turnover": float(r.get("turnover", 0)),
        "open_interest": float(r.get("oi", 0)),
        "funding_rate": float(r.get("funding_rate", 0) or 0),
        "product_id": r.get("product_id", config.DELTA_PRODUCT_ID),
        "symbol": r.get("symbol", config.DELTA_SYMBOL),
        "spot_price": float(r.get("spot_price", 0) or 0),
    }


def fetch_delta_orderbook(depth=20):
    url = f"{config.DELTA_BASE_URL}/v2/l2orderbook/{config.DELTA_SYMBOL}"
    data = _safe_request(url, source_name="Delta OB")
    if data is None or not data.get("success"):
        return None
    r = data.get("result", {})
    return {"buy": r.get("buy", [])[:depth], "sell": r.get("sell", [])[:depth]}


def fetch_delta_recent_trades():
    url = f"{config.DELTA_BASE_URL}/v2/trades/{config.DELTA_SYMBOL}"
    data = _safe_request(url, source_name="Delta Trades")
    if data is None or not data.get("success"):
        return None

    trades = data.get("result", [])
    if not trades:
        return None

    buy_count = sell_count = 0
    buy_volume = sell_volume = 0.0
    large_trades = []
    sizes = [float(t.get("size", 0)) for t in trades if t.get("size")]
    avg_size = sum(sizes) / len(sizes) if sizes else 0

    for t in trades:
        side = t.get("buyer_role", "").lower()
        size = float(t.get("size", 0))
        price = float(t.get("price", 0))
        if side == "taker":
            buy_count += 1
            buy_volume += size
        else:
            sell_count += 1
            sell_volume += size
        if size > avg_size * 2 and price > 0:
            large_trades.append({"price": price, "size": size, "side": "BUY" if side == "taker" else "SELL"})

    total_count = buy_count + sell_count
    total_volume = buy_volume + sell_volume
    aggression = (buy_volume - sell_volume) / total_volume if total_volume > 0 else 0

    return {
        "total_trades": len(trades),
        "buy_count": buy_count, "sell_count": sell_count,
        "buy_volume": round(buy_volume, 2), "sell_volume": round(sell_volume, 2),
        "buy_pct": round(buy_count / total_count * 100, 1) if total_count > 0 else 50,
        "volume_imbalance_pct": round(aggression * 100, 1),
        "avg_trade_size": round(avg_size, 2),
        "large_trades": large_trades[:5],
        "aggression": round(aggression, 3),
    }


# =============================================================================
#  BINANCE
# =============================================================================

def fetch_binance_price():
    url = f"{config.BINANCE_BASE_URL}/api/v3/ticker/price"
    data = _safe_request(url, params={"symbol": config.BINANCE_SYMBOL}, source_name="Binance Price")
    return float(data.get("price", 0)) if data else None


def fetch_binance_klines(interval="5m", limit=50):
    url = f"{config.BINANCE_BASE_URL}/api/v3/klines"
    data = _safe_request(url, params={"symbol": config.BINANCE_SYMBOL, "interval": interval, "limit": limit},
                         source_name=f"Binance Klines {interval}")
    if not data or not isinstance(data, list):
        return None
    cols = ["time", "open", "high", "low", "close", "volume",
            "close_time", "quote_vol", "trades", "taker_buy_base", "taker_buy_quote", "ignore"]
    valid_rows = [r for r in data if isinstance(r, list) and len(r) >= 6]
    if not valid_rows:
        return None
    df = pd.DataFrame(valid_rows, columns=cols[:len(valid_rows[0])])
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[["time", "open", "high", "low", "close", "volume"]]


def fetch_binance_long_short_ratio(period="5m", limit=5):
    url = f"{config.BINANCE_FUTURES_URL}/futures/data/globalLongShortAccountRatio"
    data = _safe_request(url, params={"symbol": config.BINANCE_SYMBOL, "period": period, "limit": limit},
                         source_name="Binance L/S")
    if not data or not isinstance(data, list) or len(data) == 0:
        return None
    latest = data[0]
    return {
        "long_short_ratio": float(latest.get("longShortRatio", 1.0)),
        "long_account_pct": float(latest.get("longAccount", 0.5)) * 100,
        "short_account_pct": float(latest.get("shortAccount", 0.5)) * 100,
    }


def fetch_binance_top_trader_positions(period="5m", limit=5):
    url = f"{config.BINANCE_FUTURES_URL}/futures/data/topLongShortPositionRatio"
    data = _safe_request(url, params={"symbol": config.BINANCE_SYMBOL, "period": period, "limit": limit},
                         source_name="Binance Top Traders")
    if not data or not isinstance(data, list) or len(data) == 0:
        return None
    latest = data[0]
    return {
        "long_short_ratio": float(latest.get("longShortRatio", 1.0)),
        "long_pct": float(latest.get("longAccount", 0.5)) * 100,
        "short_pct": float(latest.get("shortAccount", 0.5)) * 100,
    }


def fetch_binance_taker_buy_sell(period="5m", limit=5):
    url = f"{config.BINANCE_FUTURES_URL}/futures/data/takerlongshortRatio"
    data = _safe_request(url, params={"symbol": config.BINANCE_SYMBOL, "period": period, "limit": limit},
                         source_name="Binance Taker")
    if not data or not isinstance(data, list) or len(data) == 0:
        return None
    latest = data[0]
    return {
        "buy_sell_ratio": float(latest.get("buySellRatio", 1.0)),
        "buy_volume": float(latest.get("buyVol", 0)),
        "sell_volume": float(latest.get("sellVol", 0)),
    }


def fetch_binance_open_interest():
    url = f"{config.BINANCE_FUTURES_URL}/fapi/v1/openInterest"
    data = _safe_request(url, params={"symbol": config.BINANCE_SYMBOL}, source_name="Binance OI")
    if data is None:
        return None
    return {"open_interest": float(data.get("openInterest", 0))}


def fetch_binance_funding_rate_history(limit=10):
    url = f"{config.BINANCE_FUTURES_URL}/fapi/v1/fundingRate"
    data = _safe_request(url, params={"symbol": config.BINANCE_SYMBOL, "limit": limit},
                         source_name="Binance Funding History")
    if not data or not isinstance(data, list):
        return None
    rates = [float(r.get("fundingRate", 0)) for r in data]
    avg_rate = sum(rates) / len(rates) if rates else 0
    trend = "unknown"
    if len(rates) >= 3:
        recent = sum(rates[:3]) / 3
        older = sum(rates[-3:]) / 3
        if recent > older * 1.5: trend = "increasing_positive"
        elif recent < older * 0.5 or (recent < 0 and older > 0): trend = "turning_negative"
        else: trend = "stable"
    return {"current_rate": rates[0] if rates else 0, "avg_rate": round(avg_rate, 6), "rates": rates, "trend": trend}


def fetch_binance_futures_data():
    global _binance_futures_cache
    now = time.time()
    if (_binance_futures_cache["data"] is not None and
            (now - _binance_futures_cache["timestamp"]) < config.BINANCE_FUTURES_CACHE_SECONDS):
        return _binance_futures_cache["data"]

    result = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(fetch_binance_long_short_ratio): "long_short_ratio",
            executor.submit(fetch_binance_top_trader_positions): "top_trader_positions",
            executor.submit(fetch_binance_taker_buy_sell): "taker_buy_sell",
            executor.submit(fetch_binance_open_interest): "open_interest",
            executor.submit(fetch_binance_funding_rate_history): "funding_history",
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                result[key] = future.result()
            except Exception:
                result[key] = None

    _binance_futures_cache = {"data": result, "timestamp": now}
    return result


# =============================================================================
#  FEAR & GREED
# =============================================================================

def fetch_fear_greed_index():
    global _fear_greed_cache
    now = time.time()
    if (_fear_greed_cache["data"] is not None and
            (now - _fear_greed_cache["timestamp"]) < config.FEAR_GREED_CACHE_SECONDS):
        return _fear_greed_cache["data"]

    data = _safe_request(config.FEAR_GREED_URL, source_name="Fear & Greed")
    if data is None or "data" not in data:
        stale = _fear_greed_cache.get("data")
        if stale is not None:
            stale = dict(stale)
            stale["stale"] = True
        return stale

    entries = data["data"]
    if not entries:
        return None

    current = entries[0]
    values = [int(e.get("value", 50)) for e in entries]
    trend = "stable"
    if len(values) >= 3:
        if values[0] > values[-1] + 10: trend = "improving"
        elif values[0] < values[-1] - 10: trend = "worsening"

    result = {
        "value": int(current.get("value", 50)),
        "classification": current.get("value_classification", "Neutral"),
        "trend": trend, "values_7d": values,
    }
    _fear_greed_cache = {"data": result, "timestamp": now}
    return result


# =============================================================================
#  COINGECKO
# =============================================================================

def fetch_coingecko_global():
    global _coingecko_cache
    now = time.time()
    if (_coingecko_cache["data"] is not None and
            (now - _coingecko_cache["timestamp"]) < config.COINGECKO_CACHE_SECONDS):
        return _coingecko_cache["data"]

    data = _safe_request(config.COINGECKO_GLOBAL_URL, source_name="CoinGecko")
    if data is None or "data" not in data:
        return _coingecko_cache.get("data")

    market = data["data"]
    result = {
        "btc_dominance": round(market.get("market_cap_percentage", {}).get("btc", 0), 2),
        "total_volume_usd": market.get("total_volume", {}).get("usd", 0),
        "total_market_cap_usd": market.get("total_market_cap", {}).get("usd", 0),
        "market_cap_change_24h": market.get("market_cap_change_percentage_24h_usd", 0),
    }
    _coingecko_cache = {"data": result, "timestamp": now}
    return result


# =============================================================================
#  AGGREGATE FETCHER
# =============================================================================

def fetch_all_data():
    results = {}

    # Delta candles (sequential for same API)
    results["delta_candles_5m"] = fetch_delta_candles(resolution="5m", count=config.CANDLES_5M_COUNT)
    results["delta_candles_15m"] = fetch_delta_candles(resolution="15m", count=config.CANDLES_15M_COUNT)
    results["delta_candles_1h"] = fetch_delta_candles(resolution="1h", count=config.CANDLES_1H_COUNT)
    results["delta_candles_4h"] = fetch_delta_candles(resolution="4h", count=config.CANDLES_4H_COUNT)
    results["delta_ticker"] = fetch_delta_ticker()
    results["delta_orderbook"] = fetch_delta_orderbook()
    results["delta_trades"] = fetch_delta_recent_trades()

    # Parallel external calls
    with ThreadPoolExecutor(max_workers=4) as executor:
        ext_futures = {
            executor.submit(fetch_binance_price): "binance_price",
            executor.submit(fetch_binance_klines, "5m", 50): "binance_klines",
            executor.submit(fetch_binance_futures_data): "binance_futures",
            executor.submit(fetch_fear_greed_index): "fear_greed",
            executor.submit(fetch_coingecko_global): "coingecko",
        }
        for future in as_completed(ext_futures):
            key = ext_futures[future]
            try:
                results[key] = future.result()
            except Exception as e:
                print(f"  [WARN] {key} fetch failed: {e}")
                results[key] = None

    available = sum(1 for v in results.values() if v is not None)
    print(f"  ✓ {available}/{len(results)} data sources OK")
    return results
