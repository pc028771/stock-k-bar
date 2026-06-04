# Phase 4.3 Advisor History Backtest Report

Generated: 2026-06-03 20:15:37

## Scope

- **Tickers**: 200 (top 200 most active by avg volume 2024+)
- **Date range**: 2024-01-01 to 2026-06-30
- **Ticker-days processed**: 114,782
- **Advisor runs saved**: 114,782
- **Branch rows**: 123,454 total / 123,154 backfilled
- **Elapsed (advisor pass)**: 10.4 min | (backfill pass): 20.4 min

## Branch Hit Rates

Total (pattern x branch_id) pairs with >= 10 runs: **52**

### High Confidence (>=80%) -- 2 branches

| pattern | branch_id | n_runs | n_matched | hit_rate | avg_matched_days |
|---------|-----------|--------|-----------|----------|-----------------|
| exhaust_invalid | B2_next_day_gap_filled | 2737 | 2305 | 84.2% | 1.00 |
| exhaust_invalid | B1_next_day_gap_fills_up | 3949 | 3277 | 83.0% | 1.00 |

### Medium Confidence (50-80%) -- 7 branches

| pattern | branch_id | n_runs | n_matched | hit_rate | avg_matched_days |
|---------|-----------|--------|-----------|----------|-----------------|
| context_only_signal | B1_next_day_gap_up_holds | 327 | 218 | 66.7% | 1.00 |
| watch_only | B3_next_day_encounters_overhead_supply | 288 | 190 | 66.0% | 1.00 |
| entry_signal | B1_gap_up_attack | 100 | 57 | 57.0% | 1.00 |
| context_only_signal | B1_next_day_gap_up_attack | 875 | 454 | 51.9% | 1.00 |
| watch_only | B3_next_day_stalls | 6003 | 3052 | 50.8% | 1.00 |
| watch_only | B3_next_day_consolidation | 372 | 189 | 50.8% | 1.00 |
| watch_only | B3_next_day_stalls_within_range | 1469 | 735 | 50.0% | 1.00 |

### Low Confidence (<50%) -- Noise Candidates -- 43 branches

| pattern | branch_id | n_runs | n_matched | hit_rate | avg_matched_days |
|---------|-----------|--------|-----------|----------|-----------------|
| watch_only | B3_next_day_drifts_lower | 249 | 110 | 44.2% | 1.00 |
| context_only_signal | B2_next_day_close_above_midpoint | 875 | 376 | 43.0% | 1.00 |
| watch_only | B3_next_day_holds_above_breakout | 327 | 108 | 33.0% | 1.00 |
| context_only_signal | B2_next_day_gap_down | 464 | 150 | 32.3% | 1.00 |
| exhaust_invalid | B2_next_day_returns_to_consolidation | 327 | 104 | 31.8% | 1.00 |
| exhaust_invalid | B2_next_day_rallies_back_above_gap | 249 | 77 | 30.9% | 1.00 |
| exhaust_invalid | B3_next_day_drops_to_new_low | 875 | 269 | 30.7% | 1.00 |
| context_only_signal | B2_next_day_gap_down_confirmation | 46 | 14 | 30.4% | 1.00 |
| exhaust_invalid | B2_next_day_reverses | 249 | 75 | 30.1% | 1.00 |
| exhaust_invalid | B1_next_day_rising_three_method | 957 | 273 | 28.5% | 1.00 |
| context_only_signal | B2_next_day_breaks_opposite | 8247 | 2298 | 27.9% | 1.00 |
| exhaust_invalid | B2_next_day_fall_below_today_low | 47 | 13 | 27.7% | 1.00 |
| context_only_signal | B1_next_day_gap_down_continues | 249 | 68 | 27.3% | 1.00 |
| exhaust_invalid | B2_next_day_reverses_again | 1984 | 535 | 27.0% | 1.00 |
| context_only_signal | B1_next_day_confirms_penetration_direction | 5335 | 1429 | 26.8% | 1.00 |
| context_only_signal | B2_next_day_continues_below_gap | 3949 | 1050 | 26.6% | 1.00 |
| context_only_signal | B1_next_day_direction_continuation | 523 | 138 | 26.4% | 1.00 |
| exhaust_invalid | B2_next_day_falls_back | 16700 | 4397 | 26.3% | 1.00 |
| context_only_signal | B1_next_day_strong_close_above_today_high | 47 | 12 | 25.5% | 1.00 |
| context_only_signal | B2_next_day_reversal | 5986 | 1515 | 25.3% | 1.00 |
| context_only_signal | B1_next_day_continues_lower_after_fill | 4642 | 1172 | 25.2% | 1.00 |
| exhaust_invalid | B2_next_day_full_reversal_engulfing | 5335 | 1324 | 24.8% | 1.00 |
| context_only_signal | B1_next_day_continues_below_midpoint | 1057 | 261 | 24.7% | 1.00 |
| exhaust_invalid | B2_next_day_recovers | 4642 | 1143 | 24.6% | 1.00 |
| context_only_signal | B1_next_day_continues_breakout_direction | 249 | 61 | 24.5% | 1.00 |
| context_only_signal | B1_next_day_gap_holds_no_fill | 2737 | 666 | 24.3% | 1.00 |
| exhaust_invalid | B2_next_day_rally_above_today_high | 325 | 79 | 24.3% | 1.00 |
| context_only_signal | B1_next_day_step_continues | 5351 | 1295 | 24.2% | 1.00 |
| context_only_signal | B1_next_day_continues_lower | 1544 | 372 | 24.1% | 1.00 |
| context_only_signal | B1_next_day_weak_close_below_today_low | 325 | 78 | 24.0% | 1.00 |
| exhaust_invalid | B2_next_day_recovers_above_today_high | 668 | 160 | 24.0% | 1.00 |
| context_only_signal | B1_next_day_sunset_confirmation | 46 | 11 | 23.9% | 1.00 |
| exhaust_invalid | B3_next_day_breaks_to_new_high | 46 | 11 | 23.9% | 1.00 |
| context_only_signal | B2_next_day_continues_lower | 957 | 228 | 23.8% | 1.00 |
| context_only_signal | B1_next_day_breakout_holds | 6651 | 1566 | 23.5% | 1.00 |
| context_only_signal | B1_next_day_continues_rebound_direction | 1984 | 457 | 23.0% | 1.00 |
| context_only_signal | B1_next_day_continues_power_direction | 8247 | 1830 | 22.2% | 1.00 |
| context_only_signal | B1_next_day_continues_higher_after_fill | 4698 | 1032 | 22.0% | 1.00 |
| context_only_signal | B1_next_day_continues_same_direction | 5463 | 1163 | 21.3% | 1.00 |
| exhaust_invalid | B2_next_day_recovers_above_twin_high | 1469 | 293 | 19.9% | 1.00 |
| exhaust_invalid | B3_next_day_recovery_attempt | 389 | 70 | 18.0% | 1.00 |
| exhaust_invalid | B3_next_day_attempts_recovery | 75 | 11 | 14.7% | 1.00 |
| watch_only | B3_next_day_stalls_above_today_low | 2449 | 356 | 14.5% | 1.00 |

## Playbook Adjustment Recommendations

### Low Hit Rate Branches -- Candidates for Removal/Review

- **B3_next_day_drifts_lower** (pattern: watch_only): hit_rate=44.2%, n_runs=249 -- 考慮移除或重新檢視 when 條件
- **B2_next_day_close_above_midpoint** (pattern: context_only_signal): hit_rate=43.0%, n_runs=875 -- 考慮移除或重新檢視 when 條件
- **B3_next_day_holds_above_breakout** (pattern: watch_only): hit_rate=33.0%, n_runs=327 -- 考慮移除或重新檢視 when 條件
- **B2_next_day_gap_down** (pattern: context_only_signal): hit_rate=32.3%, n_runs=464 -- 考慮移除或重新檢視 when 條件
- **B2_next_day_returns_to_consolidation** (pattern: exhaust_invalid): hit_rate=31.8%, n_runs=327 -- 考慮移除或重新檢視 when 條件
- **B2_next_day_rallies_back_above_gap** (pattern: exhaust_invalid): hit_rate=30.9%, n_runs=249 -- 考慮移除或重新檢視 when 條件
- **B3_next_day_drops_to_new_low** (pattern: exhaust_invalid): hit_rate=30.7%, n_runs=875 -- 考慮移除或重新檢視 when 條件
- **B2_next_day_gap_down_confirmation** (pattern: context_only_signal): hit_rate=30.4%, n_runs=46 -- 考慮移除或重新檢視 when 條件
- **B2_next_day_reverses** (pattern: exhaust_invalid): hit_rate=30.1%, n_runs=249 -- 考慮移除或重新檢視 when 條件
- **B1_next_day_rising_three_method** (pattern: exhaust_invalid): hit_rate=28.5%, n_runs=957 -- 考慮移除或重新檢視 when 條件

### High Hit Rate Branches -- Advisor 應重點顯示

- **B2_next_day_gap_filled** (pattern: exhaust_invalid): hit_rate=84.2%, n_runs=2737 -- 高可靠度，advisor 優先展示
- **B1_next_day_gap_fills_up** (pattern: exhaust_invalid): hit_rate=83.0%, n_runs=3949 -- 高可靠度，advisor 優先展示

## Light Firing Rates

Note: `new_high_next_day_attack_required` and `pressure_meeting_unresolved` fire at 100% across all tickers -- likely always-true conditions, review YAML.

| light_id | severity | n_fires | fire_rate |
|----------|----------|---------|-----------|
| new_high_next_day_attack_required | info | 114782 | 100.0% |
| pressure_meeting_unresolved | warn | 114782 | 100.0% |
| pressure_layer_no_support | warn | 109398 | 95.3% |
| high_black_k_warning | warn | 61473 | 53.6% |
| limit_up_next_day_stats | info | 59988 | 52.3% |
| mountain_descent_four_types | warn | 54794 | 47.7% |
| top_formation_three_criteria | critical | 54794 | 47.7% |
| high_pushup_next_step | info | 53683 | 46.8% |
| lack_of_power_distinction | info | 53683 | 46.8% |
| selling_pressure_dissolution_required | info | 53683 | 46.8% |
| sunrise_vs_rising_three_boundary | info | 53683 | 46.8% |
| weak_bull_trendline_only | info | 53683 | 46.8% |
| lowprice_first_pull_exit | warn | 51344 | 44.7% |
| zhongshu_recency_bias | info | 51344 | 44.7% |
| manipulator_distribution_warning | critical | 48823 | 42.5% |
| just_high_upper_shadow | info | 44464 | 38.7% |
| gap_down_falling_three | warn | 21006 | 18.3% |
| pessimistic_stock_structural | warn | 3060 | 2.7% |

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