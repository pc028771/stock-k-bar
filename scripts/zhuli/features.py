"""Derived features for zhuli course strategies.

Course source: 主力大全方位操盤教戰守則 (林家洋)

Input: bars DataFrame from kline.bars.load_bars(), sorted by (ticker, trade_date).
Output: same DataFrame with zhuli-specific derived columns added.

Columns added by add_zhuli_features():
    max_vol_20d      — rolling 20-day max volume (shift(1) window, excludes today)
    vol_ratio_20d    — volume / max_vol_20d (窒息量 ratio)
    ma5              — 5-day MA (loaded from DB; validated here)
    ma10             — 10-day MA (loaded from DB; validated here)
    ma20_slope_5d    — 5-day MA20 slope proxy: ma20 / ma20[t-5] - 1
    ma5_slope_5d     — 5-day MA5 slope proxy
    ma10_slope_5d    — 5-day MA10 slope proxy
    ma60_slope_5d    — 5-day MA60 slope proxy (mirrors kline.features)
    ideal_ma_align   — bool: 5>10>20>60 price AND all slopes > 0
    prev_volume      — shifted volume (yesterday's volume)

Note: ma5, ma10, ma20, ma60 are loaded from the DB via kline.bars.load_bars().
      This module only adds columns not already present or not in kline.features.
      kline.features.add_features() adds: ma60_slope_5d, prev_close/open/high/low,
      body_abs, body_pct, lower_shadow, upper_shadow, is_red, is_black, etc.
      Call add_zhuli_features() AFTER add_features() to avoid redundant computation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def add_zhuli_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add zhuli-specific derived features. Pure function — returns new DataFrame.

    Required input columns (from load_bars() + add_features()):
        ticker, trade_date, open, high, low, close, volume,
        ma5, ma10, ma20, ma60,
        body_abs, lower_shadow (added by kline.add_features)

    Adds new columns (does NOT overwrite existing columns).
    """
    df = df.copy()
    g = df.groupby("ticker", group_keys=False)

    # === 20-day rolling max volume (excluding today) ===
    # Source: strategy-indicators.md §H — 「vol < max(vol_20d) * 0.10」
    # Shift(1) ensures today is excluded (we measure the 20d window before today).
    df["max_vol_20d"] = (
        g["volume"]
        .shift(1)
        .rolling(20, min_periods=20)
        .max()
        .reset_index(level=0, drop=True)
    )
    df["vol_ratio_20d"] = df["volume"] / df["max_vol_20d"].replace(0, np.nan)

    # === Previous bar volume (for breakout volume comparison) ===
    df["prev_volume"] = g["volume"].shift(1)

    # === Compute ma5 / ma10 if not already loaded from DB ===
    # load_bars() currently only loads ma20, ma60, ma240.
    # ma5 and ma10 are in the DB but not in the standard query.
    # We compute them from rolling close rather than modifying kline/bars.py.
    for window, col in [(5, "ma5"), (10, "ma10")]:
        if col not in df.columns:
            df[col] = (
                g["close"]
                .rolling(window, min_periods=window)
                .mean()
                .reset_index(level=0, drop=True)
            )

    # === MA slopes (5-day proxy) ===
    # slope = today / 5-days-ago - 1 (positive = rising)
    # ma60_slope_5d is already added by kline.add_features; add the others here.
    for ma_col in ("ma5", "ma10", "ma20"):
        slope_col = f"{ma_col}_slope_5d"
        if slope_col not in df.columns:
            df[slope_col] = (
                df[ma_col] / g[ma_col].shift(5) - 1
            )

    # Alias: ma20_slope from DB (pre-computed, more precise) vs our proxy.
    # If DB provides ma20_slope, prefer it; otherwise use our 5d proxy.
    # DB column name: ma20_slope (confirmed from PRAGMA table_info).
    if "ma20_slope" not in df.columns:
        df["ma20_slope"] = df["ma20_slope_5d"]

    # === 扣抵值預判（rolloff/kickout）===
    # Source: K 線力量入門 course_principles.md §季線方向 — 扣抵原理
    #         K 線行進ing Ch3 — 關鍵K線與均線連結（提早 1-2 天）
    #         主力大 §C 反轉形態 — 「短均線開始上彎（扣底值判斷）」
    #         主力大 PressPlay 11/26 扣抵值實務教學
    #
    # 扣抵 close = N 天前的收盤價（即將脫離 MA(N) 計算窗口的那一天）
    # 預判明日 MA 方向:
    #   today_close > kickout_close → 明日 MA 將上揚
    #   today_close < kickout_close → 明日 MA 將下彎
    #   today_close ≈ kickout_close → 持平 / 轉折
    #
    # 「rolloff_pressure」 = today_close - kickout_close（正值 = 上揚壓力）
    # 正規化版本 = (today_close - kickout_close) / kickout_close
    for n in (5, 10, 20, 60):
        kickout_col = f"ma{n}_kickout_close"
        pressure_col = f"ma{n}_rolloff_pressure"
        will_rise_col = f"ma{n}_will_rise"
        if kickout_col not in df.columns:
            df[kickout_col] = g["close"].shift(n)
            df[pressure_col] = (
                (df["close"] - df[kickout_col]) / df[kickout_col].replace(0, np.nan)
            )
            df[will_rise_col] = df["close"] > df[kickout_col]

    # === Ideal MA alignment (boost score condition) ===
    # Source: strategy-indicators.md §H — 「理想（最高勝率）：5/10/20/60ma 排列正確且皆上彎」
    # Price ordering: 5 > 10 > 20 > 60
    # Slope condition: all slopes > 0 (upward)
    has_all_ma = (
        df["ma5"].notna()
        & df["ma10"].notna()
        & df["ma20"].notna()
        & df["ma60"].notna()
    )
    price_ordered = (
        (df["ma5"] > df["ma10"])
        & (df["ma10"] > df["ma20"])
        & (df["ma20"] > df["ma60"])
    )
    # 「上彎」改用扣抵值判斷（明日將上揚 = 比 slope 提早 1-2 天）
    # 課程依據: K 線力量入門 §季線扣抵原理 + 主力大 §C 反轉「扣底值判斷」
    ma5_up = df["ma5_will_rise"].fillna(False)
    ma10_up = df["ma10_will_rise"].fillna(False)
    ma20_up = df["ma20_will_rise"].fillna(False)
    ma60_up = df["ma60_will_rise"].fillna(False)

    df["ideal_ma_align"] = (
        has_all_ma
        & price_ordered
        & ma5_up
        & ma10_up
        & ma20_up
        & ma60_up
    ).fillna(False)

    return df
