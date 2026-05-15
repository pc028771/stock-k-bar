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


def load_bars(db_path: Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    """Load all usable daily bars sorted by (ticker, trade_date).

    Copies the DB to /tmp first to avoid iCloud disk I/O errors.
    """
    query = """
        select
            ticker, trade_date,
            open, high, low, close, volume,
            ma20, ma60, ma240,
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
    try:
        tmp = Path(tempfile.gettempdir()) / f"kline_bars_snapshot_{os.getpid()}.sqlite"
        shutil.copy2(db_path, tmp)
        conn_path = str(tmp)
    except Exception:
        conn_path = str(db_path)

    with sqlite3.connect(conn_path, timeout=15) as conn:
        df = pd.read_sql_query(query, conn, parse_dates=["trade_date"])
    # Normalise to ns precision (pandas 3.x defaults to us; tests expect ns)
    df["trade_date"] = df["trade_date"].astype("datetime64[ns]")
    return df.reset_index(drop=True)
