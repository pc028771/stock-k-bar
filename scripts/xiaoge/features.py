"""Bollinger band features + auxiliary indicators for 權證小哥 (xiaoge) course.

Source: docs/權證小哥/籌碼技術分析/快速上手筆記.md, detector_spec.md
Course refs: ch06 (布林軌道說明), ch07 (6 種布林型態), ch12 (飆股口袋名單多頭策略)

> 「布林軌道打開，股價沿著上軌前進，那周圍點就是起漲點。」(ch03 01:35)
> 「布林軌道是一個由 20MA 加減 2 個標準差所形成的通道。」(ch06)

Bandwidth scale (老師原話、ch06):
    - bandwidth < 5  → 很窄（收斂、整理）
    - bandwidth ~ 10 → 正常
    - bandwidth ~ 20 → 寬
    - bandwidth ~ 30 → 很寬（噴出後可能進入震盪）

Formula: bandwidth = (bb_upper - bb_lower) / bb_lower * 100
"""
from __future__ import annotations

from enum import Enum

import pandas as pd


BB_PERIOD = 20
BB_STDDEV = 2.0


def add_bollinger(df: pd.DataFrame) -> pd.DataFrame:
    """Add bb_mid / bb_upper / bb_lower / bb_bandwidth columns.

    Required df columns: ticker, trade_date, close. Sorted by (ticker, trade_date).
    """
    out = df.copy()
    grp = out.groupby("ticker")["close"]
    mid = grp.transform(lambda s: s.rolling(BB_PERIOD, min_periods=BB_PERIOD).mean())
    std = grp.transform(lambda s: s.rolling(BB_PERIOD, min_periods=BB_PERIOD).std(ddof=0))
    out["bb_mid"] = mid
    out["bb_upper"] = mid + BB_STDDEV * std
    out["bb_lower"] = mid - BB_STDDEV * std
    # bandwidth normalized by lower band so it represents % range from lower→upper
    out["bb_bandwidth"] = (out["bb_upper"] - out["bb_lower"]) / out["bb_lower"] * 100.0
    return out


def add_squeeze_features(df: pd.DataFrame, squeeze_lookback: int = 10,
                         squeeze_threshold: float = 12.0) -> pd.DataFrame:
    """Add bb_in_squeeze flag.

    bb_in_squeeze[t] = True iff past `squeeze_lookback` bars all have bandwidth ≤ threshold.

    Threshold 12 (slight relaxation of 老師's 10「正常」line — gives some breathing room).
    See detector_spec.md detector 1 condition 2.
    """
    out = df.copy()
    grp = out.groupby("ticker")["bb_bandwidth"]
    max_recent = grp.transform(
        lambda s: s.rolling(squeeze_lookback, min_periods=squeeze_lookback).max()
    )
    out["bb_in_squeeze"] = max_recent <= squeeze_threshold
    return out


# ---------------------------------------------------------------------------
# Indicator 1 — 短期波動度（ch12 多頭策略 #6 / 空頭策略 #6）
# ---------------------------------------------------------------------------

def add_volatility(df: pd.DataFrame, window: int = 5,
                   threshold_rising_pct: float = 2.0) -> pd.DataFrame:
    """Add short-term volatility indicator.

    Course source: ch12 飆股口袋名單做多策略 #6 / 空頭策略 #6.

    課程原話（ch12）:
    > 「波動上升且強勢…短期波動度上升 2%↑ + 5MA 上揚 + 站上 5MA」
    > 「買權證最怕盤整、買有波動的。」

    Computation:
        volatility_5d[t]  = std(pct_change(close), window) * 100
                            (rolling std of daily returns, in % units)
        volatility_rising = volatility_5d[t] > volatility_5d[t-1] + threshold_rising_pct

    Parameters
    ----------
    df:
        Must contain: ticker, trade_date, close.  Sorted by (ticker, trade_date).
    window:
        Rolling window for std; default 5 (課程說法「短期波動度」).
    threshold_rising_pct:
        How much volatility must rise vs previous bar to count as "rising".
        Default 2.0 as per 課程原話「上升 2%↑」.

    Added columns
    -------------
    volatility_5d    : float — rolling std of daily returns × 100 (% units)
    volatility_rising: bool  — True when vol[t] > vol[t-1] + threshold_rising_pct
    """
    out = df.copy()
    vol = out.groupby("ticker")["close"].transform(
        lambda s: s.pct_change().rolling(window, min_periods=window).std() * 100
    )
    out["volatility_5d"] = vol
    prev_vol = out.groupby("ticker")["volatility_5d"].transform(lambda s: s.shift(1))
    out["volatility_rising"] = (vol > prev_vol + threshold_rising_pct).fillna(False)
    return out


# ---------------------------------------------------------------------------
# Indicator 2 — 20 日新高 / 新低（ch12 多頭策略 #7 / 空頭策略 #6）
# ---------------------------------------------------------------------------

def add_20d_high_low(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Add 20-day rolling high/low and breakout flags.

    Course source: ch12 飆股口袋名單做多策略 #7 / 空頭策略 #6.

    課程原話（ch12）:
    > 「突破平台整理區…創 20 日高價（這 20 天買的人都賺錢）。」

    The 20-day high is computed including today (rolling max of last `window` bars).
    is_20d_high[t] = True when close[t] == rolling_max(close, window)[t].
    is_20d_low[t]  = True when close[t] == rolling_min(close, window)[t].

    Parameters
    ----------
    df:
        Must contain: ticker, trade_date, close.  Sorted by (ticker, trade_date).
    window:
        Lookback window; default 20 per 課程定義.

    Added columns
    -------------
    high_20d    : float — rolling max(close) over past `window` bars (inclusive)
    low_20d     : float — rolling min(close) over past `window` bars (inclusive)
    is_20d_high : bool  — True when today's close equals the 20d high
    is_20d_low  : bool  — True when today's close equals the 20d low
    """
    out = df.copy()
    grp = out.groupby("ticker")["close"]
    high_20d = grp.transform(lambda s: s.rolling(window, min_periods=window).max())
    low_20d  = grp.transform(lambda s: s.rolling(window, min_periods=window).min())
    out["high_20d"]    = high_20d
    out["low_20d"]     = low_20d
    out["is_20d_high"] = (out["close"] == high_20d).fillna(False)
    out["is_20d_low"]  = (out["close"] == low_20d).fillna(False)
    return out


# ---------------------------------------------------------------------------
# Indicator 3 — 布林軌道 6 型態 Enum（ch07）
# ---------------------------------------------------------------------------

class BollingerPattern(str, Enum):
    """6 種布林軌道型態 (權證小哥 ch07).

    課程原話（ch07）：
    > 「布林昇龍拳…先沿下軌洗清浮額…連續二根紅K或三根紅K，從下通道一下就打到上通道，
    >   這種是多頭表態。」(ch07 00:21–01:16)
    > 「平步青雲開布林…突發性的利多，突然拉一根。」(ch07)
    > 「降龍布林掌…高檔盤整出貨之後往下開布林、沿下軌走。」(ch07)
    > 「息軍養士…初升段後布林壓縮，再次往上開布林（盤整後續攻）。」(ch07)
    > 「回測均線喝了再上…價漲量增、價跌量縮、回測均線後再次往上。」(ch07)
    > 「曲終人散…高檔主力在這邊大幅地賣超，散戶大幅地買超，集保戶數大幅地增加。
    >   第一根黑 K 後容易崩跌。」(ch07 09:13–09:35)
    """
    BB_RISING_DRAGON  = "BB_RISING_DRAGON"   # 布林昇龍拳 (多頭)
    BB_FLAT_OPEN      = "BB_FLAT_OPEN"        # 平步青雲開布林 (突發利多)
    BB_FALLING_DRAGON = "BB_FALLING_DRAGON"   # 降龍布林掌 (空頭)
    BB_REST_AND_RISE  = "BB_REST_AND_RISE"    # 息軍養士 (盤整後續攻)
    BB_PULLBACK_RISE  = "BB_PULLBACK_RISE"    # 回測均線喝了再上
    BB_DISTRIBUTION   = "BB_DISTRIBUTION"     # 曲終人散 (高檔出貨)
    NONE              = "NONE"                # 無明確型態


def classify_bollinger_pattern(
    df: pd.DataFrame,
    squeeze_threshold: float = 10.0,
    squeeze_lookback: int = 10,
    wide_threshold: float = 20.0,
    vol_ratio: float = 1.5,
) -> pd.DataFrame:
    """Classify each row into one of the 6 Bollinger pattern types.

    Course source: 權證小哥課程 ch07 (布林軌道 6 種型態).
    Reference: docs/權證小哥/籌碼技術分析/快速上手筆記.md Lesson 2.

    Pattern detection rules (in priority order, highest last wins):

    BB_PULLBACK_RISE (回測均線喝了再上) — ch07:
        「價漲量增、價跌量縮、回測均線後再次往上。」
        課程僅概念，conservative default:
        close > bb_mid AND prev_close < bb_mid (dipped below mid then bounced) AND is_red.
        (intraday volume trend check omitted — daily bar only)

    BB_REST_AND_RISE (息軍養士) — ch07:
        「初升段後布林壓縮→再次往上開布林。」
        課程僅概念，conservative default:
        NOT in squeeze currently (squeeze ended) AND was_in_squeeze (lookback) AND
        close > bb_upper AND is_red.

    BB_FALLING_DRAGON (降龍布林掌) — ch07:
        「高檔盤整出貨→往下開布林、沿下軌走。」
        Mirror of 升龍拳 (空頭): in_squeeze AND close < bb_lower
                                   AND is_black AND prev_is_black.

    BB_DISTRIBUTION (曲終人散) — ch07 09:13–09:35:
        「高檔主力大幅賣超+散戶買超+集保戶增加+帶寬寬→第一根黑K後崩跌」
        bb_width_pct ≥ wide_threshold (老師「20 以上算寬」) AND is_black AND
        close > bb_mid (still elevated) AND main_force_1d < 0 (if column present).

    BB_FLAT_OPEN (平步青雲) — ch07:
        「突發性利多，突然拉一根，開布林。」
        課程僅概念：in_squeeze AND close > bb_upper AND is_red AND vol_surge
                    AND prev bar NOT red (single-bar event; 升龍拳 requires 2 red K's).

    BB_RISING_DRAGON (布林昇龍拳, highest priority) — ch07 00:21–01:16:
        「先沿下軌洗清浮額…連續二/三根紅K從下通道一口氣打到上通道」
        in_squeeze AND close > bb_upper AND is_red AND prev_is_red
                   AND prev_close ≤ bb_mid (prev was in lower half).

    Parameters
    ----------
    df:
        Must contain: ticker, trade_date, open, close, volume,
                      bb_upper, bb_mid, bb_lower, bb_width_pct.
        Optional: main_force_1d (used for BB_DISTRIBUTION; ignored if absent).
        Sorted by (ticker, trade_date).
    squeeze_threshold:
        bb_width_pct ≤ this value counts as "in squeeze". Default 10 (老師原話).
    squeeze_lookback:
        Bars to sustain for a squeeze period. Default 10.
    wide_threshold:
        bb_width_pct ≥ this counts as "wide band". Default 20 (老師「20 以上算寬」).
    vol_ratio:
        Volume multiplier for BB_FLAT_OPEN single-bar volume surge check.
        Default 1.5 — 課程僅概念、預設值為 conservative 推測。

    Added column
    ------------
    bb_pattern : str — BollingerPattern value string (e.g. "BB_RISING_DRAGON")
    """
    out = df.copy()

    close    = out["close"]
    open_    = out["open"]
    bb_upper = out["bb_upper"]
    bb_lower = out["bb_lower"]
    bb_mid   = out["bb_mid"]
    bb_width = out["bb_width_pct"]

    is_red   = (close > open_).fillna(False)
    is_black = (close < open_).fillna(False)

    grp_close = out.groupby("ticker")["close"]
    grp_open  = out.groupby("ticker")["open"]
    grp_width = out.groupby("ticker")["bb_width_pct"]
    grp_vol   = out.groupby("ticker")["volume"]
    grp_bbmid = out.groupby("ticker")["bb_mid"]

    prev_close    = grp_close.transform(lambda s: s.shift(1))
    prev_open     = grp_open.transform(lambda s: s.shift(1))
    prev_bb_mid   = grp_bbmid.transform(lambda s: s.shift(1))
    prev_is_red   = (prev_close > prev_open).fillna(False)
    prev_is_black = (prev_close < prev_open).fillna(False)

    # Rolling squeeze: max bandwidth over past squeeze_lookback bars ≤ squeeze_threshold
    max_width_now = grp_width.transform(
        lambda s: s.rolling(squeeze_lookback, min_periods=squeeze_lookback).max()
    )
    # was_in_squeeze: squeeze window ending at previous bar
    max_width_prev = grp_width.transform(
        lambda s: s.rolling(squeeze_lookback, min_periods=squeeze_lookback).max().shift(1)
    )
    in_squeeze       = (max_width_now <= squeeze_threshold).fillna(False)
    was_squeezed     = (max_width_prev <= squeeze_threshold).fillna(False)
    not_in_squeeze   = ~in_squeeze

    # Volume vs 5-bar MA for BB_FLAT_OPEN
    vol_ma5   = grp_vol.transform(lambda s: s.rolling(5, min_periods=5).mean())
    vol_surge = (out["volume"] >= vol_ratio * vol_ma5).fillna(False)

    # Cross upper/lower
    cross_upper = (close > bb_upper).fillna(False)
    cross_lower = (close < bb_lower).fillna(False)

    # Prev close in lower half — for 升龍拳 (prev was near lower rail / below mid)
    prev_near_lower = (prev_close <= prev_bb_mid).fillna(False)

    # BB_DISTRIBUTION needs main_force_1d if available
    if "main_force_1d" in out.columns:
        main_force_neg = (out["main_force_1d"] < 0).fillna(False)
    else:
        # Without data, relax this condition so pattern can still fire on BB shape alone
        main_force_neg = pd.Series(True, index=out.index)

    # Assign in priority order (last assignment wins = highest priority)
    pattern = pd.Series(BollingerPattern.NONE.value, index=out.index, dtype=object)

    # P1 (lowest) — BB_PULLBACK_RISE
    pullback_rise = (
        is_red
        & (close > bb_mid)
        & (prev_close < prev_bb_mid).fillna(False)
    )
    pattern[pullback_rise] = BollingerPattern.BB_PULLBACK_RISE.value

    # P2 — BB_REST_AND_RISE (exited squeeze before today, now breaks upper again)
    rest_and_rise = (
        not_in_squeeze
        & was_squeezed
        & cross_upper
        & is_red
    )
    pattern[rest_and_rise] = BollingerPattern.BB_REST_AND_RISE.value

    # P3 — BB_FALLING_DRAGON (空頭鏡像)
    falling_dragon = (
        in_squeeze
        & cross_lower
        & is_black
        & prev_is_black
    )
    pattern[falling_dragon] = BollingerPattern.BB_FALLING_DRAGON.value

    # P4 — BB_DISTRIBUTION
    distribution = (
        (bb_width >= wide_threshold)
        & is_black
        & (close > bb_mid)
        & main_force_neg
    )
    pattern[distribution] = BollingerPattern.BB_DISTRIBUTION.value

    # P5 — BB_FLAT_OPEN (single large red K, volume surge, from squeeze)
    flat_open = (
        in_squeeze
        & cross_upper
        & is_red
        & vol_surge
        & ~prev_is_red  # prev bar NOT red — single-bar event
    )
    pattern[flat_open] = BollingerPattern.BB_FLAT_OPEN.value

    # P6 (highest) — BB_RISING_DRAGON
    rising_dragon = (
        in_squeeze
        & cross_upper
        & is_red
        & prev_is_red
        & prev_near_lower
    )
    pattern[rising_dragon] = BollingerPattern.BB_RISING_DRAGON.value

    out["bb_pattern"] = pattern
    return out
