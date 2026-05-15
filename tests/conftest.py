"""Shared test fixtures for kline conditions."""
from __future__ import annotations

import pandas as pd


def make_bars(rows: list[dict], ticker: str = "T0001") -> pd.DataFrame:
    """Build a minimal bar DataFrame from row dicts.

    Each row dict supplies columns; missing optional columns are filled
    with sensible defaults so condition functions can be tested in isolation.

    Required keys per row: open, high, low, close.
    Optional: volume (default 1000), ma60 (default close), trade_date.
    """
    df = pd.DataFrame(rows)
    n = len(df)
    if "ticker" not in df:
        df["ticker"] = ticker
    if "trade_date" not in df:
        df["trade_date"] = pd.date_range("2025-01-02", periods=n, freq="B")
    if "volume" not in df:
        df["volume"] = 1000.0
    if "ma60" not in df:
        df["ma60"] = df["close"].astype(float)
    if "ma20" not in df:
        df["ma20"] = df["close"].astype(float)
    if "ma240" not in df:
        df["ma240"] = df["close"].astype(float)
    if "is_usable" not in df:
        df["is_usable"] = 1
    for col in ("open", "high", "low", "close", "volume", "ma60", "ma20", "ma240"):
        df[col] = df[col].astype(float)
    return df.reset_index(drop=True)
