"""合併十字線 (merged_doji) — bull, entry candidate.

Course source:
  - 明日 K 線 第 24 篇 / E9A6F935298C7C5C2E269AA952AA1BB2
  - INVENTORY §A01 merged_doji（識別規則全部出自課程明示）
  - Playbook: scripts/kline/scenarios/playbooks/merged_doji_attack.yaml (B03)

Signal Class: entry candidate（剛創新高位置 + 明日攻擊預期）
K-bar 數量: 2 根合併

識別規則（老師明示，INVENTORY §A01）:
  1. 位置條件：今日或前 1~2 日為剛創新高（盤中或收盤觸及 prior_high_60）
     - 課程明示「盤中有過攻擊的力量」也算（看上影線創新高 = high >= prior_high_60）
     - 使用 is_just_broke_high_intraday（features.py C04b），以 high 取代 close 判斷
     - 原 close-based 版本改為 intraday 版，避免遺漏上影線創新高的案例（MD-02 5443 均豪）
  2. K 棒組成：前根有上影線、今根有下影線（力量最強組合）
     - 反向（前根下影線後根上影線）退化為「上影線單獨判斷」，不觸發此 pattern
  3. 合併條件：兩根合併後形成「長十字線」
     merged_open  = prev_open
     merged_close = close（今日收盤）
     merged_high  = max(prev_high, high)
     merged_low   = min(prev_low, low)
     判定 = is_doji(merged_open, merged_close, merged_high, merged_low)
  4. 方向限制：僅「先上影線、後下影線」觸發（INVENTORY §A01 明示最強）

不適用（老師明示）:
  - 兩根不在剛創新高位置 → 沒有意義

Output columns (appended to df via detect_with_metadata):
  merged_doji         (bool)   — pattern 觸發
  merged_doji_high    (float)  — 合併後高點 merged_high
  merged_doji_low     (float)  — 合併後低點 merged_low

[STUB-NEED-USER] 十字線判斷門檻：
  is_doji 使用 |merged_open - merged_close| / (merged_high - merged_low) <= doji_body_ratio
  doji_body_ratio = 0.25 為工程代理值 — 課程未明示具體比例，需 user 確認

Cross-course: 是（明日 K 線課程 + K 線力量判斷入門均適用）
"""
from __future__ import annotations

import numpy as np
import pandas as pd


from ..course_proxy_constants import (
    MERGED_DOJI_BODY_RATIO,
    MERGED_DOJI_SHADOW_MIN_RATIO,
)


def _is_doji_merged(
    merged_open: pd.Series,
    merged_close: pd.Series,
    merged_high: pd.Series,
    merged_low: pd.Series,
) -> pd.Series:
    """判定合併後兩根 K 線是否形成十字線（長十字線）。

    條件：
      1. |merged_open - merged_close| / merged_range <= MERGED_DOJI_BODY_RATIO
      2. 上影線長度 (merged_high - max(merged_open, merged_close)) >= SHADOW_MIN_RATIO * merged_range
      3. 下影線長度 (min(merged_open, merged_close) - merged_low) >= SHADOW_MIN_RATIO * merged_range

    [STUB-NEED-USER] MERGED_DOJI_BODY_RATIO / MERGED_DOJI_SHADOW_MIN_RATIO 數字需 user 確認。
    """
    merged_range = (merged_high - merged_low).replace(0, np.nan)
    body = (merged_open - merged_close).abs()
    body_ratio = body / merged_range

    upper_body = pd.concat([merged_open, merged_close], axis=1).max(axis=1)
    lower_body = pd.concat([merged_open, merged_close], axis=1).min(axis=1)
    upper_shadow = merged_high - upper_body
    lower_shadow = lower_body - merged_low

    doji_body_ok = body_ratio <= MERGED_DOJI_BODY_RATIO
    upper_shadow_ok = (upper_shadow / merged_range) >= MERGED_DOJI_SHADOW_MIN_RATIO
    lower_shadow_ok = (lower_shadow / merged_range) >= MERGED_DOJI_SHADOW_MIN_RATIO

    return (doji_body_ok & upper_shadow_ok & lower_shadow_ok).fillna(False)


def detect(df: pd.DataFrame) -> pd.Series:
    """合併十字線 — 觸發條件純函式版本（僅回傳 bool Series）。

    Args:
        df: 含 ticker, open, high, low, close, prior_high_60 等欄位的 DataFrame
            通常已透過 add_features() 加工（建議帶入 is_just_broke_high_intraday）。

    Returns:
        pd.Series[bool]: 合併十字線觸發的 K 棒（今日為第二根 K）

    Conditions (INVENTORY §A01):
      1. 位置條件：今日、前 1 日或前 2 日有盤中創新高（high >= prior_high_60）
         - 課程原文：「盤中有過攻擊的力量」「創新高的上影線也是攻擊過的意義」
         - 使用 is_just_broke_high_intraday（features.py C04b）；若欄位不存在，
           fallback 到 prev_high >= prior_high_60_prev OR close > prior_high_60
         - 原 close-based 版（prev_close > prior_high_60_prev OR close > prior_high_60）
           改為 intraday 版，以修正 MD-02 5443 均豪 2024-06-25 MISS（上影線創新高日）
      2. K 棒方向組合（最強）：前根上影線為主 + 今根下影線為主
         - 前根：upper_shadow_prev > lower_shadow_prev（上影線較長）
         - 今根：lower_shadow_today > upper_shadow_today（下影線較長）
      3. 合併後為十字線：_is_doji_merged(merged_{open,close,high,low})
    """
    g = df.groupby("ticker")

    prev_open = g["open"].shift(1)
    prev_high = g["high"].shift(1)
    prev_low = g["low"].shift(1)
    prev_close = g["close"].shift(1)
    prior_high_60_prev = g["prior_high_60"].shift(1)

    # --- 條件 1: 剛創新高位置（盤中版 C04b）---
    # 使用 features.py C04b 的 is_just_broke_high_intraday（如有）；
    # 否則 fallback 到盤中版本計算
    if "is_just_broke_high_intraday" in df.columns:
        just_broke_high = df["is_just_broke_high_intraday"].fillna(False)
    else:
        # Fallback: 計算 intraday 版本（不需 features.py 已 run）
        prev2_high = g["high"].shift(2)
        prior_high_60_prev2 = g["prior_high_60"].shift(2)
        just_broke_high = (
            (df["high"] >= df["prior_high_60"])
            | (prev_high >= prior_high_60_prev)
            | (prev2_high >= prior_high_60_prev2)
        ).fillna(False)

    # --- 條件 2: 影線組合 — 前根上影線 > 下影線（前根以上影線為主） ---
    prev_body_top = pd.concat([prev_open, prev_close], axis=1).max(axis=1)
    prev_body_bot = pd.concat([prev_open, prev_close], axis=1).min(axis=1)
    prev_upper_shadow = prev_high - prev_body_top
    prev_lower_shadow = prev_body_bot - prev_low
    prev_upper_dominant = prev_upper_shadow > prev_lower_shadow

    # 今根下影線 > 上影線（今根以下影線為主）
    today_body_top = pd.concat([df["open"], df["close"]], axis=1).max(axis=1)
    today_body_bot = pd.concat([df["open"], df["close"]], axis=1).min(axis=1)
    today_upper_shadow = df["high"] - today_body_top
    today_lower_shadow = today_body_bot - df["low"]
    today_lower_dominant = today_lower_shadow > today_upper_shadow

    # --- 條件 3: 合併後為十字線 ---
    merged_open = prev_open
    merged_close = df["close"]
    merged_high = pd.concat([prev_high, df["high"]], axis=1).max(axis=1)
    merged_low = pd.concat([prev_low, df["low"]], axis=1).min(axis=1)

    is_merged_doji = _is_doji_merged(merged_open, merged_close, merged_high, merged_low)

    return (just_broke_high & prev_upper_dominant & today_lower_dominant & is_merged_doji).fillna(False)


def detect_with_metadata(df: pd.DataFrame) -> pd.DataFrame:
    """合併十字線 detect + merged_high / merged_low 輸出（供 B03 playbook 使用）。

    B03 playbook (merged_doji_attack.yaml) 需要 merged_high / merged_low
    來判斷隔日攻擊方向。本函式將這兩個值附在原 df 上回傳。

    Returns:
        原 df 加三欄：
          merged_doji       (bool)
          merged_doji_high  (float) — 合併十字線 merged_high，其他列為 NaN
          merged_doji_low   (float) — 合併十字線 merged_low，其他列為 NaN
    """
    g = df.groupby("ticker")
    prev_high = g["high"].shift(1)
    prev_low = g["low"].shift(1)

    signal = detect(df)
    merged_high = pd.concat([prev_high, df["high"]], axis=1).max(axis=1).where(signal, other=float("nan"))
    merged_low = pd.concat([prev_low, df["low"]], axis=1).min(axis=1).where(signal, other=float("nan"))

    out = df.copy()
    out["merged_doji"] = signal
    out["merged_doji_high"] = merged_high
    out["merged_doji_low"] = merged_low
    return out
