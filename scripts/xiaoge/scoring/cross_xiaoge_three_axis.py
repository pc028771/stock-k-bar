"""cross_xiaoge_three_axis — 三維對齊 cross signal (BB ∩ Chip ∩ KeyBroker).

Course source: detector_spec.md §6 (cross_xiaoge_swing)、ch13 直接示範.

> 「越多條件交集的選出來的股票越少，那選出來的股票越少呢，他的精準度會越高。」
>  (ch13 02:03–02:27)

## 邏輯

- **A+**：三維對齊（BB ∩ Chip ∩ KeyBroker 三者在同日 OR 過去 window 日內都觸發）
- **A**： 二維對齊（任二個維度在 window 日內觸發）
- **B**： 單一訊號（只一個維度觸發）
- **C**： 全 0（三個維度在 window 日內都未觸發）——不獨立成訊號

## 三軸來源

1. **BB**：`scripts.xiaoge.entry.bb_squeeze_breakout.detect`（布林收斂後突破）
2. **Chip**：`scripts.xiaoge.entry.main_chip_holder.detect`（主力買超三軸多頭）
3. **KeyBroker**：`scripts.xiaoge.entry.key_broker_signal.detect`（關鍵分點動作）

## 輸出

detect_three_axis() 回傳 DataFrame with cols:
  - bb_fired:     bool — BB detector 在 window 日內觸發過
  - chip_fired:   bool — Chip detector 在 window 日內觸發過
  - broker_fired: bool — KeyBroker detector 在 window 日內觸發過
  - axes_count:   int  — 三軸中觸發的數量 (0–3)
  - tier:         str  — 'A+' / 'A' / 'B' / 'C'

## 整合紀律

A+ 不代表自動進場——仍需走 stage 1/2/3 entry SOP（「鎖 Plan + 只執行不決策」）。
"""
from __future__ import annotations

import pandas as pd

from scripts.xiaoge.entry.bb_squeeze_breakout import detect as detect_bb
from scripts.xiaoge.entry.main_chip_holder import detect as detect_chip
from scripts.xiaoge.entry.key_broker_signal import detect as detect_broker


def detect_three_axis(
    df: pd.DataFrame,
    window: int = 5,
    bb_kwargs: dict | None = None,
    chip_kwargs: dict | None = None,
    broker_kwargs: dict | None = None,
) -> pd.DataFrame:
    """三維對齊 cross signal.

    Parameters
    ----------
    df:
        日 K DataFrame。欄位需求為三個 sub-detector 的聯集：
        ticker, trade_date, close, open, high, low, volume,
        ma5, ma20, ma60, bb_upper, bb_lower, bb_mid, bb_width_pct,
        main_force_5d。
        （key_broker_signal 額外需要外部 broker/pool parquet，透過 broker_kwargs 傳）
    window:
        rolling 視窗（天數）。某軸在過去 window 日內曾觸發即算「在視窗內觸發」。
        預設 5 個交易日。
    bb_kwargs:
        傳給 bb_squeeze_breakout.detect() 的 keyword args（覆蓋預設值）。
    chip_kwargs:
        傳給 main_chip_holder.detect() 的 keyword args（覆蓋預設值）。
    broker_kwargs:
        傳給 key_broker_signal.detect() 的 keyword args（覆蓋預設值）。
        常用：{'broker_path': Path(...), 'pool_path': Path(...)}

    Returns
    -------
    pd.DataFrame
        index 同 df。欄位：bb_fired, chip_fired, broker_fired,
        axes_count (int 0-3), tier (str 'A+' / 'A' / 'B' / 'C').
    """
    bb_kwargs = bb_kwargs or {}
    chip_kwargs = chip_kwargs or {}
    broker_kwargs = broker_kwargs or {}

    # --- 各軸原始訊號 ---
    bb_sig = detect_bb(df, **bb_kwargs)
    chip_sig = detect_chip(df, **chip_kwargs)
    broker_sig = detect_broker(df, **broker_kwargs)

    # --- Rolling window：過去 window 日內曾觸發即算 ---
    def _in_window(sig: pd.Series) -> pd.Series:
        return (
            sig.groupby(df["ticker"])
            .transform(lambda s: s.rolling(window, min_periods=1).max())
            .astype(bool)
        )

    bb_fired = _in_window(bb_sig)
    chip_fired = _in_window(chip_sig)
    broker_fired = _in_window(broker_sig)

    # --- 計算觸發軸數 ---
    axes_count = bb_fired.astype(int) + chip_fired.astype(int) + broker_fired.astype(int)

    # --- 分級 ---
    def _tier(n: int) -> str:
        if n >= 3:
            return "A+"
        if n == 2:
            return "A"
        if n == 1:
            return "B"
        return "C"

    tier = axes_count.map(_tier)

    result = pd.DataFrame(
        {
            "bb_fired":     bb_fired,
            "chip_fired":   chip_fired,
            "broker_fired": broker_fired,
            "axes_count":   axes_count,
            "tier":         tier,
        },
        index=df.index,
    )
    return result
