"""
=============================================================================
 TRADE_TRACKER.PY v3 — Signal & Trade Logging (no manual confirmation)
=============================================================================
"""

import os
import csv
from datetime import datetime, timezone, timedelta
import config

IST = timezone(timedelta(hours=5, minutes=30))


def log_signal(signal, trade_taken=False, skip_reason=""):
    filepath = config.SIGNAL_LOG_FILE
    file_exists = os.path.exists(filepath)
    headers = ["timestamp", "time", "action", "confidence", "reasoning",
               "entry_price", "stop_loss", "take_profit", "trade_taken", "skip_reason"]
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
            if not file_exists: w.writeheader()
            w.writerow(row)
    except Exception as e:
        print(f"  [WARN] Signal log failed: {e}")


def log_trade(signal, contracts=0, order_id=""):
    filepath = config.TRADES_LOG_FILE
    file_exists = os.path.exists(filepath)
    headers = ["timestamp", "time", "direction", "confidence",
               "entry_price", "stop_loss", "take_profit", "reasoning",
               "contracts", "order_id"]
    row = {
        "timestamp": signal.get("timestamp", ""),
        "time": signal.get("time", ""),
        "direction": signal.get("action", ""),
        "confidence": signal.get("confidence", ""),
        "entry_price": signal.get("entry_price", ""),
        "stop_loss": signal.get("stop_loss", ""),
        "take_profit": signal.get("take_profit", ""),
        "reasoning": (signal.get("reasoning", "") or "")[:200],
        "contracts": contracts,
        "order_id": order_id,
    }
    try:
        with open(filepath, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=headers)
            if not file_exists: w.writeheader()
            w.writerow(row)
    except Exception as e:
        print(f"  [WARN] Trade log failed: {e}")
