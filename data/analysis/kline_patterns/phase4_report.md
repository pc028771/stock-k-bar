# Phase 4.3 Advisor History Backtest Report

Generated: 2026-06-05 12:28:32

## Scope

- **Tickers**: 197 (top 200 most active by avg volume 2024+)
- **Date range**: 2024-01-01 to 2026-06-30
- **Ticker-days processed**: 114,782
- **Advisor runs saved**: 113,230
- **Branch rows**: 125,408 total / 125,408 backfilled
- **Elapsed (advisor pass)**: 10.4 min | (backfill pass): 20.4 min

## Branch Hit Rates

Total (pattern x branch_id) pairs with >= 10 runs: **69**

### High Confidence (>=80%) -- 3 branches

| pattern | branch_id | n_runs | n_matched | hit_rate | avg_matched_days |
|---------|-----------|--------|-----------|----------|-----------------|
| morning_star_island_reversal | B2_next_day_gap_filled | 281 | 248 | 88.3% | 1.00 |
| gap_reversal | B2_next_day_gap_filled | 2420 | 2006 | 82.9% | 1.00 |
| gap_under_pressure_reversal | B1_next_day_gap_fills_up | 3897 | 3222 | 82.7% | 1.00 |

### Medium Confidence (50-80%) -- 10 branches

| pattern | branch_id | n_runs | n_matched | hit_rate | avg_matched_days |
|---------|-----------|--------|-----------|----------|-----------------|
| attack_cost_displayed | B3_gap_attack | 506 | 397 | 78.5% | 1.36 |
| breakout_double_star | B1_next_day_gap_up_holds | 318 | 213 | 67.0% | 1.00 |
| morning_star_island_reversal | B3_next_day_encounters_overhead_supply | 281 | 186 | 66.2% | 1.00 |
| attack_cost_displayed | B4_push_attack | 506 | 296 | 58.5% | 1.03 |
| merged_doji | B1_gap_up_attack | 513 | 276 | 53.8% | 1.00 |
| merged_doji | B4_consolidation_wait | 513 | 267 | 52.0% | 1.00 |
| morning_star_harami | B1_next_day_gap_up_attack | 860 | 446 | 51.9% | 1.00 |
| bear_engulfing | B3_next_day_consolidation | 320 | 164 | 51.2% | 1.00 |
| piercing_line | B3_next_day_stalls | 5268 | 2694 | 51.1% | 1.00 |
| dark_double_star_anye | B3_next_day_stalls_within_range | 1450 | 732 | 50.5% | 1.00 |

### Low Confidence (<50%) -- Noise Candidates -- 56 branches

| pattern | branch_id | n_runs | n_matched | hit_rate | avg_matched_days |
|---------|-----------|--------|-----------|----------|-----------------|
| evening_star_abandoned | B3_next_day_stalls | 661 | 328 | 49.6% | 1.00 |
| bull_engulfing | B3_next_day_consolidation | 45 | 21 | 46.7% | 1.00 |
| morning_star_harami | B2_next_day_close_above_midpoint | 860 | 371 | 43.1% | 1.00 |
| evening_star_island_reversal | B3_next_day_drifts_lower | 251 | 108 | 43.0% | 1.00 |
| merged_doji | B3_break_merged_low | 513 | 219 | 42.7% | 1.00 |
| attack_cost_displayed | B1_next_day_holds_attack_cost | 506 | 216 | 42.7% | 1.00 |
| attack_cost_displayed | B2_next_day_breaks_attack_cost | 506 | 197 | 38.9% | 1.00 |
| three_red_dadi_dangqian | B2_next_day_gap_down | 388 | 127 | 32.7% | 1.00 |
| breakout_double_star | B3_next_day_holds_above_breakout | 318 | 104 | 32.7% | 1.00 |
| breakout_double_star | B2_next_day_returns_to_consolidation | 318 | 101 | 31.8% | 1.00 |
| morning_star_harami | B3_next_day_drops_to_new_low | 860 | 264 | 30.7% | 1.00 |
| high_hanging_man | B2_next_day_gap_down_confirmation | 46 | 14 | 30.4% | 1.00 |
| outside_three_black | B2_next_day_gap_down | 76 | 23 | 30.3% | 1.00 |
| trapped | B2_next_day_reverses | 245 | 74 | 30.2% | 1.00 |
| evening_star_island_reversal | B2_next_day_rallies_back_above_gap | 251 | 75 | 29.9% | 1.00 |
| bull_engulfing | B2_next_day_fall_below_today_low | 45 | 13 | 28.9% | 1.00 |
| two_crow_gap | B1_next_day_rising_three_method | 954 | 268 | 28.1% | 1.00 |
| embracing | B2_next_day_breaks_opposite | 8154 | 2267 | 27.8% | 1.00 |
| gap_fill_down | B2_next_day_falls_back | 4621 | 1264 | 27.4% | 1.00 |
| evening_star_island_reversal | B1_next_day_gap_down_continues | 251 | 68 | 27.1% | 1.00 |
| piercing_line | B1_next_day_confirms_penetration_direction | 5268 | 1416 | 26.9% | 1.00 |
| rebound | B2_next_day_reverses_again | 1963 | 523 | 26.6% | 1.00 |
| evening_star_abandoned | B1_next_day_continues_below_midpoint | 661 | 176 | 26.6% | 1.00 |
| gap_under_pressure_reversal | B2_next_day_continues_below_gap | 3897 | 1032 | 26.5% | 1.00 |
| rising_falling | B2_next_day_falls_back | 5227 | 1379 | 26.4% | 1.00 |
| neutral_engulfing | B1_next_day_direction_continuation | 510 | 133 | 26.1% | 1.00 |
| biting | B2_next_day_falls_back | 6511 | 1688 | 25.9% | 1.00 |
| gap_reversal | B1_next_day_gap_holds_no_fill | 2420 | 620 | 25.6% | 1.00 |
| meeting | B2_next_day_reversal | 5409 | 1378 | 25.5% | 1.00 |
| gap_fill_up | B1_next_day_continues_lower_after_fill | 4599 | 1170 | 25.4% | 1.00 |
| piercing_line | B2_next_day_full_reversal_engulfing | 5268 | 1305 | 24.8% | 1.00 |
| gap_fill_up | B2_next_day_recovers | 4599 | 1131 | 24.6% | 1.00 |
| bull_engulfing | B1_next_day_strong_close_above_today_high | 45 | 11 | 24.4% | 1.00 |
| bear_engulfing | B2_next_day_rally_above_today_high | 320 | 78 | 24.4% | 1.00 |
| dark_double_star_anye | B1_next_day_continues_lower | 1450 | 352 | 24.3% | 1.00 |
| rising_falling | B1_next_day_step_continues | 5227 | 1259 | 24.1% | 1.00 |
| trapped | B1_next_day_continues_breakout_direction | 245 | 59 | 24.1% | 1.00 |
| bear_engulfing | B1_next_day_weak_close_below_today_low | 320 | 77 | 24.1% | 1.00 |
| high_hanging_man | B1_next_day_sunset_confirmation | 46 | 11 | 23.9% | 1.00 |
| high_hanging_man | B3_next_day_breaks_to_new_high | 46 | 11 | 23.9% | 1.00 |
| outside_three_black | B1_next_day_continues_lower | 76 | 18 | 23.7% | 1.00 |
| two_crow_gap | B2_next_day_continues_lower | 954 | 225 | 23.6% | 1.00 |
| biting | B1_next_day_breakout_holds | 6511 | 1530 | 23.5% | 1.00 |
| evening_star_abandoned | B2_next_day_recovers_above_today_high | 661 | 155 | 23.4% | 1.00 |
| rebound | B1_next_day_continues_rebound_direction | 1963 | 449 | 22.9% | 1.00 |
| neutral_engulfing | B2_next_day_reversal | 510 | 116 | 22.7% | 1.00 |
| embracing | B1_next_day_continues_power_direction | 8154 | 1812 | 22.2% | 1.00 |
| gap_fill_down | B1_next_day_continues_higher_after_fill | 4621 | 1015 | 22.0% | 1.00 |
| three_red_dadi_dangqian | B1_next_day_continues_below_midpoint | 388 | 85 | 21.9% | 1.00 |
| meeting | B1_next_day_continues_same_direction | 5409 | 1152 | 21.3% | 1.00 |
| dark_double_star_anye | B2_next_day_recovers_above_twin_high | 1450 | 288 | 19.9% | 1.00 |
| merged_doji | B2_push_attack_above_merged_high | 513 | 101 | 19.7% | 1.00 |
| three_red_dadi_dangqian | B3_next_day_recovery_attempt | 388 | 69 | 17.8% | 1.00 |
| gap_reversal | B3_next_day_stalls_above_today_low | 2420 | 354 | 14.6% | 1.00 |
| outside_three_black | B3_next_day_attempts_recovery | 76 | 11 | 14.5% | 1.00 |
| morning_star_island_reversal | B1_next_day_gap_holds_no_fill | 281 | 33 | 11.7% | 1.00 |

## Playbook Adjustment Recommendations

### Low Hit Rate Branches -- Candidates for Removal/Review

- **B3_next_day_stalls** (pattern: evening_star_abandoned): hit_rate=49.6%, n_runs=661 -- 考慮移除或重新檢視 when 條件
- **B3_next_day_consolidation** (pattern: bull_engulfing): hit_rate=46.7%, n_runs=45 -- 考慮移除或重新檢視 when 條件
- **B2_next_day_close_above_midpoint** (pattern: morning_star_harami): hit_rate=43.1%, n_runs=860 -- 考慮移除或重新檢視 when 條件
- **B3_next_day_drifts_lower** (pattern: evening_star_island_reversal): hit_rate=43.0%, n_runs=251 -- 考慮移除或重新檢視 when 條件
- **B3_break_merged_low** (pattern: merged_doji): hit_rate=42.7%, n_runs=513 -- 考慮移除或重新檢視 when 條件
- **B1_next_day_holds_attack_cost** (pattern: attack_cost_displayed): hit_rate=42.7%, n_runs=506 -- 考慮移除或重新檢視 when 條件
- **B2_next_day_breaks_attack_cost** (pattern: attack_cost_displayed): hit_rate=38.9%, n_runs=506 -- 考慮移除或重新檢視 when 條件
- **B2_next_day_gap_down** (pattern: three_red_dadi_dangqian): hit_rate=32.7%, n_runs=388 -- 考慮移除或重新檢視 when 條件
- **B3_next_day_holds_above_breakout** (pattern: breakout_double_star): hit_rate=32.7%, n_runs=318 -- 考慮移除或重新檢視 when 條件
- **B2_next_day_returns_to_consolidation** (pattern: breakout_double_star): hit_rate=31.8%, n_runs=318 -- 考慮移除或重新檢視 when 條件

### High Hit Rate Branches -- Advisor 應重點顯示

- **B2_next_day_gap_filled** (pattern: morning_star_island_reversal): hit_rate=88.3%, n_runs=281 -- 高可靠度，advisor 優先展示
- **B2_next_day_gap_filled** (pattern: gap_reversal): hit_rate=82.9%, n_runs=2420 -- 高可靠度，advisor 優先展示
- **B1_next_day_gap_fills_up** (pattern: gap_under_pressure_reversal): hit_rate=82.7%, n_runs=3897 -- 高可靠度，advisor 優先展示

## Light Firing Rates

Note: `new_high_next_day_attack_required` and `pressure_meeting_unresolved` fire at 100% across all tickers -- likely always-true conditions, review YAML.

| light_id | severity | n_fires | fire_rate |
|----------|----------|---------|-----------|
| pressure_layer_no_support | warn | 44054 | 38.9% |
| zhongshu_recency_bias | info | 27055 | 23.9% |
| lt_attack_intent_zone_breakdown | warn | 10569 | 9.3% |
| lack_of_power_distinction | info | 9032 | 8.0% |
| weak_bull_trendline_only | info | 7027 | 6.2% |
| gap_down_falling_three | warn | 5657 | 5.0% |
| new_high_next_day_attack_required | info | 4961 | 4.4% |
| just_high_upper_shadow | info | 4619 | 4.1% |
| lt_attack_cost_breakdown | critical | 4314 | 3.8% |
| pressure_meeting_unresolved | warn | 3901 | 3.4% |
| pessimistic_stock_structural | warn | 3004 | 2.7% |
| mountain_descent_four_types | warn | 2908 | 2.6% |
| top_formation_three_criteria | critical | 2848 | 2.5% |
| lt_defensive_low_break | critical | 2311 | 2.0% |
| limit_up_next_day_stats | info | 1113 | 1.0% |
| sunrise_vs_rising_three_boundary | info | 763 | 0.7% |
| lt_merged_doji_low_break | warn | 681 | 0.6% |
| manipulator_distribution_warning | warn | 678 | 0.6% |
| lt_merged_doji_high_break | info | 570 | 0.5% |
| lowprice_first_pull_exit | warn | 425 | 0.4% |
| high_black_k_warning | warn | 264 | 0.2% |
| selling_pressure_dissolution_required | info | 238 | 0.2% |
| high_pushup_next_step | info | 7 | 0.0% |

## Anomalies Found

1. **Bug fixed in simulator**: `_backfill_single_ticker` had a type mismatch -- `date_to_pos` keys were `pd.Timestamp` but DB `trade_date` is `str`. Fix: normalise both to `YYYY-MM-DD` string. All 300 NULL branches are trailing-date edge cases with no future data.
2. **Two lights always fire (100%)**: `new_high_next_day_attack_required` and `pressure_meeting_unresolved`. Review their YAML definitions.
3. **avg_matched_days = 1.0 for all branches**: All branches use `next_day_n=1`, so matched_after_n_days is always 1 when matched. Extend `next_day_n` in playbooks for multi-day confirmation windows.
4. **pattern column = action_type proxy**: `advisor_branches` DB does not store the K-bar pattern name directly. `compute_branch_hit_rates` uses `action_type` (`exhaust_invalid`, `context_only_signal`, `watch_only`, `entry_signal`) as the `pattern` grouping column.

## Output Files

- **DB**: `/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/data/analysis/kline_patterns/phase4_advisor_history.db`
- **CSV**: `/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/data/analysis/kline_patterns/phase4_branch_hit_rates.csv`
- **Report**: `/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/data/analysis/kline_patterns/phase4_report.md`

---
_Phase 4.3 backtest -- only uses downloaded data, no new data fetched._