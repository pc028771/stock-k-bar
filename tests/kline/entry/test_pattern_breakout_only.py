"""pattern_breakout_only entry signal tests."""
from __future__ import annotations

from kline.entry.pattern_breakout_only import detect
from kline.features import add_features

from tests.conftest import make_bars


def test_fires_on_pattern_breakout():
    """60+ bars of tight range, then breakout = pattern breakout = entry."""
    rows = [
        {
            "open": 100 + (i % 5 - 2),
            "high": 102,
            "low": 98,
            "close": 100 + (i % 5 - 2),
            "volume": 1000.0,
            "ma60": 100.0,
        }
        for i in range(60)
    ]
    rows.append(
        {"open": 100, "high": 110, "low": 99, "close": 109, "volume": 1000.0, "ma60": 100.0}
    )
    df = add_features(make_bars(rows))
    signal = detect(df)
    assert signal.iloc[60]


def test_does_not_fire_on_continuation():
    """Wide oscillation (range > 15%) + breakout = continuation, NOT entry."""
    rows = []
    for i in range(60):
        if i % 2 == 0:
            rows.append(
                {"open": 110, "high": 120, "low": 105, "close": 115,
                 "volume": 1000.0, "ma60": 100.0}
            )
        else:
            rows.append(
                {"open": 90, "high": 95, "low": 80, "close": 85, "volume": 1000.0, "ma60": 100.0}
            )
    rows.append(
        {"open": 115, "high": 125, "low": 110, "close": 124, "volume": 1000.0, "ma60": 100.0}
    )
    df = add_features(make_bars(rows))
    signal = detect(df)
    assert not signal.iloc[60]  # No box → no pattern breakout → no entry


def test_excludes_breakdown_pattern():
    """If in breakdown pattern, even if technically pattern breakout, excluded."""
    rows = [
        {
            "open": 100 + (i % 5 - 2),
            "high": 102,
            "low": 98,
            "close": 100 + (i % 5 - 2),
            "volume": 1000.0,
            "ma60": 100.0,
        }
        for i in range(60)
    ]
    rows.append(
        {"open": 100, "high": 110, "low": 99, "close": 109, "volume": 1000.0, "ma60": 100.0}
    )
    df = add_features(make_bars(rows))
    df.loc[60, "is_in_breakdown_pattern"] = True
    signal = detect(df)
    assert not signal.iloc[60]
