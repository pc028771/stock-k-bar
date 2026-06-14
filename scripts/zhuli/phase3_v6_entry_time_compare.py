"""Phase 3 v6 — 進場時點配對對比 Backtest

驗證「9:15-9:30 拉高出貨 filter」效果：
同一個 confirmed trigger、比較不同進場時點 (9:20 ~ 13:00) 的報酬差異。

研究問題:
  1. 9:30 vs 9:20 進場：平均報酬差幾%？
  2. 9:15-9:30 拉高出貨時段 filter 是否值得保留？
  3. 最佳進場時點分佈？

設計:
  - 樣本: 全部 confirmed trigger (Ch5-3 / T1 / T2)，不限 top-N
  - 配對: 同一個 trigger，模擬多個進場時點
  - 出場: 隔日 9:00 開盤 (策略 D，v5 最佳 exit)
  - 手續費: -0.6%

時點清單: 9:20 / 9:25 / 9:30 / 9:35 / 9:45 / 10:00 / 11:00 / 13:00

Usage:
    python scripts/zhuli/phase3_v6_entry_time_compare.py
    python scripts/zhuli/phase3_v6_entry_time_compare.py --no-report
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

from zhuli.db import get_conn, MAIN_DB
from zhuli.intraday_stage_helper import StageTrigger, _get_ma10, _DB as _HELPER_DB  # noqa

_DB = MAIN_DB
_TMP = Path("/tmp")
_CACHE_DIR = _TMP / "finmind_kbar_cache"
_CACHE_DIR.mkdir(exist_ok=True)

# 手續費 (買 + 賣 + 證交稅) 約 0.6%
FEE_PCT = 0.6

# 進場時點清單 (HH:MM)
ENTRY_TIMES = ["09:20", "09:25", "09:30", "09:35", "09:45", "10:00", "11:00", "13:00"]

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


# ── FinMind 5K 抓取 ───────────────────────────────────────────────────────────

_finmind_calls = 0


def _rate_limit():
    global _finmind_calls
    _finmind_calls += 1
    if _finmind_calls % 100 == 0:
        time.sleep(1.0)
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
    """取隔日開盤價。"""
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


def get_close_at_time(k5: pd.DataFrame, target_time: str) -> Optional[float]:
    """取 ≤ target_time 最後一根的 close。"""
    if k5.empty:
        return None
    filtered = k5[k5.index.strftime("%H:%M") <= target_time]
    if filtered.empty:
        return None
    return float(filtered.iloc[-1]["close"])


def get_close_exactly_at(k5: pd.DataFrame, target_hhmm: str) -> Optional[float]:
    """取 target_hhmm 那根 5K 的 close（找 ≥ target 且最接近的那根）。
    例如 09:20 → 找 label=09:20 那根（09:20-09:25）的 close。
    """
    if k5.empty:
        return None
    # 找該時間點或之後最近的一根
    bar_times = k5.index.strftime("%H:%M").tolist()
    for i, t in enumerate(bar_times):
        if t >= target_hhmm:
            return float(k5.iloc[i]["close"])
    return None


# ── Trigger 偵測 ──────────────────────────────────────────────────────────────

def detect_triggers_for_day(
    engine: StageTrigger,
    scan_date: str,
    next_date: str,
    watchlist: list[str],
    regime: str,
) -> list[dict]:
    """對單日 watchlist 跑 trigger 偵測，回傳所有第一次觸發記錄。"""
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
                    "trigger_time": et, "trigger_price": ep,
                    "market_regime": regime,
                    "trigger_reason": r_ch53.get("reason", "")[:80],
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
                    "trigger_time": ts_str, "trigger_price": r.get("price", 0.0),
                    "market_regime": regime,
                    "trigger_reason": r.get("reason", "")[:80],
                }
                break

            # T2
            r = engine.check_trigger_2(ticker, k5, datetime.min)
            if r.get("triggered"):
                trigger_rec = {
                    "scan_date": scan_date, "entry_date": next_date,
                    "ticker": ticker, "layer": "T2",
                    "trigger_time": ts_str, "trigger_price": r.get("price", 0.0),
                    "market_regime": regime,
                    "trigger_reason": r.get("reason", "")[:80],
                }
                break

        if trigger_rec is not None and trigger_rec.get("trigger_price"):
            day_triggers.append(trigger_rec)

    return day_triggers


# ── 主計算：配對進場時點 ──────────────────────────────────────────────────────

def compute_entry_time_pairs(
    trigger: dict,
    k5_full: pd.DataFrame,
    next_date: str,
    exit_date: str,
) -> dict:
    """
    對一個 trigger，計算各進場時點的報酬。
    出場: 隔日 (exit_date) 9:00 開盤。
    """
    ticker = trigger["ticker"]
    trigger_time = trigger.get("trigger_time", "09:20")

    exit_price = get_open_price_next_day(ticker, exit_date)

    result = dict(trigger)
    result["exit_date"] = exit_date
    result["exit_price"] = exit_price

    for entry_t in ENTRY_TIMES:
        # 進場時點必須 >= trigger 時點 (不能比觸發時點更早進)
        if entry_t < trigger_time:
            result[f"entry_price_{entry_t}"] = None
            result[f"net_{entry_t}"] = None
            result[f"skip_reason_{entry_t}"] = f"trigger@{trigger_time} > entry_t"
            continue

        entry_price = get_close_exactly_at(k5_full, entry_t)
        result[f"entry_price_{entry_t}"] = entry_price

        if entry_price is None or exit_price is None:
            result[f"net_{entry_t}"] = None
            result[f"skip_reason_{entry_t}"] = "no_data"
            continue

        gross = (exit_price / entry_price - 1) * 100
        net = round(gross - FEE_PCT, 3)
        result[f"net_{entry_t}"] = net
        result[f"skip_reason_{entry_t}"] = ""

    return result


# ── 統計函式 ──────────────────────────────────────────────────────────────────

def _stats(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0, "win_rate": None, "avg_ret": None, "total_ret": None,
                "max_ret": None, "min_ret": None}
    n = len(vals)
    return {
        "n": n,
        "win_rate": round(sum(1 for v in vals if v > 0) / n * 100, 1),
        "avg_ret": round(sum(vals) / n, 3),
        "total_ret": round(sum(vals), 2),
        "max_ret": round(max(vals), 3),
        "min_ret": round(min(vals), 3),
    }


def _fmt_pct(v) -> str:
    if v is None:
        return "—"
    return f"{v:+.3f}%"


def _fmt_price(v) -> str:
    if v is None:
        return "—"
    return f"{v:.1f}"


# ── 主 Backtest ────────────────────────────────────────────────────────────────

def run_v6_backtest() -> list[dict]:
    engine = StageTrigger()
    dates = TRADING_DATES_FULL
    all_records: list[dict] = []

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

        exit_date = next_trading_day(next_date, dates)
        if not exit_date:
            print(f"[SKIP] {next_date} 沒有出場日")
            continue

        regime = engine._detect_market_regime(next_date, db_path=_DB)
        print(f"[{scan_date} → 進場:{next_date} → 出場:{exit_date}] "
              f"watchlist={len(watchlist)} regime={_REGIME_EMOJI.get(regime, regime)}")

        day_triggers = detect_triggers_for_day(
            engine, scan_date, next_date, watchlist, regime
        )
        print(f"  → {len(day_triggers)} triggers detected")

        for trigger in day_triggers:
            ticker = trigger["ticker"]
            k5_full = fetch_finmind_kbar_5m(ticker, next_date)
            if k5_full.empty:
                continue

            rec = compute_entry_time_pairs(trigger, k5_full, next_date, exit_date)
            all_records.append(rec)

    return all_records


# ── 報告輸出 ──────────────────────────────────────────────────────────────────

def write_report(records: list[dict], out_path: Path) -> None:
    lines = [
        "# Phase 3 v6 — 進場時點配對對比 Backtest",
        "",
        "> 期間: 2026-05-19 → 2026-06-03 (T+1 進場，出場=隔日 9:00 開盤)",
        "> 出場策略: 策略 D (隔日 9:00 開盤)，與 v5 最佳 exit 對齊",
        "> 手續費: -0.6%",
        "> 樣本: 全部 confirmed trigger (Ch5-3 / T1 / T2)，不限 top-N",
        "> 研究問題: 9:15-9:30 拉高出貨 filter 是否值得保留？",
        "",
    ]

    # ── 主對比表 (9:20 vs 9:30) ───────────────────────────────────────────────
    lines += [
        "## 1. 主對比: 9:20 vs 9:30 進場",
        "",
    ]

    vals_920 = [r.get("net_09:20") for r in records if r.get("net_09:20") is not None]
    vals_930 = [r.get("net_09:30") for r in records if r.get("net_09:30") is not None]
    st_920 = _stats(vals_920)
    st_930 = _stats(vals_930)

    def diff_str(a, b):
        if a is None or b is None:
            return "—"
        return f"{b - a:+.3f}pp"

    lines += [
        "| 進場時點 | 樣本 | Win% | 平均淨報酬 | 累計淨報酬 | 最大+ | 最大- |",
        "|---------|------|------|-----------|-----------|------|------|",
        f"| **9:20** | {st_920['n']} | {st_920['win_rate']}% | {_fmt_pct(st_920['avg_ret'])} | {_fmt_pct(st_920['total_ret'])} | {_fmt_pct(st_920['max_ret'])} | {_fmt_pct(st_920['min_ret'])} |",
        f"| **9:30** | {st_930['n']} | {st_930['win_rate']}% | {_fmt_pct(st_930['avg_ret'])} | {_fmt_pct(st_930['total_ret'])} | {_fmt_pct(st_930['max_ret'])} | {_fmt_pct(st_930['min_ret'])} |",
        f"| **Diff (9:30-9:20)** | — | {diff_str(st_920['win_rate'], st_930['win_rate'])} | {diff_str(st_920['avg_ret'], st_930['avg_ret'])} | {diff_str(st_920['total_ret'], st_930['total_ret'])} | — | — |",
        "",
    ]

    # ── 全時點分佈表 ──────────────────────────────────────────────────────────
    lines += [
        "## 2. 全時點分佈 (9:20 → 13:00)",
        "",
        "| 進場時點 | 樣本 | Win% | 平均淨報酬 | 累計 | 結論 |",
        "|---------|------|------|-----------|------|------|",
    ]

    base_avg = st_920.get("avg_ret")
    for et in ENTRY_TIMES:
        col = f"net_{et}"
        vals = [r.get(col) for r in records if r.get(col) is not None]
        st = _stats(vals)
        if st["n"] == 0:
            lines.append(f"| {et} | 0 | — | — | — | 無資料 |")
            continue

        # 相對基準 (9:20) 的改善
        if base_avg is not None and st["avg_ret"] is not None:
            delta = st["avg_ret"] - base_avg
            if et == "09:20":
                note = "(基準)"
            elif delta > 0.1:
                note = f"▲ +{delta:.3f}pp vs 9:20"
            elif delta < -0.1:
                note = f"▼ {delta:.3f}pp vs 9:20"
            else:
                note = f"≈ {delta:+.3f}pp vs 9:20"
        else:
            note = ""

        lines.append(
            f"| {et} | {st['n']} | {st['win_rate']}% | {_fmt_pct(st['avg_ret'])} | {_fmt_pct(st['total_ret'])} | {note} |"
        )
    lines.append("")

    # ── 每筆詳細對比 ──────────────────────────────────────────────────────────
    lines += [
        "## 3. 每筆詳細對比",
        "",
        "| 日期 | Ticker | Layer | Regime | trigger時點 | 9:20 entry | 9:30 entry | 隔日出場 | 9:20 報酬 | 9:30 報酬 | 差 (9:30-9:20) |",
        "|------|--------|-------|--------|------------|-----------|-----------|---------|----------|----------|--------------|",
    ]

    for r in sorted(records, key=lambda x: (x.get("entry_date", ""), x.get("ticker", ""))):
        ticker = r.get("ticker", "?")
        layer = r.get("layer", "?")
        regime = r.get("market_regime", "?")
        entry_date = r.get("entry_date", "?")
        trig_t = r.get("trigger_time", "?")
        p920 = r.get("entry_price_09:20")
        p930 = r.get("entry_price_09:30")
        exit_p = r.get("exit_price")
        n920 = r.get("net_09:20")
        n930 = r.get("net_09:30")

        diff = None
        if n920 is not None and n930 is not None:
            diff = round(n930 - n920, 3)

        diff_s = f"{diff:+.3f}pp" if diff is not None else "—"
        # 標注哪個更好
        if diff is not None:
            if diff > 0:
                diff_s += " 🟢"
            elif diff < 0:
                diff_s += " 🔴"

        lines.append(
            f"| {entry_date} | {ticker} | {layer} | {regime} | {trig_t} | "
            f"{_fmt_price(p920)} | {_fmt_price(p930)} | {_fmt_price(exit_p)} | "
            f"{_fmt_pct(n920)} | {_fmt_pct(n930)} | {diff_s} |"
        )
    lines.append("")

    # ── 反例分析 (9:20 反而比 9:30 好的日期) ────────────────────────────────
    lines += [
        "## 4. 反例分析 — 9:20 反而比 9:30 好",
        "",
        "9:30 報酬 < 9:20 報酬 的案例 (早進反而更好)：",
        "",
        "| 日期 | Ticker | Layer | 9:20 報酬 | 9:30 報酬 | 差距 | Regime | 可能原因 |",
        "|------|--------|-------|----------|----------|------|--------|---------|",
    ]

    reverse_cases = [
        r for r in records
        if r.get("net_09:20") is not None and r.get("net_09:30") is not None
        and r["net_09:30"] < r["net_09:20"]
    ]
    for r in sorted(reverse_cases, key=lambda x: (x.get("net_09:30", 0) - x.get("net_09:20", 0))):
        diff = round(r["net_09:30"] - r["net_09:20"], 3)
        regime = r.get("market_regime", "?")
        reason = "強勢開盤早進更好" if r.get("market_regime") == "strong" else "非強勢日"
        lines.append(
            f"| {r['entry_date']} | {r['ticker']} | {r['layer']} | "
            f"{_fmt_pct(r['net_09:20'])} | {_fmt_pct(r['net_09:30'])} | "
            f"{diff:+.3f}pp | {regime} | {reason} |"
        )
    if not reverse_cases:
        lines.append("_(無反例)_")
    lines.append("")

    # ── 大盤 Regime 對比 ─────────────────────────────────────────────────────
    lines += [
        "## 5. 大盤 Regime 對比",
        "",
        "| Regime | 樣本 | 9:20 Win% | 9:20 均報酬 | 9:30 Win% | 9:30 均報酬 | 9:30-9:20 差 |",
        "|--------|------|----------|------------|----------|------------|------------|",
    ]

    for regime in ("strong", "normal", "weak"):
        regime_recs = [r for r in records if r.get("market_regime") == regime]
        v920 = [r["net_09:20"] for r in regime_recs if r.get("net_09:20") is not None]
        v930 = [r["net_09:30"] for r in regime_recs if r.get("net_09:30") is not None]
        s920 = _stats(v920)
        s930 = _stats(v930)
        if s920["n"] == 0 and s930["n"] == 0:
            continue
        delta = None
        if s920.get("avg_ret") is not None and s930.get("avg_ret") is not None:
            delta = round(s930["avg_ret"] - s920["avg_ret"], 3)
        emoji = _REGIME_EMOJI.get(regime, regime)
        lines.append(
            f"| {emoji} | {s920['n']} | {s920.get('win_rate')}% | {_fmt_pct(s920.get('avg_ret'))} | "
            f"{s930.get('win_rate')}% | {_fmt_pct(s930.get('avg_ret'))} | "
            f"{f'{delta:+.3f}pp' if delta is not None else '—'} |"
        )
    lines.append("")

    # ── Layer 對比 ────────────────────────────────────────────────────────────
    lines += [
        "## 6. Layer 對比 (Ch5-3 / T1 / T2)",
        "",
        "| Layer | 樣本 | 9:20 Win% | 9:20 均報酬 | 9:30 Win% | 9:30 均報酬 | 9:30-9:20 差 |",
        "|-------|------|----------|------------|----------|------------|------------|",
    ]

    for layer in ("Ch5-3", "T1", "T2"):
        layer_recs = [r for r in records if r.get("layer") == layer]
        v920 = [r["net_09:20"] for r in layer_recs if r.get("net_09:20") is not None]
        v930 = [r["net_09:30"] for r in layer_recs if r.get("net_09:30") is not None]
        s920 = _stats(v920)
        s930 = _stats(v930)
        if s920["n"] == 0 and s930["n"] == 0:
            continue
        delta = None
        if s920.get("avg_ret") is not None and s930.get("avg_ret") is not None:
            delta = round(s930["avg_ret"] - s920["avg_ret"], 3)
        lines.append(
            f"| {layer} | {s920['n']} | {s920.get('win_rate')}% | {_fmt_pct(s920.get('avg_ret'))} | "
            f"{s930.get('win_rate')}% | {_fmt_pct(s930.get('avg_ret'))} | "
            f"{f'{delta:+.3f}pp' if delta is not None else '—'} |"
        )
    lines.append("")

    # ── 結論 ──────────────────────────────────────────────────────────────────
    # 計算結論依據
    delta_920_930 = None
    if st_920.get("avg_ret") is not None and st_930.get("avg_ret") is not None:
        delta_920_930 = round(st_930["avg_ret"] - st_920["avg_ret"], 3)

    # 找最佳時點
    time_stats = {}
    for et in ENTRY_TIMES:
        col = f"net_{et}"
        vals = [r.get(col) for r in records if r.get(col) is not None]
        time_stats[et] = _stats(vals)

    best_time = max(
        (et for et in ENTRY_TIMES if time_stats[et]["n"] > 0),
        key=lambda et: time_stats[et].get("avg_ret") or -999,
        default="?",
    )
    best_avg = time_stats.get(best_time, {}).get("avg_ret")

    filter_verdict = "值得保留" if (delta_920_930 is not None and delta_920_930 > 0) else "效果不明確"

    lines += [
        "## 7. 結論",
        "",
        f"**9:20 vs 9:30 進場差距**: {_fmt_pct(delta_920_930)} (正 = 9:30 較好)",
        "",
    ]

    if delta_920_930 is not None:
        if delta_920_930 > 0.3:
            lines.append(f"✅ **9:30 系統性優於 9:20**，平均多 {delta_920_930:.3f}pp。")
            lines.append("   → 9:15-9:30 拉高出貨 filter **值得保留**。")
        elif delta_920_930 > 0:
            lines.append(f"⚠️ **9:30 小幅優於 9:20** ({delta_920_930:.3f}pp)，差距不顯著。")
            lines.append("   → filter 有輕微正效果，可保留但非決定性因素。")
        else:
            lines.append(f"❌ **9:30 不優於 9:20** (差距 {delta_920_930:.3f}pp)。")
            lines.append("   → 9:15-9:30 filter 效果不明確，需更多樣本驗證。")
    lines.append("")

    lines += [
        f"**最佳進場時點**: {best_time} (平均淨報酬 {_fmt_pct(best_avg)})",
        "",
        f"**反例個數**: {len(reverse_cases)} 筆 9:20 > 9:30",
        "",
        "---",
        "",
        "_自動產出 @ 2026-06-04 (Phase 3 v6 進場時點對比)_",
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n→ 報告寫入: {out_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--no-report", action="store_true", help="不輸出報告檔案")
    args = p.parse_args()

    print("=== Phase 3 v6 — 進場時點配對對比 ===")
    print(f"期間: 2026-05-19 → 2026-06-03 ({len(TRADING_DATES_FULL)} 個掃描日)")
    print(f"出場: 隔日 9:00 開盤 (策略 D)")
    print(f"手續費: -{FEE_PCT}%")
    print(f"進場時點: {', '.join(ENTRY_TIMES)}")
    print()

    records = run_v6_backtest()
    print(f"\n→ 收集到 {len(records)} 個 trigger 記錄")

    # 快速摘要
    print("\n=== 快速摘要 (9:20 → 13:00) ===")
    print(f"{'時點':<10} {'樣本':>5} {'Win%':>7} {'平均淨':>10} {'累計':>10}")
    print("-" * 50)

    base_avg = None
    for et in ENTRY_TIMES:
        col = f"net_{et}"
        vals = [r.get(col) for r in records if r.get(col) is not None]
        st = _stats(vals)
        if st["n"] == 0:
            print(f"  {et:<8} {'—':>5}")
            continue
        wr = f"{st['win_rate']}%" if st.get("win_rate") is not None else "—"
        ar = f"{st['avg_ret']:+.3f}%" if st.get("avg_ret") is not None else "—"
        tr = f"{st['total_ret']:+.2f}%" if st.get("total_ret") is not None else "—"
        note = ""
        if et == "09:20":
            base_avg = st.get("avg_ret")
            note = " ← 基準"
        elif base_avg is not None and st.get("avg_ret") is not None:
            d = st["avg_ret"] - base_avg
            note = f" ({d:+.3f}pp)"
        print(f"  {et:<8} {st['n']:>5} {wr:>7} {ar:>10} {tr:>10}{note}")

    print()

    # 9:20 vs 9:30 摘要
    vals_920 = [r.get("net_09:20") for r in records if r.get("net_09:20") is not None]
    vals_930 = [r.get("net_09:30") for r in records if r.get("net_09:30") is not None]
    st_920 = _stats(vals_920)
    st_930 = _stats(vals_930)

    print("=== 主對比: 9:20 vs 9:30 ===")
    print(f"  9:20: n={st_920['n']} Win={st_920.get('win_rate')}% Avg={_fmt_pct(st_920.get('avg_ret'))}")
    print(f"  9:30: n={st_930['n']} Win={st_930.get('win_rate')}% Avg={_fmt_pct(st_930.get('avg_ret'))}")
    if st_920.get("avg_ret") is not None and st_930.get("avg_ret") is not None:
        delta = round(st_930["avg_ret"] - st_920["avg_ret"], 3)
        print(f"  Diff: {delta:+.3f}pp (正 = 9:30 較好)")
        if delta > 0.3:
            print("  → ✅ 9:30 系統性較優，filter 值得保留")
        elif delta > 0:
            print("  → ⚠️ 9:30 小幅優於 9:20，差距不顯著")
        else:
            print("  → ❌ 9:30 不優於 9:20")

    print()

    if not args.no_report:
        out_path = (
            _REPO / "docs" / "主力大課程" / "strategies"
            / "phase3_v6_entry_time_compare_5_19_to_6_3.md"
        )
        write_report(records, out_path)

    print("\n完成！")


if __name__ == "__main__":
    main()
