# ⚡ BTC BRAIN v3 — Deployment Guide

## What's Built

### 1. `web_dashboard.py` — Flask Web Dashboard
Single-file Flask app with all HTML/CSS/JS inline via `render_template_string()`.

**Features:**
- Password-protected login (password from `DASHBOARD_PASSWORD` in `.env`)
- Live BTC/USD price (auto-refreshes every 30s)
- Bot status with visual badges (RUNNING / STOPPED / COOLDOWN / DRAWDOWN STOP)
- Start/Stop bot buttons (bot runs in a background thread)
- Current position display with live P&L calculation
- Daily P&L summary (trades, wins, losses, net P&L)
- Claude API call counter + pre-filter savings estimate
- Signal history table (from `signal_history.json`)
- Closed trades P&L log (from `pnl_log.csv`)
- Trade entries log (from `trades_log.csv`)
- Full bot config display
- Mobile-responsive dark theme
- IST clock in header

**Architecture:**
- Flask serves the dashboard on port 8081
- Trading bot runs in a daemon thread inside the same process
- Dashboard reads bot state from JSON/CSV files (same files the bot writes)
- JavaScript fetches `/api/data` every 30 seconds for live updates
- No React, no separate template files — everything is inline

### 2. `deploy.sh` — One-Command Server Setup
Run on your DigitalOcean VPS to set up everything:

```bash
# Upload files to server first (see below), then:
sudo ./deploy.sh
```

**What it does:**
1. Installs system packages (Python3, Nginx, Certbot)
2. Creates `/opt/btc-brain/` directory structure
3. Copies all bot files + web dashboard
4. Creates `.env` template (if missing)
5. Sets up Python venv with all dependencies
6. Creates systemd service (`btcbrain.service`)
7. Configures Nginx reverse proxy (port 80/443 → Flask 8081)
8. Updates DuckDNS subdomain (if token provided)
9. Installs SSL certificate via Let's Encrypt

---

## Deployment Steps

### Step 1: Upload files to server

```bash
# From your local machine (where the bot files are):
cd ~/btc-brain-v3

# Copy everything to server
scp -r ./* root@139.59.65.14:/tmp/btc-brain-upload/

# Or use rsync:
rsync -avz --exclude='__pycache__' --exclude='.env' \
  ./ root@139.59.65.14:/tmp/btc-brain-upload/
```

### Step 2: SSH into server and deploy

```bash
ssh root@139.59.65.14

# Go to upload directory
cd /tmp/btc-brain-upload

# Set DuckDNS token (get from https://www.duckdns.org)
export DUCKDNS_TOKEN="your-duckdns-token-here"

# Run deploy
chmod +x deploy.sh
sudo -E ./deploy.sh
```

### Step 3: Configure .env

```bash
sudo nano /opt/btc-brain/app/.env

# MUST SET:
# - ANTHROPIC_API_KEY
# - DELTA_API_KEY + DELTA_API_SECRET (for live trading)
# - DASHBOARD_PASSWORD (change from default!)
# - FLASK_SECRET_KEY (any random string)
# - TRADING_MODE (paper or live)
```

### Step 4: Start the service

```bash
sudo systemctl start btcbrain
sudo systemctl status btcbrain

# Watch logs:
sudo journalctl -u btcbrain -f
```

### Step 5: SSL (if DNS wasn't ready during deploy)

```bash
# Wait for DNS to propagate, then:
sudo certbot --nginx -d btcbrain.duckdns.org
```

---

## Server Architecture

```
Internet
  │
  ├── https://niftybrain.duckdns.org (existing)
  │     └── Nginx :443 → Flask :8080 (Nifty Bot)
  │
  └── https://btcbrain.duckdns.org (new)
        └── Nginx :443 → Flask :8081 (BTC Brain)
```

Both bots run on the same VPS (`139.59.65.14`), different ports.

---

## File Locations on Server

```
/opt/btc-brain/
├── venv/                    # Python virtual environment
└── app/
    ├── .env                 # API keys & config (edit this!)
    ├── web_dashboard.py     # Dashboard + bot runner
    ├── main.py              # Trading bot
    ├── config.py            # Bot configuration
    ├── claude_brain.py      # AI analysis engine
    ├── indicators.py        # Technical indicators
    ├── data_fetcher.py      # Market data fetcher
    ├── delta_client.py      # Delta Exchange API client
    ├── position_manager.py  # Position tracking
    ├── bot_state.py         # Persistent state
    ├── pre_filter.py        # Claude API cost saver
    ├── pnl_tracker.py       # P&L calculation
    ├── trade_tracker.py     # Trade logging
    ├── alerts.py            # Telegram notifications
    ├── bot_state.json       # Runtime state (auto-generated)
    ├── active_position.json # Current position (auto-generated)
    ├── signal_history.json  # Signal log (auto-generated)
    ├── signals_log.csv      # All signals (auto-generated)
    ├── trades_log.csv       # Executed trades (auto-generated)
    ├── pnl_log.csv          # Closed trade P&L (auto-generated)
    └── prompt_logs/         # Claude prompt history
```

---

## Useful Commands

```bash
# Service management
sudo systemctl start btcbrain
sudo systemctl stop btcbrain
sudo systemctl restart btcbrain
sudo systemctl status btcbrain

# View logs
sudo journalctl -u btcbrain -f              # live tail
sudo journalctl -u btcbrain --since '1h'    # last hour
sudo journalctl -u btcbrain --since today    # today

# Check both bots
sudo systemctl status niftybrain btcbrain

# Nginx
sudo nginx -t                    # test config
sudo systemctl reload nginx      # apply changes

# SSL renewal (auto via cron, but manual if needed)
sudo certbot renew

# Check disk/memory
df -h
free -m
htop
```

---

## RAM Considerations

Both bots on one $4/mo droplet (512MB RAM) might be tight. If you see OOM kills:

```bash
# Check memory usage
sudo journalctl -u btcbrain --since '1h' | grep -i "killed"
free -m

# Option A: Add swap (free but slower)
sudo fallocate -l 1G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Option B: Upgrade to $6/mo droplet (1GB RAM) — recommended
```

The systemd service has `MemoryMax=512M` as a safety cap.

---

## DuckDNS Setup

1. Go to https://www.duckdns.org
2. Log in with Google/GitHub
3. Create subdomain: `btcbrain`
4. Note your token
5. The deploy script auto-updates the IP and sets up a cron job

---

## Troubleshooting

**Bot won't start:**
```bash
# Check logs
sudo journalctl -u btcbrain -n 50

# Test manually
cd /opt/btc-brain/app
sudo -u ubuntu /opt/btc-brain/venv/bin/python web_dashboard.py
```

**Dashboard shows "stopped" but bot should be running:**
- The bot thread may have crashed — check logs
- Restart: `sudo systemctl restart btcbrain`

**SSL not working:**
```bash
# Ensure DNS points to server
dig btcbrain.duckdns.org
curl ifconfig.me

# If IPs match, run certbot
sudo certbot --nginx -d btcbrain.duckdns.org
```

**Port conflict:**
```bash
# Check what's using 8081
sudo lsof -i :8081
sudo ss -tlnp | grep 8081
```
