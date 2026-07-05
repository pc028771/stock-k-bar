#!/usr/bin/env python3
"""Frank 對帳單復盤 v2

新增：
  (a) 用 buy_price ≈ 當日 5m close 反推時間點、用當時 5m 判定戰法一
  (b) 出場合規性: 對每筆 sell 檢查 Frank 出場訊號 (該出未出 / 不該出卻出)
  (c) 老師標的 vs 非老師標的分層

Output: docs/frank/backtest/replay_v2_report.md
"""
from __future__ import annotations

import sys
import json
import sqlite3
from pathlib import Path
from collections import defaultdict
from datetime import datetime

_REPO = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO / "scripts"))
from zhuli.db import get_conn


def load_teacher_tickers() -> set:
    """所有老師 picks + sector universe."""
    tks = set()
    picks = _REPO / "docs" / "主力大課程" / "teacher_picks_2026.json"
    if picks.exists():
        d = json.loads(picks.read_text())
        tks.update(k for k in d if k != "_meta" and k.isdigit())
    sector = _REPO / "docs" / "主力大課程"
    for js in sector.glob("teacher_sector*.json"):
        try:
            d = json.loads(js.read_text())
            def walk(x):
                if isinstance(x, str) and x.isdigit() and len(x) >= 4:
                    tks.add(x)
                elif isinstance(x, dict):
                    for v in x.values(): walk(v)
                elif isinstance(x, list):
                    for v in x: walk(v)
            walk(d)
        except Exception:
            pass
    return tks


def load_trades(conn):
    q = """SELECT id, trade_date, ticker, stock_name, action, price, shares
           FROM broker_statement WHERE ticker IS NOT NULL AND ticker != ''
           ORDER BY ticker, trade_date, id"""
    cols = [c[0] for c in conn.execute(q).description]
    return [dict(zip(cols, r)) for r in conn.execute(q)]


def is_buy(a): return a in ("現買", "沖買", "券買")
def is_sell(a): return a in ("現賣", "沖賣", "券賣")


def check_bo2(conn, ticker, date):
    r = conn.execute("""SELECT close, ma20, ma20_slope, bb_position
                        FROM standard_daily_bar
                        WHERE ticker=? AND trade_date=?""", (ticker, date)).fetchone()
    if not r or r[1] is None or r[2] is None:
        return {"ok": False}
    close, ma20, slope, bpos = r
    return {
        "ok": slope > 0 and (bpos or 0.5) >= 0.5 and close > ma20,
        "ma20_up": slope > 0,
        "in_upper": (bpos or 0.5) >= 0.5,
        "close_gt_ma20": close > ma20,
        "close": close, "ma20": ma20, "bb_pos": bpos,
    }


def load_5m(conn, ticker, date):
    rows = conn.execute("""SELECT trade_datetime, open, high, low, close, volume
                            FROM stock_minute_kbar
                            WHERE ticker=? AND trade_datetime LIKE ?
                            ORDER BY trade_datetime""",
                         (ticker, f"{date}%")).fetchall()
    if not rows: return []
    buckets = defaultdict(lambda: {"o": None, "h": -1e9, "l": 1e9, "c": None, "v": 0, "ts": None})
    for ts, o, h, l, c, v in rows:
        try:
            t = datetime.strptime(ts, "%Y-%m-%d %H:%M")
        except ValueError: continue
        bkt = t.replace(minute=(t.minute // 5) * 5, second=0)
        b = buckets[bkt]
        if b["o"] is None: b["o"] = o; b["ts"] = bkt
        b["h"] = max(b["h"], h or -1e9)
        b["l"] = min(b["l"], l or 1e9)
        b["c"] = c; b["v"] += v or 0
    return sorted(buckets.values(), key=lambda b: b["ts"])


def ema(vals, n):
    if not vals: return []
    k = 2 / (n + 1)
    out = [vals[0]]
    for v in vals[1:]: out.append(v * k + out[-1] * (1 - k))
    return out


def find_5m_idx_by_price(bars, price):
    """(a) 反推時間: 找 low<=price<=high 的第一根 bar (fill 假設)."""
    if not bars: return None
    for i, b in enumerate(bars):
        if b["l"] <= price <= b["h"]: return i
    # fallback: 找 close 最接近的
    return min(range(len(bars)), key=lambda i: abs(bars[i]["c"] - price))


def check_bo1_at_bar(bars, idx):
    """5m 戰法一 在第 idx 根 bar 的狀態."""
    if idx is None or idx < 10 or not bars:
        return {"ok": False, "reason": "not_enough_bars"}
    closes = [b["c"] for b in bars]
    e10 = ema(closes, 10)
    e60 = ema(closes, 60)
    slope_lookback = min(6, idx)
    slope60 = e60[idx] - e60[max(0, idx - slope_lookback)]
    up = e10[idx] > e60[idx]
    return {
        "ok": up and slope60 > 0,
        "10ema": e10[idx],
        "60ema": e60[idx],
        "cross_up": up,
        "slope_up": slope60 > 0,
    }


def score(bo1, bo2):
    a, b = bo1.get("ok"), bo2.get("ok")
    if a and b: return "A_full"
    if b: return "B_bo2_only"
    if a: return "B_bo1_only"
    return "C_none"


def frank_should_exit(conn, ticker, sell_date, buy_price):
    """(b) Frank 出場檢查 — 在 sell_date 該不該出?

    出場條件（任一）:
      1. 收盤跌破月線 (連 2 日) - 破戰法二
      2. 5m 10EMA 下穿 60EMA - 破戰法一 (加碼層)
      3. ma20_slope 下彎 - 絕對出

    Return: (should_exit: bool, reasons: list)
    """
    r = conn.execute("""SELECT close, ma20, ma20_slope
                        FROM standard_daily_bar
                        WHERE ticker=? AND trade_date <= ?
                        ORDER BY trade_date DESC LIMIT 2""", (ticker, sell_date)).fetchall()
    reasons = []
    if len(r) >= 2:
        if r[0][0] < r[0][1] and r[1][0] < r[1][1]:
            reasons.append("連2日收盤跌破月線")
        if r[0][2] is not None and r[0][2] < 0:
            reasons.append("ma20 下彎")
    # 5m 戰法一 (day-close snapshot)
    bars = load_5m(conn, ticker, sell_date)
    if len(bars) >= 60:
        b1 = check_bo1_at_bar(bars, len(bars) - 1)
        if not b1.get("ok"):
            reasons.append("破 5m 戰法一")
    return (len(reasons) > 0, reasons)


def pair_trades(trades):
    holdings = defaultdict(list)
    pairs = []
    for t in trades:
        tk = t["ticker"]
        if is_buy(t["action"]):
            holdings[tk].append(dict(t))
        elif is_sell(t["action"]):
            rem = t["shares"]
            while rem > 0 and holdings[tk]:
                buy = holdings[tk][0]
                m = min(rem, buy["shares"])
                pnl = (t["price"] - buy["price"]) * m
                hold = (datetime.strptime(t["trade_date"], "%Y-%m-%d")
                        - datetime.strptime(buy["trade_date"], "%Y-%m-%d")).days
                pairs.append({
                    "ticker": tk, "buy_date": buy["trade_date"], "buy_price": buy["price"],
                    "sell_date": t["trade_date"], "sell_price": t["price"], "shares": m,
                    "pnl": pnl, "return_pct": (t["price"]/buy["price"]-1)*100,
                    "hold_days": hold, "buy_action": buy["action"], "sell_action": t["action"],
                })
                buy["shares"] -= m; rem -= m
                if buy["shares"] == 0: holdings[tk].pop(0)
    return pairs


def main():
    conn = get_conn()
    teacher_tks = load_teacher_tickers()
    print(f"Teacher universe: {len(teacher_tks)} tickers")

    trades = load_trades(conn)
    pairs = pair_trades(trades)
    print(f"{len(trades)} trades → {len(pairs)} round-trips")

    for p in pairs:
        # (a) time-aware bo1
        bars = load_5m(conn, p["ticker"], p["buy_date"])
        idx = find_5m_idx_by_price(bars, p["buy_price"])
        p["buy_5m_idx"] = idx
        p["buy_time"] = bars[idx]["ts"].strftime("%H:%M") if idx is not None and bars else "N/A"
        bo1 = check_bo1_at_bar(bars, idx)
        bo2 = check_bo2(conn, p["ticker"], p["buy_date"])
        p["entry_score"] = score(bo1, bo2)
        p["is_teacher"] = p["ticker"] in teacher_tks
        # (b) exit check
        should_exit, reasons = frank_should_exit(conn, p["ticker"], p["sell_date"], p["buy_price"])
        p["exit_frank_says"] = "EXIT" if should_exit else "HOLD"
        p["exit_reasons"] = "; ".join(reasons) if reasons else "無 exit 訊號"
        # verdict
        if should_exit and p["return_pct"] < 0:
            p["exit_verdict"] = "OK_出對了_止損"
        elif should_exit and p["return_pct"] > 0:
            p["exit_verdict"] = "OK_出對了_止盈"
        elif not should_exit and p["return_pct"] > 5:
            p["exit_verdict"] = "早賣_應續抱"  # Frank 說可以續抱、user 已賺 5%+ 就出
        elif not should_exit and p["return_pct"] < 0:
            p["exit_verdict"] = "殺低_該續抱"
        else:
            p["exit_verdict"] = "普通"

    # Aggregate by (score, is_teacher)
    lines = ["# Frank 對帳單復盤 v2",
             f"Trades {len(trades)} / Round-trips {len(pairs)}",
             "",
             "## (a)(c) 進場對齊 × 老師標的 分層",
             "",
             "| Score | 老師標的 | N | Win% | 均報酬 | 均持倉 | PnL |",
             "|---|---|---|---|---|---|---|"]
    stats = defaultdict(lambda: {"n": 0, "w": 0, "pnl": 0, "ret": 0, "hold": 0})
    for p in pairs:
        k = (p["entry_score"], "老師" if p["is_teacher"] else "非老師")
        s = stats[k]
        s["n"] += 1; s["w"] += 1 if p["pnl"] > 0 else 0
        s["pnl"] += p["pnl"]; s["ret"] += p["return_pct"]; s["hold"] += p["hold_days"]
    for k in sorted(stats):
        s = stats[k]
        wr = s["w"]/s["n"]*100
        lines.append(f"| {k[0]} | {k[1]} | {s['n']} | {wr:.1f}% | {s['ret']/s['n']:+.2f}% | {s['hold']/s['n']:.1f} 天 | ${s['pnl']:+,.0f} |")

    # (b) 出場合規性
    lines += ["", "## (b) 出場合規性", "",
              "| Verdict | N | Win% | 均報酬 | PnL |", "|---|---|---|---|---|"]
    ev = defaultdict(lambda: {"n": 0, "w": 0, "pnl": 0, "ret": 0})
    for p in pairs:
        v = ev[p["exit_verdict"]]
        v["n"] += 1; v["w"] += 1 if p["pnl"] > 0 else 0
        v["pnl"] += p["pnl"]; v["ret"] += p["return_pct"]
    for k in sorted(ev, key=lambda x: -ev[x]["pnl"]):
        s = ev[k]
        lines.append(f"| {k} | {s['n']} | {s['w']/s['n']*100:.1f}% | {s['ret']/s['n']:+.2f}% | ${s['pnl']:+,.0f} |")

    # 老師標的 vs 非老師標的 aggregate
    lines += ["", "## (c) 老師標的 vs 非老師標的 aggregate", "",
              "| Universe | N | Win% | 均報酬 | PnL |", "|---|---|---|---|---|"]
    for is_t in [True, False]:
        subset = [p for p in pairs if p["is_teacher"] == is_t]
        if not subset: continue
        w = sum(1 for p in subset if p["pnl"] > 0)
        pnl = sum(p["pnl"] for p in subset)
        ret = sum(p["return_pct"] for p in subset) / len(subset)
        lines.append(f"| {'老師標的' if is_t else '非老師'} | {len(subset)} | {w/len(subset)*100:.1f}% | {ret:+.2f}% | ${pnl:+,.0f} |")

    # 早賣清單 (最痛)
    early_sells = sorted([p for p in pairs if p["exit_verdict"] == "早賣_應續抱"],
                          key=lambda x: -x["return_pct"])[:10]
    if early_sells:
        lines += ["", "## 早賣 Top 10（Frank 認為該續抱、user 已提前賣）", "",
                  "| Ticker | Buy | Sell | Ret | Score | 老師 |", "|---|---|---|---|---|---|"]
        for p in early_sells:
            lines.append(f"| {p['ticker']} | {p['buy_date']} @{p['buy_price']} | {p['sell_date']} @{p['sell_price']} | {p['return_pct']:+.2f}% | {p['entry_score']} | {'Y' if p['is_teacher'] else 'N'} |")

    # 該砍未砍 (Frank 說 EXIT、user hold 到虧)
    should_have_exited = sorted([p for p in pairs
                                  if p["exit_verdict"] == "殺低_該續抱" or
                                     (p["return_pct"] < -5 and p["exit_frank_says"] == "EXIT")],
                                 key=lambda x: x["return_pct"])[:10]
    if should_have_exited:
        lines += ["", "## 該砍未砍 / 殺低錯砍 Top 10", "",
                  "| Ticker | Buy | Sell | Ret | Verdict | Reasons |", "|---|---|---|---|---|---|"]
        for p in should_have_exited:
            lines.append(f"| {p['ticker']} | {p['buy_date']} @{p['buy_price']} | {p['sell_date']} @{p['sell_price']} | {p['return_pct']:+.2f}% | {p['exit_verdict']} | {p['exit_reasons']} |")

    total = sum(p["pnl"] for p in pairs)
    lines += ["", "## Overall",
              f"- Total P&L: ${total:+,.0f}",
              f"- Win rate: {sum(1 for p in pairs if p['pnl'] > 0)/len(pairs)*100:.1f}%"]

    out = _REPO / "docs" / "frank" / "backtest" / "replay_v2_report.md"
    out.write_text("\n".join(lines))
    print(f"Report → {out}")


if __name__ == "__main__":
    main()
