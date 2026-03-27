# ⚡ BTC BRAIN v2 Ultra — AI Swing-Scalp Trading Bot

**Advanced signal bot for BTC/USD Inverse Perpetual on Delta Exchange India.**
Uses Claude AI as the decision engine with 76 computed indicators across 4 timeframes.

> **Mode: SIGNAL ONLY** — Generates signals, you confirm trades.

---

## What Changed from v1

### Removed (unnecessary)
- `signal_engine.py` — redundant, Claude handles all decisions
- `dashboard.py` — terminal eye candy, adds no intelligence
- `view_signals.py` — utility, not core

### Added: 8 New Indicators (21 total)
| New Indicator | Purpose |
|---|---|
| **Stochastic RSI** | Momentum within RSI — precise overbought/oversold |
| **ADX / +DI / -DI** | Trend strength measurement (strong vs weak trend) |
| **OBV (On Balance Volume)** | Volume-price confirmation |
| **Ichimoku Cloud** | Complete trend/support/resistance system |
| **Pivot Points** | S1/S2/S3 and R1/R2/R3 levels |
| **RSI Divergence** | Bullish/bearish divergence detection |
| **Volume Analysis** | Relative volume, trend, climax detection |
| **Candle Patterns** | Engulfing, hammer, doji, three soldiers/crows |
| **Support/Resistance** | Price clustering-based S/R levels |

### Upgraded Architecture
| Change | v1 | v2 |
|---|---|---|
| Scan cycle | 3 min | 5 min (better signal quality) |
| Trading hours | 2PM-2AM IST | **24/7** (BTC never sleeps) |
| Timeframes | 3m, 5m, 15m, 1h | 5m, 15m, 1h, **4h** |
| Indicators per cycle | ~20 | **76** |
| Claude max tokens | 2048 | **4096** (deeper reasoning) |
| SL range | 0.25%-∞ | 0.4%-3% (capped) |
| TP range | 0.50%-∞ | 0.8%-6% (capped) |
| Trailing stops | Manual only | **Auto-trail** to breakeven + profit lock |
| Funding rate | Single value | **10-period history + trend** |
| Fear & Greed | Single value | **7-day trend** |
| Data fetching | Sequential | **Parallel** (ThreadPoolExecutor) |
| Confluence required | 2/3 timeframes | **8+ of 15 signals** |

### Smarter Claude Brain
- 6-step analysis framework (4h → 1h → 15m → 5m cascade)
- 4h trend is KING — never counter-trade it
- Requires 8+ indicator confluence for entries
- Risk:Reward > 1.5:1 enforced
- Explicit guidance for every new indicator
- Self-improvement: tracks last 15 signals + outcomes

---

## Quick Start

```bash
cd btc-scalper

pip install -r requirements.txt

cp .env.example .env
# Add your ANTHROPIC_API_KEY (required)
# Add DELTA_API_KEY/SECRET (optional)
# Add TELEGRAM tokens (optional)

python test_connection.py   # verify everything works
python run_once.py -v       # single test cycle with verbose output
python main.py              # start the bot
```

---

## Architecture

```
btc-scalper/
├── main.py              # Entry point — 5-min loop, auto-trailing stops
├── config.py            # All settings (24/7, wider SL/TP, new indicators)
├── claude_brain.py      # AI engine — 76 indicators → Claude → JSON decision
├── indicators.py        # 21 indicator functions (8 new in v2)
├── data_fetcher.py      # Parallel multi-source data fetching
├── position_manager.py  # 1-trade-at-a-time position state
├── pnl_tracker.py       # P&L calculation with Delta Exchange fees
├── trade_tracker.py     # Signal/trade logging + Y/N confirmation
├── alerts.py            # Telegram, desktop, sound alerts
├── run_once.py          # Single cycle tester
├── test_connection.py   # Pre-flight checker (tests all 21 indicators)
├── requirements.txt     # Dependencies
└── .env.example         # Configuration template
```

---

## How It Works

Every 5 minutes:

1. **Fetch** data from Delta Exchange (4 timeframes), Binance (spot + futures intelligence), Fear & Greed, CoinGecko
2. **Compute** 76 indicator values across 5m/15m/1h/4h
3. **Send** everything to Claude with a structured system prompt
4. **Claude analyzes** using 6-step framework:
   - Step 1: 4h/1h macro bias
   - Step 2: ADX + Ichimoku + OBV trend confirmation
   - Step 3: 15m/5m entry timing (MACD + Stoch RSI + BB)
   - Step 4: 8+ confluence check across 15 signals
   - Step 5: Sentiment & positioning filter
   - Step 6: Risk management (S/R based SL, R:R > 1.5)
5. **Execute** based on Claude's JSON response (BUY/SELL/NO_TRADE)
6. **Auto-trail** stops when in profit

---

## Configuration

Key settings in `.env`:

| Setting | Default | Description |
|---|---|---|
| `CLAUDE_MODEL` | claude-sonnet-4-20250514 | AI model |
| `BOT_CYCLE_SECONDS` | 300 | 5-minute scans |
| `TRADING_START/END_HOUR` | 0/24 | 24/7 trading |
| `SL_ATR_MULTIPLIER` | 2.0 | Wider stops for swing |
| `TP_ATR_MULTIPLIER` | 4.0 | Wider targets |
| `SL_MIN/MAX_PERCENT` | 0.4/3.0 | SL guardrails |
| `TP_MIN/MAX_PERCENT` | 0.8/6.0 | TP guardrails |
| `TRAIL_TO_BREAKEVEN_PCT` | 0.5 | Auto-trail trigger |
| `TRAIL_PROFIT_LOCK_RATIO` | 0.5 | Lock 50% of profits |
| `MIN_CONFIDENCE` | 7 | Minimum confidence to trade |

---

## Notes

- **No 3m candles** — unified to 5m for consistency and better signal quality
- **4h candles** added for macro trend context (the #1 improvement)
- **Auto-trailing stops** protect profits without Claude needing to suggest it
- **Parallel fetching** reduces cycle time by ~40%
- **Signal history** fed back to Claude for self-improvement
- **Volume climax detection** warns against exhaustion moves
- Bot runs 24/7 — BTC is a continuous market, no gap risk
