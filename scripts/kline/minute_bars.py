"""minute_bars helper — reads from main DB (~/.four_seasons/data.sqlite).

Module-level cached connection (read-only URI mode). The original implementation
copied the entire 1GB DB to /tmp on every call — 400ms × N calls dominated the
backtest hot path (66% of cProfile cumtime). SQLite ro+immutable URI mode is
safe to read directly even against an iCloud-synced file: no write lock taken,
no journal touched, no sync race.
"""
from __future__ import annotations

from zhuli.db import get_conn, MAIN_DB

import shutil
import sqlite3
import tempfile
import threading
from pathlib import Path

import pandas as pd

MAIN_DB_SYMLINK = MAIN_DB
_conn: sqlite3.Connection | None = None
_conn_lock = threading.Lock()
_copy_path: Path | None = None  # fallback tmp copy if URI mode fails


def _get_conn() -> sqlite3.Connection | None:
    """Return a process-cached read-only connection to main DB, or None if absent."""
    global _conn, _copy_path
    if _conn is not None:
        return _conn
    if not MAIN_DB_SYMLINK.exists():
        return None
    with _conn_lock:
        if _conn is not None:
            return _conn
        try:
            from zhuli.db import get_conn
            _conn = get_conn(timeout=15, immutable=True, check_same_thread=False)
            return _conn
        except Exception:
            pass
        # Fallback: one-shot copy to /tmp (paid once per process, not per call)
        try:
            _copy_path = Path(tempfile.gettempdir()) / "kline_minute_bars_snapshot.sqlite"
            shutil.copy2(MAIN_DB_SYMLINK, _copy_path)
            _conn = sqlite3.connect(str(_copy_path), timeout=15, check_same_thread=False)
            return _conn
        except Exception:
            _conn = None
            return None


def get_minute_bars(ticker: str, date: str) -> pd.DataFrame | None:
    """Load minute bars for (ticker, date). Returns None if no data."""
    conn = _get_conn()
    if conn is None:
        return None
    try:
        df = pd.read_sql_query(
            "SELECT ts, open, high, low, close, volume FROM minute_bars "
            "WHERE ticker=? AND trade_date=? ORDER BY ts",
            conn,
            params=(ticker, date),
        )
        return df if not df.empty else None
    except Exception:
        return None


def get_max_volume_high(ticker: str, date: str) -> float | None:
    """最大量 bar 的 high price。無資料回傳 None（呼叫端 fallback）。"""
    conn = _get_conn()
    if conn is None:
        return None
    try:
        # Single-row query: pull the high of the max-volume bar directly.
        row = conn.execute(
            "SELECT high FROM minute_bars "
            "WHERE ticker=? AND trade_date=? "
            "ORDER BY volume DESC LIMIT 1",
            (ticker, date),
        ).fetchone()
    except Exception:
        return None
    if row is None or row[0] is None:
        return None
    return float(row[0])


def get_max_volume_highs(items: list[tuple[str, str]]) -> dict[tuple[str, str], float]:
    """Batch variant: look up max-volume high for many (ticker, date) pairs in one query.

    Returns a dict keyed by (ticker, date). Missing keys = no data; caller falls back.
    """
    if not items:
        return {}
    conn = _get_conn()
    if conn is None:
        return {}
    # Build a single query with an inline VALUES filter — avoids N round-trips.
    # SQLite has a SQLITE_MAX_VARIABLE_NUMBER (typ. 999 in older builds, 32k+ in newer).
    # Chunk to be safe.
    result: dict[tuple[str, str], float] = {}
    CHUNK = 400
    for i in range(0, len(items), CHUNK):
        chunk = items[i : i + CHUNK]
        placeholders = ",".join(["(?, ?)"] * len(chunk))
        params: list[str] = []
        for t, d in chunk:
            params.append(t)
            params.append(d)
        sql = (
            "WITH wanted(ticker, trade_date) AS (VALUES " + placeholders + ") "
            "SELECT m.ticker, m.trade_date, m.high FROM minute_bars m "
            "JOIN wanted w ON w.ticker = m.ticker AND w.trade_date = m.trade_date "
            "WHERE m.volume = ("
            "  SELECT MAX(volume) FROM minute_bars m2 "
            "  WHERE m2.ticker = m.ticker AND m2.trade_date = m.trade_date"
            ")"
        )
        try:
            rows = conn.execute(sql, params).fetchall()
        except Exception:
            continue
        for tkr, dt, high in rows:
            if high is None:
                continue
            result[(str(tkr), str(dt))] = float(high)
    return result
