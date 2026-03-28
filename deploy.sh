#!/bin/bash
# =============================================================================
#  DEPLOY.SH — BTC BRAIN v3 Server Deployment
# =============================================================================
#  Sets up everything on DigitalOcean Ubuntu 24.04 VPS:
#    • /opt/btc-brain/ directory structure
#    • Python venv + dependencies
#    • Copies all bot + dashboard files
#    • Creates .env template if missing
#    • Systemd service (auto-restart)
#    • Nginx reverse proxy (HTTPS → Flask :8081)
#    • DuckDNS subdomain setup
#    • Let's Encrypt SSL via Certbot
#
#  Usage:
#    chmod +x deploy.sh
#    sudo ./deploy.sh
#
#  After deploy:
#    1. Edit /opt/btc-brain/app/.env with your API keys
#    2. sudo systemctl restart btcbrain
#    3. Visit https://btcbrain.duckdns.org
# =============================================================================

set -euo pipefail

# ── Colors ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }
info() { echo -e "${CYAN}[→]${NC} $1"; }

# ── Check root ──
if [[ $EUID -ne 0 ]]; then
    err "Run as root: sudo ./deploy.sh"
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  ⚡ BTC BRAIN v3 — Server Deployment"
echo "═══════════════════════════════════════════════════════════"
echo ""

# =============================================================================
#  CONFIGURATION
# =============================================================================

APP_DIR="/opt/btc-brain"
APP_CODE="${APP_DIR}/app"
VENV_DIR="${APP_DIR}/venv"
SERVICE_NAME="btcbrain"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
NGINX_CONF="/etc/nginx/sites-available/btcbrain"
NGINX_LINK="/etc/nginx/sites-enabled/btcbrain"
DOMAIN="btcbrain.duckdns.org"
FLASK_PORT=8081
RUN_USER="ubuntu"

# DuckDNS config — set your token here or in env
DUCKDNS_TOKEN="${DUCKDNS_TOKEN:-}"
DUCKDNS_SUBDOMAIN="btcbrain"

# Source directory — where the bot files currently are
# If running from the repo directory:
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "  App Dir:     ${APP_DIR}"
echo "  Domain:      ${DOMAIN}"
echo "  Flask Port:  ${FLASK_PORT}"
echo "  Source:      ${SOURCE_DIR}"
echo ""

# =============================================================================
#  STEP 1: System packages
# =============================================================================

info "Installing system packages..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip nginx certbot python3-certbot-nginx curl > /dev/null 2>&1
log "System packages installed"

# =============================================================================
#  STEP 2: Directory structure
# =============================================================================

info "Creating directory structure..."
mkdir -p "${APP_CODE}"
mkdir -p "${APP_CODE}/prompt_logs"
log "Directories created: ${APP_DIR}"

# =============================================================================
#  STEP 3: Copy bot files
# =============================================================================

info "Copying bot files..."

BOT_FILES=(
    "main.py"
    "config.py"
    "claude_brain.py"
    "indicators.py"
    "data_fetcher.py"
    "delta_client.py"
    "position_manager.py"
    "bot_state.py"
    "pre_filter.py"
    "pnl_tracker.py"
    "trade_tracker.py"
    "alerts.py"
    "web_dashboard.py"
    "run_once.py"
    "test_connection.py"
    "requirements.txt"
)

copied=0
for f in "${BOT_FILES[@]}"; do
    if [[ -f "${SOURCE_DIR}/${f}" ]]; then
        cp "${SOURCE_DIR}/${f}" "${APP_CODE}/${f}"
        ((copied++))
    else
        warn "Missing: ${f}"
    fi
done
log "Copied ${copied} files to ${APP_CODE}"

# =============================================================================
#  STEP 4: Create .env if missing
# =============================================================================

ENV_FILE="${APP_CODE}/.env"
if [[ ! -f "${ENV_FILE}" ]]; then
    info "Creating .env template..."
    cat > "${ENV_FILE}" << 'ENVEOF'
# ═══════════════════════════════════════════════════════════════
#  BTC BRAIN v3 — Environment Configuration
# ═══════════════════════════════════════════════════════════════

# ── Claude AI (REQUIRED) ──
ANTHROPIC_API_KEY=your_anthropic_api_key_here
CLAUDE_MODEL=claude-sonnet-4-20250514
CLAUDE_MAX_TOKENS=4096

# ── Delta Exchange India ──
DELTA_API_KEY=your_delta_api_key_here
DELTA_API_SECRET=your_delta_api_secret_here

# ── Trading Mode: "live" or "paper" ──
TRADING_MODE=paper

# ── Risk Settings ──
LEVERAGE=20
MIN_CONFIDENCE=7
DAILY_MAX_DRAWDOWN_PCT=5.0
MAX_CONSECUTIVE_LOSSES=3
LOSS_COOLDOWN_MINUTES=60

# ── Timing ──
BASE_SCAN_INTERVAL=60
MIN_CLAUDE_INTERVAL=300
SIGNAL_COOLDOWN_SECONDS=1800

# ── SL/TP ──
SL_ATR_MULTIPLIER=2.0
TP_ATR_MULTIPLIER=4.0
SL_MIN_PERCENT=0.40
SL_MAX_PERCENT=3.0
TP_MIN_PERCENT=0.80
TP_MAX_PERCENT=6.0
TRAIL_TO_BREAKEVEN_PCT=0.5
TRAIL_PROFIT_LOCK_RATIO=0.5

# ── Telegram Alerts (optional) ──
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# ── Dashboard ──
DASHBOARD_PASSWORD=changeme_strong_password_here
FLASK_SECRET_KEY=changeme_random_string_here

# ── Notifications ──
DESKTOP_NOTIFICATIONS=false
SOUND_ALERTS=false
HEARTBEAT_INTERVAL_MINUTES=60
ENVEOF
    log "Created .env template at ${ENV_FILE}"
    warn "⚠️  EDIT ${ENV_FILE} with your actual API keys before starting!"
else
    log ".env already exists — skipping"
fi

# =============================================================================
#  STEP 5: Python venv + dependencies
# =============================================================================

info "Setting up Python virtual environment..."
python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --upgrade pip -q
"${VENV_DIR}/bin/pip" install -q flask python-dotenv
"${VENV_DIR}/bin/pip" install -q -r "${APP_CODE}/requirements.txt"
log "Python venv ready with all dependencies"

# =============================================================================
#  STEP 6: Fix ownership
# =============================================================================

info "Setting file ownership..."
chown -R ${RUN_USER}:${RUN_USER} "${APP_DIR}"
log "Ownership set to ${RUN_USER}"

# =============================================================================
#  STEP 7: Systemd service
# =============================================================================

info "Creating systemd service..."
cat > "${SERVICE_FILE}" << EOF
[Unit]
Description=BTC Brain v3 Trading Bot Dashboard
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${APP_CODE}
Environment="PATH=${VENV_DIR}/bin:/usr/bin:/bin"
Environment="PYTHONUNBUFFERED=1"
ExecStart=${VENV_DIR}/bin/python web_dashboard.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Safety limits
MemoryMax=512M
CPUQuota=80%

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ${SERVICE_NAME}
log "Systemd service created and enabled"

# =============================================================================
#  STEP 8: Nginx reverse proxy
# =============================================================================

info "Configuring Nginx reverse proxy..."
cat > "${NGINX_CONF}" << EOF
server {
    listen 80;
    server_name ${DOMAIN};

    # Redirect HTTP to HTTPS (Certbot will modify this)
    location / {
        proxy_pass http://127.0.0.1:${FLASK_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 90;
        proxy_connect_timeout 30;

        # WebSocket support (if needed later)
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Health check endpoint
    location /health {
        proxy_pass http://127.0.0.1:${FLASK_PORT}/api/data;
        access_log off;
    }
}
EOF

# Enable site
ln -sf "${NGINX_CONF}" "${NGINX_LINK}"

# Test and reload nginx
nginx -t 2>/dev/null && nginx -s reload
log "Nginx configured for ${DOMAIN} → localhost:${FLASK_PORT}"

# =============================================================================
#  STEP 9: DuckDNS setup
# =============================================================================

if [[ -n "${DUCKDNS_TOKEN}" ]]; then
    info "Updating DuckDNS..."

    # Get server's public IP
    SERVER_IP=$(curl -s ifconfig.me || curl -s icanhazip.com || echo "")

    if [[ -n "${SERVER_IP}" ]]; then
        DUCK_RESULT=$(curl -s "https://www.duckdns.org/update?domains=${DUCKDNS_SUBDOMAIN}&token=${DUCKDNS_TOKEN}&ip=${SERVER_IP}")
        if [[ "${DUCK_RESULT}" == "OK" ]]; then
            log "DuckDNS updated: ${DOMAIN} → ${SERVER_IP}"
        else
            warn "DuckDNS update failed: ${DUCK_RESULT}"
        fi
    else
        warn "Could not determine public IP for DuckDNS"
    fi

    # Set up cron job for DuckDNS auto-update (every 5 minutes)
    DUCK_CRON="*/5 * * * * curl -s 'https://www.duckdns.org/update?domains=${DUCKDNS_SUBDOMAIN}&token=${DUCKDNS_TOKEN}&ip=' > /dev/null 2>&1"
    (crontab -u ${RUN_USER} -l 2>/dev/null | grep -v "duckdns.org.*${DUCKDNS_SUBDOMAIN}" ; echo "${DUCK_CRON}") | crontab -u ${RUN_USER} -
    log "DuckDNS cron job installed"
else
    warn "DUCKDNS_TOKEN not set — skipping DuckDNS setup"
    warn "Set it manually: export DUCKDNS_TOKEN=your-token && sudo -E ./deploy.sh"
    warn "Or update DNS manually to point ${DOMAIN} to this server's IP"
fi

# =============================================================================
#  STEP 10: SSL via Let's Encrypt
# =============================================================================

info "Setting up SSL with Let's Encrypt..."
if command -v certbot &> /dev/null; then
    # Check if domain resolves to this server
    SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || echo "unknown")
    DOMAIN_IP=$(dig +short "${DOMAIN}" 2>/dev/null || echo "")

    if [[ "${SERVER_IP}" == "${DOMAIN_IP}" ]]; then
        certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos \
            --email "admin@${DOMAIN}" --redirect 2>/dev/null || {
            warn "Certbot failed — you may need to run it manually after DNS propagates:"
            warn "  sudo certbot --nginx -d ${DOMAIN}"
        }
        log "SSL certificate installed"
    else
        warn "Domain ${DOMAIN} doesn't point to this server yet (${SERVER_IP} vs ${DOMAIN_IP})"
        warn "After DNS propagates, run: sudo certbot --nginx -d ${DOMAIN}"
    fi
else
    warn "Certbot not found — install with: sudo apt install certbot python3-certbot-nginx"
fi

# =============================================================================
#  DONE
# =============================================================================

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  ✅ BTC BRAIN v3 — Deployment Complete!"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "  📁 App directory:    ${APP_CODE}"
echo "  🔧 Service name:     ${SERVICE_NAME}"
echo "  🌐 URL:              https://${DOMAIN}"
echo "  🔌 Flask port:       ${FLASK_PORT}"
echo ""
echo "  ── Next Steps ──"
echo ""
echo "  1. Edit your .env file with actual API keys:"
echo "     sudo nano ${APP_CODE}/.env"
echo ""
echo "  2. Start the service:"
echo "     sudo systemctl start ${SERVICE_NAME}"
echo ""
echo "  3. Check status:"
echo "     sudo systemctl status ${SERVICE_NAME}"
echo "     sudo journalctl -u ${SERVICE_NAME} -f"
echo ""
echo "  4. If SSL wasn't set up (DNS not ready):"
echo "     sudo certbot --nginx -d ${DOMAIN}"
echo ""
echo "  ── Useful Commands ──"
echo ""
echo "     sudo systemctl restart ${SERVICE_NAME}"
echo "     sudo systemctl stop ${SERVICE_NAME}"
echo "     sudo journalctl -u ${SERVICE_NAME} --since '1 hour ago'"
echo "     sudo tail -f ${APP_CODE}/bot.log"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""
