"""
=============================================================================
 MAIN.PY — BTC BRAIN v3 Ultra (Full Auto-Trading)
=============================================================================
 End-to-end autonomous trading bot:
   • Fetches real account balance from Delta Exchange
   • Dynamic position sizing based on confidence + available funds
   • Adaptive scan cycles (60s indicator checks, Claude only when needed)
   • Pre-filter gate saves 60-80% on Claude API costs
   • Auto-executes trades on Delta Exchange (or paper mode)
   • BRACKET ORDERS: SL + TP placed on exchange (not just local)
   • Auto-trailing stops, SL/TP management
   • Daily drawdown limits, consecutive loss protection
   • Full P&L tracking, Telegram heartbeats
   • Zero manual intervention required
=============================================================================
"""

import sys
import os
import time
import signal as os_signal
import traceback
from datetime import datetime, timezone, timedelta

import config
import data_fetcher
import indicators
import claude_brain
import trade_tracker
import alerts
import position_manager
import pnl_tracker
import pre_filter
from bot_state import BotState
from delta_client import DeltaClient

IST = timezone(timedelta(hours=5, minutes=30))
_running = True


def shutdown_handler(signum, frame):
    global _running
    _running = False
    print("\n\n  🛑 Shutting down gracefully...\n")

os_signal.signal(os_signal.SIGINT, shutdown_handler)
os_signal.signal(os_signal.SIGTERM, shutdown_handler)


class TradingBot:
    """Full autonomous trading bot."""

    def __init__(self):
        self.state = BotState()
        self.delta = DeltaClient()
        self.cycle_count = 0
        self.last_price = 0
        self.last_computed = {}

    # ─── Startup ────────────────────────────────────────────────────────

    def startup(self):
        """Initialize bot, set leverage, fetch balance."""
        self._print_banner()

        # Set leverage on Delta
        print(f"  ⚙️  Setting leverage to {config.LEVERAGE}x...")
        self.delta.set_leverage()

        # Fetch and record starting balance
        ticker = self.delta.get_ticker()
        if ticker:
            self.last_price = ticker["mark_price"]
            bal = self.delta.get_available_balance_usd(self.last_price)
            if bal:
                print(f"  💰 Balance: ${bal['available_usd']:,.2f} "
                      f"({bal['available_btc']:.6f} BTC)")
                self.state.set_starting_balance(bal['available_usd'])
            else:
                print(f"  ⚠️  Could not fetch balance (paper mode or API issue)")

        # Check for existing position — sync with Delta Exchange
        self._sync_position_with_exchange()

        # Send startup alert
        alerts.send_telegram_alert(
            f"🚀 *BTC BRAIN v3 Started*\n"
            f"Mode: `{config.TRADING_MODE}`\n"
            f"BTC: `${self.last_price:,.2f}`"
        )
        print()

    def _sync_position_with_exchange(self):
        """Sync local position state with what Delta Exchange actually shows."""
        local_pos = position_manager.get_current_position()
        
        if config.TRADING_MODE == "paper":
            if local_pos:
                print(f"  📍 RESUMING: {local_pos['direction']} @ ${local_pos['entry_price']:,.2f}")
            else:
                print(f"  📍 Starting FLAT")
            return
        
        # In LIVE mode: check what Delta actually has
        exchange_pos = self.delta.get_position_for_product()
        
        if exchange_pos and abs(exchange_pos.get("size", 0)) > 0:
            print(f"  📍 EXCHANGE POSITION: {exchange_pos['direction']} "
                  f"size={abs(exchange_pos['size'])} @ ${exchange_pos['entry_price']:,.2f}")
            if local_pos:
                print(f"  📍 Local matches — resuming")
            else:
                print(f"  ⚠️  EXCHANGE HAS POSITION but local state is FLAT!")
                print(f"  ⚠️  Recording exchange position locally")
                position_manager.open_position(
                    exchange_pos['direction'], exchange_pos['entry_price'],
                    0, 0, 0, "recovered_from_exchange",
                    contracts=abs(exchange_pos['size'])
                )
        else:
            if local_pos:
                print(f"  ⚠️  Local shows position but EXCHANGE IS FLAT — clearing local state")
                position_manager._clear_position()
            print(f"  📍 Starting FLAT")

    def _print_banner(self):
        mode = "🔴 LIVE" if config.TRADING_MODE == "live" else "📝 PAPER"
        print(f"\n{'='*60}")
        print(f"  ⚡ BTC BRAIN v3 Ultra — Full Auto-Trading Bot")
        print(f"  Mode: {mode} | Model: {config.CLAUDE_MODEL}")
        print(f"  Leverage: {config.LEVERAGE}x | Min Conf: {config.MIN_CONFIDENCE}")
        print(f"  Scan: {config.BASE_SCAN_INTERVAL}s | Claude Min: {config.MIN_CLAUDE_INTERVAL}s")
        print(f"  Daily Drawdown Limit: {config.DAILY_MAX_DRAWDOWN_PCT}%")
        print(f"  Max Consecutive Losses: {config.MAX_CONSECUTIVE_LOSSES}")
        print(f"{'='*60}")

    def _shutdown(self):
        print("\n  📊 Final Summary:")
        stats = self.state.get_daily_stats()
        if stats["trades_count"] > 0:
            print(f"  P&L: ${stats['total_pnl_usd']:+,.4f} | "
                  f"Trades: {stats['trades_count']} | W:{stats['wins']} L:{stats['losses']}")
        print(f"  Claude calls today: {self.state.claude_calls_today()}")

        summary = (
            f"📊 *BTC BRAIN v3 — Shutdown*\n"
            f"P&L: `${stats['total_pnl_usd']:+,.4f}`\n"
            f"Trades: {stats['trades_count']} | Claude calls: {self.state.claude_calls_today()}"
        )
        alerts.send_telegram_alert(summary)
        print("  👋 Goodbye!\n")

    # ─── Main Loop ──────────────────────────────────────────────────────

    def run(self):
        """Main bot loop with adaptive timing."""
        self.startup()

        while _running:
            self.cycle_count += 1
            cycle_start = time.time()

            try:
                self._run_cycle()
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"\n  ❌ Cycle error: {e}")
                traceback.print_exc()

            if not _running:
                break

            # Adaptive sleep — shorter if in position
            pos = position_manager.get_current_position()
            sleep_time = 30 if pos else config.BASE_SCAN_INTERVAL
            elapsed = time.time() - cycle_start
            actual_sleep = max(10, sleep_time - elapsed)

            print(f"  ⏳ Next scan in {actual_sleep:.0f}s...")
            for _ in range(int(actual_sleep)):
                if not _running:
                    break
                time.sleep(1)

        self._shutdown()

    def _run_cycle(self):
        """One complete bot cycle."""
        now_str = datetime.now(IST).strftime('%I:%M:%S %p IST')
        pos = position_manager.get_current_position()
        pos_str = position_manager.get_position_summary(self.last_price) if pos else "FLAT"
        stats = self.state.get_daily_stats()
        daily_str = f"${stats['total_pnl_usd']:+,.2f}" if stats["trades_count"] > 0 else ""
        claude_str = f"API:{self.state.claude_calls_today()}"

        print(f"\n  ── #{self.cycle_count} │ {now_str} │ 📍{pos_str} │ 💰{daily_str} │ {claude_str} ──")

        # ── Heartbeat ───────────────────────────────────────────────────
        if self.state.should_send_heartbeat():
            alerts.send_heartbeat(
                self.last_price, pos_str, stats, self.state.claude_calls_today()
            )
            self.state.record_heartbeat()

        # ── Fetch data ──────────────────────────────────────────────────
        all_data = data_fetcher.fetch_all_data()
        ticker = all_data.get("delta_ticker")
        if not ticker:
            print(f"  ❌ No ticker data")
            return

        price = ticker["mark_price"]
        self.last_price = price

        # ── Compute indicators (cheap — every cycle) ────────────────────
        computed = claude_brain.compute_all_indicators(all_data)
        self.last_computed = computed

        # ── In Position: Check SL/TP/Expiry + Auto-Trail ────────────────
        pos = position_manager.get_current_position()
        if pos:
            # Check SL/TP hit (software backup — exchange SL/TP should handle this)
            hit = position_manager.check_sl_tp_hit(price)
            if hit == "sl_hit":
                print(f"\n  ⚠️  STOP-LOSS HIT! (software check)")
                self._close_trade(price, "sl_hit")
                return
            elif hit == "tp_hit":
                print(f"\n  🎯 TAKE-PROFIT HIT! (software check)")
                self._close_trade(price, "tp_hit")
                return

            # Check trade expiry
            if position_manager.is_trade_expired():
                print(f"\n  ⏰ Trade expired ({config.MAX_TRADE_DURATION_MINUTES}min)")
                self._close_trade(price, "expired")
                return

            # Verify position still exists on exchange (live mode)
            if config.TRADING_MODE == "live":
                exchange_pos = self.delta.get_position_for_product()
                if exchange_pos is None or abs(exchange_pos.get("size", 0)) == 0:
                    print(f"\n  ⚠️  Position closed on exchange (SL/TP hit on exchange)")
                    # Position was closed by exchange SL/TP order
                    self._handle_exchange_closed_position(pos, price)
                    return

            # Auto-trail stop loss
            self._auto_trail_stop(pos, price)

        # ── Safety Checks ───────────────────────────────────────────────
        in_cooldown, cooldown_min = self.state.is_in_cooldown()
        if in_cooldown and not pos:
            print(f"  ⏸ Loss cooldown ({cooldown_min}m remaining)")
            return

        if self.state.is_daily_drawdown_exceeded() and not pos:
            print(f"  🛑 Daily drawdown limit hit — no new trades")
            return

        # ── Pre-Filter: Should we call Claude? ──────────────────────────
        has_position = pos is not None
        should_call, reason = pre_filter.should_call_claude(
            computed, self.state, has_position
        )

        if not should_call:
            print(f"  ⏭ Skip Claude: {reason}")
            return

        print(f"  ✅ Pre-filter passed: {reason}")

        # ── Call Claude ─────────────────────────────────────────────────
        self.state.record_claude_call()
        analysis = claude_brain.analyze_with_claude(
            all_data, current_position=pos, bot_state=self.state
        )

        if analysis is None:
            print(f"  ❌ Claude analysis failed")
            return

        action = analysis["action"]
        confidence = analysis["confidence"]
        reasoning = analysis.get("reasoning", "")

        # Record signal in persistent state
        self.state.add_signal(analysis)

        # ── FLAT: Handle entry decisions ────────────────────────────────
        if pos is None:
            self._handle_flat(analysis, all_data, price)
        # ── IN POSITION: Handle management decisions ────────────────────
        else:
            self._handle_in_position(analysis, pos, price)

    # ─── Handle Exchange-Closed Position ────────────────────────────────

    def _handle_exchange_closed_position(self, local_pos, current_price):
        """Handle when exchange closed the position (SL/TP hit on exchange side)."""
        direction = local_pos["direction"]
        entry = local_pos["entry_price"]
        sl = local_pos.get("stop_loss", 0)
        tp = local_pos.get("take_profit", 0)
        contracts = local_pos.get("contracts", 1)

        # Determine likely exit price based on which was closer
        if direction == "LONG":
            sl_dist = abs(current_price - sl) if sl > 0 else float('inf')
            tp_dist = abs(current_price - tp) if tp > 0 else float('inf')
        else:
            sl_dist = abs(current_price - sl) if sl > 0 else float('inf')
            tp_dist = abs(current_price - tp) if tp > 0 else float('inf')

        if tp_dist < sl_dist:
            exit_price = tp
            reason = "tp_hit_exchange"
            print(f"  🎯 Take-profit hit on exchange! TP=${tp:,.2f}")
        else:
            exit_price = sl
            reason = "sl_hit_exchange"
            print(f"  ⚠️  Stop-loss hit on exchange! SL=${sl:,.2f}")

        if exit_price <= 0:
            exit_price = current_price

        # Record locally
        closed = position_manager.close_position(reason, exit_price)
        if not closed:
            position_manager._clear_position()
            return

        # Calculate and record P&L
        pnl = pnl_tracker.calculate_trade_pnl(
            direction=closed["direction"],
            entry_price=closed["entry_price"],
            exit_price=exit_price,
            contracts=contracts,
            leverage=config.LEVERAGE,
        )

        pnl_tracker.log_closed_trade(pnl, close_reason=reason)
        self.state.update_daily_pnl(pnl["net_pnl_usd"])

        if pnl["result"] == "WIN":
            self.state.record_win()
            self.state.mark_last_signal_outcome(closed["direction"], "win")
        elif pnl["result"] == "LOSS":
            self.state.record_loss(closed["direction"])
            self.state.mark_last_signal_outcome(closed["direction"], "loss")
        else:
            self.state.record_breakeven()
            self.state.mark_last_signal_outcome(closed["direction"], "breakeven")

        terminal_report, telegram_report = pnl_tracker.format_trade_report(pnl, reason)
        print(terminal_report)
        alerts.send_telegram_alert(telegram_report)

    # ─── FLAT State Handler ─────────────────────────────────────────────

    def _handle_flat(self, analysis, all_data, price):
        action = analysis["action"]
        confidence = analysis["confidence"]
        reasoning = analysis.get("reasoning", "")

        if action == "NO_TRADE":
            print(f"  👁 NO_TRADE (conf:{confidence}) — {reasoning[:100]}")
            trade_tracker.log_signal(analysis, trade_taken=False, skip_reason="no_trade")
            return

        if action not in ["BUY", "SELL"]:
            return

        # Confidence gate
        if confidence < config.MIN_CONFIDENCE:
            print(f"  ⚠️  {action} blocked — conf {confidence} < {config.MIN_CONFIDENCE}")
            trade_tracker.log_signal(analysis, trade_taken=False, skip_reason=f"low_conf_{confidence}")
            return

        # Don't re-enter same direction after loss
        if (self.state.last_trade_was_loss and
                self.state.last_trade_direction and
                ((action == "BUY" and self.state.last_trade_direction == "LONG") or
                 (action == "SELL" and self.state.last_trade_direction == "SHORT"))):
            print(f"  ⚠️  {action} blocked — last {self.state.last_trade_direction} was a loss")
            trade_tracker.log_signal(analysis, trade_taken=False, skip_reason="post_loss_same_dir")
            return

        # ── Execute Trade ───────────────────────────────────────────────
        print(f"\n  ⚡ {action} SIGNAL — Confidence: {confidence}/10")
        print(f"  📝 {reasoning[:150]}")

        direction = "LONG" if action == "BUY" else "SHORT"
        entry = analysis.get("entry_price") or price
        sl = analysis.get("stop_loss") or 0
        tp = analysis.get("take_profit") or 0

        # Dynamic position sizing
        bal = self.delta.get_available_balance_usd(price)
        available_usd = bal["available_usd"] if bal else 100
        sizing = indicators.calculate_dynamic_position_size(
            entry, confidence, available_usd
        )
        contracts = sizing["contracts"]

        print(f"  📊 Size: {contracts} contracts ({sizing['usage_pct']}% of ${available_usd:,.0f})")
        print(f"  Entry: ${entry:,.2f} | SL: ${sl:,.2f} | TP: ${tp:,.2f}")

        # ═══ CRITICAL FIX: Use bracket order (SL + TP on exchange) ═══
        side = "buy" if action == "BUY" else "sell"

        if config.TRADING_MODE == "live" and sl > 0 and tp > 0:
            # LIVE MODE: Place bracket order with SL + TP on Delta Exchange
            print(f"  🔒 Placing BRACKET order (SL+TP on exchange)...")
            bracket_result = self.delta.place_bracket_order(side, contracts, sl, tp)

            if bracket_result is None:
                print(f"  ❌ Bracket order failed!")
                trade_tracker.log_signal(analysis, trade_taken=False, skip_reason="order_failed")
                return

            actual_entry = bracket_result.get("entry_price") or entry
            order_id = bracket_result.get("entry", {}).get("order_id", "")

            # Log SL/TP order status
            sl_order = bracket_result.get("stop_loss_order")
            tp_order = bracket_result.get("take_profit_order")
            if sl_order:
                print(f"  ✅ SL order placed: ${sl:,.2f} (ID: {sl_order.get('order_id', '?')})")
            else:
                print(f"  ⚠️  SL order FAILED — falling back to software SL")
                alerts.send_telegram_alert(f"⚠️ *WARNING*: SL order failed to place on exchange! Software SL active.")

            if tp_order:
                print(f"  ✅ TP order placed: ${tp:,.2f} (ID: {tp_order.get('order_id', '?')})")
            else:
                print(f"  ⚠️  TP order FAILED — falling back to software TP")
                alerts.send_telegram_alert(f"⚠️ *WARNING*: TP order failed to place on exchange! Software TP active.")
        else:
            # PAPER MODE or no SL/TP: Plain market order
            order_result = self.delta.place_market_order(side, contracts)

            if order_result is None:
                print(f"  ❌ Order failed!")
                trade_tracker.log_signal(analysis, trade_taken=False, skip_reason="order_failed")
                return

            actual_entry = order_result.get("avg_fill_price") or entry
            order_id = order_result.get("order_id", "")

        # Record position locally
        position_manager.open_position(
            direction, actual_entry, sl, tp, confidence, reasoning,
            contracts=contracts, order_id=order_id
        )

        trade_tracker.log_signal(analysis, trade_taken=True)
        trade_tracker.log_trade(analysis, contracts=contracts, order_id=order_id)

        alerts.play_signal_sound(action)
        alerts.send_telegram_alert(
            f"⚡ *{action}* (conf:{confidence}/10)\n"
            f"Entry: `${actual_entry:,.2f}` | SL: `${sl:,.2f}` | TP: `${tp:,.2f}`\n"
            f"Size: {contracts} contracts\n"
            f"SL/TP: {'✅ ON EXCHANGE' if config.TRADING_MODE == 'live' else '📝 Software only'}\n"
            f"_{reasoning[:200]}_"
        )

    # ─── In Position Handler ────────────────────────────────────────────

    def _handle_in_position(self, analysis, pos, price):
        action = analysis["action"]
        confidence = analysis["confidence"]
        reasoning = analysis.get("reasoning", "")

        # Normalize: if Claude says BUY/SELL while in position
        if action in ["BUY", "SELL"]:
            current_dir = pos["direction"]
            if (action == "BUY" and current_dir == "SHORT") or (action == "SELL" and current_dir == "LONG"):
                action = "REVERSE"
                analysis["action"] = "REVERSE"
            else:
                action = "HOLD"
        if action == "NO_TRADE":
            action = "HOLD"

        print(f"  🔄 {action} (conf:{confidence}) — {reasoning[:100]}")

        if action == "HOLD":
            pass

        elif action == "TRAIL_SL":
            new_sl = analysis.get("stop_loss")
            if new_sl:
                old_sl = pos["stop_loss"]
                # Only trail in the right direction
                if pos["direction"] == "LONG" and new_sl > old_sl:
                    position_manager.update_stop_loss(new_sl)
                    # Update SL on exchange too
                    if config.TRADING_MODE == "live":
                        self._update_exchange_sl(pos, new_sl)
                    alerts.send_telegram_alert(f"🔺 SL → ${new_sl:,.2f}")
                    print(f"  🔺 SL trailed: ${old_sl:,.2f} → ${new_sl:,.2f}")
                elif pos["direction"] == "SHORT" and new_sl < old_sl:
                    position_manager.update_stop_loss(new_sl)
                    if config.TRADING_MODE == "live":
                        self._update_exchange_sl(pos, new_sl)
                    alerts.send_telegram_alert(f"🔻 SL → ${new_sl:,.2f}")
                    print(f"  🔻 SL trailed: ${old_sl:,.2f} → ${new_sl:,.2f}")

        elif action == "ADJUST_TP":
            new_tp = analysis.get("take_profit")
            if new_tp:
                position_manager.update_take_profit(new_tp)
                if config.TRADING_MODE == "live":
                    self._update_exchange_tp(pos, new_tp)
                print(f"  🎯 TP adjusted → ${new_tp:,.2f}")

        elif action == "EXIT":
            print(f"  🚪 Claude says EXIT")
            self._close_trade(price, "claude_exit")

        elif action == "REVERSE":
            if confidence >= 7:
                print(f"  🔄 REVERSING position...")
                old_dir = pos["direction"]
                self._close_trade(price, "reverse")

                new_dir = "SHORT" if old_dir == "LONG" else "LONG"
                new_side = "sell" if new_dir == "SHORT" else "buy"
                new_entry = analysis.get("entry_price") or price
                new_sl = analysis.get("stop_loss") or 0
                new_tp = analysis.get("take_profit") or 0

                bal = self.delta.get_available_balance_usd(price)
                available_usd = bal["available_usd"] if bal else 100
                sizing = indicators.calculate_dynamic_position_size(
                    new_entry, confidence, available_usd
                )

                # Use bracket order for the new position too
                if config.TRADING_MODE == "live" and new_sl > 0 and new_tp > 0:
                    bracket_result = self.delta.place_bracket_order(new_side, sizing["contracts"], new_sl, new_tp)
                    if bracket_result:
                        actual_entry = bracket_result.get("entry_price") or new_entry
                        position_manager.open_position(
                            new_dir, actual_entry, new_sl, new_tp, confidence, reasoning,
                            contracts=sizing["contracts"],
                            order_id=bracket_result.get("entry", {}).get("order_id", "")
                        )
                        alerts.send_telegram_alert(
                            f"🔄 REVERSED → {new_dir} @ ${actual_entry:,.2f}\n"
                            f"SL: `${new_sl:,.2f}` TP: `${new_tp:,.2f}` (ON EXCHANGE)"
                        )
                else:
                    order_result = self.delta.place_market_order(new_side, sizing["contracts"])
                    if order_result:
                        actual_entry = order_result.get("avg_fill_price") or new_entry
                        position_manager.open_position(
                            new_dir, actual_entry, new_sl, new_tp, confidence, reasoning,
                            contracts=sizing["contracts"],
                            order_id=order_result.get("order_id", "")
                        )
                        alerts.send_telegram_alert(
                            f"🔄 REVERSED → {new_dir} @ ${actual_entry:,.2f}"
                        )
            else:
                print(f"  ⏸ REVERSE blocked (conf {confidence} < 7)")

        trade_tracker.log_signal(analysis, trade_taken=(action in ["EXIT", "REVERSE"]))

    # ─── Update Exchange SL/TP ──────────────────────────────────────────

    def _update_exchange_sl(self, pos, new_sl):
        """Cancel existing stop orders and place new SL on exchange."""
        try:
            contracts = pos.get("contracts", 1)
            sl_side = "sell" if pos["direction"] == "LONG" else "buy"
            # Cancel all existing stop orders first
            self.delta.cancel_all_orders()
            # Place new SL
            sl_result = self.delta._place_stop_order(
                sl_side, contracts, new_sl, reduce_only=True, order_type="stop_loss"
            )
            # Re-place TP
            tp = pos.get("take_profit", 0)
            if tp > 0:
                self.delta._place_stop_order(
                    sl_side, contracts, tp, reduce_only=True, order_type="take_profit"
                )
            if sl_result:
                print(f"  ✅ Exchange SL updated to ${new_sl:,.2f}")
            else:
                print(f"  ⚠️  Failed to update SL on exchange!")
        except Exception as e:
            print(f"  ⚠️  Exchange SL update error: {e}")

    def _update_exchange_tp(self, pos, new_tp):
        """Cancel existing TP orders and place new TP on exchange."""
        try:
            contracts = pos.get("contracts", 1)
            tp_side = "sell" if pos["direction"] == "LONG" else "buy"
            # Cancel all and re-place both
            self.delta.cancel_all_orders()
            # Re-place SL
            sl = pos.get("stop_loss", 0)
            if sl > 0:
                self.delta._place_stop_order(
                    tp_side, contracts, sl, reduce_only=True, order_type="stop_loss"
                )
            # Place new TP
            tp_result = self.delta._place_stop_order(
                tp_side, contracts, new_tp, reduce_only=True, order_type="take_profit"
            )
            if tp_result:
                print(f"  ✅ Exchange TP updated to ${new_tp:,.2f}")
        except Exception as e:
            print(f"  ⚠️  Exchange TP update error: {e}")

    # ─── Close Trade ────────────────────────────────────────────────────

    def _close_trade(self, current_price, reason):
        """Close position on Delta Exchange and record P&L."""
        pos = position_manager.get_current_position()
        if pos is None:
            return

        # Close on Delta (with retry)
        close_result = None
        for attempt in range(3):
            close_result = self.delta.close_position()
            if close_result is not None:
                break
            print(f"  ⚠️  Close attempt {attempt+1}/3 failed, retrying...")
            time.sleep(1)

        actual_exit = current_price
        if close_result and close_result.get("avg_fill_price"):
            actual_exit = close_result["avg_fill_price"]

        # Verify position is actually closed on exchange (live mode)
        if config.TRADING_MODE == "live":
            time.sleep(1)  # Give exchange a moment
            exchange_pos = self.delta.get_position_for_product()
            if exchange_pos and abs(exchange_pos.get("size", 0)) > 0:
                print(f"  🚨 CRITICAL: Position STILL OPEN on exchange after close!")
                print(f"  🚨 Retrying with force close...")
                alerts.send_telegram_alert(
                    f"🚨 *CRITICAL*: Position still open after close attempt!\n"
                    f"Retrying force close..."
                )
                # Force close retry
                self.delta.cancel_all_orders()
                time.sleep(0.5)
                close_result = self.delta.close_position()
                if close_result and close_result.get("avg_fill_price"):
                    actual_exit = close_result["avg_fill_price"]
                    print(f"  ✅ Force close succeeded")
                else:
                    print(f"  🚨🚨 FORCE CLOSE FAILED — MANUAL INTERVENTION NEEDED!")
                    alerts.send_telegram_alert(
                        f"🚨🚨 *CRITICAL*: Cannot close position!\n"
                        f"Direction: {pos['direction']}\n"
                        f"MANUAL CLOSE REQUIRED on Delta Exchange!"
                    )

        # Record locally
        closed = position_manager.close_position(reason, actual_exit)
        if not closed:
            return

        # Calculate P&L
        contracts = closed.get("contracts", 1)
        pnl = pnl_tracker.calculate_trade_pnl(
            direction=closed["direction"],
            entry_price=closed["entry_price"],
            exit_price=actual_exit,
            contracts=contracts,
            leverage=config.LEVERAGE,
        )

        pnl_tracker.log_closed_trade(pnl, close_reason=reason)
        self.state.update_daily_pnl(pnl["net_pnl_usd"])

        # Update state
        if pnl["result"] == "WIN":
            self.state.record_win()
            self.state.mark_last_signal_outcome(closed["direction"], "win")
        elif pnl["result"] == "LOSS":
            self.state.record_loss(closed["direction"])
            self.state.mark_last_signal_outcome(closed["direction"], "loss")
        else:
            self.state.record_breakeven()
            self.state.mark_last_signal_outcome(closed["direction"], "breakeven")

        # Report
        terminal_report, telegram_report = pnl_tracker.format_trade_report(pnl, reason)
        print(terminal_report)
        alerts.send_telegram_alert(telegram_report)
        alerts.play_signal_sound("SELL" if pnl["result"] == "LOSS" else "BUY")

    # ─── Auto-Trail Stop ────────────────────────────────────────────────

    def _auto_trail_stop(self, pos, current_price):
        entry = pos["entry_price"]
        sl = pos["stop_loss"]
        direction = pos["direction"]

        if direction == "LONG":
            pnl_pct = (current_price - entry) / entry * 100
        else:
            pnl_pct = (entry - current_price) / entry * 100

        # Trail to breakeven
        if pnl_pct >= config.TRAIL_TO_BREAKEVEN_PCT:
            if direction == "LONG" and sl < entry:
                new_sl = entry + (entry * 0.0001)  # tiny buffer above entry
                position_manager.update_stop_loss(new_sl)
                if config.TRADING_MODE == "live":
                    self._update_exchange_sl(pos, new_sl)
                alerts.send_telegram_alert(f"🔒 SL → breakeven ${new_sl:,.2f}")
                print(f"  🔒 SL trailed to breakeven: ${new_sl:,.2f}")
            elif direction == "SHORT" and sl > entry:
                new_sl = entry - (entry * 0.0001)
                position_manager.update_stop_loss(new_sl)
                if config.TRADING_MODE == "live":
                    self._update_exchange_sl(pos, new_sl)
                alerts.send_telegram_alert(f"🔒 SL → breakeven ${new_sl:,.2f}")
                print(f"  🔒 SL trailed to breakeven: ${new_sl:,.2f}")

        # Lock profits
        if pnl_pct > config.TRAIL_TO_BREAKEVEN_PCT:
            lock_pct = pnl_pct * config.TRAIL_PROFIT_LOCK_RATIO
            if direction == "LONG":
                lock_sl = entry * (1 + lock_pct / 100)
                if lock_sl > sl:
                    position_manager.update_stop_loss(lock_sl)
                    if config.TRADING_MODE == "live":
                        self._update_exchange_sl(pos, lock_sl)
                    alerts.send_telegram_alert(f"📈 SL → ${lock_sl:,.2f} (locking {lock_pct:.2f}%)")
                    print(f"  📈 SL locked profits: ${lock_sl:,.2f}")
            else:
                lock_sl = entry * (1 - lock_pct / 100)
                if lock_sl < sl:
                    position_manager.update_stop_loss(lock_sl)
                    if config.TRADING_MODE == "live":
                        self._update_exchange_sl(pos, lock_sl)
                    alerts.send_telegram_alert(f"📉 SL → ${lock_sl:,.2f} (locking {lock_pct:.2f}%)")
                    print(f"  📉 SL locked profits: ${lock_sl:,.2f}")


# =============================================================================
#  ENTRY POINT
# =============================================================================

def main():
    # Validate essentials
    if not config.ANTHROPIC_API_KEY or "your_" in config.ANTHROPIC_API_KEY:
        print("\n  ❌ ANTHROPIC_API_KEY not set in .env\n")
        sys.exit(1)

    if config.TRADING_MODE == "live":
        if not config.DELTA_API_KEY or "your_" in config.DELTA_API_KEY:
            print("\n  ❌ DELTA_API_KEY required for live trading. "
                  "Set TRADING_MODE=paper for simulation.\n")
            sys.exit(1)

    bot = TradingBot()
    bot.run()


if __name__ == "__main__":
    main()
