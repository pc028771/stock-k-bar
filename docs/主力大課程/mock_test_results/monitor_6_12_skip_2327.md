# Monitor Replay — 6_12_skip_2327

- date: 2026-06-12  |  tickers: 2327
- desc: 反向: 2327 國巨 6/12 漲停 + 隔日跳空 +9.1%、紅線 #1 應全部 skip、無 trigger fire
- path: check_trigger_inline (composite_check + 紅線、真實 monitor cycle)

## 2327 — 1 個非 none 燈號
| time | trigger | reason |
|---|---|---|
| 09:05 | Ch5_B5-2_skip | B5-2 B 型：跳空 +9.1% + 第 1 根衝高 (開高灌下 (黑K + 收 910.00 在 K 棒下半部)) → 隔日沖出貨、不做 |
