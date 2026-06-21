"""Tests for xiaoge/entry/key_broker_signal.py — detect() + detect_short().

Course source: 權證小哥課程 ch09-ch10, ch15.
Reference: docs/權證小哥/籌碼技術分析/detector_spec.md §4.

課程原話 (verbatim):
> 「關鍵分點…就是它會低買高賣的分點，而且它量做很大。」(ch09 01:50)
> 「關鍵分點先買，主力後面買；關鍵分點先賣，主力後面才賣。」(ch09 02:43)
> 「在殺低大買的分點呢，就是我們喜歡的分點。」(ch15 11:00)

Detector conditions (多頭 detect()):
  - 池內任一分點淨買 ≥ 50 張 (50,000 股)
  - MA20 上揚 (today > yesterday)
  - 收盤 ≥ MA20

Detector conditions (空頭 detect_short()):
  - 池內任一分點淨賣 ≥ 50 張
  - MA20 下彎 (today < yesterday)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from xiaoge.entry.key_broker_signal import detect, detect_short


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_bars_df(
    ticker: str = "A001",
    n: int = 30,
    ma20_trend: str = "up",   # 'up' | 'down' | 'flat'
) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-05", periods=n)
    idx = np.arange(n, dtype=float)

    if ma20_trend == "up":
        close = 100.0 + idx * 0.5
    elif ma20_trend == "down":
        close = 130.0 - idx * 0.5
    else:
        close = np.full(n, 100.0)

    ma20_vals = pd.Series(close).rolling(20, min_periods=20).mean().values

    return pd.DataFrame({
        "ticker":     ticker,
        "trade_date": dates,
        "open":       close * 0.99,
        "high":       close * 1.01,
        "low":        close * 0.98,
        "close":      close,
        "volume":     1000.0,
        "ma20":       ma20_vals,
    }).reset_index(drop=True)


# ---------------------------------------------------------------------------
# detect() (長多) tests
# ---------------------------------------------------------------------------

class TestKeyBrokerDetectLong:
    def test_fires_when_pool_broker_buys_heavily(self, tmp_broker_parquets: tuple[Path, Path]):
        """ch09 關鍵分點先買: pool broker 大買 ≥ 50 張 + 月線上揚 → True.

        Fixture has B01 buying 60,000 shares of A001 on 2026-02-02.
        """
        broker_path, pool_path = tmp_broker_parquets
        df = _build_bars_df(ticker="A001", n=30, ma20_trend="up")
        # Ensure the trade date 2026-02-02 is within df range
        df.loc[df.index[25], "trade_date"] = pd.Timestamp("2026-02-02")
        df = df.sort_values("trade_date").reset_index(drop=True)
        sig = detect(df, broker_path=broker_path, pool_path=pool_path)
        # Row where trade_date=2026-02-02 should fire (if ma20 is rising there)
        fired_rows = df[sig]
        assert len(fired_rows) > 0, (
            "ch09: 池內分點大買 ≥ 50 張 + 月線上揚 應觸發"
        )

    def test_no_fire_when_non_pool_broker(self, tmp_broker_parquets: tuple[Path, Path]):
        """Non-pool broker (B99) should not trigger signal even with large buy."""
        broker_path, pool_path = tmp_broker_parquets
        # Build df for a ticker not in pool (A003)
        df = _build_bars_df(ticker="A003", n=30, ma20_trend="up")
        sig = detect(df, broker_path=broker_path, pool_path=pool_path)
        assert not sig.any(), "非池內分點不應觸發訊號"

    def test_no_fire_when_ma20_not_rising(self, tmp_broker_parquets: tuple[Path, Path]):
        """月線下彎 → 多頭訊號不觸發."""
        broker_path, pool_path = tmp_broker_parquets
        df = _build_bars_df(ticker="A001", n=30, ma20_trend="down")
        df.loc[df.index[25], "trade_date"] = pd.Timestamp("2026-02-02")
        df = df.sort_values("trade_date").reset_index(drop=True)
        sig = detect(df, broker_path=broker_path, pool_path=pool_path)
        assert not sig.any(), "月線下彎時多頭訊號不應觸發"

    def test_raises_when_broker_file_missing(self, tmp_path: Path):
        """Missing broker trades file should raise FileNotFoundError."""
        df = _build_bars_df()
        with pytest.raises(FileNotFoundError):
            detect(df, broker_path=tmp_path / "missing.parquet",
                   pool_path=tmp_path / "pool.parquet")

    def test_result_is_bool_series(self, tmp_broker_parquets: tuple[Path, Path]):
        """detect() must return bool Series indexed like input."""
        broker_path, pool_path = tmp_broker_parquets
        df = _build_bars_df(ticker="A001", n=20, ma20_trend="up")
        sig = detect(df, broker_path=broker_path, pool_path=pool_path)
        assert isinstance(sig, pd.Series)
        assert sig.dtype == bool
        assert len(sig) == len(df)


# ---------------------------------------------------------------------------
# detect_short() (空頭) tests
# ---------------------------------------------------------------------------

class TestKeyBrokerDetectShort:
    def test_fires_when_pool_broker_sells_heavily(self, tmp_broker_parquets: tuple[Path, Path]):
        """ch09 關鍵分點先賣: 池內 B02 大賣 A002 ≥ 50 張 + 月線下彎 → True."""
        broker_path, pool_path = tmp_broker_parquets
        df = _build_bars_df(ticker="A002", n=30, ma20_trend="down")
        df.loc[df.index[25], "trade_date"] = pd.Timestamp("2026-02-02")
        df = df.sort_values("trade_date").reset_index(drop=True)
        sig = detect_short(df, broker_path=broker_path, pool_path=pool_path)
        assert sig.any(), "ch09 關鍵分點大賣 + 月線下彎 應觸發空頭訊號"

    def test_short_no_fire_when_ma20_rising(self, tmp_broker_parquets: tuple[Path, Path]):
        """月線上揚 → 空頭訊號不觸發."""
        broker_path, pool_path = tmp_broker_parquets
        df = _build_bars_df(ticker="A002", n=30, ma20_trend="up")
        df.loc[df.index[25], "trade_date"] = pd.Timestamp("2026-02-02")
        df = df.sort_values("trade_date").reset_index(drop=True)
        sig = detect_short(df, broker_path=broker_path, pool_path=pool_path)
        assert not sig.any(), "月線上揚時空頭訊號不應觸發"

    def test_short_result_dtype(self, tmp_broker_parquets: tuple[Path, Path]):
        broker_path, pool_path = tmp_broker_parquets
        df = _build_bars_df(ticker="A002", n=20, ma20_trend="down")
        sig = detect_short(df, broker_path=broker_path, pool_path=pool_path)
        assert isinstance(sig, pd.Series)
        assert sig.dtype == bool
