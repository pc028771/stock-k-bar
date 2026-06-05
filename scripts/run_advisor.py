"""Run advisor on a specific ticker × date and print formatted output.

Usage:
    uv run python scripts/run_advisor.py 1605 2026-06-03
    uv run python scripts/run_advisor.py 6285 2026-06-03 --raw  # 印 raw json
"""
from __future__ import annotations

import argparse
import sys


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run advisor on a ticker × date and print formatted output."
    )
    ap.add_argument("ticker", help="Ticker symbol, e.g. 2885")
    ap.add_argument("date", help="Analysis date as YYYY-MM-DD, e.g. 2026-06-03")
    ap.add_argument("--raw", action="store_true", help="Print raw JSON instead of formatted output")
    args = ap.parse_args()

    from kline.bars import load_bars
    from kline.scenarios.advisor import analyze
    from kline.scenarios.formatter import format_advisor_result

    print("Loading bars...", flush=True)
    bars = load_bars(tickers=[args.ticker])

    print(f"Analyzing {args.ticker} @ {args.date}...", flush=True)
    try:
        result = analyze(bars, today_date=args.date, ticker=args.ticker)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.raw:
        print(result.model_dump_json(indent=2))
    else:
        print(format_advisor_result(result, ticker=args.ticker, today_date=args.date, bars=bars))


if __name__ == "__main__":
    main()
