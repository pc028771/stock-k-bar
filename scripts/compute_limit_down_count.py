"""Compute per-day 跌停家數 from main standard_daily_bar DB.

跌停定義: close ≤ prev_close × 0.901  (台股 ±10% 漲跌幅)
[STUB-NEED-USER] 0.901 threshold: 課程未明示確切計算方式，建議 user 確認。

Source DB: ~/.four_seasons/data.sqlite (standard_daily_bar)
Output DB: data/analysis/kline_patterns/limit_down_history.sqlite
Schema:    trade_date TEXT PK, limit_down_count INTEGER
"""
from __future__ import annotations

from zhuli.db import get_conn

import sqlite3
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
WORKTREE = Path("/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power")
SOURCE_DB = Path("/Users/howard/.four_seasons/data.sqlite")
OUT_DB = WORKTREE / "data/analysis/kline_patterns/limit_down_history.sqlite"

# 台股跌停：收盤 ≤ 前收 × 0.901 (即跌幅 ≥ 9.9% 視為跌停)
LIMIT_DOWN_RATIO = 0.901

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS limit_down_daily (
    trade_date       TEXT PRIMARY KEY,
    limit_down_count INTEGER
)
"""


def _init_out_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn(db_path, readonly=False)
    conn.execute(CREATE_TABLE_SQL)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------------
def compute_limit_down_counts(src_db: Path) -> pd.DataFrame:
    """Read standard_daily_bar, compute daily 跌停家數.

    Strategy:
    1. Read ticker + trade_date + close from source DB.
    2. For each ticker, compute prev_close via shift(1) within ticker group.
    3. Flag limit_down = close ≤ prev_close × LIMIT_DOWN_RATIO.
    4. Group by trade_date, count limit_down flags.
    """
    print(f"Reading from {src_db} ...")
    conn = sqlite3.connect(str(src_db))
    # Only load minimum columns needed
    df = pd.read_sql_query(
        "SELECT ticker, trade_date, close FROM standard_daily_bar WHERE is_usable=1 ORDER BY ticker, trade_date",
        conn,
    )
    conn.close()
    print(f"  Loaded {len(df):,} rows across {df['ticker'].nunique():,} tickers")

    # Compute prev_close per ticker
    df = df.sort_values(["ticker", "trade_date"])
    df["prev_close"] = df.groupby("ticker")["close"].shift(1)

    # Drop rows with no previous close (first bar per ticker)
    df = df.dropna(subset=["prev_close"])

    # Flag limit down
    df["is_limit_down"] = df["close"] <= df["prev_close"] * LIMIT_DOWN_RATIO

    # Group by date
    result = (
        df.groupby("trade_date")["is_limit_down"]
        .sum()
        .astype(int)
        .reset_index()
        .rename(columns={"is_limit_down": "limit_down_count"})
    )
    result = result.sort_values("trade_date").reset_index(drop=True)
    return result


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
def store_result(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    cursor = conn.cursor()
    inserted = 0
    for _, row in df.iterrows():
        try:
            cursor.execute(
                "INSERT OR REPLACE INTO limit_down_daily (trade_date, limit_down_count) VALUES (?, ?)",
                (row["trade_date"], int(row["limit_down_count"])),
            )
            inserted += cursor.rowcount
        except Exception as e:
            print(f"  Insert error {row['trade_date']}: {e}")
    conn.commit()
    return inserted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if not SOURCE_DB.exists():
        print(f"ERROR: source DB not found: {SOURCE_DB}")
        return

    df = compute_limit_down_counts(SOURCE_DB)
    print(f"\nDate range: {df['trade_date'].min()} ~ {df['trade_date'].max()}")
    print(f"Total date rows: {len(df)}")
    print(f"Max 跌停家數: {df['limit_down_count'].max()} on {df.loc[df['limit_down_count'].idxmax(), 'trade_date']}")

    out_conn = _init_out_db(OUT_DB)
    n = store_result(out_conn, df)
    out_conn.close()

    print(f"\n=== Done ===")
    print(f"DB: {OUT_DB}")
    print(f"Total rows inserted/replaced: {n}")


if __name__ == "__main__":
    main()
