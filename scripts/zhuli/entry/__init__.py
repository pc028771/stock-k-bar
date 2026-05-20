"""Entry signals for zhuli course strategies.

Public API:
    ENTRY_REGISTRY: dict mapping signal name to detect() function.

Each detect() function accepts a features DataFrame and returns a DataFrame
of signal rows (not a bool Series like kline.entry), because zhuli signals
are multi-row (one row per signal, with scenario and metadata columns).

Course: 主力大全方位操盤教戰守則 (林家洋)

Registered signals:
    suffocation            — H 窒息量策略 (Ex1-1 ~ Ex1-3)
    open_signal_filter     — M 主力意圖判斷收高開低/收低開高 (Ch7-3)
    institutional_firstbuy — J 投信首買策略 (Ex2-3)
    swing_breakout         — A 大波段選股策略（族群+籌碼+技術三面）(Ch3-1, Ch3-2)
    bbands_upper_break     — D 布林上軌進出策略 (Ch4-2)
    overnight_swing        — G 隔日沖策略 (Ch6-1 + Ch6-2)
    reversal_breakout      — C 反轉形態策略 (Ch4-2)
"""
from __future__ import annotations

from . import (
    bbands_upper_break,
    institutional_firstbuy,
    open_signal_filter,
    overnight_swing,
    reversal_breakout,
    suffocation,
    swing_breakout,
)

ENTRY_REGISTRY = {
    "suffocation": suffocation.detect,
    "open_signal_filter": open_signal_filter.detect,
    "institutional_firstbuy": institutional_firstbuy.detect,
    "swing_breakout": swing_breakout.detect,
    "bbands_upper_break": bbands_upper_break.detect,
    "overnight_swing": overnight_swing.detect,
    "reversal_breakout": reversal_breakout.detect,
}

__all__ = [
    "ENTRY_REGISTRY",
    "bbands_upper_break",
    "institutional_firstbuy",
    "open_signal_filter",
    "overnight_swing",
    "reversal_breakout",
    "suffocation",
    "swing_breakout",
]
