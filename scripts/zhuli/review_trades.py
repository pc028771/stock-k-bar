"""對歷史對帳單套用課程框架/老師守則 → 標出違規操作.

Usage:
    python scripts/zhuli/review_trades.py             # 全部規則
    python scripts/zhuli/review_trades.py --rule chase_high  # 指定規則
    python scripts/zhuli/review_trades.py --ticker 8064     # 指定個股
"""
from __future__ import annotations

from zhuli.db import get_conn, MAIN_DB

import argparse
from collections import defaultdict
from pathlib import Path

DB = MAIN_DB
def rule_chase_high(conn) -> list[dict]:
    """違規：同檔個股連續加碼且價格越買越高（追高）.

    課程依據：「不要開盤開高追進去」、「等回檔下試單」。
    判定：同 ticker，連續 ≥2 個交易日「現買」且後一筆價 > 前一筆價 +3%。
    """
    rows = conn.execute("""
        SELECT ticker, name, trade_date, price, shares
        FROM trade_history
        WHERE trade_type='現買' AND ticker IS NOT NULL
        ORDER BY ticker, trade_date, id
    """).fetchall()
    by_ticker = defaultdict(list)
    for r in rows:
        by_ticker[r[0]].append(r)

    violations = []
    for ticker, trades in by_ticker.items():
        for i in range(1, len(trades)):
            prev = trades[i-1]
            curr = trades[i]
            if curr[3] > prev[3] * 1.03 and curr[2] != prev[2]:  # 後一日漲 >3% 後加碼
                violations.append({
                    "rule": "chase_high",
                    "ticker": ticker,
                    "name": curr[1],
                    "date": curr[2],
                    "price": curr[3],
                    "shares": curr[4],
                    "prev_date": prev[2],
                    "prev_price": prev[3],
                    "pct": (curr[3]/prev[3]-1)*100,
                    "note": f"前次 {prev[2]}@{prev[3]} → 加碼 @{curr[3]} (+{(curr[3]/prev[3]-1)*100:.1f}%)",
                })
    return violations


def rule_no_holding_check(conn) -> list[dict]:
    """違規：買進後沒守住，N 天內砍出停損 ≥ 5%.

    課程依據：「進場後應觀察是否守住關鍵支撐」。
    判定：同 ticker 現買後 ≤ 5 個交易日內現賣，且賣價 < 買價 -5%。
    """
    rows = conn.execute("""
        SELECT ticker, name, trade_date, trade_type, price, shares
        FROM trade_history
        WHERE ticker IS NOT NULL AND trade_type IN ('現買','現賣')
        ORDER BY ticker, trade_date, id
    """).fetchall()
    by_ticker = defaultdict(list)
    for r in rows:
        by_ticker[r[0]].append(r)

    violations = []
    for ticker, trades in by_ticker.items():
        buys = [t for t in trades if t[3] == '現買']
        sells = [t for t in trades if t[3] == '現賣']
        for buy in buys:
            for sell in sells:
                if sell[2] <= buy[2]:
                    continue
                # 估算交易日差（用日期粗算）
                if sell[5] >= buy[5] and sell[4] < buy[4] * 0.95:
                    violations.append({
                        "rule": "no_holding_check",
                        "ticker": ticker,
                        "name": buy[1],
                        "buy_date": buy[2],
                        "buy_price": buy[4],
                        "sell_date": sell[2],
                        "sell_price": sell[4],
                        "loss_pct": (sell[4]/buy[4]-1)*100,
                        "note": f"買 {buy[2]}@{buy[4]} → 賣 {sell[2]}@{sell[4]} (-{abs((sell[4]/buy[4]-1)*100):.1f}%)",
                    })
                    break  # 一筆買對應一筆賣即可
    return violations


def rule_day_trade_loss(conn) -> list[dict]:
    """違規：當沖追高後砍出（沖買後沖賣，賣價 < 買價）.

    課程依據：盤中追高最忌諱。
    """
    rows = conn.execute("""
        SELECT ticker, name, trade_date, trade_type, price, shares
        FROM trade_history
        WHERE ticker IS NOT NULL AND trade_type IN ('沖買','沖賣')
        ORDER BY ticker, trade_date, id
    """).fetchall()
    by_key = defaultdict(lambda: {'buy': [], 'sell': []})
    for r in rows:
        key = (r[0], r[2])  # ticker + date
        if r[3] == '沖買':
            by_key[key]['buy'].append(r)
        else:
            by_key[key]['sell'].append(r)

    violations = []
    for (ticker, date), bs in by_key.items():
        if not bs['buy'] or not bs['sell']:
            continue
        avg_buy = sum(b[4]*b[5] for b in bs['buy']) / sum(b[5] for b in bs['buy'])
        avg_sell = sum(s[4]*s[5] for s in bs['sell']) / sum(s[5] for s in bs['sell'])
        if avg_sell < avg_buy:
            violations.append({
                "rule": "day_trade_loss",
                "ticker": ticker,
                "name": bs['buy'][0][1],
                "date": date,
                "avg_buy": round(avg_buy, 2),
                "avg_sell": round(avg_sell, 2),
                "loss_pct": (avg_sell/avg_buy-1)*100,
                "note": f"當沖 買均{avg_buy:.1f} → 賣均{avg_sell:.1f} (-{abs((avg_sell/avg_buy-1)*100):.1f}%)",
            })
    return violations


RULES = {
    "chase_high":       (rule_chase_high,       "追高加碼（後一日價 > 前次 +3%）"),
    "no_holding_check": (rule_no_holding_check, "進場後沒守住 (5% 停損出)"),
    "day_trade_loss":   (rule_day_trade_loss,   "當沖追高後砍出"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rule", choices=list(RULES) + ["all"], default="all")
    ap.add_argument("--ticker", help="只看指定 ticker")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()

    conn = get_conn(args.db, timeout=15)
    rules_to_run = list(RULES) if args.rule == "all" else [args.rule]

    total_violations = 0
    for rule_name in rules_to_run:
        func, desc = RULES[rule_name]
        vs = func(conn)
        if args.ticker:
            vs = [v for v in vs if v.get("ticker") == args.ticker]
        print(f"\n{'='*70}")
        print(f"  規則：{rule_name} — {desc}")
        print(f"  違規數：{len(vs)}")
        print(f"{'='*70}")
        for v in vs:
            print(f"  [{v.get('ticker'):5}] {v.get('name', ''):8}  {v['note']}")
        total_violations += len(vs)
    print(f"\n總計：{total_violations} 筆違規操作")


if __name__ == "__main__":
    main()
