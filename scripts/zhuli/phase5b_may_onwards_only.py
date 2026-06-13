#!/usr/bin/env python3
"""Phase 5b — 純跟老師週報 Backtest (僅 5 月起，user 5 月才加入會員)。

問題：「如果 user 從 5/3 開始跟老師週報（實際加入時間），
       只用 W0503 / W0516 / W0531 三篇，報酬會是多少？」

背景：
  - Phase 5 (commit 3d84190) 用 4/18 起 4 篇週報 → +$329,773
  - 但 user 5 月才加入，不可能拿到 W0418
  - Phase 5b 改用純 5 月起 3 篇，重算真實會員可達報酬

流程：
  1. 僅用 W0503 / W0516 / W0531 三篇（排除 W0418）
  2. 同 phase5 進出場邏輯
     進場: 多頭排列 5>10>20>60MA + 收盤在MA5上 + 距MA10 -3~+10% + 跳空≤+3%
     出場: 結構底(收盤<MA10) / 分批停利+10/20/30% / 掀傘 / 高黑K / 跳空大跌-5%
  3. 對比 user 5月起真實已實現 P&L (從 broker_statement 抽)
  4. 找差距主因、Top3 案例

用法:
    python scripts/zhuli/phase5b_may_onwards_only.py
    python scripts/zhuli/phase5b_may_onwards_only.py --verbose
    python scripts/zhuli/phase5b_may_onwards_only.py --report
"""
from __future__ import annotations

from zhuli.db import get_conn, MAIN_DB

import argparse
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

for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── 費率 ──────────────────────────────────────────────────────────────────────
FEE_RATE = 0.000399   # 0.0399% 手續費
TAX_RATE = 0.003      # 0.3% 證交稅 (賣方)

# ── Sizing ────────────────────────────────────────────────────────────────────
DEFAULT_CAPITAL = 320_000   # 10% 水位 = $320k

# ── 分析區間 (5 月起) ─────────────────────────────────────────────────────────
ANALYSIS_START = "2026-05-01"
ANALYSIS_END   = "2026-06-03"

# ── Phase 5 全版參考數字 ────────────────────────────────────────────────────────
PHASE5_FULL_PNL = 329_773   # 4 篇週報 (含 W0418) 累積 P&L
PHASE5_W0418_PNL = 223_619  # W0418 單獨 P&L
# 5 月起 3 篇理論值 = 329,773 - 223,619 = 106,154 (但需重跑確認去重邏輯差異)

# ═══════════════════════════════════════════════════════════════════════════════
# 1. 週報 ticker 清單 (5 月起 3 篇，排除 W0418)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class WeeklyReportEntry:
    pub_date:   str
    report_key: str
    theme:      str
    tickers:    list[str]
    notes:      dict[str, str] = field(default_factory=dict)


# ── 5/3 週報 ──────────────────────────────────────────────────────────────────
# 主題: 台積電 vs 中小輪動; 資金從高檔轉低檔; CPO+記憶體+ABF+機器人+證券新題材
REPORT_0503 = WeeklyReportEntry(
    pub_date   = "2026-05-03",
    report_key = "W0503",
    theme      = "中小輪動接棒 — CPO+記憶體+ABF+機器人+證券股新題材",
    tickers    = [
        "3105",  # 穩懋   (CPO)
        "4979",  # 華星光 (CPO)
        "3587",  # 閎康   (CPO 檢測)
        "2337",  # 旺宏   (記憶體)
        "8299",  # 群聯   (記憶體 NAND)
        "8046",  # 南電   (ABF 載板)
        "3037",  # 欣興   (ABF 載板)
        "4958",  # 臻鼎   (ABF/PCB)
        "2233",  # 宇隆   (機器人)
        "4576",  # 大銀微 (機器人)
        "1597",  # 直得   (機器人)
        "2464",  # 盟立   (機器人)
        "2855",  # 統一證 (證券)
        "6016",  # 康和證 (證券)
        "1802",  # 台玻   (玻纖布/CCL 漲價)
        "1303",  # 南亞   (玻纖布)
    ],
    notes = {
        "3105": "穩懋 CPO 光引擎",
        "4979": "華星光 CPO",
        "3587": "閎康 CPO 檢測",
        "8046": "南電 ABF 載板",
        "3037": "欣興 ABF 載板",
        "4958": "臻鼎 高階 PCB",
        "2464": "盟立 機器人/工業自動化",
        "2855": "統一證 兆元成交量受益",
        "6016": "康和證 兆元成交量受益",
    }
)

# ── 5/16 週報 ─────────────────────────────────────────────────────────────────
# 主題: 川習會後高檔整理; 玻璃基板 CoPoS; 低軌衛星
REPORT_0516 = WeeklyReportEntry(
    pub_date   = "2026-05-16",
    report_key = "W0516",
    theme      = "高檔整理/玻璃基板 CoPoS — 鈦昇/東捷/志聖 + 低軌衛星事欣科",
    tickers    = [
        "8027",  # 鈦昇   (玻璃基板 TGV 設備、CoPoS)
        "8064",  # 東捷   (玻璃基板/半導體設備)
        "2467",  # 志聖   (PCB 設備、CoWoS G2C+)
        "4916",  # 事欣科 (工業電腦+低軌衛星)
        "3317",  # 長基   (功率元件 GaN)
        "3481",  # 群創   (面板 + AI PC 需求)
        "3149",  # 正達   (面板/光學)
    ],
    notes = {
        "8027": "CoPoS TGV 雷射設備 核心廠商",
        "8064": "CoPoS/半導體先進封裝設備",
        "2467": "CoWoS G2C+ 聯盟 PCB 設備",
        "4916": "低軌衛星 SpaceX+新客戶",
    }
)

# ── 5/31 週報 ─────────────────────────────────────────────────────────────────
# 主題: COMPUTEX 2026 + NVIDIA GTC Taipei + AI PC; 低軌衛星+功率元件+GaN/SiC
REPORT_0531 = WeeklyReportEntry(
    pub_date   = "2026-05-31",
    report_key = "W0531",
    theme      = "COMPUTEX 2026 — AI PC + 低軌衛星 + 功率元件 + GaN/SiC",
    tickers    = [
        "6285",  # 啟碁   (低軌衛星地面接收)
        "2485",  # 兆赫   (低軌衛星)
        "5425",  # 台半   (功率元件 MOSFET)
        "2481",  # 強茂   (功率元件 MOSFET) — 首次出現在5月起清單
        "3016",  # 嘉晶   (GaN/SiC 磊晶)   — 首次出現在5月起清單
        "3675",  # 德微   (SiC)
    ],
    notes = {
        "6285": "啟碁 低軌衛星 地面接收設備",
        "2485": "兆赫 低軌衛星終端設備",
        "5425": "台半 MOSFET 缺貨漲價概念",
        "2481": "強茂 MOSFET IDM 交期 30 週",
        "3016": "嘉晶 SiC 磊晶 小量產中",
        "3675": "德微 SiC 概念",
    }
)

# ── 5 月起 3 篇週報 ───────────────────────────────────────────────────────────
ALL_REPORTS: list[WeeklyReportEntry] = [
    REPORT_0503,
    REPORT_0516,
    REPORT_0531,
]


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


def get_stock_name(ticker: str) -> str:
    try:
        with _db_con() as con:
            row = con.execute(
                "SELECT stock_name FROM stock_info WHERE ticker=? LIMIT 1",
                (ticker,)
            ).fetchone()
        return row[0] if row else ticker
    except Exception:
        return ticker


# ═══════════════════════════════════════════════════════════════════════════════
# 3. User 真實 5 月起 P&L (從 broker_statement)
# ═══════════════════════════════════════════════════════════════════════════════

def get_user_may_real_pnl() -> tuple[float, dict[str, float]]:
    """從 broker_statement 計算 user 5 月起的 FIFO 已實現 P&L。

    回傳 (total_closed_pnl, by_ticker_dict)
    注意: open position 未實現部分不計入（保守口徑）
    """
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
        by_ticker[r[0]].append(r[1:])  # (date, action, shares, price, net_amount)

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
# 4. 進場邏輯 (同 phase5)
# ═══════════════════════════════════════════════════════════════════════════════

def check_entry_conditions(row: pd.Series, prev_close: Optional[float]) -> tuple[bool, str]:
    """進場條件: 多頭排列 + 收盤在MA5上 + 距MA10 -3~+10% + 跳空≤+3%"""
    close  = row["close"]
    ma5    = row["ma5"]
    ma10   = row["ma10"]
    ma20   = row["ma20"]
    ma60   = row["ma60"]
    open_p = row["open"]

    if any(pd.isna(v) for v in [close, ma5, ma10, ma20, ma60]):
        return False, "MA資料缺失"

    if not (ma5 > ma10 > ma20 > ma60):
        return False, f"非多頭排列 5={ma5:.1f} 10={ma10:.1f} 20={ma20:.1f} 60={ma60:.1f}"

    if close < ma5:
        return False, f"收盤{close:.2f}<MA5{ma5:.2f}"

    dist_ma10_pct = (close - ma10) / ma10 * 100
    if dist_ma10_pct < -3.0 or dist_ma10_pct > 10.0:
        return False, f"打擊區外 距MA10={dist_ma10_pct:+.1f}%"

    if prev_close is not None and prev_close > 0:
        gap_pct = (open_p - prev_close) / prev_close * 100
        if gap_pct > 3.0:
            return False, f"跳空過大 {gap_pct:+.1f}%>+3%"

    reason = (
        f"多頭排列✓ | MA5={ma5:.1f} MA10={ma10:.1f} | 距MA10={dist_ma10_pct:+.1f}%"
    )
    return True, reason


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 出場邏輯 (同 phase5)
# ═══════════════════════════════════════════════════════════════════════════════

def check_exit(
    df_to_date: pd.DataFrame,
    entry_price: float,
    shares_held: float,
    milestones_hit: set,
) -> tuple[Optional[str], str, float, float]:
    if len(df_to_date) < 2:
        return None, "資料不足", 0.0, 0.0

    today = df_to_date.iloc[-1]
    prev  = df_to_date.iloc[-2]
    close = float(today["close"])
    open_p = float(today["open"])
    prev_close = float(prev["close"])
    ma10  = today["ma10"]

    # P1: 跳空大跌 -5%+
    if not pd.isna(prev_close) and prev_close > 0:
        gap_pct = (open_p - prev_close) / prev_close * 100
        if gap_pct <= -5.0:
            return "exit_all", f"跳空大跌 {gap_pct:+.1f}%", open_p, 1.0

    # P2: 結構底 — 日收盤 < MA10
    if not pd.isna(ma10) and close < float(ma10):
        return "exit_all", f"收盤{close:.2f}<MA10{float(ma10):.2f}", close, 1.0

    # P3: 高檔長黑
    if len(df_to_date) >= 7:
        hlb = _check_high_long_black_simple(df_to_date)
        if hlb:
            return "exit_all", f"高檔長黑K: {hlb}", close, 1.0

    # P4: 掀傘
    if len(df_to_date) >= 5 and close > entry_price:
        umbrella = _check_umbrella_daily_simple(df_to_date, entry_price)
        if umbrella:
            return "exit_all", f"掀傘: {umbrella}", close, 1.0

    # P5: 分批停利里程碑
    profit_pct = (close / entry_price - 1) * 100
    milestones = [(10.0, "M10", 1/3), (20.0, "M20", 1/3), (30.0, "M30", 1.0)]
    for threshold, key, ratio in milestones:
        if profit_pct >= threshold and key not in milestones_hit:
            milestones_hit.add(key)
            return "take_profit", f"分批停利 +{threshold:.0f}% (出 {ratio*100:.0f}%)", close, ratio

    return None, "", close, 0.0


def _check_high_long_black_simple(df: pd.DataFrame) -> Optional[str]:
    today = df.iloc[-1]
    prev  = df.iloc[-2]
    open_p = float(today["open"])
    close  = float(today["close"])

    if close >= open_p:
        return None
    body_pct = (open_p - close) / open_p
    if body_pct < 0.04:
        return None

    lookback = df.tail(min(len(df), 61)).iloc[:-1]
    if len(lookback) < 10:
        return None
    prior_max = float(lookback["high"].max())
    prior_min = float(lookback["low"].min())
    if prior_min <= 0 or prior_max / prior_min < 1.2:
        return None

    meanings = []

    for i in range(len(df) - 2, max(0, len(df) - 22), -1):
        if df.iloc[i]["open"] > df.iloc[i-1]["high"]:
            gap_low = float(df.iloc[i-1]["high"])
            if close < gap_low:
                meanings.append(f"M1缺口回補(gap={gap_low:.1f})")
            break

    prev_close_v = float(prev["close"])
    prev_open_v  = float(prev["open"])
    prev_high_v  = float(prev["high"])
    prev_low_v   = float(prev["low"])
    if prev_close_v > prev_open_v:
        hist = df.tail(min(len(df), 63)).iloc[:-2]
        if not hist.empty and prev_close_v >= float(hist["high"].max()):
            if open_p >= prev_high_v and close <= prev_low_v:
                meanings.append(f"M2包覆創高紅K(前高{prev_high_v:.1f})")

    if len(df) >= 7:
        prior_5_closes = df.iloc[-7:-2]["close"]
        min_5 = float(prior_5_closes.min())
        if close < min_5:
            meanings.append(f"M3吃前5根(前最低收{min_5:.1f})")

    if len(meanings) >= 2:
        return " + ".join(meanings)
    return None


def _check_umbrella_daily_simple(df: pd.DataFrame, entry_price: float) -> Optional[str]:
    NO_NEW_HIGH_BARS = 3
    if len(df) < NO_NEW_HIGH_BARS + 2:
        return None
    close = float(df.iloc[-1]["close"])
    if close <= entry_price:
        return None

    prior_high = float(df.iloc[-(NO_NEW_HIGH_BARS + 1)]["high"])
    tail_highs = [float(df.iloc[-(NO_NEW_HIGH_BARS - i)]["high"]) for i in range(NO_NEW_HIGH_BARS)]
    if not all(h <= prior_high for h in tail_highs):
        return None

    vol_mean = float(df["volume"].tail(min(len(df), 10)).mean())
    last_vol  = float(df.iloc[-1]["volume"])
    vol_ratio = last_vol / vol_mean if vol_mean > 0 else 1.0
    if vol_ratio >= 0.7:
        return None

    tail_bars = df.tail(NO_NEW_HIGH_BARS)
    reds = (tail_bars["close"] > tail_bars["open"]).values
    if any(reds[i] and reds[i+1] for i in range(len(reds)-1)):
        return None

    profit_pct = (close / entry_price - 1) * 100
    return f"連3日不創高+量縮×{vol_ratio:.2f} | 浮盈+{profit_pct:.1f}%"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. 單一 Ticker 模擬
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SimTrade:
    ticker:     str
    name:       str
    report_key: str
    pub_date:   str
    theme:      str
    entry_date: Optional[str]   = None
    entry_price: float           = 0.0
    exit_date:  Optional[str]   = None
    exit_price: float            = 0.0
    exit_reason: str             = ""
    pnl:        float            = 0.0
    pnl_pct:    float            = 0.0
    capital:    float            = DEFAULT_CAPITAL
    entry_triggered_on: str      = ""
    status:     str              = "no_entry"
    max_profit_pct: float        = 0.0
    hold_days:  int              = 0


def simulate_ticker(
    ticker: str,
    report: WeeklyReportEntry,
    all_trading_dates: list[str],
    bars: pd.DataFrame,
    verbose: bool = False,
) -> SimTrade:
    name = get_stock_name(ticker)
    trade = SimTrade(
        ticker=ticker, name=name,
        report_key=report.report_key, pub_date=report.pub_date,
        theme=report.theme, capital=DEFAULT_CAPITAL,
    )

    if bars.empty:
        trade.status = "no_data"
        return trade

    monitor_dates = [d for d in all_trading_dates if d > report.pub_date]
    if not monitor_dates:
        return trade

    max_monitor_days = 10
    entry_price = None
    entry_date  = None
    prev_close_cache: dict[str, float] = {}

    sorted_bars = bars.sort_values("trade_date").reset_index(drop=True)
    for i, row in sorted_bars.iterrows():
        if i > 0:
            prev_close_cache[row["trade_date"]] = float(sorted_bars.iloc[i-1]["close"])

    # 等待進場
    for d in monitor_dates[:max_monitor_days]:
        day_rows = bars[bars["trade_date"] == d]
        if day_rows.empty:
            continue
        row = day_rows.iloc[-1]
        prev_close = prev_close_cache.get(d)
        ok, reason = check_entry_conditions(row, prev_close)

        if ok:
            entry_price = float(row["close"])
            entry_date  = d
            trade.entry_date  = entry_date
            trade.entry_price = entry_price
            trade.entry_triggered_on = reason
            trade.status = "open"
            if verbose:
                print(f"  [進場] {ticker} {name}  @{entry_date}  ${entry_price:.2f}  {reason[:70]}")
            break
        else:
            if verbose:
                print(f"  [等待] {ticker} {name}  {d}  未觸發: {reason}")

    if entry_price is None:
        trade.status = "no_entry"
        return trade

    # 持倉模擬
    hold_dates = [d for d in all_trading_dates if d > entry_date]
    if not hold_dates:
        last_row = bars[bars["trade_date"] <= ANALYSIS_END]
        if not last_row.empty:
            last_close = float(last_row.iloc[-1]["close"])
            trade.exit_price  = last_close
            trade.exit_date   = last_row.iloc[-1]["trade_date"]
            trade.exit_reason = "持倉中(分析截止)"
            _finalize_trade(trade, last_close)
        return trade

    milestones_hit: set = set()
    shares_held    = 1.0
    partial_pnl    = 0.0

    for exit_d in hold_dates:
        day_rows = bars[bars["trade_date"] == exit_d]
        if day_rows.empty:
            continue
        row = day_rows.iloc[-1]
        cur_close = float(row["close"])

        profit_pct_now = (cur_close / entry_price - 1) * 100
        if profit_pct_now > trade.max_profit_pct:
            trade.max_profit_pct = profit_pct_now

        df_to_date = bars[bars["trade_date"] <= exit_d].copy()
        df_to_date = df_to_date.sort_values("trade_date").reset_index(drop=True)

        action, reason, exit_price, ratio = check_exit(
            df_to_date, entry_price, shares_held, milestones_hit
        )

        if action == "exit_all":
            trade.exit_date   = exit_d
            trade.exit_price  = exit_price
            trade.exit_reason = reason
            trade.hold_days   = len([d for d in all_trading_dates
                                     if entry_date < d <= exit_d])
            shares_total = DEFAULT_CAPITAL / entry_price
            buy_fee  = entry_price * shares_total * FEE_RATE
            sell_fee = exit_price  * shares_total * shares_held * FEE_RATE
            sell_tax = exit_price  * shares_total * shares_held * TAX_RATE
            gross_pnl = (exit_price - entry_price) * shares_total * shares_held
            net_pnl   = gross_pnl - buy_fee - sell_fee - sell_tax + partial_pnl
            trade.pnl     = round(net_pnl, 0)
            trade.pnl_pct = round((exit_price / entry_price - 1) * 100, 2)
            trade.status  = "closed"
            if verbose:
                print(f"  [出場] {ticker}  @{exit_d}  ${exit_price:.2f}  {reason}  P&L={trade.pnl:+,.0f}")
            return trade

        elif action == "take_profit":
            shares_out = ratio * shares_held
            shares_total = DEFAULT_CAPITAL / entry_price
            gross_partial = (exit_price - entry_price) * shares_total * shares_out
            fee_partial   = exit_price * shares_total * shares_out * (FEE_RATE + TAX_RATE)
            partial_pnl  += gross_partial - fee_partial
            shares_held  -= shares_out
            if verbose:
                print(f"  [停利] {ticker}  @{exit_d}  ${exit_price:.2f}  {reason}  "
                      f"部分P&L={gross_partial-fee_partial:+,.0f}  剩{shares_held*100:.0f}%")

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

    # 分析截止仍持倉
    last_bars = bars[bars["trade_date"] <= ANALYSIS_END]
    if not last_bars.empty:
        last_close = float(last_bars.iloc[-1]["close"])
        trade.exit_price  = last_close
        trade.exit_date   = last_bars.iloc[-1]["trade_date"]
        trade.exit_reason = "持倉中(分析截止)"
        trade.hold_days   = len([d for d in all_trading_dates
                                  if entry_date < d <= trade.exit_date])
        shares_total = DEFAULT_CAPITAL / entry_price
        gross = (last_close - entry_price) * shares_total * shares_held
        fee   = last_close * shares_total * shares_held * (FEE_RATE + TAX_RATE)
        trade.pnl     = round(gross - fee + partial_pnl, 0)
        trade.pnl_pct = round((last_close / entry_price - 1) * 100, 2)
        trade.status  = "open"
    return trade


def _finalize_trade(trade: SimTrade, exit_price: float) -> None:
    shares_total = DEFAULT_CAPITAL / trade.entry_price
    gross = (exit_price - trade.entry_price) * shares_total
    fee   = exit_price * shares_total * (FEE_RATE + TAX_RATE)
    trade.pnl     = round(gross - fee, 0)
    trade.pnl_pct = round((exit_price / trade.entry_price - 1) * 100, 2)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. 回測主流程
# ═══════════════════════════════════════════════════════════════════════════════

def run_backtest(verbose: bool = False) -> list[SimTrade]:
    all_dates = get_trading_dates(ANALYSIS_START, ANALYSIS_END)

    results: list[SimTrade] = []
    seen_entries: set[str] = set()

    for report in ALL_REPORTS:
        print(f"\n=== 週報 {report.report_key} ({report.pub_date}) ===")
        print(f"主題: {report.theme}")
        print(f"監控 {len(report.tickers)} 檔: {' '.join(report.tickers)}")

        for ticker in report.tickers:
            entry_key = ticker
            if entry_key in seen_entries:
                if verbose:
                    print(f"  [SKIP] {ticker} 已在前篇報告追蹤")
                continue

            # 載入日線資料 (從報告日往前 100 天讓 MA 穩定)
            load_start = pd.Timestamp(report.pub_date) - pd.Timedelta(days=100)
            bars = load_daily_bars(ticker, load_start.strftime("%Y-%m-%d"), ANALYSIS_END)

            trade = simulate_ticker(
                ticker=ticker, report=report,
                all_trading_dates=all_dates, bars=bars, verbose=verbose,
            )
            results.append(trade)

            if trade.status in ("open", "closed") and trade.entry_date:
                seen_entries.add(entry_key)

            status_str = {
                "no_data":  "🚫 無資料",
                "no_entry": "⏳ 無進場訊號",
                "open":     "📂 持倉中",
                "closed":   "✅ 已出場",
            }.get(trade.status, trade.status)
            pnl_str = f"P&L={trade.pnl:+,.0f}" if trade.entry_date else ""
            print(f"  {ticker} {trade.name:8s}  {status_str}  {pnl_str}")

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 8. 分析 & 報告生成
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_results(results: list[SimTrade]) -> dict:
    entered  = [r for r in results if r.entry_date]
    closed   = [r for r in entered if r.status == "closed"]
    open_pos = [r for r in entered if r.status == "open"]
    no_entry = [r for r in results if not r.entry_date and r.status != "no_data"]
    no_data  = [r for r in results if r.status == "no_data"]

    total_pnl = sum(r.pnl for r in entered)
    winners   = [r for r in entered if r.pnl > 0]
    losers    = [r for r in entered if r.pnl < 0]

    by_report: dict = {}
    for r in results:
        k = r.report_key
        if k not in by_report:
            by_report[k] = {"entered": 0, "pnl": 0, "tickers": []}
        by_report[k]["tickers"].append(r.ticker)
        if r.entry_date:
            by_report[k]["entered"] += 1
            by_report[k]["pnl"] += r.pnl

    return {
        "total":    len(results),
        "entered":  len(entered),
        "closed":   len(closed),
        "open_pos": len(open_pos),
        "no_entry": len(no_entry),
        "no_data":  len(no_data),
        "total_pnl": total_pnl,
        "winners":  len(winners),
        "losers":   len(losers),
        "win_rate": len(winners) / len(entered) * 100 if entered else 0,
        "avg_pnl":  total_pnl / len(entered) if entered else 0,
        "avg_win":  sum(r.pnl for r in winners) / len(winners) if winners else 0,
        "avg_loss": sum(r.pnl for r in losers) / len(losers) if losers else 0,
        "best_trade":  max(entered, key=lambda r: r.pnl) if entered else None,
        "worst_trade": min(entered, key=lambda r: r.pnl) if entered else None,
        "by_report": by_report,
        "entered_trades": entered,
    }


def format_report(results: list[SimTrade], stats: dict,
                  user_pnl_total: float, user_pnl_by_ticker: dict) -> str:
    lines: list[str] = []

    lines.append("# Phase 5b — 5 月起純跟老師週報 Backtest 報告")
    lines.append(f"**版本說明:** User 5 月才加入老師會員，本報告排除 W0418 (4月)，")
    lines.append(f"僅用 W0503 / W0516 / W0531 三篇，反映真實可達報酬。")
    lines.append(f"**分析區間:** {ANALYSIS_START} → {ANALYSIS_END}")
    lines.append(f"**週報篇數:** {len(ALL_REPORTS)} 篇  |  **涵蓋 ticker:** {stats['total']} 個")
    lines.append("")

    # ── 各週報題材 ─────────────────────────────────────────────────────────────
    lines.append("## 1. 各週報題材整理 (5 月起 3 篇)")
    lines.append("")
    for report in ALL_REPORTS:
        lines.append(f"### {report.report_key} ({report.pub_date})")
        lines.append(f"**主題:** {report.theme}")
        lines.append(f"**推薦 ticker ({len(report.tickers)} 檔):** {' / '.join(report.tickers)}")
        rstat = stats["by_report"].get(report.report_key, {})
        lines.append(f"進場命中: **{rstat.get('entered',0)}/{len(report.tickers)}** 檔  |  "
                     f"P&L: **${rstat.get('pnl',0):+,.0f}**")
        lines.append("")

    # ── 進場明細 ──────────────────────────────────────────────────────────────
    lines.append("## 2. 進場模擬明細")
    lines.append("")
    lines.append("| 週報 | 代號 | 名稱 | 進場日 | 進場價 | 出場日 | 出場價 | 出場原因 | P&L | 最大浮盈 | 持倉日 |")
    lines.append("|------|------|------|--------|--------|--------|--------|----------|-----|---------|--------|")

    entered = sorted(stats["entered_trades"], key=lambda r: (r.pub_date, r.ticker))
    for r in entered:
        entry_d  = r.entry_date or "-"
        exit_d   = r.exit_date or "持倉中"
        exit_p   = f"${r.exit_price:.1f}" if r.exit_price else "-"
        pnl_str  = f"**{r.pnl:+,.0f}**" if r.pnl != 0 else "-"
        reason   = r.exit_reason[:28] if r.exit_reason else "持倉中"
        lines.append(
            f"| {r.report_key} | {r.ticker} | {r.name} "
            f"| {entry_d} | ${r.entry_price:.1f} "
            f"| {exit_d} | {exit_p} "
            f"| {reason} "
            f"| {pnl_str} "
            f"| {r.max_profit_pct:+.1f}% "
            f"| {r.hold_days}d |"
        )
    lines.append("")

    # ── 未觸發進場 ─────────────────────────────────────────────────────────────
    no_entry_list = [r for r in results if not r.entry_date and r.status == "no_entry"]
    if no_entry_list:
        lines.append(f"**未觸發進場 ({len(no_entry_list)} 檔):** "
                     + " / ".join(f"{r.ticker}{r.name}" for r in no_entry_list[:25]))
        lines.append("")

    # ── 累積 P&L 統計 ──────────────────────────────────────────────────────────
    lines.append("## 3. 累積報酬統計")
    lines.append("")
    lines.append(f"| 指標 | 數值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 週報推薦總標的 | {stats['total']} 檔 |")
    lines.append(f"| 成功進場 | {stats['entered']} 檔 |")
    lines.append(f"| 進場觸發率 | {stats['entered']/max(stats['total'],1)*100:.1f}% |")
    lines.append(f"| 已出場 | {stats['closed']} 檔 |")
    lines.append(f"| 仍持倉(截至{ANALYSIS_END}) | {stats['open_pos']} 檔 |")
    lines.append(f"| 未觸發進場 | {stats['no_entry']} 檔 |")
    lines.append(f"| **累積 P&L (純週報 5月起)** | **${stats['total_pnl']:+,.0f}** |")
    lines.append(f"| 勝率 | {stats['win_rate']:.1f}% |")
    lines.append(f"| 平均單筆 P&L | ${stats['avg_pnl']:+,.0f} |")
    lines.append(f"| 平均獲利(贏) | ${stats['avg_win']:+,.0f} |")
    lines.append(f"| 平均虧損(輸) | ${stats['avg_loss']:+,.0f} |")

    if stats["best_trade"]:
        bt = stats["best_trade"]
        lines.append(f"| 最佳單筆 | {bt.ticker}{bt.name} {bt.pnl:+,.0f} ({bt.pnl_pct:+.1f}%) |")
    if stats["worst_trade"]:
        wt = stats["worst_trade"]
        lines.append(f"| 最差單筆 | {wt.ticker}{wt.name} {wt.pnl:+,.0f} ({wt.pnl_pct:+.1f}%) |")
    lines.append("")

    # ── 三版對比表 ─────────────────────────────────────────────────────────────
    lines.append("## 4. 三版對比表")
    lines.append("")
    lines.append("| 策略 | 期間 | 週報篇數 | 累積 P&L | 備注 |")
    lines.append("|------|------|---------|---------|------|")
    lines.append(f"| phase5 全版 (4/18 起) | 4月–6月 | 4 篇 | **+$329,773** | 含 W0418 (user 加入前) |")
    lines.append(f"| **phase5b 5月起** | 5月–6月 | 3 篇 | **${stats['total_pnl']:+,.0f}** | User 真實可達 |")
    lines.append(f"| user 真實 5月起 | 5月–6月 | — | **${user_pnl_total:+,.0f}** (已實現) | 含非週報標的 |")
    lines.append("")

    # ── 差距分析 ──────────────────────────────────────────────────────────────
    sim_pnl = stats["total_pnl"]
    gap = sim_pnl - user_pnl_total
    lines.append("## 5. 差距分析 — 5 月起 純跟老師 vs User 真實")
    lines.append("")
    lines.append(f"**5 月起純週報 (backtest):** ${sim_pnl:+,.0f}")
    lines.append(f"**5 月起 user 真實 (已實現):** ${user_pnl_total:+,.0f}")
    lines.append(f"**差距:** ${gap:+,.0f} (backtest 領先)")
    lines.append("")

    # 找週報 ticker 的真實 P&L
    lines.append("### 重疊 ticker 對比 (週報推薦 ∩ user 真實交易)")
    lines.append("")
    lines.append("| 代號 | 名稱 | 週報 | 模擬 P&L | User 真實 P&L | 差距 | 差距來源 |")
    lines.append("|------|------|------|---------|--------------|------|---------|")

    overlap_gap_total = 0.0
    diff_cases: list[dict] = []
    for r in entered:
        real_pnl = user_pnl_by_ticker.get(r.ticker, None)
        real_str = f"${real_pnl:+,.0f}" if real_pnl is not None else "未交易"
        if real_pnl is not None:
            tk_gap = real_pnl - r.pnl
            overlap_gap_total += tk_gap
            gap_str = f"${tk_gap:+,.0f}"
            # 差距原因分類
            if real_pnl < r.pnl - 10000:
                if r.exit_reason and "停利" in r.exit_reason and real_pnl < r.pnl * 0.5:
                    reason_short = "太早停利"
                elif real_pnl < 0 and r.pnl > 0:
                    reason_short = "方向看反/沒進場"
                else:
                    reason_short = "User 輸更多"
            elif real_pnl > r.pnl + 10000:
                reason_short = "User 贏更多"
            else:
                reason_short = "相近"
            diff_cases.append({
                "ticker": r.ticker, "name": r.name,
                "sim": r.pnl, "real": real_pnl,
                "gap": tk_gap, "reason": reason_short,
            })
        else:
            gap_str = "(未交易)"
            reason_short = "User 未交易"

        lines.append(
            f"| {r.ticker} | {r.name} | {r.report_key} "
            f"| ${r.pnl:+,.0f} | {real_str} | {gap_str} | {reason_short} |"
        )
    lines.append("")
    lines.append(f"**重疊標的差距合計:** ${overlap_gap_total:+,.0f}")
    lines.append("")

    # Top 3 差距案例
    diff_cases_sorted = sorted(diff_cases, key=lambda x: x["gap"])[:5]
    lines.append("### Top 差距案例 (User 真實 vs 模擬)")
    lines.append("")
    for i, c in enumerate(diff_cases_sorted, 1):
        lines.append(
            f"{i}. **{c['ticker']}{c['name']}** — "
            f"模擬 ${c['sim']:+,.0f} vs 真實 ${c['real']:+,.0f}  "
            f"(差 ${c['gap']:+,.0f})  → {c['reason']}"
        )
    lines.append("")

    # ── 非週報標的 (user 虧損來源) ─────────────────────────────────────────────
    phase5b_tickers = {r.ticker for r in results}
    non_report_losses = {
        tk: pnl for tk, pnl in user_pnl_by_ticker.items()
        if tk not in phase5b_tickers and pnl < -5000
    }
    if non_report_losses:
        sorted_losses = sorted(non_report_losses.items(), key=lambda x: x[1])
        lines.append("### User 5月起虧損主要來源 (非週報標的)")
        lines.append("")
        lines.append("| 代號 | 已實現 P&L |")
        lines.append("|------|-----------|")
        for tk, pnl in sorted_losses[:10]:
            name = get_stock_name(tk)
            lines.append(f"| {tk} {name} | ${pnl:+,.0f} |")
        total_non_report_loss = sum(non_report_losses.values())
        lines.append(f"| **非週報虧損合計** | **${total_non_report_loss:+,.0f}** |")
        lines.append("")

    # ── 結論 ──────────────────────────────────────────────────────────────────
    lines.append("## 6. 結論")
    lines.append("")
    lines.append(f"| 項目 | 金額 |")
    lines.append(f"|------|------|")
    lines.append(f"| 5 月起純跟老師週報 (backtest) | **${sim_pnl:+,.0f}** |")
    lines.append(f"| 5 月起 user 真實已實現 | **${user_pnl_total:+,.0f}** |")
    lines.append(f"| 差距 (backtest 領先) | **${gap:+,.0f}** |")
    lines.append("")

    non_report_total = sum(pnl for tk, pnl in user_pnl_by_ticker.items()
                           if tk not in phase5b_tickers)
    lines.append(f"**非週報標的已實現合計:** ${non_report_total:+,.0f}")
    lines.append("")

    if gap > 50000:
        verdict = "5月起純跟老師週報 **顯著優於** user 真實成績"
    elif gap > 0:
        verdict = "5月起純跟老師週報 **略優於** user 真實成績"
    else:
        verdict = "5月起 user 真實成績優於純週報模擬"

    lines.append(f"### 結論: {verdict}")
    lines.append("")
    lines.append("**差距主因 Top 3:**")
    lines.append("")

    top3 = sorted(diff_cases, key=lambda x: x["gap"])[:3]
    for i, c in enumerate(top3, 1):
        lines.append(f"{i}. **{c['ticker']}{c['name']}**: 模擬 ${c['sim']:+,.0f} vs 真實 ${c['real']:+,.0f} → {c['reason']}")

    lines.append("")
    if non_report_losses:
        worst_non = sorted(non_report_losses.items(), key=lambda x: x[1])[:3]
        lines.append("**非週報標的主要虧損 (user 自選):**")
        for tk, pnl in worst_non:
            name = get_stock_name(tk)
            lines.append(f"- {tk} {name}: ${pnl:+,.0f}")
        lines.append("")

    lines.append("**對 user 真實合理可達「跟老師會員」報酬期望:**")
    lines.append("")
    lines.append(
        f"若嚴守老師週報範圍、不做週報外標的，"
        f"5 月起約可達 **${sim_pnl:+,.0f}**。"
        f"與 user 真實差距 ${gap:+,.0f} 主要來自 "
        f"週報外標的虧損（自選個股）與出場紀律落差。"
    )
    lines.append("")
    lines.append("---")
    lines.append("*本報告基於假設性 backtest，daily bar 收盤進出場，不含盤中執行落差。*")
    lines.append(f"*分析截止: {ANALYSIS_END}  |  Sizing: $320k/檔 (總資金 ~$3.2M 水位 10%)*")
    lines.append(f"*僅用 W0503/W0516/W0531 (排除 W0418) — user 5 月才加入會員*")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 5b — 純跟老師週報 Backtest (5 月起)"
    )
    parser.add_argument("--verbose", action="store_true", help="顯示每日進出場細節")
    parser.add_argument("--report",  action="store_true", help="寫出 markdown 報告")
    args = parser.parse_args()

    print("=" * 70)
    print("Phase 5b — 5 月起純跟老師「本週市場資訊報」Backtest")
    print("(User 5 月才加入會員，排除 W0418，僅用 3 篇)")
    print(f"分析區間: {ANALYSIS_START} ~ {ANALYSIS_END}")
    print(f"涵蓋週報: W0503 / W0516 / W0531")
    total_tickers = len(set(tk for r in ALL_REPORTS for tk in r.tickers))
    print(f"推薦標的: {total_tickers} 個 (去重後)")
    print("=" * 70)

    # 跑 backtest
    results = run_backtest(verbose=args.verbose)
    stats   = analyze_results(results)

    # 取 user 5 月起真實 P&L
    print("\n── 讀取 user 5 月起真實 broker_statement ───────────────────────")
    user_pnl_total, user_pnl_by_ticker = get_user_may_real_pnl()
    print(f"5 月起已實現 P&L: ${user_pnl_total:+,.0f} ({len(user_pnl_by_ticker)} 個 ticker)")

    print()
    print("=" * 70)
    print("統計結果")
    print("=" * 70)
    print(f"週報推薦: {stats['total']} 檔  進場觸發: {stats['entered']} 檔  "
          f"(觸發率 {stats['entered']/max(stats['total'],1)*100:.1f}%)")
    print(f"已出場: {stats['closed']} 筆  仍持倉: {stats['open_pos']} 筆  "
          f"無訊號: {stats['no_entry']} 檔")
    print(f"勝率: {stats['win_rate']:.1f}%  "
          f"贏:{stats['winners']} 輸:{stats['losers']}")
    print()
    print(f"★ 5月起純週報累積 P&L: ${stats['total_pnl']:+,.0f}")
    print(f"  平均單筆: ${stats['avg_pnl']:+,.0f}  "
          f"均獲利: ${stats['avg_win']:+,.0f}  均虧損: ${stats['avg_loss']:+,.0f}")
    print()
    print(f"── 三版對比 ───────────────────────────────────────────────────")
    print(f"  Phase5 全版 (4/18 起, 4 篇): +$329,773")
    print(f"  Phase5b 5月起 (3 篇):        ${stats['total_pnl']:+,.0f}")
    print(f"  User 真實 5月起 (已實現):    ${user_pnl_total:+,.0f}")
    print(f"  差距 (5月backtest - user真實): ${stats['total_pnl']-user_pnl_total:+,.0f}")
    print()

    print(f"── 各週報 P&L ──────────────────────────────────────────────────")
    for rpt in ALL_REPORTS:
        rstat = stats["by_report"].get(rpt.report_key, {})
        print(f"  {rpt.report_key} ({rpt.pub_date}): "
              f"進場 {rstat.get('entered',0)}/{len(rpt.tickers)} 檔  "
              f"P&L={rstat.get('pnl',0):+,.0f}")

    if stats["best_trade"]:
        bt = stats["best_trade"]
        print(f"\n  最佳: {bt.ticker}{bt.name}  {bt.pnl:+,.0f} ({bt.pnl_pct:+.1f}%)  "
              f"@{bt.entry_date} → {bt.exit_date}")
    if stats["worst_trade"]:
        wt = stats["worst_trade"]
        print(f"  最差: {wt.ticker}{wt.name}  {wt.pnl:+,.0f} ({wt.pnl_pct:+.1f}%)  "
              f"@{wt.entry_date} → {wt.exit_date}")

    # 重疊標的差距
    sim_map = {r.ticker: r.pnl for r in stats["entered_trades"]}
    print()
    print(f"── 重疊標的 (週報推薦 ∩ user 交易) ────────────────────────────")
    overlap_gap = 0.0
    for tk, spnl in sorted(sim_map.items()):
        rpnl = user_pnl_by_ticker.get(tk)
        if rpnl is not None:
            g = rpnl - spnl
            overlap_gap += g
            name = get_stock_name(tk)
            print(f"  {tk} {name:8s}  模擬:{spnl:+,.0f}  真實:{rpnl:+,.0f}  差:{g:+,.0f}")
    print(f"  重疊差距合計: ${overlap_gap:+,.0f}")

    # 非週報主要虧損
    phase5b_tickers = set(tk for r in ALL_REPORTS for tk in r.tickers)
    non_report = [(tk, pnl) for tk, pnl in user_pnl_by_ticker.items()
                  if tk not in phase5b_tickers and pnl < -5000]
    if non_report:
        print()
        print(f"── 非週報標的主要虧損 (user 自選) ─────────────────────────────")
        for tk, pnl in sorted(non_report, key=lambda x: x[1])[:5]:
            print(f"  {tk}  ${pnl:+,.0f}")

    # 生成報告
    if args.report:
        _STRAT_DIR.mkdir(parents=True, exist_ok=True)
        report_path = _STRAT_DIR / "phase5b_may_onwards_only_review.md"
        md_content = format_report(results, stats, user_pnl_total, user_pnl_by_ticker)
        report_path.write_text(md_content, encoding="utf-8")
        print()
        print(f"報告已寫出: {report_path}")
    else:
        print()
        print("(加 --report 可寫出完整 markdown 報告)")


if __name__ == "__main__":
    main()
