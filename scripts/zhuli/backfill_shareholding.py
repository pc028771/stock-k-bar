"""Backfill stock_shareholding (NumberOfSharesIssued) 從 FinMind.

對全部 institutional_investors 表中的 ticker × 2024-2026 backfill。
用於 I 投信跟單 scanner 計算「5 日累計買超 / 股本」需要的股本資料。

Usage:
    python scripts/zhuli/backfill_shareholding.py [--start 2024-01-01] [--end 2026-05-19]
                                                   [--limit N] [--tickers 2330,2454]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_WORKTREE = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_WORKTREE / "scripts"))
from kline.bars import DEFAULT_DB_PATH

from zhuli.db import get_conn
from common.clients.finmind_client import get_client

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2026-05-19")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--tickers", help="comma-separated")
    ap.add_argument("--sleep-every", type=int, default=10, help="(deprecated) rate limit now handled by common.finmind_client")
    args = ap.parse_args()

    # 取得 ticker 清單
    with get_conn(DEFAULT_DB_PATH, readonly=False, timeout=30) as conn:
        if args.tickers:
            tickers = args.tickers.split(",")
        else:
            cur = conn.execute(
                "SELECT DISTINCT ticker FROM institutional_investors ORDER BY ticker"
            )
            tickers = [r[0] for r in cur.fetchall()]
        if args.limit:
            tickers = tickers[: args.limit]

        print(f"Backfill {len(tickers)} tickers × {args.start} ~ {args.end}")

        # 確保表存在
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_shareholding (
                ticker TEXT, trade_date TEXT, shares_issued INTEGER,
                PRIMARY KEY (ticker, trade_date)
            )
        """)
        conn.commit()

        total = 0
        fails = []
        for i, t in enumerate(tickers, 1):
            try:
                df = get_client().fetch_dataset(
                    dataset="TaiwanStockShareholding",
                    data_id=t,
                    start_date=args.start,
                    end_date=args.end,
                    bypass_cache=True,
                )
                d = df.to_dict("records") if not df.empty else []
                rows = [
                    (t, row["date"], row["NumberOfSharesIssued"])
                    for row in d
                    if row.get("NumberOfSharesIssued")
                ]
                if rows:
                    conn.executemany(
                        "INSERT OR REPLACE INTO stock_shareholding VALUES (?,?,?)",
                        rows,
                    )
                    total += len(rows)
                if i % 50 == 0:
                    conn.commit()
                    print(f"  [{i}/{len(tickers)}] {t}: {len(rows)} rows (cumulative {total:,})")
            except Exception as exc:
                fails.append((t, str(exc)[:50]))
        conn.commit()

    print(f"\nDone: {total:,} rows inserted")
    if fails:
        print(f"Fails: {len(fails)} (first 10: {fails[:10]})")


if __name__ == "__main__":
    main()
