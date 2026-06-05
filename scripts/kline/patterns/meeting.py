"""遭遇型態 — context_only.

Course source: 第 21 篇《遭遇型態》(4A2519730555027A6612FC9C77BE51FB)
Cross-course definition: PATTERN_INVENTORY P22.
Engineering proxy constants: BITE_CLOSE_EQUAL_TOLERANCE.
"""
from __future__ import annotations

import pandas as pd

from ..course_proxy_constants import BITE_CLOSE_EQUAL_TOLERANCE
from ._common import in_trend


def detect(df: pd.DataFrame) -> pd.Series:
    """遭遇型態 — 收盤相同的抵抗（跌勢或漲勢中）.

    Course definition (article 4A2519... line 10):
      「定義：在略顯跌勢後出現的黑K，隔日遇到紅K的抵抗，收盤價與前一天的
       收盤價『相同』；或者是漲勢後的紅K，隔日遇到黑K的抵抗，收盤價與前
       一天的紅K收盤價『相同』。」

    Conditions (refactored 2026-06-03 to use _common helper):
      1. 今日 close ≈ 前日 close (BITE_CLOSE_EQUAL_TOLERANCE)
      2. 「略顯跌勢」or「略顯漲勢」context — in_trend(method='close_vs_ma20')

    Case calibration:
      - Case #1 康舒 6282 2022-01-19: close 34.10 = prev 34.10, in 下跌 context
    """
    g = df.groupby("ticker")
    prev_close = g["close"].shift(1)

    close_eq = (df["close"] - prev_close).abs() / prev_close.replace(0, float("nan")) < BITE_CLOSE_EQUAL_TOLERANCE

    # 「略顯」趨勢 — close vs ma20 (Case #1 康舒 細微下滑也算)
    trend = in_trend(df, "bull", method="close_vs_ma20") | in_trend(df, "bear", method="close_vs_ma20")

    return (close_eq & trend).fillna(False)
