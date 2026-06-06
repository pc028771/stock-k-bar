"""壓力區到達出場 — 由多空轉折 bearish patterns + 多方力竭組合判定.

Course source: 【買點賣點】出場點的各種依據-下一個買點 + 多空轉折組合 K 線 26 篇.
Cross-course alignment: K線力量入門 §44 反彈遇壓先出場.

Course quote (入門 §44):
  「應該先出場，等到股價越過了這個壓力區段，再考慮還有沒有買回的意義」

組合邏輯：任一 bearish reversal pattern 觸發 + 多方力竭/遇壓背景成立 ⇒ True.

Verification 2026-06-06 (入門 §44 alignment):
  老師明示「先出場」前提是「股價遇到壓力區段」+「並非要繼續攻擊」。
  本實作以「多空轉折 bearish pattern」作為「不要繼續攻擊」的訊號代理、
  以 bull_exhaustion_context() OR overhead_supply_layer > 0 作為「遇壓力」
  代理。符合入門「先出場、等越過再考慮買回」的雙條件原意 ✓。
  「買回」邏輯不在本 exit 內、由 user 依「越過壓力區段」判斷後手動處理。
"""
from __future__ import annotations

import pandas as pd

from ..patterns._common import bull_exhaustion_context
from ..patterns.bear_engulfing import detect as bear_engulfing
from ..patterns.dark_double_star_anye import detect as dark_double_star
from ..patterns.evening_star_abandoned import detect as evening_star
from ..patterns.evening_star_island_reversal import detect as island_bear
from ..patterns.gap_reversal import detect as gap_reversal
from ..patterns.gap_under_pressure_reversal import detect as gap_pressure
from ..patterns.high_hanging_man import detect as hanging_man
from ..patterns.outside_three_black import detect as outside_three_black
from ..patterns.piercing_line import detect as piercing
from ..patterns.three_red_dadi_dangqian import detect as three_red_dadi
from ..patterns.two_crow_gap import detect as two_crow


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    """壓力區到達出場 — bearish 多空轉折組合任一觸發.

    Component patterns:
      - bear_engulfing (P02)
      - high_hanging_man (P05)
      - three_red_dadi_dangqian (P07)
      - dark_double_star_anye (P08)
      - gap_under_pressure_reversal (P08b)
      - gap_reversal (P09)
      - two_crow_gap (P10)
      - evening_star_abandoned (P12)
      - evening_star_island_reversal (P13)
      - outside_three_black (P15)
      - piercing_line (P20 烏雲罩頂)

    多數 component pattern 已內建多方力竭 filter; 此處再 AND 保險.
    """
    triggered = (
        bear_engulfing(df)
        | hanging_man(df)
        | three_red_dadi(df)
        | dark_double_star(df)
        | gap_pressure(df)
        | gap_reversal(df)
        | two_crow(df)
        | evening_star(df)
        | island_bear(df)
        | outside_three_black(df)
        | piercing(df)
    )
    # 多方力竭/遇壓背景 — 大部分 component 已內建，這裡再 OR 「遇壓」(overhead_supply > 0)
    g = df.groupby("ticker")
    has_overhead = g["overhead_supply_layer"].shift(1).fillna(0) > 0
    exhaust_or_overhead = bull_exhaustion_context(df) | has_overhead
    return (triggered & exhaust_or_overhead).fillna(False)
