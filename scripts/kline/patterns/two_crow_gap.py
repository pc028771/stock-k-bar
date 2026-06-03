"""雙鴉躍空 — bear, exit.

Course source: 第 09 篇《雙鴉躍空》(13041D9897DBD12852724CAD0D994486)
Cross-course definition: PATTERN_INVENTORY P10.

§C13 明日 K 線補充 (INVENTORY §C13, 第 34、36 篇):
  在大盤 K 上偵測雙鴉躍空時，需額外注意「當下是否由權值股單一主導」。

  課程第 34 篇明示：「大盤走勢受個別權值股（如台積電）主導時，雙鴉躍空可能
  是主力刻意壓盤或分批出貨所形成的短暫型態，而非真實的整體市場轉弱訊號。」

  課程第 36 篇（得利影 6144 案例）補充：「主力自演的場景下，看似看空的 K 線
  型態可能只是在為後續拉抬製造恐慌買點，需搭配當時大盤背景綜合判斷。」

  實作規範（INVENTORY §C13 明示「不影響 detect 主邏輯，僅 docstring 補充」）：
  - detect() 邏輯維持不變（已包含 overhead_supply 條件）
  - 呼叫方（playbook / advisor）在大盤 K 使用此 pattern 時，應注入
    `context_overrides` 確認「無單一權值股主導」；個股 K 不受此限制
  - 跨市場 filter 屬於外部資料融合，不在本模組實作

Cross-market filter reminder (cross-market analysis 不在本 pattern 層):
  caller_note = 「大盤 K 使用時：確認非權值股單一主導（如台積電佔比 > 50%）」
"""
from __future__ import annotations

import pandas as pd


def detect(df: pd.DataFrame) -> pd.Series:
    """雙鴉躍空 — 遇壓 + 紅 K + 雙黑鴉 + D-0 開低跳空.

    Conditions (PATTERN_INVENTORY P10):
      1. 遇壓背景 (overhead_supply_layer > 0 on D-3)
      2. D-3: 紅 K (open > prev_close — 開高)
      3. D-2, D-1: 兩根黑 K (含短黑、十字線)
      4. D-0: open < prev_low (開盤跳空向下)
    """
    g = df.groupby("ticker")
    overhead_d3 = g["overhead_supply_layer"].shift(3).fillna(0)
    overhead_ok = overhead_d3 > 0

    open_d3 = g["open"].shift(3)
    close_d3 = g["close"].shift(3)
    close_d4 = g["close"].shift(4)
    d3_red_open_high = (close_d3 > open_d3) & (open_d3 > close_d4)

    open_d2 = g["open"].shift(2)
    close_d2 = g["close"].shift(2)
    open_d1 = g["open"].shift(1)
    close_d1 = g["close"].shift(1)
    d2_black = close_d2 < open_d2
    d1_black = close_d1 < open_d1

    prev_low_v = g["low"].shift(1)
    d0_gap_down_open = df["open"] < prev_low_v

    return (overhead_ok & d3_red_open_high & d2_black & d1_black & d0_gap_down_open).fillna(False)
