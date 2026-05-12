# Breakout Daily Scanner

資料庫：`/Users/howard/.four_seasons/data.sqlite`

回放日期：2026-05-08

樣本：2025-04-10 至 2026-05-08

最新交易日：2026-05-08

分K覆蓋率：0.00%（近 20 交易日每日期最多補 0 檔分K）

排除清單筆數（DB）：305
FinMind 上市/上櫃清單筆數：2720
FinMind 營建類股排除筆數：90
硬過濾 profile：`balanced`

## 排序邏輯

- 基礎分數：可交易 breakout 候選（排除注意/處置、低量、低價）
- 加分：`range regime`、`breakout_next_not_low_open`、`close_pos` 高、`volume_ratio` 高、突破幅度高
- Task 13 加分：`overhead_supply_layer ≤ 1` → +8 分（上方套牢壓力少）；`layer ≥ 4` → -8 分（層層套牢）
- 分K加權：`intraday_strong_attack` 加分；`below_open_after_1130` 和 `intraday_attack_failure` 扣分

## Top-N 歷史命中摘要

| bucket | n | mean_10d_net_pct | win_rate_10d_pct | mean_20d_net_pct | win_rate_20d_pct |
| --- | --- | --- | --- | --- | --- |
| all | 1815 | 1.523 | 44.9 | 5.385 | 50.19 |
| top5 | 973 | 2.155 | 46.45 | 6.253 | 51.08 |
| top10 | 1461 | 1.696 | 45.11 | 5.503 | 49.97 |
| top20 | 1784 | 1.543 | 45.12 | 5.491 | 50.56 |

## 最新交易日候選

| rank_in_date | ticker | scanner_score | market_regime | overhead_supply_layer | breakout_next_not_low_open | intraday_strong_attack | below_open_after_1130 | close_pos | volume_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 3450 | 93.0 | bull | 0.0 | True |  |  | 0.8860759493670886 | 1.7097415496178061 |
| 2 | 6278 | 93.0 | bull | 0.0 | True |  |  | 1.0 | 2.255222192482264 |
| 3 | 3702 | 93.0 | bull | 0.0 | True |  |  | 1.0 | 1.6024524392166664 |
| 4 | 4722 | 93.0 | bull | 0.0 | True |  |  | 1.0 | 3.4855418870345147 |
| 5 | 2379 | 93.0 | bull | 1.0 | True |  |  | 1.0 | 2.434259226046405 |
| 6 | 6532 | 93.0 | bull | 0.0 | True |  |  | 1.0 | 1.951615182344014 |
| 7 | 6669 | 93.0 | bull | 0.0 | True |  |  | 0.8611111111111112 | 1.5620743819958298 |
| 8 | 3026 | 83.0 | bull | 0.0 | False |  |  | 1.0 | 2.2875524379091354 |
| 9 | 2472 | 83.0 | bull | 0.0 | False |  |  | 1.0 | 2.0498364561482103 |
| 10 | 3709 | 83.0 | bull | 0.0 | False |  |  | 1.0 | 1.7981237549621931 |
| 11 | 6834 | 83.0 | bull | 0.0 | False |  |  | 1.0 | 5.049637927473331 |
| 12 | 3034 | 77.0 | bull | 18.0 | True |  |  | 1.0 | 4.424466013121846 |
| 13 | 6695 | 77.0 | bull | 10.0 | True |  |  | 1.0 | 3.4050143745008428 |
| 14 | 8926 | 77.0 | bull | 5.0 | True |  |  | 0.9285714285714278 | 3.8220129866272425 |
| 15 | 4966 | 71.0 | bull | 18.0 | True |  |  | 1.0 | 2.455890867097284 |

## 近 20 交易日候選

| trade_date | rank_in_date | ticker | scanner_score | market_regime | breakout_next_not_low_open | intraday_strong_attack | below_open_after_1130 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-08 | 1 | 3450 | 93.0 | bull | True |  |  |
| 2026-05-08 | 2 | 6278 | 93.0 | bull | True |  |  |
| 2026-05-08 | 3 | 3702 | 93.0 | bull | True |  |  |
| 2026-05-08 | 4 | 4722 | 93.0 | bull | True |  |  |
| 2026-05-08 | 5 | 2379 | 93.0 | bull | True |  |  |
| 2026-05-08 | 6 | 6532 | 93.0 | bull | True |  |  |
| 2026-05-08 | 7 | 6669 | 93.0 | bull | True |  |  |
| 2026-05-08 | 8 | 3026 | 83.0 | bull | False |  |  |
| 2026-05-08 | 9 | 2472 | 83.0 | bull | False |  |  |
| 2026-05-08 | 10 | 3709 | 83.0 | bull | False |  |  |
| 2026-05-08 | 11 | 6834 | 83.0 | bull | False |  |  |
| 2026-05-08 | 12 | 3034 | 77.0 | bull | True |  |  |
| 2026-05-08 | 13 | 6695 | 77.0 | bull | True |  |  |
| 2026-05-08 | 14 | 8926 | 77.0 | bull | True |  |  |
| 2026-05-08 | 15 | 4966 | 71.0 | bull | True |  |  |
| 2026-05-07 | 1 | 8150 | 93.0 | bull | True |  |  |
| 2026-05-07 | 2 | 6182 | 93.0 | bull | True |  |  |
| 2026-05-07 | 3 | 2301 | 93.0 | bull | True |  |  |
| 2026-05-07 | 4 | 6016 | 93.0 | bull | True |  |  |
| 2026-05-07 | 5 | 5864 | 93.0 | bull | True |  |  |

輸出檔：

- `data/analysis/kline_course_backtest/breakout_daily_scanner.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_recent20d.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_topn_summary.csv`
- `data/analysis/kline_course_backtest/archive/breakout_daily_scanner/YYYY-MM-DD/*`
