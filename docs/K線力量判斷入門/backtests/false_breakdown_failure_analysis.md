# 假跌破收回失敗樣本分析

本報告聚焦 `tradable_filter` 與 `tradable_next_close_confirm` 兩個主變體，定義 `10 日淨報酬 < 0` 為失敗樣本，目標是找出可落地的排除條件候選。

## 失敗與成功特徵對比

| analysis_variant | outcome | n | close_pos_mean | ret_5d_past_mean | volume_ratio_mean | reclaim_pct_mean | range_pct_mean | atr14_pct_mean | close_vs_ma20_pct_mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradable_filter | failure | 234 | 59.357 | -12.407 | 128.262 | 1.996 | 4.685 | 5.806 | -12.128 |
| tradable_filter | success | 315 | 65.554 | -15.082 | 134.957 | 3.604 | 6.261 | 6.425 | -15.569 |
| tradable_next_close_confirm | failure | 165 | 61.782 | -12.652 | 140.495 | 1.842 | 4.728 | 6.281 | -12.8 |
| tradable_next_close_confirm | success | 264 | 71.371 | -16.006 | 133.416 | 4.586 | 6.919 | 6.398 | -16.114 |

欄位說明：

- 百分比欄位已換算為 `%`
- `close_pos_mean` 越高表示訊號日越接近日內高點收盤
- `reclaim_pct_mean` 表示收盤高於關鍵價的幅度
- `close_vs_ma20_pct_mean` 表示收盤相對月線的位置

## 失敗樣本的 regime 分布

| analysis_variant | market_regime | outcome | n | share_pct | mean_10d_net_pct |
| --- | --- | --- | --- | --- | --- |
| tradable_filter | bear | failure | 62 | 11.29 | -3.754 |
| tradable_filter | bear | success | 191 | 34.79 | 6.562 |
| tradable_filter | bull | failure | 74 | 13.48 | -5.612 |
| tradable_filter | bull | success | 49 | 8.93 | 7.403 |
| tradable_filter | range | failure | 98 | 17.85 | -5.773 |
| tradable_filter | range | success | 75 | 13.66 | 7.604 |
| tradable_next_close_confirm | bear | failure | 39 | 9.09 | -3.185 |
| tradable_next_close_confirm | bear | success | 180 | 41.96 | 6.882 |
| tradable_next_close_confirm | bull | failure | 47 | 10.96 | -5.331 |
| tradable_next_close_confirm | bull | success | 23 | 5.36 | 7.232 |
| tradable_next_close_confirm | range | failure | 79 | 18.41 | -5.665 |
| tradable_next_close_confirm | range | success | 61 | 14.22 | 7.944 |

## 候選排除條件效果

| analysis_variant | candidate_filter | n | keep_rate_pct | mean_10d_net_pct | win_rate_10d_net_pct | failure_rate_10d_pct | failures_removed_pct | winners_kept_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradable_filter | bear_regime_only | 253 | 46.08 | 4.034 | 75.49 | 24.51 | 73.5 | 60.63 |
| tradable_filter | exclude_bull_and_panic_drop_ge_10pct | 272 | 49.54 | 3.526 | 70.96 | 29.04 | 66.24 | 61.27 |
| tradable_filter | panic_drop_ge_10pct | 328 | 59.74 | 3.231 | 67.99 | 32.01 | 55.13 | 70.79 |
| tradable_filter | exclude_bull_and_close_pos_ge_0_7 | 223 | 40.62 | 2.964 | 67.71 | 32.29 | 69.23 | 47.94 |
| tradable_filter | reclaim_pct_ge_1pct | 278 | 50.64 | 2.922 | 63.67 | 36.33 | 56.84 | 56.19 |
| tradable_filter | volume_ratio_ge_1_2 | 202 | 36.79 | 2.533 | 63.86 | 36.14 | 68.8 | 40.95 |
| tradable_filter | close_pos_ge_0_7 | 255 | 46.45 | 2.52 | 63.92 | 36.08 | 60.68 | 51.75 |
| tradable_filter | exclude_bull_regime | 426 | 77.6 | 2.406 | 62.44 | 37.56 | 31.62 | 84.44 |
| tradable_next_close_confirm | bear_regime_only | 219 | 51.05 | 5.09 | 82.19 | 17.81 | 76.36 | 68.18 |
| tradable_next_close_confirm | exclude_bull_and_panic_drop_ge_10pct | 243 | 56.64 | 4.44 | 76.95 | 23.05 | 66.06 | 70.83 |
| tradable_next_close_confirm | panic_drop_ge_10pct | 275 | 64.1 | 3.932 | 73.45 | 26.55 | 55.76 | 76.52 |
| tradable_next_close_confirm | exclude_bull_and_close_pos_ge_0_7 | 213 | 49.65 | 3.757 | 71.83 | 28.17 | 63.64 | 57.95 |
| tradable_next_close_confirm | reclaim_pct_ge_1pct | 254 | 59.21 | 3.281 | 68.11 | 31.89 | 50.91 | 65.53 |
| tradable_next_close_confirm | exclude_bull_regime | 359 | 83.68 | 3.208 | 67.13 | 32.87 | 28.48 | 91.29 |
| tradable_next_close_confirm | close_pos_ge_0_7 | 235 | 54.78 | 3.183 | 68.51 | 31.49 | 55.15 | 60.98 |
| tradable_next_close_confirm | volume_ratio_ge_1_2 | 169 | 39.39 | 2.777 | 70.41 | 29.59 | 69.7 | 45.08 |

## 初步判讀

- 若某條件能明顯提高 `mean_10d_net_pct`，同時 `winners_kept_pct` 不至於掉太多，就可視為候選排除條件。
- 若某條件主要只是大幅刪減樣本，但未改善 `mean_10d_net_pct` 或 `failure_rate_10d_pct`，就不應直接採用。
- `exclude_bull_regime`、`close_pos_ge_0_7`、`panic_drop_ge_10pct` 是本輪優先比較的條件，因為它們既有課程語意，也已有前面回測支持。

## 失敗樣本範例

輸出檔：

- `data/analysis/kline_course_backtest/false_breakdown_failure_examples.csv`
