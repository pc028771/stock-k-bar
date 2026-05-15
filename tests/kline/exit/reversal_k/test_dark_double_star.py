"""dark_double_star.mark: 暗夜雙星 — 長黑摜破兩根形狀相似的併排K線."""
from __future__ import annotations

from kline.exit.reversal_k.dark_double_star import mark

from tests.conftest import make_bars


def _make_similar_pair_then_black(
    k2_high, k2_low, k1_high, k1_low, k0_open, k0_high, k0_low, k0_close
):
    """Helper: K-2 and K-1 are a similar pair; K-0 is today's bar."""
    k2_mid = (k2_high + k2_low) / 2
    k1_mid = (k1_high + k1_low) / 2
    rows = [
        # K-2
        {"open": k2_mid, "high": k2_high, "low": k2_low, "close": k2_mid},
        # K-1
        {"open": k1_mid, "high": k1_high, "low": k1_low, "close": k1_mid},
        # K-0 (today)
        {"open": k0_open, "high": k0_high, "low": k0_low, "close": k0_close},
    ]
    return make_bars(rows)


def test_long_black_breaks_similar_pair_triggers():
    """Similar K-2/K-1 pair, today long black that closes below both lows."""
    # K-2 high=105, low=99; K-1 high=105.5, low=99.3 → similar within 3%
    df = _make_similar_pair_then_black(
        k2_high=105, k2_low=99,
        k1_high=105.5, k1_low=99.3,
        k0_open=100, k0_high=100.5, k0_low=91, k0_close=91,
    )
    out = mark(df)
    assert out.iloc[2], "Should trigger: similar pair + long black below pair lows"


def test_dissimilar_pair_does_not_trigger():
    """K-2 and K-1 have very different highs — not a similar pair."""
    # K-2 high=105, K-1 high=115 → > 3% apart
    df = _make_similar_pair_then_black(
        k2_high=105, k2_low=99,
        k1_high=115, k1_low=99,
        k0_open=100, k0_high=100.5, k0_low=91, k0_close=91,
    )
    out = mark(df)
    assert not out.iloc[2], "Should not trigger: pair highs are too far apart"


def test_red_k_does_not_trigger():
    """Today is a red K, not black."""
    df = _make_similar_pair_then_black(
        k2_high=105, k2_low=99,
        k1_high=105.5, k1_low=99.3,
        k0_open=91, k0_high=105, k0_low=90, k0_close=104,
    )
    out = mark(df)
    assert not out.iloc[2], "Should not trigger: today is red"


def test_body_below_threshold_does_not_trigger():
    """Today is black but body < 4%."""
    # open=100, close=97.5 → body=2.5%
    df = _make_similar_pair_then_black(
        k2_high=105, k2_low=99,
        k1_high=105.5, k1_low=99.3,
        k0_open=100, k0_high=100.5, k0_low=97, k0_close=97.5,
    )
    out = mark(df)
    assert not out.iloc[2], "Should not trigger: body too small"


def test_close_does_not_break_below_pair_does_not_trigger():
    """Today long black but close stays above pair lows."""
    # pair lows ~99; today close=99.5 → not breaking below
    df = _make_similar_pair_then_black(
        k2_high=105, k2_low=99,
        k1_high=105.5, k1_low=99.3,
        k0_open=104, k0_high=104.5, k0_low=99.4, k0_close=99.5,
    )
    out = mark(df)
    assert not out.iloc[2], "Should not trigger: close above pair lows"
