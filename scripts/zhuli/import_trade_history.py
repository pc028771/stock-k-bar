"""匯入個人對帳單 CSV 到 trade_history 資料表.

Usage:
    python scripts/zhuli/import_trade_history.py <csv_path>
"""
from __future__ import annotations

from zhuli.db import get_conn, MAIN_DB

import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path

DB_PATH = MAIN_DB
SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT,            -- 對應 standard_daily_bar.ticker（需從名稱反查或人工填）
    name TEXT NOT NULL,     -- 股名（CSV 原樣，如「國巨*」）
    trade_date DATE NOT NULL,
    trade_type TEXT NOT NULL,  -- 沖買/現買/沖賣/現賣
    shares INTEGER NOT NULL,
    price REAL NOT NULL,
    cost REAL,
    net_amount REAL,
    fee REAL,
    tax REAL,
    order_no TEXT,
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(trade_date, order_no, trade_type, price)
);
CREATE INDEX IF NOT EXISTS idx_trade_history_date ON trade_history(trade_date);
CREATE INDEX IF NOT EXISTS idx_trade_history_ticker ON trade_history(ticker);
CREATE INDEX IF NOT EXISTS idx_trade_history_name ON trade_history(name);
"""


def init_schema(conn):
    conn.executescript(SCHEMA)
    conn.commit()


def lookup_ticker(conn, name: str) -> str | None:
    """從股名反查 ticker（去掉 * 後綴）."""
    clean = re.sub(r"[*＊]", "", name).strip()
    row = conn.execute("SELECT ticker FROM stock_name WHERE name=?", (clean,)).fetchone()
    return row[0] if row else None


def parse_int(s: str) -> int:
    return int(s.replace(",", "").replace('"', '').strip() or 0)


def parse_float(s: str) -> float:
    return float(s.replace(",", "").replace('"', '').strip() or 0)


def import_csv(csv_path: Path, db_path: Path = DB_PATH, dry_run: bool = False) -> dict:
    """匯入 CSV，回傳 {imported, skipped, no_ticker} stats."""
    conn = get_conn(db_path, readonly=False, timeout=15)
    init_schema(conn)

    stats = {"imported": 0, "skipped": 0, "no_ticker": [], "errors": []}

    with open(csv_path, encoding="utf-8") as f:
        # 跳過第一行說明文字
        first = f.readline()
        if "篩選" in first or "資料" in first:
            pass  # skip
        else:
            f.seek(0)

        reader = csv.DictReader(f)
        for row in reader:
            try:
                name = row.get("股名", "").strip()
                if not name:
                    continue
                trade_date = row["日期"].strip().replace("/", "-")
                trade_type = row["買賣別"].strip()
                shares = parse_int(row["成交股數"])
                price = parse_float(row["成交價"])
                cost = parse_float(row.get("成本", "0"))
                net_amount = parse_float(row.get("淨收付金額", "0"))
                fee = parse_float(row.get("手續費", "0"))
                tax = parse_float(row.get("交易稅", "0"))
                order_no = row.get("委託書號", "").strip()

                ticker = lookup_ticker(conn, name)
                if not ticker:
                    stats["no_ticker"].append(name)

                if not dry_run:
                    try:
                        conn.execute("""
                            INSERT INTO trade_history
                            (ticker, name, trade_date, trade_type, shares, price, cost,
                             net_amount, fee, tax, order_no)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?)
                        """, (ticker, name, trade_date, trade_type, shares, price, cost,
                              net_amount, fee, tax, order_no))
                        stats["imported"] += 1
                    except sqlite3.IntegrityError:
                        stats["skipped"] += 1
            except Exception as e:
                stats["errors"].append(f"{row}: {e}")

    if not dry_run:
        conn.commit()
    conn.close()
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    stats = import_csv(Path(args.csv_path), Path(args.db), args.dry_run)
    print(f"\n=== 匯入結果 ===")
    print(f"  Imported: {stats['imported']}")
    print(f"  Skipped (duplicate): {stats['skipped']}")
    print(f"  Errors: {len(stats['errors'])}")
    if stats["no_ticker"]:
        nt = sorted(set(stats["no_ticker"]))
        print(f"  名稱反查 ticker 失敗 ({len(nt)}): {nt[:10]}{'...' if len(nt)>10 else ''}")
    if stats["errors"]:
        print("\n  錯誤明細 (前 3):")
        for e in stats["errors"][:3]:
            print(f"    {e}")


if __name__ == "__main__":
    main()
