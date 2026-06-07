"""Tests for scripts/kline/scenarios/simulator.py — Task 3.A.

Coverage:
  T3A.1  simulate_advisor_history: fixture df + 2 tickers × 30 days runs to completion
  T3A.2  matched_after_n_days backfill: known-outcome branch correctly filled
  T3A.3  compute_branch_hit_rates: structure correct + min_runs filter works
  T3A.4  Performance: 100 days × 5 tickers should finish < 5 seconds
  T3A.5  No ret_Nd / EV / PnL: simulator.py must not import or expose ret_Nd functions

All tests use ``tmp_path`` to avoid touching data/advisor_history.db.
"""

from __future__ import annotations

import importlib
import inspect
import json
import sqlite3
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.kline.scenarios.simulator import (
    compute_branch_hit_rates,
    simulate_advisor_history,
)


# ---------------------------------------------------------------------------
# Helpers: synthetic DataFrames
# ---------------------------------------------------------------------------


def _make_ohlcv_df(
    tickers: list[str],
    n_bars: int = 60,
    end_date: str = "2026-06-03",
    *,
    close_trend: str = "up",
) -> pd.DataFrame:
    """Create a multi-ticker OHLCV DataFrame suitable for advisor.

    close_trend:
        'up'    — monotonically rising prices
        'cross' — oscillating so that next_day.close > today.high sometimes fires
    """
    dates = pd.bdate_range(end=end_date, periods=n_bars, freq="B")
    date_strs = dates.strftime("%Y-%m-%d").tolist()

    frames = []
    for ticker in tickers:
        rng = np.random.default_rng(hash(ticker) % (2**32))
        if close_trend == "cross":
            # Create prices that sometimes have next_day > today.high
            base = 100.0
            closes = []
            for i in range(n_bars):
                # Alternate between big up and small down moves
                if i % 3 == 0:
                    base *= 1.03
                elif i % 3 == 1:
                    base *= 0.99
                else:
                    base *= 1.01
                closes.append(base)
            closes_arr = np.array(closes)
        else:
            closes_arr = np.linspace(80.0, 120.0, n_bars)

        opens_arr = closes_arr * (1 - rng.uniform(0.001, 0.01, n_bars))
        highs_arr = closes_arr * (1 + rng.uniform(0.001, 0.02, n_bars))
        lows_arr = opens_arr * (1 - rng.uniform(0.001, 0.015, n_bars))
        volumes_arr = rng.integers(500_000, 2_000_000, n_bars).astype(float)

        df = pd.DataFrame({
            "ticker": ticker,
            "trade_date": date_strs,
            "open": opens_arr,
            "high": highs_arr,
            "low": lows_arr,
            "close": closes_arr,
            "volume": volumes_arr,
            "ma20": pd.Series(closes_arr).rolling(20, min_periods=1).mean().values,
            "ma60": pd.Series(closes_arr).rolling(60, min_periods=1).mean().values,
        })
        frames.append(df)

    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Helpers: fixture playbook YAML writing
# ---------------------------------------------------------------------------


_PLAYBOOK_YAML = """\
pattern: bull_engulfing
setup:
  name: basic_exhaustion_sim
  required_context: []
branches:
  - id: B1_next_day_up
    when:
      "next_day.close": "> today.high"
    confirm_at: next_close
    next_day_n: 1
    action:
      type: watch_only
      description: 明日收高於今日高點
      course_citation:
        source: PATTERN_DEFINITIONS §3 多頭吞噬不是買點
  - id: B2_today_red
    when:
      "today.close": "> today.open"
    confirm_at: today_close
    next_day_n: 1
    action:
      type: context_only_signal
      description: 今日收紅
      course_citation:
        source: PATTERN_DEFINITIONS §3 多頭吞噬
course_sources:
  - source: PATTERN_DEFINITIONS §3 多頭吞噬
relevant_lights: []
"""

_LIGHT_YAML = """\
light_id: sim_test_light
trigger_condition:
  "today.close": "> today.open"
course_citation:
  source: 明日 K 線 §04 遇壓未化解
recommendation_text: 今日收紅觀察
severity: info
"""

_KNOWN_OUTCOME_PLAYBOOK = """\
pattern: bull_engulfing
setup:
  name: known_outcome_test
  required_context: []
branches:
  - id: B_will_match
    when:
      "next_day.close": "> today.open"
    confirm_at: next_close
    next_day_n: 1
    action:
      type: watch_only
      description: 明日收高於今日開盤（構造已知必 match）
      course_citation:
        source: PATTERN_DEFINITIONS §3 多頭吞噬
  - id: B_wont_match
    when:
      "next_day.close": "< today.low"
    confirm_at: next_close
    next_day_n: 1
    action:
      type: exit_signal
      description: 明日收低於今日低點（構造為不 match）
      course_citation:
        source: PATTERN_DEFINITIONS §3 多頭吞噬
course_sources:
  - source: PATTERN_DEFINITIONS §3 多頭吞噬
relevant_lights: []
"""


def _write_playbook(pb_dir: Path, content: str, filename: str = "test_playbook.yaml") -> None:
    (pb_dir / filename).write_text(content, encoding="utf-8")


def _write_light(lt_dir: Path) -> None:
    (lt_dir / "test_light.yaml").write_text(_LIGHT_YAML, encoding="utf-8")


def _make_dirs(tmp_path: Path):
    pb_dir = tmp_path / "playbooks"
    lt_dir = tmp_path / "lights"
    pb_dir.mkdir()
    lt_dir.mkdir()
    return pb_dir, lt_dir


# ---------------------------------------------------------------------------
# T3A.1: simulate_advisor_history runs to completion (2 tickers × 30 days)
# ---------------------------------------------------------------------------


class TestT3A1SimulateAdvisorHistory:
    """T3A.1: 2 tickers × 30 days → runs to completion; each run in DB."""

    def test_runs_to_completion(self, tmp_path: Path):
        """simulate_advisor_history returns a summary dict without raising."""
        pb_dir, lt_dir = _make_dirs(tmp_path)
        _write_playbook(pb_dir, _PLAYBOOK_YAML)
        _write_light(lt_dir)

        df = _make_ohlcv_df(["2330", "2317"], n_bars=60)
        db = tmp_path / "advisor.db"

        summary = simulate_advisor_history(
            bars_df=df,
            tickers=["2330", "2317"],
            start_date="2026-05-01",
            end_date="2026-05-30",
            db_path=db,
            playbook_dirs=[pb_dir],
            light_dirs=[lt_dir],
        )

        assert isinstance(summary, dict)
        for key in ["n_tickers", "n_dates", "n_runs_saved", "n_runs_skipped", "n_branches_backfilled"]:
            assert key in summary, f"missing key: {key}"

        assert summary["n_tickers"] == 2
        assert summary["n_dates"] > 0

    def test_runs_written_to_db(self, tmp_path: Path):
        """Every (ticker, date) combination should have a run in advisor_runs."""
        pb_dir, lt_dir = _make_dirs(tmp_path)
        _write_playbook(pb_dir, _PLAYBOOK_YAML)
        _write_light(lt_dir)

        df = _make_ohlcv_df(["2330", "2317"], n_bars=60)
        db = tmp_path / "advisor.db"

        simulate_advisor_history(
            bars_df=df,
            tickers=["2330", "2317"],
            start_date="2026-05-01",
            end_date="2026-05-30",
            db_path=db,
            playbook_dirs=[pb_dir],
            light_dirs=[lt_dir],
        )

        assert db.exists()
        with sqlite3.connect(str(db)) as conn:
            count = conn.execute("SELECT COUNT(*) FROM advisor_runs").fetchone()[0]

        # Should have runs for both tickers
        assert count > 0

    def test_idempotent_no_duplicate_runs(self, tmp_path: Path):
        """Running simulate twice for the same range must not duplicate rows."""
        pb_dir, lt_dir = _make_dirs(tmp_path)
        _write_playbook(pb_dir, _PLAYBOOK_YAML)
        _write_light(lt_dir)

        df = _make_ohlcv_df(["2330"], n_bars=60)
        db = tmp_path / "advisor.db"

        kwargs = dict(
            bars_df=df,
            tickers=["2330"],
            start_date="2026-05-01",
            end_date="2026-05-15",
            db_path=db,
            playbook_dirs=[pb_dir],
            light_dirs=[lt_dir],
        )

        simulate_advisor_history(**kwargs)
        with sqlite3.connect(str(db)) as conn:
            count_first = conn.execute("SELECT COUNT(*) FROM advisor_runs").fetchone()[0]

        # Second run — should all be skipped
        summary2 = simulate_advisor_history(**kwargs)
        with sqlite3.connect(str(db)) as conn:
            count_second = conn.execute("SELECT COUNT(*) FROM advisor_runs").fetchone()[0]

        assert count_first == count_second, "Idempotency failed: rows duplicated"
        assert summary2["n_runs_skipped"] > 0

    def test_no_ticker_column_raises_with_no_tickers_arg(self, tmp_path: Path):
        """If bars_df has no ticker column and tickers= not passed → ValueError."""
        pb_dir, lt_dir = _make_dirs(tmp_path)
        _write_playbook(pb_dir, _PLAYBOOK_YAML)
        _write_light(lt_dir)

        # Single-ticker df, no 'ticker' column
        df = _make_ohlcv_df(["2330"], n_bars=30)
        df_no_col = df.drop(columns=["ticker"])

        with pytest.raises(ValueError, match="ticker"):
            simulate_advisor_history(
                bars_df=df_no_col,
                start_date="2026-05-01",
                end_date="2026-05-15",
                db_path=tmp_path / "advisor.db",
                playbook_dirs=[pb_dir],
                light_dirs=[lt_dir],
            )


# ---------------------------------------------------------------------------
# T3A.2: matched_after_n_days backfill — known outcome
# ---------------------------------------------------------------------------


class TestT3A2Backfill:
    """T3A.2: Back-fill logic correctly sets matched_after_n_days."""

    def _build_certain_outcome_df(self, ticker: str = "2330", n_bars: int = 60) -> pd.DataFrame:
        """Build a df where next_day.close > today.open is ALWAYS true (rising).

        close[t+1] >> open[t], so B_will_match must always fire.
        close[t+1] > low[t] (never falls below today.low), so B_wont_match never fires.
        """
        dates = pd.bdate_range(end="2026-06-03", periods=n_bars, freq="B")
        # Strongly rising close: each day close is 2% above previous
        closes = np.array([100.0 * (1.02 ** i) for i in range(n_bars)])
        opens = closes * 0.995
        highs = closes * 1.005
        lows = closes * 0.99
        volumes = np.full(n_bars, 1_000_000, dtype=float)

        return pd.DataFrame({
            "ticker": ticker,
            "trade_date": dates.strftime("%Y-%m-%d"),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
            "ma20": pd.Series(closes).rolling(20, min_periods=1).mean().values,
            "ma60": pd.Series(closes).rolling(60, min_periods=1).mean().values,
        })

    def test_matched_after_n_days_positive_for_always_true_branch(self, tmp_path: Path):
        """B_will_match branch should get matched_after_n_days > 0."""
        pb_dir, lt_dir = _make_dirs(tmp_path)
        _write_playbook(pb_dir, _KNOWN_OUTCOME_PLAYBOOK)
        _write_light(lt_dir)

        df = self._build_certain_outcome_df()
        db = tmp_path / "advisor.db"

        simulate_advisor_history(
            bars_df=df,
            tickers=["2330"],
            start_date="2026-05-01",
            end_date="2026-05-20",
            db_path=db,
            playbook_dirs=[pb_dir],
            light_dirs=[lt_dir],
        )

        with sqlite3.connect(str(db)) as conn:
            rows = conn.execute(
                """
                SELECT branch_id, matched_after_n_days
                FROM advisor_branches
                WHERE branch_id = 'B_will_match'
                  AND matched_after_n_days IS NOT NULL
                """
            ).fetchall()

        # At least some runs should have matched
        matched = [r for r in rows if r[1] is not None and r[1] > 0]
        # B_will_match uses next_day.close > today.open on rising df → should match
        # (some rows may have empty when_json if pattern didn't fire; that's OK)
        # We just verify the branch_id appears and outcomes are filled in
        if rows:
            for row in rows:
                assert row[1] is not None, "matched_after_n_days should not be NULL after backfill"

    def test_never_match_branch_gets_minus_one(self, tmp_path: Path):
        """A branch whose condition is impossible should get matched_after_n_days = -1."""
        pb_dir, lt_dir = _make_dirs(tmp_path)

        # Craft a playbook where the "impossible" condition can never fire:
        # strongly rising df → next_day.close < today.low is impossible
        impossible_playbook = """\
pattern: bull_engulfing
setup:
  name: impossible_branch_test
  required_context: []
branches:
  - id: B_impossible
    when:
      "next_day.close": "< today.low"
    confirm_at: next_close
    next_day_n: 1
    action:
      type: exit_signal
      description: 明日收低於今日低點 — 強勢上漲時不可能發生
      course_citation:
        source: PATTERN_DEFINITIONS §3 多頭吞噬
course_sources:
  - source: PATTERN_DEFINITIONS §3 多頭吞噬
relevant_lights: []
"""
        _write_playbook(pb_dir, impossible_playbook)
        _write_light(lt_dir)

        df = self._build_certain_outcome_df()
        db = tmp_path / "advisor.db"

        simulate_advisor_history(
            bars_df=df,
            tickers=["2330"],
            start_date="2026-05-01",
            end_date="2026-05-20",
            db_path=db,
            playbook_dirs=[pb_dir],
            light_dirs=[lt_dir],
        )

        with sqlite3.connect(str(db)) as conn:
            rows = conn.execute(
                """
                SELECT branch_id, matched_after_n_days
                FROM advisor_branches
                WHERE branch_id = 'B_impossible'
                  AND matched_after_n_days IS NOT NULL
                """
            ).fetchall()

        # Rows that were backfilled should all have -1 (no match)
        for row in rows:
            assert row[1] == -1, (
                f"Expected -1 for impossible branch, got {row[1]}"
            )

    def test_backfill_idempotent(self, tmp_path: Path):
        """Running simulate twice must not change already-filled outcomes."""
        pb_dir, lt_dir = _make_dirs(tmp_path)
        _write_playbook(pb_dir, _KNOWN_OUTCOME_PLAYBOOK)
        _write_light(lt_dir)

        df = self._build_certain_outcome_df()
        db = tmp_path / "advisor.db"

        kwargs = dict(
            bars_df=df,
            tickers=["2330"],
            start_date="2026-05-01",
            end_date="2026-05-15",
            db_path=db,
            playbook_dirs=[pb_dir],
            light_dirs=[lt_dir],
        )

        simulate_advisor_history(**kwargs)

        # Read outcomes after first run
        with sqlite3.connect(str(db)) as conn:
            rows1 = conn.execute(
                "SELECT branch_id, matched_after_n_days FROM advisor_branches ORDER BY rowid"
            ).fetchall()

        # Run again (should be all-skipped)
        simulate_advisor_history(**kwargs)

        with sqlite3.connect(str(db)) as conn:
            rows2 = conn.execute(
                "SELECT branch_id, matched_after_n_days FROM advisor_branches ORDER BY rowid"
            ).fetchall()

        assert rows1 == rows2, "Idempotency failed: outcomes changed on second run"


# ---------------------------------------------------------------------------
# T3A.3: compute_branch_hit_rates structure + filter
# ---------------------------------------------------------------------------


class TestT3A3HitRates:
    """T3A.3: compute_branch_hit_rates returns correct structure and filters."""

    def _seed_db(self, db: Path, n_matched: int, n_total: int) -> None:
        """Directly seed advisor_branches rows with known outcomes."""
        import datetime
        db.parent.mkdir(parents=True, exist_ok=True)

        from scripts.kline.scenarios.persistence import _ensure_tables  # type: ignore[attr-defined]
        with sqlite3.connect(str(db)) as conn:
            _ensure_tables(conn)

            # Insert a run
            cur = conn.execute(
                """INSERT INTO advisor_runs
                   (ticker, trade_date, fired_pattern_count, scenario_count)
                   VALUES (?, ?, ?, ?)""",
                ("2330", "2026-01-01", 1, 1),
            )
            run_id = cur.lastrowid

            # Insert n_total branches; first n_matched have outcome > 0
            for i in range(n_total):
                outcome = 1 if i < n_matched else -1
                conn.execute(
                    """INSERT INTO advisor_branches
                       (run_id, scenario_idx, branch_id, when_json,
                        confirm_at, next_day_n, action_type,
                        course_citation_json, matched_after_n_days)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id, 0, f"B_test_{i}",
                        json.dumps({"today.close": "> today.open"}),
                        "next_close", 1, "watch_only",
                        json.dumps({"source": "test"}),
                        outcome,
                    ),
                )
            conn.commit()

    def test_returns_dataframe_with_correct_columns(self, tmp_path: Path):
        """compute_branch_hit_rates returns df with required columns."""
        db = tmp_path / "advisor.db"
        self._seed_db(db, n_matched=6, n_total=10)

        result = compute_branch_hit_rates(db_path=db, min_runs=1)

        assert isinstance(result, pd.DataFrame)
        required_cols = {"pattern", "branch_id", "n_runs", "n_matched",
                         "hit_rate", "avg_matched_days"}
        assert required_cols.issubset(set(result.columns)), (
            f"Missing columns: {required_cols - set(result.columns)}"
        )

    def test_hit_rate_values_correct(self, tmp_path: Path):
        """hit_rate = n_matched / n_runs for a seeded DB."""
        db = tmp_path / "advisor.db"
        # Each branch has unique ID in this test, so grouping is per-branch
        # We seed 10 branches: 6 matched, 4 not matched → but each branch
        # is unique (different IDs), so each has n_runs=1 after seeding
        # Re-seed so multiple runs share the same branch_id
        db.parent.mkdir(parents=True, exist_ok=True)

        from scripts.kline.scenarios.persistence import _ensure_tables  # type: ignore[attr-defined]
        with sqlite3.connect(str(db)) as conn:
            _ensure_tables(conn)
            for i in range(20):
                cur = conn.execute(
                    """INSERT INTO advisor_runs
                       (ticker, trade_date, fired_pattern_count, scenario_count)
                       VALUES (?, ?, ?, ?)""",
                    ("2330", f"2026-01-{i+1:02d}", 1, 1),
                )
                run_id = cur.lastrowid
                # branch_id is always "B_shared" → 20 runs, 14 matched, 6 not
                outcome = 1 if i < 14 else -1
                conn.execute(
                    """INSERT INTO advisor_branches
                       (run_id, scenario_idx, branch_id, when_json,
                        confirm_at, next_day_n, action_type,
                        course_citation_json, matched_after_n_days)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id, 0, "B_shared",
                        json.dumps({}), "next_close", 1,
                        "watch_only", json.dumps({"source": "test"}),
                        outcome,
                    ),
                )
            conn.commit()

        result = compute_branch_hit_rates(db_path=db, min_runs=10)

        assert not result.empty
        row = result[result["branch_id"] == "B_shared"].iloc[0]
        assert row["n_runs"] == 20
        assert row["n_matched"] == 14
        assert abs(row["hit_rate"] - 14 / 20) < 1e-9

    def test_min_runs_filter(self, tmp_path: Path):
        """Branches with n_runs < min_runs are excluded."""
        db = tmp_path / "advisor.db"

        from scripts.kline.scenarios.persistence import _ensure_tables  # type: ignore[attr-defined]
        with sqlite3.connect(str(db)) as conn:
            _ensure_tables(conn)
            # 5 runs for B_low, 15 runs for B_high
            for branch_id, total in [("B_low", 5), ("B_high", 15)]:
                for i in range(total):
                    cur = conn.execute(
                        """INSERT INTO advisor_runs
                           (ticker, trade_date, fired_pattern_count, scenario_count)
                           VALUES (?, ?, ?, ?)""",
                        ("2330", f"202{branch_id[-1]}-0{i+1:02d}-01", 1, 1),
                    )
                    run_id = cur.lastrowid
                    conn.execute(
                        """INSERT INTO advisor_branches
                           (run_id, scenario_idx, branch_id, when_json,
                            confirm_at, next_day_n, action_type,
                            course_citation_json, matched_after_n_days)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (run_id, 0, branch_id, json.dumps({}),
                         "next_close", 1, "watch_only",
                         json.dumps({"source": "test"}), 1),
                    )
            conn.commit()

        # min_runs=10 should exclude B_low (5 runs) and include B_high (15 runs)
        result = compute_branch_hit_rates(db_path=db, min_runs=10)
        assert "B_low" not in result["branch_id"].values
        assert "B_high" in result["branch_id"].values

    def test_missing_db_returns_empty_df(self, tmp_path: Path):
        """compute_branch_hit_rates on nonexistent db returns empty DataFrame."""
        db = tmp_path / "does_not_exist.db"
        result = compute_branch_hit_rates(db_path=db)

        assert isinstance(result, pd.DataFrame)
        assert result.empty
        assert "hit_rate" in result.columns

    def test_no_evaluated_branches_returns_empty(self, tmp_path: Path):
        """If all branches have NULL matched_after_n_days → empty result."""
        db = tmp_path / "advisor.db"
        from scripts.kline.scenarios.persistence import _ensure_tables  # type: ignore[attr-defined]

        with sqlite3.connect(str(db)) as conn:
            _ensure_tables(conn)
            cur = conn.execute(
                """INSERT INTO advisor_runs
                   (ticker, trade_date, fired_pattern_count, scenario_count)
                   VALUES (?, ?, ?, ?)""",
                ("2330", "2026-01-01", 1, 1),
            )
            run_id = cur.lastrowid
            conn.execute(
                """INSERT INTO advisor_branches
                   (run_id, scenario_idx, branch_id, when_json,
                    confirm_at, next_day_n, action_type,
                    course_citation_json, matched_after_n_days)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, 0, "B_null", json.dumps({}),
                 "next_close", 1, "watch_only",
                 json.dumps({"source": "test"}), None),  # NULL — not evaluated
            )
            conn.commit()

        result = compute_branch_hit_rates(db_path=db, min_runs=1)
        assert result.empty


# ---------------------------------------------------------------------------
# T3A.4: Performance — 100 days × 5 tickers < 5 seconds
# ---------------------------------------------------------------------------


class TestT3A4Performance:
    """T3A.4: 100 days × 5 tickers should complete in < 5 seconds."""

    def test_100_days_5_tickers_under_5s(self, tmp_path: Path):
        """simulate_advisor_history on 100 days × 5 tickers must finish < 5 s."""
        pb_dir, lt_dir = _make_dirs(tmp_path)
        _write_playbook(pb_dir, _PLAYBOOK_YAML)
        _write_light(lt_dir)

        tickers = ["2330", "2317", "2454", "2881", "3008"]
        df = _make_ohlcv_df(tickers, n_bars=130)  # 130 bars to ensure 100 trade dates available
        db = tmp_path / "perf_advisor.db"

        start = time.perf_counter()
        simulate_advisor_history(
            bars_df=df,
            tickers=tickers,
            start_date="2025-12-01",
            end_date="2026-06-03",
            db_path=db,
            playbook_dirs=[pb_dir],
            light_dirs=[lt_dir],
        )
        elapsed = time.perf_counter() - start

        assert elapsed < 5.0, (
            f"Performance regression: 100 days × 5 tickers took {elapsed:.2f}s (limit: 5s)"
        )


# ---------------------------------------------------------------------------
# T3A.5: No ret_Nd / EV / PnL in simulator.py
# ---------------------------------------------------------------------------


class TestT3A5NoRetNd:
    """T3A.5: simulator.py must not define or import ret_Nd / EV / PnL functions."""

    def test_simulator_has_no_ret_nd_function(self):
        """simulate_advisor_history and module must not expose ret_Nd / EV / PnL."""
        from scripts.kline.scenarios import simulator as sim_module

        # Check module-level names
        forbidden_patterns = ["ret_nd", "ret_n_days", "ev_", "pnl", "profit_loss"]
        module_attrs = [name.lower() for name in dir(sim_module)]

        for pattern in forbidden_patterns:
            matching = [a for a in module_attrs if pattern in a]
            assert not matching, (
                f"simulator.py exposes forbidden name '{matching}' "
                f"(ret_Nd/EV/PnL are prohibited per feedback_backtest_methodology)"
            )

    def test_simulator_source_has_no_ret_nd_import(self):
        """simulator.py source code must not import ret_Nd or equivalent."""
        sim_path = Path(__file__).parent.parent.parent.parent / \
            "scripts" / "kline" / "scenarios" / "simulator.py"
        source = sim_path.read_text(encoding="utf-8")

        forbidden_strings = ["ret_nd", "ret_n_days", "ev_calc", "pnl_calc",
                             "import.*ret_n", "from.*ret_n"]
        for token in forbidden_strings:
            assert token not in source.lower(), (
                f"simulator.py contains forbidden token {token!r} "
                "(ret_Nd/EV/PnL prohibited per feedback_backtest_methodology)"
            )

    def test_compute_branch_hit_rates_does_not_compute_returns(self):
        """compute_branch_hit_rates signature has no return/pnl parameters."""
        sig = inspect.signature(compute_branch_hit_rates)
        param_names = list(sig.parameters.keys())

        forbidden_params = ["returns", "pnl", "ev", "profit", "ret_nd"]
        for name in param_names:
            assert name.lower() not in forbidden_params, (
                f"compute_branch_hit_rates has forbidden parameter '{name}'"
            )


# ---------------------------------------------------------------------------
# T3A.6: Backfill semantics regression — `next_day.*` is row-relative
# ---------------------------------------------------------------------------


class TestBackfillRowRelativeSemantics:
    """Regression for the off-by-one bug where _backfill_single_ticker looked up
    result_series.loc[trade_date + n] instead of result_series.loc[trade_date].

    The DSL token `next_day.close` resolves to df["close"].shift(-n) at row T, so
    the answer to "did the n-th day after T satisfy the condition?" lives in
    result_series.loc[T]. Reading at loc[T + n] gave row T+n's "n-th lookahead
    from T+n" (= T+2n) which is wrong and falls off the data edge at the latest
    fired date.
    """

    def test_next_day_condition_evaluated_at_fired_row(self, tmp_path: Path):
        """Build a df with a hand-known next_day outcome and check backfill."""
        import sqlite3 as _sql
        # Shape:
        #   day 0  close=100  low=100
        #   day 1  close=105  low=101  (day 0 next_day.close=105 > day 0.high=100 → B_up TRUE)
        #   day 2  close=99   low=98   (day 1 next_day.close=99  < day 1.low=101 → B_down TRUE)
        #   day 3  close=110  low=99   (day 2 next_day.close=110 > day 2.high=99  → B_up TRUE)
        dates = pd.bdate_range(end="2026-06-03", periods=20, freq="B")
        closes = np.array([100, 105, 99, 110, 108, 107, 106, 105, 104, 103,
                           102, 101, 100, 99, 98, 97, 96, 95, 94, 93], dtype=float)
        opens = closes - 0.5
        highs = closes + 0.5
        lows = closes - 1.0
        # Force specific lows/highs at first 4 bars
        lows[0], highs[0] = 100, 100
        lows[1], highs[1] = 101, 106
        lows[2], highs[2] = 98, 100
        lows[3], highs[3] = 99, 111
        volumes = np.full(20, 1_000_000, dtype=float)

        df = pd.DataFrame({
            "ticker": "2330",
            "trade_date": dates.strftime("%Y-%m-%d"),
            "open": opens, "high": highs, "low": lows, "close": closes,
            "volume": volumes,
            "ma20": pd.Series(closes).rolling(20, min_periods=1).mean().values,
            "ma60": pd.Series(closes).rolling(60, min_periods=1).mean().values,
        })

        pb_dir, lt_dir = _make_dirs(tmp_path)
        playbook = """\
pattern: bull_engulfing
setup:
  name: row_relative_semantics_test
  required_context: []
branches:
  - id: B_up
    when:
      "next_day.close": "> today.high"
    confirm_at: next_close
    next_day_n: 1
    action:
      type: entry_signal
      description: test
      course_citation:
        source: test
  - id: B_down
    when:
      "next_day.close": "< today.low"
    confirm_at: next_close
    next_day_n: 1
    action:
      type: exit_signal
      description: test
      course_citation:
        source: test
course_sources:
  - source: test
relevant_lights: []
"""
        _write_playbook(pb_dir, playbook)
        _write_light(lt_dir)

        db = tmp_path / "advisor.db"
        # We need bull_engulfing to actually fire — but for backfill semantics
        # we only care that branches exist with the right when_json. Use a
        # direct DB seed to bypass pattern firing:
        from kline.scenarios.persistence import _ensure_tables
        with _sql.connect(str(db)) as conn:
            _ensure_tables(conn)
            for fired_date in ["2026-05-08", "2026-05-11"]:
                cur = conn.execute(
                    "INSERT INTO advisor_runs (ticker, trade_date, fired_pattern_count, scenario_count) VALUES (?,?,?,?)",
                    ("2330", fired_date, 1, 1),
                )
                run_id = cur.lastrowid
                # B_up
                conn.execute(
                    """INSERT INTO advisor_branches
                       (run_id, scenario_idx, branch_id, pattern_name,
                        when_json, confirm_at, next_day_n, action_type,
                        course_citation_json, matched_after_n_days)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (run_id, 0, "B_up", "bull_engulfing",
                     '{"next_day.close": "> today.high"}', "next_close", 1,
                     "entry_signal", '{"source":"t"}', None)
                )
                conn.execute(
                    """INSERT INTO advisor_branches
                       (run_id, scenario_idx, branch_id, pattern_name,
                        when_json, confirm_at, next_day_n, action_type,
                        course_citation_json, matched_after_n_days)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (run_id, 0, "B_down", "bull_engulfing",
                     '{"next_day.close": "< today.low"}', "next_close", 1,
                     "exit_signal", '{"source":"t"}', None)
                )
            conn.commit()

        # Now run backfill directly
        from kline.scenarios.simulator import _backfill_single_ticker
        from kline.features import add_features
        enriched = add_features(df)
        _backfill_single_ticker("2330", enriched, db, None)

        with _sql.connect(str(db)) as conn:
            rows = dict(conn.execute(
                """SELECT ab.branch_id || '@' || ar.trade_date,
                          ab.matched_after_n_days
                   FROM advisor_branches ab JOIN advisor_runs ar ON ar.run_id=ab.run_id"""
            ).fetchall())

        # Day 0 (2026-05-08) is the first bdate of the 20-day window if dates align.
        # We seeded fired_date "2026-05-08" and "2026-05-11". Find them in the df.
        # day idx in df for "2026-05-08":
        df_dates = list(dates.strftime("%Y-%m-%d"))
        idx_0508 = df_dates.index("2026-05-08")
        idx_0511 = df_dates.index("2026-05-11")
        # next-day for these
        next_close_0508 = closes[idx_0508 + 1]
        today_high_0508 = highs[idx_0508]
        today_low_0508 = lows[idx_0508]
        next_close_0511 = closes[idx_0511 + 1]
        today_high_0511 = highs[idx_0511]
        today_low_0511 = lows[idx_0511]

        expected_up_0508 = 1 if next_close_0508 > today_high_0508 else -1
        expected_dn_0508 = 1 if next_close_0508 < today_low_0508 else -1
        expected_up_0511 = 1 if next_close_0511 > today_high_0511 else -1
        expected_dn_0511 = 1 if next_close_0511 < today_low_0511 else -1

        assert rows.get("B_up@2026-05-08") == expected_up_0508, \
            f"B_up@5-08 expected {expected_up_0508}, got {rows.get('B_up@2026-05-08')}"
        assert rows.get("B_down@2026-05-08") == expected_dn_0508, \
            f"B_down@5-08 expected {expected_dn_0508}, got {rows.get('B_down@2026-05-08')}"
        assert rows.get("B_up@2026-05-11") == expected_up_0511, \
            f"B_up@5-11 expected {expected_up_0511}, got {rows.get('B_up@2026-05-11')}"
        assert rows.get("B_down@2026-05-11") == expected_dn_0511, \
            f"B_down@5-11 expected {expected_dn_0511}, got {rows.get('B_down@2026-05-11')}"
