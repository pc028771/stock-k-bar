"""sunrise.detect: 連續 3 日 sunrise + breakout."""
from __future__ import annotations

from kline.entry.sunrise import detect
from kline.features import add_features

from tests.conftest import make_bars


def test_sunrise_after_breakout_triggers():
    rows = [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
             "volume": 1000.0, "ma60": 100.0} for _ in range(60)]
    rows.append({"open": 105.0, "high": 111.0, "low": 99.0, "close": 110.0,
                 "volume": 1000.0, "ma60": 100.0})
    rows.append({"open": 110.0, "high": 112.0, "low": 100.0, "close": 111.0,
                 "volume": 1000.0, "ma60": 100.0})
    rows.append({"open": 111.0, "high": 113.0, "low": 101.0, "close": 112.0,
                 "volume": 1000.0, "ma60": 100.0})
    df = add_features(make_bars(rows))
    signal = detect(df)
    assert signal.iloc[62]
    assert not signal.iloc[61]


def test_no_sunrise_when_streak_broken():
    rows = [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
             "volume": 1000.0, "ma60": 100.0} for _ in range(60)]
    rows.append({"open": 105.0, "high": 111.0, "low": 99.0, "close": 110.0,
                 "volume": 1000.0, "ma60": 100.0})
    rows.append({"open": 110.0, "high": 112.0, "low": 100.0, "close": 111.0,
                 "volume": 1000.0, "ma60": 100.0})
    # bar 62: low does NOT exceed prev_low — streak broken
    rows.append({"open": 111.0, "high": 113.0, "low": 99.0, "close": 112.0,
                 "volume": 1000.0, "ma60": 100.0})
    df = add_features(make_bars(rows))
    signal = detect(df)
    assert not signal.iloc[62]
