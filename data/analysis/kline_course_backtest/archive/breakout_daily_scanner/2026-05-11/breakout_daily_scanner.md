# Breakout Daily Scanner

資料庫：`/Users/howard/.four_seasons/data.sqlite`

回放日期：2026-05-11

樣本：2025-04-10 至 2026-05-11

最新交易日：2026-05-11

分K覆蓋率：0.00%（近 20 交易日每日期最多補 0 檔分K）

排除清單筆數（DB）：305
FinMind 上市/上櫃清單筆數：2720
FinMind 營建類股排除筆數：90
硬過濾 profile：`balanced`

## 排序邏輯（v3 對齊回測基準）

- **85 分**：`overhead=0` + `vol<4.5` + `close_pos≥0.85` + `vol_ratio≥1.5` + `strength≥5%`（對應回測 shakeout_strong 基礎）
- **80 分**：同上但 `strength` 在 2–5% 之間
- **overhead 加分**：`layer≤1` → +8；`layer≥4` → -8
- **分K加權**：`intraday_strong_attack` +10；`below_open_after_1130` / `attack_failure` -10
- 移除「不開低」加分（回測驗證為反訊號）

## Top-N 歷史命中摘要

| bucket | n | mean_10d_net_pct | win_rate_10d_pct | mean_20d_net_pct | win_rate_20d_pct |
| --- | --- | --- | --- | --- | --- |
| all | 1815 | 1.523 | 44.9 | 5.385 | 50.19 |
| top5 | 973 | 2.179 | 46.04 | 6.265 | 50.46 |
| top10 | 1461 | 1.816 | 45.65 | 5.844 | 50.72 |
| top20 | 1784 | 1.551 | 45.12 | 5.517 | 50.5 |

## 最新交易日候選

| rank_in_date | ticker | scanner_score | breakout_vol_capped | shakeout_strong | market_regime | overhead_supply_layer | breakout_next_low_open | intraday_strong_attack | below_open_after_1130 | close_pos | volume_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 5425 | 85.0 | True | False | bull | 0.0 | False |  |  | 1.0 | 3.652213442277748 |
| 2 | 6173 | 85.0 | True | False | bull | 0.0 | False |  |  | 1.0 | 2.194129672185627 |
| 3 | 2855 | 85.0 | True | False | bull | 0.0 | False |  |  | 0.9090909090909098 | 2.6056233944531084 |
| 4 | 6016 | 85.0 | True | False | bull | 0.0 | False |  |  | 1.0 | 1.9033687463312225 |
| 5 | 1809 | 85.0 | True | False | bull | 0.0 | False |  |  | 1.0 | 1.5992006179658371 |
| 6 | 4749 | 85.0 | True | False | bull | 0.0 | False |  |  | 0.8695652173913043 | 2.741770685059879 |
| 7 | 8213 | 85.0 | False | False | bull | 0.0 | False |  |  | 1.0 | 6.032184024534763 |
| 8 | 5464 | 85.0 | True | False | bull | 0.0 | False |  |  | 1.0 | 2.058507523622808 |
| 9 | 4919 | 80.0 | True | False | bull | 0.0 | False |  |  | 1.0 | 2.436947154564925 |
| 10 | 5483 | 80.0 | True | False | bull | 0.0 | False |  |  | 1.0 | 1.6735809512634074 |
| 11 | 2492 | 80.0 | True | False | bull | 0.0 | False |  |  | 1.0 | 1.825699975368227 |
| 12 | 1721 | 80.0 | True | False | bull | 0.0 | False |  |  | 1.0 | 1.8854841762075234 |
| 13 | 3356 | 80.0 | True | False | bull | 0.0 | False |  |  | 0.9642857142857151 | 3.3487623379010616 |
| 14 | 3003 | 80.0 | True | False | bull | 0.0 | False |  |  | 0.9393939393939407 | 2.7040422925466174 |
| 15 | 6138 | 80.0 | True | False | bull | 0.0 | False |  |  | 0.96875 | 2.670290655913709 |

## 🌊 Shakeout Strong（開低震倉確認）

> **策略說明**：`breakout_vol_capped`（overhead=0 + 量比<4.5）+ 突破強度≥5% + **隔天開低撐住**
> 回測績效：20 日勝率 **62.4%**，20 日均報 **+12.7%**（樣本 298，2025Q2–2026Q2）
> ⚠️ 隔天開低為**次日確認型**訊號，今日候選須等明日開盤確認後方可進場。

### 近期已確認訊號（歷史）

| trade_date | ticker | scanner_score | overhead_supply_layer | volume_ratio | breakout_strength_pct |
| --- | --- | --- | --- | --- | --- |
| 2026-05-08 | 3026 | 85.0 | 0.0 | 2.2875524379091354 | 10.000000000000009 |
| 2026-05-08 | 2472 | 85.0 | 0.0 | 2.0498364561482103 | 8.048780487804885 |
| 2026-05-07 | 3162 | 85.0 | 0.0 | 2.45186711399245 | 5.038335158817087 |
| 2026-05-07 | 2342 | 85.0 | 0.0 | 3.4480878013331533 | 5.389908256880727 |
| 2026-05-06 | 6488 | 85.0 | 0.0 | 3.041013651478556 | 8.258258258258255 |
| 2026-05-05 | 6488 | 85.0 | 0.0 | 1.903631302761815 | 5.213270142180093 |
| 2026-05-04 | 3526 | 85.0 | 0.0 | 2.2631013426627544 | 8.520179372197312 |
| 2026-04-28 | 8103 | 85.0 | 0.0 | 4.035358237794941 | 9.871244635193133 |
| 2026-04-24 | 3228 | 85.0 | 0.0 | 3.73978027036613 | 8.436724565756816 |
| 2026-04-21 | 2351 | 85.0 | 0.0 | 2.0700725778111955 | 6.7137809187279185 |

### 今日候選（等待明日開盤確認）

若以下股票明日**開低且撐住**，即升格為 shakeout_strong 進場訊號：

| rank_in_date | ticker | scanner_score | overhead_supply_layer | volume_ratio | close_pos | breakout_strength_pct |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 5425 | 85.0 | 0.0 | 3.652213442277748 | 1.0 | 7.20961281708945 |
| 2 | 6173 | 85.0 | 0.0 | 2.194129672185627 | 1.0 | 9.836065573770503 |
| 3 | 2855 | 85.0 | 0.0 | 2.6056233944531084 | 0.9090909090909098 | 7.768187422934658 |
| 4 | 6016 | 85.0 | 0.0 | 1.9033687463312225 | 1.0 | 8.089887640449444 |
| 5 | 1809 | 85.0 | 0.0 | 1.5992006179658371 | 1.0 | 5.882352941176472 |
| 6 | 4749 | 85.0 | 0.0 | 2.741770685059879 | 0.8695652173913043 | 8.294930875576046 |
| 8 | 5464 | 85.0 | 0.0 | 2.058507523622808 | 1.0 | 9.92366412213741 |

## 近 20 交易日候選

| trade_date | rank_in_date | ticker | scanner_score | breakout_vol_capped | shakeout_strong | market_regime | breakout_next_low_open | intraday_strong_attack | below_open_after_1130 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-11 | 1 | 5425 | 85.0 | True | False | bull | False |  |  |
| 2026-05-11 | 2 | 6173 | 85.0 | True | False | bull | False |  |  |
| 2026-05-11 | 3 | 2855 | 85.0 | True | False | bull | False |  |  |
| 2026-05-11 | 4 | 6016 | 85.0 | True | False | bull | False |  |  |
| 2026-05-11 | 5 | 1809 | 85.0 | True | False | bull | False |  |  |
| 2026-05-11 | 6 | 4749 | 85.0 | True | False | bull | False |  |  |
| 2026-05-11 | 7 | 8213 | 85.0 | False | False | bull | False |  |  |
| 2026-05-11 | 8 | 5464 | 85.0 | True | False | bull | False |  |  |
| 2026-05-11 | 9 | 4919 | 80.0 | True | False | bull | False |  |  |
| 2026-05-11 | 10 | 5483 | 80.0 | True | False | bull | False |  |  |
| 2026-05-11 | 11 | 2492 | 80.0 | True | False | bull | False |  |  |
| 2026-05-11 | 12 | 1721 | 80.0 | True | False | bull | False |  |  |
| 2026-05-11 | 13 | 3356 | 80.0 | True | False | bull | False |  |  |
| 2026-05-11 | 14 | 3003 | 80.0 | True | False | bull | False |  |  |
| 2026-05-11 | 15 | 6138 | 80.0 | True | False | bull | False |  |  |
| 2026-05-11 | 16 | 2472 | 77.0 | True | False | bull | False |  |  |
| 2026-05-11 | 17 | 1560 | 77.0 | True | False | bull | False |  |  |
| 2026-05-11 | 18 | 6432 | 77.0 | True | False | bull | False |  |  |
| 2026-05-11 | 19 | 2302 | 72.0 | False | False | bull | False |  |  |
| 2026-05-11 | 20 | 5009 | 69.0 | False | False | bull | False |  |  |

輸出檔：

- `data/analysis/kline_course_backtest/breakout_daily_scanner.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_recent20d.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_topn_summary.csv`
- `data/analysis/kline_course_backtest/archive/breakout_daily_scanner/YYYY-MM-DD/*`
