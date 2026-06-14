"""Phase 4.3 advisor history backtest runner.

Usage:
    uv run python scripts/run_phase4_backtest.py --tickers 200 --start 2024-01-01 --end 2026-06-30
    uv run python scripts/run_phase4_backtest.py --all --start 2024-01-01 --end 2026-06-30

Design constraints (從 spec):
- 禁算 ret_Nd / EV / PnL (feedback_backtest_methodology)
- 只用已下載資料；缺資料 ticker / 日期直接跳過、不抓新 data
- DB lock 守好 (feedback_db_unlock)
- 只用 simulator.py 既有 API
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = Path(__file__).parent

# Add scripts/ to path so `kline` package is importable (matches pytest pythonpath config)
sys.path.insert(0, str(SCRIPTS_DIR))

from zhuli.db import get_conn
from kline.bars import load_bars
from kline.scenarios.simulator import (
    compute_branch_hit_rates,
    simulate_advisor_history,
)

OUTPUT_DIR = REPO_ROOT / "data" / "analysis" / "kline_patterns"
DB_PATH = OUTPUT_DIR / "phase4_advisor_history.db"
CSV_PATH = OUTPUT_DIR / "phase4_branch_hit_rates.csv"
REPORT_PATH = OUTPUT_DIR / "phase4_report.md"


# ---------------------------------------------------------------------------
# Ticker selection
# ---------------------------------------------------------------------------


def _pick_tickers(df: pd.DataFrame, n: int) -> list[str]:
    """Pick top-N most active tickers by mean volume (2024+), excluding TAIEX & ETF-like."""
    sub = df[df["trade_date"] >= "2024-01-01"].copy()
    avg_vol = sub.groupby("ticker")["volume"].mean()
    # Exclude TAIEX index and tickers starting with '0' (ETFs / indices)
    avg_vol = avg_vol[~avg_vol.index.str.startswith("0")]
    avg_vol = avg_vol[avg_vol.index != "TAIEX"]
    # Must have at least 100 days of data
    count = sub.groupby("ticker").size()
    valid = count[count >= 100].index
    avg_vol = avg_vol[avg_vol.index.isin(valid)]
    top_n = avg_vol.nlargest(n).index.tolist()
    return top_n


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _compute_lights_hit_rates(db_path: Path, min_runs: int = 10) -> pd.DataFrame:
    """Compute per-light_id firing rate (not a branch hit rate, but frequency)."""
    if not db_path.exists():
        return pd.DataFrame(columns=["light_id", "severity", "n_fires", "n_runs", "fire_rate"])

    with get_conn(db_path) as conn:
        total_runs = conn.execute("SELECT COUNT(*) FROM advisor_runs").fetchone()[0]
        if total_runs == 0:
            return pd.DataFrame(columns=["light_id", "severity", "n_fires", "n_runs", "fire_rate"])

        lights_df = pd.read_sql_query(
            """
            SELECT light_id, severity, COUNT(*) as n_fires
            FROM advisor_lights
            GROUP BY light_id, severity
            ORDER BY n_fires DESC
            """,
            conn,
        )

    if lights_df.empty:
        return pd.DataFrame(columns=["light_id", "severity", "n_fires", "n_runs", "fire_rate"])

    lights_df["n_runs"] = total_runs
    lights_df["fire_rate"] = lights_df["n_fires"] / total_runs
    return lights_df[lights_df["n_fires"] >= min_runs]


def _get_pattern_trigger_stats(db_path: Path) -> pd.DataFrame:
    """Get per-pattern trigger counts from advisor_runs."""
    if not db_path.exists():
        return pd.DataFrame()

    with get_conn(db_path) as conn:
        # Detect schema version (pattern_name column may not exist in older DBs)
        col_info = conn.execute("PRAGMA table_info(advisor_branches)").fetchall()
        col_names = {row[1] for row in col_info}
        has_pattern_name = "pattern_name" in col_names

        if has_pattern_name:
            df = pd.read_sql_query(
                """
                SELECT ar.ticker, ar.trade_date, ar.fired_pattern_count,
                       ar.scenario_count, ab.branch_id, ab.action_type,
                       ab.pattern_name, ab.matched_after_n_days
                FROM advisor_runs ar
                LEFT JOIN advisor_branches ab ON ar.run_id = ab.run_id
                """,
                conn,
            )
        else:
            df = pd.read_sql_query(
                """
                SELECT ar.ticker, ar.trade_date, ar.fired_pattern_count,
                       ar.scenario_count, ab.branch_id, ab.action_type,
                       ab.matched_after_n_days
                FROM advisor_runs ar
                LEFT JOIN advisor_branches ab ON ar.run_id = ab.run_id
                """,
                conn,
            )
    return df


def _generate_report(
    summary: dict,
    hit_rates: pd.DataFrame,
    lights_df: pd.DataFrame,
    tickers: list[str],
    start_date: str,
    end_date: str,
    elapsed_min: float,
    raw_df: pd.DataFrame,
) -> str:
    """Generate markdown report."""

    n_tickers = summary["n_tickers"]
    n_dates = summary["n_dates"]
    n_runs_saved = summary["n_runs_saved"]
    n_runs_skipped = summary["n_runs_skipped"]
    n_backfilled = summary["n_branches_backfilled"]

    # Estimate ticker-days
    ticker_days = len(raw_df) if not raw_df.empty else n_tickers * n_dates

    lines = [
        "# Phase 4.3 Advisor History Backtest Report",
        "",
        f"Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Scope",
        "",
        f"- **Tickers**: {n_tickers}",
        f"- **Date range**: {start_date} → {end_date}",
        f"- **Trading dates in range**: {n_dates}",
        f"- **Ticker-days processed**: {ticker_days:,}",
        f"- **Advisor runs saved**: {n_runs_saved:,}",
        f"- **Runs skipped** (idempotent): {n_runs_skipped:,}",
        f"- **Branch rows backfilled**: {n_backfilled:,}",
        f"- **Elapsed time**: {elapsed_min:.1f} minutes",
        "",
    ]

    # ---- Branch hit rates ----
    if hit_rates.empty:
        lines += [
            "## Branch Hit Rates",
            "",
            "_No branches with sufficient runs (min_runs=10) found._",
            "",
        ]
    else:
        n_pairs = len(hit_rates)
        lines += [
            "## Branch Hit Rates",
            "",
            f"Total (pattern × branch_id) pairs with ≥10 runs: **{n_pairs}**",
            "",
        ]

        # High hit rate (≥80%)
        high = hit_rates[hit_rates["hit_rate"] >= 0.80].sort_values("hit_rate", ascending=False)
        medium = hit_rates[(hit_rates["hit_rate"] >= 0.50) & (hit_rates["hit_rate"] < 0.80)].sort_values("hit_rate", ascending=False)
        low = hit_rates[hit_rates["hit_rate"] < 0.50].sort_values("hit_rate", ascending=True)

        lines += [
            f"### High Confidence (≥80%) — {len(high)} branches",
            "",
            "| pattern | branch_id | n_runs | n_matched | hit_rate | avg_matched_days |",
            "|---------|-----------|--------|-----------|----------|-----------------|",
        ]
        for _, row in high.iterrows():
            avg_d = f"{row['avg_matched_days']:.2f}" if pd.notna(row["avg_matched_days"]) else "—"
            lines.append(
                f"| {row['pattern']} | {row['branch_id']} | {int(row['n_runs'])} | "
                f"{int(row['n_matched'])} | {row['hit_rate']:.1%} | {avg_d} |"
            )

        lines += [
            "",
            f"### Medium Confidence (50–80%) — {len(medium)} branches",
            "",
            "| pattern | branch_id | n_runs | n_matched | hit_rate | avg_matched_days |",
            "|---------|-----------|--------|-----------|----------|-----------------|",
        ]
        for _, row in medium.iterrows():
            avg_d = f"{row['avg_matched_days']:.2f}" if pd.notna(row["avg_matched_days"]) else "—"
            lines.append(
                f"| {row['pattern']} | {row['branch_id']} | {int(row['n_runs'])} | "
                f"{int(row['n_matched'])} | {row['hit_rate']:.1%} | {avg_d} |"
            )

        lines += [
            "",
            f"### Low Confidence (<50%) — Noise Candidates — {len(low)} branches",
            "",
            "| pattern | branch_id | n_runs | n_matched | hit_rate | avg_matched_days |",
            "|---------|-----------|--------|-----------|----------|-----------------|",
        ]
        for _, row in low.iterrows():
            avg_d = f"{row['avg_matched_days']:.2f}" if pd.notna(row["avg_matched_days"]) else "—"
            lines.append(
                f"| {row['pattern']} | {row['branch_id']} | {int(row['n_runs'])} | "
                f"{int(row['n_matched'])} | {row['hit_rate']:.1%} | {avg_d} |"
            )

        lines += [""]

        # Playbook adjustment recommendations
        lines += [
            "## Playbook Adjustment Recommendations",
            "",
            "### Low Hit Rate Branches — Candidates for Removal/Review",
            "",
        ]
        if low.empty:
            lines.append("_None with ≥10 runs._")
        else:
            for _, row in low.head(10).iterrows():
                lines.append(
                    f"- **{row['branch_id']}** (pattern: {row['pattern']}): "
                    f"hit_rate={row['hit_rate']:.1%}, n_runs={int(row['n_runs'])} → "
                    f"考慮移除或重新檢視 when 條件"
                )

        lines += [
            "",
            "### High Hit Rate Branches — Advisor 應重點顯示",
            "",
        ]
        if high.empty:
            lines.append("_None with ≥10 runs._")
        else:
            for _, row in high.head(10).iterrows():
                lines.append(
                    f"- **{row['branch_id']}** (pattern: {row['pattern']}): "
                    f"hit_rate={row['hit_rate']:.1%}, n_runs={int(row['n_runs'])} → "
                    f"高可靠度，advisor 優先展示"
                )
        lines += [""]

    # ---- Lights ----
    lines += [
        "## Light Firing Rates",
        "",
    ]
    if lights_df.empty:
        lines.append("_No lights fired (or no data)._")
    else:
        lines += [
            "| light_id | severity | n_fires | fire_rate |",
            "|----------|----------|---------|-----------|",
        ]
        for _, row in lights_df.iterrows():
            lines.append(
                f"| {row['light_id']} | {row['severity']} | "
                f"{int(row['n_fires'])} | {row['fire_rate']:.1%} |"
            )

    lines += [
        "",
        "## Output Files",
        "",
        f"- **DB**: `{DB_PATH}`",
        f"- **CSV**: `{CSV_PATH}`",
        f"- **Report**: `{REPORT_PATH}`",
        "",
        "---",
        "_Phase 4.3 backtest — only uses downloaded data, no new data fetched._",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 4.3 advisor history backtest")
    parser.add_argument("--tickers", type=int, default=200, help="Number of tickers to sample (default: 200)")
    parser.add_argument("--all", action="store_true", help="Use all tickers (ignores --tickers)")
    parser.add_argument("--start", default="2024-01-01", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default="2026-06-30", help="End date YYYY-MM-DD")
    parser.add_argument("--min-runs", type=int, default=10, help="Min runs for hit rate inclusion")
    parser.add_argument("--dry-run", action="store_true", help="Run advisor but don't write to DB")
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel worker processes (default 1 = serial; 0 = max(1, cpu_count-1))",
    )
    args = parser.parse_args()

    if args.workers == 0:
        args.workers = max(1, (os.cpu_count() or 2) - 1)

    print("Phase 4.3 Advisor History Backtest")
    print(f"  Scope: {args.start} → {args.end}")
    print(f"  Output DB: {DB_PATH}")
    print()

    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ---- Load bars ----
    print("Loading bars from DB...")
    t0 = time.time()
    bars_df = load_bars()
    print(f"  Loaded {len(bars_df):,} rows, {bars_df['ticker'].nunique()} tickers")

    # Filter to date range (keep extra history before start for MA warm-up)
    warmup_start = pd.Timestamp(args.start) - pd.DateOffset(days=365)
    bars_df = bars_df[bars_df["trade_date"] >= warmup_start.strftime("%Y-%m-%d")].copy()
    print(f"  After warmup filter: {len(bars_df):,} rows")

    # ---- Select tickers ----
    if args.all:
        tickers = bars_df["ticker"].unique().tolist()
        tickers = [t for t in tickers if not t.startswith("0") and t != "TAIEX"]
        print(f"  Using ALL tickers: {len(tickers)}")
    else:
        n = args.tickers
        tickers = _pick_tickers(bars_df, n)
        print(f"  Sampled {len(tickers)} most active tickers by volume (2024+)")
        print(f"  Sample: {tickers[:10]}...")

    # ---- Filter bars to selected tickers ----
    bars_df = bars_df[bars_df["ticker"].isin(tickers)].copy()
    ticker_days = len(bars_df[
        (bars_df["trade_date"] >= args.start) & (bars_df["trade_date"] <= args.end)
    ])
    print(f"  Ticker-days in range: {ticker_days:,}")
    print()

    # ---- Run simulator ----
    print("Running simulate_advisor_history()...")
    print("  (This may take several minutes...)")
    t1 = time.time()

    print(f"  Workers: {args.workers}")
    summary = simulate_advisor_history(
        bars_df=bars_df,
        start_date=args.start,
        end_date=args.end,
        tickers=tickers,
        db_path=DB_PATH,
        save_to_db=not args.dry_run,
        n_workers=args.workers,
    )

    elapsed = time.time() - t1
    elapsed_min = elapsed / 60
    print(f"  Done in {elapsed_min:.1f} minutes")
    print(f"  n_tickers={summary['n_tickers']}, n_dates={summary['n_dates']}")
    print(f"  n_runs_saved={summary['n_runs_saved']:,}, n_skipped={summary['n_runs_skipped']:,}")
    print(f"  n_branches_backfilled={summary['n_branches_backfilled']:,}")
    print()

    if args.dry_run:
        print("DRY RUN — no DB writes, skipping hit rate computation")
        return

    # ---- Compute branch hit rates ----
    print("Computing branch hit rates...")
    hit_rates = compute_branch_hit_rates(db_path=DB_PATH, min_runs=args.min_runs)
    print(f"  {len(hit_rates)} (pattern × branch_id) pairs with ≥{args.min_runs} runs")

    if not hit_rates.empty:
        hit_rates_sorted = hit_rates.sort_values("hit_rate", ascending=False)
        print()
        print("  Top 5 highest hit_rate:")
        for _, row in hit_rates_sorted.head(5).iterrows():
            print(f"    {row['branch_id']:40s} {row['hit_rate']:.1%}  (n={int(row['n_runs'])})")
        print()
        print("  Bottom 5 lowest hit_rate:")
        for _, row in hit_rates_sorted.tail(5).iterrows():
            print(f"    {row['branch_id']:40s} {row['hit_rate']:.1%}  (n={int(row['n_runs'])})")

        # Save CSV
        hit_rates_sorted.to_csv(CSV_PATH, index=False)
        print(f"\n  CSV saved: {CSV_PATH}")

    # ---- Compute lights stats ----
    lights_df = _compute_lights_hit_rates(DB_PATH, min_runs=args.min_runs)

    # ---- Generate report ----
    raw_df_in_range = bars_df[
        (bars_df["trade_date"] >= args.start) & (bars_df["trade_date"] <= args.end)
    ]
    report_text = _generate_report(
        summary=summary,
        hit_rates=hit_rates,
        lights_df=lights_df,
        tickers=tickers,
        start_date=args.start,
        end_date=args.end,
        elapsed_min=elapsed_min,
        raw_df=raw_df_in_range,
    )

    REPORT_PATH.write_text(report_text, encoding="utf-8")
    print(f"  Report saved: {REPORT_PATH}")

    # ---- Final summary ----
    total_elapsed = (time.time() - t0) / 60
    print()
    print("=" * 60)
    print("PHASE 4.3 BACKTEST COMPLETE")
    print("=" * 60)
    print(f"  Tickers: {summary['n_tickers']}")
    print(f"  Ticker-days: {ticker_days:,}")
    print(f"  Elapsed: {total_elapsed:.1f} min")
    print(f"  Branch pairs: {len(hit_rates)}")
    print(f"  DB: {DB_PATH}")
    print(f"  CSV: {CSV_PATH}")
    print(f"  Report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
