"""
=============================================================================
 CLAUDE_BRAIN.PY v3 — Optimized AI Trade Analysis Engine
=============================================================================
 Key changes from v2:
   • Shorter prompts (especially for position management)
   • Prompt caching via Anthropic API headers
   • No raw candle data sent (indicators already computed)
   • Prompt logging to disk for debugging
   • Structured step output from Claude for transparency
   • Dynamic position sizing context
=============================================================================
"""

import json
import time
import os
from datetime import datetime, timezone, timedelta

import requests
import config
import indicators

IST = timezone(timedelta(hours=5, minutes=30))


def _call_claude_api(prompt, system_prompt):
    """Call Anthropic Messages API with automatic prompt caching."""
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
        "cache_control": {"type": "ephemeral"},
        "system": system_prompt,
        "messages": [{"role": "user", "content": prompt}],
    }

    # Log prompt to disk
    _log_prompt(system_prompt, prompt)

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=90)
            if resp.status_code == 200:
                data = resp.json()
                # Log cache performance
                usage = data.get("usage", {})
                cache_read = usage.get("cache_read_input_tokens", 0)
                cache_create = usage.get("cache_creation_input_tokens", 0)
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                print(f"  💰 Tokens: in={input_tokens} out={output_tokens} "
                      f"cache_read={cache_read} cache_create={cache_create}")
                return "".join(b["text"] for b in data.get("content", []) if b.get("type") == "text")

            elif resp.status_code == 429:
                wait = 10 * (2 ** (attempt - 1))
                print(f"  [WARN] Claude 429 — retry in {wait}s ({attempt}/{max_retries})")
                if attempt < max_retries:
                    time.sleep(wait)
                    continue
                return None
            elif resp.status_code in (500, 502, 503, 529):
                wait = 5 * attempt
                print(f"  [WARN] Claude {resp.status_code} — retry in {wait}s ({attempt}/{max_retries})")
                if attempt < max_retries:
                    time.sleep(wait)
                    continue
                return None
            else:
                print(f"  [ERROR] Claude {resp.status_code}: {resp.text[:300]}")
                return None
        except requests.exceptions.Timeout:
            print(f"  [ERROR] Claude timeout — attempt {attempt}/{max_retries}")
            if attempt < max_retries:
                time.sleep(5)
                continue
            return None
        except Exception as e:
            print(f"  [ERROR] Claude API: {e}")
            return None
    return None


def _log_prompt(system_prompt, user_prompt):
    """Log prompts to disk for debugging bad decisions."""
    try:
        os.makedirs(config.PROMPT_LOG_DIR, exist_ok=True)
        timestamp = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(config.PROMPT_LOG_DIR, f"prompt_{timestamp}.txt")
        with open(filepath, "w") as f:
            f.write("=== SYSTEM PROMPT ===\n")
            f.write(system_prompt)
            f.write("\n\n=== USER PROMPT ===\n")
            f.write(user_prompt)

        # Keep only last 50 prompt logs
        logs = sorted(os.listdir(config.PROMPT_LOG_DIR))
        while len(logs) > 50:
            os.remove(os.path.join(config.PROMPT_LOG_DIR, logs.pop(0)))
    except Exception:
        pass


# =============================================================================
#  SYSTEM PROMPTS — Optimized for cost
# =============================================================================

def _build_entry_system_prompt():
    """System prompt for new entry decisions (FLAT state). Cached across calls."""
    return f"""You are an elite quantitative BTC trader analyzing BTCUSD Inverse Perpetual on Delta Exchange India.

INSTRUMENT: BTCUSD Inverse Perpetual | LEVERAGE: {config.LEVERAGE}x
STYLE: Swing-Scalp Hybrid (hold minutes to hours, max ~1 day)
RISK: ATR-based SL/TP, SL {config.SL_MIN_PERCENT}-{config.SL_MAX_PERCENT}%, TP {config.TP_MIN_PERCENT}-{config.TP_MAX_PERCENT}%
RULE: 1 position at a time. No stacking.

═══ ANALYSIS FRAMEWORK (follow all 6 steps, reference step numbers in reasoning) ═══

STEP 1 — HIGHER TIMEFRAME BIAS (4h → 1h):
  • 4h trend is KING. Do NOT counter-trade it unless 4h RSI is extreme (>85 or <15).
  • 1h confirms or warns of reversal.
  • 4h + 1h agree → trade WITH trend. 4h + 1h conflict → NO_TRADE or very cautious.

STEP 2 — TREND STRENGTH CONFIRMATION:
  • ADX > 25 = strong trend → trade WITH it. ADX < 20 = no trend → mean-reversion only.
  • Ichimoku: Price above cloud = bullish. Below = bearish. Inside cloud = chop → avoid.
  • OBV rising + price rising = genuine. OBV diverging from price = fake move → avoid.
  • Tenkan/Kijun cross confirms trend changes.

STEP 3 — ENTRY TIMING (15m → 5m):
  • 15m sets the structure, 5m pinpoints the entry.
  • MACD crossover + RSI confirmation on 5m = primary entry trigger.
  • Stochastic RSI: K crossing above D below 20 = strong buy. K crossing below D above 80 = strong sell.
  • Bollinger Band squeeze → expansion = breakout entry. Width < 2% = squeeze.
  • Price at lower BB + bullish candle = long entry zone. Upper BB + bearish candle = short.

STEP 4 — CONFLUENCE CHECK (most important):
  Count how many of these 15 signals AGREE with your direction:
  [4h trend, 1h trend, 15m trend, 5m MACD, 5m RSI zone, Stoch RSI signal, ADX DI direction,
   Ichimoku cloud position, OBV trend, VWAP position, BB position, Candle patterns,
   RSI divergence, Funding rate bias, Taker buy/sell flow]
  • Need 8+ for entry. < 8 → NO_TRADE.
  • For BUY: need 3+ of 4 timeframes bullish. For SELL: 3+ bearish.

STEP 5 — SENTIMENT & POSITIONING FILTER:
  • Fear & Greed < 25 (Extreme Fear) + bullish technicals = contrarian BUY (strong).
  • Fear & Greed > 75 (Extreme Greed) + bearish technicals = contrarian SELL (strong).
  • Retail 65%+ long = contrarian sell bias. 65%+ short = contrarian buy bias.
  • Top traders (whales) positioning matters MORE than retail — follow whales.
  • Taker buy/sell > 1.3 = aggressive buying momentum. < 0.7 = aggressive selling.
  • Negative funding = longs pay less (bullish). Very positive = crowded longs (bearish).
  • Funding rate TREND: going positive→negative = bearish sentiment shift.

STEP 6 — RISK MANAGEMENT:
  • SL MUST be at a logical level: below support for longs, above resistance for shorts.
  • Use pivot points, S/R levels, or Ichimoku cloud edges for SL placement.
  • TP at next resistance (longs) or support (shorts).
  • Risk:Reward MUST be > 1.5:1. If not achievable → NO_TRADE.
  • ATR > 2% on 5m = extreme volatility → widen SL or NO_TRADE.
  • Volume climax (>3x avg) signals exhaustion, not continuation → avoid entries.

═══ CRITICAL RULES ═══
1. NO_TRADE is the correct DEFAULT. Most cycles should be NO_TRADE. Protecting capital > chasing trades.
2. Confidence < 7 → always NO_TRADE. Mixed signals → NO_TRADE.
3. After a loss, do NOT re-enter same direction immediately. Wait for opposite setup or clear reversal.
4. RSI divergence at S/R is high probability. Bullish div near support = strong buy. Bearish div near resistance = strong sell.
5. High volume on breakout = real move. Low volume breakout = fakeout → NO_TRADE.
6. Candle patterns only matter at key S/R levels. Random patterns mid-range = noise.

═══ CONFIDENCE SCORING ═══
9-10: Everything aligned across all TFs, all indicators, strong momentum, contrarian sentiment. Very rare.
7-8: Strong setup. 3+ TFs aligned, most indicators agree, decent volume. Tradeable.
5-6: Marginal. Some alignment but mixed signals. → NO_TRADE.
1-4: Conflicting signals everywhere. → Definitely NO_TRADE.

═══ RESPONSE FORMAT ═══
Return ONLY valid JSON. No markdown fences. No explanation outside JSON.
{{"action":"BUY|SELL|NO_TRADE","confidence":1-10,"reasoning":"multi-factor reasoning referencing step numbers","market_condition":"brief market state","risk_warnings":"any concerns","entry_price":0.0,"stop_loss":0.0,"take_profit":0.0}}"""


def _build_position_system_prompt(position):
    """Shorter system prompt for position management. Less tokens = less cost."""
    elapsed = (int(time.time()) - position.get("entry_timestamp", int(time.time()))) // 60
    return f"""You manage a {position['direction']} position on BTCUSD @ ${position['entry_price']:,.2f}.
SL: ${position['stop_loss']:,.2f} | TP: ${position['take_profit']:,.2f} | Time: {elapsed}min | Entry conf: {position.get('confidence','?')}/10

ACTIONS: HOLD, TRAIL_SL, ADJUST_TP, EXIT, REVERSE
- HOLD: keep position unchanged
- TRAIL_SL: move SL to lock profit (include "new_sl")
- ADJUST_TP: move TP (include "new_tp")  
- EXIT: close now (momentum dying or thesis broken)
- REVERSE: close + open opposite (include "entry_price","stop_loss","take_profit" for new position)

GUIDELINES:
- Profit >0.5%: suggest TRAIL_SL to breakeven
- Profit >1%: trail to lock 50% gains
- MACD flipping + RSI diverging: EXIT before SL hit
- REVERSE only with 8+ confidence and clear 1h+ reversal
- Trade over {config.MAX_TRADE_DURATION_MINUTES}min: consider EXIT

Return ONLY valid JSON:
{{"action":"HOLD|TRAIL_SL|ADJUST_TP|EXIT|REVERSE","confidence":1-10,"reasoning":"why this action","market_condition":"brief","risk_warnings":"concerns","new_sl":0.0,"new_tp":0.0,"entry_price":0.0,"stop_loss":0.0,"take_profit":0.0}}"""


# =============================================================================
#  INDICATOR COMPUTATION (unchanged from v2)
# =============================================================================

def compute_all_indicators(all_data):
    """Compute ALL technical indicators across ALL timeframes."""
    result = {}

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

        rsi = indicators.calculate_rsi(close, config.RSI_PERIOD)
        result["rsi_5m"] = round(float(rsi.iloc[-1]), 2)

        macd = indicators.calculate_macd(close)
        result["macd"] = macd["macd"]
        result["macd_signal"] = macd["signal_line"]
        result["macd_histogram"] = macd["histogram"]
        result["macd_crossover"] = macd["crossover"]
        result["macd_hist_momentum"] = macd.get("hist_momentum")

        bb = indicators.calculate_bollinger_bands(close)
        result["bb_upper"] = bb["upper"]
        result["bb_middle"] = bb["middle"]
        result["bb_lower"] = bb["lower"]
        result["bb_bandwidth"] = bb["bandwidth_pct"]
        result["bb_position"] = bb["price_position"]
        result["bb_squeeze"] = bb["squeeze"]

        result["vwap_5m"] = indicators.calculate_vwap(candles_5m)

        stoch = indicators.calculate_stochastic_rsi(close)
        result["stoch_rsi_k"] = stoch["k"]
        result["stoch_rsi_d"] = stoch["d"]
        result["stoch_rsi_signal"] = stoch["signal"]

        adx = indicators.calculate_adx(candles_5m)
        result["adx"] = adx["adx"]
        result["adx_plus_di"] = adx["plus_di"]
        result["adx_minus_di"] = adx["minus_di"]
        result["adx_trend_strength"] = adx["trend_strength"]
        result["adx_di_signal"] = adx["di_signal"]

        obv = indicators.calculate_obv(candles_5m)
        result["obv_trend"] = obv["obv_trend"]

        if len(candles_5m) > 55:
            ichi = indicators.calculate_ichimoku(candles_5m)
            result["ichimoku_cloud_color"] = ichi["cloud_color"]
            result["ichimoku_price_vs_cloud"] = ichi["price_vs_cloud"]
            result["ichimoku_tk_cross"] = ichi["tk_cross"]

        candles_1h = all_data.get("delta_candles_1h")
        if candles_1h is not None and len(candles_1h) > 5:
            pivots = indicators.calculate_pivot_points(candles_1h)
            result["pivot"] = pivots["pivot"]
            result["pivot_r1"] = pivots["r1"]
            result["pivot_r2"] = pivots["r2"]
            result["pivot_s1"] = pivots["s1"]
            result["pivot_s2"] = pivots["s2"]

        div = indicators.detect_rsi_divergence(candles_5m)
        result["rsi_divergence"] = div["divergence"]
        result["rsi_div_strength"] = div["strength"]

        vol = indicators.analyze_volume(candles_5m)
        result["relative_volume"] = vol["relative_volume"]
        result["volume_trend"] = vol["volume_trend"]
        result["volume_climax"] = vol["climax"]

        patterns = indicators.detect_candle_patterns(candles_5m)
        result["candle_patterns"] = patterns["patterns"]
        result["candle_bias"] = patterns["bias"]

        sr = indicators.find_support_resistance(candles_5m)
        result["support_levels"] = sr["support"]
        result["resistance_levels"] = sr["resistance"]

    # 15m
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

    # 1h
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
        if len(candles_1h) > 55:
            ichi_1h = indicators.calculate_ichimoku(candles_1h)
            result["ichimoku_1h_cloud"] = ichi_1h["cloud_color"]
            result["ichimoku_1h_price_vs_cloud"] = ichi_1h["price_vs_cloud"]
        sr_1h = indicators.find_support_resistance(candles_1h, lookback=80)
        result["support_1h"] = sr_1h["support"]
        result["resistance_1h"] = sr_1h["resistance"]
        div_1h = indicators.detect_rsi_divergence(candles_1h)
        result["rsi_divergence_1h"] = div_1h["divergence"]

    # 4h
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


# =============================================================================
#  MARKET DATA PROMPT — No raw candles, just computed values
# =============================================================================

def _build_market_data_prompt(all_data, computed, bot_state=None):
    """Build concise market data prompt — no raw candle data."""
    now_ist = datetime.now(IST)
    parts = []

    parts.append(f"=== BTC/USD — {now_ist.strftime('%d %b %I:%M %p IST')} ===")

    ticker = all_data.get("delta_ticker")
    binance_price = all_data.get("binance_price")

    if ticker:
        mp = ticker["mark_price"]
        parts.append(f"Price: ${mp:,.2f} | 24h H:${ticker['high']:,.2f} L:${ticker['low']:,.2f} | Vol:{ticker['volume']:,.0f}")
        parts.append(f"Funding:{ticker['funding_rate']:.6f} | OI:{ticker['open_interest']:,.0f}")
        if binance_price:
            spread = mp - binance_price
            parts.append(f"Binance:${binance_price:,.2f} | Spread:${spread:+,.2f}")

    # 5m indicators (compact format)
    parts.append(f"\n5M: EMA9=${computed.get('ema9',0):,.0f} EMA21=${computed.get('ema21',0):,.0f} Cross:{computed.get('ema_crossover') or '-'}")
    parts.append(f"RSI:{computed.get('rsi_5m',50):.0f} StochK:{computed.get('stoch_rsi_k',50):.0f} D:{computed.get('stoch_rsi_d',50):.0f} Sig:{computed.get('stoch_rsi_signal') or '-'}")
    parts.append(f"MACD:{computed.get('macd',0):.1f}(h:{computed.get('macd_histogram',0):.1f}) Cross:{computed.get('macd_crossover') or '-'} Mom:{computed.get('macd_hist_momentum') or '-'}")
    parts.append(f"BB: U${computed.get('bb_upper',0):,.0f} M${computed.get('bb_middle',0):,.0f} L${computed.get('bb_lower',0):,.0f} Pos:{computed.get('bb_position',0.5):.2f} Squeeze:{computed.get('bb_squeeze',False)}")
    parts.append(f"ADX:{computed.get('adx',0):.0f}({computed.get('adx_trend_strength','?')}) +DI:{computed.get('adx_plus_di',0):.0f} -DI:{computed.get('adx_minus_di',0):.0f}")
    parts.append(f"OBV:{computed.get('obv_trend','?')} | VWAP:${computed.get('vwap_5m',0):,.0f} | ATR:${computed.get('atr',0):,.0f}({computed.get('atr_pct',0):.3f}%)")

    if computed.get("ichimoku_cloud_color"):
        parts.append(f"Ichi: Cloud={computed['ichimoku_cloud_color']} Price:{computed.get('ichimoku_price_vs_cloud','?')} TK:{computed.get('ichimoku_tk_cross') or '-'}")

    if computed.get("rsi_divergence"):
        parts.append(f"RSI Div: {computed['rsi_divergence']} (str:{computed.get('rsi_div_strength',0)})")

    parts.append(f"Vol: {computed.get('relative_volume',1.0):.1f}x avg, {computed.get('volume_trend','?')}, Climax:{computed.get('volume_climax',False)}")

    if computed.get("candle_patterns"):
        parts.append(f"Candles: {','.join(computed['candle_patterns'])} Bias:{computed.get('candle_bias','neutral')}")

    if computed.get("pivot"):
        parts.append(f"Pivots: P${computed['pivot']:,.0f} R1${computed.get('pivot_r1',0):,.0f} R2${computed.get('pivot_r2',0):,.0f} S1${computed.get('pivot_s1',0):,.0f} S2${computed.get('pivot_s2',0):,.0f}")

    if computed.get("support_levels"):
        parts.append(f"S/R 5m: S={[f'${s:,.0f}' for s in computed['support_levels']]} R={[f'${r:,.0f}' for r in computed.get('resistance_levels',[])]}")

    # Higher TFs (compact)
    parts.append(f"\n15M: {computed.get('htf_15m_trend','?')} RSI:{computed.get('rsi_15m','?')} MACD:{computed.get('macd_15m_crossover') or '-'} ADX:{computed.get('adx_15m','?')}")
    parts.append(f"1H: {computed.get('htf_1h_trend','?')} RSI:{computed.get('rsi_1h','?')} MACD:{computed.get('macd_1h_crossover') or '-'}")
    if computed.get("ichimoku_1h_cloud"):
        parts.append(f"1H Ichi: {computed['ichimoku_1h_cloud']} {computed.get('ichimoku_1h_price_vs_cloud','?')}")
    if computed.get("rsi_divergence_1h"):
        parts.append(f"1H Div: {computed['rsi_divergence_1h']}")
    parts.append(f"4H: {computed.get('htf_4h_trend','?')} RSI:{computed.get('rsi_4h','?')} MACD:{computed.get('macd_4h_crossover') or '-'} ADX:{computed.get('adx_4h','?')}({computed.get('adx_4h_trend','?')}) DI:{computed.get('adx_4h_di_signal','?')}")

    if computed.get("support_1h"):
        parts.append(f"1H S/R: S={[f'${s:,.0f}' for s in computed['support_1h']]} R={[f'${r:,.0f}' for r in computed.get('resistance_1h',[])]}")

    # Binance futures (compact)
    bf = all_data.get("binance_futures") or {}
    ls = bf.get("long_short_ratio")
    tp = bf.get("top_trader_positions")
    tbs = bf.get("taker_buy_sell")
    fh = bf.get("funding_history")

    parts.append(f"\nFUTURES:")
    if ls: parts.append(f"Retail L/S:{ls['long_short_ratio']:.2f} (L:{ls['long_account_pct']:.0f}%)")
    if tp: parts.append(f"Whales L/S:{tp['long_short_ratio']:.2f} (L:{tp['long_pct']:.0f}%)")
    if tbs: parts.append(f"Taker B/S:{tbs['buy_sell_ratio']:.2f}")
    if fh: parts.append(f"Funding: {fh['current_rate']:.6f} avg:{fh['avg_rate']:.6f} trend:{fh['trend']}")

    # Orderbook imbalance
    ob = all_data.get("delta_orderbook")
    if ob:
        bid_vol = sum(float(b.get("size", 0)) for b in ob.get("buy", []))
        ask_vol = sum(float(a.get("size", 0)) for a in ob.get("sell", []))
        total = bid_vol + ask_vol
        imbalance = (bid_vol - ask_vol) / total * 100 if total > 0 else 0
        parts.append(f"OB Imbalance: {imbalance:+.0f}%")

    # Trade tape
    trades = all_data.get("delta_trades")
    if trades:
        parts.append(f"Tape: Buy:{trades['buy_pct']:.0f}% Aggr:{trades['aggression']:+.2f}")

    # Sentiment
    fg = all_data.get("fear_greed")
    cg = all_data.get("coingecko")
    if fg: parts.append(f"\nF&G: {fg['value']}({fg['classification']}) trend:{fg.get('trend','?')}")
    if cg: parts.append(f"BTC Dom:{cg['btc_dominance']:.1f}%")

    # Signal history (from persistent state)
    if bot_state:
        recent = bot_state.get_recent_signals(7)
        if recent:
            parts.append(f"\nYOUR RECENT SIGNALS:")
            for sig in reversed(recent):
                parts.append(f"  {sig['time']} {sig['decision']} conf:{sig['confidence']} → {sig.get('outcome','pending')}")

        # Loss warning
        if bot_state.last_trade_was_loss and bot_state.last_trade_direction:
            parts.append(f"\n⚠ LAST {bot_state.last_trade_direction} WAS LOSS. Do NOT re-enter same direction.")

        # Daily P&L context
        stats = bot_state.get_daily_stats()
        if stats["trades_count"] > 0:
            parts.append(f"\nToday: ${stats['total_pnl_usd']:+,.2f} ({stats['trades_count']}T W:{stats['wins']} L:{stats['losses']})")
            if stats["losses"] > stats["wins"]:
                parts.append("⚠ LOSING DAY — be conservative.")
            if stats["losses"] >= 3:
                parts.append("🛑 3+ LOSSES — strongly prefer NO_TRADE.")

    return "\n".join(parts)


# =============================================================================
#  MAIN ANALYSIS FUNCTION
# =============================================================================

def analyze_with_claude(all_data, current_position=None, bot_state=None):
    """Compute indicators → build prompt → ask Claude."""
    computed = compute_all_indicators(all_data)

    if current_position:
        system_prompt = _build_position_system_prompt(current_position)
    else:
        system_prompt = _build_entry_system_prompt()

    market_prompt = _build_market_data_prompt(all_data, computed, bot_state)

    if current_position:
        ticker = all_data.get("delta_ticker")
        current_price = ticker["mark_price"] if ticker else 0
        if current_price > 0:
            entry = current_position["entry_price"]
            direction = current_position["direction"]
            pnl = ((current_price - entry) / entry * 100) if direction == "LONG" else ((entry - current_price) / entry * 100)
            market_prompt += f"\n\nPOSITION: {direction} @ ${entry:,.2f} | Now: ${current_price:,.2f} | P&L: {pnl:+.3f}%"
        market_prompt += "\nAction? (HOLD/TRAIL_SL/ADJUST_TP/EXIT/REVERSE)"
    else:
        market_prompt += "\n\nFLAT. Action? (BUY/SELL/NO_TRADE)"

    market_prompt += "\nRespond ONLY JSON."

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

        action = (analysis.get("action") or analysis.get("decision") or "").upper().strip()
        analysis["action"] = action

        if current_position:
            valid = ["HOLD", "TRAIL_SL", "ADJUST_TP", "EXIT", "REVERSE"]
        else:
            valid = ["BUY", "SELL", "NO_TRADE"]

        if action not in valid:
            analysis["action"] = "HOLD" if current_position else "NO_TRADE"

        analysis["confidence"] = max(1, min(10, int(analysis.get("confidence", 5))))
        analysis["timestamp"] = int(time.time())
        analysis["time"] = datetime.now(IST).strftime("%I:%M %p IST")
        analysis["raw_response"] = raw_response
        analysis["indicators"] = computed

        return analysis

    except json.JSONDecodeError as e:
        print(f"  [ERROR] JSON parse: {e}")
        print(f"  Raw: {raw_response[:500]}")
        return None
    except Exception as e:
        print(f"  [ERROR] Parse: {e}")
        return None
