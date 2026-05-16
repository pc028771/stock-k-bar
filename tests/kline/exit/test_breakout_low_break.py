"""breakout_low_break.mark: 突破K的低點被跌破 → 攻擊假設失效.

Course source: 【單一K線】紅色誤解：連續紅K的判斷要點.

Audit I8: this exit is armed only AFTER the breakout_price_break window
(2 bars by default). Within the first 2 bars after entry only the
sensitive breakout_price_break is active.
"""
from __future__ import annotations

import pandas as pd
from kline.exit.breakout_low_break import mark

from tests.conftest import make_bars


def _entry_then_break(close_break_bar_idx: int, n: int):
    """Entry at bar 1; subsequent bars all close below entry-bar low."""
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},  # idx 0
        {"open": 105, "high": 110, "low": 104, "close": 109},  # idx 1 ENTRY (low=104)
    ]
    for _ in range(n - 2):
        # close 103 < entry_low 104 — triggers IF outside window.
        rows.append({"open": 108, "high": 109, "low": 102, "close": 103})
    df = make_bars(rows)
    entries = pd.Series([False, True] + [False] * (n - 2))
    return df, entries


def test_low_break_not_armed_within_price_break_window():
    """Bars 2-3 (bars_since_entry 1-2) are inside breakout_price_break window."""
    df, entries = _entry_then_break(2, n=4)
    out = mark(df, entries)
    assert not out.iloc[2]  # bars_since_entry == 1 → still in price-break window
    assert not out.iloc[3]  # bars_since_entry == 2 → boundary, still in window


def test_low_break_armed_after_price_break_window():
    """Bar 4+ (bars_since_entry > 2) — breakout_low_break is active."""
    df, entries = _entry_then_break(2, n=5)
    out = mark(df, entries)
    assert out.iloc[4]  # bars_since_entry == 3 → outside window, fires


def test_close_at_or_above_entry_low_does_not_trigger():
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},
        {"open": 105, "high": 110, "low": 104, "close": 109},
        {"open": 108, "high": 109, "low": 104, "close": 105},
        {"open": 108, "high": 109, "low": 104, "close": 105},
        {"open": 108, "high": 109, "low": 104, "close": 105},
    ]
    df = make_bars(rows)
    entries = pd.Series([False, True, False, False, False])
    out = mark(df, entries)
    assert not out.any()


def test_per_ticker_isolation():
    rows_a = [{"open": 100, "high": 110, "low": 90, "close": 100} for _ in range(5)]
    rows_b = [{"open": 100, "high": 110, "low": 50, "close": 60} for _ in range(5)]
    df = pd.concat([
        make_bars(rows_a, ticker="A"),
        make_bars(rows_b, ticker="B"),
    ]).reset_index(drop=True)
    entries = pd.Series([True, False, False, False, False,
                         True, False, False, False, False])
    out = mark(df, entries)
    # Ticker A: close 100 not below entry low 90 → never triggers.
    assert not out.iloc[:5].any()
    # Ticker B: close 60 not below entry low 50 → never triggers either.
    assert not out.iloc[5:].any()
