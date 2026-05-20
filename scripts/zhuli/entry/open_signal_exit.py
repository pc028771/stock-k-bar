"""M-Exit 主力意圖收高開低 + 漲停板平盤警示 (出場警示) — 主力大 Ch7-3 子集.

拆自 open_signal_filter (master)，保留 bearish_exit + limit_up_flat_warning。
出場語意 = **不適合 entry backtest**，是減碼/出場警示工具。

定義:
    bearish_exit         — 前日收最高 + 今日開低/開平 → 主力試空賣方意圖
    limit_up_flat_warning — 前日漲停 + 今日開平 → 動能轉弱

用途:
    - 持股盤中監控 (watchlist_intraday)
    - 跟其他 scanner signal 交叉確認時 = 紅燈
    - 不應該獨立當進場依據
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from zhuli.config import OpenSignalConfig
from zhuli.entry.open_signal_filter import detect as _master_detect


def detect(
    df: pd.DataFrame,
    cfg: Optional[OpenSignalConfig] = None,
) -> pd.DataFrame:
    """只回傳 bearish_exit + limit_up_flat_warning."""
    signals = _master_detect(df, cfg=cfg)
    if signals.empty:
        return signals
    return signals[
        signals["signal_type"].isin(["bearish_exit", "limit_up_flat_warning"])
    ].reset_index(drop=True)
