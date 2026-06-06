"""End-to-end backtest entry point.

Loads bars, computes features, runs entry detection, simulates exits,
writes trades CSV.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from kline.bars import DEFAULT_DB_PATH
from kline.exit.simulator import simulate
from kline.extras import resolve_extras
from kline.features import load_features_cached

DEFAULT_OUT_DIR = Path("data/analysis/kline")
DEFAULT_OUT = DEFAULT_OUT_DIR / "backtest_trades.csv"


def _slugify_extras(extras: dict) -> str:
    parts = []
    for name, fn in extras["entry_filters"] + extras["exits"] + extras["scoring"]:
        short = name.removeprefix("extras.")
        # Append arg if the callable carries a parameter we can show.
        for attr in ("threshold", "cap_days"):
            if hasattr(fn, attr):
                short = f"{short}{getattr(fn, attr)}"
                break
        parts.append(short)
    return "+".join(parts)


def run(
    db_path: Path = DEFAULT_DB_PATH,
    out_path: Path | None = None,
    entry_name: str = "tweezer_top_breakout",
    extras_spec: str | None = None,
) -> pd.DataFrame:
    """Run the full backtest pipeline. Returns the trades DataFrame.

    Args:
        entry_name: Course entry signal (see kline.entry.ENTRY_REGISTRY).
        extras_spec: Optional non-course toggles, e.g.
                     "intensity_floor=2,hold_days_cap=20". See
                     kline/extras/README.md.
    """
    from kline.entry import ENTRY_REGISTRY

    extras = resolve_extras(extras_spec)

    if out_path is None:
        if extras_spec:
            slug = _slugify_extras(extras)
            out_path = DEFAULT_OUT_DIR / f"backtest_trades__{entry_name}__{slug}.csv"
        else:
            out_path = DEFAULT_OUT
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Cached: skips load_bars+add_features on warm runs (~25s saved).
    # Cache key invalidates on DB mtime change or any scripts/kline/*.py edit.
    feats = load_features_cached(db_path=db_path).copy()
    feats["market_open_ret"] = 0.0

    entry_fn = ENTRY_REGISTRY.get(entry_name)
    if entry_fn is None:
        raise ValueError(
            f"Unknown entry signal: {entry_name}. "
            f"Available: {list(ENTRY_REGISTRY.keys())}"
        )
    entries = entry_fn(feats)

    # Apply course-external entry filters AFTER course entry detection.
    for _name, filter_fn in extras["entry_filters"]:
        entries = filter_fn(feats, entries)

    trades = simulate(
        feats,
        entries,
        entry_name=entry_name,
        extra_exits=extras["exits"] or None,
    )
    trades["extras_used"] = ",".join(
        n for n, _ in extras["entry_filters"] + extras["exits"]
    ) or ""
    trades.to_csv(out_path, index=False)
    return trades


def main():
    from kline.entry import ENTRY_REGISTRY

    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out", type=Path, default=None,
                        help="Output CSV path. Auto-derived if omitted.")
    parser.add_argument(
        "--entry",
        default="tweezer_top_breakout",
        choices=list(ENTRY_REGISTRY.keys()),
        help="Course entry signal to use",
    )
    parser.add_argument(
        "--extras",
        default=None,
        help="Comma-separated non-course toggles, e.g. "
             "'intensity_floor=2,hold_days_cap=20'. See kline/extras/README.md.",
    )
    args = parser.parse_args()
    trades = run(
        db_path=args.db,
        out_path=args.out,
        entry_name=args.entry,
        extras_spec=args.extras,
    )
    label = f" with extras [{args.extras}]" if args.extras else ""
    print(f"Wrote {len(trades)} trades{label}")


if __name__ == "__main__":
    main()
