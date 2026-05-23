"""每日盤後 scanner 批次任務 — 跑三個結構 scanner 找明日打擊區候選.

依 daily scanner enforcement 規則（每個開盤日前晚-早上未跑要提醒）。

每個交易日 14:30 由 launchd 觸發跑此 script:
  1. 跑 shakeout_strong + small_structure + w_bottom_launch 全市場
  2. 取聯集 → 候選清單
  3. shakeout_strong 命中 + 老師常駐族群 → 標 ⭐（EV +10.1% vs +5.1% baseline）
  4. 輸出 markdown 到 /tmp/scanner_candidates_<DATE>.md
  5. 寫 flag 到 /tmp/scanner_done_<DATE>.flag（給 morning_report 跟 Claude session 檢查）

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

from kline.extras.shakeout_strong import detect as detect_shakeout        # noqa
from zhuli.entry.small_structure import detect as detect_small_structure  # noqa
from zhuli.entry.w_bottom_launch import detect as detect_wbottom          # noqa

# 以下 scanner 尚未驗證門檻值，暫不加入 daily job
# from zhuli.entry.bbands_upper_break import detect as detect_bbands
# from zhuli.entry.bollinger_pullback import detect as detect_bb_pullback
# from zhuli.entry.intraday import detect as detect_intraday
# from zhuli.entry.overnight_swing import detect as detect_overnight
# from zhuli.entry.open_signal_entry import detect as detect_open_entry
# from zhuli.entry.open_signal_exit import detect as detect_open_exit
# from zhuli.entry.open_signal_filter import detect as detect_open_filter
# from zhuli.entry.pennant_flag import detect as detect_pennant
# from zhuli.entry.reversal_breakout import detect as detect_reversal
# from zhuli.entry.suffocation import detect as detect_suffocation

_DB   = Path.home() / ".four_seasons" / "data.sqlite"
_TMP  = Path("/tmp")
_REPO = Path(__file__).parent.parent.parent

# 老師族群對應表（teacher_sector_tickers.json）
# ticker → [族群1, 族群2, ...]
def _load_teacher_sectors() -> dict[str, list[str]]:
    import json
    p = _REPO / "docs" / "主力大課程" / "teacher_sector_tickers.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    mapping: dict[str, list[str]] = {}
    for sector, tickers in data.items():
        for t in tickers:
            mapping.setdefault(t, []).append(sector)
    return mapping

TEACHER_SECTOR_MAP: dict[str, list[str]] = _load_teacher_sectors()


def _db_uri(path: Path) -> str:
    return f"file:{path}?mode=ro"


def load_stock_info(db_path: Path) -> dict[str, dict]:
    """回傳 {ticker: {name, industry}} 對照表."""
    con = sqlite3.connect(_db_uri(db_path), uri=True, timeout=5)
    rows = con.execute(
        "SELECT ticker, stock_name, industry_category FROM stock_info"
    ).fetchall()
    con.close()
    return {r[0]: {"name": r[1], "industry": r[2] or ""} for r in rows}


def run_scanners(target_date: str, db_path: Path) -> dict[str, list[dict]]:
    """跑三個 scanner 並回傳每個的命中清單."""
    con = sqlite3.connect(_db_uri(db_path), uri=True, timeout=15)
    stock_info = load_stock_info(db_path)

    # 全市場 ticker
    all_tickers = [
        r[0] for r in con.execute(
            "SELECT DISTINCT ticker FROM standard_daily_bar WHERE trade_date=?",
            (target_date,)
        ).fetchall()
    ]

    results = {'shakeout_strong': [], 'small_structure': [], 'w_bottom_launch': []}
    # ⚠️ 只放已驗證門檻的 scanner
    # 加入新 scanner 前必須先跑 5/20→5/21 回測確認上漲率 + 平均漲幅合理
    scanners = {
        'w_bottom_launch':  detect_wbottom,         # 84% 上漲、平均 +2.54%（已驗證）
        'small_structure':  detect_small_structure,  # 77% 上漲、平均 +1.99%（已驗證）
        'shakeout_strong':  detect_shakeout,         # 3/3 案例命中（已驗證，需 overhead 特徵）
    }

    for t in all_tickers:
        df = pd.read_sql("""
            SELECT ? as ticker,
                   trade_date, trade_date as date,
                   open, high, low, close, volume,
                   vol_ratio_20, ma5, ma10, ma20, ma60,
                   vol_ma20, bb_upper, bb_lower, bb_mid,
                   ma20_slope, ma20_slope_proxy
            FROM standard_daily_bar
            WHERE ticker=? AND trade_date >= date(?, '-200 days') AND trade_date <= ?
            ORDER BY trade_date
        """, con, params=(t, t, target_date, target_date))
        if len(df) < 100:
            continue

        # 補充 derived columns
        df['prev_close'] = df['close'].shift(1)
        df['prev_open'] = df['open'].shift(1)
        df['prev_high'] = df['high'].shift(1)
        df['prev_low'] = df['low'].shift(1)
        df['ma5_slope_5d'] = df['ma5'].diff(5)
        df['volume_ratio'] = df['vol_ratio_20']  # alias

        last_close = df.iloc[-1]['close']
        info = stock_info.get(t, {"name": "", "industry": ""})
        teacher_sectors = TEACHER_SECTOR_MAP.get(t, [])  # 老師族群（可能跨多個）

        for name, fn in scanners.items():
            try:
                sig = fn(df)
                if hasattr(sig, 'iloc') and sig.iloc[-1]:
                    hit = {
                        'ticker': t,
                        'name': info['name'],
                        'industry': info['industry'],
                        'teacher_sectors': teacher_sectors,
                        'close': float(last_close),
                    }
                    # shakeout × 老師曾提過的族群 → tier-1 標記
                    if name == 'shakeout_strong' and teacher_sectors:
                        hit['tier1'] = True
                    results[name].append(hit)
            except Exception:
                pass

    con.close()
    return results


def render_markdown(target_date: str, results: dict[str, list[dict]]) -> str:
    """產出明日打擊區候選 markdown."""
    # hit_meta: ticker → {scanners, name, teacher_sectors, close, tier1}
    hit_meta: dict[str, dict] = {}
    for scanner, hits in results.items():
        for h in hits:
            t = h['ticker']
            if t not in hit_meta:
                ts = h.get('teacher_sectors', [])
                hit_meta[t] = {
                    'name': h.get('name', ''),
                    'industry': h.get('industry', ''),
                    'teacher_sectors': ts,
                    'sector_str': '/'.join(ts) if ts else h.get('industry', ''),
                    'close': h['close'],
                    'scanners': set(),
                    'tier1': False,
                }
            hit_meta[t]['scanners'].add(scanner)
            if h.get('tier1'):
                hit_meta[t]['tier1'] = True

    # tier-1 shakeout 清單
    tier1 = [t for t, m in hit_meta.items() if m['tier1']]
    tier1_count = len(tier1)

    # 排序：tier1 優先，再依共識數
    sorted_tickers = sorted(
        hit_meta.items(),
        key=lambda x: (not x[1]['tier1'], -len(x[1]['scanners']), x[0])
    )

    md = [
        f"# 打擊區候選 — {target_date} 收盤後",
        f"",
        f"> 三個結構 scanner 聯集，依 tier-1 ⭐ → 共識數排序",
        f"> ⭐ = shakeout_strong × 老師常駐族群（EV +10.1% vs 全量 +5.1%，2026 驗證）",
        f"",
        f"## 各 scanner 統計",
        f"",
        f"| Scanner | 命中數 |",
        f"|---|---|",
    ]
    for s, hits in results.items():
        md.append(f"| {s} | {len(hits)} |")

    md += [
        f"| **聯集** | **{len(hit_meta)}** |",
        f"| **⭐ tier-1 shakeout** | **{tier1_count}** |",
        f"",
    ]

    if tier1_count:
        md += [
            f"## ⭐ Tier-1：shakeout × 老師族群（{tier1_count} 檔）",
            f"",
            f"| Ticker | 名稱 | 族群 | 收盤 | 其他 scanner |",
            f"|---|---|---|---|---|",
        ]
        for t, m in sorted_tickers:
            if not m['tier1']:
                continue
            others = sorted(m['scanners'] - {'shakeout_strong'})
            other_str = ', '.join(others) if others else '—'
            md.append(f"| {t} | {m['name']} | {m['sector_str']} | {m['close']:.2f} | {other_str} |")
        md.append(f"")

    md += [
        f"## 高共識候選（≥ 2 個 scanner，非 tier-1）",
        f"",
        f"| Ticker | 名稱 | 族群 | Scanners | 收盤 |",
        f"|---|---|---|---|---|",
    ]
    high_consensus = [(t, m) for t, m in sorted_tickers if len(m['scanners']) >= 2 and not m['tier1']]
    for t, m in high_consensus[:30]:
        md.append(f"| {t} | {m['name']} | {m['sector_str']} | {', '.join(sorted(m['scanners']))} | {m['close']:.2f} |")
    if not high_consensus:
        md.append("| — | — | — | — | — |")

    md += [
        f"",
        f"## 各 scanner 單獨命中（前 20 / 每 scanner）",
        f"",
    ]
    for s, hits in results.items():
        md.append(f"### {s} ({len(hits)} 檔)")
        md.append(f"")
        md.append(f"| Ticker | 名稱 | 族群 | 收盤 | ⭐ |")
        md.append(f"|---|---|---|---|---|")
        for h in hits[:20]:
            star = "⭐" if h.get('tier1') else ""
            md.append(f"| {h['ticker']} | {h.get('name','')} | {'/'.join(h.get('teacher_sectors',[])) or h.get('industry','')} | {h['close']:.2f} | {star} |")
        md.append(f"")

    md += [
        f"---",
        f"",
        f"## 下一步動作",
        f"",
        f"1. **盤後 17:00-22:00**: 對照老師當日 line / 培訓清單，找出**雙重命中**個股",
        f"2. **凌晨 1:00+**: 偵測老師凌晨新文章，加入清單",
        f"3. **明早 8:30**: 對清單做試撮判斷，⭐ 優先考慮，符合條件試單 1/3",
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
