"""Sweep params for xiaoge_bb_squeeze_breakout — find sensitivity to thresholds."""
from __future__ import annotations

import itertools
import pandas as pd

from scripts.xiaoge.backtest_bb_squeeze import run_backtest


def main():
    rows = []
    grid = list(itertools.product(
        [6, 8, 10, 12, 15],          # squeeze_threshold
        [5, 10, 15],                 # squeeze_lookback
        [1.0, 1.5, 2.0],             # vol_multiple
        ["any", "shenglongquan", "open_breakout"],
    ))
    for st, sl, vm, mode in grid:
        try:
            trades = run_backtest(squeeze_threshold=st, squeeze_lookback=sl,
                                  vol_multiple=vm, breakout_mode=mode)
            if len(trades) == 0:
                rows.append({"sq_thr": st, "sq_lb": sl, "vol_x": vm, "mode": mode,
                             "n": 0, "avg_ret": None, "win_rate": None, "median_ret": None})
                continue
            rows.append({
                "sq_thr": st, "sq_lb": sl, "vol_x": vm, "mode": mode,
                "n": len(trades),
                "avg_ret": round(trades["ret_pct"].mean(), 2),
                "win_rate": round((trades["ret_pct"] > 0).mean() * 100, 1),
                "median_ret": round(trades["ret_pct"].median(), 2),
                "avg_hold": round(trades["hold_days"].mean(), 1),
            })
        except Exception as e:
            print(f"FAILED: {st} {sl} {vm} {mode} → {e}")
    out = pd.DataFrame(rows)
    out.to_csv("data/analysis/xiaoge/backtest/param_sweep.csv", index=False)
    print(out.sort_values("avg_ret", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
