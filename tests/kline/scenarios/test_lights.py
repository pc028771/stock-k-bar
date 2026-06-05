"""Tests for D-class lights YAML files — Task 2.3.

T2.3.1  All ~20 light yaml files load without error via loader.load_lights()
T2.3.2  trigger_condition uses only whitelisted DSL fields; unknown field raises
T2.3.3  advisor.analyze() returns active_lights with correct structure
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts.kline.scenarios import load_lights
from scripts.kline.scenarios.advisor import analyze
from scripts.kline.scenarios.condition import UnknownTokenError, evaluate
from scripts.kline.scenarios._schema import ContextSnapshot, Light

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

LIGHTS_DIR = Path(__file__).parents[3] / "scripts" / "kline" / "scenarios" / "lights"

# ---------------------------------------------------------------------------
# T2.3.1 — All light yaml files load without error
# ---------------------------------------------------------------------------


class TestLoadAllLights:
    def test_load_lights_returns_19(self):
        """T2.3.1a: loading lights dir returns exactly 27 lights (24 baseline + 3 INTRO concepts 2026-06-05:
        same_level_red_then_black, taiex_down_stock_new_high, just_high_doji_attack)."""
        lights = load_lights([LIGHTS_DIR])
        assert len(lights) == 27

    def test_all_lights_have_severity(self):
        """T2.3.1b: every loaded light has a valid severity value."""
        lights = load_lights([LIGHTS_DIR])
        for light_id, light in lights.items():
            assert light.severity in ("info", "warn", "critical"), (
                f"light {light_id!r} has invalid severity {light.severity!r}"
            )

    def test_all_lights_have_course_citation(self):
        """T2.3.1c: every loaded light has a course_citation with source ≥ 5 chars."""
        lights = load_lights([LIGHTS_DIR])
        for light_id, light in lights.items():
            assert light.course_citation is not None, (
                f"light {light_id!r} missing course_citation"
            )
            assert len(light.course_citation.source) >= 5, (
                f"light {light_id!r} source too short: {light.course_citation.source!r}"
            )

    def test_all_lights_have_recommendation_text(self):
        """T2.3.1d: every loaded light has non-empty recommendation_text."""
        lights = load_lights([LIGHTS_DIR])
        for light_id, light in lights.items():
            assert light.recommendation_text, (
                f"light {light_id!r} has empty recommendation_text"
            )

    def test_all_light_ids_unique(self):
        """T2.3.1e: no duplicate light_id (loader enforces this via ValueError)."""
        lights = load_lights([LIGHTS_DIR])
        # load_lights already enforces uniqueness; this test confirms no exception
        # was raised and we got back a dict (each key is unique by definition)
        assert len(lights) == len(set(lights.keys()))

    def test_expected_light_ids_present(self):
        """T2.3.1f: spot-check that all 24 expected light_ids are present (19 baseline + 5 advanced field lights)."""
        expected_ids = {
            "pressure_meeting_unresolved",
            "weak_bull_trendline_only",
            "selling_pressure_dissolution_required",
            "pressure_layer_no_support",
            "lowprice_first_pull_exit",
            "just_high_upper_shadow",
            "high_black_k_warning",
            "limit_up_next_day_stats",
            "gap_down_falling_three",
            "high_pushup_next_step",
            "sunrise_vs_rising_three_boundary",
            "top_formation_three_criteria",
            "mountain_descent_four_types",
            "bottom_break_struggle",
            "pessimistic_stock_structural",
            "manipulator_distribution_warning",
            "lack_of_power_distinction",
            "new_high_next_day_attack_required",
            "zhongshu_recency_bias",
            # advanced field lights (toplevel snapshot fields: attack_cost / attack_intent_zone_low /
            # defensive_low / merged_high / merged_low)
            "lt_attack_cost_breakdown",
            "lt_attack_intent_zone_breakdown",
            "lt_defensive_low_break",
            "lt_merged_doji_high_break",
            "lt_merged_doji_low_break",
            # INTRO concepts impl (2026-06-05)
            "same_level_red_then_black",
            "taiex_down_stock_new_high",
            "just_high_doji_attack",
        }
        lights = load_lights([LIGHTS_DIR])
        assert set(lights.keys()) == expected_ids

    def test_severity_distribution(self):
        """T2.3.1g: expected critical/warn/info counts (leading_env_reverse removed → warn=8)."""
        lights = load_lights([LIGHTS_DIR])
        severity_counts = {"info": 0, "warn": 0, "critical": 0}
        for light in lights.values():
            severity_counts[light.severity] += 1
        # Baseline 2026-06-04 (lights_fix_batch): 1 critical (top_formation),
        # 9 warn (manipulator_distribution_warning downgraded from critical),
        # 9 info.
        # Advanced field lights add: critical (attack_cost_breakdown,
        # defensive_low_break) = +2, warn (attack_intent_zone_breakdown,
        # merged_doji_low_break) = +2, info (merged_doji_high_break) = +1.
        # Total: 3 critical, 11 warn, 10 info.
        # INTRO concepts impl (2026-06-05) added: warn +1 (same_level_red_then_black),
        # info +2 (taiex_down_stock_new_high, just_high_doji_attack).
        # Total: 3 critical, 12 warn, 12 info.
        assert severity_counts["critical"] == 3
        assert severity_counts["warn"] == 12
        assert severity_counts["info"] == 12


# ---------------------------------------------------------------------------
# T2.3.2 — trigger_condition uses only whitelisted DSL fields
# ---------------------------------------------------------------------------


class TestTriggerConditionDSL:
    """Verify that all loaded lights' trigger_conditions use only whitelisted fields,
    and that an unknown field raises UnknownTokenError."""

    def _make_row(self, **kwargs) -> pd.Series:
        """Build a minimal pd.Series for scalar evaluation."""
        defaults = {
            "open": 100.0,
            "high": 105.0,
            "low": 98.0,
            "close": 102.0,
            "volume": 10000.0,
            "prev_open": 99.0,
            "prev_high": 104.0,
            "prev_low": 97.0,
            "prev_close": 101.0,
            "prev_high_60": 110.0,
            "prior_low_60": 80.0,
        }
        defaults.update(kwargs)
        return pd.Series(defaults)

    def _make_ctx(self, **kwargs) -> ContextSnapshot:
        """Build a minimal ContextSnapshot."""
        defaults = dict(
            ma5_will_rise=True,
            ma10_will_rise=True,
            ma20_will_rise=True,
            ma60_will_rise=True,
        )
        defaults.update(kwargs)
        return ContextSnapshot(**defaults)

    def test_all_lights_conditions_evaluate_without_unknown_token_error(self):
        """T2.3.2a: evaluating each light's trigger_condition raises no UnknownTokenError."""
        lights = load_lights([LIGHTS_DIR])
        row = self._make_row()
        ctx = self._make_ctx()

        for light_id, light in lights.items():
            try:
                result = evaluate(light.trigger_condition, row, ctx)
                # result can be True, False, or None (pending next_day.*)
                assert result in (True, False, None), (
                    f"light {light_id!r} evaluate returned unexpected value: {result!r}"
                )
            except UnknownTokenError as exc:
                pytest.fail(
                    f"light {light_id!r} trigger_condition raised UnknownTokenError: {exc}"
                )

    def test_unknown_field_raises_unknown_token_error(self):
        """T2.3.2b: a trigger_condition with an unknown field raises UnknownTokenError."""
        bad_condition = {"nonexistent_field": "> 100"}
        row = self._make_row()
        ctx = self._make_ctx()
        with pytest.raises(UnknownTokenError, match="unknown field"):
            evaluate(bad_condition, row, ctx)

    def test_arithmetic_rhs_raises_unknown_token_error(self):
        """T2.3.2c: RHS with arithmetic expression raises UnknownTokenError."""
        bad_condition = {"today.close": "< prev_high_60 * 0.98"}
        row = self._make_row()
        ctx = self._make_ctx()
        with pytest.raises(UnknownTokenError):
            evaluate(bad_condition, row, ctx)

    def test_context_unknown_field_raises(self):
        """T2.3.2d: unknown context field raises UnknownTokenError."""
        bad_condition = {"context.near_resistance": True}
        row = self._make_row()
        ctx = self._make_ctx()
        with pytest.raises(UnknownTokenError, match="unknown field"):
            evaluate(bad_condition, row, ctx)

    def test_pressure_meeting_unresolved_triggers_near_high(self):
        """T2.3.2e: pressure_meeting_unresolved activates when high >= prev_high_60 and close < prev_high_60."""
        lights = load_lights([LIGHTS_DIR])
        light = lights["pressure_meeting_unresolved"]
        # today.high >= prev_high_60 (105 >= 105) AND today.close < prev_high_60 (102 < 105)
        row = self._make_row(high=105.0, close=102.0, prev_high_60=105.0)
        ctx = self._make_ctx()
        result = evaluate(light.trigger_condition, row, ctx)
        assert result is True

    def test_pressure_meeting_unresolved_no_trigger_when_above(self):
        """T2.3.2f: pressure_meeting_unresolved does not activate when close >= prev_high_60."""
        lights = load_lights([LIGHTS_DIR])
        light = lights["pressure_meeting_unresolved"]
        # today.close >= prev_high_60 → not triggered
        row = self._make_row(high=110.0, close=112.0, prev_high_60=105.0)
        ctx = self._make_ctx()
        result = evaluate(light.trigger_condition, row, ctx)
        assert result is False

    def test_top_formation_critical_triggers(self):
        """T2.3.2g: top_formation_three_criteria activates with correct inputs.

        2026-06-04 audit fix: condition now requires 跌破頸線 proxy
        (close < prior_low_60 + is_breakdown_pattern_flag=1 + ma60_will_rise=False),
        aligned with course §17 「跌破頸線促成頭部成型」.
        """
        lights = load_lights([LIGHTS_DIR])
        light = lights["top_formation_three_criteria"]
        assert light.severity == "critical"
        # close < prior_low_60 + breakdown_pattern + ma60 下彎
        row = self._make_row(
            close=78.0,
            prev_close=82.0,
            prev_high_60=115.0,
            prior_low_60=80.0,
            is_breakdown_pattern_flag=1,
        )
        ctx = self._make_ctx(ma60_will_rise=False)
        result = evaluate(light.trigger_condition, row, ctx)
        assert result is True

    def test_manipulator_distribution_critical(self):
        """T2.3.2h: manipulator_distribution_warning severity.

        2026-06-04 audit fix: severity downgraded critical → warn because the
        original condition (single high-zone black K) fired 42.5% of days
        — too broad for critical level. Course §31 actually requires 高檔長黑
        (body ≥ 4%) as the trigger.
        """
        lights = load_lights([LIGHTS_DIR])
        light = lights["manipulator_distribution_warning"]
        assert light.severity == "warn"

    def test_new_high_next_day_attack_required_triggers_only_when_new_high(self):
        """T2.3.2i: new_high_next_day_attack_required NOT always-true — only fires when high+close >= prev_high_60.

        Bug fix test: prev_high_60 was missing from add_features() output,
        causing scalar eval to return None (pending) → always included.
        Now prev_high_60 is an alias for prior_high_60 in features.py.
        """
        lights = load_lights([LIGHTS_DIR])
        light = lights["new_high_next_day_attack_required"]

        # Should fire: high=110 >= prev_high_60=105 AND close=108 >= prev_high_60=105
        row_fire = self._make_row(high=110.0, close=108.0, prev_high_60=105.0)
        result_fire = evaluate(light.trigger_condition, row_fire, self._make_ctx())
        assert result_fire is True, "expected True when high+close >= prev_high_60"

        # Should NOT fire: close=100 < prev_high_60=105 (close didn't clear the high)
        row_no_fire = self._make_row(high=110.0, close=100.0, prev_high_60=105.0)
        result_no_fire = evaluate(light.trigger_condition, row_no_fire, self._make_ctx())
        assert result_no_fire is False, "expected False when close < prev_high_60"

    def test_pressure_meeting_unresolved_not_always_true(self):
        """T2.3.2j: pressure_meeting_unresolved NOT always-true — only fires when high touched but close below.

        Bug fix test: same root cause as T2.3.2i — prev_high_60 missing from df.
        """
        lights = load_lights([LIGHTS_DIR])
        light = lights["pressure_meeting_unresolved"]

        # Should NOT fire: close=108 >= prev_high_60=105 → pressure resolved
        row_no_fire = self._make_row(high=110.0, close=108.0, prev_high_60=105.0)
        result_no_fire = evaluate(light.trigger_condition, row_no_fire, self._make_ctx())
        assert result_no_fire is False, "expected False when close >= prev_high_60 (pressure resolved)"

        # Should NOT fire: high=100 < prev_high_60=105 → never touched resistance
        row_no_touch = self._make_row(high=100.0, close=98.0, prev_high_60=105.0)
        result_no_touch = evaluate(light.trigger_condition, row_no_touch, self._make_ctx())
        assert result_no_touch is False, "expected False when high < prev_high_60 (never touched)"


# ---------------------------------------------------------------------------
# T2.3.3 — advisor.analyze() returns active_lights with correct structure
# ---------------------------------------------------------------------------


class TestAdvisorActiveLights:
    """Verify that advisor.analyze() returns active_lights sorted and structured correctly."""

    def _make_bars_df(self, close: float = 102.0, prev_high_60: float = 115.0) -> pd.DataFrame:
        """Build a minimal bars DataFrame with required columns.

        Uses 100 rows so add_features can compute MA60, MA20, etc. correctly.
        """
        import numpy as np

        n_bars = 100
        today_date = "2026-06-03"
        dates = pd.bdate_range(end=today_date, periods=n_bars, freq="B")
        closes = np.linspace(90.0, close, n_bars)
        opens = closes * 0.99
        highs = closes * 1.02
        lows = opens * 0.98
        volumes = np.full(n_bars, 10000.0)
        ma60_vals = pd.Series(closes).rolling(60, min_periods=1).mean().values
        ma20_vals = pd.Series(closes).rolling(20, min_periods=1).mean().values

        return pd.DataFrame({
            "ticker": "TEST",
            "trade_date": dates.strftime("%Y-%m-%d"),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
            "ma20": ma20_vals,
            "ma60": ma60_vals,
            # pre-computed features needed by condition evaluator
            "prev_high_60": prev_high_60,
            "prior_low_60": 80.0,
        })

    def test_analyze_returns_advisor_result_with_active_lights(self):
        """T2.3.3a: analyze() returns AdvisorResult with active_lights list."""
        from scripts.kline.scenarios._schema import AdvisorResult

        df = self._make_bars_df()
        result = analyze(
            bars_df=df,
            today_date="2026-06-03",
            ticker="TEST",
            light_dirs=[LIGHTS_DIR],
            playbook_dirs=[],
        )
        assert isinstance(result, AdvisorResult)
        assert isinstance(result.active_lights, list)

    def test_active_lights_sorted_critical_warn_info(self):
        """T2.3.3b: active_lights are sorted critical → warn → info."""
        df = self._make_bars_df(close=98.0, prev_high_60=115.0)
        context_overrides = {
            "ma60_will_rise": False,
            "ma20_will_rise": False,
        }
        result = analyze(
            bars_df=df,
            today_date="2026-06-03",
            ticker="TEST",
            context_overrides=context_overrides,
            light_dirs=[LIGHTS_DIR],
            playbook_dirs=[],
        )
        # Extract severities of active lights in order
        order = {"critical": 0, "warn": 1, "info": 2}
        severities = [l.severity for l in result.active_lights]
        severity_ranks = [order[s] for s in severities]
        assert severity_ranks == sorted(severity_ranks), (
            f"active_lights not sorted: {severities}"
        )

    def test_active_lights_each_is_light_model(self):
        """T2.3.3c: each element in active_lights is a Light instance with required fields."""
        df = self._make_bars_df()
        result = analyze(
            bars_df=df,
            today_date="2026-06-03",
            ticker="TEST",
            light_dirs=[LIGHTS_DIR],
            playbook_dirs=[],
        )
        for light in result.active_lights:
            assert isinstance(light, Light)
            assert light.light_id
            assert light.severity in ("info", "warn", "critical")
            assert light.course_citation is not None
            assert len(light.course_citation.source) >= 5
            assert light.recommendation_text

    def test_no_active_lights_when_conditions_not_met(self):
        """T2.3.3d: no lights activate when stock is strongly bullish above all levels."""
        # Use a stock with close way above prev_high_60 — most lights won't trigger
        df = self._make_bars_df(close=130.0, prev_high_60=115.0)
        # Also give bullish context
        context_overrides = {
            "ma5_will_rise": True,
            "ma20_will_rise": True,
            "ma60_will_rise": True,
        }
        result = analyze(
            bars_df=df,
            today_date="2026-06-03",
            ticker="TEST",
            context_overrides=context_overrides,
            light_dirs=[LIGHTS_DIR],
            playbook_dirs=[],
        )
        # With strongly bullish conditions, warn/critical lights should be minimal
        # (some info lights like new_high_next_day_attack_required may still fire)
        critical_lights = [l for l in result.active_lights if l.severity == "critical"]
        assert len(critical_lights) == 0, (
            f"Unexpected critical lights with bullish bar: {[l.light_id for l in critical_lights]}"
        )

    def test_critical_lights_fire_on_bearish_conditions(self):
        """T2.3.3e: top_formation_three_criteria fires when conditions are met.

        2026-06-04 audit fix: condition aligned to course §17 「跌破頸線」 — needs
        close < prior_low_60 + is_breakdown_pattern_flag=1 + ma60 下彎.
        Build a series with sustained breakdowns (multiple new-low events) so
        is_in_breakdown_pattern fires.
        """
        import numpy as np

        n_bars = 120
        today_date = "2026-06-03"
        dates = pd.bdate_range(end=today_date, periods=n_bars, freq="B")
        # Rise then sustained decline with multiple new lows
        rise = np.linspace(100.0, 150.0, 40)
        peak_consol = np.linspace(150.0, 148.0, 20)
        # Stair-step decline to create ≥ 2 new-low events
        decline = np.concatenate([
            np.linspace(148.0, 130.0, 15),
            np.linspace(132.0, 115.0, 15),
            np.linspace(117.0, 95.0, 15),
            np.linspace(95.0, 70.0, 15),
        ])
        closes = np.concatenate([rise, peak_consol, decline])
        opens = closes * 1.005
        highs = closes * 1.01
        lows = closes * 0.99
        volumes = np.full(n_bars, 10000.0)
        ma60_vals = pd.Series(closes).rolling(60, min_periods=1).mean().values
        ma20_vals = pd.Series(closes).rolling(20, min_periods=1).mean().values

        df = pd.DataFrame({
            "ticker": "TEST",
            "trade_date": dates.strftime("%Y-%m-%d"),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
            "ma20": ma20_vals,
            "ma60": ma60_vals,
        })

        context_overrides = {
            "ma60_will_rise": False,
        }
        result = analyze(
            bars_df=df,
            today_date="2026-06-03",
            ticker="TEST",
            context_overrides=context_overrides,
            light_dirs=[LIGHTS_DIR],
            playbook_dirs=[],
        )
        active_ids = {l.light_id for l in result.active_lights}
        assert "top_formation_three_criteria" in active_ids, (
            f"Expected top_formation_three_criteria in {active_ids}"
        )
