# Breakout Daily Scanner

資料庫：`/Users/howard/.four_seasons/data.sqlite`

回放日期：2026-05-12

樣本：2025-04-10 至 2026-05-12

最新交易日：2026-05-12

分K覆蓋率：11.23%（近 20 交易日每日期最多補 15 檔分K）

排除清單筆數（DB）：0
FinMind 上市/上櫃清單筆數：2721
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
| all | 1840 | 1.461 | 44.67 | 5.337 | 50.16 |
| top5 | 981 | 2.127 | 45.97 | 6.218 | 50.46 |
| top10 | 1475 | 1.792 | 45.49 | 5.853 | 50.78 |
| top20 | 1805 | 1.489 | 44.82 | 5.453 | 50.42 |

## 最新交易日候選

| rank_in_date | ticker | scanner_score | breakout_vol_capped | shakeout_strong | market_regime | overhead_supply_layer | breakout_next_low_open | intraday_strong_attack | below_open_after_1130 | close_pos | volume_ratio | breakout_strength_pct | is_attention_stock | is_disposition_stock |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 3481 | 99.0 | True | False | bull | 0.0 | False | True | False | 1.0 | 2.275064183392429 | 6.606606606606613 | 1.0 |  |
| 2 | 2303 | 99.0 | True | False | bull | 0.0 | False | True | False | 1.0 | 1.6527388348207421 | 5.769230769230771 | 1.0 |  |
| 3 | 2492 | 99.0 | True | False | bull | 0.0 | False | True | False | 1.0 | 2.338293005318612 | 9.912536443148689 | 1.0 |  |
| 4 | 4977 | 99.0 | True | False | bull | 0.0 | False | True | False | 1.0 | 1.8167158265742147 | 5.252918287937747 | 1.0 |  |
| 5 | 3430 | 99.0 | True | False | bull | 0.0 | False | True | False | 0.9464285714285714 | 3.334556086400587 | 5.952380952380953 | 1.0 |  |
| 6 | 3209 | 99.0 | True | False | bull | 0.0 | False | True | False | 1.0 | 1.6219156065528721 | 9.917355371900815 | 1.0 |  |
| 7 | 4722 | 99.0 | True | False | bull | 0.0 | False | True | False | 1.0 | 1.884187564522021 | 5.5102040816326525 | 1.0 |  |
| 8 | 6166 | 99.0 | True | False | bull | 0.0 | False | True | False | 1.0 | 2.0775991835047534 | 8.672376873661669 | 1.0 |  |
| 9 | 3055 | 99.0 | True | False | bull | 0.0 | False | True | False | 1.0 | 1.9813645333857648 | 10.000000000000009 | 1.0 |  |
| 10 | 3691 | 99.0 | True | False | bull | 0.0 | False | True | False | 1.0 | 1.9617134528684679 | 5.442176870748305 | 1.0 |  |
| 11 | 3229 | 99.0 | True | False | bull | 0.0 | False | True | False | 0.967741935483871 | 2.4514747303906996 | 9.010011123470507 | 1.0 |  |
| 12 | 3583 | 94.0 | True | False | bull | 0.0 | False | True | False | 1.0 | 2.0358706223874234 | 2.2556390977443552 | 1.0 |  |
| 13 | 3035 | 89.0 | True | False | bull | 0.0 | False | True | True | 0.9148936170212766 | 2.6122799100418224 | 5.037783375314864 | 1.0 |  |
| 14 | 1721 | 89.0 | True | False | bull | 0.0 | False | True | True | 1.0 | 2.9590774283016237 | 9.888357256778324 | 1.0 |  |
| 15 | 4973 | 89.0 | True | False | bull | 0.0 | False | True | False | 1.0 | 1.6059958036144082 | 9.589041095890405 | 1.0 |  |

## 🌊 Shakeout Strong（開低震倉確認）

> **策略說明**：`breakout_vol_capped`（overhead=0 + 量比<4.5）+ 突破強度≥5% + **隔天開低撐住**
> 回測績效：20 日勝率 **62.4%**，20 日均報 **+12.7%**（樣本 298，2025Q2–2026Q2）
> ⚠️ 隔天開低為**次日確認型**訊號，今日候選須等明日開盤確認後方可進場。

### 近期已確認訊號（歷史）

| trade_date | ticker | scanner_score | breakout_strength_pct | sitc_lots | foreign_lots | overhead_supply_layer | volume_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-08 | 2472 | 99.0 | 8.048780487804885 | 0 | 132 | 0.0 | 2.0498364561482103 |
| 2026-05-08 | 3026 | 79.0 | 10.000000000000009 | 2145 | 77 | 0.0 | 2.2875524379091354 |
| 2026-05-07 | 2342 | 99.0 | 5.389908256880727 | 0 | 74 | 0.0 | 3.4480878013331533 |
| 2026-05-07 | 3162 | 95.0 | 5.038335158817087 | 0 | 79 | 0.0 | 2.45186711399245 |
| 2026-05-06 | 6488 | 95.0 | 8.258258258258255 | 1100 | 178 | 0.0 | 3.041013651478556 |
| 2026-05-05 | 6488 | 99.0 | 5.213270142180093 | 605 | 119 | 0.0 | 1.903631302761815 |
| 2026-05-04 | 3526 | 99.0 | 8.520179372197312 | 168 | 0 | 0.0 | 2.2631013426627544 |
| 2026-04-28 | 8103 | 99.0 | 9.871244635193133 | 303 | 54 | 0.0 | 4.035358237794941 |
| 2026-04-24 | 3228 | 75.0 | 8.436724565756816 | 0 | -32 | 0.0 | 3.73978027036613 |
| 2026-04-21 | 2351 | 99.0 | 6.7137809187279185 | 142 | -77 | 0.0 | 2.0700725778111955 |

### 今日候選（等待明日開盤確認）

若以下股票明日**開低且撐住**，即升格為 shakeout_strong 進場訊號：

| rank_in_date | ticker | scanner_score | overhead_supply_layer | volume_ratio | close_pos | breakout_strength_pct |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 3481 | 99.0 | 0.0 | 2.275064183392429 | 1.0 | 6.606606606606613 |
| 2 | 2303 | 99.0 | 0.0 | 1.6527388348207421 | 1.0 | 5.769230769230771 |
| 3 | 2492 | 99.0 | 0.0 | 2.338293005318612 | 1.0 | 9.912536443148689 |
| 4 | 4977 | 99.0 | 0.0 | 1.8167158265742147 | 1.0 | 5.252918287937747 |
| 5 | 3430 | 99.0 | 0.0 | 3.334556086400587 | 0.9464285714285714 | 5.952380952380953 |
| 6 | 3209 | 99.0 | 0.0 | 1.6219156065528721 | 1.0 | 9.917355371900815 |
| 7 | 4722 | 99.0 | 0.0 | 1.884187564522021 | 1.0 | 5.5102040816326525 |
| 8 | 6166 | 99.0 | 0.0 | 2.0775991835047534 | 1.0 | 8.672376873661669 |
| 9 | 3055 | 99.0 | 0.0 | 1.9813645333857648 | 1.0 | 10.000000000000009 |
| 10 | 3691 | 99.0 | 0.0 | 1.9617134528684679 | 1.0 | 5.442176870748305 |

## 近 20 交易日候選

| trade_date | rank_in_date | ticker | scanner_score | breakout_vol_capped | shakeout_strong | market_regime | breakout_next_low_open | intraday_strong_attack | below_open_after_1130 | breakout_strength_pct | is_attention_stock | is_disposition_stock |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-12 | 1 | 3481 | 99.0 | True | False | bull | False | True | False | 6.606606606606613 | 1.0 |  |
| 2026-05-12 | 2 | 2303 | 99.0 | True | False | bull | False | True | False | 5.769230769230771 | 1.0 |  |
| 2026-05-12 | 3 | 2492 | 99.0 | True | False | bull | False | True | False | 9.912536443148689 | 1.0 |  |
| 2026-05-12 | 4 | 4977 | 99.0 | True | False | bull | False | True | False | 5.252918287937747 | 1.0 |  |
| 2026-05-12 | 5 | 3430 | 99.0 | True | False | bull | False | True | False | 5.952380952380953 | 1.0 |  |
| 2026-05-12 | 6 | 3209 | 99.0 | True | False | bull | False | True | False | 9.917355371900815 | 1.0 |  |
| 2026-05-12 | 7 | 4722 | 99.0 | True | False | bull | False | True | False | 5.5102040816326525 | 1.0 |  |
| 2026-05-12 | 8 | 6166 | 99.0 | True | False | bull | False | True | False | 8.672376873661669 | 1.0 |  |
| 2026-05-12 | 9 | 3055 | 99.0 | True | False | bull | False | True | False | 10.000000000000009 | 1.0 |  |
| 2026-05-12 | 10 | 3691 | 99.0 | True | False | bull | False | True | False | 5.442176870748305 | 1.0 |  |
| 2026-05-12 | 11 | 3229 | 99.0 | True | False | bull | False | True | False | 9.010011123470507 | 1.0 |  |
| 2026-05-12 | 12 | 3583 | 94.0 | True | False | bull | False | True | False | 2.2556390977443552 | 1.0 |  |
| 2026-05-12 | 13 | 3035 | 89.0 | True | False | bull | False | True | True | 5.037783375314864 | 1.0 |  |
| 2026-05-12 | 14 | 1721 | 89.0 | True | False | bull | False | True | True | 9.888357256778324 | 1.0 |  |
| 2026-05-12 | 15 | 4973 | 89.0 | True | False | bull | False | True | False | 9.589041095890405 | 1.0 |  |
| 2026-05-12 | 16 | 5228 | 80.0 | True | False | bull | False |  |  | 4.441913439635536 | 1.0 |  |
| 2026-05-12 | 17 | 3141 | 77.0 | False | False | bull | False |  |  | 6.5989847715735905 | 1.0 |  |
| 2026-05-12 | 18 | 3048 | 72.0 | False | False | bull | False |  |  | 3.3039647577092435 | 1.0 |  |
| 2026-05-12 | 19 | 5269 | 69.0 | False | False | bull | False |  |  | 5.536332179930792 | 1.0 |  |
| 2026-05-12 | 20 | 8114 | 69.0 | False | False | bull | False |  |  | 9.86238532110091 | 1.0 |  |

輸出檔：

- `data/analysis/kline_course_backtest/breakout_daily_scanner.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_recent20d.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_topn_summary.csv`
- `data/analysis/kline_course_backtest/archive/breakout_daily_scanner/YYYY-MM-DD/*`
