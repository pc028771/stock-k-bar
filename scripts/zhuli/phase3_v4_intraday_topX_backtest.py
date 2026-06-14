"""Phase 3 v4 — 純當沖 Intraday Backtest (Top-2/day, 2 週)

任務規格:
  - 期間: 2026-05-19 → 2026-06-03 (~10 交易日)
  - 進場: composite_check confirmed 那根 5K 收盤價
  - 出場: 純當沖 13:30 最後 1 分 K 收盤 (絕不留倉)
  - 篩選: 只取 confirmed layer (首攻/續攻/反彈)、排除 破底
  - 排序: v3 score → 每日 top-2 (--max-per-day 2)
  - 含手續費 -0.6% (買 + 賣 + 證交稅 簡化)

Trigger 命名對照 (新中文名 → 舊英文名 alias):
  首攻 = Ch5-3  (第一根 5K SOP)
  續攻 = T1     (強勢延續)
  反彈 = T2     (跌深反彈)
  破底 = TC     (結構失敗)
  本腳本內部 layer 欄位保留舊英文名以維持歷史報告相容性。

多種 exit 策略對比:
  1. 13:30 收盤  (基本版)
  2. 13:20 收盤  (避殺尾盤)
  3. 5MA 動態    (5K 跌破 5 日線立即出)
  4. 掀傘訊號   (連 2-3 根 5K 不創高 + 量縮)

Usage:
    python scripts/zhuli/phase3_v4_intraday_topX_backtest.py
    python scripts/zhuli/phase3_v4_intraday_topX_backtest.py --max-per-day 3
    python scripts/zhuli/phase3_v4_intraday_topX_backtest.py --no-report
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

# 含手續費 (買 + 賣 + 證交稅) 約 0.6%
FEE_PCT = 0.6

# ── 交易日清單 (2 週: 5/19 ~ 6/3) ─────────────────────────────────────────────
# 5/19 的 scanner → 5/20 進場 (T+1)
# 6/3 的 scanner → 6/4 進場 (但 6/4 不是本 backtest 期間)
# 因此有效交易日 = 5/20 ~ 6/3 (9 個)
TRADING_DATES_2W = [
    "2026-05-19", "2026-05-20", "2026-05-21", "2026-05-22",
    "2026-05-26", "2026-05-27", "2026-05-28", "2026-05-29",
    "2026-06-02", "2026-06-03",
]

# 含 5/25 (週一) 的版本
TRADING_DATES_FULL = [
    "2026-05-19", "2026-05-20", "2026-05-21", "2026-05-22",
    "2026-05-25", "2026-05-26", "2026-05-27", "2026-05-28", "2026-05-29",
    "2026-06-01", "2026-06-02", "2026-06-03",
]


def next_trading_day(d: str, dates: list[str]) -> Optional[str]:
    idx = dates.index(d) if d in dates else -1
    if idx < 0 or idx + 1 >= len(dates):
        return None
    return dates[idx + 1]


# ── 大盤環境 emoji ─────────────────────────────────────────────────────────────
_REGIME_EMOJI = {"strong": "🟢強", "weak": "🔴弱", "normal": "⚪平"}


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
        print(f"  [RL] {_finmind_calls} FinMind calls, sleep 1s")
        time.sleep(1.0)
        _finmind_call_ts = time.time()
    else:
        time.sleep(0.12)


def fetch_finmind_kbar_5m(ticker: str, target_date: str) -> pd.DataFrame:
    """從 FinMind 抓 5 分 K (含 cache)。"""
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
        print("[WARN] FINMIND_TOKEN 未設定，跳過 FinMind 抓取")
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


# ── 分 K 價格查詢 (1 分 K cache) ─────────────────────────────────────────────

_MINKBAR_CACHE_DIR = _TMP / "finmind_1m_cache"
_MINKBAR_CACHE_DIR.mkdir(exist_ok=True)


def fetch_finmind_kbar_1m(ticker: str, target_date: str) -> pd.DataFrame:
    """從 FinMind 抓 1 分 K (含 cache)，用於精確出場價。"""
    cache_file = _MINKBAR_CACHE_DIR / f"{ticker}_{target_date}.json"
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
                print(f"  [ERR] FinMind 1m {ticker} {target_date}: {e}")
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

    df_save = df.reset_index()
    df_save["datetime"] = df_save["datetime"].astype(str)
    cache_file.write_text(json.dumps(df_save.to_dict("records"), ensure_ascii=False))
    return df


def get_close_at_time(k5: pd.DataFrame, target_time: str) -> Optional[float]:
    """從 5K DataFrame 找最接近 target_time 的收盤價 (13:30 = 最後一根)。"""
    if k5.empty:
        return None

    # 找 target_time 之前最後一根 5K
    target_ts = pd.Timestamp(f"2000-01-01 {target_time}")
    filtered = k5[k5.index.strftime("%H:%M") <= target_time]
    if filtered.empty:
        return None
    return float(filtered.iloc[-1]["close"])


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


# ── Score (與 v3 相同) ────────────────────────────────────────────────────────

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


def _score_trigger(hit: dict) -> float:
    score = 0.0
    # 支援新中文名及舊英文名 alias
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


# ── Exit 策略 ─────────────────────────────────────────────────────────────────

def compute_exit_1330(k5: pd.DataFrame, entry_time: str) -> tuple[Optional[float], str]:
    """Exit 1: 13:30 收盤 (最後一根)。"""
    return get_close_at_time(k5, "13:30"), "13:30"


def compute_exit_1320(k5: pd.DataFrame, entry_time: str) -> tuple[Optional[float], str]:
    """Exit 2: 13:20 收盤 (避殺尾盤)。"""
    return get_close_at_time(k5, "13:20"), "13:20"


def compute_exit_5ma_dynamic(
    k5: pd.DataFrame, entry_time: str, entry_price: float
) -> tuple[Optional[float], str]:
    """Exit 3: 跌破 5K 5 日線立即出 (動態出場)。
    5 日線 = 5K 本身的 rolling(5) MA (同日內 5 根移動平均)。
    若到 13:30 都沒跌破 → 用 13:30 收盤。
    """
    if k5.empty:
        return None, "no_data"

    # 只看進場時點之後
    entry_ts = entry_time  # "HH:MM"
    after_entry = k5[k5.index.strftime("%H:%M") >= entry_ts].copy()
    if after_entry.empty:
        return get_close_at_time(k5, "13:30"), "13:30 (no_bar_after_entry)"

    # 計算 rolling 5 MA (用全日 k5 計算，entry 後觀察)
    k5_with_ma = k5.copy()
    k5_with_ma["ma5"] = k5_with_ma["close"].rolling(5, min_periods=1).mean()

    exit_price = None
    exit_time_str = "13:30"

    for ts, row in after_entry.iterrows():
        ts_str = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)[11:16]
        if ts_str > "13:30":
            break

        ma5_val = k5_with_ma.loc[ts, "ma5"] if ts in k5_with_ma.index else None
        bar_close = float(row["close"])

        if ma5_val is not None and bar_close < float(ma5_val):
            exit_price = bar_close
            exit_time_str = f"{ts_str}(5MA出)"
            break

    if exit_price is None:
        # 沒跌破 5MA → 13:30 出
        exit_price = get_close_at_time(k5, "13:30")
        exit_time_str = "13:30"

    return exit_price, exit_time_str


def compute_exit_umbrella(
    k5: pd.DataFrame, entry_time: str, entry_price: float
) -> tuple[Optional[float], str]:
    """Exit 4: 掀傘訊號 (連 2-3 根 5K 不創新高 + 量縮)。
    老師「掀傘」= 拉上去後 2-3 根不創高 + 量萎縮 → 出。
    若到 13:30 都沒掀傘 → 13:30 出。
    """
    if k5.empty:
        return None, "no_data"

    entry_ts = entry_time
    after_entry = k5[k5.index.strftime("%H:%M") >= entry_ts].copy()
    if after_entry.empty:
        return get_close_at_time(k5, "13:30"), "13:30"

    # 找進場後最高點
    peak_price = float(k5[k5.index.strftime("%H:%M") >= entry_ts]["high"].max())

    exit_price = None
    exit_time_str = "13:30"

    # 掀傘判斷: 最高後連 2 根不創高 + 量縮 (< 前 3 根均量)
    bars = list(after_entry.iterrows())
    n = len(bars)
    for i in range(1, n - 1):
        ts_i, row_i = bars[i]
        ts_str = ts_i.strftime("%H:%M") if hasattr(ts_i, "strftime") else str(ts_i)[11:16]
        if ts_str > "13:25":  # 最晚 13:25 才出
            break

        # 找目前為止最高
        rolling_high = float(after_entry.iloc[:i + 1]["high"].max())

        # 連 2 根不創高
        next_bar_ts, next_bar = bars[i]
        if i + 1 < n:
            next2_ts, next2_bar = bars[i + 1]
        else:
            continue

        bar_high_1 = float(next_bar["high"])
        bar_high_2 = float(next2_bar["high"])

        no_new_high = (bar_high_1 <= rolling_high * 1.001 and
                       bar_high_2 <= rolling_high * 1.001)

        # 量縮: 最近 2 根均量 < 前 3 根均量
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


# ── 主 Backtest ───────────────────────────────────────────────────────────────

def run_intraday_backtest(max_per_day: int = 2) -> list[dict]:
    """核心迴圈: 每日 scanner → composite_check (confirmed only) → 當沖計算。"""
    engine = StageTrigger()
    records: list[dict] = []

    dates = TRADING_DATES_FULL

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
        regime_label = _REGIME_EMOJI.get(regime, regime)
        print(f"[{scan_date} → {next_date}] watchlist={len(watchlist)} regime={regime_label}")

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

            # cascade: Ch5-3 → T1 → T2 (排除 TC)
            for i in range(1, len(k5_full) + 1):
                k5 = k5_full.iloc[:i]
                ts = k5_full.index[i - 1]
                ts_str = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)[11:16]
                if ts_str < "09:10":
                    continue
                if ts_str > "13:00":  # 當沖不在收盤前 30 分鐘才觸發
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
                    continue  # 等 confirmed

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

                # TC 排除 (不計算當沖)

            if trigger_rec is not None and trigger_rec["entry_price"]:
                trigger_rec["score"] = _score_trigger(trigger_rec)
                day_triggers.append(trigger_rec)

        # top-N 選取
        if not day_triggers:
            print(f"  → 無觸發")
            continue

        day_triggers_sorted = sorted(day_triggers, key=lambda x: x["score"], reverse=True)
        selected = day_triggers_sorted[:max_per_day] if max_per_day > 0 else day_triggers_sorted

        print(f"  → 觸發 {len(day_triggers)} 筆，取 top {len(selected)}")

        for trec in selected:
            ticker = trec["ticker"]
            entry_price = trec["entry_price"]
            entry_time = trec["entry_time"]
            k5_full = fetch_finmind_kbar_5m(ticker, next_date)

            # 計算 4 種 exit
            ex1, et1 = compute_exit_1330(k5_full, entry_time)
            ex2, et2 = compute_exit_1320(k5_full, entry_time)
            ex3, et3 = compute_exit_5ma_dynamic(k5_full, entry_time, entry_price)
            ex4, et4 = compute_exit_umbrella(k5_full, entry_time, entry_price)

            def _ret(exit_p: Optional[float]) -> Optional[float]:
                if exit_p is None or not entry_price:
                    return None
                return round((exit_p / entry_price - 1) * 100, 3)

            def _net(r: Optional[float]) -> Optional[float]:
                if r is None:
                    return None
                return round(r - FEE_PCT, 3)

            r1 = _ret(ex1); r2 = _ret(ex2); r3 = _ret(ex3); r4 = _ret(ex4)

            trec.update({
                "exit_1330": ex1, "ret_1330": r1, "net_1330": _net(r1),
                "exit_1320": ex2, "ret_1320": r2, "net_1320": _net(r2),
                "exit_5ma":  ex3, "ret_5ma":  r3, "net_5ma":  _net(r3), "exit_5ma_time": et3,
                "exit_umb":  ex4, "ret_umb":  r4, "net_umb":  _net(r4), "exit_umb_time": et4,
            })
            records.append(trec)

    return records


# ── 統計分析 ──────────────────────────────────────────────────────────────────

def _stats_for_col(records: list[dict], ret_col: str) -> dict:
    vals = [r[ret_col] for r in records if r.get(ret_col) is not None]
    if not vals:
        return {"n": 0, "win_rate": None, "avg_ret": None, "max_ret": None, "min_ret": None}
    n = len(vals)
    win_rate = round(sum(1 for v in vals if v > 0) / n * 100, 1)
    avg_ret = round(sum(vals) / n, 3)
    return {
        "n": n,
        "win_rate": win_rate,
        "avg_ret": avg_ret,
        "max_ret": round(max(vals), 3),
        "min_ret": round(min(vals), 3),
        "total_ret": round(sum(vals), 2),
    }


def analyze_results(records: list[dict]) -> dict:
    if not records:
        return {}
    return {
        "13:30收盤":  _stats_for_col(records, "net_1330"),
        "13:20收盤":  _stats_for_col(records, "net_1320"),
        "5MA動態":    _stats_for_col(records, "net_5ma"),
        "掀傘訊號":   _stats_for_col(records, "net_umb"),
    }


# ── 報告輸出 ──────────────────────────────────────────────────────────────────

def write_report(records: list[dict], stats: dict, out_path: Path, max_per_day: int) -> None:
    lines = [
        "# Phase 3 v4 — 純當沖 Intraday Backtest (Top-2/day, 2 週)",
        "",
        f"> 期間: 2026-05-19 → 2026-06-03 (TRADING_DATES_FULL, scanner T+1 進場)",
        f"> 進場: composite_check confirmed 5K 收盤價  |  出場: 當日收盤 (多種策略)",
        f"> 每日 top-{max_per_day} (v3 score 排序)  |  含手續費 -{FEE_PCT}%",
        "",
        "## Exit 策略對比",
        "",
        "| Exit 策略 | 樣本 | Win rate | 平均淨報酬 | 累計淨報酬 | 最大單筆+ | 最大單筆- |",
        "|-----------|------|---------|-----------|-----------|----------|----------|",
    ]

    for label, s in stats.items():
        n = s.get("n", 0)
        wr = f"{s['win_rate']}%" if s.get("win_rate") is not None else "—"
        ar = f"{s['avg_ret']:+.3f}%" if s.get("avg_ret") is not None else "—"
        tr = f"{s['total_ret']:+.2f}%" if s.get("total_ret") is not None else "—"
        mx = f"{s['max_ret']:+.3f}%" if s.get("max_ret") is not None else "—"
        mn = f"{s['min_ret']:+.3f}%" if s.get("min_ret") is not None else "—"
        lines.append(f"| {label} | {n} | {wr} | {ar} | {tr} | {mx} | {mn} |")

    lines += ["", "## 每日交易明細", ""]

    # 按日期分組
    date_groups: dict[str, list[dict]] = {}
    for r in records:
        d = r.get("entry_date", "?")
        date_groups.setdefault(d, []).append(r)

    # 找大盤 regime
    engine = StageTrigger()

    for d in sorted(date_groups.keys()):
        day_recs = date_groups[d]
        regime = day_recs[0].get("market_regime", "normal") if day_recs else "normal"
        regime_icon = _REGIME_EMOJI.get(regime, regime)
        day_net = [r.get("net_1330") for r in day_recs if r.get("net_1330") is not None]
        day_avg = f"{sum(day_net)/len(day_net):+.2f}%" if day_net else "—"
        lines.append(f"### {d} ({regime_icon}) 日均淨報酬: {day_avg}")
        lines.append("")
        lines.append("| Ticker | Layer | 進場時點 | 進場價 | 13:30出 | 13:20出 | 5MA出 | 掀傘出 | 淨1330 | 淨1320 | 淨5MA | 淨掀傘 | Score |")
        lines.append("|--------|-------|---------|--------|--------|--------|------|--------|--------|--------|-------|--------|-------|")
        for r in sorted(day_recs, key=lambda x: x.get("score", 0), reverse=True):
            tk = r["ticker"]
            lyr = r.get("layer", "?")
            et = r.get("entry_time", "?")
            ep = r.get("entry_price", 0.0)
            ex1 = r.get("exit_1330") or 0.0
            ex2 = r.get("exit_1320") or 0.0
            ex3 = r.get("exit_5ma") or 0.0
            ex3t = r.get("exit_5ma_time", "—")
            ex4 = r.get("exit_umb") or 0.0
            ex4t = r.get("exit_umb_time", "—")

            def _fmt(v): return f"{v:+.3f}%" if v is not None else "—"

            n1 = _fmt(r.get("net_1330"))
            n2 = _fmt(r.get("net_1320"))
            n3 = _fmt(r.get("net_5ma"))
            n4 = _fmt(r.get("net_umb"))
            sc = round(r.get("score", 0), 1)
            lines.append(
                f"| {tk} | {lyr} | {et} | {ep:.1f} "
                f"| {ex1:.1f} | {ex2:.1f} | {ex3:.1f}({ex3t}) | {ex4:.1f}({ex4t}) "
                f"| {n1} | {n2} | {n3} | {n4} | {sc} |"
            )
        lines.append("")

    # 每日均報酬小計
    lines += ["## 每日均報酬 (13:30 淨報酬)", ""]
    lines.append("| 日期 | 大盤 | 筆數 | 日均淨報酬 (13:30) | 累計淨報酬 |")
    lines.append("|------|------|------|-----------------|-----------|")
    cum = 0.0
    for d in sorted(date_groups.keys()):
        day_recs = date_groups[d]
        regime = day_recs[0].get("market_regime", "normal") if day_recs else "normal"
        regime_icon = _REGIME_EMOJI.get(regime, regime)
        day_net = [r.get("net_1330") for r in day_recs if r.get("net_1330") is not None]
        if day_net:
            day_avg = sum(day_net) / len(day_net)
            cum += day_avg
            lines.append(
                f"| {d} | {regime_icon} | {len(day_net)} | {day_avg:+.3f}% | {cum:+.3f}% |"
            )
        else:
            lines.append(f"| {d} | {regime_icon} | 0 | — | {cum:+.3f}% |")

    lines += [
        "",
        "## 與波段 3d 對比",
        "",
        "> 前一版 phase3_v2/v3 (波段 3d 報酬) avg ≈ +2.35%",
        f"> 本版 當沖 13:30 avg = {stats.get('13:30收盤', {}).get('avg_ret', 'N/A')}% (毛)  ",
        f">        當沖 13:30 net = {stats.get('13:30收盤', {}).get('avg_ret', 'N/A')}%  ",
        "",
        "| 比較維度 | 當沖 (13:30淨) | 波段 3d (毛) | 備註 |",
        "|---------|--------------|-------------|------|",
    ]

    st1330 = stats.get("13:30收盤", {})
    intra_avg = st1330.get("avg_ret")
    intra_wr = st1330.get("win_rate")
    intra_avg_s = f"{intra_avg:+.3f}%" if intra_avg is not None else "—"
    intra_wr_s = f"{intra_wr}%" if intra_wr is not None else "—"
    lines.append(f"| 平均報酬 | {intra_avg_s} | ~+2.35% | 含手續費 vs 不含 |")
    lines.append(f"| Win rate | {intra_wr_s} | ~60-70% | 當日收盤 vs 3d 後 |")
    lines.append(f"| 持倉風險 | 無 (日結) | 高 (3日夜盤) | 當沖優勢 |")
    lines.append("")

    # 最賺/最賠
    all_net = [(r["ticker"], r["entry_date"], r.get("net_1330")) for r in records if r.get("net_1330") is not None]
    if all_net:
        best = max(all_net, key=lambda x: x[2])
        worst = min(all_net, key=lambda x: x[2])
        lines += [
            "## 最賺 / 最賠 (13:30 淨報酬)",
            "",
            f"- **最賺**: {best[0]} @ {best[1]} → **{best[2]:+.3f}%**",
            f"- **最賠**: {worst[0]} @ {worst[1]} → **{worst[2]:+.3f}%**",
            "",
        ]

    lines += [
        "---",
        "",
        "_自動產出 @ 2026-06-04 (Phase 3 v4 intraday)_",
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n→ 報告寫入: {out_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--max-per-day", type=int, default=2,
                   help="每日最多取 N 個觸發 (0=全取、預設 2)")
    p.add_argument("--no-report", action="store_true", help="不輸出報告檔案")
    args = p.parse_args()

    print("=== Phase 3 v4 — 純當沖 Intraday Backtest ===")
    print(f"期間: 2026-05-19 → 2026-06-03 (TRADING_DATES_FULL)")
    print(f"每日 top-{args.max_per_day} confirmed only (排除 TC)")
    print(f"含手續費 -{FEE_PCT}%")
    print()

    records = run_intraday_backtest(max_per_day=args.max_per_day)

    print(f"\n[完成] 共 {len(records)} 筆當沖記錄")
    if not records:
        print("[WARN] 無任何當沖記錄，可能 scanner 檔案不足或 FinMind 無資料")
        return

    stats = analyze_results(records)

    print("\n=== Exit 策略統計 ===")
    print(f"{'策略':<12} {'樣本':>5} {'Win%':>7} {'平均淨':>9} {'累計淨':>9} {'最大+':>8} {'最大-':>8}")
    for label, s in stats.items():
        n = s.get("n", 0)
        wr = f"{s['win_rate']}%" if s.get("win_rate") is not None else "—"
        ar = f"{s['avg_ret']:+.3f}%" if s.get("avg_ret") is not None else "—"
        tr = f"{s['total_ret']:+.2f}%" if s.get("total_ret") is not None else "—"
        mx = f"{s['max_ret']:+.3f}%" if s.get("max_ret") is not None else "—"
        mn = f"{s['min_ret']:+.3f}%" if s.get("min_ret") is not None else "—"
        print(f"{label:<12} {n:>5} {wr:>7} {ar:>9} {tr:>9} {mx:>8} {mn:>8}")

    # 每日詳細
    print("\n=== 每日交易明細 ===")
    date_groups: dict[str, list[dict]] = {}
    for r in records:
        date_groups.setdefault(r.get("entry_date", "?"), []).append(r)

    for d in sorted(date_groups.keys()):
        day_recs = date_groups[d]
        regime = day_recs[0].get("market_regime", "normal")
        regime_icon = _REGIME_EMOJI.get(regime, regime)
        for r in day_recs:
            n1 = r.get("net_1330")
            n3t = r.get("exit_5ma_time", "")
            print(
                f"  {d} ({regime_icon}) {r['ticker']} [{r.get('layer','?')}]"
                f" 進={r.get('entry_price',0):.1f}@{r.get('entry_time','?')}"
                f" 1330淨={n1:+.3f}%" if n1 is not None else ""
            )

    if not args.no_report:
        out_path = (
            _REPO / "docs" / "主力大課程" / "strategies"
            / "phase3_v4_intraday_top2_5_19_to_6_3.md"
        )
        write_report(records, stats, out_path, args.max_per_day)

    print("\n完成！")


if __name__ == "__main__":
    main()
