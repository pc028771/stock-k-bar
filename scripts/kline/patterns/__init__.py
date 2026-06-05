"""多空轉折組合 K 線 patterns — 26 篇 PressPlay 延伸講座的型態識別層.

設計原則 (來自 PATTERN_INVENTORY P01, P18 觀念篇):
  - 轉折組合是「多單出場」/「空單回補」，**非反向進場訊號**.
  - 力竭原理：原始趨勢結束，不一定是反向開始.
  - 純型態識別層 (pure detect)，不含「該不該買」語意.
  - 失效條件判定 (e.g. 隔日創新高使空頭吞噬失效) 留給上層 simulator.

API:
  每個 module 提供 `detect(df) -> pd.Series[bool]`.
  觸發點 = 「pattern 完成的那一根 K」(即回 True 那天可作為 entry/exit timing).

子模組對應 inventory:
  P02 bear_engulfing       P03 bull_engulfing
  P04/P06 morning_star_harami
  P05 high_hanging_man
  P07 three_red_dadi_dangqian
  P08 dark_double_star_anye
  P08b gap_under_pressure_reversal
  P09 gap_reversal
  P10 two_crow_gap
  P11 breakout_double_star
  P12 evening_star_abandoned
  P13 evening_star_island_reversal
  P14 morning_star_island_reversal
  P15 outside_three_black
  P19 neutral_engulfing
  P20 piercing_line
  P21 embracing
  P22 meeting
  P23 rebound
  P24 trapped
  P25 biting
  P26 rising_falling
  P27 gap_fill_up / gap_fill_down

  P16/P17 single_day_reversal → scripts/kline/extras/ (課程明示「最微弱」).
  P01/P18 → 觀念篇，不實作.
"""
from __future__ import annotations

from . import (
    attack_cost_displayed,
    bear_engulfing,
    biting,
    breakout_double_star,
    bull_engulfing,
    dark_double_star_anye,
    embracing,
    evening_star_abandoned,
    evening_star_island_reversal,
    gap_fill_down,
    gap_fill_up,
    gap_reversal,
    gap_under_pressure_reversal,
    high_hanging_man,
    meeting,
    merged_doji,
    morning_star_harami,
    morning_star_island_reversal,
    neutral_engulfing,
    outside_three_black,
    outside_three_black_like,
    piercing_line,
    rebound,
    rising_falling,
    self_rescue_breakout,
    three_red_dadi_dangqian,
    trapped,
    two_crow_gap,
)

PATTERN_REGISTRY = {
    "attack_cost_displayed": attack_cost_displayed.detect,
    "bear_engulfing": bear_engulfing.detect,
    "bull_engulfing": bull_engulfing.detect,
    "morning_star_harami": morning_star_harami.detect,
    "high_hanging_man": high_hanging_man.detect,
    "three_red_dadi_dangqian": three_red_dadi_dangqian.detect,
    "dark_double_star_anye": dark_double_star_anye.detect,
    "gap_under_pressure_reversal": gap_under_pressure_reversal.detect,
    "gap_reversal": gap_reversal.detect,
    "two_crow_gap": two_crow_gap.detect,
    "breakout_double_star": breakout_double_star.detect,
    "evening_star_abandoned": evening_star_abandoned.detect,
    "evening_star_island_reversal": evening_star_island_reversal.detect,
    "morning_star_island_reversal": morning_star_island_reversal.detect,
    "merged_doji": merged_doji.detect,
    "outside_three_black": outside_three_black.detect,
    "outside_three_black_like": outside_three_black_like.detect,
    "piercing_line": piercing_line.detect,
    "neutral_engulfing": neutral_engulfing.detect,
    "embracing": embracing.detect,
    "meeting": meeting.detect,
    "rebound": rebound.detect,
    "trapped": trapped.detect,
    "biting": biting.detect,
    "rising_falling": rising_falling.detect,
    "gap_fill_up": gap_fill_up.detect,
    "gap_fill_down": gap_fill_down.detect,
    # INTRO concepts impl (2026-06-05) — 入門 §34 自救型突破
    "self_rescue_breakout": self_rescue_breakout.detect,
}

__all__ = ["PATTERN_REGISTRY"] + list(PATTERN_REGISTRY.keys())
