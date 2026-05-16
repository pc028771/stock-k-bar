"""Verify stub entry conditions return all-False and follow STUB convention."""
from __future__ import annotations

from kline.entry import ENTRY_REGISTRY, trend_reversal
from kline.features import add_features

from tests.conftest import make_bars


def _sample_df():
    rows = [{"open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000} for _ in range(5)]
    return add_features(make_bars(rows))


def test_trend_reversal_stub_returns_all_false():
    df = _sample_df()
    out = trend_reversal.detect(df)
    assert out.dtype == bool
    assert not out.any()
    assert len(out) == len(df)


def test_registry_includes_all_entry_conditions():
    assert "breakout_attack" in ENTRY_REGISTRY
    assert "pattern_breakout_only" in ENTRY_REGISTRY
    assert "tweezer_top_breakout" in ENTRY_REGISTRY  # NEW
    assert "trend_reversal" in ENTRY_REGISTRY
    assert "sunrise_attack" in ENTRY_REGISTRY


def test_stub_docstring_starts_with_stub_marker():
    assert trend_reversal.__doc__.startswith("STUB:")
