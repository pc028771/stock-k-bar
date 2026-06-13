"""xiaoge_bb_squeeze_breakout — 布林軌道收斂後突破多頭訊號.

Course source: 權證小哥課程 ch06-ch08, ch12 飆股口袋名單做多策略 #8 #9.
Reference: docs/權證小哥/籌碼技術分析/detector_spec.md §1.

Course quotes (verbatim):
> 「布林昇龍拳…先沿下軌洗清浮額…連續二根紅K或三根紅K，從下通道一下就打到上通道，
>   這種是多頭表態。」 (ch07 00:21–01:16)
> 「布林軌道打開…短期有整理完畢往上攻擊的態勢，那這種呢通常壓縮的越久，
>   之後的漲勢拉就越驚人。」 (ch12 06:44–07:08)

Quantified rules (detector_spec §1):
    1. Squeeze precondition: past 10 bars all bandwidth ≤ 12 (delegated to
       features.add_squeeze_features, exposed as bb_in_squeeze)
    2. Breakout signal (option a — 升龍拳):
       2-3 consecutive red K's lifting close from ≤ bb_mid to > bb_upper.
    3. Breakout signal (option b — 開布林表態):
       single bar with close > bb_upper AND red K AND volume ≥ 1.5 × MA5(volume).
    4. Filter: 5MA up-sloping AND close > 5MA (ch12 策略 #6).

Stop loss is NOT defined in pure course; see ../exit/leave_upper_band.py for
the course-defined exit ("K 棒收盤離開上軌就找短線停利"). Structural stop
loss推測 lives in xiaoge/extras/.
"""
from __future__ import annotations

import pandas as pd


def detect(df: pd.DataFrame, breakout_mode: str = "any",
           vol_multiple: float = 1.5) -> pd.Series:
    """Return bool Series; True = xiaoge_bb_squeeze_breakout long signal.

    Parameters
    ----------
    df:
        Bars DataFrame with at least columns: ticker, trade_date, open, high,
        low, close, volume, bb_upper, bb_mid, bb_bandwidth, bb_in_squeeze, ma5.
        Sorted by (ticker, trade_date).
    breakout_mode:
        - "shenglongquan": option a only (升龍拳 / 2-3 red K's)
        - "open_breakout": option b only (single red K + volume)
        - "any": either (default)
    vol_multiple:
        Volume threshold multiplier vs MA5(volume) for option b.

    Returns
    -------
    pd.Series of bool indexed identically to df.
    """
    close = df["close"]
    open_ = df["open"]
    is_red = close > open_

    # Yesterday-state references
    grp_close = df.groupby("ticker")["close"]
    grp_volume = df.groupby("ticker")["volume"]
    grp_bb_in_squeeze = df.groupby("ticker")["bb_in_squeeze"]
    grp_bb_mid = df.groupby("ticker")["bb_mid"]
    grp_bb_upper = df.groupby("ticker")["bb_upper"]

    prev_close = grp_close.shift(1)
    prev2_close = grp_close.shift(2)
    prev_bb_upper = grp_bb_upper.shift(1)
    prev_bb_mid = grp_bb_mid.shift(1)

    # Squeeze precondition (yesterday was in squeeze — breakout fires when
    # today exits the squeeze)
    was_squeezed = grp_bb_in_squeeze.shift(1).fillna(False)

    # Today breaks above upper band
    cross_upper = (close > df["bb_upper"]) & (prev_close <= prev_bb_upper)

    # Volume vs 5-day average
    vol_ma5 = grp_volume.transform(lambda s: s.rolling(5, min_periods=5).mean())
    vol_ratio_ok = df["volume"] >= vol_multiple * vol_ma5

    # Option a — 升龍拳: 2 or 3 consecutive red K's, prev close was below or near bb_mid
    prev_is_red = grp_close.shift(1) > df.groupby("ticker")["open"].shift(1)
    two_red_streak = is_red & prev_is_red
    prev_near_or_below_mid = prev_close <= prev_bb_mid * 1.02  # within 2% of mid
    shenglong = was_squeezed & cross_upper & two_red_streak & prev_near_or_below_mid

    # Option b — 開布林表態: single large red K + volume
    open_breakout = was_squeezed & cross_upper & is_red & vol_ratio_ok

    # Trend filter (ch12 策略 #6): 5MA up-sloping + close above 5MA
    ma5 = df["ma5"] if "ma5" in df.columns else grp_close.transform(
        lambda s: s.rolling(5, min_periods=5).mean()
    )
    ma5_prev = ma5.groupby(df["ticker"]).shift(1)
    ma5_rising = (ma5 > ma5_prev).fillna(False)
    above_ma5 = (close > ma5).fillna(False)

    if breakout_mode == "shenglongquan":
        raw = shenglong
    elif breakout_mode == "open_breakout":
        raw = open_breakout
    else:
        raw = shenglong | open_breakout

    return (raw & ma5_rising & above_ma5).fillna(False)
