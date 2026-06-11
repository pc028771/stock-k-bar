"""C 反轉形態 entry signal — 主力大 Ch4-2.

Course source: strategy-indicators.md §C 反轉形態 (Ch4-2 line 217-356)

Logic:
    1. 紅 K (close > open)
    2. ma20 在 K 棒實體下方 (body_low > ma20) — 關鍵判別 (6441 失敗特徵)
    3. ma10 在實體下方 (body_low > ma10)
    4. 短均線上彎 (ma5_slope_5d > 0)
    5. 均線發散度 (max-min)/close < 5% (避免 ma20 發散)
    6. 前 60 日有下降趨勢 (H-L)/H >= 10%

Output:
    ticker, signal_date, close, prev_close,
    body_low, ma5, ma10, ma20, ma_dispersion, ma5_slope,
    decline_pct_60d, entry_price (= low + (high-low)/3), stop_loss (= low),
    entry_note
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from zhuli.config import ReversalBreakoutConfig


def detect(
    df: pd.DataFrame,
    cfg: Optional[ReversalBreakoutConfig] = None,
) -> pd.DataFrame:
    if cfg is None:
        cfg = ReversalBreakoutConfig()

    df = df.copy()
    g = df.groupby("ticker", group_keys=False)

    df["body_low"] = df[["open", "close"]].min(axis=1)
    df["body_high"] = df[["open", "close"]].max(axis=1)

    # 均線發散度
    ma_max = df[["ma5", "ma10", "ma20"]].max(axis=1)
    ma_min = df[["ma5", "ma10", "ma20"]].min(axis=1)
    df["ma_dispersion"] = (ma_max - ma_min) / df["close"].replace(0, np.nan)

    # 前 60D 下降幅度 (H-L)/H
    df["high_lookback"] = (
        g["high"].rolling(cfg.lookback_decline_days, min_periods=20)
        .max().reset_index(level=0, drop=True)
    )
    df["low_lookback"] = (
        g["low"].rolling(cfg.lookback_decline_days, min_periods=20)
        .min().reset_index(level=0, drop=True)
    )
    df["decline_pct"] = (df["high_lookback"] - df["low_lookback"]) / df["high_lookback"]

    mask = pd.Series(True, index=df.index)

    # 1. 紅 K
    if cfg.require_red_bar:
        mask &= df["close"] > df["open"]

    # 2. ma20 在實體下方
    if cfg.require_body_above_ma20:
        mask &= df["body_low"] > df["ma20"]

    # 3. ma10 在實體下方
    if cfg.require_body_above_ma10:
        mask &= df["body_low"] > df["ma10"]

    # 3b. ma5 在實體下方（🎓 課程「5/10/20 均線皆在反轉紅K 之下」、v1.6 補漏）
    if cfg.require_body_above_ma5:
        mask &= df["body_low"] > df["ma5"]

    # 4. 短均線上彎（**課程明示用扣底值判斷** — §C spec）
    # spec: 「短均線開始上彎（扣底值判斷）」
    # 扣抵預判: today_close > 5 天前 close → 明日 MA5 將上揚
    if cfg.require_ma5_uptrend:
        if "ma5_will_rise" in df.columns:
            mask &= df["ma5_will_rise"].fillna(False)
        else:
            # fallback: 用 slope_5d
            mask &= df["ma5_slope_5d"].fillna(-1) > 0

    # 5. 均線發散度（🔬 課程列「尚未發散」為加分非必要、5% 為回測歸納 → 預設不過濾）
    if cfg.enforce_ma_dispersion:
        mask &= df["ma_dispersion"].fillna(99) < cfg.max_ma_dispersion

    # 6. 前 60D 跌深
    mask &= df["decline_pct"].fillna(0) >= cfg.min_decline_pct

    # Liquidity
    if "vol_ma20" in df.columns:
        mask &= df["vol_ma20"].fillna(0) >= cfg.min_avg_volume_20
    mask &= df["close"] >= cfg.min_close

    signals = df[mask].copy()
    if signals.empty:
        return pd.DataFrame(columns=[
            "ticker", "signal_date", "close", "prev_close", "body_low",
            "ma5", "ma10", "ma20", "ma_dispersion", "ma5_slope",
            "decline_pct_60d", "entry_price", "stop_loss", "entry_note",
        ])

    slope_col = "ma5_slope_5d" if "ma5_slope_5d" in df.columns else "ma5"
    out = pd.DataFrame({
        "ticker": signals["ticker"],
        "signal_date": signals["trade_date"],
        "close": signals["close"],
        "prev_close": signals.get("prev_close", np.nan),
        "body_low": signals["body_low"],
        "ma5": signals["ma5"],
        "ma10": signals["ma10"],
        "ma20": signals["ma20"],
        "ma_dispersion": signals["ma_dispersion"],
        "ma5_slope": signals[slope_col] if slope_col in signals.columns else np.nan,
        "decline_pct_60d": signals["decline_pct"],
        "entry_price": signals["low"] + (signals["high"] - signals["low"]) * cfg.entry_third_factor,
        "stop_loss": signals["low"],
    })
    out["entry_note"] = out.apply(
        lambda r: (
            f"反轉紅K close={r['close']:.2f}; body_low={r['body_low']:.2f}>ma20={r['ma20']:.2f}; "
            f"dispersion={r['ma_dispersion']*100:.2f}%; decline60={r['decline_pct_60d']*100:.1f}%; "
            f"entry={r['entry_price']:.2f} stop={r['stop_loss']:.2f}"
        ),
        axis=1,
    )
    out = out.sort_values("signal_date", ascending=False).reset_index(drop=True)
    return out
