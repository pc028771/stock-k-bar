#!/usr/bin/env python3
"""Regime gate 驗證: 加權 20MA 上揚才開新單 (Frank raw/W22 加權戰法二)."""
import sys, json, sqlite3
from pathlib import Path
from collections import defaultdict

_REPO = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO / "scripts"))
from zhuli.db import get_conn
import frank.frank_daily_backtest as bt

# TAIEX ma20 slope per date
tc = sqlite3.connect(_REPO / "data/analysis/kline_patterns/taiex_history.sqlite")
rows = tc.execute("SELECT trade_date, close FROM taiex_daily ORDER BY trade_date").fetchall()
closes = [r[1] for r in rows]
gate = {}
for i, (d, c) in enumerate(rows):
    if i < 25: continue
    ma20 = sum(closes[i-19:i+1]) / 20
    ma20_prev = sum(closes[i-24:i-4]) / 20  # 5 days ago
    gate[d] = ma20 > ma20_prev  # 20MA 上揚

def simulate_gated(bars):
    trades = []
    pos = None
    for i in range(1, len(bars)):
        d, c, ma5, ma20, slope, bpos = bars[i]
        _, pc, pma5, *_ = bars[i-1]
        if None in (c, ma5, ma20, slope): continue
        if pos:
            if bpos and bpos > 100: pos["opened_bb"] = True
            exit_now = False
            if pos["opened_bb"]:
                if c < ma5: exit_now = True
            else:
                pos["below"] = pos["below"] + 1 if c < ma20 else 0
                if pos["below"] >= 2 or slope < 0: exit_now = True
            if exit_now or i == len(bars) - 1:
                trades.append({"entry_date": pos["entry_date"], "ret": (c/pos["entry_px"]-1)*100,
                               "forced": not exit_now})
                pos = None
            continue
        if pma5 is None or pc is None: continue
        # GATE: 加權 20MA 上揚才開新單
        if not gate.get(d, False): continue
        if slope > 0 and c > ma20 and pc <= pma5 and c > ma5:
            pos = {"entry_date": d, "entry_px": c, "opened_bb": bool(bpos and bpos > 100), "below": 0}
    return trades

conn = get_conn()
picks = json.loads((_REPO / "docs/主力大課程/teacher_picks_2026.json").read_text())
tks = {k for k in picks if k != "_meta" and k.isdigit()}
for js in (_REPO / "docs/主力大課程").glob("teacher_sector*.json"):
    try:
        def walk(x):
            if isinstance(x, str) and x.isdigit() and len(x) >= 4: tks.add(x)
            elif isinstance(x, dict):
                for v in x.values(): walk(v)
            elif isinstance(x, list):
                for v in x: walk(v)
        walk(json.loads(js.read_text()))
    except Exception: pass

periods = [("2023-01-01","2023-12-31","2023"), ("2024-01-01","2024-12-31","2024"),
           ("2025-01-01","2025-12-31","2025"), ("2026-01-01","2026-06-03","2026 YTD*")]
print("| 期間 | 無gate WR/均報酬 | 有gate Trades | 有gate WR | 有gate 均報酬 |")
print("|---|---|---|---|---|")
nogate = {"2023": "43.8% / +1.05%", "2024": "39.8% / +1.20%", "2025": "40.4% / +1.67%", "2026 YTD*": "49.2% / +6.57%"}
results = []
for s, e, label in periods:
    bt.START, bt.END = s, e
    all_t = []
    for tk in tks:
        bars = bt.load_daily(conn, tk)
        if len(bars) < 25: continue
        all_t.extend(simulate_gated(bars))
    if not all_t:
        print(f"| {label} | {nogate[label]} | 0 | - | - |"); continue
    wr = sum(1 for t in all_t if t["ret"] > 0) / len(all_t) * 100
    avg = sum(t["ret"] for t in all_t) / len(all_t)
    print(f"| {label} | {nogate[label]} | {len(all_t)} | {wr:.1f}% | {avg:+.2f}% |")
    results.append((label, len(all_t), wr, avg))
print()
print("*2026 gate 資料只到 6/3 (taiex_history 最後日)")
