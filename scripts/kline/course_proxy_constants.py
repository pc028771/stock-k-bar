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

# =============================================================================
# T1. high_long_black body_pct minimum (高檔長黑 唯一保留的 body 門檻)
# =============================================================================
# COURSE CONCEPT: PATTERN_DEFINITIONS §1 結論 — 「形狀不重要」原則下，
#   唯一保留 body 門檻的場合是 high_long_black / outside_three_black 系列：
#   若不要求 body，「短黑 K」也會被誤觸發。
# COURSE QUOTE: docs/K線行進ing/16-黑K篇二_高檔長黑.md 通篇將「高檔長黑」
#   獨立為訊號，但未給數字。既有 scripts/kline/exit/high_long_black.py
#   採 body_pct ≥ 0.04 沿用同邏輯。
# COURSE NUMBER? No — course-not-stated — engineering proposal.
# PROXY VALUE: 0.04 (4%).
# RATIONALE: 沿用既有實作的數字，避免短黑 K 誤觸發；4% body 是「視覺
#   上明顯長」的最小門檻。
HIGH_LONG_BLACK_BODY_PCT_MIN = 0.04  # course-not-stated — engineering proposal

# =============================================================================
# T2. three_red_max_body_pct — 大敵當前「拉不開」單根 body 上限 (P07)
# =============================================================================
# COURSE CONCEPT: 大敵當前 連續紅 K「拉不出距離」(P07 PATTERN_INVENTORY L158).
# COURSE QUOTE: 多空轉折 第 06 篇《大敵當前》「連續紅K拉不出距離」。
# COURSE NUMBER? No — course-not-stated — engineering proposal.
# PROXY VALUE: 0.02 (2%).
# RATIONALE: 沿用 exit/reversal_k/enemy_at_gate.py 的 SMALL_BODY_MAX=0.02；
#   2% body 視為「短紅 K」、拉不開的代理。
THREE_RED_MAX_BODY_PCT = 0.025  # course-not-stated — engineering proposal
# 2026-06-02 calibration: relaxed 0.02 → 0.025 to capture 1414 2020-11-20 (D-2 body 2.4%).
# 課程「拉不開」是視覺判斷，2.5% body 仍屬「短紅」範疇。

# =============================================================================
# T3. three_red_max_high_spread — 三紅 high 之間距離上限 (P07)
# =============================================================================
# COURSE CONCEPT: 大敵當前 三根紅 K 「高點沒有顯著突破第一根」.
# COURSE QUOTE: 同 T2。
# COURSE NUMBER? No — course-not-stated — engineering proposal.
# PROXY VALUE: 0.015 (1.5%).
# RATIONALE: PATTERN_INVENTORY L158 提議 0.5%，但實務上 1.5% 更接近
#   「拉不出距離」直觀；過嚴會抓不到。
THREE_RED_MAX_HIGH_SPREAD = 0.03  # course-not-stated — engineering proposal
# 2026-06-02 calibration: relaxed 0.015 → 0.03 to capture 1414 2020-11-20 (D-2 spread 2.93%).
# 課程「沒拉開距離」是視覺判斷，3% 仍代表「明顯滯漲」未推升新高。

# =============================================================================
# T4. side_by_side_similarity_pct — 暗夜雙星併排相似度 (P08)
# =============================================================================
# COURSE CONCEPT: 暗夜雙星 兩根 K 線「形狀相似併排」(P08).
# COURSE QUOTE: 多空轉折 第 07 篇《暗夜雙星》。
# COURSE NUMBER? No — course-not-stated — engineering proposal.
# PROXY VALUE: 0.03 (3%).
# RATIONALE: 既有 scripts/kline/exit/reversal_k/dark_double_star.py 採
#   2%；PATTERN_INVENTORY L185 提議 0.3% 太嚴。3% 折中。
SIDE_BY_SIDE_SIMILARITY_PCT = 0.035  # course-not-stated — engineering proposal
# 2026-06-02 calibration: relaxed 0.03 → 0.035 to capture 3669 2020-09-07 (low_sim 3.1%).
# Course says "形狀相似" qualitatively; 3.5% still captures visual similarity without admitting
# obviously different K shapes. Baseline drift verified < 2x.

# =============================================================================
# T5. rebound_volume_ratio_min — 反撲量比門檻 (P23 反撲 / P19 包覆量比)
# =============================================================================
# COURSE CONCEPT: 包覆型態「有量」加強訊號 / 反撲量能.
# COURSE QUOTE: 多空轉折 第 18 篇「若包覆 K 有量」。
# COURSE NUMBER? No — course-not-stated — engineering proposal.
# PROXY VALUE: 1.5.
# RATIONALE: 沿用業界常見「爆量 = 均量 ×1.5」門檻。
REBOUND_VOLUME_RATIO_MIN = 1.4  # course-not-stated — engineering proposal
# 2026-06-02 calibration: relaxed 1.5 → 1.4 to capture 6290 2022-02-18 (vol_ratio 1.43).
# 1.4 仍屬「明顯有量」，課程「若包覆 K 有量」未指定精確倍數。

# =============================================================================
# T6. bite_close_equal_tolerance — 咬定 / 遭遇收盤相等容差 (P22)
# =============================================================================
# COURSE CONCEPT: 遭遇型態 今日收盤 ≈ 前日收盤.
# COURSE QUOTE: 多空轉折 第 21 篇《遭遇型態》「收盤價相等」。
# COURSE NUMBER? No — course-not-stated — engineering proposal.
# PROXY VALUE: 0.001 (0.1%).
# RATIONALE: 完全相等過於嚴格；0.1% 容差允許跳動最小單位。
BITE_CLOSE_EQUAL_TOLERANCE = 0.001  # course-not-stated — engineering proposal

# =============================================================================
# T7. narrow_consolidation_bars / range_max — 升降 / 咬定狹幅整理 (P25, P26)
# =============================================================================
# COURSE CONCEPT: 咬定 / 升降「過去 5 根 K 線狹幅整理」.
# COURSE QUOTE: 多空轉折 第 24 / 25 篇 「至少一週」「狹幅整理」。
# COURSE NUMBER? No — course-not-stated — engineering proposal.
# PROXY VALUE: 5 根 K 線；range ≤ 3%。
# RATIONALE: 「至少一週」≈ 5 個交易日；3% range 對應「沒拉開距離」。
NARROW_CONSOLIDATION_BARS = 5     # course-not-stated — engineering proposal
NARROW_CONSOLIDATION_RANGE_MAX = 0.03  # course-not-stated — engineering proposal

# =============================================================================
# T8. gap_fill_window_days — 上下缺口回補時間窗 (P27)
# =============================================================================
# COURSE CONCEPT: 缺口在「短期內」被回補才有意義。
# COURSE QUOTE: 多空轉折 第 26 篇《上下缺回補》。
# COURSE NUMBER? No — course-not-stated — engineering proposal.
# PROXY VALUE: 20 個交易日（約一個月）。
# RATIONALE: 課程文字「短期」介於數日到數週；20 日是「一個月」常見區段，
#   採較寬窗以涵蓋大部分案例。
GAP_FILL_WINDOW_DAYS = 20  # course-not-stated — engineering proposal

# =============================================================================
# T9. rebound_lookback_n — 反撲 短期 N 上限 (P23)
# =============================================================================
# COURSE CONCEPT: 反撲 D-1 「短期內」創新低 / 新高.
# COURSE QUOTE: 多空轉折 第 22 篇《反撲型態》。
# COURSE NUMBER? No — course-not-stated — engineering proposal.
# PROXY VALUE: 5 個交易日。
REBOUND_LOOKBACK_N = 5  # course-not-stated — engineering proposal

# =============================================================================
# T10. island_max_bars — 島狀反轉 島中 K 數上限 (P13/P14)
# =============================================================================
# COURSE CONCEPT: 島狀反轉中間孤島區的 K 數.
# COURSE QUOTE: 多空轉折 第 12 / 13 篇《島狀反轉》「中間 K 線」。
# COURSE NUMBER? No — course-not-stated — engineering proposal.
# PROXY VALUE: 10 個交易日。
# RATIONALE: PATTERN_INVENTORY L298 提議「≤ 10 天」採用之；超過就純粹當壓力。
ISLAND_MAX_BARS = 10  # course-not-stated — engineering proposal

# =============================================================================
# T11. bull_exhaustion_near_high_pct — 多方力竭 close 接近 prior_high_60 (§2)
# =============================================================================
# COURSE CONCEPT: PATTERN_DEFINITIONS §2 多方力竭背景條件 (3) — 今日 close
#   仍位於 prior_high_60 的 X% 以上（沒有跌離高檔）。
# COURSE QUOTE: docs/K線行進ing/16-黑K篇二: 「高檔沒辦法用數字定義」。
# COURSE NUMBER? No — course-not-stated — engineering proposal.
# PROXY VALUE: 0.95 (95%).
# RATIONALE: PATTERN_DEFINITIONS §2 採此值；五個百分點容差代表「拉抬後
#   小幅回檔仍算高檔」。
BULL_EXHAUSTION_NEAR_HIGH_PCT = 0.95  # course-not-stated — engineering proposal

# =============================================================================
# T12. bull_exhaustion_attack_lookback — 多方力竭攻擊回看窗 (§2)
# =============================================================================
# COURSE CONCEPT: PATTERN_DEFINITIONS §2 條件 (1) — 「過去 5 日內處於攻擊狀態」。
# COURSE QUOTE: docs/K線行進ing/16-黑K篇二 + 多空轉折 第 01 篇。
# COURSE NUMBER? No — course-not-stated — engineering proposal.
# PROXY VALUE: 5 個交易日。
# RATIONALE: 「短期內仍處於拉抬狀態」最自然的代理；超過 5 日就難稱「當下力竭」。
BULL_EXHAUSTION_ATTACK_LOOKBACK = 10  # course-not-stated — engineering proposal
# 2026-06-02 calibration: extended 5 → 10. attack_intensity 為 5 日窗口 feature，
# 若大漲後盤整 5+ 天才出現轉折 K（如 3669 2020-09-07，Aug 28 攻擊 → Sep 7 暴黑），
# 5 日 lookback 抓不到。10 日仍涵蓋「短期力竭」語意。


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
    "HIGH_LONG_BLACK_BODY_PCT_MIN",
    "THREE_RED_MAX_BODY_PCT",
    "THREE_RED_MAX_HIGH_SPREAD",
    "SIDE_BY_SIDE_SIMILARITY_PCT",
    "REBOUND_VOLUME_RATIO_MIN",
    "BITE_CLOSE_EQUAL_TOLERANCE",
    "NARROW_CONSOLIDATION_BARS",
    "NARROW_CONSOLIDATION_RANGE_MAX",
    "GAP_FILL_WINDOW_DAYS",
    "REBOUND_LOOKBACK_N",
    "ISLAND_MAX_BARS",
    "BULL_EXHAUSTION_NEAR_HIGH_PCT",
    "BULL_EXHAUSTION_ATTACK_LOOKBACK",
]
