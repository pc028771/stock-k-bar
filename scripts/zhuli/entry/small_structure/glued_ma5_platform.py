"""黏 MA5 平台 detector — 老師認證小結構整理.

攻擊完後 close 停在 MA5 附近整理、不破 MA10，等下一次突破訊號。
與 ma5_pivot_breakout.py 互補：
  - glued_ma5_platform = 「平台中」watchlist（等突破）
  - ma5_pivot_breakout = 「突破當下」trigger（當下進場）

## 條件（HARD）

1. 連續 N 天（預設 n_days=3）close 距 MA5 ≤ 2%（絕對值）
   — 每日個別判斷，需在「streak」連續段中
2. close > MA10（不破 MA10）
3. 過去 10 天（shift=5 day ago）最低點 → 目前 close 漲幅 ≥ 10%（前段攻擊）
4. MA60 / MA120 / MA240 全🟢（slope > 0，3 天平均斜率）

注意：MA120/MA240/MA60 全部自算 close.rolling(N).mean()，不使用 DB 欄位
（DB 的 ma60/ma240 偶有資料異常跳位，會導致斜率計算錯誤）
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _compute_streak_n(bool_series: pd.Series, n: int) -> pd.Series:
    """回傳 bool Series：該日是否在連續 True streak ≥ n 天中.

    對每一天，往前看 n 天（含今日），若全為 True 則回傳 True。
    等效於 rolling(n).min() == 1（全為 True）。
    """
    arr = bool_series.astype(int)
    # rolling min over n days: if all n consecutive are True, min == 1
    result = arr.rolling(n, min_periods=n).min() == 1
    return result.fillna(False)


def detect_glued_ma5(
    df: pd.DataFrame,
    n_days: int = 3,
    threshold_pct: float = 2.0,
    attack_window: int = 10,
    attack_shift: int = 5,
    slope_smooth: int = 3,
) -> pd.Series:
    """黏 MA5 平台 detector — 老師認證小結構整理.

    HARD 條件:
    1. 連續 N 天（預設 3）close 距 MA5 ≤ threshold_pct%（絕對值）
    2. close > MA10（不破 MA10）
    3. 過去 attack_window 天（shift=attack_shift 天前）最低點到 close 漲幅 ≥ 10%
    4. MA60 / MA120 / MA240（全部自算）slope 均 > 0（slope = diff(slope_smooth)/slope_smooth）

    Parameters
    ----------
    df            : 需含欄位 close, ma5, ma10（MA60/120/240 自算，不用 DB 欄）
    n_days        : 連續天數門檻（預設 3）
    threshold_pct : 距 MA5 最大百分比（預設 2.0）
    attack_window : 攻擊偵測回看窗口（預設 10 天）
    attack_shift  : 攻擊偵測往前 shift 天數（預設 5 天）
    slope_smooth  : 斜率平滑天數（diff(N)/N，預設 3）

    Returns
    -------
    bool Series（index 同 df，True = 該日符合黏 MA5 平台）

    注意
    ----
    - 需至少 240 + slope_smooth 筆資料才有有效 MA240 斜率
    - 建議載入 500+ 天歷史資料（確保 MA240 穩定）
    """
    c = df['close'].reset_index(drop=True)
    ma5 = df['ma5'].reset_index(drop=True)
    ma10 = df['ma10'].reset_index(drop=True)

    # 自算 MA60 / MA120 / MA240（避免 DB 欄位異常）
    ma60 = c.rolling(60).mean()
    ma120 = c.rolling(120).mean()
    ma240 = c.rolling(240).mean()

    # 斜率（slope_smooth 天平均，降低單日噪音）
    ma60_slope = ma60.diff(slope_smooth) / slope_smooth
    ma120_slope = ma120.diff(slope_smooth) / slope_smooth
    ma240_slope = ma240.diff(slope_smooth) / slope_smooth

    # 條件 1: 距 MA5 ≤ threshold_pct
    dist_ma5 = (c - ma5).abs() / ma5 * 100
    near_ma5 = dist_ma5 <= threshold_pct

    # 連續 n_days 判定
    c1_streak = _compute_streak_n(near_ma5, n_days)

    # 條件 2: close > MA10
    c2 = c > ma10

    # 條件 3: 前段攻擊 ≥ 10%（過去 attack_window 天的最低點，shift attack_shift 天前）
    prior_low = c.rolling(attack_window).min().shift(attack_shift)
    c4 = ((c / prior_low) - 1) >= 0.10

    # 條件 4: 三條長線全🟢
    c3 = (ma60_slope > 0) & (ma120_slope > 0) & (ma240_slope > 0)

    signal = c1_streak & c2 & c3 & c4

    # 重新 align 到原始 df index
    return signal.fillna(False).values  # 回傳 numpy array 供 reindex


def detect_glued_ma5_series(
    df: pd.DataFrame,
    n_days: int = 3,
    threshold_pct: float = 2.0,
    attack_window: int = 10,
    attack_shift: int = 5,
    slope_smooth: int = 3,
) -> pd.Series:
    """detect_glued_ma5 的 Series 版本（index 同 df）.

    主要供外部呼叫使用（daily_scanner_job、backtest 等）。
    """
    result_arr = detect_glued_ma5(
        df,
        n_days=n_days,
        threshold_pct=threshold_pct,
        attack_window=attack_window,
        attack_shift=attack_shift,
        slope_smooth=slope_smooth,
    )
    return pd.Series(result_arr, index=df.index, dtype=bool)


def detect_with_diagnostics(
    df: pd.DataFrame,
    n_days: int = 3,
    threshold_pct: float = 2.0,
    attack_window: int = 10,
    attack_shift: int = 5,
    slope_smooth: int = 3,
) -> pd.DataFrame:
    """回傳含各條件診斷的 DataFrame（debug / backtest / ground truth 驗證用）.

    Returns
    -------
    DataFrame 含欄位:
        trade_date (若存在), close, ma5, ma10,
        ma60, ma120, ma240,  （自算）
        ma60_slope, ma120_slope, ma240_slope,
        dist_ma5_pct, near_ma5,
        cond_streak (連續 n_days), cond_close_above_ma10,
        cond_long_trend (MA60/120/240 全🟢), cond_prior_attack,
        signal
    """
    c = df['close'].reset_index(drop=True)
    ma5 = df['ma5'].reset_index(drop=True)
    ma10 = df['ma10'].reset_index(drop=True)

    ma60 = c.rolling(60).mean()
    ma120 = c.rolling(120).mean()
    ma240 = c.rolling(240).mean()

    ma60_slope = ma60.diff(slope_smooth) / slope_smooth
    ma120_slope = ma120.diff(slope_smooth) / slope_smooth
    ma240_slope = ma240.diff(slope_smooth) / slope_smooth

    dist_ma5 = (c - ma5).abs() / ma5 * 100
    near_ma5 = dist_ma5 <= threshold_pct
    c1_streak = _compute_streak_n(near_ma5, n_days)
    c2 = c > ma10

    prior_low = c.rolling(attack_window).min().shift(attack_shift)
    c4 = ((c / prior_low) - 1) >= 0.10

    c3 = (ma60_slope > 0) & (ma120_slope > 0) & (ma240_slope > 0)

    signal = c1_streak & c2 & c3 & c4

    date_col = None
    for col in ('trade_date', 'date'):
        if col in df.columns:
            date_col = df[col].values
            break

    result = pd.DataFrame({
        'close': c.values,
        'ma5': ma5.values,
        'ma10': ma10.values,
        'ma60': ma60.values,
        'ma120': ma120.values,
        'ma240': ma240.values,
        'ma60_slope': ma60_slope.values,
        'ma120_slope': ma120_slope.values,
        'ma240_slope': ma240_slope.values,
        'dist_ma5_pct': dist_ma5.values,
        'near_ma5': near_ma5.values,
        'cond_streak': c1_streak.values,
        'cond_close_above_ma10': c2.values,
        'cond_long_trend': c3.fillna(False).values,
        'cond_prior_attack': c4.fillna(False).values,
        'signal': signal.fillna(False).values,
    }, index=df.index)

    if date_col is not None:
        result.insert(0, 'trade_date', date_col)

    return result


def get_streak_length(df: pd.DataFrame, threshold_pct: float = 2.0) -> pd.Series:
    """輔助函式：回傳每日「連續黏 MA5 天數」（用於 daily_scanner 顯示）.

    回傳 int Series，0 表示今日不在黏 MA5 streak 中。
    """
    c = df['close'].reset_index(drop=True)
    ma5 = df['ma5'].reset_index(drop=True)
    dist = (c - ma5).abs() / ma5 * 100
    near = dist <= threshold_pct

    # 計算每日 streak 長度
    streak = pd.Series(0, index=df.index)
    count = 0
    for i in range(len(near)):
        if near.iloc[i]:
            count += 1
        else:
            count = 0
        streak.iloc[i] = count
    return streak


def get_avg_dist_ma5(df: pd.DataFrame, n: int = 5, threshold_pct: float = 2.0) -> float | None:
    """輔助函式：最近 n 天（符合黏 MA5 條件的天）的平均距 MA5 百分比."""
    c = df['close'].reset_index(drop=True)
    ma5 = df['ma5'].reset_index(drop=True)
    dist = (c - ma5).abs() / ma5 * 100
    near = dist[dist <= threshold_pct]
    if near.empty:
        return None
    return float(near.tail(n).mean())


# ── 便捷 alias（供 daily_scanner_job import）────────────────────────────────────
detect = detect_glued_ma5_series
