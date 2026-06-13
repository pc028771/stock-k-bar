"""Evaluate four-seasons classifier accuracy via forward returns.

For each (ticker, trade_date, season) classification, compute N-day forward
close-to-close returns. Aggregate by season → median return, win rate, count.

Course expectation (docs/四季投資法/course_principles.md):
  立夏  — entry signal, expect strongest short-term return
  春    — accumulation, mild positive / flat
  盛夏  — markup continuation, positive
  秋    — distribution, turning negative
  冬    — mark-down, negative
"""
from __future__ import annotations

from zhuli.db import get_conn

import argparse
import os
import shutil
import tempfile
from pathlib import Path

import pandas as pd

DEFAULT_DB = Path("/Users/howard/.four_seasons/data.sqlite")
DEFAULT_IN = Path("data/analysis/four_seasons/season_mar_may.csv")
DEFAULT_OUT = Path("data/analysis/four_seasons/season_mar_may_accuracy.md")

HORIZONS = [1, 5, 20]


def _snapshot(db: Path) -> str:
    tmp = Path(tempfile.gettempdir()) / f"fs_accuracy_{os.getpid()}.sqlite"
    shutil.copy2(db, tmp)
    return str(tmp)


def load_close_panel(conn_path: str) -> pd.DataFrame:
    """All (ticker, trade_date, close), sorted, indexed for fast lookup."""
    with get_conn(conn_path, timeout=15) as conn:
        df = pd.read_sql_query(
            "select ticker, trade_date, close from standard_daily_bar where is_usable=1",
            conn, parse_dates=["trade_date"],
        )
    df["ticker"] = df["ticker"].astype(str)
    return df.sort_values(["ticker", "trade_date"]).reset_index(drop=True)


def attach_forward_returns(
    classifications: pd.DataFrame,
    closes: pd.DataFrame,
    horizons: list[int],
) -> pd.DataFrame:
    """For each (ticker, trade_date), look up close at +N trading days."""
    closes = closes.copy()
    closes["row_idx"] = closes.groupby("ticker").cumcount()
    idx_map = closes.set_index(["ticker", "trade_date"])["row_idx"]

    out = classifications.copy()
    out["ticker"] = out["ticker"].astype(str)
    out["trade_date"] = pd.to_datetime(out["trade_date"])
    out["row_idx"] = out.set_index(["ticker", "trade_date"]).index.map(idx_map)

    # Lookup table: (ticker, row_idx) → close
    close_lookup = closes.set_index(["ticker", "row_idx"])["close"]

    for h in horizons:
        target_idx = out["row_idx"] + h
        keys = list(zip(out["ticker"], target_idx))
        future_close = pd.Series(
            [close_lookup.get(k) if pd.notna(k[1]) else None for k in keys],
            index=out.index, dtype="float64",
        )
        out[f"ret_{h}d"] = (future_close / out["close"] - 1) * 100

    return out.drop(columns=["row_idx"])


def keep_first_entries(df: pd.DataFrame) -> pd.DataFrame:
    """For each ticker, keep only rows where season differs from previous trade day.

    Removes duplicate sampling from consecutive days in the same season state.
    A re-entry after exiting counts as a new first entry.
    """
    df = df.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values(["ticker", "trade_date"]).reset_index(drop=True)
    df["prev_season"] = df.groupby("ticker")["season"].shift(1)
    return df[df["season"] != df["prev_season"]].drop(columns=["prev_season"])


def aggregate(df: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    rows = []
    for season, g in df.groupby("season"):
        row = {"season": season, "count": len(g)}
        for h in horizons:
            col = f"ret_{h}d"
            valid = g[col].dropna()
            row[f"n_{h}d"] = len(valid)
            row[f"median_{h}d"] = valid.median()
            row[f"mean_{h}d"] = valid.mean()
            row[f"winrate_{h}d"] = (valid > 0).mean() * 100 if len(valid) else None
        rows.append(row)
    order = ["春", "立夏", "盛夏", "秋", "冬", "未分類"]
    return pd.DataFrame(rows).set_index("season").reindex(order).reset_index()


def render_markdown(agg: pd.DataFrame, horizons: list[int], src: Path) -> str:
    lines = [
        f"# Four-Seasons Classifier Accuracy Report",
        f"",
        f"- Source: `{src}`",
        f"- Metric: forward close-to-close return (%) at +1d / +5d / +20d trading days",
        f"- Win rate = % of samples with positive return",
        f"",
        f"## Aggregated by Season",
        f"",
        f"| 季節 | 樣本數 | "
        + " | ".join(f"中位數 {h}d | 勝率 {h}d" for h in horizons) + " |",
        f"|---" * (2 + 2 * len(horizons)) + "|",
    ]
    for _, r in agg.iterrows():
        if pd.isna(r["count"]):
            continue
        cells = [f"{r['season']}", f"{int(r['count']):,}"]
        for h in horizons:
            m = r[f"median_{h}d"]
            w = r[f"winrate_{h}d"]
            cells.append(f"{m:+.2f}%" if pd.notna(m) else "—")
            cells.append(f"{w:.1f}%" if pd.notna(w) else "—")
        lines.append("| " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Course Expectation vs. Observed",
        "",
        "| 季節 | 課程預期 | 觀察 (median 5d) | 一致？ |",
        "|---|---|---|---|",
    ]
    expect = {
        "春": ("溫和正報酬（吃貨完成）", lambda m: m and m > 0),
        "立夏": ("最強短期正報酬（起漲日）", lambda m: m and m > 0),
        "盛夏": ("持續正報酬", lambda m: m and m > 0),
        "秋": ("轉負（主力出貨）", lambda m: m and m < 0),
        "冬": ("負或弱勢", lambda m: m and m < 0),
    }
    for season, (desc, check) in expect.items():
        row = agg[agg["season"] == season]
        if row.empty or pd.isna(row.iloc[0]["median_5d"]):
            lines.append(f"| {season} | {desc} | — (no data) | — |")
            continue
        m5 = row.iloc[0]["median_5d"]
        ok = "✅" if check(m5) else "❌"
        lines.append(f"| {season} | {desc} | {m5:+.2f}% | {ok} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--in", dest="inp", type=Path, default=DEFAULT_IN)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--first-entry", action="store_true",
                   help="Dedup: keep only the first day a ticker enters each season run.")
    args = p.parse_args()

    conn_path = _snapshot(args.db)
    classifications = pd.read_csv(args.inp)
    if args.first_entry:
        before = len(classifications)
        classifications = keep_first_entries(classifications)
        print(f"[first-entry] {before:,} → {len(classifications):,} rows")
    closes = load_close_panel(conn_path)
    with_ret = attach_forward_returns(classifications, closes, HORIZONS)
    agg = aggregate(with_ret, HORIZONS)
    md = render_markdown(agg, HORIZONS, args.inp)
    args.out.write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
