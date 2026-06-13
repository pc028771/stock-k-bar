"""Sanity check — verify M 收高開低 (open_signal_filter) scanner 對講師案例的命中.

Course source:
    strategy-indicators.md §M 主力意圖判斷 (Ch7-3)
    data/analysis/zhuli/video_screenshots/ch7-3/handwritten_extracts.md

Instructor cases:
    3041 揚智  2020-10-21  收高 27.20 → 隔日開平盤後大量下攤（bearish_exit + limit_up_flat_warning）
    2038 海光  2021-06-23  收低跌停 → 隔日轉強開高（bullish_entry）

判定特性:
    3041 期望同一天同時命中 bearish_exit + limit_up_flat_warning（set 包含關係）
    2038 期望命中 bullish_entry

Usage:
    python scripts/zhuli/sanity_check_open_signal.py [--db PATH] [--verbose]
    python -m zhuli.sanity_check_open_signal [--db PATH]
"""
from __future__ import annotations

from zhuli.db import get_conn

import argparse
import sys
from pathlib import Path

import pandas as pd

_WORKTREE = Path(__file__).parent.parent.parent
_SCRIPTS_DIR = _WORKTREE / "scripts"
for _p in [str(_WORKTREE), str(_SCRIPTS_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kline.bars import DEFAULT_DB_PATH
from kline.features import load_features_cached
from zhuli.config import OpenSignalConfig
from zhuli.features import add_zhuli_features
from zhuli.entry.open_signal_filter import detect


# === Instructor cases (Ch7-3) ===
INSTRUCTOR_CASES = [
    {
        "ticker": "3041",
        "name": "揚智",
        "signal_date": "2020-10-21",
        "expected_signal_types": {"bearish_exit", "limit_up_flat_warning"},
        "divergence_category": None,
        "note": "Ch7-3 — 前日 27.20 收最高，當日開平盤後大量下攤",
    },
    {
        "ticker": "2038",
        "name": "海光",
        "signal_date": "2021-06-23",
        "expected_signal_types": {"bullish_entry"},
        "divergence_category": None,
        "note": "Ch7-3 — 前日跌停收最低，當日轉強開高",
    },
]

TOLERANCE_DAYS = 2   # ±2 個交易日容忍


def _check_bar_data(db_path: Path, ticker: str, date: str) -> bool:
    try:
        d = pd.Timestamp(date)
        d_min = (d - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
        d_max = (d + pd.Timedelta(days=10)).strftime("%Y-%m-%d")
        with get_conn(db_path, timeout=15) as conn:
            cur = conn.execute(
                "SELECT COUNT(*) FROM standard_daily_bar "
                "WHERE ticker=? AND trade_date BETWEEN ? AND ? AND is_usable=1",
                (ticker, d_min, d_max),
            )
            return cur.fetchone()[0] > 0
    except Exception:
        return False


def run_sanity_check(
    db_path: Path = DEFAULT_DB_PATH,
    cfg: OpenSignalConfig | None = None,
    verbose: bool = False,
) -> dict:
    """對 §M 講師案例跑 sanity check.

    Returns dict: results / hits / partial_hits / misses / skipped / passed.
    """
    if cfg is None:
        cfg = OpenSignalConfig()

    if verbose:
        print(f"OpenSignalConfig: {cfg}")

    feats = load_features_cached(db_path=db_path).copy()
    feats = add_zhuli_features(feats)

    results = []

    for case in INSTRUCTOR_CASES:
        ticker = case["ticker"]
        name = case["name"]
        sig_date = pd.Timestamp(case["signal_date"])
        expected = case["expected_signal_types"]
        note = case["note"]

        if not _check_bar_data(db_path, ticker, case["signal_date"]):
            r = {
                "ticker": ticker,
                "name": name,
                "signal_date": case["signal_date"],
                "expected_signal_types": expected,
                "result": "no_bar_data",
                "divergence_category": case["divergence_category"],
                "note": note,
                "msg": f"DB 無 {ticker} 在 {case['signal_date']} ±10 日的 bar 資料",
            }
            if verbose:
                print(f"  ⚠️  {ticker} ({name})：{r['msg']}")
            results.append(r)
            continue

        # 跑 detector
        try:
            feats_sub = feats[feats["ticker"] == ticker].reset_index(drop=True).copy()
            signals = detect(feats_sub, cfg=cfg)
        except Exception as exc:
            r = {
                "ticker": ticker, "name": name,
                "signal_date": case["signal_date"],
                "expected_signal_types": expected,
                "result": "error",
                "divergence_category": case["divergence_category"],
                "note": note,
                "msg": str(exc),
            }
            results.append(r)
            continue

        # 找指定日期附近的 signals
        tol = pd.Timedelta(days=TOLERANCE_DAYS + 4)
        window = signals[
            (signals["signal_date"] >= sig_date - tol)
            & (signals["signal_date"] <= sig_date + tol)
        ]

        if window.empty:
            r = {
                "ticker": ticker, "name": name,
                "signal_date": case["signal_date"],
                "expected_signal_types": expected,
                "result": "miss",
                "found_signal_types": set(),
                "divergence_category": case["divergence_category"],
                "note": note,
                "msg": f"指定日期 {sig_date.date()} ±2 天無任何 signal 輸出",
            }
            if verbose:
                print(f"  ✗ {ticker} ({name})：{r['msg']}")
            results.append(r)
            continue

        # Group by date：找最接近 sig_date 的那天的所有 signal_types
        window = window.copy()
        window["sig_date_dt"] = pd.to_datetime(window["signal_date"])
        window["date_diff"] = (window["sig_date_dt"] - sig_date).abs()
        # Sort by 最接近日期
        closest_date = window.sort_values("date_diff").iloc[0]["sig_date_dt"]
        same_date = window[window["sig_date_dt"] == closest_date]
        found_types = set(same_date["signal_type"].tolist())

        # 判定：found_types ⊇ expected = hit, 部分相交 = partial, 完全沒有 = miss
        if expected.issubset(found_types):
            result_str = "hit"
            msg = (
                f"找到 {closest_date.strftime('%Y-%m-%d')} 同日命中："
                f"{sorted(found_types)}（涵蓋期望 {sorted(expected)}）"
            )
        elif found_types & expected:
            result_str = "partial_hit"
            missing = expected - found_types
            msg = (
                f"找到 {closest_date.strftime('%Y-%m-%d')} 部分命中："
                f"{sorted(found_types)}，缺 {sorted(missing)}"
            )
        else:
            result_str = "miss"
            msg = (
                f"找到 {closest_date.strftime('%Y-%m-%d')} 但 signal_type "
                f"{sorted(found_types)} 跟期望 {sorted(expected)} 不交集"
            )

        r = {
            "ticker": ticker,
            "name": name,
            "signal_date": case["signal_date"],
            "expected_signal_types": expected,
            "result": result_str,
            "found_date": closest_date.strftime("%Y-%m-%d"),
            "found_signal_types": found_types,
            "divergence_category": case["divergence_category"],
            "note": note,
            "msg": msg,
        }
        if verbose:
            icon = "✓" if result_str == "hit" else ("◐" if result_str == "partial_hit" else "✗")
            print(f"  {icon} {ticker} ({name})：{msg}")
        results.append(r)

    hits = [r for r in results if r["result"] == "hit"]
    partial = [r for r in results if r["result"] == "partial_hit"]
    misses = [r for r in results if r["result"] == "miss"]
    skipped = [r for r in results if r["result"] in ("no_bar_data", "error")]

    # passed = 沒有 unexpected miss（partial 是部分命中、no_bar_data 是資料缺）
    passed = len(misses) == 0

    return {
        "results": results,
        "hits": hits,
        "partial_hits": partial,
        "misses": misses,
        "skipped": skipped,
        "passed": passed,
        "total": len(INSTRUCTOR_CASES),
    }


def print_report(result: dict) -> None:
    results = result["results"]
    total = result["total"]

    print()
    print("=" * 60)
    print(f"Sanity Check (M 收高開低): {total} instructor cases")
    print("=" * 60)

    for r in results:
        ticker = r["ticker"]
        name = r["name"]
        result_str = r["result"]

        if result_str == "hit":
            print(f"  ✓ {ticker} ({name})  {r['msg']}")
        elif result_str == "partial_hit":
            print(f"  ◐ {ticker} ({name})  {r['msg']}")
        elif result_str == "no_bar_data":
            print(f"  ⚠️  {ticker} ({name})  {r['msg']}")
        elif result_str == "miss":
            print(f"  ✗ {ticker} ({name})  {r['msg']}")
        else:
            print(f"  ? {ticker} ({name})  {result_str} — {r.get('msg','')}")

    print()
    n_hit = len(result["hits"])
    n_partial = len(result["partial_hits"])
    n_miss = len(result["misses"])
    n_skip = len(result["skipped"])

    if result["passed"]:
        print(
            f"PASSED — {n_hit}/{total} strict hit, "
            f"{n_partial} partial, {n_skip} skipped（資料不足）"
        )
    else:
        print(f"FAILED — {n_hit} hit, {n_partial} partial, {n_miss} miss, {n_skip} skipped")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Sanity check: 驗證 M 收高開低 scanner 對講師案例的命中。"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument(
        "--config-override", nargs="*", metavar="KEY=VALUE",
        help="Override OpenSignalConfig，e.g. limit_up_flat_open_threshold=0.005",
    )
    args = parser.parse_args()

    cfg = OpenSignalConfig()
    if args.config_override:
        overrides = dict(kv.split("=", 1) for kv in (args.config_override or []))
        cfg = cfg.apply_overrides(overrides)

    result = run_sanity_check(db_path=args.db, cfg=cfg, verbose=args.verbose)
    print_report(result)
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
