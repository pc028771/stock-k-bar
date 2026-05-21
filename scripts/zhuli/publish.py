"""主力大推送介面 — Publish Queue 系統.

架構設計決策（重要）:
  ┌─────────────────────────────────────────────────────────┐
  │  Notion / Slack 推送需要 Claude session + MCP 工具。     │
  │  此 script 提供 SQLite publish queue：                   │
  │                                                         │
  │  任何 script 可呼叫 enqueue() 加入待推送項目。           │
  │  Claude session 定期呼叫 `publish.py drain` 執行推送。   │
  │                                                         │
  │  [daemon / script]                                      │
  │       ↓ publish.py enqueue                              │
  │       ↓ 寫入 publish_queue (status=pending)             │
  │       ↓                                                 │
  │  [Claude session with MCP]                              │
  │       ↓ publish.py drain                                │
  │       ↓ 逐筆讀 pending → 呼叫 push_to_notion / push_to_slack
  │       ↓ 更新 status=done                                 │
  └─────────────────────────────────────────────────────────┘

  ⚠️ push_to_notion / push_to_slack 函數體內有 MCP 呼叫的「佔位符說明」
  ─ 實際呼叫必須在 Claude session 裡用 MCP tool，不能在 Python subprocess 執行。
  ─ drain 命令會列出 pending items 並等待 Claude session 手動處理，
    或由 Claude session orchestration 直接呼叫這兩個函數。

用法:
  # 加入推送佇列（daemon / script 使用）
  python scripts/zhuli/publish.py enqueue \\
      --type notion \\
      --title "晨報 2026-05-21" \\
      --content-file /tmp/morning_report_2026-05-21.md \\
      --parent-id <notion_page_id>

  python scripts/zhuli/publish.py enqueue \\
      --type slack \\
      --title "晨報摘要" \\
      --content-file /tmp/morning_report_2026-05-21_summary.md \\
      --channel-id C08XXXXXXXX

  # 列出待推送佇列
  python scripts/zhuli/publish.py list

  # 由 Claude session 執行 drain（推送所有 pending）
  python scripts/zhuli/publish.py drain

  # 手動標記某筆 done（測試用）
  python scripts/zhuli/publish.py mark-done <id>
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

_DB = Path.home() / ".four_seasons" / "data.sqlite"

QUEUE_SCHEMA = """
CREATE TABLE IF NOT EXISTS publish_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,          -- notion / slack
    title TEXT NOT NULL,
    content TEXT,                -- markdown 內容（直接存）
    content_file TEXT,           -- 或指向檔案路徑
    parent_id TEXT,              -- Notion parent page id
    channel_id TEXT,             -- Slack channel id
    notion_page_url TEXT,        -- 推送後回填 Notion page URL
    slack_ts TEXT,               -- 推送後回填 Slack message ts
    status TEXT DEFAULT 'pending',  -- pending / done / error
    error_msg TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_publish_queue_status ON publish_queue(status);
"""


def _db():
    return sqlite3.connect(str(_DB), timeout=15)


def _ensure_schema():
    with _db() as conn:
        conn.executescript(QUEUE_SCHEMA)
        conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Public API (供其他 scripts import 使用)
# ─────────────────────────────────────────────────────────────────────────────

def enqueue(
    type_: str,
    title: str,
    content: str = "",
    content_file: str = "",
    parent_id: str = "",
    channel_id: str = "",
) -> int:
    """加入推送佇列，返回 queue id.

    Args:
        type_: "notion" 或 "slack"
        title: 標題
        content: 直接傳 markdown 內容（與 content_file 二選一）
        content_file: 指向 markdown 檔案路徑（與 content 二選一）
        parent_id: Notion parent page id（type_=notion 時必填）
        channel_id: Slack channel id（type_=slack 時必填）
    """
    _ensure_schema()
    with _db() as conn:
        cur = conn.execute(
            """INSERT INTO publish_queue
               (type, title, content, content_file, parent_id, channel_id, status)
               VALUES (?,?,?,?,?,?,'pending')""",
            (type_, title, content, content_file, parent_id, channel_id),
        )
        conn.commit()
        return cur.lastrowid


def get_pending() -> list[dict]:
    """取所有 pending 項目."""
    _ensure_schema()
    with _db() as conn:
        rows = conn.execute(
            """SELECT id, type, title, content, content_file, parent_id, channel_id, created_at
               FROM publish_queue WHERE status='pending' ORDER BY id"""
        ).fetchall()
    return [
        {
            "id": r[0], "type": r[1], "title": r[2],
            "content": r[3], "content_file": r[4],
            "parent_id": r[5], "channel_id": r[6], "created_at": r[7],
        }
        for r in rows
    ]


def mark_done(item_id: int, notion_url: str = "", slack_ts: str = ""):
    """標記佇列項目為 done."""
    _ensure_schema()
    with _db() as conn:
        conn.execute(
            """UPDATE publish_queue
               SET status='done', notion_page_url=?, slack_ts=?, processed_at=?
               WHERE id=?""",
            (notion_url, slack_ts, datetime.now().isoformat(), item_id),
        )
        conn.commit()


def mark_error(item_id: int, error_msg: str):
    """標記佇列項目為 error."""
    _ensure_schema()
    with _db() as conn:
        conn.execute(
            """UPDATE publish_queue
               SET status='error', error_msg=?, processed_at=?
               WHERE id=?""",
            (error_msg, datetime.now().isoformat(), item_id),
        )
        conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Claude session 呼叫的推送函數（佔位符）
#
# ⚠️ 這兩個函數需要在 Claude session 中使用 MCP 工具執行，
#    不能在 subprocess / daemon 中呼叫。
#    此處提供函數簽章 + 說明，供 Claude orchestration 參考。
# ─────────────────────────────────────────────────────────────────────────────

def push_to_notion(parent_id: str, title: str, markdown_content: str) -> str:
    """推送 markdown 到 Notion，返回 page URL.

    ⚠️ 此函數需要在 Claude session 中執行，使用：
       mcp__claude_ai_Notion__notion-create-pages

    MCP 呼叫範例（Claude session 裡執行）:
        mcp__claude_ai_Notion__notion-create-pages({
            "parent": {"page_id": parent_id},
            "properties": {"title": {"title": [{"text": {"content": title}}]}},
            "children": [<markdown 轉換為 Notion blocks>]
        })

    Args:
        parent_id: Notion parent page UUID
        title: 頁面標題
        markdown_content: markdown 字串

    Returns:
        page URL (e.g. "https://notion.so/xxx")
    """
    raise NotImplementedError(
        "push_to_notion 需要在 Claude session 中使用 Notion MCP 工具執行。\n"
        "請在 Claude session 中呼叫 mcp__claude_ai_Notion__notion-create-pages。\n"
        "參考 docs/主力大課程/tracker_system_setup.md § Claude Session Orchestration"
    )


def push_to_slack(channel_id: str, summary_text: str, link_to_notion: Optional[str] = None) -> str:
    """推送摘要到 Slack，返回 message ts.

    ⚠️ 此函數需要在 Claude session 中執行，使用：
       mcp__claude_ai_Slack__slack_send_message

    MCP 呼叫範例（Claude session 裡執行）:
        mcp__claude_ai_Slack__slack_send_message({
            "channel_id": channel_id,
            "text": summary_text + (f"\n{link_to_notion}" if link_to_notion else "")
        })

    Args:
        channel_id: Slack channel ID（如 C08XXXXXXXX）
        summary_text: 推送文字（短摘要 / 晨報）
        link_to_notion: 附帶 Notion 頁面連結（可選）

    Returns:
        message ts string
    """
    raise NotImplementedError(
        "push_to_slack 需要在 Claude session 中使用 Slack MCP 工具執行。\n"
        "請在 Claude session 中呼叫 mcp__claude_ai_Slack__slack_send_message。\n"
        "參考 docs/主力大課程/tracker_system_setup.md § Claude Session Orchestration"
    )


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def cmd_enqueue(args):
    content = ""
    if args.content_file:
        cf = Path(args.content_file)
        if cf.exists():
            content = cf.read_text(encoding="utf-8")
        else:
            print(f"⚠️  content_file 不存在: {args.content_file}（仍加入佇列，path 留存）")

    qid = enqueue(
        type_=args.type,
        title=args.title,
        content=content,
        content_file=args.content_file or "",
        parent_id=args.parent_id or "",
        channel_id=args.channel_id or "",
    )
    print(f"✅ 加入佇列 id={qid}  type={args.type}  title={args.title[:60]}")


def cmd_list(args):
    pending = get_pending()
    _ensure_schema()
    with _db() as conn:
        all_rows = conn.execute(
            "SELECT id, type, title, status, created_at, notion_page_url, slack_ts, error_msg "
            "FROM publish_queue ORDER BY id DESC LIMIT 50"
        ).fetchall()

    if not all_rows:
        print("（佇列為空）")
        return

    print(f"\n{'id':>4}  {'type':>6}  {'status':>8}  {'title':<40}  {'created_at'}")
    print("-" * 90)
    for r in all_rows:
        id_, type_, title, status, created_at, nurl, sts, err = r
        extra = ""
        if nurl: extra = f" → {nurl[:50]}"
        elif sts: extra = f" → ts={sts}"
        elif err: extra = f" ❌ {err[:40]}"
        print(f"{id_:>4}  {type_:>6}  {status:>8}  {(title or '')[:40]:<40}  {created_at or ''}{extra}")


def cmd_drain(args):
    """列出 pending items 並提示 Claude session 手動處理.

    在完全自動化版本中，此函數應由 Claude session 程式化呼叫
    push_to_notion / push_to_slack（需 MCP）。
    目前 Phase 1 輸出清單讓 Claude session 逐筆處理。
    """
    pending = get_pending()
    if not pending:
        print("✅ 佇列無 pending 項目")
        return

    print(f"\n⏳ publish_queue pending: {len(pending)} 筆")
    print("=" * 80)
    for item in pending:
        print(f"\n[id={item['id']}] type={item['type']}  title={item['title'][:60]}")
        if item["type"] == "notion":
            print(f"  parent_id: {item['parent_id'] or '(未設定)'}")
        elif item["type"] == "slack":
            print(f"  channel_id: {item['channel_id'] or '(未設定)'}")
        content_preview = (item["content"] or "")[:200]
        if item["content_file"] and not item["content"]:
            cf = Path(item["content_file"])
            if cf.exists():
                content_preview = cf.read_text(encoding="utf-8")[:200]
        if content_preview:
            print(f"  content preview:\n    {content_preview[:200].replace(chr(10), chr(10)+'    ')}")

    print(f"\n{'=' * 80}")
    print("📋 Claude session 處理步驟:")
    print("  1. 對 type=notion: 用 mcp__claude_ai_Notion__notion-create-pages 建頁面")
    print("  2. 對 type=slack:  用 mcp__claude_ai_Slack__slack_send_message 推送")
    print("  3. 各筆完成後呼叫: python scripts/zhuli/publish.py mark-done <id>")
    print("  4. 或: from zhuli.publish import mark_done; mark_done(id, notion_url='...')")


def cmd_mark_done_cli(args):
    mark_done(args.id, notion_url=args.notion_url or "", slack_ts=args.slack_ts or "")
    print(f"✅ id={args.id} 標記為 done")


def main():
    parser = argparse.ArgumentParser(description="主力大推送佇列管理")
    sub = parser.add_subparsers(dest="cmd")

    p_enq = sub.add_parser("enqueue", help="加入推送佇列")
    p_enq.add_argument("--type", required=True, choices=["notion", "slack"])
    p_enq.add_argument("--title", required=True)
    p_enq.add_argument("--content-file", default=None, dest="content_file",
                       help="markdown 檔案路徑")
    p_enq.add_argument("--parent-id", default=None, dest="parent_id",
                       help="Notion parent page id（type=notion 時用）")
    p_enq.add_argument("--channel-id", default=None, dest="channel_id",
                       help="Slack channel id（type=slack 時用）")

    sub.add_parser("list", help="列出佇列（最近 50 筆）")

    sub.add_parser("drain",
                   help="列出 pending 並提示 Claude session 處理（需 MCP）")

    p_done = sub.add_parser("mark-done", help="手動標記某筆 done")
    p_done.add_argument("id", type=int)
    p_done.add_argument("--notion-url", default=None, dest="notion_url")
    p_done.add_argument("--slack-ts", default=None, dest="slack_ts")

    args = parser.parse_args()

    if args.cmd == "enqueue":
        cmd_enqueue(args)
    elif args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "drain":
        cmd_drain(args)
    elif args.cmd == "mark-done":
        cmd_mark_done_cli(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
