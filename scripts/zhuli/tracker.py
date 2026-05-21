"""主力大老師追蹤系統 — Phase 1.

提供:
  - tracker.py init             建 DB schema
  - tracker.py ingest <md>      解析 markdown 文章 → mentions
  - tracker.py add              CLI 手動加 mention
  - tracker.py dashboard         顯示當前主推/警告
  - tracker.py list             列所有 active mentions

DB tables (in ~/.four_seasons/data.sqlite):
  zhuli_articles        — 文章 metadata
  zhuli_mentions        — (ticker, article_id, mention_date, level, status, ...)
  zhuli_stance_shifts   — stance shift 紀錄
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

_DB = Path.home() / ".four_seasons" / "data.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS zhuli_articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT,
    title TEXT NOT NULL,
    source TEXT,                    -- pressplay / line / 直播 / user_input
    publish_date DATE,
    fetch_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    content_md_path TEXT,
    UNIQUE(url, title)
);

CREATE TABLE IF NOT EXISTS zhuli_mentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER,
    ticker TEXT NOT NULL,
    name TEXT,
    mention_date DATE NOT NULL,     -- 老師講的日期 (not publish)
    level TEXT NOT NULL,            -- L1/L2/L3/L3+/L4/L5
    sector TEXT,
    status TEXT,                    -- 主推 / 觀察 / 警告 / 中性
    note TEXT,
    source_quote TEXT,              -- 老師原話
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (article_id) REFERENCES zhuli_articles(id)
);
CREATE INDEX IF NOT EXISTS idx_zhuli_mentions_ticker ON zhuli_mentions(ticker);
CREATE INDEX IF NOT EXISTS idx_zhuli_mentions_date ON zhuli_mentions(mention_date);

CREATE TABLE IF NOT EXISTS zhuli_stance_shifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shift_date DATE NOT NULL,
    summary TEXT NOT NULL,
    affected_sectors TEXT,
    affected_tickers TEXT,
    source_article_id INTEGER,
    FOREIGN KEY (source_article_id) REFERENCES zhuli_articles(id)
);
"""


def db_conn():
    return sqlite3.connect(str(_DB), timeout=15)


def cmd_init():
    with db_conn() as c:
        c.executescript(SCHEMA)
        c.commit()
    print("✅ schema initialized")


def cmd_add(args):
    """手動加 mention."""
    with db_conn() as c:
        # 確保有 article entry (source=user_input)
        art_title = args.article or f"user_input_{args.date}"
        c.execute("INSERT OR IGNORE INTO zhuli_articles (url, title, source, publish_date) VALUES (?, ?, ?, ?)",
                  (None, art_title, "user_input", args.date))
        art_id = c.execute("SELECT id FROM zhuli_articles WHERE title=?", (art_title,)).fetchone()[0]
        c.execute("""INSERT INTO zhuli_mentions
            (article_id, ticker, name, mention_date, level, sector, status, note, source_quote)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (art_id, args.ticker, args.name, args.date, args.level,
             args.sector, args.status, args.note, args.quote))
        c.commit()
    print(f"✅ added: {args.ticker} {args.name} {args.date} {args.level} {args.status}")


def cmd_list(args):
    """顯示所有 mentions."""
    with db_conn() as c:
        rows = c.execute("""SELECT mention_date, ticker, name, level, status, sector, note
                            FROM zhuli_mentions ORDER BY mention_date DESC, ticker LIMIT 200""").fetchall()
    print(f"\n{'date':<12}{'ticker':<7}{'name':<10}{'level':<5}{'status':<8}{'sector':<10}note")
    print("-" * 100)
    for r in rows:
        print(f"{r[0]:<12}{r[1]:<7}{(r[2] or ''):<10}{r[3]:<5}{(r[4] or ''):<8}{(r[5] or ''):<10}{(r[6] or '')[:50]}")


def cmd_dashboard(args):
    """顯示當前主推 / 警告 / stance shift dashboard."""
    today = datetime.now().date()
    cutoff_active = (today - timedelta(days=args.window)).isoformat()

    with db_conn() as c:
        # Active L4-L5 (近 7-14 天)
        recent = c.execute("""SELECT mention_date, ticker, name, level, status, sector, source_quote, note
                              FROM zhuli_mentions
                              WHERE mention_date >= ? AND level IN ('L4','L5')
                              ORDER BY mention_date DESC, level DESC""",
                           (cutoff_active,)).fetchall()
        # L3 追蹤
        track = c.execute("""SELECT mention_date, ticker, name, status, sector, note
                             FROM zhuli_mentions
                             WHERE mention_date >= ? AND level LIKE 'L3%'
                             ORDER BY mention_date DESC""",
                          (cutoff_active,)).fetchall()
        # Warnings
        warn = c.execute("""SELECT mention_date, ticker, name, level, status, note
                            FROM zhuli_mentions
                            WHERE mention_date >= ? AND status='警告'
                            ORDER BY mention_date DESC""",
                         (cutoff_active,)).fetchall()
        # Stance shifts
        shifts = c.execute("""SELECT shift_date, summary, affected_sectors
                              FROM zhuli_stance_shifts WHERE shift_date >= ?
                              ORDER BY shift_date DESC""",
                           ((today - timedelta(days=30)).isoformat(),)).fetchall()

    print(f"\n{'='*90}")
    print(f"  主力大追蹤 Dashboard — {today} (active window: {args.window} 天)")
    print(f"{'='*90}\n")

    print(f"🎯 當前主推 L4-L5 (近 {args.window} 天)")
    if not recent:
        print("  （無）")
    else:
        for d, tk, nm, lvl, st, sec, q, n in recent:
            print(f"  {d}  [{lvl}] {tk} {(nm or '')[:6]:<6} ({sec or '?'})  {st or ''}")
            if q:
                print(f"           老師: 「{q[:60]}」")
            if n:
                print(f"           備註: {n[:60]}")

    print(f"\n📋 L3 追蹤池 (近 {args.window} 天)")
    if not track:
        print("  （無）")
    else:
        for d, tk, nm, st, sec, n in track[:15]:
            print(f"  {d}  {tk} {(nm or '')[:6]:<6} ({sec or '?'})  {st or ''}  {(n or '')[:40]}")

    print(f"\n🚨 警告 (近 {args.window} 天)")
    if not warn:
        print("  （無）")
    else:
        for d, tk, nm, lvl, st, n in warn:
            print(f"  {d}  [{lvl}] {tk} {nm or ''} — {st} {(n or '')[:50]}")

    print(f"\n🔄 Stance Shifts (近 30 天)")
    if not shifts:
        print("  （無）")
    else:
        for d, s, sec in shifts:
            print(f"  {d}  {s[:80]}")
            if sec: print(f"        affected: {sec}")
    print()


def cmd_ingest_line(args):
    """從 line chat md 萃取已標 L 級的 mentions."""
    md = Path(args.path)
    if not md.exists():
        print(f"❌ {md} not found")
        return

    title = f"line_chat_{md.stem}"
    with db_conn() as c:
        c.execute("INSERT OR IGNORE INTO zhuli_articles (url, title, source, publish_date, content_md_path) VALUES (?, ?, ?, ?, ?)",
                  (None, title, "line", args.date, str(md)))
        c.commit()
        art_id = c.execute("SELECT id FROM zhuli_articles WHERE title=?", (title,)).fetchone()[0]
    print(f"  article id {art_id}: {title}")
    print(f"  注意：line chat 需手動標 L 級，用 'tracker.py add' 補")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("init")

    p_add = sub.add_parser("add")
    p_add.add_argument("ticker")
    p_add.add_argument("--name", default="")
    p_add.add_argument("--date", required=True, help="YYYY-MM-DD")
    p_add.add_argument("--level", required=True, choices=["L1","L2","L3","L3+","L4","L5"])
    p_add.add_argument("--sector", default="")
    p_add.add_argument("--status", default="觀察", choices=["主推","觀察","警告","中性"])
    p_add.add_argument("--note", default="")
    p_add.add_argument("--quote", default="")
    p_add.add_argument("--article", default="")

    sub.add_parser("list")

    p_dash = sub.add_parser("dashboard")
    p_dash.add_argument("--window", type=int, default=10, help="active window (days)")

    p_in = sub.add_parser("ingest-line")
    p_in.add_argument("path")
    p_in.add_argument("--date", required=True)

    args = parser.parse_args()

    if args.cmd == "init": cmd_init()
    elif args.cmd == "add": cmd_add(args)
    elif args.cmd == "list": cmd_list(args)
    elif args.cmd == "dashboard": cmd_dashboard(args)
    elif args.cmd == "ingest-line": cmd_ingest_line(args)
    else: parser.print_help()


if __name__ == "__main__":
    main()
