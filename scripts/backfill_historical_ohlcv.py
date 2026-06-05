"""Backfill historical OHLCV data for NO_OHLCV cases in CASE_INDEX.csv.

Uses FinMind client (throttled, sponsor tier) to fetch pre-2022 data for tickers
that appear in course case examples but are missing from ~/.four_seasons/data.sqlite.

Output: data/analysis/kline_patterns/historical_backfill.sqlite
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# --- Path setup ---
WORKTREE = Path("/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power")
# Prefer v4 (Sonnet vision re-extracted dates); fall back to v2/v1 if absent.
_CASE_V4 = WORKTREE / "docs/kline_course/long_short_turning_point/CASE_INDEX_v4.csv"
_CASE_V2 = WORKTREE / "docs/kline_course/long_short_turning_point/CASE_INDEX_v2.csv"
_CASE_V1 = WORKTREE / "docs/kline_course/long_short_turning_point/CASE_INDEX.csv"
CASE_CSV = _CASE_V4 if _CASE_V4.exists() else (_CASE_V2 if _CASE_V2.exists() else _CASE_V1)
OUT_DB = WORKTREE / "data/analysis/kline_patterns/historical_backfill.sqlite"

# Add stock-analysis-system to path so we can import the throttled client
SAS_PATH = Path("/Users/howard/Repository/stock-analysis-system")
if str(SAS_PATH) not in sys.path:
    sys.path.insert(0, str(SAS_PATH))

# Load env token
TOKEN = os.environ.get("FINMIND_API_TOKEN", "")
if not TOKEN:
    # Try loading from .env
    env_file = WORKTREE / ".env"
    if not env_file.exists():
        env_file = SAS_PATH / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("FINMIND_API_TOKEN="):
                TOKEN = line.split("=", 1)[1].strip()
                os.environ["FINMIND_API_TOKEN"] = TOKEN
            if line.startswith("FINMIND_TIER="):
                os.environ["FINMIND_TIER"] = line.split("=", 1)[1].strip()

print(f"Token: {'set (' + TOKEN[:20] + '...)' if TOKEN else 'MISSING'}")
print(f"Tier: {os.environ.get('FINMIND_TIER', 'free')}")

from clients.finmind_client import get_price  # noqa: E402 — must be after env setup


# --- Step 1: Extract ticker ranges from NO_OHLCV cases ---

def get_ticker_ranges() -> dict[str, tuple[str, str]]:
    """Compute per-ticker fetch windows.

    Window:
      - start = earliest approx_date − 400 calendar days (~270 trading days,
        enough to populate ma240 + prior_high_60 + attack_intensity before the
        first case date)
      - end   = latest approx_date + 60 calendar days (~40 trading days buffer
        for detect() confirmation lookahead)

    Note: covers ALL course-cited tickers (including those whose main DB has
    only post-2022 history), not just NO_OHLCV cases. This is because the
    four_seasons main DB starts ~2022-01 for many tickers, so even DB_OK
    cases on 2022-02-18 have ≤ 27 trading days of pre-context — insufficient
    for ma240 / prior_high_60 / exhaust_context features.
    """
    df = pd.read_csv(CASE_CSV)
    # Use the most-corrected date column available (v4 → v2 → original).
    if "corrected_approx_date_v4" in df.columns:
        date_col = "corrected_approx_date_v4"
    elif "corrected_approx_date" in df.columns:
        date_col = "corrected_approx_date"
    else:
        date_col = "approx_date"
    df["_use_date"] = pd.to_datetime(df[date_col], errors="coerce")
    # Fall back to approx_date for rows where the corrected column is NaT.
    df["_use_date"] = df["_use_date"].fillna(pd.to_datetime(df["approx_date"], errors="coerce"))

    ranges: dict[str, tuple[str, str]] = {}
    for ticker, g in df.groupby("ticker"):
        start = (g["_use_date"].min() - timedelta(days=400)).strftime("%Y-%m-%d")
        end = (g["_use_date"].max() + timedelta(days=60)).strftime("%Y-%m-%d")
        ranges[str(ticker)] = (start, end)
    return ranges


# --- Step 2: Fetch OHLCV from FinMind ---

def fetch_ohlcv(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Fetch price data via throttled FinMind client. Returns empty df on failure."""
    try:
        df = get_price(ticker, start, end, token=TOKEN)
        if df is None or df.empty:
            return pd.DataFrame()
        return df
    except Exception as e:
        print(f"  ERROR fetching {ticker}: {e}")
        return pd.DataFrame()


# --- Step 3: Compute MAs and store to SQLite ---

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS standard_daily_bar (
    ticker TEXT,
    trade_date TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    ma5 REAL,
    ma10 REAL,
    ma20 REAL,
    ma60 REAL,
    ma240 REAL,
    is_usable INTEGER DEFAULT 1
)
"""

CREATE_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_ticker_date
ON standard_daily_bar (ticker, trade_date)
"""


def compute_mas(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("date").copy()
    df["ma5"]   = df["close"].rolling(5,   min_periods=1).mean()
    df["ma10"]  = df["close"].rolling(10,  min_periods=1).mean()
    df["ma20"]  = df["close"].rolling(20,  min_periods=1).mean()
    df["ma60"]  = df["close"].rolling(60,  min_periods=1).mean()
    df["ma240"] = df["close"].rolling(240, min_periods=1).mean()
    return df


def store_to_db(conn: sqlite3.Connection, ticker: str, df: pd.DataFrame) -> int:
    """Insert rows into standard_daily_bar, ignoring duplicates. Returns row count inserted."""
    if df.empty:
        return 0

    df = compute_mas(df)

    # Normalize column names (FinMind may return max/min or high/low)
    col_map = {}
    if "max" in df.columns and "high" not in df.columns:
        col_map["max"] = "high"
    if "min" in df.columns and "low" not in df.columns:
        col_map["min"] = "low"
    if col_map:
        df = df.rename(columns=col_map)

    # Build rows
    records = []
    for _, row in df.iterrows():
        date_str = str(row.get("date", ""))[:10]
        if not date_str:
            continue
        records.append({
            "ticker":     ticker,
            "trade_date": date_str,
            "open":       float(row.get("open") or 0) or None,
            "high":       float(row.get("high") or 0) or None,
            "low":        float(row.get("low") or 0) or None,
            "close":      float(row.get("close") or 0) or None,
            "volume":     int(row.get("Trading_Volume") or row.get("volume") or 0) or None,
            "ma5":        float(row["ma5"])   if pd.notna(row.get("ma5"))   else None,
            "ma10":       float(row["ma10"])  if pd.notna(row.get("ma10"))  else None,
            "ma20":       float(row["ma20"])  if pd.notna(row.get("ma20"))  else None,
            "ma60":       float(row["ma60"])  if pd.notna(row.get("ma60"))  else None,
            "ma240":      float(row["ma240"]) if pd.notna(row.get("ma240")) else None,
            "is_usable":  1,
        })

    if not records:
        return 0

    ins_df = pd.DataFrame(records)
    # Use INSERT OR IGNORE for deduplication
    cursor = conn.cursor()
    inserted = 0
    for r in ins_df.to_dict("records"):
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO standard_daily_bar
                (ticker, trade_date, open, high, low, close, volume,
                 ma5, ma10, ma20, ma60, ma240, is_usable)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                r["ticker"], r["trade_date"],
                r["open"], r["high"], r["low"], r["close"], r["volume"],
                r["ma5"], r["ma10"], r["ma20"], r["ma60"], r["ma240"],
                r["is_usable"],
            ))
            inserted += cursor.rowcount
        except Exception as e:
            print(f"    Insert error for {ticker}/{r['trade_date']}: {e}")
    conn.commit()
    return inserted


# --- Main ---

def main():
    OUT_DB.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(OUT_DB))
    conn.execute(CREATE_TABLE_SQL)
    conn.execute(CREATE_INDEX_SQL)
    conn.commit()

    ticker_ranges = get_ticker_ranges()
    print(f"\nFetching OHLCV for {len(ticker_ranges)} tickers...")

    failed_tickers = []
    total_rows = 0

    for i, (ticker, (start, end)) in enumerate(sorted(ticker_ranges.items()), 1):
        print(f"[{i}/{len(ticker_ranges)}] {ticker}: {start} ~ {end} ... ", end="", flush=True)
        df = fetch_ohlcv(ticker, start, end)
        if df.empty:
            print("EMPTY (possibly delisted or no data)")
            failed_tickers.append(ticker)
            continue
        n = store_to_db(conn, ticker, df)
        total_rows += n
        print(f"{len(df)} rows fetched, {n} inserted")

    conn.close()

    db_size = OUT_DB.stat().st_size / 1024
    print(f"\n=== Done ===")
    print(f"DB: {OUT_DB}")
    print(f"DB size: {db_size:.1f} KB")
    print(f"Total rows inserted: {total_rows}")
    if failed_tickers:
        print(f"Failed/empty tickers: {failed_tickers}")


if __name__ == "__main__":
    main()
