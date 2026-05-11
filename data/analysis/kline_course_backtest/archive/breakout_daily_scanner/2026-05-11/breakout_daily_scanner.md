# Breakout Daily Scanner

資料庫：`/Users/howard/.four_seasons/data.sqlite`

回放日期：2026-05-11

樣本：2025-04-10 至 2026-05-11

最新交易日：2026-05-11

分K覆蓋率：11.78%（近 20 交易日每日期最多補 15 檔分K）

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
| top5 | 973 | 2.147 | 46.45 | 6.299 | 50.98 |
| top10 | 1461 | 1.69 | 45.11 | 5.47 | 49.83 |
| top20 | 1784 | 1.543 | 45.12 | 5.491 | 50.56 |

## 最新交易日候選

| rank_in_date | ticker | scanner_score | market_regime | overhead_supply_layer | breakout_next_not_low_open | intraday_strong_attack | below_open_after_1130 | close_pos | volume_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 4919 | 97.0 | bull | 0.0 | False | True | False | 1.0 | 2.436947154564925 |
| 2 | 5483 | 97.0 | bull | 0.0 | False | True | False | 1.0 | 1.6735809512634074 |
| 3 | 2492 | 97.0 | bull | 0.0 | False | True | False | 1.0 | 1.825699975368227 |
| 4 | 6173 | 97.0 | bull | 0.0 | False | True | False | 1.0 | 2.194129672185627 |
| 5 | 2855 | 97.0 | bull | 0.0 | False | True | False | 0.9090909090909098 | 2.6056233944531084 |
| 6 | 6016 | 97.0 | bull | 0.0 | False | True | False | 1.0 | 1.9033687463312225 |
| 7 | 1809 | 97.0 | bull | 0.0 | False | True | False | 1.0 | 1.5992006179658371 |
| 8 | 8213 | 97.0 | bull | 0.0 | False | True | False | 1.0 | 6.032184024534763 |
| 9 | 1560 | 97.0 | bull | 0.0 | False | True | False | 1.0 | 1.589038802025466 |
| 10 | 3356 | 97.0 | bull | 0.0 | False | True | False | 0.9642857142857151 | 3.3487623379010616 |
| 11 | 5464 | 97.0 | bull | 0.0 | False | True | False | 1.0 | 2.058507523622808 |
| 12 | 2472 | 93.0 | bull | 0.0 | False | True | False | 0.8775510204081632 | 3.0464141968043994 |
| 13 | 4749 | 93.0 | bull | 0.0 | False | True | False | 0.8695652173913043 | 2.741770685059879 |
| 14 | 5425 | 87.0 | bull | 0.0 | False | True | True | 1.0 | 3.652213442277748 |
| 15 | 1721 | 87.0 | bull | 0.0 | False | True | True | 1.0 | 1.8854841762075234 |

## 近 20 交易日候選

| trade_date | rank_in_date | ticker | scanner_score | market_regime | breakout_next_not_low_open | intraday_strong_attack | below_open_after_1130 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-11 | 1 | 4919 | 97.0 | bull | False | True | False |
| 2026-05-11 | 2 | 5483 | 97.0 | bull | False | True | False |
| 2026-05-11 | 3 | 2492 | 97.0 | bull | False | True | False |
| 2026-05-11 | 4 | 6173 | 97.0 | bull | False | True | False |
| 2026-05-11 | 5 | 2855 | 97.0 | bull | False | True | False |
| 2026-05-11 | 6 | 6016 | 97.0 | bull | False | True | False |
| 2026-05-11 | 7 | 1809 | 97.0 | bull | False | True | False |
| 2026-05-11 | 8 | 8213 | 97.0 | bull | False | True | False |
| 2026-05-11 | 9 | 1560 | 97.0 | bull | False | True | False |
| 2026-05-11 | 10 | 3356 | 97.0 | bull | False | True | False |
| 2026-05-11 | 11 | 5464 | 97.0 | bull | False | True | False |
| 2026-05-11 | 12 | 2472 | 93.0 | bull | False | True | False |
| 2026-05-11 | 13 | 4749 | 93.0 | bull | False | True | False |
| 2026-05-11 | 14 | 5425 | 87.0 | bull | False | True | True |
| 2026-05-11 | 15 | 1721 | 87.0 | bull | False | True | True |
| 2026-05-11 | 16 | 3003 | 83.0 | bull | False |  |  |
| 2026-05-11 | 17 | 6138 | 83.0 | bull | False |  |  |
| 2026-05-11 | 18 | 6432 | 77.0 | bull | False |  |  |
| 2026-05-11 | 19 | 2302 | 75.0 | bull | False |  |  |
| 2026-05-11 | 20 | 5009 | 67.0 | bull | False |  |  |

輸出檔：

- `data/analysis/kline_course_backtest/breakout_daily_scanner.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_recent20d.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_topn_summary.csv`
- `data/analysis/kline_course_backtest/archive/breakout_daily_scanner/YYYY-MM-DD/*`
