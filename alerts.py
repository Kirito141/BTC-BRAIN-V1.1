"""
=============================================================================
 ALERTS.PY — Notification & Logging System
=============================================================================
"""

import os
import csv
import requests
from datetime import datetime, timezone, timedelta
import config

IST = timezone(timedelta(hours=5, minutes=30))


def _md_to_html(text):
    """Convert basic Markdown (*bold*, _italic_, `code`) to Telegram HTML.
    Also strips any raw Markdown syntax that could break Telegram's parser.
    Using HTML avoids silent failures when Claude's reasoning contains
    special chars like underscores, asterisks, or dollar signs.
    """
    import re
    # Bold: *text* → <b>text</b>
    text = re.sub(r'\*(.+?)\*', r'<b>\1</b>', text)
    # Italic: _text_ → <i>text</i>
    text = re.sub(r'_(.+?)_', r'<i>\1</i>', text)
    # Inline code: `text` → <code>text</code>
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
    return text


def send_telegram_alert(message):
    """Send message via Telegram bot using HTML parse_mode.
    HTML is more robust than Markdown — special chars ($, _, *, etc.)
    in Claude's reasoning won't silently drop the message.
    """
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": _md_to_html(message),
            "parse_mode": "HTML",
        }, timeout=10)
    except Exception as e:
        print(f"  [WARN] Telegram failed: {e}")


def send_desktop_notification(title, message):
    """Send desktop notification via plyer."""
    if not config.DESKTOP_NOTIFICATIONS_ENABLED:
        return
    try:
        from plyer import notification
        notification.notify(title=title, message=message, timeout=10)
    except Exception:
        pass


def play_signal_sound(direction="BUY"):
    """Play alert sound."""
    if not config.SOUND_ALERTS_ENABLED:
        return
    try:
        if os.name == "posix":
            if os.uname().sysname == "Darwin":
                sound = "Glass" if direction == "BUY" else "Basso"
                os.system(f'afplay /System/Library/Sounds/{sound}.aiff &')
            else:
                os.system("paplay /usr/share/sounds/freedesktop/stereo/complete.oga 2>/dev/null &")
    except Exception:
        pass


def log_signal_to_csv(signal):
    """Log signal to CSV file."""
    filepath = config.SIGNAL_LOG_FILE
    file_exists = os.path.exists(filepath)
    headers = [
        "timestamp", "time", "direction", "confidence", "strategy",
        "entry_price", "stop_loss", "take_profit",
        "regime", "funding_rate", "fear_greed",
    ]
    row = {
        "timestamp": signal.get("timestamp", ""),
        "time": signal.get("time", ""),
        "direction": signal.get("direction", signal.get("action", "")),
        "confidence": signal.get("confidence", ""),
        "strategy": signal.get("strategy", "claude_brain"),
        "entry_price": signal.get("entry_price", ""),
        "stop_loss": signal.get("stop_loss", ""),
        "take_profit": signal.get("take_profit", ""),
        "regime": signal.get("regime", ""),
        "funding_rate": signal.get("funding_rate", ""),
        "fear_greed": signal.get("fear_greed", ""),
    }
    try:
        with open(filepath, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=headers)
            if not file_exists:
                w.writeheader()
            w.writerow(row)
    except Exception:
        pass
