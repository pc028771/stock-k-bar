# 假跌破收回策略原型驗證

資料庫：`/Users/howard/.four_seasons/data.sqlite`

樣本：2025-01-02 至 2026-05-11

本次只驗證 `false_breakdown_reclaim`。目標是確認它在加入可交易限制、交易成本與簡單停損後，是否仍值得進入下一步策略開發。

## 假設

- 訊號：5 日跌幅達 7% 以上，盤中跌破 60 日前低，收盤收回 60 日前低。
- 進場：訊號日收盤後成立，隔日開盤買進。
- 隔日確認 variant：隔日收盤仍站回關鍵價後，第 2 天開盤買進。
- 固定持有：第 5/10/20 個交易日收盤出場。
- 交易成本：每筆來回先用 0.585% 扣除，作為手續費與交易稅的保守近似。
- 可交易限制：排除注意股、處置股；20 日均量至少 500,000 股；收盤價至少 10 元。
- 簡單停損：跌破 `min(訊號日低點, 60日前低) * 0.995` 視為觸發停損。此版本只用日K低點判斷，尚未處理跳空穿價。

## 10 日核心結果

| variant | n | mean_10d_net_pct | win_rate_10d_net_pct | mean_10d_stop_net_pct | win_rate_10d_stop_net_pct | stop_hit_10d_pct | mean_20d_net_pct | win_rate_20d_net_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| base_signal | 1366 | 1.134 | 52.71 | 0.775 | 39.39 | 52.78 | 3.543 | 56.73 |
| tradable_filter | 549 | 1.771 | 57.38 | 1.154 | 44.63 | 46.81 | 5.838 | 62.84 |
| tradable_next_close_confirm | 429 | 2.488 | 61.54 | 1.716 | 52.21 | 35.43 | 6.188 | 64.8 |
| tradable_close_pos_ge_0_7 | 255 | 2.52 | 63.92 | 2.357 | 60.39 | 23.14 | 8.363 | 74.12 |
| tradable_panic_drop_ge_10pct | 328 | 3.231 | 67.99 | 2.204 | 56.71 | 33.54 | 8.343 | 72.56 |
| tradable_volume_ratio_ge_1_2 | 202 | 2.533 | 63.86 | 1.695 | 54.95 | 34.65 | 7.009 | 71.78 |

## 全期間固定持有結果

| variant | n | mean_5d_net_pct | win_rate_5d_net_pct | mean_10d_net_pct | win_rate_10d_net_pct | mean_20d_net_pct | win_rate_20d_net_pct | avg_volume_20_median | attention_n |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| base_signal | 1366 | 0.503 | 50.59 | 1.134 | 52.71 | 3.543 | 56.73 | 340301 | 0 |
| tradable_filter | 549 | 0.946 | 55.01 | 1.771 | 57.38 | 5.838 | 62.84 | 1697098 | 0 |
| tradable_next_close_confirm | 429 | -0.591 | 38.23 | 2.488 | 61.54 | 6.188 | 64.8 | 1737997 | 0 |
| tradable_close_pos_ge_0_7 | 255 | 1.552 | 62.75 | 2.52 | 63.92 | 8.363 | 74.12 | 1910757 | 0 |
| tradable_panic_drop_ge_10pct | 328 | 1.792 | 60.98 | 3.231 | 67.99 | 8.343 | 72.56 | 1850514 | 0 |
| tradable_volume_ratio_ge_1_2 | 202 | 0.558 | 57.43 | 2.533 | 63.86 | 7.009 | 71.78 | 1483811 | 0 |

## 市場環境 regime 分組（Task 2）

Regime 定義（全市場等權代理）：

- `bull`：市場代理指數 > MA20 且 MA20 > MA60
- `bear`：市場代理指數 < MA20 且 MA20 < MA60
- `range`：其餘情況

| variant | market_regime | n | mean_10d_net_pct | win_rate_10d_net_pct | mean_10d_stop_net_pct | stop_hit_10d_pct | mean_20d_net_pct | win_rate_20d_net_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| base_signal | bear | 526 | 3.969 | 73.38 | 2.894 | 31.37 | 9.369 | 81.18 |
| base_signal | bull | 378 | -0.67 | 39.15 | -0.193 | 71.43 | -1.689 | 35.45 |
| base_signal | range | 462 | -0.617 | 40.26 | -0.847 | 61.9 | 1.189 | 46.32 |
| tradable_close_pos_ge_0_7 | bear | 158 | 4.509 | 78.48 | 4.102 | 9.49 | 12.33 | 91.14 |
| tradable_close_pos_ge_0_7 | bull | 32 | -0.571 | 37.5 | -1.914 | 65.62 | -0.812 | 37.5 |
| tradable_close_pos_ge_0_7 | range | 65 | -0.791 | 41.54 | 0.219 | 35.38 | 3.236 | 50.77 |
| tradable_filter | bear | 253 | 4.034 | 75.49 | 3.035 | 25.3 | 10.272 | 82.61 |
| tradable_filter | bull | 123 | -0.428 | 39.84 | -0.689 | 80.49 | 0.001 | 37.4 |
| tradable_filter | range | 173 | 0.026 | 43.35 | -0.285 | 54.34 | 3.504 | 52.02 |
| tradable_next_close_confirm | bear | 219 | 5.09 | 82.19 | 3.937 | 15.98 | 10.763 | 83.11 |
| tradable_next_close_confirm | bull | 70 | -1.203 | 32.86 | -1.423 | 70.0 | -0.881 | 35.71 |
| tradable_next_close_confirm | range | 140 | 0.265 | 43.57 | -0.189 | 48.57 | 2.566 | 50.71 |
| tradable_panic_drop_ge_10pct | bear | 194 | 4.346 | 77.84 | 3.303 | 18.56 | 11.34 | 86.6 |
| tradable_panic_drop_ge_10pct | bull | 56 | 1.795 | 53.57 | 0.195 | 73.21 | 3.214 | 44.64 |
| tradable_panic_drop_ge_10pct | range | 78 | 1.489 | 53.85 | 0.914 | 42.31 | 4.569 | 57.69 |
| tradable_volume_ratio_ge_1_2 | bear | 129 | 4.502 | 80.62 | 3.384 | 16.28 | 11.683 | 89.92 |
| tradable_volume_ratio_ge_1_2 | bull | 36 | -0.371 | 36.11 | -1.902 | 75.0 | -1.781 | 38.89 |
| tradable_volume_ratio_ge_1_2 | range | 37 | -1.506 | 32.43 | -0.694 | 59.46 | -0.736 | 40.54 |

## 停損模型比較（Task 3）

停損模型：

- `simple`：`min(訊號日低點, 60日前低) * 0.995`
- `atr14`：`min(訊號日低點, 60日前低) - ATR14 * 1.0`
- `box20`：`20 日前低 * 0.995`

| variant | stop_model | n | mean_10d_stop_net_pct | win_rate_10d_stop_net_pct | stop_hit_10d_pct | mean_20d_stop_net_pct | win_rate_20d_stop_net_pct | stop_hit_20d_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| base_signal | atr14 | 1366 | 0.859 | 48.98 | 27.09 | 3.141 | 49.19 | 35.87 |
| base_signal | box20 | 1366 | 0.842 | 37.92 | 66.33 | 2.284 | 36.16 | 71.45 |
| base_signal | simple | 1366 | 0.775 | 39.39 | 52.78 | 2.695 | 38.58 | 59.66 |
| tradable_close_pos_ge_0_7 | atr14 | 255 | 2.653 | 63.14 | 8.63 | 8.345 | 72.94 | 12.94 |
| tradable_close_pos_ge_0_7 | box20 | 255 | 2.108 | 56.08 | 36.47 | 6.108 | 57.65 | 42.75 |
| tradable_close_pos_ge_0_7 | simple | 255 | 2.357 | 60.39 | 23.14 | 7.17 | 64.71 | 30.59 |
| tradable_filter | atr14 | 549 | 1.56 | 54.64 | 21.49 | 5.277 | 56.83 | 29.14 |
| tradable_filter | box20 | 549 | 1.049 | 42.26 | 59.2 | 3.335 | 41.71 | 64.12 |
| tradable_filter | simple | 549 | 1.154 | 44.63 | 46.81 | 4.037 | 45.17 | 53.92 |
| tradable_next_close_confirm | atr14 | 429 | 2.382 | 61.07 | 14.45 | 5.945 | 62.0 | 21.68 |
| tradable_next_close_confirm | box20 | 429 | 1.652 | 49.42 | 45.92 | 4.154 | 47.79 | 52.21 |
| tradable_next_close_confirm | simple | 429 | 1.716 | 52.21 | 35.43 | 4.601 | 50.58 | 44.06 |
| tradable_panic_drop_ge_10pct | atr14 | 328 | 2.78 | 65.85 | 12.2 | 7.732 | 68.9 | 17.68 |
| tradable_panic_drop_ge_10pct | box20 | 328 | 1.888 | 53.35 | 46.65 | 5.502 | 54.27 | 50.91 |
| tradable_panic_drop_ge_10pct | simple | 328 | 2.204 | 56.71 | 33.54 | 6.519 | 59.45 | 38.72 |
| tradable_volume_ratio_ge_1_2 | atr14 | 202 | 1.965 | 60.89 | 17.82 | 6.296 | 64.85 | 22.28 |
| tradable_volume_ratio_ge_1_2 | box20 | 202 | 1.546 | 53.47 | 45.54 | 5.112 | 54.95 | 48.51 |
| tradable_volume_ratio_ge_1_2 | simple | 202 | 1.695 | 54.95 | 34.65 | 5.644 | 56.93 | 39.6 |

## 判讀

- 原始 `base_signal` 扣除交易成本後，10 日平均仍為 1.134%，勝率 52.71%。
- 加入可交易限制後，`tradable_filter` 10 日平均為 1.771%，勝率 57.38%，優於原始訊號。這代表目前觀察到的邊際不是由低流動性或注意股撐出來。
- `tradable_next_close_confirm` 不使用隔日開盤進場，而是等隔日收盤確認後第 2 天開盤進場，用來檢查多等一天是否能提升訊號品質。
- `tradable_close_pos_ge_0_7` 與 `tradable_panic_drop_ge_10pct` 表現更好，代表「收盤收得強」與「急跌幅度夠大」可以優先做成策略參數。
- `tradable_filter` 在 bull/range/bear 三種 regime 的 10 日淨報酬分別為 -0.428% / 0.026% / 4.034%。
- `Task 3` 顯示 ATR 與 box 停損可調整停損觸發率與淨報酬權衡；後續應以主要變體（`tradable_filter`、`tradable_next_close_confirm`）選定預設停損模型。
- `Task 4` 的失敗樣本分析請見 `false_breakdown_failure_analysis.md`；這一版會把失敗樣本歸因獨立整理，避免主報告過重。

## 下一步

1. 將 regime 判斷改為可替換來源（例如未來接上正式加權指數）以檢查代理偏差。
2. 把目前最佳停損模型與排除條件接到 daily scanner 輸出欄位。
