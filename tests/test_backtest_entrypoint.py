"""backtest.py end-to-end: load → features → entry → simulate → trades."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd


def test_run_backtest_produces_trades_csv(tmp_path: Path):
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
        # 80 ascending bars then a clear breakout
        for i in range(80):
            conn.execute(
                "insert into standard_daily_bar values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("1101", f"2025-01-{(i % 30) + 1:02d}",
                 100, 101, 99, 100, 1000, 100, 90.0, 100,
                 1000, 1.0, 0, 0, 1),
            )
        conn.execute(
            "insert into standard_daily_bar values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("1101", "2025-04-01", 105, 115, 104, 114, 2000, 100, 100.0, 100,
             1000, 2.0, 0, 0, 1),
        )
        conn.commit()

    from scripts import backtest
    out_path = tmp_path / "trades.csv"
    trades = backtest.run(db_path=db, out_path=out_path)
    assert out_path.exists()
    assert isinstance(trades, pd.DataFrame)


def _make_test_db(tmp_path: Path) -> Path:
    """Shared helper: build a minimal test SQLite database."""
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
                (
                    "1101",
                    f"2025-01-{(i % 30) + 1:02d}",
                    100, 101, 99, 100, 1000, 100, 90.0, 100,
                    1000, 1.0, 0, 0, 1,
                ),
            )
        conn.execute(
            "insert into standard_daily_bar values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("1101", "2025-04-01", 105, 115, 104, 114, 2000, 100, 100.0, 100,
             1000, 2.0, 0, 0, 1),
        )
        conn.commit()
    return db


def test_run_backtest_with_pattern_breakout_only(tmp_path: Path):
    """Verify pattern_breakout_only mode produces (possibly fewer) trades."""
    db = _make_test_db(tmp_path)
    from scripts import backtest

    out_path = tmp_path / "trades_strict.csv"
    trades = backtest.run(db_path=db, out_path=out_path, entry_name="pattern_breakout_only")
    assert out_path.exists()
    assert isinstance(trades, pd.DataFrame)


def test_run_backtest_invalid_entry_raises(tmp_path: Path):
    """Verify passing an unknown entry name raises ValueError."""
    db = _make_test_db(tmp_path)
    import pytest

    from scripts import backtest

    out_path = tmp_path / "trades_bad.csv"
    with pytest.raises(ValueError, match="Unknown entry signal"):
        backtest.run(db_path=db, out_path=out_path, entry_name="nonexistent_entry")
