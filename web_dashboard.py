"""
=============================================================================
 WEB_DASHBOARD.PY — BTC BRAIN v3 Web Dashboard + Bot Runner
=============================================================================
 Single-file Flask app with inline HTML/CSS/JS.
 
 Features:
   • Password-protected login (DASHBOARD_PASSWORD in .env)
   • Live BTC price (auto-refresh 30s)
   • Bot status (running/stopped/cooldown/drawdown)
   • Current position with live P&L
   • Daily P&L summary
   • Trade history from CSV logs
   • Signal history from JSON
   • Claude API call counter
   • Pre-filter stats
   • Bot config display
   • Start/Stop bot control
   • Mobile-responsive dark theme
 
 Runs the trading bot in a background thread.
 Deployed behind Nginx reverse proxy on port 8081.
=============================================================================
"""

import os
import sys
import csv
import json
import time
import threading
import traceback
from datetime import datetime, timezone, timedelta
from functools import wraps

from flask import Flask, request, jsonify, redirect, url_for, make_response, render_template_string
from dotenv import load_dotenv

# ── Load env before importing bot modules ───────────────────────────────
load_dotenv()

# ── Import bot modules ──────────────────────────────────────────────────
import config
import data_fetcher
import position_manager
import pre_filter
import claude_brain
import trade_tracker
from bot_state import BotState

# ── Import main bot for background thread ───────────────────────────────
from main import TradingBot, _running

IST = timezone(timedelta(hours=5, minutes=30))

# =============================================================================
#  FLASK APP
# =============================================================================

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(32).hex())

DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "btcbrain2024")
AUTH_COOKIE_NAME = "btcbrain_auth"
AUTH_COOKIE_VALUE = None  # Set at startup

# ── Bot Thread Management ───────────────────────────────────────────────

bot_thread = None
bot_instance = None
bot_status = "stopped"  # running, stopped, error
bot_error = ""
bot_start_time = None


def run_bot_thread():
    """Run the trading bot in a background thread."""
    global bot_status, bot_error, bot_instance
    import main as main_module

    try:
        bot_status = "running"
        bot_error = ""

        # Reset the _running flag
        main_module._running = True

        bot_instance = TradingBot()
        bot_instance.run()

        bot_status = "stopped"
    except Exception as e:
        bot_status = "error"
        bot_error = str(e)
        traceback.print_exc()


def start_bot():
    """Start the bot in a background thread."""
    global bot_thread, bot_start_time
    import main as main_module

    if bot_thread and bot_thread.is_alive():
        return False, "Bot is already running"

    main_module._running = True
    bot_start_time = time.time()
    bot_thread = threading.Thread(target=run_bot_thread, daemon=True, name="TradingBot")
    bot_thread.start()
    return True, "Bot started"


def stop_bot():
    """Signal the bot to stop."""
    global bot_status
    import main as main_module

    main_module._running = False
    bot_status = "stopping"
    return True, "Stop signal sent"


# =============================================================================
#  AUTH
# =============================================================================

def check_auth():
    """Check if the request has a valid auth cookie."""
    token = request.cookies.get(AUTH_COOKIE_NAME)
    return token == AUTH_COOKIE_VALUE


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not check_auth():
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


# =============================================================================
#  DATA HELPERS
# =============================================================================

def get_bot_state_data():
    """Read bot_state.json safely."""
    try:
        if os.path.exists(config.BOT_STATE_FILE):
            with open(config.BOT_STATE_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def get_active_position():
    """Read active_position.json safely."""
    try:
        return position_manager.get_current_position()
    except Exception:
        return None


def get_signal_history():
    """Read signal_history.json safely."""
    try:
        if os.path.exists(config.SIGNAL_HISTORY_FILE):
            with open(config.SIGNAL_HISTORY_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return []


def get_csv_data(filepath, max_rows=50):
    """Read a CSV file, return list of dicts (newest first)."""
    rows = []
    try:
        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            rows.reverse()  # newest first
            rows = rows[:max_rows]
    except Exception:
        pass
    return rows


def get_live_price():
    """Fetch current BTC price from Delta Exchange."""
    try:
        ticker = data_fetcher.fetch_delta_ticker()
        if ticker:
            return {
                "price": ticker["mark_price"],
                "funding_rate": ticker["funding_rate"],
                "open_interest": ticker["open_interest"],
                "volume": ticker["volume"],
                "high": ticker["high"],
                "low": ticker["low"],
            }
    except Exception:
        pass
    return None


def get_pre_filter_stats():
    """Get pre-filter statistics from bot state."""
    state_data = get_bot_state_data()
    claude_calls = state_data.get("total_claude_calls_today", 0)
    # Estimate: bot runs ~1440 cycles/day (60s each), pre-filter blocks most
    # We track calls made; savings = potential - actual
    return {
        "claude_calls_today": claude_calls,
        "estimated_without_filter": max(claude_calls * 4, 100),  # rough estimate
    }


def get_full_dashboard_data():
    """Aggregate all data for the dashboard."""
    state_data = get_bot_state_data()
    daily_stats = state_data.get("daily_stats", {})
    position = get_active_position()
    price_data = get_live_price()
    signals = get_signal_history()
    trades = get_csv_data(config.TRADES_LOG_FILE, 30)
    pnl_log = get_csv_data(config.PNL_LOG_FILE, 30)
    filter_stats = get_pre_filter_stats()

    # Determine effective bot status
    effective_status = bot_status
    if bot_status == "running":
        in_cooldown = state_data.get("loss_cooldown_until", 0)
        if in_cooldown > time.time():
            effective_status = "cooldown"
        ds = state_data.get("daily_stats", {})
        starting_bal = ds.get("starting_balance_usd", 0)
        daily_pnl = ds.get("total_pnl_usd", 0)
        if starting_bal > 0 and daily_pnl < 0:
            dd_pct = abs(daily_pnl) / starting_bal * 100
            if dd_pct >= config.DAILY_MAX_DRAWDOWN_PCT:
                effective_status = "drawdown-stopped"

    # Position P&L
    pos_pnl = None
    if position and price_data:
        entry = position.get("entry_price", 0)
        current = price_data["price"]
        direction = position.get("direction", "")
        if entry > 0 and current > 0:
            if direction == "LONG":
                pos_pnl = (current - entry) / entry * 100
            else:
                pos_pnl = (entry - current) / entry * 100

    return {
        "bot_status": effective_status,
        "bot_error": bot_error,
        "bot_uptime": int(time.time() - bot_start_time) if bot_start_time and bot_status == "running" else 0,
        "price": price_data,
        "position": position,
        "position_pnl": round(pos_pnl, 4) if pos_pnl is not None else None,
        "daily_stats": daily_stats,
        "signals": signals[-15:],  # last 15
        "trades": trades,
        "pnl_log": pnl_log,
        "claude_calls_today": state_data.get("total_claude_calls_today", 0),
        "filter_stats": filter_stats,
        "config": {
            "mode": config.TRADING_MODE,
            "leverage": config.LEVERAGE,
            "min_confidence": config.MIN_CONFIDENCE,
            "model": config.CLAUDE_MODEL,
            "scan_interval": config.BASE_SCAN_INTERVAL,
            "claude_interval": config.MIN_CLAUDE_INTERVAL,
            "max_drawdown": config.DAILY_MAX_DRAWDOWN_PCT,
            "max_consecutive_losses": config.MAX_CONSECUTIVE_LOSSES,
            "sl_range": f"{config.SL_MIN_PERCENT}%-{config.SL_MAX_PERCENT}%",
            "tp_range": f"{config.TP_MIN_PERCENT}%-{config.TP_MAX_PERCENT}%",
        },
        "consecutive_losses": state_data.get("consecutive_losses", 0),
        "last_trade_was_loss": state_data.get("last_trade_was_loss", False),
        "timestamp": datetime.now(IST).strftime("%I:%M:%S %p IST"),
    }


# =============================================================================
#  ROUTES
# =============================================================================

@app.route("/login", methods=["GET", "POST"])
def login_page():
    error = ""
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == DASHBOARD_PASSWORD:
            resp = make_response(redirect(url_for("dashboard")))
            resp.set_cookie(AUTH_COOKIE_NAME, AUTH_COOKIE_VALUE,
                            max_age=86400 * 7, httponly=True, samesite="Lax")
            return resp
        error = "Wrong password"
    return render_template_string(LOGIN_HTML, error=error)


@app.route("/logout")
def logout():
    resp = make_response(redirect(url_for("login_page")))
    resp.delete_cookie(AUTH_COOKIE_NAME)
    return resp


@app.route("/")
@login_required
def dashboard():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/data")
@login_required
def api_data():
    """Main data endpoint — called by JS every 30s."""
    data = get_full_dashboard_data()
    return jsonify(data)


@app.route("/api/bot/start", methods=["POST"])
@login_required
def api_bot_start():
    ok, msg = start_bot()
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/bot/stop", methods=["POST"])
@login_required
def api_bot_stop():
    ok, msg = stop_bot()
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/bot/force-scan", methods=["POST"])
@login_required
def api_force_scan():
    """Force a Claude API scan, bypassing the pre-filter."""
    try:
        # Fetch fresh market data
        all_data = data_fetcher.fetch_all_data()
        ticker = all_data.get("delta_ticker")
        if not ticker:
            return jsonify({"ok": False, "message": "Failed to fetch market data"})

        # Get current position
        pos = position_manager.get_current_position()

        # Get bot state for context
        state = BotState()

        # Record the Claude call
        state.record_claude_call()

        # Call Claude directly
        analysis = claude_brain.analyze_with_claude(
            all_data, current_position=pos, bot_state=state
        )

        if analysis is None:
            return jsonify({"ok": False, "message": "Claude analysis failed"})

        # Record signal in state
        state.add_signal(analysis)

        # Log the signal
        trade_tracker.log_signal(analysis, trade_taken=False, skip_reason="manual_scan")

        return jsonify({
            "ok": True,
            "message": f"{analysis.get('action', '?')} (conf: {analysis.get('confidence', '?')}/10)",
            "analysis": {
                "action": analysis.get("action", ""),
                "confidence": analysis.get("confidence", 0),
                "reasoning": analysis.get("reasoning", ""),
                "entry_price": analysis.get("entry_price", 0),
                "stop_loss": analysis.get("stop_loss", 0),
                "take_profit": analysis.get("take_profit", 0),
                "market_condition": analysis.get("market_condition", ""),
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "message": f"Error: {str(e)}"})


# =============================================================================
#  LOGIN PAGE HTML
# =============================================================================

LOGIN_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BTC Brain v3 — Login</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0a0a0f;--surface:#12121a;--surface2:#1a1a28;--border:#2a2a3a;
  --text:#e8e8f0;--text2:#8888a0;--accent:#f7931a;--accent2:#ff6b2b;
  --green:#00d68f;--red:#ff4757;--blue:#4a9eff;
}
body{font-family:'Space Grotesk',sans-serif;background:var(--bg);color:var(--text);
  min-height:100vh;display:flex;align-items:center;justify-content:center;
  background-image:radial-gradient(ellipse at 50% 0%,rgba(247,147,26,0.06) 0%,transparent 60%)}
.login-box{background:var(--surface);border:1px solid var(--border);border-radius:16px;
  padding:48px 40px;width:100%;max-width:400px;text-align:center;
  box-shadow:0 24px 80px rgba(0,0,0,0.5)}
.logo{font-family:'JetBrains Mono',monospace;font-size:28px;font-weight:700;
  color:var(--accent);margin-bottom:4px;letter-spacing:-1px}
.logo span{color:var(--text)}
.subtitle{color:var(--text2);font-size:13px;margin-bottom:32px}
input[type=password]{width:100%;padding:14px 18px;background:var(--bg);border:1px solid var(--border);
  border-radius:10px;color:var(--text);font-family:'JetBrains Mono',monospace;font-size:15px;
  outline:none;transition:border 0.2s}
input[type=password]:focus{border-color:var(--accent)}
button{width:100%;padding:14px;margin-top:16px;background:linear-gradient(135deg,var(--accent),var(--accent2));
  border:none;border-radius:10px;color:#000;font-weight:700;font-size:15px;cursor:pointer;
  font-family:'Space Grotesk',sans-serif;transition:transform 0.15s,box-shadow 0.15s}
button:hover{transform:translateY(-1px);box-shadow:0 8px 24px rgba(247,147,26,0.3)}
button:active{transform:translateY(0)}
.error{color:var(--red);font-size:13px;margin-top:12px;font-family:'JetBrains Mono',monospace}
</style>
</head>
<body>
<div class="login-box">
  <div class="logo">⚡ BTC <span>BRAIN</span></div>
  <div class="subtitle">v3 Ultra — Trading Dashboard</div>
  <form method="POST">
    <input type="password" name="password" placeholder="Dashboard Password" autofocus required>
    <button type="submit">Unlock Dashboard</button>
  </form>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
</div>
</body>
</html>"""


# =============================================================================
#  DASHBOARD HTML (single-page app with JS auto-refresh)
# =============================================================================

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BTC Brain v3 — Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#07070c;--surface:#0e0e16;--surface2:#15151f;--surface3:#1c1c2a;
  --border:#252538;--border2:#333350;
  --text:#eaeaf2;--text2:#9898b0;--text3:#606078;
  --accent:#f7931a;--accent2:#ff6b2b;--accent-glow:rgba(247,147,26,0.15);
  --green:#00d68f;--green-dim:rgba(0,214,143,0.12);
  --red:#ff4757;--red-dim:rgba(255,71,87,0.12);
  --blue:#4a9eff;--blue-dim:rgba(74,158,255,0.12);
  --yellow:#ffd93d;
  --radius:12px;--radius-sm:8px;
}
body{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text);
  min-height:100vh;overflow-x:hidden;
  background-image:radial-gradient(ellipse at 20% 0%,rgba(247,147,26,0.04) 0%,transparent 50%),
                    radial-gradient(ellipse at 80% 100%,rgba(74,158,255,0.03) 0%,transparent 50%)}
.mono{font-family:'JetBrains Mono',monospace}

/* ── Header ── */
header{padding:16px 24px;display:flex;align-items:center;justify-content:space-between;
  border-bottom:1px solid var(--border);background:var(--surface);position:sticky;top:0;z-index:100;
  backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px)}
.brand{display:flex;align-items:center;gap:10px}
.brand-icon{font-size:22px}
.brand-name{font-family:'JetBrains Mono',monospace;font-weight:700;font-size:18px;color:var(--accent);letter-spacing:-0.5px}
.brand-name span{color:var(--text)}
.brand-ver{font-size:11px;color:var(--text3);font-family:'JetBrains Mono',monospace;
  background:var(--surface2);padding:2px 8px;border-radius:4px;margin-left:4px}
.header-right{display:flex;align-items:center;gap:16px}
.clock{font-family:'JetBrains Mono',monospace;font-size:13px;color:var(--text2)}
.logout-btn{background:var(--surface2);border:1px solid var(--border);color:var(--text2);
  padding:6px 14px;border-radius:var(--radius-sm);cursor:pointer;font-size:12px;
  font-family:'DM Sans',sans-serif;transition:all 0.2s}
.logout-btn:hover{border-color:var(--red);color:var(--red)}

/* ── Layout ── */
.container{max-width:1400px;margin:0 auto;padding:20px 24px}
.grid{display:grid;gap:16px}
.grid-top{grid-template-columns:1fr 1fr 1fr 1fr;margin-bottom:4px}
.grid-mid{grid-template-columns:1fr 1fr;margin-bottom:4px}
.grid-bot{grid-template-columns:1fr}

/* ── Cards ── */
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  padding:20px;position:relative;overflow:hidden;transition:border-color 0.3s}
.card:hover{border-color:var(--border2)}
.card-label{font-size:11px;text-transform:uppercase;letter-spacing:1.2px;color:var(--text3);
  margin-bottom:10px;font-weight:600}
.card-value{font-family:'JetBrains Mono',monospace;font-size:28px;font-weight:700;line-height:1.1}
.card-sub{font-size:12px;color:var(--text2);margin-top:6px;font-family:'JetBrains Mono',monospace}
.card-badge{position:absolute;top:16px;right:16px;padding:4px 10px;border-radius:20px;
  font-size:11px;font-weight:600;font-family:'JetBrains Mono',monospace}

/* Status colors */
.status-running{background:var(--green-dim);color:var(--green);border:1px solid rgba(0,214,143,0.25)}
.status-stopped{background:var(--red-dim);color:var(--red);border:1px solid rgba(255,71,87,0.25)}
.status-cooldown{background:var(--blue-dim);color:var(--blue);border:1px solid rgba(74,158,255,0.25)}
.status-drawdown-stopped{background:rgba(255,217,61,0.1);color:var(--yellow);border:1px solid rgba(255,217,61,0.25)}
.status-stopping{background:rgba(255,165,0,0.1);color:orange;border:1px solid rgba(255,165,0,0.25)}
.status-error{background:var(--red-dim);color:var(--red);border:1px solid rgba(255,71,87,0.25)}

.pnl-pos{color:var(--green)}
.pnl-neg{color:var(--red)}
.pnl-zero{color:var(--text2)}

/* ── Bot Control ── */
.bot-controls{display:flex;gap:10px;margin-top:14px}
.btn{padding:10px 20px;border:none;border-radius:var(--radius-sm);cursor:pointer;
  font-weight:600;font-size:13px;font-family:'DM Sans',sans-serif;transition:all 0.2s}
.btn-start{background:var(--green);color:#000}
.btn-start:hover{box-shadow:0 4px 16px rgba(0,214,143,0.3)}
.btn-stop{background:var(--red);color:#fff}
.btn-stop:hover{box-shadow:0 4px 16px rgba(255,71,87,0.3)}
.btn-scan{background:var(--blue);color:#fff}
.btn-scan:hover{box-shadow:0 4px 16px rgba(74,158,255,0.3)}
.btn-scan.scanning{opacity:0.6;cursor:wait}
.btn:disabled{opacity:0.4;cursor:not-allowed}

/* ── Position Card ── */
.pos-direction{font-size:15px;font-weight:700;margin-bottom:4px}
.pos-direction.long{color:var(--green)}
.pos-direction.short{color:var(--red)}
.pos-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:10px}
.pos-item{font-family:'JetBrains Mono',monospace;font-size:12px}
.pos-item-label{color:var(--text3);font-size:10px;text-transform:uppercase}
.flat-msg{color:var(--text3);font-family:'JetBrains Mono',monospace;font-size:14px}

/* ── Tables ── */
.section-title{font-size:14px;font-weight:700;margin-bottom:12px;display:flex;
  align-items:center;gap:8px}
.section-title .icon{font-size:16px}
.table-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;font-size:12px;font-family:'JetBrains Mono',monospace}
thead th{text-align:left;padding:8px 10px;color:var(--text3);font-size:10px;
  text-transform:uppercase;letter-spacing:0.8px;border-bottom:1px solid var(--border);
  font-weight:600;white-space:nowrap}
tbody td{padding:7px 10px;border-bottom:1px solid rgba(37,37,56,0.5);white-space:nowrap}
tbody tr:hover{background:var(--surface2)}
.tag{padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}
.tag-buy,.tag-long{background:var(--green-dim);color:var(--green)}
.tag-sell,.tag-short{background:var(--red-dim);color:var(--red)}
.tag-no_trade,.tag-hold{background:var(--blue-dim);color:var(--blue)}
.tag-win{background:var(--green-dim);color:var(--green)}
.tag-loss{background:var(--red-dim);color:var(--red)}
.tag-breakeven{background:var(--blue-dim);color:var(--blue)}
.tag-exit,.tag-reverse{background:rgba(255,165,0,0.12);color:orange}
.tag-pending{background:var(--surface3);color:var(--text3)}

/* ── Config Grid ── */
.config-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px}
.config-item{background:var(--surface2);border-radius:var(--radius-sm);padding:10px 12px}
.config-item-label{font-size:10px;text-transform:uppercase;color:var(--text3);letter-spacing:0.5px}
.config-item-value{font-family:'JetBrains Mono',monospace;font-size:14px;font-weight:600;margin-top:2px}

/* ── Scrollbar ── */
::-webkit-scrollbar{width:6px;height:6px}
::-webkit-scrollbar-track{background:var(--surface)}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}

/* ── Pulse animation ── */
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}
.pulse{animation:pulse 2s infinite}

/* ── Loading shimmer ── */
@keyframes shimmer{0%{background-position:-200% 0}100%{background-position:200% 0}}
.loading{background:linear-gradient(90deg,var(--surface2) 25%,var(--surface3) 50%,var(--surface2) 75%);
  background-size:200% 100%;animation:shimmer 1.5s infinite;border-radius:4px;
  min-height:20px;color:transparent!important}

/* ── Responsive ── */
@media(max-width:1024px){
  .grid-top{grid-template-columns:1fr 1fr}
}
@media(max-width:768px){
  header{padding:12px 16px}
  .container{padding:12px 16px}
  .grid-top{grid-template-columns:1fr 1fr}
  .grid-mid{grid-template-columns:1fr}
  .card{padding:16px}
  .card-value{font-size:22px}
  .brand-ver{display:none}
  .config-grid{grid-template-columns:1fr 1fr}
}
@media(max-width:480px){
  .grid-top{grid-template-columns:1fr}
  .config-grid{grid-template-columns:1fr}
  .pos-grid{grid-template-columns:1fr}
}
</style>
</head>
<body>

<!-- ══ HEADER ══ -->
<header>
  <div class="brand">
    <span class="brand-icon">⚡</span>
    <span class="brand-name">BTC <span>BRAIN</span></span>
    <span class="brand-ver">v3</span>
  </div>
  <div class="header-right">
    <span class="clock mono" id="clock">--:--:-- IST</span>
    <button class="logout-btn" onclick="location.href='/logout'">Logout</button>
  </div>
</header>

<div class="container">

<!-- ══ TOP CARDS ══ -->
<div class="grid grid-top">

  <!-- Bot Status -->
  <div class="card" id="card-status">
    <div class="card-label">Bot Status</div>
    <div class="card-value" id="bot-status-text">--</div>
    <div class="card-sub" id="bot-uptime"></div>
    <div class="bot-controls">
      <button class="btn btn-start" id="btn-start" onclick="botStart()">▶ Start</button>
      <button class="btn btn-stop" id="btn-stop" onclick="botStop()">■ Stop</button>
      <button class="btn btn-scan" id="btn-scan" onclick="forceScan()">🧠 Force Scan</button>
    </div>
  </div>

  <!-- BTC Price -->
  <div class="card">
    <div class="card-label">BTC/USD Price</div>
    <div class="card-value" id="btc-price">--</div>
    <div class="card-sub" id="price-extra"></div>
  </div>

  <!-- Daily P&L -->
  <div class="card">
    <div class="card-label">Daily P&L</div>
    <div class="card-value" id="daily-pnl">--</div>
    <div class="card-sub" id="daily-stats"></div>
  </div>

  <!-- Claude API -->
  <div class="card">
    <div class="card-label">Claude API Today</div>
    <div class="card-value" id="claude-calls">--</div>
    <div class="card-sub" id="filter-stats"></div>
  </div>

</div>

<!-- ══ MID SECTION ══ -->
<div class="grid grid-mid">

  <!-- Current Position -->
  <div class="card">
    <div class="section-title"><span class="icon">📍</span> Current Position</div>
    <div id="position-content">
      <div class="flat-msg">FLAT — No open position</div>
    </div>
  </div>

  <!-- Bot Config -->
  <div class="card">
    <div class="section-title"><span class="icon">⚙️</span> Configuration</div>
    <div class="config-grid" id="config-grid">
      <div class="config-item"><div class="config-item-label">Loading</div><div class="config-item-value">--</div></div>
    </div>
  </div>

</div>

<!-- ══ SIGNAL HISTORY ══ -->
<div class="grid grid-bot">
  <div class="card">
    <div class="section-title"><span class="icon">🧠</span> Signal History (Claude Decisions)</div>
    <div class="table-wrap">
      <table id="signals-table">
        <thead><tr>
          <th>Time</th><th>Decision</th><th>Conf</th><th>Entry</th><th>SL</th><th>TP</th><th>Outcome</th><th>Reasoning</th>
        </tr></thead>
        <tbody id="signals-body"><tr><td colspan="8" style="color:var(--text3)">Loading...</td></tr></tbody>
      </table>
    </div>
  </div>
</div>

<!-- ══ TRADE HISTORY ══ -->
<div class="grid grid-bot">
  <div class="card">
    <div class="section-title"><span class="icon">📈</span> Closed Trades (P&L Log)</div>
    <div class="table-wrap">
      <table id="pnl-table">
        <thead><tr>
          <th>Time</th><th>Direction</th><th>Entry</th><th>Exit</th><th>Contracts</th>
          <th>Gross P&L</th><th>Fees</th><th>Net P&L</th><th>Result</th><th>Reason</th>
        </tr></thead>
        <tbody id="pnl-body"><tr><td colspan="10" style="color:var(--text3)">Loading...</td></tr></tbody>
      </table>
    </div>
  </div>
</div>

<!-- ══ TRADE LOG ══ -->
<div class="grid grid-bot" style="margin-bottom:40px">
  <div class="card">
    <div class="section-title"><span class="icon">📋</span> Trade Entries Log</div>
    <div class="table-wrap">
      <table id="trades-table">
        <thead><tr>
          <th>Time</th><th>Direction</th><th>Conf</th><th>Entry</th><th>SL</th><th>TP</th>
          <th>Contracts</th><th>Reasoning</th>
        </tr></thead>
        <tbody id="trades-body"><tr><td colspan="8" style="color:var(--text3)">Loading...</td></tr></tbody>
      </table>
    </div>
  </div>
</div>

</div><!-- /container -->

<script>
// ═══════════════════════════════════════════════════════════════════════
//  DASHBOARD JS — Auto-refresh every 30s
// ═══════════════════════════════════════════════════════════════════════

let refreshTimer = null;
let lastData = null;

function $(id){ return document.getElementById(id) }

function formatUSD(v, decimals=2){
  const n = parseFloat(v);
  if(isNaN(n)) return '--';
  const sign = n >= 0 ? '+' : '';
  return sign + '$' + n.toFixed(decimals).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function pnlClass(v){
  const n = parseFloat(v);
  if(isNaN(n) || n === 0) return 'pnl-zero';
  return n > 0 ? 'pnl-pos' : 'pnl-neg';
}

function tag(text){
  const cls = 'tag-' + (text || '').toLowerCase().replace(/\s+/g,'_');
  return `<span class="tag ${cls}">${text || '--'}</span>`;
}

function formatSecs(s){
  if(!s || s <= 0) return '';
  const h = Math.floor(s/3600);
  const m = Math.floor((s%3600)/60);
  if(h > 0) return h+'h '+m+'m';
  return m+'m';
}

function truncate(s, max=80){
  if(!s) return '';
  return s.length > max ? s.substring(0, max) + '…' : s;
}

// ── Update clock ──
function updateClock(){
  const now = new Date();
  const ist = new Date(now.getTime() + (5.5*60*60*1000) + (now.getTimezoneOffset()*60*1000));
  const h = ist.getHours(), m = ist.getMinutes(), s = ist.getSeconds();
  const ampm = h >= 12 ? 'PM' : 'AM';
  const hh = h % 12 || 12;
  $('clock').textContent = `${String(hh).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')} ${ampm} IST`;
}
setInterval(updateClock, 1000);
updateClock();

// ── Fetch data ──
async function fetchData(){
  try {
    const resp = await fetch('/api/data');
    if(!resp.ok){ if(resp.status === 302 || resp.status === 401) location.href='/login'; return; }
    const data = await resp.json();
    lastData = data;
    renderDashboard(data);
  } catch(e){
    console.error('Fetch error:', e);
  }
}

// ── Render ──
function renderDashboard(d){
  // Bot Status
  const status = d.bot_status || 'stopped';
  const statusLabels = {
    'running':'● RUNNING','stopped':'○ STOPPED','stopping':'◌ STOPPING',
    'cooldown':'⏸ COOLDOWN','drawdown-stopped':'🛑 DRAWDOWN STOP','error':'✖ ERROR'
  };
  $('bot-status-text').textContent = statusLabels[status] || status.toUpperCase();
  $('bot-status-text').className = 'card-value';

  // Status badge
  let existingBadge = document.querySelector('#card-status .card-badge');
  if(!existingBadge){
    existingBadge = document.createElement('div');
    existingBadge.className = 'card-badge';
    $('card-status').appendChild(existingBadge);
  }
  existingBadge.className = 'card-badge status-' + status;
  existingBadge.textContent = status === 'running' ? 'LIVE' : status.toUpperCase();

  $('bot-uptime').textContent = d.bot_uptime > 0 ? 'Uptime: ' + formatSecs(d.bot_uptime) : '';
  if(d.bot_error) $('bot-uptime').textContent = 'Error: ' + d.bot_error;

  // Buttons
  $('btn-start').disabled = (status === 'running' || status === 'stopping');
  $('btn-stop').disabled = (status !== 'running');

  // BTC Price
  if(d.price){
    $('btc-price').textContent = '$' + parseFloat(d.price.price).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
    const extras = [];
    if(d.price.funding_rate !== undefined) extras.push('FR: ' + (d.price.funding_rate*100).toFixed(4) + '%');
    if(d.price.high) extras.push('H: $' + parseFloat(d.price.high).toLocaleString());
    if(d.price.low) extras.push('L: $' + parseFloat(d.price.low).toLocaleString());
    $('price-extra').textContent = extras.join(' | ');
  } else {
    $('btc-price').textContent = '--';
    $('price-extra').textContent = 'Unable to fetch price';
  }

  // Daily P&L
  const ds = d.daily_stats || {};
  const pnl = ds.total_pnl_usd || 0;
  $('daily-pnl').textContent = formatUSD(pnl, 4);
  $('daily-pnl').className = 'card-value mono ' + pnlClass(pnl);
  const parts = [];
  if(ds.trades_count !== undefined) parts.push(ds.trades_count + ' trades');
  if(ds.wins !== undefined) parts.push('W:' + ds.wins);
  if(ds.losses !== undefined) parts.push('L:' + ds.losses);
  $('daily-stats').textContent = parts.join(' | ');

  // Claude Calls
  $('claude-calls').textContent = d.claude_calls_today || 0;
  const fs = d.filter_stats || {};
  const saved = (fs.estimated_without_filter || 0) - (d.claude_calls_today || 0);
  $('filter-stats').textContent = saved > 0
    ? `~${saved} calls saved by pre-filter`
    : 'Pre-filter active';

  // Position
  renderPosition(d);

  // Config
  renderConfig(d.config || {});

  // Tables
  renderSignals(d.signals || []);
  renderPnlLog(d.pnl_log || []);
  renderTrades(d.trades || []);
}

function renderPosition(d){
  const el = $('position-content');
  const pos = d.position;
  if(!pos){
    el.innerHTML = '<div class="flat-msg">FLAT — No open position</div>';
    return;
  }
  const dir = pos.direction || '';
  const entry = parseFloat(pos.entry_price) || 0;
  const sl = parseFloat(pos.stop_loss) || 0;
  const tp = parseFloat(pos.take_profit) || 0;
  const contracts = pos.contracts || 0;
  const conf = pos.confidence || 0;
  const entryTime = pos.entry_time || '';
  const elapsed = pos.entry_timestamp ? Math.floor((Date.now()/1000 - pos.entry_timestamp)/60) : 0;
  const pnlPct = d.position_pnl;
  const curPrice = d.price ? d.price.price : 0;

  let pnlHtml = '--';
  if(pnlPct !== null && pnlPct !== undefined){
    const cls = pnlPct > 0 ? 'pnl-pos' : pnlPct < 0 ? 'pnl-neg' : 'pnl-zero';
    pnlHtml = `<span class="${cls}">${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(3)}%</span>`;
  }

  el.innerHTML = `
    <div class="pos-direction ${dir.toLowerCase()}">${dir} @ $${entry.toLocaleString('en-US',{minimumFractionDigits:2})}</div>
    <div class="pos-grid">
      <div class="pos-item"><div class="pos-item-label">Live P&L</div>${pnlHtml}</div>
      <div class="pos-item"><div class="pos-item-label">Current</div>$${curPrice ? parseFloat(curPrice).toLocaleString('en-US',{minimumFractionDigits:2}) : '--'}</div>
      <div class="pos-item"><div class="pos-item-label">Stop Loss</div>$${sl.toLocaleString('en-US',{minimumFractionDigits:2})}</div>
      <div class="pos-item"><div class="pos-item-label">Take Profit</div>$${tp.toLocaleString('en-US',{minimumFractionDigits:2})}</div>
      <div class="pos-item"><div class="pos-item-label">Contracts</div>${contracts}</div>
      <div class="pos-item"><div class="pos-item-label">Confidence</div>${conf}/10</div>
      <div class="pos-item"><div class="pos-item-label">Entry Time</div>${entryTime}</div>
      <div class="pos-item"><div class="pos-item-label">Duration</div>${elapsed}m</div>
    </div>`;
}

function renderConfig(cfg){
  const el = $('config-grid');
  if(!cfg || !Object.keys(cfg).length){ el.innerHTML = '<div style="color:var(--text3)">Loading...</div>'; return; }
  const items = [
    ['Mode', (cfg.mode||'').toUpperCase()],
    ['Model', (cfg.model||'').replace('claude-','').replace('-20250514','')],
    ['Leverage', cfg.leverage + 'x'],
    ['Min Confidence', cfg.min_confidence + '/10'],
    ['Scan Interval', cfg.scan_interval + 's'],
    ['Claude Interval', cfg.claude_interval + 's'],
    ['Max Drawdown', cfg.max_drawdown + '%'],
    ['Max Consec Losses', cfg.max_consecutive_losses],
    ['SL Range', cfg.sl_range],
    ['TP Range', cfg.tp_range],
  ];
  el.innerHTML = items.map(([label,val]) =>
    `<div class="config-item"><div class="config-item-label">${label}</div><div class="config-item-value">${val}</div></div>`
  ).join('');
}

function renderSignals(signals){
  const body = $('signals-body');
  if(!signals.length){ body.innerHTML='<tr><td colspan="8" style="color:var(--text3)">No signals yet</td></tr>'; return; }
  body.innerHTML = signals.slice().reverse().map(s => `<tr>
    <td>${s.time || '--'}</td>
    <td>${tag(s.decision)}</td>
    <td>${s.confidence || '--'}</td>
    <td>${s.entry_price ? '$'+parseFloat(s.entry_price).toLocaleString('en-US',{minimumFractionDigits:2}) : '--'}</td>
    <td>${s.stop_loss ? '$'+parseFloat(s.stop_loss).toLocaleString('en-US',{minimumFractionDigits:2}) : '--'}</td>
    <td>${s.take_profit ? '$'+parseFloat(s.take_profit).toLocaleString('en-US',{minimumFractionDigits:2}) : '--'}</td>
    <td>${tag(s.outcome)}</td>
    <td title="${(s.reasoning||'').replace(/"/g,'&quot;')}">${truncate(s.reasoning, 60)}</td>
  </tr>`).join('');
}

function renderPnlLog(rows){
  const body = $('pnl-body');
  if(!rows.length){ body.innerHTML='<tr><td colspan="10" style="color:var(--text3)">No closed trades yet</td></tr>'; return; }
  body.innerHTML = rows.map(r => {
    const net = parseFloat(r.net_pnl_usd) || 0;
    return `<tr>
      <td>${r.time_ist || '--'}</td>
      <td>${tag(r.direction)}</td>
      <td>$${parseFloat(r.entry_price||0).toLocaleString('en-US',{minimumFractionDigits:2})}</td>
      <td>$${parseFloat(r.exit_price||0).toLocaleString('en-US',{minimumFractionDigits:2})}</td>
      <td>${r.contracts || '--'}</td>
      <td class="${pnlClass(r.gross_pnl_usd)}">${formatUSD(r.gross_pnl_usd,4)}</td>
      <td style="color:var(--text3)">$${parseFloat(r.total_fee_usd||0).toFixed(4)}</td>
      <td class="${pnlClass(net)}">${formatUSD(net,4)}</td>
      <td>${tag(r.result)}</td>
      <td>${r.close_reason || '--'}</td>
    </tr>`;
  }).join('');
}

function renderTrades(rows){
  const body = $('trades-body');
  if(!rows.length){ body.innerHTML='<tr><td colspan="8" style="color:var(--text3)">No trades yet</td></tr>'; return; }
  body.innerHTML = rows.map(r => `<tr>
    <td>${r.time || '--'}</td>
    <td>${tag(r.direction)}</td>
    <td>${r.confidence || '--'}</td>
    <td>$${parseFloat(r.entry_price||0).toLocaleString('en-US',{minimumFractionDigits:2})}</td>
    <td>$${parseFloat(r.stop_loss||0).toLocaleString('en-US',{minimumFractionDigits:2})}</td>
    <td>$${parseFloat(r.take_profit||0).toLocaleString('en-US',{minimumFractionDigits:2})}</td>
    <td>${r.contracts || '--'}</td>
    <td title="${(r.reasoning||'').replace(/"/g,'&quot;')}">${truncate(r.reasoning, 60)}</td>
  </tr>`).join('');
}

// ── Bot Controls ──
async function botStart(){
  $('btn-start').disabled = true;
  try {
    const r = await fetch('/api/bot/start', {method:'POST'});
    const d = await r.json();
    if(!d.ok) alert(d.message);
    setTimeout(fetchData, 1000);
  } catch(e){ alert('Failed: '+e); }
}

async function botStop(){
  if(!confirm('Stop the trading bot?')) return;
  $('btn-stop').disabled = true;
  try {
    const r = await fetch('/api/bot/stop', {method:'POST'});
    const d = await r.json();
    setTimeout(fetchData, 2000);
  } catch(e){ alert('Failed: '+e); }
}

async function forceScan(){
  const btn = $('btn-scan');
  btn.disabled = true;
  btn.classList.add('scanning');
  btn.textContent = '🧠 Scanning...';
  try {
    const r = await fetch('/api/bot/force-scan', {method:'POST'});
    const d = await r.json();
    if(d.ok){
      const a = d.analysis;
      alert(`Claude says: ${a.action} (confidence: ${a.confidence}/10)\n\n${a.reasoning}`);
    } else {
      alert('Scan failed: ' + d.message);
    }
    setTimeout(fetchData, 1000);
  } catch(e){ alert('Failed: '+e); }
  btn.disabled = false;
  btn.classList.remove('scanning');
  btn.textContent = '🧠 Force Scan';
}

// ── Init ──
fetchData();
refreshTimer = setInterval(fetchData, 30000);

</script>
</body>
</html>"""


# =============================================================================
#  STARTUP
# =============================================================================

if __name__ == "__main__":
    import hashlib

    # Generate auth cookie value from password
    AUTH_COOKIE_VALUE = hashlib.sha256(
        (DASHBOARD_PASSWORD + app.secret_key[:16] if isinstance(app.secret_key, str)
         else DASHBOARD_PASSWORD + app.secret_key.hex()[:16]).encode()
    ).hexdigest()

    print(f"\n{'='*60}")
    print(f"  ⚡ BTC BRAIN v3 — Web Dashboard")
    print(f"  Mode: {config.TRADING_MODE.upper()}")
    print(f"  Port: 8081")
    print(f"{'='*60}\n")

    # Auto-start the bot
    ok, msg = start_bot()
    print(f"  🤖 Bot: {msg}")

    # Run Flask
    app.run(host="0.0.0.0", port=8081, debug=False, use_reloader=False)
