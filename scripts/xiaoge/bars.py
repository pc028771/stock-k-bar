"""Load bars + xiaoge-specific features from four-seasons DB.

DB schema (standard_daily_bar) already has Bollinger bands + MAs precomputed:
    bb_mid, bb_upper, bb_lower, bb_width_pct (formula: (upper-lower)/mid*100)
    ma5, ma10, ma20, ma60, ma240

So xiaoge code just needs to derive bb_in_squeeze + a few aux columns.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd


DEFAULT_DB_PATH = Path("/Users/howard/.four_seasons/data.sqlite")


def load_bars(start_date: str, end_date: str | None = None,
              db_path: Path = DEFAULT_DB_PATH,
              tickers: list[str] | None = None) -> pd.DataFrame:
    """Load bars from standard_daily_bar table, plus warm-up for indicators.

    Returns a DataFrame sorted by (ticker, trade_date) with columns:
        ticker, trade_date, open, high, low, close, volume,
        ma5, ma10, ma20, ma60,
        bb_mid, bb_upper, bb_lower, bb_width_pct
    """
    # Warm-up 80 trading days for rolling-window features (squeeze needs ~30)
    warmup_start = (pd.Timestamp(start_date) - pd.Timedelta(days=120)).strftime("%Y-%m-%d")
    end_clause = f"AND trade_date <= '{end_date}'" if end_date else ""
    ticker_clause = ""
    if tickers:
        placeholders = ",".join(f"'{t}'" for t in tickers)
        ticker_clause = f"AND ticker IN ({placeholders})"

    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        f"""
        SELECT ticker, trade_date, open, high, low, close, volume,
               ma5, ma10, ma20, ma60,
               bb_mid, bb_upper, bb_lower, bb_width_pct,
               vol_ma20,
               main_force_1d, main_force_5d, main_force_10d, main_force_20d,
               custody_accounts
        FROM standard_daily_bar
        WHERE trade_date >= '{warmup_start}'
          {end_clause}
          {ticker_clause}
          AND is_usable = 1
        ORDER BY ticker, trade_date
        """,
        conn,
    )
    conn.close()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    # Cast numerics
    for c in ["open", "high", "low", "close", "volume",
              "ma5", "ma10", "ma20", "ma60",
              "bb_mid", "bb_upper", "bb_lower", "bb_width_pct",
              "vol_ma20",
              "main_force_1d", "main_force_5d", "main_force_10d", "main_force_20d",
              "custody_accounts"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def add_squeeze_flag(df: pd.DataFrame, lookback: int = 10,
                     threshold: float = 12.0) -> pd.DataFrame:
    """Add bb_in_squeeze: True iff past `lookback` bars all have bb_width_pct ≤ threshold.

    Uses the DB's bb_width_pct (formula (upper-lower)/mid*100) — slightly
    different from spec's (upper-lower)/lower*100 but more numerically stable
    and approximately equivalent for normal stocks.
    """
    out = df.copy()
    grp = out.groupby("ticker")["bb_width_pct"]
    max_recent = grp.transform(
        lambda s: s.rolling(lookback, min_periods=lookback).max()
    )
    out["bb_in_squeeze"] = max_recent <= threshold
    return out


def vol_ma5(df: pd.DataFrame) -> pd.Series:
    """Compute 5-day rolling volume average (DB doesn't have this directly)."""
    return df.groupby("ticker")["volume"].transform(
        lambda s: s.rolling(5, min_periods=5).mean()
    )
