# Mock Test Result — 6_15_red_engulfing

- **Scenario date**: 2026-06-15
- **Tickers**: 1303
- **Description**: 6/15 — 1303 6/12 漲停隔日 (+9.9%) → R9 紅K吞噬 watch
- **Total ticks**: 55
- **Trigger events captured**: 4
- **Errors raised**: 0

## Triggered events

| Time | Ticker | Trigger | Level | Pass | Reason |
|---|---|---|---|---|---|
| 09:15 | 1303 | Ch5_3_entry | confirmed | 0 | Ch5-3 [normal盤] 09:10 過高 111.50 站穩 |
| 09:20 | 1303 | Ch5_3_entry | confirmed | 0 | Ch5-3 [normal盤] 09:10 過高 111.50 站穩 |
| 09:25 | 1303 | Ch5_3_entry | confirmed | 0 | Ch5-3 [normal盤] 09:10 過高 111.50 站穩 |
| 09:30 | 1303 | Ch5_3_entry | confirmed | 0 | Ch5-3 [normal盤] 09:10 過高 111.50 站穩 |

## Expected vs Actual

| Ticker | Expected trigger | Window | Actual? |
|---|---|---|---|
| 1303 | R9紅K吞噬 | 09:10-12:00 | ❌ FAIL (no fire) |

## Meta
- expected_triggers: 1
- matched: 0
- pass_rate: 0.00%
- errors: 0