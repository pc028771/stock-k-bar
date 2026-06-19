# Monitor Replay — 5_22_smallstr_3042

- date: 2026-05-22  |  tickers: 3042
- desc: 3042 晶技 5/19 small_structure → 5/22 漲停日。Mock 5/22 看 R1 早盤
- path: check_trigger_inline (composite_check + 紅線、真實 monitor cycle)

## 3042 — 5 個非 none 燈號
| time | trigger | reason |
|---|---|---|
| 09:05 | none | 紅線 #3: 前 10 分鐘 (09:05) 不觸發 |
| 09:25 | 紅K吞噬_confirmed | 4/5 (setup✓下行✓吞噬✓時段) ✗量配 |
| 09:35 | none | 結構未破壞 (距MA10 0.9%) |
| 09:50 | 紅K吞噬_confirmed | 5/5 (setup✓下行✓吞噬✓時段✓量配) |
| 09:55 | 續攻_watch | T1 觸發但太接近日高 $176.00、等回測 -1.5% 再切入 |
| 10:00 | none | 結構未破壞 (距MA10 3.5%) |
| 10:20 | 紅K吞噬_confirmed | 4/5 (setup✓下行✓吞噬✓時段) ✗量配 |
| 10:25 | none | 結構未破壞 (距MA10 0.7%) |
| 10:30 | 紅K吞噬_confirmed | 4/5 (setup✓下行✓吞噬✓時段) ✗量配 |
| 10:40 | none | 結構未破壞 (距MA10 0.4%) |

## Expected vs Actual
| ticker | expected | window | hit |
|---|---|---|---|
| 3042 | R1首攻 | 09:00-11:00 | ✅ |