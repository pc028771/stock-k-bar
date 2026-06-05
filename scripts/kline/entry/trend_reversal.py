"""底部轉折型買點 — 由多空轉折 patterns (bull) 組合判定.

Course source: 【買點賣點】出場點(一) + 多空轉折組合 K 線 26 篇.

⚠️ 重要警語 (PATTERN_DEFINITIONS §3 + PATTERN_INVENTORY P03/P14):
  「多頭吞噬本身不是買點」「晨星島狀反轉不是進場訊號」 — 課程明示.
  本 detect 屬「空單回補 / 弱勢進場觀察」性質，不可直接當主動買訊使用.
  上層 scanner 應再加額外確認 (例如老師點名 + 籌碼 + MA60 翻揚) 才可進場.

組合邏輯：任一 bullish reversal pattern 觸發 + 空方力竭背景已成立 ⇒ True.
"""
from __future__ import annotations

import pandas as pd

from ..patterns._common import bear_exhaustion_context
from ..patterns.breakout_double_star import detect as breakout_double_star
from ..patterns.bull_engulfing import detect as bull_engulfing
from ..patterns.morning_star_harami import detect as morning_star_harami
from ..patterns.morning_star_island_reversal import detect as island_bull
from ..patterns.piercing_line import detect as piercing


def detect(df: pd.DataFrame) -> pd.Series:
    """空單回補 / 弱勢進場觀察點 — bullish 多空轉折組合任一觸發.

    Component patterns:
      - bull_engulfing (P03)
      - morning_star_harami (P04 / P06)
      - breakout_double_star (P11)
      - morning_star_island_reversal (P14)
      - piercing_line (P20 曙光乍現)

    都已內建空方力竭 filter (本 wrapper 再 AND 一次保險).
    """
    triggered = (
        bull_engulfing(df)
        | morning_star_harami(df)
        | breakout_double_star(df)
        | island_bull(df)
        | piercing(df)
    )
    return (triggered & bear_exhaustion_context(df)).fillna(False)
