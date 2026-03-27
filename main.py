"""
=============================================================================
 MAIN.PY — BTC BRAIN v2 Ultra (Entry Point)
=============================================================================
 Position-aware AI trading bot with:
   • 1 trade at a time rule
   • Auto-trailing stop to breakeven
   • Smart position management via Claude
   • Full P&L tracking + Telegram alerts
   • 24/7 operation for BTC market
=============================================================================
"""

import sys
import os
import time
import signal as os_signal
import threading
from datetime import datetime, timezone, timedelta

import config
import data_fetcher
import indicators
import claude_brain
import trade_tracker
import alerts
import position_manager
import pnl_tracker

IST = timezone(timedelta(hours=5, minutes=30))
_running = True


def shutdown_handler(signum, frame):
    global _running
    _running = False
    print("\n\n  🛑 Shutting down gracefully...\n")
    # Send daily summary on shutdown
    try:
        summary = pnl_tracker.format_daily_summary()
        alerts.send_telegram_alert(summary)
        print(summary)
    except Exception:
        pass

os_signal.signal(os_signal.SIGINT, shutdown_handler)
os_signal.signal(os_signal.SIGTERM, shutdown_handler)


def is_within_trading_hours():
    now_ist = datetime.now(IST)
    hour = now_ist.hour
    start, end = config.TRADING_START_HOUR_IST, config.TRADING_END_HOUR_IST
    if start == 0 and end == 24:
        return True, now_ist.strftime("%I:%M %p IST")
    in_window = hour >= start or hour < end
    return in_window, now_ist.strftime("%I:%M %p IST")


def close_position_with_report(current_price, reason):
    """Close position and generate P&L report."""
    pos = position_manager.get_current_position()
    if pos is None:
        return None

    closed = position_manager.close_position(reason, current_price)
    if not closed:
        return None

    pos_size = indicators.calculate_position_size(closed["entry_price"])
    pnl = pnl_tracker.calculate_trade_pnl(
        direction=closed["direction"],
        entry_price=closed["entry_price"],
        exit_price=current_price,
        contracts=pos_size["contracts"],
        leverage=config.LEVERAGE,
    )

    pnl_tracker.log_closed_trade(pnl, close_reason=reason)
    pnl_tracker.update_daily_pnl(pnl["net_pnl_usd"], pnl["result"])

    if pnl["result"] == "LOSS":
        trade_dir = "SELL" if closed["direction"] == "SHORT" else "BUY"
        claude_brain.mark_last_signal_loss(trade_dir)

    terminal_report, telegram_report = pnl_tracker.format_trade_report(pnl, close_reason=reason)
    print(terminal_report)
    alerts.send_telegram_alert(telegram_report)
    return pnl


def auto_trail_stop(pos, current_price):
    """
    Auto-trail SL based on unrealized profit.
    - At TRAIL_TO_BREAKEVEN_PCT profit → move SL to breakeven
    - Beyond that → trail to lock TRAIL_PROFIT_LOCK_RATIO of profit
    """
    entry = pos["entry_price"]
    current_sl = pos["stop_loss"]
    direction = pos["direction"]

    if direction == "LONG":
        pnl_pct = (current_price - entry) / entry * 100
        # Move SL to breakeven when profit exceeds threshold
        if pnl_pct >= config.TRAIL_TO_BREAKEVEN_PCT and current_sl < entry:
            new_sl = entry + (entry * 0.01 / 100)  # slightly above breakeven
            position_manager.update_stop_loss(round(new_sl, 2))
            alerts.send_telegram_alert(f"📐 Auto-trail: SL → breakeven ${new_sl:,.2f}")
            return True
        # Trail to lock profits
        if pnl_pct > config.TRAIL_TO_BREAKEVEN_PCT * 2:
            profit_lock = entry + (current_price - entry) * config.TRAIL_PROFIT_LOCK_RATIO
            if profit_lock > current_sl:
                position_manager.update_stop_loss(round(profit_lock, 2))
                alerts.send_telegram_alert(f"📐 Auto-trail: SL → ${profit_lock:,.2f} (locking profit)")
                return True
    else:  # SHORT
        pnl_pct = (entry - current_price) / entry * 100
        if pnl_pct >= config.TRAIL_TO_BREAKEVEN_PCT and current_sl > entry:
            new_sl = entry - (entry * 0.01 / 100)
            position_manager.update_stop_loss(round(new_sl, 2))
            alerts.send_telegram_alert(f"📐 Auto-trail: SL → breakeven ${new_sl:,.2f}")
            return True
        if pnl_pct > config.TRAIL_TO_BREAKEVEN_PCT * 2:
            profit_lock = entry - (entry - current_price) * config.TRAIL_PROFIT_LOCK_RATIO
            if profit_lock < current_sl:
                position_manager.update_stop_loss(round(profit_lock, 2))
                alerts.send_telegram_alert(f"📐 Auto-trail: SL → ${profit_lock:,.2f} (locking profit)")
                return True
    return False


def print_startup_banner():
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text
        from rich import box
        c = Console()
        banner = Text()
        banner.append("\n  ⚡ BTC BRAIN v2 Ultra — AI Swing-Scalp Bot\n", style="bold white")
        banner.append(f"  Model: {config.CLAUDE_MODEL}\n", style="magenta")
        mode = "AUTO-ACCEPT" if config.AUTO_ACCEPT_TRADES else "MANUAL (Y/N)"
        banner.append(f"  Mode: {mode} | Cycle: {config.BOT_CYCLE_SECONDS}s\n", style="cyan")
        banner.append(f"  Balance: ${config.DEFAULT_BALANCE_USDT} | {config.LEVERAGE}x | Min Conf: {config.MIN_CONFIDENCE}\n", style="cyan")
        pos = position_manager.get_current_position()
        if pos:
            banner.append(f"\n  📍 RESUMING: {pos['direction']} @ ${pos['entry_price']:,.2f}\n", style="yellow")
        else:
            banner.append(f"\n  📍 Starting FLAT\n", style="green")
        daily = pnl_tracker.get_daily_pnl()
        if daily["trades_count"] > 0:
            banner.append(f"  📊 Today: ${daily['total_pnl_usd']:+,.2f} ({daily['trades_count']} trades)\n", style="cyan")
        banner.append(f"\n  Ctrl+C to stop\n", style="dim")
        c.print(Panel(banner, title="🚀 BTC BRAIN v2", style="blue", box=box.DOUBLE_EDGE))
    except ImportError:
        print(f"\n  ⚡ BTC BRAIN v2 | {config.CLAUDE_MODEL} | {'AUTO' if config.AUTO_ACCEPT_TRADES else 'MANUAL'}")
    print()


def run_cycle(cycle_count):
    """One complete bot cycle."""
    now_str = datetime.now(IST).strftime('%I:%M:%S %p IST')

    pos = position_manager.get_current_position()
    daily = pnl_tracker.get_daily_pnl()
    pos_str = f"{pos['direction']} @ ${pos['entry_price']:,.2f}" if pos else "FLAT"
    daily_str = f"${daily['total_pnl_usd']:+,.2f}" if daily["trades_count"] > 0 else ""

    print(f"\n  ── Cycle #{cycle_count} │ {now_str} │ 📍 {pos_str} │ 💰 {daily_str} ──")

    # Trading hours check
    in_hours, _ = is_within_trading_hours()
    if not in_hours:
        print(f"  ⏸ Outside trading hours")
        return

    # Fetch data
    print(f"  📡 Fetching market data...")
    all_data = data_fetcher.fetch_all_data()

    ticker = all_data.get("delta_ticker")
    if not ticker:
        print(f"  ❌ No ticker data")
        return

    price = ticker["mark_price"]
    print(f"  💰 BTC: ${price:,.2f}")

    # ── Check SL/TP & Auto-Trail ────────────────────────────────────────
    pos = position_manager.get_current_position()
    if pos:
        hit = position_manager.check_sl_tp_hit(price)
        if hit == "sl_hit":
            print(f"\n  ⚠ STOP-LOSS HIT!")
            alerts.play_signal_sound("SELL")
            close_position_with_report(price, "sl_hit")
            pos = None
        elif hit == "tp_hit":
            print(f"\n  🎯 TAKE-PROFIT HIT!")
            alerts.play_signal_sound("BUY")
            close_position_with_report(price, "tp_hit")
            pos = None
        else:
            # Auto-trail stop loss
            auto_trail_stop(pos, price)
            summary = position_manager.get_position_summary(price)
            print(f"  📍 {summary}")

    # ── Claude Analysis ─────────────────────────────────────────────────
    pos = position_manager.get_current_position()
    analysis = claude_brain.analyze_with_claude(all_data, current_position=pos)

    if analysis is None:
        print(f"  ❌ Claude analysis failed")
        return

    action = analysis["action"]
    confidence = analysis["confidence"]
    reasoning = analysis.get("reasoning", "")

    # ══════════════════════════════════════════════════════════════════════
    #  STATE: FLAT
    # ══════════════════════════════════════════════════════════════════════
    if pos is None:
        if action not in ["BUY", "SELL", "NO_TRADE"]:
            action = "NO_TRADE"

        if action == "NO_TRADE":
            market_cond = analysis.get("market_condition", "")
            risk_warn = analysis.get("risk_warnings", "")
            print(f"  👁 NO TRADE (conf: {confidence}/10)")
            print(f"     📝 {reasoning}")
            if market_cond:
                print(f"     🌍 {market_cond}")
            if risk_warn:
                print(f"     ⚠️  {risk_warn}")
            trade_tracker.log_signal(analysis, trade_taken=False, skip_reason="no_trade")
            return

        # Confidence gate
        if confidence < config.MIN_CONFIDENCE:
            print(f"  ⚠ {action} blocked — conf {confidence} < {config.MIN_CONFIDENCE}")
            trade_tracker.log_signal(analysis, trade_taken=False, skip_reason=f"low_conf_{confidence}")
            return

        # ── New Trade ───────────────────────────────────────────────
        print(f"\n  ⚡ {action} SIGNAL — Confidence: {confidence}/10")
        print(f"  📝 {reasoning[:150]}")
        print(f"  Entry: ${analysis.get('entry_price', price):,.2f}")
        print(f"  SL: ${analysis.get('stop_loss', 0):,.2f} | TP: ${analysis.get('take_profit', 0):,.2f}")
        alerts.play_signal_sound(action)

        alerts.send_telegram_alert(
            f"*⚡ {action} Signal* (conf: {confidence}/10)\n"
            f"Entry: `${analysis.get('entry_price', price):,.2f}`\n"
            f"SL: `${analysis.get('stop_loss', 0):,.2f}` | TP: `${analysis.get('take_profit', 0):,.2f}`\n"
            f"_{reasoning[:200]}_"
        )

        if config.AUTO_ACCEPT_TRADES:
            confirmed = True
        else:
            confirmed = trade_tracker.prompt_trade_confirmation(analysis)

        if confirmed:
            direction = "LONG" if action == "BUY" else "SHORT"
            entry = analysis.get("entry_price") or price
            sl = analysis.get("stop_loss") or 0
            tp = analysis.get("take_profit") or 0

            position_manager.open_position(direction, entry, sl, tp, confidence, reasoning)
            trade_tracker.log_signal(analysis, trade_taken=True)
            trade_tracker.log_trade(analysis)
            alerts.send_telegram_alert(f"✅ OPENED: {direction} @ ${entry:,.2f}")
        else:
            trade_tracker.log_signal(analysis, trade_taken=False, skip_reason="declined")
        return

    # ══════════════════════════════════════════════════════════════════════
    #  STATE: IN POSITION
    # ══════════════════════════════════════════════════════════════════════
    if action in ["BUY", "SELL"]:
        current_dir = pos["direction"]
        if (action == "BUY" and current_dir == "SHORT") or (action == "SELL" and current_dir == "LONG"):
            action = "REVERSE"
            analysis["reverse_entry"] = analysis.get("entry_price") or price
            analysis["reverse_sl"] = analysis.get("stop_loss") or 0
            analysis["reverse_tp"] = analysis.get("take_profit") or 0
        else:
            action = "HOLD"

    if action == "NO_TRADE":
        action = "HOLD"

    if action not in ["HOLD", "TRAIL_SL", "ADJUST_TP", "EXIT", "REVERSE"]:
        action = "HOLD"

    # ── HOLD ────────────────────────────────────────────────────────
    if action == "HOLD":
        print(f"  ✊ HOLD (conf: {confidence}/10) — {reasoning}")
        trade_tracker.log_signal(analysis, trade_taken=False, skip_reason="hold")

    # ── TRAIL_SL ────────────────────────────────────────────────────
    elif action == "TRAIL_SL":
        new_sl = analysis.get("new_sl", 0)
        if new_sl > 0:
            old_sl = pos["stop_loss"]
            # Validate: only allow SL to move in profitable direction
            if pos["direction"] == "LONG" and new_sl > old_sl:
                position_manager.update_stop_loss(new_sl)
                print(f"  📐 SL trailed: ${old_sl:,.2f} → ${new_sl:,.2f}")
                alerts.send_telegram_alert(f"📐 SL trailed → ${new_sl:,.2f}")
            elif pos["direction"] == "SHORT" and new_sl < old_sl:
                position_manager.update_stop_loss(new_sl)
                print(f"  📐 SL trailed: ${old_sl:,.2f} → ${new_sl:,.2f}")
                alerts.send_telegram_alert(f"📐 SL trailed → ${new_sl:,.2f}")
            else:
                print(f"  ⚠ SL trail rejected (wrong direction)")
        trade_tracker.log_signal(analysis, trade_taken=True)

    # ── ADJUST_TP ───────────────────────────────────────────────────
    elif action == "ADJUST_TP":
        new_tp = analysis.get("new_tp", 0)
        if new_tp > 0:
            position_manager.update_take_profit(new_tp)
            print(f"  📐 TP adjusted → ${new_tp:,.2f}")
        trade_tracker.log_signal(analysis, trade_taken=True)

    # ── EXIT ────────────────────────────────────────────────────────
    elif action == "EXIT":
        print(f"  🚪 EXIT — {reasoning[:100]}")
        if config.AUTO_ACCEPT_TRADES or confidence >= 6:
            close_position_with_report(price, "claude_exit")
            alerts.play_signal_sound("SELL")
            trade_tracker.log_signal(analysis, trade_taken=True)
        else:
            print(f"  ⏸ EXIT blocked (conf {confidence} < 6)")

    # ── REVERSE ─────────────────────────────────────────────────────
    elif action == "REVERSE":
        print(f"  🔄 REVERSE — {reasoning[:100]}")
        if config.AUTO_ACCEPT_TRADES or confidence >= 7:
            old_dir = pos["direction"]
            close_position_with_report(price, "reversed")

            new_dir = "SHORT" if old_dir == "LONG" else "LONG"
            new_entry = analysis.get("reverse_entry") or price
            new_sl = analysis.get("reverse_sl") or 0
            new_tp = analysis.get("reverse_tp") or 0

            position_manager.open_position(new_dir, new_entry, new_sl, new_tp, confidence, reasoning)
            alerts.send_telegram_alert(f"🔄 REVERSED → {new_dir} @ ${new_entry:,.2f}")
            alerts.play_signal_sound("BUY" if new_dir == "LONG" else "SELL")
            trade_tracker.log_signal(analysis, trade_taken=True)
        else:
            print(f"  ⏸ REVERSE blocked (conf {confidence} < 7)")


# =============================================================================
#  MAIN LOOP
# =============================================================================

def main():
    print_startup_banner()

    cycle_count = 0
    while _running:
        cycle_count += 1
        try:
            # Timeout guard: if cycle hangs longer than (cycle_seconds - 30s),
            # log a warning and skip to the next sleep. Prevents overlapping cycles.
            cycle_timeout = max(60, config.BOT_CYCLE_SECONDS - 30)
            cycle_timed_out = threading.Event()

            def _cycle_watchdog():
                cycle_timed_out.set()
                print(f"\n  ⚠ Cycle #{cycle_count} timed out after {cycle_timeout}s — skipping to next cycle")

            watchdog = threading.Timer(cycle_timeout, _cycle_watchdog)
            watchdog.daemon = True
            watchdog.start()
            try:
                if not cycle_timed_out.is_set():
                    run_cycle(cycle_count)
            finally:
                watchdog.cancel()

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"\n  ❌ Cycle error: {e}")
            import traceback
            traceback.print_exc()

        if not _running:
            break

        print(f"\n  ⏳ Next scan in {config.BOT_CYCLE_SECONDS}s...")
        for _ in range(config.BOT_CYCLE_SECONDS):
            if not _running:
                break
            time.sleep(1)

    # Shutdown
    print("\n  📊 Daily Summary:")
    daily = pnl_tracker.get_daily_pnl()
    if daily["trades_count"] > 0:
        print(f"  P&L: ${daily['total_pnl_usd']:+,.4f} | Trades: {daily['trades_count']} | W:{daily['wins']} L:{daily['losses']}")
    print("  👋 Goodbye!\n")


if __name__ == "__main__":
    main()
