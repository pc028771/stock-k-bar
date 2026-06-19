"""Migrate a table from local SQLite to Turso in chunked transactions.

Avoids server-side 502 timeouts on huge .dump imports by:
  1. CREATE TABLE via schema dump
  2. INSERT rows in chunks (default 5000/txn)
  3. Verify row counts match

Usage:
    python scripts/common/migrate_table_to_turso.py <table_name> [--chunk N]
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import libsql_experimental as libsql

LOCAL_DB = os.getenv("LOCAL_DB_PATH", str(Path.home() / ".four_seasons/data.sqlite"))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("table")
    p.add_argument("--chunk", type=int, default=5000)
    p.add_argument("--drop", action="store_true", help="DROP TABLE first")
    args = p.parse_args()

    url = os.getenv("TURSO_DATABASE_URL")
    token = os.getenv("TURSO_AUTH_TOKEN")
    if not url:
        print("ERROR: TURSO_DATABASE_URL not set", file=sys.stderr)
        return 1

    local = sqlite3.connect(LOCAL_DB)
    local.row_factory = sqlite3.Row

    print(f"→ source: {LOCAL_DB}")
    print(f"→ target: {url}")
    print(f"→ table:  {args.table}")

    schema_row = local.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (args.table,)
    ).fetchone()
    if not schema_row:
        print(f"ERROR: table {args.table} not found in source", file=sys.stderr)
        return 1
    create_sql = schema_row[0]

    # Also grab indexes
    index_rows = local.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
        (args.table,),
    ).fetchall()

    (total,) = local.execute(f"SELECT COUNT(*) FROM {args.table}").fetchone()
    print(f"→ rows to migrate: {total:,}")

    # Cloud-only mode for fastest writes (no local replica overhead)
    remote = libsql.connect(database=url, auth_token=token)

    if args.drop:
        print("→ DROP TABLE IF EXISTS")
        remote.execute(f"DROP TABLE IF EXISTS {args.table}")
        remote.commit()

    print("→ CREATE TABLE")
    remote.execute(create_sql)
    remote.commit()

    for idx_sql in index_rows:
        try:
            remote.execute(idx_sql[0])
        except Exception as e:
            print(f"  (index skipped: {e})")
    remote.commit()

    # Stream rows in chunks
    cur = local.execute(f"SELECT * FROM {args.table}")
    cols = [d[0] for d in cur.description]
    placeholders = ",".join("?" * len(cols))
    insert_sql = (
        f"INSERT INTO {args.table} ({','.join(cols)}) VALUES ({placeholders})"
    )

    t_start = time.time()
    inserted = 0
    batch: list[tuple] = []
    last_log = t_start

    for row in cur:
        batch.append(tuple(row))
        if len(batch) >= args.chunk:
            remote.executemany(insert_sql, batch)
            remote.commit()
            inserted += len(batch)
            batch = []
            now = time.time()
            if now - last_log >= 5:
                rate = inserted / (now - t_start)
                eta = (total - inserted) / rate if rate else 0
                print(
                    f"  {inserted:>9,} / {total:,}  "
                    f"({inserted/total*100:5.1f}%)  "
                    f"{rate:>6.0f} rows/s  eta {eta/60:.1f}m"
                )
                last_log = now

    if batch:
        remote.executemany(insert_sql, batch)
        remote.commit()
        inserted += len(batch)

    elapsed = time.time() - t_start
    print(f"→ inserted {inserted:,} rows in {elapsed/60:.1f}m  ({inserted/elapsed:.0f} rows/s)")

    # Verify
    (remote_count,) = remote.execute(f"SELECT COUNT(*) FROM {args.table}").fetchone()
    if remote_count == total:
        print(f"✅ verified: local={total:,}  turso={remote_count:,}")
        return 0
    print(f"❌ mismatch: local={total:,}  turso={remote_count:,}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
