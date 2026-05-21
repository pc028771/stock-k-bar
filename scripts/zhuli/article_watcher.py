"""主力大文章監控器 — Phase 1 Trigger-Based 設計.

架構設計決策（重要）:
  ┌─────────────────────────────────────────────────────────┐
  │  此 script 是「觸發器」，不是「爬蟲」。                    │
  │                                                         │
  │  真正的 PressPlay 文章抓取需要 Claude session + chrome   │
  │  MCP（mcp__claude-in-chrome__*）。Daemon 環境無法使用    │
  │  瀏覽器 MCP，因此採用 Trigger-Flag 模式：                 │
  │                                                         │
  │  [launchd 每小時]                                        │
  │       ↓                                                 │
  │  article_watcher.py check-interval                      │
  │       ↓ 寫 /tmp/article_watcher_trigger_<ts>.flag       │
  │       ↓ 更新 DB zhuli_metadata (last_check_ts)          │
  │       ↓                                                 │
  │  [User / Claude session 定期看 trigger flag]             │
  │       ↓ 發現 flag → 用 chrome MCP 抓文章                 │
  │       ↓ 解析 → tracker.py add / ingest                  │
  │       ↓ 呼叫 publish.py enqueue                         │
  │       ↓ 刪除 flag                                        │
  └─────────────────────────────────────────────────────────┘

用法:
  # 手動觸發 check（通常由 launchd 呼叫）
  python scripts/zhuli/article_watcher.py check-interval

  # 列出待處理 flag
  python scripts/zhuli/article_watcher.py list-flags

  # 標記 flag 已處理（Claude session 處理完後呼叫）
  python scripts/zhuli/article_watcher.py mark-done <flag_path>

  # 查上次 check 時間
  python scripts/zhuli/article_watcher.py status

  # 手動記錄一篇文章（Claude session 抓到後手動呼叫）
  python scripts/zhuli/article_watcher.py record-article --url URL --title TITLE --date 2026-05-21
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

_DB = Path.home() / ".four_seasons" / "data.sqlite"
_FLAG_DIR = Path("/tmp")
_FLAG_PREFIX = "article_watcher_trigger_"
_CHECK_INTERVAL_HOURS = 1  # 每小時最多觸發一次

METADATA_SCHEMA = """
CREATE TABLE IF NOT EXISTS zhuli_metadata (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _db():
    return sqlite3.connect(str(_DB), timeout=15)


def _ensure_metadata_table():
    with _db() as conn:
        conn.executescript(METADATA_SCHEMA)
        conn.commit()


def get_metadata(key: str) -> str | None:
    try:
        _ensure_metadata_table()
        with _db() as conn:
            row = conn.execute("SELECT value FROM zhuli_metadata WHERE key=?", (key,)).fetchone()
        return row[0] if row else None
    except Exception:
        return None


def set_metadata(key: str, value: str):
    _ensure_metadata_table()
    with _db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO zhuli_metadata (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, datetime.now().isoformat()),
        )
        conn.commit()


def write_trigger_flag() -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    flag_path = _FLAG_DIR / f"{_FLAG_PREFIX}{ts}.flag"
    flag_path.write_text(
        f"article_watcher trigger\n"
        f"timestamp: {datetime.now().isoformat()}\n"
        f"action: fetch_pressplay_articles\n"
        f"\n"
        f"# 處理步驟 (Claude session):\n"
        f"# 1. chrome MCP navigate to PressPlay 主力大全方位 文章列表\n"
        f"# 2. 抓取最新文章清單，比對 zhuli_articles DB\n"
        f"# 3. 對新文章: tracker.py add (or ingest-line)\n"
        f"# 4. publish.py enqueue -> drain (Notion + Slack)\n"
        f"# 5. article_watcher.py mark-done {flag_path}\n",
        encoding="utf-8",
    )
    return flag_path


def cmd_check_interval(args):
    """檢查是否到了觸發時間，如是則寫 flag."""
    now = datetime.now()
    last_check_str = get_metadata("article_watcher_last_check")

    if last_check_str:
        last_check = datetime.fromisoformat(last_check_str)
        elapsed = now - last_check
        if elapsed < timedelta(hours=_CHECK_INTERVAL_HOURS):
            remaining = timedelta(hours=_CHECK_INTERVAL_HOURS) - elapsed
            print(f"跳過：上次 check {last_check_str}，"
                  f"距下次觸發還有 {int(remaining.total_seconds() / 60)} 分鐘")
            return

    # 寫 flag
    flag_path = write_trigger_flag()
    set_metadata("article_watcher_last_check", now.isoformat())
    print(f"✅ trigger flag 寫出：{flag_path}")
    print(f"   請在 Claude session 中處理（見 flag 內容）")


def cmd_list_flags(args):
    """列出 /tmp 下所有待處理 flag."""
    flags = sorted(_FLAG_DIR.glob(f"{_FLAG_PREFIX}*.flag"))
    if not flags:
        print("（無待處理 flag）")
        return
    print(f"待處理 trigger flags ({len(flags)} 個):")
    for f in flags:
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  {f}  (建立 {mtime})")


def cmd_mark_done(args):
    """刪除指定 flag（處理完成）."""
    flag_path = Path(args.flag_path)
    if not flag_path.exists():
        print(f"❌ flag 不存在: {flag_path}")
        return
    flag_path.unlink()
    set_metadata("article_watcher_last_processed", datetime.now().isoformat())
    print(f"✅ flag 已刪除: {flag_path}")


def cmd_status(args):
    """顯示 watcher 狀態."""
    last_check = get_metadata("article_watcher_last_check") or "從未"
    last_processed = get_metadata("article_watcher_last_processed") or "從未"
    flags = sorted(_FLAG_DIR.glob(f"{_FLAG_PREFIX}*.flag"))

    print(f"\n主力大文章監控 狀態")
    print(f"  上次 check:    {last_check}")
    print(f"  上次 processed: {last_processed}")
    print(f"  待處理 flags:  {len(flags)} 個")
    for f in flags:
        print(f"    - {f.name}")
    print(f"  check 間隔:    每 {_CHECK_INTERVAL_HOURS} 小時")
    print()


def cmd_record_article(args):
    """手動記錄一篇文章（Claude session 抓到後呼叫）."""
    _ensure_metadata_table()
    # 確保 zhuli_articles schema 存在
    ARTICLES_SCHEMA = """
    CREATE TABLE IF NOT EXISTS zhuli_articles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT,
        title TEXT NOT NULL,
        source TEXT,
        publish_date DATE,
        fetch_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        content_md_path TEXT,
        UNIQUE(url, title)
    );
    """
    with _db() as conn:
        conn.executescript(ARTICLES_SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO zhuli_articles (url, title, source, publish_date) VALUES (?,?,?,?)",
            (args.url, args.title, args.source or "pressplay", args.date),
        )
        conn.commit()
        art = conn.execute("SELECT id FROM zhuli_articles WHERE title=?", (args.title,)).fetchone()
    print(f"✅ 文章記錄：id={art[0]}  {args.title[:60]}")


def main():
    parser = argparse.ArgumentParser(description="主力大文章監控（trigger-based）")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("check-interval",
                   help="檢查是否到觸發時間，如是則寫 /tmp trigger flag")

    sub.add_parser("list-flags", help="列出待處理 flags")

    p_done = sub.add_parser("mark-done", help="標記 flag 已處理（刪除）")
    p_done.add_argument("flag_path", help="flag 完整路徑")

    sub.add_parser("status", help="顯示 watcher 狀態")

    p_rec = sub.add_parser("record-article", help="手動記錄一篇文章")
    p_rec.add_argument("--url", default=None)
    p_rec.add_argument("--title", required=True)
    p_rec.add_argument("--date", required=True, help="YYYY-MM-DD")
    p_rec.add_argument("--source", default="pressplay")

    args = parser.parse_args()

    if args.cmd == "check-interval":
        cmd_check_interval(args)
    elif args.cmd == "list-flags":
        cmd_list_flags(args)
    elif args.cmd == "mark-done":
        cmd_mark_done(args)
    elif args.cmd == "status":
        cmd_status(args)
    elif args.cmd == "record-article":
        cmd_record_article(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
