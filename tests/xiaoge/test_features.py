"""Tests for xiaoge/features.py — add_volatility(), add_20d_high_low(), classify_bollinger_pattern().

Course source: 權證小哥課程 ch06-ch07, ch12.

課程原話:
> 「布林軌道是一個由 20MA 加減 2 個標準差所形成的通道。」(ch06)
> 「布林昇龍拳…連續二根紅K…從下通道一下就打到上通道。」(ch07 00:21–01:16)
> 「平步青雲開布林…突發性的利多，突然拉一根。」(ch07)
> 「降龍布林掌…高檔盤整出貨之後往下開布林、沿下軌走。」(ch07)
> 「息軍養士…初升段後布林壓縮，再次往上開布林（盤整後續攻）。」(ch07)
> 「回測均線喝了再上…價漲量增、價跌量縮、回測均線後再次往上。」(ch07)
> 「曲終人散…高檔主力在這邊大幅地賣超，散戶大幅地買超，集保戶數大幅地增加。」(ch07 09:13–09:35)
> 「短期波動度上升 2%↑ + 5MA 上揚 + 站上 5MA」(ch12)
> 「突破平台整理區…創 20 日高價（這 20 天買的人都賺錢）。」(ch12)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from xiaoge.features import (
    BollingerPattern,
    add_20d_high_low,
    add_bollinger,
    add_volatility,
    classify_bollinger_pattern,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_df(n: int = 40, ticker: str = "T0001",
             close_fn=None) -> pd.DataFrame:
    idx = np.arange(n, dtype=float)
    if close_fn is None:
        close = 100.0 + idx + np.sin(idx)
    else:
        close = close_fn(idx)
    open_ = close * 0.99
    dates = pd.bdate_range("2026-01-05", periods=n)
    df = pd.DataFrame({
        "ticker":     ticker,
        "trade_date": dates,
        "open":       open_,
        "high":       close * 1.01,
        "low":        open_ * 0.99,
        "close":      close,
        "volume":     1000.0,
    })
    return df


# ---------------------------------------------------------------------------
# add_volatility tests
# ---------------------------------------------------------------------------

class TestAddVolatility:
    def test_volatility_5d_column_added(self):
        """add_volatility must add volatility_5d column."""
        df = _base_df(30)
        result = add_volatility(df)
        assert "volatility_5d" in result.columns, "ch12: volatility_5d 欄位必須存在"
        assert "volatility_rising" in result.columns, "ch12: volatility_rising 欄位必須存在"

    def test_volatility_nan_before_warmup(self):
        """First 4+1 rows (window=5) should be NaN."""
        df = _base_df(20)
        result = add_volatility(df, window=5)
        assert result["volatility_5d"].iloc[:5].isna().all(), "warmup 期間應為 NaN"

    def test_volatility_rising_fires_when_vol_increases(self):
        """ch12: 波動度上升 2%↑ → volatility_rising=True.

        We construct a sequence where the last few bars have large price swings
        (high std) compared to earlier bars (low std).
        """
        # Low volatility for first 20 bars, then high volatility
        n = 30
        close = np.concatenate([
            np.linspace(100, 105, 20),           # flat, low vol
            np.array([103, 108, 101, 109, 102, 110, 100, 112, 99, 111]),  # high vol
        ])
        df = _base_df(n, close_fn=lambda _: close)
        result = add_volatility(df, window=5, threshold_rising_pct=0.1)
        # The transition rows (around index 20-25) should see volatility_rising=True
        assert result["volatility_rising"].iloc[25:].any(), (
            "ch12: 波動度明顯上升區段 volatility_rising 應亮"
        )

    def test_volatility_threshold_parameter(self):
        """Threshold change must affect how many rows are flagged."""
        df = _base_df(30)
        result_loose = add_volatility(df, threshold_rising_pct=0.0)
        result_strict = add_volatility(df, threshold_rising_pct=100.0)  # unreachable
        loose_count = result_loose["volatility_rising"].sum()
        strict_count = result_strict["volatility_rising"].sum()
        assert loose_count >= strict_count, "threshold 越大命中越少"

    def test_volatility_no_mutate(self):
        """add_volatility must return a new df and not mutate input."""
        df = _base_df(30)
        original_cols = set(df.columns)
        _ = add_volatility(df)
        assert set(df.columns) == original_cols


# ---------------------------------------------------------------------------
# add_20d_high_low tests
# ---------------------------------------------------------------------------

class TestAdd20dHighLow:
    def test_columns_added(self):
        df = _base_df(30)
        result = add_20d_high_low(df)
        for col in ["high_20d", "low_20d", "is_20d_high", "is_20d_low"]:
            assert col in result.columns, f"ch12: {col} 欄位必須存在"

    def test_is_20d_high_on_new_high(self):
        """ch12: 創 20 日高價 → is_20d_high=True."""
        n = 25
        # Steadily rising close so last bar is definitely 20d high
        close = np.linspace(100.0, 130.0, n)
        df = _base_df(n, close_fn=lambda _: close)
        result = add_20d_high_low(df)
        assert result["is_20d_high"].iloc[-1], (
            "ch12: 創 20 日新高的那根 is_20d_high 應為 True"
        )

    def test_is_20d_low_on_new_low(self):
        """Falling close: last bar is the 20d low → is_20d_low=True."""
        n = 25
        close = np.linspace(130.0, 100.0, n)
        df = _base_df(n, close_fn=lambda _: close)
        result = add_20d_high_low(df)
        assert result["is_20d_low"].iloc[-1], "創 20 日新低的那根 is_20d_low 應為 True"

    def test_not_20d_high_when_middle_bar_highest(self):
        """When a middle bar is the highest, last bar is NOT 20d high."""
        n = 25
        close = np.concatenate([
            np.linspace(100.0, 130.0, 15),  # rising
            np.linspace(129.0, 110.0, 10),  # falling
        ])
        df = _base_df(n, close_fn=lambda _: close)
        result = add_20d_high_low(df)
        assert not result["is_20d_high"].iloc[-1], (
            "最後一根不是 20 日高點時 is_20d_high 應為 False"
        )

    def test_nan_before_warmup(self):
        df = _base_df(25)
        result = add_20d_high_low(df, window=20)
        assert result["high_20d"].iloc[:19].isna().all(), "warmup 期間 high_20d 應為 NaN"

    def test_no_mutate(self):
        df = _base_df(30)
        original_cols = set(df.columns)
        _ = add_20d_high_low(df)
        assert set(df.columns) == original_cols


# ---------------------------------------------------------------------------
# classify_bollinger_pattern tests
# ---------------------------------------------------------------------------

class TestClassifyBollingerPattern:
    def _df_with_bollinger(self, n: int = 40, ticker="T0001") -> pd.DataFrame:
        """Build df with pre-computed Bollinger columns."""
        df = _base_df(n, ticker=ticker)
        df = add_bollinger(df)
        df["bb_width_pct"] = df["bb_bandwidth"]  # alias
        df["volume"] = 1000.0
        return df

    def test_bb_pattern_column_added(self):
        """classify_bollinger_pattern must add bb_pattern column."""
        df = self._df_with_bollinger()
        result = classify_bollinger_pattern(df)
        assert "bb_pattern" in result.columns, "bb_pattern 欄位必須存在"

    def test_default_pattern_is_none(self):
        """Rows not matching any pattern should be labelled NONE."""
        df = self._df_with_bollinger()
        result = classify_bollinger_pattern(df)
        none_count = (result["bb_pattern"] == BollingerPattern.NONE.value).sum()
        total = len(result)
        # In a gently trending series most rows won't match edge patterns
        assert none_count > 0, "正常趨勢中應有部分 NONE 行"
        assert none_count <= total

    def test_rising_dragon_pattern_detected(self):
        """ch07 布林昇龍拳: in_squeeze + 2連紅 + prev near lower + cross upper → RISING_DRAGON.

        We hand-craft a minimal DataFrame with exactly these conditions.
        """
        # Manually build a 35-row df where last row triggers RISING_DRAGON
        n = 35
        # Narrow bandwidth during 10-20 (squeeze), then breakout at row 34
        base_close = 100.0
        # Simulate squeeze: close stays near 100, small range
        close = np.full(n, base_close)
        close[-2] = 97.0   # prev close near lower band
        close[-1] = 108.0  # breakout above upper band

        open_ = close * 0.99
        open_[-1] = 99.0   # red K today (close > open)
        open_[-2] = 96.0   # red K yesterday

        df = pd.DataFrame({
            "ticker":     "T0001",
            "trade_date": pd.bdate_range("2026-01-05", periods=n),
            "open":       open_,
            "high":       close * 1.02,
            "low":        open_ * 0.98,
            "close":      close,
            "volume":     1000.0,
        })
        df = add_bollinger(df)
        df["bb_width_pct"] = df["bb_bandwidth"]

        # Force squeeze: set bb_width_pct artificially low for past 25+ rows
        df.loc[:n-3, "bb_width_pct"] = 5.0  # all squeeze
        # Set bb_upper artificially low so close[-1]=108 > bb_upper
        df.loc[n-1, "bb_upper"] = 105.0
        # Set bb_mid around 102 so prev_close[97] < bb_mid (near lower)
        df.loc[n-2, "bb_mid"] = 102.0

        result = classify_bollinger_pattern(df, squeeze_threshold=10.0, squeeze_lookback=10)
        # Check the last row
        pattern_last = result["bb_pattern"].iloc[-1]
        assert pattern_last == BollingerPattern.BB_RISING_DRAGON.value, (
            f"ch07 昇龍拳條件滿足時應標 BB_RISING_DRAGON, got {pattern_last}"
        )

    def test_distribution_pattern_detected(self):
        """ch07 曲終人散: wide bb + black K + close > mid + main_force_1d < 0 → DISTRIBUTION."""
        n = 25
        df = self._df_with_bollinger(n)
        # Set all bb_width_pct = 25 (wide), last bar is black K above mid
        df["bb_width_pct"] = 25.0
        df.loc[df.index[-1], "open"] = 110.0
        df.loc[df.index[-1], "close"] = 105.0   # black K
        df.loc[df.index[-1], "bb_mid"] = 100.0   # close > mid
        df["main_force_1d"] = -100.0              # main force selling

        result = classify_bollinger_pattern(df, wide_threshold=20.0)
        assert result["bb_pattern"].iloc[-1] == BollingerPattern.BB_DISTRIBUTION.value, (
            "ch07 曲終人散條件: 寬帶寬 + 黑K + 站 mid 以上 + 主力賣 → DISTRIBUTION"
        )

    def test_falling_dragon_pattern_detected(self):
        """ch07 降龍布林掌: in_squeeze + 2連黑 + cross lower → FALLING_DRAGON."""
        n = 35
        df = self._df_with_bollinger(n)
        # Force squeeze (narrow bw) and bearish conditions
        df["bb_width_pct"] = 5.0   # all rows in squeeze
        # Last 2 bars: black K, close < bb_lower
        df.loc[df.index[-2], "open"] = 110.0
        df.loc[df.index[-2], "close"] = 105.0   # black K
        df.loc[df.index[-1], "open"] = 110.0
        df.loc[df.index[-1], "close"] = 94.0    # black K + below lower
        df.loc[df.index[-1], "bb_lower"] = 100.0

        result = classify_bollinger_pattern(df, squeeze_threshold=10.0, squeeze_lookback=10)
        pattern_last = result["bb_pattern"].iloc[-1]
        assert pattern_last == BollingerPattern.BB_FALLING_DRAGON.value, (
            f"ch07 降龍布林掌應標 BB_FALLING_DRAGON, got {pattern_last}"
        )

    def test_bollinger_enum_values_valid(self):
        """All BollingerPattern enum values should be non-empty strings."""
        for member in BollingerPattern:
            assert isinstance(member.value, str) and len(member.value) > 0

    def test_no_mutate(self):
        df = self._df_with_bollinger()
        original_cols = set(df.columns)
        _ = classify_bollinger_pattern(df)
        assert set(df.columns) == original_cols


# ---------------------------------------------------------------------------
# add_bollinger tests
# ---------------------------------------------------------------------------

class TestAddBollinger:
    def test_bollinger_columns_added(self):
        df = _base_df(30)
        result = add_bollinger(df)
        for col in ["bb_mid", "bb_upper", "bb_lower", "bb_bandwidth"]:
            assert col in result.columns, f"add_bollinger 必須加 {col}"

    def test_bb_mid_equals_ma20(self):
        df = _base_df(30)
        result = add_bollinger(df)
        # bb_mid should equal 20-day rolling mean of close
        expected_ma20 = df["close"].rolling(20, min_periods=20).mean()
        pd.testing.assert_series_equal(
            result["bb_mid"].dropna(), expected_ma20.dropna(),
            check_names=False, rtol=1e-6,
        )

    def test_bb_upper_above_lower(self):
        df = _base_df(30)
        result = add_bollinger(df).dropna(subset=["bb_upper", "bb_lower"])
        assert (result["bb_upper"] >= result["bb_lower"]).all(), (
            "bb_upper 必須 ≥ bb_lower (std ≥ 0)"
        )
