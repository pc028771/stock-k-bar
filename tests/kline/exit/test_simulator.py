"""simulator.simulate: takes entries + df, returns trades DataFrame."""
from __future__ import annotations

import pandas as pd
from kline.exit import breakout_low_break, gap_fill
from kline.exit.simulator import simulate

from tests.conftest import make_bars

# Minimal exit registry / priority for simulator-logic tests.
# Only include the two conditions exercised in the tests so that future real
# pattern implementations don't inadvertently fire on the synthetic bar data.
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
    rows = [
        {"open": 100, "high": 105, "low": 99,  "close": 104},   # bar 0
        {"open": 105, "high": 110, "low": 104, "close": 109},   # bar 1: ENTRY signal
        {"open": 109, "high": 110, "low": 102, "close": 103},   # bar 2: close < entry_low 104
        {"open": 103, "high": 104, "low": 100, "close": 101},   # bar 3: exit price = 103
    ]
    df = _prepare_df(rows)
    entries = pd.Series([False, True, False, False])
    trades = simulate(df, entries, exit_priority=_TEST_PRIORITY, exit_registry=_TEST_REGISTRY)
    assert len(trades) == 1
    t = trades.iloc[0]
    # Entry at bar 1 signal → execute bar 2 open (109)
    assert t["entry_open"] == 109
    # Exit triggered bar 2 → execute bar 3 open (103)
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
    # Bar 2: gaps up >2% over market (open 112 vs prev_close 109 = +2.75%,
    # market_open_ret=0 → excess_gap=2.75% >= 2%) AND close 103 < prev_close 109
    # → gap_fill fires.
    # Bar 2: close 103 < entry_low 104 → breakout_low_break fires.
    # Both fire on bar 2; gap_fill comes before breakout_low_break in EXIT_PRIORITY
    # → gap_fill wins.
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},
        {"open": 105, "high": 110, "low": 104, "close": 109},  # ENTRY, low=104
        {"open": 112, "high": 113, "low": 100, "close": 103},  # gap_fill + breakout_low_break fire
        {"open": 103, "high": 104, "low": 100, "close": 101},  # exit price bar
    ]
    df = _prepare_df(rows)
    entries = pd.Series([False, True, False, False])
    trades = simulate(df, entries, exit_priority=_TEST_PRIORITY, exit_registry=_TEST_REGISTRY)
    assert len(trades) == 1
    # gap_fill priority is HIGHER (comes before breakout_low_break in EXIT_PRIORITY)
    assert trades.iloc[0]["exit_reason"] == "gap_fill"


def test_per_ticker_isolation_in_simulator():
    """Two tickers with overlapping dates — A's exits don't see B's bars."""
    df_a = make_bars([
        {"open": 100, "high": 105, "low": 99,  "close": 104},
        {"open": 105, "high": 110, "low": 104, "close": 109},  # ENTRY A
        {"open": 109, "high": 110, "low": 102, "close": 103},  # close < 104 → exit A
        {"open": 103, "high": 104, "low": 100, "close": 101},  # exit A price
    ], ticker="A")
    df_b = make_bars([
        {"open": 50,  "high": 52,  "low": 48,  "close": 51},
        {"open": 51,  "high": 53,  "low": 50,  "close": 52},  # ENTRY B
        {"open": 52,  "high": 54,  "low": 51,  "close": 53},  # no exit
        {"open": 53,  "high": 55,  "low": 52,  "close": 54},  # no exit, last bar
    ], ticker="B")
    combined = pd.concat([df_a, df_b]).reset_index(drop=True)
    combined["prev_low"] = combined.groupby("ticker")["low"].shift(1)
    combined["prev_close"] = combined.groupby("ticker")["close"].shift(1)
    combined["prior_low_20"] = float("nan")
    combined["ma60_slope_5d"] = 0.01
    combined["market_open_ret"] = 0.0
    entries = pd.Series([False, True, False, False, False, True, False, False])
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
