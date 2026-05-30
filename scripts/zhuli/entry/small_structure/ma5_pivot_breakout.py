"""MA5 pivot breakout detector — 攻擊→平台→攻擊型小結構.

依據 user 5/30 觀察 (3 case 驗證):
- 3481 群創 5/21、2303 聯電 4/30、3189 景碩 5/13
- 共同特徵: MA60/120/240 全🟢 + MA5 slope 翻正 + 過去有平台期（至少 1 天 MA5 🔴）

## 條件 (user 5/30 確認)

HARD 必要條件（全部必須滿足）:
  1. MA60 slope > 0（今日 MA60 > 昨日 MA60）
  2. MA120 slope > 0（自算 close.rolling(120).mean()，DB 無此欄）
  3. MA240 slope > 0
  4. 今日 MA5 slope 從 ≤0 翻 >0（pivot）
  5. 動態 platform 期間內有 ≥1 天 MA5 🔴

動態 platform 起點定義:
  - 過去 60 天內，往前找最後一次「MA5 連續 🟢 ≥ 3 天」的最後一天
  - 該日之後（不含）到今日之前（含今日）= platform 期間
  - platform 期間內需有 ≥1 天 MA5 🔴（slope ≤0）
  - 若找不到符合的連續 🟢 ≥ 3 天起點 → 沒有 platform → 不觸發
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _compute_platform_flag(ma5_slope: pd.Series, lookback: int = 60) -> pd.Series:
    """回傳 bool Series：今日是否在有效 platform 後翻正.

    邏輯（對每個日期 t）:
      1. 往前看 lookback 天（含今日）
      2. 找到「最後一次 MA5 連續 🟢 ≥ 3 天」的最後一天 → platform_start
      3. platform_start 之後到 t-1 這段期間內，有 ≥1 天 MA5 🔴（slope ≤0）→ True
      4. 若找不到符合的連續 🟢 ≥ 3 天片段 → False

    注意: 此函數計算開銷較高，逐行用 rolling apply 方式實作。
    """
    n = len(ma5_slope)
    result = pd.Series(False, index=ma5_slope.index)

    # 轉成 numpy array 加速
    slope_arr = ma5_slope.values.astype(float)

    for i in range(lookback, n):
        # 取過去 lookback 天的 slope（不含今日）
        window = slope_arr[i - lookback: i]   # shape = (lookback,)
        # 找「最後一次連續 🟢 ≥ 3 天」的結束位置（相對 window 的 index）
        # 連續 🟢 = slope > 0
        green = (window > 0).astype(int)

        # 從後往前掃，找最後一個結束的連續 🟢 streak ≥ 3
        platform_start_idx = None  # window 內的位置（0-based）
        j = len(window) - 1
        while j >= 0:
            if green[j] == 1:
                # 往回找連續 🟢 streak 長度
                streak_end = j
                k = j
                while k >= 0 and green[k] == 1:
                    k -= 1
                streak_start = k + 1
                streak_len = streak_end - streak_start + 1
                if streak_len >= 3:
                    platform_start_idx = streak_end  # 連續 🟢 結束後即 platform 開始
                    break
                j = k - 1  # 往前繼續找更早的 streak
            else:
                j -= 1

        if platform_start_idx is None:
            continue

        # platform 期間 = window[platform_start_idx+1 : end] （platform_start 之後到今日前）
        platform_window = window[platform_start_idx + 1:]
        if len(platform_window) == 0:
            continue

        # platform 期間內需有 ≥1 天 MA5 🔴（slope ≤ 0）
        has_red = np.any(platform_window <= 0)
        if has_red:
            result.iloc[i] = True

    return result


def detect_ma5_pivot(df: pd.DataFrame) -> pd.Series:
    """MA5 pivot breakout 偵測.

    回傳 bool Series，True = 該日符合「MA5 pivot 突破」條件.

    條件:
    1. MA60 slope > 0
    2. MA120 slope > 0（自算）
    3. MA240 slope > 0
    4. MA5 slope 今日 > 0，昨日 ≤ 0（pivot 翻正）
    5. 動態 platform：過去 60 天內有有效 platform 期（含 ≥1 天 MA5 🔴）

    Parameters
    ----------
    df : DataFrame
        需含欄位: close, ma5, ma60, ma240
        ma120 若存在則直接用；否則自算 close.rolling(120).mean()

    Returns
    -------
    bool Series（index 同 df）
    """
    c = df['close']
    ma5 = df['ma5']
    ma60 = df['ma60']
    ma240 = df['ma240']

    # MA120 自算（DB 無此欄）
    if 'ma120' in df.columns:
        ma120 = df['ma120']
    else:
        ma120 = c.rolling(120).mean()

    # Slope
    ma5_slope = ma5.diff()
    ma60_slope = ma60.diff()
    ma120_slope = ma120.diff()
    ma240_slope = ma240.diff()

    # 1-3: 三條長線全 🟢
    long_trend = (
        (ma60_slope > 0) &
        (ma120_slope > 0) &
        (ma240_slope > 0)
    )

    # 4: MA5 今日翻正（昨日 ≤0、今日 >0）
    ma5_pivot_today = (ma5_slope > 0) & (ma5_slope.shift(1) <= 0)

    # 5: 動態 platform 條件
    has_platform = _compute_platform_flag(ma5_slope, lookback=60)

    signal = (
        long_trend.fillna(False) &
        ma5_pivot_today.fillna(False) &
        has_platform
    )

    return signal.reindex(df.index).fillna(False)


def detect_with_diagnostics(df: pd.DataFrame) -> pd.DataFrame:
    """回傳含各條件診斷的 DataFrame（debug / backtest 用）.

    Returns
    -------
    DataFrame 含欄位:
        date, close, ma5, ma60, ma120, ma240,
        ma5_slope, ma60_slope, ma120_slope, ma240_slope,
        cond_long_trend, cond_ma5_pivot, cond_has_platform, signal
    """
    c = df['close']
    ma5 = df['ma5']
    ma60 = df['ma60']
    ma240 = df['ma240']

    if 'ma120' in df.columns:
        ma120 = df['ma120']
    else:
        ma120 = c.rolling(120).mean()

    ma5_slope = ma5.diff()
    ma60_slope = ma60.diff()
    ma120_slope = ma120.diff()
    ma240_slope = ma240.diff()

    long_trend = (
        (ma60_slope > 0) &
        (ma120_slope > 0) &
        (ma240_slope > 0)
    )
    ma5_pivot_today = (ma5_slope > 0) & (ma5_slope.shift(1) <= 0)
    has_platform = _compute_platform_flag(ma5_slope, lookback=60)

    date_col = df['trade_date'] if 'trade_date' in df.columns else (
        df['date'] if 'date' in df.columns else df.index
    )

    result = pd.DataFrame({
        'date': date_col,
        'close': c,
        'ma5': ma5,
        'ma60': ma60,
        'ma120': ma120,
        'ma240': ma240,
        'ma5_slope': ma5_slope,
        'ma60_slope': ma60_slope,
        'ma120_slope': ma120_slope,
        'ma240_slope': ma240_slope,
        'cond_long_trend': long_trend.fillna(False),
        'cond_ma5_pivot': ma5_pivot_today.fillna(False),
        'cond_has_platform': has_platform,
        'signal': (long_trend.fillna(False) & ma5_pivot_today.fillna(False) & has_platform),
    })

    return result


# ── 便捷 alias（與 detector.py 風格一致）────────────────────────────────────
detect = detect_ma5_pivot
