"""scanner.py: produces ranked candidates for a given as_of date."""
from __future__ import annotations

import sqlite3
from pathlib import Path


def test_scanner_returns_dataframe_with_score(tmp_path: Path):
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
        for i in range(80):
            conn.execute(
                "insert into standard_daily_bar values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("1101", f"2025-01-{(i % 30) + 1:02d}",
                 100, 101, 99, 100, 1000, 100, 90.0, 100, 1000, 1.0, 0, 0, 1),
            )
        conn.execute(
            "insert into standard_daily_bar values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("1101", "2025-04-01", 105, 115, 104, 114, 2000, 100, 100.0, 100,
             1000, 2.0, 0, 0, 1),
        )
        conn.commit()

    from scripts import scanner
    out_path = tmp_path / "scanner.csv"
    df = scanner.run(db_path=db, out_path=out_path)
    assert "scanner_score" in df.columns
    assert "ticker" in df.columns
    assert out_path.exists()
