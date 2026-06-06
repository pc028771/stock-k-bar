"""Parquet disk cache for add_features output.

Cache key: (ticker_set_hash, start_date, end_date, FEATURES_VERSION).
Storage:   ~/.kline_cache/features/<key>.parquet  (snappy-compressed).

Usage
-----
    from kline.cache import load_cached_features, save_cached_features

    df = load_cached_features(tickers, start, end)
    if df is None:
        df = add_features(load_bars(...))
        save_cached_features(df, tickers, start, end)
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pandas as pd

# Bump this string whenever features.py logic changes to invalidate all entries.
FEATURES_VERSION = "v1"

CACHE_DIR = Path.home() / ".kline_cache" / "features"

_log = logging.getLogger(__name__)


def _cache_key(tickers: list[str] | None, start: str | None, end: str | None, version: str) -> str:
    """Return a filename-safe cache key string."""
    if tickers is None:
        tk_hash = "all"
    else:
        tk_hash = hashlib.md5(",".join(sorted(tickers)).encode()).hexdigest()[:12]
    start_s = (start or "none").replace("-", "")
    end_s = (end or "none").replace("-", "")
    return f"{tk_hash}_{start_s}_{end_s}_{version}.parquet"


def _cache_path(tickers: list[str] | None, start: str | None, end: str | None) -> Path:
    return CACHE_DIR / _cache_key(tickers, start, end, FEATURES_VERSION)


def load_cached_features(
    tickers: list[str] | None,
    start: str | None,
    end: str | None,
) -> pd.DataFrame | None:
    """Return cached DataFrame if available, else None.

    Parameters
    ----------
    tickers:
        List of ticker symbols (order-insensitive). None = all tickers.
    start / end:
        Date strings (YYYY-MM-DD). Used only as part of the cache key —
        callers are responsible for filtering rows to the requested range.
    """
    path = _cache_path(tickers, start, end)
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path, engine="pyarrow")
        _log.info("parquet cache HIT: %s", path.name)
        return df
    except Exception as exc:
        _log.warning("parquet cache read failed (%s); cache miss", exc)
        return None


def save_cached_features(
    df: pd.DataFrame,
    tickers: list[str] | None,
    start: str | None,
    end: str | None,
) -> None:
    """Persist *df* to parquet cache.

    Silently skips write on any error (cache is best-effort).
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(tickers, start, end)
    try:
        df.to_parquet(path, engine="pyarrow", compression="snappy")
        _log.info("parquet cache WRITE: %s (%.1f MB)", path.name, path.stat().st_size / 1e6)
    except Exception as exc:
        _log.warning("parquet cache write failed: %s", exc)
