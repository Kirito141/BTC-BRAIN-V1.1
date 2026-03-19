"""
=============================================================================
 DASHBOARD.PY — Live Terminal Dashboard using `rich`
=============================================================================
 Renders a real-time terminal dashboard showing:
   • Current BTC price (Delta + Binance)
   • Market regime
   • Key indicators (EMA, RSI, ATR)
   • Latest signal (if any)
   • Fear & Greed index
   • Funding rate & OI
   • Bot status & next cycle countdown
   
 Uses the `rich` library for beautiful terminal rendering.
=============================================================================
"""

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich.columns import Columns
from rich import box
from datetime import datetime, timezone, timedelta

import config

# IST timezone
IST = timezone(timedelta(hours=5, minutes=30))

console = Console()


def render_dashboard(all_data, signal_result, cycle_count):
    """
    Render the full terminal dashboard.
    
    Args:
        all_data: dict from data_fetcher.fetch_all_data()
        signal_result: dict from signal_engine.generate_signal()
        cycle_count: int — how many cycles have run
    """
    console.clear()

    now_ist = datetime.now(IST).strftime("%d %b %Y, %I:%M:%S %p IST")

    # ── Header ──────────────────────────────────────────────────────────────
    header = Text()
    header.append("  ⚡ BTC PERPETUALS SCALPING SIGNAL BOT ", style="bold white on blue")
    header.append(f"  │  Delta Exchange India  │  {now_ist}  ", style="bold white on dark_blue")

    console.print(Panel(header, box=box.DOUBLE, style="blue"))

    # ── Price Panel ─────────────────────────────────────────────────────────
    ticker = all_data.get("delta_ticker")
    binance_price = all_data.get("binance_price")

    price_table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan",
                        title="💰 PRICE DATA", title_style="bold yellow")
    price_table.add_column("Source", style="white", width=20)
    price_table.add_column("Price", style="bold green", justify="right", width=18)
    price_table.add_column("Details", style="dim", width=30)

    if ticker:
        mp = ticker.get("mark_price", 0)
        price_table.add_row(
            "Delta (Mark)",
            f"${mp:,.2f}",
            f"H: ${ticker.get('high', 0):,.2f}  L: ${ticker.get('low', 0):,.2f}"
        )
    else:
        price_table.add_row("Delta (Mark)", "[red]Unavailable[/red]", "—")

    if binance_price:
        price_table.add_row("Binance (Spot)", f"${binance_price:,.2f}", "Reference feed")
    else:
        price_table.add_row("Binance (Spot)", "[red]Unavailable[/red]", "—")

    # Spread between Delta and Binance
    if ticker and binance_price and ticker.get("mark_price", 0) > 0:
        spread = ticker["mark_price"] - binance_price
        spread_pct = (spread / binance_price) * 100
        spread_style = "green" if abs(spread_pct) < 0.1 else "yellow"
        price_table.add_row(
            "Delta-Binance Spread",
            f"${spread:+,.2f}",
            f"[{spread_style}]{spread_pct:+.4f}%[/{spread_style}]"
        )

    console.print(price_table)

    # ── Regime & Indicators Panel ───────────────────────────────────────────
    regime_info = signal_result.get("regime", {}) if isinstance(signal_result, dict) else {}

    indicator_table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan",
                            title="📊 MARKET REGIME & INDICATORS", title_style="bold yellow")
    indicator_table.add_column("Indicator", style="white", width=22)
    indicator_table.add_column("Value", justify="right", width=18)
    indicator_table.add_column("Status", width=28)

    # Regime
    regime_name = regime_info.get("regime", "unknown")
    regime_colors = {
        "trending": "bold green",
        "ranging": "bold yellow",
        "high_volatility": "bold red",
        "unknown": "dim",
    }
    regime_style = regime_colors.get(regime_name, "dim")
    indicator_table.add_row(
        "Market Regime",
        f"[{regime_style}]{regime_name.upper()}[/{regime_style}]",
        regime_info.get("reason", "—")[:28]
    )

    # ATR
    atr_pct = regime_info.get("atr_pct", 0)
    atr_style = "red" if atr_pct > config.REGIME_ATR_HIGH_VOL_THRESHOLD else "green"
    indicator_table.add_row(
        "ATR (% of price)",
        f"[{atr_style}]{atr_pct:.4f}%[/{atr_style}]",
        f"Threshold: {config.REGIME_ATR_HIGH_VOL_THRESHOLD}%"
    )

    # EMA Spread
    ema_spread = regime_info.get("ema_spread_pct", 0)
    ema_style = "green" if ema_spread > config.REGIME_EMA_SPREAD_TREND_THRESHOLD else "yellow"
    indicator_table.add_row(
        "EMA 9/21 Spread",
        f"[{ema_style}]{ema_spread:.4f}%[/{ema_style}]",
        f"Trend threshold: {config.REGIME_EMA_SPREAD_TREND_THRESHOLD}%"
    )

    # Funding Rate
    if ticker:
        fr = ticker.get("funding_rate", 0)
        fr_style = "green" if fr < 0 else "red" if fr > 0.01 else "white"
        indicator_table.add_row(
            "Funding Rate",
            f"[{fr_style}]{fr:.6f}[/{fr_style}]",
            "Negative = shorts pay" if fr < 0 else "Positive = longs pay"
        )

    # Open Interest
    if ticker:
        oi = ticker.get("open_interest", 0)
        indicator_table.add_row("Open Interest", f"{oi:,.0f}", "")

    console.print(indicator_table)

    # ── External Data Panel ─────────────────────────────────────────────────
    ext_table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan",
                      title="🌐 EXTERNAL SENTIMENT", title_style="bold yellow")
    ext_table.add_column("Source", style="white", width=22)
    ext_table.add_column("Value", justify="right", width=18)
    ext_table.add_column("Classification", width=28)

    # Fear & Greed
    fg = all_data.get("fear_greed")
    if fg:
        fgv = fg["value"]
        fg_colors = {
            "Extreme Fear": "bold red",
            "Fear": "red",
            "Neutral": "yellow",
            "Greed": "green",
            "Extreme Greed": "bold green",
        }
        fg_style = fg_colors.get(fg["classification"], "white")
        ext_table.add_row(
            "Fear & Greed Index",
            f"[{fg_style}]{fgv}[/{fg_style}]",
            f"[{fg_style}]{fg['classification']}[/{fg_style}]"
        )
    else:
        ext_table.add_row("Fear & Greed Index", "[red]Unavailable[/red]", "—")

    # BTC Dominance
    cg = all_data.get("coingecko")
    if cg:
        dom = cg.get("btc_dominance", 0)
        ext_table.add_row("BTC Dominance", f"{dom:.2f}%", "CoinGecko")
        vol = cg.get("total_volume_usd", 0)
        ext_table.add_row("Global 24h Volume", f"${vol / 1e9:,.1f}B", "CoinGecko")
    else:
        ext_table.add_row("BTC Dominance", "[red]Unavailable[/red]", "CoinGecko cache")

    console.print(ext_table)

    # ── Signal Status Panel ─────────────────────────────────────────────────
    status = signal_result.get("status", "UNKNOWN") if isinstance(signal_result, dict) else "UNKNOWN"

    signal_panel_content = Text()

    if status == "SIGNAL":
        direction = signal_result.get("direction", "")
        dir_style = "bold green" if direction == "BUY" else "bold red"
        arrow = "▲ LONG" if direction == "BUY" else "▼ SHORT"

        signal_panel_content.append(f"  {arrow} ", style=dir_style)
        signal_panel_content.append(f"@ ${signal_result.get('entry_price', 0):,.2f}\n", style="bold white")
        signal_panel_content.append(f"  Strategy: {signal_result.get('strategy', '')}\n", style="white")
        signal_panel_content.append(f"  SL: ${signal_result.get('stop_loss', 0):,.2f}", style="red")
        signal_panel_content.append(f"  │  TP: ${signal_result.get('take_profit', 0):,.2f}\n", style="green")
        signal_panel_content.append(f"  Contracts: {signal_result.get('contracts', 0)} lots", style="white")
        signal_panel_content.append(f"  │  Confidence: {signal_result.get('confidence', 0)}/10\n", style="bold yellow")

        panel_style = "green" if direction == "BUY" else "red"
        panel_title = f"⚡ ACTIVE SIGNAL — {direction}"

    elif status == "OUTSIDE_HOURS":
        signal_panel_content.append("  ⏸  Outside trading hours (2 PM – 2 AM IST)\n", style="dim yellow")
        signal_panel_content.append(f"  Current time: {signal_result.get('time', '')}\n", style="dim")
        signal_panel_content.append("  Bot is monitoring but not generating signals.", style="dim")
        panel_style = "dim yellow"
        panel_title = "⏸ PAUSED — Outside Hours"

    elif status == "SIT_OUT":
        signal_panel_content.append("  ⚠  High volatility detected — sitting out\n", style="bold yellow")
        signal_panel_content.append(f"  {signal_result.get('reason', '')}\n", style="yellow")
        signal_panel_content.append(f"  Price: ${signal_result.get('price', 0):,.2f}", style="white")
        panel_style = "yellow"
        panel_title = "⚠ SIT OUT — High Volatility"

    elif status == "COOLDOWN":
        signal_panel_content.append("  ⏳ Signal detected but cooldown is active\n", style="dim cyan")
        signal_panel_content.append(f"  {signal_result.get('reason', '')}\n", style="dim")
        signal_panel_content.append(f"  Cooldown: {config.SIGNAL_COOLDOWN_SECONDS}s between same-direction signals", style="dim")
        panel_style = "cyan"
        panel_title = "⏳ COOLDOWN"

    elif status == "NO_SIGNAL":
        signal_panel_content.append("  👁  Watching... no signal this cycle\n", style="dim")
        signal_panel_content.append(f"  {signal_result.get('reason', '')}\n", style="dim")
        signal_panel_content.append(f"  Price: ${signal_result.get('price', 0):,.2f}", style="white")
        panel_style = "dim"
        panel_title = "👁 WATCHING"

    else:
        signal_panel_content.append(f"  Status: {status}\n", style="dim red")
        reason = signal_result.get("reason", "Unknown issue") if isinstance(signal_result, dict) else ""
        signal_panel_content.append(f"  {reason}", style="dim")
        panel_style = "red"
        panel_title = "❌ ERROR"

    console.print(Panel(signal_panel_content, title=panel_title,
                        title_align="left", style=panel_style, box=box.HEAVY))

    # ── Footer / Bot Status ─────────────────────────────────────────────────
    footer = Text()
    footer.append(f"  Cycle #{cycle_count}", style="bold")
    footer.append(f"  │  Interval: {config.BOT_CYCLE_SECONDS}s", style="dim")
    footer.append(f"  │  Cooldown: {config.SIGNAL_COOLDOWN_SECONDS}s", style="dim")
    footer.append(f"  │  Log: {config.SIGNAL_LOG_FILE}", style="dim")
    footer.append(f"  │  Mode: SIGNAL ONLY (no auto-trade)", style="bold yellow")

    console.print(Panel(footer, style="dim", box=box.ROUNDED))
