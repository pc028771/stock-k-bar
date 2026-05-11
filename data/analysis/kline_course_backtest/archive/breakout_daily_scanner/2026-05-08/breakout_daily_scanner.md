# Breakout Daily Scanner

資料庫：`/Users/howard/.four_seasons/data.sqlite`

回放日期：2026-05-08

樣本：2025-04-25 至 2026-05-08

最新交易日：2026-05-08

分K覆蓋率：0.00%（近 20 交易日每日期最多補 0 檔分K）

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
| 1 | 3450 | 75.0 | bull | False |  |  | 0.8860759493670886 | 1.7097415496178061 |
| 2 | 6278 | 75.0 | bull | False |  |  | 1.0 | 2.255222192482264 |
| 3 | 3702 | 75.0 | bull | False |  |  | 1.0 | 1.6024524392166664 |
| 4 | 3026 | 75.0 | bull | False |  |  | 1.0 | 2.2875524379091354 |
| 5 | 3034 | 75.0 | bull | False |  |  | 1.0 | 4.424466013121846 |
| 6 | 4722 | 75.0 | bull | False |  |  | 1.0 | 3.4855418870345147 |
| 7 | 2472 | 75.0 | bull | False |  |  | 1.0 | 2.0498364561482103 |
| 8 | 3709 | 75.0 | bull | False |  |  | 1.0 | 1.7981237549621931 |
| 9 | 2379 | 75.0 | bull | False |  |  | 1.0 | 2.434259226046405 |
| 10 | 6695 | 75.0 | bull | False |  |  | 1.0 | 3.4050143745008428 |
| 11 | 8926 | 75.0 | bull | False |  |  | 0.9285714285714278 | 3.8220129866272425 |
| 12 | 6834 | 75.0 | bull | False |  |  | 1.0 | 5.049637927473331 |
| 13 | 6532 | 75.0 | bull | False |  |  | 1.0 | 1.951615182344014 |
| 14 | 6669 | 75.0 | bull | False |  |  | 0.8611111111111112 | 1.5620743819958298 |
| 15 | 4966 | 69.0 | bull | False |  |  | 1.0 | 2.455890867097284 |

## 近 20 交易日候選

| trade_date | rank_in_date | ticker | scanner_score | market_regime | breakout_next_not_low_open | intraday_strong_attack | below_open_after_1130 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-08 | 1 | 3450 | 75.0 | bull | False |  |  |
| 2026-05-08 | 2 | 6278 | 75.0 | bull | False |  |  |
| 2026-05-08 | 3 | 3702 | 75.0 | bull | False |  |  |
| 2026-05-08 | 4 | 3026 | 75.0 | bull | False |  |  |
| 2026-05-08 | 5 | 3034 | 75.0 | bull | False |  |  |
| 2026-05-08 | 6 | 4722 | 75.0 | bull | False |  |  |
| 2026-05-08 | 7 | 2472 | 75.0 | bull | False |  |  |
| 2026-05-08 | 8 | 3709 | 75.0 | bull | False |  |  |
| 2026-05-08 | 9 | 2379 | 75.0 | bull | False |  |  |
| 2026-05-08 | 10 | 6695 | 75.0 | bull | False |  |  |
| 2026-05-08 | 11 | 8926 | 75.0 | bull | False |  |  |
| 2026-05-08 | 12 | 6834 | 75.0 | bull | False |  |  |
| 2026-05-08 | 13 | 6532 | 75.0 | bull | False |  |  |
| 2026-05-08 | 14 | 6669 | 75.0 | bull | False |  |  |
| 2026-05-08 | 15 | 4966 | 69.0 | bull | False |  |  |
| 2026-05-07 | 1 | 8150 | 85.0 | bull | True |  |  |
| 2026-05-07 | 2 | 6182 | 85.0 | bull | True |  |  |
| 2026-05-07 | 3 | 2301 | 85.0 | bull | True |  |  |
| 2026-05-07 | 4 | 6016 | 85.0 | bull | True |  |  |
| 2026-05-07 | 5 | 5864 | 85.0 | bull | True |  |  |

輸出檔：

- `data/analysis/kline_course_backtest/breakout_daily_scanner.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_recent20d.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_topn_summary.csv`
- `data/analysis/kline_course_backtest/archive/breakout_daily_scanner/YYYY-MM-DD/*`
