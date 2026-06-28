"""Phase 3 v9 — 尾盤 13:00-13:25 各時點進場 Backtest

研究問題:
  13:00 / 13:05 / 13:10 / 13:15 / 13:20 / 13:25 哪個進場最穩？
  User 觀察: 13:00 附近有一波殺盤洗盤、13:20 才比較安全。

設計:
  - 期間: 2026-05-19 → 2026-06-03 (~12 交易日)
  - 樣本: 所有 confirmed trigger (Ch5-3 / T1 / T2)、不限 top N
  - 對比 6 個進場時點:
      13:00 / 13:05 / 13:10 / 13:15 / 13:20 / 13:25
      進場價 = 該時點 5K 棒的 close (或最近可取得的 close)
  - 出場: 統一隔日 9:00 開盤 (策略 D)
  - 手續費: -0.6%

  「尾盤洗盤」假說:
      若 13:00-13:10 平均報酬 < 13:15-13:25 → 假說成立

Usage:
    python scripts/zhuli/phase3_v9_closing_window_compare.py
    python scripts/zhuli/phase3_v9_closing_window_compare.py --no-report
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
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common.clients.finmind_client import get_client

from zhuli.db import get_conn, MAIN_DB
from zhuli.intraday_stage_helper import StageTrigger, _get_ma10, _DB as _HELPER_DB  # noqa

_DB = MAIN_DB
_TMP = Path("/tmp")
_CACHE_DIR = _TMP / "finmind_kbar_cache"
_CACHE_DIR.mkdir(exist_ok=True)

# 手續費 (買 + 賣 + 證交稅) 約 0.6%
FEE_PCT = 0.6

# 6 個尾盤進場時點
CLOSING_WINDOWS = ["13:00", "13:05", "13:10", "13:15", "13:20", "13:25"]

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


def get_close_at_or_after(k5: pd.DataFrame, target_hhmm: str) -> tuple[Optional[float], Optional[str]]:
    """取 >= target_hhmm 的第一根 5K close，回傳 (price, actual_hhmm)。"""
    if k5.empty:
        return None, None
    for i, ts in enumerate(k5.index):
        t = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)[11:16]
        if t >= target_hhmm:
            return float(k5.iloc[i]["close"]), t
    return None, None


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


# ── 主計算：6 個時點 ──────────────────────────────────────────────────────────

def compute_six_windows(
    trigger: dict,
    k5_full: pd.DataFrame,
    exit_date: str,
) -> Optional[dict]:
    """
    對一個 trigger 計算 6 個尾盤時點的報酬。
    回傳 record dict，失敗回傳 None。
    """
    ticker = trigger["ticker"]

    exit_price = get_open_price(ticker, exit_date)
    if exit_price is None:
        return None

    def net_ret(ep: float) -> float:
        return round((exit_price / ep - 1) * 100 - FEE_PCT, 3)

    rec: dict = {
        "entry_date":    trigger["entry_date"],
        "exit_date":     exit_date,
        "ticker":        ticker,
        "layer":         trigger["layer"],
        "market_regime": trigger["market_regime"],
        "trigger_time":  trigger["trigger_time"],
        "trigger_price": trigger["trigger_price"],
        "exit_price":    round(exit_price, 2),
    }

    any_valid = False
    for t in CLOSING_WINDOWS:
        key = t.replace(":", "")  # "1300", "1305", ...
        # 取 <= t 的最後一根；若無則取 >= t 的第一根
        price, actual_t = get_close_at_or_before(k5_full, t)
        if price is None:
            price, actual_t = get_close_at_or_after(k5_full, t)
        if price is None:
            rec[f"t{key}_price"] = None
            rec[f"t{key}_time"]  = None
            rec[f"t{key}_net"]   = None
            rec[f"t{key}_win"]   = None
        else:
            net = net_ret(price)
            rec[f"t{key}_price"] = round(price, 2)
            rec[f"t{key}_time"]  = actual_t
            rec[f"t{key}_net"]   = net
            rec[f"t{key}_win"]   = net > 0
            any_valid = True

    if not any_valid:
        return None
    return rec


# ── 主 Backtest ───────────────────────────────────────────────────────────────

def run_v9_backtest() -> list[dict]:
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

            rec = compute_six_windows(trigger, k5_full, exit_date)
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


def _pct(v, fmt=".2f") -> str:
    if v is None:
        return "—"
    return f"{v:+{fmt}}%"


# ── 報告輸出 ──────────────────────────────────────────────────────────────────

def print_summary(records: list[dict]) -> str:
    lines = []

    def _h(t):
        lines.append(f"\n{'='*70}")
        lines.append(f"  {t}")
        lines.append(f"{'='*70}")

    _h("Phase 3 v9 — 尾盤 13:00-13:25 各時點進場 Backtest (5/19-6/3)")
    lines.append(f"  出場: 隔日 9:00 開盤 / Fee: -{FEE_PCT}% / 總 trigger: {len(records)}")

    # ── 主表 ─────────────────────────────────────────────────────────────────
    _h("1. 六時點整體比較")
    lines.append(f"  {'進場時點':<12} {'樣本':>5} {'Win%':>7} {'平均報酬':>10} {'中位數':>9} {'累計':>9} {'Max':>8} {'Min':>8}")
    lines.append(f"  {'-'*75}")

    window_stats: dict[str, dict] = {}
    for t in CLOSING_WINDOWS:
        key = t.replace(":", "")
        vals = [r[f"t{key}_net"] for r in records if r.get(f"t{key}_net") is not None]
        st = _stats(vals)
        window_stats[t] = st
        wr   = f"{st['win_rate']:.1f}%" if st.get("win_rate") is not None else "—"
        avg  = _pct(st.get("avg"))
        med  = _pct(st.get("median"))
        tot  = _pct(st.get("total"))
        mx   = _pct(st.get("max"))
        mn   = _pct(st.get("min"))
        lines.append(f"  {t:<12} {st['n']:>5} {wr:>7} {avg:>10} {med:>9} {tot:>9} {mx:>8} {mn:>8}")

    # 找最佳時點
    best_t = max(CLOSING_WINDOWS, key=lambda t: window_stats[t].get("win_rate") or 0)
    best_avg_t = max(CLOSING_WINDOWS, key=lambda t: window_stats[t].get("avg") or -99)
    lines.append(f"\n  ★ Win rate 最高: {best_t} ({window_stats[best_t].get('win_rate'):.1f}%)")
    lines.append(f"  ★ 平均報酬最高: {best_avg_t} (avg {window_stats[best_avg_t].get('avg'):+.3f}%)")

    # ── 13:00 vs 13:20 對比 ───────────────────────────────────────────────────
    _h("2. 13:00 vs 13:20 直接對比")
    t1300 = window_stats["13:00"]
    t1320 = window_stats["13:20"]
    d_wr  = (t1320.get("win_rate") or 0) - (t1300.get("win_rate") or 0)
    d_avg = (t1320.get("avg") or 0) - (t1300.get("avg") or 0)
    lines.append(f"  13:00  Win={t1300.get('win_rate'):.1f}%  avg={t1300.get('avg'):+.3f}%  "
                 f"median={t1300.get('median'):+.3f}%")
    lines.append(f"  13:20  Win={t1320.get('win_rate'):.1f}%  avg={t1320.get('avg'):+.3f}%  "
                 f"median={t1320.get('median'):+.3f}%")
    lines.append(f"  差距   Win {d_wr:+.1f}%pt  avg {d_avg:+.3f}pp")

    if d_wr > 5 and d_avg > 0.1:
        verdict_1320 = "✅ 13:20 明顯優於 13:00 (User 直覺正確)"
    elif d_wr > 3:
        verdict_1320 = "⚠️ 13:20 Win rate 略高，但差距不大"
    elif d_wr < -3:
        verdict_1320 = "❌ 13:00 反而優於 13:20 (User 直覺錯)"
    else:
        verdict_1320 = "⚪ 差異不顯著 (樣本量小，需更多資料)"
    lines.append(f"  結論: {verdict_1320}")

    # ── 尾盤洗盤假說驗證 ────────────────────────────────────────────────────
    _h("3. 「尾盤洗盤」假說驗證")
    lines.append("  假說: 13:00-13:10 平均報酬 < 13:15-13:25")
    lines.append("")

    early_nets: list[float] = []
    late_nets:  list[float] = []

    for t in ["13:00", "13:05", "13:10"]:
        key = t.replace(":", "")
        early_nets += [r[f"t{key}_net"] for r in records if r.get(f"t{key}_net") is not None]
    for t in ["13:15", "13:20", "13:25"]:
        key = t.replace(":", "")
        late_nets += [r[f"t{key}_net"] for r in records if r.get(f"t{key}_net") is not None]

    st_early = _stats(early_nets)
    st_late  = _stats(late_nets)

    lines.append(f"  早段 (13:00-13:10): n={st_early['n']}  "
                 f"Win={st_early.get('win_rate'):.1f}%  "
                 f"avg={st_early.get('avg'):+.3f}%  "
                 f"median={st_early.get('median'):+.3f}%")
    lines.append(f"  晚段 (13:15-13:25): n={st_late['n']}  "
                 f"Win={st_late.get('win_rate'):.1f}%  "
                 f"avg={st_late.get('avg'):+.3f}%  "
                 f"median={st_late.get('median'):+.3f}%")

    avg_gap = (st_late.get("avg") or 0) - (st_early.get("avg") or 0)
    wr_gap  = (st_late.get("win_rate") or 0) - (st_early.get("win_rate") or 0)
    lines.append(f"  晚段 vs 早段: avg +{avg_gap:+.3f}pp  Win {wr_gap:+.1f}%pt")

    if avg_gap > 0.1 and wr_gap > 3:
        verdict_wash = "✅ 尾盤洗盤規律存在 — 13:00-13:10 明顯弱於 13:15-13:25"
    elif avg_gap > 0:
        verdict_wash = "⚠️ 輕微規律 — 晚段略優，但差距不顯著"
    elif avg_gap < -0.1:
        verdict_wash = "❌ 規律不存在 — 早段反而更好"
    else:
        verdict_wash = "⚪ 無明顯差異"
    lines.append(f"  → {verdict_wash}")

    # ── 逐時點詳細分析 ─────────────────────────────────────────────────────
    _h("4. 逐時點詳細分析 (趨勢)")
    lines.append(f"  {'時點':<8} {'Win%':>7} {'Avg':>9} {'Median':>9} {'Std':>8}")
    lines.append(f"  {'-'*45}")
    for t in CLOSING_WINDOWS:
        key = t.replace(":", "")
        vals = [r[f"t{key}_net"] for r in records if r.get(f"t{key}_net") is not None]
        st = window_stats[t]
        if not vals:
            lines.append(f"  {t:<8} {'—':>7} {'—':>9} {'—':>9} {'—':>8}")
            continue
        n = len(vals)
        variance = sum((v - (st.get("avg") or 0)) ** 2 for v in vals) / n
        std = variance ** 0.5
        wr  = f"{st.get('win_rate'):.1f}%"
        avg = f"{st.get('avg'):+.3f}%"
        med = f"{st.get('median'):+.3f}%"
        marker = " ← 最佳" if t == best_t else ""
        lines.append(f"  {t:<8} {wr:>7} {avg:>9} {med:>9} {std:>7.3f}%{marker}")

    # ── Regime 對比 ────────────────────────────────────────────────────────
    _h("5. 大盤 Regime 各時點 Win%")
    header = f"  {'Regime':<10}"
    for t in CLOSING_WINDOWS:
        header += f" {t:>8}"
    lines.append(header + "  (Win%)")
    lines.append(f"  {'-'*75}")

    for regime in ("strong", "normal", "weak"):
        rr = [r for r in records if r["market_regime"] == regime]
        if not rr:
            continue
        row = f"  {_REGIME_EMOJI.get(regime, regime):<10}"
        for t in CLOSING_WINDOWS:
            key = t.replace(":", "")
            vals = [r[f"t{key}_net"] for r in rr if r.get(f"t{key}_net") is not None]
            if vals:
                wr = sum(1 for v in vals if v > 0) / len(vals) * 100
                row += f" {wr:>7.1f}%"
            else:
                row += f" {'—':>8}"
        lines.append(row)

    # ── 每日分組 ──────────────────────────────────────────────────────────
    _h("6. 每日分組 (各時點平均報酬)")
    header = f"  {'日期':<12} {'N':>3}"
    for t in CLOSING_WINDOWS:
        header += f" {t:>8}"
    lines.append(header)
    lines.append(f"  {'-'*80}")

    for d in sorted(set(r["entry_date"] for r in records)):
        day_recs = [r for r in records if r["entry_date"] == d]
        row = f"  {d:<12} {len(day_recs):>3}"
        for t in CLOSING_WINDOWS:
            key = t.replace(":", "")
            vals = [r[f"t{key}_net"] for r in day_recs if r.get(f"t{key}_net") is not None]
            if vals:
                avg = sum(vals) / len(vals)
                row += f" {avg:>+7.2f}%"
            else:
                row += f" {'—':>8}"
        lines.append(row)

    # ── 結論 ──────────────────────────────────────────────────────────────
    _h("7. 結論與建議")
    lines.append(f"  最佳進場時點 (Win rate): {best_t}  ({window_stats[best_t].get('win_rate'):.1f}%)")
    lines.append(f"  最佳進場時點 (Avg 報酬): {best_avg_t}  (avg {window_stats[best_avg_t].get('avg'):+.3f}%)")
    lines.append(f"  13:00 vs 13:20: {verdict_1320}")
    lines.append(f"  尾盤洗盤假說: {verdict_wash}")
    lines.append("")
    lines.append("  Monitor 建議:")
    if "13:20" in best_t or "13:25" in best_t or (d_wr > 3 and d_avg > 0):
        lines.append("  → 將 confirmed 燈推遲到 13:20 才亮 (跳過 13:00-13:15 洗盤段)")
        lines.append("  → 或 13:00-13:15 加 warning「洗盤高風險、等 13:20+」")
    elif "13:00" == best_t:
        lines.append("  → 13:00 即最佳，無需延遲進場")
    else:
        lines.append(f"  → 最佳在 {best_t}，可考慮 monitor 延遲到此時點")

    text = "\n".join(lines)
    print(text)
    return text


def write_report(text: str, records: list[dict]) -> Path:
    report_dir = _REPO / "docs" / "主力大課程" / "strategies"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "phase3_v9_closing_window_5_19_to_6_3.md"

    # 計算 window stats 用於 markdown 表
    window_stats: dict[str, dict] = {}
    for t in CLOSING_WINDOWS:
        key = t.replace(":", "")
        vals = [r[f"t{key}_net"] for r in records if r.get(f"t{key}_net") is not None]
        window_stats[t] = _stats(vals)

    detail_rows = [
        "# Phase 3 v9 — 尾盤 13:00-13:25 各時點進場 Backtest (5/19-6/3)",
        "",
        "**研究問題**: 13:00 / 13:05 / 13:10 / 13:15 / 13:20 / 13:25 哪個進場最穩？",
        "**User 觀察**: 13:00 附近有一波殺盤洗盤、13:20 才比較安全。",
        "",
        "## 六時點整體比較",
        "",
        "| 進場時點 | 樣本 | Win% | 平均淨報酬 | 中位數 | 累計 |",
        "|----------|------|------|-----------|--------|------|",
    ]

    for t in CLOSING_WINDOWS:
        st = window_stats[t]
        wr  = f"{st['win_rate']:.1f}%" if st.get("win_rate") is not None else "—"
        avg = f"{st['avg']:+.3f}%" if st.get("avg") is not None else "—"
        med = f"{st['median']:+.3f}%" if st.get("median") is not None else "—"
        tot = f"{st['total']:+.2f}%" if st.get("total") is not None else "—"
        detail_rows.append(f"| {t} | {st['n']} | {wr} | {avg} | {med} | {tot} |")

    detail_rows += [
        "",
        "## 執行摘要",
        "",
        "```",
        text,
        "```",
        "",
        "## 詳細清單",
        "",
    ]

    # 建立詳細清單 header
    header_cols = "| 日期 | Ticker | Layer | Regime | Trig |"
    for t in CLOSING_WINDOWS:
        header_cols += f" {t} |"
    detail_rows.append(header_cols)
    sep_cols = "|------|--------|-------|--------|------|"
    for t in CLOSING_WINDOWS:
        sep_cols += "-------|"
    detail_rows.append(sep_cols)

    for r in sorted(records, key=lambda x: (x["entry_date"], x["ticker"])):
        row = (f"| {r['entry_date']} | {r['ticker']} | {r['layer']} "
               f"| {_REGIME_EMOJI.get(r['market_regime'], r['market_regime'])} "
               f"| {r['trigger_time']} |")
        for t in CLOSING_WINDOWS:
            key = t.replace(":", "")
            net = r.get(f"t{key}_net")
            win = r.get(f"t{key}_win")
            if net is None:
                row += " — |"
            else:
                emoji = "✅" if win else "❌"
                row += f" {emoji}{net:+.2f}% |"
        detail_rows.append(row)

    detail_rows += [
        "",
        "---",
        "",
        "_自動產出 @ 2026-06-04 (Phase 3 v9 尾盤 13:00-13:25 時點比較)_",
    ]

    report_path.write_text("\n".join(detail_rows), encoding="utf-8")
    print(f"\n  報告寫入: {report_path}")
    return report_path


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Phase 3 v9 尾盤 13:00-13:25 時點比較 backtest")
    p.add_argument("--no-report", action="store_true", default=False, help="不寫報告檔")
    args = p.parse_args()

    print("Phase 3 v9 — 尾盤 13:00-13:25 各時點進場 Backtest 啟動")
    print(f"期間: {TRADING_DATES_FULL[0]} → {TRADING_DATES_FULL[-1]}")
    print(f"測試時點: {' / '.join(CLOSING_WINDOWS)}")
    print(f"出場: 隔日 9:00 開盤 / Fee: -{FEE_PCT}%")
    print(f"樣本: 全部 confirmed trigger (Ch5-3 / T1 / T2)")
    print()

    records = run_v9_backtest()
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
