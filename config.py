"""
=============================================================================
 CONFIG.PY — Central Configuration for BTC BRAIN Signal Bot
=============================================================================
 All tunable parameters in one place. Reads from .env file.
 
 Everything that a trader might want to tweak is configurable via .env.
 Sensible defaults are provided — you only need to set ANTHROPIC_API_KEY
 to get started. Everything else is optional.
=============================================================================
"""

import os
from dotenv import load_dotenv

# ── Load .env file ──────────────────────────────────────────────────────────
load_dotenv()

# =============================================================================
#  CLAUDE AI — Trade Analysis Brain
# =============================================================================
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Model choice:
#   claude-sonnet-4-20250514  — fast + smart, best for real-time (recommended)
#   claude-opus-4-20250514    — most intelligent, slower + more expensive
#   claude-haiku-3-5-20241022 — fastest + cheapest, less reasoning depth
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

# =============================================================================
#  DELTA EXCHANGE — API CREDENTIALS & ENDPOINTS
# =============================================================================
DELTA_API_KEY = os.getenv("DELTA_API_KEY", "")
DELTA_API_SECRET = os.getenv("DELTA_API_SECRET", "")
DELTA_BASE_URL = "https://api.india.delta.exchange"

# BTC Inverse Perpetual on Delta Exchange India
DELTA_SYMBOL = "BTCUSD"
DELTA_PRODUCT_ID = 27  # Product ID for BTCUSD perpetual

# =============================================================================
#  EXTERNAL API ENDPOINTS (all free, no auth required)
# =============================================================================
BINANCE_BASE_URL = "https://api.binance.com"
BINANCE_SYMBOL = "BTCUSDT"
FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=1"
COINGECKO_GLOBAL_URL = "https://api.coingecko.com/api/v3/global"

# =============================================================================
#  POSITION SIZING
# =============================================================================
# Balance — set in .env, defaults to 100 USD
DEFAULT_BALANCE_USDT = float(os.getenv("TRADING_BALANCE_USD", "100"))

# What % of balance to use per trade, and leverage
BALANCE_USAGE_PERCENT = int(os.getenv("BALANCE_USAGE_PERCENT", "50"))
LEVERAGE = int(os.getenv("LEVERAGE", "20"))

# =============================================================================
#  TRADING HOURS (IST, 24h format)
# =============================================================================
# Bot only generates signals within this window.
# Default: 2:00 PM (14) to 2:00 AM (2) IST
TRADING_START_HOUR_IST = int(os.getenv("TRADING_START_HOUR", "14"))
TRADING_END_HOUR_IST = int(os.getenv("TRADING_END_HOUR", "2"))

# =============================================================================
#  BOT TIMING
# =============================================================================
# How often the bot scans (seconds). Default 180 = 3 minutes.
BOT_CYCLE_SECONDS = int(os.getenv("BOT_CYCLE_SECONDS", "180"))

# Cooldown between same-direction signals (seconds). Default 900 = 15 min.
SIGNAL_COOLDOWN_SECONDS = int(os.getenv("SIGNAL_COOLDOWN_SECONDS", "900"))

# CoinGecko cache duration (seconds). Default 600 = 10 min.
COINGECKO_CACHE_SECONDS = 600

# =============================================================================
#  SL / TP CONFIGURATION
# =============================================================================
# ATR-based multipliers for dynamic SL/TP
SL_ATR_MULTIPLIER = float(os.getenv("SL_ATR_MULTIPLIER", "1.5"))
TP_ATR_MULTIPLIER = float(os.getenv("TP_ATR_MULTIPLIER", "2.5"))

# Minimum floors (% of entry price) — prevents absurdly tight stops
SL_MIN_PERCENT = float(os.getenv("SL_MIN_PERCENT", "0.25"))
TP_MIN_PERCENT = float(os.getenv("TP_MIN_PERCENT", "0.50"))

# =============================================================================
#  STRATEGY PARAMETERS
# =============================================================================
# Regime detection thresholds
REGIME_EMA_SPREAD_TREND_THRESHOLD = 0.15   # % — above = trending
REGIME_ATR_HIGH_VOL_THRESHOLD = 1.5        # % of price — above = sit out
REGIME_ATR_PERIOD = 14

# EMA Crossover (Trending)
EMA_FAST = 9
EMA_SLOW = 21
EMA_CANDLE_INTERVAL = "5m"
EMA_CANDLES_NEEDED = 50

# RSI Mean-Reversion (Ranging)
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
RSI_CANDLE_INTERVAL = "3m"
RSI_CANDLES_NEEDED = 50

# =============================================================================
#  CONFIDENCE SCORING WEIGHTS (used by rule-based fallback engine)
# =============================================================================
WEIGHT_STRATEGY_STRENGTH = 0.30
WEIGHT_BINANCE_AGREEMENT = 0.15
WEIGHT_FUNDING_RATE = 0.15
WEIGHT_OI_TREND = 0.10
WEIGHT_FEAR_GREED = 0.15
WEIGHT_BTC_DOMINANCE = 0.05
WEIGHT_VOLUME = 0.10

# =============================================================================
#  NOTIFICATIONS
# =============================================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Desktop + sound alerts (set to "false" in .env to disable)
DESKTOP_NOTIFICATIONS_ENABLED = os.getenv("DESKTOP_NOTIFICATIONS", "true").lower() != "false"
SOUND_ALERTS_ENABLED = os.getenv("SOUND_ALERTS", "true").lower() != "false"

# Auto-accept trades — when true, bot skips Y/N prompt and accepts all signals
# WARNING: Use with caution. Every BUY/SELL signal will be auto-confirmed.
AUTO_ACCEPT_TRADES = os.getenv("AUTO_ACCEPT_TRADES", "false").lower() == "true"

# Minimum confidence to accept a trade (1-10). Signals below this are blocked.
MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE", "7"))

# =============================================================================
#  LOGGING
# =============================================================================
SIGNAL_LOG_FILE = "signals_log.csv"
TRADES_LOG_FILE = "trades_log.csv"
BOT_LOG_FILE = "bot.log"
