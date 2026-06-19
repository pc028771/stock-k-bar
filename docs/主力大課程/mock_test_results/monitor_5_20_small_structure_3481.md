# Monitor Replay — 5_20_small_structure_3481

- date: 2026-05-20  |  tickers: 3481
- desc: 3481 群創 5/20 small_structure 觸發 → 5/21 漲停。Mock 重播 5/20 看 R1 早盤
- path: check_trigger_inline (composite_check + 紅線、真實 monitor cycle)

## 3481 — 3 個非 none 燈號
| time | trigger | reason |
|---|---|---|
| 09:05 | none | 紅線 #3: 前 10 分鐘 (09:05) 不觸發 |
| 12:15 | 反彈 | 跌深 -3.8% (盤中高 38.00) + 3 紅K + 反彈 1.8% |
| 12:20 | none | 結構未破壞 (距MA10 0.5%) |
| 13:05 | 尾盤_confirmed | 4/5 pass (結構✓殺盤✓量縮✓未追高)  ✗反彈 |
| 13:25 | 反彈 | 跌深 -3.8% (盤中高 38.00) + 5m diff 由負轉正 (early signal) |
| 13:30 | none | 結構未破壞 (距MA10 0.9%) |

## Expected vs Actual
| ticker | expected | window | hit |
|---|---|---|---|
| 3481 | R1首攻 | 09:00-13:30 | ✅ |