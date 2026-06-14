"""Sanity check — verify G 隔日沖 scanner 對講師案例的命中.

Course source: strategy-indicators.md §G 隔日沖策略 (HD vision Ch6-2)

Instructor cases (Ch6-2):
    2351 順德    2021-06-22  進 117 → 出 125 (+8 元)
    6271 同欣電  2021-06-22  ~210.5 → 211（隔日開盤）
    3149 立達    2021-06-22  漲停

⚠️ 注意：3 個案例 bandwidth_prev > 0.20，不符合 spec「< 6%」。
   案例為老師人工精選非速篩結果，全部標 spec_ambiguous。
   若 cfg_override bandwidth_max=0.30 才會命中（demo only）。

Usage:
    python scripts/zhuli/sanity_check_overnight.py [--db PATH] [--verbose]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

_WORKTREE = Path(__file__).parent.parent.parent
_SCRIPTS_DIR = _WORKTREE / "scripts"
for _p in [str(_WORKTREE), str(_SCRIPTS_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.db import get_conn
from kline.bars import DEFAULT_DB_PATH
from kline.features import load_features_cached
from zhuli.config import OvernightSwingConfig
from zhuli.features import add_zhuli_features
from zhuli.entry.overnight_swing import detect


INSTRUCTOR_CASES = [
    {
        "ticker": "2351",
        "name": "順德",
        "signal_date": "2021-06-22",
        "expected_close": 119.0,   # 進 117 出 125, 該日收盤 119
        "divergence_category": "spec_ambiguous",
        "note": (
            "⚠️ Ch6-2 10:06 — 進 117 出 125。bandwidth_prev=0.278 不符合 spec「< 6%」。"
            "Case 為老師精選非速篩。"
        ),
    },
    {
        "ticker": "6271",
        "name": "同欣電",
        "signal_date": "2021-06-22",
        "expected_close": 210.5,
        "divergence_category": "spec_ambiguous",
        "note": (
            "⚠️ Ch6-2 08:29 — ~210.5 → 211 隔日。bandwidth_prev=0.202 不符 spec「< 6%」。"
        ),
    },
    {
        "ticker": "3149",
        "name": "立達",
        "signal_date": "2021-06-22",
        "expected_close": 44.0,
        "divergence_category": "spec_ambiguous",
        "note": (
            "⚠️ Ch6-2 05:51 — 漲停。bandwidth_prev=0.333 不符 spec「< 6%」。"
        ),
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
    cfg: OvernightSwingConfig | None = None,
    verbose: bool = False,
) -> dict:
    if cfg is None:
        cfg = OvernightSwingConfig()
    if verbose:
        print(f"OvernightSwingConfig: {cfg}")

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
                "divergence_category": cat, "note": note,
                "msg": f"DB 無 {ticker} 在 {case['signal_date']} ±10 日 bar",
            }
            results.append(r)
            continue

        try:
            feats_sub = feats[feats["ticker"] == ticker].reset_index(drop=True).copy()
            signals = detect(feats_sub, cfg=cfg, db_path=db_path)
        except Exception as exc:
            r = {
                "ticker": ticker, "name": name,
                "signal_date": case["signal_date"],
                "result": "error",
                "divergence_category": cat, "note": note,
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
                "divergence_category": cat, "note": note,
                "msg": f"指定日期 {sig_date.date()} ±2 天無 signal 輸出",
            }
            if verbose:
                print(f"  ⚠️  {ticker} ({name}): {r['msg']}")
            results.append(r)
            continue

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
            "body_pct": float(best["body_pct"]),
            "divergence_category": cat, "note": note,
            "msg": (
                f"找到 {best['sig_date_dt'].strftime('%Y-%m-%d')} "
                f"close={float(best['close']):.2f} "
                f"bw={float(best['bandwidth_prev']):.3f} "
                f"body={float(best['body_pct'])*100:+.2f}%"
            ),
        }
        if verbose:
            print(f"  ✓ {ticker} ({name}): {r['msg']}")
        results.append(r)

    hits = [r for r in results if r["result"] == "hit"]
    misses = [r for r in results if r["result"] == "miss"]
    skipped = [r for r in results if r["result"] in ("no_bar_data", "error")]
    known_div = [r for r in misses if r.get("divergence_category")]
    unexpected = [r for r in misses if not r.get("divergence_category")]
    passed = len(unexpected) == 0

    return {
        "results": results,
        "hits": hits,
        "misses": misses,
        "known_divergence_misses": known_div,
        "unexpected_misses": unexpected,
        "skipped": skipped,
        "passed": passed,
        "total": len(INSTRUCTOR_CASES),
    }


def print_report(result: dict) -> None:
    total = result["total"]
    print()
    print("=" * 60)
    print(f"Sanity Check (G 隔日沖): {total} instructor cases")
    print("=" * 60)
    for r in result["results"]:
        rs = r["result"]
        if rs == "hit":
            print(f"  ✓ {r['ticker']} ({r['name']}): {r['msg']}")
        elif rs == "no_bar_data":
            print(f"  ⚠️  {r['ticker']} ({r['name']}): {r['msg']}")
        elif rs == "miss":
            if r.get("divergence_category"):
                print(f"  ⚠️  {r['ticker']} ({r['name']}) [known_{r['divergence_category']}]: {r['msg']}")
            else:
                print(f"  ✗ {r['ticker']} ({r['name']}): {r['msg']}")
        else:
            print(f"  ? {r['ticker']} ({r['name']}): {rs}")

    n_hit = len(result["hits"])
    n_known = len(result.get("known_divergence_misses", []))
    n_unexp = len(result.get("unexpected_misses", []))
    n_skip = len(result["skipped"])
    if result["passed"]:
        print(f"\nPASSED — {n_hit}/{total} strict hit, {n_known} known divergence, {n_skip} skipped")
    else:
        print(f"\nFAILED — {n_hit} hit, {n_unexp} unexpected miss, {n_known} known divergence, {n_skip} skipped")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Sanity check: G 隔日沖 scanner")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--config-override", nargs="*", metavar="KEY=VALUE")
    args = parser.parse_args()
    cfg = OvernightSwingConfig()
    if args.config_override:
        overrides = dict(kv.split("=", 1) for kv in args.config_override)
        cfg = cfg.apply_overrides(overrides)
    result = run_sanity_check(db_path=args.db, cfg=cfg, verbose=args.verbose)
    print_report(result)
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
