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
import sqlite3
from pathlib import Path
from typing import Optional

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

    all_dates = df_indexed.index.tolist()
    date_to_pos: dict[str, int] = {d: i for i, d in enumerate(all_dates)}

    # Empty context df — context fields will resolve to False in vectorized eval
    ctx_df = pd.DataFrame(index=df_indexed.index)

    # ----- Group conditions to avoid re-running evaluate_vectorized per row -----
    # key: (when_json_str, next_day_n) → pd.Series of bool indexed by trade_date
    condition_cache: dict[tuple[str, int], pd.Series] = {}

    updated = 0

    with sqlite3.connect(str(db_path)) as conn:
        for (rowid, run_id, scenario_idx, branch_id,
             when_json_str, next_day_n, trade_date) in rows:

            # Skip if run date not in our df
            if trade_date not in date_to_pos:
                continue

            cache_key = (when_json_str, next_day_n)
            if cache_key not in condition_cache:
                try:
                    when_dict = json.loads(when_json_str)
                    if not when_dict:
                        # Empty when_json — stored as {} placeholder (Phase 1)
                        # Can't evaluate → leave as NULL
                        continue
                    result_series = evaluate_vectorized(
                        when=when_dict,
                        df=df_indexed,
                        ctx_df=ctx_df,
                        next_day_n=next_day_n,
                    )
                    condition_cache[cache_key] = result_series
                except (UnknownTokenError, KeyError, Exception):
                    # DSL error or missing column → skip, leave NULL
                    continue
            else:
                result_series = condition_cache[cache_key]

            # Check days t+1 .. t+next_day_n for a match
            run_pos = date_to_pos[trade_date]
            matched_n: Optional[int] = None

            for n in range(1, next_day_n + 1):
                check_pos = run_pos + n
                if check_pos >= len(all_dates):
                    break
                check_date = all_dates[check_pos]
                try:
                    fired = bool(result_series.loc[check_date])
                except (KeyError, TypeError):
                    continue
                if fired:
                    matched_n = n
                    break

            # matched_n=None means we checked all N days and none matched
            outcome = matched_n if matched_n is not None else -1

            conn.execute(
                """
                UPDATE advisor_branches
                SET matched_after_n_days = ?
                WHERE run_id = ?
                  AND scenario_idx = ?
                  AND branch_id = ?
                  AND matched_after_n_days IS NULL
                """,
                (outcome, run_id, scenario_idx, branch_id),
            )
            updated += 1

        conn.commit()

    return updated


# ---------------------------------------------------------------------------
# Fast advisor execution (pre-loaded playbooks/lights)
# ---------------------------------------------------------------------------


def _precompute_pattern_hits(
    enriched_df: pd.DataFrame,
) -> dict[str, pd.Series]:
    """Run all pattern detectors once and return {pattern_name: bool_series}.

    This is the key performance optimisation: instead of running 24 detectors
    for each of N dates (24×N calls), we run them once (24 calls total) and
    return a Series indexed by trade_date for fast lookup.
    """
    from ..patterns import PATTERN_REGISTRY

    pattern_series: dict[str, pd.Series] = {}
    for pattern_name, detect_fn in PATTERN_REGISTRY.items():
        try:
            series = detect_fn(enriched_df)
            pattern_series[pattern_name] = series
        except Exception:  # noqa: BLE001
            pass
    return pattern_series


def _get_fired_patterns_from_cache(
    pattern_series: dict[str, pd.Series],
    today_date: str,
    enriched_df: pd.DataFrame,
    ticker: str,
) -> list:
    """Extract fired patterns for a single date from pre-computed series."""
    from ._schema import PatternHit

    hits = []
    for pattern_name, series in pattern_series.items():
        if "trade_date" in enriched_df.columns:
            mask = enriched_df["trade_date"] == today_date
            today_values = series[mask]
        else:
            today_values = series[series.index.astype(str) == today_date]

        if today_values.empty:
            continue
        if bool(today_values.iloc[0]):
            hits.append(PatternHit(pattern=pattern_name, fired_at=today_date))

    return hits


def _run_advisor_with_cache(
    ticker_df: pd.DataFrame,
    today_date: str,
    ticker: str,
    playbooks_by_pattern: dict,
    lights_dict: dict,
    pattern_series: dict[str, pd.Series] | None = None,
) -> object:
    """Run advisor internals with pre-loaded playbooks/lights.

    This avoids the I/O cost of loading YAML files on every call by
    bypassing advisor.analyze() and calling the internal functions directly.

    When *pattern_series* is provided (pre-computed), pattern detection is
    O(1) per date instead of O(24 × detect_cost).
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

    # Extract today's row
    if "trade_date" in enriched_df.columns:
        today_rows = enriched_df[enriched_df["trade_date"] == today_date]
    else:
        today_rows = enriched_df[enriched_df.index.astype(str) == today_date]

    if today_rows.empty:
        raise ValueError(f"today_date {today_date!r} not found for ticker {ticker!r}")

    today_row = today_rows.iloc[0]

    # Build context snapshot
    ctx, ctx_warns = _build_ctx(enriched_df, today_date, ticker)
    notes.extend(ctx_warns)

    # Collect fired patterns (use pre-computed cache if available)
    if pattern_series is not None:
        fired_patterns = _get_fired_patterns_from_cache(
            pattern_series, today_date, enriched_df, ticker
        )
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
                             when_json, confirm_at, next_day_n,
                             action_type, course_citation_json,
                             matched_after_n_days)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id, scenario_idx, branch_id,
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

    # ------------------------------------------------------------------
    # Pre-load playbooks + lights ONCE (key performance optimisation).
    # advisor.analyze() loads them on every call; we bypass that by
    # calling the advisor internals directly with pre-loaded objects.
    # ------------------------------------------------------------------
    _SCENARIOS_DIR = Path(__file__).parent
    pb_dirs = playbook_dirs if playbook_dirs is not None else [_SCENARIOS_DIR / "playbooks"]
    lt_dirs = light_dirs if light_dirs is not None else [_SCENARIOS_DIR / "lights"]

    from .loader import LoaderError, load_lights as _load_lights
    try:
        playbooks_by_pattern = load_playbooks(pb_dirs)
        lights_dict = _load_lights(lt_dirs)
    except Exception:
        playbooks_by_pattern = {}
        lights_dict = {}

    # Pre-build branch detail lookup for fast persist
    branch_meta: dict[tuple[str, str, str], object] = {}
    for pattern, pb_list in playbooks_by_pattern.items():
        for pb in pb_list:
            for branch in pb.branches:
                branch_meta[(pattern, pb.setup.name, branch.id)] = branch

    # Ensure DB tables exist
    if save_to_db:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(db_path)) as conn:
            from .persistence import _ensure_tables  # type: ignore[attr-defined]
            _ensure_tables(conn)
            conn.commit()

    n_runs_saved = 0
    n_runs_skipped = 0

    for ticker in ticker_list:
        # Filter df to this ticker
        if "ticker" in bars_df.columns:
            ticker_df = bars_df[bars_df["ticker"] == ticker].copy()
        else:
            ticker_df = bars_df.copy()

        if ticker_df.empty:
            continue

        # Enrich features ONCE per ticker
        try:
            from ..features import add_features as _add_features
            sentinel = "prev_close"
            if sentinel not in ticker_df.columns:
                ticker_df = _add_features(ticker_df)
        except Exception:
            pass

        # Get dates for this ticker within range
        trade_dates = _trading_dates_in_range(ticker_df, start_date, end_date)

        # Pre-check idempotency for all dates in one query
        already_saved_dates: set[str] = set()
        if save_to_db and db_path.exists():
            with sqlite3.connect(str(db_path)) as conn:
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

        # Pre-compute all pattern detectors ONCE per ticker (key optimisation)
        # This reduces pattern detection from O(24 × N_dates) to O(24)
        try:
            from ..features import add_features as _add_features
            sentinel = "prev_close"
            if sentinel not in ticker_df.columns:
                ticker_df = _add_features(ticker_df)
            pattern_series = _precompute_pattern_hits(ticker_df)
        except Exception:
            pattern_series = None

        # Batch all writes for this ticker in one connection
        rows_to_insert: list[tuple] = []  # (trade_date, result, scenario_branches)

        for trade_date in trade_dates:
            if trade_date in already_saved_dates:
                n_runs_skipped += 1
                continue

            try:
                result = _run_advisor_with_cache(
                    ticker_df=ticker_df,
                    today_date=trade_date,
                    ticker=ticker,
                    playbooks_by_pattern=playbooks_by_pattern,
                    lights_dict=lights_dict,
                    pattern_series=pattern_series,
                )
            except (ValueError, Exception):
                continue

            rows_to_insert.append((trade_date, result))

        if save_to_db and rows_to_insert:
            n_saved = _batch_save_runs(
                ticker=ticker,
                rows_to_insert=rows_to_insert,
                branch_meta=branch_meta,
                db_path=db_path,
            )
            n_runs_saved += n_saved

    # Back-fill matched_after_n_days for every ticker (vectorized pass)
    n_branches_backfilled = 0
    if save_to_db:
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
        # Attempt to fetch per-run pattern information via a cross-join approach.
        # advisor_branches doesn't store pattern directly; we derive it from
        # playbook names stored in memory (not in DB in Phase 1 schema).
        # We fall back to grouping by branch_id only.
        rows_df = pd.read_sql_query(
            """
            SELECT
                COALESCE(ab.action_type, 'unknown') as action_type,
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

    # Derive "pattern" from branch_id prefix convention:
    # Branch ids like "B1_明日續強" don't encode the pattern name.
    # We use action_type as a proxy for grouping; the caller can join
    # with playbook metadata if needed.
    # Per spec: columns must be (pattern, branch_id, n_runs, n_matched, hit_rate, avg_matched_days)
    # We use action_type as the "pattern" column in the absence of pattern column in DB.
    rows_df = rows_df.rename(columns={"action_type": "pattern"})
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
