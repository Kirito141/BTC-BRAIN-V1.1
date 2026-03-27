"""
=============================================================================
 TEST_CONNECTION.PY — Pre-flight Check for BTC BRAIN v2
=============================================================================
"""

import sys
import time

def check_mark(ok):
    return "✅" if ok else "❌"


def test_dependencies():
    print("\n📦 CHECKING DEPENDENCIES...")
    all_ok = True
    for pkg in ["requests", "pandas", "numpy", "dotenv", "anthropic"]:
        try:
            if pkg == "dotenv":
                __import__("dotenv")
            elif pkg == "anthropic":
                # Just check requests works for API
                __import__("requests")
            else:
                __import__(pkg)
            print(f"  {check_mark(True)} {pkg}")
        except ImportError:
            print(f"  {check_mark(False)} {pkg} — pip install {pkg}")
            all_ok = False
    return all_ok


def test_env():
    print("\n🔐 CHECKING ENVIRONMENT...")
    import os
    from dotenv import load_dotenv
    load_dotenv()

    env_exists = os.path.exists(".env")
    print(f"  {check_mark(env_exists)} .env file")
    if not env_exists:
        print("  → Copy .env.example to .env")
        return False

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    has_anthropic = anthropic_key and anthropic_key != "your_anthropic_api_key_here"
    print(f"  {check_mark(has_anthropic)} ANTHROPIC_API_KEY {'set' if has_anthropic else 'NOT SET (required)'}")

    delta_key = os.getenv("DELTA_API_KEY", "")
    has_delta = delta_key and delta_key != "your_delta_api_key_here"
    print(f"  {'✅' if has_delta else '⚠️ '} DELTA_API_KEY {'set' if has_delta else 'not set (optional for signals)'}")

    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    tg_chat = os.getenv("TELEGRAM_CHAT_ID", "")
    tg_ready = tg_token and tg_chat and "your_" not in tg_token
    print(f"  {'✅' if tg_ready else '⚠️ '} Telegram {'configured' if tg_ready else 'not configured'}")

    return has_anthropic


def test_delta():
    print("\n🏦 TESTING DELTA EXCHANGE...")
    import requests
    try:
        r = requests.get("https://api.india.delta.exchange/v2/tickers/BTCUSD", timeout=10)
        data = r.json()
        if data.get("success"):
            price = float(data["result"].get("mark_price", 0))
            print(f"  {check_mark(True)} Ticker OK — BTC: ${price:,.2f}")
            return True
        print(f"  {check_mark(False)} Ticker returned success=false")
    except Exception as e:
        print(f"  {check_mark(False)} Failed: {e}")
    return False


def test_binance():
    print("\n🅱️ TESTING BINANCE...")
    import requests
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": "BTCUSDT"}, timeout=10)
        data = r.json()
        price = float(data.get("price", 0))
        print(f"  {check_mark(True)} Spot OK — BTC: ${price:,.2f}")
        return True
    except Exception as e:
        print(f"  {check_mark(False)} Failed: {e}")
    return False


def test_indicators():
    print("\n📐 TESTING INDICATORS...")
    try:
        import pandas as pd
        import numpy as np
        import indicators

        np.random.seed(42)
        n = 100
        prices = 87000 + np.cumsum(np.random.randn(n) * 50)
        df = pd.DataFrame({
            "open": prices - np.random.rand(n) * 20,
            "high": prices + np.abs(np.random.randn(n) * 100),
            "low": prices - np.abs(np.random.randn(n) * 100),
            "close": prices,
            "volume": np.random.randint(100, 10000, n),
        })

        # Test all new indicators
        tests = [
            ("EMA", lambda: indicators.calculate_ema(df["close"], 9)),
            ("RSI", lambda: indicators.calculate_rsi(df["close"], 14)),
            ("ATR", lambda: indicators.get_current_atr(df)),
            ("MACD", lambda: indicators.calculate_macd(df["close"])),
            ("Bollinger", lambda: indicators.calculate_bollinger_bands(df["close"])),
            ("Stoch RSI", lambda: indicators.calculate_stochastic_rsi(df["close"])),
            ("ADX", lambda: indicators.calculate_adx(df)),
            ("OBV", lambda: indicators.calculate_obv(df)),
            ("Ichimoku", lambda: indicators.calculate_ichimoku(df)),
            ("Pivots", lambda: indicators.calculate_pivot_points(df)),
            ("RSI Div", lambda: indicators.detect_rsi_divergence(df)),
            ("Volume", lambda: indicators.analyze_volume(df)),
            ("S/R", lambda: indicators.find_support_resistance(df)),
            ("Candles", lambda: indicators.detect_candle_patterns(df)),
            ("Regime", lambda: indicators.detect_regime(df)),
            ("SL/TP", lambda: indicators.calculate_sl_tp(87000, "BUY", 300)),
            ("Position", lambda: indicators.calculate_position_size(87000)),
        ]

        all_ok = True
        for name, fn in tests:
            try:
                result = fn()
                print(f"  {check_mark(True)} {name}")
            except Exception as e:
                print(f"  {check_mark(False)} {name}: {e}")
                all_ok = False
        return all_ok
    except Exception as e:
        print(f"  {check_mark(False)} Failed: {e}")
        return False


def main():
    print("\n" + "=" * 56)
    print("  🔍 BTC BRAIN v2 — PRE-FLIGHT CHECK")
    print("=" * 56)

    results = {}
    results["deps"] = test_dependencies()
    results["env"] = test_env()

    if results["deps"]:
        results["delta"] = test_delta()
        results["binance"] = test_binance()
        results["indicators"] = test_indicators()

    print("\n" + "=" * 56)
    print("  📋 SUMMARY")
    print("=" * 56)
    for name, ok in results.items():
        print(f"  {check_mark(ok)} {name:.<30} {'PASS' if ok else 'FAIL'}")

    critical = results.get("deps", False) and results.get("env", False)
    print(f"\n  {'🚀 Ready! Run: python main.py' if critical else '⚠️  Fix issues above'}\n")
    return 0 if critical else 1


if __name__ == "__main__":
    sys.exit(main())
