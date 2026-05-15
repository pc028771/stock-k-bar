"""End-to-end backtest entry point.

Loads bars, computes features, runs entry detection, simulates exits,
writes trades CSV.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from kline.bars import DEFAULT_DB_PATH, load_bars
from kline.entry import breakout_attack
from kline.exit.simulator import simulate
from kline.features import add_features

DEFAULT_OUT = Path("data/analysis/kline/backtest_trades.csv")


def run(
    db_path: Path = DEFAULT_DB_PATH,
    out_path: Path = DEFAULT_OUT,
) -> pd.DataFrame:
    """Run the full backtest pipeline. Returns the trades DataFrame."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    bars = load_bars(db_path=db_path)
    feats = add_features(bars)
    # Required exit columns that the simulator will pull from df:
    # prev_low, prev_close, prior_low_20, ma60_slope_5d, market_open_ret.
    # All except market_open_ret are added by features. For tests/MVP, we fill 0.
    feats["market_open_ret"] = 0.0

    entries = breakout_attack(feats)
    trades = simulate(feats, entries)
    trades.to_csv(out_path, index=False)
    return trades


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    trades = run(db_path=args.db, out_path=args.out)
    print(f"Wrote {len(trades)} trades → {args.out}")


if __name__ == "__main__":
    main()
