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
