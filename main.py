"""
=============================================================================
 MAIN.PY — BTC Perpetuals Scalping Signal Bot (Entry Point)
=============================================================================
 
 ████  ████████  ████       ████████  ████████  █████  ██      ████████  ████████  ████████
 ██  ██   ██    ██         ██        ██        ██  ██  ██      ██   ██  ██        ██   ██
 ████     ██    ██         ████████  ██        █████   ██      ██████   ████████  ████████
 ██  ██   ██    ██               ██  ██        ██  ██  ██      ██       ██        ██  ██
 ████     ██     ████      ████████  ████████  ██  ██  ██████  ██       ████████  ██  ██
 
 Mode:    SIGNAL ONLY (testing phase — no auto order placement)
 Market:  BTCUSD Inverse Perpetual on Delta Exchange India
 
 Run:     python main.py
 
 Architecture (future-ready):
   ├── config.py          — all tunable parameters + .env loading
   ├── data_fetcher.py    — API calls to Delta, Binance, FnG, CoinGecko
   ├── indicators.py      — EMA, RSI, ATR, regime detection, SL/TP calc
   ├── signal_engine.py   — core signal logic + confidence scoring
   ├── alerts.py          — desktop notifs, Telegram placeholder, CSV log
   ├── dashboard.py       — rich terminal dashboard
   └── main.py            — this file (orchestrator)
   
 Future modules (architecture ready, not built yet):
   ├── auto_trader.py     — auto order placement on Delta Exchange
   ├── telegram_bot.py    — full Telegram bot with inline commands
   ├── backtester.py      — replay signals_log.csv against historical data
   └── web_app.py         — Flask/FastAPI web dashboard
=============================================================================
"""

import sys
import time
import signal as os_signal
from datetime import datetime, timezone, timedelta

# ── Local modules ───────────────────────────────────────────────────────────
import config
import data_fetcher
import signal_engine
import alerts
import dashboard

# IST timezone
IST = timezone(timedelta(hours=5, minutes=30))

# ── Graceful shutdown ───────────────────────────────────────────────────────
_running = True


def shutdown_handler(signum, frame):
    """Handle Ctrl+C gracefully."""
    global _running
    _running = False
    print("\n\n  🛑 Shutting down bot gracefully...\n")


os_signal.signal(os_signal.SIGINT, shutdown_handler)
os_signal.signal(os_signal.SIGTERM, shutdown_handler)


# =============================================================================
#  STARTUP BANNER
# =============================================================================

def print_startup_banner():
    """Print a startup banner with configuration summary."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    from rich import box

    c = Console()

    banner = Text()
    banner.append("\n")
    banner.append("  ⚡ BTC PERPETUALS SCALPING SIGNAL BOT\n", style="bold white")
    banner.append("  ─────────────────────────────────────\n", style="dim")
    banner.append(f"  Exchange:       Delta Exchange India\n", style="cyan")
    banner.append(f"  Contract:       {config.DELTA_SYMBOL} (Inverse Perpetual)\n", style="cyan")
    banner.append(f"  Mode:           SIGNAL ONLY (no auto-trade)\n", style="bold yellow")
    banner.append(f"  Cycle:          Every {config.BOT_CYCLE_SECONDS}s ({config.BOT_CYCLE_SECONDS // 60} min)\n", style="cyan")
    banner.append(f"  Trading Hours:  2:00 PM – 2:00 AM IST\n", style="cyan")
    banner.append(f"  Leverage:       {config.LEVERAGE}×\n", style="cyan")
    banner.append(f"  Balance Usage:  {config.BALANCE_USAGE_PERCENT}%\n", style="cyan")
    banner.append(f"  SL Floor:       {config.SL_MIN_PERCENT}%  │  TP Floor: {config.TP_MIN_PERCENT}%\n", style="cyan")
    banner.append(f"  Cooldown:       {config.SIGNAL_COOLDOWN_SECONDS}s between same-direction\n", style="cyan")
    banner.append("\n", style="")
    banner.append("  Data Sources:\n", style="bold")
    banner.append("    ✓ Delta Exchange — candles, ticker, orderbook\n", style="green")
    banner.append("    ✓ Binance — BTC reference price\n", style="green")
    banner.append("    ✓ Alternative.me — Fear & Greed Index\n", style="green")
    banner.append("    ✓ CoinGecko — BTC dominance & volume\n", style="green")
    banner.append("\n")
    banner.append("  Strategies:\n", style="bold")
    banner.append("    • Trending → EMA 9/21 crossover (5m candles)\n", style="white")
    banner.append("    • Ranging  → RSI mean-reversion (3m candles)\n", style="white")
    banner.append("    • High Vol → Sit out (no signal)\n", style="white")
    banner.append("\n")
    banner.append("  Press Ctrl+C to stop\n", style="dim")

    c.print(Panel(banner, title="🚀 STARTING UP", title_align="left",
                  style="bold blue", box=box.DOUBLE_EDGE))
    print()


# =============================================================================
#  SINGLE BOT CYCLE
# =============================================================================

def run_cycle(cycle_count):
    """
    Execute one complete bot cycle:
      1. Fetch all data
      2. Generate signal
      3. Dispatch alerts (if signal)
      4. Render dashboard
    
    Returns:
        signal_result dict
    """
    print(f"\n{'─'*56}")
    print(f"  🔄 Cycle #{cycle_count} — {datetime.now(IST).strftime('%I:%M:%S %p IST')}")
    print(f"{'─'*56}")

    # ── Step 1: Fetch all data ──────────────────────────────────────────────
    print("\n  📡 Fetching market data from all sources...")
    all_data = data_fetcher.fetch_all_data()

    # Quick data availability summary
    available = sum(1 for v in all_data.values() if v is not None)
    total = len(all_data)
    print(f"\n  ✓ Data sources: {available}/{total} available")

    # ── Step 2: Generate signal ─────────────────────────────────────────────
    print("\n  🧠 Analyzing market conditions...")
    signal_result = signal_engine.generate_signal(all_data)

    # ── Step 3: Dispatch alerts if signal ───────────────────────────────────
    if isinstance(signal_result, dict) and signal_result.get("status") == "SIGNAL":
        print("\n  ⚡ SIGNAL DETECTED! Dispatching alerts...")
        alerts.dispatch_signal(signal_result)

    # ── Step 4: Render dashboard ────────────────────────────────────────────
    try:
        dashboard.render_dashboard(all_data, signal_result, cycle_count)
    except Exception as e:
        # Dashboard render failure should never crash the bot
        print(f"  [WARN] Dashboard render error: {e}")
        # Print minimal status instead
        status = signal_result.get("status", "UNKNOWN") if isinstance(signal_result, dict) else "UNKNOWN"
        print(f"  Status: {status}")
        if isinstance(signal_result, dict) and signal_result.get("price"):
            print(f"  Price: ${signal_result['price']:,.2f}")

    return signal_result


# =============================================================================
#  MAIN LOOP
# =============================================================================

def main():
    """
    Main entry point. Runs the bot in an infinite loop.
    
    Loop:
      1. Run one cycle
      2. Sleep for BOT_CYCLE_SECONDS
      3. Repeat until Ctrl+C
    """
    print_startup_banner()

    cycle_count = 0

    while _running:
        cycle_count += 1

        try:
            run_cycle(cycle_count)
        except KeyboardInterrupt:
            break
        except Exception as e:
            # Catch ANY unexpected error — bot must never crash
            print(f"\n  ❌ Unexpected error in cycle #{cycle_count}: {e}")
            print("  Bot will retry next cycle...")

        if not _running:
            break

        # ── Countdown to next cycle ─────────────────────────────────────────
        wait = config.BOT_CYCLE_SECONDS
        try:
            from rich.console import Console
            c = Console()
            for remaining in range(wait, 0, -1):
                if not _running:
                    break
                mins, secs = divmod(remaining, 60)
                c.print(
                    f"  ⏱  Next cycle in: {mins:02d}:{secs:02d}",
                    end="\r",
                    style="dim cyan",
                )
                time.sleep(1)
        except KeyboardInterrupt:
            break

    # ── Shutdown ────────────────────────────────────────────────────────────
    print("\n  ✅ Bot stopped. Signal log saved to:", config.SIGNAL_LOG_FILE)
    print("  Thanks for using BTC Scalper Bot!\n")


# =============================================================================
#  ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    main()
