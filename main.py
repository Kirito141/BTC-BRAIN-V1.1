"""
=============================================================================
 MAIN.PY — BTC BRAIN Signal Bot (Entry Point)
=============================================================================
 Position-aware AI trading bot with strict 1-trade-at-a-time rule.
 
 RULES:
   • Only 1 position open at any time
   • When FLAT → Claude can: BUY, SELL, NO_TRADE
   • When IN POSITION → Claude can: HOLD, TRAIL_SL, ADJUST_TP, EXIT, REVERSE
   • If Claude returns wrong action for state → auto-corrected
   • Every position close → full P&L report with fees → Telegram
   • Daily P&L summary on shutdown
=============================================================================
"""

import sys
import os
import time
import signal as os_signal
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
    print("\n\n  🛑 Shutting down...\n")

os_signal.signal(os_signal.SIGINT, shutdown_handler)
os_signal.signal(os_signal.SIGTERM, shutdown_handler)


def is_within_trading_hours():
    now_ist = datetime.now(IST)
    hour = now_ist.hour
    start = config.TRADING_START_HOUR_IST
    end = config.TRADING_END_HOUR_IST
    if start == 0 and end == 24:
        return True, now_ist.strftime("%I:%M %p IST")
    in_window = hour >= start or hour < end
    return in_window, now_ist.strftime("%I:%M %p IST")


def close_position_with_report(current_price, reason):
    """
    Close the active position and generate full P&L report.
    Sends report to terminal + Telegram.
    Returns pnl dict or None.
    """
    pos = position_manager.get_current_position()
    if pos is None:
        return None

    # Close the position
    closed = position_manager.close_position(reason, current_price)
    if not closed:
        return None

    # Calculate contracts for P&L
    pos_size = indicators.calculate_position_size(closed["entry_price"])
    num_contracts = pos_size["contracts"]

    # Calculate P&L with fees
    pnl = pnl_tracker.calculate_trade_pnl(
        direction=closed["direction"],
        entry_price=closed["entry_price"],
        exit_price=current_price,
        contracts=num_contracts,
        leverage=config.LEVERAGE,
    )

    # Log
    pnl_tracker.log_closed_trade(pnl, close_reason=reason)
    pnl_tracker.update_daily_pnl(pnl["net_pnl_usd"], pnl["result"])

    # Mark loss in Claude's memory so it doesn't repeat the same direction
    if pnl["result"] == "LOSS":
        trade_dir = "SELL" if closed["direction"] == "SHORT" else "BUY"
        claude_brain.mark_last_signal_loss(trade_dir)

    # Report
    terminal_report, telegram_report = pnl_tracker.format_trade_report(pnl, close_reason=reason)
    print(terminal_report)
    alerts.send_telegram_alert(telegram_report)

    return pnl


def print_startup_banner():
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text
        from rich import box
        c = Console()
        banner = Text()
        banner.append("\n  ⚡ BTC BRAIN — AI Scalping Bot\n", style="bold white")
        banner.append(f"  Model: {config.CLAUDE_MODEL}\n", style="magenta")
        mode = "AUTO-ACCEPT" if config.AUTO_ACCEPT_TRADES else "MANUAL (Y/N)"
        banner.append(f"  Mode: {mode} | 1 trade at a time\n", style="bold yellow" if config.AUTO_ACCEPT_TRADES else "cyan")
        banner.append(f"  Balance: ${config.DEFAULT_BALANCE_USDT} | {config.LEVERAGE}x | Cycle: {config.BOT_CYCLE_SECONDS}s\n", style="cyan")
        pos = position_manager.get_current_position()
        if pos:
            banner.append(f"\n  📍 RESUMING: {pos['direction']} @ ${pos['entry_price']:,.2f}\n", style="yellow")
        else:
            banner.append(f"\n  📍 Starting FLAT\n", style="green")
        daily = pnl_tracker.get_daily_pnl()
        if daily["trades_count"] > 0:
            banner.append(f"  📊 Today: ${daily['total_pnl_usd']:+,.2f} ({daily['trades_count']} trades)\n", style="cyan")
        banner.append(f"\n  Ctrl+C to stop\n", style="dim")
        c.print(Panel(banner, title="🚀 BTC BRAIN", style="blue", box=box.DOUBLE_EDGE))
    except ImportError:
        print(f"\n  ⚡ BTC BRAIN | {config.CLAUDE_MODEL} | {'AUTO' if config.AUTO_ACCEPT_TRADES else 'MANUAL'}")
    print()


def run_cycle(cycle_count):
    """One complete bot cycle — position-aware, 1 trade at a time."""
    now_str = datetime.now(IST).strftime('%I:%M:%S %p IST')

    # Header
    pos = position_manager.get_current_position()
    daily = pnl_tracker.get_daily_pnl()
    pos_str = f"{pos['direction']} @ ${pos['entry_price']:,.2f}" if pos else "FLAT"
    daily_str = f"${daily['total_pnl_usd']:+,.2f}" if daily["trades_count"] > 0 else ""

    try:
        from rich.console import Console, Panel
        from rich.text import Text
        from rich import box
        c = Console()
        h = Text()
        h.append(f"  #{cycle_count} {now_str}", style="bold")
        h.append(f"  │  📍 {pos_str}", style="yellow" if pos else "green")
        if daily_str:
            h.append(f"  │  💰 {daily_str}", style="green" if daily['total_pnl_usd'] >= 0 else "red")
        c.print(Panel(h, style="cyan", box=box.ROUNDED))
    except ImportError:
        print(f"\n  #{cycle_count} {now_str} | {pos_str} | {daily_str}")

    # ── Trading hours ───────────────────────────────────────────────────
    in_hours, _ = is_within_trading_hours()
    if not in_hours:
        print(f"  ⏸ Outside trading hours")
        return

    # ── Fetch data ──────────────────────────────────────────────────────
    print(f"  📡 Fetching data...")
    all_data = data_fetcher.fetch_all_data()
    available = sum(1 for v in all_data.values() if v is not None)
    print(f"  ✓ {available}/{len(all_data)} sources")

    ticker = all_data.get("delta_ticker")
    if not ticker:
        print(f"  ❌ No ticker data")
        return

    price = ticker["mark_price"]
    print(f"  💰 ${price:,.2f}")

    # ── Check SL/TP hit ─────────────────────────────────────────────────
    pos = position_manager.get_current_position()  # re-read from disk
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
            summary = position_manager.get_position_summary(price)
            print(f"  📍 {summary}")

    # ── Ask Claude ──────────────────────────────────────────────────────
    pos = position_manager.get_current_position()  # re-read after possible SL/TP close
    analysis = claude_brain.analyze_with_claude(all_data, current_position=pos)

    if analysis is None:
        print(f"  ❌ Claude failed")
        return

    action = analysis["action"]
    confidence = analysis["confidence"]
    reasoning = analysis.get("reasoning", "")

    # ══════════════════════════════════════════════════════════════════════
    #  STATE: FLAT (no open position)
    # ══════════════════════════════════════════════════════════════════════
    if pos is None:
        # Force valid actions for flat state
        if action not in ["BUY", "SELL", "NO_TRADE"]:
            print(f"  ⚠ Claude said '{action}' while FLAT — treating as NO_TRADE")
            action = "NO_TRADE"

        if action == "NO_TRADE":
            _display_no_trade(analysis)
            trade_tracker.log_signal(analysis, trade_taken=False, skip_reason="no_trade")
            return

        # ── Minimum confidence gate ─────────────────────────────────────
        min_conf = config.MIN_CONFIDENCE
        if confidence < min_conf:
            print(f"  ⚠ {action} blocked — confidence {confidence}/10 < minimum {min_conf}")
            _display_no_trade(analysis)
            trade_tracker.log_signal(analysis, trade_taken=False, skip_reason=f"low_confidence_{confidence}")
            alerts.send_telegram_alert(f"⏸ {action} blocked (conf {confidence} < {min_conf})")
            return

        # ── BUY or SELL ─────────────────────────────────────────────────
        _display_new_trade(analysis, action)
        alerts.play_signal_sound(action)

        # Telegram signal
        alerts.send_telegram_alert(
            f"*⚡ {action} Signal* (conf: {confidence}/10)\n"
            f"Entry: `${(analysis.get('entry_price') or price):,.2f}`\n"
            f"SL: `${(analysis.get('stop_loss') or 0):,.2f}`\n"
            f"TP: `${(analysis.get('take_profit') or 0):,.2f}`\n"
            f"_{reasoning}_"
        )

        # Confirm
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
            alerts.send_telegram_alert(f"✅ OPENED: {direction} @ ${entry:,.2f} (SL: ${sl:,.2f} TP: ${tp:,.2f})")
        else:
            trade_tracker.log_signal(analysis, trade_taken=False, skip_reason="declined")
        return

    # ══════════════════════════════════════════════════════════════════════
    #  STATE: IN POSITION (manage existing trade)
    # ══════════════════════════════════════════════════════════════════════

    # Force valid actions for in-position state
    if action in ["BUY", "SELL"]:
        # Claude sent a new trade signal while in position — interpret as REVERSE or HOLD
        current_dir = pos["direction"]
        if (action == "BUY" and current_dir == "SHORT") or (action == "SELL" and current_dir == "LONG"):
            print(f"  ⚠ Claude said '{action}' while in {current_dir} — interpreting as REVERSE")
            action = "REVERSE"
            # Copy entry/sl/tp from the signal to reverse fields
            analysis["reverse_entry"] = analysis.get("entry_price") or price
            analysis["reverse_sl"] = analysis.get("stop_loss") or 0
            analysis["reverse_tp"] = analysis.get("take_profit") or 0
        else:
            # Same direction as current position — just HOLD
            print(f"  ⚠ Claude said '{action}' but already in {current_dir} — treating as HOLD")
            action = "HOLD"

    if action == "NO_TRADE":
        action = "HOLD"  # NO_TRADE doesn't make sense when in position

    if action not in ["HOLD", "TRAIL_SL", "ADJUST_TP", "EXIT", "REVERSE"]:
        print(f"  ⚠ Unknown action '{action}' while in position — defaulting to HOLD")
        action = "HOLD"

    # ── HOLD ────────────────────────────────────────────────────────────
    if action == "HOLD":
        _display_hold(analysis)
        trade_tracker.log_signal(analysis, trade_taken=False, skip_reason="hold")

    # ── TRAIL_SL ────────────────────────────────────────────────────────
    elif action == "TRAIL_SL":
        new_sl = analysis.get("new_sl")
        if new_sl and isinstance(new_sl, (int, float)) and new_sl > 0:
            old_sl = pos["stop_loss"]
            entry = pos["entry_price"]
            valid = True

            if pos["direction"] == "LONG":
                # LONG: SL must only go up (tighter), never down
                if new_sl < old_sl:
                    print(f"  ⚠ Cannot trail SL lower for LONG (${new_sl:,.2f} < ${old_sl:,.2f})")
                    valid = False
                # Never set SL at or above current price (instant trigger)
                if new_sl >= price:
                    print(f"  ⚠ SL ${new_sl:,.2f} >= current price ${price:,.2f} — would trigger instantly")
                    valid = False
            elif pos["direction"] == "SHORT":
                # SHORT: SL must only go down (tighter), never up
                if new_sl > old_sl:
                    print(f"  ⚠ Cannot trail SL higher for SHORT (${new_sl:,.2f} > ${old_sl:,.2f})")
                    valid = False
                # Never set SL at or below current price (instant trigger)
                if new_sl <= price:
                    print(f"  ⚠ SL ${new_sl:,.2f} <= current price ${price:,.2f} — would trigger instantly")
                    valid = False

            if valid:
                position_manager.update_stop_loss(new_sl)
                print(f"  📐 SL: ${old_sl:,.2f} → ${new_sl:,.2f}")
                alerts.send_telegram_alert(f"📐 SL trailed → ${new_sl:,.2f}")
                trade_tracker.log_signal(analysis, trade_taken=True)
        else:
            print(f"  ⚠ TRAIL_SL but no valid new_sl provided")

    # ── ADJUST_TP ───────────────────────────────────────────────────────
    elif action == "ADJUST_TP":
        new_tp = analysis.get("new_tp")
        if new_tp and isinstance(new_tp, (int, float)) and new_tp > 0:
            position_manager.update_take_profit(new_tp)
            alerts.send_telegram_alert(f"🎯 TP adjusted → ${new_tp:,.2f}")
            trade_tracker.log_signal(analysis, trade_taken=True)
        else:
            print(f"  ⚠ ADJUST_TP but no valid new_tp provided")

    # ── EXIT ────────────────────────────────────────────────────────────
    elif action == "EXIT":
        _display_exit(analysis, pos)
        if config.AUTO_ACCEPT_TRADES or confidence >= 6:
            pnl = close_position_with_report(price, "claude_exit")
            alerts.play_signal_sound("SELL")
            trade_tracker.log_signal(analysis, trade_taken=True)
        else:
            print(f"  ⏸ EXIT blocked (conf {confidence} < 6)")
            trade_tracker.log_signal(analysis, trade_taken=False, skip_reason="low_conf")

    # ── REVERSE ─────────────────────────────────────────────────────────
    elif action == "REVERSE":
        _display_reverse(analysis, pos)
        if config.AUTO_ACCEPT_TRADES or confidence >= 7:
            # Close current position with P&L report
            old_dir = pos["direction"]
            pnl = close_position_with_report(price, "reversed")

            # Open new position in opposite direction
            new_dir = "SHORT" if old_dir == "LONG" else "LONG"
            new_entry = analysis.get("reverse_entry") or price
            new_sl = analysis.get("reverse_sl") or 0
            new_tp = analysis.get("reverse_tp") or 0

            position_manager.open_position(new_dir, new_entry, new_sl, new_tp, confidence, reasoning)
            alerts.send_telegram_alert(f"🔄 REVERSED → {new_dir} @ ${new_entry:,.2f} (SL: ${new_sl:,.2f} TP: ${new_tp:,.2f})")
            alerts.play_signal_sound("BUY" if new_dir == "LONG" else "SELL")
            trade_tracker.log_signal(analysis, trade_taken=True)
        else:
            print(f"  ⏸ REVERSE blocked (conf {confidence} < 7)")
            trade_tracker.log_signal(analysis, trade_taken=False, skip_reason="low_conf")


# =============================================================================
#  DISPLAY HELPERS (keep main logic clean)
# =============================================================================

def _display_no_trade(analysis):
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text
        from rich import box
        c = Console()
        t = Text()
        t.append(f"\n  👁 NO TRADE\n", style="bold")
        t.append(f"  {analysis.get('reasoning', '')}\n", style="white")
        c.print(Panel(t, title="👁 WATCHING", style="dim", box=box.ROUNDED))
    except ImportError:
        print(f"  👁 NO TRADE — {analysis.get('reasoning', '')}")


def _display_new_trade(analysis, action):
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text
        from rich import box
        c = Console()
        t = Text()
        arrow = "▲ BUY (LONG)" if action == "BUY" else "▼ SELL (SHORT)"
        style = "bold green" if action == "BUY" else "bold red"
        t.append(f"\n  {arrow}\n", style=style)
        t.append(f"  Conf: {analysis['confidence']}/10\n", style="yellow")
        t.append(f"  Entry: ${(analysis.get('entry_price') or 0):,.2f}\n", style="white")
        t.append(f"  SL: ${(analysis.get('stop_loss') or 0):,.2f}  TP: ${(analysis.get('take_profit') or 0):,.2f}\n", style="white")
        t.append(f"  {analysis.get('reasoning', '')}\n", style="dim")
        if config.AUTO_ACCEPT_TRADES:
            t.append(f"  ✅ AUTO-CONFIRMED\n", style="bold green")
        c.print(Panel(t, title=f"⚡ {action}", style="green" if action == "BUY" else "red", box=box.DOUBLE))
    except ImportError:
        print(f"  ⚡ {action} @ ${(analysis.get('entry_price') or 0):,.2f} conf:{analysis['confidence']}")


def _display_hold(analysis):
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text
        from rich import box
        c = Console()
        t = Text()
        t.append(f"\n  ✊ HOLD\n", style="bold cyan")
        t.append(f"  {analysis.get('reasoning', '')}\n", style="white")
        c.print(Panel(t, title="✊ HOLDING", style="cyan", box=box.ROUNDED))
    except ImportError:
        print(f"  ✊ HOLD — {analysis.get('reasoning', '')}")


def _display_exit(analysis, pos):
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text
        from rich import box
        c = Console()
        t = Text()
        t.append(f"\n  🚪 EXIT {pos['direction']}\n", style="bold red")
        t.append(f"  Conf: {analysis['confidence']}/10\n", style="yellow")
        t.append(f"  {analysis.get('reasoning', '')}\n", style="white")
        if config.AUTO_ACCEPT_TRADES:
            t.append(f"  ✅ AUTO-CONFIRMED\n", style="bold green")
        c.print(Panel(t, title="🚪 EXITING", style="red", box=box.DOUBLE))
    except ImportError:
        print(f"  🚪 EXIT — {analysis.get('reasoning', '')}")


def _display_reverse(analysis, pos):
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text
        from rich import box
        c = Console()
        t = Text()
        old = pos["direction"]
        new = "SHORT" if old == "LONG" else "LONG"
        t.append(f"\n  🔄 REVERSE: {old} → {new}\n", style="bold magenta")
        t.append(f"  Conf: {analysis['confidence']}/10\n", style="yellow")
        t.append(f"  {analysis.get('reasoning', '')}\n", style="white")
        if config.AUTO_ACCEPT_TRADES:
            t.append(f"  ✅ AUTO-CONFIRMED\n", style="bold green")
        c.print(Panel(t, title="🔄 REVERSING", style="magenta", box=box.DOUBLE))
    except ImportError:
        print(f"  🔄 REVERSE — {analysis.get('reasoning', '')}")


# =============================================================================
#  MAIN LOOP
# =============================================================================

def main():
    if not config.ANTHROPIC_API_KEY or config.ANTHROPIC_API_KEY == "your_anthropic_api_key_here":
        print("\n  ❌ Set ANTHROPIC_API_KEY in .env\n")
        sys.exit(1)

    print_startup_banner()
    cycle_count = 0

    while _running:
        cycle_count += 1
        try:
            run_cycle(cycle_count)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"\n  ❌ Error: {e}")
            import traceback
            traceback.print_exc()

        if not _running:
            break

        wait = config.BOT_CYCLE_SECONDS
        try:
            from rich.console import Console
            c = Console()
            for remaining in range(wait, 0, -1):
                if not _running:
                    break
                mins, secs = divmod(remaining, 60)
                c.print(f"  ⏱ {mins:02d}:{secs:02d}", end="\r", style="dim cyan")
                time.sleep(1)
        except KeyboardInterrupt:
            break

    # ── Shutdown: send daily summary ────────────────────────────────────
    pos = position_manager.get_current_position()
    print(f"\n  ✅ Bot stopped.")
    if pos:
        print(f"  📍 {pos['direction']} @ ${pos['entry_price']:,.2f} still open (saved)")

    daily = pnl_tracker.get_daily_pnl()
    if daily["trades_count"] > 0:
        summary = pnl_tracker.format_daily_summary()
        print(f"  📊 Today: ${daily['total_pnl_usd']:+,.4f} ({daily['trades_count']} trades, W:{daily['wins']} L:{daily['losses']})")
        alerts.send_telegram_alert(summary)
    print()


if __name__ == "__main__":
    main()
