"""盤中即時 Stage Trigger 偵測器 — 主力大操作紀律。

每 N 秒抓 5 分 K，偵測四種 Trigger (cascade 優先順序):
  首攻 (Ch5-3): 第一根 5K SOP (當沖路徑、6 條件全 pass + 9:10 後過高站穩)
  續攻 (T1):    強勢延續 (連 2 紅K + 量增 + 站前波高 + 距開盤 >+1%)
  反彈 (T2):    跌深反彈 (從盤中最高跌 ≥ 2.5% + 3 紅K 或 5m diff 由負轉正)
  破底 (TC):    結構失敗 (跌破前波低或距 MA10 -3% + 量爆下行)

Cascade 邏輯 (composite_check):
  首攻 pass → 走當沖路徑
  → 續攻 pass → 強勢延續
  → 反彈 pass → 跌深反彈
  → 破底 pass → 結構失敗

Per-category action:
  HELD:         續攻 → Stage 2 加碼追高 / 反彈 → Stage 2 反彈低接加碼 / 破底 → 出 Stage 1 警示
  WATCH:        首攻/續攻/反彈 → Stage 1 試水 / 破底 → 不要進
  PLAN_PRIMARY: 首攻/續攻/反彈 → 進場時機 / 破底 → skip

紀律守則:
  - 09:00-09:10 不觸發任何 entry Trigger
  - 跳空 ≥ +5% 不觸發
  - 距 MA10 > +10% 不觸發

Usage:
  python scripts/zhuli/intraday_stage_helper.py
  python scripts/zhuli/intraday_stage_helper.py --tickers 1605,6207,4722
  python scripts/zhuli/intraday_stage_helper.py --interval 60 --notify
  python scripts/zhuli/intraday_stage_helper.py --simulate-date 2026-05-29 --simulate-ticker 1605
  python scripts/zhuli/intraday_stage_helper.py --simulate-date 2026-06-01 --simulate-ticker 1605
"""
from __future__ import annotations

from zhuli.db import get_conn, MAIN_DB

import argparse
import functools
import logging
import sqlite3
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# ── Path setup ────────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent.parent
_SYS  = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_REPO), str(_REPO / "scripts"), str(_SYS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── Phase 1 出場 Detector 匯入 (lazy, 避免 import error 影響啟動) ──────────────
try:
    from scripts.zhuli.exit.detectors import (
        check_umbrella_exit,
        check_high_long_black,
        check_profit_milestone,
        check_gap_down_emergency,
    )
    _EXIT_DETECTORS_AVAILABLE = True
except ImportError as _e:
    _EXIT_DETECTORS_AVAILABLE = False
    # 提供 stub functions 以避免 NameError
    def check_umbrella_exit(*a, **kw):   return {"triggered": False, "reason": "detector 未載入"}
    def check_high_long_black(*a, **kw): return {"triggered": False, "reason": "detector 未載入"}
    def check_profit_milestone(*a, **kw):return {"triggered": False, "reason": "detector 未載入"}
    def check_gap_down_emergency(*a, **kw): return {"triggered": False, "reason": "detector 未載入"}

_DB = MAIN_DB
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── 預設持倉與觀察清單 ─────────────────────────────────────────────────────────
# (ticker, name, entry_price, shares, stop_price, tactic)
HELD: list[tuple[str, str, float, int, float, str]] = [
    ("1605", "華新",  40.1,  8000, 38.75, "核心"),
    ("6285", "啟碁",  315.0, 1000, 301.0, "核心"),
]

# (ticker, name, entry_price, stop_price, tactic)
WATCH: list[tuple[str, str, float, float, str]] = [
    ("6207", "雷科",    127.0, 115.0, "短打"),
    ("8046", "南電",    862.0, 834.0, "短打"),
    ("4722", "國精化",  281.0, 268.0, "短打"),
]

# Trigger 命名對照表 (新中文名 → 舊英文 alias 向後相容)
TRIGGER_NAME_MAP: dict[str, str] = {
    "首攻":          "Ch5-3",
    "首攻_signal":   "Ch5-3_signal",
    "首攻_pullback": "Ch5-3_pullback",
    "續攻":          "T1",
    "續攻_watch":    "T1_watch",
    "反彈":          "T2",
    "反彈_watch":    "T2_watch",
    "破底":          "TC",
    "尾盤_confirmed": "Closing_confirmed",  # 3-4/5 最佳進場
    "尾盤_過熱":     "Closing_overheated",  # 5/5 Win 40% 過熱、不該追
    "尾盤_skip":     "Closing_skip",
    # ── Phase 1 出場 Trigger (新增) ──
    "掀傘":          "Open_umbrella",       # 🌂 主力收手、主動全出
    "高檔長黑":      "High_long_black",     # 🦘 高檔攻擊結束
    "隔日急殺":      "Gap_down_emergency",  # 📉 開盤 -5% 立即出
    "隔日急殺_警示": "Gap_down_warning",    # ⚠️ 開盤 -3~-5% 警示
    "分批停利_10%":  "Profit_milestone_10", # 💰 +10% 鎖 1/3
    "分批停利_20%":  "Profit_milestone_20", # 💰 +20% 再鎖 1/3
    "分批停利_30%":  "Profit_milestone_30", # 💰 +30% 守剩 1/3
}

# 出場 Trigger 顯示說明
EXIT_TRIGGER_DISPLAY: dict[str, str] = {
    "掀傘":          "🌂 掀傘出場 (主力收手)",
    "高檔長黑":      "🦘 高檔長黑 K (攻擊結束)",
    "隔日急殺":      "📉 隔日急殺 立即出",
    "隔日急殺_警示": "⚠️ 隔日跳空警示",
    "分批停利_10%":  "💰 +10% 鎖 1/3",
    "分批停利_20%":  "💰 +20% 再鎖 1/3",
    "分批停利_30%":  "💰 +30% 守剩 1/3",
}
# 反向 alias: 舊名 → 新名 (向後相容讀取)
TRIGGER_ALIAS_MAP: dict[str, str] = {v: k for k, v in TRIGGER_NAME_MAP.items()}

# 戰術 → 適用 trigger
TACTICS_TRIGGERS: dict[str, list[str]] = {
    "核心":  ["續攻", "反彈"],
    "短打":  ["續攻", "反彈"],
    "當沖":  ["首攻"],
    "題材":  ["續攻", "反彈"],
}

# ── Fubon client (lazy init) ──────────────────────────────────────────────────
_fubon_client = None


def _get_fubon():
    global _fubon_client
    if _fubon_client is None:
        from clients.fubon_client import FubonClient
        _fubon_client = FubonClient()
    return _fubon_client


# ── 通知 ──────────────────────────────────────────────────────────────────────

def notify_mac(title: str, msg: str, sound: str = "Glass") -> None:
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{msg}" with title "{title}" sound name "{sound}"'],
            capture_output=True, timeout=10,
        )
    except Exception as e:
        log.warning("macOS 通知失敗: %s", e)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _db_con(db: Path) -> sqlite3.Connection:
    for _ in range(3):
        try:
            return get_conn(db, timeout=15)
        except sqlite3.OperationalError as e:
            log.warning("DB 連線失敗，1s 後重試: %s", e)
            time.sleep(1)
    raise RuntimeError(f"無法開啟 DB: {db}")


def load_stock_names(db: Path) -> dict[str, str]:
    with _db_con(db) as con:
        rows = con.execute("SELECT ticker, stock_name FROM stock_info").fetchall()
    return {r[0]: r[1] for r in rows}


# DB data version: standard_daily_bar 的 MAX(trade_date)。
# 長駐 process (live monitor) 啟動後 DB 可能被晚到的 sync 補入新日K、
# 純 (ticker, date) key 的 cache 會永遠回傳啟動當下的舊值 (6/11 4939 假燈事件)。
# 把 data version 納入 cache key、DB 一進新日K整批 cache 自動失效。
_DATA_VERSION_TTL = 60.0
_data_version_cache: dict[str, tuple[float, str]] = {}


def db_data_version(db: Path = _DB) -> str:
    """回傳 DB 最新 trade_date 字串 (TTL 60s)、查失敗回 ''。"""
    now = time.monotonic()
    hit = _data_version_cache.get(str(db))
    if hit and now - hit[0] < _DATA_VERSION_TTL:
        return hit[1]
    try:
        with get_conn(db) as con:
            r = con.execute("SELECT MAX(trade_date) FROM standard_daily_bar").fetchone()
        v = str(r[0]) if r and r[0] else ""
    except Exception:
        v = ""
    _data_version_cache[str(db)] = (now, v)
    return v


def _get_ma10(ticker: str, target_date: str, db: Path = _DB) -> Optional[float]:
    """從 standard_daily_bar 取 target_date 前一交易日的 MA10（data-version-keyed cache）。"""
    return _get_ma10_versioned(ticker, target_date, db, db_data_version(db))


@functools.lru_cache(maxsize=4096)
def _get_ma10(ticker: str, target_date: str, db: Path = _DB) -> Optional[float]:
    """從 standard_daily_bar 取 target_date 前一交易日的 MA10。

    Cache: 同一 (ticker, target_date) 在 backtest / live monitor 內會被反覆查、
    每次都開新 sqlite connection 很貴 (profile 看到 19k+ connects)。lru_cache
    把每對 (ticker, date) 的查詢降到 1 次。

    Args:
        ticker:      股票代號
        target_date: 當日日期字串 'YYYY-MM-DD'（取其之前最新一筆）
        db:          SQLite DB 路徑

    Returns:
        MA10 浮點數，查無則回 None。
    """
    try:
        with get_conn(db) as con:
            r = con.execute(
                "SELECT ma10 FROM standard_daily_bar "
                "WHERE ticker=? AND trade_date < ? "
                "ORDER BY trade_date DESC LIMIT 1",
                (ticker, target_date),
            ).fetchone()
        return float(r[0]) if r and r[0] else None
    except Exception as e:
        log.warning("_get_ma10(%s, %s) 失敗: %s", ticker, target_date, e)
        return None


def load_daily_closes(ticker: str, db: Path, n: int = 20) -> pd.Series:
    """取最近 n 日收盤，回傳 Series(index=date str, values=float)."""
    try:
        with _db_con(db) as con:
            rows = con.execute(
                "SELECT trade_date, close FROM standard_daily_bar WHERE ticker=? ORDER BY trade_date DESC LIMIT ?",
                (ticker, n),
            ).fetchall()
        if not rows:
            return pd.Series(dtype=float)
        s = pd.Series({r[0]: float(r[1]) for r in rows})
        return s.sort_index()
    except Exception as e:
        log.warning("load_daily_closes(%s) 失敗: %s", ticker, e)
        return pd.Series(dtype=float)


# ── 5 分 K 抓取 ───────────────────────────────────────────────────────────────

def _build_5min_from_1min(df1m: pd.DataFrame, target_date: date) -> pd.DataFrame:
    df = df1m.copy()
    df["datetime"] = pd.to_datetime(df["datetime"])
    today_mask = df["datetime"].dt.date == target_date
    df = df[today_mask].sort_values("datetime").copy()
    if df.empty:
        return pd.DataFrame()

    df = df.set_index("datetime")
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df5 = df.resample("5min", label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna(subset=["open", "close"])
    return df5


def fetch_5min_kbar(ticker: str, target_date: date) -> pd.DataFrame:
    """從 Fubon 抓 1 分 K，聚合成 5 分 K，只回傳 target_date 當日資料."""
    try:
        client = _get_fubon()
        df1m = client.load_kbar(ticker, days=2)
        if df1m is None or df1m.empty:
            return pd.DataFrame()
        return _build_5min_from_1min(df1m, target_date)
    except Exception as e:
        log.warning("fetch_5min_kbar(%s) 失敗: %s", ticker, e)
        return pd.DataFrame()


def fetch_snapshot_price(ticker: str) -> Optional[float]:
    try:
        client = _get_fubon()
        snap = client.get_realtime_snapshot(ticker)
        if snap is None:
            return None
        for key in ("close", "last", "price", "lastPrice"):
            v = snap.get(key) if isinstance(snap, dict) else getattr(snap, key, None)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        return None
    except Exception as e:
        log.warning("fetch_snapshot_price(%s) 失敗: %s", ticker, e)
        return None


# ── 模擬資料 (--simulate-date) ────────────────────────────────────────────────

def _build_simulated_5k_1605() -> pd.DataFrame:
    """1605 2026-06-02 模擬 5 分 K（精簡版、覆蓋測試案例）."""
    # open_price = 40.5, prev_close = 39.8 → 跳空 +1.75% < 5%  (不觸紅線 #1)
    # 09:05 探底 38.7 → 紅線 #3 阻擋 (前 10 分鐘)
    # 11:30 二次探底 38.7 → 開始 watch
    # 11:35 反彈紅 K → signal (1 根、未 confirmed)
    # 12:50 量爆突破 40.0 → signal 強化
    # 13:00 第 3 根確認 → confirmed ✅
    sim_rows = [
        # ts, open, high, low, close, volume
        ("2026-06-02 09:00", 40.5, 40.6, 40.3, 40.4, 1200),
        ("2026-06-02 09:05", 40.4, 40.5, 38.7, 39.0, 3500),   # 探底、前 10 分鐘
        ("2026-06-02 09:10", 39.0, 39.5, 38.9, 39.2, 2000),
        ("2026-06-02 09:15", 39.2, 39.6, 39.0, 39.5, 1500),
        ("2026-06-02 09:20", 39.5, 39.8, 39.2, 39.3, 1100),
        ("2026-06-02 09:30", 39.3, 39.5, 39.1, 39.2, 900),
        ("2026-06-02 09:35", 39.2, 39.4, 38.9, 39.0, 950),
        ("2026-06-02 09:40", 39.0, 39.3, 38.8, 39.1, 850),
        ("2026-06-02 10:00", 39.1, 39.3, 38.9, 39.0, 750),
        ("2026-06-02 10:05", 39.0, 39.2, 38.8, 38.9, 700),
        ("2026-06-02 10:30", 38.9, 39.1, 38.7, 38.8, 720),
        ("2026-06-02 11:00", 38.8, 39.0, 38.6, 38.9, 700),
        ("2026-06-02 11:30", 38.9, 39.0, 38.7, 38.75, 680),   # 二次探底接近 38.7
        ("2026-06-02 11:35", 38.75, 39.2, 38.7, 39.1, 1900),  # 反彈紅 K (1 根 signal)
        ("2026-06-02 11:40", 39.1, 39.3, 39.0, 39.2, 1600),   # 第 2 根守住
        ("2026-06-02 12:00", 39.2, 39.5, 39.1, 39.3, 1400),
        ("2026-06-02 12:30", 39.3, 39.6, 39.2, 39.4, 1300),
        ("2026-06-02 12:50", 39.4, 40.1, 39.3, 40.0, 4200),   # 量爆突破 40
        ("2026-06-02 12:55", 40.0, 40.3, 39.9, 40.1, 3100),   # 第 2 根守住
        ("2026-06-02 13:00", 40.1, 40.4, 40.0, 40.2, 2800),   # 第 3 根確認 ✅
        ("2026-06-02 13:05", 40.2, 40.5, 40.1, 40.4, 2200),
        ("2026-06-02 13:15", 40.4, 40.6, 40.2, 40.2, 1800),
    ]
    rows = [{"datetime": pd.Timestamp(r[0]), "open": r[1], "high": r[2],
             "low": r[3], "close": r[4], "volume": r[5]} for r in sim_rows]
    df = pd.DataFrame(rows).set_index("datetime")
    return df


# ── Trigger 判斷邏輯 ──────────────────────────────────────────────────────────

def _df_to_arrays(df: pd.DataFrame):
    """Extract OHLCV numpy arrays + HH:MM time strings from a 5-min K-bar DataFrame.

    Hot-loop perf helper: trigger functions used to do thousands of pandas scalar
    lookups per call. Pulling arrays once and operating on numpy is ~50x faster
    with identical results (see /tmp/bench_trigger2.py).
    """
    opens  = df["open"].to_numpy(dtype=np.float64)
    highs  = df["high"].to_numpy(dtype=np.float64)
    lows   = df["low"].to_numpy(dtype=np.float64)
    closes = df["close"].to_numpy(dtype=np.float64)
    vols   = df["volume"].to_numpy(dtype=np.float64)
    idx = df.index
    if len(idx) and hasattr(idx[0], "strftime"):
        times = [t.strftime("%H:%M") for t in idx]
    else:
        times = [str(t)[11:16] for t in idx]
    return opens, highs, lows, closes, vols, times


def _check_trigger_1_np(opens, highs, lows, closes, vols, times,
                        prev_high: Optional[float]) -> dict:
    """numpy port of check_trigger_1."""
    n = len(closes)
    result = {"triggered": False, "level": "watch", "reason": "", "price": 0.0, "suggested_size": 0}
    if n < 5:
        result["reason"] = "5K 資料不足"
        return result

    open_price = float(opens[0])
    current_close = float(closes[-1])
    result["price"] = current_close

    # 連 2 紅K
    if not (closes[n - 1] > opens[n - 1] and closes[n - 2] > opens[n - 2]):
        result["reason"] = "未達連 2 紅K"
        return result

    # 量增：最後 1 根量 ≥ rolling(min(n,20), min_periods=1).mean().iloc[-1] × 1.5
    win = 20 if n >= 20 else n
    vol_5d_avg = float(vols[n - win:n].mean())
    last_vol = float(vols[n - 1])
    vol_ratio = last_vol / vol_5d_avg if vol_5d_avg > 0 else 0
    if vol_ratio < 1.5:
        result["reason"] = f"量增不足 (×{vol_ratio:.2f} < 1.5)"
        return result

    rebound_pct = (current_close / open_price - 1) * 100
    if rebound_pct <= 1.0:
        result["reason"] = f"距開盤反彈 {rebound_pct:.1f}% ≤ 1%"
        return result

    if prev_high is not None and current_close < prev_high:
        result["reason"] = f"未站穩前波高 {prev_high:.2f}"
        return result

    t_str = times[n - 1] if n - 1 < len(times) else "09:30"
    if "09:15" <= t_str < "09:45":
        result["level"] = "T1_watch"
        result["reason"] = (
            f"T1 觸發但 9:15-9:45 拉高出貨時段、等 9:45+ "
            f"(連 2 紅K + 量×{vol_ratio:.1f} + 反彈+{rebound_pct:.1f}%"
            + (f" + 站前波高 {prev_high:.2f}" if prev_high else "")
            + ")"
        )
        return result

    day_high = float(highs.max())
    if day_high > 0 and current_close >= day_high * 0.985:
        result["level"] = "T1_watch"
        result["reason"] = (
            f"T1 觸發但太接近日高 ${day_high:.2f}、等回測 -1.5% 再切入"
        )
        return result

    result["triggered"] = True
    result["level"] = "confirmed"
    result["reason"] = (
        f"連 2 紅K + 量×{vol_ratio:.1f} + 反彈+{rebound_pct:.1f}%"
        + (f" + 站前波高 {prev_high:.2f}" if prev_high else "")
    )
    result["suggested_size"] = 1
    return result


def _check_ch5_3_entry_np(opens, highs, lows, closes, vols, times,
                          prev_close: float, ma10: Optional[float],
                          market_regime: str) -> dict:
    """numpy port of check_ch5_3_entry."""
    result: dict = {
        "triggered": False,
        "level": "watch",
        "reason": "",
        "stop_loss": None,
        "stop_anchors": {},
    }
    n = len(closes)
    if n < 1:
        result["reason"] = "5K 不足"
        return result

    open_p  = float(opens[0])
    high_p  = float(highs[0])
    low_p   = float(lows[0])
    close_p = float(closes[0])

    red_k            = close_p > open_p
    gap_pct          = (open_p - prev_close) / prev_close * 100 if prev_close > 0 else 999
    close_above_prev = close_p >= prev_close
    close_above_open = close_p >= open_p
    body             = abs(close_p - open_p)
    upper            = high_p - max(close_p, open_p)
    body_gt_shadow   = body > upper
    chg_pct          = (close_p - open_p) / open_p * 100 if open_p > 0 else 0
    rise_under_4     = chg_pct < 4.0
    gap_ok           = gap_pct < 5.0

    all_pass = all([red_k, close_above_prev, close_above_open,
                    body_gt_shadow, rise_under_4, gap_ok])

    if not all_pass:
        fails = []
        if not red_k:            fails.append("非紅K")
        if not gap_ok:           fails.append(f"跳空 {gap_pct:.1f}% ≥ 5%")
        if not close_above_prev: fails.append(f"收盤 {close_p:.2f} < 前收 {prev_close:.2f}")
        if not close_above_open: fails.append("收盤 < 開盤 (雙錨失守)")
        if not body_gt_shadow:   fails.append(f"實體 {body:.2f} ≤ 上影 {upper:.2f}")
        if not rise_under_4:     fails.append(f"漲幅 {chg_pct:.1f}% ≥ 4%")
        result["level"] = "fail"
        result["reason"] = "第一根 5K 不符: " + ", ".join(fails)
        return result

    first_low = low_p
    stop_loss = max(first_low, prev_close)
    result["stop_loss"] = stop_loss
    result["stop_anchors"] = {
        "first_5k_low": first_low,
        "prev_close": prev_close,
    }

    first_high = high_p
    _regime = market_regime.lower() if market_regime else "normal"

    if _regime in ("strong", "normal"):
        for i in range(1, n):
            t_str = times[i]
            if t_str < "09:10":
                continue
            bar_close = float(closes[i])
            bar_open  = float(opens[i])
            if bar_close > first_high and bar_close > bar_open:
                if "09:15" <= t_str < "09:45":
                    result["level"] = "signal"
                    result["reason"] = (
                        f"Ch5-3 [{_regime}盤] 訊號觸發 {t_str}、"
                        f"但 9:15-9:45 拉高出貨時段、等 9:45 後確認"
                    )
                    result["regime"] = _regime
                    return result

                if t_str >= "09:45":
                    day_high_so_far = float(highs[:i + 1].max())
                    if bar_close >= day_high_so_far * 0.99:
                        result["level"] = "signal"
                        result["reason"] = (
                            f"Ch5-3 [{_regime}盤] 訊號觸發 {t_str}、"
                            f"但太接近日高 ${day_high_so_far:.2f}、等回測 -1% 再切入"
                        )
                        result["regime"] = _regime
                        return result

                result["triggered"] = True
                result["level"] = "confirmed"
                result["reason"] = (
                    f"Ch5-3 [{_regime}盤] {t_str} 過高 {first_high:.2f} 站穩"
                )
                result["entry_price"] = bar_close
                result["entry_time"]  = t_str
                result["regime"] = _regime
                return result

        result["level"] = "watch"
        result["reason"] = f"Ch5-3 [{_regime}盤] 第一根全 pass、等 9:10 後過高 {first_high:.2f}"
        result["regime"] = _regime
        return result

    # weak regime
    signal_idx: Optional[int] = None
    for i in range(1, n):
        ts_str = times[i]
        if ts_str < "09:10":
            continue
        if ts_str >= "09:30":
            break
        bar_close = float(closes[i])
        bar_open  = float(opens[i])
        if bar_close > first_high and bar_close > bar_open:
            signal_idx = i
            break

    if signal_idx is None:
        result["level"] = "watch"
        result["reason"] = f"Ch5-3 [弱勢盤] 第一根全 pass、等 9:10-9:30 過高 {first_high:.2f}"
        result["regime"] = "weak"
        return result

    result["level"] = "signal"
    result["regime"] = "weak"
    if ma10 is not None:
        result["reason"] = f"[弱勢盤] 訊號觸發 {times[signal_idx]} 過高 {first_high:.2f}、等回踩 MA10 ({ma10:.2f})"
    else:
        result["reason"] = f"[弱勢盤] 訊號觸發 {times[signal_idx]} 過高 {first_high:.2f}、MA10 未知"

    if ma10 is None or ma10 <= 0:
        return result

    MA10_BAND = 0.02
    for i in range(signal_idx + 1, n):
        bar_low   = float(lows[i])
        bar_close = float(closes[i])
        bar_open  = float(opens[i])

        touched_ma10 = bar_low <= ma10 * (1 + MA10_BAND) and bar_low >= ma10 * (1 - MA10_BAND)

        if touched_ma10:
            result["level"] = "pullback"
            result["reason"] = f"[弱勢盤] 回踩 MA10 {ma10:.2f} 中、等收紅 K 守住"
            if bar_close > bar_open and bar_close > ma10:
                result["triggered"] = True
                result["level"] = "confirmed"
                result["reason"] = (
                    f"[弱勢盤] 過高 {first_high:.2f} + 回踩 MA10 {ma10:.2f} 守住 "
                    f"(紅K {times[i]})"
                )
                result["entry_price"] = bar_close
                result["entry_time"]  = times[i]
                return result

    if result["level"] == "pullback":
        result["reason"] = f"[弱勢盤] 回踩 MA10 {ma10:.2f} 中、等收紅 K 守住"
    else:
        result["reason"] = f"[弱勢盤] 訊號觸發、等回踩 MA10 ({ma10:.2f})"
    return result


def _check_trigger_c_np(opens, highs, lows, closes, vols, times,
                        prev_low: Optional[float]) -> dict:
    """numpy port of check_trigger_c (結構失敗)."""
    n = len(closes)
    result = {"triggered": False, "level": "watch", "reason": "", "price": 0.0, "suggested_size": 0}
    if n < 5:
        result["reason"] = "5K 資料不足"
        return result

    current_close = float(closes[-1])
    result["price"] = current_close

    # MA10 = rolling(10, min_periods=1).mean().iloc[-1]
    win10 = 10 if n >= 10 else n
    ma10 = float(closes[n - win10:n].mean())
    dist_ma10_pct = (current_close / ma10 - 1) * 100 if ma10 > 0 else 0

    # vol_avg = rolling(min(n,20), min_periods=1).mean().iloc[-1]
    win20 = 20 if n >= 20 else n
    vol_avg = float(vols[n - win20:n].mean())
    last_vol = float(vols[n - 1])
    vol_ratio = last_vol / vol_avg if vol_avg > 0 else 0
    last_black = float(closes[n - 1]) < float(opens[n - 1])

    broken_structure = False
    reason_parts = []

    if prev_low is not None and current_close < prev_low:
        broken_structure = True
        reason_parts.append(f"跌破前波低 {prev_low:.2f}")

    if dist_ma10_pct <= -3.0:
        broken_structure = True
        reason_parts.append(f"距 MA10 {dist_ma10_pct:.1f}%")

    if not broken_structure:
        result["reason"] = f"結構未破壞 (距MA10 {dist_ma10_pct:.1f}%)"
        return result

    if not (vol_ratio >= 1.5 and last_black):
        result["level"] = "signal"
        result["reason"] = "、".join(reason_parts) + f" (量×{vol_ratio:.1f}、等量爆確認)"
        return result

    result["triggered"] = True
    result["level"] = "confirmed"
    result["reason"] = "、".join(reason_parts) + f"、量×{vol_ratio:.1f} 恐慌賣壓"
    return result


def _check_trigger_2_np(opens, highs, lows, closes, vols, times) -> dict:
    """numpy port of check_trigger_2. Logic must stay byte-equal to the pandas
    version — backtest determinism depends on it."""
    n = len(closes)
    result = {"triggered": False, "level": "watch", "reason": "", "price": 0.0, "suggested_size": 0}
    if n < 3:
        result["reason"] = "5K 資料不足"
        return result

    current_close = float(closes[-1])
    result["price"] = current_close

    intraday_high = float(highs.max())
    last_low = float(lows[-1])
    pullback_pct = (last_low - intraday_high) / intraday_high * 100
    if pullback_pct > -2.5:
        result["reason"] = f"未跌深 {pullback_pct:.1f}% (需 ≤ -2.5%、盤中高 {intraday_high:.2f})"
        return result

    low_idx = int(lows.argmin())
    low_price = float(lows[low_idx])

    after_low_len = n - low_idx - 1
    if after_low_len < 2:
        result["level"] = "watch"
        result["reason"] = f"跌深 {pullback_pct:.1f}% (盤中高 {intraday_high:.2f})、低後 K 不足等確認"
        return result

    # 路徑 A: 連續 3 紅K + 距低反彈 ≥ 1%
    after_start = low_idx + 1
    tail3_start = max(after_start, n - 3)
    tail3_len = n - tail3_start
    if tail3_len >= 3:
        all_red = bool(np.all(closes[tail3_start:n] > opens[tail3_start:n]))
        rebound = (float(closes[n - 1]) - low_price) / low_price * 100
        if all_red and rebound >= 1.0:
            t_str2 = times[n - 1]
            if "09:15" <= t_str2 < "09:45":
                result["level"] = "T2_watch"
                result["reason"] = (
                    f"T2 觸發但 9:15-9:45 拉高出貨時段、等 9:45+ "
                    f"(跌深 {pullback_pct:.1f}% + 3 紅K + 反彈 {rebound:.1f}%)"
                )
                return result
            day_high_t2 = intraday_high
            confirm_close = float(closes[n - 1])
            if day_high_t2 > 0 and confirm_close >= day_high_t2 * 0.985:
                result["level"] = "T2_watch"
                result["reason"] = (
                    f"T2 觸發但太接近日高 ${day_high_t2:.2f}、等回測 -1.5% 再切入"
                )
                return result
            result["triggered"] = True
            result["level"] = "confirmed"
            result["reason"] = (
                f"跌深 {pullback_pct:.1f}% (盤中高 {intraday_high:.2f})"
                f" + 3 紅K + 反彈 {rebound:.1f}%"
            )
            result["price"] = float(closes[n - 1])
            result["suggested_size"] = 1
            result["path"] = "A (3 紅K)"
            return result

    # 路徑 B: 5m diff 由負轉正 + 09:10 後 + 紅K + 量 ≥ 5 根平均
    if n >= 3:
        diff_prev = float(closes[n - 2]) - float(closes[n - 3])
        diff_now  = float(closes[n - 1]) - float(closes[n - 2])
        current_time = times[n - 1]
        v_start = max(0, n - 5)
        vol_mean5 = float(vols[v_start:n].mean())
        if (
            diff_prev < 0
            and diff_now > 0
            and current_time >= "09:10"
            and float(closes[n - 1]) > float(opens[n - 1])
            and float(vols[n - 1]) >= vol_mean5
        ):
            if "09:15" <= current_time < "09:45":
                result["level"] = "T2_watch"
                result["reason"] = (
                    f"T2(B) 觸發但 9:15-9:45 拉高出貨時段、等 9:45+ "
                    f"(跌深 {pullback_pct:.1f}% + 5m diff 轉正)"
                )
                return result
            day_high_b = intraday_high
            close_b = float(closes[n - 1])
            if day_high_b > 0 and close_b >= day_high_b * 0.985:
                result["level"] = "T2_watch"
                result["reason"] = (
                    f"T2(B) 觸發但太接近日高 ${day_high_b:.2f}、等回測 -1.5%"
                )
                return result
            result["triggered"] = True
            result["level"] = "confirmed"
            result["reason"] = (
                f"跌深 {pullback_pct:.1f}% (盤中高 {intraday_high:.2f})"
                f" + 5m diff 由負轉正 (early signal)"
            )
            result["price"] = float(closes[n - 1])
            result["suggested_size"] = 1
            result["path"] = "B (5m diff)"
            return result

    result["level"] = "watch"
    result["reason"] = f"跌深 {pullback_pct:.1f}% (盤中高 {intraday_high:.2f})、等確認"
    return result


class StageTrigger:

    def check_discipline_filter(
        self,
        ticker: str,
        k5: pd.DataFrame,
        now_time: datetime,
        prev_close: Optional[float],
        disable: bool = False,
    ) -> tuple[bool, str]:
        """紅線 #1/#2/#3 過濾。回傳 (pass, reason)。"""
        if disable:
            return True, "紀律過濾已停用 (--no-discipline)"

        if k5.empty:
            return False, "5K 資料為空"

        open_price = float(k5["open"].iloc[0])

        # 紅線 #3: 09:00-09:10 不觸發 entry
        t = now_time.time()
        if t.hour == 9 and t.minute < 10:
            return False, f"紅線 #3: 前 10 分鐘 ({t.strftime('%H:%M')}) 不觸發"

        # 紅線 #1: 跳空 ≥ +5% 不觸發
        if prev_close and prev_close > 0:
            gap_pct = (open_price / prev_close - 1) * 100
            if gap_pct >= 5.0:
                return False, f"紅線 #1: 跳空 +{gap_pct:.1f}% ≥ 5% 不觸發"

        # 紅線 #2: 距 MA10 > +10%
        closes = k5["close"]
        ma10 = closes.rolling(10, min_periods=1).mean().iloc[-1]
        current = float(closes.iloc[-1])
        if ma10 > 0:
            dist_pct = (current / ma10 - 1) * 100
            if dist_pct > 10.0:
                return False, f"紅線 #2: 距 MA10 +{dist_pct:.1f}% > 10% 不觸發"

        return True, "通過紀律過濾"

    def check_trigger_1(
        self,
        ticker: str,
        k5: pd.DataFrame,
        prev_high: Optional[float],
    ) -> dict:
        """強勢延續訊號 (連 2 紅K + 量增 + 站前波高 + 距開盤 >+1%)."""
        if len(k5) < 5:
            return {"triggered": False, "level": "watch",
                    "reason": "5K 資料不足", "price": 0.0, "suggested_size": 0}
        opens, highs, lows, closes, vols, times = _df_to_arrays(k5)
        return _check_trigger_1_np(opens, highs, lows, closes, vols, times, prev_high)

    def check_trigger_2(
        self,
        ticker: str,
        k5: pd.DataFrame,
        now_time: datetime,
    ) -> dict:
        """中盤反彈訊號 — 改用盤中最高算跌深 (≥ 2.5%)，支援路徑 A (3 紅 K) 和路徑 B (5m diff)。

        舊 now_time 參數保留向後相容，但不再做時段限制 (任何時段均可觸發)。
        prev_levels 已不需要，只依賴當日 k5。

        Hot-loop perf: backtest 中此函式被呼叫 ~5 萬次、占 cumtime ~29s；改走 numpy
        實作（_check_trigger_2_np）後同邏輯 ~52x 加速、回測結果 byte-equal。
        """
        if len(k5) < 3:
            return {"triggered": False, "level": "watch",
                    "reason": "5K 資料不足", "price": 0.0, "suggested_size": 0}
        opens, highs, lows, closes, vols, times = _df_to_arrays(k5)
        return _check_trigger_2_np(opens, highs, lows, closes, vols, times)

    def check_trigger_2_legacy(
        self,
        ticker: str,
        k5: pd.DataFrame,
        now_time: datetime,
    ) -> dict:
        """舊版 check_trigger_2 (時段 11:00-12:30、二次探底、3 根確認)。保留供回溯比較。"""
        result = {"triggered": False, "level": "watch", "reason": "", "price": 0.0, "suggested_size": 0}

        if len(k5) < 8:
            result["reason"] = "5K 資料不足"
            return result

        current_close = float(k5["close"].iloc[-1])
        result["price"] = current_close

        t = now_time.time()
        in_window = (t.hour == 11 or (t.hour == 12 and t.minute <= 30))
        confirm_window = (t.hour == 12 and t.minute > 30) or (t.hour == 13 and t.minute <= 10)
        if not (in_window or confirm_window):
            result["reason"] = f"不在中盤反彈時段 ({t.strftime('%H:%M')})"
            return result

        morning_bars = k5.between_time("09:10", "11:00") if hasattr(k5.index, "time") else k5
        if morning_bars.empty:
            result["reason"] = "早盤資料不足、無法找前波低"
            return result
        first_low = float(morning_bars["low"].min())

        recent = k5.tail(6)
        recent_low = float(recent["low"].min())
        low_diff_pct = abs(recent_low - first_low) / first_low * 100
        if low_diff_pct > 1.5:
            result["reason"] = f"二次低點 {recent_low:.2f} 與前波低 {first_low:.2f} 相差 {low_diff_pct:.1f}% > 1.5%"
            return result

        vol_avg = k5["volume"].rolling(min(len(k5), 20), min_periods=1).mean()
        recent_with_avg = recent.copy()
        recent_with_avg["vol_avg"] = vol_avg.reindex(recent.index)
        breakout_bars = recent_with_avg[recent_with_avg["close"] > recent_with_avg["open"]]
        volume_burst = any(
            float(row["volume"]) >= float(row["vol_avg"]) * 2
            for _, row in breakout_bars.iterrows()
            if float(row["vol_avg"]) > 0
        )

        last3 = k5.tail(3)
        if len(last3) < 3:
            result["level"] = "signal"
            result["reason"] = f"二次探底確認中、等 3 根 (現 {len(last3)} 根)"
            return result

        confirmed = True
        for i in range(1, len(last3)):
            if float(last3["close"].iloc[i]) < float(last3["low"].iloc[i - 1]):
                confirmed = False
                break

        first_bar_red = float(last3["close"].iloc[0]) > float(last3["open"].iloc[0])
        if not confirmed or not first_bar_red:
            if recent_low <= first_low * 1.015:
                result["level"] = "signal"
                result["reason"] = f"二次探底 {recent_low:.2f}、等 3 根確認"
            else:
                result["reason"] = "3 根確認條件未成立"
            return result

        vol_x = float(k5["volume"].iloc[-3]) / float(vol_avg.iloc[-3]) if float(vol_avg.iloc[-3]) > 0 else 0
        rebound_pct = (current_close / recent_low - 1) * 100

        result["triggered"] = True
        result["level"] = "confirmed"
        result["reason"] = (
            f"二次探底 {recent_low:.2f} 反彈 +{rebound_pct:.1f}%、3 根確認"
            + (f"、量×{vol_x:.1f}" if volume_burst else "")
        )
        result["suggested_size"] = 1
        return result

    def check_trigger_c(
        self,
        ticker: str,
        k5: pd.DataFrame,
        prev_low: Optional[float],
    ) -> dict:
        """結構失敗 (跌破前波低 + 距 MA10 -3% + 量爆下行)."""
        if len(k5) < 5:
            return {"triggered": False, "level": "watch",
                    "reason": "5K 資料不足", "price": 0.0, "suggested_size": 0}
        opens, highs, lows, closes, vols, times = _df_to_arrays(k5)
        return _check_trigger_c_np(opens, highs, lows, closes, vols, times, prev_low)

    # ── 大盤環境判別 ───────────────────────────────────────────────────────────

    @staticmethod
    def _detect_market_regime(target_date: str, db_path: Path = _DB) -> str:
        """判別大盤環境 (TAIEX 收盤 vs 開盤)。

        Returns:
            'strong': 大盤漲 > +0.5% 且站 MA5
            'normal': 大盤 -1% ~ +0.5%
            'weak':   大盤跌 > -1% (收跌幅超 1%) 或收破 MA5

        Layer 1 (優先): Fubon IX0001 即時 snapshot — 取 (close/open - 1) * 100
          - 若 TAIEX 盤中 chg% <= -1.0 → weak
          - 若 TAIEX 盤中 chg% >  0.5  → strong
          - 否則 → normal
          - 即時不知道 MA5、簡化判斷

        Layer 2 (fallback): standard_daily_bar WHERE ticker='TAIEX'
          - 若 target_date 有當日資料 → 用當日 close/open/ma5
          - 若無 (盤中即時) → 用前一交易日作 fallback
        """
        # ── Layer 1: 即時 IX0001 snapshot ─────────────────────────────────────
        try:
            client = _get_fubon()
            snap = client.get_realtime_snapshot('IX0001') or {}
            op = float(snap.get('open') or 0)
            cl = float(snap.get('close') or 0)
            if op > 0 and cl > 0:
                chg_pct = (cl / op - 1) * 100
                if chg_pct <= -1.0:
                    return "weak"
                elif chg_pct > 0.5:
                    return "strong"
                else:
                    return "normal"
        except Exception as _e:
            log.debug("_detect_market_regime IX0001 snapshot 失敗、fallback daily bar: %s", _e)

        # ── Layer 2: fallback daily bar (現有邏輯) ────────────────────────────
        try:
            for attempt in range(3):
                try:
                    con = get_conn(db_path, timeout=10)
                    # 先嘗試取當日
                    row = con.execute(
                        "SELECT close, open, ma5 FROM standard_daily_bar "
                        "WHERE ticker='TAIEX' AND trade_date=?",
                        (target_date,),
                    ).fetchone()
                    if not row:
                        # fallback: 前一交易日
                        row = con.execute(
                            "SELECT close, open, ma5 FROM standard_daily_bar "
                            "WHERE ticker='TAIEX' AND trade_date<? "
                            "ORDER BY trade_date DESC LIMIT 1",
                            (target_date,),
                        ).fetchone()
                    con.close()
                    break
                except sqlite3.OperationalError as e:
                    if attempt == 2:
                        log.warning("_detect_market_regime DB 失敗: %s", e)
                        return "normal"
                    time.sleep(1)
            else:
                return "normal"

            if not row:
                return "normal"

            taiex_close = float(row[0])
            taiex_open  = float(row[1])
            taiex_ma5   = float(row[2]) if row[2] else None

            # 收盤 vs 開盤日內漲跌幅
            chg_pct = (taiex_close / taiex_open - 1) * 100 if taiex_open > 0 else 0.0

            below_ma5 = (taiex_ma5 is not None and taiex_close < taiex_ma5)

            if chg_pct <= -1.0 or below_ma5:
                return "weak"
            elif chg_pct > 0.5 and (taiex_ma5 is None or taiex_close >= taiex_ma5):
                return "strong"
            else:
                return "normal"

        except Exception as e:
            log.warning("_detect_market_regime 例外: %s", e)
            return "normal"

    # ── Ch5-3 第一根 5K SOP ────────────────────────────────────────────────────

    def check_ch5_3_entry(
        self,
        k5: pd.DataFrame,
        prev_close: float,
        ma10: Optional[float] = None,
        ticker: Optional[str] = None,
        target_date: Optional[str] = None,
        market_regime: str = "normal",  # 'strong' / 'normal' / 'weak'
    ) -> dict:
        """Ch5-3 第一根 5K SOP 評估 (老師 5/19 實戰課完整版)。

        雙路徑 (依 market_regime 切換):
          normal / strong:
            舊版邏輯 — 9:10 後過第一根高 + 紅K = confirmed (直接進場)
            不需要回踩 MA10
            來源: 其他當沖課程教學 (正常盤 SOP)

          weak:
            新版邏輯 — 過高 = signal、等回踩 MA10 ±2% 守住 = confirmed
            弱勢盤主升股不可信、等回踩確認
            來源: 老師 5/19 弱勢盤教學 (當日大盤跌 700 點)
            額外限制: 弱勢盤 9:30 後不再觸發 Ch5-3

        6 條件 (第一根、兩路徑共用):
          1. 紅K
          2. 跳空 < 5%
          3. 收盤 ≥ 前日收盤 (close_above_prev)
          4. 收盤 ≥ 開盤 (雙錨)
          5. 實體 > 上影線 (body_gt_shadow)
          6. 5K 漲幅 < 4% (rise_under_4)

        State 機 (normal/strong):
          fail    → 第一根 6/6 不過
          watch   → 9:10 前 / 沒過第一根高、純觀察
          confirmed → 9:10 後過第一根高 紅K = 直接進場

        State 機 (weak):
          fail      → 第一根 6/6 不過
          watch     → 9:10 前 / 沒過第一根高、純觀察
          signal    → 9:10 後過第一根高 (通知、不直接切入)
          pullback  → 過高後回踩 MA10 附近 (距 -2%~+2%)
          confirmed → pullback 期間 5K 紅K + 收盤 > MA10 → 正式進場

        雙錨停損 = max(第一根 5K 低、昨日收盤)
        """
        if ma10 is None and ticker and target_date:
            ma10 = _get_ma10(ticker, target_date)

        if len(k5) < 1:
            return {
                "triggered": False, "level": "watch",
                "reason": "5K 不足", "stop_loss": None, "stop_anchors": {},
            }
        opens, highs, lows, closes, vols, times = _df_to_arrays(k5)
        return _check_ch5_3_entry_np(
            opens, highs, lows, closes, vols, times,
            prev_close, ma10, market_regime,
        )

    # ── Closing Check (13:00-13:25 尾盤進場確認) ──────────────────────────────

    def check_closing_panel(
        self,
        ticker: str,
        k5: pd.DataFrame,
        ma5: Optional[float] = None,
        ma10: Optional[float] = None,
        target_date: Optional[str] = None,
        db_path: Path = _DB,
        _now_override: Optional[str] = None,
    ) -> dict:
        """13:00-13:25 尾盤進場 5 項確認。

        老師說「尾盤才能進」的客觀條件版本。
        backtest 證實 13:00 進場 Win rate 80.8% 最高（v6 backtest）。

        Args:
            ticker:          股票代號
            k5:              全日 5 分 K DataFrame (index = datetime)
            ma5:             日線 MA5（前一日）；None → 從 5K 推算
            ma10:            日線 MA10（前一日）；None → 查 DB
            target_date:     YYYY-MM-DD；None → 今日
            db_path:         SQLite DB 路徑
            _now_override:   'HH:MM' 字串，測試用覆蓋現在時間

        Returns:
            {
                'triggered':  bool,
                'level':      'confirmed' / 'overheated' / 'skip' / 'not_in_window',
                              # confirmed = 3-4/5 Win 82% 最佳進場 (triggered=True)
                              # overheated = 5/5 Win 40% 過熱不追 (triggered=False)
                              # skip = <3/5 不進 (triggered=False)
                'reason':     str,
                'scores': {
                    'structure_hold':    bool,   # 1. close > MA10
                    'kill_test_passed':  bool,   # 2. 12:00 後有觸低 (殺盤考驗過)
                    'rebound_confirmed': bool,   # 3. 13:00 後連續 2 根紅K (單根/站MA5 已移除)
                    'volume_calm':       bool,   # 4. 尾盤 per-bar 量 < 早盤 per-bar 量 × 1.2
                    'not_chasing_high':  bool,   # 5. 距日高 < +1.5%
                },
                'pass_count':  int,  # 0-5
            }
        """
        base = {
            "triggered": False,
            "level": "not_in_window",
            "reason": "不在 13:00-13:25 時段",
            "scores": {
                "structure_hold":    False,
                "kill_test_passed":  False,
                "rebound_confirmed": False,
                "volume_calm":       False,
                "not_chasing_high":  False,
            },
            "pass_count": 0,
        }

        if k5 is None or k5.empty:
            base["reason"] = "5K 資料為空"
            return base

        # 1. 時段檢查
        if _now_override:
            now_str = _now_override
        else:
            now_str = datetime.now().strftime("%H:%M")

        if not ("13:05" <= now_str <= "13:25"):
            return base

        # 獲取 MA10 (日線)
        if ma10 is None and ticker and target_date:
            ma10 = _get_ma10(ticker, target_date, db_path)

        # 若 MA10 未知，退化到用 5K 近 10 根均
        if ma10 is None or ma10 <= 0:
            ma10_raw = k5["close"].rolling(10, min_periods=3).mean()
            ma10 = float(ma10_raw.iloc[-1]) if not ma10_raw.empty else 0.0

        # 若 MA5 未知，用 5K 近 5 根均 (日線 MA5 代理)
        if ma5 is None or ma5 <= 0:
            ma5_raw = k5["close"].rolling(5, min_periods=3).mean()
            ma5 = float(ma5_raw.iloc[-1]) if not ma5_raw.empty else 0.0

        current_close = float(k5["close"].iloc[-1])
        day_high = float(k5["high"].max())

        # 2. 條件 1: 結構守住 — close > MA10
        cond1 = (ma10 > 0 and current_close > ma10)

        # 3. 條件 2: 殺盤考驗過
        #    - 12:00 後最低 < 早盤最高 -2%  OR  12:00 後最低 < MA5 -1%
        afternoon_k5 = k5[k5.index.strftime("%H:%M") >= "12:00"] if hasattr(k5.index, "strftime") else pd.DataFrame()
        if afternoon_k5.empty:
            # 如果 index 不是 datetime-like，試用 iloc 近似
            afternoon_k5 = k5.tail(max(1, len(k5) // 3))

        morning_k5 = k5[k5.index.strftime("%H:%M") < "12:00"] if hasattr(k5.index, "strftime") else k5.head(max(1, len(k5) // 2))
        morning_high = float(morning_k5["high"].max()) if not morning_k5.empty else day_high

        after_12_low = float(afternoon_k5["low"].min()) if not afternoon_k5.empty else current_close
        kill_by_morning_high = (after_12_low < morning_high * 0.98)
        kill_by_ma5 = (ma5 > 0 and after_12_low < ma5 * 0.99)
        cond2 = kill_by_morning_high or kill_by_ma5

        # 4. 條件 3 / 4 — 先切出 13:00 後 5K
        after_13_k5 = k5[k5.index.strftime("%H:%M") >= "13:00"] if hasattr(k5.index, "strftime") else k5.tail(max(1, len(k5) // 6))

        # ── 資料不足保護：< 2 根 5K 不能判斷 ──────────────────────────────────────
        # Bug fix: 13:00 剛開始只有 1 根 5K 時、cond3/cond4 幾乎永遠 True
        # 必須等至少 2 根才有意義的量/反彈比較
        if len(after_13_k5) < 2:
            return {
                **base,
                "level": "watch",
                "reason": f"13:00 後僅 {len(after_13_k5)} 根 5K、資料不足、暫 watch",
                "pass_count": 0,
            }

        # 條件 3: 反彈確認 — 必須連續 2 根紅K
        # Bug fix: 移除「單根大紅 1.5%+」和「站 MA5」fallback (13:00 第 1 根站 MA5 太容易)
        rebound_2_red = False
        if len(after_13_k5) >= 2:
            last2 = after_13_k5.tail(2)
            rebound_2_red = bool((last2["close"] > last2["open"]).all())
        cond3 = rebound_2_red

        # 條件 4: 量縮確認 — per-bar 量比、非累積量
        # Bug fix: 原「累積量 < 全日均 × 根數 × 1.5」在 13:00 剛開始必 True
        # 改為「13:00 後 per-bar 平均量 < 早盤 per-bar 平均量 × 1.2」
        morning_k5 = k5[k5.index.strftime("%H:%M") < "13:00"] if hasattr(k5.index, "strftime") else k5.head(max(1, len(k5) - len(after_13_k5)))
        n_after_13 = len(after_13_k5)
        after_13_vol = float(after_13_k5["volume"].sum())
        afternoon_per_bar = after_13_vol / max(1, n_after_13)
        if not morning_k5.empty:
            morning_per_bar = float(morning_k5["volume"].mean())
            cond4 = afternoon_per_bar < morning_per_bar * 1.2
        else:
            cond4 = True  # 無早盤資料 fallback

        # 6. 條件 5: 未追高
        #    當前 close 距日高 < +1.5%
        # 未追高: close 距日高至少 -1.5% (避免買在尾盤最後一根衝高)
        # not_chasing_high = True 代表收盤還在日高下方 1.5% 以上、沒有追在最頂
        dist_below_high_pct = (day_high - current_close) / day_high * 100 if day_high > 0 else 99
        cond5 = dist_below_high_pct >= 1.5  # 距日高跌幅 ≥ 1.5% → 不是追在頂部

        scores = {
            "structure_hold":    cond1,
            "kill_test_passed":  cond2,
            "rebound_confirmed": cond3,
            "volume_calm":       cond4,
            "not_chasing_high":  cond5,
        }
        pass_count = sum(scores.values())

        # 7. 決定 level
        # v7 backtest 校正:
        #   5/5 = Win 40% / -0.78%  → overheated (已被拉走、不該追)
        #   3-4/5 = Win 82% / +1.62% → confirmed (最佳進場)
        #   <3/5 = Win 73% / +1.35%  → skip (不進)
        #
        # ⚠️ 2026-06-10 修正: 結構守住 (close > MA10) 設為必過條件。
        # 此前實作允許 3/5 pass 但結構失敗 → 破底股 (如 8064 -7.2%) 仍被標
        # 「最佳進場 Win 82%」嚴重誤導。老師明說「結構守住」是核心、backtest
        # 82% 樣本應該都有結構守住、此 patch 補上 implicit assumption。
        #
        # 📝 TODO (user 2026-06-10): MA10 之後想調鬆一點點 / 加彈性。
        # 候選做法:
        #   1. close > MA10 × 0.98 (容忍 -2% 微破、避免雞蛋裡挑骨頭)
        #   2. close > MA10 OR (close > MA20 AND 日內反彈 ≥ +3%)
        #   3. close 觸 MA10 後又站回 (盤中暫破不算)
        # 改之前要先 backtest 驗證不會把 Win 82% 樣本拉低。
        if not cond1:  # 結構失敗 (close < MA10) → 一律 skip、不論其他幾項過
            level = "skip"
        elif pass_count == 5:
            level = "overheated"
        elif pass_count >= 3:
            level = "confirmed"
        else:
            level = "skip"

        # 8. 組 reason 字串
        score_labels = {
            "structure_hold":    "結構",
            "kill_test_passed":  "殺盤",
            "rebound_confirmed": "反彈",
            "volume_calm":       "量縮",
            "not_chasing_high":  "未追高",
        }
        pass_parts  = [score_labels[k] for k, v in scores.items() if v]
        fail_parts  = [score_labels[k] for k, v in scores.items() if not v]
        pass_str    = "✓".join(pass_parts) if pass_parts else "—"
        reason_str  = f"{pass_count}/5 pass ({pass_str})"
        if fail_parts:
            reason_str += f"  ✗{','.join(fail_parts)}"

        # triggered = "可進場" 語意: confirmed (3-4/5) = True、overheated (5/5) 和 skip = False
        triggered = level in ("confirmed",)

        return {
            "triggered":  triggered,
            "level":      level,
            "reason":     reason_str,
            "scores":     scores,
            "pass_count": pass_count,
        }

    # ── Composite Cascade Detector ─────────────────────────────────────────────

    # Per-category action mapping (新中文 trigger 名為 primary；舊英文名 alias 向後相容)
    _CATEGORY_ACTION: dict[tuple[str, str], str] = {
        ("HELD",         "首攻"): "N/A (已持倉、首攻不適用)",
        ("HELD",         "續攻"): "Stage 2 加碼追高",
        ("HELD",         "反彈"): "Stage 2 反彈低接加碼",
        ("HELD",         "破底"): "🚨 出 Stage 1 警示",
        ("WATCH",        "首攻"): "Stage 1 試水進場 (首攻 SOP)",
        ("WATCH",        "續攻"): "Stage 1 試水追高",
        ("WATCH",        "反彈"): "Stage 1 反彈低接",
        ("WATCH",        "破底"): "⛔ 不要進、結構壞",
        ("PLAN_PRIMARY", "首攻"): "進場時機 (首攻)",
        ("PLAN_PRIMARY", "續攻"): "進場時機 (續攻)",
        ("PLAN_PRIMARY", "反彈"): "進場時機 (反彈)",
        ("PLAN_PRIMARY", "破底"): "⛔ skip 該檔",
        # 舊英文名 alias (向後相容)
        ("HELD",         "Ch5-3"): "N/A (已持倉、首攻不適用)",
        ("HELD",         "T1"):    "Stage 2 加碼追高",
        ("HELD",         "T2"):    "Stage 2 反彈低接加碼",
        ("HELD",         "TC"):    "🚨 出 Stage 1 警示",
        ("WATCH",        "Ch5-3"): "Stage 1 試水進場 (首攻 SOP)",
        ("WATCH",        "T1"):    "Stage 1 試水追高",
        ("WATCH",        "T2"):    "Stage 1 反彈低接",
        ("WATCH",        "TC"):    "⛔ 不要進、結構壞",
        ("PLAN_PRIMARY", "Ch5-3"): "進場時機 (首攻)",
        ("PLAN_PRIMARY", "T1"):    "進場時機 (續攻)",
        ("PLAN_PRIMARY", "T2"):    "進場時機 (反彈)",
        ("PLAN_PRIMARY", "TC"):    "⛔ skip 該檔",
    }

    def _format_action(self, result: dict, detector_type: str, category: str) -> dict:
        """Per-category action mapping，回傳含 detector / category / action 的 dict。"""
        action = self._CATEGORY_ACTION.get(
            (category, detector_type),
            "N/A",
        )
        return {
            **result,
            "triggered": True,
            "detector": detector_type,
            "category": category,
            "action": action,
        }

    def composite_check(
        self,
        ticker: str,
        k5: pd.DataFrame,
        prev_close: float,
        prev_levels: dict,
        category: str = "WATCH",
        target_date: Optional[str] = None,
    ) -> dict:
        """Cascade detector: 首攻 → 續攻 → 反彈 → 破底。

        新中文命名 (primary) 對應關係:
          首攻  = Ch5-3  (第一根 5K SOP)
          續攻  = T1     (強勢延續)
          反彈  = T2     (跌深反彈)
          破底  = TC     (結構失敗)

        Args:
            ticker:      股票代號 (傳給底層 check_ 函式)
            k5:          當日 5 分 K DataFrame
            prev_close:  前日收盤價
            prev_levels: {'prev_close', 'prev_high', 'prev_low'}
            category:    'HELD' / 'WATCH' / 'PLAN_PRIMARY'
            target_date: 交易日 (YYYY-MM-DD)，不傳則用 date.today()

        Returns:
            dict with keys: triggered, detector, category, action, reason, [price], [market_regime]
            detector 使用新中文名 (首攻/續攻/反彈/破底/首攻_signal/首攻_pullback/續攻_watch/反彈_watch)
        """
        prev_high = prev_levels.get("prev_high")
        prev_low  = prev_levels.get("prev_low")

        _today_str = target_date or date.today().isoformat()

        # 判別大盤環境
        regime = self._detect_market_regime(_today_str)

        # Layer 1: 首攻 (Ch5-3) 當沖 entry
        # 傳 ticker + target_date 讓 check_ch5_3_entry 自動查 MA10
        r = self.check_ch5_3_entry(
            k5, prev_close,
            ticker=ticker,
            target_date=_today_str,
            market_regime=regime,
        )
        def _with_regime(d: dict) -> dict:
            d["market_regime"] = regime
            return d

        if r.get("triggered"):
            return _with_regime(self._format_action(r, "首攻", category))

        # 首攻 signal / pullback 也需要上報（不 triggered 但 level 有意義）
        ch53_level = r.get("level", "watch")
        if ch53_level in ("signal", "pullback"):
            return _with_regime(self._format_action(
                {**r, "triggered": True},
                f"首攻_{ch53_level}",
                category,
            ))

        # Layer 2: 續攻 (T1) 強勢延續
        r = self.check_trigger_1(ticker, k5, prev_high)
        if r.get("triggered"):
            return _with_regime(self._format_action(r, "續攻", category))
        # 續攻_watch (9:15-9:45 或距日高 <1.5%) 也需要上報
        t1_level = r.get("level", "watch")
        if t1_level == "T1_watch":
            return _with_regime(self._format_action(
                {**r, "triggered": True},
                "續攻_watch",
                category,
            ))

        # Layer 3: 反彈 (T2) 跌深反彈 (新版、盤中高)
        # now_time 傳 datetime.min 表示不做時段限制 (新版已移除時段限制)
        r = self.check_trigger_2(ticker, k5, datetime.min)
        if r.get("triggered"):
            return _with_regime(self._format_action(r, "反彈", category))
        # 反彈_watch (9:15-9:45 或距日高 <1.5%) 也需要上報
        t2_level = r.get("level", "watch")
        if t2_level == "T2_watch":
            return _with_regime(self._format_action(
                {**r, "triggered": True},
                "反彈_watch",
                category,
            ))

        # Layer 4: 破底 (TC) 結構失敗
        r = self.check_trigger_c(ticker, k5, prev_low)
        if r.get("triggered"):
            return _with_regime(self._format_action(r, "破底", category))

        base_result = {
            "triggered": False,
            "detector":  "none",
            "category":  category,
            "action":    "—",
            "reason":    r.get("reason", ""),
            "market_regime": regime,
        }

        # Layer 5 (附加、不破壞既有邏輯): 尾盤 check 13:05-13:25 (v6 backtest sweet spot)
        now_str = datetime.now().strftime("%H:%M")
        if "13:05" <= now_str <= "13:25":
            closing_r = self.check_closing_panel(
                ticker=ticker,
                k5=k5,
                target_date=_today_str,
                db_path=_DB,
            )
            cl_level = closing_r.get("level", "not_in_window")
            # v7 backtest 校正命名:
            #   confirmed (3-4/5) → 尾盤_confirmed  Win 82% 最佳進場
            #   overheated (5/5)  → 尾盤_過熱       Win 40% 過熱不追
            #   skip (<3/5)       → 尾盤_skip        不進
            if cl_level == "confirmed":
                closing_detector = "尾盤_confirmed"
            elif cl_level == "overheated":
                closing_detector = "尾盤_過熱"
            else:
                closing_detector = "尾盤_skip"

            closing_triggered = cl_level in ("confirmed",)  # 過熱不算觸發
            cl_action_map = {
                "尾盤_confirmed": "🟢 尾盤可進 (3-4/5 Win 82%)",
                "尾盤_過熱":      "🔴 尾盤過熱 (5/5 Win 40% 別追)",
                "尾盤_skip":      "🔴 尾盤不進 (<3/5)",
            }
            return _with_regime({
                **base_result,
                "triggered":        closing_triggered,
                "detector":         closing_detector,
                "action":           cl_action_map.get(closing_detector, ""),
                "reason":           closing_r.get("reason", ""),
                "closing_scores":   closing_r.get("scores", {}),
                "closing_pass_count": closing_r.get("pass_count", 0),
            })

        return base_result


# ── 主監控邏輯 ────────────────────────────────────────────────────────────────

def _get_prev_levels(ticker: str, db: Path) -> dict:
    """從 DB 取前日收盤、前波高/低."""
    closes = load_daily_closes(ticker, db, n=10)
    if len(closes) < 2:
        return {}
    prev_close = float(closes.iloc[-2]) if len(closes) >= 2 else None
    recent_high = float(closes.tail(5).max())
    recent_low  = float(closes.tail(5).min())
    return {
        "prev_close": prev_close,
        "prev_high":  recent_high,
        "prev_low":   recent_low,
    }


# ── Phase 1 出場 Detector 執行函式 ─────────────────────────────────────────────

# 各 ticker 的分批停利里程碑 (跨循環共用)
_profit_milestones_state: dict[str, set] = {}


def _run_exit_detectors(
    ticker: str,
    name: str,
    k5: pd.DataFrame,
    entry_price: float,
    prev_close: float,
    now: datetime,
    cooldown: dict[str, datetime],
    notify: bool,
    log_fn,
    cooldown_min: int = 30,
) -> None:
    """對 HELD 持倉跑 4 個出場 detector，觸發時通知。

    出場優先級 (高於 TC):
      掀傘 / 高檔長黑 / 隔日急殺 → 立即出場訊號 (MAC 通知 + Sosumi 音效)
      分批停利 → 提示 (MAC 通知、不阻斷)
    """
    global _profit_milestones_state

    if ticker not in _profit_milestones_state:
        _profit_milestones_state[ticker] = set()

    t = now.time()
    t_str = now.strftime("%H:%M")
    current_price = float(k5["close"].iloc[-1])

    # ── Detector 1: 掀傘 ──────────────────────────────────────────────────────
    cd_key_umb = f"{ticker}_掀傘"
    if now > cooldown.get(cd_key_umb, datetime.min):
        r = check_umbrella_exit(k5, entry_price)
        if r.get("triggered"):
            cooldown[cd_key_umb] = now + timedelta(minutes=cooldown_min)
            reason = r.get("reason", "")
            log_fn(f"🌂 掀傘 {ticker} {name}: {reason}")
            if notify:
                notify_mac(
                    f"🌂 {ticker} {name} 掀傘出場",
                    f"現 ${current_price:.2f} | {reason[:60]}",
                    sound="Sosumi",
                )

    # ── Detector 2: 高檔長黑 K ────────────────────────────────────────────────
    # 高檔長黑需要至少 7 根 5K (proxy 版)；
    # 為讓 5K DataFrame 能跑，轉成「日線視角」的近似判斷:
    #   body > 4%、連 2 創新高後大黑 K
    # 注: 完整版在 check_high_long_black (日線)，5K 版用簡化邏輯
    cd_key_hlb = f"{ticker}_高檔長黑"
    if len(k5) >= 7 and now > cooldown.get(cd_key_hlb, datetime.min):
        last = k5.iloc[-1]
        prev_bar = k5.iloc[-2]
        body_pct = (float(last["open"]) - float(last["close"])) / float(last["open"]) if float(last["open"]) > 0 else 0
        is_long_black_5k = float(last["close"]) < float(last["open"]) and body_pct >= 0.03
        # 吃下前 5 根
        prior_5_min_close = float(k5.iloc[-7:-2]["close"].min()) if len(k5) >= 7 else 0
        m3_5k = prior_5_min_close > 0 and float(last["close"]) < prior_5_min_close
        # 前 2 根持續創高後今日長黑包覆
        prev2_high = float(k5.iloc[-3]["high"]) if len(k5) >= 3 else 0
        m2_5k = float(prev_bar["close"]) > float(prev_bar["open"]) and float(last["open"]) >= float(prev_bar["high"]) and float(last["close"]) <= float(prev_bar["low"])

        if is_long_black_5k and (m2_5k or m3_5k):
            cooldown[cd_key_hlb] = now + timedelta(minutes=cooldown_min)
            reason = (
                f"5K 高檔長黑 (實體{body_pct*100:.1f}%)"
                + (" + M2包覆" if m2_5k else "")
                + (" + M3吃前5根" if m3_5k else "")
            )
            log_fn(f"🦘 高檔長黑 {ticker} {name}: {reason}")
            if notify:
                notify_mac(
                    f"🦘 {ticker} {name} 高檔長黑",
                    f"現 ${current_price:.2f} | {reason[:60]}",
                    sound="Sosumi",
                )

    # ── Detector 3: 分批停利里程碑 ────────────────────────────────────────────
    milestones = _profit_milestones_state[ticker]
    r = check_profit_milestone(current_price, entry_price, milestones)
    if r.get("triggered"):
        key = r.get("milestone_key")
        milestones.add(key)
        action = r.get("action", key)
        reason = r.get("reason", "")
        log_fn(f"{action} {ticker} {name}: {reason}")
        if notify:
            notify_mac(
                f"{action} {ticker} {name}",
                f"現 ${current_price:.2f} | {reason[:60]}",
                sound="Glass",
            )

    # ── Detector 4: 隔日急殺 (9:00-9:10 開盤評估) ─────────────────────────────
    if t_str <= "09:10" and prev_close > 0:
        cd_key_gap = f"{ticker}_隔日急殺"
        if now > cooldown.get(cd_key_gap, datetime.min):
            open_price = float(k5["open"].iloc[0])
            r = check_gap_down_emergency(open_price, prev_close)
            if r.get("triggered"):
                cooldown[cd_key_gap] = now + timedelta(minutes=cooldown_min * 24)  # 當日只通知 1 次
                level = r.get("level", "normal")
                gap_pct = r.get("gap_pct", 0) * 100
                reason = r.get("reason", "")
                action = r.get("action", "")
                if level == "emergency":
                    log_fn(f"📉 急殺 {ticker} {name}: {reason}")
                    if notify:
                        notify_mac(
                            f"📉 {ticker} {name} 隔日急殺 {gap_pct:.1f}%",
                            f"開盤 ${open_price:.2f} | {action}",
                            sound="Sosumi",
                        )
                else:  # warning
                    log_fn(f"⚠️ 跳空警示 {ticker} {name}: {reason}")
                    if notify:
                        notify_mac(
                            f"⚠️ {ticker} {name} 跳空 {gap_pct:.1f}%",
                            f"開盤 ${open_price:.2f} | {action}",
                            sound="Basso",
                        )


def run_monitor(
    tickers: list[tuple[str, str, str]],  # (ticker, name, tactic)
    interval: int,
    notify: bool,
    no_discipline: bool,
    start_time: str,
    end_time: str,
    log_path: Optional[Path],
    db: Path,
) -> None:
    trigger_engine = StageTrigger()
    cooldown: dict[str, datetime] = {}
    COOLDOWN_MIN = 30

    fh = None
    if log_path:
        fh = open(log_path, "a", buffering=1)

    def _log(msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        log.info(msg)
        if fh:
            fh.write(line + "\n")

    _log(f"Stage Helper 啟動 — 監控 {[t[0] for t in tickers]}、間隔 {interval}s")

    st_h, st_m = (int(x) for x in start_time.split(":"))
    et_h, et_m = (int(x) for x in end_time.split(":"))

    while True:
        now = datetime.now()
        t = now.time()

        if t.hour < st_h or (t.hour == st_h and t.minute < st_m):
            _log(f"等待開盤 ({start_time})…")
            time.sleep(30)
            continue

        if t.hour > et_h or (t.hour == et_h and t.minute >= et_m):
            _log(f"已過收盤時間 ({end_time})，停止監控。")
            break

        for ticker, name, tactic in tickers:
            try:
                k5 = fetch_5min_kbar(ticker, now.date())
                if k5.empty:
                    _log(f"{ticker} {name}: 無 5K 資料")
                    continue

                prev = _get_prev_levels(ticker, db)
                pass_discipline, disc_reason = trigger_engine.check_discipline_filter(
                    ticker, k5, now, prev.get("prev_close"), disable=no_discipline
                )
                if not pass_discipline:
                    _log(f"  [{ticker}] 紀律過濾: {disc_reason}")
                    continue

                # ── Cascade composite_check (新) ──────────────────────────────
                # category: HELD / WATCH / PLAN_PRIMARY 可由呼叫方傳入；
                # 這裡 run_monitor 走 tactic 判斷 category
                category = "HELD" if tactic in ("核心",) else "WATCH"
                prev_close = prev.get("prev_close") or 0.0
                result = trigger_engine.composite_check(
                    ticker=ticker,
                    k5=k5,
                    prev_close=prev_close,
                    prev_levels=prev,
                    category=category,
                )

                detector   = result.get("detector", "none")
                action     = result.get("action", "")
                reason     = result.get("reason", "")
                price      = result.get("price", 0.0)
                cd_key     = f"{ticker}_{detector}"

                if result.get("triggered") and now > cooldown.get(cd_key, datetime.min):
                    cooldown[cd_key] = now + timedelta(minutes=COOLDOWN_MIN)
                    msg = f"現 ${price:.2f}、{action} | {reason[:60]}"

                    if detector in ("首攻", "Ch5-3"):
                        _log(f"🟡 首攻 {ticker} {name}: {reason}")
                        if notify:
                            notify_mac(f"🟡 {ticker} {name} 首攻 SOP", msg)
                    elif detector in ("續攻", "T1"):
                        _log(f"🟢 續攻 {ticker} {name}: {reason}")
                        if notify:
                            notify_mac(f"🟢 {ticker} {name} 續攻 強勢延續", msg)
                    elif detector in ("反彈", "T2"):
                        _log(f"🎯 反彈 {ticker} {name}: {reason}")
                        if notify:
                            notify_mac(f"🎯 {ticker} {name} 反彈 訊號", msg)
                    elif detector in ("破底", "TC"):
                        _log(f"🚨 破底 {ticker} {name}: {reason}")
                        if notify:
                            notify_mac(f"🚨 {ticker} {name} 破底 結構失敗", msg, sound="Sosumi")
                elif not result.get("triggered"):
                    _log(f"  [{ticker}] cascade: {detector} — {reason[:60]}")

                # ── Phase 1 出場 Detector (HELD 持倉額外評估) ─────────────────
                # 掀傘 / 高檔長黑 / 分批停利 / 急殺 — 只對 HELD 持倉跑
                if category == "HELD" and _EXIT_DETECTORS_AVAILABLE:
                    # 找對應的 HELD 進場價
                    entry_price_map = {h[0]: h[2] for h in HELD}
                    entry_price = entry_price_map.get(ticker, 0.0)
                    if entry_price > 0:
                        _run_exit_detectors(
                            ticker=ticker, name=name, k5=k5,
                            entry_price=entry_price,
                            prev_close=prev_close,
                            now=now, cooldown=cooldown,
                            notify=notify, log_fn=_log,
                        )

            except Exception as e:
                _log(f"[ERROR] {ticker}: {e}")

        time.sleep(interval)

    if fh:
        fh.close()


# ── FinMind 真實資料抓取 ──────────────────────────────────────────────────────

def _fetch_finmind_1m(ticker: str, target_date: str) -> pd.DataFrame:
    """用 FinMind TaiwanStockKBar 拉 1 分 K，聚合成 5 分 K。"""
    import os
    import requests

    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        print("[WARN] FINMIND_TOKEN 未設定，無法抓取真實資料")
        return pd.DataFrame()

    try:
        r = requests.get(
            "https://api.finmindtrade.com/api/v4/data",
            params={
                "dataset": "TaiwanStockKBar",
                "data_id": ticker,
                "start_date": target_date,
                "end_date": target_date,
                "token": token,
            },
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("status") != 200 or not data.get("data"):
            print(f"[WARN] FinMind 回傳無資料: {data.get('msg', '')}")
            return pd.DataFrame()
        df = pd.DataFrame(data["data"])
        if df.empty:
            return pd.DataFrame()
        # FinMind KBar 欄位: date (YYYY-MM-DD), minute (HH:MM:SS), stock_id, open, high, low, close, volume
        if "minute" in df.columns:
            df["datetime"] = pd.to_datetime(df["date"].astype(str) + " " + df["minute"].astype(str))
        else:
            df["datetime"] = pd.to_datetime(df["date"])
        df = df.sort_values("datetime").set_index("datetime")
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        # 先過濾目標日期
        td = date.fromisoformat(target_date)
        df = df[df.index.date == td]
        if df.empty:
            return pd.DataFrame()
        # 聚合成 5 分 K
        df5 = df.resample("5min", label="left", closed="left").agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        ).dropna(subset=["open", "close"])
        return df5
    except Exception as e:
        print(f"[ERROR] FinMind 抓取失敗: {e}")
        return pd.DataFrame()


# ── 模擬模式 ──────────────────────────────────────────────────────────────────

# 驗證情境設定
_SIM_CASES: dict[str, dict] = {
    # Case 1: 1605 5/29 → 預期走 Ch5-3 路徑
    # 5/28 收 36.0、5/29 第一根 5K 開 36.65 高 37.70 收 37.55
    "1605_2026-05-29": {
        "ticker": "1605",
        "date": "2026-05-29",
        "prev_close": 36.0,
        "prev_high": 36.5,
        "prev_low": 34.8,
        "expected_detector": "Ch5-3",
        "note": "5/28 收 36.0、5/29 第一根 5K 紅K、全 pass、預期 Ch5-3",
    },
    # Case 2: 1605 6/1 → 預期走 T2 路徑
    # 5/29 收 38.80、6/1 第一根 5K 開 39.30 收 39.15 (黑K、雙錨失守)
    "1605_2026-06-01": {
        "ticker": "1605",
        "date": "2026-06-01",
        "prev_close": 38.80,
        "prev_high": 39.5,
        "prev_low": 37.5,
        "expected_detector": "T2",
        "note": "5/29 收 38.80、6/1 第一根 5K 黑K、Ch5-3 失敗、預期 T2",
    },
}


def run_simulation(sim_date_str: str, sim_ticker: str, notify: bool, no_discipline: bool) -> None:
    """模擬模式: 用 FinMind 真實 5K 跑 composite_check cascade 驗證。"""
    engine = StageTrigger()
    case_key = f"{sim_ticker}_{sim_date_str}"

    # 取 case 設定 (若無則用預設)
    case = _SIM_CASES.get(case_key, {})
    prev_close = case.get("prev_close", 0.0)
    prev_high  = case.get("prev_high", prev_close * 1.02)
    prev_low   = case.get("prev_low",  prev_close * 0.97)
    expected_detector = case.get("expected_detector", "?")
    note = case.get("note", "")

    print(f"\n{'='*60}")
    print(f"  模擬: {sim_ticker} {sim_date_str}")
    if note:
        print(f"  {note}")
    print(f"  前收: {prev_close:.2f}  期望 detector: {expected_detector}")
    print(f"{'='*60}")

    # 嘗試從 FinMind 取真實資料
    k5_full = _fetch_finmind_1m(sim_ticker, sim_date_str)
    if k5_full.empty:
        # fallback: 若是原有模擬資料日期則用 _build_simulated_5k_1605
        if sim_ticker == "1605" and sim_date_str == "2026-06-02":
            print("[INFO] 使用內建 1605 2026-06-02 模擬資料 (FinMind 無資料)")
            k5_full = _build_simulated_5k_1605()
        else:
            print(f"[WARN] FinMind 無 {sim_ticker} {sim_date_str} 資料，無法執行驗證")
            return

    print(f"  5K 資料共 {len(k5_full)} 根  ({k5_full.index[0].strftime('%H:%M')} ~ {k5_full.index[-1].strftime('%H:%M')})")
    print()

    prev_levels = {"prev_close": prev_close, "prev_high": prev_high, "prev_low": prev_low}

    first_triggered: Optional[dict] = None
    print(f"  {'時間':6}  {'紀律':8}  {'detector':10}  action / reason")
    print(f"  {'─'*80}")

    for i in range(1, len(k5_full) + 1):
        k5 = k5_full.iloc[:i]
        ts  = k5_full.index[i - 1]
        ts_str = ts.strftime("%H:%M")
        sim_now = ts.to_pydatetime()

        pass_disc, disc_reason = engine.check_discipline_filter(
            sim_ticker, k5, sim_now, prev_close, disable=no_discipline
        )

        result = engine.composite_check(
            ticker=sim_ticker,
            k5=k5,
            prev_close=prev_close,
            prev_levels=prev_levels,
            category="PLAN_PRIMARY",
        )

        det = result.get("detector", "none")
        act = result.get("action", "")
        rsn = result.get("reason", "")
        triggered = result.get("triggered", False)

        disc_tag = "✅" if pass_disc else "❌"
        if triggered:
            price = result.get("price", 0.0)
            print(f"  {ts_str}  {disc_tag}  {det:10}  {act} | {rsn[:50]}  @ ${price:.2f}")
            if first_triggered is None:
                first_triggered = {**result, "ts": ts_str}
        # 只列有變化的節點，避免輸出過多
        # (非 triggered 只在每 5 根或重要時間列印)
        elif i <= 3 or ts_str in ("09:10", "09:15", "09:30", "10:00", "11:00", "12:00", "13:00"):
            print(f"  {ts_str}  {disc_tag}  {det:10}  {rsn[:55]}")

    print(f"\n  {'─'*80}")
    if first_triggered:
        det = first_triggered.get("detector", "none")
        price = first_triggered.get("price", 0.0)
        ts_str = first_triggered.get("ts", "?")
        action = first_triggered.get("action", "")
        ok = (det == expected_detector) or expected_detector == "?"
        result_tag = "✅ PASS" if ok else f"❌ FAIL (期望 {expected_detector})"
        print(f"  首次觸發: {det} @ {ts_str}  ${price:.2f}  {action}")
        print(f"  驗證: {result_tag}")
    else:
        ok = expected_detector in ("none", "?")
        print(f"  驗證: {'✅ PASS (無訊號如預期)' if ok else f'❌ FAIL (期望 {expected_detector} 但無觸發)'}")

    print(f"{'='*60}\n")

    if notify and first_triggered:
        price = first_triggered.get("price", 0.0)
        det   = first_triggered.get("detector", "")
        notify_mac(
            f"模擬 {sim_ticker} {sim_date_str} {det}",
            f"首次觸發 @ {first_triggered.get('ts', '?')} ${price:.2f}"
        )


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args():
    p = argparse.ArgumentParser(description="盤中 Stage Trigger 偵測器")
    p.add_argument("--tickers", default="", help="逗號分隔 ticker (預設讀 HELD + WATCH)")
    p.add_argument("--interval", type=int, default=60, help="檢查間隔秒數 (預設 60)")
    p.add_argument("--notify", action="store_true", default=True, help="推 macOS 通知 (預設 ON)")
    p.add_argument("--no-notify", dest="notify", action="store_false")
    p.add_argument("--no-discipline", action="store_true", default=False,
                   help="略過紀律過濾 (debug 用)")
    p.add_argument("--start-time", default="09:10", help="開始監控時間 (預設 09:10)")
    p.add_argument("--end-time",   default="13:25", help="停止監控時間 (預設 13:25)")
    p.add_argument("--log", default=None, help="log 寫入路徑 (預設 /tmp/intraday_stage.log)")
    p.add_argument("--db", default=str(_DB), help="DB 路徑")
    p.add_argument("--simulate-date", default=None,
                   help="模擬模式: YYYY-MM-DD (不連線 API、用內建測資)")
    p.add_argument("--simulate-ticker", default="1605",
                   help="模擬 ticker (目前僅支援 1605, 預設 1605)")
    return p.parse_args()


def _build_ticker_list(raw_tickers: str) -> list[tuple[str, str, str]]:
    """回傳 [(ticker, name, tactic)]."""
    name_map: dict[str, str] = {}
    try:
        db = Path(_DB)
        if db.exists():
            name_map = load_stock_names(db)
    except Exception:
        pass

    result: list[tuple[str, str, str]] = []

    if raw_tickers:
        for t in raw_tickers.split(","):
            t = t.strip()
            if t:
                result.append((t, name_map.get(t, t), "核心"))
        return result

    # 預設從 HELD + WATCH 讀
    for ticker, name, *_ in HELD:
        tactic = _[-1] if _ else "核心"
        result.append((ticker, name_map.get(ticker, name), tactic))
    for ticker, name, *_ in WATCH:
        tactic = _[-1] if _ else "短打"
        result.append((ticker, name_map.get(ticker, name), tactic))

    return result


def main():
    args = _parse_args()
    db = Path(args.db)

    if args.simulate_date:
        run_simulation(
            sim_date_str=args.simulate_date,
            sim_ticker=args.simulate_ticker,
            notify=args.notify,
            no_discipline=args.no_discipline,
        )
        return

    tickers = _build_ticker_list(args.tickers)
    log_path = Path(args.log) if args.log else Path("/tmp/intraday_stage.log")

    run_monitor(
        tickers=tickers,
        interval=args.interval,
        notify=args.notify,
        no_discipline=args.no_discipline,
        start_time=args.start_time,
        end_time=args.end_time,
        log_path=log_path,
        db=db,
    )


if __name__ == "__main__":
    main()
