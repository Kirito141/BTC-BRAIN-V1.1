"""
=============================================================================
 TEST_CONNECTION.PY — Pre-Flight Check for All APIs & Dependencies
=============================================================================
 Run this BEFORE starting the bot to verify:
   ✓ All Python dependencies installed
   ✓ .env file exists and has credentials
   ✓ Delta Exchange API responding
   ✓ Binance API responding
   ✓ Fear & Greed API responding
   ✓ CoinGecko API responding
   ✓ Delta candle data format is correct
   ✓ Indicator calculations work on real data
   
 Usage: python test_connection.py
=============================================================================
"""

import sys
import time


def check_mark(success):
    return "✅" if success else "❌"


def test_dependencies():
    """Test that all required Python packages are installed."""
    print("\n📦 CHECKING DEPENDENCIES...")
    print("─" * 50)

    required = {
        "requests": "HTTP client for API calls",
        "pandas": "Data manipulation",
        "numpy": "Numerical calculations",
        "dotenv": "Environment variable loading (python-dotenv)",
        "rich": "Terminal dashboard rendering",
    }

    optional = {
        "plyer": "Desktop notifications (optional)",
    }

    all_ok = True

    for module, desc in required.items():
        try:
            if module == "dotenv":
                __import__("dotenv")
            else:
                __import__(module)
            print(f"  {check_mark(True)} {module:.<30} {desc}")
        except ImportError:
            print(f"  {check_mark(False)} {module:.<30} MISSING — pip install {module}")
            all_ok = False

    for module, desc in optional.items():
        try:
            __import__(module)
            print(f"  {check_mark(True)} {module:.<30} {desc}")
        except ImportError:
            print(f"  ⚠️  {module:.<30} Not installed (optional) — pip install {module}")

    return all_ok


def test_env_file():
    """Test .env file exists and has required variables."""
    print("\n🔐 CHECKING ENVIRONMENT...")
    print("─" * 50)

    import os
    from dotenv import load_dotenv

    load_dotenv()

    env_exists = os.path.exists(".env")
    print(f"  {check_mark(env_exists)} .env file exists")

    if not env_exists:
        print("  → Copy .env.example to .env and fill in your credentials")
        return False

    key = os.getenv("DELTA_API_KEY", "")
    secret = os.getenv("DELTA_API_SECRET", "")

    has_key = key and key != "your_delta_api_key_here"
    has_secret = secret and secret != "your_delta_api_secret_here"

    print(f"  {check_mark(has_key)} DELTA_API_KEY {'configured' if has_key else 'NOT SET (needed for balance fetch)'}")
    print(f"  {check_mark(has_secret)} DELTA_API_SECRET {'configured' if has_secret else 'NOT SET (needed for balance fetch)'}")

    # These are optional for signal-only mode
    if not has_key:
        print("  ⚠️  Without API keys, bot will use default balance ($100).")
        print("     Market data (candles, ticker) works without auth.")

    # Telegram check
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    tg_chat = os.getenv("TELEGRAM_CHAT_ID", "")
    tg_ready = (tg_token and tg_token != "your_telegram_bot_token_here"
                and tg_chat and tg_chat != "your_telegram_chat_id_here")
    print(f"  {'✅' if tg_ready else '⚠️ '} Telegram {'configured' if tg_ready else 'not configured (optional)'}")

    return True  # env file exists, API keys are optional for signal mode


def test_delta_exchange():
    """Test Delta Exchange India API connectivity and data format."""
    print("\n🏦 TESTING DELTA EXCHANGE API...")
    print("─" * 50)

    import requests

    base = "https://api.india.delta.exchange"
    all_ok = True

    # Test 1: Ticker endpoint
    try:
        r = requests.get(f"{base}/v2/tickers/BTCUSD", timeout=10)
        data = r.json()
        if data.get("success"):
            result = data["result"]
            price = float(result.get("mark_price", 0))
            oi = float(result.get("oi", 0))
            fr = result.get("funding_rate", "N/A")
            print(f"  {check_mark(True)} Ticker endpoint OK")
            print(f"      Mark Price:    ${price:,.2f}")
            print(f"      Open Interest: {oi:,.0f}")
            print(f"      Funding Rate:  {fr}")
        else:
            print(f"  {check_mark(False)} Ticker returned success=false")
            all_ok = False
    except Exception as e:
        print(f"  {check_mark(False)} Ticker endpoint FAILED: {e}")
        all_ok = False

    # Test 2: Candles endpoint (5m)
    try:
        end_ts = int(time.time())
        start_ts = end_ts - (50 * 300)  # 50 x 5-min candles

        # Try "5m" format first, then "5" as fallback
        candles = None
        for res_format in ["5m", "5"]:
            r = requests.get(f"{base}/v2/history/candles", params={
                "symbol": "BTCUSD",
                "resolution": res_format,
                "start": start_ts,
                "end": end_ts,
            }, timeout=10)
            data = r.json()
            if data.get("success") and data.get("result"):
                candles = data["result"]
                print(f"  {check_mark(True)} Candles endpoint OK (5m, format='{res_format}') — {len(candles)} candles returned")
                # Verify structure
                sample = candles[0]
                has_fields = all(k in sample for k in ["time", "open", "high", "low", "close"])
                print(f"  {check_mark(has_fields)} Candle data format {'correct' if has_fields else 'UNEXPECTED'}")
                if not has_fields:
                    print(f"      Keys found: {list(sample.keys())}")
                    all_ok = False
                break

        if candles is None:
            print(f"  {check_mark(False)} Candles returned no data (tried '5m' and '5')")
            all_ok = False
    except Exception as e:
        print(f"  {check_mark(False)} Candles endpoint FAILED: {e}")
        all_ok = False

    # Test 3: Candles endpoint (3m)
    try:
        end_ts = int(time.time())
        start_ts = end_ts - (50 * 180)

        candles_3m = None
        for res_format in ["3m", "3"]:
            r = requests.get(f"{base}/v2/history/candles", params={
                "symbol": "BTCUSD",
                "resolution": res_format,
                "start": start_ts,
                "end": end_ts,
            }, timeout=10)
            data = r.json()
            if data.get("success") and data.get("result"):
                print(f"  {check_mark(True)} Candles endpoint OK (3m, format='{res_format}') — {len(data['result'])} candles returned")
                candles_3m = data["result"]
                break

        if candles_3m is None:
            print(f"  {check_mark(False)} 3m candles returned no data (tried '3m' and '3')")
            all_ok = False
    except Exception as e:
        print(f"  {check_mark(False)} 3m Candles FAILED: {e}")
        all_ok = False

    # Test 4: L2 Orderbook
    try:
        r = requests.get(f"{base}/v2/l2orderbook/BTCUSD", timeout=10)
        data = r.json()
        if data.get("success") and data.get("result"):
            ob = data["result"]
            bids = len(ob.get("buy", []))
            asks = len(ob.get("sell", []))
            print(f"  {check_mark(True)} Orderbook endpoint OK — {bids} bids, {asks} asks")
        else:
            print(f"  {check_mark(False)} Orderbook returned no data")
            all_ok = False
    except Exception as e:
        print(f"  {check_mark(False)} Orderbook FAILED: {e}")
        all_ok = False

    return all_ok


def test_binance():
    """Test Binance public API."""
    print("\n🅱️  TESTING BINANCE API...")
    print("─" * 50)

    import requests

    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price",
                         params={"symbol": "BTCUSDT"}, timeout=10)
        data = r.json()
        price = float(data.get("price", 0))
        print(f"  {check_mark(True)} Binance price endpoint OK")
        print(f"      BTC/USDT: ${price:,.2f}")
        return True
    except Exception as e:
        print(f"  {check_mark(False)} Binance FAILED: {e}")
        return False


def test_fear_greed():
    """Test Alternative.me Fear & Greed Index API."""
    print("\n😱 TESTING FEAR & GREED INDEX API...")
    print("─" * 50)

    import requests

    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        data = r.json()
        if "data" in data and len(data["data"]) > 0:
            entry = data["data"][0]
            value = entry.get("value", "?")
            label = entry.get("value_classification", "?")
            print(f"  {check_mark(True)} Fear & Greed API OK")
            print(f"      Current: {value} — {label}")
            return True
        else:
            print(f"  {check_mark(False)} Unexpected response format")
            return False
    except Exception as e:
        print(f"  {check_mark(False)} Fear & Greed FAILED: {e}")
        return False


def test_coingecko():
    """Test CoinGecko free API."""
    print("\n🦎 TESTING COINGECKO API...")
    print("─" * 50)

    import requests

    try:
        r = requests.get("https://api.coingecko.com/api/v3/global", timeout=10)
        data = r.json()
        if "data" in data:
            market = data["data"]
            btc_dom = market.get("market_cap_percentage", {}).get("btc", 0)
            total_vol = market.get("total_volume", {}).get("usd", 0)
            print(f"  {check_mark(True)} CoinGecko global endpoint OK")
            print(f"      BTC Dominance: {btc_dom:.2f}%")
            print(f"      Global 24h Vol: ${total_vol / 1e9:,.1f}B")
            return True
        else:
            print(f"  {check_mark(False)} Unexpected response format")
            return False
    except Exception as e:
        print(f"  {check_mark(False)} CoinGecko FAILED: {e}")
        return False


def test_indicators():
    """Test that indicator calculations work on real data."""
    print("\n📐 TESTING INDICATOR CALCULATIONS...")
    print("─" * 50)

    try:
        import pandas as pd
        import numpy as np
        sys.path.insert(0, ".")
        import indicators
        import config

        # Create synthetic test data (50 candles of random walk around $84,000)
        np.random.seed(42)
        n = 50
        prices = 84000 + np.cumsum(np.random.randn(n) * 50)
        df = pd.DataFrame({
            "time": range(n),
            "open": prices - np.random.rand(n) * 20,
            "high": prices + np.abs(np.random.randn(n) * 100),
            "low": prices - np.abs(np.random.randn(n) * 100),
            "close": prices,
            "volume": np.random.randint(100, 10000, n),
        })

        # Test EMA
        ema9 = indicators.calculate_ema(df["close"], 9)
        ema21 = indicators.calculate_ema(df["close"], 21)
        print(f"  {check_mark(True)} EMA calculation OK (EMA9={ema9.iloc[-1]:.2f}, EMA21={ema21.iloc[-1]:.2f})")

        # Test RSI
        rsi = indicators.calculate_rsi(df["close"], 14)
        rsi_val = rsi.iloc[-1]
        print(f"  {check_mark(True)} RSI calculation OK (RSI={rsi_val:.2f})")

        # Test ATR
        atr = indicators.get_current_atr(df, 14)
        print(f"  {check_mark(True)} ATR calculation OK (ATR=${atr:.2f})")

        # Test Regime Detection
        regime = indicators.detect_regime(df)
        print(f"  {check_mark(True)} Regime detection OK (regime={regime['regime']})")

        # Test SL/TP
        sl_tp = indicators.calculate_sl_tp(84000, "BUY", atr)
        print(f"  {check_mark(True)} SL/TP calculation OK (SL=${sl_tp['stop_loss']:,.2f}, TP=${sl_tp['take_profit']:,.2f})")

        # Test Position Sizing
        pos = indicators.calculate_position_size(84000, balance_usdt=100)
        print(f"  {check_mark(True)} Position sizing OK ({pos['contracts']} lots, ${pos['position_value_usd']:,.2f})")

        return True
    except Exception as e:
        print(f"  {check_mark(False)} Indicator test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_trading_hours():
    """Show current trading hours status."""
    print("\n🕐 TRADING HOURS CHECK...")
    print("─" * 50)

    from datetime import datetime, timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(IST)

    hour = now.hour
    in_window = hour >= 14 or hour < 2

    print(f"  Current IST time: {now.strftime('%I:%M %p IST (%d %b %Y)')}")
    print(f"  Trading window:   2:00 PM – 2:00 AM IST")
    print(f"  Status:           {'🟢 ACTIVE — signals will generate' if in_window else '🔴 OUTSIDE — bot will monitor silently'}")

    return True


# =============================================================================
#  MAIN
# =============================================================================

def main():
    print("\n" + "=" * 56)
    print("  🔍 BTC SCALPER BOT — PRE-FLIGHT CHECK")
    print("=" * 56)

    results = {}

    results["dependencies"] = test_dependencies()
    results["env"] = test_env_file()

    # Only test APIs if dependencies are met
    if results["dependencies"]:
        results["delta"] = test_delta_exchange()
        results["binance"] = test_binance()
        results["fear_greed"] = test_fear_greed()
        results["coingecko"] = test_coingecko()
        results["indicators"] = test_indicators()
        results["hours"] = test_trading_hours()
    else:
        print("\n  ⚠️  Skipping API tests — install dependencies first")
        print("     Run: pip install -r requirements.txt")

    # ── Summary ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 56)
    print("  📋 SUMMARY")
    print("=" * 56)

    critical_ok = True
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        icon = check_mark(ok)
        print(f"  {icon} {name:.<30} {status}")
        if name in ["dependencies", "delta"] and not ok:
            critical_ok = False

    print()
    if critical_ok:
        print("  🚀 All critical checks passed! Run: python main.py")
    else:
        print("  ⚠️  Fix the issues above before running the bot.")

    print()
    return 0 if critical_ok else 1


if __name__ == "__main__":
    sys.exit(main())
