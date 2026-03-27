"""
=============================================================================
 PRE_FILTER.PY — Smart Gate Before Claude API Call
=============================================================================
 Runs cheap indicator checks every 60s cycle. Only calls Claude when:
   1. Multiple timeframes agree on direction (3+ of 4)
   2. "Interesting events" detected (crossovers, divergences, extremes)
   3. Enough time has passed since last Claude call
   4. Not in cooldown / drawdown exceeded
 
 This alone eliminates 60-80% of Claude API calls.
=============================================================================
"""

import time
from datetime import datetime, timezone, timedelta

import config

IST = timezone(timedelta(hours=5, minutes=30))


def should_call_claude(computed_indicators, bot_state, has_open_position=False):
    """
    Decide whether this cycle warrants a Claude API call.
    
    Returns: (should_call: bool, reason: str)
    """
    # ── Always call if in position (but still throttle) ─────────────────
    if has_open_position:
        elapsed = bot_state.seconds_since_last_claude_call()
        # In position: call every 3 minutes minimum (position management)
        if elapsed < 180:
            return False, f"in_position_throttle ({elapsed:.0f}s < 180s)"
        return True, "position_management"

    # ── Safety checks ───────────────────────────────────────────────────
    in_cooldown, cooldown_min = bot_state.is_in_cooldown()
    if in_cooldown:
        return False, f"loss_cooldown ({cooldown_min}m remaining)"

    if bot_state.is_daily_drawdown_exceeded():
        return False, "daily_drawdown_exceeded"

    # ── Time throttle ───────────────────────────────────────────────────
    elapsed = bot_state.seconds_since_last_claude_call()
    if elapsed < config.MIN_CLAUDE_INTERVAL:
        # Unless something very interesting happened
        events = _count_interesting_events(computed_indicators)
        if events < 3:  # need MORE events to override throttle
            return False, f"time_throttle ({elapsed:.0f}s < {config.MIN_CLAUDE_INTERVAL}s, events={events})"

    # ── Check 1: Timeframe Agreement ────────────────────────────────────
    tf_score = _check_timeframe_alignment(computed_indicators)
    if tf_score["agreement_count"] < config.MIN_TF_AGREEMENT:
        return False, f"low_tf_agreement ({tf_score['agreement_count']}/4, need {config.MIN_TF_AGREEMENT})"

    # ── Check 2: Interesting Events ─────────────────────────────────────
    events = _count_interesting_events(computed_indicators)
    if events < config.MIN_INTERESTING_EVENTS:
        return False, f"no_interesting_events ({events} < {config.MIN_INTERESTING_EVENTS})"

    # ── Check 3: ADX filter — skip if no trend on any timeframe ─────────
    adx_5m = computed_indicators.get("adx", 0)
    adx_15m = computed_indicators.get("adx_15m", 0)
    adx_4h = computed_indicators.get("adx_4h", 0)
    if max(adx_5m, adx_15m, adx_4h) < 18:
        # All timeframes show no trend at all
        if events < 3:  # Unless there are many events
            return False, f"no_trend_any_tf (adx max={max(adx_5m, adx_15m, adx_4h):.0f})"

    # ── Check 4: RSI not in dead zone ───────────────────────────────────
    rsi_5m = computed_indicators.get("rsi_5m", 50)
    rsi_1h = computed_indicators.get("rsi_1h", 50)
    # If all RSIs are in the 40-60 "neutral zone" and no events, skip
    if (40 < rsi_5m < 60) and (40 < rsi_1h < 60) and events < 2:
        return False, f"rsi_neutral_zone (5m={rsi_5m:.0f}, 1h={rsi_1h:.0f})"

    # ── Passed all filters → call Claude ────────────────────────────────
    direction = tf_score["dominant_direction"]
    return True, f"qualified: {direction} ({tf_score['agreement_count']}/4 TFs, {events} events)"


def _check_timeframe_alignment(indicators):
    """Count how many timeframes agree on direction."""
    bullish = 0
    bearish = 0

    # 5m
    ema9 = indicators.get("ema9", 0)
    ema21 = indicators.get("ema21", 0)
    if ema9 > ema21:
        bullish += 1
    elif ema9 < ema21:
        bearish += 1

    # 15m trend
    trend_15m = indicators.get("htf_15m_trend", "")
    if "bullish" in trend_15m:
        bullish += 1
    elif "bearish" in trend_15m:
        bearish += 1

    # 1h trend
    trend_1h = indicators.get("htf_1h_trend", "")
    if "bullish" in trend_1h:
        bullish += 1
    elif "bearish" in trend_1h:
        bearish += 1

    # 4h trend (most important)
    trend_4h = indicators.get("htf_4h_trend", "")
    if "bullish" in trend_4h:
        bullish += 1
    elif "bearish" in trend_4h:
        bearish += 1

    agreement = max(bullish, bearish)
    direction = "bullish" if bullish >= bearish else "bearish"

    return {
        "bullish": bullish,
        "bearish": bearish,
        "agreement_count": agreement,
        "dominant_direction": direction,
    }


def _count_interesting_events(indicators):
    """Count how many 'interesting' things are happening right now."""
    events = 0

    # EMA crossover on any timeframe
    if indicators.get("ema_crossover"):
        events += 2  # Fresh crossover is very interesting

    # MACD crossover on any timeframe
    if indicators.get("macd_crossover"):
        events += 2
    if indicators.get("macd_15m_crossover"):
        events += 1
    if indicators.get("macd_1h_crossover"):
        events += 2  # 1h MACD cross is significant
    if indicators.get("macd_4h_crossover"):
        events += 3  # 4h MACD cross is very significant

    # Stochastic RSI signal
    stoch_signal = indicators.get("stoch_rsi_signal")
    if stoch_signal:
        events += 1

    # RSI at extremes
    rsi_5m = indicators.get("rsi_5m", 50)
    if rsi_5m < 25 or rsi_5m > 75:
        events += 1
    if rsi_5m < 15 or rsi_5m > 85:
        events += 2  # Very extreme

    rsi_1h = indicators.get("rsi_1h", 50)
    if rsi_1h < 25 or rsi_1h > 75:
        events += 2  # 1h RSI extreme is significant

    rsi_4h = indicators.get("rsi_4h", 50)
    if rsi_4h < 20 or rsi_4h > 80:
        events += 3  # 4h RSI extreme is very significant

    # RSI divergence
    if indicators.get("rsi_divergence"):
        events += 2
    if indicators.get("rsi_divergence_1h"):
        events += 3

    # Bollinger Band squeeze breakout
    if indicators.get("bb_squeeze"):
        events += 1
    bb_pos = indicators.get("bb_position", 0.5)
    if bb_pos < 0.05 or bb_pos > 0.95:
        events += 1  # Price at BB extremes

    # Volume climax
    if indicators.get("volume_climax"):
        events += 2

    # High relative volume
    rel_vol = indicators.get("relative_volume", 1.0)
    if rel_vol > 2.0:
        events += 1

    # Candle patterns at key levels
    patterns = indicators.get("candle_patterns", [])
    if patterns:
        events += 1
        if any("engulfing" in p for p in patterns):
            events += 1

    # Ichimoku TK cross
    if indicators.get("ichimoku_tk_cross"):
        events += 1

    # Strong ADX with DI cross
    adx = indicators.get("adx", 0)
    if adx > 30:
        events += 1

    return events


def get_filter_summary(computed_indicators, bot_state, has_position):
    """Get a human-readable summary of the pre-filter state."""
    should_call, reason = should_call_claude(computed_indicators, bot_state, has_position)
    tf = _check_timeframe_alignment(computed_indicators)
    events = _count_interesting_events(computed_indicators)
    elapsed = bot_state.seconds_since_last_claude_call()

    return {
        "should_call_claude": should_call,
        "reason": reason,
        "tf_agreement": tf["agreement_count"],
        "dominant_direction": tf["dominant_direction"],
        "interesting_events": events,
        "seconds_since_last_call": round(elapsed),
        "claude_calls_today": bot_state.claude_calls_today(),
    }
