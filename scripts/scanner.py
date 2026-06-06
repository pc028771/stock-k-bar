"""Daily scanner entry point.

Loads bars, computes features, runs entry detection, scores candidates,
writes ranked CSV.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from kline.bars import DEFAULT_DB_PATH
from kline.extras import resolve_extras
from kline.features import load_features_cached
from kline.scoring import SCORING_REGISTRY

DEFAULT_OUT = Path("data/analysis/kline/scanner_today.csv")


def run(
    db_path: Path = DEFAULT_DB_PATH,
    out_path: Path = DEFAULT_OUT,
    as_of: pd.Timestamp | None = None,
    entry_name: str = "tweezer_top_breakout",
    extras_spec: str | None = None,
) -> pd.DataFrame:
    """Run the scanner. Returns ranked candidates DataFrame.

    Args:
        entry_name: Course entry signal (see kline.entry.ENTRY_REGISTRY).
        extras_spec: Optional non-course toggles. Only entry-filter and
                     scoring extras are honored here (exits are irrelevant
                     for scanner). See kline/extras/README.md.
    """
    from kline.entry import ENTRY_REGISTRY

    out_path.parent.mkdir(parents=True, exist_ok=True)
    extras = resolve_extras(extras_spec)

    # Cached: scanner runs daily and the underlying DB usually changes once/day,
    # so cache wins on every CLI invocation past the first.
    feats = load_features_cached(db_path=db_path).copy()

    entry_fn = ENTRY_REGISTRY.get(entry_name)
    if entry_fn is None:
        raise ValueError(
            f"Unknown entry signal: {entry_name}. "
            f"Available: {list(ENTRY_REGISTRY.keys())}"
        )
    entries = entry_fn(feats)

    for _name, filter_fn in extras["entry_filters"]:
        entries = filter_fn(feats, entries)

    candidates = feats[entries].copy()

    if as_of is not None:
        candidates = candidates[candidates["trade_date"] == as_of]

    # Course scoring first.
    total = pd.Series(0.0, index=candidates.index)
    for name, fn in SCORING_REGISTRY.items():
        contribution = fn(candidates)
        candidates[f"score_{name}"] = contribution
        total += contribution
    # Then non-course scoring extras (clearly labeled).
    for name, fn in extras["scoring"]:
        contribution = fn(candidates)
        candidates[f"score_{name}"] = contribution
        total += contribution
    candidates["scanner_score"] = total.clip(0, 200)
    candidates["extras_used"] = ",".join(
        n for n, _ in extras["entry_filters"] + extras["scoring"]
    ) or ""

    candidates = candidates.sort_values("scanner_score", ascending=False)
    candidates.to_csv(out_path, index=False)
    return candidates


def main():
    from kline.entry import ENTRY_REGISTRY

    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--as-of", type=str, default=None, help="YYYY-MM-DD")
    parser.add_argument(
        "--entry",
        default="tweezer_top_breakout",
        choices=list(ENTRY_REGISTRY.keys()),
        help="Course entry signal to use",
    )
    parser.add_argument(
        "--extras",
        default=None,
        help="Comma-separated non-course toggles. "
             "See kline/extras/README.md.",
    )
    args = parser.parse_args()
    as_of = pd.Timestamp(args.as_of) if args.as_of else None
    df = run(
        db_path=args.db,
        out_path=args.out,
        as_of=as_of,
        entry_name=args.entry,
        extras_spec=args.extras,
    )
    print(f"Wrote {len(df)} candidates → {args.out}")


if __name__ == "__main__":
    main()
