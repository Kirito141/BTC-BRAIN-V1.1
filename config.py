"""
=============================================================================
 CONFIG.PY — BTC BRAIN v3 Configuration
=============================================================================
 Full auto-trading with dynamic sizing, adaptive cycles, cost optimization.
=============================================================================
"""

import os
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
#  CLAUDE AI
# =============================================================================
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
CLAUDE_MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS", "4096"))

# =============================================================================
#  DELTA EXCHANGE — API & ENDPOINTS
# =============================================================================
DELTA_API_KEY = os.getenv("DELTA_API_KEY", "")
DELTA_API_SECRET = os.getenv("DELTA_API_SECRET", "")
DELTA_BASE_URL = "https://api.india.delta.exchange"
DELTA_SYMBOL = "BTCUSD"
DELTA_PRODUCT_ID = 27

# =============================================================================
#  TRADING MODE: "live" or "paper"
# =============================================================================
TRADING_MODE = os.getenv("TRADING_MODE", "paper").lower()

# =============================================================================
#  EXTERNAL ENDPOINTS
# =============================================================================
BINANCE_BASE_URL = "https://api.binance.com"
BINANCE_FUTURES_URL = "https://fapi.binance.com"
BINANCE_SYMBOL = "BTCUSDT"
FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=7"
COINGECKO_GLOBAL_URL = "https://api.coingecko.com/api/v3/global"

# =============================================================================
#  RISK MANAGEMENT — Dynamic Position Sizing
# =============================================================================
LEVERAGE = int(os.getenv("LEVERAGE", "20"))
MAX_BALANCE_USAGE_PERCENT = int(os.getenv("MAX_BALANCE_USAGE_PERCENT", "100"))

# Confidence-based sizing: {min_confidence: usage_percent}
# Higher confidence = bigger position
CONFIDENCE_SIZING = {
    7: 75,   # min confidence — 75% of balance
    8: 100,  # good confidence — 100%
    9: 100,  # great confidence — 100%
    10: 100, # perfect — 100%
}

# Daily drawdown limit — stop trading if daily loss exceeds this %
DAILY_MAX_DRAWDOWN_PCT = float(os.getenv("DAILY_MAX_DRAWDOWN_PCT", "5.0"))

# Consecutive loss protection
MAX_CONSECUTIVE_LOSSES = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "3"))
LOSS_COOLDOWN_MINUTES = int(os.getenv("LOSS_COOLDOWN_MINUTES", "60"))

# Max trade duration — force exit stale positions
MAX_TRADE_DURATION_MINUTES = int(os.getenv("MAX_TRADE_DURATION_MINUTES", "480"))

# =============================================================================
#  BOT TIMING — Adaptive Cycles
# =============================================================================
# Fast scan for indicator checks (no Claude call)
BASE_SCAN_INTERVAL = int(os.getenv("BASE_SCAN_INTERVAL", "60"))

# Minimum interval between Claude API calls
MIN_CLAUDE_INTERVAL = int(os.getenv("MIN_CLAUDE_INTERVAL", "300"))

# Signal cooldown between same-direction entries
SIGNAL_COOLDOWN_SECONDS = int(os.getenv("SIGNAL_COOLDOWN_SECONDS", "1800"))

# Cache durations
COINGECKO_CACHE_SECONDS = 600
BINANCE_FUTURES_CACHE_SECONDS = 120
FEAR_GREED_CACHE_SECONDS = 600

# =============================================================================
#  SL / TP
# =============================================================================
SL_ATR_MULTIPLIER = float(os.getenv("SL_ATR_MULTIPLIER", "2.0"))
TP_ATR_MULTIPLIER = float(os.getenv("TP_ATR_MULTIPLIER", "4.0"))
SL_MIN_PERCENT = float(os.getenv("SL_MIN_PERCENT", "0.40"))
TP_MIN_PERCENT = float(os.getenv("TP_MIN_PERCENT", "0.80"))
SL_MAX_PERCENT = float(os.getenv("SL_MAX_PERCENT", "3.0"))
TP_MAX_PERCENT = float(os.getenv("TP_MAX_PERCENT", "6.0"))

# =============================================================================
#  TRAILING STOPS
# =============================================================================
TRAIL_TO_BREAKEVEN_PCT = float(os.getenv("TRAIL_TO_BREAKEVEN_PCT", "0.5"))
TRAIL_PROFIT_LOCK_RATIO = float(os.getenv("TRAIL_PROFIT_LOCK_RATIO", "0.5"))

# =============================================================================
#  STRATEGY PARAMETERS
# =============================================================================
# Regime detection
REGIME_EMA_SPREAD_TREND_THRESHOLD = 0.15
REGIME_ATR_HIGH_VOL_THRESHOLD = 2.0
REGIME_ATR_PERIOD = 14

# EMAs
EMA_FAST = 9
EMA_SLOW = 21

# RSI
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

# Stochastic RSI
STOCH_RSI_PERIOD = 14
STOCH_RSI_K = 3
STOCH_RSI_D = 3

# ADX
ADX_PERIOD = 14
ADX_STRONG_TREND = 25

# Ichimoku
ICHIMOKU_TENKAN = 9
ICHIMOKU_KIJUN = 26
ICHIMOKU_SENKOU_B = 52

# =============================================================================
#  CANDLE COUNTS
# =============================================================================
CANDLES_5M_COUNT = 100
CANDLES_15M_COUNT = 100
CANDLES_1H_COUNT = 100
CANDLES_4H_COUNT = 50

# =============================================================================
#  PRE-FILTER THRESHOLDS (skip Claude if not met)
# =============================================================================
# Min timeframes that must agree on direction to call Claude
MIN_TF_AGREEMENT = 3
# Min number of "interesting events" to trigger Claude call
MIN_INTERESTING_EVENTS = 2

# =============================================================================
#  CONFIDENCE SCORING WEIGHTS (for pre-filter)
# =============================================================================
WEIGHT_STRATEGY_STRENGTH = 0.25
WEIGHT_BINANCE_AGREEMENT = 0.10
WEIGHT_FUNDING_RATE = 0.10
WEIGHT_OI_TREND = 0.10
WEIGHT_FEAR_GREED = 0.10
WEIGHT_BTC_DOMINANCE = 0.05
WEIGHT_VOLUME = 0.10
WEIGHT_MULTI_TF_ALIGNMENT = 0.20

# =============================================================================
#  NOTIFICATIONS
# =============================================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DESKTOP_NOTIFICATIONS_ENABLED = os.getenv("DESKTOP_NOTIFICATIONS", "true").lower() != "false"
SOUND_ALERTS_ENABLED = os.getenv("SOUND_ALERTS", "true").lower() != "false"
HEARTBEAT_INTERVAL_MINUTES = int(os.getenv("HEARTBEAT_INTERVAL_MINUTES", "60"))

# =============================================================================
#  CONFIDENCE
# =============================================================================
MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE", "7"))

# =============================================================================
#  LOGGING & PERSISTENCE
# =============================================================================
SIGNAL_LOG_FILE = "signals_log.csv"
TRADES_LOG_FILE = "trades_log.csv"
BOT_LOG_FILE = "bot.log"
PNL_LOG_FILE = "pnl_log.csv"
SIGNAL_HISTORY_FILE = "signal_history.json"
DAILY_PNL_FILE = "daily_pnl.json"
POSITION_FILE = "active_position.json"
BOT_STATE_FILE = "bot_state.json"
PROMPT_LOG_DIR = "prompt_logs"
