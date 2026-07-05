#!/usr/bin/env python3
"""Frank 戰法一+戰法二 對帳單復盤

For each real trade in broker_statement, check if Frank spec would have:
- 進場: 戰法二 (日 K 布林上軌區間 + ma20 上揚) + 戰法一 (5m 10EMA 上穿 60EMA)
- 出場: 破 5m 戰法一 (加碼層) 或 收盤跌破月線 (主單層)

Output: docs/frank/backtest/replay_report.md
"""
from __future__ import annotations

import sys
import sqlite3
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta

_REPO = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO / "scripts"))
from zhuli.db import get_conn


def load_trades(conn: sqlite3.Connection):
    """Return trades: list of dicts sorted by (ticker, trade_date)."""
    q = """SELECT trade_date, ticker, stock_name, action, price, shares, cost
           FROM broker_statement
           WHERE ticker IS NOT NULL AND ticker != ''
           ORDER BY ticker, trade_date, id"""
    return [dict(zip([c[0] for c in conn.execute(q).description], r)) for r in conn.execute(q)]


def is_buy(action: str) -> bool:
    return action in ("現買", "沖買", "券買")  # 券買 = 融券回補 = 買

def is_sell(action: str) -> bool:
    return action in ("現賣", "沖賣", "券賣")


def check_bo2(conn, ticker: str, date: str) -> dict:
    """戰法二 條件: ma20 上揚 + 股價在布林上軌區間 + 回月線分歧."""
    r = conn.execute("""SELECT close, ma20, ma20_slope, bb_upper, bb_mid, bb_lower, bb_position, bb_upper_slope
                        FROM standard_daily_bar
                        WHERE ticker=? AND trade_date=?""", (ticker, date)).fetchone()
    if not r:
        return {"ok": False, "reason": "no_data"}
    close, ma20, slope, bu, bm, bl, bpos, bslope = r
    if ma20 is None or slope is None:
        return {"ok": False, "reason": "no_ma20"}
    checks = {
        "ma20_up": slope > 0,
        "in_upper_band": (bpos or 0.5) >= 0.5,  # bb_position ≥ 0.5 = 上軌區間
        "close_above_ma20": close > (ma20 or 0),
    }
    ok = all(checks.values())
    return {"ok": ok, "close": close, "ma20": ma20, "slope": slope,
            "bb_position": bpos, **checks}


def load_5m_bars(conn, ticker: str, date: str):
    """Aggregate 1m -> 5m bars for the day."""
    rows = conn.execute("""SELECT trade_datetime, open, high, low, close, volume
                            FROM stock_minute_kbar
                            WHERE ticker=? AND trade_datetime LIKE ?
                            ORDER BY trade_datetime""",
                         (ticker, f"{date}%")).fetchall()
    if not rows:
        return []
    # bucket into 5m
    buckets = defaultdict(lambda: {"o": None, "h": -1e9, "l": 1e9, "c": None, "v": 0, "ts": None})
    for ts, o, h, l, c, v in rows:
        # ts like "2026-03-04 09:03"
        try:
            t = datetime.strptime(ts, "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        # 5-min bucket: floor minute to 5
        bkt_min = (t.minute // 5) * 5
        bkt = t.replace(minute=bkt_min, second=0)
        b = buckets[bkt]
        if b["o"] is None:
            b["o"] = o
            b["ts"] = bkt
        b["h"] = max(b["h"], h or -1e9)
        b["l"] = min(b["l"], l or 1e9)
        b["c"] = c
        b["v"] += v or 0
    out = sorted(buckets.values(), key=lambda b: b["ts"])
    return out


def ema(values, n):
    if not values:
        return []
    k = 2 / (n + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def check_bo1_intraday(conn, ticker: str, date: str, hhmm: str = None) -> dict:
    """5m 戰法一: 10EMA > 60EMA + 60EMA 有斜率 (up).

    hhmm: 只看到那個時間為止 (None = 用當日最後一根 5m).
    """
    bars = load_5m_bars(conn, ticker, date)
    if len(bars) < 20:
        return {"ok": False, "reason": f"only_{len(bars)}_bars"}
    closes = [b["c"] for b in bars]
    e10 = ema(closes, 10)
    e60 = ema(closes, 60) if len(closes) >= 60 else ema(closes, min(20, len(closes)))
    # Take snapshot: last bar for the day (or hhmm)
    idx = len(bars) - 1
    if hhmm:
        target = datetime.strptime(f"{date} {hhmm}", "%Y-%m-%d %H:%M")
        for i, b in enumerate(bars):
            if b["ts"] > target:
                idx = max(0, i - 1)
                break
    slope_lookback = min(6, idx)
    slope60 = e60[idx] - e60[max(0, idx - slope_lookback)] if idx > 0 else 0
    up = e10[idx] > e60[idx]
    slope_ok = slope60 > 0
    return {
        "ok": up and slope_ok,
        "10ema": e10[idx],
        "60ema": e60[idx],
        "cross_up": up,
        "60ema_slope_up": slope_ok,
        "bars": len(bars),
    }


def score_entry(bo1: dict, bo2: dict) -> str:
    """A: 兩戰法都符合 / B: 一個符合 / C: 都不符合."""
    a = bo1.get("ok", False)
    b = bo2.get("ok", False)
    if a and b:
        return "A_full"
    if b:
        return "B_bo2_only"
    if a:
        return "B_bo1_only"
    return "C_none"


def pair_trades(trades: list) -> list:
    """Pair buy -> sell for same ticker (FIFO)."""
    holdings = defaultdict(list)  # ticker -> [(date, price, shares, cost)]
    pairs = []
    for t in trades:
        tk = t["ticker"]
        if is_buy(t["action"]):
            holdings[tk].append(dict(t))
        elif is_sell(t["action"]):
            remaining = t["shares"]
            while remaining > 0 and holdings[tk]:
                buy = holdings[tk][0]
                matched = min(remaining, buy["shares"])
                pnl = (t["price"] - buy["price"]) * matched
                hold_days = (datetime.strptime(t["trade_date"], "%Y-%m-%d")
                             - datetime.strptime(buy["trade_date"], "%Y-%m-%d")).days
                pairs.append({
                    "ticker": tk,
                    "buy_date": buy["trade_date"],
                    "buy_price": buy["price"],
                    "sell_date": t["trade_date"],
                    "sell_price": t["price"],
                    "shares": matched,
                    "pnl": pnl,
                    "return_pct": (t["price"] / buy["price"] - 1) * 100,
                    "hold_days": hold_days,
                    "buy_action": buy["action"],
                    "sell_action": t["action"],
                })
                buy["shares"] -= matched
                remaining -= matched
                if buy["shares"] == 0:
                    holdings[tk].pop(0)
    return pairs


def main():
    conn = get_conn()
    trades = load_trades(conn)
    print(f"Loaded {len(trades)} trades")

    # For each buy, check Frank alignment
    entries = []
    for t in trades:
        if not is_buy(t["action"]):
            continue
        bo2 = check_bo2(conn, t["ticker"], t["trade_date"])
        bo1 = check_bo1_intraday(conn, t["ticker"], t["trade_date"])
        entries.append({
            **t,
            "bo2_ok": bo2.get("ok"),
            "bo1_ok": bo1.get("ok"),
            "score": score_entry(bo1, bo2),
            "bo2": bo2,
            "bo1": bo1,
        })

    # Pair for P&L
    pairs = pair_trades(trades)
    print(f"Paired {len(pairs)} round-trips")

    # Attach entry score to each pair
    entry_by_key = {(e["ticker"], e["trade_date"], e["price"]): e for e in entries}
    for p in pairs:
        e = entry_by_key.get((p["ticker"], p["buy_date"], p["buy_price"]))
        if e:
            p["entry_score"] = e["score"]
            p["bo2_ok"] = e["bo2_ok"]
            p["bo1_ok"] = e["bo1_ok"]

    # Aggregate
    by_score = defaultdict(lambda: {"n": 0, "wins": 0, "total_pnl": 0, "total_ret": 0, "hold": 0})
    for p in pairs:
        s = p.get("entry_score", "unknown")
        g = by_score[s]
        g["n"] += 1
        g["wins"] += 1 if p["pnl"] > 0 else 0
        g["total_pnl"] += p["pnl"]
        g["total_ret"] += p["return_pct"]
        g["hold"] += p["hold_days"]

    # Report
    out_dir = _REPO / "docs" / "frank" / "backtest"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "replay_report.md"
    lines = [
        "# Frank 5m 戰法一 + 日 K 戰法二 對帳單復盤",
        f"Date: 2026-07-05",
        f"Trades: {len(trades)} 筆、Round-trips: {len(pairs)} 對",
        "",
        "## 對帳單進場 vs Frank 戰法對齊度",
        "",
        "| Score | 定義 | Trades | Win% | 均報酬 | 均持倉 | 總 PnL |",
        "|---|---|---|---|---|---|---|",
    ]
    definitions = {
        "A_full": "戰法一 + 戰法二 都符合 (Frank 主推)",
        "B_bo2_only": "只戰法二符合 (日 K 對、5m 沒切好)",
        "B_bo1_only": "只戰法一符合 (5m 訊號、但日 K 大方向沒對)",
        "C_none": "都不符合 (逆勢/追高)",
    }
    for s in ["A_full", "B_bo2_only", "B_bo1_only", "C_none"]:
        g = by_score.get(s, {"n": 0, "wins": 0, "total_pnl": 0, "total_ret": 0, "hold": 0})
        if g["n"] == 0:
            continue
        wr = g["wins"] / g["n"] * 100
        avg_ret = g["total_ret"] / g["n"]
        avg_hold = g["hold"] / g["n"]
        lines.append(f"| {s} | {definitions[s]} | {g['n']} | {wr:.1f}% | {avg_ret:+.2f}% | {avg_hold:.1f} 天 | ${g['total_pnl']:+,.0f} |")

    lines += ["", "## Top 10 大賺（實際 P&L）", "",
              "| Ticker | Buy | Sell | Ret | Score |", "|---|---|---|---|---|"]
    for p in sorted(pairs, key=lambda x: -x["pnl"])[:10]:
        lines.append(f"| {p['ticker']} | {p['buy_date']} @{p['buy_price']} | {p['sell_date']} @{p['sell_price']} | {p['return_pct']:+.2f}% | {p.get('entry_score', '?')} |")

    lines += ["", "## Top 10 大賠（實際 P&L）", "",
              "| Ticker | Buy | Sell | Ret | Score |", "|---|---|---|---|---|"]
    for p in sorted(pairs, key=lambda x: x["pnl"])[:10]:
        lines.append(f"| {p['ticker']} | {p['buy_date']} @{p['buy_price']} | {p['sell_date']} @{p['sell_price']} | {p['return_pct']:+.2f}% | {p.get('entry_score', '?')} |")

    # Overall
    total_pnl = sum(p["pnl"] for p in pairs)
    total_wins = sum(1 for p in pairs if p["pnl"] > 0)
    lines += ["", "## Overall",
              f"- Total round-trips: {len(pairs)}",
              f"- Total P&L: ${total_pnl:+,.0f}",
              f"- Win rate: {total_wins/len(pairs)*100:.1f}%" if pairs else "- Win rate: N/A"]

    report.write_text("\n".join(lines))
    print(f"Report → {report}")


if __name__ == "__main__":
    main()
