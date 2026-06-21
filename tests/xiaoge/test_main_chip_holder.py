"""Tests for xiaoge/entry/main_chip_holder.py (v1) + main_chip_holder_v2.py (v2).

Course source: 權證小哥課程 ch11 (主力買賣超與集保戶數變化), ch14 (籌碼 K 線分析).
Reference: docs/權證小哥/籌碼技術分析/detector_spec.md §2.

課程原話 (verbatim):
> 「多頭是主力買超，散戶賣超，集保戶數下降。」(ch11 00:14–00:25)
> 「主力數字…0 到 10 算小買，10 到 20 算中買，20 以上算大買。」(ch11 02:34–02:39)
> 「大戶持股的比率持續性的上升…散戶呢 100 張以下的這持股比率持續性的下降。」(ch14 02:55–03:11)

v1 conditions:
  1. main_force_5d > 0 AND chip_ratio ≥ min_chip_ratio
  2. MA20 上揚 (today > yesterday)
  3. close ≥ MA20

v2 adds:
  Axis 2: bigholder_pct 週環比上升
  Axis 3: total_people 週環比下降 OR retail_pct 週環比下降
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from xiaoge.entry.main_chip_holder import detect as detect_v1
from xiaoge.entry.main_chip_holder_v2 import detect as detect_v2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_df(
    n: int = 30,
    ticker: str = "A001",
    main_force_5d: float = 10_000.0,
    volume: float = 100_000.0,
    close_trend: str = "up",      # 'up' | 'flat' | 'down'
) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-05", periods=n)
    idx = np.arange(n, dtype=float)

    if close_trend == "up":
        close = 100.0 + idx * 0.5
    elif close_trend == "flat":
        close = np.full(n, 100.0)
    else:
        close = 100.0 - idx * 0.5

    ma20 = pd.Series(close).rolling(20, min_periods=20).mean().values

    df = pd.DataFrame({
        "ticker":        ticker,
        "trade_date":    dates,
        "open":          close * 0.99,
        "high":          close * 1.01,
        "low":           close * 0.98,
        "close":         close,
        "volume":        volume,
        "ma20":          ma20,
        "main_force_5d": main_force_5d,
    })
    return df.reset_index(drop=True)


# ===========================================================================
# v1 tests
# ===========================================================================

class TestMainChipHolderV1Fire:
    def test_fires_when_all_three_conditions_met(self):
        """ch11: 主力買超 + 月線上揚 + 站月線 → detect() True."""
        df = _base_df(n=30, main_force_5d=10_000.0, volume=100_000.0, close_trend="up")
        # chip_ratio = 10000 / (100000 * 5) = 0.02 — use low threshold to fire
        sig = detect_v1(df, min_chip_ratio=0.01)
        # Last few rows should have ma20 computed + rising + close ≥ ma20
        assert sig.iloc[25:].any(), "ch11: 主力買超 + 月線上揚 + 站月線 應觸發"

    def test_fires_with_custom_ratio_threshold(self):
        """Chip ratio threshold can be adjusted; ensure signal fires when ratio met."""
        df = _base_df(n=30, main_force_5d=8_000.0, volume=100_000.0, close_trend="up")
        # chip_ratio ≈ 8000 / 500000 = 0.016; need threshold ≤ 0.016
        sig = detect_v1(df, min_chip_ratio=0.015)
        assert sig.iloc[25:].any(), "min_chip_ratio 設低後應能觸發"


class TestMainChipHolderV1NoFire:
    def test_no_fire_when_main_force_negative(self):
        """ch11: 主力賣超 → 不觸發多頭訊號."""
        df = _base_df(n=30, main_force_5d=-5_000.0, close_trend="up")
        sig = detect_v1(df, min_chip_ratio=0.01)
        assert not sig.any(), "主力淨賣超 (main_force_5d < 0) 不應觸發"

    def test_no_fire_when_chip_ratio_below_threshold(self):
        """Chip ratio too low → no fire."""
        df = _base_df(n=30, main_force_5d=100.0, volume=1_000_000.0, close_trend="up")
        # chip_ratio = 100 / 5_000_000 = 0.00002 << 0.05
        sig = detect_v1(df, min_chip_ratio=0.05)
        assert not sig.any(), "主力比例太小不應觸發 (ch11: 需 ≥ 閾值)"

    def test_no_fire_when_ma20_falling(self):
        """MA20 下彎 → 不觸發 (月線空頭過濾)."""
        df = _base_df(n=30, main_force_5d=10_000.0, volume=100_000.0, close_trend="down")
        sig = detect_v1(df, min_chip_ratio=0.01)
        # In downtrend, ma20 will eventually fall and close < ma20
        assert not sig.iloc[25:].any(), "月線下彎時不應觸發"

    def test_no_fire_when_close_below_ma20(self):
        """close < MA20 → 不觸發 (未站月線)."""
        df = _base_df(n=30, main_force_5d=10_000.0, volume=100_000.0, close_trend="flat")
        # Force close below ma20 for last rows
        df.loc[df.index[25:], "close"] = 80.0   # below flat ma20 ~100
        sig = detect_v1(df, min_chip_ratio=0.01)
        assert not sig.iloc[25:].any(), "收盤低於月線不應觸發"


class TestMainChipHolderV1NanTolerance:
    def test_nan_main_force_gives_false(self):
        """NaN in main_force_5d → graceful False."""
        df = _base_df(n=30, main_force_5d=10_000.0, volume=100_000.0, close_trend="up")
        df["main_force_5d"] = float("nan")
        sig = detect_v1(df, min_chip_ratio=0.01)
        assert not sig.any(), "main_force_5d 全 NaN 應回傳 False"

    def test_nan_ma20_gives_false(self):
        """NaN in ma20 → graceful False."""
        df = _base_df(n=30, main_force_5d=10_000.0, volume=100_000.0, close_trend="up")
        df["ma20"] = float("nan")
        sig = detect_v1(df, min_chip_ratio=0.01)
        assert not sig.any(), "ma20 全 NaN 應回傳 False"

    def test_result_dtype(self):
        """detect() must return bool Series same length as input."""
        df = _base_df(n=20, main_force_5d=1000.0, volume=100_000.0)
        sig = detect_v1(df)
        assert isinstance(sig, pd.Series)
        assert sig.dtype == bool
        assert len(sig) == len(df)


# ===========================================================================
# v2 tests
# ===========================================================================

class TestMainChipHolderV2:
    def test_v2_fires_with_shareholding_bullish(self, tmp_shareholding_parquet: Path):
        """ch14: 三軸全過 (機構買 + 大戶累積 + 集保下降) + 月線 → v2 觸發.

        Uses bullish A001 shareholding (bigholder_pct ↑, retail ↓, total_people ↓).
        """
        df = _base_df(n=30, ticker="A001", main_force_5d=30_000.0,
                      volume=100_000.0, close_trend="up")
        sig = detect_v2(df, min_chip_ratio=0.01, shareholding_path=tmp_shareholding_parquet)
        # After warmup rows that have shareholding joined, at least some should fire
        # (A001 has bullish shareholding from fixture)
        assert sig.any(), "ch14: A001 三軸全過應觸發 v2"

    def test_v2_no_fire_when_shareholding_bearish(self, tmp_shareholding_parquet: Path):
        """ch14: 大戶賣超 (A002 bigholder_pct ↓) → v2 Axis 2 不過 → 不觸發."""
        df = _base_df(n=30, ticker="A002", main_force_5d=30_000.0,
                      volume=100_000.0, close_trend="up")
        sig = detect_v2(df, min_chip_ratio=0.01, shareholding_path=tmp_shareholding_parquet)
        # A002 has falling bigholder_pct → bigholder_up=False → should not fire
        assert not sig.any(), "ch14: 大戶持股比率下降 v2 應不觸發"

    def test_v2_raises_when_shareholding_missing(self, tmp_path: Path):
        """Missing shareholding file should raise FileNotFoundError."""
        df = _base_df(n=20, ticker="A001", main_force_5d=5_000.0, volume=100_000.0)
        bad_path = tmp_path / "nonexistent.parquet"
        with pytest.raises(FileNotFoundError, match="Shareholding parquet missing"):
            detect_v2(df, shareholding_path=bad_path)

    def test_v2_result_dtype(self, tmp_shareholding_parquet: Path):
        """detect_v2() must return bool Series same length as input."""
        df = _base_df(n=20, ticker="A001", main_force_5d=5_000.0, volume=100_000.0)
        sig = detect_v2(df, shareholding_path=tmp_shareholding_parquet)
        assert isinstance(sig, pd.Series)
        assert sig.dtype == bool
        assert len(sig) == len(df)
