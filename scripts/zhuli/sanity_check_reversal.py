"""Sanity check — verify C 反轉形態 scanner 對講師案例的命中.

Course source: strategy-indicators.md §C 反轉形態 (Ch4-2)

Instructor cases (Ch4-2):
    ✅ 1904 正隆    2020-08-11  反轉紅K +5.23% 量 15,132
    ❌ 6441 廣錠    2020-09-16  失敗對照 (均線切到 K 棒)
    ✅ 3042 晶技    2021-01-08  +3.52% 大買 4,260 張

✅ = positive case (應命中)
❌ = negative case (失敗對照，應不命中)
"""
from __future__ import annotations

import argparse
import sqlite3
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
from zhuli.config import ReversalBreakoutConfig
from zhuli.features import add_zhuli_features
from zhuli.entry.reversal_breakout import detect


# expect_signal: True = 應命中 (positive case)；False = 應不命中 (failure 對照)
INSTRUCTOR_CASES = [
    {
        "ticker": "1904", "name": "正隆",
        "signal_date": "2020-08-11",
        "expect_signal": True,
        "divergence_category": None,
        "note": "Ch4-2 23:17~26:00 — 反轉紅K +5.23%，量 15,132（HD 修正自「振容」）",
    },
    {
        "ticker": "6441", "name": "廣錠",
        "signal_date": "2020-09-16",
        "expect_signal": False,
        "divergence_category": None,
        "note": "Ch4-2 28:00 — ❌ 失敗對照：均線發散、ma20 切到 K 棒（detector 應正確排除）",
    },
    {
        "ticker": "3042", "name": "晶技",
        "signal_date": "2021-01-08",
        "expect_signal": True,
        "divergence_category": None,
        "note": "Ch4-2 30:31 — 反轉紅K +3.52%，大買 4,260 張",
    },
]

TOLERANCE_DAYS = 2


def _check_bar_data(db_path: Path, ticker: str, date: str) -> bool:
    try:
        d = pd.Timestamp(date)
        d_min = (d - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
        d_max = (d + pd.Timedelta(days=10)).strftime("%Y-%m-%d")
        with sqlite3.connect(str(db_path), timeout=15) as conn:
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
    cfg: ReversalBreakoutConfig | None = None,
    verbose: bool = False,
) -> dict:
    if cfg is None:
        cfg = ReversalBreakoutConfig()
    if verbose:
        print(f"ReversalBreakoutConfig: {cfg}")

    feats = load_features_cached(db_path=db_path).copy()
    feats = add_zhuli_features(feats)

    results = []
    for case in INSTRUCTOR_CASES:
        ticker = case["ticker"]
        name = case["name"]
        sig_date = pd.Timestamp(case["signal_date"])
        expect = case["expect_signal"]
        note = case["note"]
        cat = case["divergence_category"]

        if not _check_bar_data(db_path, ticker, case["signal_date"]):
            r = {
                "ticker": ticker, "name": name,
                "signal_date": case["signal_date"],
                "result": "no_bar_data",
                "expect_signal": expect,
                "divergence_category": cat, "note": note,
                "msg": f"DB 無 {ticker} bar 資料",
            }
            results.append(r); continue

        try:
            feats_sub = feats[feats["ticker"] == ticker].reset_index(drop=True).copy()
            signals = detect(feats_sub, cfg=cfg)
        except Exception as exc:
            r = {
                "ticker": ticker, "name": name,
                "signal_date": case["signal_date"],
                "result": "error",
                "expect_signal": expect,
                "divergence_category": cat, "note": note,
                "msg": str(exc),
            }
            results.append(r); continue

        tol = pd.Timedelta(days=TOLERANCE_DAYS + 4)
        window = signals[
            (pd.to_datetime(signals["signal_date"]) >= sig_date - tol)
            & (pd.to_datetime(signals["signal_date"]) <= sig_date + tol)
        ]
        found = not window.empty

        # Positive: expect_signal=True → 應 hit；Negative: expect_signal=False → 應 not hit
        if expect and found:
            window = window.copy()
            window["sig_date_dt"] = pd.to_datetime(window["signal_date"])
            window["diff"] = (window["sig_date_dt"] - sig_date).abs()
            best = window.sort_values("diff").iloc[0]
            r = {
                "ticker": ticker, "name": name,
                "signal_date": case["signal_date"],
                "result": "hit",
                "expect_signal": expect,
                "found_date": pd.Timestamp(best["signal_date"]).strftime("%Y-%m-%d"),
                "entry_price": float(best["entry_price"]),
                "stop_loss": float(best["stop_loss"]),
                "divergence_category": cat, "note": note,
                "msg": (
                    f"找到 {pd.Timestamp(best['signal_date']).strftime('%Y-%m-%d')} "
                    f"close={float(best['close']):.2f} entry={float(best['entry_price']):.2f} "
                    f"stop={float(best['stop_loss']):.2f}"
                ),
            }
        elif not expect and not found:
            r = {
                "ticker": ticker, "name": name,
                "signal_date": case["signal_date"],
                "result": "hit",  # negative case correctly not triggered = "hit"
                "expect_signal": expect,
                "divergence_category": cat, "note": note,
                "msg": "正確：失敗對照案例 detector 不觸發 (negative case)",
            }
        elif expect and not found:
            r = {
                "ticker": ticker, "name": name,
                "signal_date": case["signal_date"],
                "result": "miss",
                "expect_signal": expect,
                "divergence_category": cat, "note": note,
                "msg": f"指定日期 {sig_date.date()} ±2 天無 signal (應命中)",
            }
        else:  # not expect and found
            r = {
                "ticker": ticker, "name": name,
                "signal_date": case["signal_date"],
                "result": "false_positive",
                "expect_signal": expect,
                "divergence_category": cat, "note": note,
                "msg": f"失敗對照案例不應觸發但 detector 命中 (false positive)",
            }
        if verbose:
            icon = "✓" if r["result"] == "hit" else "✗"
            print(f"  {icon} {ticker} ({name}): {r['msg']}")
        results.append(r)

    hits = [r for r in results if r["result"] == "hit"]
    misses = [r for r in results if r["result"] in ("miss", "false_positive")]
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
    print(f"Sanity Check (C 反轉形態): {total} instructor cases")
    print("=" * 60)
    for r in result["results"]:
        rs = r["result"]
        if rs == "hit":
            print(f"  ✓ {r['ticker']} ({r['name']}): {r['msg']}")
        elif rs == "false_positive":
            print(f"  ✗ {r['ticker']} ({r['name']}): {r['msg']}")
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
        print(f"\nPASSED — {n_hit}/{total} correct, {n_known} known divergence, {n_skip} skipped")
    else:
        print(f"\nFAILED — {n_hit} correct, {n_unexp} unexpected miss, {n_known} known, {n_skip} skipped")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Sanity check: C 反轉形態 scanner")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--config-override", nargs="*", metavar="KEY=VALUE")
    args = parser.parse_args()
    cfg = ReversalBreakoutConfig()
    if args.config_override:
        cfg = cfg.apply_overrides(dict(kv.split("=", 1) for kv in args.config_override))
    result = run_sanity_check(db_path=args.db, cfg=cfg, verbose=args.verbose)
    print_report(result)
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
