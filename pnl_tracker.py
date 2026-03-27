"""
=============================================================================
 PNL_TRACKER.PY v3 — P&L with Delta Exchange Fees
=============================================================================
"""

import json
import os
import csv
from datetime import datetime, timezone, timedelta
import config

IST = timezone(timedelta(hours=5, minutes=30))
TRADING_FEE_PCT = 0.05
GST_PCT = 18.0


def calculate_trade_pnl(direction, entry_price, exit_price, contracts, leverage):
    if entry_price <= 0 or exit_price <= 0:
        gross_pnl_usd = gross_pnl_pct = 0
        margin = 0
    else:
        margin_btc = contracts / (entry_price * leverage) if leverage > 0 else 0
        margin = margin_btc * entry_price
        if direction == "LONG":
            gross_pnl_usd = contracts * (1 / entry_price - 1 / exit_price) * entry_price * exit_price
            gross_pnl_pct = (exit_price - entry_price) / entry_price * 100
        else:
            gross_pnl_usd = contracts * (1 / exit_price - 1 / entry_price) * entry_price * exit_price
            gross_pnl_pct = (entry_price - exit_price) / entry_price * 100

    fee_notional = contracts
    trading_fee = fee_notional * (TRADING_FEE_PCT / 100) * 2
    gst = trading_fee * (GST_PCT / 100)
    total_fee = trading_fee + gst
    net_pnl_usd = gross_pnl_usd - total_fee
    net_pnl_pct = (net_pnl_usd / margin * 100) if margin > 0 else 0
    result = "WIN" if net_pnl_usd > 0 else "LOSS" if net_pnl_usd < 0 else "BREAKEVEN"

    return {
        "direction": direction, "entry_price": entry_price, "exit_price": exit_price,
        "contracts": contracts, "leverage": leverage,
        "margin": round(margin, 4),
        "gross_pnl_pct": round(gross_pnl_pct, 4), "gross_pnl_usd": round(gross_pnl_usd, 4),
        "total_fee_usd": round(total_fee, 4),
        "net_pnl_usd": round(net_pnl_usd, 4),
        "net_pnl_pct_on_margin": round(net_pnl_pct, 2),
        "result": result,
    }


def log_closed_trade(pnl_data, close_reason=""):
    filepath = config.PNL_LOG_FILE
    file_exists = os.path.exists(filepath)
    headers = ["timestamp", "time_ist", "direction", "entry_price", "exit_price",
               "contracts", "leverage", "gross_pnl_usd", "total_fee_usd",
               "net_pnl_usd", "net_pnl_pct_on_margin", "result", "close_reason"]
    row = {
        "timestamp": int(datetime.now(IST).timestamp()),
        "time_ist": datetime.now(IST).strftime("%I:%M %p IST"),
        "direction": pnl_data.get("direction", ""),
        "entry_price": pnl_data.get("entry_price", ""),
        "exit_price": pnl_data.get("exit_price", ""),
        "contracts": pnl_data.get("contracts", ""),
        "leverage": pnl_data.get("leverage", ""),
        "gross_pnl_usd": pnl_data.get("gross_pnl_usd", ""),
        "total_fee_usd": pnl_data.get("total_fee_usd", ""),
        "net_pnl_usd": pnl_data.get("net_pnl_usd", ""),
        "net_pnl_pct_on_margin": pnl_data.get("net_pnl_pct_on_margin", ""),
        "result": pnl_data.get("result", ""),
        "close_reason": close_reason,
    }
    try:
        with open(filepath, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=headers)
            if not file_exists: w.writeheader()
            w.writerow(row)
    except Exception as e:
        print(f"  [WARN] PnL log failed: {e}")


def format_trade_report(pnl_data, close_reason=""):
    d = pnl_data
    emoji = "🟢" if d["result"] == "WIN" else "🔴" if d["result"] == "LOSS" else "⚪"
    terminal = (
        f"\n{'='*50}\n"
        f"  {emoji} TRADE CLOSED — {d['result']} | {close_reason}\n"
        f"  {d['direction']} | ${d['entry_price']:,.2f} → ${d['exit_price']:,.2f}\n"
        f"  Net: ${d['net_pnl_usd']:+,.4f} ({d['net_pnl_pct_on_margin']:+.2f}% on margin)\n"
        f"{'='*50}"
    )
    telegram = (
        f"{emoji} *Trade Closed — {d['result']}*\n"
        f"{d['direction']} | {close_reason}\n"
        f"Entry: `${d['entry_price']:,.2f}` → Exit: `${d['exit_price']:,.2f}`\n"
        f"Net: `${d['net_pnl_usd']:+,.4f}` ({d['net_pnl_pct_on_margin']:+.2f}%)"
    )
    return terminal, telegram
