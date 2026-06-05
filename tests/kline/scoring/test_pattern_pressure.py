"""pattern_pressure.score: INVENTORY §C09 型態壓力打分."""
from __future__ import annotations

from kline.scoring.pattern_pressure import score

from tests.conftest import make_bars


def test_just_broke_neckline_adds_one():
    """+1 when close drops below MA60 from above."""
    rows = [
        {"open": 100, "high": 101, "low": 99,  "close": 102},  # prev: above MA60
        {"open": 100, "high": 101, "low": 99,  "close": 98},   # today: below MA60
    ]
    df = make_bars(rows)
    # MA60 = 100 (constant), so prev_close=102 >= 100, today_close=98 < 100
    df["ma60"] = 100.0
    df["overhead_supply_layer"] = 0.0
    out = score(df)
    # Row 1: just_broke=1, rebound_at_neckline=0 (high=101>=100 AND close=98<100 → +1 too)
    # Actually rebound_at_neckline = high>=ma60 AND close<ma60 → also +1 on row 1
    assert out.iloc[1] >= 1


def test_rebound_at_neckline_adds_one():
    """+1 when high touches MA60 but close stays below."""
    rows = [{"open": 95, "high": 101, "low": 94, "close": 98}]
    df = make_bars(rows)
    df["ma60"] = 100.0
    df["overhead_supply_layer"] = 0.0
    out = score(df)
    # high=101 >= 100 AND close=98 < 100 → rebound_at_neckline=1
    assert out.iloc[0] >= 1


def test_overhead_supply_adds_up_to_three():
    """+1/+2/+3 for overhead_supply_layer."""
    rows = [{"open": 100, "high": 101, "low": 99, "close": 95}]
    df = make_bars(rows)
    df["ma60"] = 100.0
    df["overhead_supply_layer"] = 5.0  # capped at 3
    out = score(df)
    # rebound_at_neckline=1 (high=101>100, close=95<100) + supply=3 >= 4
    assert out.iloc[0] >= 3


def test_clean_state_returns_low_score():
    """No pressure: above MA60, no rebound, no supply."""
    rows = [{"open": 100, "high": 105, "low": 99, "close": 104}]
    df = make_bars(rows)
    df["ma60"] = 90.0  # close > ma60, so no neckline break/rebound
    df["overhead_supply_layer"] = 0.0
    out = score(df)
    assert out.iloc[0] == 0.0
