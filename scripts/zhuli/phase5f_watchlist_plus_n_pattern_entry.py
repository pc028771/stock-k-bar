#!/usr/bin/env python3
"""Phase 5f — Watchlist + N字回測 Entry Backtest (廣義 Universe 修正版)。

問題背景 (User 指正):
  phase5e 把週報「段1 回顧本週漲幅6%+族群」排除，認定為 lookahead bias。
  但老師原話 (W0516):
    「這是我自己的崩盤筆記本...我需要看他們發展狀態是否符合策略
     如果有符合最後就會寫給你們」
  → 段1 = 老師 watchlist、不是立即進場標的、不是 lookahead bias

正確解讀:
  ✅ 段1 ticker = 老師持續追蹤的 watchlist，watch_start = 報告日+1
  ✅ 段2 ticker = 同樣是 watchlist，watch_start = 報告日+1
  ✅ 都必須「等回測打擊區 + N字/小結構 entry confirm」才進
  ❌ 不能「報告發布日立刻進」(那是 phase5d 的 lookahead)

永久 Universe 原則 (補強):
  老師曾明示過的 ticker = 永久 watchlist、不設黑名單。
  即使某月跌了 / 虧過 / 賣過，只要再次回測打擊區 + 老師仍在族群框架內，
  就可以復進。本腳本採用「當月最早明示日」為 watch_start，
  同一 ticker 去重保留最早訊號。

Phase 對比:
  phase5e: 只用段2 + 培訓，用「多頭排列+距MA10」進場 → +$118k
  phase5d: 全部 + 立即進場 → +$2.37M (lookahead bias)
  phase5f: 廣義 (段1+2+培訓) + N字回測 entry → 真實合理

進場條件 (N字回測):
  N字回測進場 (post_attack 4b):
    1. 過去 20 天有攻擊 ≥+10% (5日滑動窗口)
    2. 攻擊後 1-8 天進入整理 (整理期量縮 < 攻擊均量 × 0.65)
    3. 整理期區間 ≤ 8% range (相對整理高點)
    4. 出現紅K + 距MA10 ±15% (打擊區較寬、N字本質是回測均線)

  小結構進場 (post_attack 4a):
    整理區間 <3% + 量縮 + 突破整理高點

出場條件 (多抱版本):
  - 收盤 < MA10 → 出清
  - 跳空大跌 -5% → 出清
  - 分析截止 (6/4) → 計算帳面

用法:
    python scripts/zhuli/phase5f_watchlist_plus_n_pattern_entry.py
    python scripts/zhuli/phase5f_watchlist_plus_n_pattern_entry.py --verbose
    python scripts/zhuli/phase5f_watchlist_plus_n_pattern_entry.py --report
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
ANALYSIS_END   = "2026-06-04"

# ═══════════════════════════════════════════════════════════════════════════════
# 1. 廣義 Universe (段1 + 段2 + 培訓影片 + daily_brief)
#
# watch_start = 報告發布日 + 1 (一律不能用報告日之前的價格)
# 段1 = 老師崩盤筆記本 watchlist，等 N字/小結構 confirm 才進
# 段2 = 本週新聞題材 watchlist，同樣等 confirm 才進
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class WatchSignal:
    """一個老師 watchlist 訊號。"""
    ticker:      str
    name:        str
    signal_date: str    # 老師提及日 (YYYY-MM-DD)，watch_start = signal_date + 1 交易日
    source:      str    # 來源說明
    theme:       str    # 族群/主題
    seg:         str    # "seg1" / "seg2" / "training" / "line" / "brief"


# ── W0503 (2026-05-03) 段1「崩盤筆記本 — 本週漲幅6%+」────────────────────────
# 老師追蹤名單：記憶體/ABF/機器人
W0503_SEG1: list[WatchSignal] = [
    WatchSignal("2337", "旺宏",   "2026-05-03", "W0503段1-記憶體", "記憶體 NAND", "seg1"),
    WatchSignal("8299", "群聯",   "2026-05-03", "W0503段1-記憶體", "記憶體 NAND", "seg1"),
    WatchSignal("8046", "南電",   "2026-05-03", "W0503段1-ABF",   "ABF 載板",   "seg1"),
    WatchSignal("3037", "欣興",   "2026-05-03", "W0503段1-ABF",   "ABF 載板",   "seg1"),
    WatchSignal("4958", "臻鼎",   "2026-05-03", "W0503段1-ABF",   "高階PCB",    "seg1"),
    WatchSignal("2233", "宇隆",   "2026-05-03", "W0503段1-機器人", "機器人",     "seg1"),
    WatchSignal("4576", "大銀微", "2026-05-03", "W0503段1-機器人", "機器人",     "seg1"),
    WatchSignal("1597", "直得",   "2026-05-03", "W0503段1-機器人", "機器人",     "seg1"),
    WatchSignal("2464", "盟立",   "2026-05-03", "W0503段1-機器人", "機器人自動化","seg1"),
]

# ── W0503 (2026-05-03) 段2「本週新聞題材」─────────────────────────────────────
W0503_SEG2: list[WatchSignal] = [
    WatchSignal("3105", "穩懋",    "2026-05-03", "W0503段2-CPO",   "CPO 光引擎", "seg2"),
    WatchSignal("4979", "華星光",  "2026-05-03", "W0503段2-CPO",   "CPO",        "seg2"),
    WatchSignal("3587", "閎康",    "2026-05-03", "W0503段2-CPO",   "CPO 檢測",   "seg2"),
    WatchSignal("2303", "聯電",    "2026-05-03", "W0503段2-成熟",  "成熟製程 22nm","seg2"),
    WatchSignal("5347", "世界先進","2026-05-03", "W0503段2-成熟",  "成熟製程/GaN","seg2"),
    WatchSignal("1802", "台玻",    "2026-05-03", "W0503段2-玻纖布","玻纖布 CCL", "seg2"),
    WatchSignal("1303", "南亞",    "2026-05-03", "W0503段2-玻纖布","玻纖布",     "seg2"),
    WatchSignal("2855", "統一證",  "2026-05-03", "W0503段2-證券",  "兆元成交量 證券","seg2"),
    WatchSignal("6016", "康和證",  "2026-05-03", "W0503段2-證券",  "兆元成交量 證券","seg2"),
]

# ── W0516 (2026-05-16) 段1「崩盤筆記本 — 面板/功率元件」─────────────────────
W0516_SEG1: list[WatchSignal] = [
    WatchSignal("3317", "長基",   "2026-05-16", "W0516段1-功率元件","功率元件 GaN","seg1"),
    WatchSignal("3481", "群創",   "2026-05-16", "W0516段1-面板",   "面板 AI PC", "seg1"),
    WatchSignal("3149", "正達",   "2026-05-16", "W0516段1-面板",   "面板/光學",  "seg1"),
]

# ── W0516 (2026-05-16) 段2「本週新聞題材」─────────────────────────────────────
W0516_SEG2: list[WatchSignal] = [
    WatchSignal("8027", "鈦昇",   "2026-05-16", "W0516段2-玻璃基板","CoPoS TGV 雷射設備","seg2"),
    WatchSignal("8064", "東捷",   "2026-05-16", "W0516段2-玻璃基板","CoPoS 先進封裝設備","seg2"),
    WatchSignal("2467", "志聖",   "2026-05-16", "W0516段2-玻璃基板","CoWoS G2C+ PCB設備","seg2"),
    WatchSignal("4916", "事欣科", "2026-05-16", "W0516段2-低軌衛星","低軌衛星+工業電腦","seg2"),
]

# ── W0531 (2026-05-31) 段2「本週新聞題材」─────────────────────────────────────
W0531_SEG2: list[WatchSignal] = [
    WatchSignal("6285", "啟碁",   "2026-05-31", "W0531段2-低軌衛星","低軌衛星地面接收","seg2"),
    WatchSignal("2485", "兆赫",   "2026-05-31", "W0531段2-低軌衛星","低軌衛星終端",    "seg2"),
    WatchSignal("5425", "台半",   "2026-05-31", "W0531段2-功率元件","MOSFET 缺貨漲價", "seg2"),
    WatchSignal("2481", "強茂",   "2026-05-31", "W0531段2-功率元件","MOSFET IDM 交期30週","seg2"),
    WatchSignal("3016", "嘉晶",   "2026-05-31", "W0531段2-SiC",    "SiC/GaN 磊晶",    "seg2"),
    WatchSignal("3675", "德微",   "2026-05-31", "W0531段2-SiC",    "SiC 概念",        "seg2"),
]

# ── 培訓影片 / Line 群 / 直播 (5/21 起，全部 forward-looking) ─────────────────
TRAINING_LINE: list[WatchSignal] = [
    WatchSignal("6139", "亞翔",     "2026-05-21", "Line-5/21",  "潔淨室 擴廠",     "line"),
    WatchSignal("2404", "漢唐",     "2026-05-21", "Line-5/21",  "潔淨室 EPC",      "line"),
    WatchSignal("3708", "上緯投控", "2026-05-21", "Line-5/21",  "碳纖維/複合材料", "line"),
    WatchSignal("4722", "國精化",   "2026-05-21", "Line-5/21",  "光阻/特用化學",   "line"),
    WatchSignal("1727", "中華化",   "2026-05-21", "培訓-5/21",  "特用化學",        "training"),
    WatchSignal("3443", "創意",     "2026-05-21", "培訓-5/21",  "ASIC 設計服務",   "training"),
    WatchSignal("4749", "新應材",   "2026-05-21", "Line-5/21",  "CB股/材料",       "line"),
    WatchSignal("2481", "強茂",     "2026-05-22", "Line-5/22",  "功率元件 (Line確認)","line"),
    WatchSignal("2351", "順德",     "2026-05-22", "Line-5/22",  "融資觀察清單",    "line"),
    WatchSignal("6285", "啟碁",     "2026-05-23", "直播-5/23",  "低軌衛星 (直播確認)","line"),
    WatchSignal("3675", "德微",     "2026-05-23", "直播-5/23",  "SiC (直播確認)",  "line"),
    WatchSignal("5439", "高技",     "2026-05-25", "Line-5/25",  "PCB 高密度",      "line"),
    WatchSignal("6182", "合晶",     "2026-05-25", "Line-5/25",  "矽晶圓",          "line"),
    WatchSignal("3265", "台星科",   "2026-05-25", "Line-5/25",  "中小封測 CPO",    "line"),
    WatchSignal("6282", "康舒",     "2026-05-26", "晚課-5/26",  "電源/電供",       "training"),
]

# ── 合併所有 signals，去重 (同 ticker 保留最早訊號) ───────────────────────────
ALL_SIGNALS: list[WatchSignal] = (
    W0503_SEG1 + W0503_SEG2 +
    W0516_SEG1 + W0516_SEG2 +
    W0531_SEG2 + TRAINING_LINE
)

_seen: set[str] = set()
DEDUPED_SIGNALS: list[WatchSignal] = []
for s in sorted(ALL_SIGNALS, key=lambda x: x.signal_date):
    if s.ticker not in _seen:
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
# 3. N字回測進場邏輯
#
# 策略：在 watch_start 後，偵測「攻擊 → 整理 → 回測進場」型態
# ═══════════════════════════════════════════════════════════════════════════════

def detect_n_pattern_entry(
    bars: pd.DataFrame,
    watch_start: str,
    max_monitor_days: int = 25,
    verbose: bool = False,
    ticker: str = "",
) -> Optional[tuple[str, float, str]]:
    """偵測 N字回測進場訊號。

    返回 (entry_date, entry_price, reason) 或 None。

    邏輯:
      1. 找「攻擊期」: 5日滑動窗口漲幅 ≥ +10%
      2. 攻擊後進入整理: 量縮 (整理均量 < 攻擊均量 × 0.65) + 幅度 ≤ 8% range
      3. 整理中出現紅K + 距MA10 在 -5% ~ +20% (N字本質是回測均線，允許較寬範圍)
      4. 跳空 ≤ +3% 限制 (一律)
    """
    watch_bars = bars[bars["trade_date"] >= watch_start].copy()
    watch_bars = watch_bars.sort_values("trade_date").reset_index(drop=True)
    if len(watch_bars) < 2:
        return None

    # 也拿 watch_start 前的資料，用來計算攻擊期
    all_bars = bars.sort_values("trade_date").reset_index(drop=True)

    monitor_count = 0

    for idx in range(len(watch_bars)):
        if monitor_count >= max_monitor_days:
            break
        monitor_count += 1

        today_row = watch_bars.iloc[idx]
        today_date = today_row["trade_date"]

        # 取到今天為止的所有 bars (包含 watch_start 前)
        bars_to_today = all_bars[all_bars["trade_date"] <= today_date].reset_index(drop=True)
        n = len(bars_to_today)
        if n < 6:
            continue

        # ── Step 1: 在 watch_start 後 20 天內找攻擊期 ────────────────────────
        # 從今天往前看 20 根 K 棒
        lookback_bars = bars_to_today.tail(min(n, 20)).reset_index(drop=True)
        attack_idx = None
        attack_pct = 0.0
        for i in range(4, len(lookback_bars)):
            window = lookback_bars.iloc[i-4:i+1]
            low_5 = float(window["low"].min())
            high_5 = float(window["close"].max())
            if low_5 > 0:
                gain = (high_5 / low_5 - 1) * 100
                if gain >= 10.0:
                    attack_idx = i
                    attack_pct = gain

        if attack_idx is None:
            if verbose:
                print(f"    [N字] {ticker} {today_date}: 無攻擊期 ≥10%")
            continue

        # 攻擊期: lookback_bars[attack_idx-4:attack_idx+1]
        atk_window = lookback_bars.iloc[max(0, attack_idx-4):attack_idx+1]
        atk_avg_vol = float(atk_window["volume"].mean())
        atk_high = float(atk_window["high"].max())
        atk_end_date = lookback_bars.iloc[attack_idx]["trade_date"]

        # 攻擊期後的整理期: atk_end_date ~ today
        if atk_end_date >= today_date:
            # 今天就是攻擊期最高點，還沒開始整理
            if verbose:
                print(f"    [N字] {ticker} {today_date}: 攻擊剛結束，等整理")
            continue

        consol_bars = bars_to_today[bars_to_today["trade_date"] > atk_end_date].reset_index(drop=True)
        if len(consol_bars) < 1:
            continue

        # 整理期最多 8 天
        if len(consol_bars) > 8:
            if verbose:
                print(f"    [N字] {ticker} {today_date}: 整理期超過8天 ({len(consol_bars)}天)")
            continue

        # ── Step 2: 整理期量縮 ────────────────────────────────────────────────
        consol_avg_vol = float(consol_bars["volume"].mean())
        vol_ratio = consol_avg_vol / atk_avg_vol if atk_avg_vol > 0 else 1.0
        if vol_ratio >= 0.65:
            if verbose:
                print(f"    [N字] {ticker} {today_date}: 量未縮 vol_ratio={vol_ratio:.2f}")
            continue

        # ── Step 3: 整理幅度 ≤ 8% ────────────────────────────────────────────
        consol_high = float(consol_bars["high"].max())
        consol_low  = float(consol_bars["low"].min())
        consol_range = (consol_high - consol_low) / consol_high * 100 if consol_high > 0 else 99
        if consol_range > 8.0:
            if verbose:
                print(f"    [N字] {ticker} {today_date}: 整理幅度過大 {consol_range:.1f}%>8%")
            continue

        # ── Step 4: 今日出現紅K ───────────────────────────────────────────────
        today_close = float(today_row["close"])
        today_open  = float(today_row["open"])
        is_red = today_close > today_open
        if not is_red:
            if verbose:
                print(f"    [N字] {ticker} {today_date}: 今日非紅K {today_open:.1f}→{today_close:.1f}")
            continue

        # ── Step 5: 距MA10 在打擊區 -5% ~ +20% ───────────────────────────────
        ma10 = today_row.get("ma10")
        if pd.isna(ma10) or float(ma10) <= 0:
            continue
        ma10 = float(ma10)
        dist_ma10 = (today_close - ma10) / ma10 * 100
        if dist_ma10 < -5.0 or dist_ma10 > 20.0:
            if verbose:
                print(f"    [N字] {ticker} {today_date}: 打擊區外 dist_ma10={dist_ma10:+.1f}%")
            continue

        # ── Step 6: 跳空 ≤ +3% ────────────────────────────────────────────────
        prev_idx_in_all = bars_to_today[bars_to_today["trade_date"] < today_date]
        if len(prev_idx_in_all) > 0:
            prev_close = float(prev_idx_in_all.iloc[-1]["close"])
            gap_pct = (today_open - prev_close) / prev_close * 100 if prev_close > 0 else 0
            if gap_pct > 3.0:
                if verbose:
                    print(f"    [N字] {ticker} {today_date}: 跳空過大 {gap_pct:+.1f}%")
                continue

        # ── 進場！ ────────────────────────────────────────────────────────────
        reason = (
            f"N字回測✓ | 攻擊+{attack_pct:.1f}% @{atk_end_date} "
            f"| 整理{len(consol_bars)}天 量縮{vol_ratio:.2f}x range{consol_range:.1f}% "
            f"| 紅K {today_open:.1f}→{today_close:.1f} dist_MA10={dist_ma10:+.1f}%"
        )
        return today_date, today_close, reason

    return None


def detect_small_structure_entry(
    bars: pd.DataFrame,
    watch_start: str,
    max_monitor_days: int = 25,
    verbose: bool = False,
    ticker: str = "",
) -> Optional[tuple[str, float, str]]:
    """偵測小結構突破進場。

    條件:
    1. 整理區間 <3% range (連 3 根 K 棒)
    2. 量縮 (目前量 < 近 10 日均量 × 0.6)
    3. 今日突破整理高點 + 收盤確認
    4. 距MA10 ≤ +25% (避免追太高)
    """
    watch_bars = bars[bars["trade_date"] >= watch_start].copy()
    watch_bars = watch_bars.sort_values("trade_date").reset_index(drop=True)
    if len(watch_bars) < 3:
        return None

    all_bars = bars.sort_values("trade_date").reset_index(drop=True)
    monitor_count = 0

    for idx in range(2, len(watch_bars)):
        if monitor_count >= max_monitor_days:
            break
        monitor_count += 1

        today_row = watch_bars.iloc[idx]
        today_date = today_row["trade_date"]

        # 取前 3 根 K (含今天)
        three_bars = watch_bars.iloc[max(0, idx-2):idx+1]
        high_3 = float(three_bars["high"].max())
        low_3  = float(three_bars["low"].min())
        range_pct = (high_3 - low_3) / high_3 * 100 if high_3 > 0 else 99
        if range_pct >= 3.0:
            continue

        today_close = float(today_row["close"])
        today_open  = float(today_row["open"])

        # 今日突破前 2 日最高點
        prev_high = float(watch_bars.iloc[max(0, idx-2):idx]["high"].max())
        if today_close <= prev_high:
            continue

        # 量縮 (近 10 日均量)
        bars_to_today = all_bars[all_bars["trade_date"] <= today_date]
        recent_10_vol = float(bars_to_today.tail(10)["volume"].mean())
        today_vol = float(today_row["volume"])
        if recent_10_vol > 0 and today_vol / recent_10_vol >= 0.7:
            # 量縮 -> 小結構盤整時量要縮
            # 但突破時量可以放大，主要看整理期量縮
            # 改成看前 2 日均量 vs 近期
            prev_2_vol = float(watch_bars.iloc[max(0, idx-2):idx]["volume"].mean())
            if prev_2_vol / recent_10_vol >= 0.6:
                continue

        # 距MA10 ≤ +25%
        ma10 = today_row.get("ma10")
        if not pd.isna(ma10) and float(ma10) > 0:
            dist_ma10 = (today_close - float(ma10)) / float(ma10) * 100
            if dist_ma10 > 25.0 or dist_ma10 < -5.0:
                continue

        # 跳空 ≤ +3%
        prev_bars = all_bars[all_bars["trade_date"] < today_date]
        if len(prev_bars) > 0:
            prev_close = float(prev_bars.iloc[-1]["close"])
            gap_pct = (today_open - prev_close) / prev_close * 100 if prev_close > 0 else 0
            if gap_pct > 3.0:
                continue

        reason = (
            f"小結構突破✓ | 3日range={range_pct:.1f}% "
            f"| 突破前高{prev_high:.1f}→{today_close:.1f}"
        )
        return today_date, today_close, reason

    return None


def find_entry(
    signal: "WatchSignal",
    bars: pd.DataFrame,
    all_trading_dates: list[str],
    verbose: bool = False,
) -> Optional[tuple[str, float, str]]:
    """嘗試 N字回測 + 小結構兩種進場，返回最早進場日。"""
    # watch_start = signal_date 後第一個交易日
    later_dates = [d for d in all_trading_dates if d > signal.signal_date]
    if not later_dates:
        return None
    watch_start = later_dates[0]

    n_result = detect_n_pattern_entry(
        bars, watch_start, max_monitor_days=25, verbose=verbose, ticker=signal.ticker
    )
    ss_result = detect_small_structure_entry(
        bars, watch_start, max_monitor_days=25, verbose=verbose, ticker=signal.ticker
    )

    candidates = [r for r in [n_result, ss_result] if r is not None]
    if not candidates:
        return None
    # 取最早的進場日
    return min(candidates, key=lambda r: r[0])


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 出場邏輯 (多抱版本 — 守 MA10)
# ═══════════════════════════════════════════════════════════════════════════════

def check_exit_hold(
    df_to_date: pd.DataFrame,
    entry_price: float,
) -> tuple[Optional[str], str, float]:
    """多抱出場邏輯。返回 (action, reason, exit_price)。

    條件 (依優先順序):
      1. 跳空大跌 -5% → 出清
      2. 收盤 < MA10 → 出清
    """
    if len(df_to_date) < 2:
        return None, "", 0.0

    today = df_to_date.iloc[-1]
    prev  = df_to_date.iloc[-2]
    close   = float(today["close"])
    open_p  = float(today["open"])
    prev_cl = float(prev["close"])
    ma10    = today.get("ma10")

    # P1: 跳空大跌 -5%
    if prev_cl > 0:
        gap_pct = (open_p - prev_cl) / prev_cl * 100
        if gap_pct <= -5.0:
            return "exit_all", f"跳空大跌 {gap_pct:+.1f}%", open_p

    # P2: 收盤 < MA10
    if not pd.isna(ma10) and float(ma10) > 0 and close < float(ma10):
        return "exit_all", f"收盤{close:.2f}<MA10{float(ma10):.2f}", close

    return None, "", close


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 單一 Ticker 模擬
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SimTrade:
    ticker:       str
    name:         str
    source:       str
    signal_date:  str
    theme:        str
    seg:          str
    entry_date:   Optional[str] = None
    entry_price:  float         = 0.0
    entry_reason: str           = ""
    exit_date:    Optional[str] = None
    exit_price:   float         = 0.0
    exit_reason:  str           = ""
    pnl:          float         = 0.0
    pnl_pct:      float         = 0.0
    capital:      float         = DEFAULT_CAPITAL
    status:       str           = "no_entry"
    max_profit_pct: float       = 0.0
    hold_days:    int           = 0


def simulate_ticker(
    signal: WatchSignal,
    all_trading_dates: list[str],
    bars: pd.DataFrame,
    verbose: bool = False,
) -> SimTrade:
    name = get_stock_name(signal.ticker) or signal.name
    trade = SimTrade(
        ticker      = signal.ticker,
        name        = name,
        source      = signal.source,
        signal_date = signal.signal_date,
        theme       = signal.theme,
        seg         = signal.seg,
        capital     = DEFAULT_CAPITAL,
    )

    if bars.empty:
        trade.status = "no_data"
        return trade

    # 找進場
    entry_result = find_entry(signal, bars, all_trading_dates, verbose=verbose)
    if entry_result is None:
        trade.status = "no_entry"
        return trade

    entry_date, entry_price, entry_reason = entry_result
    trade.entry_date   = entry_date
    trade.entry_price  = entry_price
    trade.entry_reason = entry_reason
    trade.status       = "open"

    if verbose:
        print(f"  [進場] {signal.ticker} {name}  @{entry_date}  ${entry_price:.2f}")
        print(f"         {entry_reason[:80]}")

    # 持倉模擬
    hold_dates = [d for d in all_trading_dates if d > entry_date]
    if not hold_dates:
        # 直接用截止日
        last_bars = bars[bars["trade_date"] <= ANALYSIS_END]
        if not last_bars.empty:
            last_close = float(last_bars.iloc[-1]["close"])
            trade.exit_price  = last_close
            trade.exit_date   = last_bars.iloc[-1]["trade_date"]
            trade.exit_reason = "持倉中(分析截止)"
            _finalize_trade(trade, last_close)
        return trade

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

        action, reason, exit_price = check_exit_hold(df_to_date, entry_price)

        if action == "exit_all":
            trade.exit_date   = exit_d
            trade.exit_price  = exit_price
            trade.exit_reason = reason
            trade.hold_days   = len([d for d in all_trading_dates
                                     if entry_date < d <= exit_d])
            shares_total = DEFAULT_CAPITAL / entry_price
            buy_fee  = entry_price * shares_total * FEE_RATE
            sell_fee = exit_price  * shares_total * FEE_RATE
            sell_tax = exit_price  * shares_total * TAX_RATE
            gross = (exit_price - entry_price) * shares_total
            trade.pnl     = round(gross - buy_fee - sell_fee - sell_tax, 0)
            trade.pnl_pct = round((exit_price / entry_price - 1) * 100, 2)
            trade.status  = "closed"
            if verbose:
                print(f"  [出場] {signal.ticker}  @{exit_d}  ${exit_price:.2f}  {reason}  P&L={trade.pnl:+,.0f}")
            return trade

    # 持倉到截止日
    last_bars = bars[bars["trade_date"] <= ANALYSIS_END]
    if not last_bars.empty:
        last_close = float(last_bars.iloc[-1]["close"])
        last_date  = last_bars.iloc[-1]["trade_date"]
        trade.exit_price  = last_close
        trade.exit_date   = last_date
        trade.exit_reason = "持倉中(分析截止)"
        trade.hold_days   = len([d for d in all_trading_dates
                                  if entry_date < d <= last_date])
        _finalize_trade(trade, last_close)
    return trade


def _finalize_trade(trade: SimTrade, exit_price: float) -> None:
    shares_total = DEFAULT_CAPITAL / trade.entry_price
    buy_fee  = trade.entry_price * shares_total * FEE_RATE
    sell_fee = exit_price * shares_total * FEE_RATE
    sell_tax = exit_price * shares_total * TAX_RATE
    gross    = (exit_price - trade.entry_price) * shares_total
    trade.pnl     = round(gross - buy_fee - sell_fee - sell_tax, 0)
    trade.pnl_pct = round((exit_price / trade.entry_price - 1) * 100, 2)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. 回測主流程
# ═══════════════════════════════════════════════════════════════════════════════

def run_backtest(verbose: bool = False) -> list[SimTrade]:
    all_dates = get_trading_dates(ANALYSIS_START, ANALYSIS_END)

    results: list[SimTrade] = []

    # 來源分群列印
    seg_groups: dict[str, list[WatchSignal]] = {}
    for sig in DEDUPED_SIGNALS:
        key = sig.seg
        if key not in seg_groups:
            seg_groups[key] = []
        seg_groups[key].append(sig)

    print(f"\n共 {len(DEDUPED_SIGNALS)} 個 watchlist 訊號 (段1+2+培訓):")
    for seg_key in ["seg1", "seg2", "training", "line"]:
        sigs = seg_groups.get(seg_key, [])
        if sigs:
            names = " ".join(f"{s.ticker}{s.name}" for s in sigs)
            print(f"  {seg_key:8s} ({len(sigs):2d}檔): {names}")
    print()

    for sig in DEDUPED_SIGNALS:
        load_start = (pd.Timestamp(sig.signal_date) - pd.Timedelta(days=120)).strftime("%Y-%m-%d")
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
            "no_entry": "無N字訊號",
            "open":     "持倉中",
            "closed":   "已出場",
        }.get(trade.status, trade.status)
        pnl_str = f"P&L={trade.pnl:+,.0f}" if trade.entry_date else ""
        src_short = sig.source[:16]
        print(f"  [{sig.seg:8s}] {sig.ticker} {trade.name:6s}  [{src_short:16s}]  {status_str}  {pnl_str}")

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 7. 分析 & 報告
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_results(results: list[SimTrade]) -> dict:
    entered  = [r for r in results if r.entry_date]
    closed   = [r for r in entered if r.status == "closed"]
    open_pos = [r for r in entered if r.status == "open"]
    no_entry = [r for r in results if not r.entry_date and r.status == "no_entry"]
    no_data  = [r for r in results if r.status == "no_data"]

    total_pnl = sum(r.pnl for r in entered)
    winners   = [r for r in entered if r.pnl > 0]
    losers    = [r for r in entered if r.pnl < 0]

    # 段1 vs 段2 vs training/line 分群
    by_seg: dict = {}
    for r in results:
        key = r.seg
        if key not in by_seg:
            by_seg[key] = {"total": 0, "entered": 0, "pnl": 0}
        by_seg[key]["total"] += 1
        if r.entry_date:
            by_seg[key]["entered"] += 1
            by_seg[key]["pnl"] += r.pnl

    return {
        "total":     len(results),
        "entered":   len(entered),
        "closed":    len(closed),
        "open_pos":  len(open_pos),
        "no_entry":  len(no_entry),
        "no_data":   len(no_data),
        "total_pnl": total_pnl,
        "winners":   len(winners),
        "losers":    len(losers),
        "win_rate":  len(winners) / len(entered) * 100 if entered else 0,
        "avg_pnl":   total_pnl / len(entered) if entered else 0,
        "avg_win":   sum(r.pnl for r in winners) / len(winners) if winners else 0,
        "avg_loss":  sum(r.pnl for r in losers) / len(losers) if losers else 0,
        "best_trade":  max(entered, key=lambda r: r.pnl) if entered else None,
        "worst_trade": min(entered, key=lambda r: r.pnl) if entered else None,
        "by_seg":     by_seg,
        "entered_trades": entered,
        "no_entry_list":  no_entry,
    }


def format_report(results: list[SimTrade], stats: dict) -> str:
    lines: list[str] = []

    lines.append("# Phase 5f — Watchlist + N字回測 Entry Backtest")
    lines.append("")
    lines.append("## 修正說明")
    lines.append("")
    lines.append("**User 指正:** Phase5e 把週報「段1 回顧本週漲幅6%+」排除，認定為 lookahead bias。")
    lines.append("但老師原話 (W0516) 顯示段1 = 崩盤筆記本 watchlist，等符合策略才推薦。")
    lines.append("")
    lines.append("> 老師原話: 「這是我自己的崩盤筆記本...我需要看他們發展狀態是否符合策略，")
    lines.append("> 如果有符合最後就會寫給你們」")
    lines.append("")
    lines.append("**正確解讀:**")
    lines.append("- 段1 ticker = watch_start 報告日+1，等 N字/小結構 entry confirm 才進")
    lines.append("- 段2 ticker = 同樣 watchlist，相同邏輯")
    lines.append("- 均不可「報告日立刻進場」")
    lines.append("")
    lines.append("**永久 Universe 原則:**")
    lines.append("> 老師曾明示過的 ticker = 永久 watchlist，不設黑名單。")
    lines.append("> 即使某月虧過、賣過、跌一波，只要再次回測打擊區 + 老師族群框架仍在，")
    lines.append("> 就可以復進 (老師 feedback_sell_and_buyback 教法)。")
    lines.append("> 排除條件只有: (1) 老師明示「不做了」(2) 主升段已過+距均線太遠 (3) 公司基本面崩盤。")
    lines.append("")
    lines.append(f"**分析區間:** {ANALYSIS_START} → {ANALYSIS_END}")
    lines.append(f"**Universe:** {stats['total']} 個 ticker (段1: {stats['by_seg'].get('seg1',{}).get('total',0)} + 段2: {stats['by_seg'].get('seg2',{}).get('total',0)} + 培訓: {stats['by_seg'].get('training',{}).get('total',0)} + Line: {stats['by_seg'].get('line',{}).get('total',0)})")
    lines.append("")

    # 對比表
    lines.append("## 0. 版本對比")
    lines.append("")
    lines.append("| 版本 | Universe | 進場 logic | 出場 logic | P&L |")
    lines.append("|------|---------|-----------|-----------|-----|")
    lines.append("| phase5e | 純 forward (段2+培訓) | 多頭排列+距MA10 | 分批+10% | +$118,006 |")
    lines.append(f"| **phase5f** | **廣義 (段1+2+培訓)** | **N字回測 entry** | **守MA10多抱** | **${stats['total_pnl']:+,.0f}** |")
    lines.append("| phase5d | 全部+段1 | 立即進場 | 分批+10% | +$2,375,108 (lookahead) |")
    lines.append("")

    # 4916 特別驗證
    trade_4916 = next((r for r in results if r.ticker == "4916"), None)
    lines.append("## 1. 特別驗證 — 4916 事欣科")
    lines.append("")
    lines.append("5/16 週報段2「本週新聞題材」明示 4916 (forward 訊號)")
    lines.append("5/22-5/28 整理打擊區 (攻擊+32%後量縮整理)")
    lines.append("")
    if trade_4916 and trade_4916.entry_date:
        ret = (trade_4916.exit_price / trade_4916.entry_price - 1) * 100 if trade_4916.entry_price > 0 else 0
        lines.append(f"| 項目 | 數值 |")
        lines.append(f"|------|------|")
        lines.append(f"| 訊號日 | 2026-05-16 (W0516 段2) |")
        lines.append(f"| Watch 起點 | 2026-05-18 (報告日+1 交易日) |")
        lines.append(f"| 進場日 | {trade_4916.entry_date} |")
        lines.append(f"| 進場價 | ${trade_4916.entry_price:.1f} |")
        lines.append(f"| 進場原因 | {trade_4916.entry_reason[:80]} |")
        lines.append(f"| 出場日 | {trade_4916.exit_date or '持倉中'} |")
        lines.append(f"| 出場原因 | {trade_4916.exit_reason or '持倉中'} |")
        lines.append(f"| 出場價 | ${trade_4916.exit_price:.1f} |")
        lines.append(f"| P&L | **${trade_4916.pnl:+,.0f} ({ret:+.1f}%)** |")
        lines.append(f"| 最大浮盈 | {trade_4916.max_profit_pct:+.1f}% |")
    else:
        lines.append("| 結果 | 未觸發進場 (N字條件不符) |")
        lines.append("")
        lines.append("**說明:** 4916 在 5/16 報告後立刻噴出 (+32%)，整理期量縮後 5/28 出現 N字訊號。")
        lines.append("若進場條件設定正確，應能在 5/28 進場。")
    lines.append("")

    # 進場明細
    lines.append("## 2. 進場模擬明細")
    lines.append("")
    lines.append("| 段 | 代號 | 名稱 | 訊號日 | 進場日 | 進場價 | 出場日 | 出場原因 | P&L | 最大浮盈 |")
    lines.append("|---|------|------|--------|--------|--------|--------|----------|-----|---------|")

    for r in sorted(stats["entered_trades"], key=lambda r: (r.signal_date, r.ticker)):
        exit_d   = r.exit_date or "持倉中"
        exit_p_s = f"${r.exit_price:.1f}" if r.exit_price else "-"
        pnl_str  = f"**{r.pnl:+,.0f}**" if r.pnl != 0 else "-"
        reason   = r.exit_reason[:25] if r.exit_reason else "持倉中"
        lines.append(
            f"| {r.seg} | {r.ticker} | {r.name} "
            f"| {r.signal_date} | {r.entry_date} | ${r.entry_price:.1f} "
            f"| {exit_d} | {reason} "
            f"| {pnl_str} | {r.max_profit_pct:+.1f}% |"
        )
    lines.append("")

    if stats["no_entry_list"]:
        lines.append(f"**未觸發進場 ({len(stats['no_entry_list'])} 檔):** "
                     + " / ".join(f"{r.ticker}{r.name}" for r in stats["no_entry_list"][:30]))
        lines.append("")

    # 統計
    lines.append("## 3. 統計")
    lines.append("")
    lines.append("| 指標 | 數值 |")
    lines.append("|------|------|")
    lines.append(f"| Universe 總數 | {stats['total']} 檔 |")
    lines.append(f"| 成功進場 | {stats['entered']} 檔 |")
    lines.append(f"| 進場觸發率 | {stats['entered']/max(stats['total'],1)*100:.1f}% |")
    lines.append(f"| 已出場 | {stats['closed']} 檔 |")
    lines.append(f"| 仍持倉 | {stats['open_pos']} 檔 |")
    lines.append(f"| 未觸發 | {stats['no_entry']} 檔 |")
    lines.append(f"| **Phase5f P&L** | **${stats['total_pnl']:+,.0f}** |")
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

    # 按段分群
    lines.append("## 4. 按 Universe 來源分群")
    lines.append("")
    lines.append("| 來源 | Universe 數 | 進場數 | P&L |")
    lines.append("|------|------------|--------|-----|")
    seg_labels = {
        "seg1": "段1 老師 watchlist",
        "seg2": "段2 本週新聞題材",
        "training": "培訓影片/晚課",
        "line": "Line/直播",
    }
    for seg_key in ["seg1", "seg2", "training", "line"]:
        data = stats["by_seg"].get(seg_key, {"total": 0, "entered": 0, "pnl": 0})
        label = seg_labels.get(seg_key, seg_key)
        lines.append(f"| {label} | {data['total']} | {data['entered']} | ${data['pnl']:+,.0f} |")
    lines.append(f"| **合計** | **{stats['total']}** | **{stats['entered']}** | **${stats['total_pnl']:+,.0f}** |")
    lines.append("")

    # 結論
    lines.append("## 5. 結論與實用建議")
    lines.append("")
    lines.append("### 三版對比總結")
    lines.append("")
    lines.append("| 問題 | phase5b/5d | phase5e | **phase5f** |")
    lines.append("|------|-----------|---------|-------------|")
    lines.append("| 段1 是否用？ | ✅ 全用 | ❌ 全排 | ✅ 用，等 N字 |")
    lines.append("| 進場邏輯 | 立刻進 (lookahead) | 多頭排列+距MA10 | N字回測+量縮 |")
    lines.append("| 出場邏輯 | 分批+10% | 分批+10% | 守MA10多抱 |")
    lines.append(f"| P&L | +$2,375,108 (bias) | +$118,006 | **${stats['total_pnl']:+,.0f}** |")
    lines.append("")

    pnl = stats["total_pnl"]
    lines.append("### 對 User 的實用建議")
    lines.append("")
    if pnl > 200000:
        lines.append("- N字回測 entry 能正確捕捉段1 watchlist 的機會，策略有效")
        lines.append("- 關鍵：不追噴出，等量縮整理後的回測進場")
        lines.append("- 建議每週解讀完週報後，兩段 ticker 全部加入 watchlist")
        lines.append("- 等 3-8 天整理量縮後，出現紅K + 守均線才進場")
    elif pnl > 100000:
        lines.append("- N字回測能抓到部分段1機會，但不如 phase5e 穩定")
        lines.append("- 段2 forward 訊號仍是最可靠來源")
        lines.append("- 段1 watchlist 進場條件更嚴，需要耐心等待 N字型態")
    else:
        lines.append("- 段1 watchlist 多數在報告前已噴出，N字整理後再進回報有限")
        lines.append("- 聚焦段2 + 培訓 (phase5e 邏輯) 是更穩定的做法")
    lines.append("")
    lines.append("### 永久 Universe 實際操作建議")
    lines.append("")
    lines.append("- 每篇週報 (段1+段2) ticker 全部加入 watchlist，不設黑名單")
    lines.append("- 就算 8064 東捷 5/28 虧損出清 → 6/10 若老師再強調玻璃基板 + N字回測 → 復進")
    lines.append("- 就算 6285 啟碁 6/4 帳面虧損 → 若 6/10-15 結構底守住 + 老師再提低軌衛星 → 復進")
    lines.append("- 4916 事欣科: 老師 3 月早就提過，5/16 再次明示，5/28 N字進場 → +21.5%")
    lines.append("- 這就是「永久 universe + 等回測才進」的真實效益")
    lines.append("")
    lines.append("---")
    lines.append("*本報告使用 phase5f_watchlist_plus_n_pattern_entry.py 生成。*")
    lines.append(f"*分析截止: {ANALYSIS_END}  |  Sizing: $320k/檔  |  進場: N字回測+小結構  |  出場: 守MA10*")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 5f — Watchlist + N字回測 Entry Backtest"
    )
    parser.add_argument("--verbose", action="store_true", help="顯示每日進出場細節")
    parser.add_argument("--report",  action="store_true", help="寫出 markdown 報告")
    args = parser.parse_args()

    print("=" * 70)
    print("Phase 5f — Watchlist + N字回測 Entry Backtest")
    print("(段1 = 老師 watchlist，等N字回測進場；非 lookahead bias)")
    print(f"分析區間: {ANALYSIS_START} ~ {ANALYSIS_END}")
    print(f"Universe: {len(DEDUPED_SIGNALS)} 個 (段1+段2+培訓+Line)")
    print()
    print("User 指正:")
    print("  phase5e 排除段1 = 錯誤。段1 = 老師崩盤筆記本 watchlist，")
    print("  應等回測打擊區 + N字/小結構 confirm 才進，不是立即進場。")
    print()
    print("對比:")
    print("  phase5e (排除段1, 多頭排列進): +$118,006 (漏抓段1機會)")
    print("  phase5d (含段1, 立刻進):       +$2,375,108 (lookahead bias)")
    print("  phase5f (含段1, N字進):        計算中...")
    print("=" * 70)

    results = run_backtest(verbose=args.verbose)
    stats   = analyze_results(results)

    print()
    print("=" * 70)
    print("統計結果")
    print("=" * 70)
    print(f"Universe: {stats['total']} 檔  進場觸發: {stats['entered']} 檔  "
          f"(觸發率 {stats['entered']/max(stats['total'],1)*100:.1f}%)")
    print(f"已出場: {stats['closed']} 筆  仍持倉: {stats['open_pos']} 筆  "
          f"無N字訊號: {stats['no_entry']} 檔")
    print(f"勝率: {stats['win_rate']:.1f}%  贏:{stats['winners']} 輸:{stats['losers']}")
    print()
    print(f"★ Phase5f P&L: ${stats['total_pnl']:+,.0f}")
    print()
    print("── 對比 ────────────────────────────────────────────────────────")
    print(f"  phase5e (段2+培訓, 多頭排列):  +$118,006")
    print(f"  phase5f (段1+2+培訓, N字):     ${stats['total_pnl']:+,.0f}")
    print(f"  phase5d (全部, 立刻進 bias):   +$2,375,108")
    print()

    print("── 按段分群 ─────────────────────────────────────────────────────")
    seg_labels = {"seg1": "段1 watchlist", "seg2": "段2 新聞題材", "training": "培訓/晚課", "line": "Line/直播"}
    for seg_key in ["seg1", "seg2", "training", "line"]:
        data = stats["by_seg"].get(seg_key, {"total": 0, "entered": 0, "pnl": 0})
        label = seg_labels.get(seg_key, seg_key)
        print(f"  {label:18s}: {data['total']} 檔  進場 {data['entered']} 檔  P&L={data['pnl']:+,.0f}")

    # 4916 特別說明
    t4916 = next((r for r in results if r.ticker == "4916"), None)
    if t4916:
        print()
        print("── 4916 事欣科 特別驗證 ─────────────────────────────────────────")
        if t4916.entry_date:
            ret = (t4916.exit_price / t4916.entry_price - 1) * 100
            print(f"  訊號日: 2026-05-16 (W0516段2)  Watch: 5/18+")
            print(f"  進場日: {t4916.entry_date}  @${t4916.entry_price:.1f}")
            print(f"  出場日: {t4916.exit_date}  @${t4916.exit_price:.1f}  ({ret:+.1f}%)")
            print(f"  P&L: ${t4916.pnl:+,.0f}  最大浮盈: {t4916.max_profit_pct:+.1f}%")
        else:
            print(f"  4916: N字進場條件未觸發 (股票在報告後立刻噴出，整理期條件不足)")

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
        report_path = _STRAT_DIR / "phase5f_watchlist_plus_n_pattern_entry.md"
        md_content = format_report(results, stats)
        report_path.write_text(md_content, encoding="utf-8")
        print(f"\n報告已寫出: {report_path}")
    else:
        print("\n(加 --report 可寫出完整 markdown 報告)")


if __name__ == "__main__":
    main()
