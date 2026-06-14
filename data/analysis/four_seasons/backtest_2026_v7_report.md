# Four-Seasons Backtest v7 — 真實操作版 (Portfolio Simulation)

- 起始水位: **$3,200,000** (per memory `user_capital_size`)
- 倉位數: **4** 倉 × $800,000/倉 (跟主力大 C6-4 對齊、per `feedback_exit_rules_v3`)
- 進場/出場價: 取 v5 trades CSV (course-defined exit、per `feedback_backtest_methodology`)
- 倉位滿時新訊號 → SKIP (不擠掉舊倉、模擬「不是每個訊號都能執行」)
- 持倉中按出場價 mark-to-market (censored 同 v5)
- 期間: 2025-12-26 → 2026-05-14

## 1. 各 sub-strategy 真實水位 (照時間排程 + 4 倉 slot)

| Strategy | 執行筆 | 略過 | 累計 P&L | 最終水位 | 累計報酬 | max DD | WR | cap10 | cap20 | median 持倉 |
|---|---|---|---|---|---|---|---|---|---|---|
| LONG all (春+立夏+盛夏) | 70 | 109 | $2,017,902 | $5,217,902 | +63.06% | -6.48% | 44.3% | 17.1% | 10.0% | 3d |
|   └ 春 only | 6 | 21 | $8,155 | $3,208,155 | +0.25% | -0.27% | 66.7% | 0.0% | 0.0% | 1d |
|   └ 立夏 only | 70 | 55 | $1,609,045 | $4,809,045 | +50.28% | -6.17% | 47.1% | 14.3% | 8.6% | 3d |
|     └ 立夏 trailing exit only | 14 | 0 | $1,415,961 | $4,615,961 | +44.25% | -0.18% | 92.9% | 35.7% | 21.4% | 8d |
|   └ 盛夏 only | 22 | 5 | $859,107 | $4,059,107 | +26.85% | -5.44% | 31.8% | 18.2% | 9.1% | 6d |
|   └ K 線 boosted only (K1/K2) | 8 | 0 | $413,855 | $3,613,855 | +12.93% | -0.90% | 75.0% | 12.5% | 0.0% | 1d |
| SHORT 秋 only | 47 | 0 | -$152,855 | $3,047,145 | -4.78% | -10.27% | 48.9% | 2.1% | 0.0% | 1d |

## 2. LONG all — Top 5 Winners (by P&L $)

| ticker | name | season | entry | exit | shares | days | P&L % | P&L $ | exit_reason |
|---|---|---|---|---|---|---|---|---|---|
| 6829 | 千附精密 | 盛夏 | 126.50 | 235.50 | 6324 | 14 | +86.17% | $689,316 | trailing_stop |
| 2616 | 山隆 | 立夏 | 14.95 | 21.55 | 53511 | 8 | +44.15% | $353,173 | trailing_stop |
| 2426 | 鼎元 | 盛夏 | 25.55 | 34.70 | 31311 | 9 | +35.81% | $286,496 | trailing_stop |
| 1526 | 日馳 | 立夏 | 18.70 | 23.55 | 42780 | 5 | +25.94% | $207,483 | season_change |
| 1785 | 光洋科 | 立夏 | 74.00 | 90.80 | 10810 | 13 | +22.70% | $181,608 | trailing_stop |

## 3. LONG all — Top 5 Losers (by P&L $)

| ticker | name | season | entry | exit | shares | days | P&L % | P&L $ | exit_reason |
|---|---|---|---|---|---|---|---|---|---|
| 8908 | 欣雄 | 盛夏 | 48.95 | 41.70 | 16343 | 2 | -14.81% | -$118,487 | ma20_break |
| 6129 | 普誠 | 盛夏 | 16.95 | 15.50 | 47197 | 5 | -8.55% | -$68,436 | season_change |
| 1467 | 南緯 | 盛夏 | 8.00 | 7.36 | 100000 | 4 | -8.00% | -$64,000 | season_change |
| 2379 | 瑞昱 | 立夏 | 576.00 | 532.00 | 1388 | 1 | -7.64% | -$61,072 | season_change |
| 8176 | 智捷 | 盛夏 | 13.90 | 12.90 | 57553 | 1 | -7.19% | -$57,553 | season_change |

## 4. K 線 Tier-A 升等 — 真實 P&L 對比 (long only)

| group | n_exec | n_skip | 累計 P&L | 最終水位 | 累計報酬 | WR | cap10 | cap20 |
|---|---|---|---|---|---|---|---|---|
| A: long + K1/K2 boosted | 8 | 0 | $413,855 | $3,613,855 | +12.93% | 75.0% | 12.5% | 0.0% |
| B: long, no K1/K2 | 67 | 104 | $1,686,554 | $4,886,554 | +52.70% | 41.8% | 16.4% | 9.0% |

## 5. 判讀重點 (per `feedback_small_sample_preference`)

- 看「累計報酬 vs max DD」、不只看 WR
- 「執行筆/略過筆」反映 slot 限制下這個策略多常有訊號
- 樣本少 + 累計報酬正 + max DD 控制好 = 穩定可投入
- 樣本大但累計報酬接近 0 = 稀釋、不該耗注意力
- (本檔留 user 判讀、AI 不寫死結論)

## Files

- This report: `data/analysis/four_seasons/backtest_2026_v7_report.md`
- Main exec trades: `data/analysis/four_seasons/backtest_2026_v7_executed.csv`
- Main skipped trades: `data/analysis/four_seasons/backtest_2026_v7_skipped.csv`
- Source v5 trades: `data/analysis/four_seasons/backtest_2025_final_trades.csv`