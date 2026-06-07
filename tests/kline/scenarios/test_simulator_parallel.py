"""Parity tests for simulate_advisor_history multiprocessing (Step 2).

Verifies that n_workers > 1 produces identical DB contents to n_workers = 1.
Re-uses fixture helpers from test_simulator.py.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from kline.scenarios.simulator import simulate_advisor_history

# Reuse fixtures from the main simulator test module
from tests.kline.scenarios.test_simulator import (
    _LIGHT_YAML,
    _PLAYBOOK_YAML,
    _make_dirs,
    _make_ohlcv_df,
    _write_light,
    _write_playbook,
)


def _dump_db(db_path: Path) -> dict:
    """Return sortable representations of all three tables for comparison."""
    with sqlite3.connect(str(db_path)) as conn:
        runs = conn.execute(
            "SELECT ticker, trade_date, fired_pattern_count, scenario_count "
            "FROM advisor_runs"
        ).fetchall()

        branches = conn.execute(
            """
            SELECT ar.ticker, ar.trade_date,
                   ab.scenario_idx, ab.branch_id, ab.pattern_name,
                   ab.action_type, ab.next_day_n, ab.confirm_at,
                   ab.matched_after_n_days, ab.when_json
            FROM advisor_branches ab
            JOIN advisor_runs ar ON ar.run_id = ab.run_id
            """
        ).fetchall()

        lights = conn.execute(
            """
            SELECT ar.ticker, ar.trade_date, al.light_id, al.severity
            FROM advisor_lights al
            JOIN advisor_runs ar ON ar.run_id = al.run_id
            """
        ).fetchall()

    return {
        "runs": sorted(runs),
        "branches": sorted(branches),
        "lights": sorted(lights),
    }


class TestParallelParity:
    """n_workers=2 must produce same DB content as n_workers=1."""

    def test_parity_serial_vs_parallel(self, tmp_path: Path):
        pb_dir, lt_dir = _make_dirs(tmp_path)
        _write_playbook(pb_dir, _PLAYBOOK_YAML)
        _write_light(lt_dir)

        tickers = ["2330", "2317", "2454", "2308"]
        df = _make_ohlcv_df(tickers, n_bars=60)

        serial_db = tmp_path / "serial.db"
        parallel_db = tmp_path / "parallel.db"

        serial_summary = simulate_advisor_history(
            bars_df=df,
            tickers=tickers,
            start_date="2026-05-01",
            end_date="2026-05-20",
            db_path=serial_db,
            playbook_dirs=[pb_dir],
            light_dirs=[lt_dir],
            n_workers=1,
        )

        parallel_summary = simulate_advisor_history(
            bars_df=df,
            tickers=tickers,
            start_date="2026-05-01",
            end_date="2026-05-20",
            db_path=parallel_db,
            playbook_dirs=[pb_dir],
            light_dirs=[lt_dir],
            n_workers=2,
        )

        # Summary stats should match
        assert serial_summary["n_runs_saved"] == parallel_summary["n_runs_saved"]
        assert serial_summary["n_branches_backfilled"] == parallel_summary["n_branches_backfilled"]

        # DB content should match
        serial_dump = _dump_db(serial_db)
        parallel_dump = _dump_db(parallel_db)

        assert len(serial_dump["runs"]) == len(parallel_dump["runs"])
        assert len(serial_dump["branches"]) == len(parallel_dump["branches"])
        assert len(serial_dump["lights"]) == len(parallel_dump["lights"])

        assert serial_dump["runs"] == parallel_dump["runs"]
        assert serial_dump["branches"] == parallel_dump["branches"]
        assert serial_dump["lights"] == parallel_dump["lights"]

    def test_parallel_idempotency(self, tmp_path: Path):
        """Re-running parallel on a populated DB → n_runs_saved == 0."""
        pb_dir, lt_dir = _make_dirs(tmp_path)
        _write_playbook(pb_dir, _PLAYBOOK_YAML)
        _write_light(lt_dir)

        tickers = ["2330", "2317", "2454", "2308"]
        df = _make_ohlcv_df(tickers, n_bars=60)
        db = tmp_path / "advisor.db"

        first = simulate_advisor_history(
            bars_df=df,
            tickers=tickers,
            start_date="2026-05-01",
            end_date="2026-05-20",
            db_path=db,
            playbook_dirs=[pb_dir],
            light_dirs=[lt_dir],
            n_workers=2,
        )
        assert first["n_runs_saved"] > 0

        # Snapshot DB contents
        snapshot = _dump_db(db)

        second = simulate_advisor_history(
            bars_df=df,
            tickers=tickers,
            start_date="2026-05-01",
            end_date="2026-05-20",
            db_path=db,
            playbook_dirs=[pb_dir],
            light_dirs=[lt_dir],
            n_workers=2,
        )
        assert second["n_runs_saved"] == 0
        assert second["n_runs_skipped"] == first["n_runs_saved"]

        # DB content unchanged
        after = _dump_db(db)
        assert after == snapshot
