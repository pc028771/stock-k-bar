#!/usr/bin/env python3
"""主力大 2026 選股 × Frank 進出場 portfolio 模擬

- Universe: teacher_picks + teacher_sector (353 檔)
- Entry: ma20 上揚 + close > ma20 + 回 5MA 再上 (前日 close<=ma5、今日 close>ma5)
  → 訊號日收盤進場 (Frank 尾盤 13:00-13:25 進場紀律)
- Exit: 開布林(bb>100) → 守5日 / 否則連2日破月線 or ma20下彎 → 收盤出
- Portfolio: 起始 300 萬、max 5 倉、每倉 = equity/5、同日訊號用當日漲幅排序
- 單位: 100 股 (高價股可買零股、memory 高價股零股)
- 費用: 0.4% round-trip
"""
from __future__ import annotations

import sys
import json
from pathlib import Path
from collections import defaultdict

_REPO = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO / "scripts"))
from zhuli.db import get_conn

START, END = "2026-01-01", "2026-07-03"
CAPITAL = 3_000_000
MAX_SLOTS = 5
FEE = 0.004  # round-trip
MAX_CHG = float(__import__("os").environ.get("MAX_CHG", "9.5"))


def load_universe():
    picks = json.loads((_REPO / "docs/主力大課程/teacher_picks_2026.json").read_text())
    tks = {k for k in picks if k != "_meta" and k.isdigit()}
    for js in (_REPO / "docs/主力大課程").glob("teacher_sector*.json"):
        try:
            def walk(x):
                if isinstance(x, str) and x.isdigit() and len(x) >= 4:
                    tks.add(x)
                elif isinstance(x, dict):
                    for v in x.values(): walk(v)
                elif isinstance(x, list):
                    for v in x: walk(v)
            walk(json.loads(js.read_text()))
        except Exception:
            pass
    return tks


def main():
    conn = get_conn()
    tks = load_universe()

    # Load all bars into memory: date -> ticker -> row
    q = f"""SELECT trade_date, ticker, close, ma5, ma20, ma20_slope, bb_position
            FROM standard_daily_bar
            WHERE trade_date BETWEEN ? AND ? AND close > 0
              AND ticker IN ({','.join('?'*len(tks))})
            ORDER BY trade_date"""
    by_date = defaultdict(dict)
    prev_row = {}  # ticker -> (close, ma5)
    for r in conn.execute(q, (START, END, *tks)):
        d, tk, c, ma5, ma20, slope, bpos = r
        by_date[d][tk] = {"c": c, "ma5": ma5, "ma20": ma20, "slope": slope, "bpos": bpos}

    dates = sorted(by_date)
    cash = CAPITAL
    positions = {}  # ticker -> dict(entry_date, entry_px, shares, opened_bb, below)
    closed = []
    equity_curve = []
    prev_day = {}  # ticker -> row (for entry check + 漲幅)

    for d in dates:
        rows = by_date[d]
        # 1) exits first (收盤出)
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
                closed.append({
                    "ticker": tk, "entry_date": p["entry_date"], "entry_px": p["entry_px"],
                    "exit_date": d, "exit_px": row["c"], "shares": p["shares"],
                    "pnl": proceeds - p["cost"],
                    "ret": (row["c"] * (1 - FEE) / p["entry_px"] - 1) * 100,
                })
                del positions[tk]

        # 2) entries (尾盤、slots 有空)
        if len(positions) < MAX_SLOTS:
            candidates = []
            for tk, row in rows.items():
                if tk in positions:
                    continue
                pv = prev_day.get(tk)
                if not pv or None in (row["c"], row["ma5"], row["ma20"], row["slope"]) \
                   or pv["c"] is None or pv["ma5"] is None:
                    continue
                if row["slope"] > 0 and row["c"] > row["ma20"] \
                   and pv["c"] <= pv["ma5"] and row["c"] > row["ma5"]:
                    chg = (row["c"] / pv["c"] - 1) * 100 if pv["c"] else 0
                    if chg >= MAX_CHG:  # 漲停買不進 / 不追紅
                        continue
                    candidates.append((chg, tk, row))
            candidates.sort(reverse=True)  # 漲幅最強優先 (Frank raw/05)
            # equity for sizing
            mtm = sum(rows.get(tk, {}).get("c", p["entry_px"]) * p["shares"]
                      for tk, p in positions.items())
            equity = cash + mtm
            for chg, tk, row in candidates:
                if len(positions) >= MAX_SLOTS:
                    break
                budget = min(equity / MAX_SLOTS, cash)
                shares = int(budget / row["c"] / 100) * 100
                if shares <= 0:
                    continue
                cost = row["c"] * shares
                if cost > cash:
                    continue
                cash -= cost
                positions[tk] = {"entry_date": d, "entry_px": row["c"], "shares": shares,
                                  "cost": cost, "opened_bb": bool(row["bpos"] and row["bpos"] > 100),
                                  "below": 0}

        # 3) mark to market
        mtm = sum(rows.get(tk, {}).get("c", p["entry_px"]) * p["shares"]
                  for tk, p in positions.items())
        equity_curve.append((d, cash + mtm, len(positions)))
        for tk, row in rows.items():
            prev_day[tk] = row

    # Final: force-close remaining at last price
    last_rows = by_date[dates[-1]]
    for tk, p in positions.items():
        px = last_rows.get(tk, {}).get("c", p["entry_px"])
        proceeds = px * p["shares"] * (1 - FEE)
        closed.append({"ticker": tk, "entry_date": p["entry_date"], "entry_px": p["entry_px"],
                        "exit_date": dates[-1] + "*", "exit_px": px, "shares": p["shares"],
                        "pnl": proceeds - p["cost"],
                        "ret": (px * (1 - FEE) / p["entry_px"] - 1) * 100})

    final_equity = equity_curve[-1][1]
    wins = [t for t in closed if t["pnl"] > 0]
    # max drawdown
    peak, mdd = 0, 0
    for _, eq, _ in equity_curve:
        peak = max(peak, eq)
        mdd = min(mdd, (eq - peak) / peak * 100)
    # monthly equity
    monthly = {}
    for d, eq, _ in equity_curve:
        monthly[d[:7]] = eq
    # robustness
    n_tickers = len({t["ticker"] for t in closed})
    n_months = len({t["entry_date"][:7] for t in closed})

    lines = [
        "# 主力大 2026 選股 × Frank 進出場 Portfolio 模擬",
        f"Period: {START} ~ {END} / 起始 ${CAPITAL:,} / Max {MAX_SLOTS} 倉 / 費用 0.4% RT",
        "",
        "## 總結",
        f"- 期末 equity: **${final_equity:,.0f}**（{(final_equity/CAPITAL-1)*100:+.1f}%）",
        f"- 已平倉: {len(closed)} 筆（含期末強平 {sum(1 for t in closed if t['exit_date'].endswith('*'))} 筆）",
        f"- Win rate: {len(wins)/len(closed)*100:.1f}%",
        f"- 均報酬/筆: {sum(t['ret'] for t in closed)/len(closed):+.2f}%",
        f"- Max drawdown: {mdd:.1f}%",
        f"- Robustness: 跨 {n_tickers} 檔 / 跨 {n_months} 個月（三軸: 股≥5 {'✅' if n_tickers>=5 else '❌'} / 月≥2 {'✅' if n_months>=2 else '❌'}）",
        "",
        "## 月末 equity",
        "",
        "| 月 | Equity | 累計報酬 |",
        "|---|---|---|",
    ]
    for m in sorted(monthly):
        lines.append(f"| {m} | ${monthly[m]:,.0f} | {(monthly[m]/CAPITAL-1)*100:+.1f}% |")

    lines += ["", "## Top 10 賺", "", "| Ticker | Entry | Exit | Ret | PnL |", "|---|---|---|---|---|"]
    for t in sorted(closed, key=lambda x: -x["pnl"])[:10]:
        lines.append(f"| {t['ticker']} | {t['entry_date']} @{t['entry_px']} | {t['exit_date']} @{t['exit_px']} | {t['ret']:+.1f}% | ${t['pnl']:+,.0f} |")
    lines += ["", "## Top 10 賠", "", "| Ticker | Entry | Exit | Ret | PnL |", "|---|---|---|---|---|"]
    for t in sorted(closed, key=lambda x: x["pnl"])[:10]:
        lines.append(f"| {t['ticker']} | {t['entry_date']} @{t['entry_px']} | {t['exit_date']} @{t['exit_px']} | {t['ret']:+.1f}% | ${t['pnl']:+,.0f} |")

    out = _REPO / "docs" / "frank" / "backtest" / f"portfolio_sim_2026_chg{int(MAX_CHG)}.md"
    out.write_text("\n".join(lines))
    print(f"→ {out}")
    print(f"Final: ${final_equity:,.0f} ({(final_equity/CAPITAL-1)*100:+.1f}%) | trades {len(closed)} | WR {len(wins)/len(closed)*100:.1f}% | MDD {mdd:.1f}%")


if __name__ == "__main__":
    main()
