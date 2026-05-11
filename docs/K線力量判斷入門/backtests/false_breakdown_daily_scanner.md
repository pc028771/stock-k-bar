# 假跌破收回每日掃描（Task 5）

掃描邏輯：

- 基底：`tradable_filter`（排除注意/處置、低流動性、低價）
- 分數加權：`exclude_bull_regime`、`close_pos >= 0.7`、`panic_drop >= 10%`、`volume_ratio >= 1.2`、`reclaim_pct >= 1%`
- 確認規則：隔日收盤需站回 `confirm_price`（此檔為 pending 狀態）
- 停損欄位：預設優先參考 `stop_price_atr14`

本次候選數：1

## Top 30 候選

| scan_date | ticker | market_regime | signal_close | key_level | confirm_status | close_pos | ret_5d_past_pct | volume_ratio | reclaim_pct | scanner_score | stop_price_atr14 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-11 | 3625 | bull | 15.1 | 15.0 | pending_next_close | 58.33 | -8.761 | 0.678230810134681 | 0.667 | 0 | 13.967857142857143 |

輸出檔：

- `data/analysis/kline_course_backtest/false_breakdown_daily_scanner.csv`
- `data/analysis/kline_course_backtest/false_breakdown_daily_scanner_recent20d.csv`
