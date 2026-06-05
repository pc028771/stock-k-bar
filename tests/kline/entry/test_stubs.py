"""trend_reversal STUB 已升級為 多空轉折組合 K 線 patterns wrapper.

不再 assert STUB 字串; 保留 sanity check (bool series with correct length).
"""
from __future__ import annotations

from kline.entry import ENTRY_REGISTRY, trend_reversal
from kline.features import add_features

from tests.conftest import make_bars


def _sample_df():
    rows = [{"open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000} for _ in range(5)]
    return add_features(make_bars(rows))


def test_trend_reversal_returns_bool_series():
    df = _sample_df()
    out = trend_reversal.detect(df)
    assert out.dtype == bool
    assert len(out) == len(df)
    # Flat 5-bar data should not trigger any bullish reversal pattern
    assert not out.any()


def test_registry_includes_all_entry_conditions():
    assert "breakout_attack" in ENTRY_REGISTRY
    assert "pattern_breakout_only" in ENTRY_REGISTRY
    assert "tweezer_top_breakout" in ENTRY_REGISTRY
    assert "tweezer_top_breakout_strict" in ENTRY_REGISTRY
    assert "shoulder_gap_up_pullback" in ENTRY_REGISTRY  # 型態學 17 唯一拉回承接
    assert "trend_reversal" in ENTRY_REGISTRY
    assert "sunrise_attack" in ENTRY_REGISTRY
    assert "combined_pattern_or_tweezer" in ENTRY_REGISTRY


def test_trend_reversal_docstring_no_longer_stub():
    # STUB upgraded to 多空轉折 patterns wrapper — should NOT start with STUB:
    assert not trend_reversal.__doc__.startswith("STUB:")
