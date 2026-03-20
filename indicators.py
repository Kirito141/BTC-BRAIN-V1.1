"""
=============================================================================
 INDICATORS.PY — Technical Indicator Calculations
=============================================================================
 Pure calculation functions — no API calls, no side effects.
 Takes pandas DataFrames/Series in, returns computed values out.
 
 Indicators:
   • EMA (Exponential Moving Average)
   • RSI (Relative Strength Index)
   • ATR (Average True Range)
   • Market Regime Detection (trending / ranging / high-vol)
=============================================================================
"""

import pandas as pd
import numpy as np
import config


# =============================================================================
#  EMA — Exponential Moving Average
# =============================================================================

def calculate_ema(series, period):
    """
    Calculate Exponential Moving Average for a pandas Series.
    
    Args:
        series: pandas Series of prices (typically close prices)
        period: EMA lookback period (e.g. 9, 21)
    
    Returns:
        pandas Series with EMA values
    """
    return series.ewm(span=period, adjust=False).mean()


def detect_ema_crossover(df):
    """
    Detect EMA 9/21 crossover signals on a candle DataFrame.
    
    Args:
        df: DataFrame with 'close' column
    
    Returns:
        dict with:
            - "signal": "BUY" / "SELL" / None
            - "ema_fast": current fast EMA value
            - "ema_slow": current slow EMA value
            - "spread_pct": EMA spread as % of price
            - "strength": 0.0–1.0 signal strength
    """
    if df is None or len(df) < config.EMA_SLOW + 5:
        return {"signal": None, "ema_fast": 0, "ema_slow": 0, "spread_pct": 0, "strength": 0}

    close = df["close"]
    ema_fast = calculate_ema(close, config.EMA_FAST)
    ema_slow = calculate_ema(close, config.EMA_SLOW)

    # Current and previous values
    curr_fast = ema_fast.iloc[-1]
    curr_slow = ema_slow.iloc[-1]
    prev_fast = ema_fast.iloc[-2]
    prev_slow = ema_slow.iloc[-2]

    # Guard against NaN (can happen with very short or gapped data)
    if any(np.isnan(v) for v in [curr_fast, curr_slow, prev_fast, prev_slow]):
        return {"signal": None, "ema_fast": 0, "ema_slow": 0, "spread_pct": 0, "strength": 0}

    # EMA spread as % of price
    price = close.iloc[-1]
    spread_pct = abs(curr_fast - curr_slow) / price * 100 if price > 0 else 0

    signal = None
    strength = 0.0

    # Bullish crossover: fast crosses above slow
    if prev_fast <= prev_slow and curr_fast > curr_slow:
        signal = "BUY"
        # Strength based on how decisively it crossed + volume
        strength = min(spread_pct / 0.3, 1.0)  # normalize to 0–1

    # Bearish crossover: fast crosses below slow
    elif prev_fast >= prev_slow and curr_fast < curr_slow:
        signal = "SELL"
        strength = min(spread_pct / 0.3, 1.0)

    return {
        "signal": signal,
        "ema_fast": round(curr_fast, 2),
        "ema_slow": round(curr_slow, 2),
        "spread_pct": round(spread_pct, 4),
        "strength": round(strength, 3),
    }


# =============================================================================
#  RSI — Relative Strength Index
# =============================================================================

def calculate_rsi(series, period=14):
    """
    Calculate RSI using Wilder's smoothing method.
    
    Args:
        series: pandas Series of close prices
        period: RSI lookback (default 14)
    
    Returns:
        pandas Series with RSI values (0–100)
    """
    delta = series.diff()

    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    # Wilder's smoothing (equivalent to EMA with alpha = 1/period)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()

    # Avoid division by zero — when avg_loss is 0, RSI is 100 (all gains)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.fillna(100)  # all gains, no losses → RSI = 100

    return rsi


def detect_rsi_signal(df):
    """
    Detect RSI mean-reversion signals on a candle DataFrame.
    
    Buys on oversold bounces, sells on overbought reversals.
    Requires RSI to cross BACK from extreme zone (not just touch it).
    
    Args:
        df: DataFrame with 'close' column
    
    Returns:
        dict with:
            - "signal": "BUY" / "SELL" / None
            - "rsi": current RSI value
            - "strength": 0.0–1.0 signal strength
    """
    if df is None or len(df) < config.RSI_PERIOD + 5:
        return {"signal": None, "rsi": 50, "strength": 0}

    close = df["close"]
    rsi = calculate_rsi(close, config.RSI_PERIOD)

    curr_rsi = rsi.iloc[-1]
    prev_rsi = rsi.iloc[-2]

    signal = None
    strength = 0.0

    # BUY: RSI was oversold and is now bouncing back up
    if prev_rsi < config.RSI_OVERSOLD and curr_rsi >= config.RSI_OVERSOLD:
        signal = "BUY"
        # Stronger signal if RSI was deeper in oversold territory
        depth = max(0, config.RSI_OVERSOLD - rsi.iloc[-3]) if len(rsi) > 2 else 5
        strength = min(depth / 20, 1.0)

    # SELL: RSI was overbought and is now turning down
    elif prev_rsi > config.RSI_OVERBOUGHT and curr_rsi <= config.RSI_OVERBOUGHT:
        signal = "SELL"
        depth = max(0, rsi.iloc[-3] - config.RSI_OVERBOUGHT) if len(rsi) > 2 else 5
        strength = min(depth / 20, 1.0)

    return {
        "signal": signal,
        "rsi": round(curr_rsi, 2),
        "strength": round(strength, 3),
    }


# =============================================================================
#  ATR — Average True Range
# =============================================================================

def calculate_atr(df, period=14):
    """
    Calculate Average True Range.
    
    ATR measures volatility using the greatest of:
      • Current High - Current Low
      • |Current High - Previous Close|
      • |Current Low - Previous Close|
    
    Args:
        df: DataFrame with 'high', 'low', 'close' columns
        period: ATR lookback period
    
    Returns:
        pandas Series with ATR values, or None if insufficient data
    """
    if df is None or len(df) < period + 1:
        return None

    high = df["high"]
    low = df["low"]
    close = df["close"]

    # True Range components
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()

    # True Range = max of the three
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # ATR = Wilder's smoothed average of True Range
    atr = true_range.ewm(alpha=1 / period, min_periods=period).mean()

    return atr


def get_current_atr(df, period=None):
    """
    Get the latest ATR value from a candle DataFrame.
    
    Returns:
        float ATR value, or 0.0 on failure
    """
    if period is None:
        period = config.REGIME_ATR_PERIOD

    atr = calculate_atr(df, period)
    if atr is None or atr.empty:
        return 0.0

    return round(float(atr.iloc[-1]), 2)


# =============================================================================
#  MARKET REGIME DETECTION
# =============================================================================

def detect_regime(df_5m):
    """
    Determine market regime using EMA spread and ATR.
    
    Logic:
      1. Calculate ATR as % of price
      2. If ATR% > HIGH_VOL_THRESHOLD → "high_volatility" (sit out)
      3. Calculate EMA 9/21 spread as % of price
      4. If spread > TREND_THRESHOLD → "trending"
      5. Otherwise → "ranging"
    
    Args:
        df_5m: DataFrame with 5-minute OHLCV candles
    
    Returns:
        dict with:
            - "regime": "trending" / "ranging" / "high_volatility"
            - "atr_pct": ATR as % of price
            - "ema_spread_pct": EMA spread as % of price
            - "reason": human-readable explanation
    """
    if df_5m is None or len(df_5m) < config.EMA_SLOW + 5:
        return {
            "regime": "unknown",
            "atr_pct": 0,
            "ema_spread_pct": 0,
            "reason": "Insufficient data for regime detection",
        }

    close = df_5m["close"]
    price = close.iloc[-1]

    if price <= 0:
        return {"regime": "unknown", "atr_pct": 0, "ema_spread_pct": 0, "reason": "Invalid price"}

    # ── Step 1: ATR as percentage of price ──────────────────────────────────
    atr = get_current_atr(df_5m, config.REGIME_ATR_PERIOD)
    atr_pct = (atr / price) * 100 if price > 0 else 0

    # ── Step 2: Check for high volatility → sit out ─────────────────────────
    if atr_pct > config.REGIME_ATR_HIGH_VOL_THRESHOLD:
        return {
            "regime": "high_volatility",
            "atr_pct": round(atr_pct, 4),
            "ema_spread_pct": 0,
            "reason": f"ATR {atr_pct:.3f}% exceeds {config.REGIME_ATR_HIGH_VOL_THRESHOLD}% threshold — too volatile",
        }

    # ── Step 3: EMA spread ──────────────────────────────────────────────────
    ema_fast = calculate_ema(close, config.EMA_FAST)
    ema_slow = calculate_ema(close, config.EMA_SLOW)
    spread = abs(ema_fast.iloc[-1] - ema_slow.iloc[-1])
    spread_pct = (spread / price) * 100

    # ── Step 4: Trending vs. Ranging ────────────────────────────────────────
    if spread_pct > config.REGIME_EMA_SPREAD_TREND_THRESHOLD:
        direction = "bullish" if ema_fast.iloc[-1] > ema_slow.iloc[-1] else "bearish"
        return {
            "regime": "trending",
            "atr_pct": round(atr_pct, 4),
            "ema_spread_pct": round(spread_pct, 4),
            "reason": f"EMA spread {spread_pct:.3f}% > {config.REGIME_EMA_SPREAD_TREND_THRESHOLD}% — {direction} trend detected",
        }
    else:
        return {
            "regime": "ranging",
            "atr_pct": round(atr_pct, 4),
            "ema_spread_pct": round(spread_pct, 4),
            "reason": f"EMA spread {spread_pct:.3f}% ≤ {config.REGIME_EMA_SPREAD_TREND_THRESHOLD}% — range-bound market",
        }


# =============================================================================
#  MACD — Moving Average Convergence Divergence
# =============================================================================

def calculate_macd(series, fast=12, slow=26, signal=9):
    """
    Calculate MACD line, signal line, and histogram.
    
    Args:
        series: pandas Series of close prices
        fast: fast EMA period (default 12)
        slow: slow EMA period (default 26)
        signal: signal line EMA period (default 9)
    
    Returns:
        dict: {"macd": float, "signal": float, "histogram": float,
               "crossover": "bullish"/"bearish"/None}
    """
    if series is None or len(series) < slow + signal:
        return {"macd": 0, "signal_line": 0, "histogram": 0, "crossover": None}

    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    # Detect crossover
    crossover = None
    if len(macd_line) >= 2:
        curr_macd, prev_macd = macd_line.iloc[-1], macd_line.iloc[-2]
        curr_sig, prev_sig = signal_line.iloc[-1], signal_line.iloc[-2]
        if prev_macd <= prev_sig and curr_macd > curr_sig:
            crossover = "bullish"
        elif prev_macd >= prev_sig and curr_macd < curr_sig:
            crossover = "bearish"

    return {
        "macd": round(float(macd_line.iloc[-1]), 2),
        "signal_line": round(float(signal_line.iloc[-1]), 2),
        "histogram": round(float(histogram.iloc[-1]), 2),
        "crossover": crossover,
    }


# =============================================================================
#  BOLLINGER BANDS
# =============================================================================

def calculate_bollinger_bands(series, period=20, std_dev=2.0):
    """
    Calculate Bollinger Bands.
    
    Returns:
        dict: {"upper": float, "middle": float, "lower": float,
               "bandwidth_pct": float, "price_position": float (0-1)}
    """
    if series is None or len(series) < period:
        return {"upper": 0, "middle": 0, "lower": 0, "bandwidth_pct": 0, "price_position": 0.5}

    middle = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)

    curr_upper = float(upper.iloc[-1])
    curr_middle = float(middle.iloc[-1])
    curr_lower = float(lower.iloc[-1])
    curr_price = float(series.iloc[-1])

    bandwidth = (curr_upper - curr_lower) / curr_middle * 100 if curr_middle > 0 else 0

    # Price position: 0 = at lower band, 1 = at upper band
    band_range = curr_upper - curr_lower
    price_position = (curr_price - curr_lower) / band_range if band_range > 0 else 0.5

    return {
        "upper": round(curr_upper, 2),
        "middle": round(curr_middle, 2),
        "lower": round(curr_lower, 2),
        "bandwidth_pct": round(bandwidth, 4),
        "price_position": round(max(0, min(1, price_position)), 3),
    }


# =============================================================================
#  VWAP — Volume Weighted Average Price (session-based)
# =============================================================================

def calculate_vwap(df):
    """
    Calculate VWAP from OHLCV candle data.
    Uses typical price × volume / cumulative volume.
    
    Returns:
        float: current VWAP value, or 0 on failure
    """
    if df is None or len(df) < 2 or "volume" not in df.columns:
        return 0.0

    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cum_vol = df["volume"].cumsum()
    cum_tp_vol = (typical_price * df["volume"]).cumsum()

    vwap = cum_tp_vol / cum_vol
    vwap = vwap.replace([np.inf, -np.inf], np.nan).fillna(0)

    return round(float(vwap.iloc[-1]), 2)


# =============================================================================
#  MULTI-TIMEFRAME EMA (for higher timeframe trend context)
# =============================================================================

def calculate_higher_tf_emas(df):
    """
    Calculate EMA 50 and EMA 200 (or as many as data allows).
    Used for 15m / 1h candles to give Claude the macro trend.
    
    Returns:
        dict: {"ema50": float, "ema200": float, "trend": str}
    """
    if df is None or len(df) < 10:
        return {"ema50": 0, "ema200": 0, "trend": "unknown"}

    close = df["close"]
    price = close.iloc[-1]

    ema50 = calculate_ema(close, min(50, len(close) - 1))
    ema50_val = round(float(ema50.iloc[-1]), 2)

    ema200_val = 0
    if len(close) >= 30:  # at minimum use what we have
        period = min(200, len(close) - 1)
        ema200 = calculate_ema(close, period)
        ema200_val = round(float(ema200.iloc[-1]), 2)

    # Determine trend
    trend = "unknown"
    if ema50_val > 0 and ema200_val > 0:
        if price > ema50_val > ema200_val:
            trend = "strong_bullish"
        elif price > ema50_val:
            trend = "bullish"
        elif price < ema50_val < ema200_val:
            trend = "strong_bearish"
        elif price < ema50_val:
            trend = "bearish"
        else:
            trend = "neutral"

    return {"ema50": ema50_val, "ema200": ema200_val, "trend": trend}


# =============================================================================
#  SL / TP CALCULATOR
# =============================================================================

def calculate_sl_tp(entry_price, direction, atr_value):
    """
    Calculate dynamic stop-loss and take-profit levels.
    
    Uses ATR-based distances with minimum floor enforcement.
    
    Args:
        entry_price: float — exact entry price
        direction: "BUY" or "SELL"
        atr_value: float — current ATR value
    
    Returns:
        dict: {"stop_loss": float, "take_profit": float,
               "sl_distance_pct": float, "tp_distance_pct": float,
               "sl_method": str, "tp_method": str}
    """
    # ── ATR-based distances ─────────────────────────────────────────────────
    sl_distance_atr = atr_value * config.SL_ATR_MULTIPLIER
    tp_distance_atr = atr_value * config.TP_ATR_MULTIPLIER

    # ── Minimum floor distances ─────────────────────────────────────────────
    sl_distance_floor = entry_price * (config.SL_MIN_PERCENT / 100)
    tp_distance_floor = entry_price * (config.TP_MIN_PERCENT / 100)

    # ── Use whichever is larger ─────────────────────────────────────────────
    sl_distance = max(sl_distance_atr, sl_distance_floor)
    tp_distance = max(tp_distance_atr, tp_distance_floor)

    sl_method = "ATR-dynamic" if sl_distance_atr >= sl_distance_floor else "floor (0.25%)"
    tp_method = "ATR-dynamic" if tp_distance_atr >= tp_distance_floor else "floor (0.50%)"

    # ── Calculate actual price levels ───────────────────────────────────────
    if direction == "BUY":
        stop_loss = entry_price - sl_distance
        take_profit = entry_price + tp_distance
    else:  # SELL
        stop_loss = entry_price + sl_distance
        take_profit = entry_price - tp_distance

    return {
        "stop_loss": round(stop_loss, 2),
        "take_profit": round(take_profit, 2),
        "sl_distance_pct": round((sl_distance / entry_price) * 100, 4),
        "tp_distance_pct": round((tp_distance / entry_price) * 100, 4),
        "sl_method": sl_method,
        "tp_method": tp_method,
    }


# =============================================================================
#  POSITION SIZE CALCULATOR
# =============================================================================

def calculate_position_size(entry_price, balance_usdt=None):
    """
    Calculate contract quantity for BTCUSD inverse perpetual.
    
    For BTCUSD on Delta Exchange:
      • Contract value = 0.001 BTC per lot
      • Position in USD = (number_of_lots × 0.001) × BTC_price
      • With leverage: margin_required = position_value / leverage
    
    Formula:
      usable_balance = balance × 50%
      position_value = usable_balance × leverage
      lots = position_value / (contract_value × entry_price)
    
    Args:
        entry_price: current BTC price in USD
        balance_usdt: available balance (uses default if None)
    
    Returns:
        dict: {"contracts": int, "position_value_usd": float,
               "margin_used_usd": float, "balance_used": float}
    """
    if balance_usdt is None:
        balance_usdt = config.DEFAULT_BALANCE_USDT

    if entry_price <= 0:
        return {"contracts": 0, "position_value_usd": 0, "margin_used_usd": 0, "balance_used": 0}

    # 50% of balance
    usable_balance = balance_usdt * (config.BALANCE_USAGE_PERCENT / 100)

    # Total position value with leverage
    position_value = usable_balance * config.LEVERAGE

    # BTCUSD inverse perpetual: 1 lot = 0.001 BTC
    # Number of lots = position_value_usd / (0.001 × price_usd)
    contract_value_usd = 0.001 * entry_price
    lots = int(position_value / contract_value_usd) if contract_value_usd > 0 else 0

    return {
        "contracts": lots,
        "position_value_usd": round(lots * contract_value_usd, 2),
        "margin_used_usd": round((lots * contract_value_usd) / config.LEVERAGE, 2),
        "balance_used": round(usable_balance, 2),
    }
