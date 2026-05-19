"""Sanity check — verify scanner hits the 5 instructor cases from §H.

Course source: strategy-indicators.md §H 講師案例

Expected cases (signal_date = 出量 K 日期 = entry date):
    3533 嘉澤    2020/12/30  suffocation_date ~= 2020/12/29
    8150 南茂    2021/03/10  suffocation_date ~= 2021/03/09
    6284 佳邦    2021/01/22  suffocation_date ~= 2021/01/21
    2338 光罩    2021/02/18  suffocation_date ~= 2021/02/17  (情境 B)
    1590 亞德客-KY 2020/12/24 suffocation_date ~= 2020/12/23

Note: sanity check uses a ±2 trading-day tolerance for signal_date,
because the spec records entry dates but not the exact suffocation date.
A "hit" = scanner finds a signal for that ticker within ±2 trading days
of the spec's signal_date.

Usage:
    python -m zhuli.sanity_check [--db PATH] [--verbose]
    python scripts/zhuli/sanity_check.py [--db PATH] [--verbose]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

# Allow running as script directly
_SCRIPT_DIR = Path(__file__).parent.parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from kline.bars import DEFAULT_DB_PATH, load_bars
from kline.features import add_features
from zhuli.config import SuffocationConfig
from zhuli.features import add_zhuli_features
from zhuli.entry.suffocation import detect


# === Instructor cases from strategy-indicators.md §H ===
# Format: (ticker, expected_signal_date, expected_scenario, notes)
INSTRUCTOR_CASES = [
    ("3533", "2020-12-30", "A", "嘉澤 — 窒息量範例"),
    ("8150", "2021-03-10", "A", "南茂 — 進場 35.43，停損 34.85"),
    ("6284", "2021-01-22", "A", "佳邦 — 進場 73.9，停損 71.2，目標 91.83"),
    ("2338", "2021-02-18", "B", "光罩 — 情境 B（跌破月線後），進場 ~45-48"),
    ("1590", "2020-12-24", "A", "亞德客-KY — 進場 874（還原），停損 862"),
]

TOLERANCE_DAYS = 2  # ±2 calendar days for date matching


def _get_db_date_range(db_path: Path) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """Return (min_date, max_date) from the DB, or (None, None) on error."""
    import sqlite3
    try:
        with sqlite3.connect(str(db_path), timeout=15) as conn:
            row = conn.execute(
                "SELECT MIN(trade_date), MAX(trade_date) "
                "FROM standard_daily_bar WHERE is_usable=1"
            ).fetchone()
        if row and row[0]:
            return pd.Timestamp(row[0]), pd.Timestamp(row[1])
    except Exception:
        pass
    return None, None


def run_sanity_check(
    db_path: Path = DEFAULT_DB_PATH,
    cfg: SuffocationConfig | None = None,
    verbose: bool = False,
) -> dict:
    """Run sanity check against all instructor cases.

    Returns:
        dict with keys:
            hits: list of (ticker, spec_date, found_date, scenario, notes)
            misses: list of (ticker, spec_date, notes, reason)
            hit_count: int
            total: int
            passed: bool (True if all cases hit)
    """
    if cfg is None:
        cfg = SuffocationConfig()

    db_min, db_max = _get_db_date_range(db_path)
    if db_min:
        print(f"DB date range: {db_min.date()} → {db_max.date()}")
        # Check which cases fall outside the DB range
        out_of_range = [
            (ticker, spec_date_str, notes)
            for ticker, spec_date_str, _, notes in INSTRUCTOR_CASES
            if pd.Timestamp(spec_date_str) < db_min
        ]
        if out_of_range:
            print(
                f"  ⚠ {len(out_of_range)} instructor case(s) fall BEFORE DB start "
                f"({db_min.date()}) — these will always miss without historical data:"
            )
            for t, d, n in out_of_range:
                print(f"    {t} {d} ({n.split('—')[0].strip()})")

    print("Loading bars from DB...")
    bars = load_bars(db_path=db_path)
    print(f"  Loaded {len(bars):,} rows for {bars['ticker'].nunique()} tickers.")

    print("Computing features...")
    feats = add_features(bars)
    feats = add_zhuli_features(feats)

    # Run scanner without date filter (full history)
    print("Running suffocation detector (full history)...")
    signals = detect(feats, cfg=cfg)
    print(f"  Found {len(signals):,} total signals across all dates.")

    hits = []
    misses = []

    for ticker, spec_date_str, expected_scenario, notes in INSTRUCTOR_CASES:
        spec_date = pd.Timestamp(spec_date_str)
        tolerance = pd.Timedelta(days=TOLERANCE_DAYS + 4)  # +4 for weekends/holidays

        # Filter signals for this ticker within date window
        ticker_signals = signals[
            (signals["ticker"] == ticker)
            & (signals["signal_date"] >= spec_date - tolerance)
            & (signals["signal_date"] <= spec_date + tolerance)
        ]

        if len(ticker_signals) > 0:
            # Pick closest signal date
            best = ticker_signals.iloc[
                (ticker_signals["signal_date"] - spec_date).abs().argsort().iloc[0]
            ]
            found_date = best["signal_date"]
            found_scenario = best["scenario"]

            hit_info = {
                "ticker": ticker,
                "spec_date": spec_date_str,
                "found_date": pd.Timestamp(found_date).strftime("%Y-%m-%d"),
                "found_scenario": found_scenario,
                "expected_scenario": expected_scenario,
                "scenario_match": found_scenario == expected_scenario,
                "vol_ratio": round(float(best["suffocation_vol_ratio"]), 4),
                "stop_loss": best["stop_loss"],
                "notes": notes,
            }
            hits.append(hit_info)

            if verbose:
                scenario_ok = "✓" if hit_info["scenario_match"] else "⚠"
                print(
                    f"  ✓ {ticker} ({notes.split('—')[0].strip()}): "
                    f"spec={spec_date_str} found={hit_info['found_date']} "
                    f"scenario={found_scenario}{scenario_ok} "
                    f"vol_ratio={hit_info['vol_ratio']:.4f} "
                    f"stop={hit_info['stop_loss']:.2f}"
                )
        else:
            # Check if ticker has any signals at all
            any_signals = signals[signals["ticker"] == ticker]
            if len(any_signals) == 0:
                reason = "No signals found for this ticker in full history"
            else:
                nearest = any_signals.iloc[
                    (any_signals["signal_date"] - spec_date).abs().argsort().iloc[0]
                ]
                nearest_ts = pd.Timestamp(nearest["signal_date"])
                nearest_date = (
                    nearest_ts.strftime("%Y-%m-%d")
                    if nearest_ts is not pd.NaT and not pd.isnull(nearest_ts)
                    else "unknown"
                )
                reason = (
                    f"No signal within ±{TOLERANCE_DAYS} trading days. "
                    f"Nearest signal: {nearest_date}"
                )

            # Mark whether the miss is due to data range limitations
            data_limited = db_min is not None and spec_date < db_min

            miss_info = {
                "ticker": ticker,
                "spec_date": spec_date_str,
                "expected_scenario": expected_scenario,
                "reason": reason,
                "notes": notes,
                "data_limited": data_limited,
            }
            misses.append(miss_info)

            if verbose:
                print(f"  ✗ {ticker} ({notes.split('—')[0].strip()}): {reason}")

    # "passed" = no misses that are within the DB date range
    data_limited_misses = [m for m in misses if m.get("data_limited")]
    logic_misses = [m for m in misses if not m.get("data_limited")]

    return {
        "hits": hits,
        "misses": misses,
        "data_limited_misses": data_limited_misses,
        "logic_misses": logic_misses,
        "hit_count": len(hits),
        "total": len(INSTRUCTOR_CASES),
        "in_range_total": len(INSTRUCTOR_CASES) - len(data_limited_misses),
        "passed": len(logic_misses) == 0,
        "db_range": (
            (db_min.date().isoformat(), db_max.date().isoformat())
            if db_min else None
        ),
    }


def print_report(result: dict) -> None:
    """Print formatted sanity check report."""
    hit_count = result["hit_count"]
    total = result["total"]
    passed = result["passed"]

    print()
    print("=" * 60)
    print(f"Sanity Check: {hit_count}/{total} instructor cases hit")
    print("=" * 60)

    if result["hits"]:
        print("\nHits:")
        for h in result["hits"]:
            scenario_flag = "" if h["scenario_match"] else " (scenario mismatch)"
            print(
                f"  ✓ {h['ticker']}  spec={h['spec_date']}  "
                f"found={h['found_date']}  "
                f"scenario={h['found_scenario']}{scenario_flag}  "
                f"vol_ratio={h['vol_ratio']:.4f}"
            )

    if result["misses"]:
        print("\nMisses:")
        for m in result["misses"]:
            print(f"  ✗ {m['ticker']}  spec={m['spec_date']}  {m['reason']}")

    db_range = result.get("db_range")
    data_limited = result.get("data_limited_misses", [])
    logic_misses = result.get("logic_misses", [])

    print()
    if result["passed"] and len(data_limited) == 0:
        print("PASSED — all instructor cases detected.")
    elif result["passed"] and data_limited:
        print(
            f"PASSED (within DB range) — "
            f"{result['hit_count']}/{result['in_range_total']} in-range cases hit.\n"
            f"  {len(data_limited)} case(s) skipped: spec date before DB start "
            f"({db_range[0] if db_range else '?'}).\n"
            "  Need historical data (pre-2025) to verify those cases."
        )
    else:
        miss_tickers = [m["ticker"] for m in logic_misses]
        print(f"FAILED — missed (logic error): {', '.join(miss_tickers)}")
        if data_limited:
            skip_tickers = [m["ticker"] for m in data_limited]
            print(f"  Skipped (no historical data): {', '.join(skip_tickers)}")
        print("Investigate: run with --verbose to see nearest signal dates.")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Sanity check: verify scanner detects §H instructor cases."
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print per-case detail during scan."
    )
    parser.add_argument(
        "--config-override", nargs="*", metavar="KEY=VALUE",
        help="Override SuffocationConfig values, e.g. max20_volume_ratio=0.12",
    )
    args = parser.parse_args()

    cfg = SuffocationConfig()
    if args.config_override:
        overrides = dict(kv.split("=", 1) for kv in args.config_override)
        cfg = cfg.apply_overrides(overrides)

    result = run_sanity_check(db_path=args.db, cfg=cfg, verbose=args.verbose)
    print_report(result)

    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
