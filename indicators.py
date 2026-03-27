"""
=============================================================================
 INDICATORS.PY — Technical Indicator Suite v3
=============================================================================
 Same indicators as v2, plus:
   • Dynamic position sizing based on confidence
   • Volume-profile based S/R (improved)
   • Order flow delta calculation from trade tape
=============================================================================
"""

import pandas as pd
import numpy as np
import config


# =============================================================================
#  EMA
# =============================================================================

def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def detect_ema_crossover(df):
    if df is None or len(df) < config.EMA_SLOW + 5:
        return {"signal": None, "ema_fast": 0, "ema_slow": 0, "spread_pct": 0, "strength": 0}

    close = df["close"]
    ema_fast = calculate_ema(close, config.EMA_FAST)
    ema_slow = calculate_ema(close, config.EMA_SLOW)

    curr_fast, curr_slow = ema_fast.iloc[-1], ema_slow.iloc[-1]
    prev_fast, prev_slow = ema_fast.iloc[-2], ema_slow.iloc[-2]

    if any(np.isnan(v) for v in [curr_fast, curr_slow, prev_fast, prev_slow]):
        return {"signal": None, "ema_fast": 0, "ema_slow": 0, "spread_pct": 0, "strength": 0}

    price = close.iloc[-1]
    spread_pct = abs(curr_fast - curr_slow) / price * 100 if price > 0 else 0

    signal, strength = None, 0.0
    if prev_fast <= prev_slow and curr_fast > curr_slow:
        signal = "BUY"
        strength = min(spread_pct / 0.3, 1.0)
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
#  RSI
# =============================================================================

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(100)


def detect_rsi_signal(df, period=None):
    period = period or config.RSI_PERIOD
    if df is None or len(df) < period + 5:
        return {"signal": None, "rsi": 50, "strength": 0}

    rsi = calculate_rsi(df["close"], period)
    curr_rsi, prev_rsi = rsi.iloc[-1], rsi.iloc[-2]

    signal, strength = None, 0.0
    if prev_rsi < config.RSI_OVERSOLD and curr_rsi >= config.RSI_OVERSOLD:
        signal = "BUY"
        depth = max(0, config.RSI_OVERSOLD - rsi.iloc[-3]) if len(rsi) > 2 else 5
        strength = min(depth / 20, 1.0)
    elif prev_rsi > config.RSI_OVERBOUGHT and curr_rsi <= config.RSI_OVERBOUGHT:
        signal = "SELL"
        depth = max(0, rsi.iloc[-3] - config.RSI_OVERBOUGHT) if len(rsi) > 2 else 5
        strength = min(depth / 20, 1.0)

    return {"signal": signal, "rsi": round(curr_rsi, 2), "strength": round(strength, 3)}


# =============================================================================
#  STOCHASTIC RSI
# =============================================================================

def calculate_stochastic_rsi(series, rsi_period=14, stoch_period=14, k_smooth=3, d_smooth=3):
    if series is None or len(series) < rsi_period + stoch_period + 5:
        return {"k": 50, "d": 50, "signal": None}

    rsi = calculate_rsi(series, rsi_period)
    rsi_min = rsi.rolling(window=stoch_period).min()
    rsi_max = rsi.rolling(window=stoch_period).max()
    rsi_range = rsi_max - rsi_min

    stoch_rsi = ((rsi - rsi_min) / rsi_range.replace(0, np.nan)).fillna(0.5) * 100
    k_line = stoch_rsi.rolling(window=k_smooth).mean()
    d_line = k_line.rolling(window=d_smooth).mean()

    k_val = float(k_line.iloc[-1]) if not np.isnan(k_line.iloc[-1]) else 50
    d_val = float(d_line.iloc[-1]) if not np.isnan(d_line.iloc[-1]) else 50

    signal = None
    if len(k_line) >= 2 and len(d_line) >= 2:
        k_prev, d_prev = k_line.iloc[-2], d_line.iloc[-2]
        if not (np.isnan(k_prev) or np.isnan(d_prev)):
            if k_prev <= d_prev and k_val > d_val and k_val < 30:
                signal = "BUY"
            elif k_prev >= d_prev and k_val < d_val and k_val > 70:
                signal = "SELL"

    return {"k": round(k_val, 2), "d": round(d_val, 2), "signal": signal}


# =============================================================================
#  ADX
# =============================================================================

def calculate_adx(df, period=14):
    if df is None or len(df) < period * 2:
        return {"adx": 0, "plus_di": 0, "minus_di": 0, "trend_strength": "none", "di_signal": "none"}

    high, low, close = df["high"], df["low"], df["close"]
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr = pd.DataFrame({
        "hl": high - low,
        "hc": (high - close.shift()).abs(),
        "lc": (low - close.shift()).abs(),
    }).max(axis=1)

    atr = tr.ewm(alpha=1/period, min_periods=period).mean()
    plus_di = (plus_dm.ewm(alpha=1/period, min_periods=period).mean() / atr * 100).fillna(0)
    minus_di = (minus_dm.ewm(alpha=1/period, min_periods=period).mean() / atr * 100).fillna(0)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan) * 100).fillna(0)
    adx = dx.ewm(alpha=1/period, min_periods=period).mean()

    adx_val = float(adx.iloc[-1])
    plus_val = float(plus_di.iloc[-1])
    minus_val = float(minus_di.iloc[-1])

    if adx_val > 40: strength = "very_strong"
    elif adx_val > 25: strength = "strong"
    elif adx_val > 20: strength = "moderate"
    else: strength = "weak"

    return {
        "adx": round(adx_val, 2), "plus_di": round(plus_val, 2),
        "minus_di": round(minus_val, 2), "trend_strength": strength,
        "di_signal": "bullish" if plus_val > minus_val else "bearish",
    }


# =============================================================================
#  OBV
# =============================================================================

def calculate_obv(df):
    if df is None or len(df) < 10 or "volume" not in df.columns:
        return {"obv": 0, "obv_ema": 0, "obv_trend": "unknown"}

    close, volume = df["close"], df["volume"]
    direction = np.sign(close.diff()).fillna(0)
    obv = (direction * volume).cumsum()
    obv_ema = obv.ewm(span=20, adjust=False).mean()

    if len(obv) >= 10:
        recent_avg = obv.iloc[-5:].mean()
        prev_avg = obv.iloc[-10:-5].mean()
        if recent_avg > prev_avg * 1.05: trend = "rising"
        elif recent_avg < prev_avg * 0.95: trend = "falling"
        else: trend = "flat"
    else:
        trend = "unknown"

    return {
        "obv": round(float(obv.iloc[-1]), 0),
        "obv_ema": round(float(obv_ema.iloc[-1]), 0),
        "obv_trend": trend,
    }


# =============================================================================
#  ICHIMOKU
# =============================================================================

def calculate_ichimoku(df):
    if df is None or len(df) < config.ICHIMOKU_SENKOU_B + 5:
        return {"tenkan": 0, "kijun": 0, "senkou_a": 0, "senkou_b": 0,
                "cloud_color": "none", "price_vs_cloud": "unknown", "tk_cross": None}

    high, low, close = df["high"], df["low"], df["close"]
    price = close.iloc[-1]

    tenkan = (high.rolling(config.ICHIMOKU_TENKAN).max() + low.rolling(config.ICHIMOKU_TENKAN).min()) / 2
    kijun = (high.rolling(config.ICHIMOKU_KIJUN).max() + low.rolling(config.ICHIMOKU_KIJUN).min()) / 2
    senkou_a = (tenkan + kijun) / 2
    senkou_b = (high.rolling(config.ICHIMOKU_SENKOU_B).max() + low.rolling(config.ICHIMOKU_SENKOU_B).min()) / 2

    t_val = float(tenkan.iloc[-1])
    k_val = float(kijun.iloc[-1])
    sa_val = float(senkou_a.iloc[-1])
    sb_val = float(senkou_b.iloc[-1])

    cloud_color = "green" if sa_val > sb_val else "red"
    cloud_top = max(sa_val, sb_val)
    cloud_bottom = min(sa_val, sb_val)
    if price > cloud_top: price_vs_cloud = "above"
    elif price < cloud_bottom: price_vs_cloud = "below"
    else: price_vs_cloud = "inside"

    tk_cross = None
    if len(tenkan) >= 2 and len(kijun) >= 2:
        t_prev, k_prev = tenkan.iloc[-2], kijun.iloc[-2]
        if not (np.isnan(t_prev) or np.isnan(k_prev)):
            if t_prev <= k_prev and t_val > k_val: tk_cross = "bullish"
            elif t_prev >= k_prev and t_val < k_val: tk_cross = "bearish"

    return {
        "tenkan": round(t_val, 2), "kijun": round(k_val, 2),
        "senkou_a": round(sa_val, 2), "senkou_b": round(sb_val, 2),
        "cloud_color": cloud_color, "price_vs_cloud": price_vs_cloud,
        "tk_cross": tk_cross,
    }


# =============================================================================
#  PIVOT POINTS
# =============================================================================

def calculate_pivot_points(df):
    if df is None or len(df) < 2:
        return {"pivot": 0, "r1": 0, "r2": 0, "r3": 0, "s1": 0, "s2": 0, "s3": 0}
    h = float(df["high"].iloc[-2])
    l = float(df["low"].iloc[-2])
    c = float(df["close"].iloc[-2])
    pivot = (h + l + c) / 3
    return {
        "pivot": round(pivot, 2),
        "r1": round(2 * pivot - l, 2), "r2": round(pivot + (h - l), 2), "r3": round(h + 2 * (pivot - l), 2),
        "s1": round(2 * pivot - h, 2), "s2": round(pivot - (h - l), 2), "s3": round(l - 2 * (h - pivot), 2),
    }


# =============================================================================
#  RSI DIVERGENCE
# =============================================================================

def detect_rsi_divergence(df, rsi_period=14, lookback=20):
    if df is None or len(df) < rsi_period + lookback:
        return {"divergence": None, "type": None, "strength": 0}

    close = df["close"]
    rsi = calculate_rsi(close, rsi_period)
    price_seg = close.iloc[-lookback:].values
    rsi_seg = rsi.iloc[-lookback:].values

    def find_extrema(arr, is_max=True):
        extrema = []
        for i in range(2, len(arr) - 2):
            if is_max:
                if arr[i] > arr[i-1] and arr[i] > arr[i-2] and arr[i] > arr[i+1] and arr[i] > arr[i+2]:
                    extrema.append((i, arr[i]))
            else:
                if arr[i] < arr[i-1] and arr[i] < arr[i-2] and arr[i] < arr[i+1] and arr[i] < arr[i+2]:
                    extrema.append((i, arr[i]))
        return extrema

    price_lows = find_extrema(price_seg, is_max=False)
    rsi_lows = find_extrema(rsi_seg, is_max=False)
    if len(price_lows) >= 2 and len(rsi_lows) >= 2:
        p1, p2 = price_lows[-2], price_lows[-1]
        r1, r2 = rsi_lows[-2], rsi_lows[-1]
        if p2[1] < p1[1] and r2[1] > r1[1]:
            strength = abs(r2[1] - r1[1]) / 10
            return {"divergence": "bullish", "type": "regular", "strength": min(round(strength, 2), 1.0)}

    price_highs = find_extrema(price_seg, is_max=True)
    rsi_highs = find_extrema(rsi_seg, is_max=True)
    if len(price_highs) >= 2 and len(rsi_highs) >= 2:
        p1, p2 = price_highs[-2], price_highs[-1]
        r1, r2 = rsi_highs[-2], rsi_highs[-1]
        if p2[1] > p1[1] and r2[1] < r1[1]:
            strength = abs(r1[1] - r2[1]) / 10
            return {"divergence": "bearish", "type": "regular", "strength": min(round(strength, 2), 1.0)}

    return {"divergence": None, "type": None, "strength": 0}


# =============================================================================
#  VOLUME ANALYSIS
# =============================================================================

def analyze_volume(df, lookback=20):
    if df is None or len(df) < lookback or "volume" not in df.columns:
        return {"relative_volume": 1.0, "volume_trend": "unknown", "climax": False}

    vol = df["volume"]
    avg_vol = vol.iloc[-lookback:].mean()
    current_vol = vol.iloc[-1]
    relative = current_vol / avg_vol if avg_vol > 0 else 1.0

    recent_avg = vol.iloc[-5:].mean()
    prior_avg = vol.iloc[-10:-5].mean() if len(vol) >= 10 else avg_vol
    if recent_avg > prior_avg * 1.2: trend = "increasing"
    elif recent_avg < prior_avg * 0.8: trend = "decreasing"
    else: trend = "stable"

    return {
        "relative_volume": round(relative, 2), "volume_trend": trend,
        "climax": relative > 3.0,
        "avg_volume": round(avg_vol, 0), "current_volume": round(current_vol, 0),
    }


# =============================================================================
#  SUPPORT / RESISTANCE
# =============================================================================

def find_support_resistance(df, lookback=50, num_levels=3):
    if df is None or len(df) < lookback:
        return {"support": [], "resistance": []}

    close, high, low = df["close"], df["high"], df["low"]
    price = close.iloc[-1]
    prices = []

    for i in range(2, min(lookback, len(df)) - 2):
        idx = len(df) - lookback + i
        if idx < 2 or idx >= len(df) - 2:
            continue
        if high.iloc[idx] > high.iloc[idx-1] and high.iloc[idx] > high.iloc[idx+1]:
            prices.append(float(high.iloc[idx]))
        if low.iloc[idx] < low.iloc[idx-1] and low.iloc[idx] < low.iloc[idx+1]:
            prices.append(float(low.iloc[idx]))

    if not prices:
        return {"support": [], "resistance": []}

    prices.sort()
    clusters = []
    current_cluster = [prices[0]]
    for p in prices[1:]:
        if (p - current_cluster[-1]) / current_cluster[-1] < 0.001:
            current_cluster.append(p)
        else:
            clusters.append(sum(current_cluster) / len(current_cluster))
            current_cluster = [p]
    clusters.append(sum(current_cluster) / len(current_cluster))

    support = sorted([c for c in clusters if c < price], reverse=True)[:num_levels]
    resistance = sorted([c for c in clusters if c > price])[:num_levels]

    return {"support": [round(s, 2) for s in support], "resistance": [round(r, 2) for r in resistance]}


# =============================================================================
#  CANDLE PATTERNS
# =============================================================================

def detect_candle_patterns(df):
    if df is None or len(df) < 5:
        return {"patterns": [], "bias": "neutral"}

    o, h, l, c = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    patterns = []
    i = -1
    body = abs(c[i] - o[i])
    upper_wick = h[i] - max(o[i], c[i])
    lower_wick = min(o[i], c[i]) - l[i]
    total_range = h[i] - l[i]

    if total_range == 0:
        return {"patterns": ["doji"], "bias": "neutral"}

    body_pct = body / total_range

    if body_pct < 0.1:
        patterns.append("doji")
    if lower_wick > body * 2 and upper_wick < body * 0.5 and body_pct > 0.1:
        patterns.append("hammer_bullish" if c[i] > o[i] else "hanging_man_bearish")
    if upper_wick > body * 2 and lower_wick < body * 0.5 and body_pct > 0.1:
        patterns.append("shooting_star_bearish" if c[i] < o[i] else "inverted_hammer_bullish")

    if len(df) >= 2:
        prev_body = abs(c[-2] - o[-2])
        if c[-1] > o[-1] and c[-2] < o[-2] and body > prev_body * 1.2:
            if c[-1] > o[-2] and o[-1] < c[-2]:
                patterns.append("bullish_engulfing")
        elif c[-1] < o[-1] and c[-2] > o[-2] and body > prev_body * 1.2:
            if c[-1] < o[-2] and o[-1] > c[-2]:
                patterns.append("bearish_engulfing")

    if len(df) >= 3:
        if all(c[-j] > o[-j] for j in range(1, 4)):
            if c[-1] > c[-2] > c[-3]:
                patterns.append("three_white_soldiers_bullish")
        if all(c[-j] < o[-j] for j in range(1, 4)):
            if c[-1] < c[-2] < c[-3]:
                patterns.append("three_black_crows_bearish")

    bullish = sum(1 for p in patterns if "bullish" in p)
    bearish = sum(1 for p in patterns if "bearish" in p)
    bias = "bullish" if bullish > bearish else "bearish" if bearish > bullish else "neutral"

    return {"patterns": patterns, "bias": bias}


# =============================================================================
#  ATR
# =============================================================================

def calculate_atr(df, period=14):
    if df is None or len(df) < period + 1:
        return pd.Series(dtype=float)
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.DataFrame({
        "hl": high - low, "hc": (high - close.shift()).abs(), "lc": (low - close.shift()).abs(),
    }).max(axis=1)
    return tr.ewm(alpha=1/period, min_periods=period).mean()


def get_current_atr(df, period=14):
    atr = calculate_atr(df, period)
    return round(float(atr.iloc[-1]), 2) if len(atr) > 0 else 0.0


# =============================================================================
#  MACD
# =============================================================================

def calculate_macd(series, fast=12, slow=26, signal=9):
    if series is None or len(series) < slow + signal:
        return {"macd": 0, "signal_line": 0, "histogram": 0, "crossover": None, "hist_momentum": None}

    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    crossover = None
    if len(macd_line) >= 2:
        curr_m, prev_m = macd_line.iloc[-1], macd_line.iloc[-2]
        curr_s, prev_s = signal_line.iloc[-1], signal_line.iloc[-2]
        if prev_m <= prev_s and curr_m > curr_s: crossover = "bullish"
        elif prev_m >= prev_s and curr_m < curr_s: crossover = "bearish"

    hist_momentum = None
    if len(histogram) >= 3:
        h1, h2, h3 = histogram.iloc[-3], histogram.iloc[-2], histogram.iloc[-1]
        if h3 > h2 > h1: hist_momentum = "increasing"
        elif h3 < h2 < h1: hist_momentum = "decreasing"

    return {
        "macd": round(float(macd_line.iloc[-1]), 2),
        "signal_line": round(float(signal_line.iloc[-1]), 2),
        "histogram": round(float(histogram.iloc[-1]), 2),
        "crossover": crossover, "hist_momentum": hist_momentum,
    }


# =============================================================================
#  BOLLINGER BANDS
# =============================================================================

def calculate_bollinger_bands(series, period=20, std_dev=2.0):
    if series is None or len(series) < period:
        return {"upper": 0, "middle": 0, "lower": 0, "bandwidth_pct": 0, "price_position": 0.5, "squeeze": False}

    middle = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)

    curr_upper, curr_middle, curr_lower = float(upper.iloc[-1]), float(middle.iloc[-1]), float(lower.iloc[-1])
    curr_price = float(series.iloc[-1])
    bandwidth = (curr_upper - curr_lower) / curr_middle * 100 if curr_middle > 0 else 0
    band_range = curr_upper - curr_lower
    price_position = (curr_price - curr_lower) / band_range if band_range > 0 else 0.5

    bw_series = ((upper - lower) / middle * 100)
    squeeze = bandwidth <= bw_series.iloc[-20:].min() * 1.1 if len(bw_series) >= 20 else bandwidth < 2.0

    return {
        "upper": round(curr_upper, 2), "middle": round(curr_middle, 2), "lower": round(curr_lower, 2),
        "bandwidth_pct": round(bandwidth, 4),
        "price_position": round(max(0, min(1, price_position)), 3), "squeeze": squeeze,
    }


# =============================================================================
#  VWAP
# =============================================================================

def calculate_vwap(df):
    if df is None or len(df) < 2 or "volume" not in df.columns:
        return 0.0
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cum_vol = df["volume"].cumsum()
    cum_tp_vol = (typical_price * df["volume"]).cumsum()
    vwap = cum_tp_vol / cum_vol
    vwap = vwap.replace([np.inf, -np.inf], np.nan).fillna(0)
    return round(float(vwap.iloc[-1]), 2)


# =============================================================================
#  MULTI-TIMEFRAME EMA
# =============================================================================

def calculate_higher_tf_emas(df):
    if df is None or len(df) < 10:
        return {"ema50": 0, "ema200": 0, "trend": "unknown"}

    close = df["close"]
    price = close.iloc[-1]
    ema50 = calculate_ema(close, min(50, len(close) - 1))
    ema50_val = round(float(ema50.iloc[-1]), 2)

    ema200_val = 0
    if len(close) >= 30:
        period = min(200, len(close) - 1)
        ema200 = calculate_ema(close, period)
        ema200_val = round(float(ema200.iloc[-1]), 2)

    trend = "unknown"
    if ema50_val > 0 and ema200_val > 0:
        if price > ema50_val > ema200_val: trend = "strong_bullish"
        elif price > ema50_val: trend = "bullish"
        elif price < ema50_val < ema200_val: trend = "strong_bearish"
        elif price < ema50_val: trend = "bearish"
        else: trend = "neutral"

    return {"ema50": ema50_val, "ema200": ema200_val, "trend": trend}


# =============================================================================
#  MARKET REGIME
# =============================================================================

def detect_regime(df_5m):
    if df_5m is None or len(df_5m) < config.EMA_SLOW + 5:
        return {"regime": "unknown", "atr_pct": 0, "ema_spread_pct": 0, "reason": "Insufficient data"}

    close = df_5m["close"]
    price = close.iloc[-1]
    if price <= 0:
        return {"regime": "unknown", "atr_pct": 0, "ema_spread_pct": 0, "reason": "Invalid price"}

    atr = get_current_atr(df_5m, config.REGIME_ATR_PERIOD)
    atr_pct = (atr / price) * 100

    if atr_pct > config.REGIME_ATR_HIGH_VOL_THRESHOLD:
        return {"regime": "high_volatility", "atr_pct": round(atr_pct, 4), "ema_spread_pct": 0,
                "reason": f"ATR {atr_pct:.3f}% > {config.REGIME_ATR_HIGH_VOL_THRESHOLD}%"}

    ema_fast = calculate_ema(close, config.EMA_FAST)
    ema_slow = calculate_ema(close, config.EMA_SLOW)
    spread_pct = abs(ema_fast.iloc[-1] - ema_slow.iloc[-1]) / price * 100

    if spread_pct > config.REGIME_EMA_SPREAD_TREND_THRESHOLD:
        direction = "bullish" if ema_fast.iloc[-1] > ema_slow.iloc[-1] else "bearish"
        return {"regime": "trending", "atr_pct": round(atr_pct, 4),
                "ema_spread_pct": round(spread_pct, 4), "reason": f"{direction} trend"}

    return {"regime": "ranging", "atr_pct": round(atr_pct, 4),
            "ema_spread_pct": round(spread_pct, 4), "reason": "range-bound"}


# =============================================================================
#  SL / TP
# =============================================================================

def calculate_sl_tp(entry_price, direction, atr_value):
    sl_distance = atr_value * config.SL_ATR_MULTIPLIER
    tp_distance = atr_value * config.TP_ATR_MULTIPLIER

    sl_min = entry_price * (config.SL_MIN_PERCENT / 100)
    tp_min = entry_price * (config.TP_MIN_PERCENT / 100)
    sl_distance = max(sl_distance, sl_min)
    tp_distance = max(tp_distance, tp_min)

    sl_max = entry_price * (config.SL_MAX_PERCENT / 100)
    tp_max = entry_price * (config.TP_MAX_PERCENT / 100)
    sl_distance = min(sl_distance, sl_max)
    tp_distance = min(tp_distance, tp_max)

    if direction == "BUY":
        stop_loss = entry_price - sl_distance
        take_profit = entry_price + tp_distance
    else:
        stop_loss = entry_price + sl_distance
        take_profit = entry_price - tp_distance

    return {
        "stop_loss": round(stop_loss, 2), "take_profit": round(take_profit, 2),
        "sl_distance": round(sl_distance, 2), "tp_distance": round(tp_distance, 2),
        "sl_pct": round(sl_distance / entry_price * 100, 4),
        "tp_pct": round(tp_distance / entry_price * 100, 4),
        "risk_reward_ratio": round(tp_distance / sl_distance, 2) if sl_distance > 0 else 0,
    }


# =============================================================================
#  DYNAMIC POSITION SIZING (NEW in v3)
# =============================================================================

def calculate_dynamic_position_size(entry_price, confidence, available_balance_usd,
                                    leverage=None):
    """
    Position size scales with confidence.
    Higher confidence → bigger position.
    """
    lev = leverage or config.LEVERAGE

    # Get usage % based on confidence
    usage_pct = config.MAX_BALANCE_USAGE_PERCENT  # fallback
    for conf_threshold in sorted(config.CONFIDENCE_SIZING.keys()):
        if confidence >= conf_threshold:
            usage_pct = config.CONFIDENCE_SIZING[conf_threshold]

    usable = available_balance_usd * (usage_pct / 100)
    position_value_usd = usable * lev
    contracts = int(position_value_usd / entry_price) if entry_price > 0 else 0

    return {
        "contracts": max(1, contracts),
        "position_value_usd": round(position_value_usd, 2),
        "margin_used_usd": round(usable, 2),
        "usage_pct": usage_pct,
        "leverage": lev,
        "confidence": confidence,
    }


# Legacy position sizing (for compatibility)
def calculate_position_size(entry_price, balance_usdt=None, leverage=None):
    balance = balance_usdt or 100
    lev = leverage or config.LEVERAGE
    usable = balance * (config.MAX_BALANCE_USAGE_PERCENT / 100)
    position_value_usd = usable * lev
    contracts = int(position_value_usd / entry_price) if entry_price > 0 else 0
    return {
        "contracts": max(1, contracts), "position_value_usd": round(position_value_usd, 2),
        "margin_used_usd": round(usable, 2), "leverage": lev,
    }
