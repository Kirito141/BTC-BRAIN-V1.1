"""
=============================================================================
 RUN_ONCE.PY — Single Cycle Test Runner
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

IST = timezone(timedelta(hours=5, minutes=30))


def run_single_cycle(verbose=False, data_only=False):
    now = datetime.now(IST).strftime("%I:%M:%S %p IST")
    print(f"\n{'='*60}")
    print(f"  🔬 SINGLE CYCLE TEST — {now}")
    print(f"{'='*60}")

    # Fetch data
    print("\n📡 FETCHING DATA...")
    all_data = data_fetcher.fetch_all_data()

    # Compute indicators
    print(f"\n📐 COMPUTING INDICATORS...")
    computed = claude_brain.compute_all_indicators(all_data)

    # Print all indicators
    print(f"\n  ── Computed Indicators ──")
    for key, val in sorted(computed.items()):
        if isinstance(val, list):
            print(f"    {key:.<35} {val}")
        elif isinstance(val, float):
            print(f"    {key:.<35} {val:.4f}")
        else:
            print(f"    {key:.<35} {val}")

    if verbose:
        ticker = all_data.get("delta_ticker")
        if ticker:
            print(f"\n  ── Price Info ──")
            print(f"    Mark: ${ticker['mark_price']:,.2f}")
            print(f"    Funding: {ticker['funding_rate']:.6f}")
            print(f"    OI: {ticker['open_interest']:,.0f}")

        fg = all_data.get("fear_greed")
        if fg:
            print(f"    Fear & Greed: {fg['value']} ({fg['classification']}) — Trend: {fg.get('trend', '?')}")

        bf = all_data.get("binance_futures") or {}
        fh = bf.get("funding_history")
        if fh:
            print(f"    Funding History: current={fh['current_rate']:.6f} avg={fh['avg_rate']:.6f} trend={fh['trend']}")

    if data_only:
        print(f"\n  ⏭ Skipping Claude (--data-only)")
        print(f"{'='*60}\n")
        return

    # Claude analysis
    print(f"\n🧠 CLAUDE ANALYSIS...")
    print("─" * 50)

    try:
        import position_manager
        pos = position_manager.get_current_position()
        if pos:
            print(f"  📍 Active: {pos['direction']} @ ${pos['entry_price']:,.2f}")
    except ImportError:
        pos = None

    analysis = claude_brain.analyze_with_claude(all_data, current_position=pos)

    if analysis is None:
        print(f"  ❌ Claude failed")
        return

    action = analysis.get("action", "UNKNOWN")
    confidence = analysis["confidence"]

    print(f"\n  Action:     {action}")
    print(f"  Confidence: {confidence}/10")
    print(f"  Reasoning:  {analysis.get('reasoning', '')}")
    print(f"  Market:     {analysis.get('market_condition', '')}")

    if action in ["BUY", "SELL"]:
        print(f"  Entry:      ${analysis.get('entry_price', 0):,.2f}")
        print(f"  SL:         ${analysis.get('stop_loss', 0):,.2f}")
        print(f"  TP:         ${analysis.get('take_profit', 0):,.2f}")
    if analysis.get("risk_warnings"):
        print(f"  Risk:       {analysis['risk_warnings']}")

    if verbose and analysis.get("raw_response"):
        print(f"\n📋 RAW RESPONSE:")
        print("─" * 50)
        print(analysis["raw_response"])

    if action in ["BUY", "SELL"]:
        confirmed = trade_tracker.prompt_trade_confirmation(analysis, timeout_seconds=60)
        if confirmed:
            claude_brain.record_trade_taken(analysis)
            print(f"  ✅ Trade recorded!")

    print(f"\n{'='*60}")
    print(f"  ✅ Complete.")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Single cycle test")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--data-only", "-d", action="store_true")
    args = parser.parse_args()

    if not args.data_only:
        if not config.ANTHROPIC_API_KEY or config.ANTHROPIC_API_KEY == "your_anthropic_api_key_here":
            print("\n  ❌ ANTHROPIC_API_KEY not set. Use --data-only or add key.\n")
            sys.exit(1)

    run_single_cycle(verbose=args.verbose, data_only=args.data_only)


if __name__ == "__main__":
    main()
