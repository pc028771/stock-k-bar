"""
migrate_recommendation_tracker_v2.py

將 recommendation_outcomes 從 v1 schema（含 OHLC 冗餘欄位）遷移至 v2 schema。

只需跑一次，跑完即廢。
執行前會自動備份 DB 至 /tmp/data.sqlite.v1_backup。

用法:
  python scripts/zhuli/migrate_recommendation_tracker_v2.py
  python scripts/zhuli/migrate_recommendation_tracker_v2.py --dry-run   # 只印計畫、不動 DB
"""

import argparse
import os
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.path.expanduser("~/four_seasons_local/data.sqlite")
BACKUP_PATH = "/tmp/data.sqlite.v1_backup"

# 新 schema v2
CREATE_TABLE_V2 = """
CREATE TABLE recommendation_outcomes_v2 (
  recommend_date TEXT NOT NULL,
  ticker         TEXT NOT NULL,
  -- 最小必要欄 (filter 用、避免 join JSON 才能過濾)
  priority       INT,
  primary_source TEXT,   -- sources[0] 即可、其他丟 extras
  -- 已算好指標 (% 形式、避免 query 時還要算)
  ret_t1         REAL,
  ret_t3         REAL,
  ret_t5         REAL,
  ret_t10        REAL,
  max_gain_5d    REAL,
  max_dd_5d      REAL,
  -- 版本 + 擴充
  schema_version INT NOT NULL DEFAULT 1,
  scanner_commit TEXT,   -- git short hash (7 字)
  extras         TEXT,   -- JSON blob、任何新欄都丟這
  backfilled_at  TEXT,
  PRIMARY KEY (recommend_date, ticker)
);
"""

CREATE_INDEXES_V2 = [
    "CREATE INDEX IF NOT EXISTS idx_rec_outcomes_priority ON recommendation_outcomes(priority);",
    "CREATE INDEX IF NOT EXISTS idx_rec_outcomes_source   ON recommendation_outcomes(primary_source);",
]


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


def parse_primary_source(sources_json: str | None) -> str | None:
    """從 sources JSON 字串取 sources[0]。"""
    if not sources_json:
        return None
    try:
        import json
        lst = json.loads(sources_json)
        return lst[0] if lst else None
    except Exception:
        return sources_json  # fallback: 原始值


def migrate(dry_run: bool = False):
    # ── 備份 ───────────────────────────────────────────────────
    print(f"[備份] {DB_PATH} → {BACKUP_PATH}")
    if not dry_run:
        shutil.copy2(DB_PATH, BACKUP_PATH)
        print(f"  備份完成: {os.path.getsize(BACKUP_PATH):,} bytes")
    else:
        print("  (dry-run: 跳過備份)")

    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row

    # ── 確認舊表存在 ─────────────────────────────────────────────
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "recommendation_outcomes" not in tables:
        print("[ERROR] 找不到 recommendation_outcomes table，中止。")
        conn.close()
        return

    # ── 取舊資料 ───────────────────────────────────────────────
    old_rows = conn.execute("SELECT * FROM recommendation_outcomes ORDER BY recommend_date, ticker").fetchall()
    old_count = len(old_rows)
    print(f"[讀取] 舊 table: {old_count} 筆")

    # 取舊 table page count（近似 size）
    old_page_count = conn.execute("SELECT page_count FROM pragma_page_count()").fetchone()[0]
    page_size = conn.execute("SELECT page_size FROM pragma_page_size()").fetchone()[0]
    old_db_bytes = old_page_count * page_size
    print(f"  目前 DB 大小: {old_db_bytes:,} bytes ({old_db_bytes/1024/1024:.2f} MB)")

    git_hash = get_git_short_hash()
    print(f"[git] scanner_commit = {git_hash}")

    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── 整理要插入的資料 ──────────────────────────────────────────
    new_rows = []
    for r in old_rows:
        # 欄位對應 (舊 → 新)
        primary_source = parse_primary_source(r["sources"] if "sources" in r.keys() else None)

        # ret 欄位: 舊用 ret_t1_pct，新用 ret_t1
        def col(name, fallback=None):
            try:
                return r[name]
            except (IndexError, TypeError):
                return fallback

        new_rows.append((
            r["recommend_date"],
            r["ticker"],
            col("priority"),
            primary_source,
            col("ret_t1_pct"),    # → ret_t1
            col("ret_t3_pct"),    # → ret_t3
            col("ret_t5_pct"),    # → ret_t5
            col("ret_t10_pct"),   # → ret_t10
            col("max_gain_5d_pct"),   # → max_gain_5d
            col("max_drawdown_5d_pct"),  # → max_dd_5d
            1,           # schema_version
            git_hash,    # scanner_commit
            "{}",        # extras — 空 JSON dict 預留
            col("backfilled_at", now_ts),
        ))

    print(f"[計畫] 準備寫入 {len(new_rows)} 筆至新 schema")

    if dry_run:
        print("  (dry-run: 以下為前 3 筆預覽)")
        for row in new_rows[:3]:
            print("  ", dict(zip(
                ["recommend_date","ticker","priority","primary_source",
                 "ret_t1","ret_t3","ret_t5","ret_t10",
                 "max_gain_5d","max_dd_5d","schema_version","scanner_commit","extras","backfilled_at"],
                row
            )))
        conn.close()
        return

    # ── 執行遷移 ───────────────────────────────────────────────
    # 1) 建暫存 v2 table
    conn.execute(CREATE_TABLE_V2)

    # 2) 插入資料
    conn.executemany(
        """
        INSERT OR REPLACE INTO recommendation_outcomes_v2 (
          recommend_date, ticker, priority, primary_source,
          ret_t1, ret_t3, ret_t5, ret_t10,
          max_gain_5d, max_dd_5d,
          schema_version, scanner_commit, extras, backfilled_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        new_rows,
    )
    conn.commit()
    print(f"  recommendation_outcomes_v2: 寫入完成")

    # 3) 驗證筆數
    new_count = conn.execute("SELECT COUNT(*) FROM recommendation_outcomes_v2").fetchone()[0]
    print(f"  驗證: 新 table = {new_count} 筆 (舊 {old_count} 筆)")
    if new_count != old_count:
        print(f"[WARNING] 筆數不一致！請確認後手動處理。")

    # 4) DROP 舊 table，重命名
    conn.execute("DROP TABLE recommendation_outcomes")
    conn.execute("ALTER TABLE recommendation_outcomes_v2 RENAME TO recommendation_outcomes")

    # 5) 建 index
    for idx_sql in CREATE_INDEXES_V2:
        conn.execute(idx_sql)

    conn.commit()

    # 6) VACUUM 回收空間
    print("[VACUUM] 回收 OHLC 欄位釋放的空間 ...")
    conn.execute("VACUUM")
    conn.close()

    # ── 大小比較 ────────────────────────────────────────────────
    new_db_bytes = os.path.getsize(DB_PATH)
    saved = old_db_bytes - new_db_bytes
    saved_pct = saved / old_db_bytes * 100 if old_db_bytes else 0
    print(f"\n=== 大小比較 ===")
    print(f"  遷移前: {old_db_bytes:>12,} bytes ({old_db_bytes/1024/1024:.2f} MB)")
    print(f"  遷移後: {new_db_bytes:>12,} bytes ({new_db_bytes/1024/1024:.2f} MB)")
    print(f"  節省:   {saved:>12,} bytes ({saved_pct:.1f}%)")
    print(f"\n[完成] migration v2 成功，共 {new_count} 筆。")
    print(f"  備份保留於: {BACKUP_PATH}")


def main():
    parser = argparse.ArgumentParser(description="recommendation_outcomes schema v1 → v2 遷移")
    parser.add_argument("--dry-run", action="store_true", help="只印計畫、不動 DB")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
