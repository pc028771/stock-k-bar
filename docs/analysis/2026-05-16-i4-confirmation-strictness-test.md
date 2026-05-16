# I4 Re-breakout Confirmation: Strictness Test

**Date:** 2026-05-16
**Context:** Audit I4 introduced "再突破需隔日攻擊確認" gating in `breakout.py`. Post-fix backtest showed `breakout_attack` mean return dropped from +0.050% to −0.125%. Hypothesis: the OR-form `is_attack_bar` (72% pass rate next-day after re-breakout) is too loose to actually filter for quality.

## Test

Restrict `is_attack_bar` to its strictest sub-option — **新高 only** (`high > prior_high_60`) — and re-run.

## Result

| Variant | n | win% | mean ret |
|---|---:|---:|---:|
| baseline (pre-Important, no I4) | 11,398 | 37.73% | +0.050% |
| post-Important (broad OR) | 8,687 | 37.79% | −0.125% |
| option B (new-high only) | 8,390 | 37.69% | −0.128% |

Tightening dropped 297 more trades and produced **no improvement** in win% or mean ret.

## Diagnosis

The mean-return drag is not caused by loose confirmation. It comes from the **shift-by-one-bar entry timing**:

- 84% of `breakout_attack` raw breakouts (close > prior_high_60) are re-breakouts.
- In this Taiwan dataset, re-breakouts mostly are real continuations.
- Waiting one bar costs entry-price alpha regardless of how the confirmation bar is defined.

## Decision

**Revert to broad-OR `is_attack_bar`.** Reasons:
1. Course literally states three OR-options. Broad form is the faithful reading.
2. Option B (strict) showed no empirical benefit.
3. I4 only affects `breakout_attack` (the course-loose entry). The two recommended entries — `tweezer_top_breakout` and `pattern_breakout_only` — bypass this code path and were unaffected (39.73% / 40.89% win, +0.51% mean).

## Note for future calibration

If a more selective `breakout_attack` is wanted later, the right lever is probably **not** the confirmation criterion but a stricter `is_first_breakout_above_level` window, or moving `breakout_attack` itself to extras / `course_loose` namespace and defaulting users to `pattern_breakout_only`.

This finding is informational; no further action taken in this session.
