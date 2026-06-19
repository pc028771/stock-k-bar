# Monitor Replay — 5_19_4526_short_swing

- date: 2026-05-19  |  tickers: 4526
- desc: 反向: 4526 東台雙錨停損案例 (紅線 #7)、預期早盤切入後出場、不該 R1 confirm
- path: check_trigger_inline (composite_check + 紅線、真實 monitor cycle)

## 4526 — 3 個非 none 燈號
| time | trigger | reason |
|---|---|---|
| 09:05 | none | 紅線 #3: 前 10 分鐘 (09:05) 不觸發 |
| 13:05 | 尾盤_confirmed | 4/5 pass (結構✓殺盤✓量縮✓未追高)  ✗反彈 |
| 13:10 | none | 5/5 pass (結構✓殺盤✓反彈✓量縮✓未追高) |
| 13:15 | 尾盤_confirmed | 4/5 pass (結構✓殺盤✓量縮✓未追高)  ✗反彈 |
| 13:25 | 反彈 | 跌深 -4.6% (盤中高 38.95) + 5m diff 由負轉正 (early signal) |
| 13:30 | none | 結構未破壞 (距MA10 0.4%) |
