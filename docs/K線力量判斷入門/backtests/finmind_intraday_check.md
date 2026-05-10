# FinMind 分K課程情境抽樣驗證

資料集：FinMind `TaiwanStockKBar`。官方文件說明台股分 K 資料表單次請求只提供一天資料，因此本報告採抽樣驗證。

每個日K訊號抽樣上限：10

輸出：

- `data/analysis/kline_course_backtest/finmind_intraday_signal_summary.csv`
- `data/analysis/kline_course_backtest/finmind_intraday_signal_check.csv`

## 分K摘要

| signal | n | strong_attack_rate | failure_rate | below_open_after_1130_rate | mean_intraday_return_pct | mean_close_pos |
| --- | --- | --- | --- | --- | --- | --- |
| breakout_next_low_open | 10 | 90.0 | 10.0 | 20.0 | 7.072 | 0.891 |
| breakout_next_not_low_open | 10 | 90.0 | 10.0 | 10.0 | 4.675 | 0.879 |
| false_breakdown_reclaim | 10 | 20.0 | 0.0 | 80.0 | -1.769 | 0.421 |
| upper_shadow_new_high | 10 | 10.0 | 70.0 | 80.0 | 0.336 | 0.584 |

## 課程情境補充判讀

- 突破組：`breakout_next_not_low_open` 與 `breakout_next_low_open` 在訊號當日分K都呈現高比例強攻，這代表「突破當日有攻擊」與日K條件一致；但它無法單獨解釋隔日開高/開低差異，隔日行為仍要用日K或隔日分K延伸驗證。
- 創高上影線：`upper_shadow_new_high` 的 `failure_rate` 明顯較高，支持課程說法中的關鍵點：上影線不是必然看空，但它代表盤中攻擊沒有完整延續，必須再看壓力區與隔日確認。
- 假性跌破收回：`false_breakdown_reclaim` 當日分K多數盤中偏弱，這和日K回測的後續轉強並不衝突；它更像是急跌後賣壓耗盡或收回關鍵價，而不是當天立即展開攻擊。
- 午盤後跌破開盤：`below_open_after_1130_rate` 可作為攻擊品質濾網。若突破訊號午盤後仍反覆跌破開盤，應降低攻擊分數。

## 判讀方式

- `intraday_strong_attack`: 當日收紅、收盤接近日內高點，且高點後沒有明顯跌破開盤價。
- `intraday_attack_failure`: 盤中曾上攻超過 1%，但收盤轉弱、收盤位置偏低，或高點後跌破開盤價。
- `below_open_after_1130_rate`: 午盤後跌破開盤價的比例，用來檢查課程提到的攻擊不應給太多低接機會。

## 限制

- FinMind `TaiwanStockKBar` 是 sponsor 資料，且單次一天；此處只抽樣，不做全市場逐筆分K回測。
- 分K規則仍是自動化代理，尚未加入人工圖形標註，例如壓力區、頸線、江波轉折點。
