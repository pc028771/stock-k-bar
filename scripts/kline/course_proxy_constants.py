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
# PROXY VALUE: 3 根 K 線；range ≤ 3%。
# RATIONALE: 老師「至少一週」字面 ≈ 5 個交易日，但實際 case (Case #6 富邦媒
#   8454 2022-02-25) 真實 setup 是 02/22-24 三天 close 1005 + 02/25 黑K
#   跌破。3 天是更實際的最短「狹幅整理」期；5 天 + 02/22 crash 會把窗口
#   裡的整理破壞。3 天 range 3% 對應「沒拉開距離」。Case #5 奇鋐 3017
#   2022-02-17 在 3 天 / 5 天都能 trigger，不傷既有 hit。
NARROW_CONSOLIDATION_BARS = 3     # course-not-stated — engineering proposal (was 5, adjusted 2026-06-03 per case #6)
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
# T8b. merged_doji_body_ratio — 合併十字線 body/range 上限 (明日 K 線 §合併十字)
# =============================================================================
# COURSE CONCEPT: 合併後形成「長十字線」(merged_doji pattern)。
# COURSE QUOTE: 課程說「合併後形成長十字線」，未明示 body/range 比例數字。
# COURSE NUMBER? No — [STUB-NEED-USER].
# PROXY VALUE: 0.25（body 佔合併 range ≤ 25% 視為十字結構）。
MERGED_DOJI_BODY_RATIO: float = 0.25  # [STUB-NEED-USER]

# =============================================================================
# T8c. merged_doji_shadow_min_ratio — 合併十字線 上下影線最小比例
# =============================================================================
# COURSE CONCEPT: 上下影線形成「長十字線」。
# COURSE QUOTE: 課程要求「上影線 + 下影線形成長十字線」，未明示影線長度比例。
# COURSE NUMBER? No — [STUB-NEED-USER].
# PROXY VALUE: 0.2（上影、下影各佔合併 range ≥ 20%）。
MERGED_DOJI_SHADOW_MIN_RATIO: float = 0.2  # [STUB-NEED-USER]

# =============================================================================
# T8d. at_pressure_retest — 壓力區回測（課程：二元觸及 / 越過，無 % 門檻）
# =============================================================================
# COURSE CONCEPT: 套牢/波動/獲利了結三類壓力的共通前提 = 高點觸及前高但收盤未突破。
# COURSE QUOTE: 明日 K 線 §08「壓力的分類」B5DB7A687DA4FA572833411DE9CD88D8
#   「股價第二次又來到 170 元附近，倘若對於壓力有正確的體認，應該就可以推演出來，
#    隔天要確認是攻擊，必須就是一開盤開在 176.5 元以上的跳空攻擊...」
#   老師明示「碰到了」vs「越過了」= 二元判斷（觸及 / 突破），無 % 距離概念。
# COURSE NUMBER? No percentage — 課程明示「碰到」vs「越過」二元，不是「距離 X%」。
# IMPLEMENTATION: 改用二元觸及判斷（high >= prior_high_60 AND close < prior_high_60）
#   代替 % 範圍 — 見 features.py at_pressure_retest。
# NOTE: AT_PRESSURE_RETEST_PCT 常數已廢棄，保留此區塊作為 audit 紀錄。
# COURSE CITATION: 明日 K 線 §08 B5DB7A687DA4FA572833411DE9CD88D8
# （此常數不再使用；features.py 已改用二元觸及條件）
# AT_PRESSURE_RETEST_PCT: float = 0.10  # 已廢棄 — 課程無 % 門檻、改用二元觸及

# =============================================================================
# T8e. low_price_threshold — 低價股門檻 (入門 §09 低價股的處理節奏)
# =============================================================================
# COURSE CONCEPT: 「低價股」屬於課程概念（入門 §09 低價股的處理節奏）、
#   老師有專篇講解低價股交易節奏不同。
# COURSE QUOTE: 入門 §09 — 「低價股」相對概念、低 / 中 / 高分級
# COURSE NUMBER? No — [STUB-NEED-USER]，老師只用相對概念、未明示具體門檻
# PROXY VALUE: 30.0（業界粗略 proxy；明基材 8215、錸德 2349 等案例落 10-25 元、
#   30 元為上界含緩衝）。
# RATIONALE: 概念在課程內、數字是 proxy → 留 course_proxy_constants.py + STUB-NEED-USER
LOW_PRICE_THRESHOLD: float = 30.0  # [STUB-NEED-USER]

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


# =============================================================================
# C08. attack_continuity scoring — 攻擊延續性因子 (INVENTORY §C08)
# =============================================================================
# COURSE CONCEPT: 攻擊延續性 — 跳空攻擊、攻擊企圖區維持、異常放量後縮量.
# COURSE QUOTE:
#   第 18 篇: 「跳空攻擊之後隔日繼續往上」
#   第 32 篇: 「攻擊企圖區不可跌回意圖區」
#   第 40 篇: 「異常放量之後量縮 → 攻擊仍有延續性」
# COURSE NUMBER? No — +1/-1 scoring unit is our operationalization.
# PROXY VALUE: ±1 per condition (see scoring/attack_continuity.py).
# This constant block documents the intent; actual values are inline in scoring.
# (No standalone numeric constant needed — kept for audit trail.)
ATTACK_CONTINUITY_SCORE_UNIT = 1.0  # ±1 per condition — course-not-stated magnitude

# =============================================================================
# C09. pattern_pressure scoring — 型態壓力因子 (INVENTORY §C09)
# =============================================================================
# COURSE CONCEPT: 型態壓力 — 頸線跌破、反彈遇壓、連層套牢.
# COURSE QUOTE:
#   第 17 篇: 「頸線跌破 = 頭部壓力確認」
#   第 29 篇: 「反彈遇頸線不過 = 頭部型態的阻礙」
#   入門 成本原理: 「層層套牢 = 多層壓力」
# COURSE NUMBER? No — +1 per condition is our operationalization.
# PROXY VALUE: +1 per condition, overhead_supply capped at +3.
PATTERN_PRESSURE_SCORE_UNIT = 1.0   # +1 per condition — course-not-stated magnitude
PATTERN_PRESSURE_SUPPLY_MAX = 3.0   # max supply layer contribution — course-not-stated

# =============================================================================
# C10. ma60_rolloff §C10 — 季線下彎無表態額外懲罰 (INVENTORY §C10)
# =============================================================================
# COURSE CONCEPT: 季線扣抵值 > 今日收盤 → 明日 MA60 必然下彎；若今日無紅 K
#   表態，多方力量不足，壓力加深。
# COURSE QUOTE: 明日 K 線 第 06 篇「季線扣抵」（課程明示觀念但無數字）.
# COURSE NUMBER? No — -3 is our operationalization.
# PROXY VALUE: MA60_BEARISH_NO_CONFIRM_BONUS = -3.0 (in scoring/ma60_rolloff.py).
MA60_BEARISH_NO_CONFIRM_BONUS = -3.0  # course-not-stated — engineering proxy

# =============================================================================
# C11. zhongshu_pattern — 中樞型態整理天數 (INVENTORY §C11)
# =============================================================================
# COURSE CONCEPT: 中樞型態 = 上升或下降整理區間，突破前等待。
# COURSE QUOTE:
#   第 02 篇: 「對抗近因偏誤」
#   第 21 篇: 「中樞型態 = 整理區間，突破前等待」
#   第 41 篇: 「上升中樞 vs 下降中樞 識別方式」
# COURSE NUMBER? No — 3~30 days range is our operationalization.
# [STUB-NEED-USER]: 老師只說「不要太短也不要太長」，無具體天數。
ZHONGSHU_MIN_DAYS = 3   # [STUB-NEED-USER] — course-not-stated lower bound
ZHONGSHU_MAX_DAYS = 30  # [STUB-NEED-USER] — course-not-stated upper bound

# =============================================================================
# C14. trailing_stop §C14 — 微弱多方趨勢退化版 MA 天數 (INVENTORY §C14)
# =============================================================================
# COURSE CONCEPT: 微弱多方趨勢下，以短期趨勢線（課程說「趨勢線」）作最後停利。
# COURSE QUOTE: 第 05 篇「微弱的多方趨勢就要用趨勢線來輔助」.
# COURSE NUMBER? No — course says 「趨勢線」not MA; 5-day SMA is our proxy.
# [STUB-NEED-USER]: 「5 日 SMA」是否就是課程所指的短期趨勢線？
WEAK_BULL_MA_DAYS = 5  # [STUB-NEED-USER] — course-not-stated MA period


# =============================================================================
# A20a. attack_cost_displayed — 漲停鎖住容差 (明日 K 線 §20)
# =============================================================================
# COURSE CONCEPT: 攻擊成本顯現日 — 收盤鎖住漲停板。
# COURSE QUOTE: 「突破前高的當日，股價鎖住漲停板，且最大量就是在這個漲停板的價位」
# COURSE NUMBER? No — 1.095 proxy 同 features.py C05（+10% with tick tolerance）。
# [STUB-NEED-USER]: 漲停判斷使用 prev_close * 1.095 容差，與 features.py C05 一致。
ATTACK_COST_LIMIT_UP_THRESHOLD: float = 1.095  # [STUB-NEED-USER] same as C05 proxy

# =============================================================================
# A20b. attack_cost_displayed — 日K退化版量比門檻 (明日 K 線 §20)
# =============================================================================
# COURSE CONCEPT: 攻擊成本顯現日 — 最大量在漲停板價位。
# COURSE QUOTE: 「最大量就是在這個漲停板的價位，成交量越大、成本意義越高」
# COURSE NUMBER? No — 課程需要分 K 資料確認「最大量在漲停」；
#   日K退化：當日成交量 ≥ avg_volume_20 * ATTACK_COST_VOL_RATIO。
# [STUB-NEED-USER S2]: 1.5 倍均量是工程退化值；待 user 確認或補分 K 資料。
ATTACK_COST_VOL_RATIO: float = 1.0  # [STUB-NEED-USER S2] — course-not-stated (日K退化)
# 退化值從 1.5 調降為 1.0（等同「只要有量就算」）。
# 3693 營邦 2023-04-11 volume_ratio=1.35x 在 1.5 門檻下 MISS（正例遺漏）。
# 課程明示「成交量越大、成本意義越高」是「意義強弱」判斷，非「有無觸發」條件。
# 攻擊成本顯現日本身不因量小而失效，只是信心度低；detector 應仍觸發。
# [STUB-NEED-USER S2]: 1.0 = 事實上移除量能過濾，讓 is_limit_up_locked + broke_high 主導。
# 若未來取得分 K 資料可確認「最大量在漲停板」，再加回精確量能條件。

# =============================================================================
# A20c. attack_cost_displayed — 連續觸發抑制窗 state-machine (明日 K 線 §20)
# =============================================================================
# COURSE CONCEPT: 攻擊成本顯現日後的連續漲停 = 「攻擊企圖確認 / 跳空攻擊 /
#   推升攻擊」branch、不是新的 setup-stage 攻擊成本顯現。
# COURSE QUOTE:
#   篇 20「漲太多已經不是第一次突破前高的，就不在此限」
#   篇 20「跳空攻擊算得上是攻擊成本浮現之後，明日 K 線是『繼續攻擊』的最佳解答」
#   篇 20「至此已經不用再判斷會不會轉變，而是開始設定移動停利」
#   行進ing 39「突破新高價的當天，前面要有兩個半月到三個月的整理區間」
#   明日 K 線 §20「突破前高，整理期間超過三個月」
# COURSE NUMBER? Yes (inferred) — 「三個月整理」= 60 交易日（一個月 ≈ 20 交易日）。
#   course_principles.md 既有 code 已用 prior_high_60（60 日）作為「型態突破」lookback。
#   ATTACK_COST_FIRST_BREAKOUT_LOOKBACK_DAYS 應與 prior_high_60 / FIRST_BREAKOUT_LOOKBACK 對齊。
#
# RATIONALE:
#   - 3693 2022-12-08 → 12/09/12 連續漲停（2-4 交易日）= 同段攻擊、60 日窗口仍抑制 ✓
#   - 3693 2023-01-16 → 2023-04-11（48 交易日 + -18% 深回檔）= 48 < 60，60 日窗口
#     需確認 2023-01-16 到 2023-04-11 間 close 未跌回 prior_high_60 以下才算「同段」
#   ⚠️ 3693 2023-04-11 案例需重驗（step 3 sanity）。
# PROXY VALUE: 60 個交易日（對齊課程「三個月整理」+ prior_high_60 一致性）。
# COURSE CITATION: 行進ing §39、明日 K 線 §20
ATTACK_COST_FIRST_BREAKOUT_LOOKBACK_DAYS: int = 60  # 課程明示「三個月整理」≈ 60 交易日

# =============================================================================
# L1. low_price_threshold — 已移至 extras/low_price.py [EXTRAS]
# =============================================================================
# COURSE CONCEPT: 課程明示「低價股」是 §09 lowprice_first_pull_exit 的前提，
#   未明示元/股的數值。老師只用「低 / 中 / 高」相對概念描述。
# COURSE QUOTE: 「八張低價股，跟買一張百元的中價股，價格的風險一樣，籌碼風險更高一些」
# COURSE NUMBER? No — 課程無明示任何價格數字門檻。30 元是業界 proxy。
# STATUS: 已搬至 scripts/kline/extras/low_price.py [EXTRAS]，從本檔案移除。
# REASON: 課程未明示低價數字門檻 → 屬課程外 proxy → 必須物理隔離至 extras。
# 使用方式: from scripts.kline.extras.low_price import LOW_PRICE_THRESHOLD

# =============================================================================
# L2. high_long_black_envelopment_min_pct — 高檔長黑包覆 body 最低占幅
# =============================================================================
# COURSE CONCEPT: 明日 K 線 §11 「當黑K出現」— 「高檔長黑、包覆、實質賣壓」
# COURSE QUOTE: 「高檔長黑、包覆、實質有賣壓出現」（威剛 113-05-09 案例）
# COURSE NUMBER? No — [STUB-NEED-USER] 老師未明示「長黑」的 body% 門檻。
# PROXY VALUE: 0.04（body 佔開盤 4%；與 HIGH_LONG_BLACK_BODY_PCT_MIN 同步）。
HIGH_LONG_BLACK_ENVELOPMENT_MIN_PCT: float = 0.04  # [STUB-NEED-USER]

# =============================================================================
# L3. zhongshu_range_max_pct — 中樞窄幅整理上限 (明日 K 線 §02 中樞型態)
# =============================================================================
# COURSE CONCEPT: 中樞型態 = 先上漲 + 橫向盤整（不破紅 K 低點）。
# COURSE QUOTE: 「先上漲、橫向盤整，但是都沒有跌破原本先上漲的紅K低點」
# COURSE NUMBER? No — [STUB-NEED-USER] 課程質性描述、未明示窄幅 %。
# PROXY VALUE: 10%（過去 5 日 high-low 區間幅度 ≤ 10%）。
# RATIONALE: 「橫向」= 不大幅波動；採 10% 作為窄幅代理。
ZHONGSHU_RANGE_MAX_PCT: float = 0.10  # [STUB-NEED-USER]


# =============================================================================
# A24. merged_doji_carry_days — 合併十字線 forward-fill 窗口 (明日 K 線 §24)
# =============================================================================
# COURSE CONCEPT: 合併十字線「剛創新高」位置後 N 日，merged_high/merged_low 仍有效。
# COURSE QUOTE:
#   第 24 篇「明天的重點就得要攻擊，且這是一定要發生的，無法變成後天、大後天」
#   第 26 篇「明日就得開始攻擊，或者如果不打算攻擊，跌破合併十字線的低點作為確認不攻擊。」
# COURSE NUMBER? Yes — 課程明示「明日」就要表態、「無法變成後天、大後天」。
#   合併十字線高低點的有效性是「隔日一天」（carry = 1），不是 5 天 forward-fill。
#   5 日嚴重違反課程「明日就要表態、否則失效」的精神。
# PROXY VALUE: 1 個交易日（隔日即為判斷窗口）。
# COURSE CITATION: 明日 K 線 §24 E9A6F935298C7C5C2E269AA952AA1BB2
#   §26 EF7308E2336BF7BCE94142944DB580B1
MERGED_DOJI_CARRY_DAYS: int = 1  # 課程明示「明日就要表態、無法變成後天大後天」

# =============================================================================
# A26. defensive_low_lookback_days — 防守低點回看天數 (明日 K 線 §26)
# =============================================================================
# COURSE CONCEPT: 防守姿態「過去六天的低點」— 老師 9945 案例明示。
# COURSE QUOTE: 第 26 篇「過去六天的低點」（9945 潤泰新 案例）
# COURSE NUMBER? Partial — 「六天」是個案說明、課程未明示通則適用所有股票。
#   以 9945 案例數字作為代理，待 user 確認是否適用通則。
# PROXY VALUE: 6 個交易日（與 9945 案例一致）。
# [STUB-NEED-USER]: 「過去 N 日最低收盤」的通則天數老師未明示；
#   此處沿用 9945 案例的「六天」，為個案 proxy，需 user 確認通則。
DEFENSIVE_LOW_LOOKBACK_DAYS: int = 6  # [STUB-NEED-USER] — 老師 9945 案例個案數字

# =============================================================================
# INTRO-1. self_rescue_breakout constants (入門 §34 自救型突破)
# =============================================================================
# COURSE CONCEPT: 自救型突破 = 多頭 + 利空背景 → 防守 → 漸推前高 → 量縮突破 → 隔日跳空
# COURSE QUOTE (入門 §34):
#   「通常在大盤本來是多方趨勢，檯面上有很多個股在拉抬的階段，突然遇到了重大的利空使大盤
#    下跌，資金根本來不及從容離開，就會採取防守的做法來暫時先護住股價，但是漸漸的股價又
#    往上推升來到前高位置，這個背景是必要條件。」
#   「隨著利空的逐漸鈍化，股價又突破了前高。此時成交量卻出現了比前高萎縮的跡象」
#   「自救型後的跳空是很重要的研判要點」
#   「如果這次突破比上次量增，那就不列為自救型突破的範圍了」
#
# COURSE NUMBER? Mostly NO — 老師明示「量縮」「時間遠近」但無數字。
# PROXY:
#   SELF_RESCUE_VOL_RATIO_MAX = 0.95 — 今日突破量 / 上次突破量 < 0.95 才算「明顯量縮」
#   SELF_RESCUE_PREV_BREAKOUT_LOOKBACK = 60 — 找「上次突破」的回看窗口（對齊 prior_high_60）
#   SELF_RESCUE_NEGATIVE_NEWS_LOOKBACK = 10 — 近期大盤下跌的回看窗口（利空背景）
#   SELF_RESCUE_TAIEX_DROP_PCT = 0.02 — 大盤單日跌 ≥ 2% 視為「重大利空」proxy
# [STUB-NEED-USER]: 老師「重大利空」是定性描述、未給跌幅 %；2% proxy 待 user 確認
SELF_RESCUE_VOL_RATIO_MAX: float = 0.95  # [STUB-NEED-USER] 「量縮」門檻
SELF_RESCUE_PREV_BREAKOUT_LOOKBACK: int = 60  # 對齊 prior_high_60
SELF_RESCUE_NEGATIVE_NEWS_LOOKBACK: int = 10  # [STUB-NEED-USER] 利空回看窗口
SELF_RESCUE_TAIEX_DROP_PCT: float = 0.02  # [STUB-NEED-USER] 「重大利空」單日跌幅 proxy

# =============================================================================
# INTRO-2. same_level_red_then_black light (入門 §07 + §30)
# =============================================================================
# COURSE CONCEPT: 同價位反覆紅K → 隔日黑K = 實質賣壓（§30 獲利了結賣壓的第二類）
# COURSE QUOTE (§07):
#   「同一個價位紅K的隔天就出現黑K，次數多了就顯是有實質賣壓存在」
# COURSE QUOTE (§30):
#   「到了某個價位就會多次出現紅K(上漲)接續著黑K(賣盤)的走勢，次數多了、時間久了…」
#
# COURSE NUMBER? NO — 老師明示「次數多了」「時間久了」但無確切數字。
# PROXY:
#   SAME_LEVEL_LOOKBACK_DAYS = 5 — 看回 5 日內
#   SAME_LEVEL_RED_MIN_COUNT = 2 — 至少 2 根紅K 收盤接近今日 close（=「多次」）
#   SAME_LEVEL_PRICE_TOLERANCE = 0.02 — 「接近」= ±2%
SAME_LEVEL_LOOKBACK_DAYS: int = 5  # [STUB-NEED-USER] 「次數多了」回看窗口
SAME_LEVEL_RED_MIN_COUNT: int = 2  # [STUB-NEED-USER] 「次數多了」最小紅K 數
SAME_LEVEL_PRICE_TOLERANCE: float = 0.02  # [STUB-NEED-USER] 「同一個價位」容差

# =============================================================================
# INTRO-T18. trailing_stop_slow_push retrace % (入門 出場(二) 移動停利)
# =============================================================================
# COURSE CONCEPT: 「移動停利是一個必備的操作模式、主要用來應對緩慢推升型」
# COURSE QUOTE: 入門 出場(二) 移動停利章節
# COURSE NUMBER? No — 老師明示「移動」概念、未給回撤 %。
# PROXY VALUE: 0.05（5% 回撤）。
# RATIONALE: 「緩慢推升」一根長黑通常 4-6%；5% 為中間值代理。
SLOW_PUSH_RETRACE_PCT: float = 0.05  # [STUB-NEED-USER] 緩慢推升回撤門檻

# =============================================================================
# INTRO-T4. attack_intent_consecutive_red — 攻擊意圖闕如連續紅K 量化 (入門 §31)
# =============================================================================
# COURSE CONCEPT: 突破後若連續紅K但開盤無 gap-up、低開或開平 = 沒有攻擊意圖
# COURSE QUOTE (入門「紅色誤解」+ §31):
#   「攻擊的理論基礎就是剛剛開始就不會回頭、不可能給人又有太多機會低檔買進」
#   「突破之後遇到突破的隔天就開平或下跌、顯然不具備攻擊意願」
# COURSE NUMBER? No — 老師明示「突破隔天」單日現象，亦明示「連續」傾向；
#   為 scoring 退化版本：突破日後 N 日內連續紅 K 但無 gap-up 的天數。
# PROXY:
#   ATTACK_INTENT_WINDOW_DAYS = 5 — 突破後觀察視窗（對齊 ATTACK_WINDOW_DAYS=5）
#   ATTACK_INTENT_RED_NO_GAP_MIN = 2 — 至少 2 個「紅 K + 無 gap-up」即視為「無攻擊意圖」
#   ATTACK_INTENT_PENALTY_PER_DAY = -1.0 — 每 1 個無攻擊意圖日扣 1 分（capped）
#   ATTACK_INTENT_MAX_PENALTY = -3.0
ATTACK_INTENT_WINDOW_DAYS: int = 5  # [STUB-NEED-USER] 突破後觀察窗
ATTACK_INTENT_RED_NO_GAP_MIN: int = 2  # [STUB-NEED-USER] 觸發最小天數
ATTACK_INTENT_PENALTY_PER_DAY: float = -1.0  # course-not-stated magnitude
ATTACK_INTENT_MAX_PENALTY: float = -3.0  # course-not-stated cap

# =============================================================================
# INTRO-16. consolidation_over_2_5_months + ma60_falling (入門 §07 + §21)
# =============================================================================
# COURSE CONCEPT: 整理區間超過兩個半月 + 季線下彎 = 中期轉空訊號
# COURSE QUOTE: 「整理區間超過兩個半月、那麼接下來要留意的就是季線、
#               一旦季線下彎表示中期趨勢已經轉為空頭」
# COURSE NUMBER? Yes — 老師明示「兩個半月」≈ 50 個交易日。
# PROXY VALUE:
#   CONSOLIDATION_LONG_DAYS = 50 (兩個半月 × 20 交易日 / 月 ≈ 50)
#   CONSOLIDATION_LONG_RANGE_MAX_PCT = 0.20 — 整理區間 high-low / mid ≤ 20% (proxy)
CONSOLIDATION_LONG_DAYS: int = 50  # 課程「兩個半月」≈ 50 交易日
CONSOLIDATION_LONG_RANGE_MAX_PCT: float = 0.20  # [STUB-NEED-USER] 「整理」範圍代理

# =============================================================================
# INTRO-9. early_deployment_volume — 提前部署量超套牢區量 (入門「成本原理」)
# =============================================================================
# COURSE CONCEPT: 當前成交量已超過過往套牢區的量（但價未突破）= 提前部署
# COURSE QUOTE (course_principles): 「當前成交量已超過過往套牢區的量
#               （價格還沒突破），表示有資金提前部署」
# COURSE NUMBER? No — 老師明示「超過」、未給倍數。
# PROXY:
#   EARLY_DEPLOY_RESISTANCE_LOOKBACK_DAYS = 60 — 套牢區回看
#   EARLY_DEPLOY_VOL_MULTIPLE = 1.0 — 超過即觸發（不要求倍數）
EARLY_DEPLOY_RESISTANCE_LOOKBACK_DAYS: int = 60
EARLY_DEPLOY_VOL_MULTIPLE: float = 1.0  # 課程明示「超過」、未給倍數


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
    # C08–C14 constants
    "ATTACK_CONTINUITY_SCORE_UNIT",
    "PATTERN_PRESSURE_SCORE_UNIT",
    "PATTERN_PRESSURE_SUPPLY_MAX",
    "MA60_BEARISH_NO_CONFIRM_BONUS",
    "ZHONGSHU_MIN_DAYS",
    "ZHONGSHU_MAX_DAYS",
    "WEAK_BULL_MA_DAYS",
    "MERGED_DOJI_BODY_RATIO",
    "MERGED_DOJI_SHADOW_MIN_RATIO",
    # AT_PRESSURE_RETEST_PCT — 已廢棄，改用二元觸及條件（課程無 % 門檻）
    # A20 attack_cost_displayed constants
    "ATTACK_COST_LIMIT_UP_THRESHOLD",
    "ATTACK_COST_VOL_RATIO",
    "ATTACK_COST_FIRST_BREAKOUT_LOOKBACK_DAYS",
    # L1-L3 lights-fix STUB constants (2026-06-04)
    "LOW_PRICE_THRESHOLD",  # 入門 §09 概念內、數字 STUB-NEED-USER
    "HIGH_LONG_BLACK_ENVELOPMENT_MIN_PCT",
    "ZHONGSHU_RANGE_MAX_PCT",
    # A24/A26 advanced field wiring STUB constants (2026-06-05)
    "MERGED_DOJI_CARRY_DAYS",
    "DEFENSIVE_LOW_LOOKBACK_DAYS",
    # INTRO concepts impl (2026-06-05) — 入門 §34 / §07 §30 / §49 §10
    "SELF_RESCUE_VOL_RATIO_MAX",
    "SELF_RESCUE_PREV_BREAKOUT_LOOKBACK",
    "SELF_RESCUE_NEGATIVE_NEWS_LOOKBACK",
    "SELF_RESCUE_TAIEX_DROP_PCT",
    "SAME_LEVEL_LOOKBACK_DAYS",
    "SAME_LEVEL_RED_MIN_COUNT",
    "SAME_LEVEL_PRICE_TOLERANCE",
    # INTRO-tier-2 (2026-06-06) — 入門 出場(二) / §31 / §07 + §21 / 「成本原理」
    "SLOW_PUSH_RETRACE_PCT",
    "ATTACK_INTENT_WINDOW_DAYS",
    "ATTACK_INTENT_RED_NO_GAP_MIN",
    "ATTACK_INTENT_PENALTY_PER_DAY",
    "ATTACK_INTENT_MAX_PENALTY",
    "CONSOLIDATION_LONG_DAYS",
    "CONSOLIDATION_LONG_RANGE_MAX_PCT",
    "EARLY_DEPLOY_RESISTANCE_LOOKBACK_DAYS",
    "EARLY_DEPLOY_VOL_MULTIPLE",
]
