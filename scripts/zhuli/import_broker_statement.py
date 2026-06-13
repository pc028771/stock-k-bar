#!/usr/bin/env python3
"""[FOR AGENT USE] 國泰證券對帳單 CSV → DB import.

User 上傳對帳單 CSV、import 到 broker_statement table、避免重複上傳。

Schema:
    stock_name / ticker / trade_date / shares / net_amount / action /
    price / cost / fee / tax / margin_* / order_id

Usage:
    python scripts/zhuli/import_broker_statement.py <csv_path>
    python scripts/zhuli/import_broker_statement.py /Users/howard/.claude/uploads/.../xxx.csv
"""
from __future__ import annotations

from zhuli.db import get_conn, MAIN_DB

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

DB = MAIN_DB
SCHEMA = """
CREATE TABLE IF NOT EXISTS broker_statement (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_name TEXT NOT NULL,
    ticker TEXT,
    trade_date TEXT NOT NULL,
    shares INTEGER NOT NULL,
    net_amount INTEGER,
    action TEXT NOT NULL,
    price REAL NOT NULL,
    cost INTEGER,
    fee INTEGER,
    tax INTEGER,
    margin_amount INTEGER,
    margin_self INTEGER,
    interest INTEGER,
    tax_amount INTEGER,
    short_fee INTEGER,
    order_id TEXT,
    source TEXT DEFAULT '國泰證券',
    UNIQUE(trade_date, order_id, stock_name)
);
CREATE INDEX IF NOT EXISTS idx_broker_ticker ON broker_statement(ticker);
CREATE INDEX IF NOT EXISTS idx_broker_name ON broker_statement(stock_name);
CREATE INDEX IF NOT EXISTS idx_broker_date ON broker_statement(trade_date);
"""


def _to_int(s: str) -> int:
    """'1,000' → 1000、'' → 0、'-900,359' → -900359"""
    if not s or s.strip() == "":
        return 0
    return int(s.replace(",", "").replace('"', ""))


def _to_float(s: str) -> float:
    if not s or s.strip() == "":
        return 0.0
    return float(s.replace(",", ""))


def _date_iso(s: str) -> str:
    """'2026/06/04' → '2026-06-04'"""
    return s.replace("/", "-")


def lookup_ticker(con: sqlite3.Connection, stock_name: str) -> str | None:
    """從 stock_info 反查 ticker、模糊匹配股名。"""
    s = stock_name.replace("*", "").replace("-KY", "").strip()
    r = con.execute(
        "SELECT ticker FROM stock_info WHERE stock_name=? OR stock_name LIKE ? LIMIT 1",
        (stock_name, f"%{s}%"),
    ).fetchone()
    return r[0] if r else None


def import_csv(csv_path: Path, db: Path = DB) -> dict:
    con = get_conn(db, readonly=False)
    con.executescript(SCHEMA)

    inserted = 0
    skipped = 0
    not_matched: dict[str, int] = {}

    with csv_path.open(encoding="utf-8") as f:
        # 跳過第一行 (篩選結果說明)、第二行是 header
        first = f.readline()  # 「根據您篩選的結果...」
        if "篩選" not in first:
            f.seek(0)  # 沒第一行說明、回到開頭
        reader = csv.DictReader(f)
        for row in reader:
            stock_name = row.get("股名", "").strip()
            if not stock_name:
                continue
            ticker = lookup_ticker(con, stock_name)
            if not ticker:
                not_matched[stock_name] = not_matched.get(stock_name, 0) + 1

            try:
                con.execute(
                    """INSERT OR IGNORE INTO broker_statement (
                        stock_name, ticker, trade_date, shares, net_amount,
                        action, price, cost, fee, tax,
                        margin_amount, margin_self, interest, tax_amount,
                        short_fee, order_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        stock_name, ticker, _date_iso(row.get("日期", "")),
                        _to_int(row.get("成交股數", "0")),
                        _to_int(row.get("淨收付金額", "0")),
                        row.get("買賣別", "").strip(),
                        _to_float(row.get("成交價", "0")),
                        _to_int(row.get("成本", "0")),
                        _to_int(row.get("手續費", "0")),
                        _to_int(row.get("交易稅", "0")),
                        _to_int(row.get("融資金額/券擔保品", "0")),
                        _to_int(row.get("資自備款/券保證金", "0")),
                        _to_int(row.get("利息", "0")),
                        _to_int(row.get("稅款", "0")),
                        _to_int(row.get("券手續費/標借費", "0")),
                        row.get("委託書號", "").strip(),
                    ),
                )
                if con.total_changes:
                    inserted += 1
                else:
                    skipped += 1
            except Exception as e:
                print(f"  ⚠️ skip row {stock_name} {row.get('日期', '')}: {e}")
                skipped += 1

    con.commit()
    con.close()
    return {
        "inserted": inserted,
        "skipped": skipped,
        "not_matched_tickers": not_matched,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="國泰證券對帳單 CSV import")
    p.add_argument("csv_path", help="CSV 檔案路徑")
    args = p.parse_args()

    path = Path(args.csv_path)
    if not path.exists():
        print(f"❌ 檔案不存在: {path}")
        sys.exit(1)

    result = import_csv(path)
    print(f"\n✅ Insert: {result['inserted']}")
    print(f"⏭️  Skip:   {result['skipped']}")
    if result["not_matched_tickers"]:
        print(f"\n⚠️ 未匹配 ticker 的股名 ({len(result['not_matched_tickers'])} 種):")
        for name, n in sorted(result["not_matched_tickers"].items(),
                              key=lambda x: -x[1]):
            print(f"   {name:12} ({n} 筆)")


if __name__ == "__main__":
    main()
