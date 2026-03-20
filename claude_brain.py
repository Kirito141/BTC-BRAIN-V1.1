"""
=============================================================================
 CLAUDE_BRAIN.PY — AI-Powered Trade Analysis via Claude API
=============================================================================
 The brain of the bot. Gathers ALL available market data, computes every
 indicator, and sends a comprehensive snapshot to Claude for analysis.
 
 Data sent to Claude:
   • Price data (Delta mark + Binance spot + spread)
   • Technical indicators (EMA 9/21, RSI, ATR, MACD, Bollinger Bands, VWAP)
   • Multi-timeframe context (3m, 5m, 15m, 1h candles + EMAs)
   • Market microstructure (orderbook depth, bid/ask imbalance, spread)
   • Binance Futures Intelligence:
       - Global long/short ratio (retail sentiment)
       - Top trader positions (whale sentiment)
       - Taker buy/sell volume (aggressive flow)
       - Open interest (position conviction)
   • Sentiment (Fear & Greed, BTC dominance, global volume)
   • Recent candle patterns (last 10 candles per timeframe)
   • Past signal history + trade outcomes for self-improvement
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

# ── Track context across cycles ─────────────────────────────────────────────
_recent_signals = []  # last 10 Claude signals
_trade_history = []   # trades the user actually took


def _call_claude_api(prompt, system_prompt):
    """Call the Anthropic Messages API. Returns response text or None."""
    if not config.ANTHROPIC_API_KEY:
        print("  [ERROR] ANTHROPIC_API_KEY not set in .env")
        return None

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": config.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": config.CLAUDE_MODEL,
        "max_tokens": 2048,
        "system": system_prompt,
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        if resp.status_code == 200:
            data = resp.json()
            text = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    text += block["text"]
            return text
        else:
            print(f"  [ERROR] Claude API {resp.status_code}: {resp.text[:300]}")
            return None
    except requests.exceptions.Timeout:
        print("  [ERROR] Claude API timed out (60s)")
        return None
    except Exception as e:
        print(f"  [ERROR] Claude API failed: {e}")
        return None


def _build_system_prompt(current_position=None):
    """System prompt defining Claude's role — changes based on whether a position is open."""

    start_h = config.TRADING_START_HOUR_IST
    end_h = config.TRADING_END_HOUR_IST
    if start_h == 0 and end_h == 24:
        hours_str = "24/7 (no restriction)"
    else:
        start_ampm = "PM" if start_h >= 12 else "AM"
        end_ampm = "PM" if end_h >= 12 else "AM"
        start_str = f"{start_h % 12 or 12}:00 {start_ampm}"
        end_str = f"{end_h % 12 or 12}:00 {end_ampm}"
        hours_str = f"{start_str} – {end_str} IST"

    # Position context
    if current_position:
        pos_dir = current_position["direction"]
        pos_entry = current_position["entry_price"]
        pos_sl = current_position["stop_loss"]
        pos_tp = current_position["take_profit"]
        position_block = f"""
CURRENT OPEN POSITION:
- Direction: {pos_dir}
- Entry: ${pos_entry:,.2f}
- Stop-Loss: ${pos_sl:,.2f}
- Take-Profit: ${pos_tp:,.2f}

You MUST manage this existing position. You CANNOT open a new trade.
Your options are:
  "HOLD" — keep position open, no changes needed
  "TRAIL_SL" — move SL to lock in profit or reduce risk (provide new_sl)
  "ADJUST_TP" — update TP target (provide new_tp)
  "EXIT" — close the position at current price
  "REVERSE" — close this position AND open the opposite direction

RESPONSE FORMAT for managing a position:
{{{{
    "action": "HOLD" | "TRAIL_SL" | "ADJUST_TP" | "EXIT" | "REVERSE",
    "confidence": <1-10>,
    "reasoning": "<2-3 sentence explanation>",
    "new_sl": <new SL price, only for TRAIL_SL>,
    "new_tp": <new TP price, only for ADJUST_TP>,
    "reverse_entry": <entry price for reverse trade, only for REVERSE>,
    "reverse_sl": <SL for reverse, only for REVERSE>,
    "reverse_tp": <TP for reverse, only for REVERSE>,
    "risk_warnings": "<specific risks>",
    "market_condition": "<1-line summary>"
}}}}"""
    else:
        position_block = f"""
CURRENT POSITION: FLAT (no open trade)

You can recommend:
  "BUY" — open a new LONG position
  "SELL" — open a new SHORT position
  "NO_TRADE" — stay flat, wait for better setup

RESPONSE FORMAT for new trade:
{{{{
    "action": "BUY" | "SELL" | "NO_TRADE",
    "confidence": <1-10>,
    "reasoning": "<2-3 sentence explanation>",
    "entry_price": <suggested entry>,
    "stop_loss": <suggested SL>,
    "take_profit": <suggested TP>,
    "risk_warnings": "<specific risks>",
    "market_condition": "<1-line summary>"
}}}}"""

    return f"""You are an expert BTC/USD perpetual futures scalping analyst for Delta Exchange India.

TRADING CONTEXT:
- Instrument: BTCUSD Inverse Perpetual on Delta Exchange India
- Timeframe: Scalping (3-5 minute candles, with 15m/1h for context)
- Leverage: {config.LEVERAGE}x
- Position size: {config.BALANCE_USAGE_PERCENT}% of balance per trade
- Trading hours: {hours_str}
- Risk management: ATR-based SL/TP with floors (SL min {config.SL_MIN_PERCENT}%, TP min {config.TP_MIN_PERCENT}%)
- RULE: Only 1 position at a time. No stacking trades.
- NOTE: Trading hours enforced by bot. Focus ONLY on market analysis.
{position_block}

═══ CRITICAL RULES (NEVER VIOLATE) ═══

1. HIGHER TIMEFRAME IS KING:
   - If 1h trend is BULLISH → only BUY. NEVER short against the 1h trend.
   - If 1h trend is BEARISH → only SELL. NEVER long against the 1h trend.
   - If 1h trend is NEUTRAL → either direction OK but need 7+ confidence.
   - The ONLY exception: if RSI 1h is extreme (>80 or <20), a counter-trend scalp is allowed at 8+ confidence.

2. MULTI-TIMEFRAME ALIGNMENT REQUIRED:
   - For BUY: need at least 2 of 3 bullish (5m, 15m, 1h).
   - For SELL: need at least 2 of 3 bearish (5m, 15m, 1h).
   - If timeframes conflict → NO_TRADE.

3. PREFER NO_TRADE OVER BAD TRADE:
   - If signals are mixed or unclear → NO_TRADE.
   - If confidence < 7 → NO_TRADE.
   - Losing money is worse than missing a trade.
   - NO_TRADE is the CORRECT decision most of the time.

4. NEVER RE-ENTER SAME DIRECTION AFTER A LOSS:
   - If the last trade was a losing SHORT → do NOT immediately SHORT again.
   - Wait for a clear reversal or go NO_TRADE.
   - Repeating the same losing trade is the #1 capital killer.

5. ORDERBOOK/TAPE IS NOISE — TREND IS SIGNAL:
   - Orderbook imbalance and trade tape change every second.
   - They are NOT reliable directional signals on their own.
   - Use them ONLY to confirm a trade that already aligns with the trend.
   - NEVER take a trade based primarily on orderbook or tape data.

═══ CONFIDENCE GUIDE ═══
- 9-10: Perfect alignment — all timeframes, all indicators, strong momentum
- 7-8: Good setup — trend aligned, most indicators agree
- 5-6: Marginal — mixed signals, use NO_TRADE instead
- 1-4: Bad setup — conflicting signals, definitely NO_TRADE

═══ SIGNAL PATTERNS ═══
- MACD crossover + RSI divergence = strong signal
- BB squeeze then expansion = breakout imminent
- Price near BB lower + RSI oversold + bullish MACD + 1h bullish = strong BUY
- Price near BB upper + RSI overbought + bearish MACD + 1h bearish = strong SELL
- Taker buy/sell > 1.2 = aggressive buying. < 0.8 = aggressive selling.
- 65%+ retail long = contrarian sell. 65%+ retail short = contrarian buy.
- Negative funding = bullish bias. Positive = bearish bias.
- Price above VWAP = bullish intraday. Below = bearish.
- ATR > 1.5% = too volatile, recommend NO_TRADE.

POSITION MANAGEMENT RULES:
- If in profit: consider TRAIL_SL to lock gains. Move SL to breakeven or better.
- If momentum reversing against position: EXIT early, don\\'t wait for SL hit.
- If strong reversal signal: REVERSE (close + open opposite direction).
- HOLD if market is choppy/unclear — don\\'t exit on noise.
- Only EXIT or REVERSE with confidence 7+.

RISK RULES:
- Be CONSERVATIVE. Protect capital above all.
- SL must be at least {config.SL_MIN_PERCENT}% from entry, TP at least {config.TP_MIN_PERCENT}%.
- NO_TRADE / HOLD is the DEFAULT. Only trade when you have HIGH confidence.
- When trailing SL, never move SL further from price (only tighter).

Return ONLY the JSON object. No markdown, no code fences, no extra text."""


def _build_market_data_prompt(all_data, computed):
    """Build comprehensive market data prompt with ALL available data."""
    now_ist = datetime.now(IST)
    parts = []

    parts.append(f"=== BTC/USD COMPREHENSIVE MARKET SNAPSHOT ===")
    parts.append(f"Time: {now_ist.strftime('%d %b %Y, %I:%M:%S %p IST')}")
    parts.append("")

    # ── Price Data ──────────────────────────────────────────────────────────
    ticker = all_data.get("delta_ticker")
    binance_price = all_data.get("binance_price")

    parts.append("── PRICE DATA ──")
    if ticker:
        parts.append(f"Delta Mark:        ${ticker['mark_price']:,.2f}")
        parts.append(f"Delta 24h High:    ${ticker['high']:,.2f}")
        parts.append(f"Delta 24h Low:     ${ticker['low']:,.2f}")
        parts.append(f"Delta 24h Open:    ${ticker['open']:,.2f}")
        parts.append(f"Delta 24h Volume:  {ticker['volume']:,.0f}")
        parts.append(f"Funding Rate:      {ticker['funding_rate']:.6f}")
        parts.append(f"Open Interest:     {ticker['open_interest']:,.0f}")
    if binance_price:
        parts.append(f"Binance Spot:      ${binance_price:,.2f}")
    if ticker and binance_price:
        spread = ticker['mark_price'] - binance_price
        parts.append(f"Delta-Binance Gap: ${spread:+,.2f} ({spread/binance_price*100:+.4f}%)")
    parts.append("")

    # ── Scalping Indicators (5m) ────────────────────────────────────────────
    parts.append("── SCALPING INDICATORS (5-min) ──")
    parts.append(f"EMA 9:             ${computed['ema9']:,.2f}")
    parts.append(f"EMA 21:            ${computed['ema21']:,.2f}")
    parts.append(f"EMA Spread:        {computed['ema_spread_pct']:.4f}%")
    parts.append(f"EMA Direction:     {'Bullish (9>21)' if computed['ema9'] > computed['ema21'] else 'Bearish (9<21)'}")
    parts.append(f"EMA Crossover:     {computed.get('ema_crossover') or 'None'}")
    parts.append(f"MACD:              {computed.get('macd', 0):.2f} (signal: {computed.get('macd_signal', 0):.2f}, hist: {computed.get('macd_histogram', 0):.2f})")
    parts.append(f"MACD Crossover:    {computed.get('macd_crossover') or 'None'}")
    parts.append(f"BB Upper:          ${computed.get('bb_upper', 0):,.2f}")
    parts.append(f"BB Middle:         ${computed.get('bb_middle', 0):,.2f}")
    parts.append(f"BB Lower:          ${computed.get('bb_lower', 0):,.2f}")
    parts.append(f"BB Bandwidth:      {computed.get('bb_bandwidth', 0):.4f}% ({'squeeze' if computed.get('bb_bandwidth', 99) < 2.0 else 'normal' if computed.get('bb_bandwidth', 0) < 5.0 else 'wide'})")
    parts.append(f"BB Price Position: {computed.get('bb_position', 0.5):.3f} (0=lower band, 1=upper band)")
    parts.append(f"VWAP (5m):         ${computed.get('vwap_5m', 0):,.2f}")
    parts.append(f"ATR (14):          ${computed['atr']:,.2f} ({computed['atr_pct']:.4f}%)")
    parts.append(f"Market Regime:     {computed['regime']} — {computed['regime_reason']}")
    parts.append("")

    # ── RSI (3m) ────────────────────────────────────────────────────────────
    parts.append("── RSI (3-min candles) ──")
    rsi_val = computed['rsi']
    rsi_status = "OVERSOLD (<30)" if rsi_val < 30 else "OVERBOUGHT (>70)" if rsi_val > 70 else "Neutral"
    parts.append(f"RSI (14):          {rsi_val:.2f} — {rsi_status}")
    parts.append(f"RSI Signal:        {computed.get('rsi_signal') or 'None'}")
    parts.append("")

    # ── Higher Timeframe Context ────────────────────────────────────────────
    parts.append("── HIGHER TIMEFRAME TREND ──")
    parts.append(f"15m EMA50:         ${computed.get('htf_15m_ema50', 0):,.2f}")
    parts.append(f"15m Trend:         {computed.get('htf_15m_trend', 'unknown')}")
    parts.append(f"1h EMA50:          ${computed.get('htf_1h_ema50', 0):,.2f}")
    parts.append(f"1h EMA200:         ${computed.get('htf_1h_ema200', 0):,.2f}")
    parts.append(f"1h Trend:          {computed.get('htf_1h_trend', 'unknown')}")
    parts.append(f"1h RSI:            {computed.get('rsi_1h', 50):.1f}")
    parts.append("")

    # ── Binance Futures Intelligence ────────────────────────────────────────
    bf = all_data.get("binance_futures") or {}
    parts.append("── BINANCE FUTURES INTELLIGENCE ──")

    ls = bf.get("long_short_ratio")
    if ls:
        parts.append(f"Global L/S Ratio:  {ls['long_short_ratio']:.4f}")
        parts.append(f"Long Accounts:     {ls['long_account_pct']:.1f}%")
        parts.append(f"Short Accounts:    {ls['short_account_pct']:.1f}%")
        crowd = "RETAIL HEAVILY LONG" if ls['long_account_pct'] > 65 else "RETAIL HEAVILY SHORT" if ls['short_account_pct'] > 65 else "balanced"
        parts.append(f"Retail Sentiment:  {crowd}")
    else:
        parts.append(f"Global L/S Ratio:  Unavailable")

    tt = bf.get("top_trader_positions")
    if tt:
        parts.append(f"Top Trader L/S:    {tt['long_short_ratio']:.4f}")
        parts.append(f"Top Trader Long:   {tt['long_pct']:.1f}%")
        parts.append(f"Top Trader Short:  {tt['short_pct']:.1f}%")
        whale_dir = "WHALES LONG" if tt['long_pct'] > 60 else "WHALES SHORT" if tt['short_pct'] > 60 else "whales balanced"
        parts.append(f"Whale Sentiment:   {whale_dir}")
    else:
        parts.append(f"Top Trader L/S:    Unavailable")

    tbs = bf.get("taker_buy_sell")
    if tbs:
        parts.append(f"Taker Buy/Sell:    {tbs['buy_sell_ratio']:.4f}")
        flow = "AGGRESSIVE BUYING" if tbs['buy_sell_ratio'] > 1.15 else "AGGRESSIVE SELLING" if tbs['buy_sell_ratio'] < 0.85 else "balanced flow"
        parts.append(f"Order Flow:        {flow}")
        parts.append(f"Buy Volume:        {tbs['buy_volume']:,.0f}")
        parts.append(f"Sell Volume:       {tbs['sell_volume']:,.0f}")
    else:
        parts.append(f"Taker Buy/Sell:    Unavailable")

    boi = bf.get("open_interest")
    if boi:
        parts.append(f"Binance BTC OI:    {boi['open_interest']:,.2f} BTC")

    parts.append("")

    # ── Orderbook Microstructure ────────────────────────────────────────────
    orderbook = all_data.get("delta_orderbook")
    if orderbook:
        parts.append("── ORDERBOOK (L2, top 20) ──")
        bid_vol = sum(float(b.get("size", 0)) for b in orderbook.get("buy", []))
        ask_vol = sum(float(a.get("size", 0)) for a in orderbook.get("sell", []))
        total = bid_vol + ask_vol
        imbalance = (bid_vol - ask_vol) / total * 100 if total > 0 else 0
        parts.append(f"Bid Volume:        {bid_vol:,.0f}")
        parts.append(f"Ask Volume:        {ask_vol:,.0f}")
        parts.append(f"Imbalance:         {imbalance:+.1f}% ({'BIDS dominate' if imbalance > 10 else 'ASKS dominate' if imbalance < -10 else 'balanced'})")

        bids = orderbook.get("buy", [])
        asks = orderbook.get("sell", [])
        if bids and asks:
            best_bid = float(bids[0].get("price", 0))
            best_ask = float(asks[0].get("price", 0))
            if best_bid > 0 and best_ask > 0:
                parts.append(f"Best Bid:          ${best_bid:,.2f} (size: {bids[0].get('size', 0)})")
                parts.append(f"Best Ask:          ${best_ask:,.2f} (size: {asks[0].get('size', 0)})")
                parts.append(f"Spread:            ${best_ask - best_bid:,.2f}")
        parts.append("")

    # ── Delta Recent Trade Flow (tape reading) ──────────────────────────────
    trades = all_data.get("delta_trades")
    if trades:
        parts.append("── DELTA TRADE FLOW (recent executed trades) ──")
        parts.append(f"Total Trades:      {trades['total_trades']}")
        parts.append(f"Buy Trades:        {trades['buy_count']} ({trades['buy_pct']:.1f}%)")
        parts.append(f"Sell Trades:       {trades['sell_count']} ({trades['sell_pct']:.1f}%)")
        parts.append(f"Buy Volume:        {trades['buy_volume']:,.0f}")
        parts.append(f"Sell Volume:       {trades['sell_volume']:,.0f}")
        parts.append(f"Volume Imbalance:  {trades['volume_imbalance_pct']:+.1f}%")
        parts.append(f"Avg Trade Size:    {trades['avg_trade_size']:,.2f}")

        aggression = "BUYERS aggressive" if trades['buy_pct'] > 60 else "SELLERS aggressive" if trades['sell_pct'] > 60 else "balanced"
        parts.append(f"Tape Reading:      {aggression}")

        if trades.get("large_trades"):
            parts.append(f"Large Trades (>2x avg):")
            for lt in trades["large_trades"][:3]:
                parts.append(f"  → {lt['side']} {lt['size']:,.0f} @ ${lt['price']:,.2f}")
        parts.append("")

    # ── Price Bands (exchange limits) ───────────────────────────────────────
    if ticker:
        upper = ticker.get("price_band_upper", 0)
        lower = ticker.get("price_band_lower", 0)
        spot = ticker.get("spot_price", 0)
        if upper > 0 and lower > 0:
            parts.append("── EXCHANGE PRICE BANDS ──")
            parts.append(f"Upper Limit:       ${upper:,.2f}")
            parts.append(f"Lower Limit:       ${lower:,.2f}")
            if spot > 0:
                parts.append(f"Spot/Index Price:  ${spot:,.2f}")
            parts.append(f"Band Width:        ${upper - lower:,.2f} ({(upper - lower) / ticker['mark_price'] * 100:.2f}%)")
            parts.append("")

    # ── Sentiment ───────────────────────────────────────────────────────────
    fg = all_data.get("fear_greed")
    cg = all_data.get("coingecko")
    parts.append("── SENTIMENT & MACRO ──")
    if fg:
        parts.append(f"Fear & Greed:      {fg['value']} — {fg['classification']}")
    if cg:
        parts.append(f"BTC Dominance:     {cg['btc_dominance']:.2f}%")
        parts.append(f"Global 24h Vol:    ${cg['total_volume_usd'] / 1e9:,.1f}B")
    parts.append("")

    # ── Recent 5m Candles (last 10) ─────────────────────────────────────────
    candles_5m = all_data.get("delta_candles_5m")
    if candles_5m is not None and len(candles_5m) >= 10:
        parts.append("── RECENT 5-MIN CANDLES (last 10, newest first) ──")
        last_10 = candles_5m.tail(10).iloc[::-1]
        for i, (_, row) in enumerate(last_10.iterrows(), 1):
            o, h, l, c = row["open"], row["high"], row["low"], row["close"]
            v = row.get("volume", 0)
            ct = "GREEN" if c >= o else "RED"
            parts.append(f"  {i:>2}. O:${o:,.1f} H:${h:,.1f} L:${l:,.1f} C:${c:,.1f} V:{v:,.0f} [{ct}]")
        parts.append("")

    # ── Position Sizing ─────────────────────────────────────────────────────
    if ticker:
        pos = indicators.calculate_position_size(ticker['mark_price'])
        parts.append("── POSITION SIZING ──")
        parts.append(f"Balance: ${config.DEFAULT_BALANCE_USDT} ({config.BALANCE_USAGE_PERCENT}% used) | Leverage: {config.LEVERAGE}x | Contracts: {pos['contracts']} lots")
        parts.append("")

    # ── Past Signal Performance ─────────────────────────────────────────────
    if _recent_signals:
        parts.append("── YOUR RECENT SIGNALS (newest first) ──")
        for sig in reversed(_recent_signals[-5:]):
            outcome = sig.get('outcome', 'pending')
            parts.append(f"  {sig['time']} {sig['decision']} conf:{sig['confidence']}/10 → {outcome}")
        parts.append("")

    if _trade_history:
        parts.append("── TRADES OPERATOR TOOK (newest first) ──")
        for trade in reversed(_trade_history[-5:]):
            parts.append(f"  {trade['time']} {trade['direction']} @${trade['entry_price']:,.2f}")
        parts.append("")

    parts.append("=== END OF DATA ===")
    parts.append("Based on ALL above, should I BUY, SELL, or NO_TRADE? JSON only.")

    return "\n".join(parts)


def compute_all_indicators(all_data):
    """Compute ALL technical indicators from raw candle data."""
    result = {
        "ema9": 0, "ema21": 0, "ema_spread_pct": 0, "ema_crossover": None,
        "rsi": 50, "rsi_signal": None,
        "atr": 0, "atr_pct": 0,
        "regime": "unknown", "regime_reason": "No data",
        "macd": 0, "macd_signal": 0, "macd_histogram": 0, "macd_crossover": None,
        "bb_upper": 0, "bb_middle": 0, "bb_lower": 0, "bb_bandwidth": 0, "bb_position": 0.5,
        "vwap_5m": 0,
        "htf_15m_ema50": 0, "htf_15m_trend": "unknown",
        "htf_1h_ema50": 0, "htf_1h_ema200": 0, "htf_1h_trend": "unknown",
        "rsi_1h": 50,
    }

    candles_5m = all_data.get("delta_candles_5m")
    candles_3m = all_data.get("delta_candles_3m")
    candles_15m = all_data.get("delta_candles_15m")
    candles_1h = all_data.get("delta_candles_1h")

    # ── 5m indicators ───────────────────────────────────────────────────────
    if candles_5m is not None and len(candles_5m) > 25:
        close = candles_5m["close"]
        price = close.iloc[-1]

        ema9 = indicators.calculate_ema(close, 9)
        ema21 = indicators.calculate_ema(close, 21)
        result["ema9"] = round(float(ema9.iloc[-1]), 2)
        result["ema21"] = round(float(ema21.iloc[-1]), 2)
        result["ema_spread_pct"] = round(abs(result["ema9"] - result["ema21"]) / price * 100, 4) if price > 0 else 0

        ema_result = indicators.detect_ema_crossover(candles_5m)
        result["ema_crossover"] = ema_result["signal"]

        atr = indicators.get_current_atr(candles_5m)
        result["atr"] = atr
        result["atr_pct"] = round(atr / price * 100, 4) if price > 0 else 0

        regime = indicators.detect_regime(candles_5m)
        result["regime"] = regime["regime"]
        result["regime_reason"] = regime["reason"]

        # MACD
        macd = indicators.calculate_macd(close)
        result["macd"] = macd["macd"]
        result["macd_signal"] = macd["signal_line"]
        result["macd_histogram"] = macd["histogram"]
        result["macd_crossover"] = macd["crossover"]

        # Bollinger Bands
        bb = indicators.calculate_bollinger_bands(close)
        result["bb_upper"] = bb["upper"]
        result["bb_middle"] = bb["middle"]
        result["bb_lower"] = bb["lower"]
        result["bb_bandwidth"] = bb["bandwidth_pct"]
        result["bb_position"] = bb["price_position"]

        # VWAP
        result["vwap_5m"] = indicators.calculate_vwap(candles_5m)

    # ── 3m RSI ──────────────────────────────────────────────────────────────
    if candles_3m is not None and len(candles_3m) > 20:
        rsi = indicators.calculate_rsi(candles_3m["close"], config.RSI_PERIOD)
        result["rsi"] = round(float(rsi.iloc[-1]), 2)
        rsi_result = indicators.detect_rsi_signal(candles_3m)
        result["rsi_signal"] = rsi_result["signal"]

    # ── 15m higher timeframe ────────────────────────────────────────────────
    if candles_15m is not None and len(candles_15m) > 10:
        htf_15m = indicators.calculate_higher_tf_emas(candles_15m)
        result["htf_15m_ema50"] = htf_15m["ema50"]
        result["htf_15m_trend"] = htf_15m["trend"]

    # ── 1h higher timeframe ─────────────────────────────────────────────────
    if candles_1h is not None and len(candles_1h) > 10:
        htf_1h = indicators.calculate_higher_tf_emas(candles_1h)
        result["htf_1h_ema50"] = htf_1h["ema50"]
        result["htf_1h_ema200"] = htf_1h["ema200"]
        result["htf_1h_trend"] = htf_1h["trend"]

        # 1h RSI
        if len(candles_1h) > 16:
            rsi_1h = indicators.calculate_rsi(candles_1h["close"], 14)
            result["rsi_1h"] = round(float(rsi_1h.iloc[-1]), 1)

    return result


def analyze_with_claude(all_data, current_position=None):
    """
    Main function: gather all data, compute indicators, ask Claude.
    Position-aware: changes prompt based on whether a trade is open.
    
    Args:
        all_data: dict from data_fetcher
        current_position: dict from position_manager, or None if flat
    
    Returns:
        dict with Claude's analysis, or None on failure.
        Contains "action" field: BUY/SELL/NO_TRADE/HOLD/EXIT/REVERSE/TRAIL_SL/ADJUST_TP
    """
    computed = compute_all_indicators(all_data)
    system_prompt = _build_system_prompt(current_position)
    market_prompt = _build_market_data_prompt(all_data, computed)

    # Add position P&L context to the prompt if in a trade
    if current_position:
        import position_manager
        ticker = all_data.get("delta_ticker")
        current_price = ticker["mark_price"] if ticker else 0
        pos_summary = position_manager.get_position_summary(current_price)
        market_prompt += f"\n\nCURRENT POSITION STATUS: {pos_summary}"
        market_prompt += f"\nShould I HOLD, TRAIL_SL, ADJUST_TP, EXIT, or REVERSE?"
    else:
        market_prompt += f"\n\nI am FLAT (no open position). Should I BUY, SELL, or NO_TRADE?"

    # Add daily P&L and last trade result to prevent repeat losses
    try:
        import pnl_tracker
        daily = pnl_tracker.get_daily_pnl()
        if daily["trades_count"] > 0:
            market_prompt += f"\n\nDAILY P&L: ${daily['total_pnl_usd']:+,.2f} ({daily['trades_count']} trades, W:{daily['wins']} L:{daily['losses']})"
            if daily["losses"] > daily["wins"]:
                market_prompt += f"\n⚠ LOSING DAY — be extra conservative. Prefer NO_TRADE."
    except Exception:
        pass

    # Add last trade result
    if _recent_signals:
        last = _recent_signals[-1]
        last_dir = last.get("decision", "")
        last_outcome = last.get("outcome", "")
        if last_dir in ["BUY", "SELL"] and last_outcome in ["sl_hit", "loss", "pending"]:
            market_prompt += f"\n⚠ LAST TRADE: {last_dir} was a LOSS. Do NOT immediately re-enter {last_dir}."

    market_prompt += "\nRespond ONLY with the JSON object."

    print("  🧠 Sending market data to Claude for analysis...")
    raw_response = _call_claude_api(market_prompt, system_prompt)

    if raw_response is None:
        return None

    try:
        cleaned = raw_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()

        analysis = json.loads(cleaned)

        # Normalize action field (Claude may return "action" or "decision")
        action = analysis.get("action") or analysis.get("decision") or ""
        action = action.upper().strip()
        analysis["action"] = action

        # Validate action based on position state
        if current_position:
            valid_actions = ["HOLD", "TRAIL_SL", "ADJUST_TP", "EXIT", "REVERSE"]
        else:
            valid_actions = ["BUY", "SELL", "NO_TRADE"]

        if action not in valid_actions:
            print(f"  [WARN] Invalid action '{action}' for state {'in_position' if current_position else 'flat'}. Defaulting to {'HOLD' if current_position else 'NO_TRADE'}.")
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
        if len(_recent_signals) > 10:
            _recent_signals.pop(0)

        return analysis

    except json.JSONDecodeError as e:
        print(f"  [ERROR] JSON parse failed: {e}")
        print(f"  Raw: {raw_response[:500]}")
        return None
    except Exception as e:
        print(f"  [ERROR] Parse error: {e}")
        return None


def record_trade_taken(signal, entry_price=None):
    """Record that the operator took a trade."""
    trade = {
        "time": signal.get("time", ""),
        "direction": signal.get("action") or signal.get("decision", ""),
        "entry_price": entry_price or signal.get("entry_price", 0),
        "stop_loss": signal.get("stop_loss", 0),
        "take_profit": signal.get("take_profit", 0),
        "confidence": signal.get("confidence", 0),
    }
    _trade_history.append(trade)
    if len(_trade_history) > 20:
        _trade_history.pop(0)


def mark_last_signal_loss(direction):
    """Mark the last signal of given direction as a loss so Claude avoids repeating it."""
    for sig in reversed(_recent_signals):
        if sig.get("decision") == direction:
            sig["outcome"] = "loss"
            break


def update_signal_outcome(index, outcome):
    """Update outcome of a past signal (e.g., 'hit_tp', 'hit_sl', 'manual_close')."""
    if 0 <= index < len(_recent_signals):
        _recent_signals[index]["outcome"] = outcome
