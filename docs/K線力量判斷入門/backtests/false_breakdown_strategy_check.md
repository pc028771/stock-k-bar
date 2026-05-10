# 假跌破收回策略原型驗證

資料庫：`/Users/howard/.four_seasons/data.sqlite`

樣本：2025-01-02 至 2026-05-08

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
| base_signal | 1345 | 1.081 | 52.64 | 0.738 | 39.33 | 52.94 | 3.599 | 56.8 |
| tradable_filter | 545 | 1.695 | 57.25 | 1.113 | 44.59 | 46.79 | 5.829 | 62.75 |
| tradable_next_close_confirm | 428 | 2.44 | 61.45 | 1.666 | 52.1 | 35.51 | 6.15 | 64.72 |
| tradable_close_pos_ge_0_7 | 252 | 2.338 | 63.49 | 2.273 | 60.32 | 23.02 | 8.32 | 73.81 |
| tradable_panic_drop_ge_10pct | 326 | 3.128 | 67.79 | 2.172 | 56.75 | 33.44 | 8.349 | 72.39 |
| tradable_volume_ratio_ge_1_2 | 199 | 2.302 | 63.32 | 1.578 | 54.77 | 34.67 | 6.934 | 71.36 |

## 全期間固定持有結果

| variant | n | mean_5d_net_pct | win_rate_5d_net_pct | mean_10d_net_pct | win_rate_10d_net_pct | mean_20d_net_pct | win_rate_20d_net_pct | avg_volume_20_median | attention_n |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| base_signal | 1345 | 0.438 | 50.33 | 1.081 | 52.64 | 3.599 | 56.8 | 347806 | 0 |
| tradable_filter | 545 | 0.893 | 54.86 | 1.695 | 57.25 | 5.829 | 62.75 | 1698751 | 0 |
| tradable_next_close_confirm | 428 | -0.604 | 38.08 | 2.44 | 61.45 | 6.15 | 64.72 | 1744600 | 0 |
| tradable_close_pos_ge_0_7 | 252 | 1.452 | 62.7 | 2.338 | 63.49 | 8.32 | 73.81 | 1930207 | 0 |
| tradable_panic_drop_ge_10pct | 326 | 1.734 | 61.04 | 3.128 | 67.79 | 8.349 | 72.39 | 1885198 | 0 |
| tradable_volume_ratio_ge_1_2 | 199 | 0.416 | 57.29 | 2.302 | 63.32 | 6.934 | 71.36 | 1523477 | 0 |

## 市場環境 regime 分組（Task 2）

Regime 定義（全市場等權代理）：

- `bull`：市場代理指數 > MA20 且 MA20 > MA60
- `bear`：市場代理指數 < MA20 且 MA20 < MA60
- `range`：其餘情況

| variant | market_regime | n | mean_10d_net_pct | win_rate_10d_net_pct | mean_10d_stop_net_pct | stop_hit_10d_pct | mean_20d_net_pct | win_rate_20d_net_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| base_signal | bear | 526 | 3.969 | 73.38 | 2.894 | 31.37 | 9.369 | 81.18 |
| base_signal | bull | 365 | -0.942 | 38.08 | -0.344 | 72.33 | -1.768 | 34.79 |
| base_signal | range | 454 | -0.639 | 40.31 | -0.891 | 62.33 | 1.23 | 46.26 |
| tradable_close_pos_ge_0_7 | bear | 158 | 4.509 | 78.48 | 4.102 | 9.49 | 12.33 | 91.14 |
| tradable_close_pos_ge_0_7 | bull | 30 | -1.945 | 33.33 | -2.536 | 66.67 | -1.357 | 33.33 |
| tradable_close_pos_ge_0_7 | range | 64 | -1.014 | 40.62 | 0.012 | 35.94 | 2.954 | 50.0 |
| tradable_filter | bear | 253 | 4.034 | 75.49 | 3.035 | 25.3 | 10.272 | 82.61 |
| tradable_filter | bull | 120 | -0.733 | 39.17 | -0.821 | 80.83 | -0.058 | 36.67 |
| tradable_filter | range | 172 | -0.052 | 43.02 | -0.365 | 54.65 | 3.401 | 51.74 |
| tradable_next_close_confirm | bear | 219 | 5.09 | 82.19 | 3.937 | 15.98 | 10.763 | 83.11 |
| tradable_next_close_confirm | bull | 70 | -1.203 | 32.86 | -1.423 | 70.0 | -0.881 | 35.71 |
| tradable_next_close_confirm | range | 139 | 0.1 | 43.17 | -0.358 | 48.92 | 2.425 | 50.36 |
| tradable_panic_drop_ge_10pct | bear | 194 | 4.346 | 77.84 | 3.303 | 18.56 | 11.34 | 86.6 |
| tradable_panic_drop_ge_10pct | bull | 54 | 1.12 | 51.85 | -0.073 | 74.07 | 3.06 | 42.59 |
| tradable_panic_drop_ge_10pct | range | 78 | 1.489 | 53.85 | 0.914 | 42.31 | 4.569 | 57.69 |
| tradable_volume_ratio_ge_1_2 | bear | 129 | 4.502 | 80.62 | 3.384 | 16.28 | 11.683 | 89.92 |
| tradable_volume_ratio_ge_1_2 | bull | 34 | -1.572 | 32.35 | -2.451 | 76.47 | -2.32 | 35.29 |
| tradable_volume_ratio_ge_1_2 | range | 36 | -1.923 | 30.56 | -1.088 | 61.11 | -1.346 | 38.89 |

## 停損模型比較（Task 3）

停損模型：

- `simple`：`min(訊號日低點, 60日前低) * 0.995`
- `atr14`：`min(訊號日低點, 60日前低) - ATR14 * 1.0`
- `box20`：`20 日前低 * 0.995`

| variant | stop_model | n | mean_10d_stop_net_pct | win_rate_10d_stop_net_pct | stop_hit_10d_pct | mean_20d_stop_net_pct | win_rate_20d_stop_net_pct | stop_hit_20d_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| base_signal | atr14 | 1345 | 0.804 | 48.85 | 27.29 | 3.171 | 49.14 | 35.99 |
| base_signal | box20 | 1345 | 0.844 | 37.92 | 66.17 | 2.324 | 36.28 | 71.23 |
| base_signal | simple | 1345 | 0.738 | 39.33 | 52.94 | 2.714 | 38.51 | 59.78 |
| tradable_close_pos_ge_0_7 | atr14 | 252 | 2.472 | 62.7 | 8.73 | 8.302 | 72.62 | 13.1 |
| tradable_close_pos_ge_0_7 | box20 | 252 | 2.1 | 55.95 | 36.11 | 6.117 | 57.54 | 42.46 |
| tradable_close_pos_ge_0_7 | simple | 252 | 2.273 | 60.32 | 23.02 | 7.207 | 64.68 | 30.56 |
| tradable_filter | atr14 | 545 | 1.482 | 54.5 | 21.65 | 5.262 | 56.7 | 29.17 |
| tradable_filter | box20 | 545 | 1.04 | 42.02 | 59.08 | 3.328 | 41.47 | 64.04 |
| tradable_filter | simple | 545 | 1.113 | 44.59 | 46.79 | 4.047 | 45.14 | 53.94 |
| tradable_next_close_confirm | atr14 | 428 | 2.334 | 60.98 | 14.49 | 5.907 | 61.92 | 21.73 |
| tradable_next_close_confirm | box20 | 428 | 1.602 | 49.3 | 46.03 | 4.112 | 47.66 | 52.34 |
| tradable_next_close_confirm | simple | 428 | 1.666 | 52.1 | 35.51 | 4.56 | 50.47 | 44.16 |
| tradable_panic_drop_ge_10pct | atr14 | 326 | 2.675 | 65.64 | 12.27 | 7.735 | 68.71 | 17.79 |
| tradable_panic_drop_ge_10pct | box20 | 326 | 1.916 | 53.37 | 46.32 | 5.551 | 54.29 | 50.61 |
| tradable_panic_drop_ge_10pct | simple | 326 | 2.172 | 56.75 | 33.44 | 6.587 | 59.51 | 38.65 |
| tradable_volume_ratio_ge_1_2 | atr14 | 199 | 1.725 | 60.3 | 18.09 | 6.21 | 64.32 | 22.61 |
| tradable_volume_ratio_ge_1_2 | box20 | 199 | 1.527 | 53.27 | 45.23 | 5.108 | 54.77 | 48.24 |
| tradable_volume_ratio_ge_1_2 | simple | 199 | 1.578 | 54.77 | 34.67 | 5.668 | 56.78 | 39.7 |

## 判讀

- 原始 `base_signal` 扣除交易成本後，10 日平均仍為 1.081%，勝率 52.64%。
- 加入可交易限制後，`tradable_filter` 10 日平均為 1.695%，勝率 57.25%，優於原始訊號。這代表目前觀察到的邊際不是由低流動性或注意股撐出來。
- `tradable_next_close_confirm` 不使用隔日開盤進場，而是等隔日收盤確認後第 2 天開盤進場，用來檢查多等一天是否能提升訊號品質。
- `tradable_close_pos_ge_0_7` 與 `tradable_panic_drop_ge_10pct` 表現更好，代表「收盤收得強」與「急跌幅度夠大」可以優先做成策略參數。
- `tradable_filter` 在 bull/range/bear 三種 regime 的 10 日淨報酬分別為 -0.733% / -0.052% / 4.034%。
- `Task 3` 顯示 ATR 與 box 停損可調整停損觸發率與淨報酬權衡；後續應以主要變體（`tradable_filter`、`tradable_next_close_confirm`）選定預設停損模型。
- `Task 4` 的失敗樣本分析請見 `false_breakdown_failure_analysis.md`；這一版會把失敗樣本歸因獨立整理，避免主報告過重。

## 下一步

1. 將 regime 判斷改為可替換來源（例如未來接上正式加權指數）以檢查代理偏差。
2. 把目前最佳停損模型與排除條件接到 daily scanner 輸出欄位。
