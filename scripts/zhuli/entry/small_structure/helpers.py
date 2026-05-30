"""共用工具函式 — 小結構 module 輔助計算.

提供高位判定、平台收斂、量縮、前段攻擊等基礎判斷，
可被 detector.py、watchlist.py 單獨使用。
"""
from __future__ import annotations

import pandas as pd


def has_prior_attack(close: pd.Series, window: int = 20, pct: float = 10.0) -> pd.Series:
    """前段攻擊判定：過去 N 天（shift 5 後）的最低點到當日漲幅 >= pct%.

    Parameters
    ----------
    close  : 收盤價 Series
    window : 往前看幾個交易日（預設 20）
    pct    : 最小漲幅門檻（預設 10%）

    Returns
    -------
    bool Series
    """
    prior_low = close.rolling(window).min().shift(5)
    return ((close / prior_low - 1) >= pct / 100).fillna(False)


def is_consolidating(close: pd.Series, n: int = 5, range_pct: float = 10.0) -> pd.Series:
    """平台收斂判定：近 N 天收盤 range < range_pct%.

    Parameters
    ----------
    close     : 收盤價 Series
    n         : 觀察天數（預設 5）
    range_pct : 最大 range 門檻（預設 10%）

    Returns
    -------
    bool Series
    """
    close_range = (close.rolling(n).max() - close.rolling(n).min()) / close
    return (close_range < range_pct / 100).fillna(False)


def is_volume_contracted(vol_ratio: pd.Series, n: int = 3, thresh: float = 1.5) -> pd.Series:
    """量縮判定：近 N 天均量比 < thresh 且最後一日 < 前幾天均量比.

    Parameters
    ----------
    vol_ratio : vol_ratio_20 Series（成交量 / 20日均量）
    n         : 觀察天數（預設 3）
    thresh    : 均量比門檻（預設 1.5）

    Returns
    -------
    bool Series
    """
    vol_recent = vol_ratio.rolling(n).mean()
    return ((vol_recent < thresh) & (vol_ratio < vol_recent.shift(2))).fillna(False)


def is_high_position(close: pd.Series, high: pd.Series, n: int = 10, pct: float = 85.0) -> pd.Series:
    """高位維持判定：收盤在近 N 天最高點的 pct% 以上.

    Parameters
    ----------
    close : 收盤價 Series
    high  : 最高價 Series
    n     : 回看天數（預設 10）
    pct   : 最低維持比例（預設 85%）

    Returns
    -------
    bool Series
    """
    high_nd = high.rolling(n).max()
    return (close / high_nd >= pct / 100).fillna(False)
