"""strict_breakout.filter: non-course filter — red K + close_pos + volume_ratio."""
from __future__ import annotations

from kline.extras.strict_breakout import filter as strict_filter

from tests.conftest import make_bars


def _bars_for_filter():
    rows = [
        {"open": 100, "high": 105, "low": 99,  "close": 104, "volume": 2000},
        {"open": 100, "high": 105, "low": 99,  "close": 99,  "volume": 2000},
        {"open": 100, "high": 105, "low": 99,  "close": 101, "volume": 2000},
    ]
    df = make_bars(rows)
    df["is_red"] = df["close"] > df["open"]
    df["close_pos"] = (df["close"] - df["low"]) / (df["high"] - df["low"])
    df["volume_ratio"] = [2.0, 2.0, 2.0]
    return df


def test_filter_passes_red_high_close_pos_high_volume():
    df = _bars_for_filter()
    out = strict_filter(df)
    assert out.iloc[0]


def test_filter_blocks_black_k():
    df = _bars_for_filter()
    out = strict_filter(df)
    assert not out.iloc[1]


def test_filter_blocks_low_close_pos():
    df = _bars_for_filter()
    out = strict_filter(df)
    assert not out.iloc[2]
