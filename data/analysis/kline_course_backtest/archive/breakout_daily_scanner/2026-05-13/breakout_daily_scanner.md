# Breakout Daily Scanner

資料庫：`/Users/howard/.four_seasons/data.sqlite`

回放日期：2026-05-13

樣本：2025-04-10 至 2026-05-13

最新交易日：2026-05-13

分K覆蓋率：0.00%（近 20 交易日每日期最多補 15 檔分K）

排除清單筆數（DB）：305
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
| all | 1839 | 1.523 | 44.81 | 5.438 | 50.3 |
| top5 | 983 | 2.225 | 46.19 | 6.355 | 50.56 |
| top10 | 1479 | 1.858 | 45.71 | 5.953 | 50.98 |
| top20 | 1808 | 1.551 | 45.02 | 5.57 | 50.61 |

## 最新交易日候選

| rank_in_date | ticker | scanner_score | breakout_vol_capped | shakeout_strong | market_regime | overhead_supply_layer | breakout_next_low_open | intraday_strong_attack | below_open_after_1130 | close_pos | volume_ratio | breakout_strength_pct | is_attention_stock | is_disposition_stock |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 3481 | 85.0 | True | False | bull | 0.0 | False |  |  | 0.8902439024390237 | 3.4650568795099175 | 5.633802816901401 | 1.0 |  |
| 2 | 8105 | 85.0 | False | False | bull | 0.0 | False |  |  | 1.0 | 13.461782163611321 | 9.459459459459453 | 1.0 |  |
| 3 | 8926 | 85.0 | False | False | bull | 0.0 | False |  |  | 1.0 | 7.4405116346849836 | 8.000000000000007 | 1.0 |  |
| 4 | 2302 | 85.0 | False | False | bull | 0.0 | False |  |  | 1.0 | 9.640216805631077 | 9.936575052854124 | 1.0 |  |
| 5 | 3357 | 85.0 | True | False | bull | 0.0 | False |  |  | 1.0 | 2.310895153583858 | 5.707196029776673 | 1.0 |  |
| 6 | 6166 | 85.0 | True | False | bull | 0.0 | False |  |  | 1.0 | 2.9777169493774047 | 9.852216748768484 | 1.0 |  |
| 7 | 6217 | 85.0 | True | False | bull | 0.0 | False |  |  | 1.0 | 2.827964756510372 | 9.294871794871785 | 1.0 |  |
| 8 | 5228 | 85.0 | False | False | bull | 0.0 | False |  |  | 0.8672566371681416 | 4.523479742782498 | 7.19738276990185 | 1.0 |  |
| 9 | 2356 | 80.0 | False | False | bull | 1.0 | False |  |  | 0.8627450980392152 | 4.697922294362252 | 3.52941176470587 | 1.0 |  |
| 10 | 3236 | 80.0 | True | False | bull | 0.0 | False |  |  | 1.0 | 4.144939575255167 | 2.5065963060686203 | 1.0 |  |
| 11 | 3044 | 80.0 | True | False | bull | 0.0 | False |  |  | 1.0 | 1.9641915735657267 | 3.1189083820662766 | 1.0 |  |
| 12 | 3587 | 80.0 | True | False | bull | 0.0 | False |  |  | 0.85 | 2.316669692615432 | 2.7237354085603016 | 1.0 |  |
| 13 | 2481 | 77.0 | True | False | bull | 0.0 | False |  |  | 0.8888888888888888 | 2.3950980269121267 | 1.2552301255230214 | 1.0 |  |
| 14 | 3583 | 77.0 | True | False | bull | 0.0 | False |  |  | 0.9342105263157895 | 2.4298979991485017 | 1.4705882352941124 | 1.0 |  |
| 15 | 6449 | 77.0 | False | False | bull | 3.0 | False |  |  | 1.0 | 4.004038252304873 | 9.823677581863976 | 1.0 |  |

## 🌊 Shakeout Strong（開低震倉確認）

> **策略說明**：`breakout_vol_capped`（overhead=0 + 量比<4.5）+ 突破強度≥5% + **隔天開低撐住**
> 回測績效：20 日勝率 **62.4%**，20 日均報 **+12.7%**（樣本 298，2025Q2–2026Q2）
> ⚠️ 隔天開低為**次日確認型**訊號，今日候選須等明日開盤確認後方可進場。

### 近期已確認訊號（歷史）

| trade_date | ticker | scanner_score | overhead_supply_layer | volume_ratio | breakout_strength_pct |
| --- | --- | --- | --- | --- | --- |
| 2026-05-12 | 2303 | 85.0 | 0.0 | 1.6527388348207421 | 5.769230769230771 |
| 2026-05-12 | 2492 | 85.0 | 0.0 | 2.338293005318612 | 9.912536443148689 |
| 2026-05-12 | 3035 | 85.0 | 0.0 | 2.6122799100418224 | 5.037783375314864 |
| 2026-05-12 | 4977 | 85.0 | 0.0 | 1.8167158265742147 | 5.252918287937747 |
| 2026-05-12 | 1721 | 85.0 | 0.0 | 2.9590774283016237 | 9.888357256778324 |
| 2026-05-12 | 4973 | 85.0 | 0.0 | 1.6059958036144082 | 9.589041095890405 |
| 2026-05-12 | 3430 | 85.0 | 0.0 | 3.334556086400587 | 5.952380952380953 |
| 2026-05-12 | 3209 | 85.0 | 0.0 | 1.6219156065528721 | 9.917355371900815 |
| 2026-05-12 | 4722 | 85.0 | 0.0 | 1.884187564522021 | 5.5102040816326525 |
| 2026-05-12 | 3229 | 85.0 | 0.0 | 2.4514747303906996 | 9.010011123470507 |

### 今日候選（等待明日開盤確認）

若以下股票明日**開低且撐住**，即升格為 shakeout_strong 進場訊號：

| rank_in_date | ticker | scanner_score | overhead_supply_layer | volume_ratio | close_pos | breakout_strength_pct |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 3481 | 85.0 | 0.0 | 3.4650568795099175 | 0.8902439024390237 | 5.633802816901401 |
| 5 | 3357 | 85.0 | 0.0 | 2.310895153583858 | 1.0 | 5.707196029776673 |
| 6 | 6166 | 85.0 | 0.0 | 2.9777169493774047 | 1.0 | 9.852216748768484 |
| 7 | 6217 | 85.0 | 0.0 | 2.827964756510372 | 1.0 | 9.294871794871785 |

## 近 20 交易日候選

| trade_date | rank_in_date | ticker | scanner_score | breakout_vol_capped | shakeout_strong | market_regime | breakout_next_low_open | intraday_strong_attack | below_open_after_1130 | breakout_strength_pct | is_attention_stock | is_disposition_stock |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-13 | 1 | 3481 | 85.0 | True | False | bull | False |  |  | 5.633802816901401 | 1.0 |  |
| 2026-05-13 | 2 | 8105 | 85.0 | False | False | bull | False |  |  | 9.459459459459453 | 1.0 |  |
| 2026-05-13 | 3 | 8926 | 85.0 | False | False | bull | False |  |  | 8.000000000000007 | 1.0 |  |
| 2026-05-13 | 4 | 2302 | 85.0 | False | False | bull | False |  |  | 9.936575052854124 | 1.0 |  |
| 2026-05-13 | 5 | 3357 | 85.0 | True | False | bull | False |  |  | 5.707196029776673 | 1.0 |  |
| 2026-05-13 | 6 | 6166 | 85.0 | True | False | bull | False |  |  | 9.852216748768484 | 1.0 |  |
| 2026-05-13 | 7 | 6217 | 85.0 | True | False | bull | False |  |  | 9.294871794871785 | 1.0 |  |
| 2026-05-13 | 8 | 5228 | 85.0 | False | False | bull | False |  |  | 7.19738276990185 | 1.0 |  |
| 2026-05-13 | 9 | 2356 | 80.0 | False | False | bull | False |  |  | 3.52941176470587 | 1.0 |  |
| 2026-05-13 | 10 | 3236 | 80.0 | True | False | bull | False |  |  | 2.5065963060686203 | 1.0 |  |
| 2026-05-13 | 11 | 3044 | 80.0 | True | False | bull | False |  |  | 3.1189083820662766 | 1.0 |  |
| 2026-05-13 | 12 | 3587 | 80.0 | True | False | bull | False |  |  | 2.7237354085603016 | 1.0 |  |
| 2026-05-13 | 13 | 2481 | 77.0 | True | False | bull | False |  |  | 1.2552301255230214 | 1.0 |  |
| 2026-05-13 | 14 | 3583 | 77.0 | True | False | bull | False |  |  | 1.4705882352941124 | 1.0 |  |
| 2026-05-13 | 15 | 6449 | 77.0 | False | False | bull | False |  |  | 9.823677581863976 | 1.0 |  |
| 2026-05-13 | 16 | 8069 | 69.0 | False | False | bull | False |  |  | 9.974424552429673 | 1.0 |  |
| 2026-05-12 | 1 | 3481 | 85.0 | True | False | bull | False |  |  | 6.606606606606613 | 1.0 |  |
| 2026-05-12 | 2 | 2303 | 85.0 | True | True | bull | True |  |  | 5.769230769230771 | 1.0 |  |
| 2026-05-12 | 3 | 2492 | 85.0 | True | True | bull | True |  |  | 9.912536443148689 | 1.0 |  |
| 2026-05-12 | 4 | 3035 | 85.0 | True | True | bull | True |  |  | 5.037783375314864 | 1.0 |  |

輸出檔：

- `data/analysis/kline_course_backtest/breakout_daily_scanner.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_recent20d.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_topn_summary.csv`
- `data/analysis/kline_course_backtest/archive/breakout_daily_scanner/YYYY-MM-DD/*`
