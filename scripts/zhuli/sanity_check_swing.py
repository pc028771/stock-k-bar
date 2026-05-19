"""Sanity check for A 大波段 swing_breakout scanner.

Validates the scanner against instructor cases from strategy-indicators.md §A.

⚠️ 注意：DB 目前只有 2024-2026 年的全量 bars 資料，但講師案例為 2021 年。
   若 DB 缺少歷史 bars，相關案例會標記為 SKIP（資料不足）而非 FAIL。
   需要先 backfill 全量 institutional_investors 才能做真正的族群密度驗證。

Instructor cases (from strategy-indicators.md §A):
    A1. 2002 中鋼 2021/03  — 族群性（鋼鐵）+ 技術面確認，三面齊備範例（正例）
    A2. 2002 中鋼 2021/06/30 — 上市投信買超第 1 名，6,305 張，族群：大成鋼、強茂、允強（正例）
    A3. 2409 群創 2021/03  — 帶量站上月線 + 空方缺口回補 + 雙重支撐（正例）
    A4. 2886 開發金 2021/03 — 月線季線上彎但股價距月線 > 5%，當時不符合理想距離（提示：dist > 5%）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# Path setup
_WORKTREE = Path(__file__).parent.parent.parent
_SCRIPTS_DIR = Path(__file__).parent.parent
_SYS_DIR = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_WORKTREE), str(_SCRIPTS_DIR), str(_SYS_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kline.bars import DEFAULT_DB_PATH, load_bars
from kline.features import add_features
from zhuli.config import SwingBreakoutConfig
from zhuli.entry.swing_breakout import detect, load_institutional_full, load_stock_info
from zhuli.features import add_zhuli_features

# ── 測試案例定義 ───────────────────────────────────────────────────────────────

CASES = [
    {
        "id": "A1",
        "ticker": "2002",
        "name": "中鋼",
        "date": "2021-03-09",  # 2021/03 族群性（鋼鐵）正例
        "expect": "signal",    # 應出現訊號
        "note": "族群性（鋼鐵）+ 技術面確認，三面齊備範例",
        "source": "Ch3-2 12:04 截圖",
        "cfg_override": {"require_sector_density": "false"},  # 只有 2002 被 backfill
    },
    {
        "id": "A2",
        "ticker": "2002",
        "name": "中鋼",
        "date": "2021-06-30",  # 投信買超第 1 名 6305 張
        "expect": "signal",
        "note": "上市投信買超第 1 名，6,305 張；族群：大成鋼、強茂、允強",
        "source": "HD vision Ch4-1 01:00",
        "cfg_override": {"require_sector_density": "false"},
    },
    {
        "id": "A3",
        "ticker": "2409",
        "name": "群創",
        "date": "2021-03-09",  # 帶量站上月線，空方缺口回補
        "expect": "signal",
        "note": "帶量站上月線 + 空方缺口回補 + 雙重支撐",
        "source": "Ch3-2 09:41 截圖",
        "cfg_override": {"require_sector_density": "false"},
    },
    {
        "id": "A4",
        "ticker": "2886",
        "name": "開發金",
        "date": "2021-03-09",  # 月線季線上彎但距月線 > 5%（負例：理想距離條件不符）
        "expect": "no_signal_with_dist_enforced",
        "note": "月線季線上彎，但股價距月線 > 5%，不符合理想距離條件（負例）",
        "source": "Ch3-2 05:21 截圖",
        "cfg_override": {
            "require_sector_density": "false",
            "enforce_dist_to_ma20": "true",  # 理想距離條件改為必要
        },
    },
]


# ── 測試執行 ───────────────────────────────────────────────────────────────────

def run_sanity_check(
    db_path: Path = DEFAULT_DB_PATH,
    cfg: SwingBreakoutConfig | None = None,
    verbose: bool = False,
) -> dict:
    """執行所有 sanity check cases，回傳結果 dict。

    Returns:
        dict with keys: passed, total, results (list of case dicts)
    """
    bars = load_bars(db_path=db_path)
    feats = add_features(bars)
    feats = add_zhuli_features(feats)
    inst_df = load_institutional_full(db_path)
    stock_info = load_stock_info(db_path)

    results = []
    for case in CASES:
        cid = case["id"]
        ticker = case["ticker"]
        date_str = case["date"]
        expect = case["expect"]
        overrides = case.get("cfg_override", {})

        # 建立 config
        case_cfg = SwingBreakoutConfig()
        case_cfg = case_cfg.apply_overrides(overrides)

        # 取該日 bars（先確認資料存在）
        date_ts = pd.Timestamp(date_str)
        date_feats = feats[feats["trade_date"] == date_ts]

        if date_feats.empty:
            result = "SKIP"
            reason = f"DB 無 {date_str} 的 bars 資料（需 backfill 歷史 bars）"
            passed = True  # SKIP 不算失敗
        else:
            # 過濾到該日
            ticker_in_date = ticker in date_feats["ticker"].values
            if not ticker_in_date:
                result = "SKIP"
                reason = f"{ticker} 在 {date_str} 無 bars 資料"
                passed = True
            else:
                signals = detect(
                    date_feats,
                    cfg=case_cfg,
                    inst_df=inst_df,
                    stock_info=stock_info,
                    db_path=db_path,
                )
                ticker_signals = signals[signals["ticker"] == ticker] if not signals.empty else pd.DataFrame()

                if expect == "signal":
                    if not ticker_signals.empty:
                        result = "PASS"
                        reason = f"找到訊號（inst_net={ticker_signals.iloc[0].get('inst_net', 0):.0f} 張）"
                        passed = True
                    else:
                        result = "FAIL"
                        reason = "預期有訊號但未找到"
                        passed = False
                elif expect == "no_signal_with_dist_enforced":
                    if ticker_signals.empty:
                        result = "PASS"
                        reason = "正確：距月線 > 5% 時強制過濾，訊號不出現"
                        passed = True
                    else:
                        dist = ticker_signals.iloc[0].get("dist_to_ma20_pct", 0)
                        result = "FAIL"
                        reason = f"預期無訊號但找到（dist_to_ma20_pct={dist:.4f}）"
                        passed = False
                else:
                    result = "SKIP"
                    reason = f"未知的 expect 類型: {expect}"
                    passed = True

        case_result = {
            "id": cid,
            "ticker": ticker,
            "name": case["name"],
            "date": date_str,
            "expect": expect,
            "result": result,
            "passed": passed,
            "reason": reason,
            "note": case["note"],
            "source": case["source"],
        }
        results.append(case_result)

        if verbose:
            status = "✅" if result == "PASS" else ("⚠️" if result == "SKIP" else "❌")
            print(f"  [{cid}] {status} {ticker} {case['name']} {date_str}: {result} — {reason}")

    total = len(results)
    pass_count = sum(1 for r in results if r["result"] == "PASS")
    skip_count = sum(1 for r in results if r["result"] == "SKIP")
    fail_count = sum(1 for r in results if r["result"] == "FAIL")
    passed = fail_count == 0

    return {
        "passed": passed,
        "total": total,
        "pass_count": pass_count,
        "skip_count": skip_count,
        "fail_count": fail_count,
        "results": results,
    }


def print_report(result: dict) -> None:
    """Print sanity check report."""
    print(f"\n{'='*60}")
    print("A 大波段 swing_breakout — Sanity Check Report")
    print(f"{'='*60}")
    print(f"總計: {result['total']} cases | "
          f"通過: {result['pass_count']} | "
          f"跳過: {result['skip_count']} | "
          f"失敗: {result['fail_count']}")
    print()

    for r in result["results"]:
        status = "PASS" if r["result"] == "PASS" else r["result"]
        print(f"[{r['id']}] {r['ticker']} {r['name']} {r['date']}")
        print(f"      期望: {r['expect']} | 結果: {status}")
        print(f"      說明: {r['reason']}")
        print(f"      備註: {r['note']}")
        print(f"      來源: {r['source']}")
        print()

    if result["passed"]:
        print("✅ Sanity check 通過（無失敗 case）")
    else:
        print("❌ Sanity check 失敗，請檢查上方 FAIL cases")

    print()
    print("⚠️  注意：SKIP cases 表示 DB 缺乏歷史資料（2021年），")
    print("    需要先 backfill 全量 institutional_investors 才能驗證族群密度。")
    print("    SKIP ≠ 功能錯誤。")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        prog="sanity_check_swing",
        description="A 大波段 swing_breakout scanner — 講師案例 sanity check",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH,
                        help="SQLite DB 路徑")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="詳細輸出")
    args = parser.parse_args()

    result = run_sanity_check(db_path=args.db, verbose=args.verbose)
    print_report(result)
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
