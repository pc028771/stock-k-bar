# Phase 4.3 Advisor History Backtest Report

Generated: 2026-06-05 19:47:42

## Scope

- **Tickers**: 200
- **Date range**: 2024-01-01 → 2026-06-30
- **Trading dates in range**: 585
- **Ticker-days processed**: 115,182
- **Advisor runs saved**: 115,182
- **Runs skipped** (idempotent): 0
- **Branch rows backfilled**: 127,513
- **Elapsed time**: 97.0 minutes

## Branch Hit Rates

Total (pattern × branch_id) pairs with ≥10 runs: **69**

### High Confidence (≥80%) — 3 branches

| pattern | branch_id | n_runs | n_matched | hit_rate | avg_matched_days |
|---------|-----------|--------|-----------|----------|-----------------|
| morning_star_island_reversal | B2_next_day_gap_filled | 288 | 255 | 88.5% | 1.00 |
| gap_under_pressure_reversal | B1_next_day_gap_fills_up | 3997 | 3279 | 82.0% | 1.00 |
| gap_reversal | B2_next_day_gap_filled | 2512 | 2052 | 81.7% | 1.00 |

### Medium Confidence (50–80%) — 9 branches

| pattern | branch_id | n_runs | n_matched | hit_rate | avg_matched_days |
|---------|-----------|--------|-----------|----------|-----------------|
| attack_cost_displayed | B3_gap_attack | 372 | 291 | 78.2% | 1.35 |
| breakout_double_star | B1_next_day_gap_up_holds | 327 | 218 | 66.7% | 1.00 |
| morning_star_island_reversal | B3_next_day_encounters_overhead_supply | 288 | 190 | 66.0% | 1.00 |
| attack_cost_displayed | B4_push_attack | 372 | 212 | 57.0% | 1.03 |
| merged_doji | B1_gap_up_attack | 529 | 283 | 53.5% | 1.00 |
| morning_star_harami | B1_next_day_gap_up_attack | 875 | 454 | 51.9% | 1.00 |
| merged_doji | B4_consolidation_wait | 529 | 274 | 51.8% | 1.00 |
| piercing_line | B3_next_day_stalls | 5342 | 2729 | 51.1% | 1.00 |
| bear_engulfing | B3_next_day_consolidation | 327 | 167 | 51.1% | 1.00 |

### Low Confidence (<50%) — Noise Candidates — 57 branches

| pattern | branch_id | n_runs | n_matched | hit_rate | avg_matched_days |
|---------|-----------|--------|-----------|----------|-----------------|
| morning_star_island_reversal | B1_next_day_gap_holds_no_fill | 288 | 33 | 11.5% | 1.00 |
| outside_three_black | B3_next_day_attempts_recovery | 79 | 11 | 13.9% | 1.00 |
| gap_reversal | B3_next_day_stalls_above_today_low | 2512 | 357 | 14.2% | 1.00 |
| three_red_dadi_dangqian | B3_next_day_recovery_attempt | 391 | 70 | 17.9% | 1.00 |
| merged_doji | B2_push_attack_above_merged_high | 529 | 101 | 19.1% | 1.00 |
| dark_double_star_anye | B2_next_day_recovers_above_twin_high | 1491 | 296 | 19.9% | 1.00 |
| meeting | B1_next_day_continues_same_direction | 5474 | 1164 | 21.3% | 1.00 |
| three_red_dadi_dangqian | B1_next_day_continues_below_midpoint | 391 | 85 | 21.7% | 1.00 |
| gap_fill_down | B1_next_day_continues_higher_after_fill | 4703 | 1034 | 22.0% | 1.00 |
| embracing | B1_next_day_continues_power_direction | 8265 | 1833 | 22.2% | 1.00 |
| neutral_engulfing | B2_next_day_reversal | 525 | 118 | 22.5% | 1.00 |
| outside_three_black | B1_next_day_continues_lower | 79 | 18 | 22.8% | 1.00 |
| rebound | B1_next_day_continues_rebound_direction | 1997 | 457 | 22.9% | 1.00 |
| high_hanging_man | B1_next_day_sunset_confirmation | 48 | 11 | 22.9% | 1.00 |
| high_hanging_man | B3_next_day_breaks_to_new_high | 48 | 11 | 22.9% | 1.00 |
| evening_star_abandoned | B2_next_day_recovers_above_today_high | 683 | 160 | 23.4% | 1.00 |
| biting | B1_next_day_breakout_holds | 6670 | 1568 | 23.5% | 1.00 |
| two_crow_gap | B2_next_day_continues_lower | 969 | 228 | 23.5% | 1.00 |
| trapped | B1_next_day_continues_breakout_direction | 255 | 61 | 23.9% | 1.00 |
| dark_double_star_anye | B1_next_day_continues_lower | 1491 | 358 | 24.0% | 1.00 |
| rising_falling | B1_next_day_step_continues | 5370 | 1296 | 24.1% | 1.00 |
| bear_engulfing | B2_next_day_rally_above_today_high | 327 | 79 | 24.2% | 1.00 |
| bear_engulfing | B1_next_day_weak_close_below_today_low | 327 | 79 | 24.2% | 1.00 |
| gap_fill_up | B2_next_day_recovers | 4708 | 1146 | 24.3% | 1.00 |
| piercing_line | B2_next_day_full_reversal_engulfing | 5342 | 1326 | 24.8% | 1.00 |
| gap_fill_up | B1_next_day_continues_lower_after_fill | 4708 | 1186 | 25.2% | 1.00 |
| gap_reversal | B1_next_day_gap_holds_no_fill | 2512 | 634 | 25.2% | 1.00 |
| evening_star_island_reversal | B1_next_day_gap_down_continues | 271 | 69 | 25.5% | 1.00 |
| bull_engulfing | B1_next_day_strong_close_above_today_high | 47 | 12 | 25.5% | 1.00 |
| meeting | B2_next_day_reversal | 5474 | 1403 | 25.6% | 1.00 |
| evening_star_abandoned | B1_next_day_continues_below_midpoint | 683 | 177 | 25.9% | 1.00 |
| biting | B2_next_day_falls_back | 6670 | 1730 | 25.9% | 1.00 |
| neutral_engulfing | B1_next_day_direction_continuation | 525 | 138 | 26.3% | 1.00 |
| gap_under_pressure_reversal | B2_next_day_continues_below_gap | 3997 | 1051 | 26.3% | 1.00 |
| rising_falling | B2_next_day_falls_back | 5370 | 1416 | 26.4% | 1.00 |
| piercing_line | B1_next_day_confirms_penetration_direction | 5342 | 1442 | 27.0% | 1.00 |
| rebound | B2_next_day_reverses_again | 1997 | 540 | 27.0% | 1.00 |
| gap_fill_down | B2_next_day_falls_back | 4703 | 1287 | 27.4% | 1.00 |
| bull_engulfing | B2_next_day_fall_below_today_low | 47 | 13 | 27.7% | 1.00 |
| embracing | B2_next_day_breaks_opposite | 8265 | 2304 | 27.9% | 1.00 |
| two_crow_gap | B1_next_day_rising_three_method | 969 | 273 | 28.2% | 1.00 |
| evening_star_island_reversal | B2_next_day_rallies_back_above_gap | 271 | 77 | 28.4% | 1.00 |
| high_hanging_man | B2_next_day_gap_down_confirmation | 48 | 14 | 29.2% | 1.00 |
| trapped | B2_next_day_reverses | 255 | 75 | 29.4% | 1.00 |
| outside_three_black | B2_next_day_gap_down | 79 | 24 | 30.4% | 1.00 |
| morning_star_harami | B3_next_day_drops_to_new_low | 875 | 269 | 30.7% | 1.00 |
| breakout_double_star | B2_next_day_returns_to_consolidation | 327 | 104 | 31.8% | 1.00 |
| three_red_dadi_dangqian | B2_next_day_gap_down | 391 | 127 | 32.5% | 1.00 |
| breakout_double_star | B3_next_day_holds_above_breakout | 327 | 108 | 33.0% | 1.00 |
| evening_star_island_reversal | B3_next_day_drifts_lower | 271 | 111 | 41.0% | 1.00 |
| merged_doji | B3_break_merged_low | 529 | 220 | 41.6% | 1.00 |
| attack_cost_displayed | B2_next_day_breaks_attack_cost | 372 | 158 | 42.5% | 1.00 |
| attack_cost_displayed | B1_next_day_holds_attack_cost | 372 | 159 | 42.7% | 1.00 |
| morning_star_harami | B2_next_day_close_above_midpoint | 875 | 376 | 43.0% | 1.00 |
| bull_engulfing | B3_next_day_consolidation | 47 | 22 | 46.8% | 1.00 |
| evening_star_abandoned | B3_next_day_stalls | 683 | 331 | 48.5% | 1.00 |
| dark_double_star_anye | B3_next_day_stalls_within_range | 1491 | 742 | 49.8% | 1.00 |

## Playbook Adjustment Recommendations

### Low Hit Rate Branches — Candidates for Removal/Review

- **B1_next_day_gap_holds_no_fill** (pattern: morning_star_island_reversal): hit_rate=11.5%, n_runs=288 → 考慮移除或重新檢視 when 條件
- **B3_next_day_attempts_recovery** (pattern: outside_three_black): hit_rate=13.9%, n_runs=79 → 考慮移除或重新檢視 when 條件
- **B3_next_day_stalls_above_today_low** (pattern: gap_reversal): hit_rate=14.2%, n_runs=2512 → 考慮移除或重新檢視 when 條件
- **B3_next_day_recovery_attempt** (pattern: three_red_dadi_dangqian): hit_rate=17.9%, n_runs=391 → 考慮移除或重新檢視 when 條件
- **B2_push_attack_above_merged_high** (pattern: merged_doji): hit_rate=19.1%, n_runs=529 → 考慮移除或重新檢視 when 條件
- **B2_next_day_recovers_above_twin_high** (pattern: dark_double_star_anye): hit_rate=19.9%, n_runs=1491 → 考慮移除或重新檢視 when 條件
- **B1_next_day_continues_same_direction** (pattern: meeting): hit_rate=21.3%, n_runs=5474 → 考慮移除或重新檢視 when 條件
- **B1_next_day_continues_below_midpoint** (pattern: three_red_dadi_dangqian): hit_rate=21.7%, n_runs=391 → 考慮移除或重新檢視 when 條件
- **B1_next_day_continues_higher_after_fill** (pattern: gap_fill_down): hit_rate=22.0%, n_runs=4703 → 考慮移除或重新檢視 when 條件
- **B1_next_day_continues_power_direction** (pattern: embracing): hit_rate=22.2%, n_runs=8265 → 考慮移除或重新檢視 when 條件

### High Hit Rate Branches — Advisor 應重點顯示

- **B2_next_day_gap_filled** (pattern: morning_star_island_reversal): hit_rate=88.5%, n_runs=288 → 高可靠度，advisor 優先展示
- **B1_next_day_gap_fills_up** (pattern: gap_under_pressure_reversal): hit_rate=82.0%, n_runs=3997 → 高可靠度，advisor 優先展示
- **B2_next_day_gap_filled** (pattern: gap_reversal): hit_rate=81.7%, n_runs=2512 → 高可靠度，advisor 優先展示

## Light Firing Rates

| light_id | severity | n_fires | fire_rate |
|----------|----------|---------|-----------|
| zhongshu_recency_bias | info | 27369 | 23.8% |
| lt_attack_intent_zone_breakdown | warn | 10741 | 9.3% |
| lt_attack_cost_breakdown | critical | 8952 | 7.8% |
| gap_down_falling_three | warn | 5762 | 5.0% |
| new_high_next_day_attack_required | info | 5051 | 4.4% |
| just_high_upper_shadow | info | 4699 | 4.1% |
| pressure_layer_no_support | warn | 3974 | 3.5% |
| pressure_meeting_unresolved | warn | 3974 | 3.5% |
| pessimistic_stock_structural | warn | 3060 | 2.7% |
| mountain_descent_four_types | warn | 2960 | 2.6% |
| top_formation_three_criteria | critical | 2901 | 2.5% |
| lt_defensive_low_break | critical | 2347 | 2.0% |
| limit_up_next_day_stats | info | 1136 | 1.0% |
| sunrise_vs_rising_three_boundary | info | 784 | 0.7% |
| manipulator_distribution_warning | warn | 696 | 0.6% |
| weak_bull_trendline_only | info | 476 | 0.4% |
| lowprice_first_pull_exit | warn | 426 | 0.4% |
| high_black_k_warning | warn | 274 | 0.2% |
| lack_of_power_distinction | info | 148 | 0.1% |
| lt_merged_doji_low_break | warn | 87 | 0.1% |
| lt_merged_doji_high_break | info | 82 | 0.1% |
| selling_pressure_dissolution_required | info | 57 | 0.0% |

## Output Files

- **DB**: `/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/data/analysis/kline_patterns/phase4_advisor_history.db`
- **CSV**: `/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/data/analysis/kline_patterns/phase4_branch_hit_rates.csv`
- **Report**: `/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/data/analysis/kline_patterns/phase4_report.md`

---
_Phase 4.3 backtest — only uses downloaded data, no new data fetched._