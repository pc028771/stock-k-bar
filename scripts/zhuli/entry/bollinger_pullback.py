"""E 布林回測 entry signal — 主力大 Ch4-2 形態四.

Course source: strategy-indicators.md §E + PDF p.127
              L1 Sprite scan ch4-2 48:05~71:32 (3042 晶技核心案例)

Logic:
    前置: 過去 N 天曾 close > BB_upper (D scanner pattern 觸發過)
    觸發: 急漲後回測 MA20 + 量縮 + 不跌破 + 第二波啟動
    進場: ma5 將上揚（扣抵預判）+ 量增攻擊 K
    停損: 收盤跌破 MA20
    出場: 沿用 D — 實體綠 K 跌入上軌之內

Output:
    ticker, signal_date, close, ma20, dist_to_ma20, bb_upper,
    d_triggered_date, pullback_vol_ratio, attack_volume_ratio,
    stop_loss (= ma20), entry_note
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from zhuli.config import BollingerPullbackConfig


def _compute_bbands(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    g = df.groupby("ticker", group_keys=False)
    df["bb_middle"] = (
        g["close"].rolling(20, min_periods=20).mean().reset_index(level=0, drop=True)
    )
    df["bb_std"] = (
        g["close"].rolling(20, min_periods=20).std(ddof=0).reset_index(level=0, drop=True)
    )
    df["bb_upper"] = df["bb_middle"] + 2 * df["bb_std"]
    return df


def detect(
    df: pd.DataFrame,
    cfg: Optional[BollingerPullbackConfig] = None,
) -> pd.DataFrame:
    if cfg is None:
        cfg = BollingerPullbackConfig()

    df = _compute_bbands(df)
    g = df.groupby("ticker", group_keys=False)

    # 前置: 過去 N 天 close > BB_upper 至少一次
    df["d_triggered"] = (df["close"] > df["bb_upper"]).astype(int)
    df["d_triggered_recent"] = (
        g["d_triggered"]
        .rolling(cfg.prerequisite_lookback, min_periods=1)
        .max()
        .reset_index(level=0, drop=True)
    )
    # 找最近一次 D 觸發日（debug 顯示用）
    df["dates_int"] = pd.to_datetime(df["trade_date"]).astype("int64")
    df["d_trigger_date_int"] = (
        df["dates_int"].where(df["d_triggered"] == 1)
    )
    df["d_trigger_date_int"] = (
        g["d_trigger_date_int"]
        .rolling(cfg.prerequisite_lookback, min_periods=1)
        .max()
        .reset_index(level=0, drop=True)
    )

    # 回測量縮: 近 N 日 mean volume / 過去 60 日 max volume
    df["vol_window_mean"] = (
        g["volume"].rolling(cfg.pullback_volume_window, min_periods=1)
        .mean().reset_index(level=0, drop=True)
    )
    df["vol_max_60d"] = (
        g["volume"].rolling(60, min_periods=20)
        .max().reset_index(level=0, drop=True)
    )
    df["pullback_vol_ratio"] = df["vol_window_mean"] / df["vol_max_60d"].replace(0, np.nan)

    # 攻擊 K 量增
    df["vol_recent5_mean"] = (
        g["volume"].rolling(5, min_periods=1)
        .mean().reset_index(level=0, drop=True)
    )
    df["attack_vol_ratio"] = df["volume"] / df["vol_recent5_mean"].replace(0, np.nan)

    # 距 MA20 比例
    df["dist_to_ma20"] = (df["close"] - df["ma20"]) / df["ma20"].replace(0, np.nan)

    mask = pd.Series(True, index=df.index)

    # 1. close > ma20 (不跌破中軌)
    if cfg.require_close_above_ma20:
        mask &= df["close"] > df["ma20"]

    # 2. 距 MA20 ≤ pullback_proximity_max (回測接近 MA20)
    mask &= df["dist_to_ma20"].fillna(99) <= cfg.pullback_proximity_max

    # 3. 前置: D 觸發過
    if cfg.require_d_prerequisite:
        mask &= df["d_triggered_recent"].fillna(0) == 1

    # 4. ma5 將上揚 (扣抵預判)
    if cfg.require_ma5_will_rise and "ma5_will_rise" in df.columns:
        mask &= df["ma5_will_rise"].fillna(False)

    # 5. 回測量縮
    mask &= df["pullback_vol_ratio"].fillna(99) < cfg.pullback_volume_ratio_max

    # 6. 攻擊 K 量增
    if cfg.require_attack_volume:
        mask &= df["attack_vol_ratio"].fillna(0) > cfg.attack_volume_multiplier

    # Liquidity
    if "vol_ma20" in df.columns:
        mask &= df["vol_ma20"].fillna(0) >= cfg.min_avg_volume_20
    mask &= df["close"] >= cfg.min_close

    signals = df[mask].copy()
    if signals.empty:
        return pd.DataFrame(columns=[
            "ticker", "signal_date", "close", "ma20", "dist_to_ma20",
            "bb_upper", "d_trigger_date", "pullback_vol_ratio",
            "attack_vol_ratio", "stop_loss", "entry_note",
        ])

    # D trigger date 轉回 timestamp
    d_trigger_dates = pd.to_datetime(signals["d_trigger_date_int"]).dt.strftime("%Y-%m-%d")

    out = pd.DataFrame({
        "ticker": signals["ticker"],
        "signal_date": signals["trade_date"],
        "close": signals["close"],
        "ma20": signals["ma20"],
        "dist_to_ma20": signals["dist_to_ma20"],
        "bb_upper": signals["bb_upper"],
        "d_trigger_date": d_trigger_dates.values,
        "pullback_vol_ratio": signals["pullback_vol_ratio"],
        "attack_vol_ratio": signals["attack_vol_ratio"],
        "stop_loss": signals["ma20"],  # 跌破 MA20 停損
    })
    out["entry_note"] = out.apply(
        lambda r: (
            f"close={r['close']:.2f}>MA20={r['ma20']:.2f} 距MA20={r['dist_to_ma20']*100:.1f}%; "
            f"D 觸發過 ({r['d_trigger_date']}); "
            f"回測量縮={r['pullback_vol_ratio']*100:.1f}%; 攻擊量×{r['attack_vol_ratio']:.2f}"
        ),
        axis=1,
    )
    out = out.sort_values("signal_date", ascending=False).reset_index(drop=True)
    return out
