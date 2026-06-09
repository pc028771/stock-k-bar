"""
推薦命中率月報產生器 (recommendation_tracker_report.py) v2

用法:
  python scripts/zhuli/recommendation_tracker_report.py --month 2026-06
  python scripts/zhuli/recommendation_tracker_report.py  # 預設當月

v2 改動:
- name/sector/sources 改由 daily_watchlist JSON lazy load 取得（不再從 DB 讀）
- 新增「Scanner Commit 分布」section
- 新增報告 footer（schema_version + commit 數）
- 欄位名稱從 ret_t1_pct → ret_t1 等（v2 schema）
"""

import argparse
import json
import sqlite3
import os
from datetime import datetime
from pathlib import Path
from functools import lru_cache

DB_PATH = os.path.expanduser("~/four_seasons_local/data.sqlite")
WATCHLIST_DIR = Path(__file__).parent.parent.parent / "docs" / "主力大課程" / "daily_watchlist"
REPORT_DIR = Path(__file__).parent.parent.parent / "docs" / "主力大課程" / "recommendation_accuracy"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


# ── JSON watchlist 快取 ──────────────────────────────────────────────
_watchlist_cache: dict[str, dict] = {}


def _load_watchlist(date_str: str) -> dict:
    """Lazy load + cache 單日 JSON watchlist。"""
    if date_str not in _watchlist_cache:
        p = WATCHLIST_DIR / f"{date_str}.json"
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                # 建立 ticker → candidate 的快速 lookup
                lookup = {c["ticker"]: c for c in data.get("candidates", []) if "ticker" in c}
                _watchlist_cache[date_str] = lookup
            except Exception:
                _watchlist_cache[date_str] = {}
        else:
            _watchlist_cache[date_str] = {}
    return _watchlist_cache[date_str]


def lookup_json(date_str: str, ticker: str, field: str, default=None):
    """從 JSON watchlist 查單個欄位。"""
    return _load_watchlist(date_str).get(ticker, {}).get(field, default)


# ── 格式工具 ─────────────────────────────────────────────────────────
def pct_str(val) -> str:
    if val is None:
        return "N/A"
    return f"{val:+.2f}%"


def hit_rate(up: int, total: int) -> str:
    if total == 0:
        return "N/A"
    return f"{up/total*100:.1f}% ({up}/{total})"


# ── 報告產生 ─────────────────────────────────────────────────────────
def generate_report(conn: sqlite3.Connection, month: str) -> str:
    """產生月報 Markdown 字串。"""
    year, mon = month.split("-")
    start_date = f"{year}-{mon}-01"
    if int(mon) == 12:
        end_date = f"{int(year)+1}-01-01"
    else:
        end_date = f"{year}-{int(mon)+1:02d}-01"

    rows = conn.execute(
        """
        SELECT * FROM recommendation_outcomes
        WHERE recommend_date >= ? AND recommend_date < ?
        ORDER BY recommend_date, ticker
        """,
        (start_date, end_date),
    ).fetchall()

    if not rows:
        return f"# {month} 推薦命中率月報\n\n> 該月無資料。\n"

    total = len(rows)
    has_t1 = [r for r in rows if r["ret_t1"] is not None]
    has_t5 = [r for r in rows if r["ret_t5"] is not None]

    # schema_version / commit 彙總（用於 footer）
    schema_versions = sorted({r["schema_version"] for r in rows if r["schema_version"] is not None})
    commits = sorted({r["scanner_commit"] for r in rows if r["scanner_commit"]})

    lines = []
    lines.append(f"# {month} 推薦命中率月報")
    lines.append(f"\n> 產生時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"\n## 總覽\n")
    lines.append(f"- 推薦總筆數: **{total}**")
    lines.append(f"- 有 T+1 資料: {len(has_t1)} 筆")
    lines.append(f"- 有 T+5 資料: {len(has_t5)} 筆")

    # ── By Priority ──────────────────────────────────────────
    lines.append("\n## By Priority (P1/P2/P3)\n")
    lines.append("| Priority | 筆數 | T+1 上漲率 | T+1 >+1% | 平均T+1% | 平均T+3% | 平均T+5% | 平均T+10% |")
    lines.append("|---|---|---|---|---|---|---|---|")

    for p in [3, 2, 1]:
        pr = [r for r in rows if r["priority"] == p]
        if not pr:
            continue
        pr_t1 = [r for r in pr if r["ret_t1"] is not None]
        up_t1 = sum(1 for r in pr_t1 if r["ret_t1"] > 0)
        strong_t1 = sum(1 for r in pr_t1 if r["ret_t1"] > 1)
        avg_t1 = sum(r["ret_t1"] for r in pr_t1) / len(pr_t1) if pr_t1 else None
        pr_t3 = [r for r in pr if r["ret_t3"] is not None]
        avg_t3 = sum(r["ret_t3"] for r in pr_t3) / len(pr_t3) if pr_t3 else None
        pr_t5 = [r for r in pr if r["ret_t5"] is not None]
        avg_t5 = sum(r["ret_t5"] for r in pr_t5) / len(pr_t5) if pr_t5 else None
        pr_t10 = [r for r in pr if r["ret_t10"] is not None]
        avg_t10 = sum(r["ret_t10"] for r in pr_t10) / len(pr_t10) if pr_t10 else None

        lines.append(
            f"| P{p} | {len(pr)} | {hit_rate(up_t1, len(pr_t1))} | "
            f"{hit_rate(strong_t1, len(pr_t1))} | {pct_str(avg_t1)} | "
            f"{pct_str(avg_t3)} | {pct_str(avg_t5)} | {pct_str(avg_t10)} |"
        )

    # ── By Source ────────────────────────────────────────────
    # sources 從 JSON 取，primary_source 也可直接用（已存 sources[0]）
    lines.append("\n## By Source\n")
    lines.append("| Source | 筆數 | T+1 上漲率 | 平均T+1% | 平均T+5% |")
    lines.append("|---|---|---|---|---|")

    source_map: dict[str, list] = {}
    for r in rows:
        # 優先讀完整 JSON sources list
        srcs = lookup_json(r["recommend_date"], r["ticker"], "sources") or []
        if not srcs and r["primary_source"]:
            srcs = [r["primary_source"]]
        for s in srcs:
            source_map.setdefault(s, []).append(r)

    for src, sr in sorted(source_map.items(), key=lambda x: -len(x[1])):
        sr_t1 = [r for r in sr if r["ret_t1"] is not None]
        up_t1 = sum(1 for r in sr_t1 if r["ret_t1"] > 0)
        avg_t1 = sum(r["ret_t1"] for r in sr_t1) / len(sr_t1) if sr_t1 else None
        sr_t5 = [r for r in sr if r["ret_t5"] is not None]
        avg_t5 = sum(r["ret_t5"] for r in sr_t5) / len(sr_t5) if sr_t5 else None
        lines.append(f"| `{src}` | {len(sr)} | {hit_rate(up_t1, len(sr_t1))} | {pct_str(avg_t1)} | {pct_str(avg_t5)} |")

    # ── By Sector ────────────────────────────────────────────
    lines.append("\n## By Sector (Top 5 / Bottom 5)\n")

    sector_map: dict[str, list] = {}
    for r in rows:
        # sector 從 JSON 讀
        sec = lookup_json(r["recommend_date"], r["ticker"], "sector") or "未分類"
        sector_map.setdefault(sec, []).append(r)

    sector_stats = []
    for sec, sr in sector_map.items():
        sr_t1 = [r for r in sr if r["ret_t1"] is not None]
        avg = sum(r["ret_t1"] for r in sr_t1) / len(sr_t1) if sr_t1 else None
        sector_stats.append((sec, len(sr), avg))

    ranked = sorted([x for x in sector_stats if x[2] is not None], key=lambda x: -x[2])

    lines.append("**T+1 平均報酬前 5 族群:**\n")
    lines.append("| 族群 | 筆數 | 平均T+1% |")
    lines.append("|---|---|---|")
    for sec, n, avg in ranked[:5]:
        lines.append(f"| {sec} | {n} | {pct_str(avg)} |")

    lines.append("\n**T+1 平均報酬後 5 族群:**\n")
    lines.append("| 族群 | 筆數 | 平均T+1% |")
    lines.append("|---|---|---|")
    for sec, n, avg in ranked[-5:]:
        lines.append(f"| {sec} | {n} | {pct_str(avg)} |")

    # ── Top 10 / Bottom 10 ───────────────────────────────────
    t1_sorted = sorted([r for r in rows if r["ret_t1"] is not None], key=lambda r: -r["ret_t1"])

    lines.append("\n## Top 10 Winners (T+1)\n")
    lines.append("| 推薦日 | 代號 | 名稱 | P | T+1% | T+5% |")
    lines.append("|---|---|---|---|---|---|")
    for r in t1_sorted[:10]:
        name = lookup_json(r["recommend_date"], r["ticker"], "name", r["ticker"])
        lines.append(
            f"| {r['recommend_date']} | {r['ticker']} | {name} | P{r['priority']} "
            f"| {pct_str(r['ret_t1'])} | {pct_str(r['ret_t5'])} |"
        )

    lines.append("\n## Bottom 10 Losers (T+1)\n")
    lines.append("| 推薦日 | 代號 | 名稱 | P | T+1% | T+5% |")
    lines.append("|---|---|---|---|---|---|")
    for r in t1_sorted[-10:]:
        name = lookup_json(r["recommend_date"], r["ticker"], "name", r["ticker"])
        lines.append(
            f"| {r['recommend_date']} | {r['ticker']} | {name} | P{r['priority']} "
            f"| {pct_str(r['ret_t1'])} | {pct_str(r['ret_t5'])} |"
        )

    # ── Scanner Commit 分布 ───────────────────────────────────
    lines.append("\n## Scanner Commit 分布\n")
    lines.append("| Commit (short) | 筆數 |")
    lines.append("|---|---|")
    commit_count: dict[str, int] = {}
    for r in rows:
        key = r["scanner_commit"] or "(未記錄)"
        commit_count[key] = commit_count.get(key, 0) + 1
    for commit, cnt in sorted(commit_count.items(), key=lambda x: -x[1]):
        lines.append(f"| `{commit}` | {cnt} |")

    # ── 結論段 ────────────────────────────────────────────────
    lines.append("\n## 結論\n")

    best_p = None
    best_avg = None
    for p in [3, 2, 1]:
        pr_t1 = [r for r in rows if r["priority"] == p and r["ret_t1"] is not None]
        if pr_t1:
            avg = sum(r["ret_t1"] for r in pr_t1) / len(pr_t1)
            if best_avg is None or avg > best_avg:
                best_avg = avg
                best_p = p

    best_src = None
    best_src_avg = None
    for src, sr in source_map.items():
        sr_t1 = [r for r in sr if r["ret_t1"] is not None]
        if len(sr_t1) >= 3:
            avg = sum(r["ret_t1"] for r in sr_t1) / len(sr_t1)
            if best_src_avg is None or avg > best_src_avg:
                best_src_avg = avg
                best_src = src

    if best_p:
        lines.append(f"- **最準 Priority**: P{best_p}（T+1 平均 {pct_str(best_avg)}）")
    if best_src:
        lines.append(f"- **最準 Source**: `{best_src}`（T+1 平均 {pct_str(best_src_avg)}，樣本 ≥3）")

    if has_t1:
        overall_up = sum(1 for r in has_t1 if r["ret_t1"] > 0)
        overall_avg = sum(r["ret_t1"] for r in has_t1) / len(has_t1)
        lines.append(f"- **整體 T+1 上漲率**: {hit_rate(overall_up, len(has_t1))}，平均 {pct_str(overall_avg)}")

    lines.append("\n> 樣本數 < 10 時結論僅供參考，不宜調整過濾規則。")

    # ── Footer ───────────────────────────────────────────────
    sv_str = ", ".join(f"v{v}" for v in schema_versions) if schema_versions else "unknown"
    lines.append(
        f"\n---\n"
        f"*報告基於 schema_version={sv_str}，含 {len(commits)} 個 scanner commit: "
        f"{', '.join(commits) if commits else '(無記錄)'}*\n"
        f"*Generated by recommendation_tracker_report.py*\n"
    )

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="推薦命中率月報產生器 v2")
    parser.add_argument("--month", default=datetime.now().strftime("%Y-%m"), help="月份 YYYY-MM（預設當月）")
    args = parser.parse_args()

    conn = get_connection()
    report = generate_report(conn, args.month)
    conn.close()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORT_DIR / f"{args.month}.md"
    out_path.write_text(report, encoding="utf-8")

    size_kb = out_path.stat().st_size / 1024
    print(f"月報已寫入: {out_path} ({size_kb:.1f} KB)")
    print("\n--- 預覽 ---")
    print(report[:2000])


if __name__ == "__main__":
    main()
