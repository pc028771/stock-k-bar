"""High-zone long black — bearish signal at top.

Course source: K線力量判斷入門 單一K線(7) 高檔區域的長黑K
            + 事件(二) 攻擊股價並非隨機漫步：高檔長黑、利空逆勢

Course quote (translated 高檔長黑):
  「高檔長黑可同時帶 3 種意義：
     1. 最近的攻擊缺口回補
     2. 長黑包覆創新高紅K
     3. 一根黑K吃下前 5 根
   當 2-3 種同時呈現 = 攻擊結束。」

Source URL:
  https://www.pressplay.cc/project/55DE90EBFBB634BE864F75703AB654DE/articles/C838747B22625440D61F5EA1DD18DFFB

## Pre-2026-05-16 implementation issue (audit follow-up)

The earlier version only checked (a) "high zone" via past-60d high/low ratio
≥ 1.3 (proxy) and (b) long-black body ≥ 4% (proxy). It did NOT verify any of
the three course-stated meanings. Empirical impact: in a 16-trade case
study (2026-Jan~Apr), 5 of the 16 K-line exits fired via this rule and most
were false positives — stocks subsequently rallied 50-200% after we exited.

## Current implementation

For each bar we evaluate three boolean conditions matching the course's
three meanings:

  M1 (缺口回補):  today close < the lower bound of the most recent gap-up
                  within the past GAP_LOOKBACK bars. Gap lower bound = the
                  prev_high on the gap-up day.

  M2 (包覆創新高紅K):
                  prev bar was a red K making a new prior_high_60 high;
                  today is a long-black engulf (today open >= prev_high AND
                  today close <= prev_low — strict engulfing).

  M3 (吃下前 5 根):
                  today close < min(prev 5 closes).

Trigger requires:
  - is_long_black AND
  - at least 2 of (M1, M2, M3) hold AND
  - high-zone context (kept as a guard to suppress noise in
    low-position bars where M1 alone could fire on any gap-down).

§C02 明日 K 線補充 (INVENTORY §C02, 第 03、11 篇):
  加入「開盤跳空 + 盤中回補缺口 → 收盤跌破前日紅 K 低點」的路徑。

  課程原文（第 03 篇）：「開盤跳空向上 + 當日低點回補到前日收盤之下 +
  收盤跌破前日紅 K 低點 → 視為高檔長黑的一種形式」

  日 K 退化版 (M_gap_fill_break):
    open > prev_close (開盤跳空向上 proxy: open > prev_close)
    AND today_low < prev_close (盤中回補缺口: low 跌破前日收盤)
    AND close < prev_low (收盤跌破前日低點)

  This path fires INDEPENDENTLY of the 2-of-3 requirement — it represents
  the course's explicit "intraday gap-fill + close below prev_low" path,
  which is a standalone 高檔長黑 trigger at the daily K level.

Required df columns: ticker, open, high, low, close, prev_high, prev_low, prev_close.
"""
from __future__ import annotations

import pandas as pd

# Proxy: course says "高檔" qualitatively; this 60d-range gate suppresses
# noise. Same value as pre-fix version, retained for backward continuity.
HIGH_ZONE_RANGE_MIN = 1.3
LONG_BLACK_BODY_MIN = 0.04

# Proxy: how far back to look for the most recent attack gap-up.
GAP_LOOKBACK = 20

# Proxy: course says "吃下前 5 根" — exactly 5 closes.
EAT_BARS = 5


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    """Returns bool Series. True = course-faithful 高檔長黑 on that bar."""
    g = df.groupby("ticker")

    # High-zone guard (proxy).
    prior_max_high = (
        g["high"].shift(1).rolling(60, min_periods=60).max().reset_index(level=0, drop=True)
    )
    prior_min_low = (
        g["low"].shift(1).rolling(60, min_periods=60).min().reset_index(level=0, drop=True)
    )
    is_high_zone = (
        prior_max_high / prior_min_low.replace(0, float("nan"))
    ) >= HIGH_ZONE_RANGE_MIN

    # Long-black body (proxy for "長黑").
    body_pct = (df["open"] - df["close"]) / df["open"].replace(0, float("nan"))
    is_long_black = (df["close"] < df["open"]) & (body_pct >= LONG_BLACK_BODY_MIN)

    # === M1: 攻擊缺口回補 ===
    # Find the most recent gap-up's lower bound within GAP_LOOKBACK bars.
    # Gap-up: open > prev_high. Lower bound = prev_high on that day.
    is_gap_up = df["open"] > df["prev_high"]
    gap_lower_bound = df["prev_high"].where(is_gap_up)
    # Forward-fill within ticker, but only within the lookback window.
    last_gap_low = (
        gap_lower_bound.groupby(df["ticker"]).ffill(limit=GAP_LOOKBACK).shift(1)
        .groupby(df["ticker"]).ffill(limit=0)
    )
    M1 = (df["close"] < last_gap_low).fillna(False)

    # === M2: 長黑包覆創新高紅K ===
    # Prev bar: red K (prev_close > prev_open) AND made new 60d high.
    prev_open = g["open"].shift(1)
    prev_close = g["close"].shift(1)
    prev_prior_high_60_at_prev = (
        df["prev_high"].groupby(df["ticker"]).rolling(60, min_periods=60).max()
        .reset_index(level=0, drop=True).shift(1)
    )
    prev_was_red_new_high = (prev_close > prev_open) & (prev_close >= prev_prior_high_60_at_prev)
    # Today engulfs: open ≥ prev_high AND close ≤ prev_low.
    engulfs_prev = (df["open"] >= df["prev_high"]) & (df["close"] <= df["prev_low"])
    M2 = (prev_was_red_new_high & engulfs_prev).fillna(False)

    # === M3: 吃下前 5 根 ===
    # today close < min of prior 5 closes.
    prior_5_close_min = (
        g["close"].shift(1).rolling(EAT_BARS, min_periods=EAT_BARS).min()
        .reset_index(level=0, drop=True)
    )
    M3 = (df["close"] < prior_5_close_min).fillna(False)

    # Course requirement: 2 or 3 of (M1, M2, M3) AND is_long_black AND high_zone.
    meaning_count = M1.astype(int) + M2.astype(int) + M3.astype(int)
    primary = (is_high_zone & is_long_black & (meaning_count >= 2)).fillna(False)

    # === §C02: 開盤跳空 + 盤中回補缺口 + 跌破前日低點 (日 K 退化版) ===
    # Course source: INVENTORY §C02 / 第 03、11 篇
    # Course quote: 「開盤跳空向上 + 當日低點回補到前日收盤之下 + 收盤跌破前日紅 K 低點」
    # 日 K 退化：open > prev_close (跳空) AND low < prev_close (盤中回補) AND close < prev_low
    prev_close_v = g["close"].shift(1)
    M_gap_fill_break = (
        (df["open"] > prev_close_v)          # 開盤跳空（open > prev_close 代理盤中跳空）
        & (df["low"] < prev_close_v)          # 盤中回補缺口（low < prev_close）
        & (df["close"] < df["prev_low"])      # 收盤跌破前日低點
        & is_high_zone                        # 仍在高檔背景下
    ).fillna(False)

    return (primary | M_gap_fill_break).fillna(False)
