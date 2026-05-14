# Breakout Daily Scanner

資料庫：`/Users/howard/.four_seasons/data.sqlite`

回放日期：2026-05-14

樣本：2025-04-10 至 2026-05-14

最新交易日：2026-05-14

分K覆蓋率：11.26%（近 20 交易日每日期最多補 15 檔分K）

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
| all | 1852 | 1.567 | 44.92 | 5.458 | 50.38 |
| top5 | 988 | 2.084 | 46.46 | 6.013 | 49.8 |
| top10 | 1489 | 2.05 | 46.47 | 6.075 | 51.04 |
| top20 | 1821 | 1.627 | 45.25 | 5.625 | 50.8 |

## 最新交易日候選

| rank_in_date | ticker | scanner_score | breakout_vol_capped | shakeout_strong | market_regime | overhead_supply_layer | breakout_next_low_open | intraday_strong_attack | below_open_after_1130 | close_pos | volume_ratio | breakout_strength_pct | is_attention_stock | is_disposition_stock |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 3048 | 100.0 | False | False | bull | 0.0 | False | True | False | 1.0 | 5.116977457724582 | 8.51063829787233 | 1.0 |  |
| 2 | 8016 | 100.0 | True | False | bull | 0.0 | False | True | False | 1.0 | 2.9223024271348668 | 5.366726296958846 | 1.0 |  |
| 3 | 3008 | 99.0 | True | False | bull | 0.0 | False | True | False | 1.0 | 1.963166586942176 | 6.996587030716728 | 1.0 |  |
| 4 | 7712 | 99.0 | True | False | bull | 0.0 | False | True | False | 1.0 | 2.6809580009279514 | 2.752293577981657 | 1.0 |  |
| 5 | 6525 | 99.0 | True | False | bull | 0.0 | False | True | False | 1.0 | 1.8415971217529705 | 2.643171806167399 | 1.0 |  |
| 6 | 3033 | 92.0 | True | False | bull | 0.0 | False | True | False | 0.8985507246376808 | 2.1421241969795664 | 1.978021978021971 | 1.0 |  |
| 7 | 2344 | 91.0 | False | False | bull | 2.0 | False | True | False | 1.0 | 2.329700433103822 | 3.474903474903468 | 1.0 |  |
| 8 | 8091 | 89.0 | True | False | bull | 0.0 | False | True | True | 1.0 | 1.5483671628681255 | 3.1100478468899517 | 1.0 |  |

## 近 20 交易日候選

| trade_date | rank_in_date | ticker | scanner_score | breakout_vol_capped | shakeout_strong | market_regime | breakout_next_low_open | intraday_strong_attack | below_open_after_1130 | breakout_strength_pct | is_attention_stock | is_disposition_stock |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-14 | 1 | 3048 | 100.0 | False | False | bull | False | True | False | 8.51063829787233 | 1.0 |  |
| 2026-05-14 | 2 | 8016 | 100.0 | True | False | bull | False | True | False | 5.366726296958846 | 1.0 |  |
| 2026-05-14 | 3 | 3008 | 99.0 | True | False | bull | False | True | False | 6.996587030716728 | 1.0 |  |
| 2026-05-14 | 4 | 7712 | 99.0 | True | False | bull | False | True | False | 2.752293577981657 | 1.0 |  |
| 2026-05-14 | 5 | 6525 | 99.0 | True | False | bull | False | True | False | 2.643171806167399 | 1.0 |  |
| 2026-05-14 | 6 | 3033 | 92.0 | True | False | bull | False | True | False | 1.978021978021971 | 1.0 |  |
| 2026-05-14 | 7 | 2344 | 91.0 | False | False | bull | False | True | False | 3.474903474903468 | 1.0 |  |
| 2026-05-14 | 8 | 8091 | 89.0 | True | False | bull | False | True | True | 3.1100478468899517 | 1.0 |  |
| 2026-05-13 | 1 | 8926 | 100.0 | False | False | bull | False | True | False | 8.000000000000007 | 1.0 |  |
| 2026-05-13 | 2 | 2302 | 100.0 | False | False | bull | False | True | False | 9.936575052854124 | 1.0 |  |
| 2026-05-13 | 3 | 3357 | 100.0 | True | False | bull | False | True | False | 5.707196029776673 | 1.0 |  |
| 2026-05-13 | 4 | 6166 | 100.0 | True | False | bull | False | True | False | 9.852216748768484 | 1.0 |  |
| 2026-05-13 | 5 | 6217 | 100.0 | True | False | bull | False | True | False | 9.294871794871785 | 1.0 |  |
| 2026-05-13 | 6 | 3044 | 99.0 | True | False | bull | False | True | False | 3.1189083820662766 | 1.0 |  |
| 2026-05-13 | 7 | 3583 | 96.0 | True | False | bull | False | True | False | 1.4705882352941124 | 1.0 |  |
| 2026-05-13 | 8 | 3481 | 95.0 | True | False | bull | False | True | False | 5.633802816901401 | 1.0 |  |
| 2026-05-13 | 9 | 2356 | 95.0 | False | False | bull | False | True | False | 3.52941176470587 | 1.0 |  |
| 2026-05-13 | 10 | 3587 | 95.0 | True | False | bull | True | True | False | 2.7237354085603016 | 1.0 |  |
| 2026-05-13 | 11 | 8105 | 94.0 | False | False | bull | False | True | False | 9.459459459459453 | 1.0 |  |
| 2026-05-13 | 12 | 6449 | 91.0 | False | False | bull | False | True | False | 9.823677581863976 | 1.0 |  |

輸出檔：

- `data/analysis/kline_course_backtest/breakout_daily_scanner.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_recent20d.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_topn_summary.csv`
- `data/analysis/kline_course_backtest/archive/breakout_daily_scanner/YYYY-MM-DD/*`
