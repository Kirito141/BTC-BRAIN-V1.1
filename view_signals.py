"""
=============================================================================
 VIEW_SIGNALS.PY — Signal History Viewer & Analyzer
=============================================================================
 Reads signals_log.csv and displays:
   • All past signals in a formatted table
   • Summary statistics (total, buy/sell ratio, avg confidence)
   • Filter by direction, date, confidence threshold
   
 This is your review tool during the testing phase.
 
 Usage:
   python view_signals.py                    # show all signals
   python view_signals.py --last 10          # last 10 signals
   python view_signals.py --direction BUY    # only BUY signals
   python view_signals.py --min-confidence 7 # confidence >= 7
   python view_signals.py --summary          # stats only
=============================================================================
"""

import csv
import sys
import os
import argparse
from datetime import datetime

import config


def load_signals(filepath=None):
    """Load signals from CSV file. Returns list of dicts."""
    if filepath is None:
        filepath = config.SIGNAL_LOG_FILE

    if not os.path.exists(filepath):
        print(f"  No signal log found at: {filepath}")
        print(f"  Run the bot first to generate signals.")
        return []

    signals = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            signals.append(row)

    return signals


def display_signals_table(signals):
    """Display signals in a rich table format."""
    try:
        from rich.console import Console
        from rich.table import Table
        from rich import box

        console = Console()

        table = Table(
            title=f"📊 Signal History ({len(signals)} signals)",
            box=box.SIMPLE_HEAVY,
            show_lines=False,
            header_style="bold cyan",
        )

        table.add_column("#", style="dim", width=4, justify="right")
        table.add_column("Time (IST)", style="white", width=16)
        table.add_column("Dir", width=5, justify="center")
        table.add_column("Strategy", width=20)
        table.add_column("Regime", width=10)
        table.add_column("Entry", justify="right", width=12)
        table.add_column("SL", justify="right", width=12)
        table.add_column("TP", justify="right", width=12)
        table.add_column("Lots", justify="right", width=6)
        table.add_column("Conf", justify="center", width=5)
        table.add_column("F&G", justify="center", width=5)
        table.add_column("Funding", justify="right", width=10)

        for i, s in enumerate(signals, 1):
            direction = s.get("direction", "?")
            dir_style = "bold green" if direction == "BUY" else "bold red"

            conf = s.get("confidence", "?")
            try:
                conf_val = int(conf)
                conf_style = "bold green" if conf_val >= 7 else "yellow" if conf_val >= 5 else "red"
                conf_str = f"[{conf_style}]{conf}/10[/{conf_style}]"
            except (ValueError, TypeError):
                conf_str = str(conf)

            entry = s.get("entry_price", "0")
            try:
                entry_str = f"${float(entry):,.2f}"
            except (ValueError, TypeError):
                entry_str = entry

            sl = s.get("stop_loss", "0")
            try:
                sl_str = f"${float(sl):,.2f}"
            except (ValueError, TypeError):
                sl_str = sl

            tp = s.get("take_profit", "0")
            try:
                tp_str = f"${float(tp):,.2f}"
            except (ValueError, TypeError):
                tp_str = tp

            fr = s.get("funding_rate", "")
            try:
                fr_val = float(fr)
                fr_str = f"{fr_val:.6f}"
            except (ValueError, TypeError):
                fr_str = fr

            table.add_row(
                str(i),
                s.get("time_ist", "?"),
                f"[{dir_style}]{direction}[/{dir_style}]",
                s.get("strategy", "?"),
                s.get("regime", "?"),
                entry_str,
                f"[red]{sl_str}[/red]",
                f"[green]{tp_str}[/green]",
                s.get("contracts", "?"),
                conf_str,
                s.get("fear_greed_value", "?"),
                fr_str,
            )

        console.print(table)

    except ImportError:
        # Fallback if rich not available
        print(f"\n{'='*80}")
        print(f"  Signal History ({len(signals)} signals)")
        print(f"{'='*80}")
        print(f"  {'#':>3} | {'Time':>14} | {'Dir':>4} | {'Entry':>10} | {'SL':>10} | {'TP':>10} | {'Conf':>4}")
        print(f"  {'─'*3}─┼─{'─'*14}─┼─{'─'*4}─┼─{'─'*10}─┼─{'─'*10}─┼─{'─'*10}─┼─{'─'*4}")
        for i, s in enumerate(signals, 1):
            print(
                f"  {i:>3} | "
                f"{s.get('time_ist', '?'):>14} | "
                f"{s.get('direction', '?'):>4} | "
                f"${float(s.get('entry_price', 0)):>9,.2f} | "
                f"${float(s.get('stop_loss', 0)):>9,.2f} | "
                f"${float(s.get('take_profit', 0)):>9,.2f} | "
                f"{s.get('confidence', '?'):>4}"
            )
        print()


def display_summary(signals):
    """Display statistical summary of all signals."""
    if not signals:
        print("  No signals to summarize.")
        return

    total = len(signals)
    buys = sum(1 for s in signals if s.get("direction") == "BUY")
    sells = sum(1 for s in signals if s.get("direction") == "SELL")

    confidences = []
    for s in signals:
        try:
            confidences.append(int(s.get("confidence", 0)))
        except (ValueError, TypeError):
            pass

    avg_conf = sum(confidences) / len(confidences) if confidences else 0
    max_conf = max(confidences) if confidences else 0
    min_conf = min(confidences) if confidences else 0

    # Count by strategy
    strategies = {}
    for s in signals:
        strat = s.get("strategy", "Unknown")
        strategies[strat] = strategies.get(strat, 0) + 1

    # Count by regime
    regimes = {}
    for s in signals:
        reg = s.get("regime", "Unknown")
        regimes[reg] = regimes.get(reg, 0) + 1

    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text
        from rich import box

        console = Console()
        text = Text()

        text.append(f"\n  Total Signals:     {total}\n", style="bold")
        text.append(f"  BUY Signals:       ", style="white")
        text.append(f"{buys} ({buys / total * 100:.1f}%)\n", style="bold green")
        text.append(f"  SELL Signals:      ", style="white")
        text.append(f"{sells} ({sells / total * 100:.1f}%)\n", style="bold red")
        text.append(f"\n")
        text.append(f"  Avg Confidence:    {avg_conf:.1f}/10\n", style="yellow")
        text.append(f"  Max Confidence:    {max_conf}/10\n", style="green")
        text.append(f"  Min Confidence:    {min_conf}/10\n", style="red")
        text.append(f"\n  By Strategy:\n", style="bold")
        for strat, count in strategies.items():
            text.append(f"    {strat:.<30} {count} ({count / total * 100:.1f}%)\n", style="cyan")
        text.append(f"\n  By Regime:\n", style="bold")
        for reg, count in regimes.items():
            text.append(f"    {reg:.<30} {count} ({count / total * 100:.1f}%)\n", style="cyan")

        console.print(Panel(text, title="📈 Signal Summary", box=box.HEAVY, style="blue"))

    except ImportError:
        print(f"\n{'='*50}")
        print(f"  Signal Summary")
        print(f"{'='*50}")
        print(f"  Total: {total}  |  BUY: {buys}  |  SELL: {sells}")
        print(f"  Avg Confidence: {avg_conf:.1f}/10")
        print(f"  By Strategy: {strategies}")
        print(f"  By Regime: {regimes}")
        print()


def main():
    parser = argparse.ArgumentParser(description="View signal history from the bot's CSV log.")
    parser.add_argument("--last", type=int, default=0, help="Show only last N signals")
    parser.add_argument("--direction", choices=["BUY", "SELL"], help="Filter by direction")
    parser.add_argument("--min-confidence", type=int, default=0, help="Minimum confidence score")
    parser.add_argument("--summary", action="store_true", help="Show summary stats only")
    parser.add_argument("--file", type=str, default=None, help="Path to CSV file")

    args = parser.parse_args()

    signals = load_signals(args.file)

    if not signals:
        return

    # Apply filters
    if args.direction:
        signals = [s for s in signals if s.get("direction") == args.direction]

    if args.min_confidence > 0:
        filtered = []
        for s in signals:
            try:
                if int(s.get("confidence", 0)) >= args.min_confidence:
                    filtered.append(s)
            except (ValueError, TypeError):
                pass
        signals = filtered

    if args.last > 0:
        signals = signals[-args.last:]

    if not signals:
        print("  No signals match your filters.")
        return

    # Display
    display_summary(signals)

    if not args.summary:
        display_signals_table(signals)


if __name__ == "__main__":
    main()
