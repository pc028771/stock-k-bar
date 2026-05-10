# K線力量課程情境回測

資料庫：`/Users/howard/.four_seasons/data.sqlite`

樣本：2025-01-02 至 2026-05-08，1873 檔，589,270 筆可用日K。

回測假設：訊號在當日收盤後形成，隔日開盤進場，以第 5/10/20 個交易日收盤計算報酬。此版只使用日K OHLCV 與均線欄位，尚未納入人工標註的壓力區、賣壓中空圖形區段與 intraday 江波。

## 結果摘要

| signal | n | mean_5d_pct | win_rate_5d_pct | mean_10d_pct | win_rate_10d_pct | mean_20d_pct | win_rate_20d_pct | mean_close_basis_10d_pct | win_rate_close_basis_10d_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| breakout_attack | 5655 | 0.077 | 42.6 | 1.474 | 44.17 | 3.861 | 45.98 | 2.615 | 47.8 |
| breakout_next_not_low_open | 3976 | -0.306 | 40.9 | 0.946 | 42.33 | 2.932 | 44.19 | 3.42 | 50.18 |
| breakout_next_low_open | 1679 | 0.985 | 46.63 | 2.724 | 48.54 | 6.061 | 50.21 | 0.71 | 42.17 |
| upper_shadow_new_high | 4015 | 0.224 | 42.22 | 1.46 | 45.73 | 3.636 | 47.05 | 1.781 | 47.15 |
| new_high_no_upper_shadow | 8234 | 0.284 | 43.72 | 1.597 | 45.21 | 4.114 | 47.13 | 2.769 | 48.52 |
| doji_at_pressure | 5170 | 0.41 | 43.73 | 1.185 | 44.66 | 2.77 | 46.75 | 1.466 | 45.84 |
| doji_break_up | 17450 | 0.158 | 43.6 | 0.722 | 45.87 | 1.546 | 46.48 | 1.02 | 47.18 |
| doji_break_down | 21229 | 0.216 | 47.27 | 0.501 | 47.03 | 1.106 | 47.35 | 0.854 | 48.51 |
| false_breakdown_reclaim | 1345 | 1.023 | 54.13 | 1.666 | 55.99 | 4.184 | 59.03 | 2.521 | 59.11 |
| real_breakdown_after_range | 3211 | 0.386 | 49.42 | 0.829 | 51.01 | 1.119 | 47.24 | 1.276 | 53.5 |

## 課程情境符合度

| 課程情境 | 本次量化代理 | 判讀 |
| --- | --- | --- |
| 突破後隔日不開低代表攻擊品質較好 | `breakout_next_not_low_open` vs `breakout_next_low_open` 的 close-basis 10 日報酬 | 部分符合。收盤基準 10 日平均報酬為 3.420% vs 0.710%，表示走勢延續較強；但若用隔日開盤進場，開低組因買價較低，交易報酬反而較高。 |
| 創高上影線不必然是賣壓 | `upper_shadow_new_high` vs `new_high_no_upper_shadow` | 大致符合。創高上影線 10 日 close-basis 平均仍為 1.781%，不是明顯負向；但弱於無明顯上影線的新高組 2.769%。 |
| 十字線需要隔日確認，不能單看十字線 | `doji_break_up` vs `doji_break_down` | 目前只部分支持。兩組 10 日 close-basis 報酬都偏正，方向差異不明顯；需要加入「前段已拉抬」「是否遇壓」「長/短十字線」等圖例標註。 |
| 急跌後跌破前低又收回是假性跌破，後續不宜直接看空 | `false_breakdown_reclaim` | 符合度最高。10 日 close-basis 平均 2.521%，勝率 59.11%；20 日 close-basis 平均 5.100%。 |
| 整理後長黑跌破偏真正轉弱 | `real_breakdown_after_range` | 本次簡化代理不支持。10 日 close-basis 平均仍為 1.276%；代表單用 60 日前低與長黑不足以捕捉課程的「頸線/整理後跌破」。 |


## 初步判讀

- `breakout_next_not_low_open` 對應課程中「突破後隔日不開低」的攻擊品質條件，可與 `breakout_next_low_open` 比較。
- `upper_shadow_new_high` 用來檢驗「創高上影線不必然是壓力」；若結果不顯著轉弱，較符合課程敘述。
- `doji_break_up` 與 `doji_break_down` 檢驗十字線隔日方向確認，而不是看到十字線就預測。
- `false_breakdown_reclaim` 檢驗急跌後跌破前低又收回的假性跌破情境。
- `real_breakdown_after_range` 檢驗整理後長黑跌破，與假性跌破相對。

## 限制

- 樣本只有 2025-01 至 2026-05，市場 regime 單一，不能直接視為長期結論。
- 賣壓中空、層層套牢、壓力區是否化解，需要 volume profile 或人工圖形標註；本次只保留為後續驗證項目。
- 注意股與處置股目前未排除；如果要做可交易策略，下一版應加入流動性、注意/處置、漲跌停買不到等限制。
