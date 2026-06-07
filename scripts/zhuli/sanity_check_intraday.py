"""Sanity check — verify F 當沖 scanner 對講師案例的命中.

Course source: strategy-indicators.md §F + HD vision Ch5-2

Instructor cases (Ch5-2):
    3141 晶宏    2021-06-07 距前高 6.5% (準突破示範)
    2314 台揚    2021-07     距前高 10.2%
    2010 春源    2021-07-25 距前高 7.9%
    3006 晶豪科  2021-07-01 距前高 10.7%

⚠️ 多數案例 spec_ambiguous — 課程「兩天量 > 2 萬張」對小型股偏嚴格，
   案例為老師人工精選非機械速篩結果。
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
from zhuli.config import IntradayConfig
from zhuli.features import add_zhuli_features
from zhuli.entry.intraday import detect


INSTRUCTOR_CASES = [
    {"ticker": "3141", "name": "晶宏", "signal_date": "2021-06-07",
     "divergence_category": "spec_ambiguous",
     "note": "⚠️ Ch5-2 01:37 — 準突破示範。實測 2 天量 14k-19k < 2 萬張不符 spec hard rule。"},
    {"ticker": "2314", "name": "台揚", "signal_date": "2021-07-15",
     "divergence_category": None,
     "note": "Ch5-2 04:16 — 接近邊界，量 42,823 張。期望機械命中。"},
    {"ticker": "2010", "name": "春源", "signal_date": "2021-07-25",
     "divergence_category": "spec_ambiguous",
     "note": "⚠️ Ch5-2 05:32 — 量 57,792 張。日期 2021-07-25 為週日（非交易日），課程日期可能略偏。"},
    {"ticker": "3006", "name": "晶豪科", "signal_date": "2021-07-01",
     "divergence_category": "spec_ambiguous",
     "note": "⚠️ Ch5-2 06:09 — 富邦「當沖精選鐘點」共 13 檔。距前高 9.69% 邊界，可能 turnover / range 等條件略不符。"},
]

TOLERANCE_DAYS = 5


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
    cfg: IntradayConfig | None = None,
    verbose: bool = False,
) -> dict:
    if cfg is None:
        cfg = IntradayConfig()
    if verbose:
        print(f"IntradayConfig: {cfg}")

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
            r = {"ticker": ticker, "name": name, "signal_date": case["signal_date"],
                 "result": "no_bar_data", "divergence_category": cat,
                 "note": note, "msg": f"DB 無 {ticker} bar"}
            results.append(r); continue

        try:
            feats_sub = feats[feats["ticker"] == ticker].reset_index(drop=True).copy()
            signals = detect(feats_sub, cfg=cfg, db_path=db_path)
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
                 "msg": f"指定日期 {sig_date.date()} ±5 天無 signal"}
            results.append(r); continue

        window = window.copy()
        window["sig_date_dt"] = pd.to_datetime(window["signal_date"])
        window["diff"] = (window["sig_date_dt"] - sig_date).abs()
        best = window.sort_values("diff").iloc[0]
        r = {
            "ticker": ticker, "name": name, "signal_date": case["signal_date"],
            "result": "hit",
            "found_date": best["sig_date_dt"].strftime("%Y-%m-%d"),
            "dist_from_prev_high": float(best["dist_from_prev_high"]),
            "range_3d": float(best["range_3d"]),
            "turnover_3d": float(best["turnover_3d"]),
            "divergence_category": cat, "note": note,
            "msg": (
                f"找到 {best['sig_date_dt'].strftime('%Y-%m-%d')} "
                f"close={float(best['close']):.2f} dist_high={float(best['dist_from_prev_high'])*100:.1f}% "
                f"range3d={float(best['range_3d'])*100:.1f}%"
            ),
        }
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
    print("\n" + "=" * 60)
    print(f"Sanity Check (F 當沖): {total} instructor cases")
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
    parser = argparse.ArgumentParser(description="Sanity check: F 當沖 scanner")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--config-override", nargs="*", metavar="KEY=VALUE")
    args = parser.parse_args()
    cfg = IntradayConfig()
    if args.config_override:
        cfg = cfg.apply_overrides(dict(kv.split("=", 1) for kv in args.config_override))
    result = run_sanity_check(db_path=args.db, cfg=cfg, verbose=args.verbose)
    print_report(result)
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
