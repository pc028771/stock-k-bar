#!/usr/bin/env python3
"""戰法二延伸（週K）與 戰法三（月K）portfolio 模擬、與 v2（日K戰法二）同條件比較

戰法二延伸 (raw/04):
  週K: 20週均上揚 + 週KD(9) K>=20 金叉 + 週MACD DIF>=0
  進場: 上述成立期間、日K 回5MA再上（尾盤收盤進）
  出場: 週KD 死叉 or 20週均下彎（中長波層）
戰法三 (raw/W08):
  月K: KD(9) 近月首次金叉 + DIF+MACD>0 + 柱狀體改善
  進場: 訊號月內、日K 回5MA再上
  出場: 月KD>70 / 月KD高檔死叉 / DIF+MACD<0
Portfolio: $3M / 5 倉 / 買綠<5% / 0.4% RT / universe = teacher timeline
"""
from __future__ import annotations

import sys
import os
import json
from pathlib import Path
from collections import defaultdict

_REPO = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO / "scripts"))
from zhuli.db import get_conn

START = os.environ.get("SIM_START", "2026-05-01")
END = os.environ.get("SIM_END", "2026-07-03")
WARMUP = "2024-01-01"   # 週/月指標需要長歷史
CAPITAL, MAX_SLOTS, FEE, MAX_CHG = 3_000_000, 5, 0.004, 5.0
MODE = os.environ.get("MODE", "weekly")   # weekly | monthly


def load_eligibility():
    elig = {}
    picks = json.loads((_REPO / "docs/主力大課程/teacher_picks_2026.json").read_text())
    for tk, v in picks.items():
        if tk == "_meta" or not tk.isdigit():
            continue
        ds = [m.get("date") for m in v.get("mentions", []) if m.get("date")]
        if ds:
            elig[tk] = min(ds)
    for js in (_REPO / "docs/主力大課程").glob("teacher_sectors_2026*.json"):
        st = js.stem.split("_")[-1]
        fd = f"{st[:4]}-{st[4:6]}-{st[6:8]}"
        def walk(x):
            if isinstance(x, str) and x.isdigit() and len(x) >= 4:
                elig.setdefault(x, fd)
            elif isinstance(x, dict):
                for v in x.values(): walk(v)
            elif isinstance(x, list):
                for v in x: walk(v)
        try:
            walk(json.loads(js.read_text()))
        except Exception:
            pass
    return elig


def kd(highs, lows, closes, n=9):
    ks, ds = [], []
    k = d = 50.0
    for i in range(len(closes)):
        lo = min(lows[max(0, i - n + 1): i + 1])
        hi = max(highs[max(0, i - n + 1): i + 1])
        rsv = (closes[i] - lo) / (hi - lo) * 100 if hi > lo else 50
        k = k * 2 / 3 + rsv / 3
        d = d * 2 / 3 + k / 3
        ks.append(k); ds.append(d)
    return ks, ds


def macd(closes, f=12, s=26, sig=9):
    def ema(v, n):
        k = 2 / (n + 1); out = [v[0]]
        for x in v[1:]:
            out.append(x * k + out[-1] * (1 - k))
        return out
    if len(closes) < s:
        return [0] * len(closes), [0] * len(closes)
    e12, e26 = ema(closes, f), ema(closes, s)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = ema(dif, sig)
    return dif, dea


def resample(bars, mode):
    """daily rows (d, o, h, l, c) → period bars keyed by ISO week or month."""
    out, key_of = [], (lambda d: d[:7]) if mode == "monthly" else \
        (lambda d: __import__("datetime").date(*map(int, d.split("-"))).isocalendar()[:2])
    cur = None
    for d, o, h, l, c in bars:
        k = key_of(d)
        if cur and cur["k"] == k:
            cur["h"] = max(cur["h"], h); cur["l"] = min(cur["l"], l)
            cur["c"] = c; cur["end"] = d
        else:
            if cur:
                out.append(cur)
            cur = {"k": k, "o": o, "h": h, "l": l, "c": c, "end": d}
    if cur:
        out.append(cur)
    return out


def build_gates(conn, tk, mode):
    """回傳 {daily_date: (entry_ok, exit_now)} 依週/月層訊號（只用已收完的 period、無 look-ahead）."""
    rows = conn.execute("""SELECT trade_date, open, high, low, close FROM standard_daily_bar
                           WHERE ticker=? AND trade_date BETWEEN ? AND ? AND close>0
                           ORDER BY trade_date""", (tk, WARMUP, END)).fetchall()
    if len(rows) < 120:
        return {}
    pb = resample(rows, mode)
    if len(pb) < 30:
        return {}
    cs = [b["c"] for b in pb]
    hs = [b["h"] for b in pb]
    ls = [b["l"] for b in pb]
    ks, ds = kd(hs, ls, cs)
    dif, dea = macd(cs)
    ma20 = [sum(cs[max(0, i - 19): i + 1]) / min(20, i + 1) for i in range(len(cs))]
    gates = {}
    # period i 收完後、狀態適用到 period i+1 的所有日
    for i in range(20, len(pb) - 1):
        if mode == "weekly":
            up20 = ma20[i] > ma20[i - 5]
            gold = ks[i] > ds[i] and ks[i] >= 20
            entry_ok = up20 and gold and dif[i] >= 0
            exit_now = (ks[i] < ds[i]) or (ma20[i] < ma20[i - 1])
        else:  # monthly 戰法三
            gold_now = ks[i] > ds[i]
            gold_prev = ks[i - 1] > ds[i - 1]
            fresh_gold = gold_now and not gold_prev
            hist = dif[i] - dea[i]
            hist_ok = hist > (dif[i - 1] - dea[i - 1])
            entry_ok = (fresh_gold or (gold_now and ks[i] < 70)) and (dif[i] + dea[i]) > 0 and hist_ok
            exit_now = (ks[i] > 70) or (ks[i] < ds[i] and ks[i - 1] > 70) or (dif[i] + dea[i]) < 0
        nxt_start = pb[i]["end"]
        nxt_end = pb[i + 1]["end"]
        for d, *_ in rows:
            if nxt_start < d <= nxt_end:
                gates[d] = (entry_ok, exit_now)
    return gates


def main():
    conn = get_conn()
    elig = load_eligibility()
    tks = set(elig)
    names = dict(conn.execute("SELECT ticker, name FROM stock_name"))

    q = f"""SELECT trade_date, ticker, close, ma5 FROM standard_daily_bar
            WHERE trade_date BETWEEN ? AND ? AND close>0
              AND ticker IN ({','.join('?' * len(tks))}) ORDER BY trade_date"""
    by_date = defaultdict(dict)
    for d, tk, c, ma5 in conn.execute(q, (START, END, *tks)):
        by_date[d][tk] = {"c": c, "ma5": ma5}

    print(f"[{MODE}] building gates for {len(tks)} tickers…")
    gates = {tk: build_gates(conn, tk, MODE) for tk in tks}

    dates = sorted(by_date)
    cash, positions, closed = CAPITAL, {}, []
    prev = {}
    eq_curve = []
    for d in dates:
        rows = by_date[d]
        # exits: 週/月層 exit 訊號日收盤出
        for tk in list(positions):
            g = gates.get(tk, {}).get(d)
            row = rows.get(tk)
            if not row or not g:
                continue
            if g[1]:
                p = positions.pop(tk)
                proceeds = row["c"] * p["sh"] * (1 - FEE)
                cash += proceeds
                closed.append((tk, p["ed"], p["px"], d, row["c"], p["sh"],
                               proceeds - p["cost"], (row["c"] * (1 - FEE) / p["px"] - 1) * 100))
        # entries
        if len(positions) < MAX_SLOTS:
            cands = []
            for tk, row in rows.items():
                if tk in positions or d < elig.get(tk, "9999"):
                    continue
                g = gates.get(tk, {}).get(d)
                pv = prev.get(tk)
                if not g or not g[0] or not pv or None in (row["c"], row["ma5"]) \
                   or pv["c"] is None or pv["ma5"] is None:
                    continue
                if pv["c"] <= pv["ma5"] and row["c"] > row["ma5"]:
                    chg = (row["c"] / pv["c"] - 1) * 100
                    if chg < MAX_CHG:
                        cands.append((chg, tk, row))
            cands.sort(reverse=True)
            mtm = sum(rows.get(t, {}).get("c", p["px"]) * p["sh"] for t, p in positions.items())
            equity = cash + mtm
            for chg, tk, row in cands:
                if len(positions) >= MAX_SLOTS:
                    break
                budget = min(equity / MAX_SLOTS, cash)
                sh = int(budget / row["c"] / 100) * 100
                if sh <= 0 or row["c"] * sh > cash:
                    continue
                cash -= row["c"] * sh
                positions[tk] = {"ed": d, "px": row["c"], "sh": sh, "cost": row["c"] * sh}
        mtm = sum(rows.get(t, {}).get("c", p["px"]) * p["sh"] for t, p in positions.items())
        eq_curve.append((d, cash + mtm))
        for tk, row in rows.items():
            prev[tk] = row

    for tk, p in positions.items():
        px = by_date[dates[-1]].get(tk, {}).get("c", p["px"])
        proceeds = px * p["sh"] * (1 - FEE)
        closed.append((tk, p["ed"], p["px"], dates[-1] + "*", px, p["sh"],
                       proceeds - p["cost"], (px * (1 - FEE) / p["px"] - 1) * 100))

    fin = eq_curve[-1][1]
    wins = sum(1 for t in closed if t[6] > 0)
    peak, mdd = 0, 0
    for _, e in eq_curve:
        peak = max(peak, e); mdd = min(mdd, (e - peak) / peak * 100)
    print(f"\n[{MODE}] {START}~{END}  Final ${fin:,.0f} ({(fin/CAPITAL-1)*100:+.1f}%) | "
          f"{len(closed)} trades | WR {wins/len(closed)*100:.1f}% | MDD {mdd:.1f}%" if closed
          else f"[{MODE}] no trades")
    print(f"| # | 標的 | 進場日 | 進價 | 出場日 | 出價 | 報酬 | PnL |")
    print("|---|---|---|---|---|---|---|---|")
    for i, t in enumerate(sorted(closed, key=lambda x: x[1]), 1):
        print(f"| {i} | {t[0]} {names.get(t[0],'')} | {t[1]} | {t[2]} | {t[3]} | {t[4]} | {t[7]:+.1f}% | ${t[6]:+,.0f} |")
    print(f"加總 PnL: ${sum(t[6] for t in closed):+,.0f}")


if __name__ == "__main__":
    main()
