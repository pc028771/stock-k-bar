# 突破隔日開盤品質驗證

資料庫：`/Users/howard/.four_seasons/data.sqlite`

樣本：2025-01-02 至 2026-05-08

目的：檢查 `breakout_next_not_low_open` 應該被當成什麼。

- 如果它主要提升 `close_basis`，但沒有提升 `next_open` 交易報酬，它比較像持股品質或觀察欄位。
- 如果它連 `next_open` 報酬也更好，才有資格當突破策略濾網。

## 主比較

| group | n | mean_gap_pct | mean_close_basis_10d_pct | win_close_basis_10d_pct | mean_10d_net_pct | win_10d_net_pct | mean_10d_atr_stop_net_pct | mean_20d_net_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| all_breakout_tradable | 3515 | 1.25 | 2.618 | 49.1 | 0.775 | 43.24 | 0.408 | 4.127 |
| next_not_low_open | 2547 | 2.396 | 3.424 | 51.71 | 0.412 | 42.17 | 0.18 | 3.344 |
| next_low_open | 968 | -1.768 | 0.495 | 42.25 | 1.729 | 46.07 | 1.006 | 6.188 |

## Regime 分組

| group | market_regime | n | mean_close_basis_10d_pct | mean_10d_net_pct | win_10d_net_pct |
| --- | --- | --- | --- | --- | --- |
| next_low_open | bear | 57 | -1.636 | -0.54 | 38.6 |
| next_low_open | bull | 678 | -0.235 | 1.096 | 44.4 |
| next_low_open | range | 276 | 3.398 | 4.439 | 53.26 |
| next_not_low_open | bear | 123 | 2.891 | -0.475 | 41.46 |
| next_not_low_open | bull | 1957 | 3.638 | 0.447 | 42.21 |
| next_not_low_open | range | 699 | 5.605 | 2.781 | 47.21 |

## Gap Bucket 分組

| gap_bucket | n | mean_gap_pct | mean_close_basis_10d_pct | mean_10d_net_pct | win_10d_net_pct | mean_20d_net_pct |
| --- | --- | --- | --- | --- | --- | --- |
| -1%~-3% | 395 | -1.773 | 0.238 | 1.46 | 45.06 | 5.539 |
| 0~+1% | 1033 | 0.34 | 1.7 | 0.768 | 41.43 | 2.438 |
| 0~-1% | 449 | -0.538 | 1.674 | 1.638 | 46.77 | 5.791 |
| <-3% | 167 | -5.071 | -0.96 | 3.742 | 49.1 | 8.787 |
| >=+1% | 1746 | 3.733 | 5.52 | 1.126 | 44.62 | 3.894 |

## 判讀

- `next_not_low_open` 的 close-basis 10 日平均為 3.424%，高於 `next_low_open` 的 0.495%。
- 但 `next_open` 實際交易 10 日平均報酬，`next_not_low_open` 只有 0.412%，低於 `next_low_open` 的 1.729%。
- 這代表「隔日不開低」目前更像走勢品質標籤，而不是更好的進場價格條件。
- 若後續要保留它，應該與分K攻擊品質一起驗證，而不是單獨當作突破策略買點濾網。
