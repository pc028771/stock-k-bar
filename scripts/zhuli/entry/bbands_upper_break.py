"""D 布林上軌進出策略 entry signal — 主力大 Ch4-2.

Course source: 主力大全方位操盤教戰守則 (林家洋)
  - strategy-indicators.md §D 布林上軌進出策略
  - HD vision Ch4-2 32:07 / 34:47 / 35:19

Logic:
    1. 計算 20 日布林：BB_middle = MA20, BB_std = 20d close std,
       BB_upper = mid + 2*std, BB_lower = mid - 2*std
    2. 起漲 K（今日）：close > BB_upper 且 volume > prev_volume（出量）
    3. 通道窄度（**突破前一天**算）：
        bandwidth_prev = (BB_upper_prev - BB_lower_prev) / BB_middle_prev < bandwidth_max
    4. 排除下降趨勢（如 require_ma60_not_declining = True）：ma60_slope_5d >= 0

Output columns:
    ticker                  — 股票代號
    signal_date             — 突破當日
    close                   — 收盤
    bb_upper                — 今日 BB 上軌
    bb_middle               — 今日 BB 中軌 (= MA20)
    bb_lower                — 今日 BB 下軌
    bandwidth_prev          — 突破前一天的 bandwidth
    bandwidth_today         — 今日 bandwidth
    is_ideal_bandwidth      — bandwidth_prev < cfg.bandwidth_ideal (0.10)
    volume_ratio_prev       — volume / prev_volume
    ma60_slope              — 60 日均線斜率（趨勢方向）
    second_buy_estimate     — BB_upper × cfg.second_buy_factor（二買點預估）
    stop_loss               — 出場參考價 = BB_upper（跌入即出）
    entry_note              — 文字註記

Course: 主力大全方位操盤教戰守則 (林家洋) — Ch4-2
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from zhuli.config import BBandsUpperBreakConfig


def _compute_bbands(df: pd.DataFrame) -> pd.DataFrame:
    """Add BB_upper / BB_middle / BB_lower / bandwidth columns per ticker."""
    df = df.copy()
    g = df.groupby("ticker", group_keys=False)

    # BB_middle = MA20 (可直接用 DB 載入的 ma20，但為一致性自算)
    df["bb_middle"] = (
        g["close"].rolling(20, min_periods=20).mean().reset_index(level=0, drop=True)
    )
    df["bb_std"] = (
        g["close"].rolling(20, min_periods=20).std(ddof=0).reset_index(level=0, drop=True)
    )
    df["bb_upper"] = df["bb_middle"] + 2 * df["bb_std"]
    df["bb_lower"] = df["bb_middle"] - 2 * df["bb_std"]
    df["bandwidth"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_middle"].replace(0, np.nan)
    df["bandwidth_prev"] = g["bandwidth"].shift(1)
    return df


def detect(
    df: pd.DataFrame,
    cfg: Optional[BBandsUpperBreakConfig] = None,
) -> pd.DataFrame:
    """Detect D 布林上軌進出 entry signals.

    Args:
        df: Features DataFrame from add_features() + add_zhuli_features().
            Required cols: ticker, trade_date, close, volume, ma60,
            prev_volume (from zhuli features), ma60_slope_5d (from kline features).
        cfg: BBandsUpperBreakConfig (uses defaults if None).

    Returns:
        DataFrame with one row per signal, sorted by signal_date desc.
    """
    if cfg is None:
        cfg = BBandsUpperBreakConfig()

    # 1. 計算 BB
    df = _compute_bbands(df)

    # 2. Filters
    # close > BB_upper
    mask = df["close"] > df["bb_upper"]
    if cfg.require_volume_increase:
        mask &= df["volume"] > df["prev_volume"]
    # bandwidth_prev < bandwidth_max
    mask &= df["bandwidth_prev"] < cfg.bandwidth_max
    # 排除下降趨勢（用 tolerance 允許橫盤微負）
    if cfg.require_ma60_not_declining:
        if "ma60_slope_5d" in df.columns:
            mask &= df["ma60_slope_5d"].fillna(0) > cfg.ma60_slope_tolerance
        else:
            # fallback: 用 ma60 比較 5 天前
            g = df.groupby("ticker", group_keys=False)
            ma60_prev5 = g["ma60"].shift(5)
            mask &= ((df["ma60"] / ma60_prev5 - 1).fillna(0) > cfg.ma60_slope_tolerance)

    # Liquidity filters
    if "vol_ma20" in df.columns:
        mask &= df["vol_ma20"].fillna(0) >= cfg.min_avg_volume_20
    mask &= df["close"] >= cfg.min_close

    # 取出 ma60_slope (兼容兩種欄位名)
    if "ma60_slope_5d" in df.columns:
        slope_col = "ma60_slope_5d"
    else:
        slope_col = None

    signals = df[mask].copy()
    if signals.empty:
        return pd.DataFrame(columns=[
            "ticker", "signal_date", "close", "bb_upper", "bb_middle", "bb_lower",
            "bandwidth_prev", "bandwidth_today", "is_ideal_bandwidth",
            "volume_ratio_prev", "ma60_slope", "second_buy_estimate", "stop_loss",
            "entry_note",
        ])

    out = pd.DataFrame({
        "ticker": signals["ticker"],
        "signal_date": signals["trade_date"],
        "close": signals["close"],
        "bb_upper": signals["bb_upper"],
        "bb_middle": signals["bb_middle"],
        "bb_lower": signals["bb_lower"],
        "bandwidth_prev": signals["bandwidth_prev"],
        "bandwidth_today": signals["bandwidth"],
        "is_ideal_bandwidth": signals["bandwidth_prev"] < cfg.bandwidth_ideal,
        "volume_ratio_prev": signals["volume"] / signals["prev_volume"].replace(0, np.nan),
        "ma60_slope": signals[slope_col] if slope_col else np.nan,
        "second_buy_estimate": signals["bb_upper"] * cfg.second_buy_factor,
        "stop_loss": signals["bb_upper"],
    })

    out["entry_note"] = out.apply(
        lambda r: (
            f"突破上軌 close={r['close']:.2f}>{r['bb_upper']:.2f}; "
            f"prev_bw={r['bandwidth_prev']:.3f}"
            f"{'(理想)' if r['is_ideal_bandwidth'] else ''}; "
            f"vol×{r['volume_ratio_prev']:.2f}"
        ),
        axis=1,
    )

    out = out.sort_values("signal_date", ascending=False).reset_index(drop=True)
    return out
