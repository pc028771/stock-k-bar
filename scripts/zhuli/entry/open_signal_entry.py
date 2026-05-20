"""M-Entry 主力意圖收低開高 (進場訊號) — 主力大 Ch7-3 子集.

拆自 open_signal_filter (master)，只保留 bullish_entry signal_type。
進場語意明確 = 適合進場 backtest。

定義: 前日收最低（跌停）+ 今日開高 → 主力試多買方意圖
進場: 隔日開盤 / 課程「次日開平、開紅」立即跟進
停損: 前日 low（signal_filter 已輸出 stop_loss）
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
    """只回傳 bullish_entry signal_type."""
    signals = _master_detect(df, cfg=cfg)
    if signals.empty:
        return signals
    return signals[signals["signal_type"] == "bullish_entry"].reset_index(drop=True)
