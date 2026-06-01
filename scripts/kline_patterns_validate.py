"""Pattern validation + EV backtest for scripts/kline/patterns/.

Validation phase:
- Load bars + features
- For each pattern, count triggers; check exhaustion-context rate
- Save trigger stats CSV

Backtest phase:
- For each pattern, treat detect()==True as entry on next bar's open
- Hold N=10 trading days; record forward return
- Output EV / win rate / sample size table
"""
from __future__ import annotations

import argparse
import importlib
import pkgutil
from pathlib import Path

import pandas as pd

from kline import patterns as patterns_pkg
from kline.bars import load_bars
from kline.features import add_features
from kline.patterns import _common  # noqa: F401


def discover_patterns() -> dict[str, callable]:
    """Auto-discover patterns/*.py detect() functions."""
    result = {}
    for mod_info in pkgutil.iter_modules(patterns_pkg.__path__):
        name = mod_info.name
        if name.startswith("_"):
            continue
        mod = importlib.import_module(f"kline.patterns.{name}")
        if hasattr(mod, "detect"):
            result[name] = mod.detect
    return result


def validate(df: pd.DataFrame, patterns: dict[str, callable]) -> pd.DataFrame:
    rows = []
    bull_ctx = _common.bull_exhaustion_context(df)
    bear_ctx = _common.bear_exhaustion_context(df)
    n_total = len(df)
    rows.append({"name": "_bull_exhaustion_context", "triggers": int(bull_ctx.sum()),
                 "rate_pct": round(bull_ctx.mean() * 100, 3), "unique_tickers": df.loc[bull_ctx, "ticker"].nunique()})
    rows.append({"name": "_bear_exhaustion_context", "triggers": int(bear_ctx.sum()),
                 "rate_pct": round(bear_ctx.mean() * 100, 3), "unique_tickers": df.loc[bear_ctx, "ticker"].nunique()})
    for name, fn in sorted(patterns.items()):
        sig = fn(df).fillna(False)
        rows.append({
            "name": name,
            "triggers": int(sig.sum()),
            "rate_pct": round(sig.mean() * 100, 3),
            "unique_tickers": df.loc[sig, "ticker"].nunique(),
        })
    print(f"Total bars: {n_total:,}")
    return pd.DataFrame(rows).sort_values("triggers", ascending=False)


def backtest_one(df: pd.DataFrame, sig: pd.Series, hold_days: int) -> dict:
    """For each True in sig, compute forward return (next-bar open → close after N days)."""
    g = df.groupby("ticker", group_keys=False)
    next_open = g["open"].shift(-1)
    fwd_close = g["close"].shift(-hold_days)
    sig = sig.fillna(False)
    rets = ((fwd_close - next_open) / next_open)[sig]
    rets = rets.dropna()
    if len(rets) == 0:
        return {"n": 0, "mean_ret_pct": None, "win_rate_pct": None, "median_pct": None}
    return {
        "n": int(len(rets)),
        "mean_ret_pct": round(rets.mean() * 100, 3),
        "median_pct": round(rets.median() * 100, 3),
        "win_rate_pct": round((rets > 0).mean() * 100, 2),
        "p25_pct": round(rets.quantile(0.25) * 100, 3),
        "p75_pct": round(rets.quantile(0.75) * 100, 3),
    }


def backtest(df: pd.DataFrame, patterns: dict[str, callable], hold_days: int) -> pd.DataFrame:
    rows = []
    for name, fn in sorted(patterns.items()):
        sig = fn(df)
        stats = backtest_one(df, sig, hold_days)
        stats["name"] = name
        rows.append(stats)
    return pd.DataFrame(rows)[["name", "n", "mean_ret_pct", "median_pct", "win_rate_pct", "p25_pct", "p75_pct"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold-days", type=int, default=10)
    ap.add_argument("--out-dir", default="data/analysis/kline_patterns")
    ap.add_argument("--start", default="2021-01-01")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading bars...")
    df = load_bars()
    df = df[df["trade_date"] >= args.start].copy()
    print(f"After date filter ({args.start}+): {len(df):,} bars, {df['ticker'].nunique():,} tickers")

    print("Adding features...")
    df = add_features(df)

    patterns = discover_patterns()
    print(f"Discovered {len(patterns)} patterns")

    print("\n=== Validation (trigger counts) ===")
    val = validate(df, patterns)
    val_path = out_dir / "trigger_stats.csv"
    val.to_csv(val_path, index=False)
    print(val.to_string(index=False))
    print(f"\n→ {val_path}")

    # NOTE: N-day forward return EV intentionally NOT computed here.
    # Memory rule (feedback_backtest_methodology): use course-defined exit
    # conditions via exit/simulator, not ret_Nd. Proper backtest is a
    # follow-up step requiring patterns to be wired through simulator.
    print(f"\nSkipping N-day EV (forbidden by feedback_backtest_methodology).")
    print(f"Next step: wire patterns into exit/simulator for course-correct backtest.")


if __name__ == "__main__":
    main()
