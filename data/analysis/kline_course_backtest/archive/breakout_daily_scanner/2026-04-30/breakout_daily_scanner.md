# Breakout Daily Scanner

資料庫：`/Users/howard/.four_seasons/data.sqlite`

回放日期：2026-04-30

樣本：2025-04-25 至 2026-04-30

最新交易日：2026-04-30

分K覆蓋率：0.00%（近 20 交易日每日期最多補 15 檔分K）

排除清單筆數（DB）：305
FinMind 上市/上櫃清單筆數：2718
FinMind 營建類股排除筆數：90
硬過濾 profile：`balanced`

## 排序邏輯

- 基礎分數：可交易 breakout 候選（排除注意/處置、低量、低價）
- 加分：`range regime`、`breakout_next_not_low_open`、`close_pos` 高、`volume_ratio` 高、突破幅度高
- 分K加權：`intraday_strong_attack` 加分；`below_open_after_1130` 和 `intraday_attack_failure` 扣分

## Top-N 歷史命中摘要

| bucket | n | mean_10d_net_pct | win_rate_10d_pct | mean_20d_net_pct | win_rate_20d_pct |
| --- | --- | --- | --- | --- | --- |
| all | 1709 | 1.595 | 45.11 | 5.444 | 50.44 |
| top5 | 895 | 2.185 | 46.48 | 6.507 | 50.73 |
| top10 | 1364 | 1.789 | 45.23 | 5.397 | 49.78 |
| top20 | 1678 | 1.531 | 45.17 | 5.448 | 50.48 |

## 最新交易日候選

| rank_in_date | ticker | scanner_score | market_regime | breakout_next_not_low_open | intraday_strong_attack | below_open_after_1130 | close_pos | volume_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 6207 | 85.0 | bull | True |  |  | 0.983050847457628 | 5.878570364281044 |
| 2 | 2417 | 85.0 | bull | True |  |  | 1.0 | 9.644025632076813 |
| 3 | 4576 | 85.0 | bull | True |  |  | 1.0 | 2.4269670457776784 |

## 近 20 交易日候選

| trade_date | rank_in_date | ticker | scanner_score | market_regime | breakout_next_not_low_open | intraday_strong_attack | below_open_after_1130 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-04-30 | 1 | 6207 | 85.0 | bull | True |  |  |
| 2026-04-30 | 2 | 2417 | 85.0 | bull | True |  |  |
| 2026-04-30 | 3 | 4576 | 85.0 | bull | True |  |  |
| 2026-04-28 | 1 | 2464 | 85.0 | bull | True |  |  |
| 2026-04-28 | 2 | 6405 | 85.0 | bull | True |  |  |
| 2026-04-28 | 3 | 4958 | 75.0 | bull | False |  |  |
| 2026-04-28 | 4 | 3605 | 75.0 | bull | False |  |  |
| 2026-04-28 | 5 | 8103 | 75.0 | bull | False |  |  |
| 2026-04-28 | 6 | 2243 | 75.0 | bull | False |  |  |
| 2026-04-27 | 1 | 3374 | 85.0 | bull | True |  |  |
| 2026-04-27 | 2 | 8103 | 85.0 | bull | True |  |  |
| 2026-04-27 | 3 | 5483 | 79.0 | bull | True |  |  |
| 2026-04-27 | 4 | 4927 | 75.0 | bull | False |  |  |
| 2026-04-27 | 5 | 6435 | 69.0 | bull | False |  |  |
| 2026-04-24 | 1 | 3189 | 85.0 | bull | True |  |  |
| 2026-04-24 | 2 | 2454 | 85.0 | bull | True |  |  |
| 2026-04-24 | 3 | 6789 | 85.0 | bull | True |  |  |
| 2026-04-24 | 4 | 2855 | 85.0 | bull | True |  |  |
| 2026-04-24 | 5 | 3209 | 85.0 | bull | True |  |  |
| 2026-04-24 | 6 | 3390 | 85.0 | bull | True |  |  |

輸出檔：

- `data/analysis/kline_course_backtest/breakout_daily_scanner.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_recent20d.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_topn_summary.csv`
- `data/analysis/kline_course_backtest/archive/breakout_daily_scanner/YYYY-MM-DD/*`
