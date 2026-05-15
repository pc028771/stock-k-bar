"""enemy_at_gate.mark: 大敵當前."""
from __future__ import annotations

from kline.exit.reversal_k.enemy_at_gate import mark

from tests.conftest import make_bars


def test_three_small_reds_then_long_black_below_k3_mid_triggers():
    """K-3..K-1 are small red Ks; K0 long black breaks K-3 midpoint."""
    rows = [
        # K-3: small red, open=100, close=101 (1% body), mid = 100.5
        {"open": 100, "high": 102, "low": 99,  "close": 101},
        # K-2: small red
        {"open": 101, "high": 103, "low": 100, "close": 102},
        # K-1: small red
        {"open": 102, "high": 104, "low": 101, "close": 103},
        # K0: long black (open=103, close=96 → body≈6.8%), close < K-3 mid=100.5
        {"open": 103, "high": 103.5, "low": 95, "close": 96},
    ]
    df = make_bars(rows)
    out = mark(df)
    assert out.iloc[3], "Should trigger: three small reds + long black below K-3 midpoint"


def test_large_red_bars_does_not_trigger():
    """K-3..K-1 have large bodies (>2%), not small reds."""
    rows = [
        {"open": 100, "high": 108, "low": 99,  "close": 107},  # 7% body
        {"open": 107, "high": 115, "low": 106, "close": 114},  # 6.5% body
        {"open": 114, "high": 122, "low": 113, "close": 121},  # 6% body
        {"open": 121, "high": 121.5, "low": 104, "close": 105},
    ]
    df = make_bars(rows)
    out = mark(df)
    assert not out.iloc[3], "Should not trigger: prior bars are large reds"


def test_close_above_k3_mid_does_not_trigger():
    """Three small reds but K0 close stays above K-3 midpoint."""
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 101},  # K-3, mid=100.5
        {"open": 101, "high": 103, "low": 100, "close": 102},
        {"open": 102, "high": 104, "low": 101, "close": 103},
        # K0: black, close=100.6 > K-3 mid=100.5
        {"open": 104, "high": 104.5, "low": 100, "close": 100.6},
    ]
    df = make_bars(rows)
    out = mark(df)
    assert not out.iloc[3], "Should not trigger: close doesn't break K-3 midpoint"
