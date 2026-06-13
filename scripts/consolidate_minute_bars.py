"""把所有分K來源整合到主 DB 的 minute_bars table。

Strategy:
1. Backup main DB to /tmp
2. Copy main DB to /tmp/working.sqlite
3. CREATE TABLE IF NOT EXISTS minute_bars + index
4. Iterate 3 sources, normalize, INSERT OR IGNORE
5. Run sanity checks (row count, dedup, span)
6. Write back /tmp/working.sqlite to ~/.four_seasons/data.sqlite
7. Output report

Sources:
  1. ~/.four_seasons/finmind_kbar_cache/{ticker}_{date}.csv  (372 files)
     Columns: date, minute, stock_id, open, high, low, close, volume
  2. ~/.cache/finmind/kbar/{ticker}/{date}.json  (5 files)
     Format: list of {minute, open, high, low, close, volume}
  3. data/analysis/kline_patterns/attack_cost_minute_data.sqlite  (864 rows)
     Columns: ticker, trade_date, ts, open, high, low, close, volume
"""
from __future__ import annotations

from zhuli.db import get_conn, MAIN_DB

import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

import pandas as pd

WORKTREE_ROOT = Path("/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power")
MAIN_DB_SYMLINK = MAIN_DB
CSV_CACHE_DIR = Path.home() / ".four_seasons" / "finmind_kbar_cache"
JSON_CACHE_DIR = Path.home() / ".cache" / "finmind" / "kbar"
SMALL_DB = WORKTREE_ROOT / "data/analysis/kline_patterns/attack_cost_minute_data.sqlite"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS minute_bars (
    ticker TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    ts TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    PRIMARY KEY (ticker, trade_date, ts)
);
"""
CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_minute_bars_ticker_date ON minute_bars(ticker, trade_date);
"""

INSERT_SQL = """
INSERT OR IGNORE INTO minute_bars (ticker, trade_date, ts, open, high, low, close, volume)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""


def backup_main_db() -> Path:
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_path = Path(f"/tmp/data.sqlite.backup_{ts}")
    shutil.copy2(MAIN_DB_SYMLINK, backup_path)
    print(f"[backup] {backup_path}  ({backup_path.stat().st_size / 1e6:.1f} MB)")
    return backup_path


def copy_to_tmp() -> Path:
    working = Path("/tmp/working_minute_bars.sqlite")
    shutil.copy2(MAIN_DB_SYMLINK, working)
    print(f"[working copy] {working}")
    return working


def setup_table(conn: sqlite3.Connection) -> None:
    conn.execute(CREATE_TABLE_SQL)
    conn.execute(CREATE_INDEX_SQL)
    conn.commit()
    print("[setup] minute_bars table + index ready")


# ── Source 1: CSV cache ────────────────────────────────────────────────────────

def ingest_csv_cache(conn: sqlite3.Connection) -> int:
    """Load ~/.four_seasons/finmind_kbar_cache/{ticker}_{date}.csv files."""
    files = sorted(CSV_CACHE_DIR.glob("*.csv"))
    total = 0
    skipped_files = 0
    for f in files:
        stem = f.stem  # e.g. "1326_2026-04-14"
        parts = stem.rsplit("_", 1)
        if len(parts) != 2:
            skipped_files += 1
            continue
        ticker, trade_date = parts[0], parts[1]
        try:
            df = pd.read_csv(f)
            # Columns: date, minute, stock_id, open, high, low, close, volume
            if "minute" not in df.columns:
                skipped_files += 1
                continue
            rows = [
                (
                    str(ticker),
                    str(row["date"]),
                    str(row["minute"]),
                    float(row["open"]) if pd.notna(row["open"]) else None,
                    float(row["high"]) if pd.notna(row["high"]) else None,
                    float(row["low"]) if pd.notna(row["low"]) else None,
                    float(row["close"]) if pd.notna(row["close"]) else None,
                    float(row["volume"]) if pd.notna(row["volume"]) else None,
                )
                for _, row in df.iterrows()
            ]
            conn.executemany(INSERT_SQL, rows)
            total += len(rows)
        except Exception as e:
            print(f"  [csv skip] {f.name}: {e}")
            skipped_files += 1
    conn.commit()
    print(f"[source1 CSV] {len(files)} files, {total} rows inserted (skipped {skipped_files} files)")
    return total


# ── Source 2: JSON cache ───────────────────────────────────────────────────────

def ingest_json_cache(conn: sqlite3.Connection) -> int:
    """Load ~/.cache/finmind/kbar/{ticker}/{date}.json files."""
    files = list(JSON_CACHE_DIR.rglob("*.json"))
    total = 0
    skipped = 0
    for f in files:
        # path: .../kbar/{ticker}/{date}.json
        ticker = f.parent.name
        trade_date = f.stem  # YYYY-MM-DD
        try:
            data = json.loads(f.read_text())
            if not isinstance(data, list):
                skipped += 1
                continue
            rows = [
                (
                    str(ticker),
                    str(trade_date),
                    str(item["minute"]),
                    float(item["open"]) if item.get("open") is not None else None,
                    float(item["high"]) if item.get("high") is not None else None,
                    float(item["low"]) if item.get("low") is not None else None,
                    float(item["close"]) if item.get("close") is not None else None,
                    float(item["volume"]) if item.get("volume") is not None else None,
                )
                for item in data
                if "minute" in item
            ]
            conn.executemany(INSERT_SQL, rows)
            total += len(rows)
        except Exception as e:
            print(f"  [json skip] {f}: {e}")
            skipped += 1
    conn.commit()
    print(f"[source2 JSON] {len(files)} files, {total} rows inserted (skipped {skipped} files)")
    return total


# ── Source 3: Small SQLite DB ──────────────────────────────────────────────────

def ingest_small_db(conn: sqlite3.Connection) -> int:
    """Load data/analysis/kline_patterns/attack_cost_minute_data.sqlite."""
    if not SMALL_DB.exists():
        print("[source3 SQLite] file not found, skipped")
        return 0
    src = sqlite3.connect(SMALL_DB)
    rows = src.execute(
        "SELECT ticker, trade_date, ts, open, high, low, close, volume FROM minute_bars"
    ).fetchall()
    src.close()
    # Small DB schema already matches target (ticker, trade_date, ts, open, high, low, close, volume)
    conn.executemany(INSERT_SQL, rows)
    conn.commit()
    print(f"[source3 SQLite] {len(rows)} rows inserted")
    return len(rows)


# ── Sanity checks ──────────────────────────────────────────────────────────────

def sanity_checks(conn: sqlite3.Connection) -> dict:
    total = conn.execute("SELECT count(*) FROM minute_bars").fetchone()[0]
    unique_tickers = conn.execute("SELECT count(DISTINCT ticker) FROM minute_bars").fetchone()[0]
    unique_dates = conn.execute("SELECT count(DISTINCT trade_date) FROM minute_bars").fetchone()[0]
    null_ohlcv = conn.execute(
        "SELECT count(*) FROM minute_bars WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL OR volume IS NULL"
    ).fetchone()[0]

    # Sample 3 (ticker, date) pairs
    samples = conn.execute(
        "SELECT DISTINCT ticker, trade_date FROM minute_bars ORDER BY trade_date DESC LIMIT 3"
    ).fetchall()
    sample_data = {}
    for ticker, date in samples:
        rows = conn.execute(
            "SELECT ts, open, high, low, close, volume FROM minute_bars WHERE ticker=? AND trade_date=? LIMIT 5",
            (ticker, date),
        ).fetchall()
        sample_data[f"{ticker}_{date}"] = rows

    # Ticker/date span
    min_date = conn.execute("SELECT min(trade_date) FROM minute_bars").fetchone()[0]
    max_date = conn.execute("SELECT max(trade_date) FROM minute_bars").fetchone()[0]

    return {
        "total_rows": total,
        "unique_tickers": unique_tickers,
        "unique_dates": unique_dates,
        "null_ohlcv_rows": null_ohlcv,
        "date_span": f"{min_date} ~ {max_date}",
        "samples": sample_data,
    }


# ── Write back ────────────────────────────────────────────────────────────────

def write_back(working: Path) -> None:
    real_path = MAIN_DB_SYMLINK.resolve()
    shutil.copy2(working, real_path)
    print(f"[write back] {working} -> {real_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("minute_bars consolidation pipeline")
    print("=" * 60)

    # Step 1: Backup
    backup_path = backup_main_db()

    # Step 2: Working copy
    working = copy_to_tmp()

    conn = sqlite3.connect(working)
    conn.execute("PRAGMA journal_mode=WAL")

    # Step 3: Setup table
    setup_table(conn)

    # Step 4: Ingest all sources
    rows_csv = ingest_csv_cache(conn)
    rows_json = ingest_json_cache(conn)
    rows_sqlite = ingest_small_db(conn)

    # Step 5: Sanity checks
    checks = sanity_checks(conn)
    conn.close()

    print("\n── Sanity Checks ──")
    print(f"  Total rows:        {checks['total_rows']:,}")
    print(f"  Unique tickers:    {checks['unique_tickers']}")
    print(f"  Unique dates:      {checks['unique_dates']}")
    print(f"  NULL ohlcv rows:   {checks['null_ohlcv_rows']}")
    print(f"  Date span:         {checks['date_span']}")
    print("  Samples:")
    for key, rows in checks["samples"].items():
        print(f"    {key}:")
        for r in rows:
            print(f"      {r}")

    # Step 6: Write back
    write_back(working)
    working.unlink()
    print(f"[cleanup] removed working copy {working}")

    # Step 7: Report
    total_attempted = rows_csv + rows_json + rows_sqlite
    report = f"""# minute_bars Consolidation Report

Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}

## Backup
- Path: `{backup_path}`

## Source Row Counts
| 來源 | 嘗試插入 |
|---|---|
| Source 1 — CSV cache (`finmind_kbar_cache/*.csv`) | {rows_csv:,} |
| Source 2 — JSON cache (`.cache/finmind/kbar/`) | {rows_json:,} |
| Source 3 — Small SQLite (`attack_cost_minute_data.sqlite`) | {rows_sqlite:,} |
| **Total attempted** | **{total_attempted:,}** |

Note: `INSERT OR IGNORE` — duplicates across sources are silently dropped.

## Main DB minute_bars Table (Final)
- Total rows: **{checks['total_rows']:,}**
- Unique tickers: {checks['unique_tickers']}
- Unique dates: {checks['unique_dates']}
- Date span: {checks['date_span']}
- NULL ohlcv rows: {checks['null_ohlcv_rows']}

## Schema Deviations / Data Quality
- CSV Source: columns `date,minute,stock_id,open,high,low,close,volume` — normalized to `(ticker, trade_date, ts, open, high, low, close, volume)`
- JSON Source: list of `{{minute, open, high, low, close, volume}}` — ticker/date from path
- SQLite Source: already matches target schema exactly

## detector helper 改動
- `scripts/kline/patterns/attack_cost_displayed.py`
  - `_MINUTE_BAR_DB` removed
  - `get_max_volume_price_intraday()` now calls `get_minute_bars()` from `scripts/kline/minute_bars.py`
  - New helper `scripts/kline/minute_bars.py` — copies main DB to /tmp before reading

## Files to Consider Deleting (user confirm)
- `data/analysis/kline_patterns/attack_cost_minute_data.sqlite` — already integrated into main DB
  - `~/.four_seasons/finmind_kbar_cache/*.csv` — raw source, keep for reference
  - `~/.cache/finmind/kbar/*.json` — used by FinMind client, keep
"""
    report_path = WORKTREE_ROOT / "data/analysis/kline_patterns/minute_bars_consolidation_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report)
    print(f"\n[report] {report_path}")
    print("\n✓ Pipeline complete")


if __name__ == "__main__":
    main()
