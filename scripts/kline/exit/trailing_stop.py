"""Trailing stop exit signal — 緩慢推升型 + 微弱多方趨勢退化版.

Course source:
  【買點賣點】出場點的各種依據(二),
  【賣壓化解】K線圖的第一個研判要點.
  明日 K 線 INVENTORY.md §C14 (第 05 篇 / 「微弱的多方趨勢」)

> 「前一日低點當作停利點，有過昨高都算攻擊持續」

§C14 微弱多方趨勢退化版 (INVENTORY §C14, 第 05 篇):
  「在無轉折組合可用、股價 K 棒重疊度高的狀態下，採用短期上升趨勢線
  （簡化版：5 日 SMA 跌破）作為最後停利 — 老師明示『不得已才使用』」

  課程原文（第 05 篇）：「微弱的多方趨勢就要用趨勢線來輔助，不然你根本
  找不到一個有意義的 K 棒結構支撐」

  退化規則（`mark_weak_bull`）：
    - 今日 close < 5 日 SMA（ma5 = 5日移動平均）
    - 「不得已才使用」：僅在無 attack_intensity 記錄（= 0）的低動能狀態下套用
    - 日 K 退化版：以 ma5 跌破作為趨勢線跌破的代理

  [STUB-NEED-USER]: 「5 日 SMA」是否就是課程第 05 篇所指的短期趨勢線？
    課程原文使用「趨勢線」而非 MA；ma5 是最常見的短期趨勢線代理。
    若 user 指定不同天數，只需修改 WEAK_BULL_MA_DAYS。

Vectorized implementation: per trade (delineated by entry signals within
each ticker), trailing_low = expanding max of prev_low since entry.

Required df columns: ticker, close, prev_low, (attack_intensity for weak_bull).
"""
from __future__ import annotations

import pandas as pd


# §C14: 微弱多方趨勢退化版 — MA 天數（[STUB-NEED-USER] 課程說「趨勢線」未指定天數）
WEAK_BULL_MA_DAYS: int = 5


def mark(df: pd.DataFrame, entries: pd.Series) -> pd.Series:
    """Returns bool Series. True = close fell below the trailing reference.

    Primary (課程主要停利): 前一日低點當作停利點（trailing prev_low）.
    """
    trade_id = entries.groupby(df["ticker"]).cumsum()
    trade_id = trade_id.where(trade_id > 0)

    # Guard: if no trade ever started, all trade_id values are NaN → groupby
    # on an all-NaN column raises ValueError in pandas. Return all False.
    if trade_id.isna().all():
        return pd.Series(False, index=df.index)

    work = df.assign(_tid=trade_id)
    trailing_low = (
        work.groupby(["ticker", "_tid"])["prev_low"]
            .expanding().max()
            .reset_index(level=[0, 1], drop=True)
            .reindex(df.index)
    )
    return (df["close"] < trailing_low).fillna(False)


def mark_slow_push(df: pd.DataFrame, entries: pd.Series) -> pd.Series:
    """緩慢推升型移動停利 — 入門「出場(二)」+ 入門 §18 移動停利.

    Course quote (入門 出場二):
      「移動停利是一個必備的操作模式、主要用來應對緩慢推升型」

    Definition (緩慢推升型 = 沒有跳空攻擊、沒有漲停鎖住，但 close 持續向上墊高):
      持倉期間維護一個 N 日新高 close (rolling max close during trade)，
      當今日 close < 「N 日內最高 close 的 SLOW_PUSH_RETRACE_PCT 」即停利出場。

    參數選擇 (course-not-stated proxy):
      - 老師「緩慢推升型」明確區分於「跳空 / 長紅」，需要「移動」式停利；
      - 課程無明示具體 % 或 N 日；本實作沿用日 K 退化版：
        N = 持倉以來的 expanding window（從進場日起所有 close 的最高值）
        STOP_PCT = 5%（「緩慢推升」一根長黑通常 4-6%；保留 5% 為中間值）
      - 「移動」= 隨高點推升而上移（expanding max），不是固定價位。

    Required df columns: ticker, close.
    """
    SLOW_PUSH_RETRACE_PCT: float = 0.05  # [STUB-NEED-USER] course-not-stated retrace %

    if entries is None or entries.sum() == 0:
        return pd.Series(False, index=df.index)

    trade_id = entries.groupby(df["ticker"]).cumsum()
    trade_id = trade_id.where(trade_id > 0)
    if trade_id.isna().all():
        return pd.Series(False, index=df.index)

    work = df.assign(_tid=trade_id)
    # expanding max of close within (ticker, trade)
    trailing_high_close = (
        work.groupby(["ticker", "_tid"])["close"]
        .expanding().max()
        .reset_index(level=[0, 1], drop=True)
        .reindex(df.index)
    )
    stop_level = trailing_high_close * (1.0 - SLOW_PUSH_RETRACE_PCT)
    return (df["close"] < stop_level).fillna(False)


def mark_weak_bull(df: pd.DataFrame, entries: pd.Series) -> pd.Series:
    """§C14 微弱多方趨勢退化版停利 — 5日 SMA 跌破（老師明示「不得已才使用」）.

    Course source: INVENTORY §C14 / 第 05 篇「微弱的多方趨勢」
    Course quote: 「微弱的多方趨勢就要用趨勢線來輔助」
    Intended use: 「無轉折組合可用、K 棒重疊度高的狀態下」的最後停利。

    Conditions:
      1. 今日 close < WEAK_BULL_MA_DAYS 日 SMA（短期趨勢線跌破）
      2. 僅在低動能狀態（attack_intensity == 0 over recent bars）下觸發

    Args:
        df: 含 ticker, close, attack_intensity 等欄位
        entries: bool Series (entry signals)

    Returns:
        pd.Series[bool]: True = 微弱多方趨勢線跌破，需停利
    """
    g = df.groupby("ticker")

    # Compute MA5 (using shift(1) to exclude today — backward-looking)
    ma_short = g["close"].transform(
        lambda s: s.shift(1).rolling(WEAK_BULL_MA_DAYS, min_periods=WEAK_BULL_MA_DAYS).mean()
    )

    # 今日 close < MA5 (短期趨勢線跌破)
    below_ma = (df["close"] < ma_short).fillna(False)

    # 低動能背景（attack_intensity == 0 過去 5 日）— 「不得已才使用」的代理條件
    low_momentum = (
        df["attack_intensity"]
        .fillna(0)
        .groupby(df["ticker"])
        .rolling(WEAK_BULL_MA_DAYS, min_periods=1)
        .max()
        .reset_index(level=0, drop=True)
        == 0
    )

    # Only fire after trade entry
    trade_id = entries.groupby(df["ticker"]).cumsum()
    in_trade = trade_id > 0

    return (below_ma & low_momentum & in_trade).fillna(False)
