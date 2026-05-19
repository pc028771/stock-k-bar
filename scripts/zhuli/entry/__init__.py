"""Entry signals for zhuli course strategies.

Public API:
    ENTRY_REGISTRY: dict mapping signal name to detect() function.

Each detect() function accepts a features DataFrame and returns a DataFrame
of signal rows (not a bool Series like kline.entry), because zhuli signals
are multi-row (one row per signal, with scenario and metadata columns).

Course: 主力大全方位操盤教戰守則 (林家洋)
"""
from __future__ import annotations

from . import open_signal_filter, suffocation

ENTRY_REGISTRY = {
    "suffocation": suffocation.detect,
    "open_signal_filter": open_signal_filter.detect,
}

__all__ = [
    "ENTRY_REGISTRY",
    "open_signal_filter",
    "suffocation",
]
