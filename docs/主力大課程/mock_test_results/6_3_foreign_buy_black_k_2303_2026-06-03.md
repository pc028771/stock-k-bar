# Mock Test Result — 6_3_foreign_buy_black_k_2303

- **Scenario date**: 2026-06-03
- **Tickers**: 2303
- **Description**: 2303 聯電 6/3 foreign_buy_on_black_k 案例。daily-level detector、Mock 主要看 intraday 是否出現 R1/Closing
- **Total ticks**: 55
- **Trigger events captured**: 1
- **Errors raised**: 0

## Triggered events

| Time | Ticker | Trigger | Level | Pass | Reason |
|---|---|---|---|---|---|
| 13:10 | 2303 | Closing_confirmed | confirmed | 4 | 4/5 pass (結構✓殺盤✓量縮✓未追高)  ✗反彈 |

## Expected vs Actual

| Ticker | Expected trigger | Window | Actual? |
|---|---|---|---|

### 反向 case 結果: ⚠️ AUDIT (1 fired)

## Meta
- expected_triggers: 0
- matched: 0
- pass_rate: 100.00%
- errors: 0