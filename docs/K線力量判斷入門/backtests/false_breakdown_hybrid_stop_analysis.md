# 假跌破收回情境式停損分析

本報告比較 `ATR14` 全域預設與少數幾個可辯護的 hybrid stop policy。

設計原則：

- `ATR14` 作為預設停損
- 只有在高品質情境時才切到較緊的 `simple`
- 暫不把 `box20` 納入主決策樹，等待後續箱型條件更完整

## Hybrid Policy 比較

| analysis_variant | policy | n | mean_10d_stop_net_pct | win_rate_10d_stop_net_pct | stop_hit_10d_pct | mean_20d_stop_net_pct | win_rate_20d_stop_net_pct | simple_usage_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradable_filter | atr14_only | 549 | 1.56 | 54.64 | 21.49 | 5.277 | 56.83 | 0.0 |
| tradable_filter | simple_if_non_bull_high_close_and_reclaim | 549 | 1.455 | 53.92 | 25.14 | 4.816 | 54.28 | 34.97 |
| tradable_filter | simple_if_non_bull_high_close_and_panic | 549 | 1.444 | 54.1 | 24.23 | 4.934 | 54.83 | 32.79 |
| tradable_filter | simple_if_non_bull_and_reclaim_ge_1pct | 549 | 1.423 | 53.19 | 27.32 | 4.792 | 53.19 | 43.17 |
| tradable_filter | simple_if_bear_regime_only | 549 | 1.258 | 51.18 | 28.42 | 4.753 | 52.64 | 46.08 |
| tradable_next_close_confirm | atr14_only | 429 | 2.382 | 61.07 | 14.45 | 5.945 | 62.0 | 0.0 |
| tradable_next_close_confirm | simple_if_non_bull_high_close_and_reclaim | 429 | 2.114 | 59.44 | 18.88 | 5.268 | 58.97 | 43.82 |
| tradable_next_close_confirm | simple_if_non_bull_and_reclaim_ge_1pct | 429 | 2.11 | 58.51 | 20.75 | 5.225 | 57.81 | 52.21 |
| tradable_next_close_confirm | simple_if_non_bull_high_close_and_panic | 429 | 2.075 | 59.67 | 17.95 | 5.422 | 59.91 | 41.03 |
| tradable_next_close_confirm | simple_if_bear_regime_only | 429 | 1.939 | 57.58 | 19.81 | 5.2 | 57.81 | 51.05 |

Policy 說明：

- `atr14_only`: 全部使用 `ATR14`
- `simple_if_non_bull_high_close_and_panic`: 非 bull、收盤強、且 5 日跌幅至少 10% 時改用 `simple`
- `simple_if_non_bull_high_close_and_reclaim`: 非 bull、收盤強、且收回關鍵價至少 1% 時改用 `simple`
- `simple_if_bear_regime_only`: 只有 bear regime 改用 `simple`
- `simple_if_non_bull_and_reclaim_ge_1pct`: 非 bull 且收回幅度至少 1% 時改用 `simple`
