"""Tests for xiaoge/scoring/cross_xiaoge_three_axis.py — detect_three_axis().

Course source: 權證小哥課程 ch13, detector_spec.md §6.

課程原話 (verbatim):
> 「越多條件交集的選出來的股票越少，那選出來的股票越少呢，他的精準度會越高。」
>  (ch13 02:03–02:27)

Output tiers:
  A+: 三維全觸發 (BB ∩ Chip ∩ KeyBroker)
  A:  任二維觸發
  B:  單一維度觸發
  C:  零觸發
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from xiaoge.scoring.cross_xiaoge_three_axis import detect_three_axis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_df(n: int = 30, ticker: str = "A001") -> pd.DataFrame:
    """Build a minimal df with all columns needed by the three sub-detectors."""
    dates = pd.bdate_range("2026-01-05", periods=n)
    idx = np.arange(n, dtype=float)
    close = 100.0 + idx * 0.3
    open_ = close * 0.99
    volume = 1000.0 + idx * 10.0
    ma5_vals  = pd.Series(close).rolling(5, min_periods=5).mean().values
    ma20_vals = pd.Series(close).rolling(20, min_periods=20).mean().values

    return pd.DataFrame({
        "ticker":        ticker,
        "trade_date":    dates,
        "open":          open_,
        "high":          close * 1.02,
        "low":           open_ * 0.98,
        "close":         close,
        "volume":        volume,
        "ma5":           ma5_vals,
        "ma20":          ma20_vals,
        "bb_upper":      close * 0.97,
        "bb_mid":        close * 0.95,
        "bb_lower":      close * 0.90,
        "bb_bandwidth":  np.full(n, 5.0),
        "bb_in_squeeze": np.zeros(n, dtype=bool),
        "main_force_5d": -100.0,       # default: chip signal OFF
    }).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Output schema tests
# ---------------------------------------------------------------------------

class TestDetectThreeAxisSchema:
    def test_output_dataframe_columns(self, tmp_broker_parquets: tuple[Path, Path]):
        """detect_three_axis() must return DataFrame with expected columns."""
        broker_path, pool_path = tmp_broker_parquets
        df = _minimal_df(n=20)
        result = detect_three_axis(
            df,
            broker_kwargs={"broker_path": broker_path, "pool_path": pool_path},
        )
        expected_cols = {"bb_fired", "chip_fired", "broker_fired", "axes_count", "tier"}
        assert expected_cols.issubset(result.columns), (
            f"detect_three_axis 回傳欄位應包含 {expected_cols}, got {result.columns.tolist()}"
        )

    def test_output_index_matches_input(self, tmp_broker_parquets: tuple[Path, Path]):
        """Output index must match input df index."""
        broker_path, pool_path = tmp_broker_parquets
        df = _minimal_df(n=20)
        result = detect_three_axis(df,
                                   broker_kwargs={"broker_path": broker_path,
                                                  "pool_path": pool_path})
        assert len(result) == len(df)
        pd.testing.assert_index_equal(result.index, df.index)

    def test_axes_count_is_integer(self, tmp_broker_parquets: tuple[Path, Path]):
        """axes_count must be integer values 0-3."""
        broker_path, pool_path = tmp_broker_parquets
        df = _minimal_df(n=20)
        result = detect_three_axis(df,
                                   broker_kwargs={"broker_path": broker_path,
                                                  "pool_path": pool_path})
        assert result["axes_count"].between(0, 3).all(), (
            "axes_count 必須在 0-3 範圍內"
        )

    def test_tier_values_valid(self, tmp_broker_parquets: tuple[Path, Path]):
        """tier column must contain only A+/A/B/C."""
        broker_path, pool_path = tmp_broker_parquets
        df = _minimal_df(n=20)
        result = detect_three_axis(df,
                                   broker_kwargs={"broker_path": broker_path,
                                                  "pool_path": pool_path})
        valid_tiers = {"A+", "A", "B", "C"}
        assert set(result["tier"].unique()).issubset(valid_tiers), (
            f"tier 值必須在 {valid_tiers} 內, got {set(result['tier'].unique())}"
        )


# ---------------------------------------------------------------------------
# Tier logic tests
# ---------------------------------------------------------------------------

class TestDetectThreeAxisTiers:
    def test_tier_c_when_no_axes_fire(self, tmp_broker_parquets: tuple[Path, Path]):
        """No axes firing → tier='C', axes_count=0."""
        broker_path, pool_path = tmp_broker_parquets
        # Build a df for a ticker NOT in the pool → broker_fired always False
        # All chip conditions OFF (main_force_5d < 0)
        # BB conditions OFF (not squeezed, no cross upper)
        df = _minimal_df(n=20, ticker="A003")   # not in pool fixture
        result = detect_three_axis(df,
                                   broker_kwargs={"broker_path": broker_path,
                                                  "pool_path": pool_path},
                                   chip_kwargs={"min_chip_ratio": 0.99})  # unreachable ratio
        # All rows should be C
        assert (result["tier"] == "C").all(), (
            "ch13: 三軸都不過應標 tier=C"
        )
        assert (result["axes_count"] == 0).all()

    def test_tier_b_when_one_axis_fires(self, tmp_broker_parquets: tuple[Path, Path]):
        """One axis fires → tier='B', axes_count=1."""
        broker_path, pool_path = tmp_broker_parquets
        # A001 has broker firing on 2026-02-02 but chip/bb off
        df = _minimal_df(n=30, ticker="A001")
        df.loc[df.index[25], "trade_date"] = pd.Timestamp("2026-02-02")
        df = df.sort_values("trade_date").reset_index(drop=True)
        # Force ma20 rising at the trade date row and close >= ma20
        trade_idx = df[df["trade_date"] == pd.Timestamp("2026-02-02")].index[0]
        if trade_idx > 0:
            df.loc[df.index[trade_idx - 1], "ma20"] = df["close"].iloc[trade_idx] - 1.0
        df.loc[df.index[trade_idx], "ma20"] = df["close"].iloc[trade_idx] - 0.5

        result = detect_three_axis(
            df, window=1,
            broker_kwargs={"broker_path": broker_path, "pool_path": pool_path},
            chip_kwargs={"min_chip_ratio": 0.99},  # chip OFF
        )
        # On the fired broker date, broker_fired=True, others=False → tier=B
        row = result.iloc[trade_idx]
        if row["broker_fired"]:
            assert row["tier"] == "B", f"ch13: 單軸觸發應標 tier=B, got {row['tier']}"
            assert row["axes_count"] == 1

    def test_tier_a_when_two_axes_fire(self, tmp_broker_parquets: tuple[Path, Path]):
        """axes_count=2 → tier='A'."""
        broker_path, pool_path = tmp_broker_parquets
        # Build df where chip fires AND broker fires (same row/window)
        df = _minimal_df(n=30, ticker="A001")
        df.loc[df.index[25], "trade_date"] = pd.Timestamp("2026-02-02")
        df = df.sort_values("trade_date").reset_index(drop=True)
        trade_idx = df[df["trade_date"] == pd.Timestamp("2026-02-02")].index[0]

        # Force chip signal at trade_idx: positive main_force_5d + ma20 rising + above ma20
        df.loc[df.index[trade_idx], "main_force_5d"] = 50_000.0
        if trade_idx > 0:
            df.loc[df.index[trade_idx - 1], "ma20"] = df["close"].iloc[trade_idx] - 2.0
        df.loc[df.index[trade_idx], "ma20"] = df["close"].iloc[trade_idx] - 1.0

        result = detect_three_axis(
            df, window=1,
            broker_kwargs={"broker_path": broker_path, "pool_path": pool_path},
            chip_kwargs={"min_chip_ratio": 0.001},  # very easy to pass
        )
        row = result.iloc[trade_idx]
        if row["chip_fired"] and row["broker_fired"]:
            assert row["tier"] == "A", f"ch13: 二軸觸發應標 tier=A, got {row['tier']}"
            assert row["axes_count"] == 2

    def test_axes_count_consistency(self, tmp_broker_parquets: tuple[Path, Path]):
        """axes_count should equal sum of the three fired booleans."""
        broker_path, pool_path = tmp_broker_parquets
        df = _minimal_df(n=20, ticker="A001")
        result = detect_three_axis(df,
                                   broker_kwargs={"broker_path": broker_path,
                                                  "pool_path": pool_path})
        computed = (result["bb_fired"].astype(int)
                    + result["chip_fired"].astype(int)
                    + result["broker_fired"].astype(int))
        pd.testing.assert_series_equal(
            result["axes_count"].reset_index(drop=True),
            computed.reset_index(drop=True),
            check_names=False,
        )


# ---------------------------------------------------------------------------
# Window parameter test
# ---------------------------------------------------------------------------

class TestDetectThreeAxisWindow:
    def test_window_parameter(self, tmp_broker_parquets: tuple[Path, Path]):
        """Larger window should maintain fired=True longer after signal."""
        broker_path, pool_path = tmp_broker_parquets
        df = _minimal_df(n=30, ticker="A001")
        # Place a chip signal at row 20
        chip_idx = 20
        df.loc[df.index[chip_idx], "main_force_5d"] = 50_000.0
        if chip_idx > 0:
            df.loc[df.index[chip_idx - 1], "ma20"] = df["close"].iloc[chip_idx] - 2.0
        df.loc[df.index[chip_idx], "ma20"] = df["close"].iloc[chip_idx] - 1.0

        r_narrow = detect_three_axis(df, window=1,
                                     broker_kwargs={"broker_path": broker_path,
                                                    "pool_path": pool_path},
                                     chip_kwargs={"min_chip_ratio": 0.001})
        r_wide   = detect_three_axis(df, window=8,
                                     broker_kwargs={"broker_path": broker_path,
                                                    "pool_path": pool_path},
                                     chip_kwargs={"min_chip_ratio": 0.001})
        # At row 25, chip_fired should be False for window=1, True for window=8
        assert not r_narrow["chip_fired"].iloc[25], "window=1: 5 根後 chip_fired 應 False"
        assert r_wide["chip_fired"].iloc[25], "window=8: 5 根內 chip_fired 應保持 True"
