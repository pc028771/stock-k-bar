"""每日盤後 scanner 批次任務 — 跑三個結構 scanner 找明日打擊區候選.

依 daily scanner enforcement 規則（每個開盤日前晚-早上未跑要提醒）。

每個交易日 14:30 由 launchd 觸發跑此 script:
  1. 跑 shakeout_strong + small_structure + w_bottom_launch 全市場
  2. 取聯集 → 候選清單
  3. 輸出 markdown 到 /tmp/scanner_candidates_<DATE>.md
  4. 寫 flag 到 /tmp/scanner_done_<DATE>.flag（給 morning_report 跟 Claude session 檢查）

Usage:
  python scripts/zhuli/daily_scanner_job.py [--date YYYY-MM-DD] [--db PATH]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import pandas as pd

# Path setup
_REPO = Path(__file__).parent.parent.parent
_SYS = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_REPO), str(_REPO / "scripts"), str(_SYS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kline.extras.shakeout_strong import detect as detect_shakeout  # type: ignore
from zhuli.entry.small_structure import detect as detect_small_structure  # type: ignore
from zhuli.entry.w_bottom_launch import detect as detect_wbottom  # type: ignore

_DB = Path.home() / ".four_seasons" / "data.sqlite"
_TMP = Path("/tmp")


def _db_uri(path: Path) -> str:
    return f"file:{path}?mode=ro"


def run_scanners(target_date: str, db_path: Path) -> dict[str, list[dict]]:
    """跑三個 scanner 並回傳每個的命中清單."""
    con = sqlite3.connect(_db_uri(db_path), uri=True, timeout=15)

    # 全市場 ticker
    all_tickers = [
        r[0] for r in con.execute(
            "SELECT DISTINCT ticker FROM standard_daily_bar WHERE trade_date=?",
            (target_date,)
        ).fetchall()
    ]

    results = {'shakeout_strong': [], 'small_structure': [], 'w_bottom_launch': []}
    scanners = {
        'shakeout_strong': detect_shakeout,
        'small_structure': detect_small_structure,
        'w_bottom_launch': detect_wbottom,
    }

    for t in all_tickers:
        df = pd.read_sql("""
            SELECT trade_date as date, open, high, low, close, vol_ratio_20, ma5, ma10, ma20
            FROM standard_daily_bar
            WHERE ticker=? AND trade_date >= date(?, '-200 days') AND trade_date <= ?
            ORDER BY trade_date
        """, con, params=(t, target_date, target_date))
        if len(df) < 100:
            continue
        last_close = df.iloc[-1]['close']

        for name, fn in scanners.items():
            try:
                sig = fn(df)
                if sig.iloc[-1]:
                    results[name].append({'ticker': t, 'close': float(last_close)})
            except Exception:
                pass

    con.close()
    return results


def render_markdown(target_date: str, results: dict[str, list[dict]]) -> str:
    """產出明日打擊區候選 markdown."""
    union = defaultdict(set)
    for scanner, hits in results.items():
        for h in hits:
            union[h['ticker']].add(scanner)

    # 排序：多個 scanner 共識的優先
    sorted_tickers = sorted(union.items(), key=lambda x: (-len(x[1]), x[0]))

    md = [
        f"# 打擊區候選 — {target_date} 收盤後 / {(date.fromisoformat(target_date)).isoformat()} 開盤前",
        f"",
        f"> 三個結構 scanner 聯集，依共識數排序",
        f"> Scanner: shakeout_strong（底部窒息）/ small_structure（高位整理）/ w_bottom_launch（W 底起漲）",
        f"",
        f"## 各 scanner 統計",
        f"",
        f"| Scanner | 命中數 |",
        f"|---|---|",
    ]
    for s, hits in results.items():
        md.append(f"| {s} | {len(hits)} |")

    md += [
        f"| **聯集** | **{len(union)}** |",
        f"",
        f"## 高共識候選（≥ 2 個 scanner 命中）",
        f"",
        f"| Ticker | Scanners | Count |",
        f"|---|---|---|",
    ]
    high_consensus = [(t, s) for t, s in sorted_tickers if len(s) >= 2]
    for t, scanners_hit in high_consensus[:30]:
        md.append(f"| {t} | {', '.join(sorted(scanners_hit))} | {len(scanners_hit)} |")

    if not high_consensus:
        md.append("| — | — | — |")

    md += [
        f"",
        f"## 各 scanner 單獨命中（前 20 / 每 scanner）",
        f"",
    ]
    for s, hits in results.items():
        md.append(f"### {s} ({len(hits)} 檔)")
        md.append(f"")
        for h in hits[:20]:
            md.append(f"- {h['ticker']}  收盤 {h['close']:.2f}")
        md.append(f"")

    md += [
        f"---",
        f"",
        f"## 下一步動作",
        f"",
        f"1. **盤後 17:00-22:00**: 對照老師當日 line / 培訓清單，找出**雙重命中**個股",
        f"2. **凌晨 1:00+**: 偵測老師凌晨新文章，加入清單",
        f"3. **明早 8:30**: 對清單做試撮判斷，符合條件試單 1/3",
        f"",
        f"產生時間: {datetime.now():%Y-%m-%d %H:%M:%S}",
    ]
    return "\n".join(md)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="目標收盤日（預設今天）")
    ap.add_argument("--db", default=str(_DB))
    ap.add_argument("--output-dir", default="/tmp")
    args = ap.parse_args()

    target_date = args.date or date.today().isoformat()
    db_path = Path(args.db)
    out_dir = Path(args.output_dir)

    print(f"=== Daily Scanner Job ===")
    print(f"目標日期: {target_date}")
    print(f"DB: {db_path}")
    print()

    results = run_scanners(target_date, db_path)

    print(f"\n結果:")
    for s, hits in results.items():
        print(f"  {s}: {len(hits)} 檔")

    md = render_markdown(target_date, results)

    out_md = out_dir / f"scanner_candidates_{target_date}.md"
    out_md.write_text(md, encoding="utf-8")
    print(f"\n→ 寫入 {out_md}")

    flag = out_dir / f"scanner_done_{target_date}.flag"
    flag.write_text(f"done at {datetime.now().isoformat()}\n")
    print(f"→ flag {flag}")


if __name__ == "__main__":
    main()
