"""Load daily bars from the four-seasons SQLite database.

Course source: not a course concept — infrastructure layer.

Output schema (sorted by ticker, trade_date asc):
    ticker, trade_date (datetime64[ns]),
    open, high, low, close, volume (float64),
    ma20, ma60, ma240 (float64, may be NaN),
    is_usable (int)
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pandas as pd

DEFAULT_DB_PATH = Path("/Users/howard/.four_seasons/data.sqlite")
BACKFILL_DB_PATH = Path(
    "/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/"
    "data/analysis/kline_patterns/historical_backfill.sqlite"
)


def load_bars(db_path: Path = DEFAULT_DB_PATH, fill_from_backfill: bool = True) -> pd.DataFrame:
    """Load all usable daily bars sorted by (ticker, trade_date).

    Copies the DB to /tmp first to avoid iCloud disk I/O errors.

    If `fill_from_backfill=True` and the kline_patterns backfill DB exists,
    union backfill rows into the result:
      - rows that exist ONLY in backfill (pre-2022 history) are appended
      - for overlap rows where main has NaN MAs, fill from backfill

    This ensures patterns/calibrate/sanity all see complete MA columns even
    for tickers whose main DB history is too short for the rolling windows.
    """
    query = """
        select
            ticker, trade_date,
            open, high, low, close, volume,
            ma5, ma10, ma20, ma60, ma240,
            vol_ma20, vol_ratio_20,
            is_attention_stock, is_disposition_stock, is_usable
        from standard_daily_bar
        where is_usable = 1
          and open is not null
          and high is not null
          and low is not null
          and close is not null
          and volume is not null
          and open > 0 and high > 0 and low > 0 and close > 0
        order by ticker, trade_date
    """
    # Reuse one snapshot per pid; clean up at process exit.
    # Earlier versions left a 1 GB snapshot per process — 91 stale copies
    # filled 91 GB of /tmp.
    tmp = None
    try:
        tmp = Path(tempfile.gettempdir()) / f"kline_bars_snapshot_{os.getpid()}.sqlite"
        shutil.copy2(db_path, tmp)
        conn_path = str(tmp)
    except Exception:
        conn_path = str(db_path)

    try:
        with sqlite3.connect(conn_path, timeout=15) as conn:
            df = pd.read_sql_query(query, conn, parse_dates=["trade_date"])
    finally:
        if tmp is not None and tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    # Normalise to ns precision (pandas 3.x defaults to us; tests expect ns)
    df["trade_date"] = df["trade_date"].astype("datetime64[ns]")
    df = df.reset_index(drop=True)

    if fill_from_backfill and BACKFILL_DB_PATH.exists():
        df = _union_with_backfill(df)
    return df


def _union_with_backfill(main: pd.DataFrame) -> pd.DataFrame:
    """Append backfill rows missing from main + fill main's NaN MAs from backfill.

    Single source of truth (used by calibrate, scanner, sanity, etc.).
    """
    try:
        with sqlite3.connect(str(BACKFILL_DB_PATH)) as conn:
            extra = pd.read_sql("SELECT * FROM standard_daily_bar", conn)
    except Exception as e:
        print(f"Warning: could not load backfill DB: {e}")
        return main
    if extra.empty:
        return main

    extra["trade_date"] = pd.to_datetime(extra["trade_date"], errors="coerce").astype("datetime64[ns]")

    main_cols = main.columns.tolist()
    for col in main_cols:
        if col not in extra.columns:
            extra[col] = None
    extra = extra[main_cols]

    # Step 1: rows in backfill not in main → append.
    main_key = main[["ticker", "trade_date"]].drop_duplicates()
    extra_only = extra.merge(main_key, on=["ticker", "trade_date"], how="left", indicator=True)
    extra_only = extra_only[extra_only["_merge"] == "left_only"].drop(columns=["_merge"])

    # Step 2: for overlap, fill main's NaN MAs from backfill.
    ma_cols = [c for c in ("ma5", "ma10", "ma20", "ma60", "ma240") if c in main.columns and c in extra.columns]
    if ma_cols:
        extra_indexed = extra.set_index(["ticker", "trade_date"])[ma_cols]
        main = main.set_index(["ticker", "trade_date"])
        for col in ma_cols:
            mask = main[col].isna()
            if mask.any():
                aligned = extra_indexed[col].reindex(main.index)
                main.loc[mask, col] = aligned[mask]
        main = main.reset_index()

    union = pd.concat([main, extra_only], ignore_index=True)
    return union.sort_values(["ticker", "trade_date"]).reset_index(drop=True)
