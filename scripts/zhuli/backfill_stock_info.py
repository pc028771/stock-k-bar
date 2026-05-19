"""Backfill 股票基本資料（含產業分類）至 SQLite DB。

從 FinMind TaiwanStockInfo 撈取 stock_id、stock_name、industry_category，
寫入 `stock_info` 表，供 A 大波段 swing_breakout scanner 判斷族群密度使用。

Table schema（自動建立）：
    ticker            TEXT PRIMARY KEY  — 股票代號
    stock_name        TEXT              — 股票名稱
    industry_category TEXT              — 產業分類（如「半導體業」「鋼鐵工業」）
    type              TEXT              — twse / tpex
    updated_at        TIMESTAMP         — 最後更新時間

資料來源: FinMind TaiwanStockInfo（免費 tier 支援）
         透過 stock-analysis-system 的 fetch_stock_info()（含 TTL 快取）。
         ⚠️ 禁止直接 curl FinMind API。

Usage:
    python scripts/zhuli/backfill_stock_info.py [--db PATH] [--dry-run]
    python scripts/zhuli/backfill_stock_info.py --force    # 忽略 cache，強制重撈

Note:
    fetch_stock_info() 內建 7 天 TTL 快取（~/.cache/finmind/_stock_info.json）。
    通常一次呼叫即可，不需要按 ticker 分批（全量一次 API）。
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

# ── 路徑設定 ──────────────────────────────────────────────────────────────────
_WORKTREE = Path(__file__).parent.parent.parent   # phase1-scanner/
_SCRIPTS_DIR = _WORKTREE / "scripts"
_SYS_DIR = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_WORKTREE), str(_SCRIPTS_DIR), str(_SYS_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from clients.finmind_client import fetch_stock_info   # noqa: E402
from kline.bars import DEFAULT_DB_PATH               # noqa: E402

# ── Table DDL ─────────────────────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS stock_info (
    ticker            TEXT PRIMARY KEY,
    stock_name        TEXT,
    industry_category TEXT,
    type              TEXT,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_stock_info_industry
    ON stock_info (industry_category);
"""


# ── DB 工具 ───────────────────────────────────────────────────────────────────

def ensure_table(conn: sqlite3.Connection) -> None:
    """建立 stock_info 表與索引（若不存在）。"""
    conn.execute(CREATE_TABLE_SQL)
    conn.execute(CREATE_INDEX_SQL)
    conn.commit()


def upsert_stock_info(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """INSERT OR REPLACE 多筆股票基本資料；回傳寫入筆數。"""
    if not rows:
        return 0
    now = datetime.now().isoformat(timespec="seconds")
    for row in rows:
        row["updated_at"] = now
    conn.executemany(
        """
        INSERT OR REPLACE INTO stock_info
            (ticker, stock_name, industry_category, type, updated_at)
        VALUES (:ticker, :stock_name, :industry_category, :type, :updated_at)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


# ── 主流程 ────────────────────────────────────────────────────────────────────

def backfill(
    db_path: Path = DEFAULT_DB_PATH,
    dry_run: bool = False,
    force: bool = False,
    verbose: bool = False,
) -> dict:
    """主 backfill 函式。

    Args:
        db_path:   SQLite DB 路徑
        dry_run:   True = 不寫入 DB（只顯示撈到幾筆）
        force:     True = 刪除 FinMind 快取後重撈（取最新分類）
        verbose:   True = 詳細輸出

    Returns:
        dict: {fetched, inserted, errors}
    """
    if force:
        from pathlib import Path as _Path
        cache_file = _Path.home() / ".cache" / "finmind" / "_stock_info.json"
        if cache_file.exists():
            cache_file.unlink()
            if verbose:
                print(f"[force] 刪除快取 {cache_file}")

    token = os.environ.get("FINMIND_API_TOKEN", "")

    # 撈取全量股票資料（免費 tier，有 7 天快取）
    try:
        info_df = fetch_stock_info(token)
    except Exception as exc:
        print(f"[ERROR] fetch_stock_info 失敗: {exc}")
        return {"fetched": 0, "inserted": 0, "errors": 1}

    if info_df.empty:
        print("[WARN] fetch_stock_info 回傳空資料")
        return {"fetched": 0, "inserted": 0, "errors": 0}

    fetched = len(info_df)
    if verbose:
        print(f"撈到 {fetched} 筆股票基本資料")
        if not info_df.empty:
            sample = info_df.head(3).to_dict("records")
            print(f"  Sample: {sample}")

    # 轉換欄位名稱（FinMind: stock_id → DB: ticker）
    rows = []
    for _, row in info_df.iterrows():
        rows.append({
            "ticker": str(row["stock_id"]),
            "stock_name": row.get("stock_name", ""),
            "industry_category": row.get("industry_category", ""),
            "type": row.get("type", ""),
        })

    if dry_run:
        print(f"[dry-run] 會寫入 {len(rows)} 筆（未實際寫入）。")
        return {"fetched": fetched, "inserted": 0, "errors": 0}

    conn = sqlite3.connect(str(db_path), timeout=30)
    ensure_table(conn)
    inserted = upsert_stock_info(conn, rows)
    conn.close()

    print(f"完成: fetched={fetched}, inserted={inserted}, errors=0")
    return {"fetched": fetched, "inserted": inserted, "errors": 0}


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="backfill_stock_info",
        description="Backfill 股票產業分類資料至 SQLite DB (FinMind → stock_info 表)",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH,
                        help="SQLite DB 路徑")
    parser.add_argument("--dry-run", action="store_true",
                        help="只顯示會寫入幾筆，不實際寫入")
    parser.add_argument("--force", action="store_true",
                        help="強制刪除本地快取重新從 FinMind 撈取（更新分類）")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="詳細輸出")

    args = parser.parse_args()

    backfill(
        db_path=args.db,
        dry_run=args.dry_run,
        force=args.force,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
