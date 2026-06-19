# Mock Test Result — 6_17_red_engulfing

- **Scenario date**: 2026-06-17
- **Tickers**: 1303
- **Description**: 6/17 — 1303 6/16 黑K、6/17 漲停、R9 setup check
- **Total ticks**: 55
- **Trigger events captured**: 3

## Triggered events

| Time | Ticker | Trigger | Level | Pass | Reason |
|---|---|---|---|---|---|
| 10:05 | 1303 | R9紅K吞噬 | confirmed | 4 | 4/5 (setup✓下行✓吞噬✓時段) ✗量配 |
| 10:10 | 1303 | R9紅K吞噬 | confirmed | 4 | 4/5 (setup✓下行✓吞噬✓時段) ✗量配 |
| 10:20 | 1303 | R9紅K吞噬 | confirmed | 5 | 5/5 (setup✓下行✓吞噬✓時段✓量配) |

## Expected vs Actual

| Ticker | Expected trigger | Expected window | Actual? |
|---|---|---|---|
| 1303 | R9紅K吞噬 | 09:00-13:30 | ✅ 3 fired |