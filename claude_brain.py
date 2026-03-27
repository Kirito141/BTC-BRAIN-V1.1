"""
=============================================================================
 CLAUDE_BRAIN.PY v2 — Advanced AI Trade Analysis Engine
=============================================================================
 Sends EVERY available indicator and market signal to Claude for synthesis.
 
 Data sent:
   • Multi-TF price data (5m, 15m, 1h, 4h)
   • 15+ technical indicators per timeframe
   • Ichimoku Cloud, ADX, Stoch RSI, OBV
   • RSI Divergence, Candle Patterns, Volume Analysis
   • Support/Resistance levels, Pivot Points
   • Binance Futures Intelligence (L/S, whales, taker flow, OI, funding)
   • Sentiment (Fear & Greed 7-day trend, BTC dominance)
   • Recent trade performance for self-improvement loop
=============================================================================
"""

import json
import time
import os
import csv
from datetime import datetime, timezone, timedelta

import requests
import config
import indicators

IST = timezone(timedelta(hours=5, minutes=30))

_recent_signals = []
_trade_history = []


def _call_claude_api(prompt, system_prompt):
    """Call Anthropic Messages API with extended tokens."""
    if not config.ANTHROPIC_API_KEY:
        print("  [ERROR] ANTHROPIC_API_KEY not set")
        return None

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": config.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": config.CLAUDE_MODEL,
        "max_tokens": config.CLAUDE_MAX_TOKENS,
        "system": system_prompt,
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=90)
        if resp.status_code == 200:
            data = resp.json()
            return "".join(b["text"] for b in data.get("content", []) if b.get("type") == "text")
        else:
            print(f"  [ERROR] Claude API {resp.status_code}: {resp.text[:300]}")
            return None
    except requests.exceptions.Timeout:
        print("  [ERROR] Claude API timed out (90s)")
        return None
    except Exception as e:
        print(f"  [ERROR] Claude API: {e}")
        return None


def _build_system_prompt(current_position=None):
    """Build the system prompt — the heart of the bot's intelligence."""
    hours_str = "24/7" if config.TRADING_START_HOUR_IST == 0 and config.TRADING_END_HOUR_IST == 24 else f"{config.TRADING_START_HOUR_IST}:00 - {config.TRADING_END_HOUR_IST}:00 IST"

    if current_position:
        pos = current_position
        elapsed = (int(time.time()) - pos.get("entry_timestamp", int(time.time()))) // 60
        position_block = f"""
═══ CURRENT OPEN POSITION ═══
Direction: {pos['direction']}
Entry Price: ${pos['entry_price']:,.2f}
Current SL: ${pos['stop_loss']:,.2f}
Current TP: ${pos['take_profit']:,.2f}
Entry Confidence: {pos.get('confidence', '?')}/10
Time in trade: {elapsed} minutes
Reasoning at entry: {pos.get('reasoning', 'N/A')}

YOUR ALLOWED ACTIONS: HOLD, TRAIL_SL, ADJUST_TP, EXIT, REVERSE
- HOLD: keep position unchanged
- TRAIL_SL: move SL closer to lock profit (include "new_sl" in response)
- ADJUST_TP: move TP (include "new_tp" in response)
- EXIT: close position immediately (use when momentum dying or thesis broken)
- REVERSE: close + open opposite direction (include "reverse_entry", "reverse_sl", "reverse_tp")"""

        json_format = """{
  "action": "HOLD|TRAIL_SL|ADJUST_TP|EXIT|REVERSE",
  "confidence": 1-10,
  "reasoning": "detailed reasoning for this action",
  "market_condition": "brief market state description",
  "risk_warnings": "any concerns",
  "new_sl": 0.0,        // only for TRAIL_SL
  "new_tp": 0.0,        // only for ADJUST_TP
  "reverse_entry": 0.0, // only for REVERSE
  "reverse_sl": 0.0,    // only for REVERSE
  "reverse_tp": 0.0     // only for REVERSE
}"""
    else:
        position_block = """
═══ POSITION STATE: FLAT (no open trade) ═══
YOUR ALLOWED ACTIONS: BUY, SELL, NO_TRADE
- BUY: open LONG position
- SELL: open SHORT position
- NO_TRADE: skip this cycle (DEFAULT — most cycles should be NO_TRADE)"""

        json_format = """{
  "action": "BUY|SELL|NO_TRADE",
  "confidence": 1-10,
  "reasoning": "detailed multi-factor reasoning",
  "market_condition": "brief market state",
  "risk_warnings": "any concerns",
  "entry_price": 0.0,
  "stop_loss": 0.0,
  "take_profit": 0.0
}"""

    return f"""You are an elite quantitative BTC trader analyzing BTCUSD Inverse Perpetual on Delta Exchange India.

INSTRUMENT: BTCUSD Inverse Perpetual
STYLE: Swing-Scalp Hybrid (hold minutes to hours, up to ~1 day max)
LEVERAGE: {config.LEVERAGE}x
POSITION SIZE: {config.BALANCE_USAGE_PERCENT}% of ${config.DEFAULT_BALANCE_USDT} balance
RISK MANAGEMENT: ATR-based SL/TP with floors (SL min {config.SL_MIN_PERCENT}%, TP min {config.TP_MIN_PERCENT}%, max SL {config.SL_MAX_PERCENT}%, max TP {config.TP_MAX_PERCENT}%)
TRADING HOURS: {hours_str}
RULE: 1 position at a time. No stacking.
{position_block}

═══ ANALYSIS FRAMEWORK (follow this order) ═══

STEP 1 — HIGHER TIMEFRAME BIAS (4h → 1h):
  • 4h trend sets the MACRO direction. Do NOT fight it.
  • 1h confirms or warns of reversal.
  • If 4h + 1h agree → trade WITH the trend.
  • If 4h + 1h conflict → NO_TRADE or very cautious scalp only.

STEP 2 — TREND STRENGTH CONFIRMATION:
  • ADX > 25 = strong trend → trade WITH it. ADX < 20 = no trend → mean-reversion plays.
  • Ichimoku: Price above cloud = bullish. Below = bearish. Inside = chop.
  • OBV confirming price move = real. OBV diverging = fake move.

STEP 3 — ENTRY TIMING (15m → 5m):
  • 15m gives structure. 5m gives entry timing.
  • MACD crossover + RSI confirmation on 5m = entry trigger.
  • Stochastic RSI oversold K crossing above D (< 20 zone) = strong buy trigger.
  • Stochastic RSI overbought K crossing below D (> 80 zone) = strong sell trigger.
  • Bollinger Band squeeze → expansion = breakout entry.

STEP 4 — CONFLUENCE CHECK:
  • Count how many of these AGREE with your direction:
    [4h trend, 1h trend, 15m trend, 5m MACD, 5m RSI, Stoch RSI, ADX direction,
     Ichimoku cloud position, OBV trend, VWAP position, BB position,
     Candle patterns, RSI divergence, Funding rate, Taker flow]
  • Need 8+ bullish for BUY, 8+ bearish for SELL.
  • < 8 confluence → NO_TRADE.

STEP 5 — SENTIMENT & POSITIONING FILTER:
  • Fear & Greed < 25 (Extreme Fear) + bullish technicals = STRONG BUY (contrarian).
  • Fear & Greed > 75 (Extreme Greed) + bearish technicals = STRONG SELL (contrarian).
  • 65%+ retail long = contrarian sell bias. 65%+ short = contrarian buy bias.
  • Top traders (whales) positioning matters MORE than retail.
  • Taker buy/sell > 1.3 = aggressive buying. < 0.7 = aggressive selling.
  • Negative funding = longs pay less (bullish). Very positive funding = crowded longs (bearish).
  • Funding rate TREND matters: if funding going from positive to negative = sentiment shift.

STEP 6 — RISK MANAGEMENT:
  • SL MUST be at a logical level (below support for longs, above resistance for shorts).
  • Use pivot points, S/R levels, or Ichimoku cloud edges as SL placement guides.
  • TP at next resistance (for longs) or support (for shorts).
  • Risk:Reward must be > 1.5:1. If not → NO_TRADE.
  • ATR > 2% = extreme volatility → either NO_TRADE or very wide SL.

═══ CRITICAL RULES (NEVER VIOLATE) ═══

1. 4H TREND IS KING. Never counter-trade the 4h trend unless RSI 4h is extreme (>85 or <15).

2. MULTI-TIMEFRAME ALIGNMENT REQUIRED:
   For BUY: need 3 of 4 timeframes bullish (5m, 15m, 1h, 4h).
   For SELL: need 3 of 4 timeframes bearish.
   2 or fewer aligned → NO_TRADE.

3. NO_TRADE IS THE CORRECT DEFAULT:
   Most cycles should return NO_TRADE. Only trade with HIGH conviction.
   If confidence < 7 → NO_TRADE. Mixed signals → NO_TRADE.
   Protecting capital > chasing trades.

4. NEVER RE-ENTER SAME DIRECTION AFTER A LOSS:
   If last trade was a losing LONG → do NOT immediately LONG again.
   Wait for clear reversal setup or opposite direction trade.

5. RSI DIVERGENCE IS POWERFUL:
   Bullish divergence (price lower low, RSI higher low) near support = high-probability BUY.
   Bearish divergence near resistance = high-probability SELL.

6. VOLUME CONFIRMS, LACK OF VOLUME WARNS:
   High volume on breakout = real. Low volume breakout = likely fakeout → NO_TRADE.
   Volume climax (>3x avg) often signals exhaustion, not continuation.

7. CANDLE PATTERNS MATTER AT KEY LEVELS:
   Engulfing at support/resistance is meaningful. Random engulfing in middle of range = noise.

8. POSITION MANAGEMENT:
   When in profit > 0.5%: suggest TRAIL_SL to breakeven.
   When profit > 1%: trail SL to lock 50% of gains.
   If momentum reverses (MACD flipping, RSI diverging): suggest EXIT before SL hit.
   REVERSE only with 8+ confidence and clear trend reversal on 1h+.

═══ CONFIDENCE SCORING ═══
9-10: Everything aligned. All timeframes, all indicators, strong momentum, contrarian sentiment. RARE.
7-8: Strong setup. 3+ timeframes aligned, most indicators agree, decent volume.
5-6: Marginal. Some alignment but mixed signals. → NO_TRADE.
1-4: Bad. Conflicting signals. → Definitely NO_TRADE.

═══ RESPONSE FORMAT ═══
Return ONLY valid JSON. No markdown fences. No extra text.
{json_format}"""


def compute_all_indicators(all_data):
    """Compute ALL technical indicators across ALL timeframes."""
    result = {}

    # ── 5m indicators (primary) ─────────────────────────────────────────
    candles_5m = all_data.get("delta_candles_5m")
    if candles_5m is not None and len(candles_5m) > 30:
        close = candles_5m["close"]
        price = close.iloc[-1]

        ema9 = indicators.calculate_ema(close, 9)
        ema21 = indicators.calculate_ema(close, 21)
        result["ema9"] = round(float(ema9.iloc[-1]), 2)
        result["ema21"] = round(float(ema21.iloc[-1]), 2)
        result["ema_spread_pct"] = round(abs(result["ema9"] - result["ema21"]) / price * 100, 4) if price > 0 else 0
        result["ema_crossover"] = indicators.detect_ema_crossover(candles_5m)["signal"]

        atr = indicators.get_current_atr(candles_5m)
        result["atr"] = atr
        result["atr_pct"] = round(atr / price * 100, 4) if price > 0 else 0

        regime = indicators.detect_regime(candles_5m)
        result["regime"] = regime["regime"]
        result["regime_reason"] = regime["reason"]

        # RSI
        rsi = indicators.calculate_rsi(close, config.RSI_PERIOD)
        result["rsi_5m"] = round(float(rsi.iloc[-1]), 2)
        result["rsi_5m_signal"] = indicators.detect_rsi_signal(candles_5m)["signal"]

        # MACD
        macd = indicators.calculate_macd(close)
        result["macd"] = macd["macd"]
        result["macd_signal"] = macd["signal_line"]
        result["macd_histogram"] = macd["histogram"]
        result["macd_crossover"] = macd["crossover"]
        result["macd_hist_momentum"] = macd.get("hist_momentum")

        # Bollinger Bands
        bb = indicators.calculate_bollinger_bands(close)
        result["bb_upper"] = bb["upper"]
        result["bb_middle"] = bb["middle"]
        result["bb_lower"] = bb["lower"]
        result["bb_bandwidth"] = bb["bandwidth_pct"]
        result["bb_position"] = bb["price_position"]
        result["bb_squeeze"] = bb["squeeze"]

        # VWAP
        result["vwap_5m"] = indicators.calculate_vwap(candles_5m)

        # Stochastic RSI
        stoch = indicators.calculate_stochastic_rsi(close)
        result["stoch_rsi_k"] = stoch["k"]
        result["stoch_rsi_d"] = stoch["d"]
        result["stoch_rsi_signal"] = stoch["signal"]

        # ADX
        adx = indicators.calculate_adx(candles_5m)
        result["adx"] = adx["adx"]
        result["adx_plus_di"] = adx["plus_di"]
        result["adx_minus_di"] = adx["minus_di"]
        result["adx_trend_strength"] = adx["trend_strength"]
        result["adx_di_signal"] = adx["di_signal"]

        # OBV
        obv = indicators.calculate_obv(candles_5m)
        result["obv_trend"] = obv["obv_trend"]

        # Ichimoku (needs enough data)
        if len(candles_5m) > 55:
            ichi = indicators.calculate_ichimoku(candles_5m)
            result["ichimoku_cloud_color"] = ichi["cloud_color"]
            result["ichimoku_price_vs_cloud"] = ichi["price_vs_cloud"]
            result["ichimoku_tk_cross"] = ichi["tk_cross"]
            result["ichimoku_tenkan"] = ichi["tenkan"]
            result["ichimoku_kijun"] = ichi["kijun"]

        # Pivot Points (from 1h candles for better levels)
        candles_1h = all_data.get("delta_candles_1h")
        if candles_1h is not None and len(candles_1h) > 5:
            pivots = indicators.calculate_pivot_points(candles_1h)
            result["pivot"] = pivots["pivot"]
            result["pivot_r1"] = pivots["r1"]
            result["pivot_r2"] = pivots["r2"]
            result["pivot_s1"] = pivots["s1"]
            result["pivot_s2"] = pivots["s2"]

        # RSI Divergence
        div = indicators.detect_rsi_divergence(candles_5m)
        result["rsi_divergence"] = div["divergence"]
        result["rsi_div_strength"] = div["strength"]

        # Volume Analysis
        vol = indicators.analyze_volume(candles_5m)
        result["relative_volume"] = vol["relative_volume"]
        result["volume_trend"] = vol["volume_trend"]
        result["volume_climax"] = vol["climax"]

        # Candle Patterns
        patterns = indicators.detect_candle_patterns(candles_5m)
        result["candle_patterns"] = patterns["patterns"]
        result["candle_bias"] = patterns["bias"]

        # Support/Resistance
        sr = indicators.find_support_resistance(candles_5m)
        result["support_levels"] = sr["support"]
        result["resistance_levels"] = sr["resistance"]

    # ── 15m higher timeframe ────────────────────────────────────────────
    candles_15m = all_data.get("delta_candles_15m")
    if candles_15m is not None and len(candles_15m) > 20:
        htf_15m = indicators.calculate_higher_tf_emas(candles_15m)
        result["htf_15m_trend"] = htf_15m["trend"]
        result["htf_15m_ema50"] = htf_15m["ema50"]

        rsi_15m = indicators.calculate_rsi(candles_15m["close"], 14)
        result["rsi_15m"] = round(float(rsi_15m.iloc[-1]), 1)

        macd_15m = indicators.calculate_macd(candles_15m["close"])
        result["macd_15m_crossover"] = macd_15m["crossover"]
        result["macd_15m_histogram"] = macd_15m["histogram"]

        adx_15m = indicators.calculate_adx(candles_15m)
        result["adx_15m"] = adx_15m["adx"]
        result["adx_15m_trend"] = adx_15m["trend_strength"]

    # ── 1h higher timeframe ─────────────────────────────────────────────
    candles_1h = all_data.get("delta_candles_1h")
    if candles_1h is not None and len(candles_1h) > 20:
        htf_1h = indicators.calculate_higher_tf_emas(candles_1h)
        result["htf_1h_trend"] = htf_1h["trend"]
        result["htf_1h_ema50"] = htf_1h["ema50"]
        result["htf_1h_ema200"] = htf_1h["ema200"]

        rsi_1h = indicators.calculate_rsi(candles_1h["close"], 14)
        result["rsi_1h"] = round(float(rsi_1h.iloc[-1]), 1)

        macd_1h = indicators.calculate_macd(candles_1h["close"])
        result["macd_1h_crossover"] = macd_1h["crossover"]
        result["macd_1h_histogram"] = macd_1h["histogram"]

        if len(candles_1h) > 55:
            ichi_1h = indicators.calculate_ichimoku(candles_1h)
            result["ichimoku_1h_cloud"] = ichi_1h["cloud_color"]
            result["ichimoku_1h_price_vs_cloud"] = ichi_1h["price_vs_cloud"]

        # 1h S/R levels (more significant)
        sr_1h = indicators.find_support_resistance(candles_1h, lookback=80)
        result["support_1h"] = sr_1h["support"]
        result["resistance_1h"] = sr_1h["resistance"]

        # 1h divergence
        div_1h = indicators.detect_rsi_divergence(candles_1h)
        result["rsi_divergence_1h"] = div_1h["divergence"]

    # ── 4h higher timeframe ─────────────────────────────────────────────
    candles_4h = all_data.get("delta_candles_4h")
    if candles_4h is not None and len(candles_4h) > 15:
        htf_4h = indicators.calculate_higher_tf_emas(candles_4h)
        result["htf_4h_trend"] = htf_4h["trend"]
        result["htf_4h_ema50"] = htf_4h["ema50"]

        rsi_4h = indicators.calculate_rsi(candles_4h["close"], 14)
        result["rsi_4h"] = round(float(rsi_4h.iloc[-1]), 1)

        macd_4h = indicators.calculate_macd(candles_4h["close"])
        result["macd_4h_crossover"] = macd_4h["crossover"]
        result["macd_4h_histogram"] = macd_4h["histogram"]

        adx_4h = indicators.calculate_adx(candles_4h)
        result["adx_4h"] = adx_4h["adx"]
        result["adx_4h_trend"] = adx_4h["trend_strength"]
        result["adx_4h_di_signal"] = adx_4h["di_signal"]

    return result


def _build_market_data_prompt(all_data, computed):
    """Build comprehensive market data prompt."""
    now_ist = datetime.now(IST)
    parts = []

    parts.append(f"=== BTC/USD MARKET SNAPSHOT — {now_ist.strftime('%d %b %Y, %I:%M:%S %p IST')} ===")
    parts.append("")

    # ── Price ───────────────────────────────────────────────────────────
    ticker = all_data.get("delta_ticker")
    binance_price = all_data.get("binance_price")

    parts.append("── PRICE ──")
    if ticker:
        mp = ticker["mark_price"]
        parts.append(f"Delta Mark: ${mp:,.2f} | 24h H: ${ticker['high']:,.2f} L: ${ticker['low']:,.2f}")
        parts.append(f"24h Open: ${ticker['open']:,.2f} | Volume: {ticker['volume']:,.0f}")
        parts.append(f"Funding Rate: {ticker['funding_rate']:.6f} | OI: {ticker['open_interest']:,.0f}")
        if ticker.get("spot_price", 0) > 0:
            parts.append(f"Spot/Index: ${ticker['spot_price']:,.2f}")
    if binance_price:
        parts.append(f"Binance Spot: ${binance_price:,.2f}")
        if ticker:
            spread = ticker["mark_price"] - binance_price
            parts.append(f"Delta-Binance Spread: ${spread:+,.2f} ({spread/binance_price*100:+.4f}%)")
    parts.append("")

    # ── 5m Indicators ───────────────────────────────────────────────────
    parts.append("── 5-MIN INDICATORS (primary timeframe) ──")
    parts.append(f"EMA 9: ${computed.get('ema9', 0):,.2f} | EMA 21: ${computed.get('ema21', 0):,.2f} | Spread: {computed.get('ema_spread_pct', 0):.4f}%")
    parts.append(f"EMA Direction: {'Bullish (9>21)' if computed.get('ema9', 0) > computed.get('ema21', 0) else 'Bearish (9<21)'} | Crossover: {computed.get('ema_crossover') or 'None'}")
    parts.append(f"RSI(14): {computed.get('rsi_5m', 50):.2f} | Signal: {computed.get('rsi_5m_signal') or 'None'}")
    parts.append(f"Stoch RSI: K={computed.get('stoch_rsi_k', 50):.1f} D={computed.get('stoch_rsi_d', 50):.1f} | Signal: {computed.get('stoch_rsi_signal') or 'None'}")
    parts.append(f"MACD: {computed.get('macd', 0):.2f} (sig: {computed.get('macd_signal', 0):.2f}, hist: {computed.get('macd_histogram', 0):.2f}) | Cross: {computed.get('macd_crossover') or 'None'} | Momentum: {computed.get('macd_hist_momentum') or 'flat'}")
    parts.append(f"BB Upper: ${computed.get('bb_upper', 0):,.2f} | Mid: ${computed.get('bb_middle', 0):,.2f} | Lower: ${computed.get('bb_lower', 0):,.2f}")
    parts.append(f"BB Width: {computed.get('bb_bandwidth', 0):.4f}% | Position: {computed.get('bb_position', 0.5):.3f} (0=low,1=high) | Squeeze: {computed.get('bb_squeeze', False)}")
    parts.append(f"VWAP: ${computed.get('vwap_5m', 0):,.2f}")
    parts.append(f"ADX: {computed.get('adx', 0):.1f} ({computed.get('adx_trend_strength', 'none')}) | +DI: {computed.get('adx_plus_di', 0):.1f} -DI: {computed.get('adx_minus_di', 0):.1f} | DI Signal: {computed.get('adx_di_signal', 'none')}")
    parts.append(f"OBV Trend: {computed.get('obv_trend', 'unknown')}")
    parts.append(f"ATR(14): ${computed.get('atr', 0):,.2f} ({computed.get('atr_pct', 0):.4f}%) | Regime: {computed.get('regime', 'unknown')}")
    parts.append(f"RSI Divergence: {computed.get('rsi_divergence') or 'None'} (strength: {computed.get('rsi_div_strength', 0)})")
    parts.append(f"Volume: {computed.get('relative_volume', 1.0):.2f}x avg | Trend: {computed.get('volume_trend', 'unknown')} | Climax: {computed.get('volume_climax', False)}")
    parts.append(f"Candle Patterns: {', '.join(computed.get('candle_patterns', [])) or 'None'} | Bias: {computed.get('candle_bias', 'neutral')}")

    if computed.get("ichimoku_cloud_color"):
        parts.append(f"Ichimoku: Cloud={computed['ichimoku_cloud_color']} | Price vs Cloud: {computed.get('ichimoku_price_vs_cloud', '?')} | TK Cross: {computed.get('ichimoku_tk_cross') or 'None'}")

    if computed.get("pivot"):
        parts.append(f"Pivots: P=${computed['pivot']:,.2f} | R1=${computed.get('pivot_r1', 0):,.2f} R2=${computed.get('pivot_r2', 0):,.2f} | S1=${computed.get('pivot_s1', 0):,.2f} S2=${computed.get('pivot_s2', 0):,.2f}")

    if computed.get("support_levels"):
        parts.append(f"Support: {', '.join(f'${s:,.2f}' for s in computed['support_levels'])}")
    if computed.get("resistance_levels"):
        parts.append(f"Resistance: {', '.join(f'${r:,.2f}' for r in computed['resistance_levels'])}")
    parts.append("")

    # ── Higher Timeframes ───────────────────────────────────────────────
    parts.append("── HIGHER TIMEFRAME TRENDS ──")
    parts.append(f"15m: Trend={computed.get('htf_15m_trend', '?')} | RSI={computed.get('rsi_15m', '?')} | MACD Cross={computed.get('macd_15m_crossover') or 'None'} | ADX={computed.get('adx_15m', '?')} ({computed.get('adx_15m_trend', '?')})")
    parts.append(f"1h:  Trend={computed.get('htf_1h_trend', '?')} | EMA50=${computed.get('htf_1h_ema50', 0):,.2f} EMA200=${computed.get('htf_1h_ema200', 0):,.2f} | RSI={computed.get('rsi_1h', '?')} | MACD Cross={computed.get('macd_1h_crossover') or 'None'}")
    if computed.get("ichimoku_1h_cloud"):
        parts.append(f"1h Ichimoku: Cloud={computed['ichimoku_1h_cloud']} | Price vs Cloud: {computed.get('ichimoku_1h_price_vs_cloud', '?')}")
    if computed.get("rsi_divergence_1h"):
        parts.append(f"1h RSI Divergence: {computed['rsi_divergence_1h']}")
    parts.append(f"4h:  Trend={computed.get('htf_4h_trend', '?')} | EMA50=${computed.get('htf_4h_ema50', 0):,.2f} | RSI={computed.get('rsi_4h', '?')} | MACD Cross={computed.get('macd_4h_crossover') or 'None'}")
    parts.append(f"4h ADX: {computed.get('adx_4h', '?')} ({computed.get('adx_4h_trend', '?')}) | DI Signal: {computed.get('adx_4h_di_signal', '?')}")

    if computed.get("support_1h"):
        parts.append(f"1h Support: {', '.join(f'${s:,.2f}' for s in computed['support_1h'])}")
    if computed.get("resistance_1h"):
        parts.append(f"1h Resistance: {', '.join(f'${r:,.2f}' for r in computed['resistance_1h'])}")
    parts.append("")

    # ── Binance Futures Intelligence ────────────────────────────────────
    bf = all_data.get("binance_futures") or {}
    parts.append("── BINANCE FUTURES INTELLIGENCE ──")

    ls = bf.get("long_short_ratio")
    if ls:
        parts.append(f"Retail L/S Ratio: {ls['long_short_ratio']:.3f} (Long: {ls['long_account_pct']:.1f}% Short: {ls['short_account_pct']:.1f}%)")

    tp = bf.get("top_trader_positions")
    if tp:
        parts.append(f"Whale L/S Ratio: {tp['long_short_ratio']:.3f} (Long: {tp['long_pct']:.1f}% Short: {tp['short_pct']:.1f}%)")

    tbs = bf.get("taker_buy_sell")
    if tbs:
        parts.append(f"Taker Buy/Sell: {tbs['buy_sell_ratio']:.3f} (Buy Vol: {tbs['buy_volume']:,.0f} Sell Vol: {tbs['sell_volume']:,.0f})")

    oi = bf.get("open_interest")
    if oi:
        parts.append(f"Binance OI: {oi['open_interest']:,.2f}")

    fh = bf.get("funding_history")
    if fh:
        parts.append(f"Funding: Current={fh['current_rate']:.6f} | Avg(10)={fh['avg_rate']:.6f} | Trend: {fh['trend']}")
    parts.append("")

    # ── Orderbook & Trade Tape ──────────────────────────────────────────
    ob = all_data.get("delta_orderbook")
    if ob:
        bid_vol = sum(float(b.get("size", 0)) for b in ob.get("buy", []))
        ask_vol = sum(float(a.get("size", 0)) for a in ob.get("sell", []))
        total = bid_vol + ask_vol
        imbalance = (bid_vol - ask_vol) / total * 100 if total > 0 else 0
        parts.append(f"── ORDERBOOK ──")
        parts.append(f"Bid Volume: {bid_vol:,.0f} | Ask Volume: {ask_vol:,.0f} | Imbalance: {imbalance:+.1f}%")

    trades = all_data.get("delta_trades")
    if trades:
        parts.append(f"── TRADE TAPE ──")
        parts.append(f"Recent Trades: {trades['total_trades']} | Buy: {trades['buy_pct']:.0f}% | Aggression: {trades['aggression']:+.3f}")
        if trades.get("large_trades"):
            lt_strs = []
            for t in trades["large_trades"][:3]:
                lt_strs.append(f"{t['side']} {t['size']:,.0f}@${t['price']:,.2f}")
            parts.append(f"Large trades: {', '.join(lt_strs)}")
    parts.append("")

    # ── Sentiment ───────────────────────────────────────────────────────
    fg = all_data.get("fear_greed")
    cg = all_data.get("coingecko")
    parts.append("── SENTIMENT ──")
    if fg:
        parts.append(f"Fear & Greed: {fg['value']} — {fg['classification']} | 7d Trend: {fg.get('trend', '?')} | History: {fg.get('values_7d', [])}")
    if cg:
        parts.append(f"BTC Dominance: {cg['btc_dominance']:.2f}% | Global 24h Vol: ${cg['total_volume_usd']/1e9:,.1f}B | Market Cap Δ24h: {cg.get('market_cap_change_24h', 0):.2f}%")
    parts.append("")

    # ── Recent 5m Candles ───────────────────────────────────────────────
    candles_5m = all_data.get("delta_candles_5m")
    if candles_5m is not None and len(candles_5m) >= 10:
        parts.append("── LAST 10 CANDLES (5m, newest first) ──")
        for _, row in candles_5m.tail(10).iloc[::-1].iterrows():
            o, h, l, c = row["open"], row["high"], row["low"], row["close"]
            v = row.get("volume", 0)
            ct = "GREEN" if c >= o else "RED"
            parts.append(f"  O:${o:,.1f} H:${h:,.1f} L:${l:,.1f} C:${c:,.1f} V:{v:,.0f} [{ct}]")
        parts.append("")

    # ── Position Sizing ─────────────────────────────────────────────────
    if ticker:
        pos = indicators.calculate_position_size(ticker["mark_price"])
        parts.append(f"Position: ${config.DEFAULT_BALANCE_USDT} × {config.BALANCE_USAGE_PERCENT}% × {config.LEVERAGE}x = {pos['contracts']} contracts")
        parts.append("")

    # ── Signal History ──────────────────────────────────────────────────
    if _recent_signals:
        parts.append("── YOUR RECENT SIGNALS (newest first) ──")
        for sig in reversed(_recent_signals[-7:]):
            parts.append(f"  {sig['time']} {sig['decision']} conf:{sig['confidence']}/10 → {sig.get('outcome', 'pending')}")
        parts.append("")

    # ── Loss warning ────────────────────────────────────────────────────
    try:
        if _recent_signals:
            last = _recent_signals[-1]
            if last.get("decision") in ["BUY", "SELL"] and last.get("outcome") in ["sl_hit", "loss"]:
                parts.append(f"⚠ LAST TRADE {last['decision']} WAS A LOSS. Do NOT re-enter {last['decision']}.")
                parts.append("")
    except Exception:
        pass

    parts.append("=== END DATA — Analyze and respond with JSON ===")
    return "\n".join(parts)


def analyze_with_claude(all_data, current_position=None):
    """Main analysis function: compute indicators → build prompt → ask Claude."""
    computed = compute_all_indicators(all_data)
    system_prompt = _build_system_prompt(current_position)
    market_prompt = _build_market_data_prompt(all_data, computed)

    # ── Inject position context ─────────────────────────────────────────
    if current_position:
        import position_manager
        ticker = all_data.get("delta_ticker")
        current_price = ticker["mark_price"] if ticker else 0
        pos_summary = position_manager.get_position_summary(current_price)
        market_prompt += f"\n\nCURRENT POSITION STATUS: {pos_summary}"
        market_prompt += "\nShould I HOLD, TRAIL_SL, ADJUST_TP, EXIT, or REVERSE?"
    else:
        market_prompt += "\n\nI am FLAT (no open position). Should I BUY, SELL, or NO_TRADE?"

    # ── Inject daily P&L context ────────────────────────────────────────
    try:
        import pnl_tracker
        daily = pnl_tracker.get_daily_pnl()
        if daily["trades_count"] > 0:
            market_prompt += f"\n\nDAILY P&L: ${daily['total_pnl_usd']:+,.2f} ({daily['trades_count']} trades, W:{daily['wins']} L:{daily['losses']})"
            if daily["losses"] > daily["wins"]:
                market_prompt += "\n⚠ LOSING DAY — be extra conservative. Prefer NO_TRADE."
            if daily["losses"] >= 3:
                market_prompt += "\n🛑 3+ LOSSES TODAY — STRONGLY prefer NO_TRADE. Capital preservation mode."
    except Exception:
        pass

    # ── Inject last trade loss warning ──────────────────────────────────
    if _recent_signals:
        last = _recent_signals[-1]
        last_dir = last.get("decision", "")
        last_outcome = last.get("outcome", "")
        if last_dir in ["BUY", "SELL"] and last_outcome in ["sl_hit", "loss"]:
            market_prompt += f"\n⚠ LAST TRADE: {last_dir} was a LOSS. Do NOT immediately re-enter {last_dir}."

    market_prompt += "\nRespond ONLY with the JSON object."

    print("  🧠 Analyzing with Claude...")
    raw_response = _call_claude_api(market_prompt, system_prompt)

    if raw_response is None:
        return None

    try:
        cleaned = raw_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()

        analysis = json.loads(cleaned)

        # Normalize action
        action = (analysis.get("action") or analysis.get("decision") or "").upper().strip()
        analysis["action"] = action

        # Validate action
        if current_position:
            valid = ["HOLD", "TRAIL_SL", "ADJUST_TP", "EXIT", "REVERSE"]
        else:
            valid = ["BUY", "SELL", "NO_TRADE"]

        if action not in valid:
            print(f"  [WARN] Invalid action '{action}' → {'HOLD' if current_position else 'NO_TRADE'}")
            analysis["action"] = "HOLD" if current_position else "NO_TRADE"

        analysis["confidence"] = max(1, min(10, int(analysis.get("confidence", 5))))
        analysis["timestamp"] = int(time.time())
        analysis["time"] = datetime.now(IST).strftime("%I:%M %p IST")
        analysis["raw_response"] = raw_response
        analysis["indicators"] = computed

        # Track signal
        _recent_signals.append({
            "time": analysis["time"],
            "decision": analysis["action"],
            "confidence": analysis["confidence"],
            "entry_price": analysis.get("entry_price", 0),
            "outcome": "pending",
        })
        if len(_recent_signals) > 15:
            _recent_signals.pop(0)

        return analysis

    except json.JSONDecodeError as e:
        print(f"  [ERROR] JSON parse: {e}")
        print(f"  Raw: {raw_response[:500]}")
        return None
    except Exception as e:
        print(f"  [ERROR] Parse: {e}")
        return None


def record_trade_taken(signal, entry_price=None):
    """Record a trade taken by the operator."""
    _trade_history.append({
        "time": signal.get("time", ""),
        "direction": signal.get("action") or signal.get("decision", ""),
        "entry_price": entry_price or signal.get("entry_price", 0),
        "stop_loss": signal.get("stop_loss", 0),
        "take_profit": signal.get("take_profit", 0),
        "confidence": signal.get("confidence", 0),
    })
    if len(_trade_history) > 20:
        _trade_history.pop(0)


def mark_last_signal_loss(direction):
    """Mark last signal of given direction as loss."""
    for sig in reversed(_recent_signals):
        if sig.get("decision") == direction:
            sig["outcome"] = "loss"
            break


def update_signal_outcome(index, outcome):
    """Update outcome of a past signal."""
    if 0 <= index < len(_recent_signals):
        _recent_signals[index]["outcome"] = outcome
