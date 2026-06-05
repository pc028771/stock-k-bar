"""攻擊延續性 (attack continuity) scoring factor.

Course source:
  - 明日 K 線 INVENTORY.md §C08 (第 18、32、40 篇)
  - 第 18 篇: 「跳空攻擊之後隔日繼續往上 → 攻擊企圖明確」
  - 第 32 篇: 「攻擊企圖區不可跌回意圖區」
  - 第 40 篇: 「異常放量之後量縮 → 代表沒有賣壓承接，攻擊仍有延續性」

Scoring logic (INVENTORY §C08):
  +1  if 創新高隔日跳空攻擊 (gap-up above prev_high after breakout)
  +1  if 攻擊企圖隔日無回到意圖區 (close stayed above attack_intent_zone_high)
  +1  if 異常放量後量縮（兩天放量情境反轉）— 今日 is_anomalous_volume AND 明日量縮
      (proxy: volume today > vol_thresh AND prev_volume > vol_thresh)
  -1  if 跌回缺口 (intent_zone_break — close fell below attack_intent_zone_high)
  -1  if 攻擊成本跌破 (is_limit_up_locked prev day AND close < prev_close today)

Required df columns (all added by features.add_features):
  prev_high, attack_intent_zone_high, intent_zone_break, is_anomalous_volume,
  is_limit_up_locked, is_just_broke_high, prev_close, close, open, ticker.
"""
from __future__ import annotations

import pandas as pd


def score(df: pd.DataFrame) -> pd.Series:
    """Returns float Series in range roughly [-2, +3].

    Each component adds or subtracts 1 point:
      +1  breakout_gap_attack
      +1  stayed_above_intent_zone
      +1  anomalous_vol_then_shrink
      -1  intent_zone_break
      -1  attack_cost_break
    """
    g = df.groupby("ticker")
    s = pd.Series(0.0, index=df.index)

    # --- +1: 創新高隔日跳空攻擊 ---
    # Condition: prev bar was is_just_broke_high AND today open > prev_high (gap-up).
    # Course source: INVENTORY §C08 / 第 18 篇「跳空攻擊之後隔日繼續往上」
    prev_just_broke_high = g["is_just_broke_high"].shift(1).fillna(False)
    today_gap_up = df["open"] > df["prev_high"]
    breakout_gap_attack = (prev_just_broke_high & today_gap_up).fillna(False)
    s += breakout_gap_attack.astype(float)

    # --- +1: 攻擊企圖隔日未跌回意圖區 ---
    # Condition: close is at or above attack_intent_zone_high (no intent_zone_break).
    # Course source: INVENTORY §C08 / 第 32 篇「攻擊企圖區不可跌回意圖區」
    stayed_above = (~df["intent_zone_break"].fillna(True)).fillna(False)
    # Only award when we're in a meaningful context (had a recent breakout)
    has_intent_zone = df["attack_intent_zone_high"].notna()
    s += (stayed_above & has_intent_zone).astype(float)

    # --- +1: 異常放量後量縮（延續性量能訊號）---
    # Proxy: prev bar anomalous volume AND today's volume < prev_volume (量縮).
    # Course source: INVENTORY §C08 / 第 40 篇「異常放量之後量縮」
    prev_anomalous = g["is_anomalous_volume"].shift(1).fillna(False)
    prev_vol = g["volume"].shift(1)
    vol_shrink_today = df["volume"] < prev_vol
    anomalous_then_shrink = (prev_anomalous & vol_shrink_today).fillna(False)
    s += anomalous_then_shrink.astype(float)

    # --- -1: 跌回攻擊意圖區 ---
    # Course source: INVENTORY §C08 / 第 32 篇「跌回意圖區 = 攻擊延續中斷」
    s -= df["intent_zone_break"].fillna(False).astype(float)

    # --- -1: 攻擊成本跌破 ---
    # Condition: prev day was 漲停鎖住 (attack cost displayed) AND today close < prev close.
    # Course source: INVENTORY §C08 / B02 攻擊成本跌破（第 20、28 篇）
    prev_limit_up_locked = g["is_limit_up_locked"].shift(1).fillna(False)
    attack_cost_break = (prev_limit_up_locked & (df["close"] < df["prev_close"])).fillna(False)
    s -= attack_cost_break.astype(float)

    return s.fillna(0.0)
