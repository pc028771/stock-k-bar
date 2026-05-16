"""dark_double_star.mark: 暗夜雙星 — 長黑摜破兩根形狀相似的併排紅K線 (高檔位置).

Audit C6 fix: now requires both K-1 and K-2 to be red K AND the pair to be
at top zone (high reached prior_high_60 at K-1) OR overhead_supply_layer
clean (no supply above at K-1).
"""
from __future__ import annotations

from kline.exit.reversal_k.dark_double_star import mark

from tests.conftest import make_bars


def _make_pair_then_black(
    k2_high, k2_low, k2_open, k2_close,
    k1_high, k1_low, k1_open, k1_close,
    k0_open, k0_high, k0_low, k0_close,
    prior_high_60=None,
    overhead_at_k1=0.0,
):
    """Helper: K-2 and K-1 with controllable color; K-0 is today's bar."""
    rows = [
        {"open": k2_open, "high": k2_high, "low": k2_low, "close": k2_close},
        {"open": k1_open, "high": k1_high, "low": k1_low, "close": k1_close},
        {"open": k0_open, "high": k0_high, "low": k0_low, "close": k0_close},
    ]
    df = make_bars(rows)
    # prior_high_60 at each bar: use a low constant so that the pair counts as "at top"
    if prior_high_60 is None:
        prior_high_60 = min(k1_high, k2_high) - 1
    df["prior_high_60"] = [prior_high_60] * 3
    # overhead_supply_layer at K-1 controlled via overhead_at_k1
    df["overhead_supply_layer"] = [overhead_at_k1, overhead_at_k1, overhead_at_k1]
    return df


def test_red_pair_at_top_with_long_black_triggers():
    """Two similar red Ks at top, then long black closing below pair lows."""
    df = _make_pair_then_black(
        # K-2: red, high=105, low=99, body up
        k2_high=105, k2_low=99, k2_open=100, k2_close=104,
        # K-1: red, high=105.5, low=99.3 (similar)
        k1_high=105.5, k1_low=99.3, k1_open=100, k1_close=105,
        # K-0: long black
        k0_open=100, k0_high=100.5, k0_low=91, k0_close=91,
        prior_high_60=100,
    )
    out = mark(df)
    assert out.iloc[2]


def test_non_red_pair_does_not_trigger():
    """Pair is black (not red) — should NOT trigger per course."""
    df = _make_pair_then_black(
        k2_high=105, k2_low=99, k2_open=104, k2_close=100,   # black
        k1_high=105.5, k1_low=99.3, k1_open=105, k1_close=100,  # black
        k0_open=100, k0_high=100.5, k0_low=91, k0_close=91,
        prior_high_60=100,
    )
    out = mark(df)
    assert not out.iloc[2]


def test_red_pair_not_at_top_does_not_trigger():
    """Red pair but neither high reaches prior_high_60 AND overhead is layered."""
    df = _make_pair_then_black(
        k2_high=105, k2_low=99, k2_open=100, k2_close=104,
        k1_high=105.5, k1_low=99.3, k1_open=100, k1_close=105,
        k0_open=100, k0_high=100.5, k0_low=91, k0_close=91,
        prior_high_60=200,         # well above pair highs → not at top
        overhead_at_k1=5.0,        # supply above → not clean
    )
    out = mark(df)
    assert not out.iloc[2]


def test_dissimilar_pair_does_not_trigger():
    df = _make_pair_then_black(
        k2_high=105, k2_low=99, k2_open=100, k2_close=104,
        k1_high=115, k1_low=99, k1_open=100, k1_close=114,
        k0_open=100, k0_high=100.5, k0_low=91, k0_close=91,
        prior_high_60=100,
    )
    out = mark(df)
    assert not out.iloc[2]


def test_red_k_today_does_not_trigger():
    df = _make_pair_then_black(
        k2_high=105, k2_low=99, k2_open=100, k2_close=104,
        k1_high=105.5, k1_low=99.3, k1_open=100, k1_close=105,
        k0_open=91, k0_high=105, k0_low=90, k0_close=104,   # red
        prior_high_60=100,
    )
    out = mark(df)
    assert not out.iloc[2]


def test_body_below_threshold_does_not_trigger():
    df = _make_pair_then_black(
        k2_high=105, k2_low=99, k2_open=100, k2_close=104,
        k1_high=105.5, k1_low=99.3, k1_open=100, k1_close=105,
        k0_open=100, k0_high=100.5, k0_low=97, k0_close=97.5,  # body 2.5%
        prior_high_60=100,
    )
    out = mark(df)
    assert not out.iloc[2]


def test_close_does_not_break_below_pair_does_not_trigger():
    df = _make_pair_then_black(
        k2_high=105, k2_low=99, k2_open=100, k2_close=104,
        k1_high=105.5, k1_low=99.3, k1_open=100, k1_close=105,
        k0_open=104, k0_high=104.5, k0_low=99.4, k0_close=99.5,
        prior_high_60=100,
    )
    out = mark(df)
    assert not out.iloc[2]
