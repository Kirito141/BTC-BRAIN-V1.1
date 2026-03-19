"""
=============================================================================
 CONFIG.PY — Central Configuration for BTC Perpetuals Scalping Signal Bot
=============================================================================
 All tunable parameters in one place. Reads secrets from .env file.
 
 SL/TP Floor Decision:
   For BTC scalping on 3–5 min candles at 20× leverage, we use:
     • SL floor = 0.25% — tight enough for scalps, but wide enough to
       survive normal 3-min noise (~$200 on a $84k BTC).
     • TP floor = 0.5%  — gives a 1:2 risk-reward minimum.
   The ATR-dynamic values will usually be larger; these floors only
   kick in during ultra-low-volatility periods.
=============================================================================
"""

import os
from dotenv import load_dotenv

# ── Load .env file ──────────────────────────────────────────────────────────
load_dotenv()

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

# Binance — public klines & ticker (high-liquidity reference price)
BINANCE_BASE_URL = "https://api.binance.com"
BINANCE_SYMBOL = "BTCUSDT"

# Alternative.me — Fear & Greed Index
FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=1"

# CoinGecko — Global market data (BTC dominance, total volume)
# Free Demo tier: 30 calls/min, 10K calls/month
COINGECKO_GLOBAL_URL = "https://api.coingecko.com/api/v3/global"

# =============================================================================
#  STRATEGY PARAMETERS
# =============================================================================

# ── Regime Detection Thresholds ─────────────────────────────────────────────
# EMA spread = abs(EMA9 - EMA21) / price * 100
# If spread > threshold → trending. If ATR% > vol threshold → high vol.
REGIME_EMA_SPREAD_TREND_THRESHOLD = 0.15   # % — above this = trending
REGIME_ATR_HIGH_VOL_THRESHOLD = 1.5        # % of price — above = sit out
REGIME_ATR_PERIOD = 14                      # candles for ATR calculation

# ── EMA Crossover Strategy (Trending Market) ────────────────────────────────
EMA_FAST = 9
EMA_SLOW = 21
EMA_CANDLE_INTERVAL = "5m"                 # 5-minute candles
EMA_CANDLES_NEEDED = 50                    # fetch enough for EMA warm-up

# ── RSI Mean-Reversion Strategy (Ranging Market) ────────────────────────────
RSI_PERIOD = 14
RSI_OVERSOLD = 30                          # buy when RSI drops below
RSI_OVERBOUGHT = 70                        # sell when RSI rises above
RSI_CANDLE_INTERVAL = "3m"                 # 3-minute candles
RSI_CANDLES_NEEDED = 50

# =============================================================================
#  SL / TP CONFIGURATION
# =============================================================================

# Dynamic ATR-based multipliers
SL_ATR_MULTIPLIER = 1.5   # Stop-loss = 1.5 × ATR from entry
TP_ATR_MULTIPLIER = 2.5   # Take-profit = 2.5 × ATR from entry

# Minimum floors (% of entry price) — prevents absurdly tight stops
SL_MIN_PERCENT = 0.25     # 0.25% minimum SL distance
TP_MIN_PERCENT = 0.50     # 0.50% minimum TP distance (1:2 R:R floor)

# =============================================================================
#  POSITION SIZING
# =============================================================================
BALANCE_USAGE_PERCENT = 50    # use 50% of available USDT balance
LEVERAGE = 20                 # 20× leverage
DEFAULT_BALANCE_USDT = 100    # fallback if balance can't be fetched

# =============================================================================
#  TRADING HOURS (IST)
# =============================================================================
# Bot generates signals ONLY between 2:00 PM and 2:00 AM IST
# IST = UTC + 5:30
TRADING_START_HOUR_IST = 14   # 2:00 PM IST
TRADING_END_HOUR_IST = 2      # 2:00 AM IST (next day)

# =============================================================================
#  BOT TIMING
# =============================================================================
BOT_CYCLE_SECONDS = 180       # run every 3 minutes (180 seconds)
SIGNAL_COOLDOWN_SECONDS = 900 # 15-min cooldown between same-direction signals
COINGECKO_CACHE_SECONDS = 600 # cache CoinGecko data for 10 minutes

# =============================================================================
#  CONFIDENCE SCORING WEIGHTS
# =============================================================================
# Each component contributes to a 1–10 score
WEIGHT_STRATEGY_STRENGTH = 0.30   # how strong the TA signal is
WEIGHT_BINANCE_AGREEMENT = 0.15   # does Binance price trend agree?
WEIGHT_FUNDING_RATE = 0.15        # funding rate alignment
WEIGHT_OI_TREND = 0.10            # open interest trend
WEIGHT_FEAR_GREED = 0.15          # sentiment alignment
WEIGHT_BTC_DOMINANCE = 0.05      # BTC dominance context
WEIGHT_VOLUME = 0.10              # volume confirmation

# =============================================================================
#  NOTIFICATIONS
# =============================================================================

# Telegram — placeholder, configure later
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Desktop notifications
DESKTOP_NOTIFICATIONS_ENABLED = True

# =============================================================================
#  LOGGING
# =============================================================================
SIGNAL_LOG_FILE = "signals_log.csv"
BOT_LOG_FILE = "bot.log"
