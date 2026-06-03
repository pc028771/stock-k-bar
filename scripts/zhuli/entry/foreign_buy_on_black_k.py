"""外資大買黑 K 連 N 天 entry signal — 老師 6/3 法人籌碼課程教法.

老師原話 (2303 聯電, 6/3 [21:xx]):
  「聯電這邊萬一是大買、然後是買黑K、有沒有...萬一是大買但是它是黑K、
   連兩天的、這個如果明天尾盤我就會開始來看、知道嗎、就開始把它圈起來」

核心邏輯:
  Day -1: 外資淨買 ≥ THRESHOLD + K 線為黑 K (close < open)
  Day  0: 外資淨買 ≥ THRESHOLD + K 線為黑 K
  連 2 天確認 → 升等為「圈起來」、隔天尾盤評估

THRESHOLD 依流動性 tier 自動分:
  小型股 (vol_20d_avg < 5M 張/天):  500 張
  中型股 (5M-50M 張/天):            2000 張
  大型股 (> 50M 張/天):             5000 張
  ※ vol_ma20 單位為「股」，換算：5M 張 = 5e6 * 1000 = 5e9 股
  ※ 台股 vol_ma20 通常是「張」(1000 股單位的)，需依實際資料確認

加分條件 (不過濾、只加欄位):
  - MA10 上方 (主升段中、不是底部)
  - 無破底型態 (型態學 16 — 簡化為：最近 5 日低點不是 60 日最低)

Output columns:
  ticker, signal_date, close, foreign_net_d0, foreign_net_d1,
  vol_ma20, liquidity_tier, threshold,
  above_ma10, not_breakdown,
  streak_days (連幾天滿足、≥ 2 才真正觸發),
  entry_note
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


# ── 流動性 tier 門檻 ──────────────────────────────────────────────────────────

def _get_threshold(vol_ma20: float) -> tuple[int, str]:
    """依 vol_ma20 (股/日) 計算 threshold 與 tier.

    vol_ma20 在 standard_daily_bar 單位為「股」(1 張 = 1000 股).
    邊界 (張/日)：
      小型 < 5,000 張  → threshold 500 張
      中型 < 50,000 張 → threshold 2,000 張
      大型 ≥ 50,000 張 → threshold 5,000 張

    換算 vol_ma20 (股) 成 張：
      5,000 張  = 5,000,000 股
      50,000 張 = 50,000,000 股
    """
    vol_lots = vol_ma20 / 1000  # 股 → 張
    if vol_lots < 5_000:        # < 5000 張/天 = 小型股
        return 500, "小型"
    elif vol_lots < 50_000:     # 5000–50000 張/天 = 中型股
        return 2_000, "中型"
    else:                        # ≥ 50000 張/天 = 大型股
        return 5_000, "大型"


# ── 主偵測函式 ────────────────────────────────────────────────────────────────

def detect(df: pd.DataFrame) -> pd.Series:
    """回傳 bool Series。True = 今天是「連 2 天外資大買黑K」確認日 (Day 0).

    Required df columns:
        ticker, open, close, vol_ma20 (張/日),
        foreign_net (今日外資淨買，張),
        ma10 (十日均線)
        — 前一天資料透過 shift(1) 取得 —

    使用方式: detect(df).iloc[-1] 判斷今天是否觸發。
    """
    df = df.copy()

    # 黑 K = close < open
    df["is_black"] = df["close"] < df["open"]

    # 前一天
    df["prev_foreign_net"] = df["foreign_net"].shift(1)
    df["prev_is_black"] = df["is_black"].shift(1)
    df["vol_ma20_safe"] = df["vol_ma20"].fillna(0)

    # threshold (依流動性, 用當日 vol_ma20)
    thresholds = df["vol_ma20_safe"].apply(lambda v: _get_threshold(v)[0])

    # Day 0: 外資淨買 ≥ threshold + 黑 K
    day0_ok = (df["foreign_net"] >= thresholds) & df["is_black"].fillna(False)

    # Day -1: 外資淨買 ≥ threshold + 黑 K
    day1_ok = (
        df["prev_foreign_net"].fillna(0) >= thresholds
    ) & df["prev_is_black"].fillna(False)

    signal = day0_ok & day1_ok
    return signal.fillna(False)


# ── 全市場掃描 (daily job 使用) ───────────────────────────────────────────────

def detect_batch(
    ticker_dfs: dict[str, pd.DataFrame],
    stock_info: dict[str, dict],
    teacher_sector_map: dict[str, list[str]],
    target_date: str,
) -> list[dict]:
    """對多個 ticker 跑 detect()，回傳命中 hit dict list.

    Args:
        ticker_dfs:         {ticker: df} — df 已含 foreign_net 欄位
        stock_info:         {ticker: {name, industry}}
        teacher_sector_map: {ticker: [族群1, ...]}
        target_date:        目標日期 (str YYYY-MM-DD)

    Returns:
        list of hit dicts, sorted by foreign_net_d0 desc
    """
    hits = []
    for ticker, df in ticker_dfs.items():
        if "foreign_net" not in df.columns:
            continue
        if len(df) < 3:
            continue
        try:
            sig = detect(df)
            if not (hasattr(sig, "iloc") and sig.iloc[-1]):
                continue

            last = df.iloc[-1]
            prev = df.iloc[-2]

            vol_ma20 = float(last.get("vol_ma20") or 0)
            threshold, tier = _get_threshold(vol_ma20)
            foreign_net_d0 = float(last.get("foreign_net") or 0)
            foreign_net_d1 = float(prev.get("foreign_net") or 0)
            close = float(last.get("close") or 0)
            ma10 = float(last.get("ma10") or 0) if pd.notna(last.get("ma10")) else None
            above_ma10 = bool(ma10 and close > ma10)

            # 破底判斷 (簡化：最近 5 日低點不是 60 日新低)
            try:
                recent_low = df["low"].iloc[-5:].min()
                hist_low_60 = df["low"].iloc[-60:].min()
                not_breakdown = recent_low > hist_low_60 * 1.005  # 容忍 0.5%
            except Exception:
                not_breakdown = True

            info = stock_info.get(ticker, {"name": "", "industry": ""})
            teacher_sectors = teacher_sector_map.get(ticker, [])

            # streak (連幾天滿足)
            streak = _calc_streak(df, threshold)

            entry_note = (
                f"連{streak}天外資大買黑K ({tier}股門檻:{threshold}張); "
                f"D0={foreign_net_d0:+.0f}張 D-1={foreign_net_d1:+.0f}張; "
                f"尾盤評估 (老師教法: 隔天盤前把它圈起來)"
            )

            dist_ma10 = round((close - ma10) / ma10 * 100, 1) if ma10 else None

            hits.append({
                "ticker": ticker,
                "name": info.get("name", ""),
                "industry": info.get("industry", ""),
                "teacher_sectors": teacher_sectors,
                "close": close,
                "foreign_net_d0": foreign_net_d0,
                "foreign_net_d1": foreign_net_d1,
                "vol_ma20": vol_ma20,
                "liquidity_tier": tier,
                "threshold": threshold,
                "above_ma10": above_ma10,
                "not_breakdown": not_breakdown,
                "streak_days": streak,
                "dist_ma10_pct": dist_ma10,
                "entry_note": entry_note,
            })
        except Exception:
            continue

    # Sort: not_breakdown + above_ma10 優先，then by foreign_net_d0 desc
    hits.sort(key=lambda h: (
        not h.get("not_breakdown", False),
        not h.get("above_ma10", False),
        -(h.get("foreign_net_d0") or 0),
    ))
    return hits


def _calc_streak(df: pd.DataFrame, threshold: int) -> int:
    """計算從今天往回連續幾天都滿足外資大買黑K條件."""
    streak = 0
    for i in range(len(df) - 1, -1, -1):
        row = df.iloc[i]
        fn = float(row.get("foreign_net") or 0)
        is_black = float(row.get("close") or 0) < float(row.get("open") or 0)
        if fn >= threshold and is_black:
            streak += 1
        else:
            break
    return streak
