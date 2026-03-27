"""
=============================================================================
 BOT_STATE.PY — Persistent Bot State Manager
=============================================================================
 Everything that needs to survive restarts:
   • Signal history (fed back to Claude)
   • Trade history with outcomes
   • Consecutive loss counter
   • Cooldown timestamps
   • Last Claude call timestamp
   • Daily drawdown tracking
=============================================================================
"""

import json
import os
import time
import tempfile
from datetime import datetime, timezone, timedelta

import config

IST = timezone(timedelta(hours=5, minutes=30))


def _atomic_write(filepath, data):
    """Atomic JSON write — write to temp then rename."""
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=".", suffix=".tmp")
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, filepath)
    except Exception as e:
        print(f"  [WARN] Atomic write to {filepath} failed: {e}")
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def _load_json(filepath, default=None):
    """Load JSON file, return default on failure."""
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return default if default is not None else {}


class BotState:
    """Manages all persistent bot state."""

    def __init__(self):
        self.state_file = config.BOT_STATE_FILE
        self.signal_history_file = config.SIGNAL_HISTORY_FILE
        self._state = self._load_state()
        self._signal_history = self._load_signal_history()

    def _load_state(self):
        default = {
            "last_claude_call": 0,
            "consecutive_losses": 0,
            "loss_cooldown_until": 0,
            "daily_stats": {
                "date": "",
                "total_pnl_usd": 0,
                "trades_count": 0,
                "wins": 0,
                "losses": 0,
                "breakevens": 0,
                "starting_balance_usd": 0,
            },
            "last_trade_direction": None,
            "last_trade_was_loss": False,
            "total_claude_calls_today": 0,
            "total_claude_calls_date": "",
            "last_heartbeat": 0,
        }
        loaded = _load_json(self.state_file, default)
        # Merge missing keys from default
        for k, v in default.items():
            if k not in loaded:
                loaded[k] = v
        return loaded

    def _load_signal_history(self):
        return _load_json(self.signal_history_file, [])

    def save(self):
        """Persist state to disk."""
        _atomic_write(self.state_file, self._state)

    def save_signal_history(self):
        """Persist signal history to disk."""
        _atomic_write(self.signal_history_file, self._signal_history)

    # ─── Claude Call Tracking ───────────────────────────────────────────

    @property
    def last_claude_call(self):
        return self._state.get("last_claude_call", 0)

    def record_claude_call(self):
        """Record that we just called Claude."""
        now = time.time()
        self._state["last_claude_call"] = now
        today = datetime.now(IST).strftime("%Y-%m-%d")
        if self._state.get("total_claude_calls_date") != today:
            self._state["total_claude_calls_date"] = today
            self._state["total_claude_calls_today"] = 0
        self._state["total_claude_calls_today"] += 1
        self.save()

    def seconds_since_last_claude_call(self):
        last = self._state.get("last_claude_call", 0)
        return time.time() - last if last > 0 else float("inf")

    def claude_calls_today(self):
        today = datetime.now(IST).strftime("%Y-%m-%d")
        if self._state.get("total_claude_calls_date") != today:
            return 0
        return self._state.get("total_claude_calls_today", 0)

    # ─── Signal History ─────────────────────────────────────────────────

    def add_signal(self, signal_data):
        """Add a signal to persistent history."""
        self._signal_history.append({
            "time": signal_data.get("time", ""),
            "timestamp": signal_data.get("timestamp", int(time.time())),
            "decision": signal_data.get("action", ""),
            "confidence": signal_data.get("confidence", 0),
            "entry_price": signal_data.get("entry_price", 0),
            "stop_loss": signal_data.get("stop_loss", 0),
            "take_profit": signal_data.get("take_profit", 0),
            "reasoning": (signal_data.get("reasoning", "") or "")[:200],
            "outcome": "pending",
        })
        # Keep last 20
        if len(self._signal_history) > 20:
            self._signal_history = self._signal_history[-20:]
        self.save_signal_history()

    def get_recent_signals(self, count=10):
        return self._signal_history[-count:]

    def mark_last_signal_outcome(self, direction, outcome):
        """Mark the last signal of given direction with outcome."""
        for sig in reversed(self._signal_history):
            if sig.get("decision") == direction and sig.get("outcome") == "pending":
                sig["outcome"] = outcome
                self.save_signal_history()
                return True
        return False

    def get_last_signal(self):
        return self._signal_history[-1] if self._signal_history else None

    # ─── Loss Tracking ──────────────────────────────────────────────────

    @property
    def consecutive_losses(self):
        return self._state.get("consecutive_losses", 0)

    def record_win(self):
        self._state["consecutive_losses"] = 0
        self._state["last_trade_was_loss"] = False
        self._update_daily_stats("win")
        self.save()

    def record_loss(self, direction):
        self._state["consecutive_losses"] = self._state.get("consecutive_losses", 0) + 1
        self._state["last_trade_direction"] = direction
        self._state["last_trade_was_loss"] = True
        self._update_daily_stats("loss")

        # Check if we need cooldown
        if self._state["consecutive_losses"] >= config.MAX_CONSECUTIVE_LOSSES:
            cooldown_until = time.time() + (config.LOSS_COOLDOWN_MINUTES * 60)
            self._state["loss_cooldown_until"] = cooldown_until
            print(f"  🛑 {config.MAX_CONSECUTIVE_LOSSES} consecutive losses — "
                  f"cooldown until {datetime.fromtimestamp(cooldown_until, IST).strftime('%I:%M %p IST')}")
        self.save()

    def record_breakeven(self):
        self._state["last_trade_was_loss"] = False
        self._update_daily_stats("breakeven")
        self.save()

    @property
    def last_trade_direction(self):
        return self._state.get("last_trade_direction")

    @property
    def last_trade_was_loss(self):
        return self._state.get("last_trade_was_loss", False)

    # ─── Cooldown ───────────────────────────────────────────────────────

    def is_in_cooldown(self):
        """Check if bot is in loss cooldown."""
        cooldown_until = self._state.get("loss_cooldown_until", 0)
        if time.time() < cooldown_until:
            remaining = int(cooldown_until - time.time()) // 60
            return True, remaining
        return False, 0

    # ─── Daily Stats ────────────────────────────────────────────────────

    def _ensure_daily_reset(self):
        today = datetime.now(IST).strftime("%Y-%m-%d")
        if self._state["daily_stats"].get("date") != today:
            self._state["daily_stats"] = {
                "date": today,
                "total_pnl_usd": 0,
                "trades_count": 0,
                "wins": 0,
                "losses": 0,
                "breakevens": 0,
                "starting_balance_usd": self._state["daily_stats"].get("starting_balance_usd", 0),
            }

    def _update_daily_stats(self, result):
        self._ensure_daily_reset()
        stats = self._state["daily_stats"]
        stats["trades_count"] += 1
        if result == "win":
            stats["wins"] += 1
        elif result == "loss":
            stats["losses"] += 1
        else:
            stats["breakevens"] += 1

    def update_daily_pnl(self, pnl_usd):
        self._ensure_daily_reset()
        self._state["daily_stats"]["total_pnl_usd"] = round(
            self._state["daily_stats"]["total_pnl_usd"] + pnl_usd, 4
        )
        self.save()

    def set_starting_balance(self, balance_usd):
        self._ensure_daily_reset()
        if self._state["daily_stats"]["starting_balance_usd"] == 0:
            self._state["daily_stats"]["starting_balance_usd"] = balance_usd
            self.save()

    def get_daily_stats(self):
        self._ensure_daily_reset()
        return self._state["daily_stats"]

    def is_daily_drawdown_exceeded(self):
        """Check if daily loss exceeds max drawdown limit."""
        stats = self.get_daily_stats()
        starting = stats.get("starting_balance_usd", 0)
        if starting <= 0:
            return False
        pnl = stats.get("total_pnl_usd", 0)
        if pnl >= 0:
            return False
        drawdown_pct = abs(pnl) / starting * 100
        return drawdown_pct >= config.DAILY_MAX_DRAWDOWN_PCT

    # ─── Heartbeat ──────────────────────────────────────────────────────

    def should_send_heartbeat(self):
        last = self._state.get("last_heartbeat", 0)
        interval = config.HEARTBEAT_INTERVAL_MINUTES * 60
        return (time.time() - last) >= interval

    def record_heartbeat(self):
        self._state["last_heartbeat"] = time.time()
        self.save()

    # ─── Summary ────────────────────────────────────────────────────────

    def get_status_summary(self):
        stats = self.get_daily_stats()
        in_cooldown, cooldown_min = self.is_in_cooldown()
        return {
            "daily_pnl_usd": stats.get("total_pnl_usd", 0),
            "daily_trades": stats.get("trades_count", 0),
            "daily_wins": stats.get("wins", 0),
            "daily_losses": stats.get("losses", 0),
            "consecutive_losses": self.consecutive_losses,
            "in_cooldown": in_cooldown,
            "cooldown_minutes_remaining": cooldown_min,
            "drawdown_exceeded": self.is_daily_drawdown_exceeded(),
            "claude_calls_today": self.claude_calls_today(),
            "last_trade_was_loss": self.last_trade_was_loss,
            "last_trade_direction": self.last_trade_direction,
        }
