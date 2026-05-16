"""pattern_breakout_only entry signal tests."""
from __future__ import annotations

from kline.entry.pattern_breakout_only import detect
from kline.features import add_features

from tests.conftest import make_bars


def test_fires_on_pattern_breakout():
    """60+ bars of rising lows + stable ceiling, then breakout = pattern breakout = entry.

    Course: 低點漸漸墊高 + 上緣穩定 = 主力收貨三角收斂 → 突破 = 起點
    """
    rows = []
    base_low = 95.0
    for i in range(61):
        # Lows climb steadily → every bar has a higher low
        low = base_low + i * 0.1
        rows.append({
            "open": low + 2.0,
            "high": 102.0,   # stable ceiling at 102
            "low": low,
            "close": low + 1.5,
            "volume": 1000.0,
            "ma60": 90.0,
        })
    # Breakout day: close > prior_high_60 (102) and above ma60 (90)
    rows.append({
        "open": 103.0,
        "high": 106.0,
        "low": 102.5,
        "close": 105.0,
        "volume": 2000.0,
        "ma60": 90.0,
    })
    df = add_features(make_bars(rows))
    signal = detect(df)
    assert signal.iloc[61]


def test_does_not_fire_on_sleeping_stock():
    """Dead-flat stock (no rising lows) + breakout → NOT entry.

    Course: sleeping stocks are NOT 主力收貨 patterns — no rising lows means
    no 三角收斂 accumulation structure.
    """
    rows = [{"open": 100.0, "high": 102.0, "low": 98.0, "close": 100.0,
             "volume": 1000.0, "ma60": 90.0} for _ in range(60)]
    # Breakout day above the flat 102 ceiling
    rows.append({"open": 102.0, "high": 106.0, "low": 101.5, "close": 105.0,
                 "volume": 2000.0, "ma60": 90.0})
    df = add_features(make_bars(rows))
    signal = detect(df)
    assert not signal.iloc[60]  # No rising lows → no pattern breakout → no entry


def test_does_not_fire_on_oscillating_stock():
    """Wide oscillation (no rising-low trend) + breakout → NOT entry.

    Uses a 3-step down cycle so higher_low_count = 20/60 < 30 threshold.
    """
    rows = []
    cycle_lows = [105.0, 80.0, 60.0]
    for i in range(60):
        lo = cycle_lows[i % 3]
        hi = lo + 40.0 if lo == 60.0 else lo + 15.0
        rows.append({"open": lo + 5.0, "high": hi, "low": lo, "close": lo + 3.0,
                     "volume": 1000.0, "ma60": 100.0})
    rows.append(
        {"open": 115.0, "high": 125.0, "low": 110.0, "close": 124.0,
         "volume": 1000.0, "ma60": 100.0}
    )
    df = add_features(make_bars(rows))
    signal = detect(df)
    assert not signal.iloc[60]  # No rising-low accumulation → no pattern breakout → no entry


def test_excludes_breakdown_pattern():
    """If in breakdown pattern, even if technically pattern breakout, excluded."""
    rows = []
    base_low = 95.0
    for i in range(61):
        low = base_low + i * 0.1
        rows.append({
            "open": low + 2.0,
            "high": 102.0,
            "low": low,
            "close": low + 1.5,
            "volume": 1000.0,
            "ma60": 90.0,
        })
    rows.append({
        "open": 103.0, "high": 106.0, "low": 102.5, "close": 105.0,
        "volume": 2000.0, "ma60": 90.0,
    })
    df = add_features(make_bars(rows))
    df.loc[61, "is_in_breakdown_pattern"] = True
    signal = detect(df)
    assert not signal.iloc[61]
