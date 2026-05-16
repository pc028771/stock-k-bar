# Course Compliance Audit

**Date:** 2026-05-16
**Audited by:** general-purpose agent (opus, 1M context)
**Scope:** Full system implementation at commit `dcdd00e` (post rally-type-group refactor)
**Sources of truth read:** `reference_course_source_of_truth.md`, `K線力量判斷入門/course_principles.md`, `K線行進ing/course_principles.md`, `型態學/course_principles.md`

---

## Executive Summary

The system is **generally course-compliant in spirit but has several precision and pairing issues** that the recent rally-type refactor did not address. The most serious problems are concentrated in: (a) the `prev_day_low_break` exit being applied without the course-required attack-context gate, (b) `gap_fill` (E1) using a market-adjusted excess-gap proxy that does not match the course's "attack-gap-filled" definition, (c) `neckline_break` still using `prior_low_20` while a course-precise `ma60_neckline` exists in parallel — they coexist in the same exit group, producing duplicate / conflicting signals, and (d) `attack_quality` scoring uses backtest-derived thresholds (volume_ratio, body_pct, close_pos penalties) for entry-side ranking after the course explicitly tells us NOT to use those filters on entry. No outright forbidden-pattern violations (N字戰法, 下影線=支撐, 多空循環, etc.) were found in active code paths. The rally-type→exit-group matrix itself looks correct, but its contents include some misclassifications. Confidence: medium-high.

**Total findings:** 7 critical, 8 important, 6 minor. Severity tilted toward "course-imprecise" rather than "course-violating."

---

## Methodology

For each implementation file I (1) read the docstring's cited course articles, (2) cross-referenced the cited rule against `reference_course_source_of_truth.md` Parts 1–7.5, (3) checked the code against the cited rule, (4) tested against the 8 audit axes specified by the user, (5) cross-checked rally-type → exit-group assignments in `groups.py` and (6) verified no forbidden patterns from Part 7.5 appeared in active code.

Files audited:
- `scripts/kline/features.py` (derived columns)
- `scripts/kline/entry/{breakout, sunrise, trend_reversal, shoulder_gap_up_pullback, tweezer_top_breakout, tweezer_top_breakout_strict, pattern_breakout_only, combined_pattern_or_tweezer}.py`
- `scripts/kline/exit/{breakout_low_break, breakout_price_break, consolidation_breakdown, gap_attack_filled, gap_fill, high_long_black, ma60_neckline, neckline_break, prev_day_low_break, sunrise_attack_end, supply_zone_reach, trailing_stop, trend_change, groups, simulator}.py`
- `scripts/kline/exit/reversal_k/{bearish_engulfing, dark_double_star, enemy_at_gate, evening_star, gap_reversal, two_crows}.py`
- `scripts/kline/scoring/{attack_intensity, attack_quality, high_zone_narrow_consolidation, ma60_rolloff, overhead_supply, pattern_breakout, shadow_position}.py`
- `scripts/backtest.py`, `scripts/scanner.py`

---

## Findings

### Critical (course-violating, must fix)

**C1. `prev_day_low_break` fires without the course-required "previous bar had attack meaning" gate.**
- Location: `scripts/kline/exit/prev_day_low_break.py:16`
- Course quote (紅K篇(二) / 買點與攻擊研判): the previous bar must have **攻擊意義** (red K creating new high / new-high upper shadow / red K's doji follow-up) for "前一日低點" to constitute an attack stop. Without that gate the rule degenerates into a pure mechanical stop on any prior low.
- Current code: `return (df["close"] < df["prev_low"]).fillna(False)` — every bar where today's close < prev_low triggers, regardless of whether yesterday was attack-meaningful.
- Already documented as finding #9 in the source-of-truth and listed as `SHORT_TERM_EXITS` in `groups.py`. The rally-type refactor moved it out of strong_attack groups, which mitigates the worst misuse, but the underlying detector is still wrong on its face.
- Recommended fix: add `prev_bar_had_attack_meaning` predicate (prev was red K + (close > prior_high_60 OR upper_shadow at new high OR doji-after-red)). Then gate.

**C2. `gap_fill` is NOT the course's "attack gap filled" — it is a market-adjusted excess-gap-then-close-down rule.**
- Location: `scripts/kline/exit/gap_fill.py:18-31`
- Course quote (跳空篇(二)(三)): an attack gap is filled when **close < attack_gap_lower** (the previously-unseen segment of `(prev_high, today_open)`). The course never invokes the market's open return.
- Current code: triggers when (a) stock_open - market_open_ret ≥ 2% (excess gap) AND (b) close < prev_close. This is a same-day gap-and-go-fail rule, not a multi-day attack-gap-lower-bound break.
- Severity: course-violating because the EXIT is firing on a non-course condition (market-adjusted excess gap) and is mislabeled in `STRONG_ATTACK_EXITS` as the canonical "E1".
- The course-correct mechanism — close < attack_gap_lower — is implemented as `gap_attack_filled` (跳空篇(二)). So we have BOTH a non-course gap_fill AND a course-faithful gap_attack_filled in the same `strong_attack` group. The non-course one will often fire first because it's a same-day rule.
- Recommended fix: either (a) deprecate `gap_fill` outright in favor of `gap_attack_filled`, or (b) move `gap_fill` to `extras/` with explicit non-course labeling.

**C3. `neckline_break` (prior_low_20) and `ma60_neckline` (course-precise) coexist in the trend_change group with overlapping semantics.**
- Location: `scripts/kline/exit/groups.py:34-39`; `neckline_break.py`; `ma60_neckline.py`
- Course quote (型態學 頭部型態 + 行進ing 事件七): a neckline is "季線下彎後的前一個低點 AND 該低點上方有 ≥ 3 個月套牢". The crude `prior_low_20` does not honor either condition.
- Current code: `TREND_CHANGE_EXITS = ["trend_change", "neckline_break", "ma60_neckline"]` — both fire side-by-side; the simulator takes whichever triggers earliest. `prior_low_20` will almost always trigger first because it is far more sensitive.
- Result: the precise `ma60_neckline` effort is effectively wasted; the system reports `neckline_break` as the exit reason most of the time, masking the course-faithful exit's behavior.
- Recommended fix: remove `neckline_break` from `TREND_CHANGE_EXITS`, leave only `ma60_neckline`. Either deprecate `neckline_break.py` outright or label it as `extras_neckline_crude_proxy`.

**C4. `attack_quality` scoring applies backtest-derived volume/body/close_pos penalties at ENTRY ranking.**
- Location: `scripts/kline/scoring/attack_quality.py:34-39`
- Course quote (突破跌破 — 突破意義的釐清): "對於K線圖來說，價格才是最重要的事情，不需要加上成交量"; "與這一根突破的K線是否長紅、有沒有上影線都無關". Course explicitly says volume, body, close_pos are NOT entry filters.
- Current code: applies −30 for volume_ratio ≥ 3.2, −25 for body_pct ≥ 0.04, −20 for close_pos ≥ 0.85, all on the entry-candidate scoring of the scanner.
- The factor's own docstring acknowledges these are non-course statistical thresholds and notes the caveat that "this factor is used ONLY for scanner ranking, not absolute trade decisions". That is honest. **But** the scanner's `scanner_score` then sums it with all other course-faithful factors with equal weight, so the non-course factor materially shifts which course-correct entries reach the top of the daily list.
- This is also forbidden under CLAUDE.md: "禁止將回測分析結論...套用在個股操作建議上". The scanner output IS individual stock operation guidance.
- Recommended fix: relabel `attack_quality` as `extras_backtest_quality`, gate behind a toggle, and exclude from default `scanner_score`. OR keep all four sub-factors but document that course says these should be neutral.

**C5. `gap_attack_filled` uses "most recent" gap-lower rather than the cumulative attack-gap reference.**
- Location: `scripts/kline/exit/gap_attack_filled.py:38-49`
- Course quote (跳空篇(二)): a gap-down that **消除d** the original attack gap is the trigger. The "original" attack gap is the FIRST gap after the breakout, not the most recent gap.
- Current code: per-trade, forward-fill the MOST RECENT gap-up's prev_high as the support reference. A late, smaller gap-up will override the original attack-gap reference and effectively raise the stop — the opposite of course intent (the original attack gap is the canonical support, and once IT is killed the attack is over).
- Recommended fix: within a trade, lock the FIRST attack-gap lower bound; do not replace on subsequent gap-ups.

**C6. `dark_double_star` "two similar parallel K bars" prerequisite is implemented but does not require the pair to be near a top / new high.**
- Location: `scripts/kline/exit/reversal_k/dark_double_star.py`
- Course quote (行進ing 關鍵K線×轉折): 暗夜雙星 is by definition a TOP reversal — the two parallel reds (the course shows red K, not generic K) are at high zone.
- Current code: requires only `(high_ratio ≤ 3%) AND (low_ratio ≤ 3%)` between K-1 and K-2 — no requirement that they are red, nor at new-high / overhead zone. Will fire on consolidation pairs anywhere, including bear-trend recoveries.
- Recommended fix: add `k1_is_red AND k2_is_red`, and `(k1_high or k2_high) >= prior_high_60` or `overhead_supply_layer ≥ 1`.

**C7. `consolidation_breakdown` is mapped to `consolidation` group and attached to all breakout-style entries, but the course pattern it cites (中樞型態 06) is explicitly NOT for trade entry/exit.**
- Location: `scripts/kline/exit/consolidation_breakdown.py`; `groups.py:60-63`
- Course quote (型態學 06-中樞型態): "Middle continuation; **NOT for trade entry/exit**; just '保持冷靜 during consolidation'" — `reference_course_source_of_truth.md` Part 6.8 records this verbatim.
- Current code: uses a 10-bar narrow-range + black K + break-low to fire an exit, on every breakout entry. The 10-day, 8% range threshold are pure quantitative proxies with no course backing.
- Recommended fix: remove `consolidation_breakdown` from default `ENTRY_EXIT_GROUPS` for all entries. Move to `extras/` if you want to keep the detector available.

### Important (course-imprecise, should fix)

**I1. `attack_intensity` (型態學 four-pattern) ranking conflates 推升攻擊 with 4-of-5 higher-low days.**
- Location: `features.py:300`
- Course quote (型態學 14-推升攻擊): 推升攻擊 = 「連續低點不斷墊高」without quantifying. Our threshold (`higher_low_5day >= 4`) is a proxy.
- Same for `波動前進` (波動 4 of 5 higher highs). Course gives a qualitative description, not a count.
- Recommended fix: label `4 of 5` as a non-course proxy in the docstring (which it currently does not).

**I2. `is_pattern_breakout` uses `upper_band_spread_60d ≤ 5%` as a "stable upper boundary" proxy — not course-stated.**
- Location: `features.py:226-230`
- Course quote (型態學 03-箱型整理 / 05-三角收斂): 上緣穩定 means "ceiling didn't trend up". 5% is our cutoff, not course-stated. Currently labeled in the code comment as "Stable upper boundary" without "proxy" disclosure — only the constant name (`STABLE_UPPER_MAX_SPREAD`) hints at it.
- Recommended fix: add explicit "# Proxy: course says upper boundary should be stable; we operationalize via 5%."

**I3. `higher_low_count_60d ≥ 30/60` is a course-statistical proxy for "rising lows".**
- Location: `features.py:212` `RISING_LOWS_MIN = INTEGRATION_DAYS // 2`
- Course never quantifies "half the days". Same disclosure issue as I2.

**I4. `breakout_attack` admits both "first breakout" AND "re-breakout" — but the course requires next-day attack confirmation for re-breakouts.**
- Location: `scripts/kline/entry/breakout.py:27-37`
- Course quote (突破跌破 — 突破意義的釐清): "Re-breakout... Must wait for NEXT-DAY attack confirmation". `breakout_attack` enters on the breakout day regardless.
- Mitigation: `sunrise_attack` exists as a more conservative variant. But `breakout_attack` is still in the entry registry without a `first-breakout` gate.
- Recommended fix: either (a) add a `is_first_breakout_above_level` predicate, or (b) document that `breakout_attack` is the LOOSE form and users should prefer `sunrise_attack` or `pattern_breakout_only` for re-breakout safety.

**I5. `overhead_supply` scoring threshold (-5 / -15) is backtest-style.**
- Location: `scripts/kline/scoring/overhead_supply.py:23-26`
- Course quote: layered overhead = real, but the course doesn't tier resistance by peak count. The 1-3 vs 4+ split is our choice.
- Recommended fix: same as I2 — disclose as proxy.

**I6. `high_zone_narrow_consolidation` uses 6-day window and 5% range — course says "tight" without quantification.**
- Location: `scripts/kline/scoring/high_zone_narrow_consolidation.py:23-25`
- Same as I5.

**I7. `is_doji` definition `body_pct ≤ 0.6%` and `range_pct ≥ 1.5%` are arbitrary.**
- Location: `features.py:140`
- Course gives qualitative description only. Used by `evening_star_abandoned` and `attack_intensity` — both course-cited patterns inherit our threshold.
- Recommended fix: disclose constants as proxies.

**I8. `breakout_price_break` and `breakout_low_break` are BOTH in `STRONG_ATTACK_EXITS` — but the course defines them as sequential, not parallel.**
- Location: `groups.py:30-31`
- Course quote (紅K篇(五)): breakout_price_break is the EARLIER, more-sensitive exit; breakout_low_break is the LATER one. Both firing simultaneously means whichever triggers first wins, which is usually `breakout_price_break`. The behavior is OK in practice (early exit > late exit), but the design semantics conflate two different time-horizon stops.
- Recommended fix: document the design choice; or pick one based on user trader-style (short_term vs swing).

### Minor (documentation/clarity, nice to fix)

**M1. `sunrise.py` says "SUNRISE_BARS_REQUIRED = 2" for confirmation bars but the course (紅K篇七) does not specify a count.**
- The 2-bar choice is reasonable but arbitrary. Disclose as proxy.

**M2. `high_long_black` uses `prior 60-day high/low ratio ≥ 1.3` as "high zone" definition.**
- Course says 高檔, qualitative. Disclose.

**M3. `simulator.py` priority-tie-breaking: "Priority order wins on ties: strict < keeps higher-priority condition" (line 102).**
- The comment is correct but cryptic. Code picks the EARLIEST trigger date across all conditions, breaking ties by priority order (earlier in list). This is actually different from what the comment suggests at first read.

**M4. `combined_pattern_or_tweezer` is OR — combining two course-faithful signals — but loses the per-signal exit-group routing.**
- Location: `groups.py:92` maps it to `strong_attack + supply_zone + consolidation`. Same as the underlying entries, so no real issue, but if you ever differ the exits per-signal, OR-merging would conflate them.

**M5. `trend_change.py` only implements MA60-down; explicitly leaves out last_rally_low and rising_trendline.**
- Course says take the HIGHER of three. With only one implemented, we are using a STRICTLY lower stop than course intends. Already documented in source-of-truth.

**M6. `pre_breakout_trend_days` cap at 20 is arbitrary (Spearman calibration), label as proxy.**
- Location: `features.py:62-72`

### Verified-correct (notable items that PASS audit)

- ✅ `breakout_low_break` (E4) — faithfully implements 紅K篇(七)/紅色誤解; uses entry-bar low and close-confirmation.
- ✅ `breakout_price_break` — faithful to 紅K篇(五); close < prior_high_60.
- ✅ `pattern_breakout_only` — A/B/C/D/E 5-condition AND chain is course-cited and clean overhead correctly unions overhead_supply_layer AND unfilled_gap_down. Each condition has source citation.
- ✅ `shoulder_gap_up_pullback` — accurately implements 型態學 17 three-bar structure with correct stop reference (gap lower bound = K-2.close).
- ✅ `is_in_breakdown_pattern` (破底型態 exclusion) — applied at entry across all attack-style entries (`breakout`, `sunrise`, `tweezer_top_breakout`, `shoulder_gap_up_pullback`, `pattern_breakout_only`).
- ✅ `unfilled_gap_down_count_240d` (缺口壓力) — course-cited and used in clean-overhead requirement of `is_pattern_breakout`.
- ✅ `shadow_position` scoring — correctly implements 上影線(一)(二) and IGNORES lower_shadow per course; lower_shadow is COMPUTED in features but not scored.
- ✅ Rally-type exit-group matrix structure (`ENTRY_EXIT_GROUPS`) — the architectural correction is well-formed: breakout entries → strong_attack; trend_reversal → trend_change; etc.
- ✅ Simulator uses next-day open execution (line 87) and close-price confirmation for triggers — both course-aligned.
- ✅ `trailing_stop` — faithful to 緩慢推升型 移動停利; per-trade expanding max of prev_low.
- ✅ No forbidden patterns from Part 7.5 detected in active paths: no N字戰法 reentry, no 下影線=支撐 scoring (lower_shadow_ratio exists but is unused), no 多空循環, no 假性跌破 applied to individual stocks (concept absent from code), no 均線「支撐」 (MA60 used for direction only, never as support level), no 摸頭/摸底 entry.
- ✅ `trend_reversal` is correctly left as a STUB (returns all False) per course's reluctance to give precise low-position entry rules.

---

## Specific axis findings

### Axis 1: Course-spec alignment
- Mostly OK. The largest mismatches are C2 (`gap_fill` is not the course's attack-gap-fill) and C3 (two parallel necklines).

### Axis 2: Course-concept 混淆
- C1 mixes a 短線 exit (前一日低點) into every breakout entry without the attack-context gate — short-term mechanic applied indiscriminately.
- I8 conflates two time-horizon stops (breakout_price_break, breakout_low_break) by listing both in the same group.
- C2 conflates `市場相對 gap_fill` with course's `attack_gap_filled`.

### Axis 3: Forbidden pattern check
- **NONE FOUND in active paths.** `lower_shadow_ratio` is computed but never scored (defensible — could become `extras_lower_shadow_ratio` later, or removed entirely). The forbidden patterns from Part 7.5 (N字, 打第N腳, 多空循環, 美股=台股, 缺口計數, 摸頭/底, 均線支撐, W底/頭肩底, 鑷底=支撐, 攤平, 來回操作, 楔形買進, 任何背離訊號, etc.) are absent.

### Axis 4: Proxy disclosure
- Disclosure is **inconsistent**. Some files (e.g. `attack_quality.py`) honestly disclose; others (e.g. `is_pattern_breakout`'s 5% cutoff, `attack_intensity`'s 4-of-5 count, `is_doji`'s 0.6%, `high_long_black`'s 1.3) embed magic numbers without "# Proxy:" labels. See I1-I7.

### Axis 5: Entry-exit pairing
- Architectural matrix is correct.
- BUT contents have issues:
  - `consolidation_breakdown` applied to all breakout entries — course says 中樞 is NOT for entry/exit (C7).
  - `gap_fill` and `gap_attack_filled` both in `strong_attack` (C2).
  - `neckline_break` and `ma60_neckline` both in `trend_change` (C3).
- `trend_reversal` correctly maps to `trend_change` (correct course pairing; the entry is a stub so this is hypothetical).

### Axis 6: Multi-condition (AND) usage
- `is_pattern_breakout` (5 ANDs) is course-cited per-condition: A/B/C/D/E all sourced.
- `tweezer_top_breakout` adds `clean_overhead AND above_ma60` — the docstring labels `clean_overhead` as enforcing course's implicit "剛創新高" position requirement (型態學 18 + 08). Reasonable interpretation but the course does not literally state clean_overhead as a tweezer condition. Label as inferred.
- `sunrise.py` adds `breakout_was` requirement (close > prior_high_60 + close > MA60 two bars back). Course says 突破之後 + 連續日出 — matches.

### Axis 7: Time horizon consistency
- `prev_day_low_break` is 短線 (course explicit); putting it in `SHORT_TERM_EXITS` is correct. None of the breakout entries map to short_term currently, which means it doesn't fire by default — GOOD.
- But `breakout_price_break` (短線/sensitive) and `breakout_low_break` (slightly less short-term) are both in `STRONG_ATTACK_EXITS` (I8).
- `trailing_stop` is in `SLOW_PUSH_EXITS` only; no breakout entry currently routes to slow_push (no entry signal explicitly classifies a candidate as 緩慢推升型). This is correct conservative behavior — trailing_stop should not fire on strong-attack entries.

### Axis 8: Edge cases the course addresses
- ✅ 假性跌破 individual-stock context — not applied. (No `false_breakdown_reclaim` in code.)
- ✅ 多頭吞噬 as a long entry — not implemented as entry. (`bullish_engulfing` does not exist in entry/.)
- ✅ 上肩缺口拉回承接 — implemented as the only pullback entry (`shoulder_gap_up_pullback`).
- ✅ 下影線 support meaning — not used as positive score. (lower_shadow_ratio exists but is dead weight.)
- ✅ 破底型態 individual-stock exclusion — applied uniformly to all attack entries.
- ⚠ 兩段操作 (異常體質型) — `ABNORMAL_CHARACTER_EXITS = []` is empty; documented TODO. No entry currently routes to this group anyway.

---

## Recommendations

### Immediate actions (critical)
1. **C1**: Gate `prev_day_low_break` behind a `prev_bar_had_attack_meaning` predicate, OR remove the standalone exit until that predicate exists.
2. **C2**: Deprecate / move `gap_fill` to `extras_`; rely on `gap_attack_filled` for the course-faithful E1.
3. **C3**: Remove `neckline_break` (prior_low_20) from `TREND_CHANGE_EXITS`; keep only `ma60_neckline`.
4. **C4**: Gate `attack_quality` behind an extras toggle and exclude from default `scanner_score`. (Or split the four sub-factors and only keep `pre_breakout_trend_days` which is course-aligned in direction.)
5. **C5**: Lock the FIRST attack-gap reference within a trade in `gap_attack_filled`; do not replace on subsequent gap-ups.
6. **C6**: Add red-K + new-high-zone gate to `dark_double_star`.
7. **C7**: Remove `consolidation_breakdown` from default `ENTRY_EXIT_GROUPS` for all entries; move to extras.

### Follow-up items (important + minor)
- Add explicit "# Proxy:" labels to every quantitative threshold (I1, I2, I3, I5, I6, I7, M1, M2, M6).
- Decide policy for `breakout_attack` re-breakout entry (I4).
- Document the priority-tie behavior of the simulator more clearly (M3).
- Remove unused `lower_shadow_ratio` feature OR move it to a `# Computed but intentionally unused per course` note.

### Architectural notes
- The rally-type → exit-group matrix is the right shape. The remaining work is content-cleanup, not redesign.
- Consider a `ENTRY_TIME_HORIZON` map (swing vs short_term) parallel to `ENTRY_EXIT_GROUPS`, so the short-term-only exits (`prev_day_low_break`, possibly `breakout_price_break`) can be applied selectively without the user choosing it implicitly via group merging.
- A single "course_proxy_constants.py" with all magic numbers in one place, each labeled with `# Proxy for: [course concept] | Source: [statistical or judgment]`, would make audits like this much faster next time.

---

## Audit confidence

**Confidence: medium-high.**

Reasons for confidence:
- All files in scope read in full.
- Source-of-truth doc cross-referenced for every flagged item.
- Forbidden-pattern grep returned no hits.
- Rally-type matrix structure verified end-to-end.

Reasons for uncertainty:
- Did NOT execute the backtest to confirm `neckline_break` firing more often than `ma60_neckline` (C3) — claim is inferred from threshold sensitivity. Would need empirical verification.
- Did NOT read every test file; there may be tests pinning current (non-compliant) behavior that would need updating alongside fixes.
- 多空轉折組合K線 subcategory has not been read by the project — some reversal-K definitions (especially `dark_double_star`, `gap_reversal`, `two_crows`) may need refinement once that 26-article subcategory is consulted. Current detectors use intro-level definitions only.
- "Forbidden pattern" check was textual-grep + manual review; semantic violations that don't use the Chinese terms might slip through.
