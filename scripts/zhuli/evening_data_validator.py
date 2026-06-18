"""Evening data validator — 驗證 evening_fetch.sh 跑完後資料完整性.

用途:
  在 evening_fetch.sh 跑完後 (建議 22:00) 驗證該到的資料有沒有到位、
  避免 stale data 污染 daily_scanner / monitor 等下游 (e.g. regime_info TAIEX stale bug)。

檢查清單:
  1. TAIEX daily K (standard_daily_bar)
  2. 老師 universe daily K (覆蓋率 ≥ 95%)
  3. 老師 universe 法人 (institutional_investors、覆蓋率 ≥ 95%)
  4. 老師 universe 1分K (stock_minute_kbar、樣本 30 檔 ≥ 80%)
  5. overnight_static_features.json (mtime ≥ target_date)

Exit code:
  0 = 全 OK
  1 = critical missing (TAIEX 缺、daily K < 95%)
  2 = warning (1分K / 法人 部分缺、overnight_static stale)

Usage:
  python scripts/zhuli/evening_data_validator.py [--date YYYY-MM-DD] [--strict]
"""
from __future__ import annotations
import argparse
import json
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

_REPO = Path("/Users/howard/Repository/stock-k-bar")
_DB = Path.home() / ".four_seasons" / "data.sqlite"
_TEACHER_JSON = _REPO / "docs" / "主力大課程" / "teacher_sector_tickers.json"
_OVERNIGHT_JSON = _REPO / "data" / "analysis" / "zhuli" / "overnight_static_features.json"


def _load_teacher_universe() -> set[str]:
    if not _TEACHER_JSON.exists():
        return set()
    d = json.loads(_TEACHER_JSON.read_text())
    out = set()
    for sec, tks in d.items():
        out.update(tks)
    return out


def _max_date(con, table, where) -> str | None:
    try:
        r = con.execute(f"SELECT MAX({where[0]}) FROM {table} WHERE {where[1]}").fetchone()
        return r[0] if r else None
    except Exception:
        return None


def validate(target_date: str) -> tuple[int, list[dict]]:
    """Run all checks. Return (exit_code, results)."""
    con = sqlite3.connect(str(_DB))
    universe = _load_teacher_universe()
    n_total = len(universe)
    results = []
    critical = 0
    warning = 0

    # 1. TAIEX daily K
    r = con.execute("SELECT 1 FROM standard_daily_bar WHERE ticker='TAIEX' AND trade_date=?", (target_date,)).fetchone()
    status = "ok" if r else "critical"
    if status == "critical":
        critical += 1
    results.append({
        "check": "TAIEX daily K",
        "expected": target_date,
        "actual": target_date if r else "missing",
        "status": status,
        "action": "" if r else "backfill TAIEX from FinMind (TaiwanStockPrice TAIEX)",
    })

    # 2. 老師 universe daily K coverage
    cov_daily = 0
    for t in universe:
        r = con.execute("SELECT 1 FROM standard_daily_bar WHERE ticker=? AND trade_date=?", (t, target_date)).fetchone()
        if r: cov_daily += 1
    pct = cov_daily / n_total * 100 if n_total else 0
    if pct >= 95:
        status = "ok"
    elif pct >= 80:
        status = "warning"; warning += 1
    else:
        status = "critical"; critical += 1
    results.append({
        "check": "老師 universe daily K",
        "expected": f">= 95% ({n_total})",
        "actual": f"{cov_daily}/{n_total} ({pct:.1f}%)",
        "status": status,
        "action": "" if status == "ok" else "check daily_fetcher / evening_fetch daily K backfill",
    })

    # 3. 老師 universe 法人 coverage
    cov_inst = 0
    for t in universe:
        r = con.execute("SELECT 1 FROM institutional_investors WHERE ticker=? AND trade_date=?", (t, target_date)).fetchone()
        if r: cov_inst += 1
    pct = cov_inst / n_total * 100 if n_total else 0
    if pct >= 95:
        status = "ok"
    elif pct >= 80:
        status = "warning"; warning += 1
    else:
        status = "critical"; critical += 1
    results.append({
        "check": "老師 universe 法人",
        "expected": f">= 95% ({n_total})",
        "actual": f"{cov_inst}/{n_total} ({pct:.1f}%)",
        "status": status,
        "action": "" if status == "ok" else "run scripts/zhuli/backfill_institutional.py --start-date",
    })

    # 4. 老師 universe 1分K (sample 30)
    sample = sorted(universe)[::max(1, n_total // 30)][:30]
    cov_min = 0
    for t in sample:
        r = con.execute("SELECT 1 FROM stock_minute_kbar WHERE ticker=? AND trade_datetime LIKE ? LIMIT 1", (t, f'{target_date}%')).fetchone()
        if r: cov_min += 1
    pct = cov_min / len(sample) * 100 if sample else 0
    if pct >= 80:
        status = "ok"
    elif pct >= 60:
        status = "warning"; warning += 1
    else:
        status = "critical"; critical += 1
    results.append({
        "check": "老師 universe 1分K (sample 30)",
        "expected": ">= 80%",
        "actual": f"{cov_min}/{len(sample)} ({pct:.1f}%)",
        "status": status,
        "action": "" if status == "ok" else "check backfill_minute_kbar (FinMind sponsor TaiwanStockKBar)",
    })

    # 5. overnight_static_features.json freshness
    if _OVERNIGHT_JSON.exists():
        mtime = datetime.fromtimestamp(_OVERNIGHT_JSON.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        mdate = mtime[:10]
        fresh = mdate >= target_date
        status = "ok" if fresh else "warning"
        if not fresh: warning += 1
        results.append({
            "check": "overnight_static_features.json",
            "expected": f"mtime >= {target_date}",
            "actual": mtime,
            "status": status,
            "action": "" if fresh else "run scripts/zhuli/precompute_overnight_static.py",
        })
    else:
        critical += 1
        results.append({
            "check": "overnight_static_features.json",
            "expected": "exists",
            "actual": "missing",
            "status": "critical",
            "action": "run scripts/zhuli/precompute_overnight_static.py",
        })

    exit_code = 1 if critical > 0 else (2 if warning > 0 else 0)
    return exit_code, results


def render(target_date: str, results: list[dict], exit_code: int) -> str:
    lines = [
        f"=== Evening Data Validator === {target_date} ===",
        "",
        f"{'Check':<35}{'Expected':<25}{'Actual':<28}{'Status':<10}",
        "-" * 100,
    ]
    icon = {"ok": "✅ OK", "warning": "⚠️ WARN", "critical": "🔴 CRIT"}
    for r in results:
        lines.append(f"{r['check']:<35}{r['expected']:<25}{r['actual']:<28}{icon[r['status']]:<10}")
    lines.append("")
    lines.append("Actions needed:")
    for r in results:
        if r['action']:
            lines.append(f"  - {r['check']}: {r['action']}")
    n_crit = sum(1 for r in results if r['status'] == 'critical')
    n_warn = sum(1 for r in results if r['status'] == 'warning')
    n_ok = sum(1 for r in results if r['status'] == 'ok')
    lines.append("")
    lines.append(f"Summary: ✅ {n_ok} ok / ⚠️ {n_warn} warn / 🔴 {n_crit} critical → exit {exit_code}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="target date (default: today)")
    ap.add_argument("--strict", action="store_true", help="exit 1 on warning too")
    ap.add_argument("--json", action="store_true", help="output JSON instead of text")
    args = ap.parse_args()
    target = args.date or date.today().strftime("%Y-%m-%d")
    exit_code, results = validate(target)
    if args.json:
        print(json.dumps({"date": target, "exit_code": exit_code, "results": results}, ensure_ascii=False, indent=2))
    else:
        print(render(target, results, exit_code))
    if args.strict and exit_code == 2:
        exit_code = 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
