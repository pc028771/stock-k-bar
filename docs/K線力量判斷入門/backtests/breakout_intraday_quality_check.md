# 突破策略分K攻擊品質驗證

資料庫：`/Users/howard/.four_seasons/data.sqlite` + FinMind `TaiwanStockKBar`

樣本：2025-11-13 至 2026-04-17

抽樣方式：每組目標 100 筆，依 `bull / range / bear` 分層，在各 regime 內從最新訊號往回抓。

目的：比較 `next_not_low_open` 與 `next_low_open` 在突破當天的分K攻擊品質差異，確認 `breakout_next_not_low_open` 是否值得保留為條件式標記。

有效分K樣本：199 / 200（缺失 1 筆）

## 抽樣結構

| group | market_regime | n |
| --- | --- | --- |
| next_low_open | bear | 33 |
| next_low_open | bull | 34 |
| next_low_open | range | 33 |
| next_not_low_open | bear | 33 |
| next_not_low_open | bull | 34 |
| next_not_low_open | range | 33 |

## 分K摘要

| group | n | mean_intraday_return_pct | mean_intraday_close_pos | mean_intraday_drawdown_pct | strong_attack_rate_pct | attack_failure_rate_pct | below_open_after_1130_rate_pct | low_after_high_break_open_rate_pct | mean_close_basis_10d_pct | mean_10d_net_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| next_low_open | 99 | 5.336 | 0.924 | -1.979 | 91.92 | 11.11 | 15.15 | 12.12 | 4.421 | 5.709 |
| next_not_low_open | 100 | 5.708 | 0.953 | -1.243 | 95.0 | 7.0 | 6.0 | 9.0 | 13.216 | 8.687 |

## Regime 分組

| group | market_regime | n | mean_intraday_close_pos | strong_attack_rate_pct | attack_failure_rate_pct | below_open_after_1130_rate_pct | mean_close_basis_10d_pct | mean_10d_net_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| next_low_open | bear | 32 | 0.916 | 93.75 | 9.38 | 12.5 | -1.747 | -1.011 |
| next_low_open | bull | 34 | 0.921 | 94.12 | 11.76 | 17.65 | 2.114 | 3.504 |
| next_low_open | range | 33 | 0.935 | 87.88 | 12.12 | 15.15 | 12.78 | 14.497 |
| next_not_low_open | bear | 33 | 0.953 | 90.91 | 15.15 | 9.09 | 4.376 | 1.074 |
| next_not_low_open | bull | 34 | 0.94 | 97.06 | 0.0 | 2.94 | 8.307 | 3.505 |
| next_not_low_open | range | 33 | 0.966 | 96.97 | 6.06 | 6.06 | 27.114 | 21.639 |

## 判讀

- `next_not_low_open` 若在 `intraday_close_pos`、`strong_attack_rate_pct`、`below_open_after_1130_rate_pct` 上 consistently 優於 `next_low_open`，可視為突破當天的攻擊品質標記。
- 若它的分K品質較好，但 `mean_10d_net_pct` 仍不如 `next_low_open`，代表問題主要出在隔日進場價差，而不是突破當天不夠強。
- 只有在某些 regime 下同時呈現「分K品質更好」與「實際 10 日報酬不差」時，才值得升級為條件式濾網。

## 本輪重點

- `next_not_low_open` 分K收盤位置：0.953
- `next_low_open` 分K收盤位置：0.924
- `next_not_low_open` 強攻比例：95.00%
- `next_low_open` 強攻比例：91.92%
- `next_not_low_open` 午盤後跌破開盤比例：6.00%
- `next_low_open` 午盤後跌破開盤比例：15.15%
- `next_not_low_open` 10 日淨報酬：8.687%
- `next_low_open` 10 日淨報酬：5.709%

## 限制

- 本輪是近期市場的 regime 分層抽樣，不是全期間全樣本回測。
- 若分K資料缺失，該筆樣本會自動排除；因此分K結論應搭配全樣本日K結果一起看。
