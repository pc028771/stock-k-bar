# Phase 4.3 Advisor History Backtest Report

Generated: 2026-06-04 13:14:24

## Scope

- **Tickers**: 200
- **Date range**: 2024-01-01 → 2026-06-30
- **Trading dates in range**: 583
- **Ticker-days processed**: 114,782
- **Advisor runs saved**: 114,782
- **Runs skipped** (idempotent): 0
- **Branch rows backfilled**: 123,572
- **Elapsed time**: 33.6 minutes

## Branch Hit Rates

Total (pattern × branch_id) pairs with ≥10 runs: **62**

### High Confidence (≥80%) — 3 branches

| pattern | branch_id | n_runs | n_matched | hit_rate | avg_matched_days |
|---------|-----------|--------|-----------|----------|-----------------|
| morning_star_island_reversal | B2_next_day_gap_filled | 288 | 255 | 88.5% | 1.00 |
| gap_reversal | B2_next_day_gap_filled | 2449 | 2050 | 83.7% | 1.00 |
| gap_under_pressure_reversal | B1_next_day_gap_fills_up | 3949 | 3277 | 83.0% | 1.00 |

### Medium Confidence (50–80%) — 7 branches

| pattern | branch_id | n_runs | n_matched | hit_rate | avg_matched_days |
|---------|-----------|--------|-----------|----------|-----------------|
| breakout_double_star | B1_next_day_gap_up_holds | 327 | 218 | 66.7% | 1.00 |
| morning_star_island_reversal | B3_next_day_encounters_overhead_supply | 288 | 190 | 66.0% | 1.00 |
| merged_doji | B1_gap_up_attack | 518 | 279 | 53.9% | 1.00 |
| morning_star_harami | B1_next_day_gap_up_attack | 875 | 454 | 51.9% | 1.00 |
| bear_engulfing | B3_next_day_consolidation | 325 | 167 | 51.4% | 1.00 |
| piercing_line | B3_next_day_stalls | 5335 | 2721 | 51.0% | 1.00 |
| dark_double_star_anye | B3_next_day_stalls_within_range | 1469 | 735 | 50.0% | 1.00 |

### Low Confidence (<50%) — Noise Candidates — 52 branches

| pattern | branch_id | n_runs | n_matched | hit_rate | avg_matched_days |
|---------|-----------|--------|-----------|----------|-----------------|
| morning_star_island_reversal | B1_next_day_gap_holds_no_fill | 288 | 33 | 11.5% | 1.00 |
| gap_reversal | B3_next_day_stalls_above_today_low | 2449 | 356 | 14.5% | 1.00 |
| outside_three_black | B3_next_day_attempts_recovery | 75 | 11 | 14.7% | 1.00 |
| three_red_dadi_dangqian | B3_next_day_recovery_attempt | 389 | 70 | 18.0% | 1.00 |
| dark_double_star_anye | B2_next_day_recovers_above_twin_high | 1469 | 293 | 19.9% | 1.00 |
| meeting | B1_next_day_continues_same_direction | 5463 | 1163 | 21.3% | 1.00 |
| three_red_dadi_dangqian | B1_next_day_continues_below_midpoint | 389 | 85 | 21.9% | 1.00 |
| gap_fill_down | B1_next_day_continues_higher_after_fill | 4698 | 1032 | 22.0% | 1.00 |
| neutral_engulfing | B2_next_day_reversal | 523 | 116 | 22.2% | 1.00 |
| embracing | B1_next_day_continues_power_direction | 8247 | 1830 | 22.2% | 1.00 |
| rebound | B1_next_day_continues_rebound_direction | 1984 | 457 | 23.0% | 1.00 |
| biting | B1_next_day_breakout_holds | 6651 | 1566 | 23.5% | 1.00 |
| two_crow_gap | B2_next_day_continues_lower | 957 | 228 | 23.8% | 1.00 |
| high_hanging_man | B3_next_day_breaks_to_new_high | 46 | 11 | 23.9% | 1.00 |
| high_hanging_man | B1_next_day_sunset_confirmation | 46 | 11 | 23.9% | 1.00 |
| evening_star_abandoned | B2_next_day_recovers_above_today_high | 668 | 160 | 24.0% | 1.00 |
| outside_three_black | B1_next_day_continues_lower | 75 | 18 | 24.0% | 1.00 |
| bear_engulfing | B1_next_day_weak_close_below_today_low | 325 | 78 | 24.0% | 1.00 |
| dark_double_star_anye | B1_next_day_continues_lower | 1469 | 354 | 24.1% | 1.00 |
| rising_falling | B1_next_day_step_continues | 5351 | 1295 | 24.2% | 1.00 |
| bear_engulfing | B2_next_day_rally_above_today_high | 325 | 79 | 24.3% | 1.00 |
| trapped | B1_next_day_continues_breakout_direction | 249 | 61 | 24.5% | 1.00 |
| gap_fill_up | B2_next_day_recovers | 4642 | 1143 | 24.6% | 1.00 |
| piercing_line | B2_next_day_full_reversal_engulfing | 5335 | 1324 | 24.8% | 1.00 |
| gap_fill_up | B1_next_day_continues_lower_after_fill | 4642 | 1172 | 25.2% | 1.00 |
| bull_engulfing | B1_next_day_strong_close_above_today_high | 47 | 12 | 25.5% | 1.00 |
| meeting | B2_next_day_reversal | 5463 | 1399 | 25.6% | 1.00 |
| biting | B2_next_day_falls_back | 6651 | 1714 | 25.8% | 1.00 |
| gap_reversal | B1_next_day_gap_holds_no_fill | 2449 | 633 | 25.8% | 1.00 |
| rising_falling | B2_next_day_falls_back | 5351 | 1400 | 26.2% | 1.00 |
| evening_star_abandoned | B1_next_day_continues_below_midpoint | 668 | 176 | 26.3% | 1.00 |
| neutral_engulfing | B1_next_day_direction_continuation | 523 | 138 | 26.4% | 1.00 |
| gap_under_pressure_reversal | B2_next_day_continues_below_gap | 3949 | 1050 | 26.6% | 1.00 |
| piercing_line | B1_next_day_confirms_penetration_direction | 5335 | 1429 | 26.8% | 1.00 |
| rebound | B2_next_day_reverses_again | 1984 | 535 | 27.0% | 1.00 |
| evening_star_island_reversal | B1_next_day_gap_down_continues | 249 | 68 | 27.3% | 1.00 |
| gap_fill_down | B2_next_day_falls_back | 4698 | 1283 | 27.3% | 1.00 |
| bull_engulfing | B2_next_day_fall_below_today_low | 47 | 13 | 27.7% | 1.00 |
| embracing | B2_next_day_breaks_opposite | 8247 | 2298 | 27.9% | 1.00 |
| two_crow_gap | B1_next_day_rising_three_method | 957 | 273 | 28.5% | 1.00 |
| trapped | B2_next_day_reverses | 249 | 75 | 30.1% | 1.00 |
| high_hanging_man | B2_next_day_gap_down_confirmation | 46 | 14 | 30.4% | 1.00 |
| outside_three_black | B2_next_day_gap_down | 75 | 23 | 30.7% | 1.00 |
| morning_star_harami | B3_next_day_drops_to_new_low | 875 | 269 | 30.7% | 1.00 |
| evening_star_island_reversal | B2_next_day_rallies_back_above_gap | 249 | 77 | 30.9% | 1.00 |
| breakout_double_star | B2_next_day_returns_to_consolidation | 327 | 104 | 31.8% | 1.00 |
| three_red_dadi_dangqian | B2_next_day_gap_down | 389 | 127 | 32.6% | 1.00 |
| breakout_double_star | B3_next_day_holds_above_breakout | 327 | 108 | 33.0% | 1.00 |
| morning_star_harami | B2_next_day_close_above_midpoint | 875 | 376 | 43.0% | 1.00 |
| evening_star_island_reversal | B3_next_day_drifts_lower | 249 | 110 | 44.2% | 1.00 |
| bull_engulfing | B3_next_day_consolidation | 47 | 22 | 46.8% | 1.00 |
| evening_star_abandoned | B3_next_day_stalls | 668 | 331 | 49.6% | 1.00 |

## Playbook Adjustment Recommendations

### Low Hit Rate Branches — Candidates for Removal/Review

- **B1_next_day_gap_holds_no_fill** (pattern: morning_star_island_reversal): hit_rate=11.5%, n_runs=288 → 考慮移除或重新檢視 when 條件
- **B3_next_day_stalls_above_today_low** (pattern: gap_reversal): hit_rate=14.5%, n_runs=2449 → 考慮移除或重新檢視 when 條件
- **B3_next_day_attempts_recovery** (pattern: outside_three_black): hit_rate=14.7%, n_runs=75 → 考慮移除或重新檢視 when 條件
- **B3_next_day_recovery_attempt** (pattern: three_red_dadi_dangqian): hit_rate=18.0%, n_runs=389 → 考慮移除或重新檢視 when 條件
- **B2_next_day_recovers_above_twin_high** (pattern: dark_double_star_anye): hit_rate=19.9%, n_runs=1469 → 考慮移除或重新檢視 when 條件
- **B1_next_day_continues_same_direction** (pattern: meeting): hit_rate=21.3%, n_runs=5463 → 考慮移除或重新檢視 when 條件
- **B1_next_day_continues_below_midpoint** (pattern: three_red_dadi_dangqian): hit_rate=21.9%, n_runs=389 → 考慮移除或重新檢視 when 條件
- **B1_next_day_continues_higher_after_fill** (pattern: gap_fill_down): hit_rate=22.0%, n_runs=4698 → 考慮移除或重新檢視 when 條件
- **B2_next_day_reversal** (pattern: neutral_engulfing): hit_rate=22.2%, n_runs=523 → 考慮移除或重新檢視 when 條件
- **B1_next_day_continues_power_direction** (pattern: embracing): hit_rate=22.2%, n_runs=8247 → 考慮移除或重新檢視 when 條件

### High Hit Rate Branches — Advisor 應重點顯示

- **B2_next_day_gap_filled** (pattern: morning_star_island_reversal): hit_rate=88.5%, n_runs=288 → 高可靠度，advisor 優先展示
- **B2_next_day_gap_filled** (pattern: gap_reversal): hit_rate=83.7%, n_runs=2449 → 高可靠度，advisor 優先展示
- **B1_next_day_gap_fills_up** (pattern: gap_under_pressure_reversal): hit_rate=83.0%, n_runs=3949 → 高可靠度，advisor 優先展示

## Light Firing Rates

| light_id | severity | n_fires | fire_rate |
|----------|----------|---------|-----------|
| pressure_layer_no_support | warn | 104370 | 90.9% |
| mountain_descent_four_types | warn | 54794 | 47.7% |
| top_formation_three_criteria | critical | 54794 | 47.7% |
| lowprice_first_pull_exit | warn | 51344 | 44.7% |
| zhongshu_recency_bias | info | 51344 | 44.7% |
| manipulator_distribution_warning | critical | 48823 | 42.5% |
| lack_of_power_distinction | info | 48758 | 42.5% |
| selling_pressure_dissolution_required | info | 48758 | 42.5% |
| weak_bull_trendline_only | info | 48758 | 42.5% |
| gap_down_falling_three | warn | 21006 | 18.3% |
| limit_up_next_day_stats | info | 7017 | 6.1% |
| new_high_next_day_attack_required | info | 5028 | 4.4% |
| high_pushup_next_step | info | 4925 | 4.3% |
| sunrise_vs_rising_three_boundary | info | 4925 | 4.3% |
| just_high_upper_shadow | info | 4669 | 4.1% |
| pressure_meeting_unresolved | warn | 3945 | 3.4% |
| pessimistic_stock_structural | warn | 3060 | 2.7% |
| high_black_k_warning | warn | 2893 | 2.5% |

## Output Files

- **DB**: `/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/data/analysis/kline_patterns/phase4_advisor_history.db`
- **CSV**: `/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/data/analysis/kline_patterns/phase4_branch_hit_rates.csv`
- **Report**: `/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/data/analysis/kline_patterns/phase4_report.md`

---
_Phase 4.3 backtest — only uses downloaded data, no new data fetched._