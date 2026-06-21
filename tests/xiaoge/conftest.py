"""Shared fixtures for xiaoge detector / indicator tests.

All fixtures use deterministic synthetic data (no prod DB required).
Seed: numpy random seed 42 for reproducibility.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _make_ticker_bars(
    ticker: str,
    n: int = 60,
    start_close: float = 100.0,
    start_date: str = "2026-01-05",
) -> pd.DataFrame:
    """Build n synthetic daily bars for one ticker.

    close = start_close + i + sin(i)          (deterministic, gently trending up)
    open  = close * 0.99
    high  = close * 1.01
    low   = open  * 0.99
    volume = 1000 + 200 * (i % 5)            (light intraday rhythm)

    MA5/MA10/MA20/MA60 are rolling means of close.
    BB columns derived from close (period 20, 2 std).
    main_force_1d/5d/10d/20d: synthetic positive values (trending buy).
    """
    dates = pd.bdate_range(start_date, periods=n)
    idx = np.arange(n)
    close = start_close + idx + np.sin(idx)
    open_ = close * 0.99
    high  = close * 1.01
    low   = open_ * 0.99
    volume = (1000 + 200 * (idx % 5)).astype(float)

    df = pd.DataFrame({
        "ticker":     ticker,
        "trade_date": dates,
        "open":       open_,
        "high":       high,
        "low":        low,
        "close":      close,
        "volume":     volume,
    })

    # Rolling MAs
    for window, col in [(5, "ma5"), (10, "ma10"), (20, "ma20"), (60, "ma60")]:
        df[col] = df["close"].rolling(window, min_periods=window).mean()

    # Bollinger bands (period 20, 2 std, lower-band normalised bandwidth)
    std20 = df["close"].rolling(20, min_periods=20).std(ddof=0)
    df["bb_mid"]       = df["ma20"]
    df["bb_upper"]     = df["ma20"] + 2 * std20
    df["bb_lower"]     = df["ma20"] - 2 * std20
    # bandwidth formula as per features.py: (upper-lower)/lower*100
    df["bb_bandwidth"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_lower"] * 100.0
    # screener uses (upper-lower)/mid*100 per bars.py
    df["bb_width_pct"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"] * 100.0

    # bb_in_squeeze flag (rolling max bandwidth ≤ 12 over 10 bars)
    df["bb_in_squeeze"] = (
        df["bb_width_pct"].rolling(10, min_periods=10).max() <= 12.0
    ).fillna(False)

    # Synthetic main force (positive = buying; scale relative to volume)
    df["main_force_1d"]  = volume * 0.06    # ~6% daily net buying
    df["main_force_5d"]  = volume * 0.30    # 5-day rolling positive
    df["main_force_10d"] = volume * 0.55
    df["main_force_20d"] = volume * 1.00
    df["vol_ma20"]       = df["volume"].rolling(20, min_periods=20).mean()
    df["custody_accounts"] = pd.NA

    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Public fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_bars() -> pd.DataFrame:
    """60 days × 3 tickers of synthetic OHLCV + features (deterministic seed 42).

    Tickers: A001 (uptrend, starts 100), A002 (uptrend, starts 150), A003 (starts 50).
    All columns required by any xiaoge detector are present.
    """
    np.random.seed(42)
    frames = [
        _make_ticker_bars("A001", n=60, start_close=100.0),
        _make_ticker_bars("A002", n=60, start_close=150.0),
        _make_ticker_bars("A003", n=60, start_close=50.0),
    ]
    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values(["ticker", "trade_date"]).reset_index(drop=True)
    return df


@pytest.fixture
def tmp_shareholding_parquet(tmp_path: Path) -> Path:
    """Write a minimal shareholding parquet for v2 / distribution detector tests.

    Schema: ticker, date, bigholder_pct, retail_pct, total_people
    Two tickers (A001, A002), 4 weekly snapshots each.

    For A001: bigholder_pct increasing, retail_pct decreasing, total_people decreasing
              → bullish chip flow (v2 detector should see bigholder_up=True, retail_down=True).
    For A002: opposite → bearish (v2 detector axes 2/3 False).
    """
    rows = []
    base_date = pd.Timestamp("2026-01-05")
    for w in range(4):
        dt = base_date + pd.Timedelta(weeks=w)
        # A001 bullish: big holders accumulating, retail selling
        rows.append({
            "ticker":        "A001",
            "date":          dt,
            "bigholder_pct": 35.0 + w * 1.5,   # rising
            "retail_pct":    30.0 - w * 0.5,   # falling
            "total_people":  50000 - w * 200,   # falling
        })
        # A002 bearish: big holders selling, retail accumulating
        rows.append({
            "ticker":        "A002",
            "date":          dt,
            "bigholder_pct": 40.0 - w * 1.5,   # falling
            "retail_pct":    25.0 + w * 0.5,   # rising
            "total_people":  60000 + w * 200,   # rising
        })

    sh = pd.DataFrame(rows)
    sh["date"] = pd.to_datetime(sh["date"])
    out_path = tmp_path / "shareholding.parquet"
    sh.to_parquet(out_path, index=False)
    return out_path


@pytest.fixture
def tmp_broker_parquets(tmp_path: Path) -> tuple[Path, Path]:
    """Write synthetic broker_trades + key_broker_pool parquets.

    Pool: broker B01 tracks A001 (buying), broker B02 tracks A002 (selling).
    Trades: B01 buys 60,000 shares of A001 on 2026-02-02 (net=+60000 ≥ 50000 threshold).
            B02 sells 55,000 shares of A002 on 2026-02-02 (net=-55000 ≤ -50000).
    """
    trades_date = pd.Timestamp("2026-02-02")
    trades = pd.DataFrame([
        {"ticker": "A001", "date": trades_date, "broker_id": "B01", "net_shares":  60_000},
        {"ticker": "A002", "date": trades_date, "broker_id": "B02", "net_shares": -55_000},
        {"ticker": "A001", "date": trades_date, "broker_id": "B99", "net_shares":   5_000},  # non-pool
    ])
    pool = pd.DataFrame([
        {"ticker": "A001", "broker_id": "B01"},
        {"ticker": "A002", "broker_id": "B02"},
    ])

    broker_path = tmp_path / "broker_trades.parquet"
    pool_path   = tmp_path / "key_broker_pool.parquet"
    trades.to_parquet(broker_path, index=False)
    pool.to_parquet(pool_path, index=False)
    return broker_path, pool_path
