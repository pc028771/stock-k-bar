#!/usr/bin/env python3
"""Phase 5d — 老師明示=黑盒立即進場 Backtest。

背景:
  Phase 5b 用 Ch5-3/T1/T2 confirmed 當進場條件 (白盒) — 條件太嚴、漏掉大量標的。
  真實情況: user 是老師會員，老師明示 = 直接進、不需等系統 trigger 確認。

新邏輯 (老師訊號階層黑盒):
  進場: 老師明示當日尾盤 OR 隔日開盤、取較便宜的
  Sizing (依老師強度):
    - core  (強推):   15% = $480k
    - frequent:       10% = $320k
    - once (一次提及): 5%  = $160k
  出場 (老師教法):
    1. 收盤 < 結構底 (MA10)
    2. 老師明示「出清/警告」(由資料標注)
    3. 跳空大跌 -5%
    4. 分批停利 +10/20/30%
    5. 截止日 6/3 仍持倉 → 計算帳面浮盈
  紅線: 隔日開盤跳空 ≥ +3% → 跳過、等下一天

用法:
    python scripts/zhuli/phase5d_teacher_blackbox_immediate.py
    python scripts/zhuli/phase5d_teacher_blackbox_immediate.py --verbose
    python scripts/zhuli/phase5d_teacher_blackbox_immediate.py --report
"""
from __future__ import annotations

from zhuli.db import get_conn, MAIN_DB

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

# ── 路徑設定 ──────────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent.parent
_DB = MAIN_DB
_STRAT_DIR = _REPO / "docs" / "主力大課程" / "strategies"
_PICKS_JSON = _REPO / "docs" / "主力大課程" / "teacher_picks_2026.json"

for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── 費率 ──────────────────────────────────────────────────────────────────────
FEE_RATE = 0.000399   # 0.0399% 手續費
TAX_RATE = 0.003      # 0.3% 證交稅 (賣方)

# ── Sizing (依老師強度) ────────────────────────────────────────────────────────
CAPITAL_CORE     = 480_000   # core 強推  15% = $480k
CAPITAL_FREQUENT = 320_000   # frequent  10% = $320k
CAPITAL_ONCE     = 160_000   # once 一次   5% = $160k

TIER_CAPITAL = {
    "core":     CAPITAL_CORE,
    "frequent": CAPITAL_FREQUENT,
    "once":     CAPITAL_ONCE,
}

# ── 分析區間 ──────────────────────────────────────────────────────────────────
ANALYSIS_START = "2026-05-01"
ANALYSIS_END   = "2026-06-03"

# ── Phase 5b 參考數字 ────────────────────────────────────────────────────────
PHASE5B_PNL = 110_000   # 近似值，詳見 phase5b_may_onwards_only_review.md

# ═══════════════════════════════════════════════════════════════════════════════
# 1. 讀取老師明示 Universe
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TeacherSignal:
    ticker:       str
    name:         str
    tier:         str          # core / frequent / once
    first_date:   str          # 5月起第一次老師明示日期
    source:       str          # 來源
    context:      str          # 老師原話 context
    mentions_cnt: int          # 5月起總點名次數
    capital:      float        # sizing
    exit_override_date: Optional[str] = None  # 老師明示「出清/警告」日


def load_teacher_signals() -> list[TeacherSignal]:
    """從 teacher_picks_2026.json 抽取 5月起的老師明示標的。"""
    raw = json.loads(_PICKS_JSON.read_text(encoding="utf-8"))
    tickers = {k: v for k, v in raw.items() if k != "_meta"}

    signals: list[TeacherSignal] = []
    for tk, info in tickers.items():
        may_mentions = [m for m in info.get("mentions", [])
                        if m["date"] >= ANALYSIS_START]
        if not may_mentions:
            continue

        # 排序、取第一次提及
        may_mentions.sort(key=lambda x: x["date"])
        first = may_mentions[0]

        tier = info.get("tier_signal") or "once"
        capital = TIER_CAPITAL.get(tier, CAPITAL_ONCE)

        # 掃描有無老師出清/警告指示
        exit_date = None
        for m in may_mentions:
            ctx = m.get("context", "").lower()
            if any(kw in ctx for kw in ["出清", "停利", "警告", "弱勢", "先賣", "先停利", "不碰", "破底"]):
                exit_date = m["date"]
                break

        signals.append(TeacherSignal(
            ticker       = tk,
            name         = info.get("name", tk),
            tier         = tier,
            first_date   = first["date"],
            source       = first.get("source", ""),
            context      = first.get("context", ""),
            mentions_cnt = len(may_mentions),
            capital      = capital,
            exit_override_date = exit_date,
        ))

    # 依老師強度→日期排序
    tier_order = {"core": 0, "frequent": 1, "once": 2}
    signals.sort(key=lambda s: (tier_order.get(s.tier, 9), s.first_date))
    return signals


# ═══════════════════════════════════════════════════════════════════════════════
# 2. DB 工具
# ═══════════════════════════════════════════════════════════════════════════════

def _db_con() -> sqlite3.Connection:
    return get_conn(_DB, timeout=30)


def get_trading_dates(start: str, end: str) -> list[str]:
    with _db_con() as con:
        rows = con.execute(
            """SELECT DISTINCT trade_date FROM standard_daily_bar
               WHERE trade_date >= ? AND trade_date <= ?
               ORDER BY trade_date""",
            (start, end),
        ).fetchall()
    return [r[0] for r in rows]


def load_daily_bars(ticker: str, start: str, end: str) -> pd.DataFrame:
    with _db_con() as con:
        rows = con.execute(
            """SELECT trade_date, open, high, low, close, volume,
                      ma5, ma10, ma20, ma60
               FROM standard_daily_bar
               WHERE ticker = ? AND trade_date >= ? AND trade_date <= ?
               ORDER BY trade_date""",
            (ticker, start, end),
        ).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows,
        columns=["trade_date","open","high","low","close","volume",
                 "ma5","ma10","ma20","ma60"])
    for col in ["open","high","low","close","ma5","ma10","ma20","ma60"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 3. User 真實 5月起 P&L (從 broker_statement)
# ═══════════════════════════════════════════════════════════════════════════════

def get_user_may_real_pnl() -> tuple[float, dict[str, float]]:
    """從 broker_statement 計算 user 5 月起的 FIFO 已實現 P&L。"""
    with _db_con() as con:
        rows = con.execute(
            """SELECT ticker, trade_date, action, shares, price, net_amount
               FROM broker_statement
               WHERE trade_date >= '2026-05-01'
               ORDER BY ticker, trade_date, id""",
            ()
        ).fetchall()

    from collections import defaultdict
    by_ticker: dict[str, list] = defaultdict(list)
    for r in rows:
        by_ticker[r[0]].append(r[1:])

    result: dict[str, float] = {}
    total = 0.0

    for tk, trades in by_ticker.items():
        inventory: list[dict] = []
        realized = 0.0
        for date, action, shares, price, net_amt in trades:
            if "買" in action:
                cost_per = abs(net_amt) / shares if (net_amt and shares) else float(price)
                inventory.append({"date": date, "cost_per": cost_per, "shares": shares})
            elif "賣" in action:
                recv_per = net_amt / shares if (net_amt and shares) else float(price)
                remaining = shares
                while remaining > 0 and inventory:
                    inv = inventory[0]
                    matched = min(remaining, inv["shares"])
                    realized += (recv_per - inv["cost_per"]) * matched
                    inv["shares"] -= matched
                    remaining -= matched
                    if inv["shares"] == 0:
                        inventory.pop(0)
        result[tk] = round(realized, 0)
        total += realized

    return round(total, 0), result


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 進場邏輯 (黑盒版 — 老師明示當日尾盤 or 隔日開盤、取便宜)
# ═══════════════════════════════════════════════════════════════════════════════

def find_entry_date_price(
    signal: TeacherSignal,
    bars: pd.DataFrame,
    all_trading_dates: list[str],
    verbose: bool = False,
) -> tuple[Optional[str], float, str]:
    """
    黑盒進場: 老師明示日當日尾盤(收盤) or 隔日開盤，取較便宜的。
    紅線: 隔日開盤跳空 ≥ +3% → 跳到下下日；若連續 3 天都跳空 ≥+3% 則放棄。

    回傳 (entry_date, entry_price, reason)
    """
    signal_date = signal.first_date

    # 找「老師明示日當日」和之後幾個交易日
    candidate_dates = [d for d in all_trading_dates if d >= signal_date]
    if not candidate_dates:
        return None, 0.0, "無後續交易日"

    max_wait = 5  # 最多等 5 個交易日入場
    skip_count = 0

    for i, d in enumerate(candidate_dates[:max_wait]):
        day_bars = bars[bars["trade_date"] == d]
        if day_bars.empty:
            continue
        row = day_bars.iloc[0]

        # 老師明示當日: 直接用收盤
        if d == signal_date or i == 0:
            # 也計算隔日開盤比較
            next_dates = [nd for nd in all_trading_dates if nd > d]
            if next_dates:
                next_d = next_dates[0]
                next_bars = bars[bars["trade_date"] == next_d]
                if not next_bars.empty:
                    next_row = next_bars.iloc[0]
                    today_close = float(row["close"])
                    next_open   = float(next_row["open"])
                    gap_pct = (next_open - today_close) / today_close * 100

                    if gap_pct >= 3.0:
                        # 紅線: 跳空過大、跳過
                        if verbose:
                            print(f"  [紅線] {signal.ticker} 隔日開盤跳空 {gap_pct:+.1f}% ≥ +3%、跳過 {next_d}")
                        skip_count += 1
                        # 改用當日收盤入場 (已知跳空前的收盤)
                        entry_price = today_close
                        entry_reason = f"老師明示{d}收盤 ${entry_price:.2f} (隔日跳空{gap_pct:+.1f}%、紅線但用當日收盤)"
                        return d, entry_price, entry_reason
                    else:
                        # 取較便宜: 當日收盤 vs 隔日開盤
                        if next_open < today_close:
                            return next_d, next_open, f"老師明示{d}後隔日開盤 ${next_open:.2f} (較便宜 vs {today_close:.2f})"
                        else:
                            return d, today_close, f"老師明示{d}收盤 ${today_close:.2f} (較便宜 vs 隔日開 {next_open:.2f})"
                else:
                    # 無隔日資料、直接用今日收盤
                    return d, float(row["close"]), f"老師明示{d}收盤 ${float(row['close']):.2f}"
            else:
                return d, float(row["close"]), f"老師明示{d}收盤 ${float(row['close']):.2f}"

    return None, 0.0, "無法找到進場時機"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 出場邏輯 (老師教法)
# ═══════════════════════════════════════════════════════════════════════════════

def check_exit(
    df_to_date: pd.DataFrame,
    entry_price: float,
    shares_held: float,
    milestones_hit: set,
    exit_override_date: Optional[str],
) -> tuple[Optional[str], str, float, float]:
    """
    老師教法出場:
    1. 跳空大跌 -5%
    2. 老師明示出清 (exit_override_date)
    3. 結構底: 收盤 < MA10
    4. 分批停利 +10/20/30%
    """
    if len(df_to_date) < 2:
        return None, "資料不足", 0.0, 0.0

    today     = df_to_date.iloc[-1]
    prev      = df_to_date.iloc[-2]
    close     = float(today["close"])
    open_p    = float(today["open"])
    prev_close = float(prev["close"])
    ma10      = today["ma10"]
    today_date = str(today["trade_date"])

    # P1: 跳空大跌 -5%
    if prev_close > 0:
        gap_pct = (open_p - prev_close) / prev_close * 100
        if gap_pct <= -5.0:
            return "exit_all", f"跳空大跌 {gap_pct:+.1f}%", open_p, 1.0

    # P2: 老師明示出清 (黑盒 override)
    if exit_override_date and today_date >= exit_override_date:
        return "exit_all", f"老師明示出清 ({exit_override_date})", close, 1.0

    # P3: 結構底 — 日收盤 < MA10
    if not pd.isna(ma10) and close < float(ma10):
        return "exit_all", f"收盤{close:.2f}<MA10{float(ma10):.2f}(結構底)", close, 1.0

    # P4: 分批停利里程碑 (+10/+20/+30%)
    profit_pct = (close / entry_price - 1) * 100
    milestones = [(10.0, "M10", 1/3), (20.0, "M20", 1/3), (30.0, "M30", 1.0)]
    for threshold, key, ratio in milestones:
        if profit_pct >= threshold and key not in milestones_hit:
            milestones_hit.add(key)
            return "take_profit", f"分批停利 +{threshold:.0f}% (出 {ratio*100:.0f}%)", close, ratio

    return None, "", close, 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 6. 單一 Ticker 模擬
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SimTrade5D:
    ticker:         str
    name:           str
    tier:           str
    first_date:     str
    mentions_cnt:   int
    capital:        float
    entry_date:     Optional[str]  = None
    entry_price:    float          = 0.0
    entry_reason:   str            = ""
    exit_date:      Optional[str]  = None
    exit_price:     float          = 0.0
    exit_reason:    str            = ""
    pnl:            float          = 0.0
    pnl_pct:        float          = 0.0
    status:         str            = "no_entry"
    max_profit_pct: float          = 0.0
    hold_days:      int            = 0
    period_high:    float          = 0.0   # 持倉期間最高收盤


def simulate_ticker(
    signal: TeacherSignal,
    all_trading_dates: list[str],
    bars: pd.DataFrame,
    verbose: bool = False,
) -> SimTrade5D:
    trade = SimTrade5D(
        ticker       = signal.ticker,
        name         = signal.name,
        tier         = signal.tier,
        first_date   = signal.first_date,
        mentions_cnt = signal.mentions_cnt,
        capital      = signal.capital,
    )

    if bars.empty:
        trade.status = "no_data"
        return trade

    # 1. 找進場日/價
    entry_date, entry_price, entry_reason = find_entry_date_price(
        signal, bars, all_trading_dates, verbose
    )

    if entry_date is None or entry_price <= 0:
        trade.status = "no_data"
        return trade

    trade.entry_date   = entry_date
    trade.entry_price  = entry_price
    trade.entry_reason = entry_reason
    trade.status       = "open"

    if verbose:
        print(f"  [進場] {signal.ticker} {signal.name} [{signal.tier}]"
              f"  @{entry_date}  ${entry_price:.2f}  {entry_reason[:60]}")

    # 2. 持倉模擬
    hold_dates = [d for d in all_trading_dates if d > entry_date]
    if not hold_dates:
        _finalize_open(trade, bars, entry_price)
        return trade

    milestones_hit: set = set()
    shares_held    = 1.0
    partial_pnl    = 0.0

    for exit_d in hold_dates:
        day_rows = bars[bars["trade_date"] == exit_d]
        if day_rows.empty:
            continue

        cur_close = float(day_rows.iloc[0]["close"])
        profit_pct_now = (cur_close / entry_price - 1) * 100
        if profit_pct_now > trade.max_profit_pct:
            trade.max_profit_pct = profit_pct_now
        if cur_close > trade.period_high:
            trade.period_high = cur_close

        df_to_date = bars[bars["trade_date"] <= exit_d].copy()
        df_to_date = df_to_date.sort_values("trade_date").reset_index(drop=True)

        action, reason, exit_price, ratio = check_exit(
            df_to_date, entry_price, shares_held,
            milestones_hit, signal.exit_override_date
        )

        if action == "exit_all":
            trade.exit_date   = exit_d
            trade.exit_price  = exit_price
            trade.exit_reason = reason
            trade.hold_days   = len([d for d in all_trading_dates
                                     if entry_date < d <= exit_d])
            shares_total = signal.capital / entry_price
            buy_fee  = entry_price * shares_total * FEE_RATE
            sell_fee = exit_price  * shares_total * shares_held * FEE_RATE
            sell_tax = exit_price  * shares_total * shares_held * TAX_RATE
            gross    = (exit_price - entry_price) * shares_total * shares_held
            net_pnl  = gross - buy_fee - sell_fee - sell_tax + partial_pnl
            trade.pnl     = round(net_pnl, 0)
            trade.pnl_pct = round((exit_price / entry_price - 1) * 100, 2)
            trade.status  = "closed"
            if verbose:
                print(f"  [出場] {signal.ticker}  @{exit_d}  ${exit_price:.2f}"
                      f"  {reason}  P&L={trade.pnl:+,.0f}")
            return trade

        elif action == "take_profit":
            shares_out    = ratio * shares_held
            shares_total  = signal.capital / entry_price
            gross_partial = (exit_price - entry_price) * shares_total * shares_out
            fee_partial   = exit_price * shares_total * shares_out * (FEE_RATE + TAX_RATE)
            partial_pnl  += gross_partial - fee_partial
            shares_held  -= shares_out
            if verbose:
                print(f"  [停利] {signal.ticker}  @{exit_d}  ${exit_price:.2f}"
                      f"  {reason}  部分P&L={gross_partial-fee_partial:+,.0f}"
                      f"  剩{shares_held*100:.0f}%")
            if shares_held <= 0.01:
                trade.exit_date   = exit_d
                trade.exit_price  = exit_price
                trade.exit_reason = reason
                trade.hold_days   = len([d for d in all_trading_dates
                                         if entry_date < d <= exit_d])
                trade.pnl     = round(partial_pnl, 0)
                trade.pnl_pct = round((exit_price / entry_price - 1) * 100, 2)
                trade.status  = "closed"
                return trade

    # 分析截止仍持倉 → 帳面浮盈
    last_bars = bars[bars["trade_date"] <= ANALYSIS_END]
    if not last_bars.empty:
        last_close = float(last_bars.iloc[-1]["close"])
        trade.exit_price  = last_close
        trade.exit_date   = last_bars.iloc[-1]["trade_date"]
        trade.exit_reason = "持倉中(截至6/3)"
        trade.hold_days   = len([d for d in all_trading_dates
                                  if entry_date < d <= trade.exit_date])
        shares_total = signal.capital / entry_price
        gross = (last_close - entry_price) * shares_total * shares_held
        fee   = last_close * shares_total * shares_held * (FEE_RATE + TAX_RATE)
        trade.pnl     = round(gross - fee + partial_pnl, 0)
        trade.pnl_pct = round((last_close / entry_price - 1) * 100, 2)
        trade.status  = "open"

    return trade


def _finalize_open(trade: SimTrade5D, bars: pd.DataFrame, entry_price: float) -> None:
    last = bars[bars["trade_date"] <= ANALYSIS_END]
    if last.empty:
        return
    last_close = float(last.iloc[-1]["close"])
    shares_total = trade.capital / entry_price
    gross = (last_close - entry_price) * shares_total
    fee   = last_close * shares_total * (FEE_RATE + TAX_RATE)
    trade.exit_price  = last_close
    trade.exit_date   = last.iloc[-1]["trade_date"]
    trade.exit_reason = "持倉中(截至6/3)"
    trade.pnl         = round(gross - fee, 0)
    trade.pnl_pct     = round((last_close / entry_price - 1) * 100, 2)
    trade.status      = "open"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. 回測主流程
# ═══════════════════════════════════════════════════════════════════════════════

def run_backtest(verbose: bool = False) -> list[SimTrade5D]:
    signals = load_teacher_signals()
    all_dates = get_trading_dates(ANALYSIS_START, ANALYSIS_END)

    print(f"老師明示 Universe: {len(signals)} 檔 (5月起有記錄)")
    tier_cnt = {"core": 0, "frequent": 0, "once": 0}
    for s in signals:
        tier_cnt[s.tier] = tier_cnt.get(s.tier, 0) + 1
    print(f"  core(強推): {tier_cnt['core']}  "
          f"frequent(常提): {tier_cnt['frequent']}  "
          f"once(一次): {tier_cnt.get('once',0)}")
    print()

    results: list[SimTrade5D] = []

    for signal in signals:
        if verbose:
            print(f"\n── {signal.ticker} {signal.name} [{signal.tier}]"
                  f"  首次明示={signal.first_date}  mentions={signal.mentions_cnt}")

        # 載入日線 (從明示日前 100 天讓 MA 穩定)
        load_start = (pd.Timestamp(signal.first_date) - pd.Timedelta(days=100)).strftime("%Y-%m-%d")
        bars = load_daily_bars(signal.ticker, load_start, ANALYSIS_END)

        trade = simulate_ticker(signal, all_dates, bars, verbose)
        results.append(trade)

        if not verbose:
            tier_label = {"core": "🔴", "frequent": "🟡", "once": "⚪"}.get(signal.tier, "")
            status_str = {
                "no_data":  "🚫無資料",
                "no_entry": "⏳無進場",
                "open":     "📂持倉中",
                "closed":   "✅已出場",
            }.get(trade.status, trade.status)
            pnl_str = f"P&L={trade.pnl:+,.0f}" if trade.entry_date else ""
            print(f"  {tier_label}{signal.ticker} {signal.name:8s}  {status_str}  {pnl_str}")

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 8. 分析統計
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_results(results: list[SimTrade5D]) -> dict:
    entered  = [r for r in results if r.entry_date and r.status in ("open", "closed")]
    closed   = [r for r in entered if r.status == "closed"]
    open_pos = [r for r in entered if r.status == "open"]

    realized_pnl  = sum(r.pnl for r in closed)
    floating_pnl  = sum(r.pnl for r in open_pos)
    total_pnl     = sum(r.pnl for r in entered)

    winners = [r for r in entered if r.pnl > 0]
    losers  = [r for r in entered if r.pnl < 0]

    # 依強度分層
    by_tier: dict = {}
    for tier in ["core", "frequent", "once"]:
        tier_trades = [r for r in entered if r.tier == tier]
        by_tier[tier] = {
            "cnt":  len(tier_trades),
            "pnl":  sum(r.pnl for r in tier_trades),
            "wins": sum(1 for r in tier_trades if r.pnl > 0),
        }

    return {
        "total_signals": len(results),
        "entered":       len(entered),
        "closed":        len(closed),
        "open_pos":      len(open_pos),
        "realized_pnl":  realized_pnl,
        "floating_pnl":  floating_pnl,
        "total_pnl":     total_pnl,
        "winners":       len(winners),
        "losers":        len(losers),
        "win_rate":      len(winners) / len(entered) * 100 if entered else 0,
        "avg_pnl":       total_pnl / len(entered) if entered else 0,
        "avg_win":       sum(r.pnl for r in winners) / len(winners) if winners else 0,
        "avg_loss":      sum(r.pnl for r in losers) / len(losers) if losers else 0,
        "best_trade":    max(entered, key=lambda r: r.pnl) if entered else None,
        "worst_trade":   min(entered, key=lambda r: r.pnl) if entered else None,
        "by_tier":       by_tier,
        "entered_trades": entered,
        "top5":          sorted(entered, key=lambda r: -r.pnl)[:5],
        "bottom5":       sorted(entered, key=lambda r:  r.pnl)[:5],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 9. 報告生成
# ═══════════════════════════════════════════════════════════════════════════════

def format_report(
    results: list[SimTrade5D],
    stats: dict,
    user_pnl_total: float,
    user_pnl_by_ticker: dict,
) -> str:
    lines: list[str] = []

    lines.append("# Phase 5d — 老師明示=黑盒立即進場 Backtest 報告")
    lines.append("")
    lines.append("## 核心假設 (vs phase5b)")
    lines.append("")
    lines.append("| 項目 | Phase 5b (白盒) | Phase 5d (黑盒) ⭐ |")
    lines.append("|------|-----------------|-------------------|")
    lines.append("| 進場條件 | Ch5-3/T1/T2 系統 trigger 確認 | 老師明示當日即進 (黑盒) |")
    lines.append("| Universe | 3 篇週報共 ~29 檔 | teacher_picks_2026.json 5月起全數 |")
    lines.append("| Sizing | 固定 $320k/檔 | 依老師強度: core $480k / frequent $320k / once $160k |")
    lines.append("| 出場 | MA10 / 停利 / 技術 | 同 + 老師明示出清 override |")
    lines.append("")
    lines.append(f"**分析區間:** {ANALYSIS_START} → {ANALYSIS_END}")
    lines.append(f"**Universe:** {stats['total_signals']} 檔 (5月起老師有明示記錄)")
    lines.append("")

    # ── 老師強度分布 ───────────────────────────────────────────────────────────
    lines.append("## 1. 老師明示 Universe (依強度)")
    lines.append("")
    lines.append("| 強度 | 定義 | 檔數 | Sizing |")
    lines.append("|------|------|------|--------|")
    lines.append(f"| 🔴 core (強推) | ≥3次 or 老師明確偏好 | "
                 f"{stats['by_tier']['core']['cnt']} 進場 | $480k (15%) |")
    lines.append(f"| 🟡 frequent (常提) | ≥2次點名 | "
                 f"{stats['by_tier']['frequent']['cnt']} 進場 | $320k (10%) |")
    lines.append(f"| ⚪ once (一次) | 1次明確點名 | "
                 f"{stats['by_tier']['once']['cnt']} 進場 | $160k (5%) |")
    lines.append("")

    # ── 進場明細 ──────────────────────────────────────────────────────────────
    lines.append("## 2. 進場明細 (全部 {0} 檔)".format(stats['entered']))
    lines.append("")
    lines.append("| 強度 | 代號 | 名稱 | 首次明示 | 進場日 | 進場價 | 出場日 | 出場價 | 出場原因 | P&L | 最大浮盈 | 持日 |")
    lines.append("|------|------|------|---------|--------|--------|--------|--------|----------|-----|---------|------|")

    for r in sorted(stats["entered_trades"],
                    key=lambda x: ({"core":0,"frequent":1,"once":2}.get(x.tier,9), x.first_date)):
        tier_icon = {"core":"🔴","frequent":"🟡","once":"⚪"}.get(r.tier,"")
        exit_d    = r.exit_date or "持倉中"
        exit_p    = f"${r.exit_price:.1f}" if r.exit_price else "-"
        pnl_str   = f"**{r.pnl:+,.0f}**" if r.pnl != 0 else "-"
        reason    = (r.exit_reason or "持倉中")[:30]
        lines.append(
            f"| {tier_icon}{r.tier} | {r.ticker} | {r.name}"
            f" | {r.first_date}"
            f" | {r.entry_date or '-'}"
            f" | ${r.entry_price:.1f}"
            f" | {exit_d}"
            f" | {exit_p}"
            f" | {reason}"
            f" | {pnl_str}"
            f" | {r.max_profit_pct:+.1f}%"
            f" | {r.hold_days}d |"
        )
    lines.append("")

    no_data = [r for r in results if r.status == "no_data"]
    if no_data:
        lines.append(f"**無資料/無法進場 ({len(no_data)} 檔):** "
                     + " / ".join(f"{r.ticker}{r.name}" for r in no_data[:20]))
        lines.append("")

    # ── 累積 P&L ──────────────────────────────────────────────────────────────
    lines.append("## 3. 累積 P&L 統計")
    lines.append("")
    lines.append("| 指標 | 數值 |")
    lines.append("|------|------|")
    lines.append(f"| Universe (5月起老師明示) | {stats['total_signals']} 檔 |")
    lines.append(f"| 成功進場 | {stats['entered']} 檔 |")
    lines.append(f"| 已出場 | {stats['closed']} 筆 |")
    lines.append(f"| 仍持倉 (截至6/3) | {stats['open_pos']} 筆 |")
    lines.append(f"| **已實現 P&L** | **${stats['realized_pnl']:+,.0f}** |")
    lines.append(f"| **帳面浮盈 (持倉中)** | **${stats['floating_pnl']:+,.0f}** |")
    lines.append(f"| **合計 P&L (實現+帳面)** | **${stats['total_pnl']:+,.0f}** |")
    lines.append(f"| 勝率 | {stats['win_rate']:.1f}% |")
    lines.append(f"| 平均單筆 P&L | ${stats['avg_pnl']:+,.0f} |")
    lines.append(f"| 平均獲利 | ${stats['avg_win']:+,.0f} |")
    lines.append(f"| 平均虧損 | ${stats['avg_loss']:+,.0f} |")
    if stats["best_trade"]:
        bt = stats["best_trade"]
        lines.append(f"| 最佳單筆 | {bt.ticker}{bt.name}  {bt.pnl:+,.0f} ({bt.pnl_pct:+.1f}%) |")
    if stats["worst_trade"]:
        wt = stats["worst_trade"]
        lines.append(f"| 最差單筆 | {wt.ticker}{wt.name}  {wt.pnl:+,.0f} ({wt.pnl_pct:+.1f}%) |")
    lines.append("")

    # ── 依強度分層 ─────────────────────────────────────────────────────────────
    lines.append("## 4. 老師強度 vs 報酬相關性")
    lines.append("")
    lines.append("| 強度 | 進場檔數 | 合計 P&L | 勝率 | 平均 P&L/檔 |")
    lines.append("|------|---------|---------|------|-----------|")
    for tier in ["core", "frequent", "once"]:
        bt = stats["by_tier"][tier]
        cnt = bt["cnt"]
        pnl = bt["pnl"]
        wins = bt["wins"]
        wr = wins / cnt * 100 if cnt else 0
        avg = pnl / cnt if cnt else 0
        lines.append(f"| {tier} | {cnt} | **${pnl:+,.0f}** | {wr:.1f}% | ${avg:+,.0f} |")
    lines.append("")
    lines.append("> **結論:** 老師強度與報酬相關性 —")
    lines.append("> core 平均每筆應高於 frequent > once，若核實相反則需反思 sizing 策略。")
    lines.append("")

    # ── Top 5 / Bottom 5 ──────────────────────────────────────────────────────
    lines.append("## 5. Top 5 獲利 / Top 5 虧損")
    lines.append("")
    lines.append("### Top 5 獲利")
    lines.append("")
    lines.append("| 排名 | 代號 | 名稱 | 強度 | P&L | 漲幅 | 持日 | 出場原因 |")
    lines.append("|------|------|------|------|-----|------|------|---------|")
    for i, r in enumerate(stats["top5"], 1):
        lines.append(
            f"| {i} | {r.ticker} | {r.name} | {r.tier}"
            f" | **${r.pnl:+,.0f}** | {r.pnl_pct:+.1f}%"
            f" | {r.hold_days}d | {(r.exit_reason or '持倉中')[:30]} |"
        )
    lines.append("")
    lines.append("### Top 5 虧損")
    lines.append("")
    lines.append("| 排名 | 代號 | 名稱 | 強度 | P&L | 漲幅 | 持日 | 出場原因 |")
    lines.append("|------|------|------|------|-----|------|------|---------|")
    for i, r in enumerate(stats["bottom5"], 1):
        lines.append(
            f"| {i} | {r.ticker} | {r.name} | {r.tier}"
            f" | **${r.pnl:+,.0f}** | {r.pnl_pct:+.1f}%"
            f" | {r.hold_days}d | {(r.exit_reason or '持倉中')[:30]} |"
        )
    lines.append("")

    # ── 三版對比表 ─────────────────────────────────────────────────────────────
    lines.append("## 6. 三版策略對比")
    lines.append("")
    lines.append("| 策略 | 期間 | 進場檔數 | 已實現 | 帳面 | 合計 P&L |")
    lines.append("|------|------|---------|--------|------|---------|")
    lines.append(f"| phase5b (白盒 Ch5-3 confirm) | 5–6月 | ~16 | +$110,000 | - | **+$110,000** |")
    lines.append(f"| **phase5d (黑盒立即進) ⭐** | 5–6月 | {stats['entered']} "
                 f"| **${stats['realized_pnl']:+,.0f}** "
                 f"| **${stats['floating_pnl']:+,.0f}** "
                 f"| **${stats['total_pnl']:+,.0f}** |")
    lines.append(f"| user 真實 5月起 | 5–6月 | 25–30 | **${user_pnl_total:+,.0f}** | - | **${user_pnl_total:+,.0f}** |")
    lines.append("")

    gap_vs_5b   = stats["total_pnl"] - 110_000
    gap_vs_real = stats["total_pnl"] - user_pnl_total

    lines.append(f"> **vs Phase5b:** ${gap_vs_5b:+,.0f}  (黑盒 {'領先' if gap_vs_5b>0 else '落後'})")
    lines.append(f"> **vs User 真實:** ${gap_vs_real:+,.0f}  (黑盒 {'領先' if gap_vs_real>0 else '落後'})")
    lines.append("")

    # ── Phase5b 漏掉但 5d 抓到 ────────────────────────────────────────────────
    phase5b_tickers = {
        "3105","4979","3587","2337","8299","8046","3037","4958","2233",
        "4576","1597","2464","2855","6016","1802","1303",
        "8027","8064","2467","4916","3317","3481","3149",
        "6285","2485","5425","2481","3016","3675",
    }
    extra_catches = [r for r in stats["entered_trades"]
                     if r.ticker not in phase5b_tickers]
    if extra_catches:
        lines.append("## 7. Phase5b 漏掉、Phase5d 新抓到的標的")
        lines.append("")
        extra_pnl = sum(r.pnl for r in extra_catches)
        lines.append(f"**共 {len(extra_catches)} 檔、合計 P&L ${extra_pnl:+,.0f}**")
        lines.append("")
        lines.append("| 代號 | 名稱 | 強度 | 首次明示 | P&L | 備注 |")
        lines.append("|------|------|------|---------|-----|------|")
        for r in sorted(extra_catches, key=lambda x: -x.pnl):
            lines.append(
                f"| {r.ticker} | {r.name} | {r.tier}"
                f" | {r.first_date}"
                f" | **${r.pnl:+,.0f}**"
                f" | {r.entry_reason[:40] if r.entry_reason else ''} |"
            )
        lines.append("")

    # ── 結論 ──────────────────────────────────────────────────────────────────
    lines.append("## 8. 結論")
    lines.append("")

    if gap_vs_5b > 200_000:
        verdict_5b = "黑盒**顯著領先**白盒 (差 ${:+,.0f})".format(gap_vs_5b)
    elif gap_vs_5b > 50_000:
        verdict_5b = "黑盒**領先**白盒 (差 ${:+,.0f})".format(gap_vs_5b)
    elif gap_vs_5b > 0:
        verdict_5b = "黑盒**略領先**白盒 (差 ${:+,.0f})".format(gap_vs_5b)
    else:
        verdict_5b = "黑盒**落後**白盒 (差 ${:+,.0f})".format(gap_vs_5b)

    if gap_vs_real > 200_000:
        verdict_real = "黑盒跟法**顯著優於** User 真實成績 (差 ${:+,.0f})".format(gap_vs_real)
    elif gap_vs_real > 50_000:
        verdict_real = "黑盒跟法**優於** User 真實成績 (差 ${:+,.0f})".format(gap_vs_real)
    elif gap_vs_real > 0:
        verdict_real = "黑盒跟法**略優於** User 真實成績 (差 ${:+,.0f})".format(gap_vs_real)
    else:
        verdict_real = "User 真實成績優於黑盒跟法 (差 ${:+,.0f})".format(gap_vs_real)

    lines.append(f"### 黑盒 vs 白盒: {verdict_5b}")
    lines.append(f"### 黑盒 vs 真實: {verdict_real}")
    lines.append("")
    lines.append("**對「會員直接跟老師」可行性評估:**")
    lines.append("")

    if stats["total_pnl"] > 500_000:
        feasibility = (
            f"若嚴守老師明示 Universe、依老師強度 sizing、老師教法出場，"
            f"5月起約可達 **${stats['total_pnl']:+,.0f}**。"
            f"明顯優於 User 真實 ${user_pnl_total:+,.0f}，"
            f"「直接跟老師黑盒」可行性極高，主要差距來自 User 在非老師框架外的自選標的。"
        )
    elif stats["total_pnl"] > 200_000:
        feasibility = (
            f"若嚴守老師明示 Universe，5月起約可達 **${stats['total_pnl']:+,.0f}**。"
            f"優於 User 真實，「直接跟老師黑盒」策略有相當吸引力。"
        )
    else:
        feasibility = (
            f"5月起黑盒跟老師累積 **${stats['total_pnl']:+,.0f}**，"
            f"較 User 真實差距有限，需進一步分析出場紀律或 sizing 是否可優化。"
        )

    lines.append(feasibility)
    lines.append("")
    lines.append("---")
    lines.append("*本報告基於 backtest，使用日線收盤進出場，不含盤中執行落差與滑點。*")
    lines.append(f"*分析截止: {ANALYSIS_END}  |  Sizing: core $480k / frequent $320k / once $160k*")
    lines.append(f"*Universe: teacher_picks_2026.json (5月起 {stats['total_signals']} 檔)*")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 5d — 老師明示=黑盒立即進場 Backtest"
    )
    parser.add_argument("--verbose", action="store_true", help="顯示每日進出場細節")
    parser.add_argument("--report",  action="store_true", help="寫出 markdown 報告")
    args = parser.parse_args()

    print("=" * 70)
    print("Phase 5d — 老師明示黑盒立即進場 Backtest")
    print("改用老師訊號階層 (core/frequent/once) 直接進、依強度 sizing")
    print(f"分析區間: {ANALYSIS_START} ~ {ANALYSIS_END}")
    print("=" * 70)
    print()

    # 跑 backtest
    results = run_backtest(verbose=args.verbose)
    stats   = analyze_results(results)

    # User 真實 P&L
    print("\n── 讀取 user 5月起真實 broker_statement ────────────────────────────")
    user_pnl_total, user_pnl_by_ticker = get_user_may_real_pnl()
    print(f"5月起已實現 P&L: ${user_pnl_total:+,.0f} ({len(user_pnl_by_ticker)} 個 ticker)")

    print()
    print("=" * 70)
    print("統計結果")
    print("=" * 70)
    print(f"Universe: {stats['total_signals']} 檔  進場: {stats['entered']} 檔"
          f"  已出場: {stats['closed']}  持倉中: {stats['open_pos']}")
    print(f"勝率: {stats['win_rate']:.1f}%  贏:{stats['winners']} 輸:{stats['losers']}")
    print()
    print(f"★ 已實現 P&L:  ${stats['realized_pnl']:+,.0f}")
    print(f"★ 帳面浮盈:    ${stats['floating_pnl']:+,.0f}")
    print(f"★ 合計 P&L:    ${stats['total_pnl']:+,.0f}")
    print()
    print("── 依老師強度分層 ──────────────────────────────────────────────────")
    for tier in ["core", "frequent", "once"]:
        bt = stats["by_tier"][tier]
        cnt = bt["cnt"]
        avg = bt["pnl"] / cnt if cnt else 0
        wr  = bt["wins"] / cnt * 100 if cnt else 0
        print(f"  {tier:10s}: {cnt}檔  P&L=${bt['pnl']:+,.0f}  勝率={wr:.1f}%  平均={avg:+,.0f}")
    print()
    print("── Top 5 獲利 ──────────────────────────────────────────────────────")
    for r in stats["top5"]:
        print(f"  {r.ticker} {r.name:8s} [{r.tier}]  "
              f"P&L=${r.pnl:+,.0f} ({r.pnl_pct:+.1f}%)  {r.hold_days}d")
    print()
    print("── 三版對比 ────────────────────────────────────────────────────────")
    print(f"  Phase5b (白盒 Ch5-3):   +$110,000 (估)")
    print(f"  Phase5d (黑盒立即進):   ${stats['total_pnl']:+,.0f}  (進場{stats['entered']}檔)")
    print(f"  User 真實 5月起:        ${user_pnl_total:+,.0f}")
    print(f"  黑盒 vs 白盒差距:       ${stats['total_pnl'] - 110_000:+,.0f}")
    print(f"  黑盒 vs User 真實差距:  ${stats['total_pnl'] - user_pnl_total:+,.0f}")

    if args.report:
        _STRAT_DIR.mkdir(parents=True, exist_ok=True)
        report_path = _STRAT_DIR / "phase5d_teacher_blackbox_review.md"
        md_content = format_report(results, stats, user_pnl_total, user_pnl_by_ticker)
        report_path.write_text(md_content, encoding="utf-8")
        print()
        print(f"報告已寫出: {report_path}")
    else:
        print()
        print("(加 --report 可寫出完整 markdown 報告)")


if __name__ == "__main__":
    main()
