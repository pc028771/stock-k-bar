"""Tests for scripts/kline/scenarios/condition.py — Branch / Light mini-DSL.

Coverage plan:
  T1.3.1  simple next_day.close > today.high (vectorized)
  T1.3.2  all + any combinations
  T1.3.3  next_day_n=2 correctly shifts -2
  T1.3.4  unknown field raises UnknownTokenError with field name in message
  T1.3.5  vectorized == scalar on fixture data (property-style consistency)
  T1.3.6  context.ma5_will_rise: true uses ContextSnapshot path
  Extra:  between, gap_up/down, fills_gap, nesting > 2 raises,
          RHS arithmetic expression raises, unknown operator raises,
          not node, prev.* fields, context.ma*_will_rise
"""

from __future__ import annotations

import time

import pandas as pd
import pytest

from scripts.kline.scenarios._schema import ContextSnapshot
from scripts.kline.scenarios.condition import (
    UnknownTokenError,
    evaluate,
    evaluate_vectorized,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_row(
    open_=100.0,
    high=110.0,
    low=95.0,
    close=108.0,
    volume=1_000_000,
    prev_open=98.0,
    prev_high=105.0,
    prev_low=93.0,
    prev_close=104.0,
    **kwargs,
) -> pd.Series:
    data = {
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "prev_open": prev_open,
        "prev_high": prev_high,
        "prev_low": prev_low,
        "prev_close": prev_close,
    }
    data.update(kwargs)
    return pd.Series(data)


def _empty_ctx(**kwargs) -> ContextSnapshot:
    return ContextSnapshot(**kwargs)


def _make_df(n: int = 5) -> pd.DataFrame:
    """Minimal OHLCV DataFrame with n rows."""
    closes = [100.0 + i for i in range(n)]
    opens = [c - 1 for c in closes]
    highs = [c + 5 for c in closes]
    lows = [c - 5 for c in closes]
    volumes = [1_000_000] * n
    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


def _empty_ctx_df(n: int, **col_overrides) -> pd.DataFrame:
    df = pd.DataFrame(index=range(n))
    for col, val in col_overrides.items():
        if isinstance(val, list):
            df[col] = val
        else:
            df[col] = [val] * n
    return df


# ---------------------------------------------------------------------------
# T1.3.1 — simple next_day.close > today.high (vectorized)
# ---------------------------------------------------------------------------


class TestSimpleNextDayVsToday:
    """T1.3.1"""

    def test_vectorized_next_day_close_gt_today_high(self):
        """next_day.close > today.high should be True when tomorrow close > today high."""
        when = {"next_day.close": "> today.high"}
        df = _make_df(5)
        ctx_df = _empty_ctx_df(5)

        result = evaluate_vectorized(when, df, ctx_df, next_day_n=1)
        assert isinstance(result, pd.Series)
        assert result.dtype == bool

        # Manual check: next_day.close = df.close.shift(-1), today.high = df.high
        # close[i+1] > high[i]?
        # closes: 100,101,102,103,104 → shifted: 101,102,103,104,NaN
        # highs: 105,106,107,108,109
        # 101 > 105 → False, etc. — all False (shift is smaller)
        assert result.tolist() == [False, False, False, False, False]

    def test_vectorized_simple_true_case(self):
        """Make a df where next-day close clearly exceeds today high."""
        df = pd.DataFrame(
            {
                "open": [100, 120, 100],
                "high": [105, 125, 105],
                "low": [95, 115, 95],
                "close": [102, 122, 102],
                "volume": [1e6, 1e6, 1e6],
            }
        )
        when = {"next_day.close": "> today.high"}
        ctx_df = _empty_ctx_df(3)
        result = evaluate_vectorized(when, df, ctx_df, next_day_n=1)
        # Row 0: next close = 122, today high = 105 → True
        # Row 1: next close = 102, today high = 125 → False
        # Row 2: next close = NaN (no row 3) → False
        assert result.tolist() == [True, False, False]

    def test_scalar_returns_none_for_next_day_field(self):
        """In scalar mode, next_day.* fields are pending → None."""
        when = {"next_day.close": "> today.high"}
        row = _make_row()
        ctx = _empty_ctx()
        result = evaluate(when, row, ctx)
        assert result is None

    def test_scalar_today_close_gt_prev_close(self):
        """today.close > prev.close (no next_day involved) → True/False."""
        row = _make_row(close=108.0, prev_close=104.0)
        ctx = _empty_ctx()
        when = {"today.close": "> prev.close"}
        assert evaluate(when, row, ctx) is True

        row2 = _make_row(close=100.0, prev_close=104.0)
        assert evaluate(when, row2, ctx) is False


# ---------------------------------------------------------------------------
# T1.3.2 — all + any combinations
# ---------------------------------------------------------------------------


class TestAllAnyLogic:
    """T1.3.2"""

    def test_all_two_conditions_both_true(self):
        row = _make_row(close=108.0, prev_close=100.0, volume=2_000_000)
        ctx = _empty_ctx()
        when = {
            "all": [
                {"today.close": "> prev.close"},
                {"today.volume": ">= 1500000"},
            ]
        }
        assert evaluate(when, row, ctx) is True

    def test_all_one_false_short_circuits(self):
        row = _make_row(close=99.0, prev_close=100.0, volume=2_000_000)
        ctx = _empty_ctx()
        when = {
            "all": [
                {"today.close": "> prev.close"},  # False
                {"today.volume": ">= 1500000"},   # True (would be)
            ]
        }
        assert evaluate(when, row, ctx) is False

    def test_any_one_true_returns_true(self):
        row = _make_row(close=99.0, prev_close=100.0)
        ctx = _empty_ctx()
        when = {
            "any": [
                {"today.close": "> prev.close"},   # False
                {"today.close": "<= prev.close"},  # True
            ]
        }
        assert evaluate(when, row, ctx) is True

    def test_any_all_false_returns_false(self):
        row = _make_row(close=99.0, prev_close=100.0)
        ctx = _empty_ctx()
        when = {
            "any": [
                {"today.close": "> prev.close"},   # False (99 > 100)
                {"today.close": "> 200"},          # False
            ]
        }
        assert evaluate(when, row, ctx) is False

    def test_all_contains_any_nested(self):
        row = _make_row(close=108.0, prev_close=100.0)
        ctx = _empty_ctx()
        when = {
            "all": [
                {"today.close": "> prev.close"},  # True
                {"any": [
                    {"today.close": "> 200"},      # False
                    {"today.close": "> 100"},      # True
                ]},
            ]
        }
        assert evaluate(when, row, ctx) is True

    def test_all_with_pending_returns_none_not_false(self):
        """If one item is pending (None) but none is definitively False → None."""
        row = _make_row(close=108.0, prev_close=100.0)
        ctx = _empty_ctx()
        when = {
            "all": [
                {"today.close": "> prev.close"},      # True
                {"next_day.close": "> today.high"},   # None (pending)
            ]
        }
        result = evaluate(when, row, ctx)
        assert result is None

    def test_vectorized_all_two_conditions(self):
        df = pd.DataFrame(
            {
                "open": [100, 100, 100],
                "high": [110, 110, 110],
                "low": [90, 90, 90],
                "close": [105, 95, 105],
                "volume": [2e6, 2e6, 500_000],
            }
        )
        ctx_df = _empty_ctx_df(3)
        when = {
            "all": [
                {"today.close": ">= 100"},
                {"today.volume": ">= 1000000"},
            ]
        }
        result = evaluate_vectorized(when, df, ctx_df)
        # row0: close=105>=100 & vol=2M>=1M → True
        # row1: close=95>=100 → False
        # row2: close=105>=100 & vol=500K>=1M → False
        assert result.tolist() == [True, False, False]

    def test_not_node_scalar(self):
        row = _make_row(close=99.0, prev_close=100.0)
        ctx = _empty_ctx()
        when = {"not": {"today.close": "> prev.close"}}  # not False → True
        assert evaluate(when, row, ctx) is True

    def test_not_node_vectorized(self):
        df = _make_df(3)
        ctx_df = _empty_ctx_df(3)
        when = {"not": {"today.close": ">= 200"}}  # all closes < 200 → not False → True
        result = evaluate_vectorized(when, df, ctx_df)
        assert result.tolist() == [True, True, True]


# ---------------------------------------------------------------------------
# T1.3.3 — next_day_n=2 correctly shifts -2
# ---------------------------------------------------------------------------


class TestNextDayN:
    """T1.3.3"""

    def test_next_day_n2_shifts_minus_2(self):
        df = pd.DataFrame(
            {
                "open": [100, 110, 120, 130, 140],
                "high": [105, 115, 125, 135, 145],
                "low": [95, 105, 115, 125, 135],
                "close": [102, 112, 122, 132, 142],
                "volume": [1e6] * 5,
            }
        )
        ctx_df = _empty_ctx_df(5)
        # next_day.close with n=2 = close.shift(-2): [122, 132, 142, NaN, NaN]
        # today.high: [105, 115, 125, 135, 145]
        # row0: 122 > 105 → True
        # row1: 132 > 115 → True
        # row2: 142 > 125 → True
        # row3: NaN > 135 → False
        # row4: NaN > 145 → False
        when = {"next_day.close": "> today.high"}
        result = evaluate_vectorized(when, df, ctx_df, next_day_n=2)
        assert result.tolist() == [True, True, True, False, False]

    def test_next_day_n1_vs_n2_differ(self):
        df = pd.DataFrame(
            {
                "open": [100, 101, 200, 201, 202],
                "high": [105, 106, 205, 206, 207],
                "low": [95, 96, 195, 196, 197],
                "close": [102, 103, 202, 203, 204],
                "volume": [1e6] * 5,
            }
        )
        ctx_df = _empty_ctx_df(5)
        when = {"next_day.close": "> today.high"}
        result_n1 = evaluate_vectorized(when, df, ctx_df, next_day_n=1)
        result_n2 = evaluate_vectorized(when, df, ctx_df, next_day_n=2)
        # They should differ (different shifts)
        assert result_n1.tolist() != result_n2.tolist()


# ---------------------------------------------------------------------------
# T1.3.4 — unknown field raises UnknownTokenError
# ---------------------------------------------------------------------------


class TestUnknownField:
    """T1.3.4"""

    def test_unknown_top_level_field_raises(self):
        row = _make_row()
        ctx = _empty_ctx()
        with pytest.raises(UnknownTokenError) as exc:
            evaluate({"some_random_field": "> 100"}, row, ctx)
        assert "some_random_field" in str(exc.value)

    def test_unknown_today_sub_field_raises(self):
        row = _make_row()
        ctx = _empty_ctx()
        with pytest.raises(UnknownTokenError) as exc:
            evaluate({"today.notexist": "> 100"}, row, ctx)
        assert "today.notexist" in str(exc.value)

    def test_unknown_context_field_raises(self):
        row = _make_row()
        ctx = _empty_ctx()
        with pytest.raises(UnknownTokenError) as exc:
            evaluate({"context.nonexistent_flag": True}, row, ctx)
        assert "context.nonexistent_flag" in str(exc.value)

    def test_unknown_field_in_vectorized_raises(self):
        df = _make_df(3)
        ctx_df = _empty_ctx_df(3)
        with pytest.raises(UnknownTokenError) as exc:
            evaluate_vectorized({"made_up_field": "> 100"}, df, ctx_df)
        assert "made_up_field" in str(exc.value)

    def test_unknown_rhs_field_raises(self):
        row = _make_row()
        ctx = _empty_ctx()
        with pytest.raises(UnknownTokenError) as exc:
            evaluate({"today.close": "> totally.made.up"}, row, ctx)
        assert "totally.made.up" in str(exc.value)

    def test_rhs_arithmetic_expression_raises(self):
        row = _make_row()
        ctx = _empty_ctx()
        with pytest.raises(UnknownTokenError):
            evaluate({"today.volume": "> today.volume * 1.5"}, row, ctx)

    def test_unknown_operator_raises(self):
        row = _make_row()
        ctx = _empty_ctx()
        with pytest.raises(UnknownTokenError):
            evaluate({"today.close": "~= 100"}, row, ctx)


# ---------------------------------------------------------------------------
# T1.3.5 — vectorized == scalar results consistency
# ---------------------------------------------------------------------------


class TestVectorizedEqualsScalar:
    """T1.3.5"""

    def _build_fixture(self):
        n = 10
        closes = [100.0 + i * 2 for i in range(n)]
        opens = [c - 1 for c in closes]
        highs = [c + 3 for c in closes]
        lows = [c - 3 for c in closes]
        volumes = [1_000_000 + i * 10_000 for i in range(n)]
        df = pd.DataFrame(
            {
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": volumes,
            }
        )
        ctx_df = _empty_ctx_df(n)
        return df, ctx_df

    def _check_consistency(self, when: dict, df: pd.DataFrame, ctx_df: pd.DataFrame):
        vec_result = evaluate_vectorized(when, df, ctx_df, next_day_n=1)
        for i, (_, row) in enumerate(df.iterrows()):
            # Build a row with prev.* fields from df shifted by 1
            scalar_row = row.copy()
            if i > 0:
                prev = df.iloc[i - 1]
                scalar_row["prev_open"] = prev["open"]
                scalar_row["prev_high"] = prev["high"]
                scalar_row["prev_low"] = prev["low"]
                scalar_row["prev_close"] = prev["close"]
            ctx = ContextSnapshot()
            scalar_val = evaluate(when, scalar_row, ctx, next_day_n=1)
            # Scalar may be None (pending) for next_day.* conditions;
            # vectorized uses shift which may be NaN (→ False)
            # We only assert equality when scalar is not None
            if scalar_val is not None:
                assert bool(vec_result.iloc[i]) == scalar_val, (
                    f"Row {i}: vector={vec_result.iloc[i]}, scalar={scalar_val}"
                )

    def test_simple_close_gt_prev_close(self):
        df, ctx_df = self._build_fixture()
        when = {"today.close": "> prev.close"}
        self._check_consistency(when, df, ctx_df)

    def test_all_combination(self):
        df, ctx_df = self._build_fixture()
        when = {
            "all": [
                {"today.close": ">= 104"},
                {"today.volume": ">= 1050000"},
            ]
        }
        self._check_consistency(when, df, ctx_df)

    def test_any_combination(self):
        df, ctx_df = self._build_fixture()
        when = {
            "any": [
                {"today.close": "> 120"},
                {"today.volume": ">= 1090000"},
            ]
        }
        self._check_consistency(when, df, ctx_df)

    def test_between(self):
        df, ctx_df = self._build_fixture()
        when = {"today.close": {"between": [105.0, 115.0]}}
        self._check_consistency(when, df, ctx_df)


# ---------------------------------------------------------------------------
# T1.3.6 — K線課程 context fields (ma*_will_rise, taiex_*)
# ---------------------------------------------------------------------------


class TestContextFields:
    """T1.3.6 — K線課程 context fields (ma*_will_rise, taiex_*)"""

    def test_ma5_will_rise_true(self):
        row = _make_row()
        ctx = _empty_ctx(ma5_will_rise=True)
        when = {"context.ma5_will_rise": True}
        assert evaluate(when, row, ctx) is True

    def test_ma10_will_rise_false(self):
        row = _make_row()
        ctx = _empty_ctx(ma10_will_rise=False)
        when = {"context.ma10_will_rise": True}
        assert evaluate(when, row, ctx) is False

    def test_context_ma5_will_rise_vectorized(self):
        df = _make_df(4)
        ctx_df = _empty_ctx_df(
            4, ma5_will_rise=[True, False, True, False]
        )
        when = {"context.ma5_will_rise": True}
        result = evaluate_vectorized(when, df, ctx_df)
        assert result.tolist() == [True, False, True, False]


# ---------------------------------------------------------------------------
# Extra: between
# ---------------------------------------------------------------------------


class TestBetween:
    def test_between_scalar_in_range(self):
        row = _make_row(close=108.0)
        ctx = _empty_ctx()
        when = {"today.close": {"between": [100.0, 110.0]}}
        assert evaluate(when, row, ctx) is True

    def test_between_scalar_out_of_range(self):
        row = _make_row(close=115.0)
        ctx = _empty_ctx()
        when = {"today.close": {"between": [100.0, 110.0]}}
        assert evaluate(when, row, ctx) is False

    def test_between_boundary_inclusive(self):
        row = _make_row(close=100.0)
        ctx = _empty_ctx()
        when = {"today.close": {"between": [100.0, 110.0]}}
        assert evaluate(when, row, ctx) is True

    def test_between_invalid_list_raises(self):
        row = _make_row()
        ctx = _empty_ctx()
        with pytest.raises(UnknownTokenError):
            evaluate({"today.close": {"between": [100.0]}}, row, ctx)

    def test_between_vectorized(self):
        df = pd.DataFrame(
            {
                "open": [99, 99, 99],
                "high": [115, 105, 108],
                "low": [90, 90, 90],
                "close": [99.0, 105.0, 112.0],
                "volume": [1e6, 1e6, 1e6],
            }
        )
        ctx_df = _empty_ctx_df(3)
        when = {"today.close": {"between": [100.0, 110.0]}}
        result = evaluate_vectorized(when, df, ctx_df)
        assert result.tolist() == [False, True, False]


# ---------------------------------------------------------------------------
# Extra: gap_up / gap_down / fills_gap
# ---------------------------------------------------------------------------


class TestGapFields:
    def test_gap_up_vectorized(self):
        """gap_up: next_day.open > today.close (proxy: close.shift(-1) < open.shift(-1))"""
        df = pd.DataFrame(
            {
                "open": [100, 120, 100],   # row1 opens high
                "high": [105, 125, 105],
                "low": [95, 115, 95],
                "close": [102, 122, 102],
                "volume": [1e6, 1e6, 1e6],
            }
        )
        ctx_df = _empty_ctx_df(3)
        # gap_up checks: next_day close.shift(-1) < next_day open.shift(-1)
        when = {"next_day.gap_up": True}
        result = evaluate_vectorized(when, df, ctx_df, next_day_n=1)
        assert isinstance(result, pd.Series)

    def test_gap_boolean_field_non_bool_raises(self):
        row = _make_row()
        ctx = _empty_ctx()
        with pytest.raises(UnknownTokenError):
            evaluate({"next_day.gap_up": "true"}, row, ctx)

    def test_gap_fields_scalar_returns_none(self):
        """next_day.gap_up/down/fills_gap → pending in scalar mode."""
        row = _make_row()
        ctx = _empty_ctx()
        for field in ("next_day.gap_up", "next_day.gap_down", "next_day.fills_gap"):
            assert evaluate({field: True}, row, ctx) is None

    def test_fills_gap_vectorized_shape(self):
        df = _make_df(5)
        ctx_df = _empty_ctx_df(5)
        when = {"next_day.fills_gap": True}
        result = evaluate_vectorized(when, df, ctx_df, next_day_n=1)
        assert len(result) == 5


# ---------------------------------------------------------------------------
# Extra: nesting depth > 2 raises
# ---------------------------------------------------------------------------


class TestNestingDepth:
    def test_nesting_depth_3_raises(self):
        """Three levels deep should raise UnknownTokenError."""
        row = _make_row()
        ctx = _empty_ctx()
        when = {
            "all": [
                {
                    "any": [
                        {
                            "all": [  # depth=3
                                {"today.close": "> 100"}
                            ]
                        }
                    ]
                }
            ]
        }
        with pytest.raises(UnknownTokenError) as exc:
            evaluate(when, row, ctx)
        assert "depth" in str(exc.value).lower() or "nesting" in str(exc.value).lower()

    def test_nesting_depth_2_passes(self):
        """Two levels deep is allowed."""
        row = _make_row(close=108.0)
        ctx = _empty_ctx()
        when = {
            "all": [
                {
                    "any": [
                        {"today.close": "> 100"}
                    ]
                }
            ]
        }
        result = evaluate(when, row, ctx)
        assert result is True


# ---------------------------------------------------------------------------
# Extra: prev.* fields
# ---------------------------------------------------------------------------


class TestPrevFields:
    def test_prev_close_scalar(self):
        row = _make_row(close=108.0, prev_close=104.0)
        ctx = _empty_ctx()
        when = {"prev.close": "< 105"}
        assert evaluate(when, row, ctx) is True

    def test_prev_high_scalar(self):
        row = _make_row(high=110.0, prev_high=105.0)
        ctx = _empty_ctx()
        when = {"prev.high": ">= 105"}
        assert evaluate(when, row, ctx) is True


# ---------------------------------------------------------------------------
# Extra: top-level whitelist fields (attack_cost, defensive_low, etc.)
# ---------------------------------------------------------------------------


class TestTopLevelFields:
    def test_attack_cost_scalar(self):
        row = _make_row(close=108.0)
        row["attack_cost"] = 105.0
        ctx = _empty_ctx()
        when = {"today.close": "> attack_cost"}
        assert evaluate(when, row, ctx) is True

    def test_prior_low_60_vectorized(self):
        df = _make_df(3)
        df["prior_low_60"] = [90.0, 92.0, 94.0]
        ctx_df = _empty_ctx_df(3)
        when = {"today.low": "> prior_low_60"}
        result = evaluate_vectorized(when, df, ctx_df)
        # today.low: [95,96,97] vs prior_low_60: [90,92,94] → all True
        assert result.tolist() == [True, True, True]


# ---------------------------------------------------------------------------
# Performance: vectorized 1000-row df < 50ms
# ---------------------------------------------------------------------------


class TestPerformance:
    def test_vectorized_1000_rows_under_50ms(self):
        import numpy as np

        n = 1000
        rng = np.random.default_rng(42)
        df = pd.DataFrame(
            {
                "open": rng.uniform(90, 110, n),
                "high": rng.uniform(105, 130, n),
                "low": rng.uniform(70, 95, n),
                "close": rng.uniform(95, 120, n),
                "volume": rng.integers(500_000, 5_000_000, n).astype(float),
            }
        )
        ctx_df = pd.DataFrame(
            {
                "ma5_will_rise": rng.choice([True, False], n),
                "ma10_will_rise": rng.choice([True, False], n),
            },
            index=df.index,
        )
        when = {
            "all": [
                {"any": [
                    {"next_day.close": "> today.high"},
                    {"context.ma5_will_rise": True},
                ]},
                {"today.volume": ">= 1000000"},
            ]
        }
        start = time.perf_counter()
        result = evaluate_vectorized(when, df, ctx_df, next_day_n=1)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert len(result) == n
        assert elapsed_ms < 50, f"vectorized took {elapsed_ms:.1f}ms (limit: 50ms)"
