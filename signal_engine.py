"""
=============================================================================
 SIGNAL_ENGINE.PY — Core Signal Generation Logic
=============================================================================
 Orchestrates the entire signal flow:
   1. Detect market regime (trending / ranging / high-vol)
   2. Pick the right strategy based on regime
   3. Generate signal if conditions met
   4. Score confidence using all data sources
   5. Calculate SL/TP/position size
   6. Enforce cooldown between signals
   7. Enforce trading hours (2 PM – 2 AM IST)
   
 Returns a complete Signal dict ready for alerts/display.
=============================================================================
"""

import time
from datetime import datetime, timezone, timedelta
import config
import indicators


# ── IST timezone offset ─────────────────────────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30))

# ── Signal cooldown state ───────────────────────────────────────────────────
_last_signal = {"direction": None, "timestamp": 0}


# =============================================================================
#  TRADING HOURS CHECK
# =============================================================================

def is_within_trading_hours():
    """
    Check if current time is within 2:00 PM – 2:00 AM IST.
    
    This spans midnight, so logic is:
      hour >= 14 (2 PM) OR hour < 2 (before 2 AM)
    
    Returns:
        tuple: (bool, str current_time_ist)
    """
    now_ist = datetime.now(IST)
    hour = now_ist.hour

    # 2 PM (14:00) to midnight = hours 14–23
    # Midnight to 2 AM = hours 0–1
    in_window = hour >= config.TRADING_START_HOUR_IST or hour < config.TRADING_END_HOUR_IST

    return in_window, now_ist.strftime("%I:%M %p IST")


# =============================================================================
#  COOLDOWN CHECK
# =============================================================================

def check_cooldown(direction):
    """
    Ensure we don't spam identical signals within the cooldown period.
    
    Same-direction signals are blocked for SIGNAL_COOLDOWN_SECONDS.
    Opposite-direction signals are always allowed (market reversed).
    
    Returns:
        bool — True if signal is allowed, False if in cooldown
    """
    global _last_signal

    now = time.time()

    # Opposite direction? Always allow.
    if direction != _last_signal["direction"]:
        return True

    # Same direction — check time elapsed
    elapsed = now - _last_signal["timestamp"]
    if elapsed >= config.SIGNAL_COOLDOWN_SECONDS:
        return True

    return False


def update_cooldown(direction):
    """Record that a signal was generated for cooldown tracking."""
    global _last_signal
    _last_signal = {"direction": direction, "timestamp": time.time()}


# =============================================================================
#  CONFIDENCE SCORER
# =============================================================================

def calculate_confidence(direction, strategy_strength, all_data):
    """
    Calculate a 1–10 confidence score using ALL data sources.
    
    Components (weights in config.py):
      1. Strategy strength (0.30) — how strong the TA signal is
      2. Binance agreement (0.15) — does Binance price trend agree?
      3. Funding rate    (0.15) — contrarian: negative funding favors longs
      4. OI trend        (0.10) — rising OI = conviction
      5. Fear & Greed    (0.15) — contrarian: extreme fear → buy opportunity
      6. BTC dominance   (0.05) — high dominance = BTC strength
      7. Volume          (0.10) — higher volume = more conviction
    
    Args:
        direction: "BUY" or "SELL"
        strategy_strength: 0.0–1.0 from the indicator
        all_data: dict from data_fetcher.fetch_all_data()
    
    Returns:
        dict: {"score": int (1–10), "breakdown": dict of component scores}
    """
    scores = {}

    # ── 1. Strategy Strength ────────────────────────────────────────────────
    scores["strategy"] = strategy_strength * 10  # 0–10

    # ── 2. Binance Price Agreement ──────────────────────────────────────────
    binance_score = 5.0  # neutral default
    binance_klines = all_data.get("binance_klines")
    if binance_klines is not None and len(binance_klines) >= 10:
        # Compare last 10 candles — is Binance trending same direction?
        recent_close = binance_klines["close"].iloc[-1]
        past_close = binance_klines["close"].iloc[-10]
        binance_trend = "up" if recent_close > past_close else "down"

        if (direction == "BUY" and binance_trend == "up") or \
           (direction == "SELL" and binance_trend == "down"):
            binance_score = 8.0
        elif (direction == "BUY" and binance_trend == "down") or \
             (direction == "SELL" and binance_trend == "up"):
            binance_score = 2.0

    scores["binance"] = binance_score

    # ── 3. Funding Rate ─────────────────────────────────────────────────────
    funding_score = 5.0
    ticker = all_data.get("delta_ticker")
    if ticker and ticker.get("funding_rate") is not None:
        fr = ticker["funding_rate"]
        # Contrarian: negative funding = shorts are paying → favors BUY
        # Positive funding = longs are paying → favors SELL
        if direction == "BUY":
            if fr < -0.01:
                funding_score = 9.0    # strongly negative — great for longs
            elif fr < 0:
                funding_score = 7.0
            elif fr > 0.01:
                funding_score = 2.0    # longs paying high funding — risky
            else:
                funding_score = 5.0
        else:  # SELL
            if fr > 0.01:
                funding_score = 9.0    # strongly positive — great for shorts
            elif fr > 0:
                funding_score = 7.0
            elif fr < -0.01:
                funding_score = 2.0
            else:
                funding_score = 5.0

    scores["funding"] = funding_score

    # ── 4. Open Interest Trend ──────────────────────────────────────────────
    oi_score = 5.0
    if ticker and ticker.get("open_interest", 0) > 0:
        # We check if OI is rising (bullish conviction) 
        # In a simple check, high OI = more conviction in current direction
        oi = ticker["open_interest"]
        # Normalize: we'll give a baseline score and adjust later with history
        oi_score = 6.0 if oi > 0 else 5.0

    scores["oi"] = oi_score

    # ── 5. Fear & Greed Index ───────────────────────────────────────────────
    fg_score = 5.0
    fg = all_data.get("fear_greed")
    if fg:
        value = fg["value"]
        # Contrarian: extreme fear (< 25) is good for BUY
        #             extreme greed (> 75) is good for SELL
        if direction == "BUY":
            if value < 20:
                fg_score = 9.0       # extreme fear — buy opportunity
            elif value < 35:
                fg_score = 7.0
            elif value > 75:
                fg_score = 2.0       # extreme greed — bad for new longs
            elif value > 60:
                fg_score = 4.0
            else:
                fg_score = 5.0
        else:  # SELL
            if value > 80:
                fg_score = 9.0       # extreme greed — sell opportunity
            elif value > 65:
                fg_score = 7.0
            elif value < 25:
                fg_score = 2.0       # extreme fear — bad for new shorts
            elif value < 40:
                fg_score = 4.0
            else:
                fg_score = 5.0

    scores["fear_greed"] = fg_score

    # ── 6. BTC Dominance ────────────────────────────────────────────────────
    dom_score = 5.0
    cg = all_data.get("coingecko")
    if cg:
        dom = cg.get("btc_dominance", 50)
        # High BTC dominance (> 55%) = BTC is strong relative to alts
        # Slightly favors BUY signals on BTC
        if direction == "BUY":
            dom_score = 7.0 if dom > 55 else 5.0
        else:
            dom_score = 7.0 if dom < 50 else 5.0

    scores["btc_dominance"] = dom_score

    # ── 7. Volume ───────────────────────────────────────────────────────────
    vol_score = 5.0
    if ticker and ticker.get("volume", 0) > 0:
        # Higher volume = more conviction — give a bonus
        vol_score = 7.0  # baseline "volume exists and is healthy"

    scores["volume"] = vol_score

    # ── 8. Orderbook Imbalance (bonus) ─────────────────────────────────────
    # Bid/ask pressure as a directional confirmation.
    # Not weighted separately — used as a ±1 adjustment to final score.
    ob_adjustment = 0.0
    orderbook = all_data.get("delta_orderbook")
    if orderbook:
        try:
            bid_vol = sum(float(b.get("size", 0)) for b in orderbook.get("buy", []))
            ask_vol = sum(float(a.get("size", 0)) for a in orderbook.get("sell", []))
            total_vol = bid_vol + ask_vol

            if total_vol > 0:
                imbalance = (bid_vol - ask_vol) / total_vol  # -1 to +1

                # If BUY signal and bids dominate → +0.5 bonus
                # If SELL signal and asks dominate → +0.5 bonus
                # If mismatched → -0.5 penalty
                if direction == "BUY":
                    ob_adjustment = 0.5 if imbalance > 0.1 else (-0.5 if imbalance < -0.1 else 0)
                else:  # SELL
                    ob_adjustment = 0.5 if imbalance < -0.1 else (-0.5 if imbalance > 0.1 else 0)
        except (TypeError, ValueError):
            pass

    # ── Weighted average ────────────────────────────────────────────────────
    weighted_sum = (
        scores["strategy"] * config.WEIGHT_STRATEGY_STRENGTH +
        scores["binance"] * config.WEIGHT_BINANCE_AGREEMENT +
        scores["funding"] * config.WEIGHT_FUNDING_RATE +
        scores["oi"] * config.WEIGHT_OI_TREND +
        scores["fear_greed"] * config.WEIGHT_FEAR_GREED +
        scores["btc_dominance"] * config.WEIGHT_BTC_DOMINANCE +
        scores["volume"] * config.WEIGHT_VOLUME
    )

    # Apply orderbook imbalance adjustment
    weighted_sum += ob_adjustment

    # Clamp to 1–10
    final_score = max(1, min(10, round(weighted_sum)))

    return {
        "score": final_score,
        "breakdown": {k: round(v, 1) for k, v in scores.items()},
        "ob_adjustment": ob_adjustment,
    }


# =============================================================================
#  MAIN SIGNAL GENERATOR
# =============================================================================

def generate_signal(all_data):
    """
    Master function: generates a trading signal from all fetched data.
    
    Flow:
      1. Check trading hours
      2. Detect regime from 5m candles
      3. If trending → run EMA crossover on 5m candles
      4. If ranging → run RSI mean-reversion on 3m candles
      5. If high_volatility → no signal (sit out)
      6. If signal found → score confidence, calc SL/TP/size
      7. Check cooldown
      8. Return complete signal or None
    
    Args:
        all_data: dict from data_fetcher.fetch_all_data()
    
    Returns:
        dict (complete signal) or None (no signal this cycle)
    """
    # ── Step 1: Trading hours ───────────────────────────────────────────────
    in_hours, time_str = is_within_trading_hours()
    if not in_hours:
        return {"status": "OUTSIDE_HOURS", "time": time_str}

    # ── Step 2: Get entry price ─────────────────────────────────────────────
    ticker = all_data.get("delta_ticker")
    if ticker is None:
        return {"status": "NO_DATA", "reason": "Delta ticker unavailable"}

    entry_price = ticker.get("mark_price", 0)
    if entry_price <= 0:
        return {"status": "NO_DATA", "reason": "Invalid price from Delta"}

    # ── Step 3: Detect regime ───────────────────────────────────────────────
    candles_5m = all_data.get("delta_candles_5m")
    regime = indicators.detect_regime(candles_5m)

    # ── Step 4: High volatility → sit out ───────────────────────────────────
    if regime["regime"] == "high_volatility":
        return {
            "status": "SIT_OUT",
            "regime": regime,
            "price": entry_price,
            "time": time_str,
            "reason": regime["reason"],
        }

    # ── Step 5: Apply strategy based on regime ──────────────────────────────
    signal = None
    strategy_name = None
    strategy_strength = 0

    if regime["regime"] == "trending":
        # EMA 9/21 crossover on 5-minute candles
        ema_result = indicators.detect_ema_crossover(candles_5m)
        if ema_result["signal"]:
            signal = ema_result["signal"]
            strategy_name = "EMA 9/21 Crossover"
            strategy_strength = ema_result["strength"]

    elif regime["regime"] == "ranging":
        # RSI mean-reversion on 3-minute candles
        candles_3m = all_data.get("delta_candles_3m")
        rsi_result = indicators.detect_rsi_signal(candles_3m)
        if rsi_result["signal"]:
            signal = rsi_result["signal"]
            strategy_name = "RSI Mean-Reversion"
            strategy_strength = rsi_result["strength"]

    # ── Step 6: No signal this cycle ────────────────────────────────────────
    if signal is None:
        return {
            "status": "NO_SIGNAL",
            "regime": regime,
            "price": entry_price,
            "time": time_str,
            "reason": f"No {regime['regime']} signal triggered this cycle",
        }

    # ── Step 7: Cooldown check ──────────────────────────────────────────────
    if not check_cooldown(signal):
        return {
            "status": "COOLDOWN",
            "regime": regime,
            "price": entry_price,
            "time": time_str,
            "direction": signal,
            "reason": f"Cooldown active — same direction ({signal}) signal too recent",
        }

    # ── Step 8: Calculate ATR for SL/TP ─────────────────────────────────────
    # Use 5m candles for ATR regardless of strategy
    atr_value = indicators.get_current_atr(candles_5m, config.REGIME_ATR_PERIOD)
    sl_tp = indicators.calculate_sl_tp(entry_price, signal, atr_value)

    # ── Step 9: Position sizing ─────────────────────────────────────────────
    position = indicators.calculate_position_size(entry_price)

    # ── Step 10: Confidence scoring ─────────────────────────────────────────
    confidence = calculate_confidence(signal, strategy_strength, all_data)

    # ── Step 11: Gather supplementary data ──────────────────────────────────
    fear_greed = all_data.get("fear_greed")
    coingecko = all_data.get("coingecko")
    binance_price = all_data.get("binance_price")

    # ── Step 12: Update cooldown ────────────────────────────────────────────
    update_cooldown(signal)

    # ── Step 13: Build complete signal ──────────────────────────────────────
    return {
        "status": "SIGNAL",
        "time": time_str,
        "timestamp": int(time.time()),

        # ── Core Signal ──
        "direction": signal,
        "strategy": strategy_name,
        "regime": regime,

        # ── Price Levels ──
        "entry_price": round(entry_price, 2),
        "stop_loss": sl_tp["stop_loss"],
        "take_profit": sl_tp["take_profit"],
        "sl_distance_pct": sl_tp["sl_distance_pct"],
        "tp_distance_pct": sl_tp["tp_distance_pct"],
        "sl_method": sl_tp["sl_method"],
        "tp_method": sl_tp["tp_method"],

        # ── Position Sizing ──
        "contracts": position["contracts"],
        "position_value_usd": position["position_value_usd"],
        "margin_used_usd": position["margin_used_usd"],
        "leverage": config.LEVERAGE,

        # ── Confidence ──
        "confidence": confidence["score"],
        "confidence_breakdown": confidence["breakdown"],

        # ── Market Context ──
        "atr": atr_value,
        "atr_pct": regime["atr_pct"],
        "funding_rate": ticker.get("funding_rate", 0),
        "open_interest": ticker.get("open_interest", 0),
        "delta_volume": ticker.get("volume", 0),
        "binance_price": binance_price,
        "fear_greed_value": fear_greed["value"] if fear_greed else None,
        "fear_greed_label": fear_greed["classification"] if fear_greed else None,
        "btc_dominance": coingecko["btc_dominance"] if coingecko else None,
    }
