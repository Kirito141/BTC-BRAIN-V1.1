"""
=============================================================================
 VIEW_TRADES.PY — Trade History & Performance Dashboard
=============================================================================
 Reads trades_log.csv and signals_log.csv to show:
   • All confirmed trades
   • Win/loss tracking (manual input)
   • Claude's signal accuracy by confidence level
   • Summary statistics
   
 Usage:
   python3 view_trades.py                  # show all trades
   python3 view_trades.py --signals        # show all Claude signals
   python3 view_trades.py --summary        # stats overview
   python3 view_trades.py --accuracy       # Claude accuracy analysis
   python3 view_trades.py --record-outcome # record win/loss for a trade
=============================================================================
"""

import csv
import os
import argparse
from datetime import datetime

import config


def load_csv(filepath):
    """Load a CSV file into a list of dicts."""
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r") as f:
        return list(csv.DictReader(f))


def display_trades():
    """Show all confirmed trades."""
    trades = load_csv(config.TRADES_LOG_FILE)
    if not trades:
        print("\n  No trades recorded yet. Take your first trade!")
        return

    try:
        from rich.console import Console
        from rich.table import Table
        from rich import box

        c = Console()
        table = Table(title=f"📊 Confirmed Trades ({len(trades)})",
                      box=box.SIMPLE_HEAVY, header_style="bold cyan")

        table.add_column("#", width=4, justify="right", style="dim")
        table.add_column("Time", width=14)
        table.add_column("Dir", width=5, justify="center")
        table.add_column("Entry", width=12, justify="right")
        table.add_column("SL", width=12, justify="right")
        table.add_column("TP", width=12, justify="right")
        table.add_column("Conf", width=5, justify="center")
        table.add_column("Regime", width=10)
        table.add_column("Reasoning", width=40)

        for i, t in enumerate(trades, 1):
            direction = t.get("direction", "?")
            dir_style = "bold green" if direction == "BUY" else "bold red"
            conf = t.get("confidence", "?")

            entry = t.get("entry_price", "0")
            try:
                entry_str = f"${float(entry):,.2f}"
            except (ValueError, TypeError):
                entry_str = entry

            sl = t.get("stop_loss", "0")
            try:
                sl_str = f"${float(sl):,.2f}"
            except (ValueError, TypeError):
                sl_str = sl

            tp = t.get("take_profit", "0")
            try:
                tp_str = f"${float(tp):,.2f}"
            except (ValueError, TypeError):
                tp_str = tp

            reasoning = t.get("reasoning", "")[:40]

            table.add_row(
                str(i),
                t.get("time_ist", "?"),
                f"[{dir_style}]{direction}[/{dir_style}]",
                entry_str,
                f"[red]{sl_str}[/red]",
                f"[green]{tp_str}[/green]",
                str(conf),
                t.get("regime", "?"),
                reasoning,
            )
        c.print(table)

    except ImportError:
        print(f"\n  Trades ({len(trades)}):")
        for i, t in enumerate(trades, 1):
            print(f"  {i}. {t.get('time_ist','?')} {t.get('direction','?')} "
                  f"@${float(t.get('entry_price',0)):,.2f} conf:{t.get('confidence','?')}")


def display_signals():
    """Show all Claude signals (taken + skipped)."""
    signals = load_csv(config.SIGNAL_LOG_FILE)
    if not signals:
        print("\n  No signals logged yet.")
        return

    try:
        from rich.console import Console
        from rich.table import Table
        from rich import box

        c = Console()
        table = Table(title=f"🧠 All Claude Signals ({len(signals)})",
                      box=box.SIMPLE_HEAVY, header_style="bold cyan")

        table.add_column("#", width=4, justify="right", style="dim")
        table.add_column("Time", width=14)
        table.add_column("Decision", width=10, justify="center")
        table.add_column("Conf", width=5, justify="center")
        table.add_column("Taken?", width=7, justify="center")
        table.add_column("Entry", width=12, justify="right")
        table.add_column("Market", width=25)
        table.add_column("Reason", width=35)

        for i, s in enumerate(signals, 1):
            dec = s.get("decision", "?")
            taken = s.get("trade_taken", "NO")
            taken_style = "bold green" if taken == "YES" else "dim"
            dec_style = "green" if dec == "BUY" else "red" if dec == "SELL" else "yellow"

            entry = s.get("entry_price", "0")
            try:
                entry_str = f"${float(entry):,.2f}"
            except (ValueError, TypeError):
                entry_str = entry or "—"

            table.add_row(
                str(i),
                s.get("time_ist", "?"),
                f"[{dec_style}]{dec}[/{dec_style}]",
                s.get("confidence", "?"),
                f"[{taken_style}]{taken}[/{taken_style}]",
                entry_str,
                s.get("market_condition", "?")[:25],
                s.get("reasoning", "?")[:35],
            )
        c.print(table)

    except ImportError:
        print(f"\n  Signals ({len(signals)}):")
        for i, s in enumerate(signals, 1):
            taken = "✓" if s.get("trade_taken") == "YES" else "✗"
            print(f"  {i}. {s.get('time_ist','?')} {s.get('decision','?')} "
                  f"conf:{s.get('confidence','?')} [{taken}]")


def display_accuracy():
    """Analyze Claude's signal accuracy by confidence level."""
    signals = load_csv(config.SIGNAL_LOG_FILE)
    if not signals:
        print("\n  No signals to analyze.")
        return

    total = len(signals)
    by_decision = {}
    by_confidence = {}
    taken_count = 0
    skipped_count = 0

    for s in signals:
        dec = s.get("decision", "UNKNOWN")
        conf = s.get("confidence", "0")
        taken = s.get("trade_taken", "NO")

        by_decision[dec] = by_decision.get(dec, 0) + 1

        try:
            c = int(conf)
            bucket = f"{c}/10"
        except (ValueError, TypeError):
            bucket = "?/10"
        by_confidence[bucket] = by_confidence.get(bucket, 0) + 1

        if taken == "YES":
            taken_count += 1
        else:
            skipped_count += 1

    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text
        from rich import box

        c = Console()
        text = Text()

        text.append(f"\n  Total Signals:    {total}\n", style="bold")
        text.append(f"  Trades Taken:     {taken_count} ({taken_count/total*100:.1f}%)\n", style="green")
        text.append(f"  Trades Skipped:   {skipped_count} ({skipped_count/total*100:.1f}%)\n\n", style="red")

        text.append(f"  By Decision:\n", style="bold")
        for dec, count in sorted(by_decision.items()):
            pct = count / total * 100
            style = "green" if dec == "BUY" else "red" if dec == "SELL" else "yellow"
            text.append(f"    {dec:.<15} {count:>4} ({pct:>5.1f}%)\n", style=style)

        text.append(f"\n  By Confidence:\n", style="bold")
        for conf in sorted(by_confidence.keys()):
            count = by_confidence[conf]
            pct = count / total * 100
            text.append(f"    {conf:.<15} {count:>4} ({pct:>5.1f}%)\n", style="cyan")

        c.print(Panel(text, title="📈 Claude Accuracy Analysis", box=box.HEAVY, style="blue"))

    except ImportError:
        print(f"\n  Signals: {total} | Taken: {taken_count} | Skipped: {skipped_count}")
        print(f"  Decisions: {by_decision}")
        print(f"  By Confidence: {by_confidence}")


def display_summary():
    """Quick overview of trades + signals."""
    display_accuracy()
    print()
    display_trades()


def main():
    parser = argparse.ArgumentParser(description="View trade history and Claude signal performance.")
    parser.add_argument("--signals", action="store_true", help="Show all Claude signals")
    parser.add_argument("--summary", action="store_true", help="Show summary statistics")
    parser.add_argument("--accuracy", action="store_true", help="Show Claude accuracy analysis")
    args = parser.parse_args()

    if args.signals:
        display_signals()
    elif args.accuracy:
        display_accuracy()
    elif args.summary:
        display_summary()
    else:
        display_trades()


if __name__ == "__main__":
    main()
