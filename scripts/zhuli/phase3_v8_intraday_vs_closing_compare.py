"""Phase 3 v8 — 早盤 vs 尾盤進場 錯過漲幅 Backtest

研究問題:
  等到 13:00 尾盤才進、平均錯過多少 intraday 漲幅？
  「等尾盤」是 net positive 還是 net negative？

設計:
  - 期間: 2026-05-19 → 2026-06-03 (~12 交易日)
  - 樣本: 所有 confirmed trigger (Ch5-3 / T1 / T2)、不限 top N
  - 對比 3 種進場策略 (相同 trigger、相同出場):

      策略 1: 「trigger 觸發即進」
              進場 = trigger 那根 5K close
      策略 2: 「等 9:45 再進」(filter 後最早)
              進場 = max(trigger 時間, 09:45) 那根 5K close
      策略 3: 「13:00 尾盤才進」
              進場 = max(trigger 時間, 13:00) 那根 5K close

  - 出場: 統一隔日 9:00 開盤 (策略 D)
  - 手續費: -0.6%

  「錯過漲幅」定義:
      intra_day_gain = (策略 3 進場價 - 策略 1 進場價) / 策略 1 進場價 * 100
      正值 = 尾盤比觸發時貴 (錯過漲幅)
      負值 = 尾盤比觸發時便宜 (殺尾，等反而更好)

Usage:
    python scripts/zhuli/phase3_v8_intraday_vs_closing_compare.py
    python scripts/zhuli/phase3_v8_intraday_vs_closing_compare.py --no-report
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

_REPO = Path(__file__).parent.parent.parent
_SYS = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_REPO), str(_REPO / "scripts"), str(_SYS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common.finmind_client import get_client

from zhuli.db import get_conn, MAIN_DB
from zhuli.intraday_stage_helper import StageTrigger, _get_ma10, _DB as _HELPER_DB  # noqa

_DB = MAIN_DB
_TMP = Path("/tmp")
_CACHE_DIR = _TMP / "finmind_kbar_cache"
_CACHE_DIR.mkdir(exist_ok=True)

# 手續費 (買 + 賣 + 證交稅) 約 0.6%
FEE_PCT = 0.6

# 進場策略時點
ENTRY_STRATEGY_TIMES = {
    "s1_trigger": None,     # trigger 那根 5K
    "s2_945":     "09:45",  # max(trigger, 09:45)
    "s3_1300":    "13:00",  # max(trigger, 13:00)
}

# 交易日清單
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

    try:
        df = get_client().fetch_dataset(
            dataset="TaiwanStockKBar",
            data_id=ticker,
            start_date=target_date,
            end_date=target_date,
            bypass_cache=True,
        )
    except Exception as e:
        print(f"  [ERR] FinMind {ticker} {target_date}: {e}")
        return pd.DataFrame()

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


def get_open_price(ticker: str, d: str) -> Optional[float]:
    """取指定日期開盤價。"""
    for attempt in range(3):
        try:
            con = get_conn(_DB, timeout=10)
            row = con.execute(
                "SELECT open FROM standard_daily_bar WHERE ticker=? AND trade_date=?",
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


def get_close_at_or_after(k5: pd.DataFrame, target_hhmm: str) -> tuple[Optional[float], Optional[str]]:
    """取 >= target_hhmm 的第一根 5K close，回傳 (price, actual_hhmm)。"""
    if k5.empty:
        return None, None
    for i, ts in enumerate(k5.index):
        t = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)[11:16]
        if t >= target_hhmm:
            return float(k5.iloc[i]["close"]), t
    return None, None


def get_close_at_or_before(k5: pd.DataFrame, target_hhmm: str) -> tuple[Optional[float], Optional[str]]:
    """取 <= target_hhmm 的最後一根 5K close，回傳 (price, actual_hhmm)。"""
    if k5.empty:
        return None, None
    last_price = None
    last_time = None
    for i, ts in enumerate(k5.index):
        t = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)[11:16]
        if t <= target_hhmm:
            last_price = float(k5.iloc[i]["close"])
            last_time = t
        else:
            break
    return last_price, last_time


# ── Trigger 偵測 ──────────────────────────────────────────────────────────────

def detect_first_trigger(
    engine: StageTrigger,
    ticker: str,
    entry_date: str,
    k5_full: pd.DataFrame,
    prev_levels: dict,
    regime: str,
) -> Optional[dict]:
    """偵測當日第一個 confirmed trigger，回傳記錄。"""
    prev_close = prev_levels.get("prev_close", 0.0)
    if not prev_close:
        return None

    ma10 = _get_ma10(ticker, entry_date)

    for i in range(1, len(k5_full) + 1):
        k5 = k5_full.iloc[:i]
        ts = k5_full.index[i - 1]
        ts_str = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)[11:16]
        if ts_str < "09:10":
            continue
        if ts_str > "13:00":
            break

        # Ch5-3
        r = engine.check_ch5_3_entry(k5, prev_close, ma10=ma10, market_regime=regime)
        if r.get("triggered"):
            ep = r.get("entry_price", r.get("price", float(k5.iloc[-1]["close"])))
            et = r.get("entry_time", ts_str)
            return {
                "ticker": ticker,
                "entry_date": entry_date,
                "layer": "Ch5-3",
                "trigger_time": et,
                "trigger_price": float(ep) if ep else float(k5.iloc[-1]["close"]),
                "market_regime": regime,
            }
        ch53_level = r.get("level", "watch")
        if ch53_level in ("signal", "pullback"):
            continue

        # T1
        r = engine.check_trigger_1(ticker, k5, prev_levels.get("prev_high"))
        if r.get("triggered"):
            return {
                "ticker": ticker,
                "entry_date": entry_date,
                "layer": "T1",
                "trigger_time": ts_str,
                "trigger_price": float(r.get("price") or k5.iloc[-1]["close"]),
                "market_regime": regime,
            }

        # T2
        r = engine.check_trigger_2(ticker, k5, datetime.min)
        if r.get("triggered"):
            return {
                "ticker": ticker,
                "entry_date": entry_date,
                "layer": "T2",
                "trigger_time": ts_str,
                "trigger_price": float(r.get("price") or k5.iloc[-1]["close"]),
                "market_regime": regime,
            }

    return None


# ── 主計算 ────────────────────────────────────────────────────────────────────

def compute_three_strategies(
    trigger: dict,
    k5_full: pd.DataFrame,
    exit_date: str,
) -> Optional[dict]:
    """
    對一個 trigger 計算 3 種進場策略的報酬。
    回傳 record dict，失敗回傳 None。
    """
    ticker = trigger["ticker"]
    trigger_time = trigger["trigger_time"]    # HH:MM
    trigger_price = trigger["trigger_price"]  # 策略 1 進場價

    exit_price = get_open_price(ticker, exit_date)
    if exit_price is None:
        return None

    # 策略 1: trigger 那根 5K close
    s1_price = trigger_price
    s1_time  = trigger_time

    # 策略 2: max(trigger, 09:45)
    s2_target = max(trigger_time, "09:45")
    s2_price, s2_time = get_close_at_or_before(k5_full, s2_target)
    if s2_price is None:
        # 嘗試往後找
        s2_price, s2_time = get_close_at_or_after(k5_full, s2_target)

    # 策略 3: max(trigger, 13:00)
    s3_target = max(trigger_time, "13:00")
    s3_price, s3_time = get_close_at_or_before(k5_full, s3_target)
    if s3_price is None:
        s3_price, s3_time = get_close_at_or_after(k5_full, s3_target)

    if s1_price is None or s2_price is None or s3_price is None:
        return None

    def net_ret(ep: float) -> float:
        return round((exit_price / ep - 1) * 100 - FEE_PCT, 3)

    s1_net = net_ret(s1_price)
    s2_net = net_ret(s2_price)
    s3_net = net_ret(s3_price)

    # 「錯過漲幅」: 尾盤比觸發時貴多少 (正 = 錯過漲幅、負 = 殺尾)
    intra_day_gain = round((s3_price / s1_price - 1) * 100, 3)

    return {
        "entry_date":       trigger["entry_date"],
        "exit_date":        exit_date,
        "ticker":           ticker,
        "layer":            trigger["layer"],
        "market_regime":    trigger["market_regime"],
        # 策略 1
        "s1_time":          s1_time,
        "s1_price":         round(s1_price, 2),
        "s1_net":           s1_net,
        "s1_win":           s1_net > 0,
        # 策略 2
        "s2_time":          s2_time,
        "s2_price":         round(s2_price, 2),
        "s2_net":           s2_net,
        "s2_win":           s2_net > 0,
        # 策略 3
        "s3_time":          s3_time,
        "s3_price":         round(s3_price, 2),
        "s3_net":           s3_net,
        "s3_win":           s3_net > 0,
        # 錯過分析
        "intra_day_gain":   intra_day_gain,
        "exit_price":       round(exit_price, 2),
    }


# ── 主 Backtest ───────────────────────────────────────────────────────────────

def run_v8_backtest() -> list[dict]:
    engine = StageTrigger()
    dates = TRADING_DATES_FULL
    all_records: list[dict] = []

    for scan_date in dates:
        md_path = _TMP / f"scanner_candidates_{scan_date}.md"
        if not md_path.exists():
            print(f"[SKIP] 無 scanner file: {scan_date}")
            continue

        watchlist = parse_scanner_candidates(md_path)
        entry_date = next_trading_day(scan_date, dates)
        if not entry_date:
            print(f"[SKIP] {scan_date} 沒有下一交易日 (進場日)")
            continue

        exit_date = next_trading_day(entry_date, dates)
        if not exit_date:
            print(f"[SKIP] {entry_date} 沒有下一交易日 (出場日)")
            continue

        regime = engine._detect_market_regime(entry_date, db_path=_DB)
        print(f"[{scan_date} → 進:{entry_date} → 出:{exit_date}] "
              f"watchlist={len(watchlist)} regime={_REGIME_EMOJI.get(regime, regime)}")

        day_n = 0
        for ticker in watchlist:
            k5_full = fetch_finmind_kbar_5m(ticker, entry_date)
            if k5_full.empty:
                continue

            prev_levels = get_prev_levels(ticker, entry_date)
            if not prev_levels.get("prev_close"):
                continue

            trigger = detect_first_trigger(engine, ticker, entry_date, k5_full, prev_levels, regime)
            if trigger is None:
                continue

            rec = compute_three_strategies(trigger, k5_full, exit_date)
            if rec is None:
                continue

            all_records.append(rec)
            day_n += 1

        print(f"  → {day_n} trigger(s) 收集")

    return all_records


# ── 統計函式 ──────────────────────────────────────────────────────────────────

def _stats(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0, "win_rate": None, "avg": None, "median": None,
                "total": None, "max": None, "min": None}
    n = len(vals)
    sorted_v = sorted(vals)
    return {
        "n":        n,
        "win_rate": round(sum(1 for v in vals if v > 0) / n * 100, 1),
        "avg":      round(sum(vals) / n, 3),
        "median":   round(sorted_v[n // 2], 3),
        "total":    round(sum(vals), 2),
        "max":      round(max(vals), 3),
        "min":      round(min(vals), 3),
    }


def _pct(v) -> str:
    if v is None:
        return "—"
    return f"{v:+.2f}%"


def _pct3(v) -> str:
    if v is None:
        return "—"
    return f"{v:+.3f}%"


# ── 報告輸出 ──────────────────────────────────────────────────────────────────

def print_summary(records: list[dict]) -> str:
    lines = []

    def _h(t):
        lines.append(f"\n{'='*70}")
        lines.append(f"  {t}")
        lines.append(f"{'='*70}")

    _h("Phase 3 v8 — 早盤 vs 尾盤進場 錯過漲幅 Backtest (5/19-6/3)")
    lines.append(f"  出場: 隔日 9:00 開盤 / Fee: -{FEE_PCT}% / 樣本: {len(records)} 個 trigger")

    # ── 策略比較主表 ──────────────────────────────────────────────────────────
    _h("1. 三策略整體比較")
    lines.append(f"  {'策略':<25} {'樣本':>5} {'Win%':>7} {'平均':>9} {'中位數':>9} {'累計':>9}")
    lines.append(f"  {'-'*65}")

    strategy_map = [
        ("s1", "1. 觸發即進"),
        ("s2", "2. 等 09:45"),
        ("s3", "3. 13:00 尾盤"),
    ]
    strategy_stats = {}
    for key, label in strategy_map:
        vals = [r[f"{key}_net"] for r in records if r.get(f"{key}_net") is not None]
        st = _stats(vals)
        strategy_stats[key] = st
        wr = f"{st['win_rate']:.1f}%" if st.get("win_rate") is not None else "—"
        avg = _pct(st.get("avg"))
        med = _pct(st.get("median"))
        tot = _pct(st.get("total"))
        lines.append(f"  {label:<25} {st['n']:>5} {wr:>7} {avg:>9} {med:>9} {tot:>9}")

    # 差距
    lines.append(f"\n  比較 (vs 策略 1 觸發即進):")
    for key, label in strategy_map[1:]:
        s1 = strategy_stats["s1"]
        sk = strategy_stats[key]
        if s1.get("avg") is not None and sk.get("avg") is not None:
            d_avg = sk["avg"] - s1["avg"]
            d_wr  = (sk["win_rate"] or 0) - (s1["win_rate"] or 0)
            lines.append(f"    {label}: Win {d_wr:+.1f}%pt, Avg {d_avg:+.3f}pp")

    # ── 錯過漲幅分析 ──────────────────────────────────────────────────────────
    _h("2. 「錯過漲幅」分析 (intra_day_gain = 13:00 進 vs 觸發即進)")
    lines.append("     intra_day_gain > 0 = 尾盤比早盤貴 (錯過漲幅)")
    lines.append("     intra_day_gain < 0 = 尾盤比早盤便宜 (殺尾、等反而好)")

    gains = [r["intra_day_gain"] for r in records]
    st_gain = _stats(gains)
    lines.append(f"\n  平均錯過: {st_gain['avg']:+.3f}%")
    lines.append(f"  中位數:   {st_gain['median']:+.3f}%")
    lines.append(f"  最大錯過: {st_gain['max']:+.3f}% (最痛的一筆)")
    lines.append(f"  最大反向: {st_gain['min']:+.3f}% (殺尾最多、等最值)")

    # 分布統計
    n = len(gains)
    brackets = [
        ("< -3%   (殺尾重、等很值)",  lambda g: g < -3),
        ("-3%~-1% (殺尾中)",          lambda g: -3 <= g < -1),
        ("-1%~0%  (殺尾輕)",          lambda g: -1 <= g < 0),
        ("0%~+1%  (影響小)",          lambda g: 0 <= g < 1),
        ("+1%~+3% (錯過小)",          lambda g: 1 <= g < 3),
        ("> +3%   (錯過大漲)",         lambda g: g >= 3),
    ]
    lines.append(f"\n  分布 (n={n}):")
    for label, fn in brackets:
        cnt = sum(1 for g in gains if fn(g))
        pct = cnt / n * 100 if n else 0
        lines.append(f"    {label:<28} {cnt:3}/{n}  ({pct:.1f}%)")

    cheaper = sum(1 for g in gains if g < 0)
    pct_cheaper = cheaper / n * 100 if n else 0
    lines.append(f"\n  ✅ 尾盤比早盤便宜 (殺尾):   {cheaper}/{n}  ({pct_cheaper:.1f}%)")
    lines.append(f"  ❌ 尾盤比早盤更貴 (錯過漲):  {n - cheaper}/{n}  ({100 - pct_cheaper:.1f}%)")

    # ── 每日分組統計 ──────────────────────────────────────────────────────────
    _h("3. 每日分組統計 (哪天最痛 / 哪天最值)")
    all_dates = sorted(set(r["entry_date"] for r in records))
    lines.append(f"  {'日期':<12} {'筆數':>4} {'平均錯過%':>10} {'最大錯過%':>11} {'S1 Avg':>8} {'S3 Avg':>8} {'評語':<20}")
    lines.append(f"  {'-'*75}")

    day_stats = []
    for d in all_dates:
        day_recs = [r for r in records if r["entry_date"] == d]
        dg = [r["intra_day_gain"] for r in day_recs]
        ds1 = [r["s1_net"] for r in day_recs]
        ds3 = [r["s3_net"] for r in day_recs]
        avg_g = sum(dg) / len(dg) if dg else 0
        max_g = max(dg) if dg else 0
        avg_s1 = sum(ds1) / len(ds1) if ds1 else 0
        avg_s3 = sum(ds3) / len(ds3) if ds3 else 0
        day_stats.append((d, len(day_recs), avg_g, max_g, avg_s1, avg_s3))

    # 排序: 平均錯過最多的 = 最痛
    for d, n_day, avg_g, max_g, avg_s1, avg_s3 in sorted(day_stats, key=lambda x: -x[2]):
        if avg_g > 2:
            note = "😭 最痛 (錯過大漲)"
        elif avg_g > 1:
            note = "⚠️ 錯過不少"
        elif avg_g < -1:
            note = "✅ 殺尾嚴重 (等值)"
        else:
            note = "—"
        lines.append(
            f"  {d:<12} {n_day:>4} {avg_g:>+9.2f}%  {max_g:>+10.2f}%  "
            f"{avg_s1:>+7.2f}%  {avg_s3:>+7.2f}%  {note}"
        )

    # ── Regime 對比 ───────────────────────────────────────────────────────────
    _h("4. 大盤 Regime 對比 (三策略)")
    lines.append(f"  {'Regime':<10} {'N':>4} {'S1 Win%':>8} {'S1 Avg':>8} {'S3 Win%':>8} {'S3 Avg':>8} {'錯過Avg':>9}")
    lines.append(f"  {'-'*60}")
    for regime in ("strong", "normal", "weak"):
        rr = [r for r in records if r["market_regime"] == regime]
        if not rr:
            continue
        s1v = [r["s1_net"] for r in rr]
        s3v = [r["s3_net"] for r in rr]
        gv  = [r["intra_day_gain"] for r in rr]
        st1 = _stats(s1v)
        st3 = _stats(s3v)
        stg = _stats(gv)
        emoji = _REGIME_EMOJI.get(regime, regime)
        lines.append(
            f"  {emoji:<10} {len(rr):>4} "
            f"{(st1['win_rate'] or 0):>7.1f}%  {(st1['avg'] or 0):>+7.2f}%  "
            f"{(st3['win_rate'] or 0):>7.1f}%  {(st3['avg'] or 0):>+7.2f}%  "
            f"{(stg['avg'] or 0):>+8.2f}%"
        )

    # ── Layer 對比 ────────────────────────────────────────────────────────────
    _h("5. Layer 對比 (Ch5-3 / T1 / T2)")
    lines.append(f"  {'Layer':<8} {'N':>4} {'S1 Win%':>8} {'S1 Avg':>8} {'S3 Win%':>8} {'S3 Avg':>8} {'錯過Avg':>9}")
    lines.append(f"  {'-'*60}")
    for layer in ("Ch5-3", "T1", "T2"):
        lr = [r for r in records if r["layer"] == layer]
        if not lr:
            continue
        s1v = [r["s1_net"] for r in lr]
        s3v = [r["s3_net"] for r in lr]
        gv  = [r["intra_day_gain"] for r in lr]
        st1 = _stats(s1v)
        st3 = _stats(s3v)
        stg = _stats(gv)
        lines.append(
            f"  {layer:<8} {len(lr):>4} "
            f"{(st1['win_rate'] or 0):>7.1f}%  {(st1['avg'] or 0):>+7.2f}%  "
            f"{(st3['win_rate'] or 0):>7.1f}%  {(st3['avg'] or 0):>+7.2f}%  "
            f"{(stg['avg'] or 0):>+8.2f}%"
        )

    # ── 關鍵問題回答 ──────────────────────────────────────────────────────────
    _h("6. 關鍵問題回答")

    avg_g = st_gain.get("avg") or 0
    med_g = st_gain.get("median") or 0
    s1_avg = strategy_stats["s1"].get("avg") or 0
    s3_avg = strategy_stats["s3"].get("avg") or 0
    s1_wr  = strategy_stats["s1"].get("win_rate") or 0
    s3_wr  = strategy_stats["s3"].get("win_rate") or 0

    lines.append(f"  Q1. 平均錯過多少% intraday rally?")
    lines.append(f"      → {avg_g:+.3f}% (13:00 進場比觸發時平均貴這麼多)")
    lines.append(f"  Q2. 中位數錯過?")
    lines.append(f"      → {med_g:+.3f}%")
    lines.append(f"  Q3. 多少 trigger 反而尾盤比早盤便宜 (殺尾)?")
    lines.append(f"      → {cheaper}/{n} ({pct_cheaper:.1f}%)")
    lines.append(f"  Q4. 「等尾盤」是 net positive 還是 net negative?")
    delta_wr = s3_wr - s1_wr
    delta_avg = s3_avg - s1_avg
    if delta_wr > 3 and delta_avg > 0:
        verdict = "✅ Net Positive — 尾盤 Win rate 更高、avg 更好"
    elif delta_wr > 3 and delta_avg < 0:
        verdict = "⚠️ 混合 — 尾盤 Win rate 提升但 avg 報酬下降 (錯過漲幅)"
    elif delta_wr < -3:
        verdict = "❌ Net Negative — 尾盤 Win rate 更低"
    elif abs(delta_wr) <= 3 and abs(delta_avg) < 0.3:
        verdict = "⚪ 差異不顯著 — 樣本量需更多驗證"
    else:
        verdict = f"⚠️ 差距: Win {delta_wr:+.1f}%pt, Avg {delta_avg:+.3f}pp"
    lines.append(f"      S1: Win={s1_wr:.1f}% Avg={s1_avg:+.2f}%")
    lines.append(f"      S3: Win={s3_wr:.1f}% Avg={s3_avg:+.2f}%")
    lines.append(f"      → {verdict}")

    # 最痛 / 最值
    if day_stats:
        worst_day = max(day_stats, key=lambda x: x[2])
        best_day  = min(day_stats, key=lambda x: x[2])
        lines.append(f"  Q5. 哪天最痛 (等最可惜)?")
        lines.append(f"      → {worst_day[0]}  平均錯過 {worst_day[2]:+.2f}%  (最大 {worst_day[3]:+.2f}%)")
        lines.append(f"  Q6. 哪天最值 (殺尾嚴重、等反而好)?")
        lines.append(f"      → {best_day[0]}  平均錯過 {best_day[2]:+.2f}%")

    # ── 簡易結論 ──────────────────────────────────────────────────────────────
    _h("7. 簡易結論")
    lines.append(f"  錯過漲幅: 平均 {avg_g:+.2f}%、中位數 {med_g:+.2f}%")
    lines.append(f"  殺尾比例: {pct_cheaper:.0f}% 的 trigger 尾盤反而更便宜")
    lines.append(f"  策略對比: S1(觸發)={s1_wr:.0f}%/avg{s1_avg:+.2f}%  "
                 f"S3(尾盤)={s3_wr:.0f}%/avg{s3_avg:+.2f}%")
    lines.append(f"  整體評估: {verdict}")

    text = "\n".join(lines)
    print(text)
    return text


def write_report(text: str, records: list[dict]) -> Path:
    report_dir = _REPO / "docs" / "主力大課程" / "strategies"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "phase3_v8_intraday_vs_closing_5_19_to_6_3.md"

    # 建立詳細清單
    detail_rows = [
        "# Phase 3 v8 — 早盤 vs 尾盤進場 錯過漲幅 Backtest (5/19-6/3)",
        "",
        "## 執行摘要",
        "",
        "```",
        text,
        "```",
        "",
        "## 詳細清單",
        "",
        "| 日期 | Ticker | Layer | Regime | trigger | S1 時 | S1 進 | S2 時 | S2 進 | S3 時 | S3 進 | 出場 | S1% | S2% | S3% | 錯過% |",
        "|------|--------|-------|--------|---------|------|------|------|------|------|------|------|-----|-----|-----|------|",
    ]

    for r in sorted(records, key=lambda x: (x["entry_date"], x["ticker"])):
        s1w = "✅" if r["s1_win"] else "❌"
        s2w = "✅" if r["s2_win"] else "❌"
        s3w = "✅" if r["s3_win"] else "❌"
        gain_emoji = "📉" if r["intra_day_gain"] < 0 else ("📈" if r["intra_day_gain"] > 1 else "➡️")
        row = (
            f"| {r['entry_date']} | {r['ticker']} | {r['layer']} "
            f"| {_REGIME_EMOJI.get(r['market_regime'], r['market_regime'])} "
            f"| {r['s1_time']} "
            f"| {r['s1_time']} | {r['s1_price']:.1f} "
            f"| {r['s2_time']} | {r['s2_price']:.1f} "
            f"| {r['s3_time']} | {r['s3_price']:.1f} "
            f"| {r['exit_price']:.1f} "
            f"| {s1w}{r['s1_net']:+.2f}% "
            f"| {s2w}{r['s2_net']:+.2f}% "
            f"| {s3w}{r['s3_net']:+.2f}% "
            f"| {gain_emoji}{r['intra_day_gain']:+.2f}% |"
        )
        detail_rows.append(row)

    detail_rows += [
        "",
        "---",
        "",
        "_自動產出 @ 2026-06-04 (Phase 3 v8 早盤 vs 尾盤進場比較)_",
    ]

    report_path.write_text("\n".join(detail_rows), encoding="utf-8")
    print(f"\n  報告寫入: {report_path}")
    return report_path


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Phase 3 v8 早盤 vs 尾盤進場 錯過漲幅 backtest")
    p.add_argument("--no-report", action="store_true", default=False, help="不寫報告檔")
    args = p.parse_args()

    print("Phase 3 v8 — 早盤 vs 尾盤進場 錯過漲幅 Backtest 啟動")
    print(f"期間: {TRADING_DATES_FULL[0]} → {TRADING_DATES_FULL[-1]}")
    print(f"出場: 隔日 9:00 開盤 / Fee: -{FEE_PCT}%")
    print(f"樣本: 全部 confirmed trigger (Ch5-3 / T1 / T2)")
    print()

    records = run_v8_backtest()
    print(f"\n→ 收集到 {len(records)} 個 trigger 記錄")

    if not records:
        print("  ⚠️ 無任何 trigger 記錄，請確認 scanner 檔案與 DB 資料是否正確")
        return

    report_text = print_summary(records)

    if not args.no_report:
        write_report(report_text, records)

    print("\n完成！")


if __name__ == "__main__":
    main()
