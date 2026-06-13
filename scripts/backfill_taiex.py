"""Backfill TAIEX (加權指數) historical OHLCV from FinMind.

Uses the throttled stock-analysis-system FinMind client.
Ticker = "TAIEX" on TaiwanStockPrice dataset.

Output: data/analysis/kline_patterns/taiex_history.sqlite
Schema: trade_date TEXT PK, open REAL, high REAL, low REAL, close REAL, volume INTEGER
"""
from __future__ import annotations

from zhuli.db import get_conn

import os
import sqlite3
import sys
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
WORKTREE = Path("/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power")
OUT_DB = WORKTREE / "data/analysis/kline_patterns/taiex_history.sqlite"

SAS_PATH = Path("/Users/howard/Repository/stock-analysis-system")
if str(SAS_PATH) not in sys.path:
    sys.path.insert(0, str(SAS_PATH))

# ---------------------------------------------------------------------------
# Load env token
# ---------------------------------------------------------------------------
TOKEN = os.environ.get("FINMIND_API_TOKEN", "")
if not TOKEN:
    for env_file in [WORKTREE / ".env", SAS_PATH / ".env"]:
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("FINMIND_API_TOKEN="):
                    TOKEN = line.split("=", 1)[1].strip()
                    os.environ["FINMIND_API_TOKEN"] = TOKEN
                if line.startswith("FINMIND_TIER="):
                    os.environ["FINMIND_TIER"] = line.split("=", 1)[1].strip()
            if TOKEN:
                break

print(f"Token: {'set (' + TOKEN[:20] + '...)' if TOKEN else 'MISSING'}")
print(f"Tier: {os.environ.get('FINMIND_TIER', 'free')}")

from clients.finmind_client import get_data  # noqa: E402

# ---------------------------------------------------------------------------
# DB setup
# ---------------------------------------------------------------------------
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS taiex_daily (
    trade_date TEXT PRIMARY KEY,
    open       REAL,
    high       REAL,
    low        REAL,
    close      REAL,
    volume     INTEGER
)
"""


def _init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn(db_path, readonly=False)
    conn.execute(CREATE_TABLE_SQL)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------
def fetch_taiex(start: str, end: str) -> pd.DataFrame:
    """Fetch TAIEX from FinMind, rename max→high, min→low."""
    df = get_data("TaiwanStockPrice", "TAIEX", start, end, TOKEN)
    if df is None or df.empty:
        return pd.DataFrame()
    rename = {}
    if "max" in df.columns:
        rename["max"] = "high"
    if "min" in df.columns:
        rename["min"] = "low"
    if rename:
        df = df.rename(columns=rename)
    return df


def store_taiex(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    """Insert rows to taiex_daily using INSERT OR IGNORE."""
    if df.empty:
        return 0
    cursor = conn.cursor()
    inserted = 0
    for _, row in df.iterrows():
        date_str = str(row.get("date", ""))[:10]
        if not date_str:
            continue
        try:
            cursor.execute(
                """
                INSERT OR IGNORE INTO taiex_daily (trade_date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    date_str,
                    float(row.get("open") or 0) or None,
                    float(row.get("high") or 0) or None,
                    float(row.get("low") or 0) or None,
                    float(row.get("close") or 0) or None,
                    int(row.get("Trading_Volume") or 0) or None,
                ),
            )
            inserted += cursor.rowcount
        except Exception as e:
            print(f"  Insert error {date_str}: {e}")
    conn.commit()
    return inserted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    conn = _init_db(OUT_DB)

    # Fetch in chunks to avoid timeout (FinMind max window ~10 years per call)
    chunks = [
        ("1990-01-01", "1999-12-31"),
        ("2000-01-01", "2009-12-31"),
        ("2010-01-01", "2019-12-31"),
        ("2020-01-01", "2026-12-31"),
    ]
    total = 0
    for start, end in chunks:
        print(f"Fetching {start} ~ {end} ...", end=" ", flush=True)
        df = fetch_taiex(start, end)
        if df.empty:
            print("EMPTY")
            continue
        n = store_taiex(conn, df)
        total += n
        print(f"{len(df)} rows fetched, {n} inserted")

    # Summary
    cur = conn.cursor()
    cur.execute("SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM taiex_daily")
    row = cur.fetchone()
    conn.close()

    print(f"\n=== Done ===")
    print(f"DB: {OUT_DB}")
    print(f"Date range: {row[0]} ~ {row[1]}")
    print(f"Total rows: {row[2]}")


if __name__ == "__main__":
    main()
