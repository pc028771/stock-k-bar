"""Derived features for kline conditions.

Course source: features support multiple course concepts; no single article.

Input: bars DataFrame from bars.load_bars(), sorted by (ticker, trade_date).
Output: same DataFrame with derived columns added (spec §3.2).
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from .patterns._common import is_anomalous_volume as _is_anomalous_volume
from .course_proxy_constants import (
    ATTACK_COST_FIRST_BREAKOUT_LOOKBACK_DAYS,
    ATTACK_HIGHER_HIGH_MIN_5DAY,
    ATTACK_HIGHER_LOW_MIN_5DAY,
    ATTACK_WINDOW_DAYS,
    CONSOLIDATION_LONG_DAYS,
    CONSOLIDATION_LONG_RANGE_MAX_PCT,
    DEFENSIVE_LOW_LOOKBACK_DAYS,
    DOJI_MAX_BODY_PCT,
    DOJI_MIN_RANGE_PCT,
    EARLY_DEPLOY_RESISTANCE_LOOKBACK_DAYS,
    EARLY_DEPLOY_VOL_MULTIPLE,
    FIRST_BREAKOUT_LOOKBACK,
    INTEGRATION_DAYS as _INTEGRATION_DAYS,
    MERGED_DOJI_BODY_RATIO as _MERGED_DOJI_BODY_RATIO,
    MERGED_DOJI_CARRY_DAYS,
    MERGED_DOJI_SHADOW_MIN_RATIO as _MERGED_DOJI_SHADOW_MIN_RATIO,
    RISING_LOWS_MIN_FRAC,
    SAME_LEVEL_LOOKBACK_DAYS,
    SAME_LEVEL_PRICE_TOLERANCE,
    SAME_LEVEL_RED_MIN_COUNT,
    SELF_RESCUE_VOL_RATIO_MAX,
    SELF_RESCUE_PREV_BREAKOUT_LOOKBACK,
    STABLE_UPPER_MAX_SPREAD as _STABLE_UPPER_MAX_SPREAD,
)

# ── Numba JIT helpers ─────────────────────────────────────────────────────────
# Three hot loops (overhead_supply_layer / unfilled_gap_down / body_pct_pct_rank)
# were the bottlenecks in add_features.  They are extracted as @jit(nopython=True)
# functions so Numba can compile them to native code on first call (cached on disk).
# Falls back to pure-numpy if numba is not installed.

try:
    from numba import jit as _jit  # type: ignore
    _NUMBA_AVAILABLE = True
except ImportError:  # pragma: no cover
    _NUMBA_AVAILABLE = False
    def _jit(*args, **kwargs):  # type: ignore
        """No-op decorator when numba is not installed."""
        def _wrap(fn):
            return fn
        return _wrap


@_jit(nopython=True, cache=True)
def _overhead_supply_njit(
    high_vals: np.ndarray,
    close_today: np.ndarray,
    past_max5: np.ndarray,
    cumcount: np.ndarray,
    lookback: int,
) -> np.ndarray:
    """Count swing-high peaks above today's close in trailing *lookback* days.

    A bar at lag *k* is a 5-bar local peak if ``high[k] == rolling_max5[k]``.
    Only bars within the same ticker are considered (``cumcount >= lag``).
    """
    n = len(close_today)
    counts = np.zeros(n)
    for lag in range(1, lookback + 1):
        for i in range(lag, n):
            sh = high_vals[i - lag]
            sm = past_max5[i - lag]
            if cumcount[i] >= lag and not np.isnan(sm) and sh == sm and sh > close_today[i]:
                counts[i] += 1.0
    return counts


@_jit(nopython=True, cache=True)
def _unfilled_gap_njit(
    high_vals: np.ndarray,
    prev_low_vals: np.ndarray,
    close_today: np.ndarray,
    cumcount: np.ndarray,
    lookback: int,
) -> np.ndarray:
    """Count unfilled gap-down zones above today's close in trailing *lookback* days."""
    n = len(close_today)
    counts = np.zeros(n)
    for lag in range(1, lookback + 1):
        for i in range(lag, n):
            if cumcount[i] < lag:
                continue
            sh = high_vals[i - lag]
            spl = prev_low_vals[i - lag]
            if np.isnan(spl):
                continue
            if sh < spl and spl > close_today[i]:
                counts[i] += 1.0
    return counts


@_jit(nopython=True, cache=True)
def _body_pct_rank_njit(
    body_pct_vals: np.ndarray,
    cumcount: np.ndarray,
    priors: int,
) -> np.ndarray:
    """Percentile rank of today's body_pct vs the prior *priors* bars (per-ticker)."""
    n = len(body_pct_vals)
    sum_lt = np.zeros(n)
    count_valid = np.zeros(n, dtype=np.int64)
    for lag in range(1, priors + 1):
        for i in range(lag, n):
            if cumcount[i] < lag:
                continue
            v = body_pct_vals[i - lag]
            if np.isnan(v):
                continue
            count_valid[i] += 1
            if v < body_pct_vals[i]:
                sum_lt[i] += 1.0
    result = np.full(n, np.nan)
    for i in range(n):
        today_ok = not np.isnan(body_pct_vals[i])
        in_window = count_valid[i] + (1 if today_ok else 0)
        if in_window >= 10 and today_ok and count_valid[i] > 0:
            result[i] = sum_lt[i] / count_valid[i]
    return result


# ── Feature group declarations ────────────────────────────────────────────────
# Detectors that only need a subset of features declare REQUIRED_FEATURES and
# call ``add_features(df, groups=REQUIRED_FEATURES)``.  groups=None (default)
# computes ALL groups — fully backward-compatible.

FEATURE_GROUPS: dict[str, list[str]] = {
    # Raw previous-bar lags and short rolling windows (always fast).
    "basic": [
        "prev_close", "prev_open", "prev_high", "prev_low",
        "prior_high_60", "prev_high_60", "prior_high_20",
        "prior_low_60", "prior_low_20",
    ],
    # Moving-average derived columns (mostly from DB; slope computed here).
    "ma": [
        "ma60_slope_5d", "ma60_rolling_off_close",
        "ma5_kou", "ma10_kou", "ma20_kou", "ma60_kou",
        "ma5_will_rise", "ma10_will_rise", "ma20_will_rise", "ma60_will_rise",
    ],
    # Volume ratio (fast).
    "volume": ["avg_volume_20", "volume_ratio"],
    # Single-bar shape metrics (fast, no rolling).
    "bar_shape": [
        "range_pct", "body_abs", "body_pct", "close_pos",
        "upper_shadow", "lower_shadow",
        "upper_shadow_ratio", "lower_shadow_ratio",
    ],
    # Historical rolling windows up to 60 days (moderate cost).
    "historical": [
        "prior_high_5", "prior_low_5", "prior_high_10",
        "pre_breakout_trend_days",
        "is_in_breakdown_pattern", "new_low_count_60d",
        "higher_low_count_60d", "upper_band_spread_60d",
        "is_pattern_breakout",
        "attack_intensity", "prev_bar_had_attack_meaning",
        "is_first_breakout_above_level", "is_attack_bar",
    ],
    # Slow 240-lag loops (overhead supply, gap count, pct-rank).
    "advanced": [
        "overhead_supply_layer",
        "unfilled_gap_down_count_240d",
        "body_pct_pct_rank_20d",
    ],
    # Pattern-layer derived columns and lights flags.
    "pattern": [
        "is_red", "is_black", "is_doji",
        "is_sunset_bar", "is_harami", "midpoint",
        "is_gap_up_today", "is_gap_down_today",
        "is_limit_up_locked", "is_anomalous_volume",
        "is_just_broke_high", "is_just_broke_high_intraday",
        "attack_intent_zone_high", "attack_intent_zone_low", "intent_zone_break",
        "at_pressure_retest",
        "transition_inner_to_gap",
        "merged_high", "merged_low", "attack_cost", "defensive_low",
        "is_self_rescue_breakout",
        "same_level_red_count_5d", "same_level_red_count_5d_int",
        "just_high_doji",
    ],
}

# Convenience: set of all group names
_ALL_GROUPS: frozenset[str] = frozenset(FEATURE_GROUPS)

# Detector-facing shorthand
REQUIRED_FEATURES_SUFFOCATION = ["basic", "ma", "volume", "bar_shape"]
REQUIRED_FEATURES_SMALL_STRUCTURE = ["basic", "ma", "volume", "bar_shape"]
REQUIRED_FEATURES_W_BOTTOM = ["basic", "ma", "volume", "bar_shape"]
REQUIRED_FEATURES_UNIFORM_MA = ["basic", "ma", "volume", "bar_shape"]


def add_features(df: pd.DataFrame, groups: list[str] | None = None) -> pd.DataFrame:
    """Add derived features. Pure function — returns new DataFrame.

    Parameters
    ----------
    df:
        Bars DataFrame from ``load_bars()``.
    groups:
        List of group names to compute (see ``FEATURE_GROUPS``).
        ``None`` (default) computes **all** groups — fully backward-compatible.
        Example: ``groups=['basic', 'ma', 'volume', 'bar_shape']`` for
        lightweight detector runs that skip the heavy 240-lag loops.
    """
    _compute_all = groups is None
    if groups is None:
        _active = _ALL_GROUPS
    else:
        _active = frozenset(groups)

    def _want(*grp_names: str) -> bool:
        """Return True if any of the named groups should be computed."""
        return _compute_all or any(g in _active for g in grp_names)

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

    # Precompute shared arrays used by multiple hot loops below.
    # Always computed because basic/bar_shape/historical all depend on n / cumcount.
    n = len(df)
    cumcount = g.cumcount().to_numpy()
    close_today = df["close"].to_numpy(dtype=np.float64)
    high_vals = df["high"].to_numpy(dtype=np.float64)

    # Scoring input: consecutive days closing above MA60 prior to today, capped at 20.
    if _want("historical", "advanced"):
        above_ma60 = (df["close"] > df["ma60"]).fillna(False).astype(int)
        df["pre_breakout_trend_days"] = (
            above_ma60.groupby(df["ticker"]).transform(
                lambda s: s.shift(1).fillna(0).rolling(20, min_periods=1).sum()
            ).astype(int)
        )

    # === overhead_supply_layer (Numba JIT, 240-lag loop) ===
    # Scoring input: count of swing-high peaks above current close in trailing 240 days.
    # A peak at bar k is defined as high[k] == max(high[k-4:k+1]) (5-bar local max).
    #
    # Hot-loop perf: Numba @jit(nopython=True, cache=True) compiles to native code;
    # first call triggers compilation (~3s), subsequent calls use disk cache.
    # Falls back to pure-numpy if numba is not installed.
    if _want("advanced"):
        LOOKBACK = 240
        # Per-ticker 5-bar rolling max (computed once)
        past_max5_per_row = (
            g["high"].transform(lambda s: s.rolling(5, min_periods=5).max())
        ).to_numpy(dtype=np.float64)
        has_history = cumcount >= 20

        if _NUMBA_AVAILABLE:
            peak_count = _overhead_supply_njit(
                high_vals, close_today, past_max5_per_row, cumcount, LOOKBACK
            )
        else:
            peak_count = np.zeros(n, dtype=np.float64)
            for lag in range(1, LOOKBACK + 1):
                sh = np.full(n, np.nan, dtype=np.float64)
                sh[lag:] = high_vals[:-lag]
                sm = np.full(n, np.nan, dtype=np.float64)
                sm[lag:] = past_max5_per_row[:-lag]
                same_ticker = cumcount >= lag
                is_peak = same_ticker & (sh == sm) & ~np.isnan(sm)
                peak_count += (is_peak & (sh > close_today)).astype(np.float64)

        df["overhead_supply_layer"] = np.where(has_history, peak_count, np.nan)

    # === unfilled_gap_down_count_240d (Numba JIT, 240-lag loop) ===
    # Course source: 型態學 10-缺口壓力型態.
    # 向下跳空缺口未回補 = 型態壓力 (separate from swing-high overhead).
    #
    # Course quote: 「向下跳空的缺口表示這個價位區間沒有任何人成交……
    #   這個價位卻沒有任何買單願意承接股價，於是就形成了缺口壓力的明顯壓力狀態。」
    # Quote: 「雖然不是實質套牢，但卻是一種型態上的壓力」
    # Quote: 「離現在最近的一個缺口壓力還沒有越過之前，都不宜對股價樂觀」
    #
    # Detection: gap-down bar (today.high < prev_low) where gap_top (prev_low) is
    # still above today's close (unfilled overhead gap).
    if _want("advanced"):
        GAP_RESISTANCE_LOOKBACK = 240
        prev_low_vals = df["prev_low"].to_numpy(dtype=np.float64, na_value=np.nan)

        if _NUMBA_AVAILABLE:
            unfilled_gap_count = _unfilled_gap_njit(
                high_vals, prev_low_vals, close_today, cumcount, GAP_RESISTANCE_LOOKBACK
            )
        else:
            unfilled_gap_count = np.zeros(n, dtype=np.float64)
            for lag in range(1, GAP_RESISTANCE_LOOKBACK + 1):
                sh = np.full(n, np.nan, dtype=np.float64)
                sh[lag:] = high_vals[:-lag]
                spl = np.full(n, np.nan, dtype=np.float64)
                spl[lag:] = prev_low_vals[:-lag]
                same_ticker = cumcount >= lag
                was_gap_down = same_ticker & (sh < spl)
                gap_top = spl
                above_today = gap_top > close_today
                unfilled = was_gap_down & above_today & ~np.isnan(gap_top)
                unfilled_gap_count += unfilled.astype(np.float64)

        df["unfilled_gap_down_count_240d"] = np.where(has_history, unfilled_gap_count, np.nan)

    if _want("pattern", "historical"):
        # K-line color
        df["is_red"] = df["close"] > df["open"]
        df["is_black"] = df["close"] < df["open"]
        # Proxy: course says doji = 「近乎沒有實體」 (qualitative). We operationalize
        # via body_pct ≤ 0.6% (近乎沒有實體) AND range_pct ≥ 1.5% (meaningful range).
        # See course_proxy_constants.I7 for full rationale; no course-stated number.
        df["is_doji"] = (df["body_pct"] <= DOJI_MAX_BODY_PCT) & (df["range_pct"] >= DOJI_MIN_RANGE_PCT)

    if _want("historical", "pattern"):
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

    if _want("historical", "pattern"):
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
            (df.get("overhead_supply_layer", pd.Series(0.0, index=df.index)).fillna(0) <= 0)
            & (df.get("unfilled_gap_down_count_240d", pd.Series(0.0, index=df.index)).fillna(0) <= 0)
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


    if _want("pattern"):
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


    if _want("advanced", "pattern"):
        # body_pct percentile rank over trailing 20 days (excluding today).
        # Used by is_power_bar Option B (currently OFF — see patterns/_common.py).
        # We rank today's body_pct against the prior 20-bar window.
        #
        # Hot-loop perf: rolling().apply(..., raw=False) was 64% of features.py wall
        # time (profile showed 10.6s / 16.6s on a 50-ticker subset). Vectorized via
        # the same lag-shift pattern as overhead_supply_layer — bit-identical output.
        # Window of 21 = today + 20 priors; for each prior lag, count how many priors
        # are strictly less than today (matching `_pct_rank`'s semantics).
        body_pct_vals = df["body_pct"].to_numpy(dtype=np.float64, na_value=np.nan)
        PCTRANK_PRIORS = 20
        if _NUMBA_AVAILABLE:
            pctrank = _body_pct_rank_njit(body_pct_vals, cumcount, PCTRANK_PRIORS)
        else:
            sum_lt = np.zeros(n, dtype=np.float64)
            count_valid = np.zeros(n, dtype=np.int64)
            for lag in range(1, PCTRANK_PRIORS + 1):
                lagged = np.full(n, np.nan, dtype=np.float64)
                lagged[lag:] = body_pct_vals[:-lag]
                same_ticker = cumcount >= lag
                not_nan_lag = same_ticker & ~np.isnan(lagged)
                sum_lt += (not_nan_lag & (lagged < body_pct_vals)).astype(np.float64)
                count_valid += not_nan_lag.astype(np.int64)
            today_not_nan = ~np.isnan(body_pct_vals)
            in_window_count = count_valid + today_not_nan.astype(np.int64)
            gate = (in_window_count >= 10) & today_not_nan & (count_valid > 0)
            pctrank = np.full(n, np.nan, dtype=np.float64)
            pctrank[gate] = sum_lt[gate] / count_valid[gate]
        df["body_pct_pct_rank_20d"] = pctrank

    if _want("pattern"):
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
        # Hot-loop perf: rolling(20).apply(last-non-NaN) is just ffill(limit=19) —
        # carries the most recent non-NaN forward up to 19 rows. Same per-ticker scope
        # via groupby; semantically identical and ~100x faster.
        df["attack_intent_zone_high"] = (
            breakout_ph60.groupby(df["ticker"], sort=False)
            .transform(lambda s: s.ffill(limit=19))
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
        #   「股價第二次又來到 170 元附近⋯⋯隔天要確認是攻擊，必須就是一開盤開在 176.5 元以上
        #    的跳空攻擊⋯⋯」
        #   壓力 = 盤中高點觸及前高（碰到）但收盤未突破（未越過）
        #   課程明示「碰到」vs「越過」= 二元判斷，無 % 距離概念。
        #
        # 課程依據：老師用具體價位（170 元/176.5 元）描述「碰到」vs「越過」，
        #   不是「距離 X% 以內」的區間概念。
        #
        # 條件（課程二元觸及）：
        #   high >= prior_high_60   → 盤中觸及前高（碰到）
        #   close < prior_high_60   → 收盤未突破（沒越過）
        #
        # 取代舊版 AT_PRESSURE_RETEST_PCT % 範圍方式（已廢棄）。
        # 預期 fire rate: ~5-15%（vs 舊版 ~55%；舊版含大量「接近但未觸」的 FP）
        df["at_pressure_retest"] = (
            (df["high"] >= df["prior_high_60"])
            & (df["close"] < df["prior_high_60"])
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

        # === low_price_flag — close < LOW_PRICE_THRESHOLD [EXTRAS] ===
        # Course source: 明日 K 線 §09 低價股的處理節奏 (5710C4E8...)
        # 「八張低價股，跟買一張百元的中價股，價格的風險一樣」
        # [EXTRAS] LOW_PRICE_THRESHOLD = 30.0 是業界 proxy（課程未明示門檻數字）。
        # 常數已從 course_proxy_constants.py 移至 extras/low_price.py。
        # lowprice_first_pull_exit.yaml 標記 [EXTRAS]，提醒此 light 含課程外條件。
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

        # =====================================================================
        # Advanced field wiring (2026-06-05) — 4 toplevel context fields
        # Required so lt_attack_cost_breakdown / lt_defensive_low_break /
        # lt_merged_doji_high_break / lt_merged_doji_low_break lights fire.
        # =====================================================================

        # === merged_high / merged_low — 合併十字線高低點 (§24) ===
        # Course source: 明日 K 線 第 24 篇《合併十字線》
        # 「兩根合併就是長十字線，位置也沒有錯誤，表示股價已經具備了攻擊意圖」
        # 命中日 = merged_doji pattern 觸發日；merged_high/merged_low = 兩根 K 合併後的高低點。
        # Forward-fill MERGED_DOJI_CARRY_DAYS = 1 日（課程明示「隔日就要表態、無法後天大後天」）。
        #
        # 課程依據（§24）：「明天的重點就得要攻擊，且這是一定要發生的，無法變成後天、大後天」
        # 課程依據（§26）：「明日就得開始攻擊，或者跌破合併十字線的低點作為確認不攻擊。」
        # 因此 forward-fill 只保留「隔日一天」——課程明示效力窗口。
        #
        # Inline computation reusing already-computed features.py columns for performance.
        # Logic mirrors patterns/merged_doji.detect() but avoids redundant groupby.shift().
        # Constants come from course_proxy_constants (same as merged_doji.py imports).
        _MD_BODY_RATIO = _MERGED_DOJI_BODY_RATIO
        _MD_SHADOW_RATIO = _MERGED_DOJI_SHADOW_MIN_RATIO

        # Condition 1: 剛創新高位置（use is_just_broke_high_intraday already computed above）
        _md_just_broke = df["is_just_broke_high_intraday"].fillna(False)

        # Condition 2: 前根上影線為主（prev_upper_shadow > prev_lower_shadow）
        # prev_open/close computed at top of add_features; prev_high/prev_low also.
        _prev_body_top = df[["prev_open", "prev_close"]].max(axis=1)
        _prev_body_bot = df[["prev_open", "prev_close"]].min(axis=1)
        _prev_upper_sh = df["prev_high"] - _prev_body_top
        _prev_lower_sh = _prev_body_bot - df["prev_low"]
        _prev_upper_dom = _prev_upper_sh > _prev_lower_sh

        # 今根下影線為主（lower_shadow > upper_shadow，use already-computed columns）
        _today_lower_dom = df["lower_shadow"] > df["upper_shadow"]

        # Condition 3: 合併後為十字線
        _merged_h = df[["prev_high", "high"]].max(axis=1)
        _merged_l = df[["prev_low", "low"]].min(axis=1)
        _merged_open = df["prev_open"]
        _merged_close = df["close"]
        _merged_range = (_merged_h - _merged_l).replace(0, np.nan)
        _body = (_merged_open - _merged_close).abs()
        _body_ratio = _body / _merged_range
        _upper_body = df[["prev_open", "close"]].max(axis=1)
        _lower_body = df[["prev_open", "close"]].min(axis=1)
        _upper_sh_m = _merged_h - _upper_body
        _lower_sh_m = _lower_body - _merged_l
        _is_merged_doji = (
            (_body_ratio <= _MD_BODY_RATIO)
            & ((_upper_sh_m / _merged_range) >= _MD_SHADOW_RATIO)
            & ((_lower_sh_m / _merged_range) >= _MD_SHADOW_RATIO)
        ).fillna(False)

        _md_signal = (_md_just_broke & _prev_upper_dom & _today_lower_dom & _is_merged_doji).fillna(False)

        _merged_high_raw = _merged_h.where(_md_signal, other=np.nan)
        _merged_low_raw = _merged_l.where(_md_signal, other=np.nan)

        df["merged_high"] = (
            _merged_high_raw
            .groupby(df["ticker"])
            .transform(lambda s: s.ffill(limit=MERGED_DOJI_CARRY_DAYS))
        )
        df["merged_low"] = (
            _merged_low_raw
            .groupby(df["ticker"])
            .transform(lambda s: s.ffill(limit=MERGED_DOJI_CARRY_DAYS))
        )

        # === attack_cost — 攻擊成本顯現日的漲停價 (§20) ===
        # Course source: 明日 K 線 第 20 篇《攻擊成本顯現日》
        # 「突破前高的當日，股價鎖住漲停板，且最大量就是在這個漲停板的價位」
        # 攻擊成本 = 漲停鎖住當日的 close（漲停價 proxy）。
        # Forward-fill ATTACK_COST_FIRST_BREAKOUT_LOOKBACK_DAYS 日（= 20，同 state-machine 窗口）。
        #
        # Implementation (inline, reusing already-computed df columns):
        #   raw_signal = is_limit_up_locked & close > prior_high_60
        #   (volume_condition: ATTACK_COST_VOL_RATIO = 1.0 = no-op in day-K fallback)
        #   State-machine suppression: forward-fill with limit achieves equivalent result —
        #   once attack_cost is seeded, it persists for N days, preventing re-seeding
        #   (a new signal only overwrites if the old value is already NaN'd out).
        #
        # Note: this inline skips the per-row intraday minute-bar check (分K覆寫) which
        # attack_cost_displayed.detect() does. Full intraday check available via the
        # pattern detector directly; this is the features.py vectorized approximation.
        #
        # State-machine suppression via groupby rolling max (vectorized, no lambda):
        _ac_n = ATTACK_COST_FIRST_BREAKOUT_LOOKBACK_DAYS
        _ac_raw = (df["is_limit_up_locked"].fillna(False)
                   & (df["close"] > df["prior_high_60"]).fillna(False)).astype(np.int8)

        _prior_ac = (
            _ac_raw
            .groupby(df["ticker"])
            .shift(1)
            .fillna(0)
        )
        _prior_ac_rolling = (
            _prior_ac
            .groupby(df["ticker"])
            .rolling(_ac_n, min_periods=1)
            .max()
            .reset_index(level=0, drop=True)
        )
        _acd_sig = (_ac_raw.astype(bool)) & (_prior_ac_rolling < 1)
        _ac_seed = df["close"].where(_acd_sig, other=pd.NA)

        df["attack_cost"] = (
            _ac_seed
            .groupby(df["ticker"])
            .transform(lambda s: s.ffill(limit=_ac_n))
        )

        # === defensive_low — 防守姿態低點 (§26) ===
        # Course source: 明日 K 線 第 26 篇《防守姿態》
        # 老師 9945 案例原話：「過去六天的低點」作為防守價位。
        # 課程未明示通則天數 — 以 9945 案例的「六天」為代理。
        #
        # 課程脈絡：「防守姿態」發生在股價剛創新高（is_just_broke_high）後，
        # 主力「防守」表示不讓股價跌回原本位置。
        # 非剛創新高位置不適用防守點邏輯（老師未說所有個股通用）。
        #
        # Implementation:
        #   Step 1: 計算過去 N 日的最低 K 棒 low 作為「防守支撐」seed。
        #   Step 2: 僅在 is_just_broke_high = True 的 bar 保留 seed（限制在攻擊位置）。
        #   Step 3: Forward-fill DEFENSIVE_LOW_LOOKBACK_DAYS 日（防守期間持續有效）。
        #
        # 「跌破防守價」= today.close < defensive_low（收盤跌破 K 棒支撐低點）。
        #
        # [STUB-NEED-USER]: DEFENSIVE_LOW_LOOKBACK_DAYS = 6（老師 9945 案例個案數字）。
        # 課程未明示是否適用所有個股、也未明示通則天數。
        # [STUB-NEED-USER]: 限制在 is_just_broke_high = True 是我們加的「攻擊位置」前提，
        # 課程未明示觸發條件（§26 討論的都是剛創新高的情境）。
        _def_low_6d = g["low"].transform(
            lambda s: s.shift(1).rolling(
                DEFENSIVE_LOW_LOOKBACK_DAYS,
                min_periods=DEFENSIVE_LOW_LOOKBACK_DAYS,
            ).min()
        )
        # Only populate when stock is at "just broke high" position (§26 context)
        _def_low_seed = _def_low_6d.where(df["is_just_broke_high"].fillna(False), other=np.nan)
        # Forward-fill to keep defensive_low active during the defensive window
        df["defensive_low"] = (
            _def_low_seed
            .groupby(df["ticker"])
            .transform(lambda s: s.ffill(limit=DEFENSIVE_LOW_LOOKBACK_DAYS))
        )

        # =====================================================================
        # INTRO concepts impl (2026-06-05)
        # Course sources: 入門 §34 自救型突破 / §07 + §30 同價位賣壓 /
        #                 §49 + §10 創新高十字線攻擊 / 強者恆強
        # See docs/kline_course/notes/intro_concepts_impl_2026-06-05.md
        # =====================================================================

        # === INTRO-1a: is_self_rescue_breakout — 自救型突破 (入門 §34) ===
        # Course quote:
        #   「股價又突破了前高。此時成交量卻出現了比前高萎縮的跡象」
        #   「如果這次突破比上次量增，那就不列為自救型突破的範圍了」
        # Definition:
        #   1. 今日為突破 (close > prior_high_60, is_first_breakout_above_level=True)
        #   2. 過去 N 日內存在「上次突破」(close > prior_high_60 過)
        #   3. 今日成交量 < 上次突破當日成交量 × SELF_RESCUE_VOL_RATIO_MAX (量縮)
        # NOTE: 「多頭背景」依入門 §34 一律要求季線多頭 → close > ma60 already in feature D.
        #       利空背景 (taiex 下跌) 由 context layer 提供（taiex_down_today / is_after_negative_news）
        #       — light/playbook 在 trigger_condition 串接此 context。
        breakout_today = (df["close"] > df["prior_high_60"]).fillna(False)

        # Find max volume among prior breakout bars within the lookback window
        _vol_on_breakout = df["volume"].where(breakout_today, other=np.nan)
        # Use shift(1) then rolling max to find max breakout-day volume in window (exclude today).
        _prev_max_breakout_vol = (
            _vol_on_breakout
            .groupby(df["ticker"])
            .shift(1)
            .groupby(df["ticker"])
            .transform(
                lambda s: s.rolling(SELF_RESCUE_PREV_BREAKOUT_LOOKBACK, min_periods=1).max()
            )
        )
        # vol shrinkage condition (only meaningful where prev breakout vol exists)
        _vol_shrinkage = (
            df["volume"] < _prev_max_breakout_vol * SELF_RESCUE_VOL_RATIO_MAX
        ).fillna(False)
        # multi-head background (close > ma60)
        _multi_head_bg = (df["close"] > df["ma60"]).fillna(False)

        df["is_self_rescue_breakout"] = (
            breakout_today
            & _vol_shrinkage
            & _multi_head_bg
            & _prev_max_breakout_vol.notna()
        ).fillna(False)

        # === INTRO-2: same_level_red_count_5d — 同價位反覆紅K (§07 §30) ===
        # Course quote (§07): 「同一個價位紅K的隔天就出現黑K，次數多了就顯是有實質賣壓存在」
        # Course quote (§30): 「到了某個價位就會多次出現紅K(上漲)接續著黑K(賣盤)的走勢」
        # Definition: count of prior bars in last N days where:
        #   - that bar was a red K
        #   - that bar's close was within tolerance of today's close (「同一個價位」)
        # 「實質賣壓」light 進一步要求 today.is_black + same_level_red_count_5d >= 2.
        today_close_arr = df["close"].to_numpy()
        same_level_count = np.zeros(len(df), dtype=float)
        for lag in range(1, SAME_LEVEL_LOOKBACK_DAYS + 1):
            prev_close_lag = g["close"].shift(lag).to_numpy(dtype=np.float64, na_value=np.nan)
            prev_is_red_lag = g["is_red"].shift(lag).fillna(False).to_numpy()
            # within tolerance band
            denom = np.where(today_close_arr == 0, np.nan, today_close_arr)
            diff_pct = np.abs(prev_close_lag - today_close_arr) / denom
            near_today = diff_pct <= SAME_LEVEL_PRICE_TOLERANCE
            same_level_count += (prev_is_red_lag & near_today).astype(float)

        df["same_level_red_count_5d"] = same_level_count.astype(int)

        # === INTRO-4: just_high_doji — 剛創新高 + 十字線 (§49 §10 攻擊型態) ===
        # Course quote (§49):
        #   「最簡易的攻擊K線當然是跳空、長紅，因為大家都知道這兩種的力量，反而忽略了上影線
        #    與十字線在剛創新高時代表的攻擊意義」
        # Course quote (§10):
        #   「股價創新高的時候，本來就應該視之為攻擊」
        # Definition: today is_doji AND today.high >= prior_high_60 (剛創新高位置)
        # 用既有 is_doji + just_high_upper_shadow 的 sister 概念。
        df["just_high_doji"] = (
            df["is_doji"].fillna(False)
            & (df["high"] >= df["prior_high_60"]).fillna(False)
        ).fillna(False)

        # Toplevel int aliases for YAML DSL (lights reference these)
        df["same_level_red_count_5d_int"] = df["same_level_red_count_5d"].fillna(0).astype(int)
        df["is_self_rescue_breakout_flag"] = df["is_self_rescue_breakout"].fillna(False).astype(int)
        df["just_high_doji_flag"] = df["just_high_doji"].fillna(False).astype(int)
        df["is_black_today"] = df["is_black"].fillna(False).astype(int)

        # =====================================================================
        # INTRO-tier-2 concepts impl (2026-06-06)
        # Course sources: 入門 §07 + §21 整理超過兩個半月 + 季線下彎 /
        #                 入門 「成本原理」提前部署 /
        #                 入門 §03 + §12 連續十字線區間
        # See docs/kline_course/notes/intro_tier2_impl_2026-06-06.md
        # =====================================================================

        # === INTRO-16a: ma60_falling — 季線下彎（明確 5 日斜率 < 0）===
        # Course quote (§21):「一旦季線下彎表示中期趨勢已經轉為空頭」
        df["ma60_falling"] = (df["ma60_slope_5d"].fillna(0) < 0).astype(bool)

        # === INTRO-16b: consolidation_over_2_5_months —
        #              整理區間超過兩個半月（≈ 50 交易日）
        # Course quote (§07):「整理區間超過兩個半月」
        # Definition (退化版日 K):
        #   過去 CONSOLIDATION_LONG_DAYS 日內 (high.max - low.min) / midpoint
        #   <= CONSOLIDATION_LONG_RANGE_MAX_PCT (= 20%)
        _hi_long = g["high"].transform(
            lambda s: s.shift(1).rolling(CONSOLIDATION_LONG_DAYS, min_periods=CONSOLIDATION_LONG_DAYS).max()
        )
        _lo_long = g["low"].transform(
            lambda s: s.shift(1).rolling(CONSOLIDATION_LONG_DAYS, min_periods=CONSOLIDATION_LONG_DAYS).min()
        )
        _mid_long = (_hi_long + _lo_long) / 2.0
        _range_pct_long = (_hi_long - _lo_long) / _mid_long.replace(0, np.nan)
        df["consolidation_over_2_5_months"] = (
            _range_pct_long <= CONSOLIDATION_LONG_RANGE_MAX_PCT
        ).fillna(False).astype(bool)

        # === INTRO-9: volume_exceeds_resistance_volume — 提前部署 ===
        # Course quote (course_principles 入門):
        #   「當前成交量已超過過往套牢區的量（價格還沒突破）」
        # Definition:
        #   1. 今日 volume > 過去 EARLY_DEPLOY_RESISTANCE_LOOKBACK_DAYS (60) 日
        #      內最高量 × EARLY_DEPLOY_VOL_MULTIPLE (1.0)
        #   2. 今日 close < prior_high_60（價未突破）
        # 提前部署 = 量先動、價未突破。
        _max_prior_vol = g["volume"].transform(
            lambda s: s.shift(1).rolling(
                EARLY_DEPLOY_RESISTANCE_LOOKBACK_DAYS,
                min_periods=EARLY_DEPLOY_RESISTANCE_LOOKBACK_DAYS,
            ).max()
        )
        _vol_exceeds = df["volume"] > (_max_prior_vol * EARLY_DEPLOY_VOL_MULTIPLE)
        _price_not_yet = (df["close"] < df["prior_high_60"]).fillna(False)
        df["volume_exceeds_resistance_volume"] = (
            _vol_exceeds & _price_not_yet & _max_prior_vol.notna()
        ).fillna(False).astype(bool)

        # === INTRO-6: consecutive_doji_count — 連續十字線天數 ===
        # Course quote (§03 + §12 + §09):
        #   「連續十字線的判斷要點就以這個連續十字區間的高低點作為短線方向判斷」
        # Definition: 過去 N 日含今日連續為 is_doji 的天數（streak length）
        is_doji_series = df["is_doji"].fillna(False).astype(int)
        # Per-ticker rolling streak: reset at non-doji bars
        def _streak(s: pd.Series) -> pd.Series:
            # vectorized streak count
            grp = (s != s.shift(1)).cumsum()
            return s.groupby(grp).cumsum() * s
        df["consecutive_doji_count"] = (
            is_doji_series.groupby(df["ticker"]).transform(_streak).astype(int)
        )
        # consecutive_doji_range_high/low: max high / min low over the active streak
        # (use rolling with window = current streak; we approximate with last 10-day
        #  window when streak >= 2, else NaN)
        DOJI_RANGE_WINDOW = 10
        _hi_doji = g["high"].transform(
            lambda s: s.rolling(DOJI_RANGE_WINDOW, min_periods=2).max()
        )
        _lo_doji = g["low"].transform(
            lambda s: s.rolling(DOJI_RANGE_WINDOW, min_periods=2).min()
        )
        streak_active = df["consecutive_doji_count"] >= 2
        df["consecutive_doji_range_high"] = _hi_doji.where(streak_active, other=np.nan)
        df["consecutive_doji_range_low"] = _lo_doji.where(streak_active, other=np.nan)

        # INTRO-tier-2 toplevel aliases for YAML DSL
        df["ma60_falling_flag"] = df["ma60_falling"].fillna(False).astype(int)
        df["consolidation_over_2_5_months_flag"] = (
            df["consolidation_over_2_5_months"].fillna(False).astype(int)
        )
        df["volume_exceeds_resistance_volume_flag"] = (
            df["volume_exceeds_resistance_volume"].fillna(False).astype(int)
        )
        df["consecutive_doji_count_int"] = df["consecutive_doji_count"].fillna(0).astype(int)

    return df


# ── On-disk cache for load_bars + add_features ────────────────────────────────
# Thin wrapper around scripts/kline/cache.py's parquet store. Keeps a single
# entry point (load_features_cached) for callers that just want the full-market
# featured frame without dealing with the explicit save/load API.

_log_cache = logging.getLogger(__name__ + ".cache")


def load_features_cached(
    db_path: Path | None = None,
    fill_from_backfill: bool = True,
    cache_dir: Path | None = None,  # unused; kept for backward compat
    no_cache: bool = False,
) -> pd.DataFrame:
    """load_bars + add_features with the parquet cache from ``kline.cache``.

    Returns a DataFrame identical to ``add_features(load_bars(db_path,
    fill_from_backfill=fill_from_backfill))``. Cache lives at
    ``~/.kline_cache/features/all_none_none_<FEATURES_VERSION>.parquet``.
    Bump ``cache.FEATURES_VERSION`` when features.py logic changes.

    Pass ``no_cache=True`` to bypass cache read AND write — forces a fresh
    compute, useful when iterating on features.py during development.
    """
    from .bars import DEFAULT_DB_PATH, load_bars
    from .cache import load_cached_features, save_cached_features

    if db_path is None:
        db_path = DEFAULT_DB_PATH

    if not no_cache:
        cached = load_cached_features(tickers=None, start=None, end=None)
        if cached is not None:
            return cached

    _log_cache.info("features cache %s: building from DB", "bypass" if no_cache else "miss")
    bars = load_bars(db_path=db_path, fill_from_backfill=fill_from_backfill)
    feats = add_features(bars)
    if not no_cache:
        save_cached_features(feats, tickers=None, start=None, end=None)
    return feats
