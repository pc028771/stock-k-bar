#!/usr/bin/env python3
"""真實 P&L 統計 — 從 broker_statement 計算 3 個月已實現損益。

用法:
    python scripts/zhuli/calc_real_pnl.py
    python scripts/zhuli/calc_real_pnl.py --verbose
"""
from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Optional

DB = Path.home() / ".four_seasons" / "data.sqlite"

# 手續費 / 交易稅率 (備用，優先用對帳單欄位)
FEE_RATE = 0.000399
TAX_RATE = 0.003

# 短線股票 (當沖行為，不計入 day_trade_pnl 之外的統計)
DAY_TRADE_ACTIONS = {"沖買", "沖賣"}
LONG_BUY_ACTIONS = {"現買", "券買"}
LONG_SELL_ACTIONS = {"現賣", "券賣"}


def load_trades(db: Path = DB) -> list[dict]:
    """載入所有對帳單，依 trade_date + id 排序。"""
    with sqlite3.connect(str(db)) as con:
        rows = con.execute(
            """SELECT id, stock_name, ticker, trade_date, shares, action,
                      price, fee, tax, net_amount, cost
               FROM broker_statement
               ORDER BY trade_date, id"""
        ).fetchall()
    cols = ["id", "stock_name", "ticker", "trade_date", "shares", "action",
            "price", "fee", "tax", "net_amount", "cost"]
    return [dict(zip(cols, r)) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# FIFO P&L 計算
# ─────────────────────────────────────────────────────────────────────────────

def fifo_match(trades: list[dict]) -> dict:
    """
    對單一 ticker 的所有現買/現賣/券買/券賣 trades 做 FIFO 配對。
    回傳:
      realized_pnl: 總已實現
      round_trips:  list of (買入日, 賣出日, shares, entry_price, exit_price, pnl)
      open_lots:    仍持有的 lots (price, shares)
      open_shares:  未出清股數
      open_cost:    未出清平均成本
    """
    buy_queue: list[dict] = []  # each: {date, price, shares, fee_each}
    realized = 0
    round_trips = []

    # 分開 buy / sell (現買+券買 vs 現賣+券賣)
    buys = [t for t in trades if t["action"] in LONG_BUY_ACTIONS]
    sells = [t for t in trades if t["action"] in LONG_SELL_ACTIONS]

    for b in buys:
        fee_per_share = (b["fee"] or 0) / b["shares"] if b["shares"] > 0 else 0
        buy_queue.append({
            "date": b["trade_date"],
            "price": b["price"],
            "shares": b["shares"],
            "fee_per_share": fee_per_share,
        })

    for s in sells:
        remaining = s["shares"]
        sell_fee_per = (s["fee"] or 0) / s["shares"] if s["shares"] > 0 else 0
        sell_tax_per = (s["tax"] or 0) / s["shares"] if s["shares"] > 0 else 0

        while remaining > 0 and buy_queue:
            lot = buy_queue[0]
            matched = min(lot["shares"], remaining)
            buy_net = lot["price"] + lot["fee_per_share"]
            sell_net = s["price"] - sell_fee_per - sell_tax_per
            pnl = (sell_net - buy_net) * matched

            round_trips.append({
                "entry_date": lot["date"],
                "exit_date": s["trade_date"],
                "shares": matched,
                "entry_price": lot["price"],
                "exit_price": s["price"],
                "pnl": pnl,
            })
            realized += pnl

            lot["shares"] -= matched
            remaining -= matched
            if lot["shares"] <= 0:
                buy_queue.pop(0)

        # 若賣超過持倉 (罕見)，剩餘不配對
        if remaining > 0:
            # 賣出比買進多 (可能是其他來源持股)
            pass

    # 未出清
    open_shares = sum(lot["shares"] for lot in buy_queue)
    if open_shares > 0:
        total_cost = sum(lot["price"] * lot["shares"] for lot in buy_queue)
        open_cost = total_cost / open_shares
    else:
        open_cost = 0.0

    return {
        "realized_pnl": realized,
        "round_trips": round_trips,
        "open_lots": buy_queue,
        "open_shares": open_shares,
        "open_cost": open_cost,
    }


def calc_day_trade_pnl(trades: list[dict]) -> dict:
    """計算當沖 (沖買/沖賣) P&L，配對在同一天內。"""
    by_date: dict[str, dict] = defaultdict(lambda: {"買": [], "賣": []})
    for t in trades:
        if t["action"] == "沖買":
            by_date[t["trade_date"]]["買"].append(t)
        elif t["action"] == "沖賣":
            by_date[t["trade_date"]]["賣"].append(t)

    realized = 0
    round_trips = []
    for date, sides in by_date.items():
        buys = sorted(sides["買"], key=lambda x: x["id"])
        sells = sorted(sides["賣"], key=lambda x: x["id"])

        buy_q = []
        for b in buys:
            fp = (b["fee"] or 0) / b["shares"] if b["shares"] > 0 else 0
            buy_q.append({"price": b["price"], "shares": b["shares"], "fee_per": fp})

        for s in sells:
            remaining = s["shares"]
            sf = (s["fee"] or 0) / s["shares"] if s["shares"] > 0 else 0
            st = (s["tax"] or 0) / s["shares"] if s["shares"] > 0 else 0
            while remaining > 0 and buy_q:
                lot = buy_q[0]
                matched = min(lot["shares"], remaining)
                pnl = (s["price"] - sf - st - lot["price"] - lot["fee_per"]) * matched
                realized += pnl
                round_trips.append({
                    "entry_date": date, "exit_date": date,
                    "shares": matched,
                    "entry_price": lot["price"], "exit_price": s["price"],
                    "pnl": pnl,
                    "is_day_trade": True,
                })
                lot["shares"] -= matched
                remaining -= matched
                if lot["shares"] <= 0:
                    buy_q.pop(0)

    return {"realized_pnl": realized, "round_trips": round_trips}


# ─────────────────────────────────────────────────────────────────────────────
# Main analysis
# ─────────────────────────────────────────────────────────────────────────────

def run(verbose: bool = False) -> None:
    trades = load_trades()
    print(f"✅ 載入 {len(trades)} 筆對帳單資料 ({trades[0]['trade_date']} ~ {trades[-1]['trade_date']})")
    print()

    # 依 ticker 分組
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        key = t["ticker"] or t["stock_name"]
        by_ticker[key].append(t)

    # ── 各 ticker 統計 ────────────────────────────────────────────────────────
    ticker_results = []
    total_realized = 0
    all_long_trips = []
    all_day_trips = []

    for key, ticker_trades in sorted(by_ticker.items()):
        sample = ticker_trades[0]
        name = sample["stock_name"]
        ticker = sample["ticker"] or "?"

        long_res = fifo_match(ticker_trades)
        day_res = calc_day_trade_pnl(ticker_trades)

        realized = long_res["realized_pnl"] + day_res["realized_pnl"]
        total_realized += realized

        long_buy_count = sum(t["shares"] for t in ticker_trades if t["action"] in LONG_BUY_ACTIONS)
        long_sell_count = sum(t["shares"] for t in ticker_trades if t["action"] in LONG_SELL_ACTIONS)
        day_buy_count = sum(t["shares"] for t in ticker_trades if t["action"] == "沖買")
        day_sell_count = sum(t["shares"] for t in ticker_trades if t["action"] == "沖賣")
        total_buy_lots = (long_buy_count + day_buy_count) // 1000
        total_sell_lots = (long_sell_count + day_sell_count) // 1000

        open_shares = long_res["open_shares"]
        open_lots = open_shares // 1000
        open_cost = long_res["open_cost"]

        ticker_results.append({
            "ticker": ticker,
            "name": name,
            "buy_lots": total_buy_lots,
            "sell_lots": total_sell_lots,
            "realized_pnl": realized,
            "open_lots": open_lots,
            "open_shares": open_shares,
            "open_cost": open_cost,
        })

        all_long_trips.extend(long_res["round_trips"])
        all_day_trips.extend(day_res["round_trips"])

    # ── 各 ticker P&L 表格 ───────────────────────────────────────────────────
    print("=" * 80)
    print("各 Ticker 已實現 P&L")
    print("=" * 80)
    header = f"{'Ticker':>8}  {'名稱':<12} {'進場(張)':>8} {'出場(張)':>8} {'已實現P&L':>12} {'持有':<10}"
    print(header)
    print("-" * 80)

    sorted_results = sorted(ticker_results, key=lambda x: x["realized_pnl"])
    for r in sorted_results:
        hold_str = f"{r['open_lots']}張" if r["open_lots"] > 0 else "-"
        pnl_str = f"${r['realized_pnl']:>+,.0f}"
        print(f"{r['ticker']:>8}  {r['name']:<12} {r['buy_lots']:>8}張 {r['sell_lots']:>8}張"
              f" {pnl_str:>12}  {hold_str}")

    print("-" * 80)
    print(f"{'合計':>62}  ${total_realized:>+,.0f}")
    print()

    # ── 月度趨勢 ─────────────────────────────────────────────────────────────
    monthly: dict[str, dict] = defaultdict(lambda: {"count": 0, "pnl": 0})
    for t in trades:
        ym = t["trade_date"][:7]
        monthly[ym]["count"] += 1

    # 月度 realized (需拆分 round-trips 到 exit_date 月份)
    monthly_pnl: dict[str, float] = defaultdict(float)
    for trip in all_long_trips + all_day_trips:
        ym = trip["exit_date"][:7]
        monthly_pnl[ym] += trip["pnl"]

    print("=" * 50)
    print("月度趨勢")
    print("=" * 50)
    print(f"{'月份':>8}  {'交易筆數':>8}  {'已實現P&L':>14}")
    print("-" * 50)
    for ym in sorted(monthly.keys()):
        cnt = monthly[ym]["count"]
        pnl = monthly_pnl.get(ym, 0)
        print(f"{ym:>8}  {cnt:>8}  ${pnl:>+12,.0f}")
    print()

    # ── 整體統計 ────────────────────────────────────────────────────────────
    all_trips = all_long_trips + all_day_trips
    win_trips = [t for t in all_trips if t["pnl"] > 0]
    lose_trips = [t for t in all_trips if t["pnl"] < 0]

    win_rate = len(win_trips) / len(all_trips) * 100 if all_trips else 0
    avg_win = sum(t["pnl"] for t in win_trips) / len(win_trips) if win_trips else 0
    avg_lose = sum(t["pnl"] for t in lose_trips) / len(lose_trips) if lose_trips else 0

    print("=" * 50)
    print("整體統計")
    print("=" * 50)
    print(f"  總交易筆數:      {len(trades)}")
    print(f"  Round-trip 數:   {len(all_trips)} (長線 {len(all_long_trips)} + 當沖 {len(all_day_trips)})")
    print(f"  已實現累計 P&L:  ${total_realized:+,.0f}")
    print(f"  勝率:            {win_rate:.1f}% ({len(win_trips)}勝 / {len(lose_trips)}敗)")
    print(f"  平均獲利 (勝):   ${avg_win:+,.0f}")
    print(f"  平均損失 (敗):   ${avg_lose:+,.0f}")

    # Top 5 最賺 / 最賠
    ticker_pnl = defaultdict(float)
    ticker_name_map = {}
    for trip in all_trips:
        # 找對應 ticker
        pass

    # 使用 ticker_results 統計
    sorted_by_pnl = sorted(ticker_results, key=lambda x: x["realized_pnl"], reverse=True)
    print()
    print("  最賺 Top 5:")
    for r in sorted_by_pnl[:5]:
        if r["realized_pnl"] > 0:
            print(f"    {r['ticker']} {r['name']:10}  ${r['realized_pnl']:>+,.0f}")
    print("  最賠 Top 5:")
    for r in sorted_by_pnl[-5:][::-1]:
        if r["realized_pnl"] < 0:
            print(f"    {r['ticker']} {r['name']:10}  ${r['realized_pnl']:>+,.0f}")
    print()

    # ── 仍持有的 Open Positions ──────────────────────────────────────────────
    open_positions = [r for r in ticker_results if r["open_shares"] > 0]
    if open_positions:
        print("=" * 60)
        print("仍持有 (Open Positions)")
        print("=" * 60)
        print(f"{'Ticker':>8}  {'名稱':<12} {'持股':>8}  {'平均成本':>10}")
        print("-" * 60)
        for r in open_positions:
            shares_str = f"{r['open_shares']:,} 股 ({r['open_lots']}張)"
            print(f"{r['ticker']:>8}  {r['name']:<12} {shares_str:>16}  ${r['open_cost']:.2f}")
        print()

    if verbose:
        print("=" * 80)
        print("詳細 Round-trips")
        print("=" * 80)
        for trip in sorted(all_trips, key=lambda x: x["exit_date"]):
            dt = "當沖" if trip.get("is_day_trade") else "波段"
            print(
                f"  [{dt}] {trip['entry_date']} → {trip['exit_date']}"
                f"  進 ${trip['entry_price']:.2f}  出 ${trip['exit_price']:.2f}"
                f"  {trip['shares']:,}股  P&L ${trip['pnl']:+,.0f}"
            )


def main() -> None:
    ap = argparse.ArgumentParser(description="真實 P&L 統計")
    ap.add_argument("--verbose", "-v", action="store_true", help="顯示詳細 round-trips")
    args = ap.parse_args()
    run(verbose=args.verbose)


if __name__ == "__main__":
    main()
