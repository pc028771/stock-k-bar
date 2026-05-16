"""tweezer_top_breakout entry signal tests."""
from __future__ import annotations

import pandas as pd
from kline.entry.tweezer_top_breakout import detect
from kline.features import add_features

from tests.conftest import make_bars


def test_fires_when_breakout_above_tweezer_high():
    """5 K-lines with highs ~ 102, then breakout above 102."""
    rows = []
    # Bars 0-59: oscillating but staying below 102
    for i in range(60):
        rows.append({"open": 99, "high": 101 + (i % 3) * 0.3, "low": 98,
                     "close": 100, "volume": 1000.0, "ma60": 100.0})
    # Bars 60-63: tweezer top — highs all ~102
    for h in [102.0, 102.1, 101.9, 102.0]:
        rows.append({"open": 100, "high": h, "low": 99,
                     "close": 100, "volume": 1000.0, "ma60": 100.0})
    # Bar 64: breakout above tweezer high (102) → close = 105
    rows.append({"open": 102, "high": 106, "low": 101, "close": 105,
                 "volume": 1000.0, "ma60": 100.0})
    df = add_features(make_bars(rows))
    signal = detect(df)
    assert signal.iloc[64], "Expected tweezer top breakout to fire"


def test_does_not_fire_without_breakout():
    """Tweezer formation exists but close does NOT break above the common high."""
    rows = []
    for i in range(60):
        rows.append({"open": 99, "high": 101 + (i % 3) * 0.3, "low": 98,
                     "close": 100, "volume": 1000.0, "ma60": 100.0})
    # Bars 60-63: tweezer top — highs all ~102
    for h in [102.0, 102.1, 101.9, 102.0]:
        rows.append({"open": 100, "high": h, "low": 99,
                     "close": 100, "volume": 1000.0, "ma60": 100.0})
    # Bar 64: no breakout — close stays below tweezer high
    rows.append({"open": 100, "high": 102.5, "low": 99, "close": 101,
                 "volume": 1000.0, "ma60": 100.0})
    df = add_features(make_bars(rows))
    signal = detect(df)
    assert not signal.iloc[64], "No breakout → signal must not fire"


def test_does_not_fire_without_similar_highs():
    """No tweezer formation (highs vary widely) → no entry even with breakout.

    prior_max_high at bar 64 = 120.
    Past 5 highs: 100, 105, 110, 115, 120.
    Only 120 is within 2% of 120 (the max). All others are > 4% away.
    similar_count = 1 < TWEEZER_MIN_COUNT=2 → no tweezer.
    """
    rows = []
    for _i in range(60):
        rows.append({"open": 99, "high": 99, "low": 98,
                     "close": 98, "volume": 1000.0, "ma60": 100.0})
    # Last 5 bars: widely spread highs — each 5% apart from the next
    for h in [100.0, 105.0, 110.0, 115.0, 120.0]:
        rows.append({"open": h - 1, "high": h, "low": h - 2,
                     "close": h - 0.5, "volume": 1000.0, "ma60": 100.0})
    # Bar 65: "breakout" above 120 — but prior 5 highs span too wide for tweezer
    rows.append({"open": 120, "high": 125, "low": 119, "close": 124,
                 "volume": 1000.0, "ma60": 100.0})
    df = add_features(make_bars(rows))
    signal = detect(df)
    assert not signal.iloc[65], "Wide-spread highs must not qualify as tweezer"


def test_does_not_fire_in_breakdown_pattern():
    """Tweezer setup but in breakdown pattern → excluded."""
    rows = []
    for i in range(60):
        rows.append({"open": 99, "high": 101 + (i % 3) * 0.3, "low": 98,
                     "close": 100, "volume": 1000.0, "ma60": 100.0})
    for h in [102.0, 102.1, 101.9, 102.0]:
        rows.append({"open": 100, "high": h, "low": 99,
                     "close": 100, "volume": 1000.0, "ma60": 100.0})
    rows.append({"open": 102, "high": 106, "low": 101, "close": 105,
                 "volume": 1000.0, "ma60": 100.0})
    df = add_features(make_bars(rows))
    df.loc[64, "is_in_breakdown_pattern"] = True
    signal = detect(df)
    assert not signal.iloc[64], "Breakdown pattern exclusion must suppress the signal"


def test_does_not_fire_below_ma60():
    """Tweezer breakout but close < ma60 → multi-background fails."""
    rows = []
    for i in range(60):
        rows.append({"open": 99, "high": 101 + (i % 3) * 0.3, "low": 98,
                     "close": 100, "volume": 1000.0, "ma60": 110.0})  # ma60 above price
    for h in [102.0, 102.1, 101.9, 102.0]:
        rows.append({"open": 100, "high": h, "low": 99,
                     "close": 100, "volume": 1000.0, "ma60": 110.0})
    rows.append({"open": 102, "high": 106, "low": 101, "close": 105,
                 "volume": 1000.0, "ma60": 110.0})
    df = add_features(make_bars(rows))
    signal = detect(df)
    assert not signal.iloc[64], "Close below MA60 must block the signal"


def test_works_without_is_in_breakdown_pattern_column():
    """detect() must not crash when is_in_breakdown_pattern column is absent."""
    rows = []
    for i in range(60):
        rows.append({"open": 99, "high": 101 + (i % 3) * 0.3, "low": 98,
                     "close": 100, "volume": 1000.0, "ma60": 100.0})
    for h in [102.0, 102.1, 101.9, 102.0]:
        rows.append({"open": 100, "high": h, "low": 99,
                     "close": 100, "volume": 1000.0, "ma60": 100.0})
    rows.append({"open": 102, "high": 106, "low": 101, "close": 105,
                 "volume": 1000.0, "ma60": 100.0})
    df = add_features(make_bars(rows))
    # Drop the column if add_features created it
    if "is_in_breakdown_pattern" in df.columns:
        df = df.drop(columns=["is_in_breakdown_pattern"])
    signal = detect(df)
    assert isinstance(signal, pd.Series)
    assert signal.dtype == bool
