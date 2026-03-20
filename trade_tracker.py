"""
=============================================================================
 TRADE_TRACKER.PY — Trade Confirmation & History Manager
=============================================================================
 Handles:
   • Y/N trade confirmation prompt with timeout
   • Logging confirmed trades to trades_log.csv
   • Logging all Claude signals to signals_log.csv
   • Loading trade history for review
   
 Trade flow:
   1. Claude says BUY/SELL → signal displayed
   2. User has until next scan cycle to press Y or N
   3. If Y → trade recorded as TAKEN
   4. If N or timeout → trade recorded as SKIPPED
   5. All decisions logged for future analysis
=============================================================================
"""

import os
import csv
import sys
import select
import threading
from datetime import datetime, timezone, timedelta

import config

IST = timezone(timedelta(hours=5, minutes=30))


# =============================================================================
#  SIGNAL LOGGER — logs every Claude analysis (taken or not)
# =============================================================================

def log_signal(signal, trade_taken=False, skip_reason=""):
    """
    Log every Claude signal to signals_log.csv.
    Includes whether the trade was taken or skipped.
    """
    filepath = config.SIGNAL_LOG_FILE
    file_exists = os.path.exists(filepath)

    headers = [
        "timestamp", "time_ist", "decision", "confidence",
        "entry_price", "stop_loss", "take_profit",
        "reasoning", "risk_warnings", "market_condition",
        "trade_taken", "skip_reason",
        "regime", "rsi", "ema9", "ema21", "atr", "atr_pct",
        "funding_rate", "open_interest",
        "fear_greed", "btc_dominance",
    ]

    ind = signal.get("indicators", {})

    row = {
        "timestamp": signal.get("timestamp", ""),
        "time_ist": signal.get("time", ""),
        "decision": signal.get("action") or signal.get("decision", ""),
        "confidence": signal.get("confidence", ""),
        "entry_price": signal.get("entry_price", ""),
        "stop_loss": signal.get("stop_loss", ""),
        "take_profit": signal.get("take_profit", ""),
        "reasoning": signal.get("reasoning", ""),
        "risk_warnings": signal.get("risk_warnings", ""),
        "market_condition": signal.get("market_condition", ""),
        "trade_taken": "YES" if trade_taken else "NO",
        "skip_reason": skip_reason,
        "regime": ind.get("regime", ""),
        "rsi": ind.get("rsi", ""),
        "ema9": ind.get("ema9", ""),
        "ema21": ind.get("ema21", ""),
        "atr": ind.get("atr", ""),
        "atr_pct": ind.get("atr_pct", ""),
        "funding_rate": signal.get("funding_rate", ""),
        "open_interest": signal.get("open_interest", ""),
        "fear_greed": signal.get("fear_greed", ""),
        "btc_dominance": signal.get("btc_dominance", ""),
    }

    try:
        with open(filepath, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
    except Exception as e:
        print(f"  [WARN] Signal logging failed: {e}")


# =============================================================================
#  TRADE LOGGER — logs only confirmed trades
# =============================================================================

def log_trade(signal):
    """
    Log a confirmed trade to trades_log.csv.
    Only called when user presses Y.
    """
    filepath = config.TRADES_LOG_FILE
    file_exists = os.path.exists(filepath)

    headers = [
        "timestamp", "time_ist", "direction", "confidence",
        "entry_price", "stop_loss", "take_profit",
        "reasoning", "market_condition",
        "regime", "rsi", "atr_pct", "funding_rate",
        "fear_greed", "btc_dominance",
    ]

    ind = signal.get("indicators", {})

    row = {
        "timestamp": signal.get("timestamp", ""),
        "time_ist": signal.get("time", ""),
        "direction": signal.get("action") or signal.get("decision", ""),
        "confidence": signal.get("confidence", ""),
        "entry_price": signal.get("entry_price", ""),
        "stop_loss": signal.get("stop_loss", ""),
        "take_profit": signal.get("take_profit", ""),
        "reasoning": signal.get("reasoning", ""),
        "market_condition": signal.get("market_condition", ""),
        "regime": ind.get("regime", ""),
        "rsi": ind.get("rsi", ""),
        "atr_pct": ind.get("atr_pct", ""),
        "funding_rate": signal.get("funding_rate", ""),
        "fear_greed": signal.get("fear_greed", ""),
        "btc_dominance": signal.get("btc_dominance", ""),
    }

    try:
        with open(filepath, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
    except Exception as e:
        print(f"  [WARN] Trade logging failed: {e}")


# =============================================================================
#  Y/N TRADE CONFIRMATION — with timeout
# =============================================================================

def _input_with_timeout(prompt, timeout):
    """
    Ask for input with a timeout. Returns the input string or None on timeout.
    Works on macOS/Linux.
    """
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

    if thread.is_alive():
        print()  # newline after timeout
        return None
    return result[0]


def prompt_trade_confirmation(signal, timeout_seconds=None):
    """
    Display the signal and ask Y/N.
    
    Args:
        signal: Claude's analysis dict
        timeout_seconds: how long to wait (default: until next cycle)
    
    Returns:
        bool — True if user confirmed, False if declined or timed out
    """
    if timeout_seconds is None:
        timeout_seconds = config.BOT_CYCLE_SECONDS - 30  # leave 30s buffer

    direction = signal.get("action") or signal.get("decision", "")
    confidence = signal.get("confidence", 0)
    entry = signal.get("entry_price") or 0
    sl = signal.get("stop_loss") or 0
    tp = signal.get("take_profit") or 0
    reasoning = signal.get("reasoning", "")
    risk = signal.get("risk_warnings", "")
    condition = signal.get("market_condition", "")

    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text
        from rich import box

        c = Console()

        # Build signal display
        content = Text()
        dir_style = "bold green" if direction == "BUY" else "bold red"
        arrow = "▲ BUY (LONG)" if direction == "BUY" else "▼ SELL (SHORT)"

        content.append(f"\n  {arrow}\n", style=dir_style)
        content.append(f"  Confidence: {confidence}/10\n\n", style="bold yellow")

        content.append(f"  Entry:       ${entry:,.2f}\n", style="white")
        content.append(f"  Stop-Loss:   ${sl:,.2f}\n", style="red")
        content.append(f"  Take-Profit: ${tp:,.2f}\n\n", style="green")

        content.append(f"  Market:      {condition}\n", style="cyan")
        content.append(f"  Reasoning:   {reasoning}\n\n", style="white")

        if risk:
            content.append(f"  ⚠ Risk:      {risk}\n\n", style="bold yellow")

        content.append(f"  Waiting {timeout_seconds}s for your decision...\n", style="dim")

        panel_style = "green" if direction == "BUY" else "red"
        c.print(Panel(content, title="⚡ CLAUDE SIGNAL — TAKE THIS TRADE?",
                       title_align="left", style=panel_style, box=box.DOUBLE))

    except ImportError:
        print(f"\n{'='*56}")
        print(f"  ⚡ CLAUDE SIGNAL: {direction} (Confidence: {confidence}/10)")
        print(f"  Entry: ${entry:,.2f} | SL: ${sl:,.2f} | TP: ${tp:,.2f}")
        print(f"  Reason: {reasoning}")
        if risk:
            print(f"  Risk: {risk}")
        print(f"{'='*56}")

    # Ask for confirmation
    response = _input_with_timeout(
        f"\n  👉 Take this {direction} trade? (Y/N): ",
        timeout=timeout_seconds
    )

    if response is None:
        print(f"  ⏱  Timeout — trade SKIPPED (no response in {timeout_seconds}s)")
        log_signal(signal, trade_taken=False, skip_reason="timeout")
        return False

    response = response.strip().upper()

    if response in ["Y", "YES"]:
        print(f"  ✅ Trade CONFIRMED — {direction} recorded")
        log_signal(signal, trade_taken=True)
        log_trade(signal)
        return True
    else:
        print(f"  ❌ Trade SKIPPED by operator")
        log_signal(signal, trade_taken=False, skip_reason="operator_declined")
        return False
