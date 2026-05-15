"""simulator.simulate: takes entries + df, returns trades DataFrame."""
from __future__ import annotations

import pandas as pd
from kline.exit.simulator import simulate

from tests.conftest import make_bars


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
    trades = simulate(df, entries)
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
    trades = simulate(df, entries)
    assert len(trades) == 1
    assert trades.iloc[0]["exit_reason"] == "open"
