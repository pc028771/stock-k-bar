"""2026 forward sanity test for patterns.

Runs detect() on 2026 bars only and produces:
- Trigger counts vs 2024+ baseline
- Sample 5 hit cases per pattern (ticker + date + OHLCV) for manual review

Memory anchors (known 2026 events that patterns SHOULD identify):
  - 4526 漲停隔日跳空 → high_hanging_man / gap_under_pressure_reversal
  - 8064 東捷 / 8027 鈦昇 — should show exhaustion-context bear patterns
  - 5347, 6182, 3016, 2481 — silicon wafer trio (老師 5/25), recent context
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import pandas as pd

from kline import patterns as patterns_pkg
from kline.bars import load_bars
from kline.features import add_features
from kline.patterns import _common

OUT_DIR = Path("data/analysis/kline_patterns")


def discover_patterns() -> dict[str, callable]:
    result = {}
    for mi in pkgutil.iter_modules(patterns_pkg.__path__):
        if mi.name.startswith("_"):
            continue
        mod = importlib.import_module(f"kline.patterns.{mi.name}")
        if hasattr(mod, "detect"):
            result[mi.name] = mod.detect
    return result


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = load_bars()
    # Need features computed on full history (2024+ for context); restrict to 2026 at end
    df = df[df["trade_date"] >= "2024-01-01"].copy()
    df = add_features(df)
    df_2026 = df[df["trade_date"] >= "2026-01-01"].copy()
    print(f"Total bars 2024+: {len(df):,}; 2026 only: {len(df_2026):,}, "
          f"unique tickers 2026: {df_2026['ticker'].nunique():,}")

    patterns = discover_patterns()
    print(f"Discovered {len(patterns)} patterns")

    # 2026-only signals from full-context detect (so 60d rolling features are valid)
    rows = []
    samples_all = []
    n_2026 = len(df_2026)

    bull_ctx = _common.bull_exhaustion_context(df).loc[df_2026.index]
    bear_ctx = _common.bear_exhaustion_context(df).loc[df_2026.index]
    rows.append({"name": "_bull_exhaustion_context", "triggers_2026": int(bull_ctx.sum()),
                 "rate_pct_2026": round(bull_ctx.mean() * 100, 3),
                 "unique_tickers_2026": df_2026.loc[bull_ctx.values, "ticker"].nunique()})
    rows.append({"name": "_bear_exhaustion_context", "triggers_2026": int(bear_ctx.sum()),
                 "rate_pct_2026": round(bear_ctx.mean() * 100, 3),
                 "unique_tickers_2026": df_2026.loc[bear_ctx.values, "ticker"].nunique()})

    for name, fn in sorted(patterns.items()):
        sig_full = fn(df).fillna(False)
        sig = sig_full.loc[df_2026.index]
        n = int(sig.sum())
        rows.append({
            "name": name,
            "triggers_2026": n,
            "rate_pct_2026": round(sig.mean() * 100, 3),
            "unique_tickers_2026": df_2026.loc[sig.values, "ticker"].nunique(),
        })
        # Sample up to 5 hits for manual review
        hits = df_2026.loc[sig.values, ["ticker", "trade_date", "open", "high", "low", "close", "volume"]].head(5)
        hits["pattern"] = name
        samples_all.append(hits)

    summary = pd.DataFrame(rows).sort_values("triggers_2026", ascending=False)
    summary["expected_rate_pct_2024_25"] = summary["name"].map(_baseline())
    summary["ratio_vs_baseline"] = summary["rate_pct_2026"] / summary["expected_rate_pct_2024_25"].replace(0, float("nan"))

    summary_path = OUT_DIR / "trigger_stats_2026.csv"
    summary.to_csv(summary_path, index=False)
    samples_path = OUT_DIR / "sample_hits_2026.csv"
    pd.concat(samples_all, ignore_index=True).to_csv(samples_path, index=False)

    print("\n=== 2026 Trigger Stats (vs 2024+ baseline rate) ===")
    print(summary[["name", "triggers_2026", "rate_pct_2026", "expected_rate_pct_2024_25", "ratio_vs_baseline"]].to_string(index=False))
    print(f"\n→ {summary_path}")
    print(f"→ {samples_path}")

    # Health check: any pattern whose 2026 rate diverges > 3x or < 0.3x from baseline
    drift = summary[(summary["ratio_vs_baseline"] > 3) | (summary["ratio_vs_baseline"] < 0.3)]
    drift = drift.dropna(subset=["ratio_vs_baseline"])
    if len(drift):
        print(f"\n⚠ Pattern drift (>3x or <0.3x): {len(drift)}")
        print(drift[["name", "rate_pct_2026", "expected_rate_pct_2024_25", "ratio_vs_baseline"]].to_string(index=False))
    else:
        print("\n✓ No significant drift")


def _baseline() -> dict[str, float]:
    """Read 2024+ baseline trigger rates from validate run."""
    p = OUT_DIR / "trigger_stats.csv"
    if not p.exists():
        return {}
    df = pd.read_csv(p)
    return dict(zip(df["name"], df["rate_pct"]))


if __name__ == "__main__":
    main()
