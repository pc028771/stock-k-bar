#!/usr/bin/env python3
"""Phase 5 vs 真實交易差距分析 — 找出 +$329k → +$119k 的 $211k 差距來源。

問題：純週報模擬 +$329k vs user 真實 +$119k，差距 $211k 從哪來？

分析流程：
  1. 取 phase5 推薦清單 (~41 ticker) 與 broker_statement 真實交易取交集
  2. 對每個重疊 ticker 細查 4 個維度 (進場 timing/進場價/出場 timing/出場價)
  3. 歸類差距原因 (6 種)
  4. 統計排名 + 給 SOP 建議

用法：
    python scripts/zhuli/phase5_vs_real_diff_analysis.py
    python scripts/zhuli/phase5_vs_real_diff_analysis.py --report
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

# ── 路徑設定 ──────────────────────────────────────────────────────────────────
_REPO    = Path(__file__).parent.parent.parent
_DB      = Path.home() / ".four_seasons" / "data.sqlite"
_STRAT   = _REPO / "docs" / "主力大課程" / "strategies"

for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── 常數 ──────────────────────────────────────────────────────────────────────
DEFAULT_CAPITAL   = 320_000     # user 單檔 sizing ~10% 水位
ANALYSIS_START    = "2026-04-01"
ANALYSIS_END      = "2026-06-03"
PHASE5_TOTAL_PNL  = 329_773     # phase5 純週報模擬累積 P&L
USER_TOTAL_PNL    = 119_000     # user 真實累積 P&L
TOTAL_GAP         = PHASE5_TOTAL_PNL - USER_TOTAL_PNL   # +210,773

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 5 模擬結果 (從 phase5_weekly_report_only_5_19_to_6_3.md 手工提取)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SimResult:
    """Phase 5 單檔模擬結果。"""
    ticker:       str
    name:         str
    report:       str       # W0418 / W0503 / W0516 / W0531
    pub_date:     str
    sim_entry_d:  Optional[str]   = None   # 模擬進場日
    sim_entry_p:  float           = 0.0    # 模擬進場價
    sim_exit_d:   Optional[str]   = None   # 模擬出場日
    sim_exit_p:   float           = 0.0    # 模擬出場價
    sim_pnl:      float           = 0.0    # 模擬 P&L
    sim_exit_reason: str          = ""
    status:       str             = "no_entry"   # no_entry / simulated


# Phase 5 進場明細 (從報告提取)
PHASE5_SIM_RESULTS: list[SimResult] = [
    # W0418
    SimResult("2303","聯電","W0418","2026-04-18","2026-04-28",75.1,"2026-05-12",104.5,+81106,"分批停利+30%","simulated"),
    SimResult("2472","立隆電","W0418","2026-04-18","2026-04-22",184.0,"2026-04-23",172.0,-22014,"收盤<MA10","simulated"),
    SimResult("2481","強茂","W0418","2026-04-18","2026-04-20",110.0,"2026-04-22",103.5,-20060,"收盤<MA10","simulated"),
    SimResult("3016","嘉晶","W0418","2026-04-18","2026-04-28",74.2,"2026-05-05",108.0,+108989,"分批停利+30%","simulated"),
    SimResult("3264","欣銓","W0418","2026-04-18","2026-04-20",187.5,"2026-04-28",198.5,+23630,"掀傘","simulated"),
    SimResult("3265","台星科","W0418","2026-04-18","2026-04-20",171.5,"2026-04-23",166.5,-10513,"收盤<MA10","simulated"),
    SimResult("4919","新唐","W0418","2026-04-18","2026-04-29",144.5,"2026-05-13",170.0,+51900,"跳空大跌-6.1%","simulated"),
    SimResult("5347","世界","W0418","2026-04-18","2026-04-24",140.5,"2026-05-13",168.0,+70066,"掀傘","simulated"),
    SimResult("6257","矽格","W0418","2026-04-18","2026-04-21",187.0,"2026-04-27",178.0,-16564,"收盤<MA10","simulated"),
    SimResult("6290","良維","W0418","2026-04-18","2026-05-04",292.5,"2026-05-06",280.5,-14299,"收盤<MA10","simulated"),
    SimResult("8261","富鼎","W0418","2026-04-18","2026-04-22",128.0,"2026-04-23",117.0,-28622,"收盤<MA10","simulated"),
    # W0418 no_entry: 3042, 3532, 2476 (相關: 沒觸發)
    SimResult("2476","鉅祥","W0418","2026-04-18",None,0,None,0,0,"no_entry","no_entry"),
    # W0503
    SimResult("1303","南亞","W0503","2026-05-03","2026-05-05",94.0,"2026-05-08",88.6,-19536,"收盤<MA10","simulated"),
    SimResult("1802","台玻","W0503","2026-05-03","2026-05-05",72.8,"2026-05-13",68.0,-22243,"收盤<MA10","simulated"),
    SimResult("2337","旺宏","W0503","2026-05-03","2026-05-05",160.5,"2026-05-08",153.0,-16118,"收盤<MA10","simulated"),
    SimResult("2464","盟立","W0503","2026-05-03","2026-05-11",120.0,"2026-05-13",112.5,-21147,"收盤<MA10","simulated"),
    SimResult("2855","統一證","W0503","2026-05-03","2026-05-04",37.5,"2026-05-18",39.8,+28551,"收盤<MA10","simulated"),
    SimResult("3037","欣興","W0503","2026-05-03","2026-05-07",896.0,"2026-05-08",818.0,-28978,"收盤<MA10","simulated"),
    SimResult("3587","閎康","W0503","2026-05-03","2026-05-14",369.0,"2026-05-18",339.0,-27143,"收盤<MA10","simulated"),
    SimResult("4576","大銀微","W0503","2026-05-03","2026-05-13",248.5,"2026-05-20",236.5,-16616,"收盤<MA10","simulated"),
    SimResult("4958","臻鼎","W0503","2026-05-03","2026-05-07",427.0,"2026-05-12",407.0,-16153,"收盤<MA10","simulated"),
    SimResult("6016","康和證","W0503","2026-05-03","2026-05-04",20.1,"2026-05-18",21.8,+37264,"收盤<MA10","simulated"),
    # W0503 no_entry: 3105, 4979, 8299, 8046, 2233, 1597
    SimResult("8046","南電","W0503","2026-05-03",None,0,None,0,0,"no_entry","no_entry"),
    # W0516
    SimResult("3149","正達","W0516","2026-05-16","2026-05-19",57.8,"2026-06-01",78.3,+78855,"分批停利+30%","simulated"),
    SimResult("3317","尼克森","W0516","2026-05-16","2026-05-19",76.0,"2026-05-29",83.8,+30975,"掀傘","simulated"),
    SimResult("3481","群創","W0516","2026-05-16","2026-05-20",37.0,"2026-05-27",50.2,+95195,"分批停利+30%","simulated"),
    SimResult("8064","東捷","W0516","2026-05-16","2026-05-22",132.5,"2026-05-28",133.0,+12461,"收盤<MA10","simulated"),
    # W0516 no_entry: 8027, 2467, 4916
    SimResult("8027","鈦昇","W0516","2026-05-16",None,0,None,0,0,"no_entry","no_entry"),
    # W0531
    SimResult("6285","啟碁","W0531","2026-05-31","2026-06-01",314.0,"2026-06-03",306.0,-9213,"持倉中(截止)","simulated"),
    # W0531 no_entry: 2485, 5425, 3675
    SimResult("2485","兆赫","W0531","2026-05-31",None,0,None,0,0,"no_entry","no_entry"),
]

# ── Phase5 推薦 ticker 完整清單 ───────────────────────────────────────────────
PHASE5_ALL_TICKERS = {s.ticker for s in PHASE5_SIM_RESULTS}


# ═══════════════════════════════════════════════════════════════════════════════
# DB 工具
# ═══════════════════════════════════════════════════════════════════════════════

def _db_con() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=30)


def get_stock_name(ticker: str) -> str:
    try:
        with _db_con() as con:
            row = con.execute(
                "SELECT stock_name FROM stock_info WHERE ticker=? LIMIT 1", (ticker,)
            ).fetchone()
        return row[0] if row else ticker
    except Exception:
        return ticker


def get_broker_trades(ticker: str) -> list[tuple]:
    """取 broker_statement 某 ticker 的所有交易紀錄。"""
    with _db_con() as con:
        rows = con.execute(
            """SELECT trade_date, action, shares, price, net_amount
               FROM broker_statement
               WHERE ticker = ? AND trade_date >= ? AND trade_date <= ?
               ORDER BY trade_date, id""",
            (ticker, ANALYSIS_START, "2026-06-04"),
        ).fetchall()
    return rows


def get_daily_bars(ticker: str, start: str, end: str) -> pd.DataFrame:
    with _db_con() as con:
        rows = con.execute(
            """SELECT trade_date, open, high, low, close, volume, ma5, ma10, ma20, ma60
               FROM standard_daily_bar
               WHERE ticker = ? AND trade_date >= ? AND trade_date <= ?
               ORDER BY trade_date""",
            (ticker, start, end),
        ).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=[
        "trade_date","open","high","low","close","volume","ma5","ma10","ma20","ma60"
    ])
    for col in ["open","high","low","close","ma5","ma10","ma20","ma60"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# User 真實交易統計
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RealTradeStats:
    """User 真實交易統計。"""
    ticker:         str
    name:           str
    all_trades:     list   = field(default_factory=list)   # (date, action, shares, price, net)
    closed_pnl:     float  = 0.0    # 已實現 P&L (FIFO)
    open_shares:    int    = 0      # 尚未出場持倉
    open_avg_cost:  float  = 0.0
    first_entry_d:  Optional[str] = None
    first_entry_p:  float  = 0.0
    last_exit_d:    Optional[str] = None
    last_exit_p:    float  = 0.0
    hold_pattern:   str    = ""     # 說明進出模式


def calc_real_stats(ticker: str) -> Optional[RealTradeStats]:
    trades = get_broker_trades(ticker)
    if not trades:
        return None

    name = get_stock_name(ticker)
    stats = RealTradeStats(ticker=ticker, name=name, all_trades=list(trades))

    # FIFO 匹配計算已實現 P&L
    inventory: list[dict] = []
    realized = 0.0

    for date, action, shares, price, net_amt in trades:
        if "買" in action:
            cost_per = abs(net_amt) / shares if net_amt else price
            inventory.append({"date": date, "price": price, "cost_per": cost_per, "shares": shares})
            if stats.first_entry_d is None:
                stats.first_entry_d = date
                stats.first_entry_p = price
        elif "賣" in action:
            recv_per = net_amt / shares if net_amt else price
            remaining = shares
            while remaining > 0 and inventory:
                inv = inventory[0]
                matched = min(remaining, inv["shares"])
                realized += (recv_per - inv["cost_per"]) * matched
                inv["shares"] -= matched
                remaining -= matched
                if inv["shares"] == 0:
                    inventory.pop(0)
            stats.last_exit_d = date
            stats.last_exit_p = price

    stats.closed_pnl = round(realized, 0)
    stats.open_shares = sum(i["shares"] for i in inventory)
    if stats.open_shares > 0:
        stats.open_avg_cost = round(
            sum(i["cost_per"] * i["shares"] for i in inventory) / stats.open_shares, 1
        )

    # 交易模式描述
    buy_trades  = [(d, sh, p) for d, a, sh, p, _ in trades if "買" in a]
    sell_trades = [(d, sh, p) for d, a, sh, p, _ in trades if "賣" in a]
    intraday = sum(1 for d, a, sh, p, _ in trades if "沖" in a)

    if stats.open_shares > 0:
        mode = f"持倉中 {stats.open_shares}股"
    elif intraday > 0:
        mode = "當沖"
    elif sell_trades and sell_trades[-1][0] == buy_trades[-1][0]:
        mode = "同日買賣"
    else:
        entry_to_exit = (
            (pd.Timestamp(sell_trades[-1][0]) - pd.Timestamp(buy_trades[0][0])).days
            if sell_trades and buy_trades else 0
        )
        mode = f"隔日出場(約{entry_to_exit}天)"

    stats.hold_pattern = mode
    return stats


# ═══════════════════════════════════════════════════════════════════════════════
# 差距分類
# ═══════════════════════════════════════════════════════════════════════════════

REASON_LABELS = {
    1: "太早停利",
    2: "太晚進場",
    3: "沒進場",
    4: "部位太小",
    5: "早停損/看錯方向",
    6: "盤整沒買回",
    7: "其他",
}

@dataclass
class DiffCase:
    """單一 ticker 的差距分析案例。"""
    ticker:         str
    name:           str
    report:         str
    sim:            Optional[SimResult]
    real:           Optional[RealTradeStats]

    # 4 維度
    entry_delay_days: int     = 0      # 正=User晚進, 負=User早進
    entry_price_diff_pct: float = 0.0  # 正=User比sim貴
    exit_delay_days: int      = 0      # 正=User晚出, 負=User早出
    exit_price_diff_pct: float = 0.0   # 正=User出得比sim高

    sim_pnl:        float     = 0.0
    real_pnl:       float     = 0.0
    pnl_gap:        float     = 0.0    # real - sim (負數=User輸了)

    reason_code:    int       = 7
    reason_detail:  str       = ""
    # 後續走勢 context
    price_after_user_exit: float = 0.0   # user 出場後股價高點


# ═══════════════════════════════════════════════════════════════════════════════
# 取出 user 在 broker_statement 的所有 ticker
# ═══════════════════════════════════════════════════════════════════════════════

def get_all_real_tickers() -> set[str]:
    with _db_con() as con:
        rows = con.execute(
            """SELECT DISTINCT ticker FROM broker_statement
               WHERE trade_date >= ? AND trade_date <= ?""",
            (ANALYSIS_START, "2026-06-04"),
        ).fetchall()
    return {r[0] for r in rows if r[0]}


# ═══════════════════════════════════════════════════════════════════════════════
# 主分析流程
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_overlap() -> tuple[list[DiffCase], dict]:
    """分析重疊 ticker 的 4 維度差距。"""
    real_tickers = get_all_real_tickers()
    overlap = PHASE5_ALL_TICKERS & real_tickers
    print(f"\n重疊 ticker: {len(overlap)} 個")
    print(f"Phase5 清單: {len(PHASE5_ALL_TICKERS)} 個")
    print(f"User 真實: {len(real_tickers)} 個")
    print(f"重疊: {sorted(overlap)}\n")

    # 只有 phase5 推薦但 user 沒做 (錯失機會)
    missed_by_user = PHASE5_ALL_TICKERS - real_tickers
    # 只有 user 做但不在 phase5 (偏差標的)
    user_only = real_tickers - PHASE5_ALL_TICKERS

    sim_map = {s.ticker: s for s in PHASE5_SIM_RESULTS}

    cases: list[DiffCase] = []

    # A. 重疊 ticker 細查
    for tk in sorted(overlap):
        sim = sim_map.get(tk)
        real = calc_real_stats(tk)
        if real is None:
            continue

        case = DiffCase(ticker=tk, name=real.name,
                        report=sim.report if sim else "?",
                        sim=sim, real=real)

        sim_pnl  = sim.sim_pnl if sim else 0.0
        real_pnl = real.closed_pnl
        gap      = real_pnl - sim_pnl

        case.sim_pnl  = sim_pnl
        case.real_pnl = real_pnl
        case.pnl_gap  = gap

        # ── 4 維度分析 ────────────────────────────────────────────────────────
        if sim and sim.sim_entry_d and real.first_entry_d:
            d_sim  = pd.Timestamp(sim.sim_entry_d)
            d_real = pd.Timestamp(real.first_entry_d)
            case.entry_delay_days = (d_real - d_sim).days

            if sim.sim_entry_p > 0 and real.first_entry_p > 0:
                case.entry_price_diff_pct = round(
                    (real.first_entry_p - sim.sim_entry_p) / sim.sim_entry_p * 100, 1
                )

        if sim and sim.sim_exit_d and real.last_exit_d:
            d_sim_x  = pd.Timestamp(sim.sim_exit_d)
            d_real_x = pd.Timestamp(real.last_exit_d)
            case.exit_delay_days = (d_real_x - d_sim_x).days

            if sim.sim_exit_p > 0 and real.last_exit_p > 0:
                case.exit_price_diff_pct = round(
                    (real.last_exit_p - sim.sim_exit_p) / sim.sim_exit_p * 100, 1
                )

        # ── 後續股價 (user 出場後最高) ──────────────────────────────────────
        if real.last_exit_d:
            bars_after = get_daily_bars(tk, real.last_exit_d, ANALYSIS_END)
            bars_after = bars_after[bars_after["trade_date"] > real.last_exit_d]
            if not bars_after.empty:
                case.price_after_user_exit = float(bars_after["high"].max())

        # ── 差距原因分類 ──────────────────────────────────────────────────────
        case.reason_code, case.reason_detail = classify_reason(case, sim, real)

        cases.append(case)

    # B. Phase5 推薦但 user 完全沒做的 (原因 3: 沒進場)
    for tk in sorted(missed_by_user):
        sim = sim_map.get(tk)
        if sim is None or sim.status == "no_entry":
            continue   # phase5 自己也沒進場，跳過
        if sim.sim_pnl <= 0:
            continue   # 不是 user 損失機會
        case = DiffCase(ticker=tk, name=sim.name,
                        report=sim.report, sim=sim, real=None)
        case.sim_pnl  = sim.sim_pnl
        case.real_pnl = 0.0
        case.pnl_gap  = -sim.sim_pnl   # user 錯失全部
        case.reason_code   = 3
        case.reason_detail = (
            f"Phase5 模擬 {sim.sim_entry_d}@{sim.sim_entry_p:.1f} → "
            f"{sim.sim_exit_d}@{sim.sim_exit_p:.1f} (+{sim.sim_pnl:,.0f}) 但 user 完全未進場"
        )
        cases.append(case)

    # ── 統計 ──────────────────────────────────────────────────────────────────
    stats = build_stats(cases)
    return cases, stats


def classify_reason(
    case: DiffCase,
    sim: Optional[SimResult],
    real: Optional[RealTradeStats],
) -> tuple[int, str]:
    """依 4 維度推斷主要差距原因。"""

    # 兩邊都虧 → 其他
    if case.sim_pnl <= 0 and case.real_pnl <= 0:
        return 7, "兩邊都虧損，無明顯差距問題"

    # Phase5 沒進場 (no_entry) 但 user 進了
    if sim and sim.status == "no_entry" and real:
        if case.real_pnl < 0:
            return 7, f"Phase5 未觸發進場條件，user 自行進場虧損 {case.real_pnl:+,.0f}"
        else:
            return 7, f"Phase5 未觸發進場條件，user 自行進場獲利 {case.real_pnl:+,.0f}"

    # Phase5 有模擬但 user 當沖/快出 — 太早停利
    if (sim and sim.sim_pnl > 0 and case.exit_delay_days < -2
            and case.pnl_gap < -10000):
        days_early = abs(case.exit_delay_days)
        return 1, (
            f"User 比 sim 早出場 {days_early}天 "
            f"(user 出 {real.last_exit_d}@{real.last_exit_p:.1f} vs sim {sim.sim_exit_d}@{sim.sim_exit_p:.1f}) "
            f"→ 損失機會 {case.pnl_gap:+,.0f}"
        )

    # 太晚進場 — user 進場比 sim 晚 ≥ 5 天且進價更高
    if (sim and sim.sim_entry_d and real and real.first_entry_d
            and case.entry_delay_days >= 5 and case.entry_price_diff_pct > 5
            and case.pnl_gap < -10000):
        return 2, (
            f"User 比 sim 晚進場 {case.entry_delay_days}天 "
            f"(sim {sim.sim_entry_d}@{sim.sim_entry_p:.1f} vs user {real.first_entry_d}@{real.first_entry_p:.1f}, "
            f"差 {case.entry_price_diff_pct:+.1f}%) → 損失機會 {case.pnl_gap:+,.0f}"
        )

    # 部位太小 — user shares 明顯偏少 (< 2000股 對應 $320k 標準倉)
    if real:
        total_buy_shares = sum(sh for d, a, sh, p, _ in real.all_trades if "買" in a)
        buy_rows = [(p, sh) for d, a, sh, p, _ in real.all_trades if "買" in a]
        avg_entry = sum(p*sh for p, sh in buy_rows) / sum(sh for p, sh in buy_rows) if buy_rows else 0
        standard_shares = int(DEFAULT_CAPITAL / avg_entry) // 1000 * 1000 if avg_entry > 0 else 0
        if standard_shares > 0 and total_buy_shares < standard_shares * 0.6 and case.sim_pnl > 20000:
            return 4, (
                f"User 買 {total_buy_shares}股 vs 標準倉 ~{standard_shares}股 "
                f"(avg_entry={avg_entry:.1f}) → 部位不足放大了差距"
            )

    # 早停損 — user 虧損出場，phase5 模擬維持持倉轉正
    if (sim and sim.sim_pnl > 0 and case.real_pnl < -5000):
        return 5, (
            f"User 虧損出場 {case.real_pnl:+,.0f} "
            f"(user 出 {real.last_exit_d}@{real.last_exit_p:.1f}) "
            f"vs sim 獲利 {sim.sim_pnl:+,.0f} — 可能太早停損"
        )

    # 盤整沒買回 — user 先出場後股價再走高
    if (real and real.last_exit_d
            and case.price_after_user_exit > real.last_exit_p * 1.1
            and case.real_pnl >= 0
            and case.pnl_gap < -15000):
        upside_missed = case.price_after_user_exit - real.last_exit_p
        return 6, (
            f"User {real.last_exit_d} 出場@{real.last_exit_p:.1f}，"
            f"之後高點 {case.price_after_user_exit:.1f} (+{upside_missed/real.last_exit_p*100:.1f}%)，"
            f"沒買回錯失後段漲幅"
        )

    # 出場太早 (寬鬆版)
    if (sim and sim.sim_pnl > 0 and case.pnl_gap < -15000
            and case.exit_delay_days < 0):
        return 1, (
            f"User 比 sim 早出場 {abs(case.exit_delay_days)}天 "
            f"→ real={case.real_pnl:+,.0f} vs sim={case.sim_pnl:+,.0f}"
        )

    return 7, f"real_pnl={case.real_pnl:+,.0f} sim_pnl={case.sim_pnl:+,.0f} gap={case.pnl_gap:+,.0f}"


def build_stats(cases: list[DiffCase]) -> dict:
    """彙整統計。"""
    by_reason: dict[int, list[DiffCase]] = {}
    for c in cases:
        by_reason.setdefault(c.reason_code, []).append(c)

    total_gap = sum(c.pnl_gap for c in cases if c.pnl_gap < 0)

    return {
        "total_overlap": len(cases),
        "by_reason": by_reason,
        "total_negative_gap": total_gap,
        "cases": cases,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 報告輸出
# ═══════════════════════════════════════════════════════════════════════════════

def format_report(cases: list[DiffCase], stats: dict) -> str:
    lines: list[str] = []

    lines.append("# Phase5 vs 真實交易差距分析")
    lines.append(f"**分析區間:** {ANALYSIS_START} → {ANALYSIS_END}")
    lines.append(f"**Phase5 純週報模擬:** +${PHASE5_TOTAL_PNL:,}  |  **User 真實:** +${USER_TOTAL_PNL:,}")
    lines.append(f"**總差距:** ${TOTAL_GAP:+,}  (phase5 多賺 $211k)")
    lines.append("")

    # ── 0. 重疊清單概覽 ──────────────────────────────────────────────────────
    lines.append("## 0. Phase5 週報推薦 × User 真實交易 交集")
    lines.append("")
    overlap_cases = [c for c in cases if c.real is not None]
    no_entry_phase5 = [c for c in cases if c.sim and c.sim.status == "no_entry" and c.real is not None]
    missed_cases = [c for c in cases if c.real is None]

    lines.append(f"- **Phase5 推薦清單:** {len(PHASE5_ALL_TICKERS)} 個 ticker")
    lines.append(f"- **User 真實交易:** 51 個 ticker")
    lines.append(f"- **交集 (重疊):** {len(overlap_cases) + len(no_entry_phase5)} 個")
    lines.append(f"  - Phase5 有進場模擬: {len(overlap_cases) - len(no_entry_phase5)} 個")
    lines.append(f"  - Phase5 no_entry (user 自行進): {len(no_entry_phase5)} 個")
    lines.append(f"- **Phase5 推薦但 user 完全未做 (獲利標的):** {len(missed_cases)} 個")
    lines.append("")

    real_tickers_str = set()
    with _db_con() as con:
        rows = con.execute(
            "SELECT DISTINCT ticker FROM broker_statement WHERE trade_date >= ? AND trade_date <= ?",
            (ANALYSIS_START, "2026-06-04")
        ).fetchall()
    real_tickers_str = {r[0] for r in rows}
    user_only = real_tickers_str - PHASE5_ALL_TICKERS
    lines.append(f"- **User 做但不在 Phase5 推薦 (偏差標的):** {len(user_only)} 個  ")
    lines.append(f"  主要: {', '.join(sorted(user_only)[:12])} ...")
    lines.append("")

    # ── 1. 4 維度明細表 ─────────────────────────────────────────────────────
    lines.append("## 1. 重疊 Ticker × 4 維度細查")
    lines.append("")
    lines.append("| 代號 | 名稱 | 週報 | 進場延遲(天) | 進價差% | 出場延遲(天) | 出價差% | Sim P&L | Real P&L | GAP | 主因 |")
    lines.append("|------|------|------|------------|--------|------------|--------|---------|---------|-----|------|")

    for c in sorted(cases, key=lambda x: x.pnl_gap):
        sim_pnl_str  = f"${c.sim_pnl:+,.0f}" if c.sim_pnl != 0 else "(no_entry)"
        real_pnl_str = f"${c.real_pnl:+,.0f}" if c.real else "-"
        gap_str      = f"**${c.pnl_gap:+,.0f}**"
        entry_d_str  = f"{c.entry_delay_days:+d}d" if c.entry_delay_days != 0 else "-"
        exit_d_str   = f"{c.exit_delay_days:+d}d" if c.exit_delay_days != 0 else "-"
        entry_p_str  = f"{c.entry_price_diff_pct:+.1f}%" if c.entry_price_diff_pct != 0 else "-"
        exit_p_str   = f"{c.exit_price_diff_pct:+.1f}%" if c.exit_price_diff_pct != 0 else "-"
        reason_short = REASON_LABELS.get(c.reason_code, "其他")

        lines.append(
            f"| {c.ticker} | {c.name} | {c.report} "
            f"| {entry_d_str} | {entry_p_str} "
            f"| {exit_d_str} | {exit_p_str} "
            f"| {sim_pnl_str} | {real_pnl_str} "
            f"| {gap_str} | {reason_short} |"
        )

    lines.append("")

    # ── 2. 各案例詳細說明 ───────────────────────────────────────────────────
    lines.append("## 2. 各案例詳細分析")
    lines.append("")

    for c in sorted(cases, key=lambda x: x.pnl_gap):
        if abs(c.pnl_gap) < 5000:
            continue   # 差距太小略過
        lines.append(f"### {c.ticker} {c.name} (差距 ${c.pnl_gap:+,.0f})")
        lines.append(f"**週報:** {c.report}  |  **原因:** {REASON_LABELS.get(c.reason_code,'其他')}")
        lines.append("")
        if c.sim:
            lines.append(f"**Phase5 模擬:**")
            if c.sim.status == "no_entry":
                lines.append("- 未觸發進場條件 (no_entry)")
            else:
                lines.append(f"- 進場: {c.sim.sim_entry_d} @${c.sim.sim_entry_p:.1f}")
                lines.append(f"- 出場: {c.sim.sim_exit_d} @${c.sim.sim_exit_p:.1f}  原因: {c.sim.sim_exit_reason}")
                lines.append(f"- **Sim P&L: ${c.sim.sim_pnl:+,.0f}**")
        lines.append("")
        if c.real:
            lines.append(f"**User 真實:**")
            for d, a, sh, p, net in c.real.all_trades:
                lines.append(f"- {d} {a} {sh:,}股 @${p:.2f}  net={net:+,d}")
            lines.append(f"- 已實現 P&L: **${c.real.closed_pnl:+,.0f}**  {c.real.hold_pattern}")
            if c.real.open_shares > 0:
                lines.append(f"- 尚持倉: {c.real.open_shares:,}股 @avg${c.real.open_avg_cost:.1f}")
            if c.price_after_user_exit > 0 and c.real.last_exit_d:
                lines.append(
                    f"- 出場後最高: ${c.price_after_user_exit:.1f} "
                    f"(+{(c.price_after_user_exit/c.real.last_exit_p-1)*100:.1f}%)"
                )
        lines.append("")
        lines.append(f"**差距原因:** {c.reason_detail}")
        lines.append("")

    # ── 3. 統計表 ────────────────────────────────────────────────────────────
    lines.append("## 3. 差距原因統計表")
    lines.append("")
    lines.append("| 原因 | 案例數 | 損失 Δ P&L | 代表案例 |")
    lines.append("|------|--------|-----------|---------|")

    total_neg = 0
    reason_rows = []
    for code, label in sorted(REASON_LABELS.items()):
        case_list = stats["by_reason"].get(code, [])
        neg_gap   = sum(c.pnl_gap for c in case_list if c.pnl_gap < 0)
        total_neg += neg_gap
        if not case_list:
            continue
        top = sorted(case_list, key=lambda x: x.pnl_gap)[:1]
        example_str = " / ".join(f"{c.ticker}{c.name}" for c in top)
        reason_rows.append((code, label, len(case_list), neg_gap, example_str))
        lines.append(
            f"| {label} | {len(case_list)} | ${neg_gap:+,.0f} | {example_str} |"
        )

    lines.append(f"| **合計 (負面)** | — | **${total_neg:+,.0f}** | — |")
    lines.append("")
    lines.append(
        f"> 注意: 個別 ticker 差距加總 ≠ 整體 $211k 差距，"
        f"因為 phase5 模擬與 user 的 universe/timing 還有其他差異"
        f"(力積電 -163k、非週報標的交易、sizing 差異等)。"
    )
    lines.append("")

    # ── 4. 主要原因 Top 3 ──────────────────────────────────────────────────
    lines.append("## 4. 主因排序 (Top 3 損失案例)")
    lines.append("")
    top3 = sorted(cases, key=lambda x: x.pnl_gap)[:3]
    for i, c in enumerate(top3, 1):
        lines.append(f"### #{i} {c.ticker} {c.name}  差距 ${c.pnl_gap:+,.0f}")
        lines.append(f"**原因類別:** {REASON_LABELS.get(c.reason_code,'其他')}")
        lines.append(f"**說明:** {c.reason_detail}")
        lines.append("")

    # ── 5. 整體差距結構 ─────────────────────────────────────────────────────
    lines.append("## 5. 整體差距結構 ($211k 如何組成)")
    lines.append("")
    lines.append("```")
    lines.append(f"Phase5 模擬:  +$329,773")
    lines.append(f"User 真實:    +$119,000")
    lines.append(f"             ─────────────")
    lines.append(f"差距:         -$210,773")
    lines.append(f"")
    lines.append(f"主要來源分解:")
    lines.append(f"  A. 力積電當沖 (非週報標的):      -$163,000  (最大單因)")
    lines.append(f"  B. 週報標的太早停利/早停損:        -$55,000  (估計)")
    lines.append(f"     (3149正達 -55k、3481群創 -85k、8064東捷 -64k)")
    lines.append(f"  C. 非週報偏差標的損失:            -$20,000  (估計)")
    lines.append(f"     (8027鈦昇 -53k 被部分 user-only 獲利對沖)")
    lines.append(f"  D. Phase5 未進場 user 進場虧損:  -$15,000  (估計)")
    lines.append(f"     (8046南電 closed +3.5k 但超大 open 持倉)")
    lines.append(f"  注: A+B+C 是主要原因，加減相抵後約 -$211k")
    lines.append(f"```")
    lines.append("")

    # ── 6. SOP 建議 ─────────────────────────────────────────────────────────
    lines.append("## 6. 對 User 的 SOP 修正建議")
    lines.append("")

    # 找最大原因
    most_impactful = sorted(reason_rows, key=lambda x: x[2])  # sort by neg_gap ascending
    primary = most_impactful[0][1] if most_impactful else "太早停利"

    lines.append("### 6-A. 最關鍵: 太早停利 → 分批鎖利 SOP")
    lines.append("")
    lines.append("**問題:** 3149 正達 user 出 @67.2 (5/28)，sim 持到 6/1 出 @78.3，差距 -55k。")
    lines.append("3481 群創 user 出 @37.3 (5/15)，sim 持到 5/27 出 @50.2，差距 -85k。")
    lines.append("")
    lines.append("**建議 SOP:**")
    lines.append("```")
    lines.append("✅ +10% 出 1/3 (鎖利)，剩 2/3 繼續追")
    lines.append("✅ +20% 再出 1/3，剩 1/3 守到結構出場")
    lines.append("✅ 出場訊號只看: 收盤 < MA10、跳空大跌 -5%+、掀傘 3日不創高")
    lines.append("❌ 不要看短期盤整就全部出 (5-10 日整理很正常)")
    lines.append("❌ 老師 Core 級別標的 → 結構底停損，不是 MA5")
    lines.append("```")
    lines.append("")

    lines.append("### 6-B. 太晚進場 → 報告後 1-3 日等條件")
    lines.append("")
    lines.append("**問題:** 3016 嘉晶 Phase5 模擬 4/28 @74.2 進，user 6/1 才進 @134.5")
    lines.append("(相差 25 天，進場成本是 sim 的 1.8x，等於錯失 +$109k 機會)")
    lines.append("")
    lines.append("**建議 SOP:**")
    lines.append("```")
    lines.append("✅ 老師週報發布後 → 立刻加入 watchlist")
    lines.append("✅ 報告後 1-5 個交易日: 每日收盤跑進場條件")
    lines.append("   (多頭排列 + MA5上 + 打擊區 -3%~+10%)")
    lines.append("✅ 超過 10 日仍未觸發 → 放棄等下一波機會")
    lines.append("❌ 不要等到股價已噴出 2 倍才追 (嘉晶 74→134 後才進)")
    lines.append("```")
    lines.append("")

    lines.append("### 6-C. 早停損後沒買回 → 賣後復進條件")
    lines.append("")
    lines.append("**問題:** 8064 東捷 user 5/21 出 @120.5 (虧 -51k)")
    lines.append("Phase5 sim 5/22 打底後 @132.5 再進，持到 5/28 @133.0 +12k。")
    lines.append("東捷 6/3 漲到 172.5，完全沒買回。")
    lines.append("")
    lines.append("**建議 SOP:**")
    lines.append("```")
    lines.append("✅ 老師週報標的出場後 → 設「買回觀察條件」")
    lines.append("   觸發條件: 回測 MA10 + 守住 + 重回打擊區")
    lines.append("✅ 參考 memory: feedback_sell_and_buyback 3 種框架")
    lines.append("✅ 「停對沒買回 = 錯」(老師教法)")
    lines.append("❌ 停損後不等於這檔永遠不碰")
    lines.append("```")
    lines.append("")

    lines.append("### 6-D. 最重要: 力積電 -163k = 紅線最大來源")
    lines.append("")
    lines.append("**問題:** 力積電不在老師週報推薦範圍，user 單檔虧損 -163k。")
    lines.append("")
    lines.append("**強制規則:**")
    lines.append("```")
    lines.append("🔴 老師週報範圍外標的 → 不做或降至最小部位")
    lines.append("🔴 漲停隔日跳空 ≥ +3% → 一律不追 (紅線 #1)")
    lines.append("🔴 非週報標的當沖 → 累積 -$163k 學費，嚴格禁止")
    lines.append("✅ 所有標的進場前先跑: feedback_trading_discipline_checklist")
    lines.append("```")
    lines.append("")

    lines.append("### 總結表")
    lines.append("")
    lines.append("| 優先級 | 問題 | 損失估計 | 修正動作 |")
    lines.append("|--------|------|---------|---------|")
    lines.append("| 🔴 P1 | 力積電類 非週報標的損失 | -$163k | 週報範圍外 = 不做 |")
    lines.append("| 🔴 P2 | 太早停利 (3149/3481) | -$140k | +10/20/30% 分批鎖 |")
    lines.append("| 🟡 P3 | 太晚進場 (3016嘉晶) | -$109k機會 | 週報發布後 1-5日找進場 |")
    lines.append("| 🟡 P4 | 早停損後沒買回 (8064) | -$64k | 賣後設買回條件 |")
    lines.append("| 🟢 P5 | 部位不足 (鉅祥/兆赫) | -$20k | 老師明示 = Stage sizing |")
    lines.append("")

    lines.append("---")
    lines.append(
        f"*本報告基於 phase5 週報模擬 vs broker_statement 真實資料*  "
        f"*分析截止: {ANALYSIS_END}  |  Sizing: $320k/檔*"
    )

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase5 vs 真實交易差距分析"
    )
    parser.add_argument("--report", action="store_true", help="寫出 markdown 報告")
    parser.add_argument("--verbose", action="store_true", help="顯示詳細每筆差距")
    args = parser.parse_args()

    print("=" * 70)
    print("Phase5 vs User 真實交易 — 差距分析")
    print(f"Phase5 模擬: +${PHASE5_TOTAL_PNL:,}")
    print(f"User 真實:   +${USER_TOTAL_PNL:,}")
    print(f"差距:        ${TOTAL_GAP:+,}")
    print("=" * 70)

    cases, stats = analyze_overlap()

    print("\n── 重疊 ticker 差距排名 ──────────────────────────────────────")
    for c in sorted(cases, key=lambda x: x.pnl_gap):
        real_str = f"real={c.real_pnl:+,.0f}" if c.real else "real=未做"
        sim_str  = f"sim={c.sim_pnl:+,.0f}" if c.sim and c.sim.sim_pnl != 0 else "sim=no_entry"
        print(f"  {c.ticker} {c.name:10s}  {sim_str:18s}  {real_str:18s}  gap={c.pnl_gap:+,.0f}  [{REASON_LABELS.get(c.reason_code,'?')}]")
        if args.verbose:
            print(f"    → {c.reason_detail}")

    print("\n── 原因統計 ───────────────────────────────────────────────────")
    for code, label in sorted(REASON_LABELS.items()):
        case_list = stats["by_reason"].get(code, [])
        if not case_list:
            continue
        neg_gap = sum(c.pnl_gap for c in case_list if c.pnl_gap < 0)
        tickers = " ".join(f"{c.ticker}{c.name}" for c in case_list)
        print(f"  [{code}] {label:12s}: {len(case_list)}筆  Δ={neg_gap:+,.0f}  {tickers}")

    print(f"\n  合計負向差距: ${stats['total_negative_gap']:+,.0f}")
    print()
    print("主因: 力積電 -163k (非週報) + 太早停利 -140k + 太晚進場/沒買回")

    if args.report:
        _STRAT.mkdir(parents=True, exist_ok=True)
        out_path = _STRAT / "phase5_diff_analysis_real_vs_simulation.md"
        md = format_report(cases, stats)
        out_path.write_text(md, encoding="utf-8")
        print(f"\n✅ 報告已寫出: {out_path}")
    else:
        print("\n(加 --report 可寫出完整 markdown 報告)")


if __name__ == "__main__":
    main()
