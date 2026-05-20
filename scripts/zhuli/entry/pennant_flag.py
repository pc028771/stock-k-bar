"""B 旗形 entry signal — 主力大 Ch4-2.

Course source: strategy-indicators.md §B (Ch4-2 line 9-216)

Logic (今日 = 旗形完成第三天):
    t-2: 旗杆 — 紅 K (close > open)，上影不過長
    t-1: 旗子第 1 根 — close > ma5, volume < pole_volume,
         close > pole 的 (low+close)/2 mid
    t   : 旗子第 2 根 — 同上條件

Output:
    ticker, signal_date (= t 第三天), close,
    pole_date, pole_close, pole_mid, pole_volume,
    flag1_close, flag1_volume, flag2_close, flag2_volume,
    ma5, stop_loss (= ma5_close_break), entry_note
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from zhuli.config import PennantFlagConfig


def detect(
    df: pd.DataFrame,
    cfg: Optional[PennantFlagConfig] = None,
) -> pd.DataFrame:
    if cfg is None:
        cfg = PennantFlagConfig()

    df = df.copy()
    g = df.groupby("ticker", group_keys=False)

    # Shifted columns for t-1 and t-2
    df["flag1_close"] = g["close"].shift(1)
    df["flag1_open"] = g["open"].shift(1)
    df["flag1_volume"] = g["volume"].shift(1)
    df["flag1_ma5"] = g["ma5"].shift(1)
    df["pole_close"] = g["close"].shift(2)
    df["pole_open"] = g["open"].shift(2)
    df["pole_high"] = g["high"].shift(2)
    df["pole_low"] = g["low"].shift(2)
    df["pole_volume"] = g["volume"].shift(2)
    # pole mid = (low + close)/2 (旗杆有色實體的中段)
    df["pole_mid"] = (df["pole_low"] + df["pole_close"]) / 2
    # pole 實體 + 上影
    df["pole_body"] = (df["pole_close"] - df["pole_open"]).abs()
    df["pole_upper_shadow"] = df["pole_high"] - df[["pole_open", "pole_close"]].max(axis=1)

    mask = pd.Series(True, index=df.index)

    # 1. 旗杆紅 K
    if cfg.require_pole_red:
        mask &= df["pole_close"] > df["pole_open"]

    # 2. 旗杆上影不過長 (上影 / 實體 ≤ pole_max_upper_shadow_ratio)
    pole_shadow_ratio = df["pole_upper_shadow"] / df["pole_body"].replace(0, np.nan)
    mask &= pole_shadow_ratio.fillna(0) <= cfg.pole_max_upper_shadow_ratio

    # 3. 旗子兩根 close > ma5
    if cfg.require_consolidation_close_above_ma5:
        mask &= df["flag1_close"] > df["flag1_ma5"]
        mask &= df["close"] > df["ma5"]

    # 4. 旗子兩根 volume < pole_volume (量縮)
    if cfg.require_consolidation_volume_below_pole:
        mask &= df["flag1_volume"] < df["pole_volume"]
        mask &= df["volume"] < df["pole_volume"]

    # 5. 旗子兩根「下影線」在旗杆中段以上 (spec 明示 = low 不是 close)
    # Source: strategy-indicators.md §B 「兩根的下影線在旗杆 K 棒中間以上」
    if cfg.require_consolidation_above_pole_mid:
        df["flag1_low"] = g["low"].shift(1)
        mask &= df["flag1_low"] > df["pole_mid"]
        mask &= df["low"] > df["pole_mid"]

    # Liquidity
    if "vol_ma20" in df.columns:
        mask &= df["vol_ma20"].fillna(0) >= cfg.min_avg_volume_20
    mask &= df["close"] >= cfg.min_close
    mask &= df["pole_close"].notna()  # 確保有 t-2 資料

    signals = df[mask].copy()
    if signals.empty:
        return pd.DataFrame(columns=[
            "ticker", "signal_date", "close", "pole_close", "pole_mid",
            "pole_volume", "flag1_close", "flag1_volume",
            "ma5", "stop_loss", "entry_note",
        ])

    # 計算 pole_date (t-2 trade_date)
    signals["pole_date"] = g["trade_date"].shift(2).loc[signals.index]

    out = pd.DataFrame({
        "ticker": signals["ticker"],
        "signal_date": signals["trade_date"],
        "close": signals["close"],
        "pole_date": signals["pole_date"],
        "pole_close": signals["pole_close"],
        "pole_mid": signals["pole_mid"],
        "pole_volume": signals["pole_volume"],
        "flag1_close": signals["flag1_close"],
        "flag1_volume": signals["flag1_volume"],
        "flag2_close": signals["close"],
        "flag2_volume": signals["volume"],
        "ma5": signals["ma5"],
        "stop_loss": signals["ma5"],   # 跌破 5ma 停損
    })
    out["entry_note"] = out.apply(
        lambda r: (
            f"旗杆={r['pole_date']} C={r['pole_close']:.2f} mid={r['pole_mid']:.2f}; "
            f"旗子1 C={r['flag1_close']:.2f} v={r['flag1_volume']/1000:.0f}張; "
            f"旗子2 C={r['close']:.2f} v={r['flag2_volume']/1000:.0f}張; "
            f"stop={r['stop_loss']:.2f}(5ma)"
        ),
        axis=1,
    )
    out = out.sort_values("signal_date", ascending=False).reset_index(drop=True)
    return out
