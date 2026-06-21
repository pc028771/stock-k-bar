"""Tests for xiaoge/bars.py — add_squeeze_flag() and vol_ma5().

Course source: 權證小哥課程 ch06-ch07, ch12 飆股口袋名單多頭策略 #9.

課程原話 (ch06):
> 「布林軌道打開…短期有整理完畢往上攻擊的態勢，那這種呢通常壓縮的越久，
>   之後的漲勢拉就越驚人。」
> 「bandwidth < 5 → 很窄（收斂、整理）」

Tests cover:
  - add_squeeze_flag() fires True when bandwidth narrow for 10 bars
  - add_squeeze_flag() stays False when bandwidth too wide
  - Threshold parameter changes behaviour
  - vol_ma5() returns rolling 5-day average
  - NaN / missing columns handled gracefully
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from xiaoge.bars import add_squeeze_flag, vol_ma5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_single_ticker(bb_widths: list[float], ticker: str = "T0001") -> pd.DataFrame:
    n = len(bb_widths)
    return pd.DataFrame({
        "ticker":       ticker,
        "trade_date":   pd.bdate_range("2026-01-05", periods=n),
        "open":         100.0,
        "close":        100.0,
        "volume":       1000.0 * (1 + np.arange(n) * 0.1),
        "bb_width_pct": bb_widths,
    })


# ---------------------------------------------------------------------------
# add_squeeze_flag tests
# ---------------------------------------------------------------------------

class TestAddSqueezeFlag:
    def test_squeeze_fires_when_narrow_for_10_bars(self):
        """ch09/ch12: 壓縮 10 根 → bb_in_squeeze=True.

        Squeeze condition requires ALL past 10 bars to have bandwidth ≤ threshold.
        """
        widths = [8.0] * 15          # all narrow
        df = _make_single_ticker(widths)
        result = add_squeeze_flag(df, lookback=10, threshold=12.0)
        # First 9 rows lack full lookback → NaN/False; row 9+ should be True
        assert result["bb_in_squeeze"].iloc[14], (
            "ch12 #9: 布林壓縮 10 根以上應亮 bb_in_squeeze"
        )

    def test_squeeze_false_when_bandwidth_wide(self):
        """ch06: bandwidth ~20 = 寬 → 不屬於收斂狀態."""
        widths = [20.0] * 15
        df = _make_single_ticker(widths)
        result = add_squeeze_flag(df, lookback=10, threshold=12.0)
        assert not result["bb_in_squeeze"].any(), (
            "ch06: 帶寬 20% 不應被判定為收斂 (squeeze=False)"
        )

    def test_squeeze_false_when_one_bar_exceeds_threshold(self):
        """One wide bar within lookback window breaks squeeze condition."""
        widths = [8.0] * 9 + [15.0] + [8.0] * 5  # wide bar at index 9
        df = _make_single_ticker(widths)
        result = add_squeeze_flag(df, lookback=10, threshold=12.0)
        # Rows 10-14 include bar 9 (wide) in their window → False
        assert not result["bb_in_squeeze"].iloc[10], (
            "視窗內有一根 > 閾值就不算 squeeze"
        )
        # After window slides past wide bar (row 15+) → True again, but n=15 so just check
        # first post-wide row is False
        assert not result["bb_in_squeeze"].iloc[12]

    def test_squeeze_threshold_parameter(self):
        """Changing threshold changes which rows are flagged."""
        widths = [10.0] * 15
        df = _make_single_ticker(widths)
        result_strict = add_squeeze_flag(df, lookback=10, threshold=9.0)
        result_loose  = add_squeeze_flag(df, lookback=10, threshold=12.0)
        # With threshold=9.0, bandwidth=10 > threshold → all False
        assert not result_strict["bb_in_squeeze"].any(), "strict threshold: 10 > 9 → False"
        # With threshold=12.0, bandwidth=10 ≤ 12 → True after warmup
        assert result_loose["bb_in_squeeze"].iloc[14], "loose threshold: 10 ≤ 12 → True"

    def test_squeeze_returns_copy_not_mutate(self):
        """add_squeeze_flag should return a copy, not mutate input."""
        widths = [8.0] * 15
        df = _make_single_ticker(widths)
        original_cols = set(df.columns)
        _ = add_squeeze_flag(df)
        assert set(df.columns) == original_cols, "input df should not be mutated"

    def test_missing_bb_width_pct_raises(self):
        """Missing bb_width_pct column should raise KeyError, not silently return wrong results."""
        df = pd.DataFrame({"ticker": ["T0001"], "trade_date": ["2026-01-05"]})
        with pytest.raises(KeyError):
            add_squeeze_flag(df)


# ---------------------------------------------------------------------------
# vol_ma5 tests
# ---------------------------------------------------------------------------

class TestVolMa5:
    def test_vol_ma5_rolling_mean(self):
        """vol_ma5 should return rolling 5-day average per ticker."""
        df = _make_single_ticker([8.0] * 10)
        # Override volume with known values
        df["volume"] = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
        result = vol_ma5(df)
        # Row 4 (idx 4): mean of [100,200,300,400,500] = 300
        assert abs(result.iloc[4] - 300.0) < 1e-6, "vol_ma5 rolling mean 第 5 根"
        # Row 9 (idx 9): mean of [600,700,800,900,1000] = 800
        assert abs(result.iloc[9] - 800.0) < 1e-6, "vol_ma5 rolling mean 第 10 根"

    def test_vol_ma5_nan_before_warmup(self):
        """First 4 bars should be NaN (min_periods=5)."""
        df = _make_single_ticker([8.0] * 10)
        df["volume"] = 1000.0
        result = vol_ma5(df)
        assert result.iloc[:4].isna().all(), "warmup 期間前 4 根應為 NaN"

    def test_vol_ma5_per_ticker(self):
        """vol_ma5 must compute separately per ticker."""
        df1 = _make_single_ticker([8.0] * 10, ticker="A001")
        df2 = _make_single_ticker([8.0] * 10, ticker="A002")
        df1["volume"] = 1000.0
        df2["volume"] = 5000.0
        combined = pd.concat([df1, df2], ignore_index=True)
        result = vol_ma5(combined)
        # A001 rows: vol_ma5 should converge to 1000
        a001_mask = combined["ticker"] == "A001"
        assert abs(result[a001_mask].iloc[-1] - 1000.0) < 1e-6
        # A002 rows: vol_ma5 should converge to 5000
        a002_mask = combined["ticker"] == "A002"
        assert abs(result[a002_mask].iloc[-1] - 5000.0) < 1e-6
