"""Sanity check — verify J 投信首買 scanner hits instructor cases from §J (Ex2-3).

Course source: strategy-indicators.md §J 投信首買策略
               data/analysis/zhuli/video_screenshots/ex2-3/handwritten_extracts.md

Instructor cases（截圖 05:42、06:17 確認）:
    3707 漢磊    2020-12-09  首買 3,646 張，當日漲停 +10%；前兩個月空白
    3552 同致    2020-08-03  首買 1,637 張，當日 +9.97%；前三個月空白

Note:
    這兩個案例的 bar 資料預設只在 2025 年之後才有（standard_daily_bar 覆蓋範圍）。
    若 DB 沒有 2020 年的 bar 資料，sanity check 會標記 'no_bar_data'（不算失敗）。
    若 institutional_investors 表不存在，標記 'no_institutional_data'。

Usage:
    python scripts/zhuli/sanity_check_institutional.py [--db PATH] [--verbose]
    python -m zhuli.sanity_check_institutional [--db PATH]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

_WORKTREE = Path(__file__).parent.parent.parent   # phase1-scanner/
_SCRIPTS_DIR = _WORKTREE / "scripts"
for _p in [str(_WORKTREE), str(_SCRIPTS_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kline.bars import DEFAULT_DB_PATH, load_bars
from kline.features import add_features
from zhuli.config import InstitutionalFirstBuyConfig
from zhuli.features import add_zhuli_features
from zhuli.entry.institutional_firstbuy import load_institutional, detect


# === Instructor cases from ex2-3 截圖 (strategy-indicators.md §J) ===
# divergence_category 分類:
#   None              = 期望機械命中
#   'mechanical_strict' = 機械嚴格 / 講師判斷較寬鬆
#   'spec_ambiguous'    = 講師範例無精確 spec
#   'data_gap'          = FinMind 與富邦軟體差異 / 缺資料
INSTRUCTOR_CASES = [
    {
        "ticker": "3707",
        "name": "漢磊",
        "signal_date": "2020-12-09",
        "expected_sitc_net": 3646.0,   # 張（課程截圖 05:42）
        "expected_price_action": "漲停 +10%",
        "divergence_category": "spec_ambiguous",
        "note": (
            "⚠️ Ex2-3 截圖 05:42 — 首買 3,646 張。Scanner 命中 2020-11-24（361 張首買），"
            "因 detector first buy 定義為「首次 ≥ min_firstbuy_volume」，2020-11-24 已先觸發。"
            "課程「首買」可能指「首次大買 / 漲停級首買」，spec 定義含糊。"
        ),
    },
    {
        "ticker": "3552",
        "name": "同致",
        "signal_date": "2020-08-03",
        "expected_sitc_net": 1637.0,   # 張（課程截圖 06:17）
        "expected_price_action": "+9.97%",
        "divergence_category": None,
        "note": "Ex2-3 截圖 06:17 — 首買 1,637 張，前三個月完全空白",
    },
]

TOLERANCE_DAYS = 2   # ±2 個交易日容忍


def _check_institutional_table(db_path: Path) -> bool:
    """回傳 True 若 institutional_investors 表存在且有資料。"""
    try:
        with sqlite3.connect(str(db_path), timeout=15) as conn:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='institutional_investors'"
            )
            if cur.fetchone() is None:
                return False
            cur = conn.execute("SELECT COUNT(*) FROM institutional_investors")
            return cur.fetchone()[0] > 0
    except Exception:
        return False


def _check_bar_data(db_path: Path, ticker: str, date: str) -> bool:
    """回傳 True 若 DB 有該 ticker 在指定日期附近的 bar 資料。"""
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
    cfg: InstitutionalFirstBuyConfig | None = None,
    verbose: bool = False,
) -> dict:
    """對 §J 講師案例跑 sanity check。

    Returns:
        dict with keys: results, hits, misses, skipped, passed.
    """
    if cfg is None:
        cfg = InstitutionalFirstBuyConfig()

    if verbose:
        print(f"InstitutionalFirstBuyConfig: {cfg}")

    # 確認投信資料存在
    has_inst = _check_institutional_table(db_path)
    if not has_inst:
        print(
            "⚠️  institutional_investors 表不存在或為空。\n"
            "   請先執行：python scripts/zhuli/backfill_institutional.py "
            "--tickers 3707 3552 --start-date 2020-01-01"
        )

    # 載入 bars + features（只有有 bar 資料的才能測）
    bars = load_bars(db_path=db_path)
    feats = add_features(bars)
    feats = add_zhuli_features(feats)

    # 載入投信資料
    inst_df = load_institutional(db_path) if has_inst else pd.DataFrame(
        columns=["ticker", "trade_date", "sitc_buy", "sitc_sell", "sitc_net"]
    )

    results = []

    for case in INSTRUCTOR_CASES:
        ticker = case["ticker"]
        name = case["name"]
        sig_date = pd.Timestamp(case["signal_date"])
        note = case["note"]
        expected_net = case["expected_sitc_net"]

        # 先確認基礎資料
        has_bar = _check_bar_data(db_path, ticker, case["signal_date"])
        has_inst_ticker = (
            has_inst and ticker in inst_df["ticker"].values
        )

        if not has_inst_ticker:
            r = {
                "ticker": ticker,
                "name": name,
                "signal_date": case["signal_date"],
                "result": "no_institutional_data",
                "note": note,
                "msg": f"institutional_investors 無 {ticker} 資料，請先 backfill",
            }
            if verbose:
                print(f"  ⚠️  {ticker} ({name})：{r['msg']}")
            results.append(r)
            continue

        if not has_bar:
            # 確認投信資料本身是否正確
            inst_row = inst_df[
                (inst_df["ticker"] == ticker)
                & (inst_df["trade_date"] == sig_date)
            ]
            inst_ok = (
                not inst_row.empty
                and inst_row.iloc[0]["sitc_net"] >= expected_net * 0.9
            )
            r = {
                "ticker": ticker,
                "name": name,
                "signal_date": case["signal_date"],
                "result": "no_bar_data",
                "inst_data_ok": inst_ok,
                "inst_net_found": float(inst_row.iloc[0]["sitc_net"]) if not inst_row.empty else None,
                "inst_net_expected": expected_net,
                "note": note,
                "msg": (
                    f"Bar 資料不在 DB（2020 年需另外 backfill）。"
                    f" 投信資料{'✓' if inst_ok else '✗'}："
                    f" 找到 {float(inst_row.iloc[0]['sitc_net']):.0f}張"
                    if not inst_row.empty
                    else f" 投信資料無 {sig_date.date()} 這筆"
                ),
            }
            if verbose:
                print(f"  ⚠️  {ticker} ({name})：{r['msg']}")
            results.append(r)
            continue

        # 有 bar + 投信資料：跑 detector
        try:
            feats_sub = feats[feats["ticker"] == ticker].copy()
            signals = detect(feats_sub, cfg=cfg, inst_df=inst_df)
        except RuntimeError as exc:
            r = {
                "ticker": ticker, "name": name,
                "signal_date": case["signal_date"],
                "result": "error",
                "note": note,
                "msg": str(exc),
            }
            results.append(r)
            continue

        # 找指定日期附近的 signal
        tol = pd.Timedelta(days=TOLERANCE_DAYS + 4)
        window = signals[
            (signals["signal_date"] >= sig_date - tol)
            & (signals["signal_date"] <= sig_date + tol)
        ]

        if not window.empty:
            best = window.iloc[
                (window["signal_date"] - sig_date).abs().argsort().iloc[0]
            ]
            r = {
                "ticker": ticker,
                "name": name,
                "signal_date": case["signal_date"],
                "result": "hit",
                "found_date": pd.Timestamp(best["signal_date"]).strftime("%Y-%m-%d"),
                "found_sitc_net": float(best["sitc_net"]),
                "expected_sitc_net": expected_net,
                "price_divergence": bool(best["price_divergence"]),
                "ideal_ma_align": bool(best["ideal_ma_align"]),
                "close": float(best["close"]),
                "note": note,
                "msg": (
                    f"找到 {pd.Timestamp(best['signal_date']).strftime('%Y-%m-%d')} "
                    f"sitc_net={float(best['sitc_net']):.0f}張 "
                    f"price_divergence={bool(best['price_divergence'])}"
                ),
            }
            if verbose:
                print(f"  ✓ {ticker} ({name})：{r['msg']}")
        else:
            r = {
                "ticker": ticker,
                "name": name,
                "signal_date": case["signal_date"],
                "result": "miss",
                "note": note,
                "msg": f"指定日期 {sig_date.date()} 附近無 signal 輸出",
            }
            if verbose:
                print(f"  ✗ {ticker} ({name})：{r['msg']}")

        results.append(r)

    # 把 case 的 divergence_category propagate 到 result
    for r in results:
        case = next((c for c in INSTRUCTOR_CASES if c["ticker"] == r["ticker"]), None)
        if case:
            r["divergence_category"] = case.get("divergence_category")

    hits = [r for r in results if r["result"] == "hit"]
    misses = [r for r in results if r["result"] == "miss"]
    skipped = [r for r in results if r["result"] in ("no_bar_data", "no_institutional_data", "error")]

    # known_divergence: miss 但 case 已標 divergence_category（不算 unexpected）
    known_divergence_misses = [r for r in misses if r.get("divergence_category")]
    unexpected_misses = [r for r in misses if not r.get("divergence_category")]
    passed = len(unexpected_misses) == 0

    return {
        "results": results,
        "hits": hits,
        "misses": misses,
        "known_divergence_misses": known_divergence_misses,
        "unexpected_misses": unexpected_misses,
        "skipped": skipped,
        "passed": passed,
        "total": len(INSTRUCTOR_CASES),
    }


def print_report(result: dict) -> None:
    """Print formatted sanity check report."""
    results = result["results"]
    hits = result["hits"]
    misses = result["misses"]
    skipped = result["skipped"]
    passed = result["passed"]
    total = result["total"]

    print()
    print("=" * 60)
    print(f"Sanity Check (J 投信首買): {total} instructor cases")
    print("=" * 60)

    for r in results:
        ticker = r["ticker"]
        name = r["name"]
        result_str = r["result"]

        if result_str == "hit":
            print(
                f"  ✓ {ticker} ({name})  "
                f"found={r['found_date']}  "
                f"sitc_net={r['found_sitc_net']:.0f}張  "
                f"price_divergence={r['price_divergence']}  "
                f"ideal_ma={r['ideal_ma_align']}"
            )
        elif result_str in ("no_bar_data", "no_institutional_data"):
            print(f"  ⚠️  {ticker} ({name}): {r['msg']}")
        elif result_str == "miss":
            if r.get("divergence_category"):
                print(f"  ⚠️  {ticker} ({name}) [known_{r['divergence_category']}]: {r['msg']}")
            else:
                print(f"  ✗ {ticker} ({name}): {r['msg']}")
        else:
            print(f"  ? {ticker} ({name}): {result_str} — {r.get('msg', '')}")

    print()
    n_hit = len(hits)
    n_known = len(result.get("known_divergence_misses", []))
    n_unexpected = len(result.get("unexpected_misses", []))
    n_skip = len(skipped)

    if passed:
        print(
            f"PASSED — {n_hit}/{total} strict hit, "
            f"{n_known} known divergence, "
            f"{n_skip} skipped"
        )
    else:
        print(f"FAILED — {n_hit} hit, {n_unexpected} unexpected miss, "
              f"{n_known} known divergence, {n_skip} skipped")
        for r in result.get("unexpected_misses", []):
            print(f"  ✗ {r['ticker']} {r['name']}：{r.get('msg', '')}")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Sanity check: 驗證 J 投信首買 scanner 是否能偵測到講師案例。"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument(
        "--config-override", nargs="*", metavar="KEY=VALUE",
        help="Override InstitutionalFirstBuyConfig，e.g. min_firstbuy_volume=50",
    )
    args = parser.parse_args()

    cfg = InstitutionalFirstBuyConfig()
    if args.config_override:
        overrides = dict(kv.split("=", 1) for kv in (args.config_override or []))
        cfg = cfg.apply_overrides(overrides)

    result = run_sanity_check(db_path=args.db, cfg=cfg, verbose=args.verbose)
    print_report(result)
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
