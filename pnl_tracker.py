"""
=============================================================================
 PNL_TRACKER.PY — Profit & Loss Tracking with Fee Calculation
=============================================================================
"""

import json
import os
import csv
from datetime import datetime, timezone, timedelta
import config

IST = timezone(timedelta(hours=5, minutes=30))
PNL_LOG_FILE = config.PNL_LOG_FILE
DAILY_PNL_FILE = "daily_pnl.json"

# Delta Exchange India fee structure
TRADING_FEE_PCT = 0.05   # 0.05% per side (taker)
GST_PCT = 18.0           # 18% GST on fees


def calculate_trade_pnl(direction, entry_price, exit_price, contracts, leverage):
    """Calculate detailed P&L for a closed trade including Delta Exchange fees.

    Uses inverse perpetual formula: 1 contract = $1 USD of BTC.
    Margin is denominated in BTC. PnL formula accounts for inverse convexity.
    """
    if entry_price <= 0 or exit_price <= 0:
        notional = 0
        margin = 0
        gross_pnl_pct = 0
        gross_pnl_usd = 0
    else:
        # Inverse perp: notional is contracts (USD face value), margin is in BTC
        notional = contracts  # 1 contract = $1 USD
        margin_btc = contracts / (entry_price * leverage) if leverage > 0 else 0
        margin = margin_btc * entry_price  # margin in USD at entry price

        if direction == "LONG":
            # PnL_USD = contracts * (1/entry - 1/exit) * entry * exit
            #         = contracts * (exit - entry)  [simplifies for USD output]
            gross_pnl_usd = contracts * (1 / entry_price - 1 / exit_price) * entry_price * exit_price
            gross_pnl_pct = (exit_price - entry_price) / entry_price * 100
        else:
            gross_pnl_usd = contracts * (1 / exit_price - 1 / entry_price) * entry_price * exit_price
            gross_pnl_pct = (entry_price - exit_price) / entry_price * 100

    # Fees (both sides) — fee notional is contracts (USD face value) for inverse perp
    fee_notional = contracts  # USD face value
    trading_fee = fee_notional * (TRADING_FEE_PCT / 100) * 2
    gst = trading_fee * (GST_PCT / 100)
    total_fee = trading_fee + gst

    net_pnl_usd = gross_pnl_usd - total_fee
    net_pnl_pct = (net_pnl_usd / margin * 100) if margin > 0 else 0

    result = "WIN" if net_pnl_usd > 0 else "LOSS" if net_pnl_usd < 0 else "BREAKEVEN"

    return {
        "direction": direction,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "contracts": contracts,
        "leverage": leverage,
        "notional": round(notional, 4),
        "margin": round(margin, 4),
        "gross_pnl_pct": round(gross_pnl_pct, 4),
        "gross_pnl_usd": round(gross_pnl_usd, 4),
        "leveraged_gross_pnl_pct": round(gross_pnl_pct * leverage, 2),
        "fee_breakdown": {
            "trading_fee": round(trading_fee, 4),
            "gst": round(gst, 4),
        },
        "total_fee_usd": round(total_fee, 4),
        "net_pnl_usd": round(net_pnl_usd, 4),
        "net_pnl_pct_on_margin": round(net_pnl_pct, 2),
        "result": result,
    }


def log_closed_trade(pnl_data, close_reason=""):
    """Log a closed trade to CSV."""
    filepath = PNL_LOG_FILE
    file_exists = os.path.exists(filepath)
    headers = [
        "timestamp", "time_ist", "direction", "entry_price", "exit_price",
        "contracts", "leverage", "gross_pnl_usd", "total_fee_usd",
        "net_pnl_usd", "net_pnl_pct_on_margin", "result", "close_reason",
    ]
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
            if not file_exists:
                w.writeheader()
            w.writerow(row)
    except Exception as e:
        print(f"  [WARN] PnL log failed: {e}")


def update_daily_pnl(net_pnl_usd, result):
    """Accumulate daily P&L (resets at midnight IST)."""
    today = datetime.now(IST).strftime("%Y-%m-%d")
    daily = {}
    if os.path.exists(DAILY_PNL_FILE):
        try:
            with open(DAILY_PNL_FILE, "r") as f:
                daily = json.load(f)
        except (json.JSONDecodeError, IOError):
            daily = {}

    if daily.get("date") != today:
        daily = {"date": today, "total_pnl_usd": 0, "trades_count": 0,
                 "wins": 0, "losses": 0, "breakevens": 0,
                 "best_trade_usd": 0, "worst_trade_usd": 0}

    daily["total_pnl_usd"] = round(daily["total_pnl_usd"] + net_pnl_usd, 4)
    daily["trades_count"] += 1
    if result == "WIN": daily["wins"] += 1
    elif result == "LOSS": daily["losses"] += 1
    else: daily["breakevens"] += 1
    daily["best_trade_usd"] = max(daily["best_trade_usd"], round(net_pnl_usd, 4))
    daily["worst_trade_usd"] = min(daily["worst_trade_usd"], round(net_pnl_usd, 4))

    try:
        with open(DAILY_PNL_FILE, "w") as f:
            json.dump(daily, f, indent=2)
    except IOError:
        pass
    return daily


def get_daily_pnl():
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if os.path.exists(DAILY_PNL_FILE):
        try:
            with open(DAILY_PNL_FILE, "r") as f:
                daily = json.load(f)
            if daily.get("date") == today:
                return daily
        except (json.JSONDecodeError, IOError):
            pass
    return {"date": today, "total_pnl_usd": 0, "trades_count": 0,
            "wins": 0, "losses": 0, "breakevens": 0,
            "best_trade_usd": 0, "worst_trade_usd": 0}


def format_trade_report(pnl_data, close_reason=""):
    d = pnl_data
    emoji = "🟢" if d["result"] == "WIN" else "🔴" if d["result"] == "LOSS" else "⚪"
    daily = get_daily_pnl()

    terminal = f"""
{'='*56}
  {emoji} TRADE CLOSED — {d['result']}
{'='*56}
  {'📈' if d['direction'] == 'LONG' else '📉'} {d['direction']} | {close_reason}
  Entry: ${d['entry_price']:,.2f} → Exit: ${d['exit_price']:,.2f}
  Gross: ${d['gross_pnl_usd']:+,.4f} ({d['gross_pnl_pct']:+.4f}%)
  Fees: ${d['total_fee_usd']:,.4f} | Net: ${d['net_pnl_usd']:+,.4f}
  Return on margin: {d['net_pnl_pct_on_margin']:+.2f}%
  Today: ${daily['total_pnl_usd']:+,.4f} ({daily['trades_count']} trades, W:{daily['wins']} L:{daily['losses']})
{'='*56}"""

    telegram = (
        f"{emoji} *Trade Closed — {d['result']}*\n\n"
        f"{'📈' if d['direction'] == 'LONG' else '📉'} {d['direction']} | {close_reason}\n"
        f"Entry: `${d['entry_price']:,.2f}` → Exit: `${d['exit_price']:,.2f}`\n"
        f"Net P&L: `${d['net_pnl_usd']:+,.4f}` ({d['net_pnl_pct_on_margin']:+.2f}% on margin)\n\n"
        f"📊 Today: ${daily['total_pnl_usd']:+,.4f} ({daily['trades_count']} trades)"
    )
    return terminal, telegram


def format_daily_summary():
    daily = get_daily_pnl()
    if daily["trades_count"] == 0:
        return "📊 *Daily Summary* — No trades today."
    wr = daily["wins"] / daily["trades_count"] * 100 if daily["trades_count"] > 0 else 0
    emoji = "🟢" if daily["total_pnl_usd"] > 0 else "🔴" if daily["total_pnl_usd"] < 0 else "⚪"
    return (
        f"{emoji} *BTC BRAIN v2 — Daily Report*\n"
        f"*Net P&L: ${daily['total_pnl_usd']:+,.4f}*\n"
        f"Trades: {daily['trades_count']} | W:{daily['wins']} L:{daily['losses']} | WR: {wr:.0f}%\n"
        f"Best: ${daily['best_trade_usd']:+,.4f} | Worst: ${daily['worst_trade_usd']:+,.4f}"
    )
