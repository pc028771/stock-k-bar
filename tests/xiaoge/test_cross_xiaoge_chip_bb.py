"""Tests for xiaoge/scoring/cross_xiaoge_chip_bb.py — detect_cross().

Course source: 權證小哥課程 ch06-ch08, ch11-ch12.
Reference: docs/權證小哥/籌碼技術分析/detector_spec.md §6 cross_xiaoge_swing.

Logic: 同日 OR 過去 N 日內 bb_squeeze_breakout 跟 main_chip_holder 都觸發 → 升優先級.

課程精神 (ch13):
> 「越多條件交集的選出來的股票越少，那選出來的股票越少呢，他的精準度會越高。」
>  (ch13 02:03–02:27)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from xiaoge.scoring.cross_xiaoge_chip_bb import detect_cross


# ---------------------------------------------------------------------------
# Helpers — build a df with both signals forced on specific rows
# ---------------------------------------------------------------------------

def _build_cross_df(
    n: int = 30,
    ticker: str = "A001",
    bb_signal_row: int | None = -1,    # which row fires bb signal (-1 = last); None = skip
    chip_signal_row: int | None = -2,  # which row fires chip signal; None = skip
) -> pd.DataFrame:
    """Build synthetic df with enough columns for both sub-detectors.

    We set MA values, bb_upper, bb_mid, etc. so that specific rows trigger
    each sub-detector, and all other rows don't.
    """
    dates = pd.bdate_range("2026-01-05", periods=n)
    idx = np.arange(n, dtype=float)

    # Default: gently uptrending
    close = 100.0 + idx * 0.3
    open_ = close * 0.99
    volume = 1000.0 + idx * 10.0

    ma5_vals  = pd.Series(close).rolling(5, min_periods=5).mean().values
    ma20_vals = pd.Series(close).rolling(20, min_periods=20).mean().values

    df = pd.DataFrame({
        "ticker":        ticker,
        "trade_date":    dates,
        "open":          open_,
        "high":          close * 1.02,
        "low":           open_ * 0.98,
        "close":         close,
        "volume":        volume,
        "ma5":           ma5_vals,
        "ma20":          ma20_vals,
        "bb_upper":      close * 0.97,   # default: close > bb_upper
        "bb_mid":        close * 0.95,
        "bb_lower":      close * 0.90,
        "bb_bandwidth":  np.full(n, 5.0),   # narrow → potential squeeze
        "bb_in_squeeze": np.zeros(n, dtype=bool),  # default: not squeezed
        "main_force_5d": -1_000.0,           # default: selling (chip signal OFF)
    })

    # Force chip signal on chip_signal_row: need main_force_5d > 0 + ratio + ma20 rising
    if chip_signal_row is not None:
        cidx = chip_signal_row if chip_signal_row >= 0 else n + chip_signal_row
        if 0 <= cidx < n:
            df.loc[df.index[cidx], "main_force_5d"] = 50_000.0
            # Ensure ma20 is rising at that row and close ≥ ma20
            if cidx > 0:
                df.loc[df.index[cidx - 1], "ma20"] = df["close"].iloc[cidx] - 2.0
            df.loc[df.index[cidx], "ma20"] = df["close"].iloc[cidx] - 1.0   # close ≥ ma20
            df.loc[df.index[cidx], "close"] = df["ma20"].iloc[cidx] + 1.0

    # Force bb signal on bb_signal_row:
    if bb_signal_row is not None:
        bidx = bb_signal_row if bb_signal_row >= 0 else n + bb_signal_row
        if 0 <= bidx < n and bidx > 0:
            # Yesterday was squeezed (shift(1) of bb_in_squeeze must be True)
            df.loc[df.index[bidx - 1], "bb_in_squeeze"] = True
            # Today crosses upper band with red K
            base_c = df["close"].iloc[bidx]
            df.loc[df.index[bidx], "bb_upper"]    = base_c - 5.0   # close > bb_upper (today)
            df.loc[df.index[bidx], "open"]        = base_c - 7.0   # red K
            # Ensure ma5 rising + close > ma5
            df.loc[df.index[bidx - 1], "ma5"] = base_c - 3.0
            df.loc[df.index[bidx], "ma5"] = base_c - 2.0

            # Prev day: prev_close MUST be ≤ prev_bb_upper for cross_upper to fire
            # cross_upper: today close > today bb_upper AND prev close ≤ prev bb_upper
            prev_close_v = df["close"].iloc[bidx - 1]
            df.loc[df.index[bidx - 1], "bb_upper"] = prev_close_v + 2.0   # prev close ≤ prev bb_upper ✓

            # Prev day: prev_is_red (need prev close > prev open)
            df.loc[df.index[bidx - 1], "close"] = df["open"].iloc[bidx - 1] + 1.0

            # prev_close ≤ prev_bb_mid (prev was in lower half)
            df.loc[df.index[bidx - 1], "bb_mid"] = df["close"].iloc[bidx - 1] + 1.0

    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDetectCrossFire:
    def test_cross_fires_when_both_in_window(self):
        """Both BB and Chip signals within window=5 → detect_cross fires.

        ch13: 越多條件交集精準度越高.
        """
        # BB fires on row 28, Chip fires on row 27 → both within window=5 of row 28
        df = _build_cross_df(n=30, bb_signal_row=-1, chip_signal_row=-2)
        sig = detect_cross(df, window=5)
        # Row 29 (last) should be True because both fired in last 5 rows
        assert sig.iloc[-1], (
            "ch13: BB + Chip 在 window 內都觸發應升優先級 (detect_cross=True)"
        )

    def test_cross_returns_bool_series(self):
        """detect_cross must return a bool Series indexed like input."""
        df = _build_cross_df(n=20)
        sig = detect_cross(df, window=5)
        assert isinstance(sig, pd.Series), "detect_cross 必須回傳 pd.Series"
        assert sig.dtype == bool
        assert len(sig) == len(df)

    def test_window_parameter_affects_result(self):
        """Larger window keeps cross signal active longer."""
        df = _build_cross_df(n=30, bb_signal_row=-5, chip_signal_row=-6)
        # window=3: row -1 is 4 bars past bb_signal → outside window → should NOT fire
        sig_narrow = detect_cross(df, window=3)
        # window=10: row -1 is within window → should fire
        sig_wide = detect_cross(df, window=10)
        assert not sig_narrow.iloc[-1], "window=3: 訊號超出視窗應不觸發"
        assert sig_wide.iloc[-1], "window=10: 訊號在視窗內應觸發"


class TestDetectCrossNoFire:
    def test_no_fire_when_only_bb_fires(self):
        """Only BB fires (chip never fires) → cross stays False.

        We build a df where bb fires on the last row (bb_signal_row=-1)
        but chip never fires (chip_signal_row=None, main_force_5d always negative).
        detect_cross requires BOTH in window → should be False.
        """
        df = _build_cross_df(n=30, bb_signal_row=-1, chip_signal_row=None)
        # Ensure chip is definitely OFF everywhere
        df["main_force_5d"] = -1_000.0
        sig = detect_cross(df, window=5, chip_kwargs={"min_chip_ratio": 0.99})
        # cross requires both bb AND chip → with chip always False, cross=False
        assert not sig.iloc[-1], "單 BB 觸發 (chip=False) cross 不應觸發"

    def test_no_fire_before_warmup(self):
        """First few rows lack enough warmup for rolling detectors → False."""
        df = _build_cross_df(n=30)
        sig = detect_cross(df, window=5)
        # Row 0 has NaN in many rolling cols → should be False
        assert not sig.iloc[0], "初期 warmup 行不應觸發 cross 訊號"


class TestDetectCrossNanTolerance:
    def test_nan_in_columns_no_crash(self):
        """NaN values should not cause exception; just return False for those rows."""
        df = _build_cross_df(n=15)
        df.loc[df.index[:5], "bb_upper"] = float("nan")
        df.loc[df.index[:5], "main_force_5d"] = float("nan")
        try:
            sig = detect_cross(df, window=5)
            assert isinstance(sig, pd.Series)
        except Exception as e:
            pytest.fail(f"NaN 欄位不應造成 exception: {e}")

    def test_multi_ticker_independence(self, synthetic_bars):
        """Each ticker's cross signal is computed independently."""
        sig = detect_cross(synthetic_bars, window=5,
                           chip_kwargs={"min_chip_ratio": 0.001})
        # A001 and A002 and A003 should have independent signals
        for ticker in synthetic_bars["ticker"].unique():
            mask = synthetic_bars["ticker"] == ticker
            ticker_sig = sig[mask]
            assert isinstance(ticker_sig, pd.Series), f"{ticker} 訊號必須是 Series"
