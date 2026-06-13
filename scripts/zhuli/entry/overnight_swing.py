"""G 隔日沖策略 entry signal — 主力大 Ch6-1 + Ch6-2.

Course source: 主力大全方位操盤教戰守則 (尼克)
  - strategy-indicators.md §G 隔日沖策略
  - HD vision Ch6-1 04:39+05:18 (大盤條件)
  - HD vision Ch6-2 00:44 (個股速篩)

Logic:
    Phase 1: 個股速篩
        條件 1 (布林): close > BB_upper 且 bandwidth_prev < bandwidth_max
        條件 2 (K 棒): body > body_min, vol > min_volume_lots 張, vol > prev × prev_volume_multiplier
        條件 3 (斜率): ma20_slope_5d > ma20_slope_min

    Phase 2: 大盤過濾 (可選, cfg.require_market_filter)
        加權指數 + OTC 都需「量增紅 K + close > 5ma」

Output columns:
    ticker, signal_date, close, prev_close, body_pct,
    bb_upper, bandwidth_prev, volume_lots, volume_ratio_prev,
    ma20_slope_5d, stop_loss (= prev_low), entry_note
"""
from __future__ import annotations

from zhuli.db import get_conn
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from zhuli.config import OvernightSwingConfig


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
    df["bandwidth"] = (4 * df["bb_std"]) / df["bb_middle"].replace(0, np.nan)
    df["bandwidth_prev"] = g["bandwidth"].shift(1)
    return df


def _load_market_index(db_path: Path, ticker: str) -> pd.DataFrame:
    """從 DB 載入指數資料 + 計算 ma5 + 量增紅 K flag.

    Returns DataFrame with columns: trade_date, is_market_bull
    """
    try:
        with get_conn(db_path, timeout=15) as conn:
            df = pd.read_sql_query(
                "SELECT trade_date, open, close, volume FROM standard_daily_bar "
                "WHERE ticker=? ORDER BY trade_date",
                conn, params=(ticker,),
            )
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return pd.DataFrame()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["ma5"] = df["close"].rolling(5, min_periods=5).mean()
    df["prev_volume"] = df["volume"].shift(1)
    df["is_market_bull"] = (
        (df["close"] > df["open"])            # 紅 K
        & (df["volume"] > df["prev_volume"])  # 量增
        & (df["close"] > df["ma5"])           # 收 > 5ma
    )
    return df[["trade_date", "is_market_bull"]].copy()


def detect(
    df: pd.DataFrame,
    cfg: Optional[OvernightSwingConfig] = None,
    db_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Detect G 隔日沖 entry signals.

    Args:
        df: Features DataFrame from add_features() + add_zhuli_features().
        cfg: OvernightSwingConfig (uses defaults if None).
        db_path: Required if cfg.require_market_filter=True (用於載入指數).
    """
    if cfg is None:
        cfg = OvernightSwingConfig()

    # 1. BB 計算
    df = _compute_bbands(df)

    # 2. 條件 1: close > BB_upper + bandwidth_prev < max
    mask = df["close"] > df["bb_upper"]
    mask &= df["bandwidth_prev"] < cfg.bandwidth_max

    # 3. 條件 2: K 棒 long red + 量
    body_pct = (df["close"] - df["prev_close"]) / df["prev_close"].replace(0, np.nan)
    mask &= body_pct >= cfg.body_min
    # volume 單位: 千股 (= 張)；min_volume_lots 是「張」單位
    mask &= (df["volume"] / 1000.0) >= cfg.min_volume_lots
    mask &= df["volume"] > df["prev_volume"] * cfg.prev_volume_multiplier

    # 4. 條件 3: ma20 上彎 (用扣抵預判 — 課程「月線斜率 > 0.4」=「明日上揚足夠」)
    # spec ma20_slope_min 0.004 → 用扣抵 normalized pressure 對應
    slope_col = None  # fallback
    if "ma20_rolloff_pressure" in df.columns:
        mask &= df["ma20_rolloff_pressure"].fillna(0) > cfg.ma20_slope_min
    else:
        slope_col = "ma20_slope" if "ma20_slope" in df.columns else "ma20_slope_5d"
        mask &= df[slope_col].fillna(0) > cfg.ma20_slope_min

    # 5. Liquidity
    mask &= df["close"] >= cfg.min_close

    signals = df[mask].copy()
    if signals.empty:
        return pd.DataFrame(columns=[
            "ticker", "signal_date", "close", "prev_close", "body_pct",
            "bb_upper", "bandwidth_prev", "volume_lots",
            "volume_ratio_prev", "ma20_slope", "market_pass", "stop_loss",
            "entry_note",
        ])

    # 6. 大盤過濾 (可選)
    market_pass_series = pd.Series(True, index=signals.index)
    if cfg.require_market_filter and db_path is not None:
        taiex = _load_market_index(db_path, cfg.market_taiex_ticker)
        tpex = _load_market_index(db_path, cfg.market_otc_ticker)
        if not taiex.empty and not tpex.empty:
            mkt = taiex.merge(
                tpex, on="trade_date", suffixes=("_taiex", "_tpex"),
            )
            mkt["market_pass"] = mkt["is_market_bull_taiex"] & mkt["is_market_bull_tpex"]
            sig_dates = pd.to_datetime(signals["trade_date"])
            mp = sig_dates.map(mkt.set_index("trade_date")["market_pass"]).fillna(False)
            market_pass_series = mp
            signals = signals[mp]
        else:
            # 沒指數資料就不過濾 (warn 由 caller 印)
            pass

    if signals.empty:
        return pd.DataFrame(columns=[
            "ticker", "signal_date", "close", "prev_close", "body_pct",
            "bb_upper", "bandwidth_prev", "volume_lots",
            "volume_ratio_prev", "ma20_slope", "market_pass", "stop_loss",
            "entry_note",
        ])

    out = pd.DataFrame({
        "ticker": signals["ticker"],
        "signal_date": signals["trade_date"],
        "close": signals["close"],
        "prev_close": signals["prev_close"],
        "body_pct": body_pct.loc[signals.index],
        "bb_upper": signals["bb_upper"],
        "bandwidth_prev": signals["bandwidth_prev"],
        "volume_lots": signals["volume"] / 1000.0,
        "volume_ratio_prev": signals["volume"] / signals["prev_volume"].replace(0, np.nan),
        "ma20_slope": signals[slope_col] if slope_col else signals.get("ma20_rolloff_pressure", np.nan),
        "market_pass": market_pass_series.loc[signals.index] if cfg.require_market_filter else True,
        "stop_loss": signals["prev_low"] if "prev_low" in signals.columns else signals["low"],
    })
    out["entry_note"] = out.apply(
        lambda r: (
            f"close={r['close']:.2f} > upper={r['bb_upper']:.2f}; "
            f"bw_prev={r['bandwidth_prev']:.3f}; "
            f"body={r['body_pct']*100:+.2f}%; "
            f"vol={r['volume_lots']:.0f}張×{r['volume_ratio_prev']:.2f}"
        ),
        axis=1,
    )
    out = out.sort_values("signal_date", ascending=False).reset_index(drop=True)
    return out
