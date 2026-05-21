"""shakeout_strong — User-created entry strategy using K-Line Power indicators.

## 課程立場

課程（K線力量判斷入門）明確教過量縮、上影線、跌破後站回、ma20 等個別指標的判讀方式，
但 **shakeout_strong 是 user 自創的組合策略**，把多個課程指標組合成一套具體進場條件，
並非課程明示的進場方法。課程從未說「量比 < 4.5 + overhead = 0 + 隔天開低 + 突破 5%
四條同時出現就進場」。

## 為什麼放這裡

此模組放在 `scripts/kline/extras/` 而非 `entry/`，原因如下：

- 組合條件（breakout_vol_capped + breakout_next_low_open + breakout_strength ≥ 5%）
  屬於**回測導出**的門檻組合，非課程明示。
- CLAUDE.md 明訂：「任何課程外條件必須放在 extras/，以 extras. 為命名前綴，預設 OFF。」
- 若日後課程有新章節明確說明此進場邏輯，可升格移入 entry/。

## 觀察證據（回測，非保證）

整體樣本：n = 157 筆（有法人資料），20d net +12.84%，Profit Factor 3.74。

法人方向分組（進場前 5d）：
- A 外賣投買（對做）：n=7,  20d net +25.76%, hit 71.4%, PF 14.90
- B 外買投賣（對做）：n=10, 20d net +3.17%,  hit 50.0%, PF 1.44
- C 同向買：         n=22, 20d net +12.97%, hit 68.2%, PF 2.98
- D 同向賣：         n=4,  20d net +29.96%, hit 100%,  PF 99
- E 微小：           n=22, 20d net +22.38%, hit 63.6%, PF 6.75

以上為 2025Q2–2026Q2 歷史回測，非未來報酬預測。
"""
from __future__ import annotations

import pandas as pd


def detect(df: pd.DataFrame) -> pd.Series:
    """shakeout_strong entry signal (user-created, NOT course-defined).

    對應 master 的 breakout_daily_scanner.py shakeout_strong 條件，
    使用 K線力量框架的指標（量縮 / 上影 / 跌破關鍵低站回 / ma20 等）組合。

    三個必要條件（完全對應 master build_scanner 邏輯）：
    1. breakout_vol_capped：overhead_supply_layer == 0 AND volume_ratio < 4.5
    2. breakout_next_low_open：隔天開低（次日確認欄位，歷史資料才有值）
    3. breakout_strength_pct ≥ 5.0：突破前高 60 日高點的幅度達 5%

    當日最新候選的 breakout_next_low_open 為 NaN（待次日確認），
    detect() 對這類列會回傳 False，需次日開盤後重跑。

    Parameters
    ----------
    df : pd.DataFrame
        需含欄位：overhead_supply_layer, volume_ratio, breakout_next_low_open,
        close, prior_high_60（或 breakout_strength_pct 已預計算）。

    Returns
    -------
    pd.Series[bool]
        index 對齊 df，True 表示當列符合 shakeout_strong 條件。
    """
    # --- breakout_vol_capped ---
    if "breakout_vol_capped" in df.columns:
        vol_capped = df["breakout_vol_capped"].fillna(False).astype(bool)
    else:
        layer = pd.to_numeric(df.get("overhead_supply_layer", pd.Series(dtype=float)), errors="coerce")
        vol_ratio = pd.to_numeric(df.get("volume_ratio", pd.Series(dtype=float)), errors="coerce")
        vol_capped = (layer == 0) & (vol_ratio < 4.5)

    # --- breakout_next_low_open（次日確認，NaN → False）---
    next_low_open = df["breakout_next_low_open"].fillna(False).astype(bool)

    # --- breakout_strength_pct ≥ 5.0 ---
    if "breakout_strength_pct" in df.columns:
        bs_pct = pd.to_numeric(df["breakout_strength_pct"], errors="coerce")
    else:
        close = pd.to_numeric(df.get("close", pd.Series(dtype=float)), errors="coerce")
        prior_high = pd.to_numeric(df.get("prior_high_60", pd.Series(dtype=float)), errors="coerce").replace(0, float("nan"))
        bs_pct = (close / prior_high - 1) * 100

    strength_ok = bs_pct >= 5.0

    return (vol_capped & next_low_open & strength_ok).reindex(df.index).fillna(False)
