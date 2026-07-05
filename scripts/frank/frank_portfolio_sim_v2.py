#!/usr/bin/env python3
"""主力大選股 × Frank 進出場 portfolio 模擬 v2（乾淨版）

改動 vs v1:
1. 無 look-ahead universe: 標的只在「老師首次點名日之後」才可進場
   - teacher_picks_2026.json 逐檔 mentions[0].date
   - teacher_sectors_20260602/03.json 內的 ticker → eligible 自 2026-06-02/03
2. 同日多訊號排序 = Frank 戰法分數（課程內條件、非自創）:
   +2 爆量城牆過高: close > 近20日最大量K的高點 (frank_wall_of_volume)
   +1 頭頭高: close > 昨日 high (raw/N1 表態確立方向)
   +1 壓布林頂: bb_position >= 80 (raw/W14 飆股基因)
   +1 出量表態: vol_ratio_20 >= 1.5 (raw/W02 大量突破表態)
   tie-break: 當日漲幅 desc
3. 保留: 漲幅 >= MAX_CHG (default 5、買綠不買紅) skip
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

START, END = "2026-01-01", "2026-07-03"
CAPITAL = 3_000_000
MAX_SLOTS = 5
FEE = 0.004
MAX_CHG = float(os.environ.get("MAX_CHG", "5"))


def load_eligibility():
    """ticker -> first eligible date."""
    elig = {}
    picks = json.loads((_REPO / "docs/主力大課程/teacher_picks_2026.json").read_text())
    for tk, v in picks.items():
        if tk == "_meta" or not tk.isdigit():
            continue
        dates = [m.get("date") for m in v.get("mentions", []) if m.get("date")]
        if dates:
            elig[tk] = min(dates)
    for js in (_REPO / "docs/主力大課程").glob("teacher_sectors_2026*.json"):
        # filename teacher_sectors_20260602.json → 2026-06-02
        stamp = js.stem.split("_")[-1]
        file_date = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"
        def walk(x):
            if isinstance(x, str) and x.isdigit() and len(x) >= 4:
                if x not in elig or file_date < elig[x]:
                    elig.setdefault(x, file_date)
            elif isinstance(x, dict):
                for v in x.values(): walk(v)
            elif isinstance(x, list):
                for v in x: walk(v)
        try:
            walk(json.loads(js.read_text()))
        except Exception:
            pass
    return elig


def main():
    conn = get_conn()
    elig = load_eligibility()
    tks = set(elig)
    print(f"Universe {len(tks)} 檔（含首次點名日）")

    q = f"""SELECT trade_date, ticker, close, high, volume, ma5, ma20, ma20_slope,
                   bb_position, vol_ratio_20
            FROM standard_daily_bar
            WHERE trade_date BETWEEN ? AND ? AND close > 0
              AND ticker IN ({','.join('?'*len(tks))})
            ORDER BY ticker, trade_date"""
    # per-ticker sequential: compute rolling 20d max-volume bar high (城牆)
    by_date = defaultdict(dict)
    cur_tk, hist = None, []
    for r in conn.execute(q, (START, END, *tks)):
        d, tk, c, hi, vol, ma5, ma20, slope, bpos, vr = r
        if tk != cur_tk:
            cur_tk, hist = tk, []
        # 城牆 = 近 20 根中最大量那根的 high（不含今日）
        wall_high = None
        if hist:
            w = max(hist[-20:], key=lambda x: x[2] or 0)
            wall_high = w[1]
        by_date[d][tk] = {"c": c, "hi": hi, "ma5": ma5, "ma20": ma20, "slope": slope,
                          "bpos": bpos, "vr": vr, "wall_high": wall_high}
        hist.append((d, hi, vol))

    dates = sorted(by_date)
    cash = CAPITAL
    positions, closed, equity_curve = {}, [], []
    prev_day = {}

    for d in dates:
        rows = by_date[d]
        # exits
        for tk in list(positions):
            row = rows.get(tk)
            if not row or None in (row["c"], row["ma5"], row["ma20"], row["slope"]):
                continue
            p = positions[tk]
            if row["bpos"] and row["bpos"] > 100:
                p["opened_bb"] = True
            exit_now = False
            if p["opened_bb"]:
                if row["c"] < row["ma5"]:
                    exit_now = True
            else:
                p["below"] = p["below"] + 1 if row["c"] < row["ma20"] else 0
                if p["below"] >= 2 or row["slope"] < 0:
                    exit_now = True
            if exit_now:
                proceeds = row["c"] * p["shares"] * (1 - FEE)
                cash += proceeds
                closed.append({"ticker": tk, "entry_date": p["entry_date"], "entry_px": p["entry_px"],
                                "exit_date": d, "exit_px": row["c"], "shares": p["shares"],
                                "pnl": proceeds - p["cost"], "score": p["score"],
                                "ret": (row["c"]*(1-FEE)/p["entry_px"]-1)*100})
                del positions[tk]

        # entries
        if len(positions) < MAX_SLOTS:
            candidates = []
            for tk, row in rows.items():
                if tk in positions or d < elig.get(tk, "9999"):
                    continue
                pv = prev_day.get(tk)
                if not pv or None in (row["c"], row["ma5"], row["ma20"], row["slope"]) \
                   or pv["c"] is None or pv["ma5"] is None:
                    continue
                if row["slope"] > 0 and row["c"] > row["ma20"] \
                   and pv["c"] <= pv["ma5"] and row["c"] > row["ma5"]:
                    chg = (row["c"]/pv["c"]-1)*100 if pv["c"] else 0
                    if chg >= MAX_CHG:
                        continue
                    # Frank 戰法分數
                    score = 0
                    if row["wall_high"] and row["c"] > row["wall_high"]:
                        score += 2   # 爆量城牆過高
                    if pv.get("hi") and row["c"] > pv["hi"]:
                        score += 1   # 頭頭高
                    if row["bpos"] and row["bpos"] >= 80:
                        score += 1   # 壓布林頂
                    if row["vr"] and row["vr"] >= 1.5:
                        score += 1   # 出量表態
                    candidates.append((score, chg, tk, row))
            candidates.sort(reverse=True)
            mtm = sum(rows.get(tk, {}).get("c", p["entry_px"]) * p["shares"]
                      for tk, p in positions.items())
            equity = cash + mtm
            for score, chg, tk, row in candidates:
                if len(positions) >= MAX_SLOTS:
                    break
                budget = min(equity / MAX_SLOTS, cash)
                shares = int(budget / row["c"] / 100) * 100
                if shares <= 0 or row["c"] * shares > cash:
                    continue
                cash -= row["c"] * shares
                positions[tk] = {"entry_date": d, "entry_px": row["c"], "shares": shares,
                                  "cost": row["c"]*shares, "score": score,
                                  "opened_bb": bool(row["bpos"] and row["bpos"] > 100), "below": 0}

        mtm = sum(rows.get(tk, {}).get("c", p["entry_px"]) * p["shares"]
                  for tk, p in positions.items())
        equity_curve.append((d, cash + mtm))
        for tk, row in rows.items():
            prev_day[tk] = row

    last_rows = by_date[dates[-1]]
    for tk, p in positions.items():
        px = last_rows.get(tk, {}).get("c", p["entry_px"])
        proceeds = px * p["shares"] * (1 - FEE)
        closed.append({"ticker": tk, "entry_date": p["entry_date"], "entry_px": p["entry_px"],
                        "exit_date": dates[-1]+"*", "exit_px": px, "shares": p["shares"],
                        "pnl": proceeds - p["cost"], "score": p["score"],
                        "ret": (px*(1-FEE)/p["entry_px"]-1)*100})

    final_eq = equity_curve[-1][1]
    wins = [t for t in closed if t["pnl"] > 0]
    peak, mdd = 0, 0
    for _, eq in equity_curve:
        peak = max(peak, eq); mdd = min(mdd, (eq-peak)/peak*100)
    monthly = {}
    for d, eq in equity_curve:
        monthly[d[:7]] = eq
    n_tk = len({t["ticker"] for t in closed})
    n_mo = len({t["entry_date"][:7] for t in closed})

    # score-level breakdown
    by_score = defaultdict(lambda: {"n": 0, "w": 0, "ret": 0, "pnl": 0})
    for t in closed:
        g = by_score[t["score"]]
        g["n"] += 1; g["w"] += t["pnl"] > 0; g["ret"] += t["ret"]; g["pnl"] += t["pnl"]

    lines = [
        "# 主力大選股 × Frank 進出場 v2（乾淨版：timeline 過濾 + 戰法分數排序）",
        f"Period {START}~{END} / ${CAPITAL:,} / {MAX_SLOTS} 倉 / 買綠<{MAX_CHG}% / 0.4% RT",
        f"Universe: {len(tks)} 檔、各自從老師首次點名日起 eligible",
        "",
        "## 總結",
        f"- 期末 equity: **${final_eq:,.0f}**（{(final_eq/CAPITAL-1)*100:+.1f}%）",
        f"- 已平倉 {len(closed)} 筆（強平 {sum(1 for t in closed if t['exit_date'].endswith('*'))}）",
        f"- WR {len(wins)/len(closed)*100:.1f}% / 均報酬 {sum(t['ret'] for t in closed)/len(closed):+.2f}%/筆",
        f"- MDD {mdd:.1f}%",
        f"- 跨 {n_tk} 檔 / {n_mo} 個月（三軸 {'✅' if n_tk>=5 and n_mo>=2 else '❌'}）",
        "",
        "## 戰法分數 × 績效",
        "", "| Score | N | WR | 均報酬 | PnL |", "|---|---|---|---|---|",
    ]
    for s in sorted(by_score, reverse=True):
        g = by_score[s]
        lines.append(f"| {s} | {g['n']} | {g['w']/g['n']*100:.0f}% | {g['ret']/g['n']:+.2f}% | ${g['pnl']:+,.0f} |")

    lines += ["", "## 月末 equity", "", "| 月 | Equity | 累計 |", "|---|---|---|"]
    for m in sorted(monthly):
        lines.append(f"| {m} | ${monthly[m]:,.0f} | {(monthly[m]/CAPITAL-1)*100:+.1f}% |")

    lines += ["", "## Top 10 賺 / 賠", "", "| Ticker | Entry | Exit | Ret | Score | PnL |", "|---|---|---|---|---|---|"]
    for t in sorted(closed, key=lambda x: -x["pnl"])[:10]:
        lines.append(f"| {t['ticker']} | {t['entry_date']} @{t['entry_px']} | {t['exit_date']} @{t['exit_px']} | {t['ret']:+.1f}% | {t['score']} | ${t['pnl']:+,.0f} |")
    lines.append("| — | — | — | — | — | — |")
    for t in sorted(closed, key=lambda x: x["pnl"])[:10]:
        lines.append(f"| {t['ticker']} | {t['entry_date']} @{t['entry_px']} | {t['exit_date']} @{t['exit_px']} | {t['ret']:+.1f}% | {t['score']} | ${t['pnl']:+,.0f} |")

    out = _REPO / "docs" / "frank" / "backtest" / "portfolio_sim_v2_clean.md"
    out.write_text("\n".join(lines))
    print(f"→ {out}")
    print(f"Final ${final_eq:,.0f} ({(final_eq/CAPITAL-1)*100:+.1f}%) | {len(closed)} trades | WR {len(wins)/len(closed)*100:.1f}% | MDD {mdd:.1f}%")


if __name__ == "__main__":
    main()
