"""minute_bars helper — reads from main DB (~/.four_seasons/data.sqlite).

iCloud 路徑安全：每次讀取先 copy 到 /tmp，避免 iCloud sync 衝突。
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

import pandas as pd

MAIN_DB_SYMLINK = Path.home() / ".four_seasons" / "data.sqlite"


def get_minute_bars(ticker: str, date: str) -> pd.DataFrame | None:
    """Load minute bars for (ticker, date) from main DB.

    Copies main DB to /tmp first (iCloud path safety).

    Returns DataFrame with columns [ts, open, high, low, close, volume],
    or None if no data found or main DB unavailable.
    """
    if not MAIN_DB_SYMLINK.exists():
        return None

    # Copy to tmp to avoid iCloud I/O contention
    tmp = Path(tempfile.gettempdir()) / f"mb_read_{int(time.time()*1000)}.sqlite"
    try:
        shutil.copy2(MAIN_DB_SYMLINK, tmp)
        conn = sqlite3.connect(tmp)
        df = pd.read_sql_query(
            "SELECT ts, open, high, low, close, volume FROM minute_bars "
            "WHERE ticker=? AND trade_date=? ORDER BY ts",
            conn,
            params=(ticker, date),
        )
        conn.close()
        return df if not df.empty else None
    except Exception:
        return None
    finally:
        try:
            tmp.unlink()
        except Exception:
            pass


def get_max_volume_high(ticker: str, date: str) -> float | None:
    """最大量 bar 的 high price。無資料回傳 None（呼叫端 fallback）。"""
    df = get_minute_bars(ticker, date)
    if df is None or df.empty:
        return None
    if "volume" not in df.columns or df["volume"].isna().all():
        return None
    idx = df["volume"].idxmax()
    high = df.loc[idx, "high"]
    return float(high) if pd.notna(high) else None
