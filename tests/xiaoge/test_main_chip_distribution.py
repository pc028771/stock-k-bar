"""Tests for xiaoge/exit/main_chip_distribution.py — detect() (曲終人散出場警告).

Course source: 權證小哥課程 ch07 (曲終人散), ch11.
Reference: docs/權證小哥/籌碼技術分析/detector_spec.md §3 / exit detector.

課程原話 (verbatim):
> 「在高檔的時候主力在這邊大幅地賣超，散戶大幅地買超，集保戶數大幅地增加…
>  很容易第一根出現之後後面就崩跌了。」(ch07 09:13–09:35)

5 條件:
  1. 高檔: close >= MA60 × 1.15
  2. 主力大賣: main_force_5d ≤ -20,000 (股)
  3. 集保戶數環比增加 (total_people ↑, 可選)
  4. 布林帶寬寬: bb_width_pct ≥ 20
  5. 明顯黑K: close < open AND (open-close)/open ≥ 3%
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from xiaoge.exit.main_chip_distribution import detect


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _distribution_row(
    close: float = 120.0,
    open_: float = 126.0,
    ma60: float = 100.0,
    bb_width_pct: float = 25.0,
    main_force_5d: float = -25_000.0,
    ticker: str = "A001",
    n: int = 10,
    trade_date: str = "2026-01-05",
) -> pd.DataFrame:
    """Build a minimal df where the last row should trigger 曲終人散."""
    dates = pd.bdate_range(trade_date, periods=n)
    df = pd.DataFrame({
        "ticker":        ticker,
        "trade_date":    dates,
        "open":          np.full(n, open_),
        "close":         np.full(n, close),
        "ma60":          np.full(n, ma60),
        "bb_width_pct":  np.full(n, bb_width_pct),
        "main_force_5d": np.full(n, main_force_5d),
    })
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Positive (fire) tests — no shareholding
# ---------------------------------------------------------------------------

class TestDistributionFireWithoutShareholding:
    """Tests for the 4-condition (no shareholding) path."""

    def test_fires_when_all_4_conditions_met(self):
        """ch07 曲終人散: 高檔 + 主力大賣 + 帶寬 > 20 + 明顯黑K → True (4-condition mode)."""
        # close=120, open=126 → black K, amplitude=(126-120)/126=4.76% > 3%
        # ma60=100, close/ma60=1.2 > 1.15 → high zone
        # main_force_5d=-25000 ≤ -20000
        # bb_width_pct=25 ≥ 20
        df = _distribution_row(close=120.0, open_=126.0, ma60=100.0,
                               bb_width_pct=25.0, main_force_5d=-25_000.0)
        sig = detect(df, shareholding_path=None)
        assert sig.iloc[-1], (
            "ch07 4 條全過 (無 shareholding) 應觸發曲終人散出場警告"
        )

    def test_fires_with_custom_thresholds(self):
        """Threshold parameters can be adjusted."""
        # Slightly below default thresholds, but passes with relaxed params
        df = _distribution_row(close=112.0, open_=116.0, ma60=100.0,
                               bb_width_pct=16.0, main_force_5d=-15_000.0)
        sig = detect(
            df,
            min_chip_sell_shares=-10_000,    # relaxed
            min_high_zone_ratio=1.10,         # relaxed
            min_bandwidth=15.0,              # relaxed
            min_black_k_amplitude=0.02,       # relaxed
            shareholding_path=None,
        )
        assert sig.iloc[-1], "放寬門檻後應能觸發"


# ---------------------------------------------------------------------------
# Negative (no-fire) tests
# ---------------------------------------------------------------------------

class TestDistributionNoFire:
    def test_no_fire_when_not_in_high_zone(self):
        """高檔條件未過 (close < MA60 × 1.15) → 不觸發."""
        df = _distribution_row(close=110.0, open_=115.0, ma60=100.0)
        # close/ma60 = 1.10 < 1.15 → not high zone
        sig = detect(df, shareholding_path=None)
        assert not sig.iloc[-1], "未達高檔 (close < MA60×1.15) 不應觸發"

    def test_no_fire_when_main_force_buying(self):
        """主力買超 (main_force_5d > 0) → 不觸發."""
        df = _distribution_row(main_force_5d=5_000.0)
        sig = detect(df, shareholding_path=None)
        assert not sig.iloc[-1], "主力買超時不應觸發曲終人散"

    def test_no_fire_when_bandwidth_narrow(self):
        """帶寬 < 20 → 不觸發."""
        df = _distribution_row(bb_width_pct=15.0)
        sig = detect(df, shareholding_path=None)
        assert not sig.iloc[-1], "帶寬窄 (< 20) 不應觸發 (ch07: 高檔震盪帶寬展開)"

    def test_no_fire_when_red_k(self):
        """紅K (close > open) → 不觸發 (需明顯黑K)."""
        df = _distribution_row(close=128.0, open_=120.0)  # close > open → red K
        sig = detect(df, shareholding_path=None)
        assert not sig.iloc[-1], "紅K時不應觸發 (ch07: 需第一根明顯黑K)"

    def test_no_fire_when_black_k_amplitude_too_small(self):
        """黑K振幅 < 3% → 不觸發."""
        # open=122, close=120 → amplitude = 2/122 = 1.6% < 3%
        df = _distribution_row(close=120.0, open_=122.0, ma60=100.0)
        sig = detect(df, shareholding_path=None)
        assert not sig.iloc[-1], "黑K振幅太小 (< 3%) 不應觸發"


# ---------------------------------------------------------------------------
# Shareholding integration tests
# ---------------------------------------------------------------------------

class TestDistributionWithShareholding:
    def test_fires_with_bearish_shareholding(self, tmp_shareholding_parquet: Path):
        """ch07: 集保戶數增加 (散戶大買接盤) → 5條件全過 → 觸發.

        A002 in fixture has rising total_people (bearish chip flow).
        """
        df = _distribution_row(
            ticker="A002", close=120.0, open_=126.0, ma60=100.0,
            bb_width_pct=25.0, main_force_5d=-25_000.0,
        )
        sig = detect(df, shareholding_path=tmp_shareholding_parquet)
        assert sig.iloc[-1], (
            "ch07: 5 條件全過 (含集保戶增加) 應觸發曲終人散"
        )

    def test_no_fire_with_bullish_shareholding(self, tmp_shareholding_parquet: Path):
        """ch07: 集保戶數下降 (A001 in fixture) → 散戶未接盤 → 5條件之一不過 → 不觸發."""
        df = _distribution_row(
            ticker="A001", close=120.0, open_=126.0, ma60=100.0,
            bb_width_pct=25.0, main_force_5d=-25_000.0,
        )
        sig = detect(df, shareholding_path=tmp_shareholding_parquet)
        # A001 has falling total_people (total_up=False) → 5th condition fails
        assert not sig.iloc[-1], (
            "ch07: 集保戶數未增加 (A001 fixture) 5條件不全過 → 不觸發"
        )

    def test_graceful_when_shareholding_missing(self, tmp_path: Path):
        """shareholding_path 不存在 → 降級為 4 條件模式 (不 raise)."""
        df = _distribution_row(close=120.0, open_=126.0, ma60=100.0,
                               bb_width_pct=25.0, main_force_5d=-25_000.0)
        bad_path = tmp_path / "nonexistent.parquet"
        # Should NOT raise, falls back to 4-condition mode
        sig = detect(df, shareholding_path=bad_path)
        assert isinstance(sig, pd.Series)
        assert sig.dtype == bool

    def test_shareholding_none_uses_4_conditions(self):
        """shareholding_path=None → 4-condition mode, should fire when others pass."""
        df = _distribution_row(close=120.0, open_=126.0, ma60=100.0,
                               bb_width_pct=25.0, main_force_5d=-25_000.0)
        sig = detect(df, shareholding_path=None)
        assert sig.iloc[-1], "shareholding_path=None 4 條件全過應觸發"


# ---------------------------------------------------------------------------
# NaN / edge-case tests
# ---------------------------------------------------------------------------

class TestDistributionNanTolerance:
    def test_nan_ma60_gives_false(self):
        df = _distribution_row()
        df["ma60"] = float("nan")
        sig = detect(df, shareholding_path=None)
        assert not sig.any(), "ma60 為 NaN 時應回傳 False"

    def test_result_is_bool_series(self):
        df = _distribution_row()
        sig = detect(df, shareholding_path=None)
        assert isinstance(sig, pd.Series)
        assert sig.dtype == bool
        assert len(sig) == len(df)

    def test_parameter_min_bandwidth_boundary(self):
        """Boundary test: bb_width_pct exactly at threshold should fire."""
        df = _distribution_row(bb_width_pct=20.0, close=120.0, open_=126.0, ma60=100.0,
                               main_force_5d=-25_000.0)
        sig = detect(df, min_bandwidth=20.0, shareholding_path=None)
        assert sig.iloc[-1], "帶寬剛好等於門檻 (≥ 20) 應觸發"
