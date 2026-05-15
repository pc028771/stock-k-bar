"""Daily scanner entry point.

Loads bars, computes features, runs entry detection, scores candidates,
writes ranked CSV.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from kline.bars import DEFAULT_DB_PATH, load_bars
from kline.entry import breakout_attack
from kline.features import add_features
from kline.scoring import SCORING_REGISTRY

DEFAULT_OUT = Path("data/analysis/kline/scanner_today.csv")


def run(
    db_path: Path = DEFAULT_DB_PATH,
    out_path: Path = DEFAULT_OUT,
    as_of: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Run the scanner. Returns ranked candidates DataFrame."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    bars = load_bars(db_path=db_path)
    feats = add_features(bars)

    # Scoring factors need features not in add_features:
    if "pre_breakout_trend_days" not in feats.columns:
        above = (feats["close"] > feats["ma60"]).fillna(False).astype(int)
        # Shift(1) excludes today; rolling 20-day sum counts prior trend days.
        # Uses the same groupby+shift pattern as features.py (pandas 3.x safe).
        feats["pre_breakout_trend_days"] = (
            above.groupby(feats["ticker"])
            .shift(1)
            .fillna(0)
            .groupby(feats["ticker"])
            .rolling(20, min_periods=1)
            .sum()
            .reset_index(level=0, drop=True)
            .astype(int)
        )

    if "overhead_supply_layer" not in feats.columns:
        feats["overhead_supply_layer"] = 0.0  # placeholder; precise version pending VP

    entries = breakout_attack(feats)
    candidates = feats[entries].copy()

    if as_of is not None:
        candidates = candidates[candidates["trade_date"] == as_of]

    # Sum all scoring factors.
    total = pd.Series(0.0, index=candidates.index)
    for name, fn in SCORING_REGISTRY.items():
        contribution = fn(candidates)
        candidates[f"score_{name}"] = contribution
        total += contribution
    candidates["scanner_score"] = total.clip(0, 200)

    candidates = candidates.sort_values("scanner_score", ascending=False)
    candidates.to_csv(out_path, index=False)
    return candidates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--as-of", type=str, default=None, help="YYYY-MM-DD")
    args = parser.parse_args()
    as_of = pd.Timestamp(args.as_of) if args.as_of else None
    df = run(db_path=args.db, out_path=args.out, as_of=as_of)
    print(f"Wrote {len(df)} candidates → {args.out}")


if __name__ == "__main__":
    main()
