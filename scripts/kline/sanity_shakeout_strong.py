"""Sanity check: extras.shakeout_strong.detect() vs master breakout.csv ground truth.

從 /tmp/shakeout_borrow/breakout.csv 抽取 shakeout_strong=True 且 ret_20d_net > 0.20
的 cases 作為基準，驗證 detect() 能正確命中 ≥ 80% 的 spot-check 樣本。

Usage:
    python scripts/kline/sanity_shakeout_strong.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# 確保 extras 可被匯入（從 kline/ 根目錄往上找 scripts/kline）
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from extras.shakeout_strong import detect  # noqa: E402

BREAKOUT_CSV = Path("/tmp/shakeout_borrow/breakout.csv")
SPOT_CHECK_N = 5
MIN_ACCURACY = 0.80


def main() -> int:
    if not BREAKOUT_CSV.exists():
        print(f"[ERROR] {BREAKOUT_CSV} not found — copy master breakout.csv first.")
        return 1

    df = pd.read_csv(BREAKOUT_CSV)
    print(f"Loaded {len(df)} rows from {BREAKOUT_CSV}")

    # Ground-truth positives
    gt_positive = df["shakeout_strong"].fillna(False).astype(bool)
    n_total_positive = gt_positive.sum()
    print(f"Ground-truth shakeout_strong=True: {n_total_positive}")

    # Spot-check pool: shakeout_strong=True AND ret_20d_net > 20%
    pool = df[gt_positive & (df["ret_20d_net"].fillna(0) > 0.20)].copy()
    print(f"Spot-check pool (shakeout_strong=True, ret_20d_net>20%): {len(pool)}")

    if len(pool) < SPOT_CHECK_N:
        sample = pool
        print(f"[WARN] Pool smaller than {SPOT_CHECK_N}, using all {len(pool)} rows.")
    else:
        sample = pool.sample(n=SPOT_CHECK_N, random_state=42)

    print(f"\nSpot-check sample ({len(sample)} rows):")
    print(sample[["ticker", "trade_date", "breakout_vol_capped", "breakout_next_low_open",
                   "breakout_strength_pct", "overhead_supply_layer", "volume_ratio",
                   "ret_20d_net"]].to_string(index=False))

    # Run detect() on the full df, then check sample rows
    predicted = detect(df)
    sample_predicted = predicted.loc[sample.index]

    hits = int(sample_predicted.sum())
    n = len(sample)
    accuracy = hits / n if n > 0 else 0.0

    print(f"\ndetect() results on sample:")
    for idx in sample.index:
        tick = df.loc[idx, "ticker"]
        date = df.loc[idx, "trade_date"]
        gt = "✓" if gt_positive.loc[idx] else "✗"
        pred = "✓" if predicted.loc[idx] else "✗"
        print(f"  idx={idx:4d}  {tick}  {date}  GT={gt}  detect={pred}")

    print(f"\nSpot-check accuracy: {hits}/{n} = {accuracy:.1%}")
    passed = accuracy >= MIN_ACCURACY

    # Full-set consistency check
    full_hits = int((predicted & gt_positive).sum())
    full_miss = int((~predicted & gt_positive).sum())
    false_pos = int((predicted & ~gt_positive).sum())
    print(f"\nFull-set consistency (n={len(df)}):")
    print(f"  True  positive (predict=T, GT=T): {full_hits}")
    print(f"  False negative (predict=F, GT=T): {full_miss}")
    print(f"  False positive (predict=T, GT=F): {false_pos}")
    full_recall = full_hits / n_total_positive if n_total_positive > 0 else 0.0
    print(f"  Full-set recall: {full_recall:.1%}")

    if passed:
        print(f"\n[PASS] Spot-check accuracy {accuracy:.1%} >= {MIN_ACCURACY:.0%}")
    else:
        print(f"\n[FAIL] Spot-check accuracy {accuracy:.1%} < {MIN_ACCURACY:.0%}")

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
