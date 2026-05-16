"""Centralized proxy constants — every magic number used to operationalize
a course concept lives here, labeled with its course source and proxy status.

Audit goal (see docs/analysis/2026-05-16-course-compliance-audit.md): make
future audits trivial by listing every quantitative threshold in one place
along with the course quote it operationalizes and whether the threshold
is course-stated or our judgment.

Convention for each constant block:
  COURSE CONCEPT  — what course teaches qualitatively.
  COURSE QUOTE    — exact words (if quoted in source-of-truth doc).
  COURSE NUMBER?  — yes / no / inferred. If inferred, what we observed.
  PROXY VALUE     — the number we use.
  RATIONALE       — why this value.

If course gives a number, we use it. If it gives only qualitative wording,
we keep an explicit proxy with rationale and "course-not-stated" disclosure.
"""
from __future__ import annotations

# =============================================================================
# I1. attack_intensity higher-low / higher-high count (推升攻擊 / 波動前進)
# =============================================================================
# COURSE CONCEPT: 推升攻擊 = 「連續低點不斷墊高」; 波動前進 = 「高點不斷墊高」.
# COURSE QUOTE:
#   型態學 14-推升攻擊: 「低點不斷墊高，呈現連續推升的型態」
#   型態學 15-波動前進: 「高點不斷向上墊高，但低點與高點之間的距離保持穩定」
# COURSE NUMBER? No — course is qualitative, no count given. The 4/5 ratio
#   matches the "almost every day" feel of the course's chart examples.
# PROXY VALUE: 4 of 5 days.
# RATIONALE: 4/5 = 80% rising days operationalizes "連續" (continuous) without
#   demanding perfection; allows one off-day in a five-bar window.
ATTACK_HIGHER_LOW_MIN_5DAY = 4   # 推升攻擊: ≥ 4 of 5 days had higher-low
ATTACK_HIGHER_HIGH_MIN_5DAY = 4  # 波動前進: ≥ 4 of 5 days had higher-high
ATTACK_WINDOW_DAYS = 5

# =============================================================================
# I2. is_pattern_breakout upper-band stability spread (箱型整理 上緣穩定)
# =============================================================================
# COURSE CONCEPT: 箱型 / 上升三角的「上緣穩定」(stable ceiling).
# COURSE QUOTE:
#   型態學 03-箱型整理: 「上方有一個明顯的壓力線，價格反覆觸碰但無法突破」
#   型態學 05-三角收斂 (上升三角): 「上緣是平的、低點不斷墊高」
# COURSE NUMBER? No — course shows charts where the ceiling line is drawn
#   as visually flat, but no percentage is given. 5% empirically captures
#   typical box ceilings while excluding rising-trend stocks.
# PROXY VALUE: 5%.
# RATIONALE: difference between early-half max and full-60 max ≤ 5% means
#   the ceiling did not materially rise during the integration.
STABLE_UPPER_MAX_SPREAD = 0.05

# =============================================================================
# I3. higher_low_count_60d threshold (整理中低點墊高的天數比例)
# =============================================================================
# COURSE CONCEPT: 主力收貨的整理 = 「低點漸漸墊高」over the integration window.
# COURSE QUOTE: 型態學 03 + 14: 「低點漸漸墊高」, no quantification.
# COURSE NUMBER? No — course never says "half the days". The half-window
#   threshold is a moderate operationalization: a stock that has higher-low
#   on at least 30 of 60 bars is qualitatively rising-low; lower would
#   admit random walks.
# PROXY VALUE: INTEGRATION_DAYS // 2 = 30 of 60.
# RATIONALE: half-window is a common screening cutoff and a defensible "more
#   often than not" interpretation of 「漸漸墊高」.
INTEGRATION_DAYS = 60
RISING_LOWS_MIN_FRAC = 0.5  # → 30 of 60 days

# =============================================================================
# I4. breakout_attack — first-breakout vs re-breakout window
# =============================================================================
# COURSE CONCEPT: First breakout enters on the breakout bar; re-breakout
#   requires NEXT-DAY attack confirmation before entry.
# COURSE QUOTE: 突破跌破 — 突破意義的釐清:
#   「第一次突破，可以直接進攻；再次突破，需等隔日攻擊確認」
# COURSE NUMBER? Partially. Course gives the rule, but "first breakout"
#   needs a lookback to define what counts as "first". We use 60 bars
#   (matching prior_high_60 horizon).
# PROXY VALUE: FIRST_BREAKOUT_LOOKBACK = 60 bars; CONFIRMATION_BARS = 1
#   (the very next bar must be an attack bar).
FIRST_BREAKOUT_LOOKBACK = 60
REBREAKOUT_CONFIRMATION_BARS = 1

# =============================================================================
# I5. overhead_supply tiered penalty (套牢層數分級)
# =============================================================================
# COURSE CONCEPT: layered overhead supply is real resistance; the more
#   peaks above current price, the heavier the supply.
# COURSE QUOTE: 入門 成本原理 / 層層套牢的結構判斷.
# COURSE NUMBER? No — course never tiers resistance by peak count.
# PROXY VALUE: 0 peaks → 0, 1–3 peaks → −5, ≥ 4 peaks → −15.
# RATIONALE: 1–3 is "some" overhead, 4+ is "stacked". Pure judgment;
#   chosen so a clean stock (0) keeps its base score while a heavily-
#   layered stock loses meaningful ranking.
OVERHEAD_LIGHT_PENALTY = -5
OVERHEAD_HEAVY_PENALTY = -15
OVERHEAD_HEAVY_MIN_PEAKS = 4

# =============================================================================
# I6. high_zone_narrow_consolidation (高檔狹幅 醞釀)
# =============================================================================
# COURSE CONCEPT: 突破紅K 後 N 天狹幅 + 低點不破突破點 = 推升攻擊的醞釀.
# COURSE QUOTE: 型態學 14-推升攻擊.
# COURSE NUMBER? Partially. "N 天" is given as a small number; specific
#   value is not stated. 6 bars ≈ "about a week" of post-breakout
#   consolidation, which matches the course's chart examples.
# PROXY VALUE: window = 6 bars, narrow range ≤ 5%.
HIGH_ZONE_CONSOLIDATION_DAYS = 6
HIGH_ZONE_NARROW_RANGE_MAX = 0.05
HIGH_ZONE_BONUS = 8.0

# =============================================================================
# I7. is_doji thresholds (近乎沒有實體)
# =============================================================================
# COURSE CONCEPT: 十字線 / doji = 「近乎沒有實體」.
# COURSE QUOTE: 入門 單一K線 doji definition.
# COURSE NUMBER? No — course gives qualitative "近乎沒有實體" only.
# PROXY VALUE: body_pct ≤ 0.6% AND range_pct ≥ 1.5%.
# RATIONALE: body ≤ 0.6% of open = "近乎沒有實體"; range ≥ 1.5% ensures
#   the bar still has meaningful range (otherwise it's just a quiet day).
DOJI_MAX_BODY_PCT = 0.006
DOJI_MIN_RANGE_PCT = 0.015

# =============================================================================
# I8. breakout_price_break vs breakout_low_break sequencing window
# =============================================================================
# COURSE CONCEPT: breakout_price_break (close < prior_high_60) is the
#   EARLIER, more-sensitive exit; breakout_low_break (close < entry-bar
#   low) is the LATER, more-permissive exit.
# COURSE QUOTE: 紅K篇(五): 「突破紅K 後接黑K，跌破突破價 → 短線交易者立即停損」
#   (immediate, applies to the first day or two after breakout).
# COURSE NUMBER? No — course gives qualitative "first day or two" only.
# PROXY VALUE: 2 bars window for breakout_price_break; after the window,
#   breakout_low_break takes over.
BREAKOUT_PRICE_BREAK_WINDOW = 2  # bars after entry; thereafter low_break only

# =============================================================================
# trend_continuation +25 trigger — pre_breakout_trend_days threshold
# =============================================================================
# COURSE CONCEPT: 順勢交易 — pre-breakout trend strength supports the
#   attack thesis (trend-following).
# COURSE QUOTE: 入門 / 行進ing repeatedly emphasize that 季線多頭 background
#   strengthens an attack; specific day-count not stated.
# COURSE NUMBER? No — 17 was originally chosen by Spearman correlation
#   inflection in backtest. Keeping as proxy.
# PROXY VALUE: 17 days closing above MA60 in past 20 bars.
TREND_CONTINUATION_MIN_DAYS = 17
TREND_CONTINUATION_BONUS = 25.0


__all__ = [
    "ATTACK_HIGHER_LOW_MIN_5DAY",
    "ATTACK_HIGHER_HIGH_MIN_5DAY",
    "ATTACK_WINDOW_DAYS",
    "STABLE_UPPER_MAX_SPREAD",
    "INTEGRATION_DAYS",
    "RISING_LOWS_MIN_FRAC",
    "FIRST_BREAKOUT_LOOKBACK",
    "REBREAKOUT_CONFIRMATION_BARS",
    "OVERHEAD_LIGHT_PENALTY",
    "OVERHEAD_HEAVY_PENALTY",
    "OVERHEAD_HEAVY_MIN_PEAKS",
    "HIGH_ZONE_CONSOLIDATION_DAYS",
    "HIGH_ZONE_NARROW_RANGE_MAX",
    "HIGH_ZONE_BONUS",
    "DOJI_MAX_BODY_PCT",
    "DOJI_MIN_RANGE_PCT",
    "BREAKOUT_PRICE_BREAK_WINDOW",
    "TREND_CONTINUATION_MIN_DAYS",
    "TREND_CONTINUATION_BONUS",
]
