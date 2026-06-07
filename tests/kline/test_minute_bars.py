"""Smoke tests for minute_bars.get_max_volume_highs batch helper.

The module caches a sqlite connection against a hardcoded path
(`MAIN_DB_SYMLINK`). We monkeypatch that path to a tmp DB and reset
the cached `_conn` so each test gets a fresh connection.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from kline import minute_bars


@pytest.fixture
def fake_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build a fake main DB with a minute_bars table and redirect the module to it."""
    db = tmp_path / "data.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE minute_bars ("
            "ticker TEXT, trade_date TEXT, ts TEXT, "
            "open REAL, high REAL, low REAL, close REAL, volume REAL"
            ")"
        )
        # 1101 / 2025-01-02: max-volume bar high = 105 (volume 5000)
        # 1101 / 2025-01-03: max-volume bar high = 110 (volume 3000)
        # 2330 / 2025-01-02: max-volume bar high = 600 (volume 9000)
        conn.executemany(
            "INSERT INTO minute_bars VALUES (?,?,?,?,?,?,?,?)",
            [
                ("1101", "2025-01-02", "09:00", 100, 101, 99, 100, 1000),
                ("1101", "2025-01-02", "09:05", 100, 105, 100, 104, 5000),
                ("1101", "2025-01-02", "09:10", 104, 104, 103, 103, 2000),
                ("1101", "2025-01-03", "09:00", 103, 110, 103, 109, 3000),
                ("1101", "2025-01-03", "09:05", 109, 109, 107, 108, 1500),
                ("2330", "2025-01-02", "09:00", 595, 600, 594, 599, 9000),
                ("2330", "2025-01-02", "09:05", 599, 601, 598, 598, 4000),
            ],
        )
        conn.commit()
    # Redirect the module's hardcoded path + reset cached connection.
    monkeypatch.setattr(minute_bars, "MAIN_DB_SYMLINK", db)
    monkeypatch.setattr(minute_bars, "_conn", None)
    return db


def test_get_max_volume_highs_returns_expected_mapping(fake_db: Path):
    items = [("1101", "2025-01-02"), ("1101", "2025-01-03"), ("2330", "2025-01-02")]
    result = minute_bars.get_max_volume_highs(items)
    assert result == {
        ("1101", "2025-01-02"): 105.0,
        ("1101", "2025-01-03"): 110.0,
        ("2330", "2025-01-02"): 600.0,
    }


def test_get_max_volume_highs_empty_input_returns_empty_dict(fake_db: Path):
    assert minute_bars.get_max_volume_highs([]) == {}


def test_get_max_volume_highs_missing_ticker_omitted(fake_db: Path):
    items = [("1101", "2025-01-02"), ("9999", "2025-01-02")]
    result = minute_bars.get_max_volume_highs(items)
    assert ("1101", "2025-01-02") in result
    assert ("9999", "2025-01-02") not in result
    assert result[("1101", "2025-01-02")] == 105.0
