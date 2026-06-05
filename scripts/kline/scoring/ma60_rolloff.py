"""MA60 carry-off (扣抵) pressure score.

Course source: 【移動平均】季線與K線高低點.
  明日 K 線 INVENTORY.md §C10 (第 06 篇 / 「季線扣抵」)

MA60 direction tomorrow is determined by comparing today's new close
against the close from 60 bars ago (which is about to roll off the window).

  new_close > rolling_off_close → MA60 turns up tomorrow  (bullish)
  new_close < rolling_off_close → MA60 turns down tomorrow (bearish)

This factor adds a small bonus/penalty proportional to the carry-off
direction.

§C10 明日 K 線補充（INVENTORY §C10）:
  季線即將下彎（扣抵高、close 低）+ 隔日無紅 K 表態 → 加分（多方力量不足）。
  Implementation: `ma60_about_to_fall` flag = (rolloff_close > today_close AND
  is_black_or_doji today). When MA60 is about to fall and today did NOT show
  bullish intent, add an extra `MA60_BEARISH_NO_CONFIRM_BONUS` to the base score.

Required df columns: close, ma60_rolling_off_close, is_red (added by features).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MAX_DELTA = 10.0  # cap so extreme rolloffs don't dominate

# §C10: extra penalty when MA60 is about to bend down AND today shows no bullish intent
# Course source: INVENTORY §C10 / 第 06 篇「季線即將下彎 + 隔日無紅 K 表態 → 多方力量不足」
MA60_BEARISH_NO_CONFIRM_BONUS = -3.0  # course-not-stated magnitude — engineering proxy


def score(df: pd.DataFrame) -> pd.Series:
    """Returns float Series.

      +10 if rolling_off_close is well below current close
      −10 if well above
      −3  extra if MA60 about to fall (rolloff > close) AND today not bullish (§C10)
      0 otherwise / NaN
    """
    delta = df["close"] - df["ma60_rolling_off_close"]
    norm = (delta / df["close"].replace(0, np.nan)).clip(-0.10, 0.10) / 0.10
    base = (norm * MAX_DELTA).fillna(0.0)

    # === §C10: 季線即將下彎 + 今日無紅 K 表態 ===
    # Course: INVENTORY §C10 / 第 06 篇 — 「季線扣抵」判斷明日 MA60 方向
    # 季線即將下彎 = 扣抵值 > 今日收盤（明日 MA60 必然下彎）
    ma60_about_to_fall = (
        df["ma60_rolling_off_close"].notna()
        & (df["ma60_rolling_off_close"] > df["close"])
    )
    # 今日無紅 K 表態 = is_red 為 False（黑 K 或十字線）
    # Fallback: if is_red not yet computed, derive from open/close
    if "is_red" in df.columns:
        today_no_bull = ~df["is_red"].fillna(False)
    else:
        today_no_bull = (df["close"] <= df["open"])

    extra = ma60_about_to_fall & today_no_bull
    return (base + extra.astype(float) * MA60_BEARISH_NO_CONFIRM_BONUS).fillna(0.0)
