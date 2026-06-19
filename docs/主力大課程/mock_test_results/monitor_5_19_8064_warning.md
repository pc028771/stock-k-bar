# Monitor Replay — 5_19_8064_warning

- date: 2026-05-19  |  tickers: 8064
- desc: 反向: 8064 東捷破底股 (Ch2 警示)、預期無 entry trigger fire
- path: check_trigger_inline (composite_check + 紅線、真實 monitor cycle)

## 8064 — 3 個非 none 燈號
| time | trigger | reason |
|---|---|---|
| 09:05 | Ch5_skip | 紅線 #9：前 5 分鐘高 +6.5% > 5% → 整檔 skip |
| 13:05 | 尾盤_confirmed | 4/5 pass (結構✓殺盤✓量縮✓未追高)  ✗反彈 |
| 13:30 | Ch5_skip | 紅線 #9：前 5 分鐘高 +6.5% > 5% → 整檔 skip |
