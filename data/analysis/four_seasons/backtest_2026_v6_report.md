# Four-Seasons Backtest v6 — 2026-06-08 校正方法論 + K 線 Tier-A cross

- Total trades: 245 (closed: 226, censored: 19)
- Entry-day range: 2025-12-26 → 2026-05-13
- 套用方法論: feedback_scanner_evaluation_correction_20260608 (雙維度 WR + cap10 + segment audit) + small_sample_preference
- K 線 tier-A: attack_cost_displayed (K1) + morning_star_island_reversal (K2)

## 1. 各季節主表 (closed only)

| 季節 | n | WR | mean ret | median ret | **cap10** | **cap20** | median_dd | worst_dd | median 持倉 |
|---|---|---|---|---|---|---|---|---|---|
| 春 | 27 | 25.9% | -0.66% | -0.47% | 0.0% | 0.0% | -0.89% | -10.54% | 1d |
| 立夏 | 125 | 45.6% | +2.28% | -0.90% | 13.6% | 7.2% | -6.83% | -13.64% | 4d |
| 盛夏 | 27 | 33.3% | +4.60% | -0.68% | 18.5% | 7.4% | -7.02% | -17.47% | 5d |
| 秋 | 47 | 48.9% | -0.41% | +0.00% | 2.1% | 0.0% | -5.63% | -16.30% | 1d |

**判讀 (per `feedback_small_sample_preference` 雙維度):**
- cap10 (大魚抓到率) ≥ 20% + WR ≥ 45% = 真 edge
- WR 高但 cap10 低 = 小贏稀釋大魚、四季 trend rider 邏輯失效
- worst_dd < -15% = 中途吃過大套牢、需檢視 trailing-stop 設定

## 2. By 季節 × exit_reason segment

| 季節 / exit | n | WR | mean | median | cap10 | cap20 | median_dd | worst_dd | 持倉 |
|---|---|---|---|---|---|---|---|---|---|
| 立夏 / season_change | 99 | 42.4% | +1.69% | -1.12% | 12.1% | 6.1% | -6.99% | -13.64% | 2d |
| 春 / season_change | 27 | 25.9% | -0.66% | -0.47% | 0.0% | 0.0% | -0.89% | -10.54% | 1d |
| 秋 / season_change | 24 | 95.8% | +4.32% | +3.40% | 4.2% | 0.0% | -6.48% | -16.30% | 2d |
| 秋 / new_high | 23 | 0.0% | -5.34% | -5.22% | 0.0% | 0.0% | -4.85% | -11.98% | 1d |
| 盛夏 / season_change | 18 | 27.8% | -0.13% | -1.52% | 11.1% | 0.0% | -8.08% | -13.67% | 4d |
| 立夏 / trailing_stop | 14 | 92.9% | +12.64% | +9.19% | 35.7% | 21.4% | -4.49% | -8.11% | 8d |
| 立夏 / ma20_break | 12 | 16.7% | -4.96% | -6.25% | 0.0% | 0.0% | -7.30% | -10.03% | 9d |
| 盛夏 / trailing_stop | 7 | 57.1% | +20.67% | +9.19% | 42.9% | 28.6% | -5.91% | -7.79% | 7d |
| 盛夏 / ma20_break | 2 | 0.0% | -9.03% | -9.03% | 0.0% | 0.0% | -11.80% | -17.47% | 10d |

## 3. K 線 Tier-A 升等 cross (long only) — 新增、本 v6 重點

| group | n | WR | mean | median | cap10 | cap20 | median_dd | worst_dd | 持倉 |
|---|---|---|---|---|---|---|---|---|---|
| A: long + K1/K2 (boosted) | 8 | 75.0% | +6.47% | +8.23% | 12.5% | 0.0% | -7.21% | -9.06% | 1d |
| B: long, no K1/K2 (control) | 171 | 39.2% | +1.99% | -0.76% | 12.3% | 6.4% | -5.93% | -17.47% | 3d |
|   A1: long + K1 attack_cost | 8 | 75.0% | +6.47% | +8.23% | 12.5% | 0.0% | -7.21% | -9.06% | 1d |
|   A2: long + K2 morning_star_island | 0 | — | — | — | — | — | — | — | — |

**A vs B 升等效果:**
- mean delta: **+4.48pp**
- WR delta: **+35.8pp**
- cap10 delta: **+0.2pp**
- A 樣本: n=8 (偏小 < 30、需更多資料)

### 3.1 K 線 cross × 季節

| group | n | WR | mean | median | cap10 | cap20 | median_dd | worst_dd | 持倉 |
|---|---|---|---|---|---|---|---|---|---|
| 春: boosted (K1/K2) | 0 | — | — | — | — | — | — | — | — |
| 春: control | 27 | 25.9% | -0.66% | -0.47% | 0.0% | 0.0% | -0.89% | -10.54% | 1d |
| 立夏: boosted (K1/K2) | 5 | 60.0% | +3.63% | +4.69% | 0.0% | 0.0% | -6.64% | -9.06% | 1d |
| 立夏: control | 120 | 45.0% | +2.22% | -0.99% | 14.2% | 7.5% | -6.88% | -13.64% | 4d |
| 盛夏: boosted (K1/K2) | 3 | 100.0% | +11.20% | +9.80% | 33.3% | 0.0% | -7.79% | -9.05% | 2d |
| 盛夏: control | 24 | 25.0% | +3.78% | -1.52% | 16.7% | 8.3% | -6.79% | -17.47% | 5d |

## 4. Per-ticker quadrant — Q1 真 edge (WR ≥ 50% AND cap10 ≥ 20%, n ≥ 2)

| ticker | name | n | WR | cap10 | mean ret |
|---|---|---|---|---|---|
| 6829 | 千附精密 | 2 | 50% | 50% | +40.50% |
| 2426 | 鼎元 | 2 | 100% | 100% | +28.27% |
| 1526 | 日馳 | 2 | 100% | 100% | +20.27% |
| 3437 | 榮創 | 2 | 50% | 50% | +20.11% |
| 6167 | 久正 | 2 | 100% | 100% | +18.67% |
| 8096 | 擎亞 | 2 | 100% | 50% | +14.61% |
| 8110 | 華東 | 2 | 100% | 50% | +9.87% |
| 4561 | 健椿 | 3 | 67% | 33% | +9.43% |
| 9950 | 萬國通 | 2 | 100% | 50% | +9.03% |
| 1514 | 亞力 | 2 | 50% | 50% | +6.26% |

- Q1 tickers: 10 / 34 (29%)

## 5. 判讀與行動

(待 user 看完上方數字後判讀；本檔不寫死結論、避免 AI 過度詮釋。)

## Files

- Augmented trades: `data/analysis/four_seasons/backtest_2026_v6_trades_aug.csv`
- This report: `data/analysis/four_seasons/backtest_2026_v6_report.md`
- Source trades (v5 unchanged): `data/analysis/four_seasons/backtest_2025_final_trades.csv`