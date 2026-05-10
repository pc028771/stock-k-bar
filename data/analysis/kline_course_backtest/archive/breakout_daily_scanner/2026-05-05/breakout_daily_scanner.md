# Breakout Daily Scanner

資料庫：`/Users/howard/.four_seasons/data.sqlite`

回放日期：2026-05-05

樣本：2025-04-25 至 2026-05-04

最新交易日：2026-05-04

分K覆蓋率：11.34%（近 20 交易日每日期最多補 15 檔分K）

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
| top5 | 895 | 2.222 | 46.48 | 6.543 | 50.73 |
| top10 | 1364 | 1.778 | 45.23 | 5.396 | 49.78 |
| top20 | 1678 | 1.531 | 45.17 | 5.448 | 50.48 |

## 最新交易日候選

| rank_in_date | ticker | scanner_score | market_regime | breakout_next_not_low_open | intraday_strong_attack | below_open_after_1130 | close_pos | volume_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2486 | 99.0 | bull | True | True | False | 1.0 | 1.5738698296707367 |
| 2 | 2855 | 99.0 | bull | True | True | False | 0.9743589743589722 | 1.663165265814838 |
| 3 | 3498 | 99.0 | bull | True | True | False | 1.0 | 1.8717725846556088 |
| 4 | 2465 | 99.0 | bull | True | True | False | 1.0 | 3.3911281424903543 |
| 5 | 3580 | 99.0 | bull | True | True | False | 1.0 | 1.9415609072723643 |
| 6 | 6414 | 99.0 | bull | True | True | False | 0.9565217391304348 | 1.5009875956981948 |
| 7 | 2395 | 89.0 | bull | False | True | False | 1.0 | 3.0110221740738505 |
| 8 | 6166 | 89.0 | bull | False | True | False | 0.9629629629629625 | 2.7164632858368827 |
| 9 | 3526 | 89.0 | bull | False | True | False | 1.0 | 2.2631013426627544 |

## 近 20 交易日候選

| trade_date | rank_in_date | ticker | scanner_score | market_regime | breakout_next_not_low_open | intraday_strong_attack | below_open_after_1130 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-04 | 1 | 2486 | 99.0 | bull | True | True | False |
| 2026-05-04 | 2 | 2855 | 99.0 | bull | True | True | False |
| 2026-05-04 | 3 | 3498 | 99.0 | bull | True | True | False |
| 2026-05-04 | 4 | 2465 | 99.0 | bull | True | True | False |
| 2026-05-04 | 5 | 3580 | 99.0 | bull | True | True | False |
| 2026-05-04 | 6 | 6414 | 99.0 | bull | True | True | False |
| 2026-05-04 | 7 | 2395 | 89.0 | bull | False | True | False |
| 2026-05-04 | 8 | 6166 | 89.0 | bull | False | True | False |
| 2026-05-04 | 9 | 3526 | 89.0 | bull | False | True | False |
| 2026-04-30 | 1 | 6207 | 99.0 | bull | True | True | False |
| 2026-04-30 | 2 | 4576 | 99.0 | bull | True | True | False |
| 2026-04-30 | 3 | 2417 | 89.0 | bull | True | True | True |
| 2026-04-28 | 1 | 2464 | 99.0 | bull | True | True | False |
| 2026-04-28 | 2 | 6405 | 99.0 | bull | True | True | False |
| 2026-04-28 | 3 | 4958 | 89.0 | bull | False | True | False |
| 2026-04-28 | 4 | 3605 | 89.0 | bull | False | True | False |
| 2026-04-28 | 5 | 8103 | 89.0 | bull | False | True | False |
| 2026-04-28 | 6 | 2243 | 89.0 | bull | False | True | False |
| 2026-04-27 | 1 | 8103 | 99.0 | bull | True | True | False |
| 2026-04-27 | 2 | 5483 | 93.0 | bull | True | True | False |

輸出檔：

- `data/analysis/kline_course_backtest/breakout_daily_scanner.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_recent20d.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_topn_summary.csv`
- `data/analysis/kline_course_backtest/archive/breakout_daily_scanner/YYYY-MM-DD/*`
