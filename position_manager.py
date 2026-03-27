"""
=============================================================================
 POSITION_MANAGER.PY — Active Position Tracking
=============================================================================
 1 position at a time. Persists to disk across restarts.
=============================================================================
"""

import json
import os
import time
from datetime import datetime, timezone, timedelta
import config

IST = timezone(timedelta(hours=5, minutes=30))
POSITION_FILE = "active_position.json"


def _load_position():
    if os.path.exists(POSITION_FILE):
        try:
            with open(POSITION_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    return None


def _save_position(position):
    try:
        with open(POSITION_FILE, "w") as f:
            json.dump(position, f, indent=2)
    except IOError as e:
        print(f"  [WARN] Save position failed: {e}")


def _clear_position():
    if os.path.exists(POSITION_FILE):
        os.remove(POSITION_FILE)


def get_current_position():
    return _load_position()


def is_flat():
    return get_current_position() is None


def get_position_summary(current_price=0):
    pos = get_current_position()
    if pos is None:
        return "FLAT"

    d, entry, sl, tp = pos["direction"], pos["entry_price"], pos["stop_loss"], pos["take_profit"]
    summary = f"{d} @ ${entry:,.2f} (SL: ${sl:,.2f}, TP: ${tp:,.2f})"

    if current_price > 0:
        pnl = ((current_price - entry) / entry * 100) if d == "LONG" else ((entry - current_price) / entry * 100)
        summary += f" | P&L: {pnl:+.3f}%"

        elapsed = (int(time.time()) - pos.get("entry_timestamp", 0)) // 60
        summary += f" | {elapsed}m"

    return summary


def open_position(direction, entry_price, stop_loss, take_profit, confidence, reasoning=""):
    if not is_flat():
        print(f"  [WARN] Cannot open {direction} — already in position!")
        return False

    _save_position({
        "direction": direction,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "confidence": confidence,
        "reasoning": reasoning,
        "entry_time": datetime.now(IST).strftime("%I:%M %p IST"),
        "entry_timestamp": int(time.time()),
    })
    return True


def close_position(reason="manual", exit_price=0):
    pos = get_current_position()
    if pos is None:
        return None

    if exit_price > 0:
        entry = pos["entry_price"]
        pnl_pct = ((exit_price - entry) / entry * 100) if pos["direction"] == "LONG" else ((entry - exit_price) / entry * 100)
        pos["exit_price"] = exit_price
        pos["pnl_pct"] = round(pnl_pct, 4)

    pos["close_reason"] = reason
    pos["close_time"] = datetime.now(IST).strftime("%I:%M %p IST")
    pos["close_timestamp"] = int(time.time())

    _clear_position()
    return pos


def update_stop_loss(new_sl):
    pos = get_current_position()
    if pos is None:
        return False
    old_sl = pos["stop_loss"]
    pos["stop_loss"] = new_sl
    _save_position(pos)
    print(f"  📐 SL: ${old_sl:,.2f} → ${new_sl:,.2f}")
    return True


def update_take_profit(new_tp):
    pos = get_current_position()
    if pos is None:
        return False
    old_tp = pos["take_profit"]
    pos["take_profit"] = new_tp
    _save_position(pos)
    print(f"  📐 TP: ${old_tp:,.2f} → ${new_tp:,.2f}")
    return True


def check_sl_tp_hit(current_price):
    pos = get_current_position()
    if pos is None or current_price <= 0:
        return None

    sl, tp = pos["stop_loss"], pos["take_profit"]
    if pos["direction"] == "LONG":
        if current_price <= sl: return "sl_hit"
        if current_price >= tp: return "tp_hit"
    else:
        if current_price >= sl: return "sl_hit"
        if current_price <= tp: return "tp_hit"
    return None
