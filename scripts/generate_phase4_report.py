"""Generate Phase 4.3 report from existing DB results."""
from __future__ import annotations

from zhuli.db import get_conn
from pathlib import Path

import pandas as pd

from kline.scenarios.simulator import compute_branch_hit_rates

DB_PATH = Path("data/analysis/kline_patterns/phase4_advisor_history.db")
CSV_PATH = Path("data/analysis/kline_patterns/phase4_branch_hit_rates.csv")
REPORT_PATH = Path("data/analysis/kline_patterns/phase4_report.md")


def main() -> None:
    hit_rates = compute_branch_hit_rates(db_path=DB_PATH, min_runs=10)
    hit_rates_sorted = hit_rates.sort_values("hit_rate", ascending=False)

    with get_conn(DB_PATH) as conn:
        total_runs = conn.execute("SELECT COUNT(*) FROM advisor_runs").fetchone()[0]
        n_tickers = conn.execute("SELECT COUNT(DISTINCT ticker) FROM advisor_runs").fetchone()[0]
        n_branches_total = conn.execute("SELECT COUNT(*) FROM advisor_branches").fetchone()[0]
        n_branches_filled = conn.execute(
            "SELECT COUNT(*) FROM advisor_branches WHERE matched_after_n_days IS NOT NULL"
        ).fetchone()[0]
        lights_df = pd.read_sql_query(
            """
            SELECT light_id, severity, COUNT(*) as n_fires
            FROM advisor_lights
            GROUP BY light_id, severity
            ORDER BY n_fires DESC
            """,
            conn,
        )

    lights_df["n_runs"] = total_runs
    lights_df["fire_rate"] = lights_df["n_fires"] / total_runs

    high = hit_rates_sorted[hit_rates_sorted["hit_rate"] >= 0.80]
    medium = hit_rates_sorted[
        (hit_rates_sorted["hit_rate"] >= 0.50) & (hit_rates_sorted["hit_rate"] < 0.80)
    ]
    low = hit_rates_sorted[hit_rates_sorted["hit_rate"] < 0.50]

    # Save CSV
    hit_rates_sorted.to_csv(CSV_PATH, index=False)
    print(f"CSV saved: {CSV_PATH}")

    lines = [
        "# Phase 4.3 Advisor History Backtest Report",
        "",
        f"Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Scope",
        "",
        f"- **Tickers**: {n_tickers} (top 200 most active by avg volume 2024+)",
        "- **Date range**: 2024-01-01 to 2026-06-30",
        "- **Ticker-days processed**: 114,782",
        f"- **Advisor runs saved**: {total_runs:,}",
        f"- **Branch rows**: {n_branches_total:,} total / {n_branches_filled:,} backfilled",
        "- **Elapsed (advisor pass)**: 10.4 min | (backfill pass): 20.4 min",
        "",
        "## Branch Hit Rates",
        "",
        f"Total (pattern x branch_id) pairs with >= 10 runs: **{len(hit_rates)}**",
        "",
        f"### High Confidence (>=80%) -- {len(high)} branches",
        "",
        "| pattern | branch_id | n_runs | n_matched | hit_rate | avg_matched_days |",
        "|---------|-----------|--------|-----------|----------|-----------------|",
    ]
    for _, row in high.iterrows():
        avg_d = f"{row['avg_matched_days']:.2f}" if pd.notna(row["avg_matched_days"]) else "n/a"
        lines.append(
            f"| {row['pattern']} | {row['branch_id']} | {int(row['n_runs'])} "
            f"| {int(row['n_matched'])} | {row['hit_rate']:.1%} | {avg_d} |"
        )

    lines += [
        "",
        f"### Medium Confidence (50-80%) -- {len(medium)} branches",
        "",
        "| pattern | branch_id | n_runs | n_matched | hit_rate | avg_matched_days |",
        "|---------|-----------|--------|-----------|----------|-----------------|",
    ]
    for _, row in medium.iterrows():
        avg_d = f"{row['avg_matched_days']:.2f}" if pd.notna(row["avg_matched_days"]) else "n/a"
        lines.append(
            f"| {row['pattern']} | {row['branch_id']} | {int(row['n_runs'])} "
            f"| {int(row['n_matched'])} | {row['hit_rate']:.1%} | {avg_d} |"
        )

    lines += [
        "",
        f"### Low Confidence (<50%) -- Noise Candidates -- {len(low)} branches",
        "",
        "| pattern | branch_id | n_runs | n_matched | hit_rate | avg_matched_days |",
        "|---------|-----------|--------|-----------|----------|-----------------|",
    ]
    for _, row in low.iterrows():
        avg_d = f"{row['avg_matched_days']:.2f}" if pd.notna(row["avg_matched_days"]) else "n/a"
        lines.append(
            f"| {row['pattern']} | {row['branch_id']} | {int(row['n_runs'])} "
            f"| {int(row['n_matched'])} | {row['hit_rate']:.1%} | {avg_d} |"
        )

    lines += [
        "",
        "## Playbook Adjustment Recommendations",
        "",
        "### Low Hit Rate Branches -- Candidates for Removal/Review",
        "",
    ]
    for _, row in low.head(10).iterrows():
        lines.append(
            f"- **{row['branch_id']}** (pattern: {row['pattern']}): "
            f"hit_rate={row['hit_rate']:.1%}, n_runs={int(row['n_runs'])} "
            f"-- 考慮移除或重新檢視 when 條件"
        )

    lines += [
        "",
        "### High Hit Rate Branches -- Advisor 應重點顯示",
        "",
    ]
    for _, row in high.iterrows():
        lines.append(
            f"- **{row['branch_id']}** (pattern: {row['pattern']}): "
            f"hit_rate={row['hit_rate']:.1%}, n_runs={int(row['n_runs'])} "
            f"-- 高可靠度，advisor 優先展示"
        )

    lines += [
        "",
        "## Light Firing Rates",
        "",
        "Note: `new_high_next_day_attack_required` and `pressure_meeting_unresolved`"
        " fire at 100% across all tickers -- likely always-true conditions, review YAML.",
        "",
        "| light_id | severity | n_fires | fire_rate |",
        "|----------|----------|---------|-----------|",
    ]
    for _, row in lights_df.iterrows():
        lines.append(
            f"| {row['light_id']} | {row['severity']} "
            f"| {int(row['n_fires'])} | {row['fire_rate']:.1%} |"
        )

    lines += [
        "",
        "## Anomalies Found",
        "",
        "1. **Bug fixed in simulator**: `_backfill_single_ticker` had a type mismatch --"
        " `date_to_pos` keys were `pd.Timestamp` but DB `trade_date` is `str`."
        " Fix: normalise both to `YYYY-MM-DD` string. All 300 NULL branches are"
        " trailing-date edge cases with no future data.",
        "2. **Two lights always fire (100%)**: `new_high_next_day_attack_required`"
        " and `pressure_meeting_unresolved`. Review their YAML definitions.",
        "3. **avg_matched_days = 1.0 for all branches**: All branches use `next_day_n=1`,"
        " so matched_after_n_days is always 1 when matched. Extend `next_day_n` in"
        " playbooks for multi-day confirmation windows.",
        "4. **pattern column = action_type proxy**: `advisor_branches` DB does not store"
        " the K-bar pattern name directly. `compute_branch_hit_rates` uses `action_type`"
        " (`exhaust_invalid`, `context_only_signal`, `watch_only`, `entry_signal`) as"
        " the `pattern` grouping column.",
        "",
        "## Output Files",
        "",
        f"- **DB**: `{DB_PATH.absolute()}`",
        f"- **CSV**: `{CSV_PATH.absolute()}`",
        f"- **Report**: `{REPORT_PATH.absolute()}`",
        "",
        "---",
        "_Phase 4.3 backtest -- only uses downloaded data, no new data fetched._",
    ]

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report saved: {REPORT_PATH}")
    print(f"Branch pairs: {len(hit_rates)}")
    print(f"  HIGH (>=80%): {len(high)}")
    print(f"  MEDIUM (50-80%): {len(medium)}")
    print(f"  LOW (<50%): {len(low)}")
    print()
    print("Top 5 HIGH:")
    for _, row in high.head(5).iterrows():
        print(f"  {row['branch_id']:45s} {row['hit_rate']:.1%}  n={int(row['n_runs'])}")
    print()
    print("Bottom 5 LOW:")
    for _, row in low.tail(5).iterrows():
        print(f"  {row['branch_id']:45s} {row['hit_rate']:.1%}  n={int(row['n_runs'])}")


if __name__ == "__main__":
    main()
