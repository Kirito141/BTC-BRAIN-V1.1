"""
=============================================================================
 PNL_TRACKER.PY — Profit & Loss Tracking with Fee Calculation
=============================================================================
 Tracks:
   • Per-trade P&L (gross and net after fees)
   • Delta Exchange fees (taker 0.05% + 18% GST = 0.059% per side)
   • Funding rate costs/income
   • Daily accumulated P&L
   • Running session total
   
 Generates:
   • Per-trade P&L report (printed + Telegram)
   • Daily summary report
   • Session summary on bot shutdown
   
 Fee Structure (Delta Exchange India, BTCUSD Futures):
   • Taker fee: 0.05% of notional value (per side)
   • Maker fee: 0.02% of notional value (per side)
   • GST: 18% on trading fees
   • We assume taker fees (market orders) for conservative estimation
   • Notional = contracts × 0.001 BTC × BTC price
=============================================================================
"""

import os
import csv
import json
from datetime import datetime, timezone, timedelta

import config

IST = timezone(timedelta(hours=5, minutes=30))

# Fee rates (Delta Exchange India, Futures)
TAKER_FEE_PCT = 0.05      # 0.05% per side
MAKER_FEE_PCT = 0.02      # 0.02% per side
GST_RATE = 0.18            # 18% GST on fees

# Session P&L file
PNL_LOG_FILE = "pnl_log.csv"
DAILY_PNL_FILE = "daily_pnl.json"


def calculate_trade_fees(entry_price, exit_price, contracts, leverage):
    """
    Calculate total fees for a round-trip trade (entry + exit).
    
    For BTCUSD inverse perpetual:
      Notional value = contracts × 0.001 BTC × price
      Fee per side = notional × taker_fee_pct / 100
      Total fee = (entry_fee + exit_fee) × (1 + GST_rate)
    
    Returns:
        dict with fee breakdown
    """
    # Notional values at entry and exit
    contract_size_btc = 0.001
    entry_notional = contracts * contract_size_btc * entry_price
    exit_notional = contracts * contract_size_btc * exit_price

    # Taker fees (both sides)
    entry_fee = entry_notional * (TAKER_FEE_PCT / 100)
    exit_fee = exit_notional * (TAKER_FEE_PCT / 100)
    total_trading_fee = entry_fee + exit_fee

    # GST on fees
    gst_amount = total_trading_fee * GST_RATE

    # Total cost
    total_fee = total_trading_fee + gst_amount

    return {
        "entry_notional": round(entry_notional, 2),
        "exit_notional": round(exit_notional, 2),
        "entry_fee": round(entry_fee, 4),
        "exit_fee": round(exit_fee, 4),
        "trading_fee": round(total_trading_fee, 4),
        "gst": round(gst_amount, 4),
        "total_fee": round(total_fee, 4),
        "fee_pct_of_notional": round(total_fee / entry_notional * 100, 4) if entry_notional > 0 else 0,
    }


def calculate_trade_pnl(direction, entry_price, exit_price, contracts, leverage):
    """
    Calculate complete P&L for a closed trade including fees.
    
    Args:
        direction: "LONG" or "SHORT"
        entry_price: float
        exit_price: float
        contracts: int (number of lots)
        leverage: int
    
    Returns:
        dict with complete P&L breakdown
    """
    contract_size_btc = 0.001
    notional = contracts * contract_size_btc * entry_price

    # Gross P&L (before fees)
    if direction == "LONG":
        gross_pnl_pct = (exit_price - entry_price) / entry_price * 100
    else:  # SHORT
        gross_pnl_pct = (entry_price - exit_price) / entry_price * 100

    gross_pnl_usd = notional * (gross_pnl_pct / 100)

    # Leveraged P&L (on margin)
    margin = notional / leverage
    leveraged_pnl_pct = gross_pnl_pct * leverage

    # Fees
    fees = calculate_trade_fees(entry_price, exit_price, contracts, leverage)

    # Net P&L
    net_pnl_usd = gross_pnl_usd - fees["total_fee"]
    net_pnl_pct = (net_pnl_usd / margin * 100) if margin > 0 else 0

    return {
        "direction": direction,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "contracts": contracts,
        "leverage": leverage,
        "notional": round(notional, 2),
        "margin": round(margin, 2),
        # Gross
        "gross_pnl_pct": round(gross_pnl_pct, 4),
        "gross_pnl_usd": round(gross_pnl_usd, 4),
        # Fees
        "total_fee_usd": fees["total_fee"],
        "fee_breakdown": fees,
        # Net (after fees)
        "net_pnl_usd": round(net_pnl_usd, 4),
        "net_pnl_pct_on_margin": round(net_pnl_pct, 2),
        "leveraged_gross_pnl_pct": round(leveraged_pnl_pct, 2),
        # Result
        "result": "WIN" if net_pnl_usd > 0 else "LOSS" if net_pnl_usd < 0 else "BREAKEVEN",
    }


def log_closed_trade(pnl_data, close_reason=""):
    """
    Log a closed trade with full P&L to pnl_log.csv.
    """
    filepath = PNL_LOG_FILE
    file_exists = os.path.exists(filepath)

    headers = [
        "timestamp", "time_ist", "direction", "entry_price", "exit_price",
        "contracts", "leverage", "notional", "margin",
        "gross_pnl_pct", "gross_pnl_usd",
        "total_fee_usd", "net_pnl_usd", "net_pnl_pct_on_margin",
        "result", "close_reason",
    ]

    row = {
        "timestamp": int(datetime.now(IST).timestamp()),
        "time_ist": datetime.now(IST).strftime("%I:%M %p IST"),
        "direction": pnl_data.get("direction", ""),
        "entry_price": pnl_data.get("entry_price", ""),
        "exit_price": pnl_data.get("exit_price", ""),
        "contracts": pnl_data.get("contracts", ""),
        "leverage": pnl_data.get("leverage", ""),
        "notional": pnl_data.get("notional", ""),
        "margin": pnl_data.get("margin", ""),
        "gross_pnl_pct": pnl_data.get("gross_pnl_pct", ""),
        "gross_pnl_usd": pnl_data.get("gross_pnl_usd", ""),
        "total_fee_usd": pnl_data.get("total_fee_usd", ""),
        "net_pnl_usd": pnl_data.get("net_pnl_usd", ""),
        "net_pnl_pct_on_margin": pnl_data.get("net_pnl_pct_on_margin", ""),
        "result": pnl_data.get("result", ""),
        "close_reason": close_reason,
    }

    try:
        with open(filepath, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
    except Exception as e:
        print(f"  [WARN] PnL logging failed: {e}")


def update_daily_pnl(net_pnl_usd, result):
    """
    Accumulate daily P&L totals.
    Resets at midnight IST.
    """
    today = datetime.now(IST).strftime("%Y-%m-%d")

    # Load existing daily data
    daily = {}
    if os.path.exists(DAILY_PNL_FILE):
        try:
            with open(DAILY_PNL_FILE, "r") as f:
                daily = json.load(f)
        except (json.JSONDecodeError, IOError):
            daily = {}

    # Reset if new day
    if daily.get("date") != today:
        daily = {
            "date": today,
            "total_pnl_usd": 0,
            "total_fees_usd": 0,
            "trades_count": 0,
            "wins": 0,
            "losses": 0,
            "breakevens": 0,
            "best_trade_usd": 0,
            "worst_trade_usd": 0,
        }

    # Update
    daily["total_pnl_usd"] = round(daily["total_pnl_usd"] + net_pnl_usd, 4)
    daily["trades_count"] += 1

    if result == "WIN":
        daily["wins"] += 1
    elif result == "LOSS":
        daily["losses"] += 1
    else:
        daily["breakevens"] += 1

    if net_pnl_usd > daily["best_trade_usd"]:
        daily["best_trade_usd"] = round(net_pnl_usd, 4)
    if net_pnl_usd < daily["worst_trade_usd"]:
        daily["worst_trade_usd"] = round(net_pnl_usd, 4)

    # Save
    try:
        with open(DAILY_PNL_FILE, "w") as f:
            json.dump(daily, f, indent=2)
    except IOError as e:
        print(f"  [WARN] Daily PnL save failed: {e}")

    return daily


def get_daily_pnl():
    """Get today's accumulated P&L."""
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if os.path.exists(DAILY_PNL_FILE):
        try:
            with open(DAILY_PNL_FILE, "r") as f:
                daily = json.load(f)
            if daily.get("date") == today:
                return daily
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "date": today, "total_pnl_usd": 0, "trades_count": 0,
        "wins": 0, "losses": 0, "breakevens": 0,
        "best_trade_usd": 0, "worst_trade_usd": 0,
    }


def format_trade_report(pnl_data, close_reason=""):
    """
    Format a trade P&L report for terminal and Telegram.
    Returns (terminal_text, telegram_text).
    """
    d = pnl_data
    result_emoji = "🟢" if d["result"] == "WIN" else "🔴" if d["result"] == "LOSS" else "⚪"
    direction = d["direction"]
    dir_emoji = "📈" if direction == "LONG" else "📉"

    terminal = f"""
{'='*56}
  {result_emoji} TRADE CLOSED — {d['result']}
{'='*56}

  {dir_emoji} {direction} Position Closed ({close_reason})

  Entry:           ${d['entry_price']:,.2f}
  Exit:            ${d['exit_price']:,.2f}
  Contracts:       {d['contracts']} lots @ {d['leverage']}x

  ── P&L Breakdown ──────────────────────
  Gross P&L:       ${d['gross_pnl_usd']:+,.4f} ({d['gross_pnl_pct']:+.4f}%)
  Leveraged:       {d['leveraged_gross_pnl_pct']:+.2f}% on margin

  ── Fees ────────────────────────────────
  Trading Fee:     ${d['fee_breakdown']['trading_fee']:,.4f}
  GST (18%):       ${d['fee_breakdown']['gst']:,.4f}
  Total Fees:      ${d['total_fee_usd']:,.4f}

  ── Net Result ──────────────────────────
  Net P&L:         ${d['net_pnl_usd']:+,.4f}
  Return on Margin: {d['net_pnl_pct_on_margin']:+.2f}%

{'='*56}"""

    # Get daily totals
    daily = get_daily_pnl()
    terminal += f"""
  ── Daily Running Total ─────────────────
  Today's P&L:     ${daily['total_pnl_usd']:+,.4f}
  Trades:          {daily['trades_count']} (W:{daily['wins']} L:{daily['losses']})
  Win Rate:        {daily['wins'] / daily['trades_count'] * 100:.0f}% 
{'='*56}"""

    # Telegram version
    telegram = (
        f"{result_emoji} *Trade Closed — {d['result']}*\n\n"
        f"{dir_emoji} {direction} | {close_reason}\n"
        f"Entry: `${d['entry_price']:,.2f}`\n"
        f"Exit: `${d['exit_price']:,.2f}`\n"
        f"Contracts: `{d['contracts']}` @ `{d['leverage']}x`\n\n"
        f"Gross P&L: `${d['gross_pnl_usd']:+,.4f}` ({d['gross_pnl_pct']:+.4f}%)\n"
        f"Fees: `${d['total_fee_usd']:,.4f}`\n"
        f"*Net P&L: `${d['net_pnl_usd']:+,.4f}`*\n"
        f"Return on margin: `{d['net_pnl_pct_on_margin']:+.2f}%`\n\n"
        f"📊 *Today: ${daily['total_pnl_usd']:+,.4f}* "
        f"({daily['trades_count']} trades, W:{daily['wins']} L:{daily['losses']})"
    )

    return terminal, telegram


def format_daily_summary():
    """
    Format the daily P&L summary for Telegram end-of-day report.
    Returns telegram text.
    """
    daily = get_daily_pnl()

    if daily["trades_count"] == 0:
        return "📊 *Daily Summary*\nNo trades today."

    win_rate = daily["wins"] / daily["trades_count"] * 100 if daily["trades_count"] > 0 else 0
    result_emoji = "🟢" if daily["total_pnl_usd"] > 0 else "🔴" if daily["total_pnl_usd"] < 0 else "⚪"

    return (
        f"{result_emoji} *BTC BRAIN — Daily Report*\n"
        f"Date: {daily['date']}\n\n"
        f"*Net P&L: ${daily['total_pnl_usd']:+,.4f}*\n\n"
        f"Trades: {daily['trades_count']}\n"
        f"Wins: {daily['wins']} | Losses: {daily['losses']}\n"
        f"Win Rate: {win_rate:.0f}%\n"
        f"Best Trade: ${daily['best_trade_usd']:+,.4f}\n"
        f"Worst Trade: ${daily['worst_trade_usd']:+,.4f}\n\n"
        f"_Balance: ${config.DEFAULT_BALANCE_USDT:,.2f}_"
    )
