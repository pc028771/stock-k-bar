"""Backfill 1 分 K 資料至 SQLite DB stock_minute_kbar 表。

資料來源: FinMind TaiwanStockKBar (Sponsor tier)
         透過 stock-analysis-system 的 fetch_kbar() 函式 (含快取)
         ⚠️ 禁止直接 curl FinMind API。

Table schema:
    stock_minute_kbar (
        ticker          TEXT    -- 股票代號
        trade_datetime  TEXT    -- 'YYYY-MM-DD HH:MM' (1 分 K)
        open            REAL
        high            REAL
        low             REAL
        close           REAL
        volume          INTEGER
        source          TEXT    DEFAULT 'FinMind'
        PRIMARY KEY (ticker, trade_datetime)
    )

Usage:
    python scripts/zhuli/backfill_minute_kbar.py \\
        --tickers 2885,1605,3481 \\
        --start-date 2026-05-19 \\
        --end-date 2026-06-03

    # 跳過已存在資料:
    python scripts/zhuli/backfill_minute_kbar.py \\
        --tickers 2885,1605 --start-date 2026-05-19 --skip-existing

Note:
    FinMind Sponsor tier 4500 req/hr。
    每次呼叫 = 1 ticker × 1 day。
    sleep 0.3s / req 安全線 = 12 req/min = 720 req/hr (far below 4500).
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import date as _date, timedelta
from pathlib import Path

import pandas as pd

# ── 路徑設定 ──────────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent.parent
_SYS_DIR = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_REPO), str(_REPO / "scripts"), str(_SYS_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.db import get_conn, MAIN_DB
from clients.finmind_client import fetch_kbar  # noqa: E402

# ── 常數 ──────────────────────────────────────────────────────────────────────
_DB = MAIN_DB
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS stock_minute_kbar (
    ticker        TEXT NOT NULL,
    trade_datetime TEXT NOT NULL,
    open          REAL,
    high          REAL,
    low           REAL,
    close         REAL,
    volume        INTEGER,
    source        TEXT DEFAULT 'FinMind',
    PRIMARY KEY (ticker, trade_datetime)
);
"""

CREATE_INDEX_TICKER_DATE_SQL = """
CREATE INDEX IF NOT EXISTS idx_minute_ticker_date
    ON stock_minute_kbar(ticker, trade_datetime);
"""

CREATE_INDEX_DATE_SQL = """
CREATE INDEX IF NOT EXISTS idx_minute_date
    ON stock_minute_kbar(trade_datetime);
"""

SLEEP_PER_REQ = 0.3  # 秒 (保守)


# ── DB 工具 ───────────────────────────────────────────────────────────────────

def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(CREATE_TABLE_SQL)
    conn.execute(CREATE_INDEX_TICKER_DATE_SQL)
    conn.execute(CREATE_INDEX_DATE_SQL)
    conn.commit()


def get_existing_dates(conn: sqlite3.Connection, ticker: str) -> set[str]:
    """取得已存在資料的日期集合 (YYYY-MM-DD)。"""
    rows = conn.execute(
        "SELECT DISTINCT substr(trade_datetime, 1, 10) FROM stock_minute_kbar WHERE ticker=?",
        (ticker,),
    ).fetchall()
    return {r[0] for r in rows}


def insert_rows(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """INSERT OR IGNORE 多筆 1 分 K 資料。"""
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT OR IGNORE INTO stock_minute_kbar
            (ticker, trade_datetime, open, high, low, close, volume, source)
        VALUES (:ticker, :trade_datetime, :open, :high, :low, :close, :volume, :source)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


# ── 資料處理 ──────────────────────────────────────────────────────────────────

def _trading_days(start: str, end: str) -> list[str]:
    """回傳 [start, end] 之間的非假日日期 (週一~五)。"""
    days: list[str] = []
    d = _date.fromisoformat(start)
    end_d = _date.fromisoformat(end)
    while d <= end_d:
        if d.weekday() < 5:  # Mon-Fri
            days.append(d.isoformat())
        d += timedelta(days=1)
    return days


def _kbar_to_rows(df: pd.DataFrame, ticker: str, date_str: str) -> list[dict]:
    """將 fetch_kbar() 回傳的 DataFrame 轉成 DB insert rows。

    fetch_kbar() 回傳欄位: minute (HH:MM), open, high, low, close, volume
    """
    if df.empty:
        return []

    rows: list[dict] = []
    for _, row in df.iterrows():
        minute_str = str(row.get("minute", ""))
        if not minute_str or len(minute_str) < 4:
            continue
        # trade_datetime = 'YYYY-MM-DD HH:MM'
        trade_dt = f"{date_str} {minute_str[:5]}"
        rows.append({
            "ticker": ticker,
            "trade_datetime": trade_dt,
            "open": float(row["open"]) if pd.notna(row["open"]) else None,
            "high": float(row["high"]) if pd.notna(row["high"]) else None,
            "low":  float(row["low"])  if pd.notna(row["low"])  else None,
            "close": float(row["close"]) if pd.notna(row["close"]) else None,
            "volume": int(row["volume"]) if pd.notna(row["volume"]) else None,
            "source": "FinMind",
        })
    return rows


# ── 主流程 ────────────────────────────────────────────────────────────────────

def backfill(
    tickers: list[str],
    start_date: str,
    end_date: str,
    db_path: Path = _DB,
    skip_existing: bool = True,
    verbose: bool = False,
) -> dict:
    """主 backfill 函式。

    Args:
        tickers:       要 backfill 的 ticker 清單 (至少 1 檔)
        start_date:    起始日期 YYYY-MM-DD
        end_date:      結束日期 YYYY-MM-DD
        db_path:       SQLite DB 路徑
        skip_existing: True = 跳過已存在的 (ticker, date) pair
        verbose:       詳細輸出

    Returns:
        dict: {tickers, days, api_calls, rows_inserted, rows_skipped, errors}
    """
    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        sys.exit("ERROR: FINMIND_TOKEN env var not set.")

    all_days = _trading_days(start_date, end_date)
    conn = get_conn(db_path, readonly=False, timeout=30)
    ensure_table(conn)

    stats = {
        "tickers": len(tickers),
        "days": len(all_days),
        "api_calls": 0,
        "rows_inserted": 0,
        "rows_skipped": 0,
        "errors": 0,
    }

    total_ops = len(tickers) * len(all_days)
    op_idx = 0

    for ticker in tickers:
        existing_dates = get_existing_dates(conn, ticker) if skip_existing else set()
        ticker_rows = 0
        ticker_skipped = 0
        ticker_errors = 0

        for date_str in all_days:
            op_idx += 1

            if skip_existing and date_str in existing_dates:
                ticker_skipped += 1
                stats["rows_skipped"] += 1
                continue

            try:
                df = fetch_kbar(ticker, date_str, token)
                stats["api_calls"] += 1
                time.sleep(SLEEP_PER_REQ)

                if df.empty:
                    if verbose:
                        print(f"  [{op_idx}/{total_ops}] {ticker} {date_str}: 空資料 (非交易日?)")
                    continue

                rows = _kbar_to_rows(df, ticker, date_str)
                n = insert_rows(conn, rows)
                ticker_rows += n
                stats["rows_inserted"] += n

                if verbose:
                    print(f"  [{op_idx}/{total_ops}] {ticker} {date_str}: {n} rows")

            except Exception as exc:
                ticker_errors += 1
                stats["errors"] += 1
                print(f"  [{op_idx}/{total_ops}] {ticker} {date_str}: ERROR — {exc}")
                time.sleep(1.0)  # 錯誤後稍等

        print(
            f"  {ticker}: inserted={ticker_rows}, skipped={ticker_skipped}, errors={ticker_errors}"
        )

    conn.close()

    print(
        f"\n完成: tickers={stats['tickers']}, api_calls={stats['api_calls']}, "
        f"rows_inserted={stats['rows_inserted']}, "
        f"rows_skipped={stats['rows_skipped']}, errors={stats['errors']}"
    )
    return stats


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        prog="backfill_minute_kbar",
        description="Backfill 1 分 K 資料至 stock_minute_kbar 表 (FinMind TaiwanStockKBar)",
    )
    p.add_argument(
        "--tickers", required=True,
        help="逗號分隔的股票代號，例如 2885,1605,3481",
    )
    p.add_argument("--start-date", required=True, metavar="YYYY-MM-DD")
    p.add_argument("--end-date",   required=True, metavar="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=_DB, metavar="PATH", help="SQLite DB 路徑")
    p.add_argument("--skip-existing", action="store_true", default=False,
                   help="跳過已存在的 (ticker, date) 組合")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    if not tickers:
        sys.exit("ERROR: --tickers 必須至少包含一個代號")

    backfill(
        tickers=tickers,
        start_date=args.start_date,
        end_date=args.end_date,
        db_path=args.db,
        skip_existing=args.skip_existing,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
