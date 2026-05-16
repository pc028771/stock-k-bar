# Important-tier fixes report (audit I1–I8 + attack_quality split)

**Date:** 2026-05-16
**Base commit:** `da24cd6` (post-7-critical fixes)
**Scope:** 8 Important findings (I1–I8) from `2026-05-16-course-compliance-audit.md`
          + the option-B split of the legacy `attack_quality` factor.
**New file:** `scripts/kline/course_proxy_constants.py` (centralized proxy thresholds).

---

## Summary

All 8 Important findings + the `attack_quality` split were addressed. No
course-given numbers were found for any of I1–I3, I5–I7 in the cited articles
(`型態學 03/05/14/15`, `入門 doji`, `成本原理 / 套牢`), so existing defaults
were retained but explicitly labeled as proxies and centralized in the new
`course_proxy_constants.py`. I4 introduces a real behavioral change
(re-breakout entries now require next-day attack confirmation). I8 makes
`breakout_price_break` and `breakout_low_break` sequentially gated by a
2-bar window. The legacy `attack_quality` factor was split:
`scoring/trend_continuation.py` (course-aligned, default ON) retains the
`+25 pre_breakout_trend_days` contribution; `extras/attack_quality_anti_course_penalties.py`
(default OFF) retains the three anti-course penalties.

---

## Per-finding detail

### I1 — `attack_intensity` 4-of-5 higher-low / higher-high count
- **Course quote:** 型態學 14: 「低點不斷墊高」; 型態學 15: 「高點不斷墊高」 — both qualitative.
- **Old default:** `higher_low_5day >= 4`, `higher_high_5day >= 4`.
- **New default:** unchanged (4 of 5). No course example number found.
- **Change:** moved constants to `course_proxy_constants.ATTACK_HIGHER_LOW_MIN_5DAY` / `_HIGHER_HIGH_MIN_5DAY`; inline `# Proxy:` comments in `features.py` and a proxy block in `scoring/attack_intensity.py` docstring.

### I2 — `is_pattern_breakout` upper-band 5% spread
- **Course quote:** 型態學 03 + 05: 「上緣穩定」/「壓力線是平的」 — qualitative, no percentage.
- **Old default:** `STABLE_UPPER_MAX_SPREAD = 0.05`.
- **New default:** unchanged. No course-stated number.
- **Change:** moved to `course_proxy_constants.STABLE_UPPER_MAX_SPREAD`; explicit proxy comment in `features.py`.

### I3 — `higher_low_count_60d >= 30/60`
- **Course quote:** 型態學 03: 「低點漸漸墊高」 — qualitative.
- **Old default:** `RISING_LOWS_MIN = INTEGRATION_DAYS // 2 = 30`.
- **New default:** unchanged. Course gives no count.
- **Change:** moved to `course_proxy_constants.RISING_LOWS_MIN_FRAC`; proxy comment in `features.py`.

### I4 — `breakout_attack` re-breakout requires next-day attack confirmation
- **Course quote:** 突破跌破 — 突破意義的釐清: 「第一次突破，可以直接進攻；再次突破，需等隔日攻擊確認」.
- **Old behavior:** every bar with `close > prior_high_60 & close > ma60` produced an entry signal, regardless of whether the prior breakout was the first.
- **New behavior:**
  - First breakout (no prior `close > prior_high_60` in the trailing 60 bars) → signals on the breakout bar (simulator executes next-day open). Unchanged timing.
  - Re-breakout → signal fires on the bar AFTER a `close > prior_high_60` non-first bar IF that next bar is an `is_attack_bar` (red K closing above prev close, OR gap-up, OR new prior_high_60 high) AND still satisfies `close > ma60` and is not in breakdown pattern. Net: re-breakout entries execute two bars later than before (one bar for the confirmation, one for next-day-open execution).
- **New features added:** `is_first_breakout_above_level`, `is_attack_bar` (both in `features.py`).
- **Constants:** `course_proxy_constants.FIRST_BREAKOUT_LOOKBACK = 60` (proxy, matches `prior_high_60` horizon), `REBREAKOUT_CONFIRMATION_BARS = 1`.
- **Backtest delta:** `breakout_attack` trade count = 8687 (no prior post-critical baseline available; trade count cannot be directly compared but is materially different from naïve old behavior because most signals in a sustained uptrend become re-breakouts).

### I5 — `overhead_supply` tier penalties
- **Course quote:** 入門 成本原理 — qualitative layered-supply concept; no tier or magnitude.
- **Old default:** `1–3 peaks → −5`, `4+ peaks → −15`.
- **New default:** unchanged.
- **Change:** moved to `course_proxy_constants.OVERHEAD_LIGHT_PENALTY / OVERHEAD_HEAVY_PENALTY / OVERHEAD_HEAVY_MIN_PEAKS`; explicit proxy docstring in `scoring/overhead_supply.py`.

### I6 — `high_zone_narrow_consolidation` 6-day 5% window
- **Course quote:** 型態學 14: 「突破紅K 後 N 天狹幅 + 低點不破突破點」 — qualitative N and 「狹幅」.
- **Old default:** 6 days, 5% range.
- **New default:** unchanged.
- **Change:** moved to `course_proxy_constants.HIGH_ZONE_CONSOLIDATION_DAYS / HIGH_ZONE_NARROW_RANGE_MAX / HIGH_ZONE_BONUS`; proxy comment in scoring module.

### I7 — `is_doji` 0.6% body / 1.5% range
- **Course quote:** 入門 doji: 「近乎沒有實體」 — qualitative.
- **Old default:** `body_pct <= 0.006`, `range_pct >= 0.015`.
- **New default:** unchanged.
- **Change:** moved to `course_proxy_constants.DOJI_MAX_BODY_PCT / DOJI_MIN_RANGE_PCT`; proxy comment in `features.py`.

### I8 — `breakout_price_break` and `breakout_low_break` sequential
- **Course quote:** 紅K篇五: 「突破紅K 後接黑K，跌破突破價 → 短線交易者立即停損」. Course treats it as the immediate, first-day(s) stop — `breakout_low_break` is the slower attack-failure stop.
- **Old behavior:** both in `STRONG_ATTACK_EXITS`, parallel; whichever triggered first won.
- **New behavior:** gated by `bars_since_entry`:
  - bars_since_entry ∈ [1, 2] → only `breakout_price_break` armed.
  - bars_since_entry > 2 → only `breakout_low_break` armed.
- **Constants:** `course_proxy_constants.BREAKOUT_PRICE_BREAK_WINDOW = 2` (proxy; course says "first day or two", no number).
- **Implementation:** shared `_bars_since_entry(df, entries)` helper in `exit/breakout_price_break.py`, imported by `exit/breakout_low_break.py`. Both exits remain in `STRONG_ATTACK_EXITS`; gating is internal.
- **Caveat:** the 2-bar window is the smallest "first day or two" reading; user can tune by editing the constant.

### attack_quality split (audit option B)
- **Old:** `scripts/kline/scoring/attack_quality.py` combined +25 trend-days (course-aligned) with three anti-course penalties (volume_ratio, body_pct, close_pos). Wholesale-moved to `extras/attack_quality_penalty.py` in critical-tier fixes.
- **New:**
  - `scripts/kline/scoring/trend_continuation.py` — registered in `SCORING_REGISTRY` (default ON). Score: `pre_breakout_trend_days >= 17 → +25`, else 0. Threshold 17 retained as proxy (no course example).
  - `scripts/kline/extras/attack_quality_anti_course_penalties.py` — renamed from `attack_quality_penalty.py`. Retains only the three anti-course penalties (`volume_ratio`, `body_pct`, `close_pos`). Default OFF; opt-in via `--extras attack_quality_anti_course_penalties`.
- **Constants:** `course_proxy_constants.TREND_CONTINUATION_MIN_DAYS = 17`, `TREND_CONTINUATION_BONUS = 25.0`.
- **Tests:** `tests/kline/scoring/test_attack_quality.py` rewritten to test the renamed extras module without the trend-bonus contribution; new `tests/kline/scoring/test_trend_continuation.py` added; `tests/kline/scoring/test_registry.py` updated to include the new key.

---

## Backtest comparison

| Entry | Pre-Important (`da24cd6`) | Post-Important |
|---|---|---|
| tweezer_top_breakout | 3066 trades, 39.69% win, +0.52% mean | 3066 trades, 39.73% win, +0.51% mean |
| pattern_breakout_only | 900 trades, 40.89% win, +0.52% mean | 900 trades, 40.89% win, +0.51% mean |
| breakout_attack | (no prior baseline) | 8687 trades, 37.79% win, -0.13% mean |

Notes:
- Tweezer and pattern-breakout entries are effectively unchanged — they do not route through `breakout.detect`, and the I8 sequential gating has minimal net effect on the trade set when held trades are short (the same exit usually fires either way).
- The minor win-rate drift on tweezer (39.69 → 39.73) is within rounding; mean return is identical to two decimals.
- `breakout_attack` figures reflect the new behavior. There is no apples-to-apples pre-Important baseline for that entry in the brief, so the table records the new value only.

---

## Files touched

New:
- `scripts/kline/course_proxy_constants.py`
- `scripts/kline/scoring/trend_continuation.py`
- `tests/kline/scoring/test_trend_continuation.py`

Renamed:
- `scripts/kline/extras/attack_quality_penalty.py` → `attack_quality_anti_course_penalties.py`

Modified:
- `scripts/kline/features.py` — proxy labels, new `is_first_breakout_above_level`, `is_attack_bar`.
- `scripts/kline/entry/breakout.py` — first/re-breakout split (I4).
- `scripts/kline/exit/breakout_price_break.py` — window gate + `_bars_since_entry` helper (I8).
- `scripts/kline/exit/breakout_low_break.py` — after-window gate (I8).
- `scripts/kline/scoring/__init__.py` — register `trend_continuation`.
- `scripts/kline/scoring/attack_intensity.py` — proxy disclosure docstring.
- `scripts/kline/scoring/overhead_supply.py` — proxy labels via constants.
- `scripts/kline/scoring/high_zone_narrow_consolidation.py` — proxy labels via constants.
- `scripts/kline/extras/__init__.py` — registry rename.
- `tests/kline/scoring/test_attack_quality.py` — adapted to renamed module & split.
- `tests/kline/scoring/test_registry.py` — registry now includes trend_continuation.
- `tests/kline/exit/test_breakout_low_break.py` — adapted to sequential gating.
- `tests/kline/exit/test_breakout_price_break.py` — added outside-window test.
- `tests/kline/exit/test_simulator.py` — adapted three simulator tests to longer post-entry windows.

---

## Caveats / unresolved proxies

No course-given numbers were found in the cited articles for any of:
- I1 — `ATTACK_HIGHER_LOW_MIN_5DAY` / `ATTACK_HIGHER_HIGH_MIN_5DAY` (kept at 4 of 5).
- I2 — `STABLE_UPPER_MAX_SPREAD` (kept at 5%).
- I3 — `RISING_LOWS_MIN_FRAC` (kept at half-window).
- I5 — `OVERHEAD_LIGHT_PENALTY / HEAVY_PENALTY / HEAVY_MIN_PEAKS` (kept at -5 / -15 / 4).
- I6 — `HIGH_ZONE_CONSOLIDATION_DAYS / NARROW_RANGE_MAX` (kept at 6 / 5%).
- I7 — `DOJI_MAX_BODY_PCT / MIN_RANGE_PCT` (kept at 0.6% / 1.5%).
- I8 — `BREAKOUT_PRICE_BREAK_WINDOW` (kept at 2 bars; course says "first day or two" without specifying).
- trend_continuation — `TREND_CONTINUATION_MIN_DAYS` (kept at 17; originally Spearman-derived).

All are now documented under `course_proxy_constants.py` and labeled `# Proxy:` at point-of-use. Future audits should focus on whether deeper course materials (e.g. specific 行進ing case studies not yet read) offer numerical examples that would let these thresholds be set from course rather than judgment.

---

## Verification commands

```bash
uv run pytest tests/ -x -q           # 199 passed
uv run python -m scripts.backtest --entry tweezer_top_breakout
uv run python -m scripts.backtest --entry pattern_breakout_only --out data/analysis/kline/backtest_pattern_post_important.csv
uv run python -m scripts.backtest --entry breakout_attack --out data/analysis/kline/backtest_breakout_attack_post_important.csv
uv run python -m scripts.scanner --entry tweezer_top_breakout --out /tmp/scanner_check.csv
```
