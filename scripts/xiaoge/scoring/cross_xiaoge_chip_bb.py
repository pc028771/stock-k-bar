"""cross_xiaoge_chip_bb — detector 1 ∩ detector 2 交叉強化訊號.

Logic: 同日 OR 過去 N 日內 detector 1 跟 detector 2 都觸發 → 升優先級.

Course source: detector_spec.md §6 cross_xiaoge_swing — 把布林 + 籌碼兩軸交叉。
分點 (detector 4) 因資料未到位、暫缺、留 Phase 3b.
"""
from __future__ import annotations

import pandas as pd

from scripts.xiaoge.entry.bb_squeeze_breakout import detect as detect_bb
from scripts.xiaoge.entry.main_chip_holder import detect as detect_chip


def detect_cross(df: pd.DataFrame, window: int = 5,
                 bb_kwargs: dict | None = None,
                 chip_kwargs: dict | None = None) -> pd.Series:
    """Return bool Series; True = both detectors fired within `window` days.

    Required df columns: 同 bb_squeeze_breakout + main_chip_holder.
    """
    bb_kwargs = bb_kwargs or {}
    chip_kwargs = chip_kwargs or {}

    bb_sig = detect_bb(df, **bb_kwargs)
    chip_sig = detect_chip(df, **chip_kwargs)

    # Was bb signal fired anytime in past `window` days for this ticker?
    bb_in_window = bb_sig.groupby(df["ticker"]).transform(
        lambda s: s.rolling(window, min_periods=1).max()
    ).astype(bool)
    chip_in_window = chip_sig.groupby(df["ticker"]).transform(
        lambda s: s.rolling(window, min_periods=1).max()
    ).astype(bool)

    # Cross signal fires the day BOTH conditions are true (i.e., both
    # fired within their rolling window). Fires on every such day, not just
    # transition — caller can de-duplicate if needed.
    return (bb_in_window & chip_in_window).fillna(False)
