"""combined_pattern_or_tweezer entry tests."""
from __future__ import annotations

from kline.entry.combined_pattern_or_tweezer import detect
from kline.entry.pattern_breakout_only import detect as pattern_detect
from kline.entry.tweezer_top_breakout import detect as tweezer_detect
from kline.features import add_features

from tests.conftest import make_bars


def _make_df(rows):
    return add_features(make_bars(rows))


def test_combined_equals_union_of_components():
    """Combined output must exactly equal pattern | tweezer on every bar."""
    rows = []
    for i in range(60):
        rows.append(
            {
                "open": 99,
                "high": 101 + (i % 3) * 0.3,
                "low": 98,
                "close": 100,
                "volume": 1000.0,
                "ma60": 100.0,
            }
        )
    for h in [102.0, 102.1, 101.9, 102.0]:
        rows.append(
            {"open": 100, "high": h, "low": 99, "close": 100, "volume": 1000.0, "ma60": 100.0}
        )
    rows.append(
        {"open": 102, "high": 106, "low": 101, "close": 105, "volume": 1000.0, "ma60": 100.0}
    )
    df = _make_df(rows)

    combined = detect(df)
    expected = (pattern_detect(df) | tweezer_detect(df)).fillna(False)

    assert (combined == expected).all(), "combined must equal pattern | tweezer on every bar"


def test_combined_fires_when_either_component_fires():
    """If either component fires on a bar, combined must also fire on that bar."""
    rows = []
    for i in range(60):
        rows.append(
            {
                "open": 99,
                "high": 101 + (i % 3) * 0.3,
                "low": 98,
                "close": 100,
                "volume": 1000.0,
                "ma60": 100.0,
            }
        )
    for h in [102.0, 102.1, 101.9, 102.0]:
        rows.append(
            {"open": 100, "high": h, "low": 99, "close": 100, "volume": 1000.0, "ma60": 100.0}
        )
    rows.append(
        {"open": 102, "high": 106, "low": 101, "close": 105, "volume": 1000.0, "ma60": 100.0}
    )
    df = _make_df(rows)

    combined = detect(df)
    p = pattern_detect(df)
    t = tweezer_detect(df)

    for i in range(len(df)):
        if p.iloc[i] or t.iloc[i]:
            assert combined.iloc[i], f"bar {i}: either component fires but combined does not"


def test_combined_returns_bool_series_same_length():
    """Output dtype must be bool, length matches input."""
    rows = [{"open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000} for _ in range(5)]
    df = _make_df(rows)
    out = detect(df)
    assert out.dtype == bool
    assert len(out) == len(df)


def test_combined_never_fires_when_neither_component_fires():
    """Combined must be False whenever both components are False."""
    rows = [
        {"open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000} for _ in range(5)
    ]
    df = _make_df(rows)
    combined = detect(df)
    p = pattern_detect(df)
    t = tweezer_detect(df)

    for i in range(len(df)):
        if not p.iloc[i] and not t.iloc[i]:
            assert not combined.iloc[i], (
                f"bar {i}: neither component fires but combined is True"
            )
