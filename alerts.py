"""
=============================================================================
 ALERTS.PY v3 — Notifications
=============================================================================
"""

import os
import re
import requests
from datetime import datetime, timezone, timedelta
import config

IST = timezone(timedelta(hours=5, minutes=30))


def _md_to_html(text):
    text = re.sub(r'\*(.+?)\*', r'<b>\1</b>', text)
    text = re.sub(r'_(.+?)_', r'<i>\1</i>', text)
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
    return text


def send_telegram_alert(message):
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


def send_heartbeat(price, pos_summary, daily_stats, claude_calls):
    """Send periodic heartbeat to Telegram."""
    now = datetime.now(IST).strftime("%I:%M %p IST")
    pnl = daily_stats.get("total_pnl_usd", 0)
    trades = daily_stats.get("trades_count", 0)
    msg = (
        f"💓 *BTC BRAIN v3 — Alive*\n"
        f"Time: {now}\n"
        f"BTC: `${price:,.2f}`\n"
        f"Position: {pos_summary}\n"
        f"Today: `${pnl:+,.2f}` ({trades} trades)\n"
        f"Claude calls today: {claude_calls}"
    )
    send_telegram_alert(msg)


def send_desktop_notification(title, message):
    if not config.DESKTOP_NOTIFICATIONS_ENABLED:
        return
    try:
        from plyer import notification
        notification.notify(title=title, message=message, timeout=10)
    except Exception:
        pass


def play_signal_sound(direction="BUY"):
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
