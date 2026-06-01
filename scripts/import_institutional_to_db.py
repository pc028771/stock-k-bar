#!/usr/bin/env python3
"""
Import FinMind TaiwanStockInstitutionalInvestorsBuySell NDJSON cache to SQLite.
Schema: ticker, trade_date, foreign_buy, foreign_sell, foreign_net, sitc_buy, sitc_sell, sitc_net
Unique constraint: (ticker, trade_date)
"""

import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

DB_PATH = Path.home() / '.four_seasons' / 'data.sqlite'
DATA_ROOT = Path('/Users/howard/Repository/stock-k-bar/.claude/worktrees/four-seasons-redesign/data/raw/TaiwanStockInstitutionalInvestorsBuySell')

# Mapping from NDJSON 'name' to DB column prefix
# 6 investor types
INVESTOR_TYPE_MAPPING = {
    'Foreign_Investor': 'foreign',           # Foreign_Investor → foreign_buy/sell
    'Foreign_Dealer_Self': 'foreign',        # Treat same as Foreign_Investor
    'Investment_Trust': 'sitc',              # Investment_Trust → sitc_buy/sell
    'Dealer_self': 'sitc',                   # Treat as sitc
    'Dealer_Hedging': 'sitc',                # Treat as sitc
    'Dealer': 'sitc',                        # Treat as sitc
}

def load_ndjson_file(file_path: Path) -> List[Dict]:
    """Load NDJSON file and return list of dicts."""
    rows = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"⚠️  JSON parse error in {file_path}: {e}", file=sys.stderr)
                    continue
    except Exception as e:
        print(f"⚠️  Error reading {file_path}: {e}", file=sys.stderr)
    return rows


def parse_record(row: Dict) -> Optional[Dict]:
    """
    Parse NDJSON record and return dict suitable for INSERT.
    Returns None if record should be skipped.
    """
    try:
        stock_id = str(row.get('stock_id', '')).strip()
        date_str = str(row.get('date', '')).strip()
        buy = row.get('buy')
        sell = row.get('sell')
        name = str(row.get('name', '')).strip()

        # Skip if buy or sell is None
        if buy is None or sell is None:
            return None

        # Extract trade_date (first 10 chars of date: "2024-01-02")
        trade_date = date_str[:10] if len(date_str) >= 10 else date_str

        # Determine column prefix based on investor type
        col_prefix = INVESTOR_TYPE_MAPPING.get(name)
        if not col_prefix:
            return None  # Unknown investor type

        # Build insert record
        record = {
            'ticker': stock_id,
            'trade_date': trade_date,
            'buy': float(buy),
            'sell': float(sell),
            'col_prefix': col_prefix,  # Temporary marker
            'name': name,
        }
        return record
    except Exception as e:
        print(f"⚠️  Error parsing record: {e}", file=sys.stderr)
        return None


def insert_batch(conn: sqlite3.Connection, batch: List[Dict]) -> int:
    """
    Insert a batch of records. Aggregate by (ticker, trade_date, col_prefix).
    Returns number of new rows inserted.
    """
    if not batch:
        return 0

    # Aggregate by (ticker, trade_date, col_prefix)
    aggregated = {}
    for rec in batch:
        key = (rec['ticker'], rec['trade_date'], rec['col_prefix'])
        if key not in aggregated:
            aggregated[key] = {'buy': 0, 'sell': 0}
        aggregated[key]['buy'] += rec['buy']
        aggregated[key]['sell'] += rec['sell']

    # Prepare INSERT statements
    cursor = conn.cursor()
    inserted = 0

    for (ticker, trade_date, col_prefix), agg_data in aggregated.items():
        buy = agg_data['buy']
        sell = agg_data['sell']
        net = buy - sell

        if col_prefix == 'foreign':
            sql = """
                INSERT OR IGNORE INTO institutional_investors
                (ticker, trade_date, foreign_buy, foreign_sell, foreign_net)
                VALUES (?, ?, ?, ?, ?)
            """
            params = (ticker, trade_date, buy, sell, net)
        else:  # sitc
            sql = """
                INSERT OR IGNORE INTO institutional_investors
                (ticker, trade_date, sitc_buy, sitc_sell, sitc_net)
                VALUES (?, ?, ?, ?, ?)
            """
            params = (ticker, trade_date, buy, sell, net)

        try:
            cursor.execute(sql, params)
            inserted += cursor.rowcount
        except Exception as e:
            print(f"⚠️  Insert error for {ticker} {trade_date} ({col_prefix}): {e}", file=sys.stderr)

    return inserted


def main():
    """Main import loop."""
    if not DB_PATH.exists():
        print(f"❌ DB file not found: {DB_PATH}")
        return 1

    if not DATA_ROOT.exists():
        print(f"❌ Data directory not found: {DATA_ROOT}")
        return 1

    # Collect all ticker directories
    ticker_dirs = sorted([d for d in DATA_ROOT.iterdir() if d.is_dir()])
    print(f"📦 Found {len(ticker_dirs)} ticker directories")

    total_inserted = 0
    batch_buffer = []
    batch_size = 10000
    commit_interval = 50
    processed_tickers = 0

    start_time = datetime.now()

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        for ticker_idx, ticker_dir in enumerate(ticker_dirs):
            ticker = ticker_dir.name

            # Load all NDJSON files for this ticker
            ndjson_files = sorted(ticker_dir.glob('*.ndjson'))

            for ndjson_file in ndjson_files:
                rows = load_ndjson_file(ndjson_file)

                for row in rows:
                    parsed = parse_record(row)
                    if parsed:
                        batch_buffer.append(parsed)

                # Insert when batch is full
                if len(batch_buffer) >= batch_size:
                    inserted = insert_batch(conn, batch_buffer)
                    total_inserted += inserted
                    batch_buffer = []

            processed_tickers += 1

            # Progress report every 200 tickers
            if processed_tickers % 200 == 0:
                print(f"  ✓ Processed {processed_tickers} tickers, cumulative INSERT: {total_inserted}")

            # Commit every 50 tickers
            if processed_tickers % commit_interval == 0:
                conn.commit()

        # Final batch
        if batch_buffer:
            inserted = insert_batch(conn, batch_buffer)
            total_inserted += inserted

        conn.commit()

    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()

    print(f"\n✅ Import completed")
    print(f"   Total INSERT rows: {total_inserted}")
    print(f"   Time elapsed: {elapsed:.2f}s")

    # Verify with sample data (2330 on 2024-12-31)
    print(f"\n📋 Verification: 2330 on 2024-12-31")
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        rows = cursor.execute("""
            SELECT ticker, trade_date, foreign_buy, foreign_sell, foreign_net,
                   sitc_buy, sitc_sell, sitc_net
            FROM institutional_investors
            WHERE ticker = '2330' AND trade_date = '2024-12-31'
            ORDER BY foreign_buy + sitc_buy DESC
        """).fetchall()

        if rows:
            for row in rows[:3]:
                print(f"   ticker={row['ticker']}, date={row['trade_date']}")
                print(f"     foreign: buy={row['foreign_buy']}, sell={row['foreign_sell']}, net={row['foreign_net']}")
                print(f"     sitc:    buy={row['sitc_buy']}, sell={row['sitc_sell']}, net={row['sitc_net']}")
        else:
            print(f"   No data found for 2330 on 2024-12-31")

    return 0


if __name__ == '__main__':
    sys.exit(main())
