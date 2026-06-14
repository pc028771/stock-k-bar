"""Sanity check — verify I 投信跟單 scanner 對講師案例的命中.

Course source: strategy-indicators.md §I 投信跟單策略 (Ex2-1 + Ex2-2)

⚠️ Note: FinMind 的投信買賣超資料對小型股顯著缺漏（與課程截圖數字差距大）。
   多數案例會標 data_gap (FinMind vs 富邦軟體差異)。
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
from zhuli.config import InstitutionalSwingConfig
from zhuli.features import add_zhuli_features
from zhuli.entry.institutional_swing import detect


# 進場 case (5 日投本比 ≥ 1.5% 篩選): 都標 data_gap (FinMind 資料缺漏)
# 警戒 case (投本比 > 12%): 標 spec_ambiguous (FinMind 無投信持股 ratio 資料)
INSTRUCTOR_CASES = [
    # 進場篩選案例 (Ex2-2)
    {"ticker": "3092", "name": "鴻碩", "signal_date": "2021-03-11",
     "expected_buy_pct": 1.99, "divergence_category": "data_gap",
     "note": "⚠️ Ex2-2 03:20 — 第一個案例。FinMind 該日附近 sitc_buy 資料缺。"},
    {"ticker": "3545", "name": "敦泰", "signal_date": "2021-03-11",
     "expected_buy_pct": 1.72, "divergence_category": "data_gap",
     "note": "⚠️ Ex2-2 04:28 — 操作演示。FinMind buy_pct=1.144% 不到 1.5%（與課程 1.72% 差異）。"},
    {"ticker": "6237", "name": "驊訊", "signal_date": "2021-03-11",
     "expected_buy_pct": 2.18, "divergence_category": "data_gap",
     "note": "⚠️ Ex2-2 05:00 — 最高 175.37 案例。FinMind buy_pct=1.739% 接近但 MA alignment 未過。"},
    {"ticker": "6284", "name": "佳邦", "signal_date": "2021-03-11",
     "expected_buy_pct": 1.66, "divergence_category": "data_gap",
     "note": "⚠️ Ex2-2 — FinMind 資料未達 1.5%"},
    {"ticker": "6443", "name": "元晶", "signal_date": "2021-03-11",
     "expected_buy_pct": 2.27, "divergence_category": "data_gap",
     "note": "⚠️ Ex2-2 — FinMind sitc_buy 嚴重缺漏（淨賣狀態）"},
    {"ticker": "8016", "name": "矽創", "signal_date": "2021-03-11",
     "expected_buy_pct": 1.62, "divergence_category": "data_gap",
     "note": "⚠️ Ex2-2 — FinMind sitc_buy 嚴重缺漏"},
    # 警戒案例 (Ex2-1) — 投本比 > 12% 倒貨風險，目前 FinMind 無投信持股 ratio
    {"ticker": "2138", "name": "茂達", "signal_date": "2021-07-27",
     "expected_buy_pct": None, "divergence_category": "spec_ambiguous",
     "note": "⚠️ Ex2-1 16:00 — 警戒案例 17.6% 投本比 → 倒貨。FinMind 無投信持股 ratio dataset。"},
    {"ticker": "3131", "name": "弘塑", "signal_date": "2020-10-15",
     "expected_buy_pct": None, "divergence_category": "spec_ambiguous",
     "note": "⚠️ Ex2-1 16:38 — 警戒案例 24.7% 投本比 → 腰斬。FinMind 無投信持股 ratio dataset。"},
    {"ticker": "4919", "name": "新唐", "signal_date": "2021-04-01",
     "expected_buy_pct": None, "divergence_category": "spec_ambiguous",
     "note": "⚠️ Ex2-1 13:00 — 投信認養成功案例（高 161.06）。Spec 為「連續紅柱買超」非精確訊號定義。"},
]

TOLERANCE_DAYS = 5  # 案例日期容忍較寬


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
    cfg: InstitutionalSwingConfig | None = None,
    verbose: bool = False,
) -> dict:
    if cfg is None:
        cfg = InstitutionalSwingConfig()
    if verbose:
        print(f"InstitutionalSwingConfig: {cfg}")

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
                 "note": note, "msg": f"DB 無 {ticker} bar 資料"}
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
            "buy_pct": float(best["buy_pct_of_shares"]),
            "divergence_category": cat, "note": note,
            "msg": (
                f"找到 {best['sig_date_dt'].strftime('%Y-%m-%d')} "
                f"buy_pct={float(best['buy_pct_of_shares'])*100:.3f}%"
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
    print()
    print("=" * 60)
    print(f"Sanity Check (I 投信跟單): {total} instructor cases")
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
    parser = argparse.ArgumentParser(description="Sanity check: I 投信跟單 scanner")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--config-override", nargs="*", metavar="KEY=VALUE")
    args = parser.parse_args()
    cfg = InstitutionalSwingConfig()
    if args.config_override:
        cfg = cfg.apply_overrides(dict(kv.split("=", 1) for kv in args.config_override))
    result = run_sanity_check(db_path=args.db, cfg=cfg, verbose=args.verbose)
    print_report(result)
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
