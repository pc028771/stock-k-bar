"""trailing_stop.mark: 前一日低點 trailing stop.

Course source: 【買點賣點】出場點的各種依據(二) +【賣壓化解】K線圖的第一個研判要點.

> 「前一日低點當作停利點，有過昨高都算攻擊持續」
"""
from __future__ import annotations

import pandas as pd
from kline.exit.trailing_stop import mark

from tests.conftest import make_bars


def test_close_below_trailing_low_triggers():
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},
        {"open": 105, "high": 110, "low": 104, "close": 109},
        {"open": 109, "high": 112, "low": 108, "close": 111},
        {"open": 111, "high": 111, "low": 103, "close": 103},
    ]
    df = make_bars(rows)
    df["prev_low"] = df["low"].shift(1)
    entries = pd.Series([False, True, False, False])
    out = mark(df, entries)
    assert out.iloc[3]


def test_close_above_trailing_low_does_not_trigger():
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},
        {"open": 105, "high": 110, "low": 104, "close": 109},
        {"open": 109, "high": 112, "low": 108, "close": 111},
        {"open": 111, "high": 113, "low": 109, "close": 112},
    ]
    df = make_bars(rows)
    df["prev_low"] = df["low"].shift(1)
    entries = pd.Series([False, True, False, False])
    out = mark(df, entries)
    assert not out.iloc[3]


# ============================================================================
# §C14 — 微弱多方趨勢退化版 mark_weak_bull
# ============================================================================

def test_c14_weak_bull_triggers_when_close_below_ma5_and_low_momentum():
    """§C14: close < MA5 AND low momentum → mark_weak_bull triggers."""
    from kline.exit.trailing_stop import mark_weak_bull
    from kline.features import add_features

    # 10 bars: flat price around 100, no attack (attack_intensity=0)
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(9)]
    # Final bar: close drops to 95 (below MA5 ≈ 100)
    rows.append({"open": 100, "high": 101, "low": 94, "close": 95})
    df = make_bars(rows)
    df = add_features(df)
    # Force attack_intensity=0 (should already be 0 for flat bars)
    df["attack_intensity"] = 0
    entries = pd.Series([False] * 8 + [True, False])
    out = mark_weak_bull(df, entries)
    # Row 9: close=95 < MA5≈100, attack=0, in_trade=True → should trigger
    assert out.iloc[9], "§C14: close below MA5 in low-momentum state should trigger"


def test_c14_weak_bull_does_not_trigger_with_high_momentum():
    """§C14: close < MA5 but attack_intensity > 0 → should NOT trigger (momentum present)."""
    from kline.exit.trailing_stop import mark_weak_bull
    from kline.features import add_features

    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(9)]
    rows.append({"open": 100, "high": 101, "low": 94, "close": 95})
    df = make_bars(rows)
    df = add_features(df)
    # Force attack_intensity > 0 on recent bar
    df.loc[8, "attack_intensity"] = 2
    entries = pd.Series([False] * 8 + [True, False])
    out = mark_weak_bull(df, entries)
    # Should NOT trigger because momentum exists
    assert not out.iloc[9], "§C14: high momentum → weak_bull should NOT trigger"


def test_c14_weak_bull_no_trigger_before_entry():
    """§C14: mark_weak_bull should not fire on bars before entry signal."""
    from kline.exit.trailing_stop import mark_weak_bull
    from kline.features import add_features

    rows = [{"open": 100, "high": 101, "low": 99, "close": 95} for _ in range(10)]
    df = make_bars(rows)
    df = add_features(df)
    df["attack_intensity"] = 0
    # Entry only on last bar → earlier bars should be False
    entries = pd.Series([False] * 9 + [True])
    out = mark_weak_bull(df, entries)
    assert not out.iloc[0], "Before entry: should not trigger"
