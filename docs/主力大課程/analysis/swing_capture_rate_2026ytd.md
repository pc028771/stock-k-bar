# Swing Turning-Point Capture Rate — 2026 YTD

> Sibling analysis to `scanner_diagnostics_6282_6285_passive_2026ytd.md`.
> This analysis measures **pivot capture**, not win rate or trade frequency.

Generated: 2026-06-07 23:40

---

## Method

### Data Sources
- **Price data**: `standard_daily_bar` in `~/.four_seasons/data.sqlite`, 2026-01-01 to 2026-06-07
- **Scanner signals**: all 8 `backtest_ytd/*_trades.csv` files combined (total 12,463 rows)
- **Universe**: `universe_accuracy_2026ytd_filtered.csv` (teacher universe minus financials, 2184 tickers)

### Pivot Detection (Zigzag-style)

For each ticker:

1. **Short-term pivot** (`short`): local max/min in rolling ±5 trading-day window,
   filtered so consecutive same-direction extremes collapse to one, and adjacent H→L (or L→H)
   move must be **≥ 5.0%** to count as a real pivot.

2. **Medium-term pivot** (`medium`): same logic with ±10 trading-day window,
   **≥ 10.0%** move required.

Both use a zigzag algorithm: scan for local extremes → collapse consecutive same-direction → keep only
alternating H/L pairs where the move meets the minimum threshold.

### Signal Hit Check

For each pivot date P, check if **any** scanner fired a signal within `[P − 2 bdays, P + 2 bdays]`.
Direction-agnostic on first pass (any signal near any pivot counts as hit).

### Score

```
short_capture_rate  = short_caught / short_pivots
medium_capture_rate = medium_caught / medium_pivots
combined_score      = 0.4 × short_capture + 0.6 × medium_capture
```

Tickers with **< 3 medium_pivots** are excluded (sideways stocks, no real swing to test).

---

## Sample Base

**1379 tickers** had ≥ 3 medium pivots (10%+ swings) in 2026 YTD.

---

## Top 20 by Combined Score

| ticker | name | sector | short_pivots | short_caught | short_capture_rate | medium_pivots | medium_caught | medium_capture_rate | combined_score | ytd_return_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2481 | 強茂 | 功率元件 | 10 | 7 | 0.7 | 5 | 5 | 1.0 | 0.88 | 106.51 |
| 3272 | 東碩 | 其他 | 9 | 6 | 0.6667 | 3 | 3 | 1.0 | 0.8667 | -14.75 |
| 6239 | 力成 | 記憶體 | 9 | 4 | 0.4444 | 3 | 3 | 1.0 | 0.7778 | 84.2 |
| 7882 |  | 其他 | 4 | 3 | 0.75 | 4 | 3 | 0.75 | 0.75 | -3.48 |
| 2061 | 風青 | 其他 | 8 | 3 | 0.375 | 3 | 3 | 1.0 | 0.75 | 116.89 |
| 6175 | 立敦 | 被動元件 | 9 | 6 | 0.6667 | 5 | 4 | 0.8 | 0.7467 | 75.96 |
| 3085 | 新零售 | 其他 | 10 | 6 | 0.6 | 6 | 5 | 0.8333 | 0.74 | -5.17 |
| 8162 | 微矽電子-創 | 功率元件 | 8 | 5 | 0.625 | 5 | 4 | 0.8 | 0.73 | 95.47 |
| 8150 | 南茂 | 記憶體 | 11 | 9 | 0.8182 | 6 | 4 | 0.6667 | 0.7273 | 99.18 |
| 9933 | 中鼎 | 其他 | 7 | 4 | 0.5714 | 5 | 4 | 0.8 | 0.7086 | 41.3 |
| 4108 | 懷特 | 其他 | 8 | 5 | 0.625 | 4 | 3 | 0.75 | 0.7 | -5.93 |
| 3715 | 定穎投控 | PCB | 15 | 12 | 0.8 | 5 | 3 | 0.6 | 0.68 | 33.86 |
| 3543 | 州巧 | 其他 | 7 | 4 | 0.5714 | 4 | 3 | 0.75 | 0.6786 | -18.05 |
| 3048 | 益登 | 其他 | 9 | 5 | 0.5556 | 4 | 3 | 0.75 | 0.6722 | 45.08 |
| 3090 | 日電貿 | 被動元件 | 9 | 5 | 0.5556 | 4 | 3 | 0.75 | 0.6722 | 104.63 |
| 6182 | 合晶 | 矽晶圓 | 11 | 6 | 0.5455 | 4 | 3 | 0.75 | 0.6682 | 173.6 |
| 2402 | 毅嘉 | 光通訊/CPO | 11 | 6 | 0.5455 | 4 | 3 | 0.75 | 0.6682 | 4.41 |
| 3481 | 群創 | 面板 | 6 | 4 | 0.6667 | 6 | 4 | 0.6667 | 0.6667 | 196.69 |
| 3189 | 景碩 | 封測 | 6 | 4 | 0.6667 | 6 | 4 | 0.6667 | 0.6667 | 356.41 |
| 7767 | 仁大資訊 | 其他 | 3 | 2 | 0.6667 | 3 | 2 | 0.6667 | 0.6667 | -16.34 |

---

## Bottom 10 (Scanner Missed All/Most Swings)

| ticker | name | sector | short_pivots | short_caught | short_capture_rate | medium_pivots | medium_caught | medium_capture_rate | combined_score | ytd_return_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 3097 |  | 其他 | 10 | 0 | 0.0 | 3 | 0 | 0.0 | 0.0 | 18.1 |
| 3388 | 崇越電 | 其他 | 6 | 0 | 0.0 | 3 | 0 | 0.0 | 0.0 | 63.41 |
| 3516 | 亞帝歐 | 其他 | 7 | 0 | 0.0 | 3 | 0 | 0.0 | 0.0 | 10.05 |
| 4155 | 訊映 | 其他 | 3 | 0 | 0.0 | 3 | 0 | 0.0 | 0.0 | 6.19 |
| 4557 | 永新-KY | 其他 | 3 | 0 | 0.0 | 3 | 0 | 0.0 | 0.0 | -42.01 |
| 6146 | 耕興 | 其他 | 6 | 0 | 0.0 | 3 | 0 | 0.0 | 0.0 | 39.12 |
| 6158 | 禾昌 | 其他 | 4 | 0 | 0.0 | 3 | 0 | 0.0 | 0.0 | -16.17 |
| 6212 |  | 其他 | 6 | 0 | 0.0 | 3 | 0 | 0.0 | 0.0 | -31.39 |
| 6637 | 醫影 | 其他 | 5 | 0 | 0.0 | 3 | 0 | 0.0 | 0.0 | -14.74 |
| 6872 | 浩宇生醫 | 其他 | 5 | 0 | 0.0 | 3 | 0 | 0.0 | 0.0 | -14.71 |

---

## Spot-Check: Top-1 Ticker

  
**Ticker**: 2481 強茂    **Medium pivots** (10%+ / ±10d window):  - 2026-01-22 **H** @ 99.4  - 2026-03-09 **L** @ 82.5  - 2026-03-17 **H** @ 104.0  - 2026-03-31 **L** @ 86.4  - 2026-04-17 **H** @ 118.0    **Scanner hits near medium pivots (±2 bdays)**:  - Pivot 2026-01-22 H@99.4 ← hit on: 2026-01-22, 2026-01-21, 2026-01-20  - Pivot 2026-03-09 L@82.5 ← hit on: 2026-03-06  - Pivot 2026-03-17 H@104.0 ← hit on: 2026-03-18, 2026-03-17, 2026-03-16, 2026-03-13  - Pivot 2026-03-31 L@86.4 ← hit on: 2026-04-01  - Pivot 2026-04-17 H@118.0 ← hit on: 2026-04-21, 2026-04-20, 2026-04-17    **Short pivots** (5%+ / ±5d window):  - 2026-01-22 **H** @ 99.4  - 2026-02-11 **L** @ 84.2  - 2026-03-02 **H** @ 94.6  - 2026-03-09 **L** @ 82.5  - 2026-03-17 **H** @ 104.0  - 2026-03-31 **L** @ 86.4  - 2026-04-07 **H** @ 104.5  - 2026-04-14 **L** @ 99.0  - 2026-04-17 **H** @ 118.0  - 2026-04-28 **L** @ 99.2    **Scanner hits near short pivots**:  - Pivot 2026-01-22 H@99.4 ← hit on: 2026-01-22, 2026-01-21, 2026-01-20  - Pivot 2026-03-09 L@82.5 ← hit on: 2026-03-06  - Pivot 2026-03-17 H@104.0 ← hit on: 2026-03-18, 2026-03-17, 2026-03-16, 2026-03-13  - Pivot 2026-03-31 L@86.4 ← hit on: 2026-04-01  - Pivot 2026-04-07 H@104.5 ← hit on: 2026-04-09, 2026-04-08, 2026-04-07  - Pivot 2026-04-14 L@99.0 ← hit on: 2026-04-10  - Pivot 2026-04-17 H@118.0 ← hit on: 2026-04-21, 2026-04-20, 2026-04-17

---

## Sector Breakdown (avg capture rate, excl. 其他)

| sector | n_tickers | avg_short_capture | avg_medium_capture | avg_combined |
| --- | --- | --- | --- | --- |
| CCL材料 | 2 | 0.5272 | 0.55 | 0.5409 |
| 矽晶圓 | 8 | 0.363 | 0.525 | 0.4602 |
| 記憶體 | 12 | 0.3687 | 0.4683 | 0.4284 |
| 光通訊/CPO | 12 | 0.351 | 0.3792 | 0.3679 |
| 面板 | 10 | 0.3525 | 0.375 | 0.366 |
| 功率元件 | 11 | 0.3252 | 0.3818 | 0.3592 |
| PCB | 11 | 0.3473 | 0.3424 | 0.3444 |
| 被動元件 | 18 | 0.3097 | 0.3454 | 0.3311 |
| 成熟製程 | 3 | 0.4445 | 0.25 | 0.3278 |
| 網通 | 14 | 0.3473 | 0.2947 | 0.3157 |
| 小設備 | 4 | 0.2672 | 0.3292 | 0.3044 |
| 特化 | 13 | 0.3143 | 0.2795 | 0.2934 |
| 封測 | 16 | 0.2866 | 0.2854 | 0.2859 |
| 低軌衛星 | 18 | 0.3013 | 0.2653 | 0.2797 |
| BBU | 6 | 0.3234 | 0.2377 | 0.272 |
| IC設計 | 8 | 0.2836 | 0.2594 | 0.2691 |
| 工業電腦 | 12 | 0.2188 | 0.2736 | 0.2517 |
| 機器人 | 16 | 0.2539 | 0.2458 | 0.2491 |
| 廠務設備 | 16 | 0.2573 | 0.2312 | 0.2417 |
| ABF載板 | 1 | 0.3333 | 0.1667 | 0.2333 |
| 產業通路 | 2 | 0.2792 | 0.2 | 0.2317 |
| 連接器 | 13 | 0.2335 | 0.2282 | 0.2303 |
| 主流設備 | 8 | 0.1785 | 0.2241 | 0.2058 |
| 散熱 | 15 | 0.219 | 0.1818 | 0.1966 |
| BMC | 1 | 0.2222 | 0.0 | 0.0889 |
| 航太國防 | 3 | 0.1037 | 0.0 | 0.0415 |

**Top 3 sectors by avg combined score:**
```
sector  n_tickers  avg_medium_capture  avg_combined
 CCL材料          2              0.5500        0.5409
   矽晶圓          8              0.5250        0.4602
   記憶體         12              0.4683        0.4284
```

**Bottom 3 sectors by avg combined score:**
```
sector  n_tickers  avg_medium_capture  avg_combined
    散熱         15              0.1818        0.1966
   BMC          1              0.0000        0.0889
  航太國防          3              0.0000        0.0415
```

---

## Key Insight: Capture Rate vs Win Rate Ranking

Correlation of `combined_score` with `win_rate` (from universe_accuracy file): **r = 0.101**
Correlation of `combined_score` with `avg_pnl_pct`: **r = 0.026**

Combined_score has a weak correlation with win_rate (r=0.10). The two metrics measure meaningfully different things: win_rate reflects trade-level outcome, while capture_rate reflects alignment with structural pivot points regardless of trade outcome.

The capture-rate metric specifically answers: *"When this stock made a real swing, did the scanner notice?"*
Win-rate answers: *"When the scanner fired, did it make money?"*
These are orthogonal quality dimensions. A scanner can have high win-rate but miss major pivots
(fires on noise but gets lucky), or high capture-rate but low win-rate (detects pivots but enters at wrong price).
The ideal scanner scores well on BOTH axes.
