# Monitor Replay — 6_11_closing_panel_1303

- date: 2026-06-11  |  tickers: 1303
- desc: 6/11 1303 南亞 backtest 期間最佳尾盤進場日 (next day 6/12 漲停)
- path: check_trigger_inline (composite_check + 紅線、真實 monitor cycle)

## 1303 — 2 個非 none 燈號
| time | trigger | reason |
|---|---|---|
| 09:05 | Ch5_skip | 紅線 #9：前 5 分鐘高 +6.4% > 5% → 整檔 skip |
| 09:10 | 首攻 | Ch5-3 [normal盤] 09:10 過高 96.40 站穩 |

## Expected vs Actual
| ticker | expected | window | hit |
|---|---|---|---|
| 1303 | Closing_confirmed | 13:00-13:25 | ❌ |