"""I 投信跟單 entry signal — 主力大 Ex2-1 + Ex2-2.

Course source: strategy-indicators.md §I 投信跟單策略

Logic:
    1. 5 日累計投信買進 / 股本 ≥ 1.5%
    2. 「剛上榜」: 前 30 天此條件無觸發 (避免追高已啟動標的)
    3. MA5 > MA10 > MA20 皆上彎 (短均線多頭排列)
    4. (警戒線 — 留待後續) 投信持股 / 股本 > 12% → 不進場

Output:
    ticker, signal_date, close, sitc_buy_5d, shares_issued,
    buy_pct_of_shares, is_first_appearance, ma_alignment_ok,
    stop_loss (= ma10), entry_note
"""
from __future__ import annotations

from zhuli.db import get_conn
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from zhuli.config import InstitutionalSwingConfig


def _load_institutional(db_path: Path) -> pd.DataFrame:
    with get_conn(db_path, timeout=15) as conn:
        return pd.read_sql_query("""
            SELECT ticker, trade_date, sitc_buy, sitc_sell, sitc_net
            FROM institutional_investors
        """, conn)


def _load_shareholding(db_path: Path) -> pd.DataFrame:
    try:
        with get_conn(db_path, timeout=15) as conn:
            return pd.read_sql_query("""
                SELECT ticker, trade_date, shares_issued FROM stock_shareholding
            """, conn)
    except Exception:
        return pd.DataFrame(columns=["ticker", "trade_date", "shares_issued"])


def detect(
    df: pd.DataFrame,
    cfg: Optional[InstitutionalSwingConfig] = None,
    db_path: Optional[Path] = None,
) -> pd.DataFrame:
    if cfg is None:
        cfg = InstitutionalSwingConfig()
    if db_path is None:
        from kline.bars import DEFAULT_DB_PATH
        db_path = DEFAULT_DB_PATH

    # 載入 institutional + shareholding
    inst_df = _load_institutional(db_path)
    shares_df = _load_shareholding(db_path)
    if inst_df.empty or shares_df.empty:
        return pd.DataFrame(columns=[
            "ticker", "signal_date", "close", "sitc_buy_5d",
            "shares_issued", "buy_pct_of_shares",
            "is_first_appearance", "ma_alignment_ok",
            "stop_loss", "entry_note",
        ])

    inst_df["trade_date"] = pd.to_datetime(inst_df["trade_date"]).dt.strftime("%Y-%m-%d")
    shares_df["trade_date"] = pd.to_datetime(shares_df["trade_date"]).dt.strftime("%Y-%m-%d")
    df = df.copy()
    df["trade_date_str"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")

    # 5 日累計 sitc_buy
    inst_df = inst_df.sort_values(["ticker", "trade_date"]).reset_index(drop=True)
    g = inst_df.groupby("ticker", group_keys=False)
    buy_col = "sitc_buy" if cfg.use_sitc_buy_not_net else "sitc_net"
    inst_df["sitc_5d_sum"] = (
        g[buy_col].rolling(5, min_periods=1).sum().reset_index(level=0, drop=True)
    )

    # Merge inst + shares + bars
    merged = df.merge(
        inst_df[["ticker", "trade_date", "sitc_5d_sum"]],
        left_on=["ticker", "trade_date_str"], right_on=["ticker", "trade_date"],
        how="left", suffixes=("", "_inst"),
    )
    merged = merged.merge(
        shares_df, left_on=["ticker", "trade_date_str"], right_on=["ticker", "trade_date"],
        how="left", suffixes=("", "_shares"),
    )

    # buy_pct = sitc_5d_sum (張) × 1000 / shares_issued × 100
    merged["buy_pct_of_shares"] = (
        merged["sitc_5d_sum"] * 1000 / merged["shares_issued"].replace(0, np.nan)
    )

    mask = merged["buy_pct_of_shares"].fillna(0) >= cfg.min_5d_buy_pct
    # MA alignment (上彎用扣抵預判 — 比 slope 提早 1-2 天)
    if cfg.require_ma_alignment:
        ma_align = (
            (merged["ma5"] > merged["ma10"])
            & (merged["ma10"] > merged["ma20"])
        )
        if "ma5_will_rise" in merged.columns:
            ma_align &= merged["ma5_will_rise"].fillna(False)
            ma_align &= merged["ma10_will_rise"].fillna(False)
            ma_align &= merged["ma20_will_rise"].fillna(False)
        elif "ma5_slope_5d" in merged.columns:
            ma_align &= merged["ma5_slope_5d"].fillna(-1) > 0
            ma_align &= merged["ma10_slope_5d"].fillna(-1) > 0
            ma_align &= merged["ma20_slope_5d"].fillna(-1) > 0
        mask &= ma_align

    # Liquidity
    if "vol_ma20" in merged.columns:
        mask &= merged["vol_ma20"].fillna(0) >= cfg.min_avg_volume_20
    mask &= merged["close"] >= cfg.min_close

    signals = merged[mask].copy()
    if signals.empty:
        return pd.DataFrame(columns=[
            "ticker", "signal_date", "close", "sitc_buy_5d",
            "shares_issued", "buy_pct_of_shares",
            "is_first_appearance", "ma_alignment_ok",
            "stop_loss", "entry_note",
        ])

    # 「剛上榜」：前 N 天此 ticker 未在 signal 中
    signals = signals.sort_values(["ticker", "trade_date"]).reset_index(drop=True)
    signals["sig_date_dt"] = pd.to_datetime(signals["trade_date"])
    signals["prev_sig_dt"] = signals.groupby("ticker")["sig_date_dt"].shift(1)
    signals["days_since_prev"] = (signals["sig_date_dt"] - signals["prev_sig_dt"]).dt.days
    signals["is_first_appearance"] = (
        signals["days_since_prev"].isna() | (signals["days_since_prev"] > cfg.first_appearance_days)
    )

    out = pd.DataFrame({
        "ticker": signals["ticker"],
        "signal_date": signals["trade_date"],
        "close": signals["close"],
        "sitc_buy_5d": signals["sitc_5d_sum"],
        "shares_issued": signals["shares_issued"],
        "buy_pct_of_shares": signals["buy_pct_of_shares"],
        "is_first_appearance": signals["is_first_appearance"],
        "ma_alignment_ok": True,  # 既然 mask 已過濾
        "stop_loss": signals["ma10"],  # spec: 跌破 MA10 停損
    })
    out["entry_note"] = out.apply(
        lambda r: (
            f"5d_buy={r['sitc_buy_5d']:.0f}張 ({r['buy_pct_of_shares']*100:.3f}%); "
            f"first={r['is_first_appearance']}; stop={r['stop_loss']:.2f}(MA10)"
        ),
        axis=1,
    )
    out = out.sort_values("signal_date", ascending=False).reset_index(drop=True)
    return out
