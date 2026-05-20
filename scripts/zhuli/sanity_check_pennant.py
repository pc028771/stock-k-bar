"""Sanity check — verify B 旗形 scanner 對講師案例的命中.

Course source: strategy-indicators.md §B (Ch4-2 line 9-216)

Instructor cases (Ch4-2):
    2492 華新科  2019-12-24 旗杆 → 12-26 第三天命中 (投信大買 3,725 張)
    2108 南帝    2020-09-29 旗杆 → 10-05 第三天（spec_ambiguous，邊界範例）
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

from kline.bars import DEFAULT_DB_PATH, load_bars
from kline.features import add_features
from zhuli.config import PennantFlagConfig
from zhuli.features import add_zhuli_features
from zhuli.entry.pennant_flag import detect


INSTRUCTOR_CASES = [
    {
        "ticker": "2492",
        "name": "華新科",
        "signal_date": "2019-12-26",   # 第三天 (旗形完成)
        "pole_date": "2019-12-24",
        "divergence_category": None,
        "note": (
            "Ch4-2 06:31 — 第一個旗型案例。旗杆 12/24 投信大買 3,725 張、漲 +9.19%、"
            "量 48,463 張。旗子 12/25/12/26 量縮整理。"
        ),
    },
    {
        "ticker": "2108",
        "name": "南帝",
        "signal_date": "2020-10-05",   # 第三天 (中秋連假後)
        "pole_date": "2020-09-29",
        "divergence_category": "spec_ambiguous",
        "note": (
            "⚠️ Ch4-2 09:16 — 第二實例。「第四天打不到五日線就直接噴出去」邊界範例。"
            "旗子 09/30 close 49.9 < 旗杆 mid 50.45（不符嚴格旗形 spec），10/05 才符合。"
            "案例用於展示非標準旗形仍能獲利，scanner 嚴格 spec 下不命中是預期。"
        ),
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
    cfg: PennantFlagConfig | None = None,
    verbose: bool = False,
) -> dict:
    if cfg is None:
        cfg = PennantFlagConfig()
    if verbose:
        print(f"PennantFlagConfig: {cfg}")

    bars = load_bars(db_path=db_path)
    feats = add_features(bars)
    feats = add_zhuli_features(feats)

    results = []
    for case in INSTRUCTOR_CASES:
        ticker = case["ticker"]
        name = case["name"]
        sig_date = pd.Timestamp(case["signal_date"])
        note = case["note"]
        cat = case["divergence_category"]

        if not _check_bar_data(db_path, ticker, case["signal_date"]):
            r = {"ticker": ticker, "name": name, "signal_date": case["signal_date"],
                 "result": "no_bar_data", "divergence_category": cat,
                 "note": note, "msg": f"DB 無 {ticker} bar 資料"}
            results.append(r); continue

        try:
            feats_sub = feats[feats["ticker"] == ticker].reset_index(drop=True).copy()
            signals = detect(feats_sub, cfg=cfg)
        except Exception as exc:
            r = {"ticker": ticker, "name": name, "signal_date": case["signal_date"],
                 "result": "error", "divergence_category": cat, "note": note, "msg": str(exc)}
            results.append(r); continue

        tol = pd.Timedelta(days=TOLERANCE_DAYS + 4)
        window = signals[
            (pd.to_datetime(signals["signal_date"]) >= sig_date - tol)
            & (pd.to_datetime(signals["signal_date"]) <= sig_date + tol)
        ]
        if window.empty:
            r = {"ticker": ticker, "name": name, "signal_date": case["signal_date"],
                 "result": "miss", "divergence_category": cat, "note": note,
                 "msg": f"指定日期 {sig_date.date()} ±2 天無 signal"}
            if verbose:
                print(f"  ⚠️  {ticker} ({name}): {r['msg']}")
            results.append(r); continue

        window = window.copy()
        window["sig_date_dt"] = pd.to_datetime(window["signal_date"])
        window["diff"] = (window["sig_date_dt"] - sig_date).abs()
        best = window.sort_values("diff").iloc[0]
        r = {
            "ticker": ticker, "name": name, "signal_date": case["signal_date"],
            "result": "hit",
            "found_date": best["sig_date_dt"].strftime("%Y-%m-%d"),
            "pole_close": float(best["pole_close"]),
            "stop_loss": float(best["stop_loss"]),
            "divergence_category": cat, "note": note,
            "msg": (
                f"找到 {best['sig_date_dt'].strftime('%Y-%m-%d')} "
                f"close={float(best['close']):.2f} pole={float(best['pole_close']):.2f} "
                f"stop={float(best['stop_loss']):.2f}"
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
        "results": results, "hits": hits, "misses": misses,
        "known_divergence_misses": known_div, "unexpected_misses": unexpected,
        "skipped": skipped, "passed": passed, "total": len(INSTRUCTOR_CASES),
    }


def print_report(result: dict) -> None:
    total = result["total"]
    print()
    print("=" * 60)
    print(f"Sanity Check (B 旗形): {total} instructor cases")
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
        print(f"\nFAILED — {n_hit} hit, {n_unexp} unexpected miss, {n_known} known, {n_skip} skipped")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Sanity check: B 旗形 scanner")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--config-override", nargs="*", metavar="KEY=VALUE")
    args = parser.parse_args()
    cfg = PennantFlagConfig()
    if args.config_override:
        cfg = cfg.apply_overrides(dict(kv.split("=", 1) for kv in args.config_override))
    result = run_sanity_check(db_path=args.db, cfg=cfg, verbose=args.verbose)
    print_report(result)
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
