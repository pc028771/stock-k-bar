"""Phase 4 v2 出場 Detector Backtest — 1 分 K + 5 分 K aggregation 版。

改進重點 vs daily 版 (phase4_exit_compare_backtest.py, commit 205529e):
  掀傘  : 改用 5 分 K vol_ratio (daily 太粗 → 誤觸 2885 早出 -$40k)
  高檔長黑: 沿用 daily K 為判斷主體，但 high zone 改用 intraday 真實波動率
  分批停利: 仍用 daily close + entry price (不變)
  急殺   : 改用 1 分 K 第一根 (09:00) 取真實開盤價 vs 前日收

Usage:
    python scripts/zhuli/phase4_v2_exit_detectors_minute_kbar.py
    python scripts/zhuli/phase4_v2_exit_detectors_minute_kbar.py --verbose
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

# ── 路徑設定 ─────────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

_DB = Path.home() / ".four_seasons" / "data.sqlite"

# ── Import daily detectors (高檔長黑 / 分批停利 沿用) ─────────────────────────
from scripts.zhuli.exit.detectors import (
    check_high_long_black,
    check_profit_milestone,
)

# ── Phase4 trade list (同 v1) ─────────────────────────────────────────────────
REAL_TRADES = [
    # ── 已出清 ────────────────────────────────────────────────────────────────
    ("8064", "東捷",   "2026-05-19", 136.5,  1000, "2026-05-20", 126.5,  -10000, "東捷 -10k 教訓 (結構底失守)"),
    ("2476", "鉅祥",   "2026-05-20", 114.5,  2000, "2026-05-28", 121.5,   -6395, "拉高出貨日清倉"),
    ("3162", "精確",   "2026-05-26",  88.5,  1000, "2026-05-28",  81.4,  -10412, "小部位認損"),
    ("3149", "正達",   "2026-05-22",  59.1,  4000, "2026-05-28",  67.2,   23036, "強檔鎖利 +13%"),
    ("2464", "盟立",   "2026-05-22", 143.5,  3000, "2026-05-28", 172.0,   85185, "機器人族群大波段"),
    ("3265", "台星科", "2026-05-26", 186.0,  1000, "2026-05-28", 189.0,    3000, "光通族群持有 3 天"),
    ("6282", "康舒",   "2026-05-22",  57.7,  3000, "2026-05-28",  57.7,       0, "BBU 強勢守在 56.8"),
    ("8027", "鈦昇",   "2026-05-19", 273.5,  1000, "2026-05-20", 245.0,  -28500, "鈦昇早出 -28k"),
    ("2485", "兆赫",   "2026-06-01",  73.4,  5000, "2026-06-02",  73.5,    -894, "MA5/10 破 + 外資出"),
    ("3016", "嘉晶",   "2026-06-02", 134.0,  1000, "2026-06-02", 113.0,  -21388, "試撮 FOMO 違紀 -21k"),
    ("6285", "啟碁",   "2026-06-01", 315.0,  1000, "2026-06-02", 306.0,   -6705, "老師明示加碼 6/2 尾盤出"),
    # ── 仍持有 ────────────────────────────────────────────────────────────────
    ("1605", "華新",   "2026-06-01",  40.1,  8000, None,          42.7,    None, "Tier-S core、仍持有"),
    ("2885", "元大金", "2026-05-27",  58.0, 10000, None,          63.7,    None, "券商族群 core"),
    ("8046", "南電",   "2026-05-21", 862.0,  1000, None,         904.0,    None, "PCB 警示族群、持有"),
    ("3481", "星宇航", "2026-05-21",  40.6,  5000, None,          59.4,    None, "AI 飛機題材、仍持有"),
]

FEE_RATE = 0.000399
TAX_RATE = 0.003


def calc_pnl(entry: float, exit_p: float, shares: int) -> float:
    buy_cost = entry  * shares * (1 + FEE_RATE)
    sell_net = exit_p * shares * (1 - FEE_RATE - TAX_RATE)
    return sell_net - buy_cost


# ── 資料載入 ──────────────────────────────────────────────────────────────────

def load_daily_bars(ticker: str, start_date: str, end_date: str = "2026-06-03") -> pd.DataFrame:
    """Daily bar (含 MA10 / vol_ma20)。"""
    try:
        with sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=10) as con:
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


def load_minute_bars(ticker: str, start_date: str, end_date: str = "2026-06-03") -> pd.DataFrame:
    """從 stock_minute_kbar 載入 1 分 K。"""
    try:
        with sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=10) as con:
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


# ── 5 分 K aggregation ────────────────────────────────────────────────────────

def aggregate_to_5min(df_1min: pd.DataFrame) -> pd.DataFrame:
    """1 分 K → 5 分 K。"""
    if df_1min.empty:
        return pd.DataFrame()
    df = df_1min.copy()
    df = df.set_index("dt")
    df_5min = df[["open", "high", "low", "close", "volume"]].resample("5min").agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum",
    })
    return df_5min.dropna(subset=["close"]).reset_index()


def get_5min_for_date(df_1min: pd.DataFrame, date_str: str) -> pd.DataFrame:
    """取某交易日的 5 分 K 資料。"""
    mask = df_1min["trade_datetime"].str.startswith(date_str)
    day_1min = df_1min[mask].copy()
    if day_1min.empty:
        return pd.DataFrame()
    day_1min["dt"] = pd.to_datetime(day_1min["trade_datetime"])
    return aggregate_to_5min(day_1min)


def get_open_price_from_1min(df_1min: pd.DataFrame, date_str: str) -> Optional[float]:
    """取某日 09:00~09:05 第一根 1 分 K 的 open (真實開盤價)。"""
    prefix = f"{date_str} 09:0"
    mask = df_1min["trade_datetime"].str.startswith(prefix)
    day_rows = df_1min[mask].sort_values("trade_datetime")
    if day_rows.empty:
        # fallback: 取當日任何最早一根
        mask2 = df_1min["trade_datetime"].str.startswith(date_str)
        day_rows = df_1min[mask2].sort_values("trade_datetime")
    if day_rows.empty:
        return None
    return float(day_rows.iloc[0]["open"])


# ── v2 Detectors ──────────────────────────────────────────────────────────────

def check_umbrella_exit_5k(
    k5_today: pd.DataFrame,
    entry_price: float,
    vol_ratio_threshold: float = 0.7,
    no_new_high_bars: int = 3,
) -> dict:
    """掀傘偵測 — 5 分 K 版 (每日僅在當日收盤後彙算)。

    使用「當日全部 5K 棒」判斷：
      - 最後 3 根不創前段 5K 新高
      - 量縮：最後 1 根量 < 前 10 根均量 × 0.7
      - 在賺中
    """
    result = {"triggered": False, "reason": "", "detector": "掀傘_5K"}
    min_bars = no_new_high_bars + 2

    if len(k5_today) < min_bars:
        result["reason"] = f"5K 資料不足 ({len(k5_today)} < {min_bars})"
        return result

    current_close = float(k5_today["close"].iloc[-1])
    if current_close <= entry_price:
        result["reason"] = f"未賺中 ({current_close:.2f} ≤ {entry_price:.2f})"
        return result

    # 連續 N 根不創新高
    prior_high = float(k5_today.iloc[-(no_new_high_bars + 1)]["high"])
    tail_highs = [float(k5_today.iloc[-(no_new_high_bars - i)]["high"]) for i in range(no_new_high_bars)]
    no_new_high = all(h <= prior_high for h in tail_highs)
    if not no_new_high:
        result["reason"] = f"仍創新高 (前高 {prior_high:.2f} tail={[f'{h:.2f}' for h in tail_highs]})"
        return result

    # 量縮
    vol_window = k5_today["volume"].tail(max(len(k5_today), 10))
    vol_mean = float(vol_window.mean())
    last_vol = float(k5_today["volume"].iloc[-1])
    vol_ratio = last_vol / vol_mean if vol_mean > 0 else 1.0
    if vol_ratio >= vol_ratio_threshold:
        result["reason"] = f"量未縮 (×{vol_ratio:.2f} ≥ {vol_ratio_threshold})"
        return result

    # 無連續紅K
    tail_bars = k5_today.tail(no_new_high_bars)
    reds = (tail_bars["close"] > tail_bars["open"]).values
    if len(reds) >= 2 and any(reds[i] and reds[i+1] for i in range(len(reds)-1)):
        result["reason"] = "仍有連續紅K"
        return result

    profit_pct = (current_close / entry_price - 1) * 100
    result["triggered"] = True
    result["reason"] = (
        f"5K 連{no_new_high_bars}根不創高(前高{prior_high:.2f}) + 量縮×{vol_ratio:.2f}"
        f" | 浮盈+{profit_pct:.1f}%"
    )
    return result


def check_high_long_black_intraday(
    df_daily: pd.DataFrame,
    df_1min_today: pd.DataFrame,
    lookback_days: int = 60,
    long_black_pct: float = 0.04,
    intraday_volatility_ratio: float = 1.2,
) -> dict:
    """高檔長黑 K v2 — 沿用 daily K 架構 + intraday 波動率加分確認。

    相較 v1:
      high_zone_ratio 改為 1.2 (放寬，用 intraday volatility 補強確認)
      加一個 intraday 確認: 當日真實波動率 (high-low) > intraday_volatility_ratio × ATR5

    Args:
        df_1min_today: 當日 1 分 K (用於計算 intraday 真實波動率)
    """
    # 先跑 daily 版 (high_zone_ratio 放寬到 1.2)
    base = check_high_long_black(df_daily, lookback_days=lookback_days,
                                  long_black_pct=long_black_pct, high_zone_ratio=1.2)
    result = base.copy()
    result["detector"] = "高檔長黑_intraday"

    if not result["triggered"]:
        return result

    # intraday 波動率加分確認
    if df_1min_today.empty:
        result["intraday_confirm"] = False
        result["reason"] += " | intraday資料不足 (無法確認)"
        return result

    intraday_range = float(df_1min_today["high"].max()) - float(df_1min_today["low"].min())
    today_close = float(df_daily.iloc[-1]["close"])
    volatility_pct = intraday_range / today_close if today_close > 0 else 0

    # ATR5 (過去 5 日 true range 均)
    if len(df_daily) >= 6:
        atr5 = float((df_daily["high"].tail(5) - df_daily["low"].tail(5)).mean())
    else:
        atr5 = intraday_range  # fallback

    intraday_confirm = intraday_range >= atr5 * intraday_volatility_ratio
    result["intraday_confirm"] = intraday_confirm
    result["intraday_range"] = intraday_range
    result["atr5"] = atr5

    if intraday_confirm:
        result["reason"] += (
            f" | intraday波動{intraday_range:.2f} ≥ ATR5×{intraday_volatility_ratio}={atr5*intraday_volatility_ratio:.2f} ✓"
        )
    else:
        result["reason"] += (
            f" | intraday波動{intraday_range:.2f} < ATR5×{intraday_volatility_ratio}={atr5*intraday_volatility_ratio:.2f} 弱"
        )

    return result


def check_gap_down_1min(
    df_1min: pd.DataFrame,
    date_str: str,
    prev_close: float,
    emergency_threshold: float = -0.05,
    warning_threshold: float = -0.03,
) -> dict:
    """急殺偵測 v2 — 使用 1 分 K 真實開盤價 (09:00 第一根 open)。"""
    result = {
        "triggered": False,
        "level": "normal",
        "reason": "",
        "price": 0.0,
        "detector": "隔日急殺_1min",
        "gap_pct": 0.0,
    }

    open_price = get_open_price_from_1min(df_1min, date_str)
    if open_price is None:
        result["reason"] = f"1分K無 {date_str} 開盤資料"
        return result

    result["price"] = open_price

    if prev_close <= 0:
        result["reason"] = "前收無效"
        return result

    gap_pct = (open_price / prev_close - 1)
    result["gap_pct"] = gap_pct

    if gap_pct <= emergency_threshold:
        result["triggered"] = True
        result["level"] = "emergency"
        result["reason"] = f"真實跳空 {gap_pct*100:.1f}% ≤ -5% (1分K 09:00 open={open_price:.2f})"
        return result

    if gap_pct <= warning_threshold:
        result["triggered"] = True
        result["level"] = "warning"
        result["reason"] = f"真實跳空 {gap_pct*100:.1f}% (-3~-5%) 警示 (1分K open={open_price:.2f})"
        return result

    result["reason"] = f"開盤跳空 {gap_pct*100:.1f}% 正常 (1分K open={open_price:.2f})"
    return result


# ── 模擬單筆 trade ─────────────────────────────────────────────────────────────

def simulate_trade_v2(
    ticker: str,
    name: str,
    entry_date: str,
    entry_price: float,
    shares: int,
    actual_exit_date: Optional[str],
    actual_exit_price: float,
    actual_pnl: Optional[float],
    notes: str,
    verbose: bool = False,
) -> dict:
    end_ref = actual_exit_date if actual_exit_date else "2026-06-03"
    df_daily = load_daily_bars(ticker, entry_date, end_date="2026-06-03")
    df_1min  = load_minute_bars(ticker, entry_date, end_date="2026-06-03")

    if df_daily.empty:
        return {"ticker": ticker, "name": name, "entry_date": entry_date,
                "entry_price": entry_price, "actual_exit_date": actual_exit_date,
                "actual_exit_price": actual_exit_price, "actual_pnl": actual_pnl,
                "detectors": {}, "notes": notes, "error": "無日線資料"}

    df_daily = df_daily[df_daily["trade_date"] >= entry_date].reset_index(drop=True)
    if df_daily.empty:
        return {"ticker": ticker, "name": name, "error": "進場後無資料"}

    detector_exits: dict[str, dict] = {}
    milestones_hit: set = set()

    for i in range(1, len(df_daily)):
        today_daily_row = df_daily.iloc[:i+1]
        today = df_daily.iloc[i]
        date_str = str(today["trade_date"])

        if actual_exit_date and date_str > actual_exit_date:
            break

        current_close = float(today["close"])
        prev_close    = float(df_daily.iloc[i-1]["close"])

        # ── 5 分 K for 當日 ────────────────────────────────────────────────
        k5_today = get_5min_for_date(df_1min, date_str) if not df_1min.empty else pd.DataFrame()
        min1_today_mask = df_1min["trade_datetime"].str.startswith(date_str) if not df_1min.empty else pd.Series([], dtype=bool)
        min1_today = df_1min[min1_today_mask] if not df_1min.empty else pd.DataFrame()

        # ── Detector 1: 掀傘 5K 版 ────────────────────────────────────────
        if "掀傘" not in detector_exits:
            if not k5_today.empty:
                r = check_umbrella_exit_5k(k5_today, entry_price)
            else:
                r = {"triggered": False, "reason": "無5K資料"}
            if r["triggered"]:
                pnl = calc_pnl(entry_price, current_close, shares)
                detector_exits["掀傘"] = {
                    "date": date_str, "price": current_close,
                    "pnl": pnl, "reason": r["reason"],
                }
                if verbose:
                    print(f"  [{ticker}] 掀傘5K @ {date_str} ${current_close:.2f} PNL={pnl:+.0f}")

        # ── Detector 2: 高檔長黑 K + intraday 確認 ────────────────────────
        if "高檔長黑" not in detector_exits:
            r = check_high_long_black_intraday(today_daily_row, min1_today)
            if r["triggered"]:
                pnl = calc_pnl(entry_price, current_close, shares)
                detector_exits["高檔長黑"] = {
                    "date": date_str, "price": current_close,
                    "pnl": pnl, "reason": r["reason"],
                    "intraday_confirm": r.get("intraday_confirm", False),
                }
                if verbose:
                    print(f"  [{ticker}] 高檔長黑intraday @ {date_str} ${current_close:.2f} PNL={pnl:+.0f}")

        # ── Detector 3: 分批停利里程碑 ────────────────────────────────────
        r = check_profit_milestone(current_close, entry_price, milestones_hit)
        if r["triggered"]:
            key = r["milestone_key"]
            milestones_hit.add(key)
            if key not in detector_exits:
                partial_shares = shares // 3
                pnl = calc_pnl(entry_price, current_close, partial_shares)
                detector_exits[key] = {
                    "date": date_str, "price": current_close,
                    "pnl_partial": pnl, "reason": r["reason"], "action": r["action"],
                }
                if verbose:
                    print(f"  [{ticker}] {key} @ {date_str} ${current_close:.2f}")

        # ── Detector 4: 急殺 1 分 K 版 ───────────────────────────────────
        if "隔日急殺" not in detector_exits:
            r = check_gap_down_1min(df_1min, date_str, prev_close)
            if r["triggered"] and r["level"] in ("emergency", "warning"):
                open_px = r["price"]
                pnl = calc_pnl(entry_price, open_px, shares)
                detector_exits["隔日急殺"] = {
                    "date": date_str, "price": open_px,
                    "pnl": pnl, "reason": r["reason"], "level": r["level"],
                    "gap_pct": r["gap_pct"],
                }
                if verbose:
                    print(f"  [{ticker}] 急殺1min @ {date_str} ${open_px:.2f} PNL={pnl:+.0f} [{r['level']}]")

    # user 損益
    if actual_pnl is None:
        user_pnl = calc_pnl(entry_price, actual_exit_price, shares)
    else:
        user_pnl = actual_pnl

    return {
        "ticker": ticker, "name": name, "entry_date": entry_date,
        "entry_price": entry_price, "shares": shares,
        "actual_exit_date": actual_exit_date or "仍持有",
        "actual_exit_price": actual_exit_price,
        "user_pnl": user_pnl,
        "detectors": detector_exits,
        "notes": notes,
        "has_1min": not df_1min.empty,
    }


def format_pnl(v) -> str:
    if v is None:
        return "—"
    return f"{v:+,.0f}"


# ── 主 backtest ───────────────────────────────────────────────────────────────

def run_backtest_v2(verbose: bool = False) -> None:
    print("=" * 90)
    print("  Phase 4 v2 出場 Detector Backtest — 1分K + 5分K (2026-05-19 ~ 2026-06-03)")
    print("=" * 90)
    print()

    results = []
    for trade in REAL_TRADES:
        (ticker, name, entry_date, entry_price, shares,
         actual_exit_date, actual_exit_price, actual_pnl, notes) = trade
        if verbose:
            print(f"\n[{ticker} {name}] 進 {entry_date} @${entry_price:.2f} ×{shares}")
        r = simulate_trade_v2(
            ticker, name, entry_date, entry_price, shares,
            actual_exit_date, actual_exit_price, actual_pnl, notes, verbose=verbose,
        )
        results.append(r)

    # ── 對比表 ──────────────────────────────────────────────────────────────
    print("\n" + "─" * 130)
    print(f"{'Ticker':<6}{'名稱':<8}{'進場日':<12}{'進場價':>7}  "
          f"{'User出場':>16}  {'User PNL':>10}  "
          f"{'掀傘5K':>12}  {'掀傘PNL':>9}  "
          f"{'高黑+intra':>12}  {'高黑PNL':>9}  "
          f"{'急殺1min':>12}  {'急殺PNL':>9}")
    print("─" * 130)

    total_user_pnl = 0.0
    umbrella_triggered = 0
    high_black_triggered = 0
    gap_triggered = 0
    milestone_10 = milestone_20 = milestone_30 = 0
    umbrella_delta = []
    high_black_delta = []
    gap_delta = []

    for r in results:
        if "error" in r:
            print(f"{'':6} {r.get('name','?'):<8} ⚠ {r.get('error','')}")
            continue

        user_pnl = r.get("user_pnl", 0.0) or 0.0
        dets = r.get("detectors", {})
        umb = dets.get("掀傘")
        hb  = dets.get("高檔長黑")
        gap = dets.get("隔日急殺")

        u_date = umb["date"]  if umb  else "未觸發"
        u_pnl  = umb["pnl"]   if umb  else None
        h_date = hb["date"]   if hb   else "未觸發"
        h_pnl  = hb["pnl"]    if hb   else None
        g_date = gap["date"]  if gap  else "未觸發"
        g_pnl  = gap["pnl"]   if gap  else None

        actual_str = r["actual_exit_date"]
        if actual_str != "仍持有":
            actual_str = f"{actual_str} ${r['actual_exit_price']:.0f}"

        print(f"{r['ticker']:<6}{r['name']:<8}{r['entry_date']:<12}{r['entry_price']:>7.2f}  "
              f"{actual_str:>16}  {format_pnl(user_pnl):>10}  "
              f"{u_date:>12}  {format_pnl(u_pnl):>9}  "
              f"{h_date:>12}  {format_pnl(h_pnl):>9}  "
              f"{g_date:>12}  {format_pnl(g_pnl):>9}")

        total_user_pnl += user_pnl
        if umb:
            umbrella_triggered += 1
            umbrella_delta.append((u_pnl or 0.0) - user_pnl)
        if hb:
            high_black_triggered += 1
            high_black_delta.append((h_pnl or 0.0) - user_pnl)
        if gap:
            gap_triggered += 1
            gap_delta.append((g_pnl or 0.0) - user_pnl)
        if "分批停利_10%" in dets: milestone_10 += 1
        if "分批停利_20%" in dets: milestone_20 += 1
        if "分批停利_30%" in dets: milestone_30 += 1

    n = len([r for r in results if "error" not in r])
    print("─" * 130)
    print(f"\n總計 User PNL: {total_user_pnl:+,.0f}")
    print(f"\n{'─'*60}")
    print(f"  分析筆數: {n} 筆")
    print()
    print(f"  掀傘(5K):   觸發 {umbrella_triggered}/{n}")
    if umbrella_delta:
        print(f"              平均 Δ PNL: {sum(umbrella_delta)/len(umbrella_delta):+,.0f} (正=比User好)")
    print()
    print(f"  高檔長黑(intra): 觸發 {high_black_triggered}/{n}")
    if high_black_delta:
        print(f"              平均 Δ PNL: {sum(high_black_delta)/len(high_black_delta):+,.0f}")
    print()
    print(f"  分批停利: +10% 觸發 {milestone_10} / +20% {milestone_20} / +30% {milestone_30}")
    print()
    print(f"  急殺(1min): 觸發 {gap_triggered}/{n}")
    if gap_delta:
        print(f"              平均 Δ PNL: {sum(gap_delta)/len(gap_delta):+,.0f}")

    # ── 重點案例 ──────────────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("  重點案例分析 (v2 vs v1):")
    case_map = {r["ticker"]: r for r in results if "error" not in r}

    # 2885 元大金 — 掀傘改善核心案例
    r2885 = case_map.get("2885")
    if r2885:
        umb = r2885["detectors"].get("掀傘")
        user_pnl = r2885.get("user_pnl", 0)
        if umb:
            print(f"\n  2885 元大金 [掀傘 5K 版]:")
            print(f"    觸發 @ {umb['date']} ${umb['price']:.2f} → PNL {format_pnl(umb['pnl'])}")
            print(f"    vs User (仍持有 6/3@63.7) → PNL {format_pnl(user_pnl)}")
            print(f"    → 5K 版是否避免 daily 誤觸 -$40k 需比對 daily 版觸發日期")
        else:
            print(f"\n  2885 元大金: 掀傘 5K 版未觸發 ✓ (避免 daily 版早出問題)")

    # 3016 嘉晶 — 急殺 1min 案例
    r3016 = case_map.get("3016")
    if r3016:
        gap = r3016["detectors"].get("隔日急殺")
        user_pnl = r3016.get("user_pnl", -21388)
        print(f"\n  3016 嘉晶 [急殺 1min 版]:")
        if gap:
            print(f"    觸發 @ {gap['date']} open={gap['price']:.2f} gap={gap['gap_pct']*100:.1f}%")
            print(f"    Detector PNL {format_pnl(gap['pnl'])} vs User {format_pnl(user_pnl)} Δ={format_pnl(gap['pnl']-user_pnl)}")
            print(f"    注意: 嘉晶案是試撮違紀進場 (09:00前)，合法進場才適用 detector")
        else:
            print(f"    急殺未觸發 (進場當天即損失、無觀察期)")

    # 2464 盟立 — 掀傘 / 分批停利
    r2464 = case_map.get("2464")
    if r2464:
        umb = r2464["detectors"].get("掀傘")
        m30 = r2464["detectors"].get("分批停利_30%")
        user_pnl = r2464.get("user_pnl", 85185)
        print(f"\n  2464 盟立 [掀傘 5K + 分批]:")
        if umb:
            print(f"    掀傘 @ {umb['date']} ${umb['price']:.2f} PNL {format_pnl(umb['pnl'])} vs User {format_pnl(user_pnl)}")
        else:
            print(f"    掀傘未觸發 → 持到 user 出場合理")
        if m30:
            print(f"    +30% 里程碑 @ {m30['date']} ${m30['price']:.2f}")

    # 現有持倉建議
    print(f"\n{'─'*60}")
    print("  5 個現有持倉 Detector 狀態 (截至 2026-06-03):")
    for tkr in ["1605", "2885", "8046", "3481"]:
        rr = case_map.get(tkr)
        if not rr:
            continue
        dets = rr.get("detectors", {})
        umb_str = f"掀傘5K @ {dets['掀傘']['date']}" if "掀傘" in dets else "掀傘 未觸"
        gap_str = f"急殺 @ {dets['隔日急殺']['date']}" if "隔日急殺" in dets else "急殺 未觸"
        m10_str = f"+10%里程碑 @ {dets['分批停利_10%']['date']}" if "分批停利_10%" in dets else ""
        m20_str = f"+20% @ {dets['分批停利_20%']['date']}" if "分批停利_20%" in dets else ""
        print(f"    {tkr} {rr['name']}: {umb_str} | {gap_str}"
              + (f" | {m10_str}" if m10_str else "")
              + (f" | {m20_str}" if m20_str else ""))

    # 6285 啟碁 (已出清 6/2)
    r6285 = case_map.get("6285")
    if r6285:
        dets = r6285.get("detectors", {})
        umb = dets.get("掀傘")
        hb  = dets.get("高檔長黑")
        user_pnl = r6285.get("user_pnl", -6705)
        print(f"    6285 啟碁 (已出清): User PNL {format_pnl(user_pnl)}"
              + (f" | 掀傘 @ {umb['date']}" if umb else " | 掀傘 未觸")
              + (f" | 高黑 @ {hb['date']}" if hb else " | 高黑 未觸"))

    print()


def main():
    p = argparse.ArgumentParser(description="Phase 4 v2 出場 Detector Backtest (1分K)")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()
    run_backtest_v2(verbose=args.verbose)


if __name__ == "__main__":
    main()
