# Critical Course-Compliance Fixes Report

**Date:** 2026-05-16
**Branch:** main (uncommitted)
**Audit source:** `docs/analysis/2026-05-16-course-compliance-audit.md`

Fixed all 7 Critical findings (C1–C7). No Important/Minor items touched.

Per coordinator instructions: every non-course detector was **physically
moved** to `scripts/kline/extras/`, not just deregistered. Each moved file
declares its non-course nature in the module docstring and is registered in
the appropriate extras registry so it can still be exercised via
`--extras <name>`.

---

## C1 — `prev_day_low_break` attack-meaning gate

**Course rule:** 紅K篇(二) / 買點與攻擊研判 — "前一日低點" only counts as
an attack stop when the previous bar had 攻擊意義 (red K at new 60-day high,
upper-shadow K at new high, or doji follow-up after a red attack K).

**Files touched**
- `scripts/kline/features.py` — added `prev_bar_had_attack_meaning` derived
  column (OR of three course conditions).
- `scripts/kline/exit/prev_day_low_break.py` — gate trigger by
  `prev_bar_had_attack_meaning`; if column missing, fire never (conservative).
- `tests/kline/exit/test_prev_day_low_break.py` — replaced 2-case unconditional
  test with 4-case set covering: with-gate fires, without-gate does NOT fire,
  at-prev-low does NOT fire, missing-column does NOT fire.

**Before:**
```python
return (df["close"] < df["prev_low"]).fillna(False)
```

**After:**
```python
broke = df["close"] < df["prev_low"]
gate = df["prev_bar_had_attack_meaning"].fillna(False).astype(bool)
return (broke & gate).fillna(False)
```

**Test impact:** existing test pinned the old (no-gate) behavior; rewritten
with explicit gate column. All other tests pass.

---

## C2 — `gap_fill` (market-adjusted excess gap) moved to extras

**Course rule:** 跳空篇(二) defines attack-gap-filled as **close below
attack_gap_lower** (= prev_high on gap-up day) — a cross-day comparison.
The course never invokes market_open_ret. The `gap_attack_filled` detector
is the course-faithful version.

**Files touched**
- `scripts/kline/exit/gap_fill.py` → **moved to** `scripts/kline/extras/gap_fill_excess_market_adjusted.py`.
  Docstring updated to declare non-course nature and reference the audit.
  Added `make_mark(arg)` factory matching extras registry signature.
- `scripts/kline/exit/__init__.py` — removed import + EXIT_REGISTRY entry.
- `scripts/kline/exit/groups.py` — removed `"gap_fill"` from STRONG_ATTACK_EXITS;
  added a comment pointing to the course-faithful `gap_attack_filled` and the
  extras-enabled comparison toggle.
- `scripts/kline/extras/__init__.py` — registered as
  `gap_fill_excess_market_adjusted` in EXIT_REGISTRY.
- `tests/kline/exit/test_gap_fill.py` — import path → `kline.extras.gap_fill_excess_market_adjusted`.
- `tests/kline/exit/test_simulator.py` — import path updated; clarified
  comment that this is now an extras-only synthetic exit.
- `tests/kline/exit/test_registry.py` — removed `"gap_fill"` from expected set;
  added negative assertion.

**Enable via:** `--extras gap_fill_excess_market_adjusted`

---

## C3 — `neckline_break` (crude prior_low_20) moved to extras

**Course rule:** 型態學 頭部型態 + 行進ing 事件七 — a neckline = 季線下彎
後的前一個低點 AND that low has ≥ 3 months of overhead 套牢. `ma60_neckline`
already implements the course-precise version.

**Files touched**
- `scripts/kline/exit/neckline_break.py` → **moved to** `scripts/kline/extras/neckline_break_crude.py`.
  Docstring updated. Added `make_mark(arg)` factory.
- `scripts/kline/exit/__init__.py` — removed.
- `scripts/kline/exit/groups.py` — removed `"neckline_break"` from
  TREND_CHANGE_EXITS; added migration comment.
- `scripts/kline/extras/__init__.py` — registered as `neckline_break_crude_proxy`.
- `tests/kline/exit/test_neckline_break.py` — import path updated.
- `tests/kline/exit/test_registry.py` — removed `"neckline_break"`; added
  negative assertion.
- `tests/kline/exit/test_groups.py` — no change needed (already had
  `ma60_neckline in trend` assertion).

**Enable via:** `--extras neckline_break_crude_proxy`

---

## C4 — `attack_quality` scoring moved to extras

**Course rule:** 突破跌破 — 突破意義的釐清:
> 「對於K線圖來說，價格才是最重要的事情，不需要加上成交量」
> 「與這一根突破的K線是否長紅、有沒有上影線都無關」

Course explicitly says volume / body / close_pos are NOT entry filters.
The factor's penalties at entry ranking violate this AND CLAUDE.md.
Empirical evidence (audit): scanner_score is anti-signal (top-5 win 37.8% <
baseline 39.4% < bottom-5 40.7%).

**Files touched**
- `scripts/kline/scoring/attack_quality.py` → **moved to** `scripts/kline/extras/attack_quality_penalty.py`.
  Docstring updated. Added `make_score(arg)` factory matching SCORING_REGISTRY
  signature (`arg → callable(df) → Series`).
- `scripts/kline/scoring/__init__.py` — removed import + SCORING_REGISTRY entry +
  __all__ entry.
- `scripts/kline/extras/__init__.py` — registered as `attack_quality_penalty`
  in SCORING_REGISTRY.
- `tests/kline/scoring/test_attack_quality.py` — import path updated.
- `tests/kline/scoring/test_registry.py` — removed `"attack_quality"` from
  expected set.

**Enable via:** `--extras attack_quality_penalty`

---

## C5 — `gap_attack_filled` locks FIRST gap-up reference (not most recent)

**Course rule:** 跳空篇(二) — the "original" attack gap is the FIRST gap-up
after the breakout; once IT is killed the attack is over. Subsequent gap-ups
do NOT replace the reference.

**Files touched**
- `scripts/kline/exit/gap_attack_filled.py` — replaced `ffill` (which uses
  most-recent gap) with a group-transform that locks the FIRST non-NaN
  `gap_lower` per (ticker, trade_id) and reuses it indefinitely. Also gated
  on `trade_id >= 1` so the rule does not fire before any entry.
- `tests/kline/exit/test_gap_attack_filled.py`:
  - Adjusted existing test's entry-bar `prev_high` to avoid entry-day phantom
    gap (open=100, prev_high=100 → not a gap-up) so the test isolates the
    FIRST-gap-after-entry behavior.
  - Added `test_first_attack_gap_locks_not_replaced_by_later_smaller_gap` —
    asserts the locked reference is NOT replaced by a later gap (the C5 fix
    directly).
  - Added `test_first_attack_gap_kill_fires` — sanity test of FIRST-gap-kill.

**Before (most-recent gap):**
```python
recent_gap_lower = gap_lower.groupby(composite_key).ffill()
return (df["close"] < recent_gap_lower).fillna(False)
```

**After (locked-first gap, per trade):**
```python
def _first_gap_lower(group):
    valid = group.dropna()
    if valid.empty: return pd.Series(np.nan, index=group.index)
    first_value = valid.iloc[0]; first_pos = valid.index[0]
    out = pd.Series(np.nan, index=group.index)
    out.loc[first_pos:] = first_value
    return out
first_gap_lower = gap_lower.groupby(composite_key, sort=False).transform(_first_gap_lower)
in_trade = trade_id >= 1
return (in_trade & (df["close"] < first_gap_lower)).fillna(False)
```

**Caveat / interpretive choice:** the entry bar's own gap (if `open > prev_high`
on the entry day itself) IS counted as a candidate for "first attack gap of
the trade". The audit text says "after each entry signal, find the first
gap_up_bar" — I interpret "from entry day onward, inclusive". Mentioned here
because tests were adjusted to avoid the ambiguity.

---

## C6 — `dark_double_star` red-K + top-zone prerequisites

**Course rule:** 行進ing 關鍵K線×轉折 暗夜雙星 — two parallel **red** Ks at
the top (new high or overhead-clear), then a black engulfing.

**Files touched**
- `scripts/kline/exit/reversal_k/dark_double_star.py` — added
  `(k1_is_red AND k2_is_red)` AND `((k1_high OR k2_high) >= prior_high_60.shift(1))
  OR (overhead_supply_layer.shift(1) <= 0)`.
- `tests/kline/exit/reversal_k/test_dark_double_star.py` — rewrote to control
  bar color and inject `prior_high_60` + `overhead_supply_layer` columns;
  added `test_non_red_pair_does_not_trigger` and
  `test_red_pair_not_at_top_does_not_trigger`. Other tests adjusted to pass
  the new gates (red Ks + prior_high_60 supplied).

---

## C7 — `consolidation_breakdown` moved to extras; `consolidation` group removed

**Course rule:** 型態學 06-中樞型態:
> "Middle continuation; **NOT for trade entry/exit**; just 保持冷靜 during
> consolidation"

**Files touched**
- `scripts/kline/exit/consolidation_breakdown.py` → **moved to** `scripts/kline/extras/consolidation_breakdown.py`.
  Docstring updated; constants explicitly labeled non-course. Added
  `make_mark(arg)` factory.
- `scripts/kline/exit/__init__.py` — removed import + EXIT_REGISTRY entry.
- `scripts/kline/exit/groups.py` — removed `CONSOLIDATION_EXITS`, removed
  `"consolidation"` from `EXIT_GROUPS`, removed `"consolidation"` from every
  entry's group list in `ENTRY_EXIT_GROUPS`.
- `scripts/kline/extras/__init__.py` — registered as `consolidation_breakdown`.
- `tests/kline/exit/test_consolidation_breakdown.py` — import path updated.
- `tests/kline/exit/test_registry.py` — added negative assertion for
  `"consolidation"` group key.
- `tests/kline/exit/test_groups.py` — `test_tweezer_includes_supply_zone_and_consolidation`
  renamed to `test_tweezer_includes_supply_zone_only` and now asserts
  `consolidation_breakdown not in priority`.

**Enable via:** `--extras consolidation_breakdown`

---

## Backtest comparison

Pre-fix baseline (from coordinator-supplied figures):
- tweezer: n=3066, win=39.37%, mean_ret=+0.51%
- pattern: n≈895

Post-fix (this run, `data/analysis/kline/`):
- `backtest_trades.csv` (tweezer): **n=3066, win=39.69%, mean_ret=+0.52%**
- `backtest_pattern_post_critical.csv` (pattern): **n=900, win=40.89%, mean_ret=+0.52%**

| Run            | Pre n | Pre win | Pre mean_ret | Post n | Post win | Post mean_ret |
|----------------|------:|--------:|-------------:|-------:|---------:|--------------:|
| tweezer_top_breakout | 3066  | 39.37%  | +0.51%       | 3066   | 39.69%   | +0.52%        |
| pattern_breakout_only| ~895  | n/a     | n/a          | 900    | 40.89%   | +0.52%        |

Entry counts unchanged (entry-side untouched). Slight win-rate uptick (+0.32pp
for tweezer) consistent with removing the non-course `gap_fill` and the
crude `neckline_break` from exit priority — both formerly fired ahead of the
course-faithful versions. `gap_fill` and `consolidation_breakdown` no longer
appear in `exit_reason` counts (confirmed in CSV output), proving the moves
took effect at runtime.

Top exit reasons (tweezer post-fix): `sunrise_attack_end` 1507, `high_long_black`
607, `reversal_k.bearish_engulfing` 455, `breakout_price_break` 221,
`gap_attack_filled` 116, `breakout_low_break` 75, `reversal_k.gap_reversal`
43, `open` 18.

## Test status

All 194 tests pass (`uv run pytest tests/ -x -q`).

Tests modified (each due to pinning old non-compliant behavior):
- `tests/kline/exit/test_prev_day_low_break.py` — rewrote for gate (C1).
- `tests/kline/exit/test_gap_attack_filled.py` — adjusted entry-bar prev_high
  to avoid phantom entry-day gap; added 2 new tests (C5).
- `tests/kline/exit/reversal_k/test_dark_double_star.py` — rewrote helper for
  controllable bar color + added prior_high_60 / overhead column injection
  (C6).
- `tests/kline/exit/test_simulator.py` — import path of `gap_fill` redirected
  to extras module (C2).
- `tests/kline/exit/test_gap_fill.py`, `test_neckline_break.py`,
  `test_consolidation_breakdown.py`, `tests/kline/scoring/test_attack_quality.py`
  — import paths redirected to extras modules (C2/C3/C4/C7).
- `tests/kline/exit/test_registry.py` — removed moved-out entries from
  expected set; added negative assertions.
- `tests/kline/exit/test_groups.py` — renamed/adjusted test for removed
  consolidation group (C7).
- `tests/kline/scoring/test_registry.py` — removed `"attack_quality"` from
  expected set (C4).

## Caveats / unfinished items

- **C5 entry-day gap interpretation:** I treat the entry day's own gap-up
  (if `open > prev_high` on entry bar) as a candidate for "first attack gap
  of the trade". The audit text "after each entry signal, find the first
  gap_up_bar" is slightly ambiguous on whether the entry bar itself counts.
  I chose the inclusive interpretation; tests now use `prev_high == open` on
  entry to disambiguate. If course-of-truth says "strictly after entry bar",
  a single-line adjustment is needed.
- **C6 top-zone definition:** I implemented "top zone" as
  `(k1_high OR k2_high) >= prior_high_60.shift(1)` OR
  `overhead_supply_layer.shift(1) <= 0`. Both are course-grounded but the
  OR-combination is my interpretation; audit text gave them as alternatives.
- **C1 attack-meaning predicate (cond_b):** "upper-shadow K at new high" is
  operationalized as `prev.upper_shadow > prev.body_abs` AND `prev.high >
  prior_high_60.shift(1)`. The ratio threshold is a proxy; the course gives
  qualitative description only. Marked as proxy in the feature comment.
- **C1/C6 features.py additions assume sorted (ticker, trade_date) input**
  and use `groupby("ticker", group_keys=False)` consistently with the rest of
  the file. No new sort assumption introduced.
- No Important / Minor items were touched per scope constraints.
- Files unchanged outside the 7 Criticals; CLAUDE.md untouched; no commits
  made.
