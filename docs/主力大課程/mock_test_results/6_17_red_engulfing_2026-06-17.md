# Mock Test Result — 6_17_red_engulfing

- **Scenario date**: 2026-06-17
- **Tickers**: 1303
- **Description**: 6/17 — 1303 6/16 黑K (-4.6%) 後、R9 setup check (today gap?)
- **Total ticks**: 55
- **Trigger events captured**: 7
- **Errors raised**: 0

## Triggered events

| Time | Ticker | Trigger | Level | Pass | Reason |
|---|---|---|---|---|---|
| 09:15 | 1303 | Ch5_3_entry | confirmed | 0 | Ch5-3 [normal盤] 09:10 過高 118.50 站穩 |
| 09:20 | 1303 | Ch5_3_entry | confirmed | 0 | Ch5-3 [normal盤] 09:10 過高 118.50 站穩 |
| 09:25 | 1303 | Ch5_3_entry | confirmed | 0 | Ch5-3 [normal盤] 09:10 過高 118.50 站穩 |
| 09:30 | 1303 | Ch5_3_entry | confirmed | 0 | Ch5-3 [normal盤] 09:10 過高 118.50 站穩 |
| 10:05 | 1303 | R9紅K吞噬 | confirmed | 4 | 4/5 (setup✓下行✓吞噬✓時段) ✗量配 |
| 10:10 | 1303 | R9紅K吞噬 | confirmed | 4 | 4/5 (setup✓下行✓吞噬✓時段) ✗量配 |
| 10:20 | 1303 | R9紅K吞噬 | confirmed | 5 | 5/5 (setup✓下行✓吞噬✓時段✓量配) |

## Expected vs Actual

| Ticker | Expected trigger | Window | Actual? |
|---|---|---|---|
| 1303 | R9紅K吞噬 | 09:10-12:00 | ✅ PASS (3 fired) |

## Meta
- expected_triggers: 1
- matched: 1
- pass_rate: 100.00%
- errors: 0