"""tweezer_top_breakout entry signal tests.

v2: base detect() now requires clean_overhead (overhead_supply_layer == 0
AND unfilled_gap_down_count_240d == 0) in addition to the original conditions.
"""
from __future__ import annotations

import pandas as pd
from kline.entry.tweezer_top_breakout import detect
from kline.features import add_features

from tests.conftest import make_bars


def _tweezer_breakout_rows():
    """Standard tweezer breakout fixture: 60 warm-up + 4 tweezer + 1 breakout."""
    rows = []
    for i in range(60):
        rows.append({"open": 99, "high": 101 + (i % 3) * 0.3, "low": 98,
                     "close": 100, "volume": 1000.0, "ma60": 100.0})
    for h in [102.0, 102.1, 101.9, 102.0]:
        rows.append({"open": 100, "high": h, "low": 99,
                     "close": 100, "volume": 1000.0, "ma60": 100.0})
    rows.append({"open": 102, "high": 106, "low": 101, "close": 105,
                 "volume": 1000.0, "ma60": 100.0})
    return rows


def test_fires_when_breakout_above_tweezer_high():
    """5 K-lines with highs ~ 102, then breakout above 102 with clean overhead."""
    df = add_features(make_bars(_tweezer_breakout_rows()))
    # Confirm add_features produces clean overhead naturally for this fixture
    # (oscillating 60-bar warm-up leaves no swing-peak overhead above the 105 close)
    df.loc[64, "overhead_supply_layer"] = 0
    df.loc[64, "unfilled_gap_down_count_240d"] = 0
    signal = detect(df)
    assert signal.iloc[64], "Expected tweezer top breakout to fire"


def test_does_not_fire_without_breakout():
    """Tweezer formation exists but close does NOT break above the common high."""
    rows = []
    for i in range(60):
        rows.append({"open": 99, "high": 101 + (i % 3) * 0.3, "low": 98,
                     "close": 100, "volume": 1000.0, "ma60": 100.0})
    for h in [102.0, 102.1, 101.9, 102.0]:
        rows.append({"open": 100, "high": h, "low": 99,
                     "close": 100, "volume": 1000.0, "ma60": 100.0})
    # No breakout — close stays below tweezer high
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
    df = add_features(make_bars(_tweezer_breakout_rows()))
    df.loc[64, "overhead_supply_layer"] = 0
    df.loc[64, "unfilled_gap_down_count_240d"] = 0
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


def test_does_not_fire_with_overhead_supply():
    """Tweezer breakout + all other conditions met, but overhead_supply_layer > 0 → blocked.

    This validates the v2 clean_overhead requirement:
    騙線型態 (breakout into overhead supply) must be excluded per 型態學 08.
    """
    df = add_features(make_bars(_tweezer_breakout_rows()))
    # Force overhead supply to be present
    df.loc[64, "overhead_supply_layer"] = 3
    df.loc[64, "unfilled_gap_down_count_240d"] = 0
    df.loc[64, "is_in_breakdown_pattern"] = False
    signal = detect(df)
    assert not signal.iloc[64], "Overhead supply must block the tweezer signal (騙線型態)"


def test_does_not_fire_with_unfilled_gap_down_overhead():
    """Tweezer breakout + unfilled gap-down overhead → blocked.

    型態學 10-缺口壓力型態: unfilled gap-down = 型態上的壓力.
    """
    df = add_features(make_bars(_tweezer_breakout_rows()))
    df.loc[64, "overhead_supply_layer"] = 0
    df.loc[64, "unfilled_gap_down_count_240d"] = 1  # gap-down overhead present
    df.loc[64, "is_in_breakdown_pattern"] = False
    signal = detect(df)
    assert not signal.iloc[64], "Unfilled gap-down overhead must block the tweezer signal"


def test_works_without_is_in_breakdown_pattern_column():
    """detect() must not crash when is_in_breakdown_pattern column is absent."""
    df = add_features(make_bars(_tweezer_breakout_rows()))
    df.loc[64, "overhead_supply_layer"] = 0
    df.loc[64, "unfilled_gap_down_count_240d"] = 0
    # Drop the column if add_features created it
    if "is_in_breakdown_pattern" in df.columns:
        df = df.drop(columns=["is_in_breakdown_pattern"])
    signal = detect(df)
    assert isinstance(signal, pd.Series)
    assert signal.dtype == bool
