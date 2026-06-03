"""型態壓力 (pattern pressure) scoring factor.

Course source:
  - 明日 K 線 INVENTORY.md §C09 (第 17、29 篇)
  - 第 17 篇: 「頭部成型三要件 — 頸線跌破 = 頭部壓力確認」
  - 第 29 篇: 「反彈遇頸線不過 = 頭部型態的阻礙」
  - 入門 §成本原理: 「層層套牢 = 多層壓力」

Scoring logic (INVENTORY §C09, all additive):
  +1  if 頸線剛跌破（下行，在頸線下方收盤）
  +1  if 反彈遇頸線不過（回到頸線但收盤未突破）
  +1  if 連層套牢 — 每多一層 overhead_supply 壓力 +1（上限 +3）

Note: 型態壓力是「bear side」因子，得分越高表示越多壓力阻力。
呼叫方可乘以 -1 轉換為加入 bear 計分。

Required df columns (all added by features.add_features):
  close, prev_close, overhead_supply_layer, ticker.

Neckline note:
  「頸線」在既有 exit/ma60_neckline.py 定義為 MA60 收盤跌破。
  本因子採用相同代理：close < ma60 (收盤跌破 MA60 = 頸線壓力)。
  更精確的頸線需要型態學 08「騙線」/ 15「反轉型態」的頸線定義，
  此處以 MA60 作為最廣泛使用的動態頸線代理。
  [STUB-NEED-USER]: 若 user 希望用靜態頸線（先高後低），需另建頸線 detect。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def score(df: pd.DataFrame) -> pd.Series:
    """Returns float Series in range [0, +5].

    +1  just_broke_neckline (收盤跌破 MA60 → 頸線壓力確認)
    +1  rebound_at_neckline (反彈觸及 MA60 但收盤未穿越 — 壓力依然)
    +1/+2/+3  overhead_supply_layers (連層套牢，上限 +3)

    All components are non-negative (pressure = bear-side resistance).
    """
    s = pd.Series(0.0, index=df.index)

    # --- +1: 頸線剛跌破 ---
    # Proxy: 今日收盤 < MA60 AND 前日收盤 ≥ MA60（剛跌破）
    # Course: INVENTORY §C09 / 第 17 篇「頸線跌破 = 頭部壓力」
    prev_close = df.groupby("ticker")["close"].shift(1)
    just_broke = (
        (df["close"] < df["ma60"])
        & (prev_close >= df["ma60"])
    ).fillna(False)
    s += just_broke.astype(float)

    # --- +1: 反彈遇頸線不過 ---
    # Proxy: 今日 high >= MA60 AND 今日 close < MA60（觸碰但未穿越）
    # Course: INVENTORY §C09 / 第 29 篇「反彈遇頸線不過」
    rebound_at_neckline = (
        (df["high"] >= df["ma60"])
        & (df["close"] < df["ma60"])
    ).fillna(False)
    s += rebound_at_neckline.astype(float)

    # --- +1/+2/+3: 連層套牢 ---
    # 每多一層 overhead_supply_layer 加一分，上限 3。
    # Course: INVENTORY §C09 / 入門 成本原理「層層套牢」
    supply_layers = df["overhead_supply_layer"].fillna(0).clip(0, 3)
    s += supply_layers

    return s.fillna(0.0)
