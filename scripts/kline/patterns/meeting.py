"""遭遇型態 — context_only.

Course source: 第 21 篇《遭遇型態》(4A2519730555027A6612FC9C77BE51FB)
Cross-course definition: PATTERN_INVENTORY P22.
Engineering proxy constants: BITE_CLOSE_EQUAL_TOLERANCE.
"""
from __future__ import annotations

import pandas as pd

from ..course_proxy_constants import BITE_CLOSE_EQUAL_TOLERANCE


def detect(df: pd.DataFrame) -> pd.Series:
    """遭遇型態 — 收盤相同的抵抗（跌勢或漲勢中）.

    Course definition (article 4A2519... line 10):
      「定義：在略顯跌勢後出現的黑K，隔日遇到紅K的抵抗，收盤價與前一天的
       收盤價『相同』；或者是漲勢後的紅K，隔日遇到黑K的抵抗，收盤價與前
       一天的紅K收盤價『相同』。」

    Conditions:
      1. 今日 close ≈ 前日 close (BITE_CLOSE_EQUAL_TOLERANCE)
      2. 「跌勢」or「漲勢」context — 用 ma20 走向代理
         (course: 「略顯跌勢 / 漲勢」 是 setup background)

    Earlier (2026-06-02) the impl required prev_was_gap, but course never
    mentions gap as a defining condition; it only mentions「攻擊缺口的封口」
    as one of several POST-hoc interpretations. Removed gap requirement
    after 康舒 6282 2022-01-19 case (close 34.10→34.10 with no gap) was
    confirmed by user as legitimate course example.
    """
    g = df.groupby("ticker")
    prev_close = g["close"].shift(1)

    close_eq = (df["close"] - prev_close).abs() / prev_close.replace(0, float("nan")) < BITE_CLOSE_EQUAL_TOLERANCE

    # 跌勢 OR 漲勢 — course says「略顯」(slight). Use position vs ma20 as
    # primary indicator: close materially above/below ma20 implies trend.
    # Avoids over-strict slope check (-0.5%/3d originally proposed missed
    # 康舒 6282 2022-01-19 case which had ma20 sliding gently -0.4%/3d).
    in_uptrend = df["close"] > df["ma20"] * 1.005  # close ≥ 0.5% above ma20
    in_downtrend = df["close"] < df["ma20"] * 0.995  # close ≥ 0.5% below ma20
    in_trend = in_uptrend | in_downtrend

    return (close_eq & in_trend).fillna(False)
