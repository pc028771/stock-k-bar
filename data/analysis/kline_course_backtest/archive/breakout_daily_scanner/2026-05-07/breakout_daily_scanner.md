# Breakout Daily Scanner

資料庫：`/Users/howard/.four_seasons/data.sqlite`

回放日期：2026-05-07

樣本：2025-04-25 至 2026-05-07

最新交易日：2026-05-07

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
| 1 | 8150 | 85.0 | bull | True |  |  | 1.0 | 2.18426670345582 |
| 2 | 6182 | 85.0 | bull | True |  |  | 1.0 | 1.630765064884192 |
| 3 | 2301 | 85.0 | bull | True |  |  | 1.0 | 1.624328965190976 |
| 4 | 6016 | 85.0 | bull | True |  |  | 0.8666666666666648 | 2.1690568684478024 |
| 5 | 5864 | 85.0 | bull | True |  |  | 1.0 | 2.8750843146378884 |
| 6 | 8042 | 85.0 | bull | True |  |  | 1.0 | 2.1938048712636293 |
| 7 | 3094 | 85.0 | bull | True |  |  | 1.0 | 4.188120689312769 |
| 8 | 6526 | 85.0 | bull | True |  |  | 1.0 | 3.609399057372692 |
| 9 | 8016 | 85.0 | bull | True |  |  | 1.0 | 3.4439017197962927 |
| 10 | 2070 | 85.0 | bull | True |  |  | 1.0 | 3.328487543037171 |
| 11 | 3141 | 85.0 | bull | True |  |  | 1.0 | 3.58186143632499 |
| 12 | 3122 | 85.0 | bull | True |  |  | 1.0 | 3.812874931956256 |
| 13 | 8227 | 85.0 | bull | True |  |  | 1.0 | 1.5943313178745524 |
| 14 | 3526 | 85.0 | bull | True |  |  | 1.0 | 2.019440085184902 |
| 15 | 6834 | 85.0 | bull | True |  |  | 1.0 | 2.3244033903772436 |

## 近 20 交易日候選

| trade_date | rank_in_date | ticker | scanner_score | market_regime | breakout_next_not_low_open | intraday_strong_attack | below_open_after_1130 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-07 | 1 | 8150 | 85.0 | bull | True |  |  |
| 2026-05-07 | 2 | 6182 | 85.0 | bull | True |  |  |
| 2026-05-07 | 3 | 2301 | 85.0 | bull | True |  |  |
| 2026-05-07 | 4 | 6016 | 85.0 | bull | True |  |  |
| 2026-05-07 | 5 | 5864 | 85.0 | bull | True |  |  |
| 2026-05-07 | 6 | 8042 | 85.0 | bull | True |  |  |
| 2026-05-07 | 7 | 3094 | 85.0 | bull | True |  |  |
| 2026-05-07 | 8 | 6526 | 85.0 | bull | True |  |  |
| 2026-05-07 | 9 | 8016 | 85.0 | bull | True |  |  |
| 2026-05-07 | 10 | 2070 | 85.0 | bull | True |  |  |
| 2026-05-07 | 11 | 3141 | 85.0 | bull | True |  |  |
| 2026-05-07 | 12 | 3122 | 85.0 | bull | True |  |  |
| 2026-05-07 | 13 | 8227 | 85.0 | bull | True |  |  |
| 2026-05-07 | 14 | 3526 | 85.0 | bull | True |  |  |
| 2026-05-07 | 15 | 6834 | 85.0 | bull | True |  |  |
| 2026-05-07 | 16 | 3090 | 79.0 | bull | True |  |  |
| 2026-05-07 | 17 | 1785 | 75.0 | bull | False |  |  |
| 2026-05-07 | 18 | 4919 | 75.0 | bull | False |  |  |
| 2026-05-07 | 19 | 4540 | 75.0 | bull | False |  |  |
| 2026-05-07 | 20 | 3162 | 75.0 | bull | False |  |  |

輸出檔：

- `data/analysis/kline_course_backtest/breakout_daily_scanner.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_recent20d.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_topn_summary.csv`
- `data/analysis/kline_course_backtest/archive/breakout_daily_scanner/YYYY-MM-DD/*`
