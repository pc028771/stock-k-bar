"""Phase 3 v5 — 當沖優化 A/B/C/D 對比 Backtest

4 種改良策略 vs baseline (v4):

  A. 只做 Ch5-3 confirmed (排除 T1 / T2)
     - Entry filter: layer == 'Ch5-3'
     - Exit: 13:30 (baseline對齊) + 掀傘 (最佳版)

  B. 動 Score 公式 (Ch5-3 加重 / T2 降權)
     - Ch5-3: 50 pts (原 30) / T2: -10 pts (原 25) / T1: 10 pts (原 20)
     - 預期: T2 從 top-2 中被擠出、強制 top-2 都來自 Ch5-3/T1

  C. 加 Stop Loss -1.5%
     - Entry: 同 baseline (Ch5-3 + T1 + T2)
     - 進場後跌 -1.5% 立即出
     - Exit 優先: stop loss > 掀傘 > 13:30

  D. 隔日 9:00 開盤出 (1 day swing)
     - Entry: 同 baseline
     - Exit: 隔日 9:00 開盤價 (用日 K open)
     - 避免 13:30 殺尾 + 享受隔日跳空

Usage:
    python scripts/zhuli/phase3_v5_intraday_ABCD_backtest.py
    python scripts/zhuli/phase3_v5_intraday_ABCD_backtest.py --no-report
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

_REPO = Path(__file__).parent.parent.parent
_SYS = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_REPO), str(_REPO / "scripts"), str(_SYS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.db import get_conn, MAIN_DB
from zhuli.intraday_stage_helper import StageTrigger, _get_ma10, _DB as _HELPER_DB  # noqa

_DB = MAIN_DB
_TMP = Path("/tmp")
_CACHE_DIR = _TMP / "finmind_kbar_cache"
_CACHE_DIR.mkdir(exist_ok=True)
_MINKBAR_CACHE_DIR = _TMP / "finmind_1m_cache"
_MINKBAR_CACHE_DIR.mkdir(exist_ok=True)

# 含手續費 (買 + 賣 + 證交稅) 約 0.6%
FEE_PCT = 0.6

# ── 交易日清單 ─────────────────────────────────────────────────────────────────
TRADING_DATES_FULL = [
    "2026-05-19", "2026-05-20", "2026-05-21", "2026-05-22",
    "2026-05-25", "2026-05-26", "2026-05-27", "2026-05-28", "2026-05-29",
    "2026-06-01", "2026-06-02", "2026-06-03",
]

_REGIME_EMOJI = {"strong": "🟢強", "weak": "🔴弱", "normal": "⚪平"}


def next_trading_day(d: str, dates: list[str]) -> Optional[str]:
    idx = dates.index(d) if d in dates else -1
    if idx < 0 or idx + 1 >= len(dates):
        return None
    return dates[idx + 1]


# ── Scanner 解析 ──────────────────────────────────────────────────────────────

def parse_scanner_candidates(md_path: Path) -> list[str]:
    text = md_path.read_text()
    tickers: list[str] = []
    seen: set[str] = set()
    in_entry = False
    in_teacher = False
    in_observation = False

    for line in text.splitlines():
        if line.startswith("## 🎯 可進場"):
            in_entry = True; in_teacher = False; in_observation = False; continue
        elif line.startswith("## ⚠️ 後續觀察"):
            in_entry = False; in_teacher = False; in_observation = True; continue
        elif line.startswith("## 📋 老師 core 級指名"):
            in_entry = False; in_teacher = True; in_observation = False; continue
        elif line.startswith("## "):
            in_entry = False; in_teacher = False; in_observation = False; continue
        if in_observation:
            continue
        if in_entry or in_teacher:
            m = re.match(r'\|\s*\*?\*?(\d{4})\*?\*?\s*', line)
            if m:
                t = m.group(1)
                if t not in seen:
                    seen.add(t)
                    tickers.append(t)

    return tickers


# ── FinMind 抓取 (5K) ─────────────────────────────────────────────────────────

_finmind_calls = 0
_finmind_call_ts = time.time()


def _rate_limit():
    global _finmind_calls, _finmind_call_ts
    _finmind_calls += 1
    if _finmind_calls % 100 == 0:
        time.sleep(1.0)
        _finmind_call_ts = time.time()
    else:
        time.sleep(0.12)


def fetch_finmind_kbar_5m(ticker: str, target_date: str) -> pd.DataFrame:
    cache_file = _CACHE_DIR / f"{ticker}_{target_date}.json"
    if cache_file.exists():
        try:
            raw = json.loads(cache_file.read_text())
            if not raw:
                return pd.DataFrame()
            df = pd.DataFrame(raw)
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.set_index("datetime")
            for col in ("open", "high", "low", "close", "volume"):
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            return df
        except Exception:
            pass

    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        return pd.DataFrame()

    _rate_limit()
    for attempt in range(3):
        try:
            import requests
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
                cache_file.write_text("[]")
                return pd.DataFrame()
            break
        except Exception as e:
            if attempt == 2:
                print(f"  [ERR] FinMind {ticker} {target_date}: {e}")
                return pd.DataFrame()
            time.sleep(2 ** attempt)
    else:
        return pd.DataFrame()

    df = pd.DataFrame(data["data"])
    if df.empty:
        cache_file.write_text("[]")
        return pd.DataFrame()

    if "minute" in df.columns:
        df["datetime"] = pd.to_datetime(df["date"].astype(str) + " " + df["minute"].astype(str))
    else:
        df["datetime"] = pd.to_datetime(df["date"])

    df = df.sort_values("datetime").set_index("datetime")
    td = date.fromisoformat(target_date)
    df = df[df.index.date == td]
    if df.empty:
        cache_file.write_text("[]")
        return pd.DataFrame()

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

    df5_save = df5.reset_index()
    df5_save["datetime"] = df5_save["datetime"].astype(str)
    cache_file.write_text(json.dumps(df5_save.to_dict("records"), ensure_ascii=False))
    return df5


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_prev_levels(ticker: str, d: str) -> dict:
    for attempt in range(3):
        try:
            con = get_conn(_DB, timeout=10)
            rows = con.execute(
                "SELECT trade_date, close, high, low FROM standard_daily_bar "
                "WHERE ticker=? AND trade_date<? ORDER BY trade_date DESC LIMIT 10",
                (ticker, d),
            ).fetchall()
            con.close()
            if not rows:
                return {}
            prev_close = float(rows[0][1])
            highs = [float(r[2]) for r in rows[:5] if r[2] is not None]
            lows  = [float(r[3]) for r in rows[:5] if r[3] is not None]
            recent_high = max(highs) if highs else prev_close * 1.02
            recent_low  = min(lows)  if lows  else prev_close * 0.98
            return {"prev_close": prev_close, "prev_high": recent_high, "prev_low": recent_low}
        except sqlite3.OperationalError:
            if attempt == 2:
                return {}
            time.sleep(1)
    return {}


def get_open_price_next_day(ticker: str, d: str) -> Optional[float]:
    """取隔日開盤價 (用 standard_daily_bar.open)。"""
    for attempt in range(3):
        try:
            con = get_conn(_DB, timeout=10)
            row = con.execute(
                "SELECT open FROM standard_daily_bar "
                "WHERE ticker=? AND trade_date=?",
                (ticker, d),
            ).fetchone()
            con.close()
            if row and row[0] is not None:
                return float(row[0])
            return None
        except sqlite3.OperationalError:
            if attempt == 2:
                return None
            time.sleep(1)
    return None


# ── Score 函式 ────────────────────────────────────────────────────────────────

_TEACHER_TIER_CACHE: dict[str, str] = {}


def _load_teacher_tier() -> dict[str, str]:
    global _TEACHER_TIER_CACHE
    if _TEACHER_TIER_CACHE:
        return _TEACHER_TIER_CACHE
    tier: dict[str, str] = {}
    try:
        picks_path = _REPO / "docs" / "主力大課程" / "data" / "teacher_picks_2026.json"
        if picks_path.exists():
            data = json.loads(picks_path.read_text())
            for item in data if isinstance(data, list) else data.get("picks", []):
                tk = str(item.get("ticker", ""))
                lvl = item.get("tier", "mentioned")
                if tk:
                    tier[tk] = lvl
    except Exception:
        pass
    _TEACHER_TIER_CACHE = tier
    return tier


def _score_trigger_baseline(hit: dict) -> float:
    """v4 原始分數公式。支援新中文名及舊英文名 alias。"""
    score = 0.0
    trigger_base = {
        "首攻": 30, "續攻": 20, "反彈": 25, "破底": -100,  # 新中文名
        "Ch5-3": 30, "T1": 20, "T2": 25, "TC": -100,       # 舊英文名 alias
    }
    score += trigger_base.get(hit.get("layer", ""), 0)

    fire_time = hit.get("entry_time") or "09:30"
    try:
        h, m = int(fire_time[:2]), int(fire_time[3:5])
        minutes_after_910 = (h - 9) * 60 + (m - 10)
        score -= minutes_after_910 * 0.5
    except Exception:
        pass

    tier_map = _load_teacher_tier()
    tier = tier_map.get(hit.get("ticker", ""), "")
    if tier == "core":
        score += 25
    elif tier == "frequent":
        score += 15
    elif tier == "mentioned":
        score += 8

    if hit.get("market_regime") == "strong":
        score += 5

    return score


def _score_trigger_v5b(hit: dict) -> float:
    """策略 B: 首攻+50 / 反彈-10 / 續攻+10 (其餘不變)。支援新中文名及舊英文名 alias。"""
    score = 0.0
    trigger_base = {
        "首攻": 50, "續攻": 10, "反彈": -10, "破底": -100,  # 新中文名
        "Ch5-3": 50, "T1": 10, "T2": -10, "TC": -100,        # 舊英文名 alias
    }
    score += trigger_base.get(hit.get("layer", ""), 0)

    fire_time = hit.get("entry_time") or "09:30"
    try:
        h, m = int(fire_time[:2]), int(fire_time[3:5])
        minutes_after_910 = (h - 9) * 60 + (m - 10)
        score -= minutes_after_910 * 0.5
    except Exception:
        pass

    tier_map = _load_teacher_tier()
    tier = tier_map.get(hit.get("ticker", ""), "")
    if tier == "core":
        score += 25
    elif tier == "frequent":
        score += 15
    elif tier == "mentioned":
        score += 8

    if hit.get("market_regime") == "strong":
        score += 5

    return score


# ── Exit 策略 ─────────────────────────────────────────────────────────────────

def get_close_at_time(k5: pd.DataFrame, target_time: str) -> Optional[float]:
    if k5.empty:
        return None
    filtered = k5[k5.index.strftime("%H:%M") <= target_time]
    if filtered.empty:
        return None
    return float(filtered.iloc[-1]["close"])


def compute_exit_1330(k5: pd.DataFrame, entry_time: str) -> tuple[Optional[float], str]:
    return get_close_at_time(k5, "13:30"), "13:30"


def compute_exit_stop_loss(
    k5: pd.DataFrame,
    entry_time: str,
    entry_price: float,
    stop_pct: float = -1.5,
) -> tuple[Optional[float], str]:
    """策略 C: 跌 stop_pct% 立即出，否則 13:30 出。"""
    if k5.empty:
        return None, "no_data"

    stop_price = entry_price * (1 + stop_pct / 100)
    after_entry = k5[k5.index.strftime("%H:%M") >= entry_time].copy()
    if after_entry.empty:
        return get_close_at_time(k5, "13:30"), "13:30"

    for ts, row in after_entry.iterrows():
        ts_str = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)[11:16]
        if ts_str > "13:30":
            break
        bar_low = float(row["low"])
        if bar_low <= stop_price:
            # 以 stop_price 出 (假設 intrabar 觸及)
            exit_p = min(float(row["close"]), stop_price)  # 取較保守值
            return exit_p, f"{ts_str}(SL{stop_pct}%)"

    # 沒觸發 stop → 13:30 出
    exit_p = get_close_at_time(k5, "13:30")
    return exit_p, "13:30"


def compute_exit_umbrella(
    k5: pd.DataFrame, entry_time: str, entry_price: float
) -> tuple[Optional[float], str]:
    """掀傘訊號出場。"""
    if k5.empty:
        return None, "no_data"

    after_entry = k5[k5.index.strftime("%H:%M") >= entry_time].copy()
    if after_entry.empty:
        return get_close_at_time(k5, "13:30"), "13:30"

    exit_price = None
    exit_time_str = "13:30"

    bars = list(after_entry.iterrows())
    n = len(bars)
    for i in range(1, n - 1):
        ts_i, row_i = bars[i]
        ts_str = ts_i.strftime("%H:%M") if hasattr(ts_i, "strftime") else str(ts_i)[11:16]
        if ts_str > "13:25":
            break

        rolling_high = float(after_entry.iloc[:i + 1]["high"].max())

        next_bar_ts, next_bar = bars[i]
        if i + 1 < n:
            next2_ts, next2_bar = bars[i + 1]
        else:
            continue

        bar_high_1 = float(next_bar["high"])
        bar_high_2 = float(next2_bar["high"])

        no_new_high = (bar_high_1 <= rolling_high * 1.001 and
                       bar_high_2 <= rolling_high * 1.001)

        prev_vol = float(after_entry.iloc[max(0, i - 3):i]["volume"].mean()) if i >= 1 else 0
        curr_vol = float(after_entry.iloc[i:i + 2]["volume"].mean())
        vol_shrink = (prev_vol > 0 and curr_vol < prev_vol * 0.8)

        if no_new_high and vol_shrink:
            exit_price = float(next2_bar["close"])
            next2_ts_str = next2_ts.strftime("%H:%M") if hasattr(next2_ts, "strftime") else str(next2_ts)[11:16]
            exit_time_str = f"{next2_ts_str}(掀傘)"
            break

    if exit_price is None:
        exit_price = get_close_at_time(k5, "13:30")
        exit_time_str = "13:30"

    return exit_price, exit_time_str


def compute_exit_c_with_umbrella(
    k5: pd.DataFrame,
    entry_time: str,
    entry_price: float,
    stop_pct: float = -1.5,
) -> tuple[Optional[float], str]:
    """策略 C + 掀傘: stop loss > 掀傘 > 13:30。"""
    if k5.empty:
        return None, "no_data"

    stop_price = entry_price * (1 + stop_pct / 100)
    after_entry = k5[k5.index.strftime("%H:%M") >= entry_time].copy()
    if after_entry.empty:
        return get_close_at_time(k5, "13:30"), "13:30"

    # 先找掀傘時點
    umbrella_time: Optional[str] = None
    bars = list(after_entry.iterrows())
    n = len(bars)
    for i in range(1, n - 1):
        ts_i, row_i = bars[i]
        ts_str = ts_i.strftime("%H:%M") if hasattr(ts_i, "strftime") else str(ts_i)[11:16]
        if ts_str > "13:25":
            break

        rolling_high = float(after_entry.iloc[:i + 1]["high"].max())
        next_bar_ts, next_bar = bars[i]
        if i + 1 < n:
            next2_ts, next2_bar = bars[i + 1]
        else:
            continue

        no_new_high = (float(next_bar["high"]) <= rolling_high * 1.001 and
                       float(next2_bar["high"]) <= rolling_high * 1.001)
        prev_vol = float(after_entry.iloc[max(0, i - 3):i]["volume"].mean()) if i >= 1 else 0
        curr_vol = float(after_entry.iloc[i:i + 2]["volume"].mean())
        vol_shrink = (prev_vol > 0 and curr_vol < prev_vol * 0.8)

        if no_new_high and vol_shrink:
            umbrella_time = next2_ts.strftime("%H:%M") if hasattr(next2_ts, "strftime") else str(next2_ts)[11:16]
            break

    # 掃描所有 bar，stop loss 優先
    for ts, row in after_entry.iterrows():
        ts_str = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)[11:16]
        if ts_str > "13:30":
            break

        # Stop loss 先判
        if float(row["low"]) <= stop_price:
            exit_p = min(float(row["close"]), stop_price)
            return exit_p, f"{ts_str}(SL{stop_pct}%)"

        # 掀傘時點
        if umbrella_time is not None and ts_str >= umbrella_time:
            return float(row["close"]), f"{ts_str}(掀傘)"

    # 沒觸發
    exit_p = get_close_at_time(k5, "13:30")
    return exit_p, "13:30"


# ── 核心觸發偵測 ──────────────────────────────────────────────────────────────

def detect_triggers_for_day(
    engine: StageTrigger,
    scan_date: str,
    next_date: str,
    watchlist: list[str],
    regime: str,
) -> list[dict]:
    """對單日 watchlist 跑 composite_check，回傳所有觸發 (含 baseline score)。"""
    day_triggers: list[dict] = []

    for ticker in watchlist:
        k5_full = fetch_finmind_kbar_5m(ticker, next_date)
        if k5_full.empty:
            continue

        prev_levels = get_prev_levels(ticker, next_date)
        prev_close = prev_levels.get("prev_close", 0.0)
        if not prev_close:
            continue

        ma10 = _get_ma10(ticker, next_date)
        trigger_rec: Optional[dict] = None

        for i in range(1, len(k5_full) + 1):
            k5 = k5_full.iloc[:i]
            ts = k5_full.index[i - 1]
            ts_str = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)[11:16]
            if ts_str < "09:10":
                continue
            if ts_str > "13:00":
                break

            # Ch5-3
            r_ch53 = engine.check_ch5_3_entry(
                k5, prev_close, ma10=ma10, market_regime=regime
            )
            if r_ch53.get("triggered"):
                ep = r_ch53.get("entry_price", r_ch53.get("price", 0.0))
                et = r_ch53.get("entry_time", ts_str)
                trigger_rec = {
                    "scan_date": scan_date, "entry_date": next_date,
                    "ticker": ticker, "layer": "Ch5-3",
                    "entry_price": ep, "entry_time": et,
                    "market_regime": regime,
                    "trigger_reason": r_ch53.get("reason", "")[:60],
                }
                break

            ch53_level = r_ch53.get("level", "watch")
            if ch53_level in ("signal", "pullback"):
                continue

            # T1
            r = engine.check_trigger_1(ticker, k5, prev_levels.get("prev_high"))
            if r.get("triggered"):
                trigger_rec = {
                    "scan_date": scan_date, "entry_date": next_date,
                    "ticker": ticker, "layer": "T1",
                    "entry_price": r.get("price", 0.0), "entry_time": ts_str,
                    "market_regime": regime,
                    "trigger_reason": r.get("reason", "")[:60],
                }
                break

            # T2
            r = engine.check_trigger_2(ticker, k5, datetime.min)
            if r.get("triggered"):
                trigger_rec = {
                    "scan_date": scan_date, "entry_date": next_date,
                    "ticker": ticker, "layer": "T2",
                    "entry_price": r.get("price", 0.0), "entry_time": ts_str,
                    "market_regime": regime,
                    "trigger_reason": r.get("reason", "")[:60],
                }
                break

        if trigger_rec is not None and trigger_rec["entry_price"]:
            trigger_rec["score_baseline"] = _score_trigger_baseline(trigger_rec)
            trigger_rec["score_v5b"] = _score_trigger_v5b(trigger_rec)
            day_triggers.append(trigger_rec)

    return day_triggers


# ── 主 Backtest (ABCD) ────────────────────────────────────────────────────────

def run_v5_backtest() -> dict[str, list[dict]]:
    """
    回傳 {策略名: [records]}
    策略: baseline / A / B / C / D
    (baseline 用來對齊、A/B/C/D 是改良版)
    """
    engine = StageTrigger()
    dates = TRADING_DATES_FULL

    # 收集所有 triggers (全部日期)
    all_day_triggers: dict[str, list[dict]] = {}  # key=entry_date

    for scan_date in dates:
        md_path = _TMP / f"scanner_candidates_{scan_date}.md"
        if not md_path.exists():
            print(f"[SKIP] 無 scanner file: {scan_date}")
            continue

        watchlist = parse_scanner_candidates(md_path)
        next_date = next_trading_day(scan_date, dates)
        if not next_date:
            print(f"[SKIP] {scan_date} 沒有下一交易日")
            continue

        regime = engine._detect_market_regime(next_date, db_path=_DB)
        print(f"[{scan_date} → {next_date}] watchlist={len(watchlist)} "
              f"regime={_REGIME_EMOJI.get(regime, regime)}")

        day_triggers = detect_triggers_for_day(
            engine, scan_date, next_date, watchlist, regime
        )
        if day_triggers:
            all_day_triggers[next_date] = day_triggers

    # ── 對每個策略選 top-2 並計算報酬 ────────────────────────────────────────
    strategy_records: dict[str, list[dict]] = {
        "baseline": [],
        "A": [],
        "B": [],
        "C": [],
        "D": [],
    }

    for entry_date, day_triggers in all_day_triggers.items():
        # 策略 baseline: 同 v4 (score_baseline 排序, top-2, 全 layer)
        base_sorted = sorted(day_triggers, key=lambda x: x["score_baseline"], reverse=True)
        baseline_top2 = base_sorted[:2]

        # 策略 A: 只取 Ch5-3, score_baseline 排序
        a_filtered = [t for t in day_triggers if t["layer"] == "Ch5-3"]
        a_sorted = sorted(a_filtered, key=lambda x: x["score_baseline"], reverse=True)
        a_top2 = a_sorted[:2]

        # 策略 B: score_v5b 排序, top-2 (全 layer)
        b_sorted = sorted(day_triggers, key=lambda x: x["score_v5b"], reverse=True)
        b_top2 = b_sorted[:2]

        # 策略 C: 同 baseline top-2 (但出場邏輯不同)
        c_top2 = baseline_top2

        # 策略 D: 同 baseline top-2 (但出場邏輯不同)
        d_top2 = baseline_top2

        # ── 計算各策略報酬 ───────────────────────────────────────────────────
        for strat, selected in [("baseline", baseline_top2), ("A", a_top2),
                                 ("B", b_top2), ("C", c_top2), ("D", d_top2)]:
            for trec in selected:
                ticker = trec["ticker"]
                entry_price = trec["entry_price"]
                entry_time = trec["entry_time"]
                k5_full = fetch_finmind_kbar_5m(ticker, entry_date)
                rec = dict(trec)  # copy

                if strat in ("baseline", "A", "B"):
                    # Exit: 13:30 (baseline) + 掀傘 (best version)
                    ex_1330, et_1330 = compute_exit_1330(k5_full, entry_time)
                    ex_umb, et_umb = compute_exit_umbrella(k5_full, entry_time, entry_price)

                    def _ret(ep): return round((ep / entry_price - 1) * 100, 3) if ep and entry_price else None
                    def _net(r): return round(r - FEE_PCT, 3) if r is not None else None

                    rec["exit_1330"] = ex_1330
                    rec["exit_1330_time"] = et_1330
                    rec["net_1330"] = _net(_ret(ex_1330))
                    rec["exit_umb"] = ex_umb
                    rec["exit_umb_time"] = et_umb
                    rec["net_umb"] = _net(_ret(ex_umb))

                elif strat == "C":
                    # Exit: stop loss -1.5% > 掀傘 > 13:30
                    ex_c, et_c = compute_exit_c_with_umbrella(
                        k5_full, entry_time, entry_price, stop_pct=-1.5
                    )
                    def _ret(ep): return round((ep / entry_price - 1) * 100, 3) if ep and entry_price else None
                    def _net(r): return round(r - FEE_PCT, 3) if r is not None else None

                    rec["exit_c"] = ex_c
                    rec["exit_c_time"] = et_c
                    rec["net_c"] = _net(_ret(ex_c))
                    # 也算一個純 stop loss 版 (不含掀傘)
                    ex_sl, et_sl = compute_exit_stop_loss(k5_full, entry_time, entry_price, -1.5)
                    rec["exit_sl"] = ex_sl
                    rec["exit_sl_time"] = et_sl
                    rec["net_sl"] = _net(_ret(ex_sl))

                elif strat == "D":
                    # Exit: 隔日 open (在 TRADING_DATES_FULL 找下一日)
                    exit_dates = TRADING_DATES_FULL
                    next_d = next_trading_day(entry_date, exit_dates)
                    open_price = None
                    if next_d:
                        open_price = get_open_price_next_day(ticker, next_d)
                    rec["exit_d_date"] = next_d or "N/A"
                    rec["exit_d_price"] = open_price

                    def _ret(ep): return round((ep / entry_price - 1) * 100, 3) if ep and entry_price else None
                    def _net(r): return round(r - FEE_PCT, 3) if r is not None else None
                    rec["net_d"] = _net(_ret(open_price))

                strategy_records[strat].append(rec)

    return strategy_records


# ── 統計分析 ──────────────────────────────────────────────────────────────────

def _stats(records: list[dict], net_col: str) -> dict:
    vals = [r[net_col] for r in records if r.get(net_col) is not None]
    if not vals:
        return {"n": 0, "win_rate": None, "avg_ret": None, "total_ret": None}
    n = len(vals)
    return {
        "n": n,
        "win_rate": round(sum(1 for v in vals if v > 0) / n * 100, 1),
        "avg_ret": round(sum(vals) / n, 3),
        "total_ret": round(sum(vals), 2),
        "max_ret": round(max(vals), 3),
        "min_ret": round(min(vals), 3),
    }


def layer_breakdown(records: list[dict]) -> dict[str, int]:
    bd: dict[str, int] = {}
    for r in records:
        layer = r.get("layer", "?")
        bd[layer] = bd.get(layer, 0) + 1
    return bd


# ── 報告輸出 ──────────────────────────────────────────────────────────────────

def _fmt_pct(v) -> str:
    if v is None:
        return "—"
    return f"{v:+.3f}%"


def write_report(
    strategy_records: dict[str, list[dict]],
    out_path: Path,
) -> None:
    lines = [
        "# Phase 3 v5 — 當沖優化 A/B/C/D 對比 Backtest",
        "",
        "> 期間: 2026-05-20 → 2026-06-03 (T+1 進場，11 交易日)",
        "> 含手續費 -0.6%",
        "> Baseline: v4 (Ch5-3+T1+T2, score 原公式, 每日 top-2, 13:30 出)",
        "",
        "## 五策略對比表",
        "",
    ]

    # 計算各策略 stats
    stats_table = []

    # Baseline
    bl = strategy_records["baseline"]
    bl_stats = _stats(bl, "net_1330")
    bl_umb_stats = _stats(bl, "net_umb")
    bl_bd = layer_breakdown(bl)

    # A
    a_recs = strategy_records["A"]
    a_stats = _stats(a_recs, "net_1330")
    a_umb_stats = _stats(a_recs, "net_umb")
    a_bd = layer_breakdown(a_recs)

    # B
    b_recs = strategy_records["B"]
    b_stats = _stats(b_recs, "net_1330")
    b_umb_stats = _stats(b_recs, "net_umb")
    b_bd = layer_breakdown(b_recs)

    # C (stop loss + 掀傘)
    c_recs = strategy_records["C"]
    c_stats = _stats(c_recs, "net_c")
    c_sl_stats = _stats(c_recs, "net_sl")
    c_bd = layer_breakdown(c_recs)

    # D (隔日開盤)
    d_recs = strategy_records["D"]
    d_stats = _stats(d_recs, "net_d")
    d_bd = layer_breakdown(d_recs)

    def bd_str(bd: dict) -> str:
        parts = []
        for k in ("Ch5-3", "T1", "T2"):
            if k in bd:
                parts.append(f"{k}×{bd[k]}")
        return " / ".join(parts) if parts else "—"

    lines += [
        "| 策略 | 說明 | 樣本 | Layer 分佈 | Win% | 平均淨報酬 | 累計淨報酬 | 最大+ | 最大- |",
        "|------|------|------|-----------|------|-----------|-----------|------|------|",
        f"| Baseline 13:30 | v4 原始 (T1+T2+Ch5-3) | {bl_stats['n']} | {bd_str(bl_bd)} | {bl_stats['win_rate']}% | {_fmt_pct(bl_stats['avg_ret'])} | {_fmt_pct(bl_stats['total_ret'])} | {_fmt_pct(bl_stats.get('max_ret'))} | {_fmt_pct(bl_stats.get('min_ret'))} |",
        f"| Baseline 掀傘  | v4 掀傘出場 | {bl_umb_stats['n']} | {bd_str(bl_bd)} | {bl_umb_stats['win_rate']}% | {_fmt_pct(bl_umb_stats['avg_ret'])} | {_fmt_pct(bl_umb_stats['total_ret'])} | {_fmt_pct(bl_umb_stats.get('max_ret'))} | {_fmt_pct(bl_umb_stats.get('min_ret'))} |",
        f"| A. Ch5-3 only (13:30) | 排除 T1/T2 | {a_stats['n']} | {bd_str(a_bd)} | {a_stats['win_rate']}% | {_fmt_pct(a_stats['avg_ret'])} | {_fmt_pct(a_stats['total_ret'])} | {_fmt_pct(a_stats.get('max_ret'))} | {_fmt_pct(a_stats.get('min_ret'))} |",
        f"| A. Ch5-3 only (掀傘)  | 排除 T1/T2 | {a_umb_stats['n']} | {bd_str(a_bd)} | {a_umb_stats['win_rate']}% | {_fmt_pct(a_umb_stats['avg_ret'])} | {_fmt_pct(a_umb_stats['total_ret'])} | {_fmt_pct(a_umb_stats.get('max_ret'))} | {_fmt_pct(a_umb_stats.get('min_ret'))} |",
        f"| B. 動 score (13:30) | Ch5-3+50/T2-10 | {b_stats['n']} | {bd_str(b_bd)} | {b_stats['win_rate']}% | {_fmt_pct(b_stats['avg_ret'])} | {_fmt_pct(b_stats['total_ret'])} | {_fmt_pct(b_stats.get('max_ret'))} | {_fmt_pct(b_stats.get('min_ret'))} |",
        f"| B. 動 score (掀傘)  | Ch5-3+50/T2-10 | {b_umb_stats['n']} | {bd_str(b_bd)} | {b_umb_stats['win_rate']}% | {_fmt_pct(b_umb_stats['avg_ret'])} | {_fmt_pct(b_umb_stats['total_ret'])} | {_fmt_pct(b_umb_stats.get('max_ret'))} | {_fmt_pct(b_umb_stats.get('min_ret'))} |",
        f"| C. Stop -1.5%+掀傘 | SL>掀傘>13:30 | {c_stats['n']} | {bd_str(c_bd)} | {c_stats['win_rate']}% | {_fmt_pct(c_stats['avg_ret'])} | {_fmt_pct(c_stats['total_ret'])} | {_fmt_pct(c_stats.get('max_ret'))} | {_fmt_pct(c_stats.get('min_ret'))} |",
        f"| C. Stop -1.5% only | 純 SL>13:30 | {c_sl_stats['n']} | {bd_str(c_bd)} | {c_sl_stats['win_rate']}% | {_fmt_pct(c_sl_stats['avg_ret'])} | {_fmt_pct(c_sl_stats['total_ret'])} | {_fmt_pct(c_sl_stats.get('max_ret'))} | {_fmt_pct(c_sl_stats.get('min_ret'))} |",
        f"| D. 隔日 9:00 開盤出 | 1day swing | {d_stats['n']} | {bd_str(d_bd)} | {d_stats['win_rate']}% | {_fmt_pct(d_stats['avg_ret'])} | {_fmt_pct(d_stats['total_ret'])} | {_fmt_pct(d_stats.get('max_ret'))} | {_fmt_pct(d_stats.get('min_ret'))} |",
        "",
    ]

    # ── 每個策略詳細明細 ──────────────────────────────────────────────────────
    def write_strategy_section(title: str, recs: list[dict], net_col: str, exit_col: str, exit_time_col: str) -> list[str]:
        sec_lines = [f"## {title}", ""]
        date_groups: dict[str, list[dict]] = {}
        for r in recs:
            d = r.get("entry_date", "?")
            date_groups.setdefault(d, []).append(r)

        sec_lines += [
            "| 日期 | Ticker | Layer | 進場時點 | 進場價 | 出場價 | 出場時點 | 淨報酬 | Score |",
            "|------|--------|-------|---------|--------|--------|---------|--------|-------|",
        ]
        for d in sorted(date_groups.keys()):
            for r in sorted(date_groups[d], key=lambda x: x.get("score_baseline", 0), reverse=True):
                ticker = r["ticker"]
                layer = r.get("layer", "?")
                et = r.get("entry_time", "?")
                ep = r.get("entry_price", 0.0)
                ex_p = r.get(exit_col) or 0.0
                ex_t = r.get(exit_time_col, "—") or "—"
                net = r.get(net_col)
                net_s = _fmt_pct(net)
                sc = round(r.get("score_baseline", 0), 1)
                sec_lines.append(
                    f"| {d} | {ticker} | {layer} | {et} | {ep:.1f} | {ex_p:.1f} | {ex_t} | {net_s} | {sc} |"
                )

        sec_lines.append("")

        # 統計
        st = _stats(recs, net_col)
        bd = layer_breakdown(recs)
        sec_lines += [
            f"**統計**: 樣本 {st['n']} | Win rate {st.get('win_rate')}% | 平均淨 {_fmt_pct(st.get('avg_ret'))} | 累計 {_fmt_pct(st.get('total_ret'))}",
            f"**Layer 分佈**: {bd_str(bd)}",
            "",
        ]

        # 最賺/最賠
        vals = [(r["ticker"], r["entry_date"], r.get(net_col)) for r in recs if r.get(net_col) is not None]
        if vals:
            best = max(vals, key=lambda x: x[2])
            worst = min(vals, key=lambda x: x[2])
            sec_lines += [
                f"- 最賺: **{best[0]}** @ {best[1]} → {_fmt_pct(best[2])}",
                f"- 最賠: **{worst[0]}** @ {worst[1]} → {_fmt_pct(worst[2])}",
                "",
            ]
        return sec_lines

    # Baseline
    lines += write_strategy_section(
        "Baseline (13:30出)",
        strategy_records["baseline"],
        "net_1330", "exit_1330", "exit_1330_time",
    )

    # A
    lines += write_strategy_section(
        "策略 A — 只做 Ch5-3 (13:30出)",
        strategy_records["A"],
        "net_1330", "exit_1330", "exit_1330_time",
    )
    lines += write_strategy_section(
        "策略 A — 只做 Ch5-3 (掀傘出)",
        strategy_records["A"],
        "net_umb", "exit_umb", "exit_umb_time",
    )

    # B
    lines += write_strategy_section(
        "策略 B — 動 Score (13:30出)",
        strategy_records["B"],
        "net_1330", "exit_1330", "exit_1330_time",
    )
    lines += write_strategy_section(
        "策略 B — 動 Score (掀傘出)",
        strategy_records["B"],
        "net_umb", "exit_umb", "exit_umb_time",
    )

    # C
    lines += write_strategy_section(
        "策略 C — Stop -1.5% + 掀傘出",
        strategy_records["C"],
        "net_c", "exit_c", "exit_c_time",
    )
    lines += write_strategy_section(
        "策略 C — 純 Stop -1.5% (13:30兜底)",
        strategy_records["C"],
        "net_sl", "exit_sl", "exit_sl_time",
    )

    # D
    def write_d_section(recs: list[dict]) -> list[str]:
        sec_lines = ["## 策略 D — 隔日 9:00 開盤出", ""]
        date_groups: dict[str, list[dict]] = {}
        for r in recs:
            d = r.get("entry_date", "?")
            date_groups.setdefault(d, []).append(r)

        sec_lines += [
            "| 進場日 | Ticker | Layer | 進場時點 | 進場價 | 出場日 | 開盤出場價 | 淨報酬 |",
            "|--------|--------|-------|---------|--------|--------|-----------|--------|",
        ]
        for d in sorted(date_groups.keys()):
            for r in sorted(date_groups[d], key=lambda x: x.get("score_baseline", 0), reverse=True):
                ticker = r["ticker"]
                layer = r.get("layer", "?")
                et = r.get("entry_time", "?")
                ep = r.get("entry_price", 0.0)
                ex_d = r.get("exit_d_date", "N/A")
                ex_p = r.get("exit_d_price") or 0.0
                net = r.get("net_d")
                net_s = _fmt_pct(net)
                sec_lines.append(
                    f"| {d} | {ticker} | {layer} | {et} | {ep:.1f} | {ex_d} | {ex_p:.1f} | {net_s} |"
                )
        sec_lines.append("")

        st = _stats(recs, "net_d")
        bd = layer_breakdown(recs)
        sec_lines += [
            f"**統計**: 樣本 {st['n']} | Win rate {st.get('win_rate')}% | 平均淨 {_fmt_pct(st.get('avg_ret'))} | 累計 {_fmt_pct(st.get('total_ret'))}",
            f"**Layer 分佈**: {bd_str(bd)}",
            "",
        ]
        vals = [(r["ticker"], r["entry_date"], r.get("net_d")) for r in recs if r.get("net_d") is not None]
        if vals:
            best = max(vals, key=lambda x: x[2])
            worst = min(vals, key=lambda x: x[2])
            sec_lines += [
                f"- 最賺: **{best[0]}** @ {best[1]} → {_fmt_pct(best[2])}",
                f"- 最賠: **{worst[0]}** @ {worst[1]} → {_fmt_pct(worst[2])}",
                "",
            ]
        return sec_lines

    lines += write_d_section(strategy_records["D"])

    lines += [
        "---",
        "",
        "_自動產出 @ 2026-06-04 (Phase 3 v5 ABCD 對比)_",
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n→ 報告寫入: {out_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--no-report", action="store_true", help="不輸出報告檔案")
    args = p.parse_args()

    print("=== Phase 3 v5 — 當沖優化 A/B/C/D ===")
    print(f"期間: 2026-05-20 → 2026-06-03 (11 交易日)")
    print(f"含手續費 -{FEE_PCT}%")
    print()

    strategy_records = run_v5_backtest()

    print("\n=== 五策略摘要 ===")
    print(f"{'策略':<28} {'樣本':>5} {'Win%':>7} {'平均淨':>9} {'累計淨':>9}")

    summaries = [
        ("Baseline 13:30", strategy_records["baseline"], "net_1330"),
        ("A Ch5-3 13:30",  strategy_records["A"],        "net_1330"),
        ("A Ch5-3 掀傘",   strategy_records["A"],        "net_umb"),
        ("B 動score 13:30", strategy_records["B"],       "net_1330"),
        ("B 動score 掀傘",  strategy_records["B"],       "net_umb"),
        ("C SL+掀傘",      strategy_records["C"],        "net_c"),
        ("C 純SL-1.5%",    strategy_records["C"],        "net_sl"),
        ("D 隔日開盤",      strategy_records["D"],       "net_d"),
    ]

    for label, recs, col in summaries:
        st = _stats(recs, col)
        n = st["n"]
        wr = f"{st['win_rate']}%" if st.get("win_rate") is not None else "—"
        ar = f"{st['avg_ret']:+.3f}%" if st.get("avg_ret") is not None else "—"
        tr = f"{st['total_ret']:+.2f}%" if st.get("total_ret") is not None else "—"
        bd = layer_breakdown(recs)
        bd_s = "/".join(f"{k}:{v}" for k, v in bd.items() if v > 0)
        print(f"  {label:<26} {n:>5} {wr:>7} {ar:>9} {tr:>9}  [{bd_s}]")

    if not args.no_report:
        out_path = (
            _REPO / "docs" / "主力大課程" / "strategies"
            / "phase3_v5_intraday_ABCD_5_19_to_6_3.md"
        )
        write_report(strategy_records, out_path)

    print("\n完成！")


if __name__ == "__main__":
    main()
