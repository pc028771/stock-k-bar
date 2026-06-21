"""Tests for xiaoge/entry/flying_stock_screener.py (D5 飆股口袋名單 sub-detectors).

Synthetic data only — no DB / parquet dependency.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from xiaoge.entry.flying_stock_screener import (
    m3_main_buy_streak, m4_foreign_buy_streak, m5_invest_trust_buy_streak,
    m7_break_high,
    s3_main_sell_streak, s4_foreign_sell_streak, s5_invest_trust_sell_streak,
    s7_break_low,
    long_score, short_score, screener_long, screener_short,
)


def _df(close_seq, main_seq=None, foreign_seq=None, sitc_seq=None,
        ticker="A001"):
    n = len(close_seq)
    out = pd.DataFrame({
        "ticker": ticker,
        "trade_date": pd.bdate_range("2026-01-05", periods=n),
        "close": close_seq,
        "main_force_1d": main_seq if main_seq is not None else [0.0] * n,
        "foreign_net": foreign_seq if foreign_seq is not None else [0.0] * n,
        "sitc_net": sitc_seq if sitc_seq is not None else [0.0] * n,
    })
    return out


# ── M3 main_buy_streak ─────────────────────────────────────────────────────

def test_m3_fires_on_streak3():
    # 5 days, last 3 all positive → streak fires on day 5 (idx 4) and day 4 (idx 3)
    df = _df(close_seq=[100]*5, main_seq=[-1, -1, 1, 1, 1])
    sig = m3_main_buy_streak(df, n=3)
    assert list(sig) == [False, False, False, False, True]


def test_m3_breaks_on_neg():
    df = _df(close_seq=[100]*5, main_seq=[1, 1, 1, -1, 1])
    sig = m3_main_buy_streak(df, n=3)
    # idx 2: rolling [1,1,1].min=1 > 0 → True
    # idx 3: rolling [1,1,-1].min=-1 → False
    # idx 4: rolling [1,-1,1].min=-1 → False
    assert list(sig) == [False, False, True, False, False]


def test_m3_zero_is_not_positive():
    df = _df(close_seq=[100]*4, main_seq=[1, 1, 0, 1])
    sig = m3_main_buy_streak(df, n=3)
    # 0 is not > 0, so streak breaks on idx 2
    assert list(sig) == [False, False, False, False]


# ── M4 / M5 ────────────────────────────────────────────────────────────────

def test_m4_foreign_streak():
    df = _df(close_seq=[100]*4, foreign_seq=[100, 50, 200, 10])
    assert list(m4_foreign_buy_streak(df, n=3)) == [False, False, True, True]


def test_m5_sitc_streak():
    df = _df(close_seq=[100]*4, sitc_seq=[1, 2, 3, -1])
    assert list(m5_invest_trust_buy_streak(df, n=3)) == [False, False, True, False]


# ── M7 break_20d_high ──────────────────────────────────────────────────────

def test_m7_break_high():
    # 25 days; close monotonic up. Test strict new high vs prior 20-day base.
    closes = [100 + i for i in range(20)] + [105, 110, 119, 120, 130]
    df = _df(close_seq=closes)
    sig = m7_break_high(df, lookback=20)
    # idx 0..19: NaN/False (rolling needs 20 bars + shift(1) needs prior eligible)
    for i in range(20):
        assert sig.iloc[i] == False, f"idx {i} should be False (warmup)"
    # idx 20 close=105, prior 20 (idx 0..19) max=119 → 105 < 119 → False
    assert sig.iloc[20] == False
    # idx 23 close=120, prior 20 (idx 3..22) max=119 → 120 > 119 → True
    assert sig.iloc[23] == True
    # idx 24 close=130, prior 20 max=120 → True
    assert sig.iloc[24] == True


def test_m7_no_high_on_dip():
    closes = [100 + i for i in range(20)] + [110]
    df = _df(close_seq=closes)
    sig = m7_break_high(df, lookback=20)
    # idx 20 close=110, prior 20 (idx 0..19) max=119 → 110 < 119 → False
    assert sig.iloc[20] == False


# ── short mirrors ──────────────────────────────────────────────────────────

def test_s3_main_sell_streak():
    df = _df(close_seq=[100]*5, main_seq=[1, -1, -1, -1, 1])
    sig = s3_main_sell_streak(df, n=3)
    assert list(sig) == [False, False, False, True, False]


def test_s7_break_low():
    # 25 days, monotonic down; warmup 20, then test new low after that
    closes = [200 - i for i in range(20)] + [185, 184, 182, 180, 178]
    df = _df(close_seq=closes)
    sig = s7_break_low(df, lookback=20)
    # warmup
    for i in range(20):
        assert sig.iloc[i] == False
    # idx 20 close=185, prior 20 (idx 0..19) min = 200-19=181 → 185 > 181 → False
    assert sig.iloc[20] == False
    # idx 23 close=180, prior 20 (idx 3..22) min=182 → 180 < 182 → True
    assert sig.iloc[23] == True
    assert sig.iloc[24] == True


# ── combinator ─────────────────────────────────────────────────────────────

def test_long_score_counts_hits():
    # 5-day window. Make m3, m4 fire on last day, m5/m7 don't.
    df = _df(
        close_seq=[100, 100, 100, 100, 100],   # m7 won't fire (not 20 bars)
        main_seq=[1, 1, 1, 1, 1],
        foreign_seq=[10, 10, 10, 10, 10],
        sitc_seq=[-1, -1, -1, -1, -1],
    )
    s = long_score(df, n_streak=3, n_high=20)
    # m3, m4 should fire on idx 2-4; m5 never; m7 never
    assert list(s["m3"]) == [False, False, True, True, True]
    assert list(s["m4"]) == [False, False, True, True, True]
    assert list(s["m5"]) == [False] * 5
    assert list(s["m7"]) == [False] * 5
    assert list(s["score"]) == [0, 0, 2, 2, 2]


def test_screener_long_min_score():
    df = _df(
        close_seq=[100]*5,
        main_seq=[1]*5,
        foreign_seq=[10]*5,
    )
    sig2 = screener_long(df, n_streak=3, min_score=2)
    assert list(sig2) == [False, False, True, True, True]
    sig3 = screener_long(df, n_streak=3, min_score=3)
    assert list(sig3) == [False] * 5


# ── multi-ticker isolation ─────────────────────────────────────────────────

def test_multi_ticker_streak_isolation():
    df = pd.concat([
        _df(close_seq=[100]*5, main_seq=[1, 1, 1, 1, 1], ticker="A001"),
        _df(close_seq=[100]*5, main_seq=[-1, -1, -1, -1, -1], ticker="B002"),
    ], ignore_index=True)
    sig = m3_main_buy_streak(df, n=3)
    a = sig[df["ticker"] == "A001"].tolist()
    b = sig[df["ticker"] == "B002"].tolist()
    assert a == [False, False, True, True, True]
    assert b == [False] * 5
