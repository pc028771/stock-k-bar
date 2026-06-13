"""Phase 3 v11 — Closing_check 移除「反彈確認」改 4 條件 Backtest

研究問題:
  v10 發現 cond #3「反彈確認」(2 紅K) 太嚴、80% 樣本 fail、但 fail 標的仍 Win 77-83%。
  v11: 直接移除 #3、改 4 條件、看新分組的 Win rate 是否更穩定。

4 個條件 (v11):
  1. structure_hold:   close > MA10 (結構守住)
  2. kill_test_passed: 12:00 後有殺盤考驗 (原 #2)
  3. volume_calm:      量縮 (非爆量) (原 #4)
  4. not_chasing_high: 距日高 ≥ 1.5% (未追高) (原 #5)

新 level 分組:
  4/4 全 pass → overheated (類 5/5、預期 Win 40-60%、不進)
  3/4 pass    → confirmed ⭐ (預期 Win 80%+、可進)
  2/4 pass    → watch (預期 Win 60-70%、謹慎)
  <2/4        → skip (不進)

對比 v10 (5 條件) vs v11 (4 條件) 各 bucket 的 Win rate 與樣本量分佈。

設計:
  - 期間: 2026-05-19 → 2026-06-03
  - 樣本: 所有 confirmed trigger、不限 top N
  - 進場: 13:00 收盤 / 出場: 隔日 9:00 開盤
  - 手續費: -0.6%

Usage:
    python scripts/zhuli/phase3_v11_closing_4cond_backtest.py
    python scripts/zhuli/phase3_v11_closing_4cond_backtest.py --no-report
"""
from __future__ import annotations

from zhuli.db import get_conn, MAIN_DB

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

_REPO = Path(__file__).parent.parent.parent
_SYS = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_REPO), str(_REPO / "scripts"), str(_SYS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.intraday_stage_helper import StageTrigger, _get_ma10, _DB as _HELPER_DB  # noqa

_DB = MAIN_DB
_TMP = Path("/tmp")
_CACHE_DIR = _TMP / "finmind_kbar_cache"
_CACHE_DIR.mkdir(exist_ok=True)

FEE_PCT = 0.6

TRADING_DATES_FULL = [
    "2026-05-19", "2026-05-20", "2026-05-21", "2026-05-22",
    "2026-05-25", "2026-05-26", "2026-05-27", "2026-05-28", "2026-05-29",
    "2026-06-01", "2026-06-02", "2026-06-03",
]

_REGIME_EMOJI = {"strong": "🟢強", "weak": "🔴弱", "normal": "⚪平"}

# v11 只有 4 條件 (移除 rebound_confirmed)
COND_KEYS_V11 = [
    "structure_hold",
    "kill_test_passed",
    "volume_calm",
    "not_chasing_high",
]
COND_LABELS_V11 = [
    "#1 結構守住 (close>MA10)",
    "#2 殺盤考驗過",
    "#3 量縮 (原 #4)",
    "#4 未追高 (原 #5)",
]

# v10 原 5 條件 (用於對比)
COND_KEYS_V10 = [
    "structure_hold",
    "kill_test_passed",
    "rebound_confirmed",
    "volume_calm",
    "not_chasing_high",
]


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


# ── v11 Closing_check (4 條件，移除 rebound_confirmed) ───────────────────────

def compute_v11_scores(ticker: str, k5_full: pd.DataFrame, ma10: float) -> dict:
    """直接從 5K 資料計算 v11 4 條件，不依賴 check_closing_panel (因為原函式有 5 條件)。

    Returns:
        {
            'scores': {structure_hold, kill_test_passed, volume_calm, not_chasing_high},
            'pass_count_v11': int (0-4),
            'level_v11': 'overheated'|'confirmed'|'watch'|'skip',
            'rebound_confirmed': bool  (保留 v10 #3、用於對比分析)
            'pass_count_v10': int (0-5, 原 v10 分數)
        }
    """
    k5_1305 = k5_full[k5_full.index.strftime("%H:%M") <= "13:05"]
    if k5_1305.empty or len(k5_1305) < 2:
        return {
            "scores": {k: False for k in COND_KEYS_V11},
            "pass_count_v11": 0,
            "level_v11": "skip",
            "rebound_confirmed": False,
            "pass_count_v10": 0,
        }

    current_close = float(k5_1305["close"].iloc[-1])
    day_high = float(k5_1305["high"].max())

    # ma10 fallback
    if ma10 is None or ma10 <= 0:
        ma10_raw = k5_1305["close"].rolling(10, min_periods=3).mean()
        ma10 = float(ma10_raw.iloc[-1]) if not ma10_raw.empty else 0.0

    ma5_raw = k5_1305["close"].rolling(5, min_periods=3).mean()
    ma5 = float(ma5_raw.iloc[-1]) if not ma5_raw.empty else 0.0

    # cond 1: 結構守住
    cond1 = (ma10 > 0 and current_close > ma10)

    # cond 2: 殺盤考驗過
    afternoon_k5 = k5_1305[k5_1305.index.strftime("%H:%M") >= "12:00"]
    morning_k5 = k5_1305[k5_1305.index.strftime("%H:%M") < "12:00"]
    morning_high = float(morning_k5["high"].max()) if not morning_k5.empty else day_high
    after_12_low = float(afternoon_k5["low"].min()) if not afternoon_k5.empty else current_close
    kill_by_morning_high = (after_12_low < morning_high * 0.98)
    kill_by_ma5 = (ma5 > 0 and after_12_low < ma5 * 0.99)
    cond2 = kill_by_morning_high or kill_by_ma5

    # (v10 cond3: 反彈確認 2 紅K — 保留以對比)
    after_13_k5 = k5_1305[k5_1305.index.strftime("%H:%M") >= "13:00"]
    rebound_confirmed = False
    if len(after_13_k5) >= 2:
        last2 = after_13_k5.tail(2)
        rebound_confirmed = bool((last2["close"] > last2["open"]).all())

    # cond 3 (原 #4): 量縮
    morning_k5_alt = k5_1305[k5_1305.index.strftime("%H:%M") < "13:00"]
    n_after_13 = len(after_13_k5)
    after_13_vol = float(after_13_k5["volume"].sum()) if not after_13_k5.empty else 0.0
    afternoon_per_bar = after_13_vol / max(1, n_after_13)
    if not morning_k5_alt.empty:
        morning_per_bar = float(morning_k5_alt["volume"].mean())
        cond3 = afternoon_per_bar < morning_per_bar * 1.2
    else:
        cond3 = True

    # cond 4 (原 #5): 未追高
    dist_below_high_pct = (day_high - current_close) / day_high * 100 if day_high > 0 else 99
    cond4 = dist_below_high_pct >= 1.5

    scores = {
        "structure_hold":    cond1,
        "kill_test_passed":  cond2,
        "volume_calm":       cond3,
        "not_chasing_high":  cond4,
    }
    pass_count_v11 = sum(scores.values())

    # v10 pass count (含 rebound_confirmed)
    pass_count_v10 = pass_count_v11 + int(rebound_confirmed)
    if not cond1 and not cond2 and not cond3 and not cond4 and not rebound_confirmed:
        pass_count_v10 = 0

    # v11 level
    if pass_count_v11 == 4:
        level_v11 = "overheated"
    elif pass_count_v11 == 3:
        level_v11 = "confirmed"
    elif pass_count_v11 == 2:
        level_v11 = "watch"
    else:
        level_v11 = "skip"

    return {
        "scores":            scores,
        "pass_count_v11":    pass_count_v11,
        "level_v11":         level_v11,
        "rebound_confirmed": rebound_confirmed,
        "pass_count_v10":    pass_count_v10,
    }


# ── 主掃描 ────────────────────────────────────────────────────────────────────

def scan_v11_all(
    engine: StageTrigger,
    entry_date: str,
    watchlist: list[str],
    regime: str,
) -> list[dict]:
    results = []

    for ticker in watchlist:
        k5_full = fetch_finmind_kbar_5m(ticker, entry_date)
        if k5_full.empty:
            continue

        prev_levels = get_prev_levels(ticker, entry_date)
        prev_close = prev_levels.get("prev_close", 0.0)
        if not prev_close:
            continue

        ma10 = _get_ma10(ticker, entry_date)

        k5_1300 = k5_full[k5_full.index.strftime("%H:%M") <= "13:00"]
        if k5_1300.empty:
            continue
        entry_price_1300 = float(k5_1300.iloc[-1]["close"])
        entry_time_str = k5_1300.index[-1].strftime("%H:%M")

        v11_r = compute_v11_scores(ticker, k5_full, ma10)

        next_date = next_trading_day(entry_date, TRADING_DATES_FULL)
        if not next_date:
            continue
        exit_price = get_open_price_next_day(ticker, next_date)
        if exit_price is None or not entry_price_1300:
            continue

        raw_ret_pct = (exit_price / entry_price_1300 - 1) * 100
        net_ret_pct = round(raw_ret_pct - FEE_PCT, 3)
        win = net_ret_pct > 0

        rec = {
            "entry_date":        entry_date,
            "ticker":            ticker,
            "entry_price":       entry_price_1300,
            "entry_time":        entry_time_str,
            "exit_date":         next_date,
            "exit_price":        exit_price,
            "raw_ret_pct":       round(raw_ret_pct, 3),
            "net_ret_pct":       net_ret_pct,
            "win":               win,
            "pass_count_v11":    v11_r["pass_count_v11"],
            "level_v11":         v11_r["level_v11"],
            "pass_count_v10":    v11_r["pass_count_v10"],
            "scores":            v11_r["scores"],
            "rebound_confirmed": v11_r["rebound_confirmed"],
            "market_regime":     regime,
        }
        results.append(rec)

    return results


# ── 統計函式 ──────────────────────────────────────────────────────────────────

def calc_stats(records: list[dict]) -> dict:
    if not records:
        return {"n": 0, "win_rate": None, "avg_ret": None, "median_ret": None,
                "avg_win": None, "avg_loss": None}
    n = len(records)
    rets = [r["net_ret_pct"] for r in records if r["net_ret_pct"] is not None]
    wins = [r for r in records if r.get("win")]
    losses = [r for r in records if not r.get("win")]
    win_rate = len(wins) / n * 100 if n > 0 else 0
    avg_ret = sum(rets) / len(rets) if rets else 0
    sorted_rets = sorted(rets)
    median_ret = sorted_rets[len(sorted_rets) // 2] if sorted_rets else 0
    avg_win = sum(r["net_ret_pct"] for r in wins) / len(wins) if wins else 0
    avg_loss = sum(r["net_ret_pct"] for r in losses) / len(losses) if losses else 0
    return {
        "n":          n,
        "win_rate":   round(win_rate, 1),
        "avg_ret":    round(avg_ret, 3),
        "median_ret": round(median_ret, 3),
        "avg_win":    round(avg_win, 3),
        "avg_loss":   round(avg_loss, 3),
    }


def _win_emoji(win_rate: Optional[float]) -> str:
    if win_rate is None:
        return "—"
    if win_rate >= 80:
        return f"🟢{win_rate:.0f}%"
    if win_rate >= 65:
        return f"🟡{win_rate:.0f}%"
    return f"🔴{win_rate:.0f}%"


# ── 主 Backtest ───────────────────────────────────────────────────────────────

def run_v11_backtest() -> dict:
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

        regime = engine._detect_market_regime(next_date, db_path=_DB)
        print(f"[{scan_date} → {next_date}] watchlist={len(watchlist)} "
              f"regime={_REGIME_EMOJI.get(regime, regime)}")

        day_records = scan_v11_all(engine, next_date, watchlist, regime)
        all_records.extend(day_records)
        print(f"  → {len(day_records)} 樣本")

    # 分組 v11
    buckets_v11: dict[str, list[dict]] = {
        "4/4 overheated": [],
        "3/4 confirmed":  [],
        "2/4 watch":      [],
        "<2/4 skip":      [],
    }
    for r in all_records:
        pc = r["pass_count_v11"]
        if pc == 4:
            buckets_v11["4/4 overheated"].append(r)
        elif pc == 3:
            buckets_v11["3/4 confirmed"].append(r)
        elif pc == 2:
            buckets_v11["2/4 watch"].append(r)
        else:
            buckets_v11["<2/4 skip"].append(r)

    # 對比 v10 分組 (依 pass_count_v10)
    buckets_v10_compare: dict[str, list[dict]] = {
        "5/5 v10": [],
        "4/5 v10": [],
        "3/5 v10": [],
        "<3/5 v10": [],
    }
    for r in all_records:
        pc10 = r["pass_count_v10"]
        if pc10 == 5:
            buckets_v10_compare["5/5 v10"].append(r)
        elif pc10 == 4:
            buckets_v10_compare["4/5 v10"].append(r)
        elif pc10 == 3:
            buckets_v10_compare["3/5 v10"].append(r)
        else:
            buckets_v10_compare["<3/5 v10"].append(r)

    # 細分: missing 哪個 v11 條件 (4/4 組合分析)
    missing_detail: dict[str, list[dict]] = {}
    for i, k in enumerate(COND_KEYS_V11):
        label = f"3/4 missing #{i+1}"
        missing_detail[label] = []
    for r in all_records:
        if r["pass_count_v11"] == 3:
            scores = r["scores"]
            missing = [k for k in COND_KEYS_V11 if not scores.get(k, False)]
            if len(missing) == 1:
                idx = COND_KEYS_V11.index(missing[0]) + 1
                key = f"3/4 missing #{idx}"
                if key in missing_detail:
                    missing_detail[key].append(r)

    return {
        "all":               all_records,
        "buckets_v11":       buckets_v11,
        "buckets_v10_compare": buckets_v10_compare,
        "missing_detail":    missing_detail,
    }


# ── 報告輸出 ──────────────────────────────────────────────────────────────────

def print_summary(results: dict) -> str:
    lines = []
    all_r = results["all"]
    bv11  = results["buckets_v11"]
    bv10  = results["buckets_v10_compare"]
    mdet  = results["missing_detail"]

    def _h(title: str):
        lines.append(f"\n{'='*70}")
        lines.append(f"  {title}")
        lines.append(f"{'='*70}")

    _h("Phase 3 v11 — Closing_check 4 條件 Backtest (5/19-6/3)")
    lines.append("  移除原 #3「反彈確認 2 紅K」→ 改 4 條件")
    lines.append("  進場: 13:00 收盤 / 出場: 隔日 9:00 開盤 / Fee: -0.6%")
    lines.append(f"  總樣本: {len(all_r)} 筆")

    # ── v11 主對比表 ──────────────────────────────────────────────────────────
    _h("v11 4 條件分組 (主表)")
    header = f"  {'組合':<25} {'樣本':>5} {'Win%':>10} {'平均淨報酬':>10} {'中位數':>8} {'AvgW':>7} {'AvgL':>7}"
    lines.append(header)
    lines.append("  " + "-" * 73)

    v11_order = ["4/4 overheated", "3/4 confirmed", "2/4 watch", "<2/4 skip"]
    v11_labels = {
        "4/4 overheated": "4/4 全 pass (過熱)",
        "3/4 confirmed":  "3/4 confirmed ⭐",
        "2/4 watch":      "2/4 watch",
        "<2/4 skip":      "<2/4 skip",
    }
    stats_v11: dict[str, dict] = {}
    for bk in v11_order:
        recs = bv11.get(bk, [])
        st = calc_stats(recs)
        stats_v11[bk] = st
        label = v11_labels[bk]
        avg_d   = f"{st['avg_ret']:+.2f}%"    if st['avg_ret']    is not None else "—"
        med_d   = f"{st['median_ret']:+.2f}%" if st['median_ret'] is not None else "—"
        avw_d   = f"{st['avg_win']:+.2f}%"   if st['avg_win']    is not None else "—"
        avl_d   = f"{st['avg_loss']:+.2f}%"  if st['avg_loss']   is not None else "—"
        lines.append(
            f"  {label:<25} {st['n']:>5} {_win_emoji(st['win_rate']):>10} "
            f"{avg_d:>10} {med_d:>8} {avw_d:>7} {avl_d:>7}"
        )

    # ── v10 對比表 ────────────────────────────────────────────────────────────
    _h("v10 5 條件對比 (同一批樣本重新算 v10 分數)")
    lines.append(header)
    lines.append("  " + "-" * 73)

    v10_order = ["5/5 v10", "4/5 v10", "3/5 v10", "<3/5 v10"]
    v10_labels = {
        "5/5 v10":  "5/5 全 pass (v10 過熱)",
        "4/5 v10":  "4/5 (v10 confirmed)",
        "3/5 v10":  "3/5 (v10 confirmed)",
        "<3/5 v10": "<3/5 (v10 skip)",
    }
    for bk in v10_order:
        recs = bv10.get(bk, [])
        st = calc_stats(recs)
        label = v10_labels[bk]
        avg_d  = f"{st['avg_ret']:+.2f}%"    if st['avg_ret']    is not None else "—"
        med_d  = f"{st['median_ret']:+.2f}%" if st['median_ret'] is not None else "—"
        avw_d  = f"{st['avg_win']:+.2f}%"   if st['avg_win']    is not None else "—"
        avl_d  = f"{st['avg_loss']:+.2f}%"  if st['avg_loss']   is not None else "—"
        lines.append(
            f"  {label:<25} {st['n']:>5} {_win_emoji(st['win_rate']):>10} "
            f"{avg_d:>10} {med_d:>8} {avw_d:>7} {avl_d:>7}"
        )

    # ── 3/4 confirmed 細分 (缺哪個條件) ─────────────────────────────────────
    _h("3/4 confirmed — 缺哪個條件最常見 / 成績如何")
    cond_display = {
        "3/4 missing #1": "#1 結構守住 缺",
        "3/4 missing #2": "#2 殺盤考驗 缺",
        "3/4 missing #3": "#3 量縮 缺",
        "3/4 missing #4": "#4 未追高 缺",
    }
    lines.append(f"  {'組合':<25} {'樣本':>5} {'Win%':>10} {'平均淨報酬':>10}")
    lines.append("  " + "-" * 53)
    for bk, label in cond_display.items():
        recs = mdet.get(bk, [])
        st = calc_stats(recs)
        avg_d = f"{st['avg_ret']:+.2f}%" if st['avg_ret'] is not None else "—"
        lines.append(
            f"  {label:<25} {st['n']:>5} {_win_emoji(st['win_rate']):>10} {avg_d:>10}"
        )

    # ── 分析結論 ──────────────────────────────────────────────────────────────
    _h("分析結論")

    st_conf = stats_v11.get("3/4 confirmed", {})
    st_oh   = stats_v11.get("4/4 overheated", {})
    st_watch = stats_v11.get("2/4 watch", {})
    st_skip  = stats_v11.get("<2/4 skip", {})

    # 對比 v10 3/5 vs v11 3/4
    st_v10_35 = calc_stats(bv10.get("3/5 v10", []))
    st_v10_45 = calc_stats(bv10.get("4/5 v10", []))

    lines.append("")
    lines.append(f"  [v11] 3/4 confirmed  Win={_win_emoji(st_conf['win_rate'])}  avg={st_conf.get('avg_ret', 0):+.2f}%  n={st_conf['n']}")
    lines.append(f"  [v11] 4/4 overheated Win={_win_emoji(st_oh['win_rate'])}  avg={st_oh.get('avg_ret', 0):+.2f}%  n={st_oh['n']}")
    lines.append(f"  [v11] 2/4 watch      Win={_win_emoji(st_watch['win_rate'])}  avg={st_watch.get('avg_ret', 0):+.2f}%  n={st_watch['n']}")
    lines.append(f"  [v11] <2/4 skip      Win={_win_emoji(st_skip['win_rate'])}  avg={st_skip.get('avg_ret', 0):+.2f}%  n={st_skip['n']}")
    lines.append("")
    lines.append(f"  [v10] 4/5 confirmed  Win={_win_emoji(st_v10_45['win_rate'])}  avg={st_v10_45.get('avg_ret', 0):+.2f}%  n={st_v10_45['n']}")
    lines.append(f"  [v10] 3/5 confirmed  Win={_win_emoji(st_v10_35['win_rate'])}  avg={st_v10_35.get('avg_ret', 0):+.2f}%  n={st_v10_35['n']}")
    lines.append("")

    # v11 vs v10 樣本量對比
    lines.append("  樣本分佈對比 (v10 vs v11 confirmed bucket):")
    n_v10_conf = (bv10.get("4/5 v10", []) + bv10.get("3/5 v10", []))
    n_v11_conf = bv11.get("3/4 confirmed", [])
    lines.append(f"    v10 confirmed (3+4/5): n={len(n_v10_conf)}")
    lines.append(f"    v11 confirmed (3/4):   n={len(n_v11_conf)}")

    # 是否比 v10 更好
    v10_wr = (calc_stats(n_v10_conf).get("win_rate") or 0)
    v11_wr = (st_conf.get("win_rate") or 0)
    if v11_wr >= v10_wr - 2 and len(n_v11_conf) > len(n_v10_conf) * 0.9:
        verdict = "✅ v11 4 條件樣本量更平均、Win rate 相當或更高 → 建議改 v11"
    elif v11_wr < 65:
        verdict = "❌ v11 3/4 confirmed Win rate 偏低 → 保留 v10 5 條件"
    else:
        verdict = "🟡 v11 vs v10 差異不大 → 視樣本量與使用者偏好決定"
    lines.append(f"\n  結論: {verdict}")
    lines.append(f"  (v10 confirmed avg Win={v10_wr:.1f}%  v11 confirmed Win={v11_wr:.1f}%)")

    text = "\n".join(lines)
    print(text)
    return text


def _cases_table(records: list[dict]) -> list[str]:
    rows = []
    rows.append("| 進場日 | Ticker | 進場 | 出場 | 淨報酬 | Win | v11-Pass | v10-Pass | 反彈K |")
    rows.append("|--------|--------|------|------|--------|-----|----------|----------|-------|")
    for r in records:
        win_tag = "✅" if r["win"] else "❌"
        reb = "✓" if r.get("rebound_confirmed") else "✗"
        rows.append(
            f"| {r['entry_date']} | {r['ticker']} | {r['entry_price']:.2f} "
            f"| {r['exit_price']:.2f} | {r['net_ret_pct']:+.2f}% | {win_tag} "
            f"| {r['pass_count_v11']}/4 | {r['pass_count_v10']}/5 | {reb} |"
        )
    return rows


def write_report(summary_text: str, results: dict) -> Path:
    report_dir = _REPO / "docs" / "主力大課程" / "strategies"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "phase3_v11_closing_4cond_5_19_to_6_3.md"

    all_r = results["all"]
    bv11  = results["buckets_v11"]
    mdet  = results["missing_detail"]

    lines = [
        "# Phase 3 v11 — Closing_check 移除反彈條件改 4 條件 Backtest (5/19-6/3)",
        "",
        "## 背景",
        "",
        "v10 發現 cond #3「反彈確認 2 紅K」太嚴：",
        "- 80% 樣本 fail 此條件",
        "- 但 fail 的標的 Win rate 仍高達 77-83%",
        "- <3/5 整體 Win 88% > confirmed (3-4/5) 的 82%",
        "",
        "v11 假設：移除 #3 後 4 條件分組樣本量更平均、Win rate 更穩定。",
        "",
        "## 4 條件定義",
        "",
        "| # | 條件 | 說明 |",
        "|---|------|------|",
        "| 1 | 結構守住 | close > MA10 |",
        "| 2 | 殺盤考驗過 | 12:00 後有觸低 (原 #2) |",
        "| 3 | 量縮 | per-bar 量 < 早盤 × 1.2 (原 #4) |",
        "| 4 | 未追高 | 距日高 ≥ 1.5% (原 #5) |",
        "",
        "## Level 定義",
        "",
        "| Pass | Level | 預期 Win |",
        "|------|-------|---------|",
        "| 4/4 | overheated | 40-60% (類 5/5) |",
        "| 3/4 | confirmed ⭐ | 80%+ |",
        "| 2/4 | watch | 60-70% |",
        "| <2/4 | skip | 不進 |",
        "",
        "## 執行摘要",
        "",
        "```",
        summary_text,
        "```",
        "",
        "## v11 各組合詳細案例",
        "",
    ]

    v11_order = ["4/4 overheated", "3/4 confirmed", "2/4 watch", "<2/4 skip"]
    v11_labels = {
        "4/4 overheated": "4/4 全 pass (過熱)",
        "3/4 confirmed":  "3/4 confirmed ⭐",
        "2/4 watch":      "2/4 watch",
        "<2/4 skip":      "<2/4 skip",
    }

    for bk in v11_order:
        recs = bv11.get(bk, [])
        label = v11_labels[bk]
        st = calc_stats(recs)
        lines.append(f"### {label}")
        lines.append("")
        if not recs:
            lines.append("n=0 無樣本")
            lines.append("")
            continue
        lines.append(f"- 樣本數: {st['n']}  Win%: {_win_emoji(st['win_rate'])}  "
                     f"平均淨報酬: {st['avg_ret']:+.2f}%  中位數: {st['median_ret']:+.2f}%")
        lines.append("")

        sorted_r = sorted(recs, key=lambda x: x["net_ret_pct"], reverse=True)
        tops = sorted_r[:min(5, len(sorted_r))]
        bots = sorted_r[-min(5, len(sorted_r)):]

        lines.append("**最佳 5 筆:**")
        lines.append("")
        lines.extend(_cases_table(tops))
        lines.append("")
        lines.append("**最差 5 筆:**")
        lines.append("")
        lines.extend(_cases_table(bots))
        lines.append("")

    # 3/4 缺條件細分
    lines.append("## 3/4 confirmed — 缺哪個條件細分")
    lines.append("")
    lines.append("| 缺少條件 | 樣本 | Win% | 平均報酬 |")
    lines.append("|----------|------|------|---------|")
    cond_display = {
        "3/4 missing #1": "#1 結構守住",
        "3/4 missing #2": "#2 殺盤考驗",
        "3/4 missing #3": "#3 量縮",
        "3/4 missing #4": "#4 未追高",
    }
    for bk, label in cond_display.items():
        recs = mdet.get(bk, [])
        st = calc_stats(recs)
        wr_disp = _win_emoji(st["win_rate"]) if st["n"] else "—"
        avg_disp = f"{st['avg_ret']:+.2f}%" if st["avg_ret"] is not None else "—"
        lines.append(f"| 缺 {label} | {st['n']} | {wr_disp} | {avg_disp} |")
    lines.append("")

    # v10 vs v11 cross table
    lines.append("## v10 vs v11 對比矩陣")
    lines.append("")
    lines.append("同一批樣本、重新按 v10 (5 條) 和 v11 (4 條) 分組比較：")
    lines.append("")
    lines.append("| 指標 | v10 confirmed (3+4/5) | v11 confirmed (3/4) |")
    lines.append("|------|----------------------|---------------------|")
    bv10 = results["buckets_v10_compare"]
    n_v10_conf = bv10.get("4/5 v10", []) + bv10.get("3/5 v10", [])
    n_v11_conf = bv11.get("3/4 confirmed", [])
    st_v10 = calc_stats(n_v10_conf)
    st_v11 = calc_stats(n_v11_conf)
    lines.append(f"| 樣本數 | {st_v10['n']} | {st_v11['n']} |")
    wr10 = _win_emoji(st_v10['win_rate'])
    wr11 = _win_emoji(st_v11['win_rate'])
    lines.append(f"| Win% | {wr10} | {wr11} |")
    avg10 = f"{st_v10['avg_ret']:+.2f}%" if st_v10['avg_ret'] is not None else "—"
    avg11 = f"{st_v11['avg_ret']:+.2f}%" if st_v11['avg_ret'] is not None else "—"
    lines.append(f"| 平均淨報酬 | {avg10} | {avg11} |")
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  報告寫入: {report_path}")
    return report_path


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Phase 3 v11 Closing_check 4 條件 backtest")
    p.add_argument("--no-report", action="store_true", default=False, help="不寫報告檔")
    args = p.parse_args()

    print("Phase 3 v11 — Closing_check 4 條件 Backtest 啟動")
    print(f"移除原 #3「反彈確認」→ 改 4 條件")
    print(f"期間: {TRADING_DATES_FULL[0]} → {TRADING_DATES_FULL[-1]}  (所有樣本、不限 top N)")
    print()

    results = run_v11_backtest()
    report_text = print_summary(results)

    if not args.no_report:
        write_report(report_text, results)


if __name__ == "__main__":
    main()
