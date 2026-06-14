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

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

_REPO = Path(__file__).parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.db import get_conn, MAIN_DB

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
    """從 stock_info 反查 ticker — 嚴格 exact match 為主、避免「南亞」→「南亞科」誤命中。

    順序:
      1. exact match (含 *、-KY 等後綴)
      2. 去後綴後 exact match
      3. 都不中 → None (寧可空、不要亂寫)
    """
    cleaned = stock_name.replace("*", "").replace("-KY", "").strip()
    for q in (stock_name, cleaned):
        r = con.execute(
            "SELECT ticker FROM stock_info WHERE stock_name=? LIMIT 1", (q,),
        ).fetchone()
        if r:
            return r[0]
    return None


def _supersede_manual(
    con: sqlite3.Connection, *,
    trade_date: str, ticker: str | None, stock_name: str,
    action: str, shares: int, price: float,
) -> tuple[int, list[str]]:
    """CSV import 前、清掉對應的 manual 暫存。

    回傳 (auto_deleted_count, review_warnings)
      - Layer 1 (exact): date+ticker+action+shares+price 一致 → 直接刪
      - Layer 2 (fuzzy): date+ticker+action 一致、shares 或 price 接近 (差 ≤1%) → 刪 + log
      - Layer 3 (suspect): date+ticker 一致、其他差異 → 不刪、印警告
    """
    if not ticker:
        return 0, []
    deleted = 0
    warnings: list[str] = []

    # Layer 1: 完全一致
    cur = con.execute(
        "DELETE FROM broker_statement "
        "WHERE source='manual' AND trade_date=? AND ticker=? "
        "AND action=? AND shares=? AND ABS(price-?) < 0.005",
        (trade_date, ticker, action, shares, price),
    )
    if cur.rowcount > 0:
        deleted += cur.rowcount
        print(f"  ✅ Layer 1 supersede: {trade_date} {ticker} {stock_name} "
              f"{action} {shares} @ {price} (-{cur.rowcount} manual)")
        return deleted, warnings

    # Layer 2: 模糊 (同 action、shares 或 price 差 ≤1%)
    fuzzy_rows = con.execute(
        "SELECT id, shares, price FROM broker_statement "
        "WHERE source='manual' AND trade_date=? AND ticker=? AND action=?",
        (trade_date, ticker, action),
    ).fetchall()
    for fid, fshares, fprice in fuzzy_rows:
        shares_diff = abs(fshares - shares) / max(shares, 1)
        price_diff = abs(fprice - price) / max(price, 0.01)
        if shares_diff <= 0.01 or price_diff <= 0.01:
            con.execute("DELETE FROM broker_statement WHERE id=?", (fid,))
            deleted += 1
            print(f"  ⚠️ Layer 2 fuzzy supersede: {trade_date} {ticker} {stock_name} "
                  f"{action} manual({fshares}@{fprice}) ≈ CSV({shares}@{price})")

    # Layer 3: 同 date+ticker 但其他不符 → 不刪、警告
    suspects = con.execute(
        "SELECT id, action, shares, price FROM broker_statement "
        "WHERE source='manual' AND trade_date=? AND ticker=?",
        (trade_date, ticker),
    ).fetchall()
    for sid, sact, sshares, sprice in suspects:
        warnings.append(
            f"{trade_date} {ticker} {stock_name}: "
            f"manual({sact} {sshares}@{sprice}) vs CSV({action} {shares}@{price}) — 請手動 review (id={sid})"
        )
    return deleted, warnings


def import_csv(csv_path: Path, db: Path = DB) -> dict:
    con = get_conn(db, readonly=False)
    con.executescript(SCHEMA)

    inserted = 0
    skipped = 0
    superseded = 0
    not_matched: dict[str, int] = {}
    review_warnings: list[str] = []

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

            trade_date = _date_iso(row.get("日期", ""))
            shares = _to_int(row.get("成交股數", "0"))
            price = _to_float(row.get("成交價", "0"))
            action = row.get("買賣別", "").strip()

            # 3 層 supersede pass、先清 manual 暫存
            d, w = _supersede_manual(
                con, trade_date=trade_date, ticker=ticker, stock_name=stock_name,
                action=action, shares=shares, price=price,
            )
            superseded += d
            review_warnings.extend(w)

            try:
                con.execute(
                    """INSERT OR IGNORE INTO broker_statement (
                        stock_name, ticker, trade_date, shares, net_amount,
                        action, price, cost, fee, tax,
                        margin_amount, margin_self, interest, tax_amount,
                        short_fee, order_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        stock_name, ticker, trade_date,
                        shares,
                        _to_int(row.get("淨收付金額", "0")),
                        action,
                        price,
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
        "superseded": superseded,
        "not_matched_tickers": not_matched,
        "review_warnings": review_warnings,
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
    print(f"\n✅ Insert:     {result['inserted']}")
    print(f"⏭️  Skip:       {result['skipped']}")
    print(f"🧹 Superseded: {result['superseded']} (manual 暫存被 CSV 取代)")
    if result["not_matched_tickers"]:
        print(f"\n⚠️ 未匹配 ticker 的股名 ({len(result['not_matched_tickers'])} 種、stock_info 沒對應、需手填):")
        for name, n in sorted(result["not_matched_tickers"].items(),
                              key=lambda x: -x[1]):
            print(f"   {name:12} ({n} 筆)")
    if result["review_warnings"]:
        print(f"\n🚨 Review 警告 ({len(result['review_warnings'])} 筆同 date+ticker 的 manual 沒對到 CSV):")
        for w in result["review_warnings"]:
            print(f"   {w}")


if __name__ == "__main__":
    main()
