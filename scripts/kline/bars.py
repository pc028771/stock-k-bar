"""Load daily bars from the four-seasons SQLite database.

Course source: not a course concept — infrastructure layer.

Output schema (sorted by ticker, trade_date asc):
    ticker, trade_date (datetime64[ns]),
    open, high, low, close, volume (float64),
    ma20, ma60, ma240 (float64, may be NaN),
    is_usable (int)
"""
from __future__ import annotations

from zhuli.db import get_conn

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


def load_bars(
    db_path: Path = DEFAULT_DB_PATH,
    fill_from_backfill: bool = True,
    tickers: list[str] | None = None,
) -> pd.DataFrame:
    """Load all usable daily bars sorted by (ticker, trade_date).

    Copies the DB to /tmp first to avoid iCloud disk I/O errors.

    Parameters
    ----------
    db_path:
        Source SQLite path.
    fill_from_backfill:
        Union with backfill DB (default True).
    tickers:
        Optional list of ticker symbols to filter. If provided, the SQL query
        is narrowed to these tickers — useful for advisor CLI (single ticker)
        to avoid loading 2.1M rows × 16s pandas overhead. Backfill union still
        only adds rows for these tickers when filter is active.

    If `fill_from_backfill=True` and the kline_patterns backfill DB exists,
    union backfill rows into the result:
      - rows that exist ONLY in backfill (pre-2022 history) are appended
      - for overlap rows where main has NaN MAs, fill from backfill

    This ensures patterns/calibrate/sanity all see complete MA columns even
    for tickers whose main DB history is too short for the rolling windows.
    """
    base_query = """
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
    """
    if tickers:
        placeholders = ",".join("?" * len(tickers))
        query = base_query + f" and ticker in ({placeholders}) order by ticker, trade_date"
        params = tuple(tickers)
    else:
        query = base_query + " order by ticker, trade_date"
        params = ()
    # Cached snapshot reused across processes (CLI re-runs); copy only when
    # source mtime is newer. Saves ~20s per CLI call vs always-copy.
    # Single shared path (not per-pid) — race-safe via atomic os.replace().
    tmp = None
    cache_path = Path(tempfile.gettempdir()) / "kline_bars_snapshot.sqlite"
    try:
        src_stat = db_path.stat()
        # Cache valid only when mtime >= source AND size >= ~50% of source
        # (guards against truncated / empty cache from a previously failed copy).
        if (
            cache_path.exists()
            and cache_path.stat().st_mtime >= src_stat.st_mtime
            and cache_path.stat().st_size >= src_stat.st_size // 2
        ):
            conn_path = str(cache_path)
        else:
            # Copy to a unique temp then atomic replace, so concurrent readers
            # never see a half-copied file. Close the mkstemp fd before copy
            # so shutil.copy2 can write to the path.
            fd, staging_str = tempfile.mkstemp(
                suffix=".sqlite",
                prefix="kline_bars_staging_",
                dir=tempfile.gettempdir(),
            )
            os.close(fd)
            shutil.copy2(db_path, staging_str)
            os.replace(staging_str, cache_path)
            conn_path = str(cache_path)
    except Exception:
        conn_path = str(db_path)

    # ── Parquet I/O cache for full-market queries ────────────────────────────
    # Skipping the SQL query + pandas type conversion (~60s) saves the majority
    # of load_bars wall time on repeat runs.  Only applicable when:
    #   - No tickers filter (full market — partial queries are too varied to key)
    # Cache key: DB mtime + backfill DB mtime.
    # Cache location: /tmp/kline_bars_full_<key>.parquet  (~100 MB snappy)
    _parquet_cache: pd.DataFrame | None = None
    _pq_path: Path | None = None
    if not tickers:
        try:
            import hashlib as _hl
            _ph = _hl.md5()
            _ph.update(str(db_path.resolve()).encode())
            _ph.update(str(int(db_path.stat().st_mtime)).encode())
            if fill_from_backfill:
                try:
                    _bf_mtime = int(BACKFILL_DB_PATH.stat().st_mtime) if BACKFILL_DB_PATH.exists() else 0
                    _ph.update(str(_bf_mtime).encode())
                except Exception:
                    pass
            _pq_key = _ph.hexdigest()[:12]
            _pq_path = Path(tempfile.gettempdir()) / f"kline_bars_full_{_pq_key}.parquet"
            if _pq_path.exists():
                _parquet_cache = pd.read_parquet(_pq_path, engine="pyarrow")
        except Exception:
            _parquet_cache = None
    # ─────────────────────────────────────────────────────────────────────────

    if _parquet_cache is not None:
        return _parquet_cache

    with get_conn(conn_path, timeout=15) as conn:
        df = pd.read_sql_query(query, conn, params=params, parse_dates=["trade_date"])
    # Normalise to ns precision (pandas 3.x defaults to us; tests expect ns)
    df["trade_date"] = df["trade_date"].astype("datetime64[ns]")
    df = df.reset_index(drop=True)

    if fill_from_backfill and BACKFILL_DB_PATH.exists():
        df = _union_with_backfill(df)

    # Persist full-market result to parquet for next run
    if not tickers:
        try:
            _pq_staging = str(_pq_path) + ".staging"
            df.to_parquet(_pq_staging, engine="pyarrow", compression="snappy")
            os.replace(_pq_staging, str(_pq_path))
        except Exception:
            pass

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
