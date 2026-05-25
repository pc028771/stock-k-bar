#!/usr/bin/env python3
"""
Import NDJSON cache from FinMind to SQLite standard_daily_bar table.

Maps:
  stock_id -> ticker
  date (first 10 chars) -> trade_date
  max -> high
  min -> low
  Trading_Volume -> volume
  open, close -> same

Inserts only if (ticker, trade_date, data_source_id) doesn't exist (UNIQUE constraint).
"""

import json
import sqlite3
import os
from pathlib import Path
from datetime import datetime

# Configuration
NDJSON_ROOT = "/Users/howard/Repository/stock-k-bar/.claude/worktrees/four-seasons-redesign/data/raw/TaiwanStockPrice"
DB_PATH = "/Users/howard/.four_seasons/data.sqlite"
DATA_SOURCE_ID = 1  # FinMind
BATCH_SIZE = 50  # commit every N tickers
PROGRESS_INTERVAL = 200  # print progress every N tickers

def parse_ndjson_row(json_line):
    """Parse single NDJSON line and extract fields."""
    data = json.loads(json_line)

    # Extract trade_date from "2023-01-03 00:00:00" -> "2023-01-03"
    trade_date = data.get("date", "")[:10]

    # Skip if close or volume is None/null
    close = data.get("close")
    volume = data.get("Trading_Volume")
    if close is None or volume is None:
        return None

    return {
        "ticker": data.get("stock_id"),
        "trade_date": trade_date,
        "data_source_id": DATA_SOURCE_ID,
        "open": data.get("open"),
        "high": data.get("max"),
        "low": data.get("min"),
        "close": close,
        "volume": volume,
        "is_usable": 1,
        "created_at": datetime.now().isoformat(),
    }

def import_ndjson_to_db():
    """Main import function."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Verify UNIQUE constraint exists
    cursor.execute("""
        SELECT sql FROM sqlite_master
        WHERE type='table' AND name='standard_daily_bar'
    """)
    schema = cursor.fetchone()[0]
    if "UNIQUE(ticker, trade_date, data_source_id)" not in schema:
        print("ERROR: UNIQUE constraint not found on (ticker, trade_date, data_source_id)")
        conn.close()
        return

    total_inserted = 0
    ticker_count = 0
    start_time = datetime.now()

    # Walk all ticker subdirectories
    tickers = sorted([d for d in os.listdir(NDJSON_ROOT)
                     if os.path.isdir(os.path.join(NDJSON_ROOT, d))])
    print(f"Found {len(tickers)} ticker directories\n")

    for ticker in tickers:
        ticker_path = os.path.join(NDJSON_ROOT, ticker)
        ticker_inserted = 0

        # Process 2023.ndjson and 2024.ndjson
        for year_file in ["2023.ndjson", "2024.ndjson"]:
            ndjson_path = os.path.join(ticker_path, year_file)
            if not os.path.exists(ndjson_path):
                continue

            try:
                with open(ndjson_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue

                        row = parse_ndjson_row(line)
                        if row is None:
                            continue

                        # INSERT OR IGNORE relies on UNIQUE constraint
                        try:
                            cursor.execute("""
                                INSERT OR IGNORE INTO standard_daily_bar
                                (ticker, trade_date, data_source_id, open, high, low, close, volume, is_usable, created_at)
                                VALUES (:ticker, :trade_date, :data_source_id, :open, :high, :low, :close, :volume, :is_usable, :created_at)
                            """, row)
                            ticker_inserted += cursor.rowcount
                        except Exception as e:
                            print(f"ERROR inserting row {row}: {e}")
                            continue

            except Exception as e:
                print(f"ERROR reading {ndjson_path}: {e}")
                continue

        ticker_count += 1
        total_inserted += ticker_inserted

        # Commit every BATCH_SIZE tickers
        if ticker_count % BATCH_SIZE == 0:
            conn.commit()

        # Progress report every PROGRESS_INTERVAL tickers
        if ticker_count % PROGRESS_INTERVAL == 0:
            elapsed = (datetime.now() - start_time).total_seconds()
            print(f"Progress: {ticker_count} tickers processed, {total_inserted} rows inserted ({elapsed:.1f}s)")

    # Final commit
    conn.commit()

    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n✓ Import complete:")
    print(f"  Total tickers: {ticker_count}")
    print(f"  Total rows inserted: {total_inserted}")
    print(f"  Time elapsed: {elapsed:.1f}s")

    # Verification: sample 3 rows from 2023-01-03
    print(f"\nVerification (2023-01-03 samples):")
    samples = [("2330", "2023-01-03", "expected ~453±10"),
               ("1101", "2023-01-03", "expected ~25±3"),
               ("0050", "2023-01-03", "expected ~110±1")]

    for ticker, trade_date, expected in samples:
        cursor.execute("""
            SELECT close, volume FROM standard_daily_bar
            WHERE ticker=? AND trade_date=? AND data_source_id=?
        """, (ticker, trade_date, DATA_SOURCE_ID))
        result = cursor.fetchone()
        if result:
            close, volume = result
            print(f"  {ticker} {trade_date}: close={close} ({expected}), volume={volume}")
        else:
            print(f"  {ticker} {trade_date}: NOT FOUND")

    conn.close()

if __name__ == "__main__":
    import_ndjson_to_db()
