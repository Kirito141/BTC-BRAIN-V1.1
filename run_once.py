"""
=============================================================================
 RUN_ONCE.PY — Single Cycle Runner (for testing/debugging)
=============================================================================
 Runs exactly ONE cycle of the bot and exits.
 
 Usage:
   python3 run_once.py              # run one cycle with Claude analysis
   python3 run_once.py --verbose    # show raw indicator values + Claude prompt
   python3 run_once.py --data-only  # just fetch data + indicators, skip Claude
=============================================================================
"""

import sys
import json
import argparse
from datetime import datetime, timezone, timedelta

import config
import data_fetcher
import indicators
import claude_brain
import trade_tracker
import alerts

IST = timezone(timedelta(hours=5, minutes=30))


def run_single_cycle(verbose=False, data_only=False):
    """Run one complete bot cycle with detailed output."""

    now = datetime.now(IST).strftime("%I:%M:%S %p IST")
    print(f"\n{'='*60}")
    print(f"  🔬 SINGLE CYCLE TEST — {now}")
    print(f"{'='*60}")

    # ── Step 1: Fetch data ──────────────────────────────────────────────────
    print("\n📡 FETCHING DATA FROM ALL SOURCES...")
    print("─" * 50)

    all_data = data_fetcher.fetch_all_data()

    print(f"\n  Data Source Status:")
    for key, val in all_data.items():
        if val is None:
            print(f"    ❌ {key}: UNAVAILABLE")
        elif hasattr(val, '__len__'):
            print(f"    ✅ {key}: {len(val)} records")
        elif isinstance(val, dict):
            print(f"    ✅ {key}: OK")
        else:
            print(f"    ✅ {key}: {val}")

    # ── Step 2: Compute indicators ──────────────────────────────────────────
    print(f"\n📐 COMPUTING INDICATORS...")
    print("─" * 50)

    computed = claude_brain.compute_all_indicators(all_data)
    for key, val in computed.items():
        print(f"    {key:.<25} {val}")

    # ── Step 3: Show raw data (verbose) ─────────────────────────────────────
    if verbose:
        print(f"\n📋 VERBOSE — RAW INDICATOR VALUES:")
        print("─" * 50)

        candles_5m = all_data.get("delta_candles_5m")
        candles_3m = all_data.get("delta_candles_3m")

        if candles_5m is not None and len(candles_5m) > 0:
            close = candles_5m["close"]
            price = close.iloc[-1]
            print(f"  5m Last Close:  ${price:,.2f}")

        if candles_3m is not None and len(candles_3m) > 0:
            rsi = indicators.calculate_rsi(candles_3m["close"], config.RSI_PERIOD)
            print(f"  3m RSI(14):     {rsi.iloc[-1]:.2f}")

        ob = all_data.get("delta_orderbook")
        if ob:
            bid_vol = sum(float(b.get("size", 0)) for b in ob.get("buy", []))
            ask_vol = sum(float(a.get("size", 0)) for a in ob.get("sell", []))
            total = bid_vol + ask_vol
            imbalance = (bid_vol - ask_vol) / total * 100 if total > 0 else 0
            print(f"  Orderbook:      {imbalance:+.1f}% imbalance")

        fg = all_data.get("fear_greed")
        if fg:
            print(f"  Fear & Greed:   {fg['value']} — {fg['classification']}")

    if data_only:
        print(f"\n  ⏭  --data-only flag set, skipping Claude analysis")
        print(f"{'='*60}\n")
        return

    # ── Step 4: Claude analysis ─────────────────────────────────────────────
    print(f"\n🧠 SENDING TO CLAUDE FOR ANALYSIS...")
    print("─" * 50)

    # Pass position state to Claude
    try:
        import position_manager
        pos = position_manager.get_current_position()
        if pos:
            print(f"  📍 Active position: {pos['direction']} @ ${pos['entry_price']:,.2f}")
    except ImportError:
        pos = None

    analysis = claude_brain.analyze_with_claude(all_data, current_position=pos)

    if analysis is None:
        print(f"  ❌ Claude analysis failed")
        print(f"{'='*60}\n")
        return

    action = analysis.get("action") or analysis.get("decision", "UNKNOWN")
    confidence = analysis["confidence"]

    print(f"\n  Action:         {action}")
    print(f"  Confidence:     {confidence}/10")
    print(f"  Reasoning:      {analysis.get('reasoning', '')}")
    print(f"  Market:         {analysis.get('market_condition', '')}")
    if action in ["BUY", "SELL"]:
        print(f"  Entry:          ${(analysis.get('entry_price') or 0):,.2f}")
        print(f"  Stop-Loss:      ${(analysis.get('stop_loss') or 0):,.2f}")
        print(f"  Take-Profit:    ${(analysis.get('take_profit') or 0):,.2f}")
    elif action == "TRAIL_SL":
        print(f"  New SL:         ${(analysis.get('new_sl') or 0):,.2f}")
    elif action == "REVERSE":
        print(f"  Reverse Entry:  ${(analysis.get('reverse_entry') or 0):,.2f}")
        print(f"  Reverse SL:     ${(analysis.get('reverse_sl') or 0):,.2f}")
        print(f"  Reverse TP:     ${(analysis.get('reverse_tp') or 0):,.2f}")
    if analysis.get('risk_warnings'):
        print(f"  Risk:           {analysis['risk_warnings']}")

    if verbose and analysis.get("raw_response"):
        print(f"\n📋 RAW CLAUDE RESPONSE:")
        print("─" * 50)
        print(analysis["raw_response"])

    # ── Step 5: Ask Y/N if actionable signal ─────────────────────────────────
    if action in ["BUY", "SELL"]:
        print()
        confirmed = trade_tracker.prompt_trade_confirmation(analysis, timeout_seconds=60)
        if confirmed:
            claude_brain.record_trade_taken(analysis)
            print(f"  ✅ Trade recorded!")

    print(f"\n{'='*60}")
    print(f"  ✅ Single cycle complete.")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Run a single bot cycle for testing.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show detailed indicator values and raw Claude response")
    parser.add_argument("--data-only", "-d", action="store_true",
                        help="Only fetch data and compute indicators, skip Claude API call")
    args = parser.parse_args()

    if not args.data_only:
        if not config.ANTHROPIC_API_KEY or config.ANTHROPIC_API_KEY == "your_anthropic_api_key_here":
            print("\n  ❌ ANTHROPIC_API_KEY not set in .env")
            print("  Use --data-only flag to test without Claude, or add your key.\n")
            sys.exit(1)

    run_single_cycle(verbose=args.verbose, data_only=args.data_only)


if __name__ == "__main__":
    main()
