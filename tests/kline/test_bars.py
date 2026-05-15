"""bars.load_bars: DB → DataFrame with required schema."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from kline import bars


def test_load_bars_returns_required_columns(tmp_path: Path):
    db = tmp_path / "test.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("""
            create table standard_daily_bar (
                ticker text, trade_date text,
                open real, high real, low real, close real, volume real,
                ma20 real, ma60 real, ma240 real,
                vol_ma20 real, vol_ratio_20 real,
                is_attention_stock int, is_disposition_stock int, is_usable int
            )
        """)
        conn.execute("""
            insert into standard_daily_bar values
                ('1101','2025-01-02',100,102,99,101,1000,100,100,100,1000,1.0,0,0,1),
                ('1101','2025-01-03',101,103,100,102,1100,100,100,100,1000,1.1,0,0,1)
        """)
        conn.commit()
    df = bars.load_bars(db_path=db)
    required = {"ticker", "trade_date", "open", "high", "low", "close",
                "volume", "ma60", "ma20", "ma240", "is_usable"}
    assert required.issubset(df.columns)
    assert df["trade_date"].dtype == "datetime64[ns]"
    assert len(df) == 2
    # Sorted by (ticker, trade_date)
    assert df["trade_date"].is_monotonic_increasing


def test_load_bars_filters_unusable(tmp_path: Path):
    db = tmp_path / "test.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("""
            create table standard_daily_bar (
                ticker text, trade_date text,
                open real, high real, low real, close real, volume real,
                ma20 real, ma60 real, ma240 real,
                vol_ma20 real, vol_ratio_20 real,
                is_attention_stock int, is_disposition_stock int, is_usable int
            )
        """)
        conn.execute("""
            insert into standard_daily_bar values
                ('1101','2025-01-02',100,102,99,101,1000,100,100,100,1000,1.0,0,0,1),
                ('1101','2025-01-03',null,103,100,102,1100,100,100,100,1000,1.1,0,0,1)
        """)
        conn.commit()
    df = bars.load_bars(db_path=db)
    assert len(df) == 1  # row with null open filtered out
