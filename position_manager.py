"""
=============================================================================
 POSITION_MANAGER.PY — Active Position Tracking & Management
=============================================================================
 Tracks the bot's current position state:
   • Is a trade currently open? (LONG / SHORT / FLAT)
   • What was the entry price, SL, TP?
   • How long has it been open?
   • Current P&L based on live price
   
 Rules:
   • Only 1 position at a time
   • New trade requires closing/exiting the current one first
   • Claude sees current position state and can suggest:
     HOLD, EXIT, REVERSE, TRAIL_SL, or new BUY/SELL (only when flat)
=============================================================================
"""

import json
import os
import time
from datetime import datetime, timezone, timedelta

import config

IST = timezone(timedelta(hours=5, minutes=30))

# Position state file — persists across restarts
POSITION_FILE = "active_position.json"


def _load_position():
    """Load active position from disk."""
    if os.path.exists(POSITION_FILE):
        try:
            with open(POSITION_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    return None


def _save_position(position):
    """Save active position to disk."""
    try:
        with open(POSITION_FILE, "w") as f:
            json.dump(position, f, indent=2)
    except IOError as e:
        print(f"  [WARN] Failed to save position: {e}")


def _clear_position():
    """Remove position file (go flat)."""
    if os.path.exists(POSITION_FILE):
        os.remove(POSITION_FILE)


def get_current_position():
    """
    Get the current active position.
    
    Returns:
        dict with position details, or None if flat (no position).
        
        Keys when position exists:
            direction: "LONG" or "SHORT"
            entry_price: float
            stop_loss: float
            take_profit: float
            entry_time: str (IST)
            entry_timestamp: int
            confidence: int
            reasoning: str
    """
    return _load_position()


def is_flat():
    """Return True if no position is currently open."""
    return get_current_position() is None


def get_position_summary(current_price=0):
    """
    Get a human-readable summary of the current position.
    Includes unrealized P&L if current_price is provided.
    """
    pos = get_current_position()
    if pos is None:
        return "FLAT (no open position)"

    direction = pos["direction"]
    entry = pos["entry_price"]
    sl = pos["stop_loss"]
    tp = pos["take_profit"]

    summary = f"{direction} @ ${entry:,.2f} (SL: ${sl:,.2f}, TP: ${tp:,.2f})"

    if current_price > 0:
        if direction == "LONG":
            pnl = (current_price - entry) / entry * 100
            sl_dist = (current_price - sl) / current_price * 100
            tp_dist = (tp - current_price) / current_price * 100
        else:  # SHORT
            pnl = (entry - current_price) / entry * 100
            sl_dist = (sl - current_price) / current_price * 100
            tp_dist = (current_price - tp) / current_price * 100

        pnl_str = f"+{pnl:.3f}%" if pnl >= 0 else f"{pnl:.3f}%"
        summary += f" | P&L: {pnl_str}"
        summary += f" | SL dist: {sl_dist:.3f}% | TP dist: {tp_dist:.3f}%"

        # Check if SL or TP hit
        if direction == "LONG":
            if current_price <= sl:
                summary += " ⚠ SL HIT"
            elif current_price >= tp:
                summary += " 🎯 TP HIT"
        else:
            if current_price >= sl:
                summary += " ⚠ SL HIT"
            elif current_price <= tp:
                summary += " 🎯 TP HIT"

    # Time in trade
    entry_ts = pos.get("entry_timestamp", 0)
    if entry_ts > 0:
        elapsed = int(time.time()) - entry_ts
        mins = elapsed // 60
        summary += f" | Open: {mins}m"

    return summary


def open_position(direction, entry_price, stop_loss, take_profit, confidence, reasoning=""):
    """
    Open a new position. Only works if currently flat.
    
    Args:
        direction: "LONG" or "SHORT"
        entry_price: float
        stop_loss: float
        take_profit: float
        confidence: int (1-10)
        reasoning: str
    
    Returns:
        True if opened, False if a position is already active.
    """
    if not is_flat():
        print(f"  [WARN] Cannot open {direction} — already in a position!")
        return False

    position = {
        "direction": direction,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "confidence": confidence,
        "reasoning": reasoning,
        "entry_time": datetime.now(IST).strftime("%I:%M %p IST"),
        "entry_timestamp": int(time.time()),
    }

    _save_position(position)
    return True


def close_position(reason="manual", exit_price=0):
    """
    Close the current position.
    
    Args:
        reason: why it was closed (e.g., "tp_hit", "sl_hit", "reversed", "manual")
        exit_price: the price at which position was closed
    
    Returns:
        dict with closed position details (for logging), or None if was flat.
    """
    pos = get_current_position()
    if pos is None:
        return None

    # Calculate P&L
    if exit_price > 0:
        entry = pos["entry_price"]
        if pos["direction"] == "LONG":
            pnl_pct = (exit_price - entry) / entry * 100
        else:
            pnl_pct = (entry - exit_price) / entry * 100
        pos["exit_price"] = exit_price
        pos["pnl_pct"] = round(pnl_pct, 4)
    
    pos["close_reason"] = reason
    pos["close_time"] = datetime.now(IST).strftime("%I:%M %p IST")
    pos["close_timestamp"] = int(time.time())

    _clear_position()
    return pos


def update_stop_loss(new_sl):
    """Trail the stop loss to a new level."""
    pos = get_current_position()
    if pos is None:
        return False

    old_sl = pos["stop_loss"]
    pos["stop_loss"] = new_sl
    _save_position(pos)
    print(f"  📐 SL updated: ${old_sl:,.2f} → ${new_sl:,.2f}")
    return True


def update_take_profit(new_tp):
    """Update the take profit level."""
    pos = get_current_position()
    if pos is None:
        return False

    old_tp = pos["take_profit"]
    pos["take_profit"] = new_tp
    _save_position(pos)
    print(f"  📐 TP updated: ${old_tp:,.2f} → ${new_tp:,.2f}")
    return True


def check_sl_tp_hit(current_price):
    """
    Check if current price has hit the SL or TP.
    
    Returns:
        "sl_hit", "tp_hit", or None
    """
    pos = get_current_position()
    if pos is None or current_price <= 0:
        return None

    entry = pos["entry_price"]
    sl = pos["stop_loss"]
    tp = pos["take_profit"]

    if pos["direction"] == "LONG":
        if current_price <= sl:
            return "sl_hit"
        elif current_price >= tp:
            return "tp_hit"
    else:  # SHORT
        if current_price >= sl:
            return "sl_hit"
        elif current_price <= tp:
            return "tp_hit"

    return None
