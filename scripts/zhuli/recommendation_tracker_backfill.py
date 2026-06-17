"""
推薦命中率回填腳本 (recommendation_tracker_backfill.py) v2

用法:
  python scripts/zhuli/recommendation_tracker_backfill.py --date 2026-06-04
  python scripts/zhuli/recommendation_tracker_backfill.py --all

讀取 docs/主力大課程/daily_watchlist/YYYY-MM-DD.json，
從 standard_daily_bar 查詢 T+1/3/5/10 收盤，計算 ret_*，
UPSERT 到 recommendation_outcomes（v2 schema）。

name/sources/sector/tactic 不重複存，需要時 join JSON 即可。
"""

import argparse
import json
import sqlite3
import os
import sys
import glob
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# 加 scripts/ 到 sys.path 才能 import zhuli.* (launchd 環境沒設 PYTHONPATH)
_scripts_dir = Path(__file__).parent.parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from zhuli.db import get_conn

DB_PATH = os.path.expanduser("~/four_seasons_local/data.sqlite")
WATCHLIST_DIR = Path(__file__).parent.parent.parent / "docs" / "主力大課程" / "daily_watchlist"

# 確保 table 存在（第一次跑時自動建立）
DDL = """
CREATE TABLE IF NOT EXISTS recommendation_outcomes (
  recommend_date TEXT NOT NULL,
  ticker         TEXT NOT NULL,
  priority       INT,
  primary_source TEXT,
  ret_t1         REAL,
  ret_t3         REAL,
  ret_t5         REAL,
  ret_t10        REAL,
  max_gain_5d    REAL,
  max_dd_5d      REAL,
  schema_version INT NOT NULL DEFAULT 1,
  scanner_commit TEXT,
  extras         TEXT,
  backfilled_at  TEXT,
  PRIMARY KEY (recommend_date, ticker)
);
CREATE INDEX IF NOT EXISTS idx_rec_outcomes_priority ON recommendation_outcomes(priority);
CREATE INDEX IF NOT EXISTS idx_rec_outcomes_source   ON recommendation_outcomes(primary_source);
"""


def get_connection() -> sqlite3.Connection:
    conn = get_conn(DB_PATH, readonly=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    return conn


def get_git_short_hash() -> str | None:
    """取得目前 repo 的 git short hash（7 字）。"""
    try:
        result = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(Path(__file__).parent.parent.parent),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        return result[:7] if result else None
    except Exception:
        return None


def get_trade_dates_after(conn: sqlite3.Connection, ref_date: str, n: int) -> list[str]:
    """取得 ref_date 之後第 1~n 個交易日（跳假日、用全市場 DISTINCT）。"""
    rows = conn.execute(
        """
        SELECT DISTINCT trade_date
        FROM standard_daily_bar
        WHERE trade_date > ?
        ORDER BY trade_date ASC
        LIMIT ?
        """,
        (ref_date, n),
    ).fetchall()
    return [r["trade_date"] for r in rows]


def get_close(conn: sqlite3.Connection, ticker: str, trade_date: str) -> float | None:
    """查單日收盤價，不存在回 None。"""
    row = conn.execute(
        "SELECT close FROM standard_daily_bar WHERE ticker=? AND trade_date=?",
        (ticker, trade_date),
    ).fetchone()
    return row["close"] if row else None


def get_high_low(conn: sqlite3.Connection, ticker: str, trade_date: str) -> tuple[float | None, float | None]:
    """查單日最高 / 最低價，用於算 max_gain / max_dd。"""
    row = conn.execute(
        "SELECT high, low FROM standard_daily_bar WHERE ticker=? AND trade_date=?",
        (ticker, trade_date),
    ).fetchone()
    if row is None:
        return None, None
    return row["high"], row["low"]


def compute_outcomes(conn: sqlite3.Connection, ticker: str, recommend_date: str, ref_close: float) -> dict:
    """計算 T+1/3/5/10 ret 及 5 日內最大漲跌幅（% 形式）。"""
    # 取 10 個交易日（夠算 T+1~T+10）
    dates = get_trade_dates_after(conn, recommend_date, 10)

    def close_at(n: int) -> float | None:
        if len(dates) < n:
            return None
        return get_close(conn, ticker, dates[n - 1])

    def ret(close_val: float | None) -> float | None:
        if close_val is None or not ref_close:
            return None
        return round((close_val - ref_close) / ref_close * 100, 4)

    # 5 日內最高漲幅 / 最大回撤（用 high/low）
    max_gain: float | None = None
    max_dd: float | None = None
    if ref_close:
        for n in range(1, 6):
            if len(dates) < n:
                break
            high, low = get_high_low(conn, ticker, dates[n - 1])
            if high is not None:
                gain = (high - ref_close) / ref_close * 100
                max_gain = max(max_gain, gain) if max_gain is not None else gain
            if low is not None:
                dd = (low - ref_close) / ref_close * 100
                max_dd = min(max_dd, dd) if max_dd is not None else dd
        if max_gain is not None:
            max_gain = round(max_gain, 4)
        if max_dd is not None:
            max_dd = round(max_dd, 4)

    return {
        "ret_t1":     ret(close_at(1)),
        "ret_t3":     ret(close_at(3)),
        "ret_t5":     ret(close_at(5)),
        "ret_t10":    ret(close_at(10)),
        "max_gain_5d": max_gain,
        "max_dd_5d":   max_dd,
    }


def backfill_date(conn: sqlite3.Connection, date_str: str, git_hash: str | None) -> int:
    """回填單日 watchlist，回傳寫入/更新筆數。"""
    json_path = WATCHLIST_DIR / f"{date_str}.json"
    if not json_path.exists():
        print(f"  [skip] {date_str}: 找不到 {json_path}")
        return 0

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    candidates = data.get("candidates", [])
    if not candidates:
        print(f"  [skip] {date_str}: candidates 為空")
        return 0

    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    written = 0

    for c in candidates:
        ticker = c.get("ticker", "")
        if not ticker:
            continue

        ref_close = c.get("ref_close")
        outcomes = compute_outcomes(conn, ticker, date_str, ref_close)

        # primary_source = sources[0]
        srcs = c.get("sources", [])
        primary_source = srcs[0] if srcs else None

        # extras: 預留 dict，存 dist_ma10_pct 作為示範（可移除 / 擴充）
        extras = json.dumps({
            "dist_ma10_pct": c.get("dist_ma10_pct"),
        }, ensure_ascii=False)

        conn.execute(
            """
            INSERT INTO recommendation_outcomes (
              recommend_date, ticker,
              priority, primary_source,
              ret_t1, ret_t3, ret_t5, ret_t10,
              max_gain_5d, max_dd_5d,
              schema_version, scanner_commit, extras, backfilled_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?,?)
            ON CONFLICT(recommend_date, ticker) DO UPDATE SET
              ret_t1         = COALESCE(excluded.ret_t1,     ret_t1),
              ret_t3         = COALESCE(excluded.ret_t3,     ret_t3),
              ret_t5         = COALESCE(excluded.ret_t5,     ret_t5),
              ret_t10        = COALESCE(excluded.ret_t10,    ret_t10),
              max_gain_5d    = COALESCE(excluded.max_gain_5d, max_gain_5d),
              max_dd_5d      = COALESCE(excluded.max_dd_5d,  max_dd_5d),
              backfilled_at  = excluded.backfilled_at
            """,
            (
                date_str, ticker,
                c.get("priority"), primary_source,
                outcomes["ret_t1"], outcomes["ret_t3"],
                outcomes["ret_t5"], outcomes["ret_t10"],
                outcomes["max_gain_5d"], outcomes["max_dd_5d"],
                git_hash, extras, now_ts,
            ),
        )
        written += 1

    conn.commit()
    print(f"  [{date_str}] {written} 筆寫入/更新")
    return written


def print_summary(conn: sqlite3.Connection):
    """印統計摘要。"""
    rows = conn.execute("""
        SELECT
            recommend_date,
            COUNT(*) AS total,
            SUM(CASE WHEN ret_t1 IS NOT NULL THEN 1 ELSE 0 END) AS has_t1,
            SUM(CASE WHEN ret_t1 > 0 THEN 1 ELSE 0 END) AS up_t1,
            ROUND(AVG(CASE WHEN ret_t1 IS NOT NULL THEN ret_t1 END), 2) AS avg_ret_t1
        FROM recommendation_outcomes
        GROUP BY recommend_date
        ORDER BY recommend_date
    """).fetchall()

    print("\n=== Backfill 統計摘要 ===")
    print(f"{'日期':<12} {'總筆數':>6} {'有T+1':>6} {'上漲':>6} {'平均T+1%':>10}")
    print("-" * 46)
    for r in rows:
        up_rate = f"{r['up_t1']}/{r['has_t1']}" if r['has_t1'] else "N/A"
        avg = f"{r['avg_ret_t1']:+.2f}%" if r['avg_ret_t1'] is not None else "N/A"
        print(f"{r['recommend_date']:<12} {r['total']:>6} {r['has_t1']:>6} {up_rate:>6} {avg:>10}")

    total = conn.execute("SELECT COUNT(*) FROM recommendation_outcomes").fetchone()[0]
    print(f"\n總計: {total} 筆")


def main():
    parser = argparse.ArgumentParser(description="推薦命中率回填腳本 v2")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--date", help="指定日期 YYYY-MM-DD")
    group.add_argument("--all", action="store_true", help="回填所有 daily_watchlist")
    args = parser.parse_args()

    conn = get_connection()
    git_hash = get_git_short_hash()
    print(f"[git] scanner_commit = {git_hash}")

    if args.all:
        json_files = sorted(glob.glob(str(WATCHLIST_DIR / "*.json")))
        dates = [Path(f).stem for f in json_files if Path(f).stem.count("-") == 2]
        print(f"找到 {len(dates)} 個 watchlist 日期: {dates}")
        total = 0
        for d in dates:
            total += backfill_date(conn, d, git_hash)
        print(f"\n全部完成，共 {total} 筆")
    else:
        backfill_date(conn, args.date, git_hash)

    print_summary(conn)
    conn.close()


if __name__ == "__main__":
    main()
