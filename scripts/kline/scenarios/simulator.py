"""Scenario Advisor history simulator — Task 3.A.

Purpose
-------
Run ``advisor.analyze()`` over historical bars for one or many tickers,
persist every run via ``persistence.save()``, then back-fill
``matched_after_n_days`` for every enabled branch using
``condition.evaluate_vectorized``.

Public API
----------
::

    summary = simulate_advisor_history(
        bars_df=df,
        tickers=["2330", "2317"],
        start_date="2024-01-01",
        end_date="2026-05-31",
        db_path=Path("data/advisor_history.db"),
    )

    hit_rates = compute_branch_hit_rates(db_path=Path("data/advisor_history.db"))

Design constraints
------------------
- 禁算「N 日報酬 / EV / PnL」(feedback_backtest_methodology)
- 只算「branch when 條件在未來 N 天內是否觸發」(matched_after_n_days)
- matched_after_n_days == -1 → 明確「未命中」（區別 NULL「未檢驗」）
- 不依賴既有 exit/simulator.py — 兩者目的完全不同
- 大批量走 evaluate_vectorized；每 ticker 只算一次 vectorized pass
- DB 操作後立刻 close  (feedback_db_unlock)
- 不污染 production advisor_history.db — tests 用 tmp_path 傳入 db_path
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from . import advisor as _advisor_module
from .condition import UnknownTokenError, evaluate_vectorized
from .loader import load_playbooks
from .persistence import DEFAULT_DB_PATH, save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum future days to check when back-filling branch outcomes.
# Branches have next_day_n ≤ 3 (spec), but we scan up to MAX_LOOKFORWARD
# so that any branch up to next_day_n=3 can resolve.
_MAX_LOOKFORWARD = 3

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _trading_dates_in_range(
    bars_df: pd.DataFrame,
    start_date: str,
    end_date: str,
) -> list[str]:
    """Return sorted list of unique trade_dates within [start_date, end_date]."""
    if "trade_date" in bars_df.columns:
        dates = bars_df["trade_date"].astype(str)
    else:
        dates = bars_df.index.astype(str)

    mask = (dates >= start_date) & (dates <= end_date)
    return sorted(dates[mask].unique().tolist())


def _get_ticker_list(
    bars_df: pd.DataFrame,
    tickers: list[str] | None,
) -> list[str]:
    """Return the list of tickers to process."""
    if tickers is not None:
        return tickers
    if "ticker" in bars_df.columns:
        return sorted(bars_df["ticker"].unique().tolist())
    # Single-ticker df without a ticker column → caller must pass tickers
    raise ValueError(
        "bars_df has no 'ticker' column; pass tickers= explicitly"
    )


def _is_already_saved(
    ticker: str,
    trade_date: str,
    conn: sqlite3.Connection,
) -> bool:
    """Check whether a (ticker, trade_date) run already exists in the DB."""
    row = conn.execute(
        "SELECT run_id FROM advisor_runs WHERE ticker=? AND trade_date=? LIMIT 1",
        (ticker, trade_date),
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Branch outcome back-fill logic
# ---------------------------------------------------------------------------


def _backfill_single_ticker(
    ticker: str,
    ticker_df: pd.DataFrame,
    db_path: Path,
    playbook_dirs: list[Path] | None,
) -> int:
    """Back-fill matched_after_n_days for all NULL branches of *ticker*.

    Strategy
    --------
    1. Load all branches with matched_after_n_days IS NULL for this ticker.
    2. Group by (branch_id, when_json, next_day_n) — unique condition variants.
    3. For each variant, run evaluate_vectorized once across all of ticker_df.
    4. For each run/branch row, check shifted result[run_date+1..run_date+N].
    5. Write -1 (no match) or N' (first match day) via update_branch_outcome.

    Returns the number of rows updated.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return 0

    # ----- Fetch all pending branches for this ticker -----
    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT ab.rowid, ab.run_id, ab.scenario_idx, ab.branch_id,
                   ab.when_json, ab.next_day_n, ar.trade_date
            FROM advisor_branches ab
            JOIN advisor_runs ar ON ar.run_id = ab.run_id
            WHERE ar.ticker = ?
              AND ab.matched_after_n_days IS NULL
            """,
            (ticker,),
        ).fetchall()

    if not rows:
        return 0

    # ----- Prepare ticker_df index by trade_date for fast lookup -----
    if "trade_date" in ticker_df.columns:
        df_indexed = ticker_df.set_index("trade_date").sort_index()
    else:
        df_indexed = ticker_df.sort_index()

    # Normalise index to str "YYYY-MM-DD" so DB strings and Timestamp keys match.
    all_dates = [str(d)[:10] for d in df_indexed.index.tolist()]
    date_to_pos: dict[str, int] = {d: i for i, d in enumerate(all_dates)}

    # Empty context df — context fields will resolve to False in vectorized eval
    ctx_df = pd.DataFrame(index=df_indexed.index)

    # ----- Group rows by (when_json, next_day_n) so we evaluate once per group ----
    # H1+H2 optimisation: previously we iterated row-by-row, hitting a Python
    # cache + `pd.Series.loc[date_str]` per branch (~1.5s of ~3s in profile).
    # Now we (1) group rows by (when_json, next_day_n), (2) per group, eval each
    # lookahead n=1..n_max ONCE into a numpy bool array (O(1) lookup instead of
    # Series.loc string index), (3) run the lookup loop on plain arrays.
    from collections import defaultdict
    groups: dict[tuple[str, int], list[tuple[int, str]]] = defaultdict(list)
    for (rowid, _run_id, _sc_idx, _branch_id,
         when_json_str, next_day_n, trade_date) in rows:
        if trade_date not in date_to_pos:
            continue
        groups[(when_json_str, next_day_n)].append((rowid, trade_date))

    n_total_dates = len(all_dates)
    update_batch: list[tuple[int, int]] = []
    updated = 0

    parse_cache: dict[str, dict] = {}
    for (when_json_str, n_max), group_rows in groups.items():
        # Parse DSL once per group; cache across groups in case multiple
        # next_day_n values share a when_json.
        if when_json_str not in parse_cache:
            try:
                parse_cache[when_json_str] = json.loads(when_json_str) or {}
            except Exception:
                parse_cache[when_json_str] = {}
        when_dict = parse_cache[when_json_str]
        if not when_dict:
            continue  # leave rows NULL — caller's playbook had empty `when`

        # Evaluate result for each lookahead n=1..n_max ONCE, materialised as
        # a contiguous numpy bool array (NaN → False). `df_indexed`'s row
        # order matches `date_to_pos`, so we can index by run_pos directly.
        arrays: dict[int, "np.ndarray | None"] = {}
        eval_failed = False
        for n in range(1, n_max + 1):
            try:
                rs = evaluate_vectorized(
                    when=when_dict, df=df_indexed, ctx_df=ctx_df, next_day_n=n,
                )
                arrays[n] = np.asarray(rs.fillna(False).to_numpy(), dtype=bool)
            except (UnknownTokenError, KeyError, Exception):
                eval_failed = True
                break
        if eval_failed:
            continue  # leave rows NULL — DSL error

        # Look up per row in this group. `next_day.*` is row-relative, so the
        # answer for "did the n-th day after T satisfy the branch?" is at
        # arr[date_to_pos[T]] (not at date_to_pos[T]+n).
        for (rowid, trade_date) in group_rows:
            run_pos = date_to_pos[trade_date]
            matched_n: Optional[int] = None
            had_any_eval = False
            for n in range(1, n_max + 1):
                if run_pos + n >= n_total_dates:
                    break
                arr = arrays.get(n)
                if arr is None or run_pos >= arr.shape[0]:
                    break
                had_any_eval = True
                if arr[run_pos]:
                    matched_n = n
                    break
            if not had_any_eval:
                continue  # leave NULL — couldn't check any future day
            outcome = matched_n if matched_n is not None else -1
            update_batch.append((outcome, rowid))

    if update_batch:
        with sqlite3.connect(str(db_path)) as conn:
            conn.executemany(
                "UPDATE advisor_branches SET matched_after_n_days = ? "
                "WHERE rowid = ? AND matched_after_n_days IS NULL",
                update_batch,
            )
            conn.commit()
        updated = len(update_batch)

    return updated


# ---------------------------------------------------------------------------
# Fast advisor execution (pre-loaded playbooks/lights)
# ---------------------------------------------------------------------------


def _precompute_pattern_hits(
    enriched_df: pd.DataFrame,
) -> dict[str, list[str]]:
    """Run all pattern detectors once and return {date_str: [pattern_names_fired]}.

    Performance: the old implementation returned {pattern_name: bool_series}
    and the per-date lookup did `enriched_df["trade_date"] == today_date` —
    O(N_rows) full-column scan × 28 patterns × N_dates. For a typical ticker
    that's ~14 400 scans per ticker.

    This version inverts the layout once: we walk each pattern's bool array
    in numpy, collect the row indices where it fires, and append the
    pattern name to that date's list. Subsequent lookups are O(1) dict get.
    """
    from ..patterns import PATTERN_REGISTRY

    if enriched_df.empty:
        return {}

    if "trade_date" in enriched_df.columns:
        dates_arr = enriched_df["trade_date"].to_numpy()
    else:
        dates_arr = enriched_df.index.to_numpy()

    fired_by_date: dict[str, list[str]] = {}
    for pattern_name, detect_fn in PATTERN_REGISTRY.items():
        try:
            series = detect_fn(enriched_df)
        except Exception:  # noqa: BLE001
            continue
        values = np.asarray(series, dtype=bool)
        if values.shape[0] != dates_arr.shape[0]:
            # Detector returned a misaligned series — fall back to safe per-row
            # mapping via the series' own index.
            try:
                idx_to_date = {i: str(d)[:10] for i, d in enumerate(dates_arr)}
                for pos, v in enumerate(values):
                    if not v:
                        continue
                    d = idx_to_date.get(pos)
                    if d is None:
                        continue
                    fired_by_date.setdefault(d, []).append(pattern_name)
            except Exception:
                pass
            continue
        # Fast path: vectorized — pick the dates where this pattern fires.
        hit_dates = dates_arr[values]
        for d in hit_dates:
            d_str = str(d)[:10]
            fired_by_date.setdefault(d_str, []).append(pattern_name)
    return fired_by_date


def _get_fired_patterns_from_cache(
    fired_by_date: dict[str, list[str]],
    today_date: str,
) -> list:
    """Extract fired patterns for a single date from the precomputed map."""
    from ._schema import PatternHit

    names = fired_by_date.get(today_date)
    if not names:
        return []
    return [PatternHit(pattern=n, fired_at=today_date) for n in names]


def _run_advisor_with_cache(
    ticker_df: pd.DataFrame,
    today_date: str,
    ticker: str,
    playbooks_by_pattern: dict,
    lights_dict: dict,
    pattern_series: dict[str, list[str]] | None = None,
    today_row: pd.Series | None = None,
) -> object:
    """Run advisor internals with pre-loaded playbooks/lights.

    This avoids the I/O cost of loading YAML files on every call by
    bypassing advisor.analyze() and calling the internal functions directly.

    When *pattern_series* (a precomputed {date_str: [pattern_names]} map) is
    provided, pattern detection is O(1) per date instead of O(28 × detect_cost).
    """
    from ._schema import AdvisorResult
    from .advisor import (
        _build_scenarios,
        _collect_fired_patterns,
        _ensure_features,
        _evaluate_lights,
    )
    from .context import build_context_snapshot as _build_ctx

    notes: list[str] = []

    # Ensure features
    enriched_df = _ensure_features(ticker_df)

    # Extract today's row — use caller-provided row if available (hot path),
    # otherwise fall back to the O(N) mask scan for backwards compat.
    if today_row is None:
        if "trade_date" in enriched_df.columns:
            today_rows = enriched_df[enriched_df["trade_date"] == today_date]
        else:
            today_rows = enriched_df[enriched_df.index.astype(str) == today_date]

        if today_rows.empty:
            raise ValueError(f"today_date {today_date!r} not found for ticker {ticker!r}")

        today_row = today_rows.iloc[0]

    # Build context snapshot — pass today_row so build_context_snapshot also
    # skips its own ticker / date filter scans.
    ctx, ctx_warns = _build_ctx(enriched_df, today_date, ticker, today_row=today_row)
    notes.extend(ctx_warns)

    # Collect fired patterns (use pre-computed cache if available)
    if pattern_series is not None:
        fired_patterns = _get_fired_patterns_from_cache(pattern_series, today_date)
    else:
        fired_patterns = _collect_fired_patterns(enriched_df, today_date, ticker, notes)

    # Build scenarios (using pre-loaded playbooks)
    scenarios = _build_scenarios(fired_patterns, playbooks_by_pattern, today_row, ctx, notes)

    # Evaluate lights (using pre-loaded lights dict)
    active_lights = _evaluate_lights(lights_dict, today_row, ctx, notes)

    return AdvisorResult(
        fired_patterns=fired_patterns,
        scenarios=scenarios,
        active_lights=active_lights,
        notes=notes,
        context_snapshot=ctx,
    )


def _batch_save_runs(
    ticker: str,
    rows_to_insert: list[tuple],
    branch_meta: dict,
    db_path: Path,
) -> int:
    """Write a batch of (trade_date, AdvisorResult) rows in a single transaction.

    Returns the number of runs saved.
    """
    from .persistence import _ensure_tables  # type: ignore[attr-defined]

    saved = 0
    with sqlite3.connect(str(db_path)) as conn:
        _ensure_tables(conn)

        for (trade_date, result) in rows_to_insert:
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
            saved += 1

            for scenario_idx, scenario in enumerate(result.scenarios):
                # Extract pattern_name from the scenario's pattern_hit
                pattern_name = getattr(scenario, "pattern_hit", None)
                if pattern_name is not None:
                    pattern_name = getattr(pattern_name, "pattern", "")
                pattern_name = pattern_name or ""

                for branch_id in scenario.enabled_branches:
                    # Look up full branch object
                    branch_obj = branch_meta.get(
                        (scenario.pattern_hit.pattern, scenario.playbook_name, branch_id)
                    )

                    if branch_obj is not None:
                        when_json = json.dumps(branch_obj.when)
                        confirm_at = branch_obj.confirm_at
                        next_day_n = branch_obj.next_day_n
                        action_type = branch_obj.action.type
                        citation_json = json.dumps({
                            "source": branch_obj.action.course_citation.source,
                        })
                    else:
                        when_json = json.dumps({})
                        confirm_at = "next_close"
                        next_day_n = 1
                        action_type = "watch_only"
                        citation_json = json.dumps({"source": "pending"})

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
                            run_id, scenario_idx, branch_id,
                            pattern_name,
                            when_json, confirm_at, next_day_n,
                            action_type, citation_json, None,
                        ),
                    )

            for light in result.active_lights:
                conn.execute(
                    """
                    INSERT INTO advisor_lights (run_id, light_id, severity)
                    VALUES (?, ?, ?)
                    """,
                    (run_id, light.light_id, light.severity),
                )

        conn.commit()

    return saved


# ---------------------------------------------------------------------------
# Per-ticker worker function (Step 1 refactor)
# ---------------------------------------------------------------------------


# Module-level worker state. Initialised once per worker process by _init_worker
# under multiprocessing, or populated inline by the serial driver.
_WORKER_PLAYBOOKS: Optional[dict] = None
_WORKER_LIGHTS: Optional[dict] = None
_WORKER_BRANCH_META: Optional[dict] = None
_WORKER_PB_DIRS: Optional[list[Path]] = None
_WORKER_LT_DIRS: Optional[list[Path]] = None


def _init_worker(playbook_dirs: list[Path] | None, light_dirs: list[Path] | None) -> None:
    """Called once per worker process — pre-load playbooks + lights + branch_meta.

    Also used by the serial driver to populate module globals before calling
    ``_simulate_one_ticker`` inline.
    """
    global _WORKER_PLAYBOOKS, _WORKER_LIGHTS, _WORKER_BRANCH_META
    global _WORKER_PB_DIRS, _WORKER_LT_DIRS

    _SCENARIOS_DIR = Path(__file__).parent
    pb_dirs = playbook_dirs if playbook_dirs is not None else [_SCENARIOS_DIR / "playbooks"]
    lt_dirs = light_dirs if light_dirs is not None else [_SCENARIOS_DIR / "lights"]

    from .loader import load_lights as _load_lights
    try:
        playbooks_by_pattern = load_playbooks(pb_dirs)
        lights_dict = _load_lights(lt_dirs)
    except Exception:
        playbooks_by_pattern = {}
        lights_dict = {}

    branch_meta: dict[tuple[str, str, str], object] = {}
    for pattern, pb_list in playbooks_by_pattern.items():
        for pb in pb_list:
            for branch in pb.branches:
                branch_meta[(pattern, pb.setup.name, branch.id)] = branch

    _WORKER_PLAYBOOKS = playbooks_by_pattern
    _WORKER_LIGHTS = lights_dict
    _WORKER_BRANCH_META = branch_meta
    _WORKER_PB_DIRS = playbook_dirs
    _WORKER_LT_DIRS = light_dirs


def _simulate_one_ticker(
    ticker: str,
    ticker_df: pd.DataFrame,
    start_date: str,
    end_date: str,
    worker_db_path: Path,
    save_to_db: bool,
) -> dict:
    """Run advisor over [start_date, end_date] for a single ticker.

    Caller must have invoked ``_init_worker`` first so module globals are
    populated. Writes to *worker_db_path* (which may be a per-worker temp DB
    under multiprocessing, or the main DB under serial mode).

    Returns ``{"ticker", "n_runs_saved", "n_runs_skipped"}``.
    """
    assert _WORKER_PLAYBOOKS is not None, "_init_worker must be called first"

    playbooks_by_pattern = _WORKER_PLAYBOOKS
    lights_dict = _WORKER_LIGHTS or {}
    branch_meta = _WORKER_BRANCH_META or {}

    worker_db_path = Path(worker_db_path)

    n_runs_saved = 0
    n_runs_skipped = 0

    if ticker_df is None or ticker_df.empty:
        return {"ticker": ticker, "n_runs_saved": 0, "n_runs_skipped": 0}

    # Ensure features once
    try:
        from ..features import add_features as _add_features
        sentinel = "prev_close"
        if sentinel not in ticker_df.columns:
            ticker_df = _add_features(ticker_df)
    except Exception:
        pass

    trade_dates = _trading_dates_in_range(ticker_df, start_date, end_date)

    # Pre-check idempotency against the target DB
    already_saved_dates: set[str] = set()
    if save_to_db and worker_db_path.exists():
        with sqlite3.connect(str(worker_db_path)) as conn:
            rows = conn.execute(
                """
                SELECT trade_date FROM advisor_runs
                WHERE ticker = ?
                  AND trade_date >= ?
                  AND trade_date <= ?
                """,
                (ticker, start_date, end_date),
            ).fetchall()
            already_saved_dates = {r[0] for r in rows}

    # Pre-compute pattern detectors once per ticker
    try:
        pattern_series = _precompute_pattern_hits(ticker_df)
    except Exception:
        pattern_series = None

    # Pre-build a date → row-position index once per ticker (O(N) once, no Series
    # materialised). Per-date iteration then does dict.get + iloc — each O(1)
    # — instead of the O(N) full-column mask scans that _run_advisor_with_cache
    # / build_context_snapshot would otherwise do. Eager dict-of-Series was
    # ~8× more expensive than lazy iloc per call, so we stay lazy.
    if "trade_date" in ticker_df.columns:
        date_to_pos: dict[str, int] = {
            str(d)[:10]: i for i, d in enumerate(ticker_df["trade_date"].to_numpy())
        }
    else:
        date_to_pos = {str(d)[:10]: i for i, d in enumerate(ticker_df.index)}

    rows_to_insert: list[tuple] = []
    for trade_date in trade_dates:
        if trade_date in already_saved_dates:
            n_runs_skipped += 1
            continue

        pos = date_to_pos.get(trade_date)
        if pos is None:
            continue
        today_row = ticker_df.iloc[pos]

        try:
            result = _run_advisor_with_cache(
                ticker_df=ticker_df,
                today_date=trade_date,
                ticker=ticker,
                playbooks_by_pattern=playbooks_by_pattern,
                lights_dict=lights_dict,
                pattern_series=pattern_series,
                today_row=today_row,
            )
        except (ValueError, Exception):
            continue

        rows_to_insert.append((trade_date, result))

    if save_to_db and rows_to_insert:
        n_runs_saved = _batch_save_runs(
            ticker=ticker,
            rows_to_insert=rows_to_insert,
            branch_meta=branch_meta,
            db_path=worker_db_path,
        )

    # Per-ticker backfill — runs immediately on this worker's DB so the work
    # parallelises across workers. The global backfill loop in
    # simulate_advisor_history still runs as a safety net (it's idempotent —
    # only touches NULL rows, which there should be ~none of after this).
    n_branches_backfilled = 0
    if save_to_db and worker_db_path.exists():
        try:
            n_branches_backfilled = _backfill_single_ticker(
                ticker, ticker_df, worker_db_path, None
            )
        except Exception:
            n_branches_backfilled = 0

    return {
        "ticker": ticker,
        "n_runs_saved": n_runs_saved,
        "n_runs_skipped": n_runs_skipped,
        "n_branches_backfilled": n_branches_backfilled,
    }


def _simulate_one_ticker_task(
    ticker: str,
    ticker_df: pd.DataFrame,
    start_date: str,
    end_date: str,
    worker_db_path: Path,
    save_to_db: bool,
) -> dict:
    """Multiprocessing task wrapper — ensures worker DB has tables ready."""
    worker_db_path = Path(worker_db_path)
    if save_to_db:
        worker_db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(worker_db_path)) as conn:
            from .persistence import _ensure_tables  # type: ignore[attr-defined]
            _ensure_tables(conn)
            conn.commit()
    return _simulate_one_ticker(
        ticker=ticker,
        ticker_df=ticker_df,
        start_date=start_date,
        end_date=end_date,
        worker_db_path=worker_db_path,
        save_to_db=save_to_db,
    )


def _merge_worker_dbs(main_db: Path, worker_dbs: list[Path]) -> tuple[int, int]:
    """Merge per-worker DBs into the main DB with run_id remap.

    Worker DBs each have their own autoincrement run_id sequence, so we
    cannot simply ATTACH + INSERT — run_ids would collide. We read each
    worker's runs, insert into main (new run_id), build a remap, then
    insert branches/lights with the remapped run_id.

    Idempotency is preserved via a pre-existence check on (ticker, trade_date)
    in the main DB before inserting each run.

    Returns
    -------
    (n_inserted, n_skipped_dup)
        n_inserted: rows newly inserted into main advisor_runs
        n_skipped_dup: rows skipped because (ticker, trade_date) already existed
    """
    main_db = Path(main_db)
    main_db.parent.mkdir(parents=True, exist_ok=True)
    n_inserted = 0
    n_skipped_dup = 0
    with sqlite3.connect(str(main_db)) as main_conn:
        from .persistence import _ensure_tables  # type: ignore[attr-defined]
        _ensure_tables(main_conn)

        for wdb in worker_dbs:
            wdb = Path(wdb)
            if not wdb.exists():
                continue
            with sqlite3.connect(str(wdb)) as wconn:
                runs = wconn.execute(
                    """
                    SELECT run_id, ticker, trade_date,
                           fired_pattern_count, scenario_count
                    FROM advisor_runs
                    """
                ).fetchall()

                if not runs:
                    continue

                remap: dict[int, int] = {}
                for (w_run_id, ticker, trade_date, fp_count, sc_count) in runs:
                    # Idempotency: skip if (ticker, trade_date) already in main
                    existing = main_conn.execute(
                        "SELECT run_id FROM advisor_runs "
                        "WHERE ticker=? AND trade_date=? LIMIT 1",
                        (ticker, trade_date),
                    ).fetchone()
                    if existing is not None:
                        # Already merged from another worker / previous run
                        n_skipped_dup += 1
                        continue
                    cur = main_conn.execute(
                        """
                        INSERT INTO advisor_runs
                            (ticker, trade_date, fired_pattern_count, scenario_count)
                        VALUES (?, ?, ?, ?)
                        """,
                        (ticker, trade_date, fp_count, sc_count),
                    )
                    remap[w_run_id] = int(cur.lastrowid)  # type: ignore[arg-type]
                    n_inserted += 1

                if remap:
                    # Branches
                    branches = wconn.execute(
                        """
                        SELECT run_id, scenario_idx, branch_id, pattern_name,
                               when_json, confirm_at, next_day_n,
                               action_type, course_citation_json,
                               matched_after_n_days
                        FROM advisor_branches
                        """
                    ).fetchall()
                    for row in branches:
                        new_id = remap.get(row[0])
                        if new_id is None:
                            continue
                        main_conn.execute(
                            """
                            INSERT INTO advisor_branches
                                (run_id, scenario_idx, branch_id, pattern_name,
                                 when_json, confirm_at, next_day_n,
                                 action_type, course_citation_json,
                                 matched_after_n_days)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (new_id, *row[1:]),
                        )

                    # Lights
                    lights = wconn.execute(
                        "SELECT run_id, light_id, severity FROM advisor_lights"
                    ).fetchall()
                    for (w_run_id, light_id, severity) in lights:
                        new_id = remap.get(w_run_id)
                        if new_id is None:
                            continue
                        main_conn.execute(
                            "INSERT INTO advisor_lights (run_id, light_id, severity) "
                            "VALUES (?, ?, ?)",
                            (new_id, light_id, severity),
                        )

        main_conn.commit()

    return n_inserted, n_skipped_dup


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def simulate_advisor_history(
    bars_df: pd.DataFrame,
    start_date: str,
    end_date: str,
    tickers: list[str] | None = None,
    db_path: Path = DEFAULT_DB_PATH,
    playbook_dirs: list[Path] | None = None,
    light_dirs: list[Path] | None = None,
    save_to_db: bool = True,
    n_workers: int = 1,
) -> dict:
    """Run advisor.analyze() over historical bars and persist results.

    For each (ticker, trade_date) in [start_date, end_date]:
    1. Calls advisor.analyze() with the given bars_df.
    2. Calls persistence.save() to store the AdvisorResult in db_path.
    3. Skips (ticker, trade_date) pairs already present (idempotent).

    After all runs are saved, back-fills matched_after_n_days for every
    enabled branch using evaluate_vectorized (vectorized per-ticker pass).

    Parameters
    ----------
    bars_df:
        Multi-ticker OHLCV DataFrame sorted (ticker, trade_date).
        Must have a 'ticker' column (unless a single ticker is passed via
        tickers= and the df is pre-filtered).
    start_date:
        Inclusive start date as 'YYYY-MM-DD'.
    end_date:
        Inclusive end date as 'YYYY-MM-DD'.
    tickers:
        Explicit list of tickers to process.  If None, all unique tickers
        in bars_df are used.
    db_path:
        Path to the SQLite advisor_history.db.  Pass a tmp_path in tests.
    playbook_dirs:
        Playbook directories for advisor.  Defaults to the standard dir.
    light_dirs:
        Light directories for advisor.  Defaults to the standard dir.
    save_to_db:
        If False, runs advisor but does not write to DB (dry-run mode).

    Returns
    -------
    dict with keys:
        - n_tickers: int
        - n_dates: int
        - n_runs_saved: int
        - n_runs_skipped: int  (already in DB)
        - n_branches_backfilled: int
    """
    db_path = Path(db_path)
    ticker_list = _get_ticker_list(bars_df, tickers)

    # Ensure DB tables exist on main DB
    if save_to_db:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(db_path)) as conn:
            from .persistence import _ensure_tables  # type: ignore[attr-defined]
            _ensure_tables(conn)
            conn.commit()

    # Pre-slice bars per ticker once — small enough to pickle for workers.
    def _slice(ticker: str) -> pd.DataFrame:
        if "ticker" in bars_df.columns:
            return bars_df[bars_df["ticker"] == ticker].copy()
        return bars_df.copy()

    n_runs_saved = 0
    n_runs_skipped = 0
    # _simulate_one_ticker now runs per-ticker backfill on its worker DB so
    # the work parallelises. The global backfill loop below still runs as a
    # safety net (idempotent — only touches NULL rows), but it's mostly a
    # no-op now; we report whichever count was actually done.
    n_branches_backfilled_in_workers = 0

    if n_workers <= 1:
        # ---------- Serial path (preserves existing behaviour) ----------
        _init_worker(playbook_dirs, light_dirs)
        for ticker in ticker_list:
            ticker_df = _slice(ticker)
            if ticker_df.empty:
                continue
            res = _simulate_one_ticker(
                ticker=ticker,
                ticker_df=ticker_df,
                start_date=start_date,
                end_date=end_date,
                worker_db_path=db_path,
                save_to_db=save_to_db,
            )
            n_runs_saved += res["n_runs_saved"]
            n_runs_skipped += res["n_runs_skipped"]
            n_branches_backfilled_in_workers += res.get("n_branches_backfilled", 0)
    else:
        # ---------- Parallel path ----------
        # Per-worker temp DBs under db_path.parent / <stem>.workers/
        workers_dir = db_path.parent / f"{db_path.stem}.workers"
        if save_to_db:
            workers_dir.mkdir(parents=True, exist_ok=True)

        # Build the task list (skip empty tickers up front)
        tasks: list[tuple[str, pd.DataFrame, Path]] = []
        run_uuid = uuid.uuid4().hex[:8]
        for i, ticker in enumerate(ticker_list):
            ticker_df = _slice(ticker)
            if ticker_df.empty:
                continue
            wdb = workers_dir / f"worker_{run_uuid}_{i:05d}.db" if save_to_db else db_path
            tasks.append((ticker, ticker_df, wdb))

        worker_dbs: list[Path] = []
        worker_saved_sum = 0
        with ProcessPoolExecutor(
            max_workers=n_workers,
            initializer=_init_worker,
            initargs=(playbook_dirs, light_dirs),
        ) as pool:
            futures = [
                pool.submit(
                    _simulate_one_ticker_task,
                    ticker,
                    ticker_df,
                    start_date,
                    end_date,
                    wdb,
                    save_to_db,
                )
                for (ticker, ticker_df, wdb) in tasks
            ]
            for fut in as_completed(futures):
                res = fut.result()
                worker_saved_sum += res["n_runs_saved"]
                n_runs_skipped += res["n_runs_skipped"]
                n_branches_backfilled_in_workers += res.get("n_branches_backfilled", 0)

        if save_to_db:
            worker_dbs = [wdb for (_t, _df, wdb) in tasks]
            n_inserted, n_dup = _merge_worker_dbs(db_path, worker_dbs)
            n_runs_saved = n_inserted
            # Worker DBs were fresh, so they didn't see existing rows in main —
            # dedup happens at merge time. Reclassify those as skipped.
            n_runs_skipped += n_dup
        else:
            n_runs_saved = worker_saved_sum

        # Clean up worker DBs and dir (both save_to_db paths — leftover files
        # in workers_dir otherwise stay on disk after every run).
        if save_to_db:
            for wdb in worker_dbs:
                try:
                    Path(wdb).unlink()
                except FileNotFoundError:
                    pass
                # Also remove any -wal / -shm sidecar files from journaling.
                for sidecar_suffix in ("-wal", "-shm", "-journal"):
                    side = Path(str(wdb) + sidecar_suffix)
                    if side.exists():
                        try:
                            side.unlink()
                        except FileNotFoundError:
                            pass
            try:
                workers_dir.rmdir()
            except OSError:
                pass

    # Back-fill matched_after_n_days. Per-worker backfill already ran inside
    # _simulate_one_ticker (parallelises with the advisor work). This global
    # pass is a safety net for any NULL rows that survived (e.g. branches
    # whose future-day data wasn't yet available when the worker ran but is
    # now). It's idempotent — only touches matched_after_n_days IS NULL rows.
    n_branches_backfilled = n_branches_backfilled_in_workers
    if save_to_db:
        # Quick check: any NULL rows left? Skip the loop entirely if not.
        with sqlite3.connect(str(db_path)) as conn:
            null_count = conn.execute(
                "SELECT COUNT(*) FROM advisor_branches WHERE matched_after_n_days IS NULL"
            ).fetchone()[0]

        if null_count > 0:
            for ticker in ticker_list:
                if "ticker" in bars_df.columns:
                    ticker_df = bars_df[bars_df["ticker"] == ticker].copy()
                else:
                    ticker_df = bars_df.copy()

                if ticker_df.empty:
                    continue

                # Ensure features are present for evaluate_vectorized
                try:
                    from ..features import add_features as _add_features
                    sentinel = "prev_close"
                    if sentinel not in ticker_df.columns:
                        ticker_df = _add_features(ticker_df)
                except Exception:
                    pass

                updated = _backfill_single_ticker(ticker, ticker_df, db_path, playbook_dirs)
                n_branches_backfilled += updated

    n_dates = len(_trading_dates_in_range(bars_df, start_date, end_date))

    return {
        "n_tickers": len(ticker_list),
        "n_dates": n_dates,
        "n_runs_saved": n_runs_saved,
        "n_runs_skipped": n_runs_skipped,
        "n_branches_backfilled": n_branches_backfilled,
    }


def compute_branch_hit_rates(
    db_path: Path = DEFAULT_DB_PATH,
    min_runs: int = 10,
) -> pd.DataFrame:
    """Compute per-(pattern, branch_id) hit rates from advisor_history.db.

    Only considers branches where matched_after_n_days IS NOT NULL (i.e.
    backfill has been run).  Branches with NULL are excluded (未檢驗).

    Parameters
    ----------
    db_path:
        Path to the SQLite advisor_history.db.
    min_runs:
        Minimum number of evaluated runs (non-NULL matched_after_n_days) for
        a branch to be included in the output.

    Returns
    -------
    pd.DataFrame with columns:
        pattern, branch_id, n_runs, n_matched, hit_rate, avg_matched_days

    Where:
        - n_runs: rows with matched_after_n_days IS NOT NULL (evaluated)
        - n_matched: rows with matched_after_n_days > 0 (matched)
        - hit_rate: n_matched / n_runs
        - avg_matched_days: mean of matched_after_n_days where > 0
          (i.e. average days until match, for rows that did match)
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return pd.DataFrame(
            columns=["pattern", "branch_id", "n_runs", "n_matched",
                     "hit_rate", "avg_matched_days"]
        )

    query = """
    SELECT
        ar.fired_pattern_count,
        ab.branch_id,
        ab.matched_after_n_days,
        ab.run_id,
        ab.scenario_idx
    FROM advisor_branches ab
    JOIN advisor_runs ar ON ar.run_id = ab.run_id
    WHERE ab.matched_after_n_days IS NOT NULL
    """

    # We also need the pattern name — stored in advisor_branches indirectly.
    # The branch_id encodes the branch but not the pattern; we need to join
    # via advisor_runs → we store pattern as a separate column query.
    # Since Phase 1 schema doesn't store pattern in advisor_branches, we
    # reconstruct it from run metadata via a separate query for patterns.
    # For now, we group by branch_id only (cross-pattern branch_ids are unique
    # in practice due to naming convention like "B1_attack_cost_hold").

    with sqlite3.connect(str(db_path)) as conn:
        # Check if pattern_name column exists (Phase 4.3+ schema).
        # Older DBs without this column fall back to action_type as proxy.
        col_info = conn.execute("PRAGMA table_info(advisor_branches)").fetchall()
        col_names = {row[1] for row in col_info}
        has_pattern_name = "pattern_name" in col_names

        if has_pattern_name:
            rows_df = pd.read_sql_query(
                """
                SELECT
                    COALESCE(NULLIF(ab.pattern_name, ''), ab.action_type, 'unknown') as pattern,
                    ab.branch_id,
                    ab.matched_after_n_days
                FROM advisor_branches ab
                JOIN advisor_runs ar ON ar.run_id = ab.run_id
                WHERE ab.matched_after_n_days IS NOT NULL
                """,
                conn,
            )
        else:
            # Fallback for old DBs without pattern_name column
            rows_df = pd.read_sql_query(
                """
                SELECT
                    COALESCE(ab.action_type, 'unknown') as pattern,
                    ab.branch_id,
                    ab.matched_after_n_days
                FROM advisor_branches ab
                JOIN advisor_runs ar ON ar.run_id = ab.run_id
                WHERE ab.matched_after_n_days IS NOT NULL
                """,
                conn,
            )

    if rows_df.empty:
        return pd.DataFrame(
            columns=["pattern", "branch_id", "n_runs", "n_matched",
                     "hit_rate", "avg_matched_days"]
        )

    rows_df["matched"] = rows_df["matched_after_n_days"] > 0

    grouped = rows_df.groupby(["pattern", "branch_id"])

    agg = grouped.agg(
        n_runs=("matched_after_n_days", "count"),
        n_matched=("matched", "sum"),
    ).reset_index()

    # avg_matched_days: mean of days-to-match (only for matched rows)
    def _avg_days(sub: pd.DataFrame) -> float:
        matched_days = sub.loc[sub["matched_after_n_days"] > 0, "matched_after_n_days"]
        if matched_days.empty:
            return float("nan")
        return float(matched_days.mean())

    avg_days = rows_df.groupby(["pattern", "branch_id"]).apply(_avg_days).reset_index()
    avg_days.columns = ["pattern", "branch_id", "avg_matched_days"]

    result_df = agg.merge(avg_days, on=["pattern", "branch_id"])
    result_df["hit_rate"] = result_df["n_matched"] / result_df["n_runs"]

    # Apply min_runs filter
    result_df = result_df[result_df["n_runs"] >= min_runs].copy()

    return result_df[
        ["pattern", "branch_id", "n_runs", "n_matched", "hit_rate", "avg_matched_days"]
    ].reset_index(drop=True)
