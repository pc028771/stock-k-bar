# Breakout Daily Scanner

資料庫：`/Users/howard/.four_seasons/data.sqlite`

回放日期：2026-05-05

樣本：2025-04-25 至 2026-05-05

最新交易日：2026-05-05

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
| 1 | 3707 | 85.0 | bull | True |  |  | 1.0 | 2.613385789496911 |
| 2 | 6274 | 85.0 | bull | True |  |  | 1.0 | 1.667861653488247 |
| 3 | 2855 | 85.0 | bull | True |  |  | 0.8571428571428571 | 1.8131033822626226 |
| 4 | 2417 | 85.0 | bull | True |  |  | 1.0 | 4.784343060396902 |
| 5 | 3550 | 85.0 | bull | True |  |  | 1.0 | 2.568288792180192 |
| 6 | 2465 | 85.0 | bull | True |  |  | 1.0 | 3.6081462822730765 |
| 7 | 3532 | 85.0 | bull | True |  |  | 1.0 | 2.2319379844175486 |
| 8 | 8040 | 85.0 | bull | True |  |  | 1.0 | 3.782465987056498 |
| 9 | 2342 | 85.0 | bull | True |  |  | 1.0 | 2.8085257104550263 |
| 10 | 4991 | 85.0 | bull | True |  |  | 1.0 | 2.1662171066595826 |
| 11 | 1595 | 85.0 | bull | True |  |  | 1.0 | 1.6824233294730082 |
| 12 | 4541 | 85.0 | bull | True |  |  | 0.9777777777777791 | 2.27077318031035 |
| 13 | 3022 | 85.0 | bull | True |  |  | 0.8571428571428568 | 2.7598101831099364 |
| 14 | 6435 | 85.0 | bull | True |  |  | 0.926829268292683 | 1.5471410297496193 |
| 15 | 4526 | 75.0 | bull | False |  |  | 0.8648648648648647 | 4.051525010482598 |

## 近 20 交易日候選

| trade_date | rank_in_date | ticker | scanner_score | market_regime | breakout_next_not_low_open | intraday_strong_attack | below_open_after_1130 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-05 | 1 | 3707 | 85.0 | bull | True |  |  |
| 2026-05-05 | 2 | 6274 | 85.0 | bull | True |  |  |
| 2026-05-05 | 3 | 2855 | 85.0 | bull | True |  |  |
| 2026-05-05 | 4 | 2417 | 85.0 | bull | True |  |  |
| 2026-05-05 | 5 | 3550 | 85.0 | bull | True |  |  |
| 2026-05-05 | 6 | 2465 | 85.0 | bull | True |  |  |
| 2026-05-05 | 7 | 3532 | 85.0 | bull | True |  |  |
| 2026-05-05 | 8 | 8040 | 85.0 | bull | True |  |  |
| 2026-05-05 | 9 | 2342 | 85.0 | bull | True |  |  |
| 2026-05-05 | 10 | 4991 | 85.0 | bull | True |  |  |
| 2026-05-05 | 11 | 1595 | 85.0 | bull | True |  |  |
| 2026-05-05 | 12 | 4541 | 85.0 | bull | True |  |  |
| 2026-05-05 | 13 | 3022 | 85.0 | bull | True |  |  |
| 2026-05-05 | 14 | 6435 | 85.0 | bull | True |  |  |
| 2026-05-05 | 15 | 4526 | 75.0 | bull | False |  |  |
| 2026-05-05 | 16 | 6488 | 75.0 | bull | False |  |  |
| 2026-05-04 | 1 | 2486 | 85.0 | bull | True |  |  |
| 2026-05-04 | 2 | 2855 | 85.0 | bull | True |  |  |
| 2026-05-04 | 3 | 3498 | 85.0 | bull | True |  |  |
| 2026-05-04 | 4 | 2465 | 85.0 | bull | True |  |  |

輸出檔：

- `data/analysis/kline_course_backtest/breakout_daily_scanner.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_recent20d.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_topn_summary.csv`
- `data/analysis/kline_course_backtest/archive/breakout_daily_scanner/YYYY-MM-DD/*`
