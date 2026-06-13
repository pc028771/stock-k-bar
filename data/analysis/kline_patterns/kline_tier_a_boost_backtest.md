# K 線力量 Tier-A 升等訊號 — Boost EV Backtest

- Universe: teacher 332 (330 processed)
- Period: 2024-01-01 → 2026-05-31
- Scanner proxy: shakeout_strong OR w_bottom_launch (daily_scanner_job main bull layer)
- K 線 tier-A: attack_cost_displayed / morning_star_island_reversal / morning_star_harami
- Forward returns: close[d+N] / close[d+0] - 1

## 主表（boosted vs control vs kline_only vs baseline）

| group | n | mean_5d | median_5d | wr_5d | cap10_5d | mean_20d | wr_20d |
|---|---|---|---|---|---|---|---|
| A:  boosted K1+K2+K3 (current) | 309 | +2.63% | +0.48% | 53.07% | 21.68% | +8.44% | 55.52% |
| A': boosted K1+K2 only (drop K3) | 215 | +4.20% | +1.74% | 57.67% | 28.84% | +12.39% | 63.45% |
| B:  control vs A (scanner only, no K123) | 43,625 | +1.09% | +0.00% | 49.26% | 11.26% | +4.53% | 51.65% |
| B': control vs A' (scanner only, no K12) | 43,719 | +1.09% | +0.00% | 49.25% | 11.24% | +4.52% | 51.63% |
| C:  kline_only (K1+K2+K3, no scanner) | 2,282 | +1.12% | +0.78% | 55.21% | 10.21% | +5.49% | 59.30% |
| D:  baseline (all rows) | 189,742 | +1.10% | +0.26% | 51.12% | 9.89% | +4.49% | 54.39% |
|   A1: shakeout × K1+K2+K3 | 35 | +0.96% | +0.00% | 45.71% | 17.14% | +15.68% | 62.86% |
|   B1: shakeout × no_kline | 366 | +0.36% | -0.70% | 45.90% | 17.21% | +9.91% | 59.65% |
|   A2: w_bottom × K1+K2+K3 | 290 | +2.76% | +0.61% | 53.45% | 22.41% | +8.42% | 55.72% |
|   B2: w_bottom × no_kline | 43,430 | +1.09% | +0.00% | 49.27% | 11.22% | +4.51% | 51.63% |
| K1: attack_cost_displayed (raw) | 639 | +3.99% | +2.34% | 58.06% | 26.45% | +11.23% | 60.59% |
| K2: morning_star_island_reversal (raw) | 599 | +2.39% | +1.88% | 62.10% | 10.02% | +9.00% | 75.79% |
| K3: morning_star_harami (raw) | 1,360 | -0.43% | +0.17% | 50.37% | 5.29% | +1.97% | 50.67% |
| K3a: msh + vol_ratio_20 ≥ 1.5 | 50 | +0.68% | +1.30% | 60.00% | 6.00% | -0.84% | 42.86% |
| K3b: msh + ma5 ≥ ma10 | 41 | +1.80% | +1.08% | 58.54% | 12.20% | +1.64% | 50.00% |
| K3c: msh + vol + ma_align | 1 | +28.91% | +28.91% | 100.00% | 100.00% | -2.05% | 0.00% |
|   A3a: scanner × K3a (msh+vol) | 0 | — | — | — | — | — | — |
|   A3b: scanner × K3b (msh+ma) | 5 | -1.41% | -3.57% | 20.00% | 20.00% | -7.07% | 25.00% |
|   A3c: scanner × K3c (msh+vol+ma) | 0 | — | — | — | — | — | — |

## 升等是否有效？

- **A  (current K1+K2+K3) n=309**, mean_5d=+2.63%, mean_20d=+8.44%, wr_5d=53.1%
- **A' (K1+K2 only)       n=215**, mean_5d=+4.20%, mean_20d=+12.39%, wr_5d=57.7%
- **B  (control vs A)     n=43625**, mean_5d=+1.09%, mean_20d=+4.53%, wr_5d=49.3%
- **B' (control vs A')    n=43719**, mean_5d=+1.09%, mean_20d=+4.52%, wr_5d=49.2%

- A  vs B  : 5d delta=**+1.54pp**, 20d delta=**+3.91pp**, wr_5d delta=**+3.8pp**
- A' vs B' : 5d delta=**+3.11pp**, 20d delta=**+7.87pp**, wr_5d delta=**+8.4pp**

## 判讀

- A' > A → 移除 K3 對升等有效性正面、production 用 K1+K2
- A' ≈ A → K3 可留作 ✨ badge-only、不升 tier
- A' < A → K3 仍貢獻 (反直覺、可能與其他訊號互補)