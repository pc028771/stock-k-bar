"""遭遇型態 — context_only.

Course source: 第 21 篇《遭遇型態》(4A2519730555027A6612FC9C77BE51FB)
Cross-course definition: PATTERN_INVENTORY P22.
Engineering proxy constants: BITE_CLOSE_EQUAL_TOLERANCE.
"""
from __future__ import annotations

import pandas as pd

from ..course_proxy_constants import BITE_CLOSE_EQUAL_TOLERANCE


def detect(df: pd.DataFrame) -> pd.Series:
    """遭遇型態 — 前日帶跳空力量 K + 今日收盤 ≈ 前日收盤 (缺口封閉).

    Conditions (PATTERN_INVENTORY P22):
      1. 前一日帶跳空 (open-gap or body-gap relative to prev_prev close/high/low)
      2. 今日收盤 ≈ 前日收盤 (BITE_CLOSE_EQUAL_TOLERANCE)

    NOTE per MISS_DIAGNOSIS calibration (2026-06-02): 原本第 3 條「顏色相反」
    過嚴。課程明示「最後一天是平盤作收」(article 4A2519...) — 今日只要 close
    ≈ prev close 即成立，不論 doji 或反色。6556 2022-02-10 即為此型 (今日為
    open=close 平盤 K)。改為允許今日為任何顏色。

    Gap relaxation: 原本要求 prev 整根 K 跳空 (high<prev_prev_low OR
    low>prev_prev_high)。但課程定義「攻擊缺口的封口」涵蓋 open-gap (今日
    開盤就跳空)。改為前日 open 或 low/high 任一證實跳空即可。
    """
    g = df.groupby("ticker")
    prev_close = g["close"].shift(1)
    prev_open = g["open"].shift(1)
    prev_high_v = g["high"].shift(1)
    prev_low_v = g["low"].shift(1)
    prev_prev_close = g["close"].shift(2)
    prev_prev_low = g["low"].shift(2)
    prev_prev_high = g["high"].shift(2)

    # adjusted 2026-06-02 per MISS_DIAGNOSIS calibration — 放寬為 open-gap 或 body-gap
    prev_gap_down = (prev_high_v < prev_prev_low) | (prev_open < prev_prev_close) & (prev_high_v < prev_prev_close)
    prev_gap_up = (prev_low_v > prev_prev_high) | ((prev_open > prev_prev_close) & (prev_low_v > prev_prev_close))
    prev_was_gap = prev_gap_down | prev_gap_up

    close_eq = (df["close"] - prev_close).abs() / prev_close.replace(0, float("nan")) < BITE_CLOSE_EQUAL_TOLERANCE

    # adjusted 2026-06-02 per MISS_DIAGNOSIS — drop strict opposite color
    # (course: 「最後一天是平盤作收」allows doji/flat today)
    return (prev_was_gap & close_eq).fillna(False)
