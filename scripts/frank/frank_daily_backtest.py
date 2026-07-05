#!/usr/bin/env python3
"""(e)(f) Frank 戰法 daily-level 回測引擎

Entry (Setup 2 日 K 中軌分歧 近似):
  ma20_slope > 0 AND close > ma20 AND 前日 close <= 前日 ma5 AND 今日 close > ma5
  → 以當日收盤進場 (Frank: 尾盤確認)

Exit (分層):
  - 進場後曾 bb_position > 100 (開布林) → 飆股守5日: 收盤 < ma5 出
  - 否則: 連 2 日收盤 < ma20 出 OR ma20_slope < 0 出
  - 期末 (資料最後一天) 強制平倉

(e) universe = user 交易過的 ticker, (f) universe = 老師 353 檔
Output: docs/frank/backtest/ef_report.md
"""
from __future__ import annotations

import sys
import json
from pathlib import Path
from collections import defaultdict

_REPO = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO / "scripts"))
from zhuli.db import get_conn

START, END = "2026-03-01", "2026-07-03"


def load_daily(conn, ticker):
    q = """SELECT trade_date, close, ma5, ma20, ma20_slope, bb_position
           FROM standard_daily_bar
           WHERE ticker=? AND trade_date BETWEEN ? AND ? AND close > 0
           ORDER BY trade_date"""
    return conn.execute(q, (ticker, START, END)).fetchall()


def simulate(bars):
    """Return list of trades: (entry_date, entry_px, exit_date, exit_px, ret_pct, opened_bb)."""
    trades = []
    pos = None  # dict(entry_date, entry_px, opened_bb, below_ma20_days)
    for i in range(1, len(bars)):
        d, c, ma5, ma20, slope, bpos = bars[i]
        _, pc, pma5, *_ = bars[i - 1]
        if None in (c, ma5, ma20, slope):
            continue
        if pos:
            if bpos and bpos > 100:
                pos["opened_bb"] = True
            exit_now = False
            if pos["opened_bb"]:
                if c < ma5:
                    exit_now = True
            else:
                pos["below"] = pos["below"] + 1 if c < ma20 else 0
                if pos["below"] >= 2 or slope < 0:
                    exit_now = True
            if exit_now or i == len(bars) - 1:
                trades.append({
                    "entry_date": pos["entry_date"], "entry_px": pos["entry_px"],
                    "exit_date": d, "exit_px": c,
                    "ret": (c / pos["entry_px"] - 1) * 100,
                    "opened_bb": pos["opened_bb"],
                    "forced": not exit_now,
                })
                pos = None
            continue
        # entry check
        if pma5 is None or pc is None:
            continue
        if slope > 0 and c > ma20 and pc <= pma5 and c > ma5:
            pos = {"entry_date": d, "entry_px": c, "opened_bb": bool(bpos and bpos > 100), "below": 0}
    return trades


def agg(trades):
    if not trades:
        return None
    wins = [t for t in trades if t["ret"] > 0]
    months = {t["entry_date"][:7] for t in trades}
    return {
        "n": len(trades),
        "wr": len(wins) / len(trades) * 100,
        "avg": sum(t["ret"] for t in trades) / len(trades),
        "total": sum(t["ret"] for t in trades),
        "months": len(months),
        "best": max(trades, key=lambda t: t["ret"]),
        "worst": min(trades, key=lambda t: t["ret"]),
    }


def run_universe(conn, tickers, label):
    all_trades = []
    per_ticker = {}
    for tk in sorted(tickers):
        bars = load_daily(conn, tk)
        if len(bars) < 25:
            continue
        ts = simulate(bars)
        for t in ts:
            t["ticker"] = tk
        all_trades.extend(ts)
        if ts:
            per_ticker[tk] = agg(ts)
    return all_trades, per_ticker


def main():
    conn = get_conn()

    user_tks = {r[0] for r in conn.execute(
        "SELECT DISTINCT ticker FROM broker_statement WHERE ticker IS NOT NULL AND ticker != ''")}

    picks = json.loads((_REPO / "docs" / "主力大課程" / "teacher_picks_2026.json").read_text())
    teacher_tks = {k for k in picks if k != "_meta" and k.isdigit()}
    for js in (_REPO / "docs" / "主力大課程").glob("teacher_sector*.json"):
        try:
            def walk(x):
                if isinstance(x, str) and x.isdigit() and len(x) >= 4:
                    teacher_tks.add(x)
                elif isinstance(x, dict):
                    for v in x.values(): walk(v)
                elif isinstance(x, list):
                    for v in x: walk(v)
            walk(json.loads(js.read_text()))
        except Exception:
            pass

    lines = ["# (e)(f) Frank 戰法 Daily 回測", f"Period: {START} ~ {END}",
             "Entry: 中軌分歧近似 (ma20上揚 + close>ma20 + 回 5MA 再上、收盤進)",
             "Exit: 開布林→守5日 / 未開→連2日破月線 or ma20下彎", ""]

    # user actual PnL for comparison
    actual_pnl = -8400

    for tickers, label in [(user_tks, "(e) 你交易過的 53 檔 — 嚴格照 Frank 模擬"),
                            (teacher_tks, "(f) 老師 universe 353 檔")]:
        trades, per_tk = run_universe(conn, tickers, label)
        a = agg(trades)
        lines.append(f"## {label}")
        lines.append("")
        if not a:
            lines.append("無交易")
            continue
        forced = sum(1 for t in trades if t["forced"])
        lines += [
            f"- Trades: {a['n']}（{len(per_tk)} 檔有訊號、{forced} 筆期末強制平倉）",
            f"- Win rate: {a['wr']:.1f}%",
            f"- 均報酬: {a['avg']:+.2f}% / 筆",
            f"- 跨月數: {a['months']}",
            f"- Best: {a['best']['ticker']} {a['best']['entry_date']} {a['best']['ret']:+.1f}%",
            f"- Worst: {a['worst']['ticker']} {a['worst']['entry_date']} {a['worst']['ret']:+.1f}%",
            "",
        ]
        # top tickers
        tops = sorted(per_tk.items(), key=lambda kv: -kv[1]["total"])[:10]
        lines += ["| Ticker | Trades | WR | 總報酬 |", "|---|---|---|---|"]
        for tk, s in tops:
            lines.append(f"| {tk} | {s['n']} | {s['wr']:.0f}% | {s['total']:+.1f}% |")
        lines.append("")

        if label.startswith("(e)"):
            lines += [f"**對照**：你實際同期 total P&L = ${actual_pnl:+,}（194 round-trips、WR 35.6%）", ""]

    out = _REPO / "docs" / "frank" / "backtest" / "ef_report.md"
    out.write_text("\n".join(lines))
    print(f"→ {out}")


if __name__ == "__main__":
    main()


def run_regime_validation():
    """跨年 regime 驗證: 同一套 entry/exit 跑 2023/2024/2025/2026."""
    global START, END
    conn = get_conn()
    picks = json.loads((_REPO / "docs" / "主力大課程" / "teacher_picks_2026.json").read_text())
    teacher_tks = {k for k in picks if k != "_meta" and k.isdigit()}
    for js in (_REPO / "docs" / "主力大課程").glob("teacher_sector*.json"):
        try:
            def walk(x):
                if isinstance(x, str) and x.isdigit() and len(x) >= 4:
                    teacher_tks.add(x)
                elif isinstance(x, dict):
                    for v in x.values(): walk(v)
                elif isinstance(x, list):
                    for v in x: walk(v)
            walk(json.loads(js.read_text()))
        except Exception:
            pass

    periods = [("2023-01-01", "2023-12-31", "2023 全年"),
               ("2024-01-01", "2024-12-31", "2024 全年"),
               ("2025-01-01", "2025-12-31", "2025 全年"),
               ("2026-01-01", "2026-07-03", "2026 YTD")]
    lines = ["# Frank 戰法跨年 regime 驗證", 
             "Universe: 老師 2026 名單 353 檔 (⚠️ survivorship bias: 名單是 2026 選的、歷史年份僅驗證機制不驗證選股)",
             "Entry/Exit: 同 ef_report", ""]
    lines += ["| 期間 | Trades | WR | 均報酬 | 中位數持有標的數 |", "|---|---|---|---|---|"]
    for s, e, label in periods:
        START, END = s, e
        trades, per_tk = run_universe(conn, teacher_tks, label)
        a = agg(trades)
        if not a:
            lines.append(f"| {label} | 0 | - | - | - |")
            continue
        lines.append(f"| {label} | {a['n']} | {a['wr']:.1f}% | {a['avg']:+.2f}% | {len(per_tk)} 檔 |")
        # quarterly breakdown
        from collections import Counter
        qs = defaultdict(list)
        for t in trades:
            m = int(t["entry_date"][5:7])
            q = f"Q{(m-1)//3+1}"
            qs[q].append(t["ret"])
        for q in sorted(qs):
            rets = qs[q]
            wr = sum(1 for r in rets if r > 0) / len(rets) * 100
            lines.append(f"| └ {label[:4]} {q} | {len(rets)} | {wr:.1f}% | {sum(rets)/len(rets):+.2f}% | |")

    out = _REPO / "docs" / "frank" / "backtest" / "regime_validation.md"
    out.write_text("\n".join(lines))
    print(f"→ {out}")


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "regime":
    run_regime_validation()
