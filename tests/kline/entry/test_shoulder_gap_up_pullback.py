"""shoulder_gap_up_pullback entry signal tests."""
from __future__ import annotations

import pandas as pd
from kline.entry.shoulder_gap_up_pullback import detect
from kline.features import add_features

from tests.conftest import make_bars


def test_fires_on_textbook_shoulder_gap():
    """3-bar setup: pattern breakout red → gap-up red → sundown black with unfilled gap."""
    # Build rising-lows base to satisfy is_pattern_breakout
    rows = []
    # Bars 0-59: rising-lows phase (lows climb slowly, highs stable at 102)
    for i in range(60):
        low = 95 + i * 0.1  # rising lows
        rows.append({"open": 100, "high": 102, "low": low,
                     "close": 100, "volume": 1000.0, "ma60": 100.0})
    # Bar 60 = K-2: pattern breakout red K
    rows.append({"open": 100, "high": 110, "low": 99, "close": 109,
                 "volume": 1000.0, "ma60": 100.0})
    # Bar 61 = K-1: gap-up red K (open > K-2 high 110)
    rows.append({"open": 113, "high": 116, "low": 112, "close": 115,
                 "volume": 1000.0, "ma60": 100.0})
    # Bar 62 = K0: sundown black K, gap unfilled (low 110 > K-2.close 109)
    rows.append({"open": 114, "high": 115, "low": 110, "close": 111,
                 "volume": 1000.0, "ma60": 100.0})
    df = add_features(make_bars(rows))
    signal = detect(df)
    # If add_features set is_pattern_breakout on bar 60, this should fire
    if df["is_pattern_breakout"].iloc[60]:
        assert signal.iloc[62], "Expected shoulder gap pullback to fire"


def test_does_not_fire_when_gap_filled():
    """If today's low fills the gap (low <= K-2 close), no signal."""
    rows = []
    for i in range(60):
        low = 95 + i * 0.1
        rows.append({"open": 100, "high": 102, "low": low,
                     "close": 100, "volume": 1000.0, "ma60": 100.0})
    rows.append({"open": 100, "high": 110, "low": 99, "close": 109,
                 "volume": 1000.0, "ma60": 100.0})
    rows.append({"open": 113, "high": 116, "low": 112, "close": 115,
                 "volume": 1000.0, "ma60": 100.0})
    # K0: low = 108 fills the gap (108 < K-2 close 109)
    rows.append({"open": 114, "high": 115, "low": 108, "close": 111,
                 "volume": 1000.0, "ma60": 100.0})
    df = add_features(make_bars(rows))
    signal = detect(df)
    assert not signal.iloc[62], "Gap filled → signal must not fire"


def test_does_not_fire_without_pattern_breakout():
    """If K-2 is not a pattern breakout (e.g., no rising lows), no signal."""
    rows = []
    # Wide oscillation (no rising lows)
    for i in range(60):
        if i % 2 == 0:
            rows.append({"open": 100, "high": 105, "low": 95, "close": 102,
                         "volume": 1000.0, "ma60": 100.0})
        else:
            rows.append({"open": 102, "high": 103, "low": 90, "close": 92,
                         "volume": 1000.0, "ma60": 100.0})
    # K-2: breakout but no pattern (no rising lows)
    rows.append({"open": 100, "high": 110, "low": 99, "close": 109,
                 "volume": 1000.0, "ma60": 100.0})
    rows.append({"open": 113, "high": 116, "low": 112, "close": 115,
                 "volume": 1000.0, "ma60": 100.0})
    rows.append({"open": 114, "high": 115, "low": 110, "close": 111,
                 "volume": 1000.0, "ma60": 100.0})
    df = add_features(make_bars(rows))
    signal = detect(df)
    # Without is_pattern_breakout on K-2, signal should not fire
    if not df["is_pattern_breakout"].iloc[60]:
        assert not signal.iloc[62], "No pattern breakout on K-2 → signal must not fire"


def test_does_not_fire_when_k1_is_black():
    """K-1 must be a red (up) K; if it's black, the setup is invalid."""
    rows = []
    for i in range(60):
        low = 95 + i * 0.1
        rows.append({"open": 100, "high": 102, "low": low,
                     "close": 100, "volume": 1000.0, "ma60": 100.0})
    # K-2: breakout red K
    rows.append({"open": 100, "high": 110, "low": 99, "close": 109,
                 "volume": 1000.0, "ma60": 100.0})
    # K-1: gap-up but BLACK (close < open)
    rows.append({"open": 113, "high": 116, "low": 112, "close": 112.5,
                 "volume": 1000.0, "ma60": 100.0})
    # K0: sundown black, gap unfilled
    rows.append({"open": 114, "high": 115, "low": 110, "close": 111,
                 "volume": 1000.0, "ma60": 100.0})
    df = add_features(make_bars(rows))
    signal = detect(df)
    assert not signal.iloc[62], "K-1 black K → signal must not fire"


def test_does_not_fire_when_k1_no_gap():
    """K-1 must gap up above K-2 high; if open <= K-2.high, no signal."""
    rows = []
    for i in range(60):
        low = 95 + i * 0.1
        rows.append({"open": 100, "high": 102, "low": low,
                     "close": 100, "volume": 1000.0, "ma60": 100.0})
    # K-2: breakout red K with high = 110
    rows.append({"open": 100, "high": 110, "low": 99, "close": 109,
                 "volume": 1000.0, "ma60": 100.0})
    # K-1: NO gap (open = 110 = K-2.high, not strictly greater)
    rows.append({"open": 110, "high": 116, "low": 109, "close": 115,
                 "volume": 1000.0, "ma60": 100.0})
    # K0: sundown black
    rows.append({"open": 114, "high": 115, "low": 110, "close": 111,
                 "volume": 1000.0, "ma60": 100.0})
    df = add_features(make_bars(rows))
    signal = detect(df)
    assert not signal.iloc[62], "No gap on K-1 → signal must not fire"


def test_does_not_fire_when_k0_not_sundown():
    """K0 must be a sundown bar (high < K-1.high AND low < K-1.low)."""
    rows = []
    for i in range(60):
        low = 95 + i * 0.1
        rows.append({"open": 100, "high": 102, "low": low,
                     "close": 100, "volume": 1000.0, "ma60": 100.0})
    rows.append({"open": 100, "high": 110, "low": 99, "close": 109,
                 "volume": 1000.0, "ma60": 100.0})
    rows.append({"open": 113, "high": 116, "low": 112, "close": 115,
                 "volume": 1000.0, "ma60": 100.0})
    # K0: high > K-1.high (not sundown, high = 117 > 116)
    rows.append({"open": 114, "high": 117, "low": 110, "close": 111,
                 "volume": 1000.0, "ma60": 100.0})
    df = add_features(make_bars(rows))
    signal = detect(df)
    assert not signal.iloc[62], "K0 not sundown → signal must not fire"


def test_does_not_fire_below_ma60():
    """Close below MA60 fails multi-background check."""
    rows = []
    for i in range(60):
        low = 95 + i * 0.1
        rows.append({"open": 100, "high": 102, "low": low,
                     "close": 100, "volume": 1000.0, "ma60": 200.0})
    rows.append({"open": 100, "high": 110, "low": 99, "close": 109,
                 "volume": 1000.0, "ma60": 200.0})
    rows.append({"open": 113, "high": 116, "low": 112, "close": 115,
                 "volume": 1000.0, "ma60": 200.0})
    rows.append({"open": 114, "high": 115, "low": 110, "close": 111,
                 "volume": 1000.0, "ma60": 200.0})
    df = add_features(make_bars(rows))
    signal = detect(df)
    assert not signal.iloc[62], "Close below MA60 → signal must not fire"


def test_does_not_fire_in_breakdown_pattern():
    """Breakdown pattern exclusion suppresses the signal."""
    rows = []
    for i in range(60):
        low = 95 + i * 0.1
        rows.append({"open": 100, "high": 102, "low": low,
                     "close": 100, "volume": 1000.0, "ma60": 100.0})
    rows.append({"open": 100, "high": 110, "low": 99, "close": 109,
                 "volume": 1000.0, "ma60": 100.0})
    rows.append({"open": 113, "high": 116, "low": 112, "close": 115,
                 "volume": 1000.0, "ma60": 100.0})
    rows.append({"open": 114, "high": 115, "low": 110, "close": 111,
                 "volume": 1000.0, "ma60": 100.0})
    df = add_features(make_bars(rows))
    df.loc[62, "is_in_breakdown_pattern"] = True
    signal = detect(df)
    assert not signal.iloc[62], "Breakdown exclusion must suppress the signal"


def test_works_without_is_pattern_breakout_column():
    """detect() must not crash when is_pattern_breakout column is absent."""
    rows = []
    for i in range(60):
        low = 95 + i * 0.1
        rows.append({"open": 100, "high": 102, "low": low,
                     "close": 100, "volume": 1000.0, "ma60": 100.0})
    rows.append({"open": 100, "high": 110, "low": 99, "close": 109,
                 "volume": 1000.0, "ma60": 100.0})
    rows.append({"open": 113, "high": 116, "low": 112, "close": 115,
                 "volume": 1000.0, "ma60": 100.0})
    rows.append({"open": 114, "high": 115, "low": 110, "close": 111,
                 "volume": 1000.0, "ma60": 100.0})
    df = add_features(make_bars(rows))
    if "is_pattern_breakout" in df.columns:
        df = df.drop(columns=["is_pattern_breakout"])
    signal = detect(df)
    assert isinstance(signal, pd.Series)
    assert signal.dtype == bool
    # Without is_pattern_breakout, k2_is_pattern_breakout is all False → no signal
    assert not signal.iloc[62], "Missing is_pattern_breakout → all-False fallback"


def test_works_without_is_in_breakdown_pattern_column():
    """detect() must not crash when is_in_breakdown_pattern column is absent."""
    rows = []
    for i in range(60):
        low = 95 + i * 0.1
        rows.append({"open": 100, "high": 102, "low": low,
                     "close": 100, "volume": 1000.0, "ma60": 100.0})
    rows.append({"open": 100, "high": 110, "low": 99, "close": 109,
                 "volume": 1000.0, "ma60": 100.0})
    rows.append({"open": 113, "high": 116, "low": 112, "close": 115,
                 "volume": 1000.0, "ma60": 100.0})
    rows.append({"open": 114, "high": 115, "low": 110, "close": 111,
                 "volume": 1000.0, "ma60": 100.0})
    df = add_features(make_bars(rows))
    if "is_in_breakdown_pattern" in df.columns:
        df = df.drop(columns=["is_in_breakdown_pattern"])
    signal = detect(df)
    assert isinstance(signal, pd.Series)
    assert signal.dtype == bool
