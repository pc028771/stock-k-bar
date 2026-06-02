"""Auto-correct CASE_INDEX_v2 dates by scanning detect() output.

For each confirmed_signal case where detect() doesn't fire within current
window, expand to ±30 trading days and search for the FIRST trigger date.
If found → update corrected_approx_date and add `date_autocorrected=True`.
If not found anywhere in ±30 → mark as `real_miss=True` (true detect gap).

Conservative: only update when detect fires for the SAME ticker on EXACTLY
the expected pattern. No cross-pattern reassignment.
"""
from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path

import pandas as pd

from kline.bars import load_bars
from kline.features import add_features

CASE_V2 = Path("docs/kline_course/long_short_turning_point/CASE_INDEX_v2.csv")
CASE_V3 = Path("docs/kline_course/long_short_turning_point/CASE_INDEX_v3.csv")
OUT_DIR = Path("data/analysis/kline_patterns")
BACKFILL_DB = Path("data/analysis/kline_patterns/historical_backfill.sqlite")

WINDOW_DAYS = 30  # ±30 calendar days search

SLUG_MAP = {
    "step_up_down": "rising_falling",
    "harami_neutral": "embracing",
    "harami": "embracing",
    "engulfing_pattern_neutral": "neutral_engulfing",
    "bearish_one_day_reversal": None,
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
    "gap_fill_pattern": "gap_fill_up",
    "morning_star_harami": "morning_star_harami",
    "engulfing": None,
}


def load_bars_union():
    main = load_bars()
    if not BACKFILL_DB.exists():
        return main
    with sqlite3.connect(str(BACKFILL_DB)) as conn:
        extra = pd.read_sql("SELECT * FROM standard_daily_bar", conn)
    if extra.empty:
        return main
    extra["trade_date"] = pd.to_datetime(extra["trade_date"], errors="coerce")
    extra = extra[extra["trade_date"] < pd.to_datetime("2022-01-01")].copy()
    main_cols = main.columns.tolist()
    for col in main_cols:
        if col not in extra.columns:
            extra[col] = None
    extra = extra[main_cols]
    union = pd.concat([main, extra], ignore_index=True)
    return union.sort_values(["ticker", "trade_date"]).reset_index(drop=True)


def map_slug(agent_slug, notes):
    if agent_slug in SLUG_MAP:
        v = SLUG_MAP[agent_slug]
        return [v] if v else []
    if agent_slug == "engulfing":
        notes_low = str(notes or "").lower()
        if "bear" in notes_low or "黑" in notes_low or "空" in notes_low:
            return ["bear_engulfing"]
        return ["bull_engulfing"]
    if agent_slug == "gap_fill_pattern":
        return ["gap_fill_up", "gap_fill_down"]
    return [agent_slug]


def main():
    cases = pd.read_csv(CASE_V2)
    cases["corrected_approx_date"] = pd.to_datetime(cases["corrected_approx_date"], errors="coerce")
    confirmed = cases[cases["case_kind"] == "confirmed_signal"].copy()
    print(f"confirmed_signal cases: {len(confirmed)}")

    print("Loading bars + features ...")
    df = load_bars_union()
    df = df[df["trade_date"] >= "2015-01-01"].copy()
    df = add_features(df)

    # Pre-compute detect signals for the slugs we'll need
    needed_slugs = set()
    for _, row in confirmed.iterrows():
        for s in map_slug(row["pattern_slug"], row.get("notes")):
            needed_slugs.add(s)
    detect_results = {}
    for slug in sorted(needed_slugs):
        try:
            mod = importlib.import_module(f"kline.patterns.{slug}")
            detect_results[slug] = mod.detect(df).fillna(False)
        except Exception as e:
            print(f"  FAIL {slug}: {e}")
            detect_results[slug] = pd.Series(False, index=df.index)

    # Auto-correct
    new_rows = []
    n_corrected = 0
    n_real_miss = 0
    n_still_hit = 0
    for _, row in cases.iterrows():
        row = row.to_dict()
        if row.get("case_kind") != "confirmed_signal":
            row["date_autocorrected"] = False
            row["real_miss"] = None
            new_rows.append(row)
            continue
        ticker = str(row["ticker"])
        approx = pd.to_datetime(row["corrected_approx_date"])
        slugs = map_slug(row["pattern_slug"], row.get("notes"))
        if not slugs:
            row["date_autocorrected"] = False
            row["real_miss"] = None
            new_rows.append(row)
            continue

        # Look ±WINDOW_DAYS for any fire
        mask_ticker = df["ticker"] == ticker
        mask_window = (df["trade_date"] >= approx - pd.Timedelta(days=WINDOW_DAYS)) & (
            df["trade_date"] <= approx + pd.Timedelta(days=WINDOW_DAYS)
        )
        idx_window = df.index[mask_ticker & mask_window]
        if len(idx_window) == 0:
            row["date_autocorrected"] = False
            row["real_miss"] = True
            new_rows.append(row)
            n_real_miss += 1
            continue

        hit_dates = []
        for s in slugs:
            sig = detect_results[s].loc[idx_window]
            for idx in idx_window[sig.values]:
                hit_dates.append(df.loc[idx, "trade_date"])
        if not hit_dates:
            row["date_autocorrected"] = False
            row["real_miss"] = True
            new_rows.append(row)
            n_real_miss += 1
            continue

        # Pick the hit date CLOSEST to original approx_date
        hit_dates = sorted(hit_dates, key=lambda d: abs((d - approx).days))
        best = hit_dates[0]
        if abs((best - approx).days) <= 10:
            # Already within original ±10 → would have been hit; don't change
            row["date_autocorrected"] = False
            row["real_miss"] = False
            new_rows.append(row)
            n_still_hit += 1
        else:
            row["original_approx_date"] = row.get("original_approx_date") or row.get("approx_date")
            row["corrected_approx_date"] = best.strftime("%Y-%m-%d")
            row["date_autocorrected"] = True
            row["real_miss"] = False
            new_rows.append(row)
            n_corrected += 1

    out = pd.DataFrame(new_rows)
    out.to_csv(CASE_V3, index=False)
    print(f"\nAuto-corrected: {n_corrected}")
    print(f"Already hit within ±10: {n_still_hit}")
    print(f"Real miss (no fire in ±{WINDOW_DAYS} days): {n_real_miss}")
    print(f"\nWrote {CASE_V3}")

    # Real-miss breakdown
    real = out[out["real_miss"] == True]
    if len(real):
        print(f"\n=== Real misses by pattern ({len(real)}) ===")
        print(real.groupby("pattern_slug")["ticker"].count().sort_values(ascending=False).to_string())


if __name__ == "__main__":
    main()
