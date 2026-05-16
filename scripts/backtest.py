"""End-to-end backtest entry point.

Loads bars, computes features, runs entry detection, simulates exits,
writes trades CSV.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from kline.bars import DEFAULT_DB_PATH, load_bars
from kline.exit.simulator import simulate
from kline.features import add_features

DEFAULT_OUT = Path("data/analysis/kline/backtest_trades.csv")


def run(
    db_path: Path = DEFAULT_DB_PATH,
    out_path: Path = DEFAULT_OUT,
    entry_name: str = "tweezer_top_breakout",
) -> pd.DataFrame:
    """Run the full backtest pipeline. Returns the trades DataFrame.

    Args:
        entry_name: Which entry signal to use (default: tweezer_top_breakout).
                    Options: "tweezer_top_breakout" (best single strategy per analysis),
                            "pattern_breakout_only" (course strict, starting points only),
                            "breakout_attack" (course basic, admits continuations).
    """
    from kline.entry import ENTRY_REGISTRY

    out_path.parent.mkdir(parents=True, exist_ok=True)

    bars = load_bars(db_path=db_path)
    feats = add_features(bars)
    # Required exit columns that the simulator will pull from df:
    # prev_low, prev_close, prior_low_20, ma60_slope_5d, market_open_ret.
    # All except market_open_ret are added by features. For tests/MVP, we fill 0.
    feats["market_open_ret"] = 0.0

    entry_fn = ENTRY_REGISTRY.get(entry_name)
    if entry_fn is None:
        raise ValueError(
            f"Unknown entry signal: {entry_name}. "
            f"Available: {list(ENTRY_REGISTRY.keys())}"
        )
    entries = entry_fn(feats)
    trades = simulate(feats, entries, entry_name=entry_name)
    trades.to_csv(out_path, index=False)
    return trades


def main():
    from kline.entry import ENTRY_REGISTRY

    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--entry",
        default="tweezer_top_breakout",
        choices=list(ENTRY_REGISTRY.keys()),
        help="Entry signal to use",
    )
    args = parser.parse_args()
    trades = run(db_path=args.db, out_path=args.out, entry_name=args.entry)
    print(f"Wrote {len(trades)} trades → {args.out}")


if __name__ == "__main__":
    main()
