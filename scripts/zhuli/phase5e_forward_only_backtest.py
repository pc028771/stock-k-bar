#!/usr/bin/env python3
"""Phase 5e — 純 Forward-Looking Universe Backtest (修正 Lookahead Bias)。

問題：phase5b/c/d 的 universe 混入了週報「段1 崩盤筆記本」(回顧性資料)，
      導致 +$110k / +$987k / +$2.37M 等數字包含 lookahead bias。

修正：只用真正 forward-looking 的訊號來源：
  ✅ 週報「段2 本週新聞題材」— 老師對下週的前瞻分析
  ✅ 培訓影片 / Line 群 / 直播（5/21+ 來源）— 發佈時的當下觀點
  ❌ 週報「段1 回顧本週漲幅 6%+ 族群崩盤筆記本」— 回顧性、lookahead bias

對比：
  phase5b (含段1)  : +$110,670 (96% 來自 lookahead bias)
  phase5e (純段2)  : 重跑計算真實 forward P&L

用法:
    python scripts/zhuli/phase5e_forward_only_backtest.py
    python scripts/zhuli/phase5e_forward_only_backtest.py --verbose
    python scripts/zhuli/phase5e_forward_only_backtest.py --report
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
_REPO = Path(__file__).parent.parent.parent
_DB = MAIN_DB
_STRAT_DIR = _REPO / "docs" / "主力大課程" / "strategies"

for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.db import get_conn, MAIN_DB
# ── 費率 ──────────────────────────────────────────────────────────────────────
FEE_RATE = 0.000399   # 0.0399% 手續費
TAX_RATE = 0.003      # 0.3% 證交稅 (賣方)

# ── Sizing ────────────────────────────────────────────────────────────────────
DEFAULT_CAPITAL = 320_000   # 10% 水位 = $320k

# ── 分析區間 ──────────────────────────────────────────────────────────────────
ANALYSIS_START = "2026-05-01"
ANALYSIS_END   = "2026-06-03"

# ═══════════════════════════════════════════════════════════════════════════════
# 1. FORWARD-ONLY Universe 定義
#
# 選股依據：只來自以下來源（不含週報段1崩盤筆記本）
#
# ❌ 排除的標的（段1崩盤筆記本，已知這週漲的標的）:
#   W0503: 2337旺宏 8299群聯 8046南電 3037欣興 4958臻鼎 2233宇隆
#          4576大銀微 1597直得 2464盟立（機器人族群）
#   W0516: 3317尼克森 3481群創 3149正達（面板族群）
#          6207雷科（崩盤筆記本「玻璃設備」）
#
# ✅ 保留的標的（週報段2「本週新聞題材」+ 培訓/Line）
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ForwardSignal:
    """一個 forward-looking 訊號。"""
    ticker:      str
    name:        str           # 顯示用
    signal_date: str           # 老師明示日 (YYYY-MM-DD)
    source:      str           # 來源說明
    theme:       str           # 族群/主題
    lookahead:   bool = False  # True = 有 lookahead 疑慮 (標記用，不進場)


# ── 週報段2「本週新聞題材」— 每篇報告獨立分析，不依賴崩盤筆記本 ─────────────

# W0503 段2 — 本週新聞題材（2026-05-03 發佈）
# 段2明確分析: CPO / 成熟製程 / 玻纖布 / 5月產業:證券股
W0503_SEG2: list[ForwardSignal] = [
    ForwardSignal("3105", "穩懋",   "2026-05-03", "W0503段2-CPO",   "CPO 光引擎"),
    ForwardSignal("4979", "華星光", "2026-05-03", "W0503段2-CPO",   "CPO"),
    ForwardSignal("3587", "閎康",   "2026-05-03", "W0503段2-CPO",   "CPO 檢測"),
    ForwardSignal("2303", "聯電",   "2026-05-03", "W0503段2-成熟",  "成熟製程 22nm"),
    ForwardSignal("5347", "世界先進","2026-05-03", "W0503段2-成熟",  "成熟製程/GaN"),
    ForwardSignal("1802", "台玻",   "2026-05-03", "W0503段2-玻纖布","玻纖布 CCL漲價"),
    ForwardSignal("1303", "南亞",   "2026-05-03", "W0503段2-玻纖布","玻纖布"),
    ForwardSignal("2855", "統一證", "2026-05-03", "W0503段2-證券",  "兆元成交量 證券"),
    ForwardSignal("6016", "康和證", "2026-05-03", "W0503段2-證券",  "兆元成交量 證券"),
]

# W0516 段2 — 本週新聞題材（2026-05-16 發佈）
# 段2明確分析: 玻璃基板 CoPoS / 工業電腦+低軌衛星
W0516_SEG2: list[ForwardSignal] = [
    ForwardSignal("8027", "鈦昇",   "2026-05-16", "W0516段2-玻璃基板","CoPoS TGV 雷射設備"),
    ForwardSignal("8064", "東捷",   "2026-05-16", "W0516段2-玻璃基板","CoPoS 先進封裝設備"),
    ForwardSignal("2467", "志聖",   "2026-05-16", "W0516段2-玻璃基板","CoWoS G2C+ PCB設備"),
    ForwardSignal("4916", "事欣科", "2026-05-16", "W0516段2-低軌衛星","低軌衛星+工業電腦"),
]

# W0531 段2 — 本週新聞題材（2026-05-31 發佈）
# 段2明確分析: 低軌衛星 / 功率元件 / GaN/SiC磊晶
W0531_SEG2: list[ForwardSignal] = [
    ForwardSignal("6285", "啟碁",   "2026-05-31", "W0531段2-低軌衛星","低軌衛星地面接收"),
    ForwardSignal("2485", "兆赫",   "2026-05-31", "W0531段2-低軌衛星","低軌衛星終端"),
    ForwardSignal("5425", "台半",   "2026-05-31", "W0531段2-功率元件","MOSFET 缺貨漲價"),
    ForwardSignal("2481", "強茂",   "2026-05-31", "W0531段2-功率元件","MOSFET IDM 交期30週"),
    ForwardSignal("3016", "嘉晶",   "2026-05-31", "W0531段2-SiC",    "SiC/GaN 磊晶 小量產"),
    ForwardSignal("3675", "德微",   "2026-05-31", "W0531段2-SiC",    "SiC 概念"),
]

# 培訓影片 / Line 群 (5/21 起，全部 forward-looking)
TRAINING_LINE: list[ForwardSignal] = [
    ForwardSignal("6139", "亞翔",     "2026-05-21", "Line-5/21",  "潔淨室 擴廠"),
    ForwardSignal("2404", "漢唐",     "2026-05-21", "Line-5/21",  "潔淨室 EPC"),
    ForwardSignal("3708", "上緯投控", "2026-05-21", "Line-5/21",  "碳纖維/複合材料"),
    ForwardSignal("4722", "國精化",   "2026-05-21", "Line-5/21",  "光阻/特用化學"),
    ForwardSignal("1727", "中華化",   "2026-05-21", "培訓-5/21",  "特用化學"),
    ForwardSignal("3443", "創意",     "2026-05-21", "培訓-5/21",  "ASIC 設計服務"),
    ForwardSignal("4749", "新應材",   "2026-05-21", "Line-5/21",  "CB股/材料"),
    ForwardSignal("2481", "強茂",     "2026-05-22", "Line-5/22",  "功率元件 (Line確認)"),
    ForwardSignal("2351", "順德",     "2026-05-22", "Line-5/22",  "融資觀察清單"),
    ForwardSignal("6285", "啟碁",     "2026-05-23", "直播-5/23",  "低軌衛星 (直播確認)"),
    ForwardSignal("3675", "德微",     "2026-05-23", "直播-5/23",  "SiC (直播確認)"),
    ForwardSignal("5439", "高技",     "2026-05-25", "Line-5/25",  "PCB 高密度"),
    ForwardSignal("6182", "合晶",     "2026-05-25", "Line-5/25",  "矽晶圓 (矽晶圓三劍客)"),
    ForwardSignal("3265", "台星科",   "2026-05-25", "Line-5/25",  "中小封測 CPO"),
    ForwardSignal("6282", "康舒",     "2026-05-26", "晚課-5/26",  "電源/電供"),
]

# ── 組合所有 forward-only signals ─────────────────────────────────────────────
ALL_FORWARD_SIGNALS: list[ForwardSignal] = (
    W0503_SEG2 + W0516_SEG2 + W0531_SEG2 + TRAINING_LINE
)

# 去重（同 ticker 保留最早訊號）
_seen: set[str] = set()
DEDUPED_SIGNALS: list[ForwardSignal] = []
for s in sorted(ALL_FORWARD_SIGNALS, key=lambda x: x.signal_date):
    if s.ticker not in _seen and not s.lookahead:
        _seen.add(s.ticker)
        DEDUPED_SIGNALS.append(s)


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
# 3. 進場邏輯 (同 phase5b — 多頭排列 + MA5 + 打擊區)
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
# 4. 出場邏輯 (同 phase5b)
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

    # P5: 分批停利
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
# 5. 單一 Ticker 模擬
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SimTrade:
    ticker:      str
    name:        str
    source:      str
    signal_date: str
    theme:       str
    entry_date:  Optional[str]  = None
    entry_price: float          = 0.0
    exit_date:   Optional[str]  = None
    exit_price:  float          = 0.0
    exit_reason: str            = ""
    pnl:         float          = 0.0
    pnl_pct:     float          = 0.0
    capital:     float          = DEFAULT_CAPITAL
    entry_triggered_on: str     = ""
    status:      str            = "no_entry"
    max_profit_pct: float       = 0.0
    hold_days:   int            = 0


def simulate_ticker(
    signal: ForwardSignal,
    all_trading_dates: list[str],
    bars: pd.DataFrame,
    verbose: bool = False,
) -> SimTrade:
    name = get_stock_name(signal.ticker)
    trade = SimTrade(
        ticker      = signal.ticker,
        name        = name,
        source      = signal.source,
        signal_date = signal.signal_date,
        theme       = signal.theme,
        capital     = DEFAULT_CAPITAL,
    )

    if bars.empty:
        trade.status = "no_data"
        return trade

    monitor_dates = [d for d in all_trading_dates if d > signal.signal_date]
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
                print(f"  [進場] {signal.ticker} {name}  @{entry_date}  ${entry_price:.2f}  {reason[:70]}")
            break
        else:
            if verbose:
                print(f"  [等待] {signal.ticker} {name}  {d}  未觸發: {reason}")

    if entry_price is None:
        trade.status = "no_entry"
        return trade

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
                print(f"  [出場] {signal.ticker}  @{exit_d}  ${exit_price:.2f}  {reason}  P&L={trade.pnl:+,.0f}")
            return trade

        elif action == "take_profit":
            shares_out = ratio * shares_held
            shares_total = DEFAULT_CAPITAL / entry_price
            gross_partial = (exit_price - entry_price) * shares_total * shares_out
            fee_partial   = exit_price * shares_total * shares_out * (FEE_RATE + TAX_RATE)
            partial_pnl  += gross_partial - fee_partial
            shares_held  -= shares_out
            if verbose:
                print(f"  [停利] {signal.ticker}  @{exit_d}  ${exit_price:.2f}  {reason}  "
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
# 6. 回測主流程
# ═══════════════════════════════════════════════════════════════════════════════

def run_backtest(verbose: bool = False) -> list[SimTrade]:
    all_dates = get_trading_dates(ANALYSIS_START, ANALYSIS_END)

    results: list[SimTrade] = []

    # 按訊號來源分群列印
    source_groups = {}
    for sig in DEDUPED_SIGNALS:
        grp = sig.source.split("-")[0]  # W0503段2 / W0516段2 / W0531段2 / Line / 培訓 / 直播
        if grp not in source_groups:
            source_groups[grp] = []
        source_groups[grp].append(sig)

    for grp_key, signals in source_groups.items():
        print(f"\n=== {grp_key} ({len(signals)} 檔) ===")
        for sig in signals:
            print(f"  監控: {sig.ticker} {sig.name} [{sig.signal_date}] {sig.theme}")

    print(f"\n共 {len(DEDUPED_SIGNALS)} 個 forward-only 訊號\n")
    print("=" * 60)

    for sig in DEDUPED_SIGNALS:
        load_start = (pd.Timestamp(sig.signal_date) - pd.Timedelta(days=100)).strftime("%Y-%m-%d")
        bars = load_daily_bars(sig.ticker, load_start, ANALYSIS_END)

        trade = simulate_ticker(
            signal=sig,
            all_trading_dates=all_dates,
            bars=bars,
            verbose=verbose,
        )
        results.append(trade)

        status_str = {
            "no_data":  "無資料",
            "no_entry": "無進場訊號",
            "open":     "持倉中",
            "closed":   "已出場",
        }.get(trade.status, trade.status)
        pnl_str = f"P&L={trade.pnl:+,.0f}" if trade.entry_date else ""
        src_short = sig.source[:15]
        print(f"  {sig.ticker} {trade.name:8s}  [{src_short:15s}]  {status_str}  {pnl_str}")

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 7. 分析 & 報告生成
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

    # 按來源分群
    by_source: dict = {}
    for r in results:
        grp = r.source.split("-")[0] if r.source else "unknown"
        if grp not in by_source:
            by_source[grp] = {"entered": 0, "pnl": 0}
        if r.entry_date:
            by_source[grp]["entered"] += 1
            by_source[grp]["pnl"] += r.pnl

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
        "by_source": by_source,
        "entered_trades": entered,
    }


def format_report(results: list[SimTrade], stats: dict) -> str:
    lines: list[str] = []

    lines.append("# Phase 5e — 純 Forward-Looking Universe Backtest 報告")
    lines.append("")
    lines.append("**修正說明:** 排除週報段1「崩盤筆記本」(retrospective/lookahead bias)，")
    lines.append("只用週報段2「本週新聞題材」+ 培訓影片/Line (forward-looking)。")
    lines.append(f"**分析區間:** {ANALYSIS_START} → {ANALYSIS_END}")
    lines.append(f"**Forward-only ticker 數:** {stats['total']} 個")
    lines.append("")

    # 對比表
    lines.append("## 0. 版本對比 (Lookahead 修正前後)")
    lines.append("")
    lines.append("| 版本 | Universe | 總 P&L | Lookahead 說明 |")
    lines.append("|------|---------|--------|---------------|")
    lines.append("| phase5b (5月起3篇週報) | 29檔 | +$110,670 | 96%來自段1崩盤筆記本 |")
    lines.append("| phase5d (黑盒130檔) | 130檔 | +$2,375,108 | ~69%來自段1崩盤筆記本 |")
    lines.append(f"| **phase5e (純forward)** | **{stats['total']}檔** | **${stats['total_pnl']:+,.0f}** | **0% lookahead** |")
    lines.append("")

    # 進場明細
    lines.append("## 1. 進場模擬明細")
    lines.append("")
    lines.append("| 來源 | 代號 | 名稱 | 訊號日 | 進場日 | 進場價 | 出場日 | 出場原因 | P&L | 最大浮盈 |")
    lines.append("|------|------|------|--------|--------|--------|--------|----------|-----|---------|")

    for r in sorted(stats["entered_trades"], key=lambda r: (r.signal_date, r.ticker)):
        entry_d  = r.entry_date or "-"
        exit_d   = r.exit_date or "持倉中"
        exit_p   = f"${r.exit_price:.1f}" if r.exit_price else "-"
        pnl_str  = f"**{r.pnl:+,.0f}**" if r.pnl != 0 else "-"
        reason   = r.exit_reason[:28] if r.exit_reason else "持倉中"
        src_short = r.source[:15]
        lines.append(
            f"| {src_short} | {r.ticker} | {r.name} "
            f"| {r.signal_date} | {entry_d} | ${r.entry_price:.1f} "
            f"| {exit_d} | {reason} "
            f"| {pnl_str} "
            f"| {r.max_profit_pct:+.1f}% |"
        )
    lines.append("")

    no_entry_list = [r for r in results if not r.entry_date and r.status == "no_entry"]
    if no_entry_list:
        lines.append(f"**未觸發進場 ({len(no_entry_list)} 檔):** "
                     + " / ".join(f"{r.ticker}{r.name}" for r in no_entry_list[:25]))
        lines.append("")

    # 統計
    lines.append("## 2. 統計")
    lines.append("")
    lines.append(f"| 指標 | 數值 |")
    lines.append(f"|------|------|")
    lines.append(f"| Forward ticker 總數 | {stats['total']} 檔 |")
    lines.append(f"| 成功進場 | {stats['entered']} 檔 |")
    lines.append(f"| 進場觸發率 | {stats['entered']/max(stats['total'],1)*100:.1f}% |")
    lines.append(f"| 已出場 | {stats['closed']} 檔 |")
    lines.append(f"| 仍持倉 | {stats['open_pos']} 檔 |")
    lines.append(f"| 未觸發 | {stats['no_entry']} 檔 |")
    lines.append(f"| **純 Forward P&L** | **${stats['total_pnl']:+,.0f}** |")
    lines.append(f"| 勝率 | {stats['win_rate']:.1f}% |")
    lines.append(f"| 平均單筆 | ${stats['avg_pnl']:+,.0f} |")
    lines.append(f"| 平均獲利 | ${stats['avg_win']:+,.0f} |")
    lines.append(f"| 平均虧損 | ${stats['avg_loss']:+,.0f} |")
    if stats["best_trade"]:
        bt = stats["best_trade"]
        lines.append(f"| 最佳單筆 | {bt.ticker}{bt.name} {bt.pnl:+,.0f} ({bt.pnl_pct:+.1f}%) |")
    if stats["worst_trade"]:
        wt = stats["worst_trade"]
        lines.append(f"| 最差單筆 | {wt.ticker}{wt.name} {wt.pnl:+,.0f} ({wt.pnl_pct:+.1f}%) |")
    lines.append("")

    # 來源分群
    lines.append("## 3. 各來源 P&L 分群")
    lines.append("")
    lines.append("| 來源 | 進場 | P&L |")
    lines.append("|------|------|-----|")
    for src, data in sorted(stats["by_source"].items()):
        lines.append(f"| {src} | {data['entered']} 檔 | ${data['pnl']:+,.0f} |")
    lines.append("")

    # 結論
    lines.append("## 4. Honest 結論")
    lines.append("")
    pnl = stats["total_pnl"]
    if pnl > 300000:
        verdict = "純 forward-only universe 仍有顯著正報酬，策略有效。"
    elif pnl > 0:
        verdict = "純 forward-only 有小幅正報酬，但比 lookahead 版本低很多。"
    elif pnl > -100000:
        verdict = "純 forward-only 接近損益平衡，不能確定策略有 edge。"
    else:
        verdict = "純 forward-only 虧損，phase5b/5d 的高報酬幾乎全來自 lookahead bias。"

    lines.append(f"**結論:** {verdict}")
    lines.append("")
    lines.append("| 項目 | 數字 |")
    lines.append("|------|------|")
    lines.append(f"| phase5b 含 lookahead | +$110,670 |")
    lines.append(f"| phase5b lookahead 部分 (3481/3149/3317) | +$205,425 |")
    lines.append(f"| phase5b 排除 lookahead | -$94,755 |")
    lines.append(f"| phase5d 含 lookahead | +$2,375,108 |")
    lines.append(f"| phase5d lookahead 估算 (69%) | ~+$1,635,000 |")
    lines.append(f"| phase5d forward 估算 (31%) | ~+$740,000 |")
    lines.append(f"| **phase5e 實際 forward P&L** | **${pnl:+,.0f}** |")
    lines.append("")
    lines.append("**對 user 的 honest 建議:**")
    lines.append("")
    if pnl > 100000:
        lines.append("- 即使排除 lookahead，週報段2 + 培訓影片的 forward 訊號仍有正報酬")
        lines.append("- 嚴格只跟週報段2 + 培訓影片，可期待每月正報酬")
    elif pnl > 0:
        lines.append("- Forward-only 勉強有正報酬，但 edge 不顯著")
        lines.append("- 需要更嚴格的進場條件或加入籌碼過濾才能提升 edge")
    else:
        lines.append("- Phase5b/5d 的高報酬主要來自 lookahead bias，不是真實 edge")
        lines.append("- 真實 forward-only 策略仍需改進（進場條件、出場優化）")
    lines.append("")
    lines.append("---")
    lines.append("*本報告使用 phase5e_forward_only_backtest.py 生成。*")
    lines.append(f"*分析截止: {ANALYSIS_END}  |  Sizing: $320k/檔*")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 5e — 純 Forward-Looking Universe Backtest"
    )
    parser.add_argument("--verbose", action="store_true", help="顯示每日進出場細節")
    parser.add_argument("--report",  action="store_true", help="寫出 markdown 報告")
    args = parser.parse_args()

    print("=" * 70)
    print("Phase 5e — 純 Forward-Looking Universe Backtest")
    print("(排除週報段1崩盤筆記本 lookahead bias)")
    print(f"分析區間: {ANALYSIS_START} ~ {ANALYSIS_END}")
    print(f"Forward-only signals: {len(DEDUPED_SIGNALS)} 個")
    print()
    print("修正依據:")
    print("  phase5b +$110,670 → 96% 來自段1 lookahead (3481/3149/3317)")
    print("  phase5d +$2,375,108 → ~69% 來自段1 lookahead 估算")
    print("=" * 70)

    results = run_backtest(verbose=args.verbose)
    stats   = analyze_results(results)

    print()
    print("=" * 70)
    print("統計結果")
    print("=" * 70)
    print(f"Forward ticker: {stats['total']} 檔  進場觸發: {stats['entered']} 檔  "
          f"(觸發率 {stats['entered']/max(stats['total'],1)*100:.1f}%)")
    print(f"已出場: {stats['closed']} 筆  仍持倉: {stats['open_pos']} 筆  "
          f"無訊號: {stats['no_entry']} 檔")
    print(f"勝率: {stats['win_rate']:.1f}%  "
          f"贏:{stats['winners']} 輸:{stats['losers']}")
    print()
    print(f"★ 純 Forward P&L: ${stats['total_pnl']:+,.0f}")
    print()
    print("── 對比 ────────────────────────────────────────────────────────")
    print(f"  phase5b (含 lookahead):   +$110,670")
    print(f"  phase5b (純 forward 估算): +$4,257")
    print(f"  phase5d (含 lookahead):   +$2,375,108")
    print(f"  phase5d (純 forward 估算): ~+$740,000")
    print(f"  phase5e (實際 forward):   ${stats['total_pnl']:+,.0f}")
    print()

    print("── 各來源 P&L ──────────────────────────────────────────────────")
    for src, data in sorted(stats["by_source"].items()):
        print(f"  {src:20s}: 進場 {data['entered']} 檔  P&L={data['pnl']:+,.0f}")

    if stats["best_trade"]:
        bt = stats["best_trade"]
        print(f"\n  最佳: {bt.ticker}{bt.name}  {bt.pnl:+,.0f} ({bt.pnl_pct:+.1f}%)  "
              f"@{bt.entry_date} → {bt.exit_date}")
    if stats["worst_trade"]:
        wt = stats["worst_trade"]
        print(f"  最差: {wt.ticker}{wt.name}  {wt.pnl:+,.0f} ({wt.pnl_pct:+.1f}%)  "
              f"@{wt.entry_date} → {wt.exit_date}")

    if args.report:
        _STRAT_DIR.mkdir(parents=True, exist_ok=True)
        report_path = _STRAT_DIR / "phase5e_forward_only_backtest_result.md"
        md_content = format_report(results, stats)
        report_path.write_text(md_content, encoding="utf-8")
        print(f"\n報告已寫出: {report_path}")
    else:
        print("\n(加 --report 可寫出完整 markdown 報告)")


if __name__ == "__main__":
    main()
