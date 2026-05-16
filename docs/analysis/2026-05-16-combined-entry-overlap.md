# Combined Entry Overlap Analysis
**Date:** 2026-05-16  
**Signal:** `combined_pattern_or_tweezer` = `pattern_breakout_only` OR `tweezer_top_breakout`  
**Backtest period:** same as individual backtests (2-year window, course exit rules)

---

## Signal Set Sizes

| Signal | Trade count |
|--------|-------------|
| pattern_breakout_only | 895 |
| tweezer_top_breakout | 3,042 |
| combined_pattern_or_tweezer | 3,444 |
| Union (P\|T) check | 3,444 ✓ |

Dedup note: combined backtest count matches union of the two key sets exactly, confirming no phantom duplicates.

---

## Overlap Analysis

| Metric | Value |
|--------|-------|
| Signals in BOTH (pattern ∩ tweezer) | 493 |
| Pattern-only (not in tweezer) | 402 / 895 = 44.9% |
| Tweezer-only (not in pattern) | 2,549 / 3,042 = **83.8%** |
| Tweezer signals also in pattern | 493 / 3,042 = **16.2%** |
| Pattern signals also in tweezer | 493 / 895 = **55.1%** |

**Key finding:** tweezer and pattern are largely orthogonal from tweezer's perspective — 83.8% of tweezer signals have no overlap with pattern. From pattern's perspective, 55% of its signals are also flagged by tweezer.

---

## Performance by Subset (from combined backtest)

| Subset | n | Win% | Mean net% | Median net% |
|--------|---|------|-----------|-------------|
| Both (pattern ∩ tweezer) | 493 | 39.6% | +0.50% | -0.69% |
| Pattern only | 402 | 41.0% | +0.25% | -1.26% |
| Tweezer only | 2,549 | 39.7% | +0.55% | -0.99% |
| Combined union | 3,444 | 39.8% | +0.51% | -0.96% |

---

## Standalone Backtest Comparison

| Signal | n | Win% | Mean net% | Median net% |
|--------|---|------|-----------|-------------|
| pattern_breakout_only | 895 | 40.2% | +0.39% | -0.93% |
| tweezer_top_breakout | 3,042 | 39.6% | +0.55% | -0.94% |
| combined_pattern_or_tweezer | 3,444 | 39.8% | +0.51% | -0.96% |

---

## Hypothesis Assessment

### H1 (Additive): union captures more good trades ✗ NOT SUPPORTED

The combined win rate (39.8%) is between the two individual rates and shows no improvement. Mean return (+0.51%) is also between the two. Adding tweezer to pattern does not amplify alpha — it dilutes it slightly by pulling win% toward the lower tweezer rate.

### H2 (Redundant): heavy overlap, no value-add ✗ NOT SUPPORTED

The overlap is NOT heavy — only 16.2% of tweezer signals overlap with pattern. The two signals are structurally different: pattern requires rising-lows formation (主力收貨 confirmation); tweezer only requires similar prior highs. They genuinely detect different chart geometries.

### H3 (Orthogonal): tweezer captures different setups with its own win rate ✓ PARTIALLY SUPPORTED

The two legs are largely orthogonal (83.8% tweezer-only). However, the tweezer-only subset's performance (+0.55% mean, 39.7% win) is nearly identical to the combined and standalone tweezer results. There is no distinct alpha in the non-overlap subset vs the overlap subset.

**Winner: H3 (partial)** — the signals are orthogonal in structure, but that orthogonality does not produce a meaningfully superior non-overlap subset.

---

## Recommendation

**Do NOT make combined the default.**

Rationale:
1. Combined doubles the trade count (895 → 3,444) with no improvement in win rate or mean return.
2. The 3.8× volume increase requires more capital allocation and monitoring without proportional reward.
3. `tweezer_top_breakout` alone (3,042 trades, +0.55% mean) outperforms `pattern_breakout_only` (895 trades, +0.39% mean) on mean return while combined falls between them.
4. If the goal is maximum deployment of capital at the best risk-adjusted return, **tweezer_top_breakout** is the stronger single signal.
5. If the goal is highest selectivity with the fewest trades, **pattern_breakout_only** has the highest win rate (40.2%) and the strongest course-alignment (5-condition 起點 filter).

### When combined makes sense
- If you want to ensure you never miss a pattern signal that tweezer doesn't flag (the 44.9% pattern-only trades), combined is equivalent to running both signals concurrently.
- There is no statistical penalty for using combined — it does not introduce noise signals; each leg is individually course-faithful.

---

## Files

- Combined trades: `data/analysis/kline/backtest_combined.csv` (3,444 rows)
- Pattern trades: `data/analysis/kline/backtest_trades_strict_v5.csv` (895 rows)
- Tweezer trades: `data/analysis/kline/backtest_tweezer_v2.csv` (3,042 rows)
