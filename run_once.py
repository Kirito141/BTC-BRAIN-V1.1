"""
=============================================================================
 RUN_ONCE.PY — Single Cycle Runner (for testing/debugging)
=============================================================================
 Runs exactly ONE cycle of the bot and exits.
 Perfect for:
   • Testing after changes without waiting for the 3-min loop
   • Debugging data fetching or signal logic
   • Running a quick check before starting the full bot
   
 Usage: python run_once.py
 
 Add --verbose flag for extra debug output:
        python run_once.py --verbose
=============================================================================
"""

import sys
import json
import argparse
from datetime import datetime, timezone, timedelta

# Local modules
import config
import data_fetcher
import indicators
import signal_engine
import alerts

IST = timezone(timedelta(hours=5, minutes=30))


def run_single_cycle(verbose=False):
    """Run one complete bot cycle with detailed output."""

    now = datetime.now(IST).strftime("%I:%M:%S %p IST")
    print(f"\n{'='*60}")
    print(f"  🔬 SINGLE CYCLE TEST — {now}")
    print(f"{'='*60}")

    # ── Step 1: Fetch data ──────────────────────────────────────────────────
    print("\n📡 FETCHING DATA FROM ALL SOURCES...")
    print("─" * 50)

    all_data = data_fetcher.fetch_all_data()

    # Report data availability
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

    # ── Step 2: Show raw indicator values (verbose) ─────────────────────────
    if verbose:
        print(f"\n📐 RAW INDICATOR VALUES:")
        print("─" * 50)

        candles_5m = all_data.get("delta_candles_5m")
        candles_3m = all_data.get("delta_candles_3m")

        if candles_5m is not None and len(candles_5m) > 0:
            close = candles_5m["close"]
            ema9 = indicators.calculate_ema(close, 9).iloc[-1]
            ema21 = indicators.calculate_ema(close, 21).iloc[-1]
            atr = indicators.get_current_atr(candles_5m)
            price = close.iloc[-1]

            print(f"  5m Candles:")
            print(f"    Last Close:  ${price:,.2f}")
            print(f"    EMA 9:       ${ema9:,.2f}")
            print(f"    EMA 21:      ${ema21:,.2f}")
            print(f"    EMA Spread:  {abs(ema9 - ema21) / price * 100:.4f}%")
            print(f"    ATR:         ${atr:,.2f} ({atr / price * 100:.4f}%)")

            # EMA crossover check
            ema_result = indicators.detect_ema_crossover(candles_5m)
            print(f"    EMA Signal:  {ema_result['signal'] or 'None'} (strength: {ema_result['strength']:.3f})")

        if candles_3m is not None and len(candles_3m) > 0:
            close_3m = candles_3m["close"]
            rsi = indicators.calculate_rsi(close_3m, config.RSI_PERIOD)
            rsi_val = rsi.iloc[-1]

            print(f"\n  3m Candles:")
            print(f"    Last Close:  ${close_3m.iloc[-1]:,.2f}")
            print(f"    RSI(14):     {rsi_val:.2f}")
            print(f"    RSI Status:  ", end="")
            if rsi_val < config.RSI_OVERSOLD:
                print(f"OVERSOLD (< {config.RSI_OVERSOLD})")
            elif rsi_val > config.RSI_OVERBOUGHT:
                print(f"OVERBOUGHT (> {config.RSI_OVERBOUGHT})")
            else:
                print(f"Neutral")

            rsi_result = indicators.detect_rsi_signal(candles_3m)
            print(f"    RSI Signal:  {rsi_result['signal'] or 'None'} (strength: {rsi_result['strength']:.3f})")

        # Orderbook imbalance
        ob = all_data.get("delta_orderbook")
        if ob:
            bid_vol = sum(float(b.get("size", 0)) for b in ob.get("buy", []))
            ask_vol = sum(float(a.get("size", 0)) for a in ob.get("sell", []))
            total = bid_vol + ask_vol
            imbalance = (bid_vol - ask_vol) / total * 100 if total > 0 else 0
            print(f"\n  Orderbook:")
            print(f"    Bid Volume:  {bid_vol:,.0f}")
            print(f"    Ask Volume:  {ask_vol:,.0f}")
            print(f"    Imbalance:   {imbalance:+.1f}% ({'bids dominate' if imbalance > 0 else 'asks dominate'})")

    # ── Step 3: Generate signal ─────────────────────────────────────────────
    print(f"\n🧠 GENERATING SIGNAL...")
    print("─" * 50)

    result = signal_engine.generate_signal(all_data)
    status = result.get("status", "UNKNOWN")

    print(f"  Status: {status}")

    if status == "SIGNAL":
        print(f"\n  ⚡ SIGNAL GENERATED!")
        alerts.dispatch_signal(result)

    elif status == "OUTSIDE_HOURS":
        print(f"  ⏸  Outside trading hours — {result.get('time', '')}")
        print(f"     Window: 2:00 PM – 2:00 AM IST")

    elif status == "SIT_OUT":
        print(f"  ⚠  Sitting out — {result.get('reason', '')}")

    elif status == "COOLDOWN":
        print(f"  ⏳ Cooldown — {result.get('reason', '')}")

    elif status == "NO_SIGNAL":
        print(f"  👁  No signal — {result.get('reason', '')}")
        regime = result.get("regime", {})
        print(f"     Regime: {regime.get('regime', 'unknown')}")
        print(f"     Reason: {regime.get('reason', '')}")

    else:
        print(f"  ❌ {result.get('reason', 'Unknown error')}")

    # ── Step 4: Raw result dump (verbose) ───────────────────────────────────
    if verbose:
        print(f"\n📋 RAW SIGNAL RESULT:")
        print("─" * 50)
        # Clean print — remove DataFrame objects
        clean = {}
        for k, v in result.items():
            if isinstance(v, dict):
                clean[k] = v
            elif isinstance(v, (str, int, float, bool, type(None))):
                clean[k] = v
        print(json.dumps(clean, indent=2, default=str))

    print(f"\n{'='*60}")
    print(f"  ✅ Single cycle complete.")
    print(f"{'='*60}\n")

    return result


def main():
    parser = argparse.ArgumentParser(description="Run a single bot cycle for testing.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show detailed indicator values and raw output")
    args = parser.parse_args()

    run_single_cycle(verbose=args.verbose)


if __name__ == "__main__":
    main()
