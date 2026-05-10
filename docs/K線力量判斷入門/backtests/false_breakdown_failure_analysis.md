# 假跌破收回失敗樣本分析

本報告聚焦 `tradable_filter` 與 `tradable_next_close_confirm` 兩個主變體，定義 `10 日淨報酬 < 0` 為失敗樣本，目標是找出可落地的排除條件候選。

## 失敗與成功特徵對比

| analysis_variant | outcome | n | close_pos_mean | ret_5d_past_mean | volume_ratio_mean | reclaim_pct_mean | range_pct_mean | atr14_pct_mean | close_vs_ma20_pct_mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradable_filter | failure | 233 | 59.475 | -12.424 | 128.49 | 2.004 | 4.68 | 5.807 | -12.135 |
| tradable_filter | success | 312 | 65.301 | -15.049 | 132.825 | 3.6 | 6.213 | 6.426 | -15.557 |
| tradable_next_close_confirm | failure | 165 | 61.782 | -12.652 | 140.495 | 1.842 | 4.728 | 6.281 | -12.8 |
| tradable_next_close_confirm | success | 263 | 71.262 | -16.034 | 133.45 | 4.601 | 6.936 | 6.406 | -16.14 |

欄位說明：

- 百分比欄位已換算為 `%`
- `close_pos_mean` 越高表示訊號日越接近日內高點收盤
- `reclaim_pct_mean` 表示收盤高於關鍵價的幅度
- `close_vs_ma20_pct_mean` 表示收盤相對月線的位置

## 失敗樣本的 regime 分布

| analysis_variant | market_regime | outcome | n | share_pct | mean_10d_net_pct |
| --- | --- | --- | --- | --- | --- |
| tradable_filter | bear | failure | 62 | 11.38 | -3.754 |
| tradable_filter | bear | success | 191 | 35.05 | 6.562 |
| tradable_filter | bull | failure | 73 | 13.39 | -5.625 |
| tradable_filter | bull | success | 47 | 8.62 | 6.865 |
| tradable_filter | range | failure | 98 | 17.98 | -5.773 |
| tradable_filter | range | success | 74 | 13.58 | 7.524 |
| tradable_next_close_confirm | bear | failure | 39 | 9.11 | -3.185 |
| tradable_next_close_confirm | bear | success | 180 | 42.06 | 6.882 |
| tradable_next_close_confirm | bull | failure | 47 | 10.98 | -5.331 |
| tradable_next_close_confirm | bull | success | 23 | 5.37 | 7.232 |
| tradable_next_close_confirm | range | failure | 79 | 18.46 | -5.665 |
| tradable_next_close_confirm | range | success | 60 | 14.02 | 7.69 |

## 候選排除條件效果

| analysis_variant | candidate_filter | n | keep_rate_pct | mean_10d_net_pct | win_rate_10d_net_pct | failure_rate_10d_pct | failures_removed_pct | winners_kept_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradable_filter | bear_regime_only | 253 | 46.42 | 4.034 | 75.49 | 24.51 | 73.39 | 61.22 |
| tradable_filter | exclude_bull_and_panic_drop_ge_10pct | 272 | 49.91 | 3.526 | 70.96 | 29.04 | 66.09 | 61.86 |
| tradable_filter | panic_drop_ge_10pct | 326 | 59.82 | 3.128 | 67.79 | 32.21 | 54.94 | 70.83 |
| tradable_filter | exclude_bull_and_close_pos_ge_0_7 | 222 | 40.73 | 2.916 | 67.57 | 32.43 | 69.1 | 48.08 |
| tradable_filter | reclaim_pct_ge_1pct | 276 | 50.64 | 2.798 | 63.41 | 36.59 | 56.65 | 56.09 |
| tradable_filter | exclude_bull_regime | 425 | 77.98 | 2.38 | 62.35 | 37.65 | 31.33 | 84.94 |
| tradable_filter | close_pos_ge_0_7 | 252 | 46.24 | 2.338 | 63.49 | 36.51 | 60.52 | 51.28 |
| tradable_filter | volume_ratio_ge_1_2 | 199 | 36.51 | 2.302 | 63.32 | 36.68 | 68.67 | 40.38 |
| tradable_next_close_confirm | bear_regime_only | 219 | 51.17 | 5.09 | 82.19 | 17.81 | 76.36 | 68.44 |
| tradable_next_close_confirm | exclude_bull_and_panic_drop_ge_10pct | 243 | 56.78 | 4.44 | 76.95 | 23.05 | 66.06 | 71.1 |
| tradable_next_close_confirm | panic_drop_ge_10pct | 275 | 64.25 | 3.932 | 73.45 | 26.55 | 55.76 | 76.81 |
| tradable_next_close_confirm | exclude_bull_and_close_pos_ge_0_7 | 212 | 49.53 | 3.665 | 71.7 | 28.3 | 63.64 | 57.79 |
| tradable_next_close_confirm | reclaim_pct_ge_1pct | 254 | 59.35 | 3.281 | 68.11 | 31.89 | 50.91 | 65.78 |
| tradable_next_close_confirm | exclude_bull_regime | 358 | 83.64 | 3.152 | 67.04 | 32.96 | 28.48 | 91.25 |
| tradable_next_close_confirm | close_pos_ge_0_7 | 234 | 54.67 | 3.097 | 68.38 | 31.62 | 55.15 | 60.84 |
| tradable_next_close_confirm | volume_ratio_ge_1_2 | 168 | 39.25 | 2.656 | 70.24 | 29.76 | 69.7 | 44.87 |

## 初步判讀

- 若某條件能明顯提高 `mean_10d_net_pct`，同時 `winners_kept_pct` 不至於掉太多，就可視為候選排除條件。
- 若某條件主要只是大幅刪減樣本，但未改善 `mean_10d_net_pct` 或 `failure_rate_10d_pct`，就不應直接採用。
- `exclude_bull_regime`、`close_pos_ge_0_7`、`panic_drop_ge_10pct` 是本輪優先比較的條件，因為它們既有課程語意，也已有前面回測支持。

## 失敗樣本範例

輸出檔：

- `data/analysis/kline_course_backtest/false_breakdown_failure_examples.csv`
