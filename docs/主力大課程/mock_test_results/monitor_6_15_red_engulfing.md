# Monitor Replay — 6_15_red_engulfing

- date: 2026-06-15  |  tickers: 1303
- desc: 6/15 — 1303 6/12 漲停隔日 (+9.9%) → R9 紅K吞噬 watch
- path: check_trigger_inline (composite_check + 紅線、真實 monitor cycle)

## 1303 — 2 個非 none 燈號
| time | trigger | reason |
|---|---|---|
| 09:05 | Ch5_skip | 紅線 #9：前 5 分鐘高 +5.5% > 5% → 整檔 skip |
| 09:15 | 首攻 | Ch5-3 [strong盤] 09:10 過高 111.50 站穩 |

## Expected vs Actual
| ticker | expected | window | hit |
|---|---|---|---|
| 1303 | R9紅K吞噬 | 09:10-12:00 | ✅ |