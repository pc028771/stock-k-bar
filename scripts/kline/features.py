"""Derived features for kline conditions.

Course source: features support multiple course concepts; no single article.

Input: bars DataFrame from bars.load_bars(), sorted by (ticker, trade_date).
Output: same DataFrame with derived columns added (spec §3.2).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

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

    # Rolling prior highs/lows (exclude today via shift)
    df["prior_high_60"] = (
        g["high"].shift(1).rolling(60, min_periods=60).max().reset_index(level=0, drop=True)
    )
    df["prior_high_20"] = (
        g["high"].shift(1).rolling(20, min_periods=20).max().reset_index(level=0, drop=True)
    )
    df["prior_low_60"] = (
        g["low"].shift(1).rolling(60, min_periods=60).min().reset_index(level=0, drop=True)
    )
    df["prior_low_20"] = (
        g["low"].shift(1).rolling(20, min_periods=20).min().reset_index(level=0, drop=True)
    )

    # Avg volume (excluding today)
    df["avg_volume_20"] = (
        g["volume"].shift(1).rolling(20, min_periods=20).mean().reset_index(level=0, drop=True)
    )
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
        above_ma60.groupby(df["ticker"])
        .shift(1)
        .fillna(0)
        .groupby(df["ticker"])
        .rolling(20, min_periods=1)
        .sum()
        .reset_index(level=0, drop=True)
        .astype(int)
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
            .shift(lag)
            .rolling(5, min_periods=5)
            .max()
            .reset_index(level=0, drop=True)
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
        g["high"].shift(31).rolling(30, min_periods=30).max()
        .reset_index(level=0, drop=True)
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

    return df
