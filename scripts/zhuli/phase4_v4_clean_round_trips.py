#!/usr/bin/env python3
"""Phase 4 v4 — Clean Round-Trip Detector Backtest。

改進重點 vs v3:
  - 依 user 提供的「完整 round-trip 配對成功」ticker 清單過濾
  - 跳過缺賣出紀錄的 ticker (3481/2303/4555/8064/8358)
  - broker ticker → DB real ticker 轉換 (頎邦 711127 → 6147、金居 709966 → 8358 skip)
  - 拉寬分析區間到 3/04 起 (cover 頎邦 4/14 等 Q2 早期操作)
  - 掀傘改用 check_umbrella_exit_daily (日線版) 而非 5K 版
  - 高檔長黑 high_zone_ratio 放寬至 1.2
  - 完整 delta_pnl 統計表 + 具體有救 case
  - User 出場行為模式分析

用法:
    python scripts/zhuli/phase4_v4_clean_round_trips.py
    python scripts/zhuli/phase4_v4_clean_round_trips.py --verbose
"""
from __future__ import annotations

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

from zhuli.db import get_conn, MAIN_DB
_DB = MAIN_DB
# ── 費率 ──────────────────────────────────────────────────────────────────────
FEE_RATE = 0.000399
TAX_RATE = 0.003

LONG_BUY_ACTIONS  = {"現買", "券買"}
LONG_SELL_ACTIONS = {"現賣", "券賣"}

# ── 分析區間 ──────────────────────────────────────────────────────────────────
ANALYSIS_START = "2026-03-04"   # 對帳單起始

# ── Broker ticker → DB real ticker 轉換表 ────────────────────────────────────
BROKER_TO_REAL: dict[str, str] = {
    "711127": "6147",    # 頎邦
    "709966": "8358",    # 金居 (但 8358 在 user 的 skip list 故不影響)
}

# ── User 明確指定的 clean round-trip ticker (broker 代號) ─────────────────────
# 來源: user 提供的 broker_statement reconcile 結果
CLEAN_ROUND_TRIP_TICKERS: set[str] = {
    "711127",   # 頎邦
    "2351",     # 順德
    "2327",     # 國巨
    "6770",     # 力積電
    "2449",     # 京元電子
    "8210",     # 勤誠
    "3583",     # 辛耘
    "8027",     # 鈦昇
    "3265",     # 台星科
    "6415",     # 矽力*-KY
    "2337",     # 旺宏
    "1802",     # 台玻
    "1785",     # 光洋科
    "5439",     # 高技
    "6207",     # 雷科
    "2049",     # 上銀
    "8016",     # 矽創 (當沖完整)
    "3006",     # 晶豪科
    "2476",     # 鉅祥
    "3149",     # 正達
    "6282",     # 康舒
    "2464",     # 盟立
    "5347",     # 世界
    "4939",     # 亞電 (當沖)
    "3016",     # 嘉晶 (當沖)
    "2485",     # 兆赫
    "2344",     # 華邦電
    "2317",     # 鴻海 (當沖)
    "2481",     # 強茂
    "6271",     # 同欣電
    "8046",     # 南電 (4月那筆 1天 round-trip)
    # ETF/指數產品 — 有完整配對但跳過 (非個股 detector 適用)
    # "00632R",   # 元大50反1
}

# ── 缺賣出紀錄、跳過的 ticker ──────────────────────────────────────────────────
SKIP_TICKERS: set[str] = {
    "3481",  # 群創
    "2303",  # 聯電
    "1721",  # 三晃 (=4555 如有)
    "8064",  # 東捷
    "709966", # 金居 (= 8358)
}

# ── Import detectors ──────────────────────────────────────────────────────────
try:
    from zhuli.exit.detectors import (
        check_umbrella_exit_daily,
        check_high_long_black,
        check_profit_milestone,
        check_gap_down_emergency,
    )
    _DETECTORS_AVAILABLE = True
except ImportError:
    _DETECTORS_AVAILABLE = False
    print("[WARN] exit.detectors 無法載入，部分 detector 停用")


# ─────────────────────────────────────────────────────────────────────────────
# 資料載入
# ─────────────────────────────────────────────────────────────────────────────

def get_real_ticker(broker_ticker: str) -> str:
    """轉換 broker ticker → DB real ticker。"""
    return BROKER_TO_REAL.get(broker_ticker, broker_ticker)


def load_broker_trades() -> list[dict]:
    with get_conn(_DB) as con:
        rows = con.execute(
            """SELECT id, stock_name, ticker, trade_date, shares, action, price, fee, tax
               FROM broker_statement
               WHERE trade_date >= ?
               ORDER BY trade_date, id""",
            (ANALYSIS_START,),
        ).fetchall()
    cols = ["id", "stock_name", "ticker", "trade_date", "shares", "action", "price", "fee", "tax"]
    return [dict(zip(cols, r)) for r in rows]


def load_daily_bars(real_ticker: str, start_date: str, end_date: str = "2026-06-04") -> pd.DataFrame:
    try:
        with get_conn(_DB, timeout=10) as con:
            rows = con.execute(
                """SELECT trade_date, open, high, low, close, volume
                   FROM standard_daily_bar
                   WHERE ticker=? AND trade_date >= ? AND trade_date <= ?
                   ORDER BY trade_date""",
                (real_ticker, start_date, end_date),
            ).fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["trade_date", "open", "high", "low", "close", "volume"])
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
        return df
    except Exception as e:
        return pd.DataFrame()


def load_minute_bars(real_ticker: str, start_date: str, end_date: str = "2026-06-04") -> pd.DataFrame:
    try:
        with get_conn(_DB, timeout=10) as con:
            rows = con.execute(
                """SELECT trade_datetime, open, high, low, close, volume
                   FROM stock_minute_kbar
                   WHERE ticker=?
                     AND substr(trade_datetime,1,10) >= ?
                     AND substr(trade_datetime,1,10) <= ?
                   ORDER BY trade_datetime""",
                (real_ticker, start_date, end_date),
            ).fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["trade_datetime", "open", "high", "low", "close", "volume"])
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
        return df
    except Exception as e:
        return pd.DataFrame()


def get_open_price_from_minute(df_1min: pd.DataFrame, date_str: str) -> Optional[float]:
    mask = df_1min["trade_datetime"].str.startswith(date_str)
    day_rows = df_1min[mask].sort_values("trade_datetime")
    if day_rows.empty:
        return None
    return float(day_rows.iloc[0]["open"])


# ─────────────────────────────────────────────────────────────────────────────
# Round-trip 抽出
# ─────────────────────────────────────────────────────────────────────────────

def extract_closed_long_trips(trades: list[dict]) -> list[dict]:
    """FIFO 配對現買/現賣，只回傳 clean round-trip 且已出清的紀錄。"""
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        broker_tk = t["ticker"] or t["stock_name"]
        if broker_tk not in CLEAN_ROUND_TRIP_TICKERS:
            continue
        if broker_tk in SKIP_TICKERS:
            continue
        by_ticker[broker_tk].append(t)

    all_trips: list[dict] = []
    for broker_tk, ticker_trades in by_ticker.items():
        real_tk = get_real_ticker(broker_tk)
        name = ticker_trades[0]["stock_name"]

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
                    # 使用實際 fee/tax 計算 pnl
                    pnl = (
                        t["price"] * (1 - sell_fee_per / t["price"] if t["price"] > 0 else 0)
                        - sell_tax_per
                        - lot["price"]
                        - lot["fee_per"]
                    ) * matched
                    # 更精確：(exit_price - exit_fee_per - exit_tax_per - entry_price - entry_fee_per) * shares
                    pnl = (t["price"] - sell_fee_per - sell_tax_per
                           - lot["price"] - lot["fee_per"]) * matched

                    all_trips.append({
                        "broker_ticker": broker_tk,
                        "ticker": real_tk,
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
    """配對沖買/沖賣 (同日當沖) — 只處理 CLEAN_ROUND_TRIP_TICKERS。"""
    by_key: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        if t["action"] not in {"沖買", "沖賣"}:
            continue
        broker_tk = t["ticker"] or t["stock_name"]
        if broker_tk not in CLEAN_ROUND_TRIP_TICKERS:
            continue
        key = f"{broker_tk}|{t['trade_date']}"
        by_key[key].append(t)

    all_trips: list[dict] = []
    for key, ticker_trades in by_key.items():
        broker_tk, date_str = key.rsplit("|", 1)
        real_tk = get_real_ticker(broker_tk)
        name = ticker_trades[0]["stock_name"]

        buys  = sorted([t for t in ticker_trades if t["action"] == "沖買"], key=lambda x: x["id"])
        sells = sorted([t for t in ticker_trades if t["action"] == "沖賣"], key=lambda x: x["id"])

        buy_q: list[dict] = []
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
                    "broker_ticker": broker_tk,
                    "ticker": real_tk,
                    "name": name,
                    "entry_date": date_str,
                    "exit_date": date_str,
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
# Detector 模擬
# ─────────────────────────────────────────────────────────────────────────────

def pnl_if_exit(exit_price: float, entry_price: float, shares: int) -> float:
    return (exit_price * (1 - FEE_RATE - TAX_RATE)
            - entry_price * (1 + FEE_RATE)) * shares


def pnl_if_partial(exit_price: float, entry_price: float, shares: int, fraction: float = 1/3) -> float:
    partial = max(1, int(shares * fraction))
    return (exit_price * (1 - FEE_RATE - TAX_RATE)
            - entry_price * (1 + FEE_RATE)) * partial


def simulate_trip(trip: dict, verbose: bool = False) -> dict:
    """對單一 round-trip 跑 6 個 detectors。"""
    ticker      = trip["ticker"]
    entry_date  = trip["entry_date"]
    exit_date   = trip["exit_date"]
    entry_price = trip["entry_price"]
    shares      = trip["shares"]
    actual_pnl  = trip["actual_pnl"]

    # 當沖 — 不跑 detector
    if trip["trade_type"] == "當沖":
        return {**trip, "detectors": {}, "skip_reason": "當沖不跑 detector"}

    # 持有 = entry_date == exit_date 且非當沖 (罕見) → 也 skip
    if entry_date == exit_date:
        return {**trip, "detectors": {}, "skip_reason": "單日波段 skip"}

    df_daily = load_daily_bars(ticker, entry_date)
    df_1min  = load_minute_bars(ticker, entry_date)

    if df_daily.empty:
        return {**trip, "detectors": {}, "skip_reason": f"無日線資料 ({ticker})"}

    # 只看進場後到出場日的資料
    df_hold = df_daily[
        (df_daily["trade_date"] >= entry_date) &
        (df_daily["trade_date"] <= exit_date)
    ].reset_index(drop=True)

    if len(df_hold) < 2:
        return {**trip, "detectors": {}, "skip_reason": "持有日數不足"}

    detector_exits: dict[str, dict] = {}
    milestones_hit: set[str] = set()

    # 歷史 df (包含 entry 之前的日線，給高檔長黑 lookback 用)
    df_hist_full = df_daily.copy().reset_index(drop=True)

    for i in range(1, len(df_hold)):
        today     = df_hold.iloc[i]
        prev      = df_hold.iloc[i - 1]
        date_str  = str(today["trade_date"])
        cur_close = float(today["close"])
        prev_close = float(prev["close"])

        # 找到 df_hist_full 中 date_str 的 row index (給高檔長黑)
        mask_today = df_hist_full["trade_date"] == date_str
        idx_today  = df_hist_full.index[mask_today].tolist()

        # ── Detector 1: 掀傘 (日線版) ─────────────────────────────────────
        if "掀傘" not in detector_exits and _DETECTORS_AVAILABLE:
            try:
                df_for_umb = df_hold.iloc[:i + 1].copy()
                r = check_umbrella_exit_daily(df_for_umb, entry_price)
                if r["triggered"]:
                    exit_px = cur_close
                    dpnl = pnl_if_exit(exit_px, entry_price, shares)
                    detector_exits["掀傘"] = {
                        "date": date_str,
                        "price": exit_px,
                        "pnl": dpnl,
                        "delta": dpnl - actual_pnl,
                        "reason": r["reason"],
                    }
            except Exception as e:
                if verbose:
                    print(f"    [掀傘] 例外: {e}")

        # ── Detector 2: 高檔長黑 ──────────────────────────────────────────
        if "高檔長黑" not in detector_exits and _DETECTORS_AVAILABLE and idx_today:
            try:
                end_idx = idx_today[0] + 1
                df_for_hlb = df_hist_full.iloc[:end_idx].copy()
                r = check_high_long_black(df_for_hlb, high_zone_ratio=1.2)
                if r["triggered"]:
                    exit_px = cur_close
                    dpnl = pnl_if_exit(exit_px, entry_price, shares)
                    detector_exits["高檔長黑"] = {
                        "date": date_str,
                        "price": exit_px,
                        "pnl": dpnl,
                        "delta": dpnl - actual_pnl,
                        "reason": r["reason"],
                    }
            except Exception as e:
                if verbose:
                    print(f"    [高檔長黑] 例外: {e}")

        # ── Detector 3/4/5: 分批停利 10% / 20% / 30% ──────────────────────
        for threshold, key in [(0.10, "分批_10%"), (0.20, "分批_20%"), (0.30, "分批_30%")]:
            if key not in detector_exits and key not in milestones_hit:
                pct = (cur_close / entry_price - 1)
                if pct >= threshold:
                    milestones_hit.add(key)
                    exit_px = cur_close
                    partial_shares = max(1, shares // 3)
                    dpnl_partial = pnl_if_partial(exit_px, entry_price, shares, 1/3)
                    detector_exits[key] = {
                        "date": date_str,
                        "price": exit_px,
                        "pnl_partial": dpnl_partial,
                        # delta: 若早鎖 1/3，剩 2/3 照 actual 出 → 總收益
                        "delta": dpnl_partial + pnl_if_exit(
                            trip["exit_price"], entry_price, shares - partial_shares
                        ) - actual_pnl,
                        "reason": f"+{threshold*100:.0f}% 達標 @ {exit_px:.2f} (1/3 出)",
                    }

        # ── Detector 6: 急殺 (次日跳空) ────────────────────────────────────
        if "急殺" not in detector_exits and not df_1min.empty:
            open_px = get_open_price_from_minute(df_1min, date_str)
            if open_px is not None and prev_close > 0:
                gap_pct = (open_px / prev_close - 1)
                if gap_pct <= -0.03:
                    dpnl = pnl_if_exit(open_px, entry_price, shares)
                    detector_exits["急殺"] = {
                        "date": date_str,
                        "price": open_px,
                        "pnl": dpnl,
                        "delta": dpnl - actual_pnl,
                        "gap_pct": gap_pct,
                        "reason": f"跳空 {gap_pct*100:.1f}% ≤ -3%",
                    }

    return {**trip, "detectors": detector_exits, "skip_reason": None}


# ─────────────────────────────────────────────────────────────────────────────
# 格式化輔助
# ─────────────────────────────────────────────────────────────────────────────

def fmt_pnl(v) -> str:
    if v is None:
        return "—"
    return f"${v:>+,.0f}"


def fmt_delta(v) -> str:
    if v is None:
        return "—"
    arrow = "↑" if v > 0 else ("↓" if v < 0 else "=")
    return f"{arrow}{abs(v):,.0f}"


# ─────────────────────────────────────────────────────────────────────────────
# 統計彙整
# ─────────────────────────────────────────────────────────────────────────────

def build_detector_stats(results: list[dict]) -> dict:
    """計算各 detector 的觸發率 / 平均 delta / 中位數 delta。"""
    det_keys = ["掀傘", "高檔長黑", "分批_10%", "分批_20%", "分批_30%", "急殺"]
    stats: dict[str, dict] = {}
    # 只算波段 (當沖 skip)
    swing = [r for r in results if not r.get("skip_reason")]
    n = len(swing)

    for key in det_keys:
        triggered = [r for r in swing if key in r.get("detectors", {})]
        deltas = []
        for r in triggered:
            d = r["detectors"][key]
            delta_val = d.get("delta")
            if delta_val is not None:
                deltas.append(delta_val)

        if deltas:
            avg_d  = sum(deltas) / len(deltas)
            median_d = sorted(deltas)[len(deltas) // 2]
            best_d = max(deltas)
            worst_d = min(deltas)
        else:
            avg_d = median_d = best_d = worst_d = None

        stats[key] = {
            "trigger_n": len(triggered),
            "total_n": n,
            "trigger_pct": len(triggered) / n * 100 if n > 0 else 0,
            "avg_delta": avg_d,
            "median_delta": median_d,
            "best_delta": best_d,
            "worst_delta": worst_d,
            "triggered_trips": triggered,
        }
    return stats


def top_cases(results: list[dict], det_key: str, top_n: int = 5) -> list[tuple]:
    """回傳某 detector 的 top delta cases。"""
    cases = []
    for r in results:
        d = r.get("detectors", {}).get(det_key)
        if d and d.get("delta") is not None:
            cases.append((d["delta"], r, d))
    return sorted(cases, key=lambda x: x[0], reverse=True)[:top_n]


# ─────────────────────────────────────────────────────────────────────────────
# 報告生成
# ─────────────────────────────────────────────────────────────────────────────

def generate_report(
    results: list[dict],
    day_trips: list[dict],
    stats: dict,
    total_long_pnl: float,
    total_day_pnl: float,
) -> str:
    lines: list[str] = []
    a = lines.append

    a("# Phase 4 v4 — Clean Round-Trip Detector Backtest")
    a("")
    a(f"分析區間: {ANALYSIS_START} ~ 2026-06-04")
    a(f"資料來源: broker_statement (國泰證券, 311 筆)")
    a("")
    a("## 方法說明")
    a("")
    a("- **只用「現股 net = 0」完整配對 ticker**，跳過缺賣出紀錄的 5 檔")
    a("- 跳過: 3481 群創 / 2303 聯電 / 1721 三晃 / 8064 東捷 / 709966 金居")
    a("- Broker ticker 轉換: 711127 頎邦 → DB 6147")
    a("- 現股波段 FIFO 配對，當沖另計 (detector 不適用)")
    a("- 4+2 detector: 掀傘(日K) / 高檔長黑 / 分批 10%/20%/30% / 急殺跳空")
    a("")

    swing_results = [r for r in results if not r.get("skip_reason")]
    n_swing = len(swing_results)
    n_day   = len(day_trips)

    a("## 真實 P&L 統計")
    a("")
    a(f"| 類型 | 筆數 | P&L |")
    a(f"|------|------|-----|")
    a(f"| 波段 | {n_swing} | ${total_long_pnl:+,.0f} |")
    a(f"| 當沖 | {n_day} | ${total_day_pnl:+,.0f} |")
    a(f"| **合計** | **{n_swing + n_day}** | **${total_long_pnl + total_day_pnl:+,.0f}** |")
    a("")

    # 勝率
    all_trips = swing_results + day_trips
    win  = [r for r in all_trips if r["actual_pnl"] > 0]
    lose = [r for r in all_trips if r["actual_pnl"] < 0]
    a(f"勝率: {len(win)}/{len(all_trips)} = {len(win)/len(all_trips)*100:.1f}%")
    a("")

    # 各 ticker P&L
    a("### 各 Ticker P&L")
    a("")
    a(f"| Ticker | 名稱 | 類型 | P&L |")
    a(f"|--------|------|------|-----|")
    by_ticker: dict[str, dict] = {}
    for r in all_trips:
        tk = r["ticker"]
        if tk not in by_ticker:
            by_ticker[tk] = {"name": r["name"], "pnl": 0, "types": set()}
        by_ticker[tk]["pnl"] += r["actual_pnl"]
        by_ticker[tk]["types"].add(r["trade_type"])
    for tk, info in sorted(by_ticker.items(), key=lambda x: x[1]["pnl"]):
        a(f"| {tk} | {info['name']} | {'/'.join(info['types'])} | ${info['pnl']:+,.0f} |")
    a("")

    # Detector 統計表
    a("## Detector 觸發統計")
    a("")
    a("(波段 round-trips 分析，當沖不計)")
    a("")
    a(f"| Detector | 觸發 | 觸發率 | 平均 Δpnl | 中位數 | 最佳 | 最差 |")
    a(f"|----------|------|--------|-----------|--------|------|------|")
    det_display = {
        "掀傘":    "🌂 掀傘 (日K)",
        "高檔長黑": "🦘 高檔長黑",
        "分批_10%": "💰 分批 +10%",
        "分批_20%": "💰 分批 +20%",
        "分批_30%": "💰 分批 +30%",
        "急殺":    "📉 急殺跳空",
    }
    for key, label in det_display.items():
        s = stats.get(key, {})
        tn = s.get("trigger_n", 0)
        tp = s.get("trigger_pct", 0)
        avg = s.get("avg_delta")
        med = s.get("median_delta")
        best = s.get("best_delta")
        worst = s.get("worst_delta")
        a(f"| {label} | {tn}/{n_swing} | {tp:.0f}% | "
          f"{fmt_delta(avg)} | {fmt_delta(med)} | {fmt_delta(best)} | {fmt_delta(worst)} |")
    a("")

    # Top 案例
    a("## 真實有救 Case — Top 5")
    a("")
    for key, label in det_display.items():
        top = top_cases(swing_results, key, top_n=5)
        if not top:
            continue
        a(f"### {label}")
        a("")
        for delta, r, d in top:
            hold_days = 0
            try:
                from datetime import date
                ed = date.fromisoformat(r["exit_date"])
                sd = date.fromisoformat(r["entry_date"])
                hold_days = (ed - sd).days
            except Exception:
                pass

            a(f"- **{r['name']} ({r['ticker']})** {r['entry_date']} → {r['exit_date']}"
              f" (+{hold_days}天)")
            a(f"  - 進 @ ${r['entry_price']:.2f} × {r['shares']:,} 張 → 實際出 @ ${r['exit_price']:.2f}")
            a(f"  - 實際 PNL: {fmt_pnl(r['actual_pnl'])}")
            a(f"  - {key} 觸發: {d['date']} @ ${d.get('price', d.get('price', 0)):.2f}")
            det_pnl_key = "pnl" if "pnl" in d else "pnl_partial"
            a(f"  - Detector PNL: {fmt_pnl(d.get(det_pnl_key))}")
            a(f"  - **Δ = {fmt_delta(delta)}** {'✅ 救到' if delta > 0 else '❌ 反而差'}")
            a(f"  - 原因: {d['reason']}")
            a("")
        a("")

    # 完整 trade 明細
    a("## 完整 Wave 明細")
    a("")
    a("| 名稱 | Ticker | 進場日 | 出場日 | 進 | 出 | 張數 | 實際PNL | 掀傘 | 高檔長黑 | 分批10% | 分批20% | 急殺 |")
    a("|------|--------|--------|--------|-----|-----|------|---------|------|----------|---------|---------|------|")
    for r in sorted(swing_results, key=lambda x: x["entry_date"]):
        dets = r.get("detectors", {})

        def det_cell(key):
            d = dets.get(key)
            if not d:
                return "—"
            return f"{d['date']} {fmt_delta(d.get('delta'))}"

        a(f"| {r['name']} | {r['ticker']} | {r['entry_date']} | {r['exit_date']} "
          f"| {r['entry_price']:.1f} | {r['exit_price']:.1f} | {r['shares']:,} "
          f"| {fmt_pnl(r['actual_pnl'])} "
          f"| {det_cell('掀傘')} "
          f"| {det_cell('高檔長黑')} "
          f"| {det_cell('分批_10%')} "
          f"| {det_cell('分批_20%')} "
          f"| {det_cell('急殺')} |")
    a("")

    # User 行為模式
    a("## User 出場行為模式分析")
    a("")
    # 計算有無 早出 / 晚出
    early_exit = []  # 掀傘 detector 在實際出場前觸發 = 應早出
    late_exit  = []  # 高檔長黑在實際出場前觸發 = 太晚出
    no_partial = []  # 分批 20%+ 觸發但 user 沒分批
    gap_risk   = []  # 急殺觸發 = 有過夜風險

    for r in swing_results:
        dets = r.get("detectors", {})
        actual_exit = r["exit_date"]

        umb = dets.get("掀傘")
        if umb and umb["date"] < actual_exit and umb.get("delta", 0) > 0:
            early_exit.append(r)

        hlb = dets.get("高檔長黑")
        if hlb and hlb["date"] < actual_exit and hlb.get("delta", 0) > 0:
            late_exit.append(r)

        m20 = dets.get("分批_20%")
        if m20 and m20["date"] < actual_exit:
            no_partial.append(r)

        gap = dets.get("急殺")
        if gap:
            gap_risk.append(r)

    a(f"### 出場過早 (掀傘早觸發、delta > 0)")
    a(f"- 共 {len(early_exit)} 筆，佔波段 {len(early_exit)/n_swing*100:.0f}%")
    for r in early_exit[:5]:
        a(f"  - {r['name']} {r['entry_date']}→{r['exit_date']} "
          f"| 掀傘 {r['detectors']['掀傘']['date']} "
          f"| delta {fmt_delta(r['detectors']['掀傘'].get('delta'))}")
    a("")

    a(f"### 出場過晚 (高檔長黑先觸發、delta > 0)")
    a(f"- 共 {len(late_exit)} 筆，佔波段 {len(late_exit)/n_swing*100:.0f}%")
    for r in late_exit[:5]:
        a(f"  - {r['name']} {r['entry_date']}→{r['exit_date']} "
          f"| 高檔長黑 {r['detectors']['高檔長黑']['date']} "
          f"| delta {fmt_delta(r['detectors']['高檔長黑'].get('delta'))}")
    a("")

    a(f"### 未分批停利 (+20% 觸發)")
    a(f"- 共 {len(no_partial)} 筆，佔波段 {len(no_partial)/n_swing*100:.0f}%")
    for r in no_partial[:5]:
        m20 = r["detectors"]["分批_20%"]
        a(f"  - {r['name']} {r['entry_date']}→{r['exit_date']} "
          f"| +20% 達標 {m20['date']} @ {m20['price']:.2f} "
          f"| delta {fmt_delta(m20.get('delta'))}")
    a("")

    a(f"### 急殺風險 (有過跳空 -3%+ 的持倉)")
    a(f"- 共 {len(gap_risk)} 筆")
    for r in gap_risk[:5]:
        gap = r["detectors"]["急殺"]
        a(f"  - {r['name']} {gap['date']} 跳空 {gap.get('gap_pct', 0)*100:.1f}% "
          f"| delta {fmt_delta(gap.get('delta'))}")
    a("")

    # 行為總結
    a("### 行為模式總結")
    a("")
    if len(no_partial) > n_swing * 0.4:
        a("- ⚠️ **最顯著問題: 未分批停利** — 超過 40% 的波段有 +20% 機會但未鎖利")
    if len(late_exit) > len(early_exit):
        a("- ⚠️ **出場偏晚** — 高檔長黑觸發較掀傘多，user 傾向抱太久")
    elif len(early_exit) > len(late_exit):
        a("- ⚠️ **出場偏早** — 掀傘觸發後 delta 正，代表還有空間但已出")
    if len(gap_risk) > n_swing * 0.3:
        a("- ⚠️ **過夜跳空風險高** — 逾 30% 持倉有急殺事件")

    a("")
    a("## 現有持倉建議")
    a("")
    a("(依目前持倉 1605/2885/6285/8046/3481 分析，需即時價格)")
    a("")
    a("| Ticker | 名稱 | 狀態 | 建議 |")
    a("|--------|------|------|------|")
    a("| 1605 | 華新 | 持倉中 | 監控 MA5 + 掀傘條件 |")
    a("| 2885 | 元大金 | 持倉中 | 波段持有，+10% 考慮分批 |")
    a("| 6285 | 啟碁 | 持倉中 | 急殺注意 (6/2 當沖已確認) |")
    a("| 8046 | 南電 | 持倉中 | 新倉，結構底停損 |")
    a("| 3481 | 群創 | 缺賣出紀錄 | 無法 backtest，需人工核對 |")
    a("")

    a("---")
    a("")
    a(f"*生成時間: 2026-06-04*")
    a(f"*Script: scripts/zhuli/phase4_v4_clean_round_trips.py*")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def run(verbose: bool = False) -> None:
    sep = "=" * 100
    print(sep)
    print("  Phase 4 v4 — Clean Round-Trip Detector Backtest")
    print(f"  分析區間: {ANALYSIS_START} ~ 2026-06-04")
    print(f"  DB: {_DB}")
    print(sep)
    print()

    # ── 載入資料 ────────────────────────────────────────────────────────────
    broker_trades = load_broker_trades()
    print(f"✅ 載入 broker_statement: {len(broker_trades)} 筆")

    long_trips = extract_closed_long_trips(broker_trades)
    day_trips  = extract_closed_day_trips(broker_trades)
    print(f"   Clean round-trips: 波段 {len(long_trips)} 筆 + 當沖 {len(day_trips)} 筆")

    # ── P&L 統計 ────────────────────────────────────────────────────────────
    total_long_pnl = sum(t["actual_pnl"] for t in long_trips)
    total_day_pnl  = sum(t["actual_pnl"] for t in day_trips)
    total_pnl      = total_long_pnl + total_day_pnl
    all_trips      = long_trips + day_trips
    win   = [t for t in all_trips if t["actual_pnl"] > 0]
    lose  = [t for t in all_trips if t["actual_pnl"] < 0]

    print()
    print("─" * 60)
    print("真實 P&L (Clean Round-Trips)")
    print("─" * 60)
    print(f"  波段 P&L:  ${total_long_pnl:>+,.0f}")
    print(f"  當沖 P&L:  ${total_day_pnl:>+,.0f}")
    print(f"  合計 P&L:  ${total_pnl:>+,.0f}")
    print(f"  勝率:      {len(win)}/{len(all_trips)} = {len(win)/len(all_trips)*100:.1f}%")
    print()

    # ── Ticker P&L ─────────────────────────────────────────────────────────
    by_tkr: dict[str, float] = defaultdict(float)
    tkr_name: dict[str, str] = {}
    for t in all_trips:
        by_tkr[t["ticker"]] += t["actual_pnl"]
        tkr_name[t["ticker"]] = t["name"]
    print(f"{'Ticker':<8}  {'名稱':<12}  {'P&L':>12}")
    print("-" * 38)
    for tk, pnl in sorted(by_tkr.items(), key=lambda x: x[1]):
        print(f"{tk:<8}  {tkr_name.get(tk,'?'):<12}  ${pnl:>+12,.0f}")
    print()

    # ── 跑 Detector ─────────────────────────────────────────────────────────
    print("─" * 100)
    print("Detector Backtest (波段 round-trips)")
    print("─" * 100)
    results: list[dict] = []
    for trip in sorted(long_trips, key=lambda x: x["entry_date"]):
        if verbose:
            print(f"  [{trip['name']}] {trip['entry_date']} → {trip['exit_date']}"
                  f"  進@{trip['entry_price']:.1f} 出@{trip['exit_price']:.1f}")
        r = simulate_trip(trip, verbose=verbose)
        results.append(r)

    # 輸出明細
    hdr = (f"{'名稱':<8}{'Ticker':<7}{'進場日':<12}{'出場日':<12}"
           f"{'進@':>7}{'出@':>7}{'張':>6}{'實際PNL':>10}  "
           f"{'掀傘':>12}{'高檔長黑':>12}{'分批10%':>12}{'分批20%':>12}{'急殺':>10}")
    print(hdr)
    print("-" * 105)
    for r in results:
        if r.get("skip_reason"):
            print(f"  [{r['name']}] SKIP: {r['skip_reason']}")
            continue
        dets = r.get("detectors", {})

        def dc(key):
            d = dets.get(key)
            if not d:
                return "未觸發"
            delta = d.get("delta")
            arrow = "↑" if (delta is not None and delta > 0) else ("↓" if (delta is not None and delta < 0) else "=")
            return f"{d['date']} {arrow}{abs(delta or 0):,.0f}"

        print(f"{r['name']:<8}{r['ticker']:<7}{r['entry_date']:<12}{r['exit_date']:<12}"
              f"{r['entry_price']:>7.1f}{r['exit_price']:>7.1f}{r['shares']:>6,}"
              f"{r['actual_pnl']:>10,.0f}  "
              f"{dc('掀傘'):>12}{dc('高檔長黑'):>12}{dc('分批_10%'):>12}{dc('分批_20%'):>12}{dc('急殺'):>10}")

    # ── Detector 統計 ────────────────────────────────────────────────────────
    stats = build_detector_stats(results)
    print()
    print("═" * 90)
    print("Detector 效果彙整")
    print("═" * 90)
    print(f"{'Detector':<18}{'觸發':>6}{'觸發率':>8}{'平均Δ':>12}{'中位數Δ':>12}{'最佳Δ':>12}{'最差Δ':>12}")
    print("-" * 80)
    det_labels = {
        "掀傘":    "🌂 掀傘(日K)",
        "高檔長黑": "🦘 高檔長黑",
        "分批_10%": "💰 分批+10%",
        "分批_20%": "💰 分批+20%",
        "分批_30%": "💰 分批+30%",
        "急殺":    "📉 急殺跳空",
    }
    n_swing = len([r for r in results if not r.get("skip_reason")])
    for key, label in det_labels.items():
        s = stats.get(key, {})
        tn = s.get("trigger_n", 0)
        tp = s.get("trigger_pct", 0)
        avg_d   = s.get("avg_delta")
        med_d   = s.get("median_delta")
        best_d  = s.get("best_delta")
        worst_d = s.get("worst_delta")

        def fd(v):
            if v is None: return "—"
            a = "↑" if v > 0 else ("↓" if v < 0 else "=")
            return f"{a}{abs(v):,.0f}"

        print(f"{label:<18}{tn:>3}/{n_swing:<3}{tp:>7.0f}%"
              f"{fd(avg_d):>12}{fd(med_d):>12}{fd(best_d):>12}{fd(worst_d):>12}")

    # ── Top 有救 case ───────────────────────────────────────────────────────
    print()
    print("═" * 70)
    print("具體有救 Case (delta > 0 前 3)")
    print("═" * 70)
    for key, label in det_labels.items():
        top = top_cases([r for r in results if not r.get("skip_reason")], key, top_n=3)
        if not top:
            continue
        print(f"\n{label}:")
        for delta, r, d in top:
            if delta <= 0:
                continue
            arrow = "↑"
            print(f"  {r['name']} {r['entry_date']}→{r['exit_date']} | "
                  f"實際 ${r['actual_pnl']:+,.0f} | "
                  f"Detector {d['date']} @ {d.get('price', 0):.2f} | "
                  f"Δ {arrow}{delta:,.0f} | {d['reason'][:60]}")

    # ── 行為模式 ────────────────────────────────────────────────────────────
    print()
    print("═" * 60)
    print("User 出場行為模式")
    print("═" * 60)
    swing_results = [r for r in results if not r.get("skip_reason")]
    n_sw = len(swing_results)

    # 各類計數
    cnt_too_early = sum(
        1 for r in swing_results
        if "掀傘" in r.get("detectors", {})
        and r["detectors"]["掀傘"].get("delta", 0) > 0
        and r["detectors"]["掀傘"]["date"] < r["exit_date"]
    )
    cnt_too_late = sum(
        1 for r in swing_results
        if "高檔長黑" in r.get("detectors", {})
        and r["detectors"]["高檔長黑"].get("delta", 0) > 0
        and r["detectors"]["高檔長黑"]["date"] < r["exit_date"]
    )
    cnt_no_partial = sum(
        1 for r in swing_results
        if "分批_20%" in r.get("detectors", {})
        and r["detectors"]["分批_20%"]["date"] < r["exit_date"]
    )
    cnt_gap = sum(1 for r in swing_results if "急殺" in r.get("detectors", {}))

    print(f"  波段筆數:         {n_sw}")
    print(f"  出場過早 (掀傘有效提示): {cnt_too_early} 筆 ({cnt_too_early/n_sw*100:.0f}%)")
    print(f"  出場過晚 (高檔長黑提示): {cnt_too_late} 筆 ({cnt_too_late/n_sw*100:.0f}%)")
    print(f"  未分批鎖利 (+20%機會):   {cnt_no_partial} 筆 ({cnt_no_partial/n_sw*100:.0f}%)")
    print(f"  急殺風險 (曾跳空-3%+):   {cnt_gap} 筆 ({cnt_gap/n_sw*100:.0f}%)")
    print()
    if cnt_no_partial > n_sw * 0.4:
        print("  ⚠️  主要問題: 未分批停利 — 超過 40% 波段有 +20% 機會未鎖")
    if cnt_too_late > cnt_too_early:
        print("  ⚠️  出場偏晚 > 出場偏早")
    elif cnt_too_early > cnt_too_late:
        print("  ⚠️  出場偏早 > 出場偏晚")

    # ── 儲存報告 ────────────────────────────────────────────────────────────
    print()
    report_path = _REPO / "docs" / "主力大課程" / "strategies" / "phase4_v4_clean_round_trips_5_19_to_6_3.md"
    # 確保目錄存在
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_text = generate_report(results, day_trips, stats, total_long_pnl, total_day_pnl)
    report_path.write_text(report_text, encoding="utf-8")
    print(f"✅ 報告已儲存: {report_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 4 v4 Clean Round-Trip Detector Backtest")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()
    run(verbose=args.verbose)


if __name__ == "__main__":
    main()
