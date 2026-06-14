"""批次 re-sync institutional_investors 4-5 月、修 unit bug.

借用 sync_today 的 fetch_institutional_whole（已知有 /1000 正確處理）.
INSERT OR REPLACE → 覆寫舊資料.

Usage:
    python scripts/zhuli/resync_institutional.py --start 2026-04-01 --end 2026-05-25
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

_REPO = Path(__file__).parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts"), "/Users/howard/Repository/stock-analysis-system"]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.db import get_conn, MAIN_DB
from zhuli.sync_today import fetch_institutional_whole, upsert_institutional

DB = MAIN_DB
def get_trading_dates(start: str, end: str) -> list[str]:
    """從 standard_daily_bar 取既有交易日（避免拉假日）."""
    conn = get_conn(DB)
    rows = conn.execute(
        "SELECT DISTINCT trade_date FROM standard_daily_bar WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date",
        (start, end),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_valid_tickers() -> set:
    conn = get_conn(DB)
    rows = conn.execute("SELECT DISTINCT ticker FROM stock_info").fetchall()
    conn.close()
    return {r[0] for r in rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-04-01")
    ap.add_argument("--end", default="2026-05-25")
    args = ap.parse_args()

    token = os.environ.get("FINMIND_TOKEN")
    if not token:
        print("ERROR: FINMIND_TOKEN missing")
        sys.exit(1)

    dates = get_trading_dates(args.start, args.end)
    print(f"Re-sync {len(dates)} 個交易日: {dates[0]} → {dates[-1]}")

    valid_tickers = get_valid_tickers()
    print(f"Valid tickers: {len(valid_tickers)}")

    total = 0
    for i, d in enumerate(dates):
        print(f"\n[{i+1}/{len(dates)}] {d}")
        try:
            df = fetch_institutional_whole(d, token, valid_tickers)
            if not df.empty:
                n = upsert_institutional(df, DB)
                total += n
                print(f"  → upserted {n} tickers")
        except Exception as exc:
            print(f"  ERROR: {exc}")
        time.sleep(0.5)  # rate limit gentle

    print(f"\n完成、共 upserted {total} 筆")


if __name__ == "__main__":
    main()
