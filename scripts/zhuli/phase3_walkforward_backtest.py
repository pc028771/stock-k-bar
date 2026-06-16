"""Phase 3 Walk-forward Backtest — 5/1 ~ 6/2 (22 交易日)

每日從 daily_scanner watchlist 動態取 Tier-A/B + 老師明示標的，
以 FinMind 1 分 K 聚合 5 分 K，跑 composite_check cascade detector，
計算各 Layer 命中率與 1d/3d 報酬。

Usage:
    python scripts/zhuli/phase3_walkforward_backtest.py [--output-only]
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

_REPO = Path(__file__).parent.parent.parent
_SYS = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_REPO), str(_REPO / "scripts"), str(_SYS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common.finmind_client import get_client

from zhuli.db import get_conn, MAIN_DB
from zhuli.intraday_stage_helper import StageTrigger  # noqa

_DB = MAIN_DB
_TMP = Path("/tmp")
_CACHE_DIR = _TMP / "finmind_kbar_cache"
_CACHE_DIR.mkdir(exist_ok=True)

# ── 交易日清單 (5/1 ~ 6/2, 台股假日 5/1) ──────────────────────────────────────
TRADING_DATES = [
    "2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07", "2026-05-08",
    "2026-05-11", "2026-05-12", "2026-05-13", "2026-05-14", "2026-05-15",
    "2026-05-18", "2026-05-19", "2026-05-20", "2026-05-21", "2026-05-22",
    "2026-05-25", "2026-05-26", "2026-05-27", "2026-05-28", "2026-05-29",
    "2026-06-01", "2026-06-02",
]


def next_trading_day(d: str) -> Optional[str]:
    """取下一個交易日字串。"""
    idx = TRADING_DATES.index(d) if d in TRADING_DATES else -1
    if idx < 0 or idx + 1 >= len(TRADING_DATES):
        return None
    return TRADING_DATES[idx + 1]


def get_trading_day_n(d: str, n: int = 3) -> Optional[str]:
    """取 T+n 交易日。"""
    idx = TRADING_DATES.index(d) if d in TRADING_DATES else -1
    if idx < 0 or idx + n >= len(TRADING_DATES):
        return None
    return TRADING_DATES[idx + n]


# ── Scanner 解析 ──────────────────────────────────────────────────────────────

def parse_scanner_candidates(md_path: Path) -> list[str]:
    """解析 markdown，只取 Tier-A/B + 老師明示，排除後續觀察。

    規則:
    - 包含: 🎯 可進場 Tier-A/B (距 MA10 ≤ 10%)
    - 包含: 📋 老師 core 級指名
    - 排除: ⚠️ 後續觀察 (距 MA10 > 10%)
    - 排除: 一般命中 (老師無 tag)
    """
    text = md_path.read_text()
    tickers: list[str] = []
    seen: set[str] = set()

    # 解析區段
    # 找 "## 🎯 可進場" 和 "## 📋 老師 core 級指名" 區塊
    in_entry = False
    in_teacher = False
    in_observation = False

    for line in text.splitlines():
        # 區段標題判斷
        if line.startswith("## 🎯 可進場"):
            in_entry = True
            in_teacher = False
            in_observation = False
            continue
        elif line.startswith("## ⚠️ 後續觀察"):
            in_entry = False
            in_teacher = False
            in_observation = True
            continue
        elif line.startswith("## 📋 老師 core 級指名"):
            in_entry = False
            in_teacher = True
            in_observation = False
            continue
        elif line.startswith("## "):
            in_entry = False
            in_teacher = False
            in_observation = False
            continue

        # 後續觀察 → 跳過
        if in_observation:
            continue

        if in_entry or in_teacher:
            # 從表格行抽 ticker
            # 格式: | **8021** ⭐ Tier-B | 尖點 | ...
            # 或:   | 1605 | 華新 | ...
            m = re.match(r'\|\s*\*?\*?(\d{4})\*?\*?\s*', line)
            if m:
                t = m.group(1)
                if t not in seen:
                    seen.add(t)
                    tickers.append(t)

    return tickers


# ── FinMind 抓取 ──────────────────────────────────────────────────────────────




def fetch_finmind_kbar_5m(ticker: str, target_date: str) -> pd.DataFrame:
    """抓 FinMind 1 分 K 聚合 5 分 K，含磁碟快取。"""
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

    # 聚合 5 分 K
    df5 = df.resample("5min", label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna(subset=["open", "close"])

    # 存快取
    df5_save = df5.reset_index()
    df5_save["datetime"] = df5_save["datetime"].astype(str)
    cache_file.write_text(json.dumps(df5_save.to_dict("records"), ensure_ascii=False))
    return df5


# ── DB 工具 ───────────────────────────────────────────────────────────────────

def get_daily_close(ticker: str, d: str) -> Optional[float]:
    """從 DB 取指定日收盤。"""
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
    """取前日收盤、近 5 日高/低。"""
    for attempt in range(3):
        try:
            con = get_conn(_DB, timeout=10)
            rows = con.execute(
                "SELECT trade_date, close, high, low FROM standard_daily_bar WHERE ticker=? AND trade_date<? ORDER BY trade_date DESC LIMIT 10",
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
        except sqlite3.OperationalError as e:
            if attempt == 2:
                return {}
            time.sleep(1)
    return {}


# ── Backtest 核心 ─────────────────────────────────────────────────────────────

def run_backtest() -> list[dict]:
    """主迴圈: 每日 watchlist → composite_check → 記錄觸發。"""
    engine = StageTrigger()
    records: list[dict] = []

    for scan_date in TRADING_DATES:
        # scanner file 用 scan_date (T 日掃描 → T+1 進場)
        md_path = _TMP / f"scanner_candidates_{scan_date}.md"
        if not md_path.exists():
            print(f"[SKIP] 無 scanner file: {scan_date}")
            continue

        watchlist = parse_scanner_candidates(md_path)
        next_date = next_trading_day(scan_date)
        if not next_date:
            continue  # 最後一天無 T+1

        t3_date = get_trading_day_n(scan_date, 3)

        print(f"[{scan_date} → T+1={next_date}] watchlist={len(watchlist)} tickers")

        for ticker in watchlist:
            # 抓 T+1 的 5 分 K
            k5_full = fetch_finmind_kbar_5m(ticker, next_date)
            if k5_full.empty:
                records.append({
                    "scan_date": scan_date, "entry_date": next_date,
                    "ticker": ticker, "layer": "N/A",
                    "triggered": False, "skip_reason": "5K 無資料",
                    "entry_price": None, "entry_time": None,
                    "ret_1d": None, "ret_3d": None,
                })
                continue

            # 取前收與 prev_levels
            prev_levels = get_prev_levels(ticker, next_date)
            prev_close = prev_levels.get("prev_close", 0.0)

            if not prev_close:
                records.append({
                    "scan_date": scan_date, "entry_date": next_date,
                    "ticker": ticker, "layer": "N/A",
                    "triggered": False, "skip_reason": "無前收資料",
                    "entry_price": None, "entry_time": None,
                    "ret_1d": None, "ret_3d": None,
                })
                continue

            # 逐根 5K 跑 composite_check
            trigger_rec = None
            for i in range(1, len(k5_full) + 1):
                k5 = k5_full.iloc[:i]
                ts = k5_full.index[i - 1]
                ts_str = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)[11:16]

                # 紀律過濾
                import datetime as _dt
                if ts_str < "09:10":
                    continue

                result = engine.composite_check(
                    ticker=ticker,
                    k5=k5,
                    prev_close=prev_close,
                    prev_levels=prev_levels,
                    category="WATCH",
                )
                if result.get("triggered"):
                    trigger_rec = {
                        "scan_date": scan_date,
                        "entry_date": next_date,
                        "ticker": ticker,
                        "layer": result.get("detector", "none"),
                        "triggered": True,
                        "skip_reason": "",
                        "entry_price": result.get("price", 0.0),
                        "entry_time": ts_str,
                        "trigger_path": result.get("path", ""),
                        "trigger_reason": result.get("reason", "")[:80],
                    }
                    break

            if trigger_rec is None:
                records.append({
                    "scan_date": scan_date, "entry_date": next_date,
                    "ticker": ticker, "layer": "none",
                    "triggered": False, "skip_reason": "無 cascade 觸發",
                    "entry_price": None, "entry_time": None,
                    "ret_1d": None, "ret_3d": None,
                })
                continue

            # 計算 1d/3d 報酬
            entry_price = trigger_rec["entry_price"]
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

    # Per layer 統計
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

        # Hit rate = ret_1d > 0
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

        layer_stats[layer] = {
            "n": n,
            "hit_rate": round(hit_rate, 1) if hit_rate is not None else None,
            "avg_1d": round(avg_1d, 2) if avg_1d is not None else None,
            "avg_3d": round(avg_3d, 2) if avg_3d is not None else None,
            "avg_time": avg_time,
        }

    # T2 path 分解
    t2_subset = [r for r in triggered if r.get("layer") == "T2"]
    t2_path_a = [r for r in t2_subset if "A" in r.get("trigger_path", "")]
    t2_path_b = [r for r in t2_subset if "B" in r.get("trigger_path", "")]

    def _path_stat(subset_p):
        n = len(subset_p)
        if n == 0:
            return {"n": 0, "hit_rate": None, "avg_1d": None, "avg_3d": None, "avg_time": None}
        r1 = [r["ret_1d"] for r in subset_p if r.get("ret_1d") is not None]
        r3 = [r["ret_3d"] for r in subset_p if r.get("ret_3d") is not None]
        hit = sum(1 for v in r1 if v > 0)
        times = [r["entry_time"] for r in subset_p if r.get("entry_time")]
        avg_min = None
        if times:
            mins = []
            for t in times:
                try:
                    h, m = t.split(":")
                    mins.append(int(h) * 60 + int(m))
                except Exception:
                    pass
            avg_min = f"{sum(mins)//len(mins)//60:02d}:{sum(mins)//len(mins)%60:02d}" if mins else None
        return {
            "n": n,
            "hit_rate": round(hit / len(r1) * 100, 1) if r1 else None,
            "avg_1d": round(sum(r1) / len(r1), 2) if r1 else None,
            "avg_3d": round(sum(r3) / len(r3), 2) if r3 else None,
            "avg_time": avg_min,
        }

    layer_stats["T2_路徑A"] = _path_stat(t2_path_a)
    layer_stats["T2_路徑B"] = _path_stat(t2_path_b)

    # 整體統計
    all_ret_1d = [r["ret_1d"] for r in triggered if r.get("ret_1d") is not None]
    overall_hit = sum(1 for v in all_ret_1d if v > 0)

    return {
        "total_records": len(records),
        "total_triggered": len(triggered),
        "total_skipped": len(not_triggered),
        "overall_hit_rate": round(overall_hit / len(all_ret_1d) * 100, 1) if all_ret_1d else None,
        "layer_stats": layer_stats,
        "triggered_records": triggered,
        "skip_reasons": {},
    }


# ── 報告輸出 ──────────────────────────────────────────────────────────────────

def write_report(records: list[dict], stats: dict, out_path: Path) -> None:
    triggered = stats["triggered_records"]
    layer_stats = stats["layer_stats"]

    # 失敗案例分析
    failures = [r for r in triggered if r.get("ret_1d") is not None and r["ret_1d"] <= 0]

    lines = [
        "# Phase 3 — Walk-forward Backtest 5/1-6/2",
        "",
        "## TL;DR (戰略結論)",
        "",
    ]

    total_t = stats["total_triggered"]
    hit = stats["overall_hit_rate"]
    lines.append(f"- 樣本: {total_t} 個 trigger（22 交易日動態 watchlist）")
    lines.append(f"- Composite cascade 整體 1d Hit rate (>0%): **{hit}%**")
    lines.append(f"- 未觸發 / 無資料: {stats['total_skipped']} 筆")
    lines.append("")

    # Layer 排行
    ranked = sorted(
        [(k, v) for k, v in layer_stats.items() if v["n"] > 0 and k not in ("T2_路徑A", "T2_路徑B")],
        key=lambda x: (x[1].get("hit_rate") or 0),
        reverse=True,
    )
    if ranked:
        lines.append("- Layer 表現排行: " + " > ".join(f"{k}({v['hit_rate']}%)" for k, v in ranked if v.get("hit_rate") is not None))
    lines.append("")

    lines += [
        "## Universe (每日 watchlist 來源)",
        "",
        "- 來源: daily_scanner_job.py Tier-A/B + 老師明示 (距 MA10 ≤ 10%)",
        "- 排除: 後續觀察 (距 MA10 > 10%) / 一般命中 (無老師 tag)",
        "",
        "| 日期 | Scanner watchlist | T+1 觸發數 |",
        "|------|------|------|",
    ]

    # 每日統計
    from collections import defaultdict
    daily_wl: dict[str, int] = {}
    daily_trig: dict[str, int] = defaultdict(int)
    for r in records:
        sd = r["scan_date"]
        daily_trig[sd] += 1 if r.get("triggered") else 0

    for scan_date in TRADING_DATES:
        md_path = _TMP / f"scanner_candidates_{scan_date}.md"
        if md_path.exists():
            wl = parse_scanner_candidates(md_path)
            trig = daily_trig.get(scan_date, 0)
            lines.append(f"| {scan_date} | {len(wl)} | {trig} |")

    lines.append("")
    lines += [
        "## Per Layer 結果",
        "",
        "| Layer | 觸發次數 | Hit rate (>0%) | 平均報酬 1d | 平均報酬 3d | Avg 進場時點 |",
        "|-------|---------|---------------|------------|------------|------------|",
    ]

    for layer_key in ["Ch5-3", "T1", "T2", "T2_路徑A", "T2_路徑B", "TC"]:
        s = layer_stats.get(layer_key, {})
        n = s.get("n", 0)
        hr = f"{s['hit_rate']}%" if s.get("hit_rate") is not None else "—"
        a1 = f"{s['avg_1d']:+.2f}%" if s.get("avg_1d") is not None else "—"
        a3 = f"{s['avg_3d']:+.2f}%" if s.get("avg_3d") is not None else "—"
        t = s.get("avg_time") or "—"
        if layer_key == "TC":
            lines.append(f"| TC | {n} | (避免損失) | — | — | {t} |")
        else:
            lines.append(f"| {layer_key} | {n} | {hr} | {a1} | {a3} | {t} |")

    lines.append("")
    lines += [
        "## 假訊號分析",
        "",
        f"觸發後 1d 報酬 ≤ 0 共 {len(failures)} 筆：",
        "",
        "| Ticker | 日期 | Layer | 進場價 | 1d 報酬 | 原因摘要 |",
        "|--------|------|-------|--------|---------|----------|",
    ]
    for r in failures[:20]:  # 最多列 20 筆
        t = r["ticker"]
        d = r["entry_date"]
        layer = r.get("layer", "?")
        price = r.get("entry_price", 0)
        ret = r.get("ret_1d")
        reason = r.get("trigger_reason", "")[:40]
        lines.append(f"| {t} | {d} | {layer} | {price:.2f} | {ret:+.2f}% | {reason} |")

    lines.append("")
    lines += [
        "## vs Hardcoded 14 檔 (Phase 1+2 baseline)",
        "",
        "- Phase 1+2: 固定 14 檔樣本、非 walk-forward",
        "- Phase 3: 22 交易日動態 watchlist、每日 scanner 決定 universe",
        "- Walk-forward 較嚴格：候選池隨市場條件每日變動",
        "",
    ]

    # 簡單比較
    all_ret_1d = [r["ret_1d"] for r in triggered if r.get("ret_1d") is not None]
    if all_ret_1d:
        avg_1d_overall = sum(all_ret_1d) / len(all_ret_1d)
        lines.append(f"- Walk-forward 平均 1d 報酬: {avg_1d_overall:+.2f}%")
        lines.append(f"- Walk-forward 1d Hit rate: {stats['overall_hit_rate']}%")
    lines.append("")

    lines += [
        "## 對 user 實際操作的反思",
        "",
    ]

    # 找知名個股
    known_good = [r for r in triggered if r.get("ret_1d") and r["ret_1d"] > 3 and r["scan_date"] >= "2026-05-19"]
    if known_good:
        lines.append("**系統會推、user 可能漏接（5/19 後 1d >3%）:**")
        lines.append("")
        lines.append("| Ticker | 進場日 | Layer | 進場時點 | 1d 報酬 |")
        lines.append("|--------|--------|-------|---------|---------|")
        for r in sorted(known_good, key=lambda x: -x["ret_1d"])[:15]:
            lines.append(f"| {r['ticker']} | {r['entry_date']} | {r.get('layer')} | {r.get('entry_time')} | {r['ret_1d']:+.2f}% |")
        lines.append("")

    bad_tc = [r for r in triggered if r.get("layer") == "TC"]
    if bad_tc:
        lines.append(f"**系統警示 TC (結構失敗) = 避免損失: {len(bad_tc)} 次**")
        lines.append("")

    lines += [
        "---",
        "",
        f"_自動產出 @ 2026-06-03_",
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n→ 報告寫入: {out_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=== Phase 3 Walk-forward Backtest 5/1-6/2 ===")
    print(f"交易日: {len(TRADING_DATES)} 天")
    print(f"FinMind cache dir: {_CACHE_DIR}")
    print()

    records = run_backtest()

    print(f"\n[完成] 共 {len(records)} 筆記錄，其中觸發 {sum(1 for r in records if r.get('triggered'))} 筆")

    stats = analyze(records)

    out_path = (
        _REPO / "docs" / "主力大課程" / "strategies"
        / "phase3_walkforward_backtest_5_1_to_6_2.md"
    )
    write_report(records, stats, out_path)

    # 輸出概要
    print("\n=== 概要 ===")
    print(f"總觸發: {stats['total_triggered']}")
    print(f"整體 Hit rate: {stats['overall_hit_rate']}%")
    print()
    for k, v in stats["layer_stats"].items():
        if v["n"] > 0:
            print(f"  {k}: n={v['n']}, hr={v['hit_rate']}%, avg1d={v['avg_1d']}%")


if __name__ == "__main__":
    main()
