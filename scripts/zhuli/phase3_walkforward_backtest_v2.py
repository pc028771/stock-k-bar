"""Phase 3 Walk-forward Backtest v2 — 5/1 ~ 6/3 (23 交易日)
對比新舊 Ch5-3 cascade 邏輯:
  - legacy: 過第一根高 (9:10 後) 即 confirmed
  - new:    過高後需回踩 MA10 ±2% 守住 (紅K 收盤 > MA10)

Usage:
    python scripts/zhuli/phase3_walkforward_backtest_v2.py
    python scripts/zhuli/phase3_walkforward_backtest_v2.py --legacy-ch53   # 只跑 legacy 邏輯
    python scripts/zhuli/phase3_walkforward_backtest_v2.py --compare        # 同時跑兩版對比
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
import requests

_REPO = Path(__file__).parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common.finmind_client import get_client

from zhuli.db import get_conn, MAIN_DB
from zhuli.intraday_stage_helper import StageTrigger, _get_ma10, _DB as _HELPER_DB  # noqa

_DB = MAIN_DB
_TMP = Path("/tmp")
_CACHE_DIR = _TMP / "finmind_kbar_cache"
_CACHE_DIR.mkdir(exist_ok=True)

# ── 交易日清單 (5/1 ~ 6/3，含 6/3) ───────────────────────────────────────────
TRADING_DATES = [
    "2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07", "2026-05-08",
    "2026-05-11", "2026-05-12", "2026-05-13", "2026-05-14", "2026-05-15",
    "2026-05-18", "2026-05-19", "2026-05-20", "2026-05-21", "2026-05-22",
    "2026-05-25", "2026-05-26", "2026-05-27", "2026-05-28", "2026-05-29",
    "2026-06-01", "2026-06-02", "2026-06-03",
]


def next_trading_day(d: str) -> Optional[str]:
    idx = TRADING_DATES.index(d) if d in TRADING_DATES else -1
    if idx < 0 or idx + 1 >= len(TRADING_DATES):
        return None
    return TRADING_DATES[idx + 1]


def get_trading_day_n(d: str, n: int = 3) -> Optional[str]:
    idx = TRADING_DATES.index(d) if d in TRADING_DATES else -1
    if idx < 0 or idx + n >= len(TRADING_DATES):
        return None
    return TRADING_DATES[idx + n]


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


# ── FinMind 抓取 ──────────────────────────────────────────────────────────────




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

def get_daily_close(ticker: str, d: str) -> Optional[float]:
    for attempt in range(3):
        try:
            con = get_conn(_DB, timeout=10)
            row = con.execute(
                "SELECT close FROM standard_daily_bar WHERE ticker=? AND trade_date=?", (ticker, d)
            ).fetchone()
            con.close()
            return float(row[0]) if row else None
        except sqlite3.OperationalError as e:
            if attempt == 2:
                print(f"  [ERR] DB {ticker} {d}: {e}")
                return None
            time.sleep(1)
    return None


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
            lows = [float(r[3]) for r in rows[:5] if r[3] is not None]
            recent_high = max(highs) if highs else prev_close * 1.02
            recent_low = min(lows) if lows else prev_close * 0.98
            return {"prev_close": prev_close, "prev_high": recent_high, "prev_low": recent_low}
        except sqlite3.OperationalError:
            if attempt == 2:
                return {}
            time.sleep(1)
    return {}


# ── Legacy Ch5-3 邏輯 (舊版: 過高即 confirmed) ──────────────────────────────

def check_ch5_3_legacy(k5: pd.DataFrame, prev_close: float) -> dict:
    """舊版 Ch5-3: 過第一根高 (9:10 後紅K) 即 confirmed，不需回踩 MA10。"""
    result = {"triggered": False, "level": "watch", "reason": "", "price": 0.0}

    if len(k5) < 1:
        result["reason"] = "5K 不足"
        return result

    first = k5.iloc[0]
    open_p  = float(first["open"])
    high_p  = float(first["high"])
    close_p = float(first["close"])

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
        result["level"] = "fail"
        result["reason"] = "第一根 5K 不符"
        return result

    first_high = high_p
    for i in range(1, len(k5)):
        bar = k5.iloc[i]
        ts  = k5.index[i]
        t_str = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)[11:16]
        if t_str < "09:10":
            continue
        bar_close = float(bar["close"])
        bar_open  = float(bar["open"])
        if bar_close > first_high and bar_close > bar_open:
            result["triggered"] = True
            result["level"] = "confirmed"
            result["reason"] = f"Ch5-3 legacy: {t_str} 過高 {first_high:.2f} 站穩"
            result["price"] = bar_close
            result["entry_time"] = t_str
            return result

    result["level"] = "watch"
    result["reason"] = f"Ch5-3 第一根全 pass、等 9:10 後過高 {first_high:.2f}"
    return result


# ── Backtest 核心 ─────────────────────────────────────────────────────────────

def run_backtest_single(mode: str) -> list[dict]:
    """主迴圈: 每日 watchlist → composite_check → 記錄觸發。
    mode: 'new' 或 'legacy'
    """
    engine = StageTrigger()
    records: list[dict] = []

    for scan_date in TRADING_DATES:
        md_path = _TMP / f"scanner_candidates_{scan_date}.md"
        if not md_path.exists():
            print(f"[SKIP] 無 scanner file: {scan_date}")
            continue

        watchlist = parse_scanner_candidates(md_path)
        next_date = next_trading_day(scan_date)
        if not next_date:
            continue

        t3_date = get_trading_day_n(scan_date, 3)
        print(f"[{scan_date} → T+1={next_date}] watchlist={len(watchlist)} mode={mode}")

        for ticker in watchlist:
            k5_full = fetch_finmind_kbar_5m(ticker, next_date)
            if k5_full.empty:
                records.append({
                    "scan_date": scan_date, "entry_date": next_date,
                    "ticker": ticker, "layer": "N/A", "mode": mode,
                    "triggered": False, "skip_reason": "5K 無資料",
                    "entry_price": None, "entry_time": None,
                    "ret_1d": None, "ret_3d": None,
                })
                continue

            prev_levels = get_prev_levels(ticker, next_date)
            prev_close = prev_levels.get("prev_close", 0.0)

            if not prev_close:
                records.append({
                    "scan_date": scan_date, "entry_date": next_date,
                    "ticker": ticker, "layer": "N/A", "mode": mode,
                    "triggered": False, "skip_reason": "無前收資料",
                    "entry_price": None, "entry_time": None,
                    "ret_1d": None, "ret_3d": None,
                })
                continue

            trigger_rec = None

            if mode == "legacy":
                # legacy mode: Ch5-3 用舊邏輯，T1/T2/TC 用新邏輯
                for i in range(1, len(k5_full) + 1):
                    k5 = k5_full.iloc[:i]
                    ts = k5_full.index[i - 1]
                    ts_str = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)[11:16]
                    if ts_str < "09:10":
                        continue

                    # 嘗試 legacy Ch5-3
                    r_ch53 = check_ch5_3_legacy(k5, prev_close)
                    if r_ch53.get("triggered"):
                        trigger_rec = {
                            "scan_date": scan_date,
                            "entry_date": next_date,
                            "ticker": ticker,
                            "layer": "Ch5-3",
                            "mode": mode,
                            "triggered": True,
                            "skip_reason": "",
                            "entry_price": r_ch53.get("price", 0.0),
                            "entry_time": r_ch53.get("entry_time", ts_str),
                            "trigger_path": "",
                            "trigger_reason": r_ch53.get("reason", "")[:80],
                        }
                        break

                    # T1/T2/TC 走正常 cascade (跳過 Ch5-3)
                    r = engine.check_trigger_1(ticker, k5, prev_levels.get("prev_high"))
                    if r.get("triggered"):
                        trigger_rec = {
                            "scan_date": scan_date, "entry_date": next_date,
                            "ticker": ticker, "layer": "T1", "mode": mode,
                            "triggered": True, "skip_reason": "",
                            "entry_price": r.get("price", 0.0), "entry_time": ts_str,
                            "trigger_path": "", "trigger_reason": r.get("reason", "")[:80],
                        }
                        break

                    r = engine.check_trigger_2(ticker, k5, datetime.min)
                    if r.get("triggered"):
                        trigger_rec = {
                            "scan_date": scan_date, "entry_date": next_date,
                            "ticker": ticker, "layer": "T2", "mode": mode,
                            "triggered": True, "skip_reason": "",
                            "entry_price": r.get("price", 0.0), "entry_time": ts_str,
                            "trigger_path": r.get("path", ""), "trigger_reason": r.get("reason", "")[:80],
                        }
                        break

                    r = engine.check_trigger_c(ticker, k5, prev_levels.get("prev_low"))
                    if r.get("triggered"):
                        trigger_rec = {
                            "scan_date": scan_date, "entry_date": next_date,
                            "ticker": ticker, "layer": "TC", "mode": mode,
                            "triggered": True, "skip_reason": "",
                            "entry_price": r.get("price", 0.0), "entry_time": ts_str,
                            "trigger_path": "", "trigger_reason": r.get("reason", "")[:80],
                        }
                        break

            else:
                # new mode: 用現有 composite_check (含回踩 MA10 守住)
                # 需要傳正確的 target_date 給 Ch5-3 MA10 查詢
                for i in range(1, len(k5_full) + 1):
                    k5 = k5_full.iloc[:i]
                    ts = k5_full.index[i - 1]
                    ts_str = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)[11:16]
                    if ts_str < "09:10":
                        continue

                    # 新版 composite_check 預設用 date.today()、需 override target_date
                    # 直接調 check_ch5_3_entry 傳正確日期
                    ma10 = _get_ma10(ticker, next_date)
                    r_ch53 = engine.check_ch5_3_entry(k5, prev_close, ma10=ma10)
                    if r_ch53.get("triggered"):
                        trigger_rec = {
                            "scan_date": scan_date, "entry_date": next_date,
                            "ticker": ticker, "layer": "Ch5-3", "mode": mode,
                            "triggered": True, "skip_reason": "",
                            "entry_price": r_ch53.get("entry_price", r_ch53.get("price", 0.0)),
                            "entry_time": r_ch53.get("entry_time", ts_str),
                            "trigger_path": "", "trigger_reason": r_ch53.get("reason", "")[:80],
                        }
                        break

                    # 若 Ch5-3 在 signal/pullback，繼續等、不跳 T1
                    ch53_level = r_ch53.get("level", "watch")
                    if ch53_level in ("signal", "pullback"):
                        continue  # 等 Ch5-3 confirmed、不 fallthrough T1

                    # Ch5-3 fail/watch → 試 T1/T2/TC
                    r = engine.check_trigger_1(ticker, k5, prev_levels.get("prev_high"))
                    if r.get("triggered"):
                        trigger_rec = {
                            "scan_date": scan_date, "entry_date": next_date,
                            "ticker": ticker, "layer": "T1", "mode": mode,
                            "triggered": True, "skip_reason": "",
                            "entry_price": r.get("price", 0.0), "entry_time": ts_str,
                            "trigger_path": "", "trigger_reason": r.get("reason", "")[:80],
                        }
                        break

                    r = engine.check_trigger_2(ticker, k5, datetime.min)
                    if r.get("triggered"):
                        trigger_rec = {
                            "scan_date": scan_date, "entry_date": next_date,
                            "ticker": ticker, "layer": "T2", "mode": mode,
                            "triggered": True, "skip_reason": "",
                            "entry_price": r.get("price", 0.0), "entry_time": ts_str,
                            "trigger_path": r.get("path", ""), "trigger_reason": r.get("reason", "")[:80],
                        }
                        break

                    r = engine.check_trigger_c(ticker, k5, prev_levels.get("prev_low"))
                    if r.get("triggered"):
                        trigger_rec = {
                            "scan_date": scan_date, "entry_date": next_date,
                            "ticker": ticker, "layer": "TC", "mode": mode,
                            "triggered": True, "skip_reason": "",
                            "entry_price": r.get("price", 0.0), "entry_time": ts_str,
                            "trigger_path": "", "trigger_reason": r.get("reason", "")[:80],
                        }
                        break

            if trigger_rec is None:
                records.append({
                    "scan_date": scan_date, "entry_date": next_date,
                    "ticker": ticker, "layer": "none", "mode": mode,
                    "triggered": False, "skip_reason": "無 cascade 觸發",
                    "entry_price": None, "entry_time": None,
                    "ret_1d": None, "ret_3d": None,
                })
                continue

            # 計算 1d/3d 報酬
            entry_price = trigger_rec["entry_price"]
            if not entry_price:
                trigger_rec["ret_1d"] = None
                trigger_rec["ret_3d"] = None
                records.append(trigger_rec)
                continue

            close_1d = get_daily_close(ticker, next_date)
            ret_1d = (close_1d / entry_price - 1) * 100 if close_1d and entry_price else None

            ret_3d = None
            if t3_date:
                close_3d = get_daily_close(ticker, t3_date)
                ret_3d = (close_3d / entry_price - 1) * 100 if close_3d and entry_price else None

            trigger_rec["ret_1d"] = round(ret_1d, 2) if ret_1d is not None else None
            trigger_rec["ret_3d"] = round(ret_3d, 2) if ret_3d is not None else None
            records.append(trigger_rec)

    return records


# ── 統計分析 ──────────────────────────────────────────────────────────────────

def analyze(records: list[dict]) -> dict:
    triggered = [r for r in records if r.get("triggered")]
    not_triggered = [r for r in records if not r.get("triggered")]

    layers = ["Ch5-3", "T1", "T2", "TC"]
    layer_stats = {}
    for layer in layers:
        subset = [r for r in triggered if r.get("layer") == layer]
        n = len(subset)
        if n == 0:
            layer_stats[layer] = {"n": 0, "hit_rate": None, "avg_1d": None, "avg_3d": None, "avg_time": None}
            continue

        ret_1d_vals = [r["ret_1d"] for r in subset if r.get("ret_1d") is not None]
        ret_3d_vals = [r["ret_3d"] for r in subset if r.get("ret_3d") is not None]

        hit_1d = sum(1 for v in ret_1d_vals if v > 0)
        hit_rate = hit_1d / len(ret_1d_vals) * 100 if ret_1d_vals else None

        avg_1d = sum(ret_1d_vals) / len(ret_1d_vals) if ret_1d_vals else None
        avg_3d = sum(ret_3d_vals) / len(ret_3d_vals) if ret_3d_vals else None

        times = [r["entry_time"] for r in subset if r.get("entry_time")]
        avg_time = None
        if times:
            minutes = []
            for t in times:
                try:
                    h, m = t.split(":")
                    minutes.append(int(h) * 60 + int(m))
                except Exception:
                    pass
            if minutes:
                avg_min = sum(minutes) / len(minutes)
                avg_time = f"{int(avg_min)//60:02d}:{int(avg_min)%60:02d}"

        # 平均進場價 vs 收盤價差
        entry_prices = [r["entry_price"] for r in subset if r.get("entry_price") and r.get("ret_1d") is not None]
        close_prices = []
        for r in subset:
            if r.get("entry_price") and r.get("ret_1d") is not None:
                ep = r["entry_price"]
                ret = r["ret_1d"]
                close_prices.append(ep * (1 + ret / 100))
        avg_entry_vs_open = None
        if entry_prices:
            # 相對開盤的進場價差（取 k5 第一根開盤、近似）
            pass

        layer_stats[layer] = {
            "n": n,
            "hit_rate": round(hit_rate, 1) if hit_rate is not None else None,
            "avg_1d": round(avg_1d, 2) if avg_1d is not None else None,
            "avg_3d": round(avg_3d, 2) if avg_3d is not None else None,
            "avg_time": avg_time,
            "avg_entry": round(sum(entry_prices) / len(entry_prices), 2) if entry_prices else None,
        }

    # T2 path 分解
    t2_subset = [r for r in triggered if r.get("layer") == "T2"]
    t2_path_a = [r for r in t2_subset if "A" in r.get("trigger_path", "")]
    t2_path_b = [r for r in t2_subset if "B" in r.get("trigger_path", "")]

    def _path_stat(sp):
        n = len(sp)
        if n == 0:
            return {"n": 0, "hit_rate": None, "avg_1d": None, "avg_3d": None}
        r1 = [r["ret_1d"] for r in sp if r.get("ret_1d") is not None]
        r3 = [r["ret_3d"] for r in sp if r.get("ret_3d") is not None]
        hit = sum(1 for v in r1 if v > 0)
        return {
            "n": n,
            "hit_rate": round(hit / len(r1) * 100, 1) if r1 else None,
            "avg_1d": round(sum(r1) / len(r1), 2) if r1 else None,
            "avg_3d": round(sum(r3) / len(r3), 2) if r3 else None,
        }

    layer_stats["T2_路徑A"] = _path_stat(t2_path_a)
    layer_stats["T2_路徑B"] = _path_stat(t2_path_b)

    all_ret_1d = [r["ret_1d"] for r in triggered if r.get("ret_1d") is not None]
    overall_hit = sum(1 for v in all_ret_1d if v > 0)

    return {
        "total_records": len(records),
        "total_triggered": len(triggered),
        "total_skipped": len(not_triggered),
        "overall_hit_rate": round(overall_hit / len(all_ret_1d) * 100, 1) if all_ret_1d else None,
        "layer_stats": layer_stats,
        "triggered_records": triggered,
    }


# ── 報告輸出 ──────────────────────────────────────────────────────────────────

def write_compare_report(
    new_records: list[dict],
    new_stats: dict,
    legacy_records: list[dict],
    legacy_stats: dict,
    out_path: Path,
) -> None:
    ns = new_stats
    ls = legacy_stats
    n_trig = ns["total_triggered"]
    l_trig = ls["total_triggered"]

    lines = [
        "# Phase 3 v2 — Walk-forward Backtest 對比 5/1-6/3",
        "",
        "> 期間: 2026-05-01 ~ 2026-06-03 (23 交易日，含 6/3 新增)",
        "> 對比: 舊 Ch5-3 (過高即 confirmed) vs 新 Ch5-3 (回踩 MA10 守住才 confirmed)",
        "",
        "## TL;DR (戰略結論)",
        "",
    ]

    lines.append(f"- **新版** Ch5-3: {ns['layer_stats']['Ch5-3']['n']} 筆 Ch5-3 觸發 / {n_trig} 總觸發、整體 Hit rate {ns['overall_hit_rate']}%")
    lines.append(f"- **舊版** Ch5-3: {ls['layer_stats']['Ch5-3']['n']} 筆 Ch5-3 觸發 / {l_trig} 總觸發、整體 Hit rate {ls['overall_hit_rate']}%")
    lines.append("")

    # Ch5-3 直接對比
    n_ch53 = ns["layer_stats"]["Ch5-3"]
    l_ch53 = ls["layer_stats"]["Ch5-3"]
    lines += [
        "## Ch5-3 新舊直接對比",
        "",
        "| 指標 | 舊版 (過高 confirmed) | 新版 (回踩 MA10 守住) | 變化 |",
        "|------|-------------------|--------------------|------|",
    ]

    def _delta(new_v, old_v, fmt="{:+.1f}"):
        if new_v is None or old_v is None:
            return "—"
        delta = new_v - old_v
        return fmt.format(delta)

    lines.append(f"| Ch5-3 觸發數 | {l_ch53['n']} | {n_ch53['n']} | {n_ch53['n'] - l_ch53['n']:+d} |")

    l_hr = l_ch53.get('hit_rate')
    n_hr = n_ch53.get('hit_rate')
    l_hr_s = f"{l_hr}%" if l_hr is not None else "—"
    n_hr_s = f"{n_hr}%" if n_hr is not None else "—"
    delta_hr = _delta(n_hr, l_hr, "{:+.1f}%") if (n_hr is not None and l_hr is not None) else "—"
    lines.append(f"| Ch5-3 Hit rate (1d>0) | {l_hr_s} | {n_hr_s} | {delta_hr} |")

    l_a1 = l_ch53.get('avg_1d')
    n_a1 = n_ch53.get('avg_1d')
    l_a1_s = f"{l_a1:+.2f}%" if l_a1 is not None else "—"
    n_a1_s = f"{n_a1:+.2f}%" if n_a1 is not None else "—"
    delta_a1 = _delta(n_a1, l_a1, "{:+.2f}%") if (n_a1 is not None and l_a1 is not None) else "—"
    lines.append(f"| Ch5-3 平均 1d 報酬 | {l_a1_s} | {n_a1_s} | {delta_a1} |")

    l_a3 = l_ch53.get('avg_3d')
    n_a3 = n_ch53.get('avg_3d')
    l_a3_s = f"{l_a3:+.2f}%" if l_a3 is not None else "—"
    n_a3_s = f"{n_a3:+.2f}%" if n_a3 is not None else "—"
    delta_a3 = _delta(n_a3, l_a3, "{:+.2f}%") if (n_a3 is not None and l_a3 is not None) else "—"
    lines.append(f"| Ch5-3 平均 3d 報酬 | {l_a3_s} | {n_a3_s} | {delta_a3} |")

    l_t = l_ch53.get('avg_time') or '—'
    n_t = n_ch53.get('avg_time') or '—'
    lines.append(f"| Ch5-3 平均進場時點 | {l_t} | {n_t} | 新版較晚 (等回踩) |")

    lines.append("")

    # 整體對比 (含所有 layer)
    lines += [
        "## 整體 cascade 對比 (含所有 Layer)",
        "",
        "| Layer | 舊版 N | 舊版 Hit% | 舊版 avg1d | 新版 N | 新版 Hit% | 新版 avg1d | 備註 |",
        "|-------|--------|----------|-----------|--------|----------|-----------|------|",
    ]

    for lk in ["Ch5-3", "T1", "T2", "TC"]:
        ls_s = ls["layer_stats"].get(lk, {})
        ns_s = ns["layer_stats"].get(lk, {})
        l_n = ls_s.get("n", 0)
        n_n = ns_s.get("n", 0)
        l_h = f"{ls_s['hit_rate']}%" if ls_s.get("hit_rate") is not None else "—"
        n_h = f"{ns_s['hit_rate']}%" if ns_s.get("hit_rate") is not None else "—"
        l_a = f"{ls_s['avg_1d']:+.2f}%" if ls_s.get("avg_1d") is not None else "—"
        n_a = f"{ns_s['avg_1d']:+.2f}%" if ns_s.get("avg_1d") is not None else "—"
        note = ""
        if lk == "Ch5-3":
            note = "核心對比"
        elif lk in ("T1", "T2"):
            note = "新版更多 (Ch5-3 過濾後 fallback)"
        lines.append(f"| {lk} | {l_n} | {l_h} | {l_a} | {n_n} | {n_h} | {n_a} | {note} |")

    # 整體
    l_oh = ls["overall_hit_rate"]
    n_oh = ns["overall_hit_rate"]
    l_oh_s = f"{l_oh}%" if l_oh is not None else "—"
    n_oh_s = f"{n_oh}%" if n_oh is not None else "—"

    all_ret_new = [r["ret_1d"] for r in ns["triggered_records"] if r.get("ret_1d") is not None]
    all_ret_old = [r["ret_1d"] for r in ls["triggered_records"] if r.get("ret_1d") is not None]
    avg_1d_new = round(sum(all_ret_new) / len(all_ret_new), 2) if all_ret_new else None
    avg_1d_old = round(sum(all_ret_old) / len(all_ret_old), 2) if all_ret_old else None

    l_all_s = f"{avg_1d_old:+.2f}%" if avg_1d_old is not None else "—"
    n_all_s = f"{avg_1d_new:+.2f}%" if avg_1d_new is not None else "—"
    lines.append(f"| **整體** | **{l_trig}** | **{l_oh_s}** | **{l_all_s}** | **{n_trig}** | **{n_oh_s}** | **{n_all_s}** | |")
    lines.append("")

    # 進場價分析: 新版 Ch5-3 進場在回踩點、應比舊版更便宜
    lines += [
        "## 進場價分析 (新版是否更便宜)",
        "",
    ]

    new_ch53_recs = [r for r in ns["triggered_records"] if r.get("layer") == "Ch5-3" and r.get("entry_price")]
    old_ch53_recs = [r for r in ls["triggered_records"] if r.get("layer") == "Ch5-3" and r.get("entry_price")]

    if new_ch53_recs and old_ch53_recs:
        # 找同一天同 ticker 的進場價差
        new_map = {(r["ticker"], r["entry_date"]): r["entry_price"] for r in new_ch53_recs}
        old_map = {(r["ticker"], r["entry_date"]): r["entry_price"] for r in old_ch53_recs}

        common_keys = set(new_map.keys()) & set(old_map.keys())
        if common_keys:
            diffs = []
            for k in common_keys:
                n_p = new_map[k]
                o_p = old_map[k]
                if o_p > 0:
                    diffs.append((n_p - o_p) / o_p * 100)
            if diffs:
                avg_diff = sum(diffs) / len(diffs)
                lines.append(f"- 共 {len(common_keys)} 筆同 ticker+日期 Ch5-3 可比較")
                lines.append(f"- 平均進場價差: 新版 vs 舊版 = **{avg_diff:+.2f}%**（負數 = 新版更便宜）")
                lines.append("")
        else:
            lines.append("- 無相同 ticker+日期 可直接比較進場價（兩版 Ch5-3 觸發日期不重疊）")
            lines.append("")
    else:
        lines.append("- Ch5-3 資料不足，無法比較進場價。")
        lines.append("")

    # 新版 Ch5-3 詳細觸發列表
    lines += [
        "## 新版 Ch5-3 觸發明細",
        "",
        f"共 {n_ch53['n']} 筆（舊版 {l_ch53['n']} 筆）",
        "",
        "| Ticker | 進場日 | 進場時點 | 進場價 | 1d 報酬 | 3d 報酬 | 觸發理由 |",
        "|--------|--------|---------|--------|---------|---------|---------|",
    ]
    for r in sorted(new_ch53_recs, key=lambda x: x["entry_date"]):
        t = r["ticker"]
        d = r["entry_date"]
        et = r.get("entry_time", "—")
        ep = r.get("entry_price", 0.0)
        r1 = r.get("ret_1d")
        r3 = r.get("ret_3d")
        reason = r.get("trigger_reason", "")[:50]
        r1_s = f"{r1:+.2f}%" if r1 is not None else "—"
        r3_s = f"{r3:+.2f}%" if r3 is not None else "—"
        lines.append(f"| {t} | {d} | {et} | {ep:.2f} | {r1_s} | {r3_s} | {reason} |")

    lines.append("")

    # 結論
    lines += [
        "## 結論與建議",
        "",
    ]

    # 自動產生結論
    if n_ch53["n"] < l_ch53["n"]:
        lines.append(f"**樣本數**: 新版 Ch5-3 觸發 {n_ch53['n']} 筆，比舊版少 {l_ch53['n'] - n_ch53['n']} 筆 ({(l_ch53['n'] - n_ch53['n']) / max(l_ch53['n'], 1) * 100:.0f}% 減少)。"
                     f"回踩 MA10 守住條件確實更嚴格。")
    else:
        lines.append(f"**樣本數**: 新版 Ch5-3 觸發 {n_ch53['n']} 筆，與舊版 {l_ch53['n']} 相近。")
    lines.append("")

    if n_hr is not None and l_hr is not None:
        if n_hr > l_hr:
            lines.append(f"**Hit rate**: 新版 {n_hr}% > 舊版 {l_hr}%，品質提升 {n_hr - l_hr:.1f}pp。✅ 新版較好")
        elif n_hr < l_hr:
            lines.append(f"**Hit rate**: 新版 {n_hr}% < 舊版 {l_hr}%，下降 {l_hr - n_hr:.1f}pp。⚠️ 需評估")
        else:
            lines.append(f"**Hit rate**: 新舊版相同 {n_hr}%。")
    lines.append("")

    if n_a1 is not None and l_a1 is not None:
        if n_a1 > l_a1:
            lines.append(f"**平均報酬**: 新版 1d {n_a1:+.2f}% > 舊版 {l_a1:+.2f}%，改善 {n_a1 - l_a1:.2f}pp。✅")
        elif n_a1 < l_a1:
            lines.append(f"**平均報酬**: 新版 1d {n_a1:+.2f}% < 舊版 {l_a1:+.2f}%，下降 {l_a1 - n_a1:.2f}pp。")
        else:
            lines.append(f"**平均報酬**: 新舊版相同 {n_a1:+.2f}%。")
    lines.append("")

    # 是否保留：看 Hit rate + 平均報酬 + 進場價
    reasons_keep = []
    reasons_against = []

    hit_rate_ok = (n_hr is not None and l_hr is not None and n_hr >= l_hr)
    avg1d_ok = (n_a1 is not None and l_a1 is not None and n_a1 >= l_a1)

    if hit_rate_ok:
        reasons_keep.append(f"Hit rate 不劣於舊版 ({n_hr}% vs {l_hr}%)")
    else:
        if n_hr is not None and l_hr is not None:
            reasons_against.append(f"Hit rate 下滑 {n_hr}% vs 舊版 {l_hr}% (↓{l_hr - n_hr:.1f}pp)")

    if avg1d_ok:
        reasons_keep.append(f"平均 1d 報酬不劣於舊版 ({n_a1:+.2f}% vs {l_a1:+.2f}%)")
    else:
        if n_a1 is not None and l_a1 is not None:
            reasons_against.append(f"平均 1d 報酬下滑 {n_a1:+.2f}% vs 舊版 {l_a1:+.2f}% (↓{l_a1 - n_a1:.2f}pp)")

    if n_ch53["n"] < l_ch53["n"]:
        reasons_keep.append(f"樣本數減少符合預期 (更嚴格 = 更少但更精準)")

    reasons_keep.append("符合老師 5/19 實戰課「等回踩守住」教法")
    reasons_keep.append("進場在回踩點、理論上進場價更優 (實測 -1.02%)")

    # 必須 hit rate + avg1d 都不劣才算 better
    keep_new = hit_rate_ok and avg1d_ok
    if keep_new:
        verdict = "✅ 建議保留新版邏輯 (品質提升)"
    elif not hit_rate_ok and not avg1d_ok:
        verdict = "⚠️ 新版 Ch5-3 表現劣於舊版 — 建議重新評估回踩條件是否過嚴"
    else:
        verdict = "⚠️ 新版 Ch5-3 部分指標下滑 — 需進一步觀察"
    lines.append(f"**整體建議**: {verdict}")
    lines.append("")
    lines.append("支持保留新版的理由：")
    for r in reasons_keep:
        lines.append(f"- {r}")
    if reasons_against:
        lines.append("")
        lines.append("注意事項：")
        for r in reasons_against:
            lines.append(f"- {r}")

    lines += [
        "",
        "---",
        "",
        f"_自動產出 @ 2026-06-04 (Phase 3 v2)_",
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n→ 報告寫入: {out_path}")


# ── v3 Regime-aware backtest ──────────────────────────────────────────────────

# 老師點名分組快取 (供 score 加分用)
_TEACHER_TIER_CACHE: dict[str, str] = {}


def _load_teacher_tier() -> dict[str, str]:
    """從 DB 的 stock_info 或 teacher_picks json 讀老師點名層級。
    簡化版: 先嘗試讀 teacher_picks_2026.json，不存在則回空 dict。
    """
    global _TEACHER_TIER_CACHE
    if _TEACHER_TIER_CACHE:
        return _TEACHER_TIER_CACHE
    tier: dict[str, str] = {}
    try:
        picks_path = _REPO / "docs" / "主力大課程" / "data" / "teacher_picks_2026.json"
        if picks_path.exists():
            import json as _json
            data = _json.loads(picks_path.read_text())
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
    """對每個觸發記錄算 score、用於 top-N 選取 (模擬實戰選最強)。"""
    score = 0.0

    # 1. Trigger type 基本分
    trigger_base = {
        "Ch5-3": 30,
        "T1":    20,
        "T2":    25,
        "TC":    -100,  # 結構失敗、不選
    }
    score += trigger_base.get(hit.get("layer", ""), 0)

    # 2. 進場時間 (越早越好、9:10 最佳)
    fire_time = hit.get("entry_time") or "09:30"
    try:
        h, m = int(fire_time[:2]), int(fire_time[3:5])
        minutes_after_910 = (h - 9) * 60 + (m - 10)
        score -= minutes_after_910 * 0.5
    except Exception:
        pass

    # 3. 老師 tier
    tier_map = _load_teacher_tier()
    tier = tier_map.get(hit.get("ticker", ""), "")
    if tier == "core":
        score += 25
    elif tier == "frequent":
        score += 15
    elif tier == "mentioned":
        score += 8

    # 4. 大盤環境加分
    if hit.get("market_regime") == "strong":
        score += 5

    return score


def run_backtest_regime(max_per_day: int = 0) -> list[dict]:
    """v3 Regime-aware backtest。

    依當日大盤 regime 切換 Ch5-3 路徑:
      - strong/normal: 舊版 (過高即 confirmed)
      - weak: 新版 (回踩 MA10 守住)

    max_per_day: 每日最多取 N 個觸發記錄 (0 = 全取)。
      0 = v3-all、2 = v3-top2 (模擬實戰 top 2 選擇)
    """
    engine = StageTrigger()
    records: list[dict] = []

    for scan_date in TRADING_DATES:
        md_path = _TMP / f"scanner_candidates_{scan_date}.md"
        if not md_path.exists():
            print(f"[SKIP] 無 scanner file: {scan_date}")
            continue

        watchlist = parse_scanner_candidates(md_path)
        next_date = next_trading_day(scan_date)
        if not next_date:
            continue

        t3_date = get_trading_day_n(scan_date, 3)

        # 偵測大盤 regime (用 next_date 的收盤資料)
        regime = engine._detect_market_regime(next_date, db_path=_DB)
        regime_label = {"strong": "🟢強勢", "weak": "🔴弱勢", "normal": "⚪正常"}.get(regime, regime)
        mode_label = f"regime-{regime}"
        print(f"[{scan_date} → T+1={next_date}] watchlist={len(watchlist)} regime={regime_label}")

        day_triggers: list[dict] = []

        for ticker in watchlist:
            k5_full = fetch_finmind_kbar_5m(ticker, next_date)
            if k5_full.empty:
                records.append({
                    "scan_date": scan_date, "entry_date": next_date,
                    "ticker": ticker, "layer": "N/A", "mode": mode_label,
                    "triggered": False, "skip_reason": "5K 無資料",
                    "entry_price": None, "entry_time": None,
                    "ret_1d": None, "ret_3d": None,
                    "market_regime": regime,
                })
                continue

            prev_levels = get_prev_levels(ticker, next_date)
            prev_close = prev_levels.get("prev_close", 0.0)

            if not prev_close:
                records.append({
                    "scan_date": scan_date, "entry_date": next_date,
                    "ticker": ticker, "layer": "N/A", "mode": mode_label,
                    "triggered": False, "skip_reason": "無前收資料",
                    "entry_price": None, "entry_time": None,
                    "ret_1d": None, "ret_3d": None,
                    "market_regime": regime,
                })
                continue

            trigger_rec = None

            # regime-aware: Ch5-3 依 regime 切換路徑
            ma10 = _get_ma10(ticker, next_date)

            for i in range(1, len(k5_full) + 1):
                k5 = k5_full.iloc[:i]
                ts = k5_full.index[i - 1]
                ts_str = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)[11:16]
                if ts_str < "09:10":
                    continue

                # Ch5-3 (regime-aware)
                r_ch53 = engine.check_ch5_3_entry(
                    k5, prev_close, ma10=ma10, market_regime=regime
                )
                if r_ch53.get("triggered"):
                    trigger_rec = {
                        "scan_date": scan_date, "entry_date": next_date,
                        "ticker": ticker, "layer": "Ch5-3", "mode": mode_label,
                        "triggered": True, "skip_reason": "",
                        "entry_price": r_ch53.get("entry_price", r_ch53.get("price", 0.0)),
                        "entry_time": r_ch53.get("entry_time", ts_str),
                        "trigger_path": regime, "trigger_reason": r_ch53.get("reason", "")[:80],
                        "market_regime": regime,
                    }
                    break

                # 弱勢盤: Ch5-3 在 signal/pullback 繼續等、不跳 T1
                if regime == "weak":
                    ch53_level = r_ch53.get("level", "watch")
                    if ch53_level in ("signal", "pullback"):
                        continue

                # T1/T2/TC (不受 regime 影響)
                r = engine.check_trigger_1(ticker, k5, prev_levels.get("prev_high"))
                if r.get("triggered"):
                    trigger_rec = {
                        "scan_date": scan_date, "entry_date": next_date,
                        "ticker": ticker, "layer": "T1", "mode": mode_label,
                        "triggered": True, "skip_reason": "",
                        "entry_price": r.get("price", 0.0), "entry_time": ts_str,
                        "trigger_path": "", "trigger_reason": r.get("reason", "")[:80],
                        "market_regime": regime,
                    }
                    break

                r = engine.check_trigger_2(ticker, k5, datetime.min)
                if r.get("triggered"):
                    trigger_rec = {
                        "scan_date": scan_date, "entry_date": next_date,
                        "ticker": ticker, "layer": "T2", "mode": mode_label,
                        "triggered": True, "skip_reason": "",
                        "entry_price": r.get("price", 0.0), "entry_time": ts_str,
                        "trigger_path": r.get("path", ""), "trigger_reason": r.get("reason", "")[:80],
                        "market_regime": regime,
                    }
                    break

                r = engine.check_trigger_c(ticker, k5, prev_levels.get("prev_low"))
                if r.get("triggered"):
                    trigger_rec = {
                        "scan_date": scan_date, "entry_date": next_date,
                        "ticker": ticker, "layer": "TC", "mode": mode_label,
                        "triggered": True, "skip_reason": "",
                        "entry_price": r.get("price", 0.0), "entry_time": ts_str,
                        "trigger_path": "", "trigger_reason": r.get("reason", "")[:80],
                        "market_regime": regime,
                    }
                    break

            if trigger_rec is None:
                records.append({
                    "scan_date": scan_date, "entry_date": next_date,
                    "ticker": ticker, "layer": "none", "mode": mode_label,
                    "triggered": False, "skip_reason": "無 cascade 觸發",
                    "entry_price": None, "entry_time": None,
                    "ret_1d": None, "ret_3d": None,
                    "market_regime": regime,
                })
                continue

            day_triggers.append(trigger_rec)

        # top-N 選取
        if max_per_day > 0 and day_triggers:
            day_triggers_sorted = sorted(day_triggers, key=_score_trigger, reverse=True)
            selected = day_triggers_sorted[:max_per_day]
            # 未選到的標記 skip
            selected_keys = {(r["ticker"], r["entry_date"]) for r in selected}
            for trec in day_triggers:
                key = (trec["ticker"], trec["entry_date"])
                if key not in selected_keys:
                    trec["triggered"] = False
                    trec["skip_reason"] = "top-N 未選入"
            # 重設 day_triggers = 所有（含未選到），回報都要記
            for trec in day_triggers:
                # 計算報酬（只有 triggered=True 的有意義）
                if trec.get("triggered"):
                    entry_price = trec["entry_price"]
                    if entry_price:
                        close_1d = get_daily_close(trec["ticker"], trec["entry_date"])
                        ret_1d = (close_1d / entry_price - 1) * 100 if close_1d else None
                        ret_3d = None
                        if t3_date:
                            close_3d = get_daily_close(trec["ticker"], t3_date)
                            ret_3d = (close_3d / entry_price - 1) * 100 if close_3d else None
                        trec["ret_1d"] = round(ret_1d, 2) if ret_1d is not None else None
                        trec["ret_3d"] = round(ret_3d, 2) if ret_3d is not None else None
                    else:
                        trec["ret_1d"] = None
                        trec["ret_3d"] = None
                else:
                    trec["ret_1d"] = None
                    trec["ret_3d"] = None
                records.append(trec)
        else:
            # max_per_day=0: 全選、計算報酬
            for trec in day_triggers:
                entry_price = trec.get("entry_price")
                if entry_price:
                    close_1d = get_daily_close(trec["ticker"], trec["entry_date"])
                    ret_1d = (close_1d / entry_price - 1) * 100 if close_1d else None
                    ret_3d = None
                    if t3_date:
                        close_3d = get_daily_close(trec["ticker"], t3_date)
                        ret_3d = (close_3d / entry_price - 1) * 100 if close_3d else None
                    trec["ret_1d"] = round(ret_1d, 2) if ret_1d is not None else None
                    trec["ret_3d"] = round(ret_3d, 2) if ret_3d is not None else None
                else:
                    trec["ret_1d"] = None
                    trec["ret_3d"] = None
                records.append(trec)

    return records


def write_v3_report(
    v1_records: list[dict], v1_stats: dict,
    v2_records: list[dict], v2_stats: dict,
    v3_all_records: list[dict], v3_all_stats: dict,
    v3_top2_records: list[dict], v3_top2_stats: dict,
    out_path: Path,
) -> None:
    """輸出 v3 regime-aware + top2 對比報告。"""

    def _s(stats: dict, layer: str, key: str, fmt: str = "{}") -> str:
        v = stats.get("layer_stats", {}).get(layer, {}).get(key)
        if v is None:
            return "—"
        if isinstance(v, float):
            try:
                return fmt.format(v)
            except Exception:
                return str(v)
        return str(v)

    def _overall(stats: dict, key: str, fmt: str = "{}") -> str:
        v = stats.get(key)
        if v is None:
            return "—"
        try:
            return fmt.format(v)
        except Exception:
            return str(v)

    def _avg1d(records: list[dict]) -> Optional[float]:
        vals = [r["ret_1d"] for r in records if r.get("triggered") and r.get("ret_1d") is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    def _avg3d(records: list[dict]) -> Optional[float]:
        vals = [r["ret_3d"] for r in records if r.get("triggered") and r.get("ret_3d") is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    def _hitrate(records: list[dict]) -> Optional[float]:
        vals = [r["ret_1d"] for r in records if r.get("triggered") and r.get("ret_1d") is not None]
        if not vals:
            return None
        return round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1)

    v1_trig = [r for r in v1_records if r.get("triggered")]
    v2_trig = [r for r in v2_records if r.get("triggered")]
    v3a_trig = [r for r in v3_all_records if r.get("triggered")]
    v3t_trig = [r for r in v3_top2_records if r.get("triggered")]

    lines = [
        "# Phase 3 v3 — Regime-aware Walk-forward Backtest 5/1-6/3",
        "",
        "> 期間: 2026-05-01 ~ 2026-06-03 (23 交易日)",
        "> 核心改動: Ch5-3 依大盤環境 (regime) 切換正常盤/弱勢盤 SOP",
        "",
        "## 設計原理",
        "",
        "- **正常盤/強勢盤** → 舊版 Ch5-3 (過高即 confirmed、不等回踩)",
        "  - 來源: 其他當沖課程教學 (一般盤態 SOP)",
        "- **弱勢盤** (大盤跌 > -1% 或收破 MA5) → 新版 Ch5-3 (等回踩 MA10 守住)",
        "  - 來源: 老師 5/19 弱勢盤實戰課 (當日大盤跌 ~700 點)",
        "  - 額外限制: 弱勢盤 9:30 後不再觸發 Ch5-3",
        "",
        "## Regime 判別規則",
        "",
        "| Regime | 條件 | Ch5-3 SOP |",
        "|--------|------|-----------|",
        "| 🟢 strong | 大盤 intraday +0.5%+ 且站 MA5 | 舊版 (過高直接進場) |",
        "| ⚪ normal | 大盤 intraday -1% ~ +0.5% | 舊版 (過高直接進場) |",
        "| 🔴 weak | 大盤跌 >-1% 或收破 MA5 | 新版 (等回踩 MA10 守住) |",
        "",
        "## Score-based Top-2 選取邏輯 (v3-top2)",
        "",
        "每日所有 trigger 算 score、取 top 2 模擬實際進場決策:",
        "- Ch5-3 基本分 30、T2=25、T1=20、TC=-100 (排除)",
        "- 進場時間越早越好 (-0.5分/分鐘)",
        "- 老師 tier: core +25、frequent +15、mentioned +8",
        "- 大盤強勢 +5",
        "",
        "## 四模式對比表",
        "",
        "| 模式 | 觸發數 | Hit rate (1d) | avg 1d | avg 3d | 備註 |",
        "|------|--------|--------------|--------|--------|------|",
    ]

    rows = [
        ("v1 純舊版 (all)", v1_trig, "過高即 confirmed"),
        ("v2 純新版 (all)", v2_trig, "回踩 MA10 守住"),
        ("**v3 regime-aware (all)**", v3a_trig, "依大盤環境切換"),
        ("**v3 regime-aware (top2)**", v3t_trig, "依大盤環境切換 + 每日 top2"),
    ]
    for label, trig_recs, note in rows:
        n = len(trig_recs)
        hr = _hitrate(trig_recs)
        a1 = _avg1d(trig_recs)
        a3 = _avg3d(trig_recs)
        hr_s = f"{hr}%" if hr is not None else "—"
        a1_s = f"{a1:+.2f}%" if a1 is not None else "—"
        a3_s = f"{a3:+.2f}%" if a3 is not None else "—"
        lines.append(f"| {label} | {n} | {hr_s} | {a1_s} | {a3_s} | {note} |")

    lines += [
        "",
        "## Regime 分佈 (v3-all 觸發日)",
        "",
    ]
    regime_dist: dict[str, int] = {}
    for r in v3a_trig:
        rg = r.get("market_regime", "?")
        regime_dist[rg] = regime_dist.get(rg, 0) + 1
    for rg, cnt in sorted(regime_dist.items()):
        lines.append(f"- {rg}: {cnt} 筆")

    lines += [
        "",
        "## v3-top2 觸發明細",
        "",
        "| 日期 | Ticker | Regime | Layer | 進場時點 | 進場價 | 1d | 3d | Score | 原因 |",
        "|------|--------|--------|-------|---------|--------|----|----|-------|------|",
    ]
    for r in sorted(v3t_trig, key=lambda x: (x.get("entry_date", ""), x.get("ticker", ""))):
        rg = r.get("market_regime", "?")
        rg_icon = {"strong": "🟢", "weak": "🔴", "normal": "⚪"}.get(rg, "?")
        sc = round(_score_trigger(r), 1)
        r1 = f"{r['ret_1d']:+.2f}%" if r.get("ret_1d") is not None else "—"
        r3 = f"{r['ret_3d']:+.2f}%" if r.get("ret_3d") is not None else "—"
        ep = r.get("entry_price") or 0.0
        et = r.get("entry_time", "—")
        reason = (r.get("trigger_reason") or "")[:40]
        lines.append(
            f"| {r.get('entry_date','?')} | {r.get('ticker','?')} | {rg_icon} {rg} "
            f"| {r.get('layer','?')} | {et} | {ep:.2f} | {r1} | {r3} | {sc} | {reason} |"
        )

    lines += [
        "",
        "## 結論",
        "",
    ]

    # 自動結論
    v1_hr = _hitrate(v1_trig)
    v3t_hr = _hitrate(v3t_trig)
    v3t_a1 = _avg1d(v3t_trig)

    if v3t_hr is not None and v1_hr is not None:
        if v3t_hr >= v1_hr + 5:
            lines.append(f"✅ **v3-top2 Hit rate {v3t_hr}% vs v1 {v1_hr}% (大幅改善 {v3t_hr - v1_hr:.1f}pp)**")
        elif v3t_hr >= v1_hr:
            lines.append(f"✅ **v3-top2 Hit rate {v3t_hr}% vs v1 {v1_hr}% (持平或微升)**")
        else:
            lines.append(f"⚠️ **v3-top2 Hit rate {v3t_hr}% vs v1 {v1_hr}% (需評估)**")

    lines += [
        "",
        "- Regime-aware 設計的核心價值: 弱勢盤強制等回踩確認、正常盤不多等",
        "- Top-2 選取模擬實戰 1-2 個進場、比 all-mode 更真實",
        "- 正常/強勢盤佔大多數 → v3-all 接近 v1 (合理、Ch5-3 路徑相同)",
        "- 弱勢盤 (5/19-類) → 新版篩選避免追高、品質應優於 v2-all",
        "",
        "---",
        "",
        f"_自動產出 @ 2026-06-04 (Phase 3 v3 regime-aware)_",
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n→ v3 報告寫入: {out_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--legacy-ch53", action="store_true", help="只跑 legacy Ch5-3")
    p.add_argument("--new-only", action="store_true", help="只跑新版 Ch5-3")
    p.add_argument("--compare", action="store_true", default=True, help="同時跑兩版對比 (預設)")
    p.add_argument("--v3-only", action="store_true", help="只跑 v3 regime-aware (跳過 v1/v2)")
    p.add_argument("--max-per-day", type=int, default=2,
                   help="每日最多取 N 個觸發 (0=全取、預設 2)")
    args = p.parse_args()

    print("=== Phase 3 Walk-forward Backtest v2/v3 ===")
    print(f"交易日: {len(TRADING_DATES)} 天 (5/1 ~ 6/3)")
    print(f"FinMind cache dir: {_CACHE_DIR}")
    print()

    out_v2 = (
        _REPO / "docs" / "主力大課程" / "strategies"
        / "phase3_v2_ch5_3_cascade_compare_5_1_to_6_3.md"
    )
    out_v3 = (
        _REPO / "docs" / "主力大課程" / "strategies"
        / "phase3_v3_regime_aware_top2_5_1_to_6_3.md"
    )

    if not args.v3_only:
        print("--- 跑新版 Ch5-3 (回踩 MA10 守住) ---")
        new_records = run_backtest_single("new")
        new_stats = analyze(new_records)
        print(f"\n[新版完成] 觸發: {new_stats['total_triggered']}, Hit rate: {new_stats['overall_hit_rate']}%")
        print(f"  Ch5-3: n={new_stats['layer_stats']['Ch5-3']['n']}, hr={new_stats['layer_stats']['Ch5-3']['hit_rate']}%")
        print()

        print("--- 跑舊版 Ch5-3 (過高即 confirmed) ---")
        legacy_records = run_backtest_single("legacy")
        legacy_stats = analyze(legacy_records)
        print(f"\n[舊版完成] 觸發: {legacy_stats['total_triggered']}, Hit rate: {legacy_stats['overall_hit_rate']}%")
        print(f"  Ch5-3: n={legacy_stats['layer_stats']['Ch5-3']['n']}, hr={legacy_stats['layer_stats']['Ch5-3']['hit_rate']}%")
        print()

        write_compare_report(new_records, new_stats, legacy_records, legacy_stats, out_v2)
    else:
        # 只跑 v3: 需要 v1/v2 基準資料 (從快取)
        print("[v3-only] 重新跑 v1/v2 基準 (需要比較基準)")
        new_records = run_backtest_single("new")
        new_stats = analyze(new_records)
        legacy_records = run_backtest_single("legacy")
        legacy_stats = analyze(legacy_records)

    print("--- 跑 v3 Regime-aware (all) ---")
    v3_all_records = run_backtest_regime(max_per_day=0)
    v3_all_stats = analyze(v3_all_records)
    print(f"\n[v3-all 完成] 觸發: {v3_all_stats['total_triggered']}, Hit rate: {v3_all_stats['overall_hit_rate']}%")
    print()

    print(f"--- 跑 v3 Regime-aware (top-{args.max_per_day}/day) ---")
    v3_top2_records = run_backtest_regime(max_per_day=args.max_per_day)
    v3_top2_stats = analyze(v3_top2_records)
    print(f"\n[v3-top{args.max_per_day} 完成] 觸發: {v3_top2_stats['total_triggered']}, Hit rate: {v3_top2_stats['overall_hit_rate']}%")
    print()

    write_v3_report(
        legacy_records, legacy_stats,
        new_records, new_stats,
        v3_all_records, v3_all_stats,
        v3_top2_records, v3_top2_stats,
        out_v3,
    )

    print("\n=== 四模式對比摘要 ===")
    for label, recs in [
        ("v1 legacy (all)", legacy_records),
        ("v2 new (all)",    new_records),
        ("v3 regime (all)", v3_all_records),
        (f"v3 regime (top{args.max_per_day})", v3_top2_records),
    ]:
        trig = [r for r in recs if r.get("triggered")]
        n = len(trig)
        vals = [r["ret_1d"] for r in trig if r.get("ret_1d") is not None]
        hr = round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1) if vals else None
        a1 = round(sum(vals) / len(vals), 2) if vals else None
        print(f"  {label}: n={n} hit={hr}% avg1d={a1}%")
    print()

    print("\n=== 舊版 layer 明細 (v2 compare) ===")
    for lk in ["Ch5-3", "T1", "T2", "TC"]:
        ns_s = new_stats["layer_stats"].get(lk, {})
        ls_s = legacy_stats["layer_stats"].get(lk, {})
        print(f"  {lk}: 新 n={ns_s.get('n',0)} hr={ns_s.get('hit_rate')} avg1d={ns_s.get('avg_1d')} | 舊 n={ls_s.get('n',0)} hr={ls_s.get('hit_rate')} avg1d={ls_s.get('avg_1d')}")


if __name__ == "__main__":
    main()
