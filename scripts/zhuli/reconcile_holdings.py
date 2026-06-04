#!/usr/bin/env python3
"""Reconcile holdings.json vs 真實 broker_statement 持倉對照。

比較邏輯:
  broker 真實持倉 = FIFO 計算 (現買 - 現賣) + ETF 現買 - 現賣
  holdings.json   = 手動維護的 JSON 快照

輸出:
  diff table — 每個 ticker 的 JSON shares vs broker shares + 差異說明

用法:
    python scripts/zhuli/reconcile_holdings.py
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

DB = Path.home() / ".four_seasons" / "data.sqlite"
HOLDINGS_JSON = Path(__file__).parent.parent.parent / "docs" / "主力大課程" / "holdings.json"

LONG_BUY_ACTIONS = {"現買", "券買"}
LONG_SELL_ACTIONS = {"現賣", "券賣"}


def calc_broker_positions(db: Path = DB) -> dict[str, dict]:
    """從 broker_statement FIFO 計算每個 ticker 目前真實持股。

    回傳 dict[ticker → {shares, avg_cost, stock_name}]
    """
    with sqlite3.connect(str(db)) as con:
        rows = con.execute(
            """SELECT id, stock_name, ticker, trade_date, shares, action, price, fee
               FROM broker_statement
               ORDER BY trade_date, id"""
        ).fetchall()

    cols = ["id", "stock_name", "ticker", "trade_date", "shares", "action", "price", "fee"]
    trades = [dict(zip(cols, r)) for r in rows]

    # Group by ticker
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        key = t["ticker"] or t["stock_name"]
        by_ticker[key].append(t)

    positions: dict[str, dict] = {}
    for key, ticker_trades in by_ticker.items():
        name = ticker_trades[0]["stock_name"]
        ticker = ticker_trades[0]["ticker"] or key

        buy_queue: list[dict] = []
        for t in ticker_trades:
            if t["action"] in LONG_BUY_ACTIONS:
                fp = (t["fee"] or 0) / t["shares"] if t["shares"] > 0 else 0
                buy_queue.append({
                    "date": t["trade_date"],
                    "price": t["price"],
                    "shares": t["shares"],
                    "fee_per": fp,
                })
            elif t["action"] in LONG_SELL_ACTIONS:
                remaining = t["shares"]
                while remaining > 0 and buy_queue:
                    lot = buy_queue[0]
                    matched = min(lot["shares"], remaining)
                    lot["shares"] -= matched
                    remaining -= matched
                    if lot["shares"] <= 0:
                        buy_queue.pop(0)
                # 若賣超持倉忽略 (表示有前期持倉未在對帳單內)

        open_shares = sum(lot["shares"] for lot in buy_queue)
        if open_shares > 0 and buy_queue:
            total_cost = sum(lot["price"] * lot["shares"] for lot in buy_queue)
            avg_cost = total_cost / open_shares
            positions[ticker] = {
                "stock_name": name,
                "shares": open_shares,
                "avg_cost": avg_cost,
            }

    return positions


def parse_holdings_json(path: Path = HOLDINGS_JSON) -> dict[str, dict]:
    """從 holdings.json 抽出每個 HELD 持倉的 shares。

    回傳 dict[ticker → {shares, cost, name}]
    """
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    holdings: dict[str, dict] = {}
    h = data.get("holdings", {})

    # 只抓非 _CLOSED / 非 metadata 的 key
    for key, val in h.items():
        if key.startswith("_") or "CLOSED" in key:
            continue
        if not isinstance(val, dict):
            continue
        # 嘗試解析 ticker (key 可能是 "6285_啟碁" 或 "2885")
        ticker_raw = key.split("_")[0]
        shares_raw = val.get("shares", None)
        if shares_raw is None:
            continue
        try:
            shares = int(float(shares_raw)) * 1000  # JSON 單位是「張」
        except (ValueError, TypeError):
            shares = 0

        name = val.get("name", key)
        cost = val.get("cost", 0)
        holdings[ticker_raw] = {
            "name": name,
            "shares": shares,
            "cost": cost,
        }

    # ETF locked
    for ticker, val in data.get("etf_locked", {}).items():
        etf_shares = int(float(val.get("shares", 0))) * 1000
        holdings[ticker] = {
            "name": val.get("name", ticker),
            "shares": etf_shares,
            "cost": val.get("cost", 0),
        }

    return holdings


def run() -> None:
    print("=" * 70)
    print("holdings.json vs broker 真實持倉 Reconcile")
    print("=" * 70)

    broker_pos = calc_broker_positions()
    json_pos = parse_holdings_json()

    # 合併所有 tickers
    all_tickers = sorted(set(list(broker_pos.keys()) + list(json_pos.keys())))

    print(f"\n{'Ticker':>10}  {'名稱':<14} {'JSON shares':>12} {'Broker shares':>14} {'差異':>10}  狀態")
    print("-" * 80)

    has_mismatch = False
    for ticker in all_tickers:
        b = broker_pos.get(ticker)
        j = json_pos.get(ticker)

        b_shares = b["shares"] if b else 0
        j_shares = j["shares"] if j else 0
        diff = j_shares - b_shares
        name = (j["name"] if j else b["stock_name"]) if (j or b) else ticker

        if b_shares == 0 and j_shares == 0:
            continue

        if diff == 0:
            status = "✅ OK"
        elif j_shares == 0 and b_shares > 0:
            status = "⚠️ JSON 未記錄 (broker 有持倉)"
            has_mismatch = True
        elif j_shares > 0 and b_shares == 0:
            status = "⚠️ JSON 有但 broker 無 (可能已清倉)"
            has_mismatch = True
        else:
            status = f"❌ 差異 {diff:+,} 股"
            has_mismatch = True

        print(f"{ticker:>10}  {name:<14} {j_shares:>12,} {b_shares:>14,} {diff:>+10,}  {status}")

    print("-" * 80)

    if not has_mismatch:
        print("\n✅ 所有 ticker 持倉一致，無差異。")
    else:
        print("\n⚠️ 有差異，請確認 holdings.json 是否需要更新。")
        print("   注意: 本工具只生成 diff report，不自動修改 holdings.json。")

    print()
    print("=== Broker 真實持倉 (非零) ===")
    print(f"{'Ticker':>10}  {'名稱':<14} {'持股':>10}  {'平均成本':>10}")
    print("-" * 55)
    for ticker, v in sorted(broker_pos.items()):
        lots = v["shares"] // 1000
        remain = v["shares"] % 1000
        lot_str = f"{lots}張" + (f"+{remain}股" if remain else "")
        print(f"{ticker:>10}  {v['stock_name']:<14} {lot_str:>10}  ${v['avg_cost']:>8.2f}")

    print()
    print("=== holdings.json 記錄 (非零) ===")
    print(f"{'Ticker':>10}  {'名稱':<14} {'JSON shares':>12}  {'成本':>8}")
    print("-" * 55)
    for ticker, v in sorted(json_pos.items()):
        if v["shares"] > 0:
            lots = v["shares"] // 1000
            remain = v["shares"] % 1000
            lot_str = f"{lots}張" + (f"+{remain}股" if remain else "")
            print(f"{ticker:>10}  {v['name']:<14} {lot_str:>12}  ${v['cost']}")


if __name__ == "__main__":
    run()
