"""
=============================================================================
 ALERTS.PY — Signal Notification & Logging
=============================================================================
 Three alert channels:
   1. Desktop notification (plyer — with fallback)
   2. Telegram (placeholder — ready for token/chat_id integration)
   3. CSV logging (every signal saved for future backtesting)
   
 Also includes a signal formatter for clean terminal output.
=============================================================================
"""

import os
import csv
from datetime import datetime
import config


# =============================================================================
#  DESKTOP NOTIFICATIONS
# =============================================================================

def send_desktop_notification(title, message):
    """
    Send a desktop notification using plyer.
    Falls back silently if plyer isn't available or the system doesn't support it.
    """
    if not config.DESKTOP_NOTIFICATIONS_ENABLED:
        return

    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message[:256],  # plyer has message length limits on some OS
            app_name="BTC Scalper Bot",
            timeout=10,
        )
    except ImportError:
        # plyer not installed — skip silently
        pass
    except Exception as e:
        # Some Linux systems without dbus/notify daemon
        print(f"  [WARN] Desktop notification failed: {e}")


# =============================================================================
#  TELEGRAM — Fully Wired (just add token + chat_id to .env)
# =============================================================================

def _is_telegram_configured():
    """Check if Telegram credentials are present and not placeholder values."""
    token = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID

    if not token or not chat_id:
        return False
    if token == "your_telegram_bot_token_here":
        return False
    if chat_id == "your_telegram_chat_id_here":
        return False
    return True


def send_telegram_alert(message):
    """
    Send alert via Telegram bot.
    
    Setup (one-time):
      1. Open Telegram, search for @BotFather
      2. Send /newbot, follow prompts to create a bot
      3. Copy the bot token (looks like 123456789:ABCdef...)
      4. Start a chat with your new bot (send /start)
      5. Visit https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
      6. Find your chat_id in the JSON response
      7. Add both to .env:
           TELEGRAM_BOT_TOKEN=123456789:ABCdef...
           TELEGRAM_CHAT_ID=987654321
    
    The message is sent with Markdown formatting.
    Errors are caught silently — Telegram failures never crash the bot.
    """
    if not _is_telegram_configured():
        return

    import requests as req

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    try:
        resp = req.post(url, json=payload, timeout=10)
        if not resp.ok:
            # Try again without Markdown (in case of formatting issues)
            payload["parse_mode"] = None
            req.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"  [WARN] Telegram send failed: {e}")


# =============================================================================
#  CSV SIGNAL LOGGER
# =============================================================================

def log_signal_to_csv(signal):
    """
    Append a signal to the CSV log file.
    Creates the file with headers if it doesn't exist.
    
    This log is essential for:
      • Reviewing signal quality during testing
      • Future backtesting module
      • Tracking win/loss rate manually
    """
    filepath = config.SIGNAL_LOG_FILE
    file_exists = os.path.exists(filepath)

    headers = [
        "timestamp", "time_ist", "direction", "strategy", "regime",
        "entry_price", "stop_loss", "take_profit",
        "sl_pct", "tp_pct", "sl_method", "tp_method",
        "contracts", "position_value_usd", "leverage",
        "confidence", "atr", "atr_pct",
        "funding_rate", "open_interest",
        "binance_price", "fear_greed_value", "fear_greed_label",
        "btc_dominance", "delta_volume",
    ]

    row = {
        "timestamp": signal.get("timestamp", ""),
        "time_ist": signal.get("time", ""),
        "direction": signal.get("direction", ""),
        "strategy": signal.get("strategy", ""),
        "regime": signal.get("regime", {}).get("regime", ""),
        "entry_price": signal.get("entry_price", ""),
        "stop_loss": signal.get("stop_loss", ""),
        "take_profit": signal.get("take_profit", ""),
        "sl_pct": signal.get("sl_distance_pct", ""),
        "tp_pct": signal.get("tp_distance_pct", ""),
        "sl_method": signal.get("sl_method", ""),
        "tp_method": signal.get("tp_method", ""),
        "contracts": signal.get("contracts", ""),
        "position_value_usd": signal.get("position_value_usd", ""),
        "leverage": signal.get("leverage", ""),
        "confidence": signal.get("confidence", ""),
        "atr": signal.get("atr", ""),
        "atr_pct": signal.get("atr_pct", ""),
        "funding_rate": signal.get("funding_rate", ""),
        "open_interest": signal.get("open_interest", ""),
        "binance_price": signal.get("binance_price", ""),
        "fear_greed_value": signal.get("fear_greed_value", ""),
        "fear_greed_label": signal.get("fear_greed_label", ""),
        "btc_dominance": signal.get("btc_dominance", ""),
        "delta_volume": signal.get("delta_volume", ""),
    }

    try:
        with open(filepath, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
    except Exception as e:
        print(f"  [WARN] CSV logging failed: {e}")


# =============================================================================
#  SIGNAL FORMATTER — for terminal + notifications
# =============================================================================

def format_signal_text(signal):
    """
    Format a signal into a clean, readable text block.
    Used for both terminal output and notification messages.
    """
    direction = signal["direction"]
    arrow = "🟢 BUY (LONG)" if direction == "BUY" else "🔴 SELL (SHORT)"
    regime = signal.get("regime", {})

    lines = [
        f"{'='*56}",
        f"  ⚡ SIGNAL ALERT — {arrow}",
        f"{'='*56}",
        f"",
        f"  Direction:       {direction}",
        f"  Strategy:        {signal.get('strategy', 'N/A')}",
        f"  Market Regime:   {regime.get('regime', 'N/A')}",
        f"  Confidence:      {signal.get('confidence', 'N/A')}/10",
        f"  Time:            {signal.get('time', 'N/A')}",
        f"",
        f"  ── Price Levels ────────────────────────",
        f"  Entry Price:     ${signal.get('entry_price', 0):,.2f}",
        f"  Stop-Loss:       ${signal.get('stop_loss', 0):,.2f}  ({signal.get('sl_distance_pct', 0):.3f}% — {signal.get('sl_method', '')})",
        f"  Take-Profit:     ${signal.get('take_profit', 0):,.2f}  ({signal.get('tp_distance_pct', 0):.3f}% — {signal.get('tp_method', '')})",
        f"",
        f"  ── Position Sizing ─────────────────────",
        f"  Contracts:       {signal.get('contracts', 0)} lots",
        f"  Position Value:  ${signal.get('position_value_usd', 0):,.2f}",
        f"  Margin Used:     ${signal.get('margin_used_usd', 0):,.2f}",
        f"  Leverage:        {signal.get('leverage', 0)}×",
        f"",
        f"  ── Market Context ──────────────────────",
        f"  ATR:             ${signal.get('atr', 0):,.2f} ({signal.get('atr_pct', 0):.3f}%)",
        f"  Funding Rate:    {signal.get('funding_rate', 0):.6f}",
        f"  Open Interest:   {signal.get('open_interest', 0):,.0f}",
        f"  Binance Price:   ${signal.get('binance_price', 0):,.2f}" if signal.get('binance_price') else "  Binance Price:   N/A",
        f"  Fear & Greed:    {signal.get('fear_greed_value', 'N/A')} ({signal.get('fear_greed_label', 'N/A')})",
        f"  BTC Dominance:   {signal.get('btc_dominance', 'N/A')}%",
        f"",
        f"  ── Confidence Breakdown ────────────────",
    ]

    # Add breakdown
    breakdown = signal.get("confidence_breakdown", {})
    labels = {
        "strategy": "Strategy Strength",
        "binance": "Binance Agreement",
        "funding": "Funding Rate",
        "oi": "Open Interest",
        "fear_greed": "Fear & Greed",
        "btc_dominance": "BTC Dominance",
        "volume": "Volume",
    }
    for key, label in labels.items():
        val = breakdown.get(key, 5.0)
        bar = "█" * int(val) + "░" * (10 - int(val))
        lines.append(f"  {label:.<22} {bar} {val:.1f}/10")

    # Orderbook imbalance adjustment (if present)
    ob_adj = signal.get("confidence_breakdown", {}).get("ob_adjustment",
              signal.get("ob_adjustment", 0))
    if ob_adj and isinstance(ob_adj, (int, float)) and ob_adj != 0:
        adj_label = "Orderbook Imbalance"
        adj_str = f"+{ob_adj:.1f}" if ob_adj > 0 else f"{ob_adj:.1f}"
        adj_style = "boost" if ob_adj > 0 else "penalty"
        lines.append(f"  {adj_label:.<22} {adj_str} ({adj_style})")

    lines.append(f"{'='*56}")

    return "\n".join(lines)


# =============================================================================
#  SEND ALL ALERTS
# =============================================================================

def dispatch_signal(signal):
    """
    Send a signal through ALL configured alert channels.
    Called once per valid signal.
    """
    # Format the text
    text = format_signal_text(signal)

    # 1. Print to terminal
    print(text)

    # 2. Desktop notification (short version)
    direction = signal["direction"]
    notif_msg = (
        f"{direction} @ ${signal['entry_price']:,.2f}\n"
        f"SL: ${signal['stop_loss']:,.2f} | TP: ${signal['take_profit']:,.2f}\n"
        f"Confidence: {signal['confidence']}/10 | {signal['strategy']}"
    )
    send_desktop_notification(
        title=f"⚡ BTC {direction} Signal",
        message=notif_msg,
    )

    # 3. Telegram (when configured)
    telegram_msg = (
        f"*⚡ BTC {direction} Signal*\n\n"
        f"Entry: `${signal['entry_price']:,.2f}`\n"
        f"SL: `${signal['stop_loss']:,.2f}` ({signal['sl_distance_pct']:.3f}%)\n"
        f"TP: `${signal['take_profit']:,.2f}` ({signal['tp_distance_pct']:.3f}%)\n"
        f"Contracts: `{signal['contracts']}` lots\n"
        f"Confidence: `{signal['confidence']}/10`\n"
        f"Strategy: {signal['strategy']}\n"
        f"Regime: {signal.get('regime', {}).get('regime', 'N/A')}"
    )
    send_telegram_alert(telegram_msg)

    # 4. CSV log
    log_signal_to_csv(signal)
