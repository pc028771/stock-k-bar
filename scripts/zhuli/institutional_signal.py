"""三大法人粗篩 — 快速無 API call 偵測投信 / 外資動向.

用 standard SQLite institutional_investors 表（已 sync 每日）、
做 stage 1 篩選後、再由 contrarian_strong_scanner stage 2 走 broker 細抓.

Public API:
    institutional_5d(ticker, target_date, conn) -> dict
        {sitc_5d, foreign_5d, sitc_streak_buy, foreign_streak_buy,
         sitc_score, foreign_score, total_score}

評分（max +6）：
    投信 5d net ≥ 2000 張 → +3 (大買)
            ≥ 800 張  → +2 (中買)
            ≥ 200 張  → +1 (微買)
    投信連續 3 日買超       → +1 額外（穩定買盤）

    外資 5d net ≥ 10000 張 → +2 (集中買)
            ≥ 3000 張  → +1 (買進)
    外資連續 3 日買超       → +1 額外
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta


def _recent_trading_dates(conn: sqlite3.Connection, ticker: str, target_date: str, n: int = 5) -> list[str]:
    rows = conn.execute(
        """SELECT trade_date FROM institutional_investors
           WHERE ticker=? AND trade_date <= ?
           ORDER BY trade_date DESC LIMIT ?""",
        (ticker, target_date, n),
    ).fetchall()
    return [r[0] for r in rows]


def institutional_5d(ticker: str, target_date: str, conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        """SELECT trade_date, sitc_net, foreign_net FROM institutional_investors
           WHERE ticker=? AND trade_date <= ?
           ORDER BY trade_date DESC LIMIT 5""",
        (ticker, target_date),
    ).fetchall()

    if not rows:
        return {
            "sitc_5d": 0, "foreign_5d": 0,
            "sitc_streak_buy": 0, "foreign_streak_buy": 0,
            "sitc_score": 0, "foreign_score": 0, "total_score": 0,
            "details": [],
        }

    # 反向（由舊到新）
    rows = [(r[0], r[1] or 0, r[2] or 0) for r in reversed(rows)]
    sitc_5d = sum(r[1] for r in rows)
    foreign_5d = sum(r[2] for r in rows)

    # 連續買超 streak（從最近一日往前）
    sitc_streak = 0
    foreign_streak = 0
    for r in reversed(rows):
        if r[1] > 0:
            sitc_streak += 1
        else:
            break
    for r in reversed(rows):
        if r[2] > 0:
            foreign_streak += 1
        else:
            break

    # 投信評分
    sitc_score = 0
    if sitc_5d >= 2000: sitc_score += 3
    elif sitc_5d >= 800: sitc_score += 2
    elif sitc_5d >= 200: sitc_score += 1
    if sitc_streak >= 3: sitc_score += 1

    # 外資評分
    foreign_score = 0
    if foreign_5d >= 10000: foreign_score += 2
    elif foreign_5d >= 3000: foreign_score += 1
    if foreign_streak >= 3: foreign_score += 1

    return {
        "sitc_5d": int(sitc_5d),
        "foreign_5d": int(foreign_5d),
        "sitc_streak_buy": sitc_streak,
        "foreign_streak_buy": foreign_streak,
        "sitc_score": sitc_score,
        "foreign_score": foreign_score,
        "total_score": sitc_score + foreign_score,
        "details": [(r[0], int(r[1]), int(r[2])) for r in rows],
    }


def main():
    import sys
    from pathlib import Path
    if len(sys.argv) < 3:
        print("Usage: institutional_signal.py <ticker> <date>")
        sys.exit(1)
    ticker, d = sys.argv[1], sys.argv[2]
    from zhuli.db import get_conn
    conn = get_conn()
    r = institutional_5d(ticker, d, conn)
    print(f"\n=== {ticker} 三大法人 5d 訊號 (截至 {d}) ===")
    print(f"投信 5d 淨買: {r['sitc_5d']:+,} 張 / streak {r['sitc_streak_buy']} 日 → {r['sitc_score']} 分")
    print(f"外資 5d 淨買: {r['foreign_5d']:+,} 張 / streak {r['foreign_streak_buy']} 日 → {r['foreign_score']} 分")
    print(f"合計: {r['total_score']} 分")
    print("\n每日明細:")
    for d2, s, f in r["details"]:
        print(f"  {d2}  投信 {s:+,} / 外資 {f:+,}")


if __name__ == "__main__":
    main()
