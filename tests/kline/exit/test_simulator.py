"""simulator.simulate: takes entries + df, returns trades DataFrame."""
from __future__ import annotations

import pandas as pd
from kline.exit import breakout_low_break
from kline.exit.simulator import simulate
from kline.extras import gap_fill_excess_market_adjusted as gap_fill

from tests.conftest import make_bars

# Minimal exit registry / priority for simulator-logic tests.
# Only include the two conditions exercised in the tests so that future real
# pattern implementations don't inadvertently fire on the synthetic bar data.
# Note: `gap_fill` (the non-course excess-market-adjusted variant) was moved
# to extras (audit C2). We import it here purely as a synthetic exit for the
# simulator-logic tests; production no longer uses it by default.
_TEST_REGISTRY = {
    "gap_fill":           gap_fill.mark,
    "breakout_low_break": breakout_low_break.mark,
}
_TEST_PRIORITY = ["gap_fill", "breakout_low_break"]


def _prepare_df(rows):
    df = make_bars(rows)
    df["prev_low"] = df["low"].shift(1)
    df["prev_close"] = df["close"].shift(1)
    df["prior_low_20"] = float("nan")
    df["ma60_slope_5d"] = 0.01
    df["market_open_ret"] = 0.0
    return df


def test_single_trade_exits_on_breakout_low_break():
    """Audit I8: breakout_low_break arms only after the 2-bar price-break window."""
    rows = [
        {"open": 100, "high": 105, "low": 99,  "close": 104},   # bar 0
        {"open": 105, "high": 110, "low": 104, "close": 109},   # bar 1: ENTRY signal
        {"open": 109, "high": 110, "low": 105, "close": 108},   # bar 2: bars_since=1
        {"open": 108, "high": 109, "low": 105, "close": 106},   # bar 3: bars_since=2
        {"open": 106, "high": 107, "low": 102, "close": 103},   # bar 4: bars_since=3 → fires
        {"open": 103, "high": 104, "low": 100, "close": 101},   # bar 5: exit execute
    ]
    df = _prepare_df(rows)
    entries = pd.Series([False, True, False, False, False, False])
    trades = simulate(df, entries, exit_priority=_TEST_PRIORITY, exit_registry=_TEST_REGISTRY)
    assert len(trades) == 1
    t = trades.iloc[0]
    # Entry at bar 1 signal → execute bar 2 open (109)
    assert t["entry_open"] == 109
    # Exit triggered bar 4 → execute bar 5 open (103)
    assert t["exit_open"] == 103
    assert t["exit_reason"] == "breakout_low_break"


def test_no_exit_uses_last_bar_open():
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},
        {"open": 101, "high": 103, "low": 100, "close": 102},   # ENTRY
        {"open": 102, "high": 104, "low": 101, "close": 103},   # no exit
    ]
    df = _prepare_df(rows)
    entries = pd.Series([False, True, False])
    trades = simulate(df, entries, exit_priority=_TEST_PRIORITY, exit_registry=_TEST_REGISTRY)
    assert len(trades) == 1
    assert trades.iloc[0]["exit_reason"] == "open"


def test_priority_tie_breaking_uses_higher_priority_reason():
    """Same-day trigger for multiple conditions → EXIT_PRIORITY decides."""
    # Audit I8: breakout_low_break only fires bars_since > 2, so we move the
    # combined trigger out to bar 4. Bar 4 gaps up >2% over market AND closes
    # below entry-bar low → both gap_fill and breakout_low_break fire; priority
    # ordering selects gap_fill.
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},
        {"open": 105, "high": 110, "low": 104, "close": 109},  # ENTRY, low=104
        {"open": 109, "high": 110, "low": 106, "close": 108},  # bar 2, bars_since=1
        {"open": 108, "high": 110, "low": 105, "close": 107},  # bar 3, bars_since=2
        {"open": 112, "high": 113, "low": 100, "close": 103},  # bar 4: gap_fill + low_break fire
        {"open": 103, "high": 104, "low": 100, "close": 101},  # exit price bar
    ]
    df = _prepare_df(rows)
    entries = pd.Series([False, True, False, False, False, False])
    trades = simulate(df, entries, exit_priority=_TEST_PRIORITY, exit_registry=_TEST_REGISTRY)
    assert len(trades) == 1
    # gap_fill priority is HIGHER (comes before breakout_low_break in EXIT_PRIORITY)
    assert trades.iloc[0]["exit_reason"] == "gap_fill"


def test_per_ticker_isolation_in_simulator():
    """Two tickers with overlapping dates — A's exits don't see B's bars."""
    df_a = make_bars([
        {"open": 100, "high": 105, "low": 99,  "close": 104},
        {"open": 105, "high": 110, "low": 104, "close": 109},  # ENTRY A
        {"open": 109, "high": 110, "low": 106, "close": 108},  # bars_since=1
        {"open": 108, "high": 110, "low": 105, "close": 107},  # bars_since=2
        {"open": 107, "high": 108, "low": 102, "close": 103},  # bars_since=3 → low_break
        {"open": 103, "high": 104, "low": 100, "close": 101},  # exit A price
    ], ticker="A")
    df_b = make_bars([
        {"open": 50,  "high": 52,  "low": 48,  "close": 51},
        {"open": 51,  "high": 53,  "low": 50,  "close": 52},  # ENTRY B
        {"open": 52,  "high": 54,  "low": 51,  "close": 53},  # no exit
        {"open": 53,  "high": 55,  "low": 52,  "close": 54},  # no exit
        {"open": 54,  "high": 56,  "low": 53,  "close": 55},  # no exit
        {"open": 55,  "high": 57,  "low": 54,  "close": 56},  # no exit, last bar
    ], ticker="B")
    combined = pd.concat([df_a, df_b]).reset_index(drop=True)
    combined["prev_low"] = combined.groupby("ticker")["low"].shift(1)
    combined["prev_close"] = combined.groupby("ticker")["close"].shift(1)
    combined["prior_low_20"] = float("nan")
    combined["ma60_slope_5d"] = 0.01
    combined["market_open_ret"] = 0.0
    entries = pd.Series([False, True, False, False, False, False,
                          False, True, False, False, False, False])
    trades = simulate(combined, entries, exit_priority=_TEST_PRIORITY, exit_registry=_TEST_REGISTRY)
    assert len(trades) == 2
    a_trade = trades[trades["ticker"] == "A"].iloc[0]
    b_trade = trades[trades["ticker"] == "B"].iloc[0]
    assert a_trade["exit_reason"] == "breakout_low_break"
    assert b_trade["exit_reason"] == "open"  # no exit triggered


def test_entry_on_last_bar_is_skipped():
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},
        {"open": 101, "high": 103, "low": 100, "close": 102},  # ENTRY on last bar → skip
    ]
    df = _prepare_df(rows)
    entries = pd.Series([False, True])
    trades = simulate(df, entries, exit_priority=_TEST_PRIORITY, exit_registry=_TEST_REGISTRY)
    assert len(trades) == 0


def test_alignment_mismatch_raises():
    rows = [{"open": 100, "high": 102, "low": 99, "close": 100} for _ in range(3)]
    df = _prepare_df(rows)
    entries = pd.Series([False, True])  # wrong length
    try:
        simulate(df, entries, exit_priority=_TEST_PRIORITY, exit_registry=_TEST_REGISTRY)
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "length" in str(e).lower()
