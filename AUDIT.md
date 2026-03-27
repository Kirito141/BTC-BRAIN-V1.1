# BTC BRAIN v2 — Complete Issue Audit

## CRITICAL ISSUES

### Issue #1: 180s cycle instead of 300s — YOUR .ENV FILE
**Root cause**: Your `.env` file on Mac still has `BOT_CYCLE_SECONDS=180` from v1.
The code in config.py correctly reads: `BOT_CYCLE_SECONDS = int(os.getenv("BOT_CYCLE_SECONDS", "300"))`
But your .env overrides it to 180.

**Fix**: Edit your `.env` file:
```
BOT_CYCLE_SECONDS=300
```

**Other stale .env values to check/update**:
- `SIGNAL_COOLDOWN_SECONDS` — should be 1800 (was 900 in v1)
- `SL_ATR_MULTIPLIER` — should be 2.0 (was 1.5)
- `TP_ATR_MULTIPLIER` — should be 4.0 (was 2.5)
- `SL_MIN_PERCENT` — should be 0.40 (was 0.25)
- `TP_MIN_PERCENT` — should be 0.80 (was 0.50)
- `TRADING_START_HOUR` — should be 0 (was 14)
- `TRADING_END_HOUR` — should be 24 (was 2)
- `CLAUDE_MAX_TOKENS` — should be 4096 (was missing/defaulted to 2048)
- `TRAIL_TO_BREAKEVEN_PCT` — should be 0.5 (new in v2)
- `TRAIL_PROFIT_LOCK_RATIO` — should be 0.5 (new in v2)

### Issue #2: Old v1 files still in GitHub repo
Your repo likely still has:
- `signal_engine.py` — REMOVED in v2 (Claude handles everything)
- `dashboard.py` — REMOVED in v2
- `view_signals.py` — REMOVED in v2

These dead files won't cause crashes but add confusion.

**Fix**: Delete them from repo:
```bash
cd ~/BTC-BRAIN
rm -f signal_engine.py dashboard.py view_signals.py
git add -A
git commit -m "remove deprecated v1 files"
git push
```

### Issue #3: PnL calculation uses WRONG formula for inverse perpetuals
**Location**: pnl_tracker.py line 24
**Bug**: `notional = contracts * entry_price` — this is WRONG for inverse contracts.

Delta Exchange BTC inverse perpetuals are denominated in USD but margined in BTC.
For inverse contracts:
- 1 contract = 1 USD of BTC
- Notional in BTC = contracts / price
- P&L formula is different from linear contracts

**Current** (wrong for inverse):
```python
notional = contracts * entry_price
gross_pnl_usd = notional * (gross_pnl_pct / 100)
```

**Should be** (inverse perpetual P&L):
```python
# For inverse perps: PnL = contracts * (1/entry - 1/exit) for LONG
# Or equivalently: PnL = contracts * (exit - entry) / (entry * exit)
if direction == "LONG":
    gross_pnl_usd = contracts * (1/entry_price - 1/exit_price) * entry_price * exit_price
else:
    gross_pnl_usd = contracts * (1/exit_price - 1/entry_price) * entry_price * exit_price
```

However — the impact at small price moves (<5%) is minimal (~0.01% difference).
So this is technically wrong but won't significantly affect P&L reporting.


## MEDIUM ISSUES

### Issue #4: OBV calculation is O(n) with slow iloc-based loop
**Location**: indicators.py, calculate_obv()
The for loop uses `iloc` indexing which is slow for large DataFrames.

**Fix**: Replace with vectorized numpy:
```python
direction = np.sign(close.diff())
obv = (direction * volume).cumsum()
```

### Issue #5: RSI fillna(50) masks real edge cases
**Location**: indicators.py line 83
When all candles are gains (no losses), avg_loss=0, RS=infinity, RSI should be 100.
But `fillna(50)` makes it look neutral instead.

**Fix**: `return rsi.fillna(100)` — all gains = RSI 100 (max bullish).

### Issue #6: No error handling for position file corruption
**Location**: position_manager.py
If `active_position.json` gets corrupted mid-write (e.g., power loss), the bot
can't recover. It returns None (treated as flat) even if a position is actually open.

**Fix**: Use atomic write (write to temp file, then rename):
```python
import tempfile
def _save_position(position):
    tmp_fd, tmp_path = tempfile.mkstemp(dir=".", suffix=".tmp")
    with os.fdopen(tmp_fd, 'w') as f:
        json.dump(position, f, indent=2)
    os.replace(tmp_path, POSITION_FILE)
```

### Issue #7: Telegram alerts send Markdown without escaping special chars
**Location**: alerts.py, send_telegram_alert()
If Claude's reasoning contains `_underscores_`, `*asterisks*`, or `$dollar` signs,
Telegram Markdown parse fails silently (message not sent).

**Fix**: Either escape special chars or use parse_mode="HTML" instead.

### Issue #8: No timeout protection on the entire cycle
**Location**: main.py, run_cycle()
If Delta Exchange hangs for 30+ seconds on one candle fetch, AND Claude takes 90s,
the total cycle could take 3+ minutes. With 180s (or even 300s) cycle time,
cycles could overlap or the bot appears hung.

**Fix**: Wrap run_cycle() in a total timeout:
```python
import signal
signal.alarm(config.BOT_CYCLE_SECONDS - 30)  # leave 30s buffer
```


## MINOR ISSUES

### Issue #9: .gitignore from v1 doesn't include `__pycache__/` cleanup
Already in .gitignore but if old __pycache__ was committed, it persists.
Run: `git rm -r --cached __pycache__/ 2>/dev/null; git commit -m "clean cache"`

### Issue #10: test_connection.py tests for "anthropic" package but bot uses requests
The test does `__import__("requests")` when checking for anthropic, which is misleading.
It should either test the actual anthropic SDK or just note "using requests for API".

### Issue #11: Binance futures URL inconsistency
data_fetcher.py uses both `config.BINANCE_FUTURES_URL` (fapi.binance.com) and
hardcoded "https://fapi.binance.com" in some functions. Should use config everywhere.

### Issue #12: No rate limit handling for Claude API
If you get HTTP 429 (rate limited), the bot just prints error and moves on.
Should implement exponential backoff for transient errors.

### Issue #13: Fear & Greed cache returns stale data on API failure
When API fails, it returns the cached value (could be hours old).
Should mark stale data so Claude knows it's not fresh.
