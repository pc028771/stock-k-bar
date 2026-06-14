"""資料完備性檢查 — 每次分析前必跑.

Usage:
    python scripts/zhuli/check_data_freshness.py
    python scripts/zhuli/check_data_freshness.py --date 2026-05-22

輸出：
    ✅ / ⚠️ / ❌ 每個資料表的最新日期與完整度
    若有缺漏明確列出需要補的指令
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

# 讓 zhuli 模組可被 import
_SCRIPTS = Path(__file__).parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from zhuli.db import get_conn, MAIN_DB
DB = MAIN_DB
def check(target_date: str | None = None) -> bool:
    today = target_date or date.today().isoformat()

    # 上一個交易日 — 用 FinMind 交易日曆（處理假日）
    try:
        from zhuli.trading_calendar import prev_trading_day, is_trading_day
        prev_str = prev_trading_day(today)
        if not prev_str:
            raise ValueError("無法取得上一個交易日")
        if not is_trading_day(today):
            print(f"ℹ️  {today} 非交易日，以上一個交易日 {prev_str} 為基準\n")
            today = prev_str
            prev_str = prev_trading_day(today)
    except Exception:
        # FinMind 無法使用時 fallback 到週曆
        from datetime import timedelta
        d = date.fromisoformat(today)
        prev = d - timedelta(days=3 if d.weekday() == 0 else 1)
        prev_str = prev.isoformat()

    con = get_conn(DB, timeout=5)

    print(f"\n=== 資料完備性檢查 (基準日: {today}) ===\n")
    ok = True

    checks = [
        ("日K (standard_daily_bar)",
         "SELECT MAX(trade_date), COUNT(DISTINCT ticker) FROM standard_daily_bar WHERE is_usable=1",
         "SELECT COUNT(DISTINCT ticker) FROM standard_daily_bar WHERE trade_date=?",
         2000),
        ("法人 (institutional_investors)",
         "SELECT MAX(trade_date), COUNT(DISTINCT ticker) FROM institutional_investors",
         "SELECT COUNT(DISTINCT ticker) FROM institutional_investors WHERE trade_date=?",
         1500),
    ]

    for label, max_sql, count_sql, min_tickers in checks:
        max_date, total = con.execute(max_sql).fetchone()
        n_today = con.execute(count_sql, (today,)).fetchone()[0]
        n_prev = con.execute(count_sql, (prev_str,)).fetchone()[0]

        if max_date == today and n_today >= min_tickers:
            status = "✅"
        elif max_date >= prev_str and n_prev >= min_tickers:
            status = "⚠️ "
            ok = False
        else:
            status = "❌"
            ok = False

        print(f"  {status} {label}")
        print(f"     最新: {max_date} ({total:,} total)")
        print(f"     今日({today}): {n_today:,}  前日({prev_str}): {n_prev:,}")

    con.close()

    if not ok:
        print(f"\n📋 補齊指令:")
        print(f"  python scripts/zhuli/sync_today.py --date {today}")

    print()
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    ok = check(args.date)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
