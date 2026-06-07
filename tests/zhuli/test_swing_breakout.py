"""Unit tests for swing_breakout ma60_near_bottom relaxed condition.

Tests use synthetic bar sequences that reproduce the 6449 scenario:
  - MA60 is down-sloping by a tiny amount (< 1% 5-day range)
  - MA20 has been up-sloping for 5+ consecutive days
  - The relaxed condition should allow entry; strict should block it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from zhuli.config import SwingBreakoutConfig
from zhuli.entry.swing_breakout import detect


def _make_synthetic_df(
    n_bars: int = 80,
    ma60_start: float = 165.0,
    ma60_drift: float = -0.03,  # small daily drift on MA60 (negative = slowly falling)
    ma20_start: float = 160.0,
    ma20_drift: float = 0.50,   # positive daily drift on MA20 (rising)
    close_start: float = 162.0,
    close_drift: float = 0.40,
) -> pd.DataFrame:
    """Generate a single-ticker synthetic DataFrame with computed MA columns.

    MA values are directly set (not computed from close) to allow precise control
    over slope direction. This mimics the case where MA60 is barely falling while
    MA20 is rising.
    """
    trade_dates = pd.date_range("2026-01-01", periods=n_bars, freq="B")

    close = close_start + np.arange(n_bars) * close_drift
    ma20 = ma20_start + np.arange(n_bars) * ma20_drift
    ma60 = ma60_start + np.arange(n_bars) * ma60_drift

    df = pd.DataFrame({
        "ticker": "TEST",
        "trade_date": trade_dates,
        "open": close - 0.5,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": 1_000_000.0,   # 1000 張/day — above liquidity threshold
        "vol_ma20": 1_000_000.0,
        "ma5": ma20 - 2.0,
        "ma10": ma20 - 1.0,
        "ma20": ma20,
        "ma60": ma60,
        "ma20_slope": ma20_drift / ma20_start,   # positive — MA20 rising
        "ma60_slope_5d": ma60_drift * 5 / ma60_start,  # tiny negative
        "prev_volume": 900_000.0,
    })
    return df


def _make_inst_df(ticker: str = "TEST", net: int = 5000) -> pd.DataFrame:
    """Minimal inst_df with a single large buying event at the last date."""
    return pd.DataFrame({
        "ticker": ticker,
        "trade_date": pd.date_range("2026-01-01", periods=80, freq="B"),
        "sitc_net": [float(net)] * 80,
        "foreign_net": [0.0] * 80,
        "foreign_buy": [0.0] * 80,
        "foreign_sell": [0.0] * 80,
    })


def _make_stock_info(ticker: str = "TEST") -> pd.DataFrame:
    # Three tickers in same industry so sector_density ≥ 3 passes
    return pd.DataFrame({
        "ticker": [ticker, "TEST2", "TEST3"],
        "stock_name": [ticker, "TEST2", "TEST3"],
        "industry_category": ["測試產業", "測試產業", "測試產業"],
    })


def _make_multi_ticker_inst(tickers=("TEST", "TEST2", "TEST3"), net=5000):
    frames = []
    for t in tickers:
        frames.append(pd.DataFrame({
            "ticker": t,
            "trade_date": pd.date_range("2026-01-01", periods=80, freq="B"),
            "sitc_net": [float(net)] * 80,
            "foreign_net": [0.0] * 80,
            "foreign_buy": [0.0] * 80,
            "foreign_sell": [0.0] * 80,
        }))
    return pd.concat(frames, ignore_index=True)


def _make_multi_ticker_df(n_bars=80):
    dfs = []
    for t in ("TEST", "TEST2", "TEST3"):
        df = _make_synthetic_df(n_bars=n_bars)
        df["ticker"] = t
        dfs.append(df)
    return pd.concat(dfs, ignore_index=True)


class TestMa60NearBottomRelaxedCondition:
    """The relaxed condition triggers when MA60 is barely falling AND MA20 is rising."""

    def test_strict_blocks_when_ma60_slope_negative(self):
        """Without relaxed condition, negative ma60_slope_5d should block entry."""
        df = _make_multi_ticker_df()
        inst_df = _make_multi_ticker_inst()
        stock_info = _make_stock_info()
        # Expand stock_info for all 3 tickers
        stock_info = pd.DataFrame({
            "ticker": ["TEST", "TEST2", "TEST3"],
            "stock_name": ["TEST", "TEST2", "TEST3"],
            "industry_category": ["測試產業", "測試產業", "測試產業"],
        })

        cfg = SwingBreakoutConfig(
            ma60_near_bottom_enabled=False,
            require_sector_density=True,
            sector_density_min_count=3,
            institutional_volume_ratio=1/3,
            institutional_volume_absolute=20000,
        )
        result = detect(df, cfg=cfg, inst_df=inst_df, stock_info=stock_info)

        # ma60_drift = -0.03 per day, ma60_start=165 → slope_5d ≈ -0.03*5/165 = -0.00091 per day
        # Should be blocked (negative slope, strict mode)
        assert result.empty or (result["ma60_slope"] > 0).all(), (
            f"Strict mode should block all negative-slope MA60 signals; "
            f"got {len(result)} signals with slopes: {result['ma60_slope'].tolist()}"
        )

    def test_relaxed_allows_near_flat_ma60(self):
        """With relaxed condition, nearly-flat MA60 + rising MA20 should pass."""
        df = _make_multi_ticker_df()
        inst_df = _make_multi_ticker_inst()
        stock_info = pd.DataFrame({
            "ticker": ["TEST", "TEST2", "TEST3"],
            "stock_name": ["TEST", "TEST2", "TEST3"],
            "industry_category": ["測試產業", "測試產業", "測試產業"],
        })

        cfg = SwingBreakoutConfig(
            ma60_near_bottom_enabled=True,
            ma60_near_bottom_max_drop_pct=1.0,
            ma60_near_bottom_ma20_up_days=5,
            require_sector_density=True,
            sector_density_min_count=3,
            institutional_volume_ratio=1/3,
            institutional_volume_absolute=20000,
        )
        result = detect(df, cfg=cfg, inst_df=inst_df, stock_info=stock_info)

        # With ma60_drift=-0.03, ma60_start=165, 5-day drop = 0.03*4/165 = 0.073%
        # This is well below 1.0% threshold → should allow entry
        assert not result.empty, "Relaxed mode should allow near-flat MA60 signals"
        near_bottom_signals = result[result["ma60_near_bottom"] == True]
        assert len(near_bottom_signals) > 0, (
            "At least some signals should be flagged as ma60_near_bottom=True"
        )

    def test_relaxed_blocks_steeply_falling_ma60(self):
        """Steeply falling MA60 should still be blocked even with relaxed=True."""
        # ma60_drift = -0.50 per day (very steep drop)
        df = _make_multi_ticker_df(n_bars=80)
        # Override ma60 to be steeply falling
        for t in ("TEST", "TEST2", "TEST3"):
            mask = df["ticker"] == t
            df.loc[mask, "ma60"] = 165.0 - np.arange(mask.sum()) * 0.50
            # slope_5d = (165 - 0.5*5)/165 / 5-day window ≈ -1.5%/165 * 5 = -4.5%
            df.loc[mask, "ma60_slope_5d"] = -0.045

        inst_df = _make_multi_ticker_inst()
        stock_info = pd.DataFrame({
            "ticker": ["TEST", "TEST2", "TEST3"],
            "stock_name": ["TEST", "TEST2", "TEST3"],
            "industry_category": ["測試產業", "測試產業", "測試產業"],
        })

        cfg = SwingBreakoutConfig(
            ma60_near_bottom_enabled=True,
            ma60_near_bottom_max_drop_pct=1.0,  # 1% threshold
            ma60_near_bottom_ma20_up_days=5,
            require_sector_density=True,
            sector_density_min_count=3,
            institutional_volume_ratio=1/3,
            institutional_volume_absolute=20000,
        )
        result = detect(df, cfg=cfg, inst_df=inst_df, stock_info=stock_info)

        # Steep drop (~2.4% per 5 days) > 1.0% threshold → near_bottom should NOT fire
        if not result.empty:
            nb_signals = result[result["ma60_near_bottom"] == True]
            assert len(nb_signals) == 0, (
                f"Steep MA60 fall should not trigger near_bottom; got {len(nb_signals)} near_bottom signals"
            )

    def test_ma60_near_bottom_flag_in_output(self):
        """Output DataFrame should always have ma60_near_bottom column."""
        df = _make_multi_ticker_df()
        inst_df = _make_multi_ticker_inst()
        stock_info = pd.DataFrame({
            "ticker": ["TEST", "TEST2", "TEST3"],
            "stock_name": ["TEST", "TEST2", "TEST3"],
            "industry_category": ["測試產業", "測試產業", "測試產業"],
        })

        for enabled in (True, False):
            cfg = SwingBreakoutConfig(
                ma60_near_bottom_enabled=enabled,
                require_sector_density=True,
                sector_density_min_count=3,
            )
            result = detect(df, cfg=cfg, inst_df=inst_df, stock_info=stock_info)
            if not result.empty:
                assert "ma60_near_bottom" in result.columns, (
                    f"ma60_near_bottom column missing (enabled={enabled})"
                )

    def test_config_flag_default_on(self):
        """ma60_near_bottom_enabled should default to True."""
        cfg = SwingBreakoutConfig()
        assert cfg.ma60_near_bottom_enabled is True
        assert cfg.ma60_near_bottom_max_drop_pct == 1.0
        assert cfg.ma60_near_bottom_ma20_up_days == 5

    def test_config_can_disable(self):
        """ma60_near_bottom_enabled=False should disable the relaxed condition."""
        cfg = SwingBreakoutConfig(ma60_near_bottom_enabled=False)
        assert cfg.ma60_near_bottom_enabled is False

    def test_config_apply_overrides(self):
        """apply_overrides should handle all new ma60_near_bottom fields."""
        cfg = SwingBreakoutConfig()
        cfg2 = cfg.apply_overrides({
            "ma60_near_bottom_enabled": "false",
            "ma60_near_bottom_max_drop_pct": "1.5",
            "ma60_near_bottom_ma20_up_days": "3",
        })
        assert cfg2.ma60_near_bottom_enabled is False
        assert cfg2.ma60_near_bottom_max_drop_pct == 1.5
        assert cfg2.ma60_near_bottom_ma20_up_days == 3
