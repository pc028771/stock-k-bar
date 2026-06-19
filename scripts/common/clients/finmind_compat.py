# finmind_compat.py
"""FinMind API legacy compat shim — 從 stock-analysis-system/clients/finmind_client.py
vendor 過來、行為 1:1 對齊以保留既有 NDJSON raw cache 與 ~/.cache/finmind/ disk layout。

⚠️  與 `scripts/common/finmind_client.py` (quota-aware client) 是兩套並行 FinMind
   client、不互相 import。前者 (compat) 給既有 19 個 importer 用、後者給新 code 用。
   未來可考慮整合、但本次脫鉤先保留現狀降低風險。

FinMind API client with NDJSON raw cache, in-memory session cache, and token-bucket rate limiter."""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import date as _date_cls, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests

# Thread-local storage for per-request response time tracking
_tl = threading.local()


def _timed_get(url: str, **kwargs) -> requests.Response:
    """requests.get wrapper that records elapsed time in thread-local storage."""
    t0 = time.monotonic()
    resp = requests.get(url, **kwargs)
    _tl.last_response_ms = (time.monotonic() - t0) * 1000
    return resp


def get_last_response_ms() -> float | None:
    """Return the last HTTP response time (ms) recorded on the current thread."""
    return getattr(_tl, "last_response_ms", None)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_BASE = "https://api.finmindtrade.com/api/v4/data"


# ---------------------------------------------------------------------------
# Tier system
# ---------------------------------------------------------------------------

class FinMindTier(str, Enum):
    FREE    = "free"
    SPONSOR = "sponsor"


def get_tier() -> FinMindTier:
    """Read FINMIND_TIER env var (default: 'free').

    Set FINMIND_TIER=sponsor in .env or shell to unlock Sponsor-only features:
    - bulk multi-stock queries (omit data_id)
    - real-time snapshot API
    - higher rate limit
    """
    val = os.environ.get("FINMIND_TIER", "free").strip().lower()
    return FinMindTier.SPONSOR if val == "sponsor" else FinMindTier.FREE


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

_TOKEN_BUCKET_PARAMS: dict[FinMindTier, tuple[float, float]] = {
    #                      capacity  refill_rate (tokens/sec)
    FinMindTier.FREE:    ( 10,       600  / 3600 * 0.9 ),  # burst 10, ~0.15/s
    FinMindTier.SPONSOR: ( 50,       6000 / 3600 * 0.9 ),  # burst 50, ~0.75/s
}


class _RateLimiter:
    """True token-bucket rate limiter.

    Tokens refill at `refill_rate` tokens/second up to `capacity`.
    acquire() consumes one token; blocks (sleep) if bucket empty.
    Thread-safe. Disk state is best-effort (not cross-process atomic).
    """

    def __init__(self, capacity: float, refill_rate: float) -> None:
        self.capacity    = capacity
        self.refill_rate = refill_rate   # tokens / second
        self._tokens     = capacity      # start full
        self._last       = time.monotonic()
        self._lock       = threading.Lock()
        self._last_save  = 0.0           # wall-clock time of last _save_state()
        self._disabled   = False
        self._cache_dir  = Path(os.environ.get("FINMIND_CACHE_DIR",
                                 Path.home() / ".cache" / "finmind"))
        self._state_file = self._cache_dir / "_rate_state.json"
        self._load_state()

    def disable(self) -> None:
        """Bypass rate limiting — acquire() becomes a no-op. Use for batch CLI jobs."""
        self._disabled = True

    def _load_state(self) -> None:
        if self._state_file.exists():
            try:
                s = json.loads(self._state_file.read_text())
                saved_at = float(s.get("saved_at", 0))
                elapsed = time.time() - saved_at
                if elapsed < 3600:          # discard if > 1 hr old
                    loaded = float(s.get("tokens", self.capacity))
                    # Credit tokens refilled since last save
                    self._tokens = min(loaded + elapsed * self.refill_rate, self.capacity)
                    return
            except Exception:
                pass
        self._tokens = self.capacity

    def _save_state(self) -> None:
        """Persist token count at most once every 10 seconds to reduce I/O."""
        now = time.time()
        if now - self._last_save < 10:
            return
        self._last_save = now
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(json.dumps(
            {"tokens": self._tokens, "saved_at": now}))

    def _refill(self) -> None:
        now = time.monotonic()
        self._tokens = min(self.capacity,
                           self._tokens + (now - self._last) * self.refill_rate)
        self._last = now

    def acquire(self) -> None:
        """Block until a token is available. KeyboardInterrupt propagates from time.sleep."""
        if self._disabled:
            return
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    self._save_state()
                    return
                wait = (1.0 - self._tokens) / self.refill_rate
            time.sleep(wait)   # KeyboardInterrupt propagates naturally here


# Module-level singleton — picks up FINMIND_TIER at import time.
# To switch tier at runtime, set the env var before importing this module.
_limiter = _RateLimiter(*_TOKEN_BUCKET_PARAMS[get_tier()])

# ---------------------------------------------------------------------------
# Session cache  (in-memory, per-process, volatile)
# ---------------------------------------------------------------------------

# key: "{dataset}/{stock_id}" → full historical DataFrame (sorted by date)
_session_cache: dict[str, pd.DataFrame] = {}
# key: "{dataset}/{stock_id}/_today_ts" → float unix timestamp of last today-fetch
_session_today_ts: dict[str, float] = {}
_session_lock = threading.Lock()

# When True, get_data() skips all API fetches and uses only session cache / NDJSON.
# Set this before calling screen() in backtest/learn mode to avoid rate-limiter sleeps
# on symbols with small cache gaps.
_cache_only: bool = False


def set_cache_only(enabled: bool) -> None:
    """Enable or disable cache-only mode (no API fetches). Thread-safe as long as
    it is set before worker threads are spawned."""
    global _cache_only
    _cache_only = enabled


def evict(symbol: str, datasets: list[str] | None = None) -> None:
    """Remove a symbol from session cache to free memory after processing."""
    _DS = datasets or [
        "TaiwanStockPrice",
        "TaiwanStockInstitutionalInvestorsBuySell",
        "TaiwanStockMarginPurchaseShortSale",
    ]
    with _session_lock:
        for ds in _DS:
            _session_cache.pop(f"{ds}/{symbol}", None)
            _session_today_ts.pop(f"{ds}/{symbol}", None)


# ---------------------------------------------------------------------------
# Raw data cache  (append-only, one file per API call / date range)
# ---------------------------------------------------------------------------

def _raw_base() -> Path:
    raw_base_env = os.environ.get("FINMIND_RAW_DIR")
    if raw_base_env:
        return Path(raw_base_env)
    if os.environ.get("FINMIND_CACHE_DIR"):
        return Path(os.environ["FINMIND_CACHE_DIR"]) / "raw"
    return Path("./data/raw")


def _raw_dir(dataset: str, stock_id: str) -> Path:
    return _raw_base() / dataset / stock_id


def _ndjson_path(raw_d: Path, record_date_str: str) -> Path:
    """Return the NDJSON file path for a given record date.

    Current year  → raw_d/YYYY-MM.ndjson  (monthly, append-only per day)
    Past years    → raw_d/YYYY.ndjson     (yearly, stable after year ends)
    """
    year = str(record_date_str)[:4]
    if year == str(_date_cls.today().year):
        return raw_d / f"{str(record_date_str)[:7]}.ndjson"
    return raw_d / f"{year}.ndjson"


def _save_raw(dataset: str, stock_id: str,
              start: str, end: str, payload: dict) -> None:
    """Append raw API records to monthly/yearly NDJSON files.

    Current year → YYYY-MM.ndjson; past years → YYYY.ndjson.
    Each line is a single JSON record (no status/msg wrapper).
    Normally append-only; rewrites sorted when backfill rows predate the
    existing file's first line (keeps _ndjson_available_range accurate).
    """
    raw_d = _raw_dir(dataset, stock_id)
    raw_d.mkdir(parents=True, exist_ok=True)

    rows = payload.get("data", [])
    if not rows:
        return

    buckets: dict[Path, list] = {}
    for row in rows:
        path = _ndjson_path(raw_d, str(row.get("date", ""))[:10])
        if path not in buckets:
            buckets[path] = []
        buckets[path].append(row)

    for path, path_rows in buckets.items():
        if path.exists():
            # Check if any new row predates the existing file's first line.
            # This happens during backfill (e.g. --start 2024-01-01 on a cache
            # built with the default 2-years-ago start).  Appending out-of-order
            # rows would leave the first line stale and cause _ndjson_available_range
            # to keep reporting the old (later) min_date → infinite re-fetch loop.
            existing_first_date: str | None = None
            try:
                with path.open(encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            existing_first_date = str(json.loads(line).get("date", ""))[:10]
                            break
            except Exception:
                pass

            new_min_date = min(str(r.get("date", ""))[:10] for r in path_rows)
            if existing_first_date and new_min_date <= existing_first_date:
                # Backfill case: rewrite the file with merged, sorted, deduped rows.
                existing_rows: list[dict] = []
                try:
                    with path.open(encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    existing_rows.append(json.loads(line))
                                except json.JSONDecodeError:
                                    pass
                except Exception:
                    pass
                all_rows = existing_rows + path_rows
                seen: set[str] = set()
                sorted_rows: list[dict] = []
                for r in sorted(all_rows, key=lambda r: str(r.get("date", ""))[:10]):
                    key = json.dumps(r, ensure_ascii=False, default=str, sort_keys=True)
                    if key not in seen:
                        seen.add(key)
                        sorted_rows.append(r)
                with path.open("w", encoding="utf-8") as f:
                    for r in sorted_rows:
                        f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
                continue

        with path.open("a", encoding="utf-8") as f:
            for row in path_rows:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _ndjson_available_range(dataset: str, stock_id: str) -> tuple[str, str] | None:
    """Return (min_date, max_date) available in NDJSON files, without reading all content.

    Both min_date and max_date are read from actual record data:
    - min_date: first line of earliest file
    - max_date: last line of latest file
    Returns None if no NDJSON files exist or files are empty.

    Special case: if the directory exists but has no NDJSON files (API returned empty
    data on a previous attempt), return (today, today) if the directory was touched
    within the last 24 hours — so callers treat this symbol as already checked today.
    """
    import time as _time
    raw_d = _raw_dir(dataset, stock_id)
    if not raw_d.exists():
        return None
    files = sorted(raw_d.glob("*.ndjson"))
    if not files:
        if (_time.time() - raw_d.stat().st_mtime) < 7 * 86400:  # tried within 7 days
            today = _date_cls.today().isoformat()
            # Use "0000-01-01" as start so ndjson_start <= any requested start_date
            return ("0000-01-01", today)
        return None

    # min_date from first line of earliest file
    min_date: str | None = None
    try:
        with files[0].open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    min_date = str(json.loads(line).get("date", ""))[:10]
                    break
    except Exception:
        pass
    if not min_date:
        return None

    # max_date from last line of latest file
    max_date: str | None = None
    try:
        with files[-1].open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            buf_size = min(size, 1024)
            f.seek(size - buf_size)
            buf = f.read()
        last_line = buf.rstrip(b"\n").rsplit(b"\n", 1)[-1].decode("utf-8", errors="ignore").strip()
        if last_line:
            max_date = str(json.loads(last_line).get("date", ""))[:10]
    except Exception:
        pass
    if not max_date:
        return None

    # Check for ".checked_start" sentinel written by prefetch after an empty
    # backfill (e.g. stock IPO'd after the requested start date).  The file
    # stores the start_date that was checked; use it as effective min_date so
    # _cache_status returns "done" and stops re-triggering the same backfill.
    checked_file = raw_d / ".checked_start"
    if checked_file.exists():
        try:
            marked = checked_file.read_text().strip()
            if marked and (min_date is None or marked < min_date):
                min_date = marked
        except Exception:
            pass

    return (min_date, max_date)


def _load_all_ndjson(dataset: str, stock_id: str) -> pd.DataFrame | None:
    """Load all NDJSON slices for a symbol into a single sorted DataFrame.

    Returns None when no raw data is available.
    """
    all_rows: list[dict] = []
    raw_d = _raw_dir(dataset, stock_id)
    if raw_d.exists():
        for f in sorted(raw_d.glob("*.ndjson")):
            with f.open(encoding="utf-8") as fp:
                for line in fp:
                    line = line.strip()
                    if line:
                        try:
                            all_rows.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
    if not all_rows:
        return None
    df = pd.DataFrame(all_rows)
    df["date"] = pd.to_datetime(df["date"], format="mixed")
    return df.drop_duplicates().sort_values("date").reset_index(drop=True)

# ---------------------------------------------------------------------------
# Core data-fetch function
# ---------------------------------------------------------------------------

def get_data(
    dataset: str,
    stock_id: str,
    start_date: str,
    end_date: str,
    token: str,
) -> pd.DataFrame:
    """Fetch dataset for a symbol, using NDJSON + in-memory session cache.

    Storage hierarchy (no parquet, no meta.json):
      1. session cache  — in-memory DataFrame for current process lifetime
      2. NDJSON files   — persistent raw data in data/raw/
      3. FinMind API    — fetched only for missing date ranges
    """
    cache_key = f"{dataset}/{stock_id}"
    today_str = _date_cls.today().isoformat()
    yesterday = (_date_cls.today() - timedelta(days=1)).isoformat()
    hist_end  = min(end_date, yesterday)

    def _api_fetch(s: str, e: str) -> list[dict]:
        if s > e:
            return []
        _limiter.acquire()
        p: dict[str, Any] = {
            "dataset": dataset, "data_id": stock_id,
            "start_date": s, "end_date": e, "token": token,
        }
        r = _timed_get(API_BASE, params=p, timeout=30)
        if r.status_code == 402:
            raise RuntimeError("FinMind API 配額已用完")
        r.raise_for_status()
        pl = r.json()
        _save_raw(dataset, stock_id, s, e, pl)
        return pl.get("data", [])

    def _merge(base: pd.DataFrame | None, new_rows: list[dict]) -> pd.DataFrame:
        new_df = pd.DataFrame(new_rows)
        new_df["date"] = pd.to_datetime(new_df["date"])
        combined = pd.concat([base, new_df] if base is not None and not base.empty
                              else [new_df], ignore_index=True)
        return combined.drop_duplicates().sort_values("date").reset_index(drop=True)

    # ── 1. Load from session cache or NDJSON ──────────────────────────────
    with _session_lock:
        df = _session_cache.get(cache_key)

    if df is None and _ndjson_available_range(dataset, stock_id) is not None:
        df = _load_all_ndjson(dataset, stock_id)
        if df is not None:
            with _session_lock:
                _session_cache[cache_key] = df

    # ── 2. Fetch missing historical ranges ────────────────────────────────
    df_min = str(df["date"].min())[:10] if df is not None and not df.empty else None
    df_max = str(df["date"].max())[:10] if df is not None and not df.empty else None

    fetch_ranges: list[tuple[str, str]] = []
    if df_min is None:
        if start_date <= hist_end:
            fetch_ranges.append((start_date, hist_end))
    else:
        if start_date < df_min:
            bf_end = min(
                (_date_cls.fromisoformat(df_min) - timedelta(days=1)).isoformat(),
                hist_end,
            )
            if start_date <= bf_end:
                fetch_ranges.append((start_date, bf_end))
        if df_max is not None and df_max < hist_end:
            fetch_ranges.append((
                (_date_cls.fromisoformat(df_max) + timedelta(days=1)).isoformat(),
                hist_end,
            ))

    if not _cache_only:
        for s, e in fetch_ranges:
            rows = _api_fetch(s, e)
            if rows:
                df = _merge(df, rows)
                with _session_lock:
                    _session_cache[cache_key] = df

    # ── 3. Today's data (60-min TTL, session-scoped) ──────────────────────
    # Errors here (API not yet settled, 400 while market is open, network blip)
    # must NOT propagate — the screener catches exceptions and returns None for
    # the whole stock, silently producing 0 candidates for every symbol.
    if not _cache_only and end_date >= today_str:
        now_ts = time.time()
        with _session_lock:
            last_ts = _session_today_ts.get(cache_key, 0.0)
        if now_ts - last_ts > 3600:
            try:
                rows = _api_fetch(today_str, today_str)
            except Exception:
                rows = []
            if rows:
                df = _merge(df, rows)
                with _session_lock:
                    _session_cache[cache_key] = df
                    _session_today_ts[cache_key] = now_ts

    if df is None or df.empty:
        return pd.DataFrame()

    mask = (df["date"].astype(str) >= start_date) & (df["date"].astype(str) <= end_date)
    return df[mask].reset_index(drop=True)

# ---------------------------------------------------------------------------
# Prefetch — fetch & save without loading a full DataFrame
# ---------------------------------------------------------------------------

def prefetch(
    dataset: str,
    stock_id: str,
    start_date: str,
    end_date: str,
    token: str,
) -> float | None:
    """Fetch and persist missing data ranges without building a DataFrame.

    Faster than get_data() for the fetch CLI: uses _ndjson_available_range()
    (filename + tail read) for gap detection, skips the full _load_all_ndjson()
    call entirely when the returned DataFrame is not needed.

    Returns the last API response time in ms, or None if already fully cached.
    """
    today_str = _date_cls.today().isoformat()
    yesterday = (_date_cls.today() - timedelta(days=1)).isoformat()
    hist_end = min(end_date, yesterday)
    last_ms: float | None = None

    def _do_fetch(s: str, e: str) -> None:
        nonlocal last_ms
        if s > e:
            return
        _limiter.acquire()
        r = _timed_get(API_BASE, params={
            "dataset": dataset, "data_id": stock_id,
            "start_date": s, "end_date": e, "token": token,
        }, timeout=30)
        if r.status_code == 402:
            raise RuntimeError("FinMind API 配額已用完")
        r.raise_for_status()
        _save_raw(dataset, stock_id, s, e, r.json())
        last_ms = get_last_response_ms()

    # Gap detection via fast filename+tail check (no full NDJSON load)
    # Grace periods:
    #   start: up to 7 days — handles holidays/weekends at the requested start date
    #   end:   up to 5 days — handles data provider lag (institutional data lags 1-3 days)
    _start_grace = (_date_cls.fromisoformat(start_date) + timedelta(days=7)).isoformat()
    _end_grace   = (_date_cls.fromisoformat(hist_end)   - timedelta(days=5)).isoformat()

    avail = _ndjson_available_range(dataset, stock_id)
    if avail is None:
        if start_date <= hist_end:
            _do_fetch(start_date, hist_end)
    else:
        ndjson_start, ndjson_end = avail
        # Backfill: only if the gap is larger than the start grace window
        if start_date < ndjson_start and ndjson_start > _start_grace:
            bf_end = min(
                (_date_cls.fromisoformat(ndjson_start) - timedelta(days=1)).isoformat(),
                hist_end,
            )
            if start_date <= bf_end:
                _do_fetch(start_date, bf_end)
            # If the backfill produced no new data (e.g. stock IPO'd after
            # start_date), write a sentinel so future runs skip this attempt
            # instead of looping forever.
            post_avail = _ndjson_available_range(dataset, stock_id)
            post_start = post_avail[0] if post_avail else ndjson_start
            if post_start >= ndjson_start:
                checked_file = _raw_dir(dataset, stock_id) / ".checked_start"
                checked_file.write_text(start_date)
        # Forward fill: only if genuinely beyond the end grace window.
        # If the API returned 0 rows last time (data gap), a sentinel file
        # .checked_fwd records hist_end so we skip the retry until the grace
        # window advances again (i.e. the stock has a new trading day to fill).
        if ndjson_end < _end_grace:
            _checked_fwd = _raw_dir(dataset, stock_id) / ".checked_fwd"
            _skip_fwd = (
                _checked_fwd.exists()
                and _checked_fwd.read_text(encoding="utf-8").strip() >= _end_grace
            )
            if not _skip_fwd:
                _range_before = _ndjson_available_range(dataset, stock_id)
                _do_fetch(
                    (_date_cls.fromisoformat(ndjson_end) + timedelta(days=1)).isoformat(),
                    hist_end,
                )
                _range_after = _ndjson_available_range(dataset, stock_id)
                # If no new rows were written, record sentinel to avoid daily retries
                if _range_before == _range_after:
                    _checked_fwd.write_text(hist_end, encoding="utf-8")

    # Today's data (60-min TTL, session-scoped)
    if end_date >= today_str:
        cache_key = f"{dataset}/{stock_id}"
        now_ts = time.time()
        with _session_lock:
            last_ts = _session_today_ts.get(cache_key, 0.0)
        if now_ts - last_ts > 3600:
            _do_fetch(today_str, today_str)
            if last_ms is not None:
                with _session_lock:
                    _session_today_ts[cache_key] = now_ts

    return last_ms


# ---------------------------------------------------------------------------
# Public convenience functions
# ---------------------------------------------------------------------------

def get_price(
    stock_id: str,
    start_date: str,
    end_date: str,
    token: str,
) -> pd.DataFrame:
    """Return OHLCV price DataFrame; renames max→high, min→low."""
    df = get_data("TaiwanStockPrice", stock_id, start_date, end_date, token)
    rename_map = {}
    if "max" in df.columns:
        rename_map["max"] = "high"
    if "min" in df.columns:
        rename_map["min"] = "low"
    if rename_map:
        df = df.rename(columns=rename_map)
    return df


def get_institutional(
    stock_id: str,
    start_date: str,
    end_date: str | None = None,
    token: str = "",
) -> pd.DataFrame:
    """Return institutional investors buy/sell DataFrame."""
    _INSTITUTIONAL_COLS = ["date", "name", "buy", "sell"]
    if end_date is None:
        end_date = _date_cls.today().isoformat()
    df = get_data(
        "TaiwanStockInstitutionalInvestorsBuySell",
        stock_id,
        start_date,
        end_date,
        token,
    )
    if df.empty:
        return pd.DataFrame(columns=_INSTITUTIONAL_COLS)
    for col in _INSTITUTIONAL_COLS:
        if col not in df.columns:
            df[col] = None
    for col in ["buy", "sell"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    # Normalize English names (newer FinMind format) → Traditional Chinese names
    # Foreign_Investor / Foreign_Dealer_Self → 外資
    # Investment_Trust → 投信
    # Dealer_self / Dealer_Hedging → 自營商
    _NAME_MAP = {
        "Foreign_Investor":   "外資",
        "Foreign_Dealer_Self": "外資",
        "Investment_Trust":   "投信",
        "Dealer_self":        "自營商",
        "Dealer_Hedging":     "自營商",
    }
    df["name"] = df["name"].map(_NAME_MAP).fillna(df["name"])
    return df


def get_margin(
    stock_id: str,
    start_date: str,
    end_date: str | None = None,
    token: str = "",
) -> pd.DataFrame:
    """Return margin purchase / short sale DataFrame."""
    _MARGIN_COLS = ["date", "BalanceOfMarginPurchase", "BalanceOfShortSale"]
    if end_date is None:
        end_date = _date_cls.today().isoformat()
    df = get_data(
        "TaiwanStockMarginPurchaseShortSale",
        stock_id,
        start_date,
        end_date,
        token,
    )
    if df.empty:
        return pd.DataFrame(columns=_MARGIN_COLS)
    for col in _MARGIN_COLS:
        if col not in df.columns:
            df[col] = None
    for col in ["BalanceOfMarginPurchase", "BalanceOfShortSale"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


import re as _re

_ORDINARY_PATTERN = _re.compile(r'^[1-9]\d{3}$')


def filter_ordinary_stocks(symbols: list[str]) -> list[str]:
    """Keep only ordinary Taiwan stocks: pure 4-digit codes (1000–9999).

    Excludes:
    - ETFs: 00xx (start with 0)
    - Warrants: 4-digit code + letter suffix (e.g. 2330C, 6505P)
    - Futures/bonds: 01xx/02xx
    - Longer codes (TDRs, preferred shares, etc.)
    """
    return [s for s in symbols if _ORDINARY_PATTERN.match(s)]


def ndjson_recent_avg_volume(dataset: str, stock_id: str, days: int = 22) -> float | None:
    """Return avg daily Trading_Volume (shares) from the most recent `days` records.

    Reads backward from the latest NDJSON files without loading all data.
    Returns None if fewer than half of `days` records are available.
    """
    raw_d = _raw_dir(dataset, stock_id)
    if not raw_d.exists():
        return None
    files = sorted(raw_d.glob("*.ndjson"))
    if not files:
        return None

    volumes: list[float] = []
    for f in reversed(files):
        if len(volumes) >= days:
            break
        try:
            lines = f.read_text(encoding="utf-8").strip().split("\n")
            for line in reversed(lines):
                if len(volumes) >= days:
                    break
                line = line.strip()
                if line:
                    vol = json.loads(line).get("Trading_Volume")
                    if vol is not None:
                        volumes.append(float(vol))
        except Exception:
            continue

    if len(volumes) < days // 2:
        return None
    return sum(volumes) / len(volumes)


def get_stock_list(token: str) -> list[str]:
    """Return list of Taiwan stock IDs from TaiwanStockInfo (Free tier supported).

    Results are cached for 24 hours to avoid redundant API calls.
    """
    cache_dir = Path(os.environ.get("FINMIND_CACHE_DIR",
                                    Path.home() / ".cache" / "finmind"))
    cache_file = cache_dir / "_stock_list.json"

    if cache_file.exists():
        try:
            payload = json.loads(cache_file.read_text())
            cached_date = payload.get("date", "")
            if cached_date == _date_cls.today().isoformat():
                return payload["symbols"]
        except (json.JSONDecodeError, KeyError):
            pass

    _limiter.acquire()
    resp = _timed_get(
        API_BASE,
        params={"dataset": "TaiwanStockInfo", "token": token},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json().get("data", [])
    # TaiwanStockInfo has duplicate stock_ids (one row per industry classification).
    # Use dict.fromkeys to deduplicate while preserving order.
    symbols = list(dict.fromkeys(row["stock_id"] for row in data if row.get("stock_id")))
    names   = {row["stock_id"]: row.get("stock_name", row["stock_id"])
               for row in data if row.get("stock_id")}

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({
        "date": _date_cls.today().isoformat(),
        "symbols": symbols,
        "names": names,
    }))
    return symbols


def get_stock_name(stock_id: str, token: str) -> str | None:
    """Return the Chinese company name for a stock ID, e.g. '台積電' for '2330'.

    Reuses the TaiwanStockInfo cache written by get_stock_list.
    Returns None if not found.
    """
    cache_dir = Path(os.environ.get("FINMIND_CACHE_DIR",
                                    Path.home() / ".cache" / "finmind"))
    cache_file = cache_dir / "_stock_list.json"

    names: dict[str, str] = {}
    if cache_file.exists():
        try:
            payload = json.loads(cache_file.read_text())
            if payload.get("date") == _date_cls.today().isoformat():
                names = payload.get("names", {})
                if names:
                    return names.get(stock_id)
        except (json.JSONDecodeError, KeyError):
            pass

    # Cache miss or stale — fetch from API (also refreshes get_stock_list cache)
    _limiter.acquire()
    resp = _timed_get(
        API_BASE,
        params={"dataset": "TaiwanStockInfo", "token": token},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json().get("data", [])
    names = {row["stock_id"]: row.get("stock_name", row["stock_id"])
             for row in data if row.get("stock_id")}
    symbols = list(names.keys())

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({
        "date": _date_cls.today().isoformat(),
        "symbols": symbols,
        "names": names,
    }))
    return names.get(stock_id)


def get_bulk_institutional(date_str: str, token: str) -> pd.DataFrame:
    """Fetch all stocks' institutional data for a single date (Sponsor tier).

    Returns DataFrame with columns [date, stock_id, name, buy, sell].
    Returns empty DataFrame on API error.
    """
    df = get_market_data("TaiwanStockInstitutionalInvestorsBuySell", date_str, token)
    if df.empty:
        return pd.DataFrame()
    for col in ["buy", "sell"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    _NAME_MAP = {
        "Foreign_Investor":    "外資",
        "Foreign_Dealer_Self": "外資",
        "Investment_Trust":    "投信",
        "Dealer_self":         "自營商",
        "Dealer_Hedging":      "自營商",
    }
    if "name" in df.columns:
        df["name"] = df["name"].map(_NAME_MAP).fillna(df["name"])
    return df


def get_realtime_snapshot(stock_id: str, token: str) -> dict | None:
    """Real-time stock price snapshot via taiwan_stock_tick_snapshot (Sponsor tier).

    Returns a dict with keys such as open, high, low, close, volume, change_rate,
    buy_price, sell_price, etc. Returns None when unavailable.

    Usage:
        snap = get_realtime_snapshot("2330", token)
        if snap:
            print(snap["close"], snap["change_rate"])
    """
    _limiter.acquire()
    try:
        resp = _timed_get(
            "https://api.finmindtrade.com/api/v4/taiwan_stock_tick_snapshot",
            params={"data_id": stock_id, "token": token},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        data = resp.json().get("data", [])
        return data[0] if data else None
    except Exception:
        return None


def get_market_data(dataset: str, date_str: str, token: str) -> pd.DataFrame:
    """Fetch full-market single-day data (Sponsor tier: omit data_id).

    If the API returns 402 or empty data (Free tier does not support bulk fetch),
    returns an empty DataFrame — caller should fall back to per-symbol mode.
    """
    if _cache_only:
        return pd.DataFrame()
    _limiter.acquire()
    try:
        resp = _timed_get(
            API_BASE,
            params={"dataset": dataset, "start_date": date_str,
                    "end_date": date_str, "token": token},
            timeout=30,
        )
        if resp.status_code == 402:
            return pd.DataFrame()
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


def fetch_stock_info(token: str) -> pd.DataFrame:
    """Return full TaiwanStockInfo DataFrame with industry_category (Free tier).

    Columns: stock_id, stock_name, industry_category, type.
    Results are cached as JSON for 7 days (industry classification rarely changes).
    """
    cache_dir = Path(os.environ.get("FINMIND_CACHE_DIR",
                                    Path.home() / ".cache" / "finmind"))
    cache_file = cache_dir / "_stock_info.json"

    # Check 7-day TTL via file mtime
    if cache_file.exists():
        if time.time() - cache_file.stat().st_mtime < 7 * 24 * 3600:
            return pd.DataFrame(json.loads(cache_file.read_text(encoding="utf-8")))

    _limiter.acquire()
    resp = _timed_get(
        API_BASE,
        params={"dataset": "TaiwanStockInfo", "token": token},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json().get("data", [])
    if not data:
        return pd.DataFrame(columns=["stock_id", "stock_name", "industry_category", "type"])

    df = pd.DataFrame(data)
    # Ensure required columns exist
    for required in ["stock_id", "stock_name", "industry_category", "type"]:
        if required not in df.columns:
            df[required] = None

    df = df[["stock_id", "stock_name", "industry_category", "type"]].copy()
    df = df.dropna(subset=["stock_id"]).reset_index(drop=True)

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(df.to_json(orient="records", force_ascii=False), encoding="utf-8")

    return df


def fetch_kbar(stock_id: str, date: str, token: str) -> pd.DataFrame:
    """Sponsor tier: fetch 1-minute K-bar data for a single stock on a single date.

    Dataset: TaiwanStockKBar (Sponsor tier only).
    Returns DataFrame with columns: minute, open, high, low, close, volume.
    Results are cached as JSON per stock per date (immutable for past dates).

    Raises:
        PermissionError: If FINMIND_TIER is not 'sponsor'.
    """
    cache_dir = Path(os.environ.get("FINMIND_CACHE_DIR",
                                    Path.home() / ".cache" / "finmind"))
    cache_file = cache_dir / "kbar" / stock_id / f"{date}.json"

    if cache_file.exists():
        return pd.DataFrame(json.loads(cache_file.read_text(encoding="utf-8")))

    _limiter.acquire()
    resp = _timed_get(
        API_BASE,
        params={
            "dataset": "TaiwanStockKBar",
            "data_id": stock_id,
            "start_date": date,
            "token": token,
        },
        timeout=30,
    )
    if resp.status_code == 402:
        raise RuntimeError("FinMind API 配額已用完")
    resp.raise_for_status()

    data = resp.json().get("data", [])
    _KBAR_COLS = ["minute", "open", "high", "low", "close", "volume"]
    if not data:
        return pd.DataFrame(columns=_KBAR_COLS)

    df = pd.DataFrame(data)
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Keep only the target date rows and required columns
    if "date" in df.columns:
        df = df[df["date"].astype(str).str.startswith(date)].copy()
    if "minute" not in df.columns and "date" in df.columns:
        # FinMind may encode time in the date column as "YYYY-MM-DD HH:MM:SS"
        df["minute"] = df["date"].astype(str).str[11:16]

    for col in _KBAR_COLS:
        if col not in df.columns:
            df[col] = None

    df = df[_KBAR_COLS].reset_index(drop=True)

    # Cache for past dates (past data is immutable)
    today_str = _date_cls.today().isoformat()
    if date < today_str:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(df.to_json(orient="records", force_ascii=False), encoding="utf-8")

    return df


def _estimate_kbar_download(
    stock_id: str,
    from_date: str,
    to_date: str,
) -> tuple[int, int, int]:
    """Estimate KBar download cost for a date range.

    Returns (need_download, cached_days, total_est_rows).
    Assumes ~270 bars per trading day (9:00–13:30).
    Weekends are skipped; public holidays are not accounted for.
    """
    cache_dir = Path(os.environ.get("FINMIND_CACHE_DIR", Path.home() / ".cache" / "finmind"))
    from_d = _date_cls.fromisoformat(from_date)
    to_d   = _date_cls.fromisoformat(to_date)

    trading_days: list[str] = []
    d = from_d
    while d <= to_d:
        if d.weekday() < 5:
            trading_days.append(d.isoformat())
        d += timedelta(days=1)

    cached = sum(
        1 for dt in trading_days
        if (cache_dir / "kbar" / stock_id / f"{dt}.json").exists()
    )
    need_download = len(trading_days) - cached
    total_est_rows = len(trading_days) * 270
    return need_download, cached, total_est_rows


def fetch_kbar_range(
    stock_id: str,
    from_date: str,
    to_date: str,
    token: str,
    resample: str | None = None,
    confirm: bool = True,
) -> pd.DataFrame:
    """Sponsor tier: fetch 1-minute KBar data for a date range.

    Loops over each weekday and calls fetch_kbar() (which caches per date).
    Prompts for confirmation before downloading uncached dates.

    Args:
        resample: pandas resample rule, e.g. '5min', '60min'. None = 1-minute.
        confirm: if True (default), prompt user before downloading missing dates.

    Returns DataFrame with columns: datetime, open, high, low, close, volume.
    datetime is a pandas Timestamp in Taiwan market time.
    """
    need_dl, cached, est_rows = _estimate_kbar_download(stock_id, from_date, to_date)
    total_days = need_dl + cached

    if confirm and need_dl > 0:
        print(f"\n準備下載 KBar 資料（Sponsor）：")
        print(f"  股票：{stock_id}  期間：{from_date} ~ {to_date}（約 {total_days} 個交易日）")
        print(f"  已快取：{cached} 天，需下載：{need_dl} 天")
        print(f"  預計：{need_dl} 次 API 呼叫，約 {est_rows:,} 筆 1分K 資料")
        ans = input("確認下載？[y/N] ").strip().lower()
        if ans != "y":
            return pd.DataFrame()

    from_d = _date_cls.fromisoformat(from_date)
    to_d   = _date_cls.fromisoformat(to_date)
    frames: list[pd.DataFrame] = []
    d = from_d
    while d <= to_d:
        if d.weekday() < 5:
            try:
                df = fetch_kbar(stock_id, d.isoformat(), token)
                if not df.empty:
                    df = df.copy()
                    df["_date"] = d.isoformat()
                    frames.append(df)
            except Exception:
                pass
        d += timedelta(days=1)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined["datetime"] = pd.to_datetime(
        combined["_date"].astype(str) + " " + combined["minute"].astype(str)
    )
    combined = combined.sort_values("datetime").reset_index(drop=True)
    combined = combined[["datetime", "open", "high", "low", "close", "volume"]]

    if resample:
        combined = (
            combined.set_index("datetime")[["open", "high", "low", "close", "volume"]]
            .resample(resample)
            .agg({"open": "first", "high": "max", "low": "min",
                  "close": "last", "volume": "sum"})
            .dropna(subset=["close"])
            .reset_index()
        )

    return combined


def fetch_delta_batch(
    dataset: str,
    symbols: set[str],
    hist_end: str,
    default_start: str,
    token: str,
    on_date: "Callable[[str, str, bool, float | None], None]",
) -> None:
    """Sponsor tier: fetch missing days for all symbols via date-by-date bulk API.

    Cheaper than per-symbol when delta_days < len(symbols):
      batch API calls = delta_days   (vs per-symbol = len(symbols))

    Saves raw NDJSON per symbol and updates the in-memory session cache.

    on_date(date_str, dataset_short, ok) — called after each bulk API call.
    """
    from datetime import date as _date, timedelta as _td

    _DS_SHORT = {
        "TaiwanStockPrice":                          "price",
        "TaiwanStockInstitutionalInvestorsBuySell":  "institutional",
        "TaiwanStockMarginPurchaseShortSale":        "margin",
    }
    ds_short = _DS_SHORT.get(dataset, dataset)

    # Per-symbol start dates using NDJSON availability.
    sym_starts: dict[str, str] = {}
    for sym in symbols:
        avail = _ndjson_available_range(dataset, sym)
        if avail:
            ndjson_start, ndjson_end = avail
            if ndjson_start > default_start:
                sym_starts[sym] = default_start  # backfill needed
            else:
                sym_starts[sym] = (_date.fromisoformat(ndjson_end) + _td(days=1)).isoformat()
        else:
            sym_starts[sym] = default_start
    if not sym_starts:
        return
    batch_start = min(sym_starts.values())

    # Accumulate genuinely-new rows per symbol
    accumulated: dict[str, list[dict]] = {sym: [] for sym in symbols}

    cur = _date.fromisoformat(batch_start)
    end_dt = _date.fromisoformat(hist_end)

    while cur <= end_dt:
        date_str = cur.isoformat()
        df_all = get_market_data(dataset, date_str, token)
        ok = not df_all.empty

        if ok and "stock_id" in df_all.columns:
            for sym in symbols:
                if date_str < sym_starts[sym]:
                    continue
                sym_rows = df_all[df_all["stock_id"] == sym]
                if not sym_rows.empty:
                    rows = sym_rows.to_dict("records")
                    accumulated[sym].extend(rows)
                    _save_raw(dataset, sym, date_str, date_str, {"data": rows})

        on_date(date_str, ds_short, ok, get_last_response_ms())
        cur += _td(days=1)

    # Update session cache for affected symbols.
    # For symbols that got 0 new rows, write .checked_fwd sentinel to prevent
    # daily retries on stocks with persistent FinMind data gaps.
    for sym, new_rows in accumulated.items():
        if not new_rows:
            _fwd = _raw_dir(dataset, sym) / ".checked_fwd"
            _fwd.write_text(hist_end, encoding="utf-8")
            continue
        cache_key = f"{dataset}/{sym}"
        new_df = pd.DataFrame(new_rows)
        new_df["date"] = pd.to_datetime(new_df["date"])
        with _session_lock:
            existing = _session_cache.get(cache_key)
        if existing is not None and not existing.empty:
            combined = pd.concat([existing, new_df], ignore_index=True)
            combined = combined.drop_duplicates().sort_values("date").reset_index(drop=True)
        else:
            combined = new_df.sort_values("date").reset_index(drop=True)
        with _session_lock:
            _session_cache[cache_key] = combined


# ---------------------------------------------------------------------------
# MarketDataClient implementation
# ---------------------------------------------------------------------------

from common.clients.base import SnapshotDict  # noqa: E402


class FinMindClient:
    """Wraps module-level finmind_client functions as a market-data client.

    Note: 不繼承 ABC。stock-k-bar 沒有任何 isinstance 檢查、duck typing 足夠。
    """

    def __init__(self, token: str) -> None:
        self.token = token

    def get_price(self, stock_id: str, start_date: str, end_date: str) -> pd.DataFrame:
        return get_price(stock_id, start_date, end_date, token=self.token)

    def get_realtime_snapshot(self, stock_id: str) -> SnapshotDict | None:
        # FinMind snapshot keys already match SnapshotDict — no remapping needed
        return get_realtime_snapshot(stock_id, self.token)  # type: ignore[return-value]

    def load_kbar(self, stock_id: str, days: int = 14) -> pd.DataFrame | None:
        """Read from ~/.cache/finmind/kbar/{stock_id}/{date}.json (no API calls)."""
        import json
        from datetime import date as _date, timedelta
        from pathlib import Path

        if get_tier() != FinMindTier.SPONSOR:
            return None

        cache_root = Path(os.environ.get(
            "FINMIND_CACHE_DIR", Path.home() / ".cache" / "finmind"
        )) / "kbar"
        today = _date.today()

        frames: list[pd.DataFrame] = []
        for i in range(1, days + 1):          # skip today (index 0)
            d = today - timedelta(days=i)
            if d.weekday() >= 5:              # skip weekends
                continue
            cache_file = cache_root / stock_id / f"{d.isoformat()}.json"
            if not cache_file.exists():
                continue
            try:
                raw = json.loads(cache_file.read_text(encoding="utf-8"))
                df = pd.DataFrame(raw)
                if df.empty or "minute" not in df.columns:
                    continue
                df["datetime"] = pd.to_datetime(
                    d.isoformat() + " " + df["minute"].astype(str)
                )
                frames.append(df[["datetime", "open", "high", "low", "close", "volume"]])
            except Exception:
                continue

        if not frames:
            return None
        return (
            pd.concat(frames, ignore_index=True)
            .sort_values("datetime")
            .reset_index(drop=True)
        )
