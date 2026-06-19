# Monitor Replay — 6_3_foreign_buy_black_k_2303

- date: 2026-06-03  |  tickers: 2303
- desc: 2303 聯電 6/3 foreign_buy_on_black_k 案例。daily-level detector、Mock 主要看 intraday 是否出現 R1/Closing
- path: check_trigger_inline (composite_check + 紅線、真實 monitor cycle)

## 2303 — 2 個非 none 燈號
| time | trigger | reason |
|---|---|---|
| 09:05 | none | 紅線 #3: 前 10 分鐘 (09:05) 不觸發 |
| 13:10 | 尾盤_confirmed | 4/5 pass (結構✓殺盤✓量縮✓未追高)  ✗反彈 |
| 13:15 | none | 3/5 pass (殺盤✓量縮✓未追高)  ✗結構,反彈 |
| 13:25 | 破底 | 跌破前波低 133.50、量×1.5 恐慌賣壓 |
| 13:30 | none | 跌破前波低 133.50 (量×3.9、等量爆確認) |
