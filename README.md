# ⚡ BTC Perpetuals Scalping Signal Bot

**Signal-only bot for BTC/USD Inverse Perpetual on Delta Exchange India.**  
Generates high-confidence trading signals using multi-source data analysis.

> **Mode: TESTING PHASE** — Generates signals only. No auto-trading yet.

---

## Quick Start

```bash
# 1. Clone/copy the project
cd btc-scalper

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure your API keys
cp .env.example .env
# Edit .env with your Delta Exchange API key & secret

# 4. Pre-flight check — verify all APIs are reachable
python test_connection.py

# 5. Run a single test cycle (no loop)
python run_once.py --verbose

# 6. Start the bot (loops every 3 minutes)
python main.py
```

---

## Architecture

```
btc-scalper/
├── main.py              # Entry point — runs the 3-min loop
├── config.py            # All settings, thresholds, API URLs
├── data_fetcher.py      # API calls to all 4 data sources
├── indicators.py        # EMA, RSI, ATR, regime detection, SL/TP
├── signal_engine.py     # Signal logic + confidence scoring
├── alerts.py            # Desktop notifs, Telegram, CSV logging
├── dashboard.py         # Rich terminal dashboard
├── test_connection.py   # Pre-flight API & dependency checker
├── run_once.py          # Single-cycle runner for testing
├── view_signals.py      # Signal history viewer & analyzer
├── requirements.txt     # Python dependencies
├── .env.example         # Environment variables template
└── signals_log.csv      # Auto-generated signal history
```

### Utility Commands

```bash
# Pre-flight check (run before starting)
python test_connection.py

# Single cycle with verbose indicator output
python run_once.py --verbose

# View all past signals
python view_signals.py

# View last 10 signals
python view_signals.py --last 10

# View only BUY signals with confidence >= 7
python view_signals.py --direction BUY --min-confidence 7

# Summary stats only
python view_signals.py --summary
```

---

## Strategy: Adaptive Regime-Based

The bot **detects the market condition first**, then applies the right strategy:

| Regime | Detection | Strategy | Candles |
|--------|-----------|----------|---------|
| **Trending** | EMA spread > 0.15% | EMA 9/21 Crossover | 5-min |
| **Ranging** | EMA spread ≤ 0.15% | RSI Mean-Reversion | 3-min |
| **High Volatility** | ATR > 1.5% of price | **Sit out** | — |

---

## Data Sources

| Source | Data | Auth Required |
|--------|------|---------------|
| Delta Exchange | Candles, ticker, orderbook, funding rate, OI | API key (for balance only) |
| Binance | BTC spot price (reference) | None |
| Alternative.me | Fear & Greed Index (0–100) | None |
| CoinGecko | BTC dominance, global volume | None (free tier) |

---

## Signal Output

Each signal includes:
- **Direction**: BUY or SELL
- **Market Regime**: trending / ranging
- **Strategy Used**: EMA crossover / RSI reversion
- **Confidence Score**: 1–10 (weighted multi-source)
- **Entry Price**: exact mark price at signal time
- **Stop-Loss**: dynamic ATR-based, min floor 0.25%
- **Take-Profit**: dynamic ATR-based, min floor 0.50%
- **Contracts**: based on 50% balance at 20× leverage
- **Funding Rate & OI**: at time of signal
- **Fear & Greed**: index value at time of signal

---

## Configuration

All parameters are in `config.py`. Key settings:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `LEVERAGE` | 20× | Position leverage |
| `BALANCE_USAGE_PERCENT` | 50% | % of balance per trade |
| `SL_ATR_MULTIPLIER` | 1.5× | SL = 1.5 × ATR |
| `TP_ATR_MULTIPLIER` | 2.5× | TP = 2.5 × ATR |
| `SL_MIN_PERCENT` | 0.25% | Minimum SL floor |
| `TP_MIN_PERCENT` | 0.50% | Minimum TP floor |
| `BOT_CYCLE_SECONDS` | 180 | Check every 3 min |
| `SIGNAL_COOLDOWN_SECONDS` | 900 | 15 min between same-direction |
| `TRADING_START_HOUR_IST` | 14 | Start at 2 PM IST |
| `TRADING_END_HOUR_IST` | 2 | End at 2 AM IST |

---

## Trading Hours

Signals only between **2:00 PM – 2:00 AM IST**.  
Outside these hours, the bot runs but stays silent.

---

## Confidence Scoring

Weighted from 7 components:

| Component | Weight | Logic |
|-----------|--------|-------|
| Strategy Strength | 30% | How strong the TA signal is |
| Binance Agreement | 15% | Does Binance trend agree? |
| Funding Rate | 15% | Contrarian — negative FR favors longs |
| Open Interest | 10% | Rising OI = conviction |
| Fear & Greed | 15% | Contrarian — extreme fear = buy |
| BTC Dominance | 5% | High dominance = BTC strength |
| Volume | 10% | Higher volume = more conviction |

---

## Telegram Setup

Telegram is fully wired — just add your credentials:

1. Open Telegram, search for **@BotFather**
2. Send `/newbot`, follow prompts to create a bot
3. Copy the bot token (looks like `123456789:ABCdef...`)
4. Start a chat with your new bot (send `/start`)
5. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
6. Find your `chat_id` in the JSON response
7. Add both to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456789:ABCdef...
   TELEGRAM_CHAT_ID=987654321
   ```

Signals will be sent to your Telegram automatically alongside desktop notifications.

---

## Future Scope (architecture ready)

- [ ] Auto order placement on Delta Exchange
- [ ] Telegram bot with inline commands
- [ ] Backtesting module (replay signals_log.csv)
- [ ] Web dashboard (Flask/FastAPI)

---

## Notes

- **CoinGecko**: cached for 10 min to respect free tier (30 calls/min, 10K/month)
- **Error resilience**: if any single API fails, bot continues with reduced confidence
- **Signal log**: every signal saved to `signals_log.csv` for review
- **Desktop notifications**: uses `plyer` — falls back to console if unavailable
