"""Ch5 純當沖補強 indicator 實作。

每個 indicator 為純函式、無 side effect、回傳 dict 與 StageTrigger 介面一致：
    {"triggered": bool, "level": str, "reason": str, ...}

所有規則來源於 docs/主力大課程/course_map_from_scripts.md Ch5 區塊、
時間戳對應 5/1 復盤課（B5-1~B5-7 編號）或 5/19 復盤課。
"""
from __future__ import annotations

from datetime import datetime, time as dtime
from typing import Optional

import pandas as pd


# ── 紅線 #9 — 前 5 分鐘 > 5% skip ───────────────────────────────────────────────


def check_first5min_skip(
    k1: pd.DataFrame,
    open_price: Optional[float] = None,
) -> dict:
    """紅線 #9：開盤前 5 分鐘漲幅 > 5% → 整檔今日 skip（一票否決）。

    來源：feedback_short_swing_entry_discipline + 5/19 line 167
    老師原句：「一開始開盤前 5 分鐘如果他已經拉到拉了 5% 以上的，基本上就是有點堵了」

    Args:
        k1: 當日 1 分 K DataFrame、需含 open/close/datetime（或 index 為 datetime）
        open_price: 開盤價（不傳則用 k1 第 1 根 open）

    Returns:
        triggered=True 代表「應 skip 該檔」、level='skip'
        triggered=False 代表「未達 skip 條件」、可繼續評估
    """
    if k1.empty:
        return {"triggered": False, "level": "watch", "reason": "1K 資料為空"}

    open_p = float(open_price) if open_price else float(k1["open"].iloc[0])

    if open_p <= 0:
        return {"triggered": False, "level": "watch", "reason": "開盤價無效"}

    # 取前 5 分鐘高點（前 5 根 1K 的最大 high）
    first_5 = k1.head(5)
    if first_5.empty:
        return {"triggered": False, "level": "watch", "reason": "前 5 分鐘 1K 不足"}

    high_5min = float(first_5["high"].max())
    rise_pct = (high_5min / open_p - 1) * 100

    if rise_pct > 5.0:
        return {
            "triggered": True,
            "level": "skip",
            "reason": f"紅線 #9：前 5 分鐘高 +{rise_pct:.1f}% > 5% → 整檔 skip",
            "rise_pct": rise_pct,
        }

    return {
        "triggered": False,
        "level": "watch",
        "reason": f"前 5 分鐘高 +{rise_pct:.1f}% ≤ 5%",
        "rise_pct": rise_pct,
    }


# ── 均線發散硬性過濾 ─────────────────────────────────────────────────────────


def check_ma_divergence(
    k5: pd.DataFrame,
    divergence_threshold_pct: float = 3.0,
) -> dict:
    """5/10/20 MA 已發散（拉開太遠）→ 硬性過濾。

    來源：5/19 line 306「軍心發散了…不符合我們喜歡的長相」
    course_map Ch5-3「5 分 K 理想條件」: 發散 = 硬性過濾

    判定：max(MA5, MA10, MA20) 與 min(三者) 距離 > threshold_pct → 發散

    Args:
        k5: 當日 5 分 K（需 ≥ 20 根）
        divergence_threshold_pct: 發散門檻 % (預設 3.0)

    Returns:
        triggered=True 代表「已發散、應過濾」、level='filter'
    """
    if k5.empty or len(k5) < 20:
        return {"triggered": False, "level": "watch",
                "reason": f"5K 資料不足（{len(k5)} < 20）"}

    closes = k5["close"]
    ma5  = float(closes.rolling(5,  min_periods=5).mean().iloc[-1])
    ma10 = float(closes.rolling(10, min_periods=10).mean().iloc[-1])
    ma20 = float(closes.rolling(20, min_periods=20).mean().iloc[-1])

    if pd.isna(ma5) or pd.isna(ma10) or pd.isna(ma20):
        return {"triggered": False, "level": "watch",
                "reason": "MA 計算 NaN"}

    mas = [ma5, ma10, ma20]
    spread_pct = (max(mas) - min(mas)) / min(mas) * 100

    if spread_pct > divergence_threshold_pct:
        return {
            "triggered": True,
            "level": "filter",
            "reason": (f"均線發散 {spread_pct:.1f}% > {divergence_threshold_pct}% "
                       f"(MA5={ma5:.2f} / MA10={ma10:.2f} / MA20={ma20:.2f})"),
            "spread_pct": spread_pct,
        }

    return {
        "triggered": False,
        "level": "watch",
        "reason": f"均線糾結 {spread_pct:.1f}% ≤ {divergence_threshold_pct}%",
        "spread_pct": spread_pct,
    }


# ── B5-1 — 2 分 K 3% / 5 分 K 5% 大紅棒必停利 ─────────────────────────────────


def check_b5_1_stop_profit(
    k_recent: pd.DataFrame,
    timeframe: str = "5m",
) -> dict:
    """B5-1：2 分 K 拉 ≥ 3% 或 5 分 K 拉 ≥ 5% → 必停利出場。

    來源：course_map B5-1、5/1 復盤 [06:44][07:04]
    老師原句：「2 分 K 拉這種 3% 以上的…就很要命了」「5 分 K 拉 5% 更可怕」

    Args:
        k_recent: 最近的 K 棒 DataFrame（最後 1 根為當下評估目標）
        timeframe: '2m' 或 '5m'（決定門檻 3% / 5%）

    Returns:
        triggered=True 代表「應立即停利」、level='exit'
    """
    if k_recent.empty:
        return {"triggered": False, "level": "watch", "reason": "K 棒資料為空"}

    threshold = 3.0 if timeframe == "2m" else 5.0
    last = k_recent.iloc[-1]
    open_p  = float(last["open"])
    close_p = float(last["close"])

    if open_p <= 0:
        return {"triggered": False, "level": "watch", "reason": "開盤無效"}

    rise_pct = (close_p - open_p) / open_p * 100

    if rise_pct >= threshold:
        return {
            "triggered": True,
            "level": "exit",
            "reason": (f"B5-1：{timeframe} 大紅棒 +{rise_pct:.1f}% ≥ {threshold}% "
                       f"→ 立即停利"),
            "rise_pct": rise_pct,
            "timeframe": timeframe,
        }

    return {
        "triggered": False,
        "level": "watch",
        "reason": f"{timeframe} 漲幅 +{rise_pct:.1f}% < {threshold}%",
        "rise_pct": rise_pct,
    }


# ── B5-2 — 漲停隔日 A/B 型識別 ──────────────────────────────────────────────


def check_b5_2_limit_up_pattern(
    k5: pd.DataFrame,
    prev_close: float,
    prev_was_limit_up: bool,
) -> dict:
    """B5-2：昨日漲停 + 今日盤前段長相分 A/B 型。

    來源：course_map B5-2、5/1 復盤 [13:46][15:42]

    A 型（可做）：今日沒跳空（或小跳空）+ 開盤後踩均線守住 → 可當沖
    B 型（不做）：今日跳空高開 + 快速衝高 + 快速灌下 → 隔日沖出貨、不追

    判定：
      - gap_pct < 2% AND 至少 2 根 5K → 觀察結構
      - 第 2 根 5K 收盤 ≥ 第 1 根 5K 開盤（守住開盤）= A 型
      - gap_pct ≥ 3% AND 第 1 根衝高（high - close >= body * 1.5）= B 型

    Args:
        k5: 當日 5 分 K（≥ 2 根）
        prev_close: 昨日收盤
        prev_was_limit_up: 昨日是否漲停

    Returns:
        triggered=True 代表「識別出 A 或 B 型」、level='A'/'B'
        若 prev_was_limit_up=False、直接 not triggered
    """
    if not prev_was_limit_up:
        return {"triggered": False, "level": "watch",
                "reason": "昨日非漲停、B5-2 不適用"}

    if len(k5) < 2 or prev_close <= 0:
        return {"triggered": False, "level": "watch",
                "reason": f"資料不足（{len(k5)} 根 5K）"}

    first  = k5.iloc[0]
    second = k5.iloc[1]
    open_1  = float(first["open"])
    close_1 = float(first["close"])
    high_1  = float(first["high"])
    close_2 = float(second["close"])

    gap_pct = (open_1 / prev_close - 1) * 100
    body_1  = abs(close_1 - open_1)
    upper_1 = high_1 - max(close_1, open_1)

    # B 型：跳空 ≥ 3% + 第 1 根衝高
    # 含十字星 case：body ≈ 0 但有顯著上影、視為極端 B 型
    body_threshold = max(body_1, open_1 * 0.001)
    if gap_pct >= 3.0 and upper_1 >= body_threshold * 1.5:
        return {
            "triggered": True,
            "level": "B",
            "reason": (f"B5-2 B 型：跳空 +{gap_pct:.1f}% + 第 1 根衝高 "
                       f"(上影 {upper_1:.2f} ≥ body {body_1:.2f} × 1.5) "
                       f"→ 隔日沖出貨、不做"),
            "gap_pct": gap_pct,
        }

    # A 型：跳空 < 2% + 第 2 根守住第 1 根開盤
    if gap_pct < 2.0 and close_2 >= open_1:
        return {
            "triggered": True,
            "level": "A",
            "reason": (f"B5-2 A 型：跳空 +{gap_pct:.1f}% < 2% + 第 2 根守 "
                       f"{close_2:.2f} ≥ 第 1 根開 {open_1:.2f} → 可做"),
            "gap_pct": gap_pct,
        }

    return {
        "triggered": False,
        "level": "neutral",
        "reason": f"跳空 +{gap_pct:.1f}%、A/B 型皆不明確",
        "gap_pct": gap_pct,
    }


# ── B5-3 — 季線往上不空（空方過濾） ─────────────────────────────────────────


def check_b5_3_quarterly_ma_short_filter(
    daily_closes: pd.Series,
    lookback_days: int = 5,
) -> dict:
    """B5-3：日 K 季線（60ma）方向上揚 → 一律不空（空方過濾）。

    來源：course_map B5-3、5/1 復盤 [22:25][23:00]
    老師原句：「他的季線是往上揚的，所以你不要空在這個地方」

    判定：MA60 最近 N 天斜率 > 0 → 季線上揚 → 過濾空單

    Args:
        daily_closes: 日 K 收盤序列（≥ 60 + lookback_days）
        lookback_days: 評估斜率的回看天數（預設 5）

    Returns:
        triggered=True 代表「季線上揚、空單應過濾」、level='filter_short'
        triggered=False 代表「季線下行或走平、可考慮空」
    """
    needed = 60 + lookback_days
    if len(daily_closes) < needed:
        return {"triggered": False, "level": "watch",
                "reason": f"日 K 資料不足（{len(daily_closes)} < {needed}）"}

    ma60 = daily_closes.rolling(60, min_periods=60).mean()
    recent = ma60.tail(lookback_days).dropna()

    if len(recent) < 2:
        return {"triggered": False, "level": "watch", "reason": "MA60 計算不足"}

    slope_pct = (recent.iloc[-1] / recent.iloc[0] - 1) * 100

    if slope_pct > 0:
        return {
            "triggered": True,
            "level": "filter_short",
            "reason": (f"B5-3：季線 {lookback_days} 日斜率 +{slope_pct:.2f}% > 0 "
                       f"→ 上揚、空單過濾"),
            "ma60_slope_pct": slope_pct,
            "ma60_now": float(recent.iloc[-1]),
        }

    return {
        "triggered": False,
        "level": "watch",
        "reason": f"季線 {lookback_days} 日斜率 {slope_pct:.2f}% ≤ 0、可考慮空",
        "ma60_slope_pct": slope_pct,
    }


# ── B5-7 — 等 K 棒收完才下判斷（操作紀律） ──────────────────────────────────


def is_bar_closed(
    bar_start: datetime,
    now: datetime,
    bar_duration_seconds: int = 300,
) -> bool:
    """B5-7：當前 K 棒是否已收完。

    來源：course_map B5-7、5/1 line 273-275
    老師原句：「等 K 棒收手所以灌下來就直接結束了這檔就沒了」

    用法：作為其他 indicator 的前置條件、避免在 K 棒形成中誤判。

    Args:
        bar_start: K 棒開始時間
        now: 當下時間
        bar_duration_seconds: K 棒時長（5 分 K = 300、2 分 K = 120）

    Returns:
        True 代表 K 棒已收完、可下判斷
        False 代表 K 棒形成中、應等待
    """
    elapsed = (now - bar_start).total_seconds()
    return elapsed >= bar_duration_seconds
