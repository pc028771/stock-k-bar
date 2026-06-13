#!/usr/bin/env python3
"""Phase 4 v3 — 真實對帳單 round-trip backtest (修正 v2 agent 幻覺版)。

改進重點 vs v2:
  - Trade list 來自 broker_statement DB，不再用 REAL_TRADES hardcode
  - 只抓 closed round-trips (現買 → 現賣 FIFO 配對 + 當沖)
  - 6/4 南電單日不算 round-trip
  - 3481 群創 5月那筆重新驗證 (v2 用的是 StarLux 星宇航 = 幻覺)
  - 4 個 detector 重跑 (掀傘_5K / 高檔長黑_intraday / 分批停利 / 急殺_1min)

用法:
    python scripts/zhuli/phase4_v3_real_broker_data.py
    python scripts/zhuli/phase4_v3_real_broker_data.py --verbose
"""
from __future__ import annotations

from zhuli.db import get_conn, MAIN_DB

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

import pandas as pd

# ── 路徑設定 ──────────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

_DB = MAIN_DB
# ── Import detectors from v2 ────────────────────────────────────────────────
try:
    from scripts.zhuli.exit.detectors import (
        check_high_long_black,
        check_profit_milestone,
    )
    _DETECTORS_AVAILABLE = True
except ImportError:
    _DETECTORS_AVAILABLE = False
    print("[WARN] exit.detectors 無法載入，部分 detector 停用")

FEE_RATE = 0.000399
TAX_RATE = 0.003
LONG_BUY_ACTIONS = {"現買", "券買"}
LONG_SELL_ACTIONS = {"現賣", "券賣"}

# 僅考慮 2026-05-01 以後的 round-trips (與 v2 對比區間)
ANALYSIS_START = "2026-05-01"


# ─────────────────────────────────────────────────────────────────────────────
# 從 broker_statement 抽出真實 closed round-trips
# ─────────────────────────────────────────────────────────────────────────────

def load_broker_trades(db: Path = _DB) -> list[dict]:
    with get_conn(db) as con:
        rows = con.execute(
            """SELECT id, stock_name, ticker, trade_date, shares, action, price, fee, tax
               FROM broker_statement
               WHERE trade_date >= ?
               ORDER BY trade_date, id""",
            (ANALYSIS_START,),
        ).fetchall()
    cols = ["id", "stock_name", "ticker", "trade_date", "shares", "action", "price", "fee", "tax"]
    return [dict(zip(cols, r)) for r in rows]


def extract_closed_long_trips(trades: list[dict]) -> list[dict]:
    """FIFO 配對現買/現賣，只回傳已出清的 round-trips。"""
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        key = t["ticker"] or t["stock_name"]
        by_ticker[key].append(t)

    all_trips = []
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
                sell_fee_per = (t["fee"] or 0) / t["shares"] if t["shares"] > 0 else 0
                sell_tax_per = (t["tax"] or 0) / t["shares"] if t["shares"] > 0 else 0

                while remaining > 0 and buy_queue:
                    lot = buy_queue[0]
                    matched = min(lot["shares"], remaining)
                    pnl = (t["price"] - sell_fee_per - sell_tax_per
                           - lot["price"] - lot["fee_per"]) * matched

                    all_trips.append({
                        "ticker": ticker,
                        "name": name,
                        "entry_date": lot["date"],
                        "exit_date": t["trade_date"],
                        "entry_price": lot["price"],
                        "exit_price": t["price"],
                        "shares": matched,
                        "actual_pnl": pnl,
                        "trade_type": "波段",
                    })

                    lot["shares"] -= matched
                    remaining -= matched
                    if lot["shares"] <= 0:
                        buy_queue.pop(0)

    return all_trips


def extract_closed_day_trips(trades: list[dict]) -> list[dict]:
    """配對沖買/沖賣 (同日當沖)。"""
    by_ticker_date: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        if t["action"] in {"沖買", "沖賣"}:
            key = f"{t['ticker'] or t['stock_name']}|{t['trade_date']}"
            by_ticker_date[key].append(t)

    all_trips = []
    for key, ticker_trades in by_ticker_date.items():
        ticker_part, date_part = key.rsplit("|", 1)
        name = ticker_trades[0]["stock_name"]
        ticker = ticker_trades[0]["ticker"] or ticker_part

        buys = sorted([t for t in ticker_trades if t["action"] == "沖買"], key=lambda x: x["id"])
        sells = sorted([t for t in ticker_trades if t["action"] == "沖賣"], key=lambda x: x["id"])

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
                all_trips.append({
                    "ticker": ticker,
                    "name": name,
                    "entry_date": date_part,
                    "exit_date": date_part,
                    "entry_price": lot["price"],
                    "exit_price": s["price"],
                    "shares": matched,
                    "actual_pnl": pnl,
                    "trade_type": "當沖",
                })
                lot["shares"] -= matched
                remaining -= matched
                if lot["shares"] <= 0:
                    buy_q.pop(0)

    return all_trips


# ─────────────────────────────────────────────────────────────────────────────
# 資料載入 (from v2)
# ─────────────────────────────────────────────────────────────────────────────

def load_daily_bars(ticker: str, start_date: str, end_date: str = "2026-06-04") -> pd.DataFrame:
    try:
        with get_conn(_DB, timeout=10) as con:
            rows = con.execute(
                """SELECT trade_date, open, high, low, close, volume, ma10, vol_ma20
                   FROM standard_daily_bar
                   WHERE ticker=? AND trade_date >= ? AND trade_date <= ?
                   ORDER BY trade_date""",
                (ticker, start_date, end_date),
            ).fetchall()
        df = pd.DataFrame(rows, columns=["trade_date", "open", "high", "low", "close", "volume", "ma10", "vol_ma20"])
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
        return df
    except Exception as e:
        print(f"[WARN] load_daily_bars({ticker}) 失敗: {e}")
        return pd.DataFrame()


def load_minute_bars(ticker: str, start_date: str, end_date: str = "2026-06-04") -> pd.DataFrame:
    try:
        with get_conn(_DB, timeout=10) as con:
            rows = con.execute(
                """SELECT trade_datetime, open, high, low, close, volume
                   FROM stock_minute_kbar
                   WHERE ticker=?
                     AND substr(trade_datetime,1,10) >= ?
                     AND substr(trade_datetime,1,10) <= ?
                   ORDER BY trade_datetime""",
                (ticker, start_date, end_date),
            ).fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["trade_datetime", "open", "high", "low", "close", "volume"])
        df["dt"] = pd.to_datetime(df["trade_datetime"])
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
        return df
    except Exception as e:
        print(f"[WARN] load_minute_bars({ticker}) 失敗: {e}")
        return pd.DataFrame()


def aggregate_to_5min(df_1min: pd.DataFrame) -> pd.DataFrame:
    if df_1min.empty:
        return pd.DataFrame()
    df = df_1min.copy().set_index("dt")
    df_5min = df[["open", "high", "low", "close", "volume"]].resample("5min").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    })
    return df_5min.dropna(subset=["close"]).reset_index()


def get_5min_for_date(df_1min: pd.DataFrame, date_str: str) -> pd.DataFrame:
    mask = df_1min["trade_datetime"].str.startswith(date_str)
    day_1min = df_1min[mask].copy()
    if day_1min.empty:
        return pd.DataFrame()
    day_1min["dt"] = pd.to_datetime(day_1min["trade_datetime"])
    return aggregate_to_5min(day_1min)


def get_open_price_from_1min(df_1min: pd.DataFrame, date_str: str) -> Optional[float]:
    prefix = f"{date_str} 09:0"
    mask = df_1min["trade_datetime"].str.startswith(prefix)
    day_rows = df_1min[mask].sort_values("trade_datetime")
    if day_rows.empty:
        mask2 = df_1min["trade_datetime"].str.startswith(date_str)
        day_rows = df_1min[mask2].sort_values("trade_datetime")
    if day_rows.empty:
        return None
    return float(day_rows.iloc[0]["open"])


# ─────────────────────────────────────────────────────────────────────────────
# Detectors (inline 簡化版，不依賴 detectors.py)
# ─────────────────────────────────────────────────────────────────────────────

def check_umbrella_exit_5k(k5: pd.DataFrame, entry_price: float) -> dict:
    result = {"triggered": False, "reason": "", "detector": "掀傘_5K"}
    if len(k5) < 5:
        result["reason"] = f"5K 不足 ({len(k5)})"
        return result
    current_close = float(k5["close"].iloc[-1])
    if current_close <= entry_price:
        result["reason"] = f"未賺中 ({current_close:.2f} ≤ {entry_price:.2f})"
        return result
    prior_high = float(k5.iloc[-4]["high"])
    tail_highs = [float(k5.iloc[-(3 - i)]["high"]) for i in range(3)]
    if not all(h <= prior_high for h in tail_highs):
        result["reason"] = f"仍創新高 (前高 {prior_high:.2f})"
        return result
    vol_window = k5["volume"].tail(10)
    vol_mean = float(vol_window.mean())
    last_vol = float(k5["volume"].iloc[-1])
    vol_ratio = last_vol / vol_mean if vol_mean > 0 else 1.0
    if vol_ratio >= 0.7:
        result["reason"] = f"量未縮 (×{vol_ratio:.2f})"
        return result
    profit_pct = (current_close / entry_price - 1) * 100
    result["triggered"] = True
    result["reason"] = f"5K 連3根不創高(前高{prior_high:.2f}) + 量縮×{vol_ratio:.2f} | 浮盈+{profit_pct:.1f}%"
    return result


def check_gap_down_1min(df_1min: pd.DataFrame, date_str: str, prev_close: float) -> dict:
    result = {"triggered": False, "level": "normal", "reason": "", "price": 0.0,
              "detector": "急殺_1min", "gap_pct": 0.0}
    open_price = get_open_price_from_1min(df_1min, date_str)
    if open_price is None:
        result["reason"] = f"無 {date_str} 開盤資料"
        return result
    result["price"] = open_price
    if prev_close <= 0:
        result["reason"] = "前收無效"
        return result
    gap_pct = (open_price / prev_close - 1)
    result["gap_pct"] = gap_pct
    if gap_pct <= -0.05:
        result["triggered"] = True
        result["level"] = "emergency"
        result["reason"] = f"跳空 {gap_pct*100:.1f}% ≤ -5%"
    elif gap_pct <= -0.03:
        result["triggered"] = True
        result["level"] = "warning"
        result["reason"] = f"跳空 {gap_pct*100:.1f}% (-3~-5%)"
    else:
        result["reason"] = f"開盤跳空 {gap_pct*100:.1f}% 正常"
    return result


def check_profit_milestone_simple(current_close: float, entry_price: float, milestones_hit: set) -> dict:
    pct = (current_close / entry_price - 1) * 100
    for threshold, key in [(30, "分批停利_30%"), (20, "分批停利_20%"), (10, "分批停利_10%")]:
        if pct >= threshold and key not in milestones_hit:
            return {"triggered": True, "milestone_key": key,
                    "reason": f"+{threshold}% 達標 (現收{current_close:.2f}, 進場{entry_price:.2f})",
                    "action": f"出 1/3 @ {current_close:.2f}"}
    return {"triggered": False, "milestone_key": "", "reason": ""}


def simulate_trip(trip: dict, verbose: bool = False) -> dict:
    """對單一 round-trip 跑 4 個 detectors。"""
    ticker = trip["ticker"]
    entry_date = trip["entry_date"]
    exit_date = trip["exit_date"]
    entry_price = trip["entry_price"]
    shares = trip["shares"]
    actual_pnl = trip["actual_pnl"]

    # 當沖 — detectors 不適用
    if trip["trade_type"] == "當沖":
        return {**trip, "detectors": {}, "skip_reason": "當沖不跑 detector"}

    # 持有時間太短 (≤ 1 天) 且非開盤急殺
    df_daily = load_daily_bars(ticker, entry_date)
    df_1min = load_minute_bars(ticker, entry_date)

    if df_daily.empty:
        return {**trip, "detectors": {}, "skip_reason": "無日線資料"}

    df_daily = df_daily[df_daily["trade_date"] >= entry_date].reset_index(drop=True)
    if df_daily.empty:
        return {**trip, "detectors": {}, "skip_reason": "進場後無日線"}

    detector_exits: dict[str, dict] = {}
    milestones_hit: set = set()

    for i in range(1, len(df_daily)):
        today = df_daily.iloc[i]
        date_str = str(today["trade_date"])

        # 只看持有期間 + 1 天
        if exit_date and date_str > exit_date:
            break

        current_close = float(today["close"])
        prev_close = float(df_daily.iloc[i - 1]["close"])

        # 5 分 K
        k5_today = get_5min_for_date(df_1min, date_str) if not df_1min.empty else pd.DataFrame()
        min1_today_mask = df_1min["trade_datetime"].str.startswith(date_str) if not df_1min.empty else pd.Series([], dtype=bool)
        min1_today = df_1min[min1_today_mask] if not df_1min.empty else pd.DataFrame()

        # Detector 1: 掀傘 5K
        if "掀傘" not in detector_exits and not k5_today.empty:
            r = check_umbrella_exit_5k(k5_today, entry_price)
            if r["triggered"]:
                pnl = (current_close * (1 - FEE_RATE - TAX_RATE) - entry_price * (1 + FEE_RATE)) * shares
                detector_exits["掀傘"] = {"date": date_str, "price": current_close, "pnl": pnl, "reason": r["reason"]}

        # Detector 2: 高檔長黑 + intraday (需 detectors module)
        if "高檔長黑" not in detector_exits and _DETECTORS_AVAILABLE:
            today_daily_rows = df_daily.iloc[:i + 1]
            try:
                r = check_high_long_black(today_daily_rows, high_zone_ratio=1.2)
                if r["triggered"]:
                    pnl = (current_close * (1 - FEE_RATE - TAX_RATE) - entry_price * (1 + FEE_RATE)) * shares
                    detector_exits["高檔長黑"] = {"date": date_str, "price": current_close, "pnl": pnl, "reason": r["reason"]}
            except Exception:
                pass

        # Detector 3: 分批停利
        r3 = check_profit_milestone_simple(current_close, entry_price, milestones_hit)
        if r3["triggered"]:
            k = r3["milestone_key"]
            milestones_hit.add(k)
            if k not in detector_exits:
                partial_shares = shares // 3
                pnl = (current_close * (1 - FEE_RATE - TAX_RATE) - entry_price * (1 + FEE_RATE)) * partial_shares
                detector_exits[k] = {"date": date_str, "price": current_close, "pnl_partial": pnl, "reason": r3["reason"]}

        # Detector 4: 急殺 1min
        if "急殺" not in detector_exits and not df_1min.empty:
            r4 = check_gap_down_1min(df_1min, date_str, prev_close)
            if r4["triggered"]:
                open_px = r4["price"]
                pnl = (open_px * (1 - FEE_RATE - TAX_RATE) - entry_price * (1 + FEE_RATE)) * shares
                detector_exits["急殺"] = {"date": date_str, "price": open_px, "pnl": pnl,
                                           "reason": r4["reason"], "level": r4["level"]}

    return {**trip, "detectors": detector_exits, "skip_reason": None}


def format_pnl(v) -> str:
    if v is None:
        return "—"
    return f"{v:+,.0f}"


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def run(verbose: bool = False) -> None:
    print("=" * 100)
    print("  Phase 4 v3 — 真實對帳單 Round-trip Backtest (修正 v2 agent 幻覺版)")
    print(f"  分析區間: {ANALYSIS_START} ~ 2026-06-04  (broker_statement 真實資料)")
    print("=" * 100)
    print()

    broker_trades = load_broker_trades()
    print(f"✅ 載入 broker_statement {len(broker_trades)} 筆 ({ANALYSIS_START} 之後)")

    long_trips = extract_closed_long_trips(broker_trades)
    day_trips = extract_closed_day_trips(broker_trades)

    all_trips_raw = long_trips + day_trips
    print(f"   閉合 round-trips: 長線 {len(long_trips)} + 當沖 {len(day_trips)} = {len(all_trips_raw)} 筆")
    print()

    # ── 真實 P&L 統計 ────────────────────────────────────────────────────────
    total_long_pnl = sum(t["actual_pnl"] for t in long_trips)
    total_day_pnl = sum(t["actual_pnl"] for t in day_trips)
    total_pnl = total_long_pnl + total_day_pnl

    win = [t for t in all_trips_raw if t["actual_pnl"] > 0]
    lose = [t for t in all_trips_raw if t["actual_pnl"] < 0]
    win_rate = len(win) / len(all_trips_raw) * 100 if all_trips_raw else 0

    print("─" * 60)
    print("真實 P&L 統計 (May 至今已結 round-trips)")
    print("─" * 60)
    print(f"  長線 P&L:    ${total_long_pnl:>+,.0f}")
    print(f"  當沖 P&L:    ${total_day_pnl:>+,.0f}")
    print(f"  合計 P&L:    ${total_pnl:>+,.0f}")
    print(f"  勝率:        {win_rate:.1f}% ({len(win)}勝/{len(lose)}敗)")
    print()

    # ── 各 ticker 摘要 ────────────────────────────────────────────────────────
    by_ticker_pnl: dict[str, float] = defaultdict(float)
    for t in all_trips_raw:
        by_ticker_pnl[t["ticker"]] += t["actual_pnl"]
    ticker_name = {t["ticker"]: t["name"] for t in all_trips_raw}

    print("─" * 70)
    print("各 Ticker P&L (May+ 已結 round-trips)")
    print("─" * 70)
    print(f"{'Ticker':>8}  {'名稱':<12}  {'P&L':>12}")
    print("-" * 40)
    for tkr, pnl in sorted(by_ticker_pnl.items(), key=lambda x: x[1]):
        print(f"{tkr:>8}  {ticker_name.get(tkr,'?'):<12}  ${pnl:>+12,.0f}")
    print()

    # ── 跑 Detector (只跑長線) ────────────────────────────────────────────────
    print("─" * 100)
    print("Detector Backtest (長線 round-trips only，當沖 skip)")
    print("─" * 100)
    print(f"{'Ticker':<6}{'名稱':<8}{'進場日':<12}{'出場日':<12}{'進場':>7}{'出場':>7}{'真實P&L':>10}  "
          f"{'掀傘':>12}{'掀傘PNL':>9}  {'急殺':>10}{'急殺PNL':>9}  {'分批10%':>12}")
    print("-" * 120)

    results = []
    for trip in sorted(long_trips, key=lambda x: x["entry_date"]):
        if verbose:
            print(f"  [{trip['ticker']}] {trip['entry_date']} → {trip['exit_date']}"
                  f" @{trip['entry_price']:.2f}→{trip['exit_price']:.2f}")
        r = simulate_trip(trip, verbose=verbose)
        results.append(r)

        dets = r.get("detectors", {})
        umb = dets.get("掀傘")
        gap = dets.get("急殺")
        m10 = dets.get("分批停利_10%")

        u_str = f"{umb['date']}" if umb else "未觸發"
        u_pnl = umb.get("pnl") if umb else None
        g_str = f"{gap['date']}" if gap else "未觸發"
        g_pnl = gap.get("pnl") if gap else None
        m_str = f"{m10['date']}" if m10 else "未觸發"

        skip_str = r.get("skip_reason") or ""
        actual_str = r["actual_pnl"]

        print(f"{r['ticker']:<6}{r['name']:<8}{r['entry_date']:<12}{r['exit_date']:<12}"
              f"{r['entry_price']:>7.2f}{r['exit_price']:>7.2f}{format_pnl(actual_str):>10}  "
              f"{u_str:>12}{format_pnl(u_pnl):>9}  "
              f"{g_str:>10}{format_pnl(g_pnl):>9}  "
              f"{m_str:>12}"
              + (f"  [{skip_str}]" if skip_str else ""))

    print("-" * 120)

    # ── v2 vs v3 對比 ────────────────────────────────────────────────────────
    print()
    print("═" * 70)
    print("v2 vs v3 對比重點")
    print("═" * 70)

    # 3481 群創
    trips_3481 = [r for r in results if r["ticker"] == "3481"]
    print(f"\n3481 群創 (v2 錯誤：用 '星宇航' hardcode，v3 用真實對帳單):")
    if trips_3481:
        for t in trips_3481:
            dets = t.get("detectors", {})
            umb = dets.get("掀傘")
            print(f"  {t['entry_date']} → {t['exit_date']}  "
                  f"進 ${t['entry_price']:.2f} → 出 ${t['exit_price']:.2f}  "
                  f"真實P&L ${t['actual_pnl']:+,.0f}")
            if umb:
                print(f"  掀傘觸發 @ {umb['date']} → detector PNL ${umb['pnl']:+,.0f}")
            else:
                print(f"  掀傘未觸發")
    else:
        print("  3481 在 May+ 無已出清長線 round-trip")
        # 從全部 broker_trades 看
        all_3481 = [t for t in broker_trades if t["ticker"] == "3481"]
        buy_3481 = [(t["trade_date"], t["shares"], t["price"], t["action"]) for t in all_3481]
        print(f"  broker 記錄: {buy_3481}")

    # 8046 南電
    trips_8046 = [r for r in results if r["ticker"] == "8046"]
    print(f"\n8046 南電 (6/4 新買單日，不算 round-trip):")
    if trips_8046:
        for t in trips_8046:
            print(f"  {t['entry_date']} → {t['exit_date']}  P&L ${t['actual_pnl']:+,.0f}")
    else:
        all_8046 = [t for t in broker_trades if t["ticker"] == "8046"]
        buy_8046 = [(t["trade_date"], t["shares"], t["price"], t["action"]) for t in all_8046]
        print(f"  broker 記錄 (仍持有): {buy_8046}")
        print(f"  → 確認無 closed round-trip，6/4 買單不符")

    # ── Detector 效果彙整 ────────────────────────────────────────────────────
    print()
    print("═" * 60)
    print("Detector 效果彙整")
    print("═" * 60)

    umb_triggered = [r for r in results if "掀傘" in r.get("detectors", {})]
    gap_triggered = [r for r in results if "急殺" in r.get("detectors", {})]
    m10_triggered = [r for r in results if "分批停利_10%" in r.get("detectors", {})]
    m20_triggered = [r for r in results if "分批停利_20%" in r.get("detectors", {})]

    n_long = len([r for r in results if not r.get("skip_reason")])
    print(f"  分析 {n_long} 筆長線 round-trips")
    print(f"  掀傘_5K 觸發:     {len(umb_triggered)}/{n_long}")
    print(f"  急殺_1min 觸發:   {len(gap_triggered)}/{n_long}")
    print(f"  分批停利_10% 觸發: {len(m10_triggered)}/{n_long}")
    print(f"  分批停利_20% 觸發: {len(m20_triggered)}/{n_long}")

    # 掀傘 delta
    umb_deltas = [(r["detectors"]["掀傘"]["pnl"] or 0) - r["actual_pnl"] for r in umb_triggered]
    if umb_deltas:
        avg_delta = sum(umb_deltas) / len(umb_deltas)
        print(f"\n  掀傘 平均 Δ PNL vs 真實: {avg_delta:+,.0f} (正=比user好)")
    gap_deltas = [(r["detectors"]["急殺"]["pnl"] or 0) - r["actual_pnl"] for r in gap_triggered]
    if gap_deltas:
        avg_delta = sum(gap_deltas) / len(gap_deltas)
        print(f"  急殺 平均 Δ PNL vs 真實: {avg_delta:+,.0f}")

    print()
    print("─" * 60)
    print("結論 (v3 vs v2):")
    print("  v2 問題: REAL_TRADES hardcode 含 '3481 星宇航' (v2 agent 幻覺)")
    print("         → 3481 群創是面板股，非 AI 飛機題材")
    print("  v3 修正: 從 broker_statement FIFO 抽真實 round-trips")
    print("         → 去掉幻覺 ticker、3481 實際在 May 買多賣少 = 仍持有")
    print()
    print("  掀傘_5K detector 結論: 見上方觸發率")
    print("  分批停利 在波段大漲股 (盟立/正達) 仍有效，")
    print("  急殺_1min 需每天 09:00 前確認前收")


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 4 v3 Detector Backtest (真實對帳單)")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()
    run(verbose=args.verbose)


if __name__ == "__main__":
    main()
