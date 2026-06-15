"""Backfill 投信（投資信託）及外資每日買賣超資料至 SQLite DB。

Creates the `institutional_investors` table (if not exists) and populates
investment-trust and foreign-investor net-buy data from FinMind,
covering 2024-01-01 ~ today.

資料來源: FinMind dataset `TaiwanStockInstitutionalInvestorsBuySell`
           透過 stock-analysis-system 的 FinMindClient（含 throttle）。
           ⚠️ 禁止直接 curl FinMind API。

Table schema:
    ticker        TEXT  -- 股票代號
    trade_date    DATE  -- 日期 YYYY-MM-DD
    sitc_buy      REAL  -- 投信買進張數
    sitc_sell     REAL  -- 投信賣出張數
    sitc_net      REAL  -- 投信淨買超（張）= sitc_buy - sitc_sell
    foreign_buy   REAL  -- 外資買進張數
    foreign_sell  REAL  -- 外資賣出張數
    foreign_net   REAL  -- 外資淨買超（張）= foreign_buy - foreign_sell

Usage:
    python scripts/zhuli/backfill_institutional.py [--db PATH] [--dry-run]
    python scripts/zhuli/backfill_institutional.py --start-date 2020-06-01
    python scripts/zhuli/backfill_institutional.py --tickers 3707 3552 --dry-run

Note:
    Rate limit: FinMind Sponsor tier 4500 req/hr — 1 request per ticker.
    每批 50 檔後 sleep 2s；每 500 檔後 sleep 30s。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd

# ── 路徑設定 ──────────────────────────────────────────────────────────────────
_WORKTREE = Path(__file__).parent.parent.parent   # phase1-scanner/
_SCRIPTS_DIR = _WORKTREE / "scripts"
_SYS_DIR = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_WORKTREE), str(_SCRIPTS_DIR), str(_SYS_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.db import get_conn
from clients.finmind_client import get_institutional  # noqa: E402
from kline.bars import DEFAULT_DB_PATH               # noqa: E402

# ── 常數 ──────────────────────────────────────────────────────────────────────
DEFAULT_START = "2024-01-01"   # 確保「前 60 天」窗口從 2024-03-01 起都夠用
# 史上案例需要 2020 年資料 (漢磊 3707, 同致 3552)，backfill 額外支援

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS institutional_investors (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker       TEXT    NOT NULL,
    trade_date   DATE    NOT NULL,
    sitc_buy     REAL    DEFAULT 0,
    sitc_sell    REAL    DEFAULT 0,
    sitc_net     REAL    DEFAULT 0,
    foreign_buy  REAL    DEFAULT 0,
    foreign_sell REAL    DEFAULT 0,
    foreign_net  REAL    DEFAULT 0,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, trade_date)
);
"""

# Migration: add foreign_* columns to existing tables that predate this schema
MIGRATE_FOREIGN_COLS_SQL = [
    "ALTER TABLE institutional_investors ADD COLUMN foreign_buy  REAL DEFAULT 0",
    "ALTER TABLE institutional_investors ADD COLUMN foreign_sell REAL DEFAULT 0",
    "ALTER TABLE institutional_investors ADD COLUMN foreign_net  REAL DEFAULT 0",
]

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_inst_inv_ticker_date
    ON institutional_investors (ticker, trade_date);
"""


# ── DB 工具 ───────────────────────────────────────────────────────────────────

def ensure_table(conn: sqlite3.Connection) -> None:
    """建立 institutional_investors 表（若不存在），並遷移 foreign_* 欄位。"""
    conn.execute(CREATE_TABLE_SQL)
    conn.execute(CREATE_INDEX_SQL)
    # Migration: 既有表可能缺少 foreign_* 欄位（Phase 1 J scanner 初版）
    existing_cols = {c[1] for c in conn.execute("PRAGMA table_info(institutional_investors)").fetchall()}
    for alter_sql in MIGRATE_FOREIGN_COLS_SQL:
        col_name = alter_sql.split("ADD COLUMN")[1].strip().split()[0]
        if col_name not in existing_cols:
            conn.execute(alter_sql)
    conn.commit()


def get_existing_tickers(conn: sqlite3.Connection, start_date: str) -> set[str]:
    """取得已有資料（且覆蓋 start_date 之後的）的 ticker 集合。"""
    cur = conn.execute(
        "SELECT DISTINCT ticker FROM institutional_investors WHERE trade_date >= ?",
        (start_date,),
    )
    return {row[0] for row in cur.fetchall()}


def upsert_rows(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """INSERT OR REPLACE 多筆資料；回傳寫入筆數。

    支援 sitc_* 與 foreign_* 欄位，舊版資料若缺少 foreign_* 以 0 填補。
    """
    if not rows:
        return 0
    # 確保每筆都有 foreign_* 欄位（向後相容）
    for row in rows:
        row.setdefault("foreign_buy", 0.0)
        row.setdefault("foreign_sell", 0.0)
        row.setdefault("foreign_net", 0.0)
    conn.executemany(
        """
        INSERT OR REPLACE INTO institutional_investors
            (ticker, trade_date, sitc_buy, sitc_sell, sitc_net,
             foreign_buy, foreign_sell, foreign_net)
        VALUES (:ticker, :trade_date, :sitc_buy, :sitc_sell, :sitc_net,
                :foreign_buy, :foreign_sell, :foreign_net)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


# ── 資料處理 ──────────────────────────────────────────────────────────────────

def _parse_inst_df(raw: pd.DataFrame, ticker: str) -> list[dict]:
    """將 get_institutional() 回傳的 DataFrame 轉成 DB insert rows。

    FinMind v4 回傳 long-form schema (2026 起):
        [date, stock_id, buy, name, sell]
      - 每日每法人一列 (外資 / 投信 / 自營商 / 外資自營)
      - 沒有預先算好 net、需自行 buy - sell

    我們要萃取投信（sitc_*）與外資（foreign_*）、合併為每日一筆。

    ⚠️ FinMind 回傳單位為「股（shares）」、需除以 1000 轉換為「張（lots）」。
       課程定義與 scanner 門檻均以「張」計（如「2 萬張」「1/3 成交量」）。
    """
    if raw.empty:
        return []

    if not {"name", "buy", "sell", "date"}.issubset(raw.columns):
        return []

    # 投信 (Investment Trust)
    sitc_rows = raw[raw["name"].str.contains("投信|Investment_Trust", na=False)].copy()
    sitc_daily = (
        sitc_rows.groupby("date")[["buy", "sell"]].sum()
        .rename(columns={"buy": "sitc_buy", "sell": "sitc_sell"})
        .reset_index()
    )
    sitc_daily["sitc_net"] = sitc_daily["sitc_buy"] - sitc_daily["sitc_sell"]

    # 外資 (含外資自營)
    foreign_rows = raw[raw["name"].str.contains("外資|Foreign", na=False)].copy()
    foreign_daily = (
        foreign_rows.groupby("date")[["buy", "sell"]].sum()
        .rename(columns={"buy": "foreign_buy", "sell": "foreign_sell"})
        .reset_index()
    )
    foreign_daily["foreign_net"] = foreign_daily["foreign_buy"] - foreign_daily["foreign_sell"]

    # 從 raw 取所有 unique dates 當 base
    daily_nets = raw[["date"]].drop_duplicates().copy()
    daily_nets = daily_nets.merge(sitc_daily, on="date", how="left")
    daily_nets = daily_nets.merge(foreign_daily, on="date", how="left")

    daily_nets["ticker"] = ticker
    daily_nets = daily_nets.rename(columns={"date": "trade_date"})
    # Timestamp → str for sqlite
    daily_nets["trade_date"] = daily_nets["trade_date"].astype(str).str[:10]

    # Fill NaN with 0
    for col in ("sitc_buy", "sitc_sell", "sitc_net", "foreign_buy", "foreign_sell", "foreign_net"):
        if col not in daily_nets.columns:
            daily_nets[col] = 0.0
        daily_nets[col] = daily_nets[col].fillna(0)

    # 單位換算：FinMind 回傳股（shares）→ 課程與 scanner 用張（lots = 1000股）
    for col in ("sitc_buy", "sitc_sell", "sitc_net", "foreign_buy", "foreign_sell", "foreign_net"):
        daily_nets[col] = daily_nets[col] / 1000.0

    return daily_nets[[
        "ticker", "trade_date",
        "sitc_buy", "sitc_sell", "sitc_net",
        "foreign_buy", "foreign_sell", "foreign_net",
    ]].to_dict("records")


# ── 主流程 ────────────────────────────────────────────────────────────────────

def backfill(
    db_path: Path = DEFAULT_DB_PATH,
    start_date: str = DEFAULT_START,
    end_date: str | None = None,
    tickers: list[str] | None = None,
    skip_existing: bool = True,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict:
    """主 backfill 函式。

    Args:
        db_path:       SQLite DB 路徑
        start_date:    撈取起始日期（YYYY-MM-DD）
        end_date:      撈取結束日期（None = 今天）
        tickers:       指定 ticker 清單；None = 從 DB 取所有股票
        skip_existing: True = 已有資料的 ticker 略過（增量更新請改 False）
        dry_run:       True = 不寫入 DB（只顯示會撈哪些）
        verbose:       True = 詳細輸出

    Returns:
        dict: {fetched, inserted, skipped, errors}
    """
    import os, shutil, tempfile

    if end_date is None:
        end_date = pd.Timestamp.today().strftime("%Y-%m-%d")

    # 拷貝 DB 到 /tmp 避免 iCloud 磁碟 I/O 問題（寫入時用原路徑）
    try:
        tmp = Path(tempfile.gettempdir()) / f"inst_backfill_{os.getpid()}.sqlite"
        shutil.copy2(db_path, tmp)
        read_conn = sqlite3.connect(str(tmp), timeout=15)
    except Exception:
        # fallback 純讀 ticker 清單、不需 RW lock
        read_conn = get_conn(db_path, timeout=15)

    write_conn = get_conn(db_path, readonly=False, timeout=30)
    ensure_table(write_conn)

    # 取得全部 ticker 清單
    if tickers is None:
        cur = read_conn.execute(
            "SELECT DISTINCT ticker FROM standard_daily_bar WHERE is_usable=1"
        )
        all_tickers = sorted(r[0] for r in cur.fetchall())
    else:
        all_tickers = sorted(tickers)
    read_conn.close()

    # 跳過已有資料的 ticker
    existing_set: set[str] = set()
    if skip_existing:
        existing_set = get_existing_tickers(write_conn, start_date)
        if verbose:
            print(f"[skip_existing] {len(existing_set)} tickers already have data ≥ {start_date}")

    to_fetch = [t for t in all_tickers if t not in existing_set]
    if verbose or dry_run:
        print(f"Tickers to fetch: {len(to_fetch)} (total={len(all_tickers)}, existing={len(existing_set)})")
        print(f"Date range: {start_date} ~ {end_date}")

    if dry_run:
        print("[dry-run] No data written.")
        write_conn.close()
        return {"fetched": 0, "inserted": 0, "skipped": len(existing_set), "errors": 0}

    stats = {"fetched": 0, "inserted": 0, "skipped": len(existing_set), "errors": 0}

    import os as _os
    _finmind_token = _os.environ.get("FINMIND_TOKEN", "")
    for i, ticker in enumerate(to_fetch, start=1):
        try:
            # 使用 stock-analysis-system 的 get_institutional（含 throttle）
            # ⚠️ 禁止直接 curl FinMind API
            raw = get_institutional(ticker, start_date, end_date, token=_finmind_token)
            stats["fetched"] += 1

            rows = _parse_inst_df(raw, ticker)
            n = upsert_rows(write_conn, rows)
            stats["inserted"] += n

            if verbose:
                print(f"  [{i}/{len(to_fetch)}] {ticker}: {n} rows")

        except Exception as exc:
            stats["errors"] += 1
            print(f"  [{i}/{len(to_fetch)}] {ticker}: ERROR — {exc}")

        # Rate limit 保護：每 50 檔 sleep 2s，每 500 檔 sleep 30s
        if i % 500 == 0:
            if verbose:
                print(f"  [batch pause] Processed {i} tickers, sleeping 30s …")
            time.sleep(30)
        elif i % 50 == 0:
            time.sleep(2)

    write_conn.close()

    # 摘要
    print(
        f"完成: fetched={stats['fetched']}, inserted={stats['inserted']}, "
        f"skipped={stats['skipped']}, errors={stats['errors']}"
    )
    return stats


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="backfill_institutional",
        description="Backfill 投信買賣超資料至 SQLite DB (FinMind → institutional_investors 表)",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH,
                        help="SQLite DB 路徑")
    parser.add_argument("--start-date", default=DEFAULT_START, metavar="YYYY-MM-DD",
                        help=f"資料起始日期（預設 {DEFAULT_START}）")
    parser.add_argument("--end-date", default=None, metavar="YYYY-MM-DD",
                        help="資料結束日期（預設今天）")
    parser.add_argument("--tickers", nargs="*", metavar="TICKER",
                        help="只撈指定 ticker；不填 = 全部")
    parser.add_argument("--no-skip-existing", action="store_true",
                        help="不略過已有資料的 ticker（強制重撈）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只顯示會撈哪些，不寫入 DB")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="詳細輸出每檔結果")

    args = parser.parse_args()

    backfill(
        db_path=args.db,
        start_date=args.start_date,
        end_date=args.end_date,
        tickers=args.tickers,
        skip_existing=not args.no_skip_existing,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
