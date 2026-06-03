"""中樞型態 (zhongshu_pattern) — 上升中樞 / 下降中樞 detect.

Course source:
  - 明日 K 線 INVENTORY.md §C11 (第 02、21、41 篇)
  - 第 02 篇: 「對抗近因偏誤 — 中樞型態中勿過度解讀單一 K 棒」
  - 第 21 篇: 「中樞型態 = 整理區間，突破前等待」
  - 第 41 篇: 「上升中樞 vs 下降中樞 的識別方式」

Definition (INVENTORY §C11):
  上升中樞 (rising_zhongshu):
    - 前段：有明確的紅 K 拉抬（is_just_broke_high 或 attack_intensity ≥ 1）
    - 中間 N 日（3 < N < 60）：price 在整理區間內，未跌破前段紅 K 低點
    - 今日尚未突破也未跌破 → 中樞進行中

  下降中樞 (falling_zhongshu):
    - 前段：有明確的黑 K 下跌（close < prior_low_60 or is_in_breakdown_pattern）
    - 中間 N 日：price 在整理區間內，未收復前段黑 K 高點
    - 今日尚未突破也未跌破 → 中樞進行中

「明日 K 線」用法：
  偵測進入中樞狀態 → 標記「等待突破/跌破」context
  不提供 entry/exit 訊號本身，是 playbook 的前提條件。

Proxy limitation:
  「前段拉抬」的精確起點需要結構分析；我們以「過去 ZHONGSHU_LOOKBACK 日內
  曾出現 attack_intensity ≥ 1 且 is_just_broke_high」作為代理。
  「中間整理」以「今日 close 在 zhongshu_high/low 區間內」作為代理。

[STUB-NEED-USER]: N 的精確定義（3 < N < 60）— 老師只說「不要太短也不要太長」，
  工程代理上限 ZHONGSHU_MAX_DAYS = 30，下限 ZHONGSHU_MIN_DAYS = 3。

Required df columns (from features.add_features):
  close, high, low, prev_high, prev_low, prior_high_60, prior_low_60,
  attack_intensity, is_just_broke_high, is_in_breakdown_pattern, ticker.

Output: pd.Series[bool] — True = 中樞型態進行中（等待突破/跌破）
"""
from __future__ import annotations

import pandas as pd


# [STUB-NEED-USER] 中樞整理天數範圍（課程說「不太長不太短」，無數字）
ZHONGSHU_MIN_DAYS: int = 3   # 最少 3 根 K 才算整理
ZHONGSHU_MAX_DAYS: int = 30  # 超過 30 天視為長期盤整，非中樞型態


def detect_rising(df: pd.DataFrame) -> pd.Series:
    """上升中樞 — 前段拉抬後進入整理，等待突破.

    Conditions:
      1. 過去 ZHONGSHU_MAX_DAYS 日內曾出現 attack_intensity ≥ 1（前段拉抬發生過）
      2. 今日 close ≤ zhongshu_high（=過去 ZHONGSHU_MAX_DAYS 日最高 close — 未新突破）
      3. 今日 close ≥ zhongshu_low（=過去 ZHONGSHU_MAX_DAYS 日最低 close — 未跌破）
      4. 過去 ZHONGSHU_MIN_DAYS 日到 ZHONGSHU_MAX_DAYS 日內 close 維持在此區間

    Returns pd.Series[bool]: 上升中樞進行中的 K 棒
    """
    g = df.groupby("ticker")

    # Condition 1: 前段拉抬存在（過去 MAX 日有攻擊）
    attack_max = (
        df["attack_intensity"]
        .groupby(df["ticker"])
        .rolling(ZHONGSHU_MAX_DAYS, min_periods=1)
        .max()
        .reset_index(level=0, drop=True)
    )
    had_attack = attack_max >= 1

    # 整理區間（過去 MAX 日的 close 高低）
    zhongshu_high = g["close"].transform(
        lambda s: s.shift(1).rolling(ZHONGSHU_MAX_DAYS, min_periods=ZHONGSHU_MIN_DAYS).max()
    )
    zhongshu_low = g["close"].transform(
        lambda s: s.shift(1).rolling(ZHONGSHU_MAX_DAYS, min_periods=ZHONGSHU_MIN_DAYS).min()
    )

    # Condition 2+3: 今日 close 在整理區間內（不突破、不跌破）
    in_range = (
        (df["close"] <= zhongshu_high)
        & (df["close"] >= zhongshu_low)
        & zhongshu_high.notna()
    )

    # Condition 4: 整理寬度不過大（上升中樞理應比較緊密）
    # Proxy: high/low range ≤ 20% of zhongshu_high
    range_ok = (
        (zhongshu_high - zhongshu_low) / zhongshu_high.replace(0, float("nan"))
    ).fillna(1.0) <= 0.20

    return (had_attack & in_range & range_ok).fillna(False)


def detect_falling(df: pd.DataFrame) -> pd.Series:
    """下降中樞 — 前段下跌後進入整理，等待跌破.

    Conditions (symmetric with rising):
      1. 過去 ZHONGSHU_MAX_DAYS 日內有破底型態（is_in_breakdown_pattern 或 close < prior_low_60）
      2. 今日 close ≤ zhongshu_high（未收復前段高點）
      3. 今日 close ≥ zhongshu_low（尚未繼續跌破）
      4. 整理區間合理（range ≤ 20%）

    Returns pd.Series[bool]: 下降中樞進行中的 K 棒
    """
    g = df.groupby("ticker")

    # Condition 1: 前段下跌確認（破底型態最近存在）
    breakdown_recent = (
        df["is_in_breakdown_pattern"]
        .fillna(False)
        .astype(int)
        .groupby(df["ticker"])
        .rolling(ZHONGSHU_MAX_DAYS, min_periods=1)
        .max()
        .reset_index(level=0, drop=True)
        > 0
    )

    # 整理區間
    zhongshu_high = g["close"].transform(
        lambda s: s.shift(1).rolling(ZHONGSHU_MAX_DAYS, min_periods=ZHONGSHU_MIN_DAYS).max()
    )
    zhongshu_low = g["close"].transform(
        lambda s: s.shift(1).rolling(ZHONGSHU_MAX_DAYS, min_periods=ZHONGSHU_MIN_DAYS).min()
    )

    in_range = (
        (df["close"] <= zhongshu_high)
        & (df["close"] >= zhongshu_low)
        & zhongshu_high.notna()
    )

    range_ok = (
        (zhongshu_high - zhongshu_low) / zhongshu_high.replace(0, float("nan"))
    ).fillna(1.0) <= 0.20

    return (breakdown_recent & in_range & range_ok).fillna(False)


def detect(df: pd.DataFrame) -> pd.Series:
    """中樞型態 — 上升或下降中樞（任一進行中）.

    Returns pd.Series[bool]: 中樞型態進行中（等待突破/跌破 context）
    """
    return (detect_rising(df) | detect_falling(df)).fillna(False)
