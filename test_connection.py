"""
=============================================================================
 TEST_CONNECTION.PY — Pre-flight Check for BTC BRAIN v3
=============================================================================
"""

import sys
import os


def check_mark(ok):
    return "✅" if ok else "❌"


def test_dependencies():
    print("\n📦 DEPENDENCIES...")
    all_ok = True
    for pkg in ["requests", "pandas", "numpy", "dotenv", "rich"]:
        try:
            __import__("dotenv" if pkg == "dotenv" else pkg)
            print(f"  {check_mark(True)} {pkg}")
        except ImportError:
            print(f"  {check_mark(False)} {pkg}")
            all_ok = False
    return all_ok


def test_env():
    print("\n🔐 ENVIRONMENT...")
    from dotenv import load_dotenv
    load_dotenv(override=True)

    env_exists = os.path.exists(".env")
    print(f"  {check_mark(env_exists)} .env file")
    if not env_exists:
        print("  → Copy .env.example to .env")
        return False

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    has_anthropic = anthropic_key and "your_" not in anthropic_key
    print(f"  {check_mark(has_anthropic)} ANTHROPIC_API_KEY")

    delta_key = os.getenv("DELTA_API_KEY", "")
    has_delta = delta_key and "your_" not in delta_key
    print(f"  {'✅' if has_delta else '⚠️ '} DELTA_API_KEY {'set' if has_delta else '(optional for paper mode)'}")

    mode = os.getenv("TRADING_MODE", "paper")
    print(f"  ℹ️  TRADING_MODE = {mode}")

    return has_anthropic


def test_delta():
    print("\n🏦 DELTA EXCHANGE...")
    import requests
    try:
        r = requests.get("https://api.india.delta.exchange/v2/tickers/BTCUSD", timeout=10)
        data = r.json()
        if data.get("success"):
            price = float(data["result"].get("mark_price", 0))
            print(f"  {check_mark(True)} Ticker OK — BTC: ${price:,.2f}")
            return True
    except Exception as e:
        print(f"  {check_mark(False)} Failed: {e}")
    return False


def test_delta_auth():
    print("\n🔑 DELTA AUTH...")
    from dotenv import load_dotenv
    load_dotenv(override=True)
    import config
    if not config.DELTA_API_KEY or "your_" in config.DELTA_API_KEY:
        print(f"  ⚠️  No API key — skipping auth test")
        return True

    try:
        from delta_client import DeltaClient
        client = DeltaClient()
        balances = client.get_wallet_balances()
        if balances:
            btc = balances.get("BTC", {})
            print(f"  {check_mark(True)} Auth OK — BTC balance: {btc.get('balance', 0):.8f}")
            return True
        else:
            print(f"  {check_mark(False)} Auth failed — check API key/secret")
            return False
    except Exception as e:
        print(f"  {check_mark(False)} Auth error: {e}")
        return False


def test_binance():
    print("\n🅱️  BINANCE...")
    import requests
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price",
                         params={"symbol": "BTCUSDT"}, timeout=10)
        data = r.json()
        price = float(data.get("price", 0))
        print(f"  {check_mark(True)} Spot OK — BTC: ${price:,.2f}")
        return True
    except Exception as e:
        print(f"  {check_mark(False)} Failed: {e}")
    return False


def test_indicators():
    print("\n📐 INDICATORS...")
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
            ("Dynamic Sizing", lambda: indicators.calculate_dynamic_position_size(87000, 8, 500)),
        ]

        all_ok = True
        for name, fn in tests:
            try:
                fn()
                print(f"  {check_mark(True)} {name}")
            except Exception as e:
                print(f"  {check_mark(False)} {name}: {e}")
                all_ok = False
        return all_ok
    except Exception as e:
        print(f"  {check_mark(False)} Import failed: {e}")
        return False


def test_pre_filter():
    print("\n🔍 PRE-FILTER...")
    try:
        from bot_state import BotState
        import pre_filter

        state = BotState()
        mock_indicators = {
            "ema9": 87100, "ema21": 87000,
            "htf_15m_trend": "bullish", "htf_1h_trend": "bullish", "htf_4h_trend": "bullish",
            "adx": 30, "adx_15m": 25, "adx_4h": 28,
            "rsi_5m": 45, "rsi_1h": 50, "rsi_4h": 55,
            "macd_crossover": "bullish", "macd_15m_crossover": None,
            "macd_1h_crossover": None, "macd_4h_crossover": None,
            "stoch_rsi_signal": None, "rsi_divergence": None, "rsi_divergence_1h": None,
            "bb_squeeze": False, "bb_position": 0.6,
            "volume_climax": False, "relative_volume": 1.2,
            "candle_patterns": [], "ichimoku_tk_cross": None,
        }

        should_call, reason = pre_filter.should_call_claude(mock_indicators, state, False)
        print(f"  {check_mark(True)} Pre-filter works: should_call={should_call} reason={reason}")
        return True
    except Exception as e:
        print(f"  {check_mark(False)} Pre-filter error: {e}")
        return False


def main():
    print(f"\n{'='*56}")
    print(f"  🔍 BTC BRAIN v3 — PRE-FLIGHT CHECK")
    print(f"{'='*56}")

    results = {}
    results["deps"] = test_dependencies()
    results["env"] = test_env()

    if results["deps"]:
        results["delta"] = test_delta()
        results["delta_auth"] = test_delta_auth()
        results["binance"] = test_binance()
        results["indicators"] = test_indicators()
        results["pre_filter"] = test_pre_filter()

    print(f"\n{'='*56}")
    print(f"  📋 SUMMARY")
    print(f"{'='*56}")
    for name, ok in results.items():
        print(f"  {check_mark(ok)} {name:.<30} {'PASS' if ok else 'FAIL'}")

    critical = results.get("deps", False) and results.get("env", False)
    print(f"\n  {'🚀 Ready! Run: python main.py' if critical else '⚠️  Fix issues above'}\n")
    return 0 if critical else 1


if __name__ == "__main__":
    sys.exit(main())
