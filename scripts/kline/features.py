"""Derived features for kline conditions.

Course source: features support multiple course concepts; no single article.

Input: bars DataFrame from bars.load_bars(), sorted by (ticker, trade_date).
Output: same DataFrame with derived columns added (spec §3.2).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .patterns._common import is_anomalous_volume as _is_anomalous_volume
from .course_proxy_constants import (
    ATTACK_HIGHER_HIGH_MIN_5DAY,
    ATTACK_HIGHER_LOW_MIN_5DAY,
    ATTACK_WINDOW_DAYS,
    DOJI_MAX_BODY_PCT,
    DOJI_MIN_RANGE_PCT,
    FIRST_BREAKOUT_LOOKBACK,
    INTEGRATION_DAYS as _INTEGRATION_DAYS,
    RISING_LOWS_MIN_FRAC,
    STABLE_UPPER_MAX_SPREAD as _STABLE_UPPER_MAX_SPREAD,
)


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add all derived features. Pure function — returns new DataFrame."""
    df = df.copy()
    g = df.groupby("ticker", group_keys=False)

    # Previous-bar values
    df["prev_close"] = g["close"].shift(1)
    df["prev_open"] = g["open"].shift(1)
    df["prev_high"] = g["high"].shift(1)
    df["prev_low"] = g["low"].shift(1)

    # Rolling prior highs/lows (exclude today via shift).
    # NOTE: must use transform to keep rolling WITHIN each ticker.
    # Earlier `g["x"].shift(1).rolling(N)` rolled across ticker boundaries
    # because the rolling ran on a flat Series after the groupwise shift.
    df["prior_high_60"] = g["high"].transform(lambda s: s.shift(1).rolling(60, min_periods=60).max())
    # DSL alias: condition YAML uses "prev_high_60"; features.py uses "prior_high_60".
    # Both columns carry the same value. "prev_high_60" is whitelisted in condition.py.
    df["prev_high_60"] = df["prior_high_60"]
    df["prior_high_20"] = g["high"].transform(lambda s: s.shift(1).rolling(20, min_periods=20).max())
    df["prior_low_60"] = g["low"].transform(lambda s: s.shift(1).rolling(60, min_periods=60).min())
    df["prior_low_20"] = g["low"].transform(lambda s: s.shift(1).rolling(20, min_periods=20).min())

    # Avg volume (excluding today) — same cross-ticker fix.
    df["avg_volume_20"] = g["volume"].transform(lambda s: s.shift(1).rolling(20, min_periods=20).mean())
    df["volume_ratio"] = df["volume"] / df["avg_volume_20"].replace(0, np.nan)

    # OHLC-derived
    df["range_pct"] = (df["high"] - df["low"]) / df["open"].replace(0, np.nan)
    df["body_abs"] = (df["close"] - df["open"]).abs()
    df["body_pct"] = df["body_abs"] / df["open"].replace(0, np.nan)
    df["close_pos"] = (df["close"] - df["low"]) / (df["high"] - df["low"]).replace(0, np.nan)

    # Shadows
    df["upper_shadow"] = df["high"] - df[["open", "close"]].max(axis=1)
    df["lower_shadow"] = df[["open", "close"]].min(axis=1) - df["low"]
    df["upper_shadow_ratio"] = df["upper_shadow"] / df["body_abs"].replace(0, np.nan)
    df["lower_shadow_ratio"] = df["lower_shadow"] / df["body_abs"].replace(0, np.nan)

    # MA60 slope (5-day) and 60-day-ago close (for 扣抵 prediction)
    df["ma60_slope_5d"] = df["ma60"] / g["ma60"].shift(5) - 1
    df["ma60_rolling_off_close"] = g["close"].shift(60)

    # Scoring input: consecutive days closing above MA60 prior to today, capped at 20.
    above_ma60 = (df["close"] > df["ma60"]).fillna(False).astype(int)
    df["pre_breakout_trend_days"] = (
        above_ma60.groupby(df["ticker"]).transform(
            lambda s: s.shift(1).fillna(0).rolling(20, min_periods=1).sum()
        ).astype(int)
    )

    # Scoring input: count of swing-high peaks above current close in trailing 240 days.
    # A peak at bar k is defined as high[k] == max(high[k-4:k+1]) (5-bar local max).
    # We iterate over lags 1..240 (shifted window, excludes today) and accumulate.
    LOOKBACK = 240
    n = len(df)
    peak_count = np.zeros(n, dtype=float)
    close_today = df["close"].to_numpy()
    for lag in range(1, LOOKBACK + 1):
        past_high = g["high"].shift(lag).to_numpy()
        past_max5 = (
            g["high"]
            .transform(lambda s: s.shift(lag).rolling(5, min_periods=5).max())
            .to_numpy()
        )
        is_peak = (past_high == past_max5) & ~np.isnan(past_max5)
        peak_count += ((past_high > close_today) & is_peak).astype(float)
    has_history = g.cumcount().to_numpy() >= 20
    df["overhead_supply_layer"] = np.where(has_history, peak_count, np.nan)

    # === Unfilled gap-down overhead resistance ===
    # Course source: 型態學 10-缺口壓力型態.
    # 向下跳空缺口未回補 = 型態壓力 (separate from swing-high overhead).
    #
    # Course quote: 「向下跳空的缺口表示這個價位區間沒有任何人成交……
    #   這個價位卻沒有任何買單願意承接股價，於是就形成了缺口壓力的明顯壓力狀態。」
    # Quote: 「雖然不是實質套牢，但卻是一種型態上的壓力」
    # Quote: 「離現在最近的一個缺口壓力還沒有越過之前，都不宜對股價樂觀」
    #
    # Detection (vectorized lag-accumulation, matches overhead_supply_layer pattern):
    #   1. Gap-down day: today's high < prev_low
    #      (the price range [high, prev_low] had ZERO trades — a true K-line gap)
    #   2. Gap still overhead: gap_top (= prev_low on that day) is above today's close.
    #      Proxy: "today's close still below gap_top" means the gap hasn't been crossed.
    #      If today's close > gap_top the gap is no longer overhead supply.
    #   3. Count how many such unfilled gaps exist ABOVE current price in past 240 days.
    #
    # Proxy limitation: this counts a gap as "unfilled" if today's close is below gap_top.
    # It does NOT verify that every bar between then and now stayed below gap_top.
    # A gap that was temporarily crossed and then dropped back would still show 0 if
    # the current close is above gap_top. This is a known simplification; the practical
    # effect is minimal because such round-trip cases are rare and the course focuses on
    # the current overhead state, not the path taken.

    GAP_RESISTANCE_LOOKBACK = 240

    unfilled_gap_count = np.zeros(n, dtype=float)
    for lag in range(1, GAP_RESISTANCE_LOOKBACK + 1):
        past_high_l = g["high"].shift(lag).to_numpy()
        past_prev_low_l = g["prev_low"].shift(lag).to_numpy()
        # Was that historical bar a gap-down day? (strict K-line gap: high < prev_low)
        was_gap_down = past_high_l < past_prev_low_l
        # Gap top = the prev_low on that day (upper bound of the empty zone)
        gap_top = past_prev_low_l
        # Gap is still overhead: gap_top is above today's close (not yet crossed)
        above_today = gap_top > close_today
        unfilled = was_gap_down & above_today & ~np.isnan(gap_top)
        unfilled_gap_count += unfilled.astype(float)

    df["unfilled_gap_down_count_240d"] = np.where(has_history, unfilled_gap_count, np.nan)

    # K-line color
    df["is_red"] = df["close"] > df["open"]
    df["is_black"] = df["close"] < df["open"]
    # Proxy: course says doji = 「近乎沒有實體」 (qualitative). We operationalize
    # via body_pct ≤ 0.6% (近乎沒有實體) AND range_pct ≥ 1.5% (meaningful range).
    # See course_proxy_constants.I7 for full rationale; no course-stated number.
    df["is_doji"] = (df["body_pct"] <= DOJI_MAX_BODY_PCT) & (df["range_pct"] >= DOJI_MIN_RANGE_PCT)

    # 破底型態 detection
    # Course source: 型態學 16-破底型態 (pseudocode at end of the article)
    #
    # Implementation note (proxy):
    #   The course's own pseudocode uses `low < prior_low_20` as the "new-low"
    #   event signal. This is a coarse proxy for "破前低 / swing low":
    #   strictly speaking, "前低" means the previous swing low (local minimum),
    #   but the course defines this computationally as breaking the rolling 20-day
    #   prior min. We follow the course's exact pseudocode.
    #
    # Definition: >= 2 new-low events in past 60 days AND MA60 declining.
    #
    # Course rule: automatically exclude from scanner candidacy.
    # Reason: layered supply + no way to clear without absent reason or trend change.
    # Course quote: 「離最近壓力越過、或空方趨勢結束之前，都不能有摸底的想法」
    #
    # A "new-low event" = today's low broke the 20-day prior swing low.
    # BREAKDOWN_THRESHOLD = 2 implements 「不只一次」(more than once → ≥ 2).

    BREAKDOWN_WINDOW = 60          # ~3 months lookback
    BREAKDOWN_THRESHOLD = 2        # course says "不只一次" = more than once ≥ 2

    new_low_event = df["low"] < df["prior_low_20"]
    new_low_count_60d = (
        new_low_event
        .groupby(df["ticker"])
        .rolling(BREAKDOWN_WINDOW, min_periods=BREAKDOWN_WINDOW)
        .sum()
        .reset_index(level=0, drop=True)
    )
    df["new_low_count_60d"] = new_low_count_60d

    is_ma60_down = df["ma60_slope_5d"].fillna(0) < 0

    df["is_in_breakdown_pattern"] = (
        (new_low_count_60d >= BREAKDOWN_THRESHOLD)
        & is_ma60_down
    ).fillna(False)

    # === Pattern breakout — course-faithful 起點 detection (5 conditions, ALL AND) ===
    # Course sources (all conditions are AND-combined):
    #   A. 低點墊高 — 型態學 03-箱型整理 + 14-推升攻擊 + 行進ing 推升攻擊
    #   B. 上緣穩定 — 型態學 05-三角收斂 (上升三角 = 低點升 + 上緣平)
    #   C. 上方無套牢 — 型態學 08-騙線型態 + 行進ing 24-跳空篇三 + 入門 賣壓化解
    #      「上有壓力的突破 = 最常見的陷阱」
    #      「攻擊跳空的精確邊界 = 過去沒有成交過的價位區段」
    #      「等到越過了之後才能確定有攻擊意願」
    #   D. 突破前高 — 入門 突破跌破
    #   E. 季線多頭背景 — 入門 MA60 必要條件
    #
    # Definition (course-aligned):
    #   主力收貨的整理型態 = 低點漸漸墊高 + 上緣穩定（壓力線）+ 上方無套牢
    #   Breakout above the stable upper boundary, with overhead cleared = TRUE 起點
    #
    # NOT: a "sleeping" flat-range stock (no rising lows = no 主力收貨 signal).
    # NOT: a breakout into overhead supply (= 騙線型態).

    # Course-stated: integration window ≈ 3 months (型態學 03).
    INTEGRATION_DAYS = _INTEGRATION_DAYS  # 60 trading days ~ 3 months

    # === A. Rising lows count ===
    # How many days in past 60 had higher_low (low > prev_low)?
    # Course-aligned threshold: at least HALF the bars must be rising-low.
    higher_low_indicator = (df["low"] > df["prev_low"]).astype(int)
    df["higher_low_count_60d"] = (
        higher_low_indicator
        .groupby(df["ticker"])
        .rolling(INTEGRATION_DAYS, min_periods=INTEGRATION_DAYS)
        .sum()
        .reset_index(level=0, drop=True)
    )
    # Proxy: course says 「低點漸漸墊高」 (qualitative). We require at least
    # half the integration bars to have higher-low (30 of 60). Course-not-stated;
    # see course_proxy_constants.I3.
    RISING_LOWS_MIN = int(INTEGRATION_DAYS * RISING_LOWS_MIN_FRAC)  # 30 of 60

    # === B. Stable upper boundary ===
    # The 60-day ceiling should not have risen from the first half to the second half.
    # Measured by comparing:
    #   - prior_high_60: the overall 60-day ceiling (rolling max of shift(1) over 60 bars)
    #   - prior_high_30_early: rolling max of the FIRST half (shift(31) over 30 bars)
    # Spread = (prior_high_60 - prior_high_30_early) / prior_high_60
    #   - Triangle pattern: ceiling is the same throughout → spread ≈ 0
    #   - Trending stock: early-half max << late-half max → spread is large
    prior_high_30_early = (
        g["high"].transform(lambda s: s.shift(31).rolling(30, min_periods=30).max())
    )
    upper_band_spread = (
        (df["prior_high_60"] - prior_high_30_early) / df["prior_high_60"].replace(0, np.nan)
    )
    df["upper_band_spread_60d"] = upper_band_spread.fillna(1.0)
    # Proxy: course says 「上緣穩定」 / 「壓力線是平的」 (qualitative).
    # We operationalize as early-half max ≤ 5% below full-window max.
    # No course-stated number; see course_proxy_constants.I2.
    STABLE_UPPER_MAX_SPREAD = _STABLE_UPPER_MAX_SPREAD  # 0.05

    # === C. is_pattern_breakout (course-faithful, 5 conditions ALL AND) ===
    # Course condition C: 上方無套牢 (clean overhead)
    # Source: 型態學 08-騙線型態 + 行進ing 24-跳空篇三 + 入門 賣壓化解
    #         + 型態學 10-缺口壓力型態 (向下跳空缺口未回補 = 型態上的壓力)
    # "上有壓力的突破 = 最常見的陷阱"
    # Overhead supply must be cleared BEFORE breakout to qualify as genuine 起點.
    # "clean overhead" now covers BOTH forms of course-defined overhead pressure:
    #   (1) swing-high peaks (overhead_supply_layer) — 套牢型壓力
    #   (2) unfilled gap-down zones (unfilled_gap_down_count_240d) — 型態型壓力
    is_clean_overhead = (
        (df["overhead_supply_layer"].fillna(0) <= 0)
        & (df["unfilled_gap_down_count_240d"].fillna(0) <= 0)
    )

    df["is_pattern_breakout"] = (
        (df["higher_low_count_60d"] >= RISING_LOWS_MIN)         # A. 低點墊高
        & (df["upper_band_spread_60d"] <= STABLE_UPPER_MAX_SPREAD)  # B. 上緣穩定
        & is_clean_overhead                                      # C. 上方無套牢
        & (df["close"] > df["prior_high_60"])                   # D. 突破前高
        & df["ma60"].notna()                                     # E. 季線多頭背景
        & (df["close"] > df["ma60"])
    ).fillna(False)

    # === Attack intensity level (型態學 攻擊型態 four-pattern ranking) ===
    # Course source: 型態學 12 (日出) + 13 (跳空) + 14 (推升) + 15 (波動前進).
    #
    # Levels:
    #   4 = 日出攻擊 (sunrise: high>prev_high AND low>prev_low for past 3 days,
    #                 plus close > prior_high_60)
    #   3 = 跳空攻擊 (gap attack: open > prev_high AND low > prev_high, today is breakout day,
    #                 prev day was a breakout-red K)
    #   2 = 推升攻擊 (push attack: rising lows over past 5 days + close > prior_high_60)
    #   1 = 波動前進 (wave forward: higher highs over past 5 days + bodies overlap heavily)
    #   0 = none
    #
    # Detection order: 4 > 3 > 2 > 1 > 0 (higher levels override lower).

    above_prior_high_60 = df["close"] > df["prior_high_60"]

    # Level 4: 日出攻擊 — 3 consecutive sunrise bars + above prior_high_60
    is_sunrise_bar = (df["high"] > df["prev_high"]) & (df["low"] > df["prev_low"])
    sunrise_3day = (
        is_sunrise_bar
        .groupby(df["ticker"])
        .rolling(3, min_periods=3)
        .sum()
        .reset_index(level=0, drop=True)
    )
    is_sunrise_attack = (sunrise_3day >= 3) & above_prior_high_60

    # Level 3: 跳空攻擊 — prev was breakout-red K, today is gap up + unfilled
    prev_close_gap = g["close"].shift(1)
    prev_open_gap = g["open"].shift(1)
    prev_high_prev = g["prior_high_60"].shift(1)
    prev_was_breakout_red = (prev_close_gap > prev_high_prev) & (prev_close_gap > prev_open_gap)
    today_gap_up = df["open"] > df["prev_high"]
    today_no_fill = df["low"] > df["prev_high"]
    is_gap_attack = prev_was_breakout_red & today_gap_up & today_no_fill

    # Level 2: 推升攻擊 — rising lows 5-day + breakout
    is_higher_low = df["low"] > df["prev_low"]
    higher_low_5day = (
        is_higher_low
        .groupby(df["ticker"])
        .rolling(ATTACK_WINDOW_DAYS, min_periods=ATTACK_WINDOW_DAYS)
        .sum()
        .reset_index(level=0, drop=True)
    )
    # Proxy: course says 推升攻擊 = 「連續低點不斷墊高」 (qualitative, no count).
    # We require ≥ 4 of 5 days had higher-low. Course-not-stated; see
    # course_proxy_constants.I1.
    is_push_attack = (higher_low_5day >= ATTACK_HIGHER_LOW_MIN_5DAY) & above_prior_high_60

    # Level 1: 波動前進 — higher highs 5-day + bodies overlap
    is_higher_high = df["high"] > df["prev_high"]
    higher_high_5day = (
        is_higher_high
        .groupby(df["ticker"])
        .rolling(ATTACK_WINDOW_DAYS, min_periods=ATTACK_WINDOW_DAYS)
        .sum()
        .reset_index(level=0, drop=True)
    )
    # Body overlap = body abs is small relative to range
    body_overlap_proxy = df["body_pct"].fillna(0) < df["range_pct"].fillna(1) * 0.3
    # Proxy: course says 波動前進 = 「高點不斷墊高」 (qualitative, no count).
    # We require ≥ 4 of 5 days had higher-high. Course-not-stated; see
    # course_proxy_constants.I1.
    is_wave_forward = (higher_high_5day >= ATTACK_HIGHER_HIGH_MIN_5DAY) & body_overlap_proxy & above_prior_high_60

    # Combine: higher levels override lower
    attack_intensity = pd.Series(0, index=df.index)
    attack_intensity = attack_intensity.mask(is_wave_forward.fillna(False), 1)
    attack_intensity = attack_intensity.mask(is_push_attack.fillna(False), 2)
    attack_intensity = attack_intensity.mask(is_gap_attack.fillna(False), 3)
    attack_intensity = attack_intensity.mask(is_sunrise_attack.fillna(False), 4)

    df["attack_intensity"] = attack_intensity.astype(int)

    # === prev_bar_had_attack_meaning ===
    # Course source: 紅K篇(二) / 買點與攻擊研判.
    # "前一日低點" only counts as an attack stop when the previous bar had
    # 攻擊意義. Course defines 攻擊意義 as one of:
    #   (a) red K creating new 60-day high (close > prior_high_60)
    #   (b) upper-shadow K at new high (high > prior_high_60 with upper shadow)
    #   (c) doji follow-up after a red attack K (yesterday's doji after a
    #       red-K-at-new-high two bars ago)
    #
    # Proxy notes:
    #   - "upper-shadow K at new high" — we use upper_shadow > body_abs as proxy
    #     for the course's "上影線" definition; course gives qualitative description.
    #   - "doji follow-up" — yesterday is a doji AND the bar before was a
    #     red K at a new 60-day high.
    prev_is_red = g["is_red"].shift(1).fillna(False)
    prev_close_v = g["close"].shift(1)
    prev_prior_high_60 = g["prior_high_60"].shift(1)
    prev_high_v = g["high"].shift(1)
    prev_upper_shadow = g["upper_shadow"].shift(1)
    prev_body_abs = g["body_abs"].shift(1)
    prev_is_doji = g["is_doji"].shift(1).fillna(False)

    # (a) red K at new 60-day high
    cond_a = prev_is_red & (prev_close_v > prev_prior_high_60)
    # (b) upper-shadow K at new high (high broke prior_high_60 with sizeable upper shadow)
    cond_b = (prev_high_v > prev_prior_high_60) & (prev_upper_shadow > prev_body_abs.replace(0, np.nan))
    # (c) doji follow-up after a red K at new high
    prev2_is_red = g["is_red"].shift(2).fillna(False)
    prev2_close = g["close"].shift(2)
    prev2_prior_high_60 = g["prior_high_60"].shift(2)
    cond_c = prev_is_doji & prev2_is_red & (prev2_close > prev2_prior_high_60)

    df["prev_bar_had_attack_meaning"] = (cond_a | cond_b | cond_c).fillna(False)

    # === is_first_breakout_above_level ===
    # Course source: 突破跌破 — 突破意義的釐清.
    # Course quote: 「第一次突破，可以直接進攻；再次突破，需等隔日攻擊確認」
    #
    # A bar is the FIRST breakout if it is the first bar within the trailing
    # FIRST_BREAKOUT_LOOKBACK window where close > prior_high_60. Subsequent
    # close-above-prior_high_60 bars within the window are "re-breakouts".
    #
    # Implementation: count how many prior bars in the lookback window
    # (excluding today) already had close > their prior_high_60. If zero,
    # today is the FIRST breakout.
    breakout_indicator = (df["close"] > df["prior_high_60"]).fillna(False).astype(int)
    prior_breakout_count = (
        breakout_indicator
        .groupby(df["ticker"])
        .shift(1)
        .fillna(0)
        .groupby(df["ticker"])
        .rolling(FIRST_BREAKOUT_LOOKBACK, min_periods=1)
        .sum()
        .reset_index(level=0, drop=True)
    )
    df["is_first_breakout_above_level"] = (
        (breakout_indicator == 1) & (prior_breakout_count == 0)
    ).fillna(False)

    # === is_attack_bar ===
    # Used by re-breakout confirmation (I4). An "attack bar" continues the
    # breakout: red K closing above prior bar's close, OR gap-up, OR new high.
    # Course quote (突破跌破): 「攻擊確認 = 隔日續攻 / 跳空 / 創新高」
    #
    # Empirical note (2026-05-16): tightening to new-high-only (the strictest
    # OR option) did NOT improve metrics — see docs/analysis/2026-05-16-i4-
    # confirmation-strictness-test.md. The course states three OR options,
    # broad form is the literal reading; we keep it.
    df["is_attack_bar"] = (
        (df["is_red"].fillna(False) & (df["close"] > df["prev_close"]))
        | (df["open"] > df["prev_high"])
        | (df["high"] > df["prior_high_60"])
    ).fillna(False)

    # === Pattern-layer derived columns (多空轉折組合 K 線 patterns/) ===
    # Course source: 多空轉折組合K線 26 篇 + PATTERN_DEFINITIONS.md.
    # These are simple structural facts (no proxy numbers) reused by many
    # patterns. Added at the END to keep backward compatibility — no existing
    # column is touched.

    # 日落 (sunset) — high < prev_high AND low < prev_low. Mirror of is_sunrise_bar
    # used inside attack_intensity above. Used by hanging_man (P05), bear_single_day (P16).
    df["is_sunset_bar"] = (df["high"] < df["prev_high"]) & (df["low"] < df["prev_low"])

    # 孕線 / 懷抱 (harami) — high <= prev_high AND low >= prev_low (today fully
    # inside prev day's range). Used by morning_star (P04, P06), harami_neutral (P21),
    # internal_trap (P24).
    df["is_harami"] = (df["high"] <= df["prev_high"]) & (df["low"] >= df["prev_low"])

    # K 棒中值 — (open + close) / 2. Course明示 (第 03 篇). Used by morning_star,
    # enemy_at_gate, evening_star, piercing.
    df["midpoint"] = (df["open"] + df["close"]) / 2

    # 跳空 (gap up / gap down) — strict K-line gap definition (no overlap with prev range).
    df["is_gap_up_today"] = df["low"] > df["prev_high"]
    df["is_gap_down_today"] = df["high"] < df["prev_low"]

    # body_pct percentile rank over trailing 20 days (excluding today).
    # Used by is_power_bar Option B (currently OFF — see patterns/_common.py).
    # We rank today's body_pct against the prior 20-bar window.
    def _pct_rank(s):
        if s.isna().all() or len(s) < 2:
            return float("nan")
        # rank today's value within the prior window
        prior = s.iloc[:-1].dropna()
        today = s.iloc[-1]
        if pd.isna(today) or len(prior) == 0:
            return float("nan")
        return (prior < today).sum() / len(prior)

    df["body_pct_pct_rank_20d"] = (
        df.groupby("ticker")["body_pct"]
        .rolling(21, min_periods=10)
        .apply(_pct_rank, raw=False)
        .reset_index(level=0, drop=True)
    )

    # =====================================================================
    # Task 2.4 additions — 明日 K 線 INVENTORY C03 / C04 / C05 / C07
    # Added at the END; no existing column is modified.
    # =====================================================================

    # === C03: 攻擊意圖區 / 攻擊企圖區 boundary features ===
    # Course source: 明日 K 線 INVENTORY.md §C03 (第 23、32 篇)
    #
    # 攻擊意圖區 = 從低檔往上靠近前高、賣壓化解的區段（突破前高之前）
    # 攻擊企圖區 = 突破前高之後的價位區段（突破點往上，不可跌回意圖區）
    #
    # Columns:
    #   attack_intent_zone_high — 意圖區上緣（突破前高當日的高點）
    #                             = prior_high_60 at the breakout bar
    #                             Implementation: rolling window max of
    #                             (high on bars where close > prior_high_60),
    #                             using a 20-bar lookback.
    #
    #   attack_intent_zone_low  — 意圖區下緣（突破前高之前 N 日的最低 close）
    #                             退化值 [STUB-NEED-USER S6]:
    #                             min(close) over the 20 bars before breakout.
    #                             Implementation: rolling 20-bar prior min close.
    #
    #   intent_zone_break       — 今日 close 跌回攻擊意圖區（跌破意圖區上緣）
    #                             = today_close < attack_intent_zone_high
    #
    # Note on attack_intent_zone_high:
    #   We track the most recent prior_high_60 value among bars where a breakout
    #   occurred in the trailing 20 days. If no breakout occurred, we fall back
    #   to the current prior_high_60 as the "potential" intent zone ceiling.
    #
    # [STUB-NEED-USER S6]: 意圖區下緣（賣壓化解起點）的精確計算需 user 確認。
    #   退化值：過去 20 日最低收盤，作為賣壓化解區段的下緣估算。

    # 攻擊意圖區上緣：找過去 20 天內最近一次突破前高的當日 prior_high_60
    # Vectorized: on each day, look back up to 20 bars for a breakout bar
    # (close > prior_high_60) and pick the prior_high_60 of that bar.
    # For simplicity / efficiency: roll 20-bar max of (prior_high_60 * breakout_flag).
    # When no breakout in window, returns NaN.
    breakout_ph60 = df["prior_high_60"].where(
        (df["close"] > df["prior_high_60"]).fillna(False)
    )
    df["attack_intent_zone_high"] = (
        g["close"]
        .transform(lambda _s: breakout_ph60.reindex(_s.index)
                   .rolling(20, min_periods=1).apply(
                       lambda x: x.dropna().iloc[-1] if x.dropna().shape[0] > 0 else float("nan"),
                       raw=False,
                   ))
    )

    # 攻擊意圖區下緣：過去 20 日收盤最低值（退化值 STUB S6）
    df["attack_intent_zone_low"] = g["close"].transform(
        lambda s: s.shift(1).rolling(20, min_periods=1).min()
    )

    # 跌回攻擊意圖區 flag
    df["intent_zone_break"] = (
        df["close"] < df["attack_intent_zone_high"].fillna(df["prior_high_60"])
    ).fillna(False)

    # === C04: 剛創新高 label ===
    # Course source: 明日 K 線 INVENTORY.md §C04 (第 03、10、24、40 篇)
    #
    # 「剛創新高」= 今日或前 1~2 日的高點 == 當時的 60 日前高（prior_high_60）
    # 用途：合併十字線、攻擊成本、防守姿態等多個明日 K 線劇本都需要此位置條件。
    #
    # Definition (from INVENTORY §C04):
    #   is_just_broke_high = (today.high >= prior_high_60)
    #                      OR (prev.high >= prev.prior_high_60)
    #                      OR (prev_prev.high >= prev_prev.prior_high_60)
    #
    # "≥" is used (not "==") because a gap-up breakout bar may close above
    # prior_high_60 while the high itself exceeds it. The INVENTORY wording
    # "(high == prior_high_60)" is a course-level conceptual shorthand for
    # "touched or broke the 60-day prior high".

    prev_high_ph60_match = (
        g["high"].shift(1) >= g["prior_high_60"].shift(1)
    ).fillna(False)
    prev2_high_ph60_match = (
        g["high"].shift(2) >= g["prior_high_60"].shift(2)
    ).fillna(False)

    df["is_just_broke_high"] = (
        (df["high"] >= df["prior_high_60"])
        | prev_high_ph60_match
        | prev2_high_ph60_match
    ).fillna(False)

    # === C04b: 剛創新高（盤中版）label ===
    # Course source: 明日 K 線 第 24 篇《合併十字線》
    #
    # 老師原文（E9A6F935298C7C5C2E269AA952AA1BB2）：
    #   「股價在剛創新高的位置，長十字線代表的是盤中有過先上漲的拉抬」
    #   「創新高的上影線也是攻擊過的意義」
    #   「位置就在剛創新高的狀態」
    #
    # 關鍵差異：
    #   is_just_broke_high（C04）   = close >= prior_high_60（收盤突破）
    #   is_just_broke_high_intraday = high  >= prior_high_60（盤中觸及即算）
    #
    # 課程明示「盤中有過攻擊的力量」= 上影線創新高（high >= prior_high_60），
    # 不一定要收盤突破。此變體專為 merged_doji 新增，不改動原有 is_just_broke_high。
    #
    # 窗口：今日、前 1 日、前 2 日（同 C04 三天窗口，用 high 取代 close）。
    #
    # [STUB-NEED-USER S5]:
    #   「盤中創新高」的定義已由課程明示（high > prior_high_60），
    #   但「前 2 日」窗口（今日 + D-1 + D-2）是否足夠，課程未明示窗口天數。
    #   沿用 C04 的三天窗口作為代理。

    prev_high_ph60_intraday = (
        g["high"].shift(1) >= g["prior_high_60"].shift(1)
    ).fillna(False)
    prev2_high_ph60_intraday = (
        g["high"].shift(2) >= g["prior_high_60"].shift(2)
    ).fillna(False)

    df["is_just_broke_high_intraday"] = (
        (df["high"] >= df["prior_high_60"])
        | prev_high_ph60_intraday
        | prev2_high_ph60_intraday
    ).fillna(False)

    # === C05: 漲停鎖住 flag ===
    # Course source: 明日 K 線 INVENTORY.md §C05 (第 20、28 篇)
    #
    # 漲停鎖住 = 收盤在漲停價 + 全天最高 == 收盤（沒有上影線）+ 全天最低 ≥ 前日收盤
    #
    # Taiwan market: 漲停 = prev_close * 1.10（無條件截到 tick 0.1）
    # Proxy: use close >= prev_close * 1.095 to avoid tick-rounding precision issues.
    # (INVENTORY definition uses exact == ; 0.095 threshold matches zhuli/entry usage.)
    #
    # Conditions (all AND):
    #   1. close >= prev_close * 1.095   — 收盤達漲停（含 tick 容差）
    #   2. high == close                 — 無上影線（鎖住，無賣壓突破）
    #   3. low >= prev_close             — 全天最低 ≥ 參考價（從不跌回昨收）
    _limit_up_threshold = 1.095  # proxy for +10% limit; see zhuli/entry/open_signal_filter.py
    df["is_limit_up_locked"] = (
        (df["close"] >= df["prev_close"] * _limit_up_threshold)
        & (df["high"] == df["close"])
        & (df["low"] >= df["prev_close"])
    ).fillna(False)

    # === C07: 異常放量 flag ===
    # Course source: 明日 K 線 INVENTORY.md §C07 (第 40 篇)
    #
    # 「明顯放量」= 本來無量，突然出現的大量（老師定性描述，無數字）
    #
    # [STUB-NEED-USER S1]:
    #   K (vol_ma_60 multiplier) = 2.0, J (vol_max_60 multiplier) = 1.5（退化預設值）
    #   上述數字待 user 拍板；回測時可傳入不同 K/J 至 _common.is_anomalous_volume。
    #   實作已抽到 patterns/_common.py — 調整 K/J 只需改該 helper 的參數。
    df["is_anomalous_volume"] = _is_anomalous_volume(df)

    # === at_pressure_retest: 壓力區回測（套牢/波動/獲利了結三類賣壓共通前提） ===
    # Course source: 明日 K 線 §08「壓力的分類」B5DB7A687DA4FA572833411DE9CD88D8
    #   「碰到了賣壓之後，接下來股價會怎樣走呢？」
    #   壓力 = 接近過去高點但尚未突破；課程明示「K 線上只有壓力沒有支撐」
    #
    # 條件：close 接近 prev_high_60（在門檻內回測）且尚未突破
    #   close >= prev_high_60 * (1 - AT_PRESSURE_RETEST_PCT)
    #   close <  prev_high_60
    #
    # [STUB-NEED-USER]: AT_PRESSURE_RETEST_PCT 在 course_proxy_constants.py，老師未明示。
    from .course_proxy_constants import AT_PRESSURE_RETEST_PCT
    df["at_pressure_retest"] = (
        (df["close"] < df["prior_high_60"])
        & (df["close"] >= df["prior_high_60"] * (1 - AT_PRESSURE_RETEST_PCT))
    ).fillna(False)

    # === 扣抵值 (kou values) 預判明日 MA 方向 ===
    # Course sources: 入門 + 行進ing 均明示，N 天前 close 是「明日扣抵」
    # 預判邏輯（假設明日 close ≈ 今日 close）:
    #   明日 MA_N > 今日 MA_N  iff  今日 close > N 天前的 close（扣抵值）
    # 故 ma_will_rise = today.close > shift(N).close
    df["ma5_kou"] = g["close"].shift(5)
    df["ma10_kou"] = g["close"].shift(10)
    df["ma20_kou"] = g["close"].shift(20)
    df["ma60_kou"] = g["close"].shift(60)
    # Use plain bool comparison; kou NaN propagates → False. Consumers can
    # check ma{N}_kou notna() to distinguish "no data" from "will fall".
    df["ma5_will_rise"] = (df["close"] > df["ma5_kou"]).fillna(False).astype(bool)
    df["ma10_will_rise"] = (df["close"] > df["ma10_kou"]).fillna(False).astype(bool)
    df["ma20_will_rise"] = (df["close"] > df["ma20_kou"]).fillna(False).astype(bool)
    df["ma60_will_rise"] = (df["close"] > df["ma60_kou"]).fillna(False).astype(bool)

    # =====================================================================
    # Task 3.E additions — 明日 K 線 INVENTORY C12
    # Added at the END; no existing column is modified.
    # =====================================================================

    # === C12: transition_inner_to_gap — 內困翻黑演進為向下跳空反轉 ===
    # Course source: 明日 K 線 INVENTORY.md §C12 (第 13 篇)
    #
    # 「內困型態（孕線）翻黑後，若隔日向下跳空 → trigger 既有 gap_reversal
    #   並標註是『內困演進』」 — 明日 K 線對 trapped.py + gap_reversal.py 的串接
    #
    # Definition:
    #   D-2: 創新高紅 K（close > prior_high_60 AND is_red）
    #   D-1: 孕線（high <= D-2 high AND low >= D-2 low）
    #   D-0: 向下跳空（open < prev_low）— 無論是否回補，已視為 gap_reversal 演進
    #
    # 日 K 退化版：
    #   D-0 open < prev_low 已是真實跳空（K-line gap），與 gap_reversal.py 一致。
    #   「是否回補」不在此層判斷（留給 exit/gap_attack_filled.py）。
    #
    # Note: INVENTORY §C12 明示「標註是內困演進」，本欄位即提供此 label，
    # 讓 playbook 或 advisor 知道這是 trapped → gap_reversal 的串接模式。
    g3 = df.groupby("ticker")
    open_d2 = g3["open"].shift(2)
    close_d2 = g3["close"].shift(2)
    high_d2 = g3["high"].shift(2)
    low_d2 = g3["low"].shift(2)
    prior_high_60_d2 = g3["prior_high_60"].shift(2)

    high_d1 = g3["high"].shift(1)
    low_d1 = g3["low"].shift(1)
    d1_harami_in_d2 = (high_d1 <= high_d2) & (low_d1 >= low_d2)
    d2_red_new_high = (close_d2 > open_d2) & (close_d2 > prior_high_60_d2)

    # D-0 gap down open
    d0_gap_down_open = df["open"] < df["prev_low"]

    df["transition_inner_to_gap"] = (
        d2_red_new_high & d1_harami_in_d2 & d0_gap_down_open
    ).fillna(False)

    # =====================================================================
    # Lights-fix additions (2026-06-04) — toplevel features for YAML lights
    # to express course-faithful conditions. No existing column modified.
    # Course sources noted per feature.
    # =====================================================================

    # === Short-window prior highs/lows (5/10 day windows) ===
    # Used by §15 高檔推升, §02 中樞窄幅, §10 上影線, §12 漲停隔日, §16 上升三法.
    df["prior_high_5"] = g["high"].transform(lambda s: s.shift(1).rolling(5, min_periods=5).max())
    df["prior_low_5"] = g["low"].transform(lambda s: s.shift(1).rolling(5, min_periods=5).min())
    df["prior_high_10"] = g["high"].transform(lambda s: s.shift(1).rolling(10, min_periods=10).max())

    # === body_pct / range_pct as toplevel scalars (for §11 高檔長黑 body 門檻) ===
    # Alias existing body_pct/range_pct so YAML can reference them as toplevel.
    df["body_pct_today"] = df["body_pct"]
    df["range_pct_today"] = df["range_pct"]

    # === is_limit_up_today — toplevel bool alias for is_limit_up_locked ===
    # Course source: 明日 K 線 §12 漲停板出現後再繼續上漲的機率
    # Stored as int (0/1) so vectorized float cast works; consumed via bool field check.
    df["is_limit_up_today"] = df["is_limit_up_locked"].fillna(False).astype(int)

    # === low_price_flag — close < LOW_PRICE_THRESHOLD ===
    # Course source: 明日 K 線 §09 低價股的處理節奏 (5710C4E8...)
    # 「八張低價股，跟買一張百元的中價股，價格的風險一樣」
    # [STUB-NEED-USER L1]: LOW_PRICE_THRESHOLD = 30.0
    from .course_proxy_constants import LOW_PRICE_THRESHOLD
    df["low_price_flag"] = (df["close"] < LOW_PRICE_THRESHOLD).fillna(False).astype(int)

    # === is_breakdown_pattern_flag — toplevel int alias for is_in_breakdown_pattern ===
    # Course source: 明日 K 線 §17 頭部成型 (跌破頸線). Proxy: ≥2 new-low events + MA60 下彎.
    df["is_breakdown_pattern_flag"] = df["is_in_breakdown_pattern"].fillna(False).astype(int)

    # === is_anomalous_volume_flag — toplevel int alias for is_anomalous_volume ===
    # Course source: §40 明顯放量創新高 + 賣壓化解需有量.
    df["is_anomalous_volume_flag"] = df["is_anomalous_volume"].fillna(False).astype(int)

    # === recent_range_pct_5 — 過去 5 日（含今日）high-low 區間 / close 比 ===
    # Course source: 明日 K 線 §02 中樞型態 — 「橫向盤整」窄幅判斷
    # [STUB-NEED-USER L3]: ZHONGSHU_RANGE_MAX_PCT = 0.10
    high_5 = g["high"].transform(lambda s: s.rolling(5, min_periods=5).max())
    low_5 = g["low"].transform(lambda s: s.rolling(5, min_periods=5).min())
    df["recent_range_pct_5"] = ((high_5 - low_5) / df["close"].replace(0, np.nan)).fillna(1.0)

    return df
