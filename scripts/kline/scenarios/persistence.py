"""Historical advisor output storage — Task 1.6.

Saves and loads AdvisorResult snapshots from a SQLite database.

Design constraints (feedback_db_unlock)
-----------------------------------------
- Every function opens its own connection via a context manager and closes
  it immediately after the operation.
- No global / module-level connection is held.
- Write operations commit inside the ``with`` block, then the connection is
  closed on block exit.
- Multiple rapid calls (stress test: 10+ save+load cycles) must not produce
  "database is locked" errors.

Schema
------
Three tables:

``advisor_runs``
    One row per (ticker, trade_date) analysis run.

``advisor_branches``
    One row per enabled branch inside each scenario.
    ``matched_after_n_days`` is nullable — filled in later by the simulator
    via ``update_branch_outcome()``.

``advisor_lights``
    One row per active light in the run.

Public API
----------
::

    run_id = save(result, ticker, trade_date)
    run_id = save(result, ticker, trade_date, db_path=Path("my.db"))

    runs = load_runs("2330", "2026-01-01", "2026-06-30")

    update_branch_outcome(run_id, 0, "B1_明日續強", matched_after_n_days=2)
"""

from __future__ import annotations

from zhuli.db import get_conn

import json
import sqlite3
from pathlib import Path
from typing import Optional

from ._schema import AdvisorResult

# ---------------------------------------------------------------------------
# Default DB path (relative to repo root; tests override via tmp_path)
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH = Path("data/advisor_history.db")

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = """\
CREATE TABLE IF NOT EXISTS advisor_runs (
    run_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker              TEXT    NOT NULL,
    trade_date          TEXT    NOT NULL,
    fired_pattern_count INTEGER NOT NULL,
    scenario_count      INTEGER NOT NULL,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS advisor_branches (
    run_id                  INTEGER NOT NULL,
    scenario_idx            INTEGER NOT NULL,
    branch_id               TEXT    NOT NULL,
    pattern_name            TEXT    NOT NULL DEFAULT '',
    when_json               TEXT    NOT NULL,
    confirm_at              TEXT    NOT NULL,
    next_day_n              INTEGER NOT NULL,
    action_type             TEXT    NOT NULL,
    course_citation_json    TEXT    NOT NULL,
    matched_after_n_days    INTEGER,
    FOREIGN KEY (run_id) REFERENCES advisor_runs(run_id)
);

CREATE TABLE IF NOT EXISTS advisor_lights (
    run_id      INTEGER NOT NULL,
    light_id    TEXT    NOT NULL,
    severity    TEXT    NOT NULL,
    FOREIGN KEY (run_id) REFERENCES advisor_runs(run_id)
);
"""


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist yet."""
    conn.executescript(_DDL)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save(
    result: AdvisorResult,
    ticker: str,
    trade_date: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    """Persist an AdvisorResult snapshot to SQLite.

    Parameters
    ----------
    result:
        The AdvisorResult to store.
    ticker:
        Ticker symbol (e.g. ``"2330"``).
    trade_date:
        Analysis date as ``'YYYY-MM-DD'`` string.
    db_path:
        Path to the SQLite DB file.  Created on first call.

    Returns
    -------
    int
        The ``run_id`` of the newly inserted row in ``advisor_runs``.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with get_conn(db_path, readonly=False) as conn:
        _ensure_tables(conn)

        # Insert run summary
        cur = conn.execute(
            """
            INSERT INTO advisor_runs
                (ticker, trade_date, fired_pattern_count, scenario_count)
            VALUES (?, ?, ?, ?)
            """,
            (
                ticker,
                trade_date,
                len(result.fired_patterns),
                len(result.scenarios),
            ),
        )
        run_id: int = cur.lastrowid  # type: ignore[assignment]

        # Insert branches (one row per enabled branch per scenario)
        for scenario_idx, scenario in enumerate(result.scenarios):
            # We need full branch details — look them up from the Playbook
            # structures stored in scenario.  In Phase 1 the Scenario only
            # stores enabled_branch_ids (strings), not full Branch objects.
            # We store what we have; Phase 4 can backfill when_json etc.
            pattern_name = getattr(scenario, "pattern_hit", None)
            if pattern_name is not None:
                pattern_name = getattr(pattern_name, "pattern", "")
            pattern_name = pattern_name or ""
            for branch_id in scenario.enabled_branches:
                conn.execute(
                    """
                    INSERT INTO advisor_branches
                        (run_id, scenario_idx, branch_id,
                         pattern_name,
                         when_json, confirm_at, next_day_n,
                         action_type, course_citation_json,
                         matched_after_n_days)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        scenario_idx,
                        branch_id,
                        pattern_name,
                        json.dumps({}),   # when_json: full branch detail Phase 4
                        "next_close",     # confirm_at default; Phase 4 will use real value
                        1,                # next_day_n default
                        "watch_only",     # action_type default; Phase 4 will use real value
                        json.dumps({"source": "pending Phase 4"}),
                        None,             # matched_after_n_days — filled by simulator
                    ),
                )

        # Insert active lights
        for light in result.active_lights:
            conn.execute(
                """
                INSERT INTO advisor_lights (run_id, light_id, severity)
                VALUES (?, ?, ?)
                """,
                (run_id, light.light_id, light.severity),
            )

        conn.commit()

    return run_id


def load_runs(
    ticker: str,
    start_date: str,
    end_date: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[dict]:
    """Load advisor runs for a ticker within a date range.

    Parameters
    ----------
    ticker:
        Ticker symbol to filter by.
    start_date:
        Inclusive start date as ``'YYYY-MM-DD'``.
    end_date:
        Inclusive end date as ``'YYYY-MM-DD'``.
    db_path:
        Path to the SQLite DB file.

    Returns
    -------
    list[dict]
        List of run dicts (columns: run_id, ticker, trade_date,
        fired_pattern_count, scenario_count, created_at), ordered by
        ``trade_date`` ascending.  Returns ``[]`` if DB file does not exist.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return []

    with get_conn(db_path, readonly=False) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT run_id, ticker, trade_date,
                   fired_pattern_count, scenario_count, created_at
            FROM advisor_runs
            WHERE ticker = ?
              AND trade_date >= ?
              AND trade_date <= ?
            ORDER BY trade_date ASC
            """,
            (ticker, start_date, end_date),
        )
        rows = [dict(row) for row in cur.fetchall()]

    return rows


def update_branch_outcome(
    run_id: int,
    scenario_idx: int,
    branch_id: str,
    matched_after_n_days: int,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Back-fill ``matched_after_n_days`` for a branch (called by simulator).

    Parameters
    ----------
    run_id:
        The run to update.
    scenario_idx:
        Index of the scenario within the run.
    branch_id:
        The branch id to update.
    matched_after_n_days:
        Number of calendar / trading days until the branch condition resolved.
    db_path:
        Path to the SQLite DB file.
    """
    db_path = Path(db_path)

    with get_conn(db_path, readonly=False) as conn:
        conn.execute(
            """
            UPDATE advisor_branches
            SET matched_after_n_days = ?
            WHERE run_id = ?
              AND scenario_idx = ?
              AND branch_id = ?
            """,
            (matched_after_n_days, run_id, scenario_idx, branch_id),
        )
        conn.commit()
