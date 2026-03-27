"""
=============================================================================
 TRADE_TRACKER.PY — Trade Confirmation & Logging
=============================================================================
"""

import os
import csv
import threading
from datetime import datetime, timezone, timedelta
import config

IST = timezone(timedelta(hours=5, minutes=30))


def log_signal(signal, trade_taken=False, skip_reason=""):
    """Log every Claude signal to signals_log.csv."""
    filepath = config.SIGNAL_LOG_FILE
    file_exists = os.path.exists(filepath)
    headers = [
        "timestamp", "time", "action", "confidence", "reasoning",
        "entry_price", "stop_loss", "take_profit",
        "trade_taken", "skip_reason",
    ]
    row = {
        "timestamp": signal.get("timestamp", ""),
        "time": signal.get("time", ""),
        "action": signal.get("action", ""),
        "confidence": signal.get("confidence", ""),
        "reasoning": (signal.get("reasoning", "") or "")[:200],
        "entry_price": signal.get("entry_price", ""),
        "stop_loss": signal.get("stop_loss", ""),
        "take_profit": signal.get("take_profit", ""),
        "trade_taken": trade_taken,
        "skip_reason": skip_reason,
    }
    try:
        with open(filepath, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=headers)
            if not file_exists:
                w.writeheader()
            w.writerow(row)
    except Exception as e:
        print(f"  [WARN] Signal log failed: {e}")


def log_trade(signal):
    """Log a confirmed trade to trades_log.csv."""
    filepath = config.TRADES_LOG_FILE
    file_exists = os.path.exists(filepath)
    headers = [
        "timestamp", "time", "direction", "confidence",
        "entry_price", "stop_loss", "take_profit", "reasoning",
    ]
    row = {
        "timestamp": signal.get("timestamp", ""),
        "time": signal.get("time", ""),
        "direction": signal.get("action", ""),
        "confidence": signal.get("confidence", ""),
        "entry_price": signal.get("entry_price", ""),
        "stop_loss": signal.get("stop_loss", ""),
        "take_profit": signal.get("take_profit", ""),
        "reasoning": (signal.get("reasoning", "") or "")[:200],
    }
    try:
        with open(filepath, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=headers)
            if not file_exists:
                w.writeheader()
            w.writerow(row)
    except Exception as e:
        print(f"  [WARN] Trade log failed: {e}")


def _input_with_timeout(prompt, timeout):
    """Input with timeout (macOS/Linux)."""
    print(prompt, end="", flush=True)
    result = [None]

    def get_input():
        try:
            result[0] = input()
        except EOFError:
            result[0] = None

    thread = threading.Thread(target=get_input, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    return result[0] if not thread.is_alive() else None


def prompt_trade_confirmation(signal, timeout_seconds=None):
    """Ask Y/N for trade confirmation."""
    if config.AUTO_ACCEPT_TRADES:
        print("  ✅ Auto-accepted")
        return True

    timeout = timeout_seconds or config.BOT_CYCLE_SECONDS - 10
    response = _input_with_timeout(f"\n  ❓ Take this trade? (Y/N, {timeout}s timeout): ", timeout)

    if response is None:
        print("  ⏳ Timeout — skipping")
        return False
    return response.strip().upper() in ["Y", "YES"]
