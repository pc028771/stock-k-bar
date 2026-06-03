"""Tests for scripts/kline/scenarios/persistence.py — Task 1.6.

Coverage:
  T1.6.1  save → load round-trip 結構正確
  T1.6.2  DB lock 不發生（多次 save + load 連續執行 10+ 次）
  T1.6.3  update_branch_outcome 正確更新 matched_after_n_days
  T1.6.4  同 run_id 多 branches / lights 正確存
  T1.6.5  load_runs 跨 ticker / date range 正確過濾

All tests use ``tmp_path`` to avoid touching data/advisor_history.db.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts.kline.scenarios._schema import (
    AdvisorResult,
    CourseCitation,
    Light,
    PatternHit,
    Scenario,
)
from scripts.kline.scenarios.persistence import (
    DEFAULT_DB_PATH,
    load_runs,
    save,
    update_branch_outcome,
)

# ---------------------------------------------------------------------------
# Helpers — build minimal AdvisorResult fixtures
# ---------------------------------------------------------------------------


def _citation() -> CourseCitation:
    return CourseCitation(source="PATTERN_DEFINITIONS §3 多頭吞噬")


def _light(light_id: str = "test_light", severity: str = "warn") -> Light:
    return Light(
        light_id=light_id,
        trigger_condition={"today.close": "> today.open"},
        course_citation=_citation(),
        recommendation_text="test light",
        severity=severity,  # type: ignore[arg-type]
    )


def _pattern_hit(pattern: str = "bull_engulfing") -> PatternHit:
    return PatternHit(pattern=pattern, fired_at="2026-06-01")


def _scenario(branches: list[str] | None = None) -> Scenario:
    return Scenario(
        pattern_hit=_pattern_hit(),
        playbook_name="basic_exhaustion",
        enabled_branches=branches or ["B1_明日續強"],
    )


def _result(
    fired: int = 1,
    scenario_branches: list[str] | None = None,
    lights: list[Light] | None = None,
) -> AdvisorResult:
    return AdvisorResult(
        fired_patterns=[_pattern_hit() for _ in range(fired)],
        scenarios=[_scenario(scenario_branches)] if fired else [],
        active_lights=lights or [],
        notes=[],
    )


# ---------------------------------------------------------------------------
# T1.6.1 — save → load round-trip
# ---------------------------------------------------------------------------

def test_t161_save_load_round_trip(tmp_path: Path):
    """T1.6.1: save + load returns correct run metadata."""
    db = tmp_path / "test.db"
    result = _result(fired=2)
    run_id = save(result, "2330", "2026-06-01", db_path=db)

    assert isinstance(run_id, int)
    assert run_id >= 1

    runs = load_runs("2330", "2026-01-01", "2026-12-31", db_path=db)
    assert len(runs) == 1

    run = runs[0]
    assert run["run_id"] == run_id
    assert run["ticker"] == "2330"
    assert run["trade_date"] == "2026-06-01"
    assert run["fired_pattern_count"] == 2
    assert run["scenario_count"] == 1
    assert "created_at" in run


# ---------------------------------------------------------------------------
# T1.6.2 — DB lock 不發生 (stress: 10+ rapid save + load cycles)
# ---------------------------------------------------------------------------

def test_t162_no_db_lock_under_stress(tmp_path: Path):
    """T1.6.2: 10+ rapid save+load cycles must never raise sqlite3.OperationalError."""
    db = tmp_path / "stress.db"
    n_cycles = 12

    for i in range(n_cycles):
        date = f"2026-01-{i + 1:02d}"
        result = _result(fired=1)
        run_id = save(result, "2330", date, db_path=db)
        assert isinstance(run_id, int)

        # Immediately load after each save
        runs = load_runs("2330", "2026-01-01", "2026-12-31", db_path=db)
        assert len(runs) == i + 1

    # Final check
    all_runs = load_runs("2330", "2026-01-01", "2026-12-31", db_path=db)
    assert len(all_runs) == n_cycles


# ---------------------------------------------------------------------------
# T1.6.3 — update_branch_outcome 正確更新
# ---------------------------------------------------------------------------

def test_t163_update_branch_outcome(tmp_path: Path):
    """T1.6.3: update_branch_outcome sets matched_after_n_days correctly."""
    db = tmp_path / "update.db"
    result = _result(scenario_branches=["B1_明日續強"])
    run_id = save(result, "2330", "2026-06-01", db_path=db)

    # Verify initial state is NULL
    with sqlite3.connect(str(db)) as conn:
        row = conn.execute(
            "SELECT matched_after_n_days FROM advisor_branches WHERE run_id=?",
            (run_id,),
        ).fetchone()
    assert row is not None
    assert row[0] is None

    # Update
    update_branch_outcome(run_id, 0, "B1_明日續強", matched_after_n_days=2, db_path=db)

    # Verify updated
    with sqlite3.connect(str(db)) as conn:
        row = conn.execute(
            "SELECT matched_after_n_days FROM advisor_branches "
            "WHERE run_id=? AND branch_id=?",
            (run_id, "B1_明日續強"),
        ).fetchone()
    assert row is not None
    assert row[0] == 2


# ---------------------------------------------------------------------------
# T1.6.4 — 多 branches / lights 正確存
# ---------------------------------------------------------------------------

def test_t164_multiple_branches_and_lights(tmp_path: Path):
    """T1.6.4: 一個 scenario 多 branches + 多 lights 全部入庫。"""
    db = tmp_path / "multi.db"
    branches = ["B1_明日續強", "B2_明日回測", "B3_停損"]
    lights = [
        _light("pressure_light", "critical"),
        _light("volume_light", "warn"),
        _light("info_light", "info"),
    ]
    result = _result(scenario_branches=branches, lights=lights)
    run_id = save(result, "2330", "2026-06-01", db_path=db)

    with sqlite3.connect(str(db)) as conn:
        branch_rows = conn.execute(
            "SELECT branch_id FROM advisor_branches WHERE run_id=? ORDER BY branch_id",
            (run_id,),
        ).fetchall()
        light_rows = conn.execute(
            "SELECT light_id, severity FROM advisor_lights WHERE run_id=? ORDER BY light_id",
            (run_id,),
        ).fetchall()

    assert len(branch_rows) == 3
    stored_branch_ids = {r[0] for r in branch_rows}
    assert stored_branch_ids == set(branches)

    assert len(light_rows) == 3
    stored_light_ids = {r[0] for r in light_rows}
    assert stored_light_ids == {"pressure_light", "volume_light", "info_light"}

    # Check severity persisted correctly
    sev_map = {r[0]: r[1] for r in light_rows}
    assert sev_map["pressure_light"] == "critical"
    assert sev_map["volume_light"] == "warn"


# ---------------------------------------------------------------------------
# T1.6.5 — load_runs 跨 ticker / date range 過濾
# ---------------------------------------------------------------------------

def test_t165_load_runs_filter_by_ticker_and_date(tmp_path: Path):
    """T1.6.5: load_runs filters correctly by ticker and date range."""
    db = tmp_path / "filter.db"

    save(_result(), "2330", "2026-01-15", db_path=db)
    save(_result(), "2330", "2026-02-20", db_path=db)
    save(_result(), "2330", "2026-03-10", db_path=db)
    save(_result(), "2454", "2026-02-20", db_path=db)  # different ticker

    # Filter by ticker only (wide date range)
    runs_2330 = load_runs("2330", "2026-01-01", "2026-12-31", db_path=db)
    assert len(runs_2330) == 3
    for r in runs_2330:
        assert r["ticker"] == "2330"

    # Filter by ticker + narrow date range
    runs_narrow = load_runs("2330", "2026-01-01", "2026-02-28", db_path=db)
    assert len(runs_narrow) == 2
    dates = [r["trade_date"] for r in runs_narrow]
    assert "2026-01-15" in dates
    assert "2026-02-20" in dates
    assert "2026-03-10" not in dates

    # Different ticker
    runs_2454 = load_runs("2454", "2026-01-01", "2026-12-31", db_path=db)
    assert len(runs_2454) == 1
    assert runs_2454[0]["ticker"] == "2454"

    # Non-existent ticker
    runs_none = load_runs("9999", "2026-01-01", "2026-12-31", db_path=db)
    assert runs_none == []

    # Results in date order
    dates_order = [r["trade_date"] for r in runs_2330]
    assert dates_order == sorted(dates_order)


# ---------------------------------------------------------------------------
# Extra — load_runs on missing DB returns empty list (not exception)
# ---------------------------------------------------------------------------

def test_load_runs_missing_db_returns_empty(tmp_path: Path):
    """load_runs on non-existent DB file → [] (not FileNotFoundError)."""
    runs = load_runs("2330", "2026-01-01", "2026-12-31",
                     db_path=tmp_path / "does_not_exist.db")
    assert runs == []


# ---------------------------------------------------------------------------
# Extra — save auto-creates parent directories
# ---------------------------------------------------------------------------

def test_save_creates_parent_dirs(tmp_path: Path):
    """save() creates intermediate dirs if needed."""
    db = tmp_path / "deep" / "nested" / "advisor.db"
    assert not db.parent.exists()
    run_id = save(_result(), "2330", "2026-06-01", db_path=db)
    assert isinstance(run_id, int)
    assert db.exists()
