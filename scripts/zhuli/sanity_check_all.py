"""跨 scanner 整合 sanity check — 跑 4 套 + 寫 markdown 報告.

Usage:
    python scripts/zhuli/sanity_check_all.py [--db PATH] [--verbose]
                                              [--out PATH]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

_WORKTREE = Path(__file__).parent.parent.parent
_SCRIPTS_DIR = _WORKTREE / "scripts"
for _p in [str(_WORKTREE), str(_SCRIPTS_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kline.bars import DEFAULT_DB_PATH

from zhuli.sanity_check import run_sanity_check as run_h
from zhuli.sanity_check_open_signal import run_sanity_check as run_m
from zhuli.sanity_check_institutional import run_sanity_check as run_j
from zhuli.sanity_check_swing import run_sanity_check as run_a
from zhuli.sanity_check_bbands import run_sanity_check as run_d
from zhuli.sanity_check_overnight import run_sanity_check as run_g
from zhuli.sanity_check import EXPECTED_CASES as H_CASES
from zhuli.sanity_check_open_signal import INSTRUCTOR_CASES as M_CASES
from zhuli.sanity_check_institutional import INSTRUCTOR_CASES as J_CASES
from zhuli.sanity_check_swing import CASES as A_CASES
from zhuli.sanity_check_bbands import INSTRUCTOR_CASES as D_CASES
from zhuli.sanity_check_overnight import INSTRUCTOR_CASES as G_CASES


# ── 統一 result normalizer ─────────────────────────────────────────────────────
def normalize_h(result: dict) -> list[dict]:
    """H sanity 結構：results 含 ticker/name/result/scenario/etc."""
    out = []
    for r in result.get("results", []):
        ticker = r["ticker"]
        case = next((c for c in H_CASES if c["ticker"] == ticker), {})
        out.append({
            "scanner": "H 窒息量",
            "ticker": ticker,
            "name": r.get("name", case.get("name", "")),
            "date": "/".join(case.get("date_range", ("?", "?"))),
            "status": r.get("result", "?"),
            "category": case.get("divergence_category"),
            "note": case.get("note", r.get("reason", "")),
        })
    return out


def normalize_m(result: dict) -> list[dict]:
    out = []
    for r in result.get("results", []):
        out.append({
            "scanner": "M 收高開低",
            "ticker": r["ticker"],
            "name": r["name"],
            "date": r.get("signal_date", "?"),
            "status": r.get("result", "?"),
            "category": r.get("divergence_category"),
            "note": r.get("note", ""),
        })
    return out


def normalize_j(result: dict) -> list[dict]:
    out = []
    for r in result.get("results", []):
        out.append({
            "scanner": "J 投信首買",
            "ticker": r["ticker"],
            "name": r["name"],
            "date": r.get("signal_date", "?"),
            "status": r.get("result", "?"),
            "category": r.get("divergence_category"),
            "note": r.get("note", ""),
        })
    return out


def normalize_d(result: dict) -> list[dict]:
    out = []
    for r in result.get("results", []):
        out.append({
            "scanner": "D 布林上軌",
            "ticker": r["ticker"],
            "name": r["name"],
            "date": r.get("signal_date", "?"),
            "status": r.get("result", "?"),
            "category": r.get("divergence_category"),
            "note": r.get("note", ""),
        })
    return out


def normalize_g(result: dict) -> list[dict]:
    out = []
    for r in result.get("results", []):
        out.append({
            "scanner": "G 隔日沖",
            "ticker": r["ticker"],
            "name": r["name"],
            "date": r.get("signal_date", "?"),
            "status": r.get("result", "?"),
            "category": r.get("divergence_category"),
            "note": r.get("note", ""),
        })
    return out


def normalize_a(result: dict) -> list[dict]:
    out = []
    for r in result.get("results", []):
        ticker = r.get("ticker", "?")
        date_str = r.get("date", "?")
        case = next((c for c in A_CASES if c["ticker"] == ticker and c["date"] == date_str), {})
        out.append({
            "scanner": "A 大波段",
            "ticker": ticker,
            "name": r.get("name", ""),
            "date": date_str,
            "status": r.get("result", "?"),
            "category": case.get("divergence_category"),
            "note": case.get("note", r.get("reason", "")),
        })
    return out


def categorize(status: str, category: str | None) -> str:
    """把 status + divergence_category 映射成統一分類."""
    s = (status or "").lower()
    if s in ("hit", "pass", "suffocation_found", "suffocation_only_hit", "suffocation_hit"):
        return "strict_hit"
    if s == "partial_hit":
        return "partial_hit"
    if s in ("no_bar_data", "no_institutional_data", "skip"):
        return "data_gap"
    if s in ("miss", "fail", "suffocation_missing"):
        if category:
            return f"known_divergence ({category})"
        return "unexpected_miss"
    return f"other ({s})"


def run_all(db_path: Path, verbose: bool = False) -> dict:
    """跑 4 套 sanity 並彙整。

    Returns dict:
        scanners: {name: result}
        all_rows: 統一格式 list
        totals: dict
        passed: bool
    """
    print("=" * 60)
    print("跑 4 套 sanity check")
    print("=" * 60)

    if verbose:
        print("\n--- H 窒息量 ---")
    h_result = run_h(db_path=db_path, verbose=verbose)

    if verbose:
        print("\n--- M 收高開低 ---")
    m_result = run_m(db_path=db_path, verbose=verbose)

    if verbose:
        print("\n--- J 投信首買 ---")
    j_result = run_j(db_path=db_path, verbose=verbose)

    if verbose:
        print("\n--- A 大波段 ---")
    a_result = run_a(db_path=db_path, verbose=verbose)

    if verbose:
        print("\n--- D 布林上軌 ---")
    d_result = run_d(db_path=db_path, verbose=verbose)

    if verbose:
        print("\n--- G 隔日沖 ---")
    g_result = run_g(db_path=db_path, verbose=verbose)

    all_rows = []
    all_rows.extend(normalize_h(h_result))
    all_rows.extend(normalize_m(m_result))
    all_rows.extend(normalize_j(j_result))
    all_rows.extend(normalize_a(a_result))
    all_rows.extend(normalize_d(d_result))
    all_rows.extend(normalize_g(g_result))

    # 統計
    totals = {
        "strict_hit": 0,
        "partial_hit": 0,
        "known_divergence": 0,
        "data_gap": 0,
        "unexpected_miss": 0,
        "other": 0,
    }
    for row in all_rows:
        cat = categorize(row["status"], row["category"])
        row["unified_category"] = cat
        if cat.startswith("known_divergence"):
            totals["known_divergence"] += 1
        elif cat.startswith("other"):
            totals["other"] += 1
        elif cat in totals:
            totals[cat] += 1

    passed = totals["unexpected_miss"] == 0

    return {
        "scanners": {
            "H 窒息量": h_result,
            "M 收高開低": m_result,
            "J 投信首買": j_result,
            "A 大波段": a_result,
            "D 布林上軌": d_result,
            "G 隔日沖": g_result,
        },
        "all_rows": all_rows,
        "totals": totals,
        "passed": passed,
        "total_cases": len(all_rows),
    }


def write_markdown_report(summary: dict, out_path: Path) -> None:
    """輸出整合 markdown 報告."""
    totals = summary["totals"]
    total = summary["total_cases"]

    lines = []
    lines.append("# Phase 1 講師案例端對端驗證")
    lines.append("")
    lines.append(f"> 評估日期：{date.today().isoformat()}")
    lines.append(f"> DB 範圍：bars + institutional 2020-01 ~ 2021-12 backfill")
    lines.append(f"> 案例總數：{total} cases（H 5 + M 2 + J 2 + A 4 + D 3 + G 3）")
    lines.append(f"> **判定：{'✅ PASSED' if summary['passed'] else '❌ FAILED'}**")
    lines.append("")
    lines.append("## 總表")
    lines.append("")
    lines.append("| Scanner | 案例 | strict hit | partial | known divergence | data gap | unexpected miss |")
    lines.append("|---|---|---|---|---|---|---|")

    scanner_groups = {}
    for row in summary["all_rows"]:
        scanner_groups.setdefault(row["scanner"], []).append(row)

    for sc_name in ["H 窒息量", "M 收高開低", "J 投信首買", "A 大波段", "D 布林上軌", "G 隔日沖"]:
        rows = scanner_groups.get(sc_name, [])
        n = len(rows)
        n_hit = sum(1 for r in rows if r["unified_category"] == "strict_hit")
        n_partial = sum(1 for r in rows if r["unified_category"] == "partial_hit")
        n_known = sum(1 for r in rows if r["unified_category"].startswith("known_divergence"))
        n_skip = sum(1 for r in rows if r["unified_category"] == "data_gap")
        n_miss = sum(1 for r in rows if r["unified_category"] == "unexpected_miss")
        lines.append(f"| {sc_name} | {n} | {n_hit} | {n_partial} | {n_known} | {n_skip} | {n_miss} |")

    lines.append(f"| **總計** | **{total}** | **{totals['strict_hit']}** | "
                 f"**{totals['partial_hit']}** | **{totals['known_divergence']}** | "
                 f"**{totals['data_gap']}** | **{totals['unexpected_miss']}** |")
    lines.append("")

    lines.append("## 各 Scanner 詳情")
    lines.append("")
    for sc_name in ["H 窒息量", "M 收高開低", "J 投信首買", "A 大波段", "D 布林上軌", "G 隔日沖"]:
        rows = scanner_groups.get(sc_name, [])
        if not rows:
            continue
        lines.append(f"### {sc_name}")
        lines.append("")
        lines.append("| ticker | name | date | result | category | note |")
        lines.append("|---|---|---|---|---|---|")
        for r in rows:
            cat = r["unified_category"]
            icon = {
                "strict_hit": "✓",
                "partial_hit": "◐",
                "data_gap": "⚠️",
                "unexpected_miss": "✗",
            }.get(cat, "ⓘ" if cat.startswith("known_divergence") else "?")
            note = (r["note"] or "").replace("|", "\\|").replace("\n", " ")
            cat_label = cat
            lines.append(f"| {r['ticker']} | {r['name']} | {r['date']} | "
                         f"{icon} {r['status']} | {cat_label} | {note} |")
        lines.append("")

    lines.append("## Divergence 分類解析")
    lines.append("")
    lines.append("- **strict_hit**：scanner 完整命中講師範例")
    lines.append("- **partial_hit**：命中部分 signal_type（如 M 同日多重訊號未全中）")
    lines.append("- **known_divergence**：已記錄落差（不算 FAIL）")
    lines.append("  - `mechanical_strict`：scanner 機械嚴格，講師判斷較寬鬆")
    lines.append("  - `spec_ambiguous`：講師範例 spec 含糊")
    lines.append("  - `data_gap`：FinMind 與富邦軟體資料差異")
    lines.append("- **data_gap (skip)**：DB 缺資料無法測（非邏輯錯）")
    lines.append("- **unexpected_miss**：應該命中但 scanner 沒抓到，需要查 spec / detector")
    lines.append("")

    lines.append("## 結論")
    lines.append("")
    lines.append(f"- 嚴格命中：**{totals['strict_hit']} / {total}**")
    lines.append(f"- 已知落差（已記錄）：{totals['known_divergence']}")
    lines.append(f"- 資料缺漏：{totals['data_gap']}")
    lines.append(f"- 意外漏抓：**{totals['unexpected_miss']}**")
    lines.append("")
    if summary["passed"]:
        lines.append("✅ **Phase 1 收尾驗收 PASSED** — 無意外漏抓，所有落差已分類記錄。")
    else:
        lines.append(f"❌ **Phase 1 收尾驗收 FAILED** — {totals['unexpected_miss']} 個意外漏抓需要查。")
    lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n報告已寫入：{out_path}")


def main():
    parser = argparse.ArgumentParser(
        description="跨 scanner 整合 sanity check — 4 套全跑 + 寫整合 markdown 報告。"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument(
        "--out",
        type=Path,
        default=_WORKTREE / "docs" / "主力大課程" / "all_instructor_cases_validation.md",
    )
    args = parser.parse_args()

    summary = run_all(args.db, verbose=args.verbose)

    print()
    print("=" * 60)
    print(f"跨 scanner 整合摘要：{summary['total_cases']} cases")
    print("=" * 60)
    t = summary["totals"]
    print(f"   strict_hit:        {t['strict_hit']} / {summary['total_cases']}")
    print(f"   partial_hit:       {t['partial_hit']}")
    print(f"   known_divergence:  {t['known_divergence']}")
    print(f"   data_gap:          {t['data_gap']}")
    print(f"   unexpected_miss:   {t['unexpected_miss']}")
    print(f"   other:             {t['other']}")
    print("=" * 60)

    write_markdown_report(summary, args.out)
    sys.exit(0 if summary["passed"] else 1)


if __name__ == "__main__":
    main()
