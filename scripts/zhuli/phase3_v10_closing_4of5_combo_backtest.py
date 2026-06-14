"""Phase 3 v10 — Closing_check 4/5 + 3/5 各組合細部 Backtest

研究問題:
  4/5 中缺哪個條件效果最好？3/5 中缺哪 2 條最可接受？

5 個條件:
  1. structure_hold:    close > MA10 (結構守住)
  2. kill_test_passed:  12:00 後有殺盤考驗
  3. rebound_confirmed: 13:00 後連續 2 根紅K
  4. volume_calm:       量縮 (非爆量)
  5. not_chasing_high:  距日高 ≥ 1.5% (未追高)

全部 buckets (5+5+1+10+1+1 = 共 18 個):
  5/5 全 pass
  4/5 missing #1 (結構未守)
  4/5 missing #2 (沒殺盤)
  4/5 missing #3 (沒紅K反彈)
  4/5 missing #4 (爆量)
  4/5 missing #5 (追高)
  4/5 整體
  3/5 missing #1#2 (結構+殺盤)
  3/5 missing #1#3 (結構+反彈)
  3/5 missing #1#4 (結構+量縮)
  3/5 missing #1#5 (結構+追高)
  3/5 missing #2#3 (殺盤+反彈)
  3/5 missing #2#4 (殺盤+量縮)
  3/5 missing #2#5 (殺盤+追高)
  3/5 missing #3#4 (反彈+量縮)
  3/5 missing #3#5 (反彈+追高)
  3/5 missing #4#5 (量縮+追高)
  3/5 整體
  <3/5 整體 (0-2 pass)

設計:
  - 期間: 2026-05-19 → 2026-06-03
  - 樣本: 所有 confirmed trigger、不限 top N
  - 進場: 13:00 收盤 / 出場: 隔日 9:00 開盤
  - 手續費: -0.6%

Usage:
    python scripts/zhuli/phase3_v10_closing_4of5_combo_backtest.py
    python scripts/zhuli/phase3_v10_closing_4of5_combo_backtest.py --no-report
"""
from __future__ import annotations

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

from zhuli.db import get_conn, MAIN_DB
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

# 5 個條件 key (與 scores dict 對應)
COND_KEYS = [
    "structure_hold",
    "kill_test_passed",
    "rebound_confirmed",
    "volume_calm",
    "not_chasing_high",
]
COND_LABELS = [
    "#1 結構守住 (close>MA10)",
    "#2 殺盤考驗過",
    "#3 反彈 2 紅K",
    "#4 量縮",
    "#5 未追高 (距日高≥1.5%)",
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


def _score_trigger(hit: dict) -> float:
    score = 0.0
    trigger_base = {
        "首攻": 30, "續攻": 20, "反彈": 25, "破底": -100,
        "Ch5-3": 30, "T1": 20, "T2": 25, "TC": -100,
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


# ── 主掃描 (不限 top N) ────────────────────────────────────────────────────────

def scan_closing_candidates_all(
    engine: StageTrigger,
    entry_date: str,
    watchlist: list[str],
    regime: str,
) -> list[dict]:
    """對 entry_date 的 watchlist 跑 13:00 進場 + Closing_check。
    不限 top N，回傳所有有效樣本。
    """
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

        k5_1305 = k5_full[k5_full.index.strftime("%H:%M") <= "13:05"]
        closing_r = engine.check_closing_panel(
            ticker=ticker,
            k5=k5_1305,
            ma10=ma10,
            target_date=entry_date,
            db_path=_DB,
            _now_override="13:05",
        )

        closing_level = closing_r.get("level", "skip")
        pass_count = closing_r.get("pass_count", 0)
        scores = closing_r.get("scores", {})

        next_date = next_trading_day(entry_date, TRADING_DATES_FULL)
        exit_price = None
        exit_date_used = None
        if next_date:
            exit_price = get_open_price_next_day(ticker, next_date)
            exit_date_used = next_date

        if exit_price is None or not entry_price_1300:
            continue

        raw_ret_pct = (exit_price / entry_price_1300 - 1) * 100
        net_ret_pct = round(raw_ret_pct - FEE_PCT, 3)
        win = net_ret_pct > 0

        rec = {
            "entry_date":    entry_date,
            "ticker":        ticker,
            "entry_price":   entry_price_1300,
            "entry_time":    entry_time_str,
            "exit_date":     exit_date_used,
            "exit_price":    exit_price,
            "raw_ret_pct":   round(raw_ret_pct, 3),
            "net_ret_pct":   net_ret_pct,
            "win":           win,
            "closing_level": closing_level,
            "pass_count":    pass_count,
            "scores":        scores,
            "market_regime": regime,
            "layer":         "none",
        }
        rec["score"] = _score_trigger(rec)
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


def _combo_bucket(r: dict) -> list[str]:
    """判斷 record 屬於哪些 buckets (可多個、用於整體 + 細分)。"""
    scores = r.get("scores", {})
    pc = r.get("pass_count", 0)

    buckets_out: list[str] = []

    if pc == 5:
        buckets_out.append("5/5")
    elif pc == 4:
        # 細分
        missing = [k for k in COND_KEYS if not scores.get(k, False)]
        if len(missing) == 1:
            idx = COND_KEYS.index(missing[0]) + 1
            buckets_out.append(f"4/5 missing #{idx}")
        buckets_out.append("4/5 整體")
    elif pc == 3:
        # 細分 C(5,2)=10 種
        missing = [k for k in COND_KEYS if not scores.get(k, False)]
        if len(missing) == 2:
            i1 = COND_KEYS.index(missing[0]) + 1
            i2 = COND_KEYS.index(missing[1]) + 1
            buckets_out.append(f"3/5 missing #{i1}#{i2}")
        buckets_out.append("3/5 整體")
    else:
        buckets_out.append("<3/5 整體")

    return buckets_out


# ── 主 Backtest ───────────────────────────────────────────────────────────────

def run_v10_backtest() -> dict:
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

        day_records = scan_closing_candidates_all(engine, next_date, watchlist, regime)

        if day_records:
            all_records.extend(day_records)
            print(f"  → {len(day_records)} 樣本 (不限 top N)")
        else:
            print(f"  → 0 候選")

    # 分組到各 bucket
    bucket_keys = [
        "5/5",
        "4/5 missing #1",
        "4/5 missing #2",
        "4/5 missing #3",
        "4/5 missing #4",
        "4/5 missing #5",
        "4/5 整體",
        "3/5 missing #1#2",
        "3/5 missing #1#3",
        "3/5 missing #1#4",
        "3/5 missing #1#5",
        "3/5 missing #2#3",
        "3/5 missing #2#4",
        "3/5 missing #2#5",
        "3/5 missing #3#4",
        "3/5 missing #3#5",
        "3/5 missing #4#5",
        "3/5 整體",
        "<3/5 整體",
    ]
    buckets: dict[str, list[dict]] = {k: [] for k in bucket_keys}
    for r in all_records:
        for bk in _combo_bucket(r):
            if bk in buckets:
                buckets[bk].append(r)

    return {
        "all":     all_records,
        "buckets": buckets,
    }


# ── 報告輸出 ──────────────────────────────────────────────────────────────────

BUCKET_DISPLAY = {
    "5/5":                "5/5 (全 pass)",
    "4/5 missing #1":     "4/5 缺 #1 結構未守",
    "4/5 missing #2":     "4/5 缺 #2 沒殺盤",
    "4/5 missing #3":     "4/5 缺 #3 沒紅K反彈",
    "4/5 missing #4":     "4/5 缺 #4 爆量",
    "4/5 missing #5":     "4/5 缺 #5 追高",
    "4/5 整體":            "4/5 整體",
    "3/5 missing #1#2":   "3/5 缺 #1#2 結構+殺盤",
    "3/5 missing #1#3":   "3/5 缺 #1#3 結構+反彈",
    "3/5 missing #1#4":   "3/5 缺 #1#4 結構+量縮",
    "3/5 missing #1#5":   "3/5 缺 #1#5 結構+追高",
    "3/5 missing #2#3":   "3/5 缺 #2#3 殺盤+反彈",
    "3/5 missing #2#4":   "3/5 缺 #2#4 殺盤+量縮",
    "3/5 missing #2#5":   "3/5 缺 #2#5 殺盤+追高",
    "3/5 missing #3#4":   "3/5 缺 #3#4 反彈+量縮",
    "3/5 missing #3#5":   "3/5 缺 #3#5 反彈+追高",
    "3/5 missing #4#5":   "3/5 缺 #4#5 量縮+追高",
    "3/5 整體":            "3/5 整體",
    "<3/5 整體":           "<3/5 整體 (0-2 pass)",
}


def _win_emoji(win_rate: Optional[float]) -> str:
    if win_rate is None:
        return "—"
    if win_rate >= 80:
        return f"🟢{win_rate:.0f}%"
    if win_rate >= 65:
        return f"🟡{win_rate:.0f}%"
    return f"🔴{win_rate:.0f}%"


def print_summary(results: dict) -> str:
    lines = []
    buckets = results["buckets"]
    all_r = results["all"]

    def _h(title: str):
        lines.append(f"\n{'='*70}")
        lines.append(f"  {title}")
        lines.append(f"{'='*70}")

    _h("Phase 3 v10 — Closing_check 4/5 各組合細部 Backtest (5/19-6/3)")
    lines.append("  進場: 13:00 收盤 / 出場: 隔日 9:00 開盤 / Fee: -0.6%")
    lines.append(f"  總樣本: {len(all_r)} 筆 (不限 top N)")

    # ── 主對比表 ──────────────────────────────────────────────────────────────
    _h("主對比表")
    header = f"  {'組合':<26} {'樣本':>5} {'Win%':>10} {'平均淨報酬':>10} {'中位數':>8} {'AvgW':>7} {'AvgL':>7}"
    lines.append(header)
    lines.append("  " + "-" * 75)

    bucket_keys_order = [
        "5/5",
        "4/5 missing #1",
        "4/5 missing #2",
        "4/5 missing #3",
        "4/5 missing #4",
        "4/5 missing #5",
        "4/5 整體",
        "3/5 missing #1#2",
        "3/5 missing #1#3",
        "3/5 missing #1#4",
        "3/5 missing #1#5",
        "3/5 missing #2#3",
        "3/5 missing #2#4",
        "3/5 missing #2#5",
        "3/5 missing #3#4",
        "3/5 missing #3#5",
        "3/5 missing #4#5",
        "3/5 整體",
        "<3/5 整體",
    ]

    stats_by_bucket: dict[str, dict] = {}
    for bk in bucket_keys_order:
        recs = buckets.get(bk, [])
        st = calc_stats(recs)
        stats_by_bucket[bk] = st
        label = BUCKET_DISPLAY.get(bk, bk)
        win_disp = _win_emoji(st["win_rate"])
        avg_disp = f"{st['avg_ret']:+.2f}%" if st["avg_ret"] is not None else "—"
        med_disp = f"{st['median_ret']:+.2f}%" if st["median_ret"] is not None else "—"
        avw_disp = f"{st['avg_win']:+.2f}%" if st["avg_win"] is not None else "—"
        avl_disp = f"{st['avg_loss']:+.2f}%" if st["avg_loss"] is not None else "—"
        n_disp = st["n"]
        # 在 4/5 整體 和 3/5 整體 前加分隔線
        if bk in ("4/5 整體", "3/5 missing #1#2", "3/5 整體", "<3/5 整體"):
            lines.append("  " + "-" * 75)
        lines.append(
            f"  {label:<26} {n_disp:>5} {win_disp:>10} {avg_disp:>10} {med_disp:>8} {avw_disp:>7} {avl_disp:>7}"
        )

    # ── 分析 ──────────────────────────────────────────────────────────────────
    _h("分析")

    # 找 4/5 最佳 / 最差 (只比較 5 種細分、不含整體)
    combo_4of5_detail = [bk for bk in bucket_keys_order if bk.startswith("4/5 missing")]
    combo_4of5_all    = [bk for bk in bucket_keys_order if bk.startswith("4/5")]
    valid_4of5 = [(bk, stats_by_bucket[bk]) for bk in combo_4of5_detail if stats_by_bucket[bk]["n"] > 0]

    # 找 3/5 最佳 / 最差 (只比較 10 種細分)
    combo_3of5_detail = [bk for bk in bucket_keys_order if bk.startswith("3/5 missing")]
    valid_3of5 = [(bk, stats_by_bucket[bk]) for bk in combo_3of5_detail if stats_by_bucket[bk]["n"] > 0]

    best_4_bk = worst_4_bk = None
    if valid_4of5:
        best_4_bk, best_4_st = max(valid_4of5, key=lambda x: (x[1]["win_rate"] or 0))
        worst_4_bk, worst_4_st = min(valid_4of5, key=lambda x: (x[1]["win_rate"] or 0))
        lines.append(f"\n  [4/5] 最佳組合: {BUCKET_DISPLAY[best_4_bk]}  Win={_win_emoji(best_4_st['win_rate'])}  avg={best_4_st['avg_ret']:+.2f}%  n={best_4_st['n']}")
        lines.append(f"  [4/5] 最差組合: {BUCKET_DISPLAY[worst_4_bk]}  Win={_win_emoji(worst_4_st['win_rate'])}  avg={worst_4_st['avg_ret']:+.2f}%  n={worst_4_st['n']}")

    best_3_bk = worst_3_bk = None
    if valid_3of5:
        best_3_bk, best_3_st = max(valid_3of5, key=lambda x: (x[1]["win_rate"] or 0))
        worst_3_bk, worst_3_st = min(valid_3of5, key=lambda x: (x[1]["win_rate"] or 0))
        lines.append(f"\n  [3/5] 最佳組合: {BUCKET_DISPLAY[best_3_bk]}  Win={_win_emoji(best_3_st['win_rate'])}  avg={best_3_st['avg_ret']:+.2f}%  n={best_3_st['n']}")
        lines.append(f"  [3/5] 最差組合: {BUCKET_DISPLAY[worst_3_bk]}  Win={_win_emoji(worst_3_st['win_rate'])}  avg={worst_3_st['avg_ret']:+.2f}%  n={worst_3_st['n']}")

    # 回答各分析問題
    _h("各問題回答 (4/5 篇)")

    def _bk_fmt(bk: str) -> str:
        st = stats_by_bucket.get(bk, {})
        if not st.get("n"):
            return "n=0 無樣本"
        return f"Win={_win_emoji(st['win_rate'])}  avg={st.get('avg_ret', 0):+.2f}%  n={st['n']}"

    lines.append(f"\n  Q1. 哪個 4/5 組合 Win rate 最高?")
    if best_4_bk:
        lines.append(f"      → {BUCKET_DISPLAY[best_4_bk]} ({_bk_fmt(best_4_bk)})")

    lines.append(f"\n  Q2. 「沒殺盤」(#2 缺) 是否最佳?")
    st2 = stats_by_bucket.get("4/5 missing #2", {})
    ref_5of5 = stats_by_bucket.get("5/5", {})
    if st2.get("n"):
        cmp = "較 5/5 高" if (st2.get("win_rate") or 0) >= (ref_5of5.get("win_rate") or 0) else "較 5/5 低"
        lines.append(f"      → {_bk_fmt('4/5 missing #2')}  ({cmp}、5/5={_win_emoji(ref_5of5.get('win_rate'))})")
    else:
        lines.append(f"      → 4/5 missing #2 n=0")

    lines.append(f"\n  Q3. 「沒紅K反彈」(#3 缺) 仍可進?")
    st3 = stats_by_bucket.get("4/5 missing #3", {})
    if st3.get("n"):
        verdict = "✅ 可進 (Win≥65%)" if (st3.get("win_rate") or 0) >= 65 else "⚠️ 謹慎 (Win<65%)"
        lines.append(f"      → {_bk_fmt('4/5 missing #3')}  {verdict}")
    else:
        lines.append(f"      → 4/5 missing #3 n=0")

    lines.append(f"\n  Q4. 「追高」(#5 缺) 是否最差?")
    st5 = stats_by_bucket.get("4/5 missing #5", {})
    if st5.get("n") and valid_4of5:
        is_worst = (worst_4_bk == "4/5 missing #5")
        lines.append(f"      → {_bk_fmt('4/5 missing #5')}  {'✅ 確實最差' if is_worst else '❌ 不是最差'}")
    else:
        lines.append(f"      → 4/5 missing #5 n=0")

    lines.append(f"\n  Q5. 「結構未守」(#1 缺) 應該最差?")
    st1 = stats_by_bucket.get("4/5 missing #1", {})
    if st1.get("n") and valid_4of5:
        is_worst = (worst_4_bk == "4/5 missing #1")
        lines.append(f"      → {_bk_fmt('4/5 missing #1')}  {'✅ 確實最差' if is_worst else '❌ 不是最差，最差是 ' + BUCKET_DISPLAY[worst_4_bk]}")
    else:
        lines.append(f"      → 4/5 missing #1 n=0")

    _h("各問題回答 (3/5 篇)")

    lines.append(f"\n  Q6. 哪個 3/5 組合 Win rate 最高?")
    if best_3_bk:
        lines.append(f"      → {BUCKET_DISPLAY[best_3_bk]} ({_bk_fmt(best_3_bk)})")

    lines.append(f"\n  Q7. 「結構+反彈」(#1#3) 缺是否最差?")
    st13 = stats_by_bucket.get("3/5 missing #1#3", {})
    if st13.get("n") and valid_3of5:
        is_worst = (worst_3_bk == "3/5 missing #1#3")
        lines.append(f"      → {_bk_fmt('3/5 missing #1#3')}  {'✅ 確實最差' if is_worst else '非最差，最差是 ' + BUCKET_DISPLAY[worst_3_bk]}")
    else:
        lines.append(f"      → 3/5 missing #1#3 n=0")

    lines.append(f"\n  Q8. 「殺盤+量縮」(#2#4) 缺是否尚可 (純強勢)?")
    st24 = stats_by_bucket.get("3/5 missing #2#4", {})
    if st24.get("n"):
        verdict = "✅ 尚可 (Win≥65%)" if (st24.get("win_rate") or 0) >= 65 else "⚠️ 較差 (Win<65%)"
        lines.append(f"      → {_bk_fmt('3/5 missing #2#4')}  {verdict}")
    else:
        lines.append(f"      → 3/5 missing #2#4 n=0")

    lines.append(f"\n  Q9. 「量縮+追高」(#4#5) 缺是否 OK (強勢續攻)?")
    st45 = stats_by_bucket.get("3/5 missing #4#5", {})
    if st45.get("n"):
        verdict = "✅ OK (Win≥65%)" if (st45.get("win_rate") or 0) >= 65 else "⚠️ 謹慎 (Win<65%)"
        lines.append(f"      → {_bk_fmt('3/5 missing #4#5')}  {verdict}")
    else:
        lines.append(f"      → 3/5 missing #4#5 n=0")

    # ── Monitor 細分建議 ─────────────────────────────────────────────────────
    _h("Monitor 顯示細分建議 — 4/5")
    lines.append("")
    for bk in combo_4of5_detail:
        st = stats_by_bucket.get(bk, {})
        if not st.get("n"):
            continue
        wr = st.get("win_rate") or 0
        label = BUCKET_DISPLAY[bk]
        if wr >= 80:
            tier = "🟢 最佳 — 可進 (Win≥80%)"
        elif wr >= 65:
            tier = "🟡 一般 — 謹慎可進 (Win 65-79%)"
        else:
            tier = "🔴 差 — 不建議進 (Win<65%)"
        lines.append(f"  {label:<26}  {tier}")

    _h("Monitor 顯示細分建議 — 3/5")
    lines.append("")
    for bk in combo_3of5_detail:
        st = stats_by_bucket.get(bk, {})
        if not st.get("n"):
            continue
        wr = st.get("win_rate") or 0
        label = BUCKET_DISPLAY[bk]
        if wr >= 80:
            tier = "🟢 尚可考慮 (Win≥80%)"
        elif wr >= 65:
            tier = "🟡 邊緣 (Win 65-79%)"
        else:
            tier = "🔴 不建議 (Win<65%)"
        lines.append(f"  {label:<26}  {tier}")

    text = "\n".join(lines)
    print(text)
    return text


# ── 案例詳細列表 ─────────────────────────────────────────────────────────────

def _top_bottom_cases(records: list[dict], n: int = 5) -> tuple[list[dict], list[dict]]:
    sorted_r = sorted(records, key=lambda x: x["net_ret_pct"], reverse=True)
    return sorted_r[:n], sorted_r[-n:]


def _cases_table(records: list[dict]) -> list[str]:
    rows = []
    rows.append("| 進場日 | Ticker | 進場 | 出場 | 淨報酬 | Win | Closing | Pass |")
    rows.append("|--------|--------|------|------|--------|-----|---------|------|")
    for r in records:
        win_tag = "✅" if r["win"] else "❌"
        lvl_emoji = {"confirmed": "🟢", "watch": "🟡", "skip": "🔴"}.get(r["closing_level"], "⚪")
        rows.append(
            f"| {r['entry_date']} | {r['ticker']} | {r['entry_price']:.2f} "
            f"| {r['exit_price']:.2f} | {r['net_ret_pct']:+.2f}% | {win_tag} "
            f"| {lvl_emoji}{r['closing_level']} | {r['pass_count']}/5 |"
        )
    return rows


def write_report(summary_text: str, results: dict) -> Path:
    report_dir = _REPO / "docs" / "主力大課程" / "strategies"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "phase3_v10_closing_4of5_combo_5_19_to_6_3.md"

    buckets = results["buckets"]
    lines = [
        "# Phase 3 v10 — Closing_check 4/5 各組合細部 Backtest (5/19-6/3)",
        "",
        "## 執行摘要",
        "",
        "```",
        summary_text,
        "```",
        "",
        "## 各組合詳細案例",
        "",
    ]

    bucket_keys_order = [
        "5/5",
        "4/5 missing #1",
        "4/5 missing #2",
        "4/5 missing #3",
        "4/5 missing #4",
        "4/5 missing #5",
        "4/5 整體",
        "3/5 missing #1#2",
        "3/5 missing #1#3",
        "3/5 missing #1#4",
        "3/5 missing #1#5",
        "3/5 missing #2#3",
        "3/5 missing #2#4",
        "3/5 missing #2#5",
        "3/5 missing #3#4",
        "3/5 missing #3#5",
        "3/5 missing #4#5",
        "3/5 整體",
        "<3/5 整體",
    ]

    for bk in bucket_keys_order:
        recs = buckets.get(bk, [])
        label = BUCKET_DISPLAY.get(bk, bk)
        st = calc_stats(recs)
        lines.append(f"### {label}")
        lines.append("")
        if not recs:
            lines.append("n=0 無樣本")
            lines.append("")
            continue

        win_disp = _win_emoji(st["win_rate"])
        lines.append(f"- 樣本數: {st['n']}  Win%: {win_disp}  平均淨報酬: {st['avg_ret']:+.2f}%  中位數: {st['median_ret']:+.2f}%")
        lines.append("")

        tops, bots = _top_bottom_cases(recs, 5)

        lines.append("**最佳 5 筆:**")
        lines.append("")
        lines.extend(_cases_table(tops))
        lines.append("")

        lines.append("**最差 5 筆:**")
        lines.append("")
        lines.extend(_cases_table(bots))
        lines.append("")

    # 結論 4/5
    lines.append("## 結論：哪些 4/5 該進、哪些不該進")
    lines.append("")
    lines.append("| 組合 | Win% | 建議 |")
    lines.append("|------|------|------|")
    for bk in [k for k in bucket_keys_order if k.startswith("4/5 missing")]:
        st = calc_stats(buckets.get(bk, []))
        label = BUCKET_DISPLAY.get(bk, bk)
        wr = st.get("win_rate")
        if wr is None:
            verdict = "— 無樣本"
        elif wr >= 80:
            verdict = "✅ 可進"
        elif wr >= 65:
            verdict = "🟡 謹慎可進"
        else:
            verdict = "❌ 不建議進"
        wr_disp = _win_emoji(wr) if wr is not None else "—"
        lines.append(f"| {label} | {wr_disp} | {verdict} |")

    lines.append("")
    lines.append("## 結論：哪些 3/5 組合尚可考慮")
    lines.append("")
    lines.append("| 組合 | Win% | 建議 |")
    lines.append("|------|------|------|")
    for bk in [k for k in bucket_keys_order if k.startswith("3/5 missing")]:
        st = calc_stats(buckets.get(bk, []))
        label = BUCKET_DISPLAY.get(bk, bk)
        wr = st.get("win_rate")
        if wr is None:
            verdict = "— 無樣本"
        elif wr >= 80:
            verdict = "🟢 尚可考慮"
        elif wr >= 65:
            verdict = "🟡 邊緣"
        else:
            verdict = "❌ 不建議"
        wr_disp = _win_emoji(wr) if wr is not None else "—"
        lines.append(f"| {label} | {wr_disp} | {verdict} |")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  報告寫入: {report_path}")
    return report_path


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Phase 3 v10 Closing_check 4/5 combo backtest")
    p.add_argument("--no-report", action="store_true", default=False, help="不寫報告檔")
    args = p.parse_args()

    print("Phase 3 v10 — Closing_check 4/5 組合細部 Backtest 啟動")
    print(f"期間: {TRADING_DATES_FULL[0]} → {TRADING_DATES_FULL[-1]}  (所有樣本、不限 top N)")
    print()

    results = run_v10_backtest()
    report_text = print_summary(results)

    if not args.no_report:
        write_report(report_text, results)


if __name__ == "__main__":
    main()
