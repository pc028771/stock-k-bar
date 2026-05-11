# Breakout Daily Scanner

資料庫：`/Users/howard/.four_seasons/data.sqlite`

回放日期：2026-05-06

樣本：2025-04-25 至 2026-05-06

最新交易日：2026-05-06

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
| 1 | 2354 | 85.0 | bull | True |  |  | 1.0 | 10.003614138488626 |
| 2 | 3033 | 85.0 | bull | True |  |  | 1.0 | 8.114288360698914 |
| 3 | 3706 | 85.0 | bull | True |  |  | 0.8936170212765958 | 3.235657768773763 |
| 4 | 6173 | 85.0 | bull | True |  |  | 1.0 | 3.4158863657881406 |
| 5 | 8042 | 85.0 | bull | True |  |  | 0.9206349206349206 | 7.706656275125077 |
| 6 | 6274 | 85.0 | bull | True |  |  | 0.8611111111111112 | 2.104618878420834 |
| 7 | 3532 | 85.0 | bull | True |  |  | 1.0 | 4.265030323023188 |
| 8 | 6108 | 85.0 | bull | True |  |  | 1.0 | 5.237161016174136 |
| 9 | 2357 | 85.0 | bull | True |  |  | 0.868421052631579 | 2.3603745083122583 |
| 10 | 8215 | 85.0 | bull | True |  |  | 1.0 | 1.9350550456866884 |
| 11 | 3094 | 85.0 | bull | True |  |  | 1.0 | 5.249662883034621 |
| 12 | 6526 | 85.0 | bull | True |  |  | 1.0 | 3.3677712337825616 |
| 13 | 4556 | 85.0 | bull | True |  |  | 1.0 | 2.6851703273562917 |
| 14 | 3023 | 79.0 | bull | True |  |  | 0.9545454545454546 | 2.425779255631275 |
| 15 | 6831 | 79.0 | bull | True |  |  | 0.8987341772151899 | 2.0194898925158267 |

## 近 20 交易日候選

| trade_date | rank_in_date | ticker | scanner_score | market_regime | breakout_next_not_low_open | intraday_strong_attack | below_open_after_1130 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-06 | 1 | 2354 | 85.0 | bull | True |  |  |
| 2026-05-06 | 2 | 3033 | 85.0 | bull | True |  |  |
| 2026-05-06 | 3 | 3706 | 85.0 | bull | True |  |  |
| 2026-05-06 | 4 | 6173 | 85.0 | bull | True |  |  |
| 2026-05-06 | 5 | 8042 | 85.0 | bull | True |  |  |
| 2026-05-06 | 6 | 6274 | 85.0 | bull | True |  |  |
| 2026-05-06 | 7 | 3532 | 85.0 | bull | True |  |  |
| 2026-05-06 | 8 | 6108 | 85.0 | bull | True |  |  |
| 2026-05-06 | 9 | 2357 | 85.0 | bull | True |  |  |
| 2026-05-06 | 10 | 8215 | 85.0 | bull | True |  |  |
| 2026-05-06 | 11 | 3094 | 85.0 | bull | True |  |  |
| 2026-05-06 | 12 | 6526 | 85.0 | bull | True |  |  |
| 2026-05-06 | 13 | 4556 | 85.0 | bull | True |  |  |
| 2026-05-06 | 14 | 3023 | 79.0 | bull | True |  |  |
| 2026-05-06 | 15 | 6831 | 79.0 | bull | True |  |  |
| 2026-05-06 | 16 | 6488 | 75.0 | bull | False |  |  |
| 2026-05-05 | 1 | 3707 | 85.0 | bull | True |  |  |
| 2026-05-05 | 2 | 6274 | 85.0 | bull | True |  |  |
| 2026-05-05 | 3 | 2855 | 85.0 | bull | True |  |  |
| 2026-05-05 | 4 | 2417 | 85.0 | bull | True |  |  |

輸出檔：

- `data/analysis/kline_course_backtest/breakout_daily_scanner.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_recent20d.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_topn_summary.csv`
- `data/analysis/kline_course_backtest/archive/breakout_daily_scanner/YYYY-MM-DD/*`
