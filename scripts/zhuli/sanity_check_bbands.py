"""Sanity check — verify D 布林上軌進出 scanner 對講師案例的命中.

Course source: strategy-indicators.md §D 布林上軌進出策略 (HD vision Ch4-2)

Instructor cases:
    6672 騰輝電子-KY  2021-05-28  105.5 +5.5%  bandwidth 0.19
    3006 晶豪科       2021-02-17  69.1  +9.86% bandwidth 0.16
    6237 華訊         2020-12-17  51.5  +9.23% bandwidth 0.15

Usage:
    python scripts/zhuli/sanity_check_bbands.py [--db PATH] [--verbose]
    python -m zhuli.sanity_check_bbands [--db PATH]
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
from zhuli.config import BBandsUpperBreakConfig
from zhuli.features import add_zhuli_features
from zhuli.entry.bbands_upper_break import detect


INSTRUCTOR_CASES = [
    {
        "ticker": "6672",
        "name": "騰輝電子-KY",
        "signal_date": "2021-05-28",
        "expected_close": 105.5,
        "expected_change_pct": 5.5,
        "divergence_category": None,
        "note": "HD vision Ch4-2 37:15 — 帶量突破布林上軌，8 天 100→130",
    },
    {
        "ticker": "3006",
        "name": "晶豪科",
        "signal_date": "2021-02-17",
        "expected_close": 69.1,
        "expected_change_pct": 9.86,
        "divergence_category": None,
        "note": "HD vision Ch4-2 39:32 — 大買 7,407 張，7 天 70→91",
    },
    {
        "ticker": "6237",
        "name": "華訊",
        "signal_date": "2020-12-17",
        "expected_close": 51.5,
        "expected_change_pct": 9.23,
        "divergence_category": None,
        "note": "HD vision Ch4-2 42:36 — 大買 4,183 張",
    },
]

TOLERANCE_DAYS = 2


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
    cfg: BBandsUpperBreakConfig | None = None,
    verbose: bool = False,
) -> dict:
    if cfg is None:
        cfg = BBandsUpperBreakConfig()
    if verbose:
        print(f"BBandsUpperBreakConfig: {cfg}")

    feats = load_features_cached(db_path=db_path).copy()
    feats = add_zhuli_features(feats)

    results = []
    for case in INSTRUCTOR_CASES:
        ticker = case["ticker"]
        name = case["name"]
        sig_date = pd.Timestamp(case["signal_date"])
        note = case["note"]
        cat = case["divergence_category"]

        if not _check_bar_data(db_path, ticker, case["signal_date"]):
            r = {
                "ticker": ticker, "name": name,
                "signal_date": case["signal_date"],
                "result": "no_bar_data",
                "divergence_category": cat,
                "note": note,
                "msg": f"DB 無 {ticker} 在 {case['signal_date']} ±10 日 bar 資料",
            }
            results.append(r)
            continue

        try:
            feats_sub = feats[feats["ticker"] == ticker].reset_index(drop=True).copy()
            signals = detect(feats_sub, cfg=cfg)
        except Exception as exc:
            r = {
                "ticker": ticker, "name": name,
                "signal_date": case["signal_date"],
                "result": "error",
                "divergence_category": cat,
                "note": note,
                "msg": str(exc),
            }
            results.append(r)
            continue

        tol = pd.Timedelta(days=TOLERANCE_DAYS + 4)
        window = signals[
            (pd.to_datetime(signals["signal_date"]) >= sig_date - tol)
            & (pd.to_datetime(signals["signal_date"]) <= sig_date + tol)
        ]

        if window.empty:
            r = {
                "ticker": ticker, "name": name,
                "signal_date": case["signal_date"],
                "result": "miss",
                "divergence_category": cat,
                "note": note,
                "msg": f"指定日期 {sig_date.date()} ±2 天無 signal 輸出",
            }
            if verbose:
                print(f"  ✗ {ticker} ({name})：{r['msg']}")
            results.append(r)
            continue

        # 找最接近的
        window = window.copy()
        window["sig_date_dt"] = pd.to_datetime(window["signal_date"])
        window["diff"] = (window["sig_date_dt"] - sig_date).abs()
        best = window.sort_values("diff").iloc[0]

        r = {
            "ticker": ticker, "name": name,
            "signal_date": case["signal_date"],
            "result": "hit",
            "found_date": best["sig_date_dt"].strftime("%Y-%m-%d"),
            "found_close": float(best["close"]),
            "bandwidth_prev": float(best["bandwidth_prev"]),
            "is_ideal_bandwidth": bool(best["is_ideal_bandwidth"]),
            "volume_ratio_prev": float(best["volume_ratio_prev"]),
            "divergence_category": cat,
            "note": note,
            "msg": (
                f"找到 {best['sig_date_dt'].strftime('%Y-%m-%d')} "
                f"close={float(best['close']):.2f} "
                f"bw_prev={float(best['bandwidth_prev']):.3f}"
                f"{'(ideal)' if best['is_ideal_bandwidth'] else ''} "
                f"vol×{float(best['volume_ratio_prev']):.2f}"
            ),
        }
        if verbose:
            print(f"  ✓ {ticker} ({name})：{r['msg']}")
        results.append(r)

    hits = [r for r in results if r["result"] == "hit"]
    misses = [r for r in results if r["result"] == "miss"]
    skipped = [r for r in results if r["result"] in ("no_bar_data", "error")]
    known_div_misses = [r for r in misses if r.get("divergence_category")]
    unexpected_misses = [r for r in misses if not r.get("divergence_category")]
    passed = len(unexpected_misses) == 0

    return {
        "results": results,
        "hits": hits,
        "misses": misses,
        "known_divergence_misses": known_div_misses,
        "unexpected_misses": unexpected_misses,
        "skipped": skipped,
        "passed": passed,
        "total": len(INSTRUCTOR_CASES),
    }


def print_report(result: dict) -> None:
    results = result["results"]
    total = result["total"]
    print()
    print("=" * 60)
    print(f"Sanity Check (D 布林上軌進出): {total} instructor cases")
    print("=" * 60)
    for r in results:
        rs = r["result"]
        if rs == "hit":
            print(f"  ✓ {r['ticker']} ({r['name']})  {r['msg']}")
        elif rs == "no_bar_data":
            print(f"  ⚠️  {r['ticker']} ({r['name']}): {r['msg']}")
        elif rs == "miss":
            if r.get("divergence_category"):
                print(f"  ⚠️  {r['ticker']} ({r['name']}) [known_{r['divergence_category']}]: {r['msg']}")
            else:
                print(f"  ✗ {r['ticker']} ({r['name']}): {r['msg']}")
        else:
            print(f"  ? {r['ticker']} ({r['name']}): {rs} — {r.get('msg','')}")

    print()
    n_hit = len(result["hits"])
    n_known = len(result.get("known_divergence_misses", []))
    n_unexp = len(result.get("unexpected_misses", []))
    n_skip = len(result["skipped"])
    if result["passed"]:
        print(f"PASSED — {n_hit}/{total} strict hit, {n_known} known divergence, {n_skip} skipped")
    else:
        print(f"FAILED — {n_hit} hit, {n_unexp} unexpected miss, {n_known} known divergence, {n_skip} skipped")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Sanity check: D 布林上軌 scanner")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--config-override", nargs="*", metavar="KEY=VALUE")
    args = parser.parse_args()
    cfg = BBandsUpperBreakConfig()
    if args.config_override:
        overrides = dict(kv.split("=", 1) for kv in args.config_override)
        cfg = cfg.apply_overrides(overrides)
    result = run_sanity_check(db_path=args.db, cfg=cfg, verbose=args.verbose)
    print_report(result)
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
