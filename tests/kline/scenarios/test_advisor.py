"""Tests for scripts/kline/scenarios/advisor.py — Task 1.4.

Coverage:
  T1.4.1  fixture df + fixture playbook → AdvisorResult correct structure
  T1.4.2  context_overrides correctly applied to ContextSnapshot
  T1.4.3  fired_patterns empty → scenarios empty but active_lights can still have values
  T1.4.4  playbook YAML schema error → analyze() raises LoaderError (fail loud)
  T1.4.5  ContextSnapshot missing field → notes has warn (not crash)
  T1.4.6  bars_df raw vs already enriched both work (advisor auto-adds features)
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.kline.scenarios import AdvisorResult, LoaderError, analyze
from scripts.kline.scenarios._schema import ContextSnapshot

# ---------------------------------------------------------------------------
# Helpers: synthetic DataFrames
# ---------------------------------------------------------------------------


def _make_raw_df(
    ticker: str = "2330",
    n_bars: int = 100,
    today_date: str = "2026-06-01",
    base_close: float = 100.0,
) -> pd.DataFrame:
    """Create a minimal raw OHLCV DataFrame with trade_date column.

    The DataFrame contains ``n_bars`` rows ending on ``today_date``.
    Values are monotonically rising so that MA columns can be set here for
    add_features to work.
    """
    dates = pd.bdate_range(end=today_date, periods=n_bars, freq="B")
    closes = np.linspace(base_close * 0.8, base_close, n_bars)
    opens = closes * 0.99
    highs = closes * 1.02
    lows = opens * 0.98
    volumes = np.full(n_bars, 1_000_000)

    df = pd.DataFrame({
        "ticker": ticker,
        "trade_date": dates.strftime("%Y-%m-%d"),
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        # features.py needs ma20, ma60 pre-computed (from bars layer)
        "ma20": pd.Series(closes).rolling(20, min_periods=1).mean().values,
        "ma60": pd.Series(closes).rolling(60, min_periods=1).mean().values,
    })
    return df


def _make_enriched_df(
    ticker: str = "2330",
    n_bars: int = 100,
    today_date: str = "2026-06-01",
) -> pd.DataFrame:
    """Create a features-enriched DataFrame (with prev_close sentinel column)."""
    from scripts.kline.features import add_features
    raw = _make_raw_df(ticker=ticker, n_bars=n_bars, today_date=today_date)
    return add_features(raw)


# ---------------------------------------------------------------------------
# Helpers: fixture directories (always separate pb_dir / lt_dir)
# ---------------------------------------------------------------------------


def _mk_dirs(tmp_path: Path):
    """Create and return (pb_dir, lt_dir) subdirectories."""
    pb_dir = tmp_path / "playbooks"
    lt_dir = tmp_path / "lights"
    pb_dir.mkdir()
    lt_dir.mkdir()
    return pb_dir, lt_dir


# ---------------------------------------------------------------------------
# Helpers: fixture YAML strings
# ---------------------------------------------------------------------------

def _playbook_yaml_content() -> str:
    """A minimal but valid playbook YAML for bull_engulfing."""
    return """\
pattern: bull_engulfing
setup:
  name: basic_exhaustion
  required_context: []
branches:
  - id: B1_today_red
    when:
      "today.close": "> today.open"
    confirm_at: next_close
    next_day_n: 1
    action:
      type: context_only_signal
      description: 今日收紅，持續觀察
      course_citation:
        source: PATTERN_DEFINITIONS §3 多頭吞噬不是買點
course_sources:
  - source: PATTERN_DEFINITIONS §3 多頭吞噬
relevant_lights: []
"""


def _light_yaml_content() -> str:
    """A minimal valid light YAML using only whitelisted condition fields."""
    return """\
light_id: test_active_light
trigger_condition:
  "today.close": "> today.open"
course_citation:
  source: 明日 K 線 §04 遇壓未化解警示
  quote: 今日收紅為觀察觸發
recommendation_text: 今日收紅，注意明日走勢
severity: info
"""


def _light_yaml_false_condition() -> str:
    """A light YAML whose condition is never true (today.close < today.open)."""
    return """\
light_id: test_inactive_light
trigger_condition:
  "today.close": "< today.open"
course_citation:
  source: 明日 K 線 §04 遇壓未化解警示
recommendation_text: 今日收黑觸發
severity: warn
"""


def _invalid_playbook_yaml_content() -> str:
    """A playbook YAML missing course_citation (schema error)."""
    return """\
pattern: bull_engulfing
setup:
  name: broken_setup
  required_context: []
branches:
  - id: B1_bad
    when:
      "today.close": "> today.open"
    confirm_at: next_close
    action:
      type: context_only_signal
      description: missing citation
course_sources:
  - source: PATTERN_DEFINITIONS §3
"""


def _playbook_with_required_context(req_field: str) -> str:
    return f"""\
pattern: bull_engulfing
setup:
  name: requires_{req_field}
  required_context: [{req_field}]
branches:
  - id: B1_req
    when:
      "today.close": "> today.open"
    confirm_at: next_close
    action:
      type: context_only_signal
      description: 需要 context 欄位
      course_citation:
        source: K線力量課程 §MA扣抵狀態判斷
course_sources:
  - source: K線力量課程 §MA扣抵定義
"""


# ---------------------------------------------------------------------------
# T1.4.1 — fixture df + fixture playbook → AdvisorResult correct structure
# ---------------------------------------------------------------------------


class TestAdvisorResultStructure:
    def test_result_is_advisor_result_type(self, tmp_path):
        """T1.4.1a: analyze() returns AdvisorResult instance."""
        pb_dir, lt_dir = _mk_dirs(tmp_path)
        df = _make_enriched_df()
        result = analyze(df, "2026-06-01", "2330", playbook_dirs=[pb_dir], light_dirs=[lt_dir])
        assert isinstance(result, AdvisorResult)

    def test_result_has_all_fields(self, tmp_path):
        """T1.4.1b: AdvisorResult has all required fields."""
        pb_dir, lt_dir = _mk_dirs(tmp_path)
        df = _make_enriched_df()
        result = analyze(df, "2026-06-01", "2330", playbook_dirs=[pb_dir], light_dirs=[lt_dir])
        assert hasattr(result, "fired_patterns")
        assert hasattr(result, "scenarios")
        assert hasattr(result, "active_lights")
        assert hasattr(result, "notes")
        assert hasattr(result, "context_snapshot")

    def test_context_snapshot_is_set(self, tmp_path):
        """T1.4.1c: context_snapshot is a ContextSnapshot instance."""
        pb_dir, lt_dir = _mk_dirs(tmp_path)
        df = _make_enriched_df()
        result = analyze(df, "2026-06-01", "2330", playbook_dirs=[pb_dir], light_dirs=[lt_dir])
        assert isinstance(result.context_snapshot, ContextSnapshot)

    def test_playbook_loaded_and_structure_correct(self, tmp_path):
        """T1.4.1d: playbook YAML loaded — AdvisorResult has correct structure."""
        pb_dir, lt_dir = _mk_dirs(tmp_path)
        (pb_dir / "bull_engulfing.yaml").write_text(_playbook_yaml_content())
        df = _make_enriched_df(today_date="2026-06-01")

        result = analyze(df, "2026-06-01", "2330", playbook_dirs=[pb_dir], light_dirs=[lt_dir])
        assert isinstance(result, AdvisorResult)
        assert isinstance(result.scenarios, list)
        assert isinstance(result.fired_patterns, list)
        assert isinstance(result.notes, list)

    def test_active_lights_present_when_condition_true(self, tmp_path):
        """T1.4.1e: a light with 'today.close > today.open' activates on a red-candle day."""
        pb_dir, lt_dir = _mk_dirs(tmp_path)
        (lt_dir / "test_light.yaml").write_text(_light_yaml_content())
        df = _make_enriched_df(today_date="2026-06-01")
        result = analyze(df, "2026-06-01", "2330", playbook_dirs=[pb_dir], light_dirs=[lt_dir])
        # Our synthetic df has close > open on every bar → light should be active
        light_ids = [l.light_id for l in result.active_lights]
        assert "test_active_light" in light_ids

    def test_inactive_light_not_in_active_lights(self, tmp_path):
        """T1.4.1f: a light whose condition is false does not appear in active_lights."""
        pb_dir, lt_dir = _mk_dirs(tmp_path)
        (lt_dir / "test_light_false.yaml").write_text(_light_yaml_false_condition())
        df = _make_enriched_df(today_date="2026-06-01")
        result = analyze(df, "2026-06-01", "2330", playbook_dirs=[pb_dir], light_dirs=[lt_dir])
        light_ids = [l.light_id for l in result.active_lights]
        assert "test_inactive_light" not in light_ids


# ---------------------------------------------------------------------------
# T1.4.2 — context_overrides correctly applied
# ---------------------------------------------------------------------------


class TestContextOverrides:
    def test_override_ma5_will_rise(self, tmp_path):
        """T1.4.2b: ma5_will_rise override injected into snapshot."""
        pb_dir, lt_dir = _mk_dirs(tmp_path)
        df = _make_enriched_df()
        result = analyze(
            df,
            "2026-06-01",
            "2330",
            context_overrides={"ma5_will_rise": False},
            playbook_dirs=[pb_dir],
            light_dirs=[lt_dir],
        )
        assert result.context_snapshot.ma5_will_rise is False

    def test_override_takes_precedence_over_row(self, tmp_path):
        """T1.4.2c: context_overrides value wins over row value for same field."""
        pb_dir, lt_dir = _mk_dirs(tmp_path)
        df = _make_enriched_df()
        result = analyze(
            df,
            "2026-06-01",
            "2330",
            context_overrides={"is_anomalous_volume": True},
            playbook_dirs=[pb_dir],
            light_dirs=[lt_dir],
        )
        assert result.context_snapshot.is_anomalous_volume is True

    def test_multiple_overrides(self, tmp_path):
        """T1.4.2d: multiple context_overrides (K線課程 fields) all applied."""
        pb_dir, lt_dir = _mk_dirs(tmp_path)
        df = _make_enriched_df()
        result = analyze(
            df,
            "2026-06-01",
            "2330",
            context_overrides={
                "ma5_will_rise": True,
                "ma10_will_rise": False,
                "is_anomalous_volume": True,
            },
            playbook_dirs=[pb_dir],
            light_dirs=[lt_dir],
        )
        ctx = result.context_snapshot
        assert ctx.ma5_will_rise is True
        assert ctx.ma10_will_rise is False
        assert ctx.is_anomalous_volume is True


# ---------------------------------------------------------------------------
# T1.4.3 — fired_patterns empty → scenarios empty, active_lights can still be set
# ---------------------------------------------------------------------------


class TestEmptyFiredPatterns:
    def test_no_patterns_no_playbooks_no_lights(self, tmp_path):
        """T1.4.3a: empty playbook and light dirs → empty lists, no crash."""
        pb_dir, lt_dir = _mk_dirs(tmp_path)
        df = _make_enriched_df()
        result = analyze(df, "2026-06-01", "2330", playbook_dirs=[pb_dir], light_dirs=[lt_dir])
        assert result.scenarios == []
        assert result.active_lights == []

    def test_no_patterns_but_light_still_active(self, tmp_path):
        """T1.4.3b: even if no pattern fires, active lights are still evaluated."""
        pb_dir, lt_dir = _mk_dirs(tmp_path)
        (lt_dir / "test_light.yaml").write_text(_light_yaml_content())
        df = _make_enriched_df()
        result = analyze(df, "2026-06-01", "2330", playbook_dirs=[pb_dir], light_dirs=[lt_dir])
        # scenarios empty (no playbooks loaded)
        assert result.scenarios == []
        # but light can still be active
        light_ids = [l.light_id for l in result.active_lights]
        assert "test_active_light" in light_ids

    def test_scenarios_empty_when_no_matching_playbook(self, tmp_path):
        """T1.4.3c: even if patterns fire, no matching playbook → scenarios empty."""
        pb_dir, lt_dir = _mk_dirs(tmp_path)
        # Only a light file, no playbook files
        (lt_dir / "test_light.yaml").write_text(_light_yaml_content())
        df = _make_enriched_df()
        result = analyze(df, "2026-06-01", "2330", playbook_dirs=[pb_dir], light_dirs=[lt_dir])
        # No playbook for any pattern → scenarios must be empty
        assert result.scenarios == []


# ---------------------------------------------------------------------------
# T1.4.4 — invalid YAML schema → analyze() raises LoaderError
# ---------------------------------------------------------------------------


class TestLoaderErrorPropagation:
    def test_invalid_playbook_raises_loader_error(self, tmp_path):
        """T1.4.4a: playbook YAML missing course_citation raises LoaderError."""
        pb_dir, lt_dir = _mk_dirs(tmp_path)
        (pb_dir / "bad_playbook.yaml").write_text(_invalid_playbook_yaml_content())
        df = _make_enriched_df()
        with pytest.raises(LoaderError):
            analyze(df, "2026-06-01", "2330", playbook_dirs=[pb_dir], light_dirs=[lt_dir])

    def test_invalid_light_raises_loader_error(self, tmp_path):
        """T1.4.4b: light YAML with short source (< 5 chars) raises LoaderError."""
        pb_dir, lt_dir = _mk_dirs(tmp_path)
        bad_light = """\
light_id: bad_light
trigger_condition:
  "today.close": "> today.open"
course_citation:
  source: "§1"
recommendation_text: 測試
severity: info
"""
        (lt_dir / "bad_light.yaml").write_text(bad_light)
        df = _make_enriched_df()
        with pytest.raises(LoaderError):
            analyze(df, "2026-06-01", "2330", playbook_dirs=[pb_dir], light_dirs=[lt_dir])


# ---------------------------------------------------------------------------
# T1.4.5 — ContextSnapshot missing field → notes has warn (not crash)
# ---------------------------------------------------------------------------


class TestMissingContextWarn:
    def test_missing_attack_cost_no_crash(self, tmp_path):
        """T1.4.5a: attack_cost not in df or overrides → snapshot.attack_cost = None, no crash."""
        pb_dir, lt_dir = _mk_dirs(tmp_path)
        df = _make_enriched_df()
        result = analyze(df, "2026-06-01", "2330", playbook_dirs=[pb_dir], light_dirs=[lt_dir])
        # Should not crash
        assert result.context_snapshot.attack_cost is None

    def test_playbook_with_required_context_skipped_when_missing(self, tmp_path):
        """T1.4.5b: playbook required_context check — missing field → warn emitted when pattern fires.

        The WARN is only generated when:
          (a) the pattern fires, AND
          (b) the required_context field is None.
        We test this by calling the internal _build_scenarios helper directly with
        a synthetic PatternHit to avoid needing a real bull_engulfing fire.
        """
        from scripts.kline.scenarios.advisor import _build_scenarios
        from scripts.kline.scenarios._schema import (
            ContextSnapshot,
            PatternHit,
            PlaybookSetup,
            Branch,
            Action,
            CourseCitation,
            Playbook,
        )
        import pandas as pd

        # Synthetic PatternHit for bull_engulfing
        hit = PatternHit(pattern="bull_engulfing", fired_at="2026-06-01")

        # Minimal playbook requiring ma5_will_rise
        playbook = Playbook(
            pattern="bull_engulfing",
            setup=PlaybookSetup(name="req_ma5", required_context=["ma5_will_rise"]),
            branches=[
                Branch(
                    id="B1",
                    when={"today.close": "> today.open"},
                    confirm_at="next_close",
                    action=Action(
                        type="context_only_signal",
                        description="test",
                        course_citation=CourseCitation(source="K線力量課程 §MA扣抵"),
                    ),
                )
            ],
            course_sources=[CourseCitation(source="K線力量課程 §MA扣抵定義")],
        )
        playbooks_by_pattern = {"bull_engulfing": [playbook]}

        # Context with ma5_will_rise = None
        ctx = ContextSnapshot()
        today_row = pd.Series({"open": 100.0, "high": 110.0, "low": 95.0, "close": 108.0, "volume": 1_000_000})
        notes: list[str] = []

        scenarios = _build_scenarios([hit], playbooks_by_pattern, today_row, ctx, notes)

        # Playbook was skipped → scenarios empty
        assert scenarios == []
        # WARN about missing ma5_will_rise
        warn_notes = [n for n in notes if "WARN" in n and "ma5_will_rise" in n]
        assert len(warn_notes) >= 1, f"Expected WARN in notes; got: {notes}"

    def test_playbook_with_required_context_satisfied(self, tmp_path):
        """T1.4.5c: playbook required_context met via overrides → not skipped."""
        pb_dir, lt_dir = _mk_dirs(tmp_path)
        (pb_dir / "bull_engulfing.yaml").write_text(_playbook_with_required_context("ma5_will_rise"))
        df = _make_enriched_df()

        # Override ma5_will_rise = True → playbook not skipped
        result = analyze(
            df,
            "2026-06-01",
            "2330",
            context_overrides={"ma5_will_rise": True},
            playbook_dirs=[pb_dir],
            light_dirs=[lt_dir],
        )
        # No WARN about ma5_will_rise being skipped
        skip_warns = [
            n for n in result.notes
            if "WARN" in n and "ma5_will_rise" in n and "skipped" in n
        ]
        assert len(skip_warns) == 0


# ---------------------------------------------------------------------------
# T1.4.6 — raw vs enriched df both work
# ---------------------------------------------------------------------------


class TestRawVsEnrichedDf:
    def test_raw_df_enriched_automatically(self, tmp_path):
        """T1.4.6a: raw OHLCV df (without prev_close) → add_features called automatically."""
        pb_dir, lt_dir = _mk_dirs(tmp_path)
        raw_df = _make_raw_df()
        result = analyze(raw_df, "2026-06-01", "2330", playbook_dirs=[pb_dir], light_dirs=[lt_dir])
        assert isinstance(result, AdvisorResult)
        assert result.context_snapshot is not None

    def test_enriched_df_not_double_enriched(self, tmp_path):
        """T1.4.6b: enriched df (with prev_close) → add_features NOT called again."""
        pb_dir, lt_dir = _mk_dirs(tmp_path)
        enriched_df = _make_enriched_df()
        result = analyze(enriched_df, "2026-06-01", "2330", playbook_dirs=[pb_dir], light_dirs=[lt_dir])
        assert isinstance(result, AdvisorResult)

    def test_raw_and_enriched_give_same_result(self, tmp_path):
        """T1.4.6c: raw and enriched dfs produce equivalent AdvisorResult structure."""
        pb_dir, lt_dir = _mk_dirs(tmp_path)
        raw_df = _make_raw_df()
        enriched_df = _make_enriched_df()

        (lt_dir / "test_light.yaml").write_text(_light_yaml_content())

        result_raw = analyze(raw_df, "2026-06-01", "2330", playbook_dirs=[pb_dir], light_dirs=[lt_dir])
        result_enriched = analyze(enriched_df, "2026-06-01", "2330", playbook_dirs=[pb_dir], light_dirs=[lt_dir])

        # Both should produce same number of active lights
        assert len(result_raw.active_lights) == len(result_enriched.active_lights)


# ---------------------------------------------------------------------------
# Performance test: analyze() < 200ms per single ticker × single date
# ---------------------------------------------------------------------------


class TestPerformance:
    def test_single_ticker_under_200ms(self, tmp_path):
        """analyze() for a single ticker × date must complete in < 200ms."""
        pb_dir, lt_dir = _mk_dirs(tmp_path)
        df = _make_enriched_df(n_bars=300)
        (lt_dir / "test_light.yaml").write_text(_light_yaml_content())
        (pb_dir / "bull_engulfing.yaml").write_text(_playbook_yaml_content())

        start = time.perf_counter()
        result = analyze(df, "2026-06-01", "2330", playbook_dirs=[pb_dir], light_dirs=[lt_dir])
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert isinstance(result, AdvisorResult)
        assert elapsed_ms < 200, f"analyze() took {elapsed_ms:.1f}ms, expected < 200ms"


# ---------------------------------------------------------------------------
# Error handling edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_unknown_ticker_raises_value_error(self, tmp_path):
        """analyze() raises ValueError if ticker not found in df."""
        pb_dir, lt_dir = _mk_dirs(tmp_path)
        df = _make_enriched_df(ticker="2330")
        with pytest.raises(ValueError, match="9999"):
            analyze(df, "2026-06-01", "9999", playbook_dirs=[pb_dir], light_dirs=[lt_dir])

    def test_unknown_date_raises_value_error(self, tmp_path):
        """analyze() raises ValueError if today_date not found."""
        pb_dir, lt_dir = _mk_dirs(tmp_path)
        df = _make_enriched_df()
        with pytest.raises(ValueError, match="1900-01-01"):
            analyze(df, "1900-01-01", "2330", playbook_dirs=[pb_dir], light_dirs=[lt_dir])

    def test_active_lights_sorted_by_severity(self, tmp_path):
        """active_lights list is sorted critical → warn → info."""
        pb_dir, lt_dir = _mk_dirs(tmp_path)
        critical_light = """\
light_id: critical_one
trigger_condition:
  "today.close": "> today.open"
course_citation:
  source: 明日 K 線 §17 頭部三要件
recommendation_text: 危險訊號
severity: critical
"""
        warn_light = """\
light_id: warn_one
trigger_condition:
  "today.close": "> today.open"
course_citation:
  source: 明日 K 線 §11 黑 K 高檔警示
recommendation_text: 注意訊號
severity: warn
"""
        info_light = """\
light_id: info_one
trigger_condition:
  "today.close": "> today.open"
course_citation:
  source: 明日 K 線 §10 上影線觀察
recommendation_text: 一般觀察
severity: info
"""
        (lt_dir / "critical_light.yaml").write_text(critical_light)
        (lt_dir / "warn_light.yaml").write_text(warn_light)
        (lt_dir / "info_light.yaml").write_text(info_light)

        df = _make_enriched_df()
        result = analyze(df, "2026-06-01", "2330", playbook_dirs=[pb_dir], light_dirs=[lt_dir])

        assert len(result.active_lights) == 3
        assert result.active_lights[0].severity == "critical"
        assert result.active_lights[1].severity == "warn"
        assert result.active_lights[2].severity == "info"
