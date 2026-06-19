# Monitor Replay — 6_5_closing_panel_1605

- date: 2026-06-05  |  tickers: 1605
- desc: 6/5 1605 華新 broker tier 1「飆股們的媽媽」、尾盤面板應 confirm
- path: check_trigger_inline (composite_check + 紅線、真實 monitor cycle)

## 1605 — 4 個非 none 燈號
| time | trigger | reason |
|---|---|---|
| 09:05 | none | 紅線 #3: 前 10 分鐘 (09:05) 不觸發 |
| 09:50 | 反彈 | 跌深 -5.6% (盤中高 41.30) + 3 紅K + 反彈 2.4% |
| 09:55 | none | 結構未破壞 (距MA10 0.5%) |
| 13:05 | 尾盤_confirmed | 4/5 pass (結構✓殺盤✓量縮✓未追高)  ✗反彈 |
| 13:10 | none | 5/5 pass (結構✓殺盤✓反彈✓量縮✓未追高) |
| 13:15 | 尾盤_confirmed | 4/5 pass (結構✓殺盤✓量縮✓未追高)  ✗反彈 |
| 13:20 | none | 5/5 pass (結構✓殺盤✓反彈✓量縮✓未追高) |
| 13:25 | 尾盤_confirmed | 4/5 pass (結構✓殺盤✓量縮✓未追高)  ✗反彈 |
| 13:30 | none | 結構未破壞 (距MA10 0.5%) |

## Expected vs Actual
| ticker | expected | window | hit |
|---|---|---|---|
| 1605 | Closing_confirmed | 13:00-13:25 | ✅ |