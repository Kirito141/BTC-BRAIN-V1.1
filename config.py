"""
=============================================================================
 CONFIG.PY — BTC BRAIN v2 Ultra Configuration
=============================================================================
 Optimized for smart swing-scalp hybrid trading on BTC perpetuals.
 24-hour market awareness, 5-min scan cycles, wider SL/TP for holding.
=============================================================================
"""

import os
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
#  CLAUDE AI — Trade Analysis Brain
# =============================================================================
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

# Max tokens for Claude response — higher = more reasoning depth
CLAUDE_MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS", "4096"))

# =============================================================================
#  DELTA EXCHANGE — API CREDENTIALS & ENDPOINTS
# =============================================================================
DELTA_API_KEY = os.getenv("DELTA_API_KEY", "")
DELTA_API_SECRET = os.getenv("DELTA_API_SECRET", "")
DELTA_BASE_URL = "https://api.india.delta.exchange"
DELTA_SYMBOL = "BTCUSD"
DELTA_PRODUCT_ID = 27

# =============================================================================
#  EXTERNAL API ENDPOINTS
# =============================================================================
BINANCE_BASE_URL = "https://api.binance.com"
BINANCE_FUTURES_URL = "https://fapi.binance.com"
BINANCE_SYMBOL = "BTCUSDT"
FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=7"  # 7 days for trend
COINGECKO_GLOBAL_URL = "https://api.coingecko.com/api/v3/global"

# =============================================================================
#  POSITION SIZING
# =============================================================================
DEFAULT_BALANCE_USDT = float(os.getenv("TRADING_BALANCE_USD", "100"))
BALANCE_USAGE_PERCENT = int(os.getenv("BALANCE_USAGE_PERCENT", "50"))
LEVERAGE = int(os.getenv("LEVERAGE", "20"))

# =============================================================================
#  TRADING HOURS — 24/7 by default (BTC never sleeps)
# =============================================================================
TRADING_START_HOUR_IST = int(os.getenv("TRADING_START_HOUR", "0"))
TRADING_END_HOUR_IST = int(os.getenv("TRADING_END_HOUR", "24"))

# =============================================================================
#  BOT TIMING
# =============================================================================
# 5-minute cycles — better for swing-scalp hybrid
BOT_CYCLE_SECONDS = int(os.getenv("BOT_CYCLE_SECONDS", "300"))

# Cooldown between same-direction signals — 30 min for swing style
SIGNAL_COOLDOWN_SECONDS = int(os.getenv("SIGNAL_COOLDOWN_SECONDS", "1800"))

# CoinGecko cache (10 min), Binance futures cache (3 min)
COINGECKO_CACHE_SECONDS = 600
BINANCE_FUTURES_CACHE_SECONDS = 180

# =============================================================================
#  SL / TP CONFIGURATION — wider for swing holding
# =============================================================================
SL_ATR_MULTIPLIER = float(os.getenv("SL_ATR_MULTIPLIER", "2.0"))
TP_ATR_MULTIPLIER = float(os.getenv("TP_ATR_MULTIPLIER", "4.0"))

# Wider floors for swing trades
SL_MIN_PERCENT = float(os.getenv("SL_MIN_PERCENT", "0.40"))
TP_MIN_PERCENT = float(os.getenv("TP_MIN_PERCENT", "0.80"))

# Maximum SL/TP caps to prevent absurd levels
SL_MAX_PERCENT = float(os.getenv("SL_MAX_PERCENT", "3.0"))
TP_MAX_PERCENT = float(os.getenv("TP_MAX_PERCENT", "6.0"))

# =============================================================================
#  STRATEGY PARAMETERS
# =============================================================================
# Regime detection
REGIME_EMA_SPREAD_TREND_THRESHOLD = 0.15
REGIME_ATR_HIGH_VOL_THRESHOLD = 2.0  # raised — BTC is volatile, don't sit out too easily
REGIME_ATR_PERIOD = 14

# EMA Crossover
EMA_FAST = 9
EMA_SLOW = 21
EMA_CANDLE_INTERVAL = "5m"
EMA_CANDLES_NEEDED = 100  # more history for better EMAs

# RSI
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
RSI_CANDLE_INTERVAL = "5m"  # unified to 5m
RSI_CANDLES_NEEDED = 100

# Stochastic RSI
STOCH_RSI_PERIOD = 14
STOCH_RSI_K = 3
STOCH_RSI_D = 3

# ADX (trend strength)
ADX_PERIOD = 14
ADX_STRONG_TREND = 25

# Ichimoku
ICHIMOKU_TENKAN = 9
ICHIMOKU_KIJUN = 26
ICHIMOKU_SENKOU_B = 52

# =============================================================================
#  MULTI-TIMEFRAME CANDLE REQUIREMENTS
# =============================================================================
CANDLES_5M_COUNT = 100
CANDLES_15M_COUNT = 100
CANDLES_1H_COUNT = 100
CANDLES_4H_COUNT = 50

# =============================================================================
#  CONFIDENCE SCORING WEIGHTS (rule-based fallback)
# =============================================================================
WEIGHT_STRATEGY_STRENGTH = 0.25
WEIGHT_BINANCE_AGREEMENT = 0.10
WEIGHT_FUNDING_RATE = 0.10
WEIGHT_OI_TREND = 0.10
WEIGHT_FEAR_GREED = 0.10
WEIGHT_BTC_DOMINANCE = 0.05
WEIGHT_VOLUME = 0.10
WEIGHT_MULTI_TF_ALIGNMENT = 0.20  # new: multi-timeframe alignment

# =============================================================================
#  TRAILING STOP CONFIGURATION
# =============================================================================
# Auto trail SL to breakeven when profit exceeds this %
TRAIL_TO_BREAKEVEN_PCT = float(os.getenv("TRAIL_TO_BREAKEVEN_PCT", "0.5"))

# Trail SL by this fraction of profit (e.g., 0.5 = trail 50% of unrealized profit)
TRAIL_PROFIT_LOCK_RATIO = float(os.getenv("TRAIL_PROFIT_LOCK_RATIO", "0.5"))

# =============================================================================
#  NOTIFICATIONS
# =============================================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DESKTOP_NOTIFICATIONS_ENABLED = os.getenv("DESKTOP_NOTIFICATIONS", "true").lower() != "false"
SOUND_ALERTS_ENABLED = os.getenv("SOUND_ALERTS", "true").lower() != "false"

# Auto-accept trades
AUTO_ACCEPT_TRADES = os.getenv("AUTO_ACCEPT_TRADES", "false").lower() == "true"
MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE", "7"))

# =============================================================================
#  LOGGING
# =============================================================================
SIGNAL_LOG_FILE = "signals_log.csv"
TRADES_LOG_FILE = "trades_log.csv"
BOT_LOG_FILE = "bot.log"
PNL_LOG_FILE = "pnl_log.csv"
