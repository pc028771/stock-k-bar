# Breakout Daily Scanner

資料庫：`/Users/howard/.four_seasons/data.sqlite`

回放日期：2026-05-15

樣本：2025-04-10 至 2026-05-15

最新交易日：2026-05-15

分K覆蓋率：0.00%（近 20 交易日每日期最多補 15 檔分K）

排除清單筆數（DB）：305
FinMind 上市/上櫃清單筆數：2722
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
| all | 1868 | 1.582 | 45.02 | 5.444 | 50.32 |
| top5 | 993 | 2.177 | 47.43 | 6.46 | 50.76 |
| top10 | 1499 | 1.902 | 46.23 | 5.833 | 50.77 |
| top20 | 1837 | 1.65 | 45.24 | 5.575 | 50.63 |

## 最新交易日候選

| rank_in_date | ticker | scanner_score | breakout_vol_capped | shakeout_strong | market_regime | overhead_supply_layer | breakout_next_low_open | intraday_strong_attack | below_open_after_1130 | close_pos | volume_ratio | breakout_strength_pct | is_attention_stock | is_disposition_stock | vp_supply_vacuum | vp_dense_above | vp_overhead_pct | vp_nearest_resistance_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 8028 | 72.0 | True | False | bull | 0.0 | False |  |  | 1.0 | 2.0070441895242728 | 9.94263862332696 | 1.0 |  |  |  |  |  |
| 2 | 3048 | 72.0 | True | False | bull | 0.0 | False |  |  | 1.0 | 3.071552061267782 | 10.000000000000009 | 1.0 |  |  |  |  |  |
| 3 | 3498 | 72.0 | True | False | bull | 0.0 | False |  |  | 1.0 | 1.9638164240652514 | 9.963099630996307 | 1.0 |  |  |  |  |  |
| 4 | 8091 | 72.0 | True | False | bull | 0.0 | False |  |  | 1.0 | 2.4524300070757894 | 9.976798143851507 | 1.0 |  |  |  |  |  |
| 5 | 6227 | 72.0 | True | False | bull | 0.0 | False |  |  | 1.0 | 2.8322708916066333 | 6.41025641025641 | 1.0 |  |  |  |  |  |
| 6 | 3209 | 67.0 | True | False | bull | 0.0 | False |  |  | 0.9130434782608698 | 1.8751437466783516 | 2.2556390977443552 | 1.0 |  |  |  |  |  |
| 7 | 6451 | 57.0 | True | False | bull | 0.0 | False |  |  | 1.0 | 1.718460723360165 | 3.7769784172661858 | 1.0 |  |  |  |  |  |
| 8 | 3305 | 49.0 | False | False | bull | 3.0 | False |  |  | 1.0 | 3.0081387112546953 | 2.973977695167296 | 1.0 |  |  |  |  |  |
| 9 | 6449 | 49.0 | True | False | bull | 0.0 | False |  |  | 1.0 | 3.522004452063557 | 9.812108559498967 | 1.0 |  |  |  |  |  |
| 10 | 3504 | 34.0 | False | False | bull | 0.0 | False |  |  | 0.8518518518518514 | 5.521853100034064 | 3.342245989304815 | 1.0 |  |  |  |  |  |
| 11 | 8374 | 33.0 | False | False | bull | 12.0 | False |  |  | 1.0 | 4.952104317893405 | 7.291666666666674 | 1.0 |  |  |  |  |  |
| 12 | 6215 | 25.0 | False | False | bull | 9.0 | False |  |  | 1.0 | 4.1765597538840975 | 1.953125 | 1.0 |  |  |  |  |  |

## 🌊 Shakeout Strong（開低震倉確認）

> **策略說明**：`breakout_vol_capped`（overhead=0 + 量比<4.5）+ 突破強度≥5% + **隔天開低撐住**
> 回測績效：20 日勝率 **62.4%**，20 日均報 **+12.7%**（樣本 298，2025Q2–2026Q2）
> ⚠️ 隔天開低為**次日確認型**訊號，今日候選須等明日開盤確認後方可進場。

### 近期已確認訊號（歷史）

| trade_date | ticker | scanner_score | breakout_strength_pct | overhead_supply_layer | volume_ratio |
| --- | --- | --- | --- | --- | --- |
| 2026-05-14 | 8016 | 72.0 | 5.366726296958846 | 0.0 | 2.9223024271348668 |
| 2026-05-12 | 2303 | 72.0 | 5.769230769230771 | 0.0 | 1.6527388348207421 |
| 2026-05-12 | 2492 | 72.0 | 9.912536443148689 | 0.0 | 2.338293005318612 |
| 2026-05-12 | 3035 | 72.0 | 5.037783375314864 | 0.0 | 2.6122799100418224 |
| 2026-05-12 | 4977 | 72.0 | 5.252918287937747 | 0.0 | 1.8167158265742147 |
| 2026-05-12 | 1721 | 72.0 | 9.888357256778324 | 0.0 | 2.9590774283016237 |
| 2026-05-12 | 4973 | 72.0 | 9.589041095890405 | 0.0 | 1.6059958036144082 |
| 2026-05-12 | 3209 | 72.0 | 9.917355371900815 | 0.0 | 1.6219156065528721 |
| 2026-05-12 | 4722 | 72.0 | 5.5102040816326525 | 0.0 | 1.884187564522021 |
| 2026-05-12 | 3229 | 72.0 | 9.010011123470507 | 0.0 | 2.4514747303906996 |

### 今日候選（等待明日開盤確認）

若以下股票明日**開低且撐住**，即升格為 shakeout_strong 進場訊號：

| rank_in_date | ticker | scanner_score | overhead_supply_layer | volume_ratio | close_pos | breakout_strength_pct |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 8028 | 72.0 | 0.0 | 2.0070441895242728 | 1.0 | 9.94263862332696 |
| 2 | 3048 | 72.0 | 0.0 | 3.071552061267782 | 1.0 | 10.000000000000009 |
| 3 | 3498 | 72.0 | 0.0 | 1.9638164240652514 | 1.0 | 9.963099630996307 |
| 4 | 8091 | 72.0 | 0.0 | 2.4524300070757894 | 1.0 | 9.976798143851507 |
| 5 | 6227 | 72.0 | 0.0 | 2.8322708916066333 | 1.0 | 6.41025641025641 |
| 9 | 6449 | 49.0 | 0.0 | 3.522004452063557 | 1.0 | 9.812108559498967 |

## 近 20 交易日候選

| trade_date | rank_in_date | ticker | scanner_score | breakout_vol_capped | shakeout_strong | market_regime | breakout_next_low_open | intraday_strong_attack | below_open_after_1130 | breakout_strength_pct | is_attention_stock | is_disposition_stock |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-15 | 1 | 8028 | 72.0 | True | False | bull | False |  |  | 9.94263862332696 | 1.0 |  |
| 2026-05-15 | 2 | 3048 | 72.0 | True | False | bull | False |  |  | 10.000000000000009 | 1.0 |  |
| 2026-05-15 | 3 | 3498 | 72.0 | True | False | bull | False |  |  | 9.963099630996307 | 1.0 |  |
| 2026-05-15 | 4 | 8091 | 72.0 | True | False | bull | False |  |  | 9.976798143851507 | 1.0 |  |
| 2026-05-15 | 5 | 6227 | 72.0 | True | False | bull | False |  |  | 6.41025641025641 | 1.0 |  |
| 2026-05-15 | 6 | 3209 | 67.0 | True | False | bull | False |  |  | 2.2556390977443552 | 1.0 |  |
| 2026-05-15 | 7 | 6451 | 57.0 | True | False | bull | False |  |  | 3.7769784172661858 | 1.0 |  |
| 2026-05-15 | 8 | 3305 | 49.0 | False | False | bull | False |  |  | 2.973977695167296 | 1.0 |  |
| 2026-05-15 | 9 | 6449 | 49.0 | True | False | bull | False |  |  | 9.812108559498967 | 1.0 |  |
| 2026-05-15 | 10 | 3504 | 34.0 | False | False | bull | False |  |  | 3.342245989304815 | 1.0 |  |
| 2026-05-15 | 11 | 8374 | 33.0 | False | False | bull | False |  |  | 7.291666666666674 | 1.0 |  |
| 2026-05-15 | 12 | 6215 | 25.0 | False | False | bull | False |  |  | 1.953125 | 1.0 |  |
| 2026-05-14 | 1 | 8016 | 72.0 | True | True | bull | True |  |  | 5.366726296958846 | 1.0 |  |
| 2026-05-14 | 2 | 3008 | 67.0 | True | False | bull | False |  |  | 6.996587030716728 | 1.0 |  |
| 2026-05-14 | 3 | 7712 | 67.0 | True | False | bull | False |  |  | 2.752293577981657 | 1.0 |  |
| 2026-05-14 | 4 | 6525 | 67.0 | True | False | bull | True |  |  | 2.643171806167399 | 1.0 |  |
| 2026-05-14 | 5 | 8091 | 67.0 | True | False | bull | False |  |  | 3.1100478468899517 | 1.0 |  |
| 2026-05-14 | 6 | 3033 | 64.0 | True | False | bull | True |  |  | 1.978021978021971 | 1.0 |  |
| 2026-05-14 | 7 | 2344 | 59.0 | False | False | bull | True |  |  | 3.474903474903468 | 1.0 |  |
| 2026-05-14 | 8 | 3048 | 49.0 | False | False | bull | False |  |  | 8.51063829787233 | 1.0 |  |

輸出檔：

- `data/analysis/kline_course_backtest/breakout_daily_scanner.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_recent20d.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_topn_summary.csv`
- `data/analysis/kline_course_backtest/archive/breakout_daily_scanner/YYYY-MM-DD/*`
