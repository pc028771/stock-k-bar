"""Calibrate patterns against course case examples.

Loads CASE_INDEX.csv (extracted from 26 articles by Opus subagent), maps the
agent's slugs to our patterns/*.py file slugs, then for each DB-validated case
checks whether the corresponding detect() fires within approx_date ±
uncertainty days. Reports hit/miss per case + summary per pattern.

Used to validate whether course_proxy_constants.py engineering proposals are
consistent with course-cited historical examples.
"""
from __future__ import annotations

import argparse
import importlib
import sqlite3
from pathlib import Path

import pandas as pd

from kline.bars import load_bars
from kline.features import add_features

BACKFILL_DB = Path("data/analysis/kline_patterns/historical_backfill.sqlite")


def load_bars_union(date_threshold: str = "2022-01-01") -> pd.DataFrame:
    """Union main DB (2022+) with historical backfill (pre-2022 NO_OHLCV cases).

    Main DB is authoritative for 2022+; backfill covers pre-2022 course examples.
    Overlap is resolved by dropping backfill rows >= date_threshold.
    """
    main = load_bars()

    if not BACKFILL_DB.exists():
        return main

    try:
        with sqlite3.connect(str(BACKFILL_DB)) as conn:
            extra = pd.read_sql("SELECT * FROM standard_daily_bar", conn)
    except Exception as e:
        print(f"Warning: could not load backfill DB: {e}")
        return main

    if extra.empty:
        return main

    extra["trade_date"] = pd.to_datetime(extra["trade_date"], errors="coerce")
    # Drop overlap: only keep backfill rows strictly before threshold
    extra = extra[extra["trade_date"] < pd.to_datetime(date_threshold)].copy()

    # Align columns to what load_bars() returns (add missing cols as None/NaN)
    main_cols = main.columns.tolist()
    for col in main_cols:
        if col not in extra.columns:
            extra[col] = None
    extra = extra[main_cols]

    union = pd.concat([main, extra], ignore_index=True)
    union = union.sort_values(["ticker", "trade_date"]).reset_index(drop=True)
    return union

CASE_CSV = Path("docs/kline_course/long_short_turning_point/CASE_INDEX.csv")
OUT_DIR = Path("data/analysis/kline_patterns")

# Map Opus agent's pattern_slug → actual scripts/kline/patterns/*.py slug.
# Cases the agent emitted for extras/ patterns are mapped to None and skipped.
SLUG_MAP = {
    "step_up_down": "rising_falling",
    "harami_neutral": "embracing",
    "harami": "embracing",
    "engulfing_pattern_neutral": "neutral_engulfing",
    "bearish_one_day_reversal": None,  # in extras/ — skip
    "bullish_one_day_reversal": None,
    "island_reversal_bull": "morning_star_island_reversal",
    "island_reversal_bear": "evening_star_island_reversal",
    "counterattack_pattern": "rebound",
    "meeting_lines": "meeting",
    "piercing_pattern": "piercing_line",
    "breakout_two_star": "breakout_double_star",
    "determined_break": "biting",
    "evening_star": "evening_star_abandoned",
    "hanging_man": "high_hanging_man",
    "internal_trap": "trapped",
    "enemy_at_gate": "three_red_dadi_dangqian",
    "gap_down_reversal": "gap_reversal",
    "two_crows_gap": "two_crow_gap",
    "dark_night_two_star": "dark_double_star_anye",
    "outside_three_black": "outside_three_black",
    "gap_fill_pattern": "gap_fill_up",  # ambiguous; will check both up + down
    "morning_star_harami": "morning_star_harami",
    "engulfing": None,  # ambiguous bull/bear; will dispatch by notes
}


def load_cases(path: Path) -> pd.DataFrame:
    """Load calibration cases.

    Includes:
    - DB_OK cases: already validated in main DB
    - NO_OHLCV cases with backfill data in historical_backfill.sqlite
    """
    df = pd.read_csv(path)
    df["approx_date"] = pd.to_datetime(df["approx_date"], errors="coerce")
    notes = df["notes"].fillna("")
    db_ok = df[notes.str.contains("DB_OK")].copy()

    # Include NO_OHLCV cases that now have backfill data
    if BACKFILL_DB.exists():
        try:
            with sqlite3.connect(str(BACKFILL_DB)) as conn:
                backfill_tickers = set(
                    pd.read_sql("SELECT DISTINCT ticker FROM standard_daily_bar", conn)["ticker"].tolist()
                )
        except Exception:
            backfill_tickers = set()

        no_ohlcv = df[notes.str.contains("NO_OHLCV")].copy()
        no_ohlcv["ticker"] = no_ohlcv["ticker"].astype(str)
        backfilled = no_ohlcv[no_ohlcv["ticker"].isin(backfill_tickers)].copy()
        if not backfilled.empty:
            print(f"Including {len(backfilled)} NO_OHLCV cases now covered by backfill DB")
            db_ok = pd.concat([db_ok, backfilled], ignore_index=True)

    return db_ok


def map_slug(row) -> list[str]:
    agent_slug = str(row["pattern_slug"])
    if agent_slug in SLUG_MAP:
        v = SLUG_MAP[agent_slug]
        return [v] if v else []
    if agent_slug == "engulfing":
        notes = str(row.get("notes", "")).lower()
        if "bear" in notes or "黑" in notes or "空" in notes:
            return ["bear_engulfing"]
        return ["bull_engulfing"]
    if agent_slug == "gap_fill_pattern":
        return ["gap_fill_up", "gap_fill_down"]
    return [agent_slug]  # fallback assume matches our file slug


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(CASE_CSV))
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cases = load_cases(Path(args.cases))
    print(f"DB-validated cases: {len(cases)}")

    # Load all bars (2015+) — union of main DB and historical backfill
    print("Loading bars + features (one pass) ...")
    df = load_bars_union()
    df = df[df["trade_date"] >= "2015-01-01"].copy()
    df = add_features(df)

    # Pre-compute every detect() signal once (expensive but reusable)
    print("Computing detect() for each pattern ...")
    detect_results = {}
    for slug in sorted(set(v for v in SLUG_MAP.values() if v) | {"bull_engulfing", "bear_engulfing", "gap_fill_up", "gap_fill_down"}):
        try:
            mod = importlib.import_module(f"kline.patterns.{slug}")
            detect_results[slug] = mod.detect(df).fillna(False)
        except Exception as e:
            print(f"  FAIL {slug}: {e}")
            detect_results[slug] = pd.Series(False, index=df.index)

    # Index df by (ticker, trade_date) for fast lookup
    df_idx = df.set_index(["ticker", "trade_date"]).index

    rows = []
    for _, row in cases.iterrows():
        ticker = str(row["ticker"])
        approx = row["approx_date"]
        unc = max(int(row.get("date_uncertainty_days") or 5), 10)  # min ±10 days
        slugs = map_slug(row)
        if not slugs:
            rows.append({**row.to_dict(), "actual_slug": None, "hit": None, "reason": "extras_pattern_skipped"})
            continue
        mask_ticker = df["ticker"] == ticker
        mask_window = (df["trade_date"] >= approx - pd.Timedelta(days=unc)) & (df["trade_date"] <= approx + pd.Timedelta(days=unc))
        idx_window = df.index[mask_ticker & mask_window]
        if len(idx_window) == 0:
            rows.append({**row.to_dict(), "actual_slug": slugs[0], "hit": False, "reason": "no_bars_in_window"})
            continue
        hit_any = False
        actual_slug_used = None
        for s in slugs:
            sig = detect_results[s].loc[idx_window]
            if sig.any():
                hit_any = True
                actual_slug_used = s
                hit_dates = df.loc[idx_window[sig.values], "trade_date"].dt.strftime("%Y-%m-%d").tolist()
                break
        rows.append({
            **row.to_dict(),
            "actual_slug": actual_slug_used or slugs[0],
            "hit": hit_any,
            "reason": "hit" if hit_any else "no_trigger_in_window",
            "hit_dates": ",".join(hit_dates) if hit_any else "",
        })

    out = pd.DataFrame(rows)
    out_path = out_dir / "calibration_results.csv"
    out.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")

    # Summary by pattern (positive cases only)
    pos = out[out["expected_detect"] == True]
    summary = pos.groupby("actual_slug").agg(
        n=("hit", "size"),
        hits=("hit", "sum"),
    )
    summary["hit_rate_pct"] = (summary["hits"] / summary["n"] * 100).round(1)
    summary = summary.sort_values("hit_rate_pct")
    print("\n=== Hit rate per pattern (positive cases) ===")
    print(summary.to_string())

    sum_path = out_dir / "calibration_summary.csv"
    summary.to_csv(sum_path)
    print(f"\nWrote {sum_path}")

    # Misses list — for constant adjustment focus
    miss = out[(out["expected_detect"] == True) & (out["hit"] == False)]
    print(f"\n=== Misses ({len(miss)}) ===")
    if len(miss):
        print(miss[["actual_slug", "ticker", "case_company_name", "approx_date", "reason"]].to_string(index=False))


if __name__ == "__main__":
    main()
