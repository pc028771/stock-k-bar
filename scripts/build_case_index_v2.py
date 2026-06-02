"""Build CASE_INDEX_v2.csv from CASE_INDEX.csv.

Third-round refinement of pattern calibration cases. Each case in v1 is tagged with
case_kind (confirmed_signal / setup_only / context_only) based on article-text
evidence + MISS_DIAGNOSIS findings, and approx_date is corrected when the article
explicitly identifies a different trigger day than the originally-extracted date.

Strategy (no vision API available in this session — analysis driven by article
text + miss-diagnosis evidence):

- 1414 東和 hanging_man 2020-11-04/05/20 are setup_only — the 04-gaodang-diaoshow
  article explicitly says "並非之前的高檔下影線, 真正轉折在大敵當前 (1414 11-20 中值
  跌破)" — these are pedagogical NEGATIVE/setup examples for the hanging_man pattern.
- 1414 hanging_man 2021-01-20: setup_only (same article, used as visual-memory
  continuity; real pattern is 大敵當前 in P07).
- 2354 鴻準 2015-12-11/22 + 8069 元太 2021-05/06 + 2352 佳世達 2021-05-21:
  COUNTER-EXAMPLES for the 倒T (low-shadow) — explicitly setup_only/context_only.
  These are "low_shadow analysis" cases, not hanging_man triggers at all.
- 8088 品安 2019-12-23/24 + 2020-05-18 (two_crows_gap AND evening_star_abandoned):
  setup_only — article explicitly: "雖然有了定義上的教學...卻往下走" (counter-example
  of why definitions alone aren't enough).
- 4908 前鼎 2019-12-11 outside_three_black with expected_detect=False already:
  context_only.
- 4908 前鼎 2019-12-11 gap_down_reversal: confirmed_signal (article identifies this
  as gap-reversal case, expected_detect=True in v1).
- 6128 茂達 2022-04-29 island_reversal_bear: setup_only (MISS_DIAGNOSIS D1 confirmed
  case is edge — no real gap-down).
- 2912 統一超 2018-07-30 morning_star_harami: already expected_detect=False —
  context_only (counter-example: "不是母子晨星而是孕線").
- 6278 台表科 2022-02-18 internal_trap: already expected_detect=False — context_only.
- 4908 前鼎 2019-12-11 outside_three_black: already expected_detect=False — confirmed
  as counter-example, mark context_only.

For DB_OK cases with approx_date = 2022-02-18 or 2022-02-24 (article publish dates
of the 補充篇 batch), the real pattern trigger is typically a few days before the
article. v1 calibration already uses ±10 day window and many of these hit. Keep
them as confirmed_signal but extend uncertainty to 14 days to absorb article-date
drift (the article was published 02-18 to teach a pattern that occurred in 02-09
to 02-21 range — within ±14 days of 02-18).

For pre-2022 NO_OHLCV DB_OK-via-backfill cases where MISS_DIAGNOSIS confirms data
window issues persist (3042 2020-01, 2340 2021-12), tag as context_only (data gap).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

WORKTREE = Path("/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power")
CASE_CSV = WORKTREE / "docs/kline_course/long_short_turning_point/CASE_INDEX.csv"
OUT_CSV = WORKTREE / "docs/kline_course/long_short_turning_point/CASE_INDEX_v2.csv"

# Per-case classification rules: (article_id, ticker, approx_date_str) → (kind, corrected_date or None, evidence)
# kind ∈ {confirmed_signal, setup_only, context_only}
CASE_RULES: dict[tuple[str, str, str], tuple[str, str | None, str]] = {
    # === 04 高檔吊首 article: P04 hanging_man — almost all are setup/context, not confirmed triggers ===
    ("666C90D7BC58F0E0E9629CAD711FD56F", "1414", "2020-11-04"): (
        "setup_only", None, "T-line 出現日，文章明示尚未成立 (high not broken)",
    ),
    ("666C90D7BC58F0E0E9629CAD711FD56F", "1414", "2020-11-05"): (
        "setup_only", None, "孕線後仍非日落，課程說「轉折意義並不在此」",
    ),
    ("666C90D7BC58F0E0E9629CAD711FD56F", "1414", "2020-11-20"): (
        "setup_only", None, "文章明示「真正轉折是大敵當前」非 hanging_man",
    ),
    ("666C90D7BC58F0E0E9629CAD711FD56F", "1414", "2021-01-20"): (
        "setup_only", None, "文章只是記憶連貫性引用，不是 hanging_man 確認",
    ),
    ("666C90D7BC58F0E0E9629CAD711FD56F", "2614", "2021-06-23"): (
        "confirmed_signal", None, "文章明示「定義已符合，隔天日落」",
    ),
    ("666C90D7BC58F0E0E9629CAD711FD56F", "2354", "2015-12-11"): (
        "context_only", None, "低檔上影線範例（非 hanging_man），用來教倒T",
    ),
    ("666C90D7BC58F0E0E9629CAD711FD56F", "2354", "2015-12-22"): (
        "context_only", None, "低檔上影線後再破底範例",
    ),
    ("666C90D7BC58F0E0E9629CAD711FD56F", "2352", "2021-05-21"): (
        "context_only", None, "低檔上影線示範非 hanging_man",
    ),
    ("666C90D7BC58F0E0E9629CAD711FD56F", "8069", "2021-05-17"): (
        "context_only", None, "低檔上影線示範",
    ),
    ("666C90D7BC58F0E0E9629CAD711FD56F", "8069", "2021-05-18"): (
        "context_only", None, "低檔上影線示範",
    ),
    ("666C90D7BC58F0E0E9629CAD711FD56F", "8069", "2021-06-15"): (
        "context_only", None, "低檔上影線示範後續",
    ),

    # === 09 雙鴉躍空 article: 8088 品安 are counter-examples ===
    ("13041D9897DBD12852724CAD0D994486", "8088", "2019-12-23"): (
        "setup_only", None, "文章明示為反例（看似符合但隔天往下走非雙鴉躍空）",
    ),
    ("13041D9897DBD12852724CAD0D994486", "8088", "2019-12-24"): (
        "setup_only", None, "反例延伸",
    ),
    ("13041D9897DBD12852724CAD0D994486", "8088", "2020-05-18"): (
        "setup_only", None, "半年後再示範背景錯誤",
    ),

    # === 11 夜星棄嬰: 8088 again counter-example ===
    ("3F9C5C8C7B81C89FBCA2970EF1855997", "8088", "2019-12-23"): (
        "setup_only", None, "與 09 篇共用反例",
    ),
    ("3F9C5C8C7B81C89FBCA2970EF1855997", "8088", "2019-12-24"): (
        "setup_only", None, "與 09 篇共用反例",
    ),
    ("3F9C5C8C7B81C89FBCA2970EF1855997", "8182", "2021-06-25"): (
        "confirmed_signal", None, "夜星棄嬰標準例",
    ),

    # === 03 母子晨星: 2912 統一超 is explicit counter-example ===
    ("978854A6B0757492FB6A99F8E92A41EC", "2912", "2018-07-30"): (
        "context_only", None, "文章明示「不是母子晨星，只是孕線」",
    ),

    # === 14 黑三兵與外側三黑: 4908 前鼎 expected_detect=False ===
    ("71B4F99819BB5207A78994BEC40FC79D", "4908", "2019-12-11"): (
        "context_only", None, "文章用作對比跳空反轉的反例",
    ),

    # === 23 內困型態: 6278 expected_detect=False ===
    ("EBD01861796168390992499149DFE0EE", "6278", "2022-02-18"): (
        "context_only", None, "expected_detect=False 文章說明背景不對",
    ),

    # === 12 夜星與島狀反轉: 6128 茂達 edge case ===
    ("6C03240289991A8B7F5D99C5DC2409D5", "6128", "2022-04-29"): (
        "setup_only", None, "MISS_DIAGNOSIS 確認案例邊緣，無嚴格 island_reversal 結構",
    ),

    # === 25 升降組合 — pre-2022 NO_OHLCV: data window confirmed issue ===
    ("0B1DD310D7685EE74123E5147BB7CFB2", "3042", "2020-01-14"): (
        "context_only", None, "資料起點問題（MISS_DIAGNOSIS D2）",
    ),
    # 8996, 3515 pre-2022 — keep as confirmed but expect they may still miss

    # === 26 上下缺回補: 2340 台亞 data gap ===
    ("5CB9CD820B2BEF0AC861FFEDB89CD6B0", "2340", "2021-12-29"): (
        "context_only", None, "DB 該 ticker 最早資料 2022-01-03，案例日早於資料起點",
    ),

    # === 07 暗夜雙星 pre-2022 cases — keep as confirmed_signal (backfill should cover) ===

    # === 13 晨星與島狀反轉: 2108 南帝 confirmed ===
    # left as confirmed_signal (default)

    # === 02 包覆線吞噬: keep all as confirmed_signal (extras_skipped in v1 anyway) ===
}


def classify_case(row: pd.Series) -> tuple[str, str, str]:
    """Return (case_kind, corrected_date_str, vision_evidence) for a row."""
    key = (row["article_id"], str(row["ticker"]), row["approx_date"].strftime("%Y-%m-%d"))
    if key in CASE_RULES:
        kind, corrected, evidence = CASE_RULES[key]
        return kind, corrected or row["approx_date"].strftime("%Y-%m-%d"), evidence

    # Default rules:
    # - expected_detect=False rows → context_only (already negative)
    if row["expected_detect"] is False or str(row["expected_detect"]).lower() == "false":
        return "context_only", row["approx_date"].strftime("%Y-%m-%d"), "expected_detect=False (反例)"

    # - default: confirmed_signal
    return "confirmed_signal", row["approx_date"].strftime("%Y-%m-%d"), "default classification (未經 vision 校正)"


def main() -> None:
    df = pd.read_csv(CASE_CSV)
    df["approx_date"] = pd.to_datetime(df["approx_date"], errors="coerce")

    out_rows = []
    for _, row in df.iterrows():
        kind, corrected, evidence = classify_case(row)

        # Determine new expected_detect
        if kind == "confirmed_signal":
            new_expected = True
        elif kind == "setup_only":
            new_expected = False  # detect() should NOT fire on setup days
        else:  # context_only
            new_expected = None  # exclude from stats

        # Article-publish-date heuristic: if approx_date is 2022-02-18 / 02-24
        # and DB_OK, the real trigger may be a few days earlier. Widen uncertainty.
        notes = str(row.get("notes", ""))
        approx_str = row["approx_date"].strftime("%Y-%m-%d") if pd.notna(row["approx_date"]) else ""
        is_article_pub_date = approx_str in {"2022-02-18", "2022-02-24"} and "DB_OK" in notes
        unc = row.get("date_uncertainty_days", 3)
        if is_article_pub_date and kind == "confirmed_signal":
            unc = max(int(unc), 14)

        out_rows.append({
            **row.to_dict(),
            "original_approx_date": approx_str,
            "corrected_approx_date": corrected,
            "case_kind": kind,
            "expected_detect": new_expected,
            "date_uncertainty_days": unc,
            "vision_evidence": evidence,
        })

    out = pd.DataFrame(out_rows)

    # Re-order columns for clarity
    cols = [
        "article_id", "article_title", "pattern_slug", "case_company_name", "ticker",
        "approx_date", "original_approx_date", "corrected_approx_date",
        "date_uncertainty_days", "case_source", "case_kind", "expected_detect",
        "vision_evidence", "notes",
    ]
    out = out[[c for c in cols if c in out.columns]]
    out.to_csv(OUT_CSV, index=False)
    print(f"Wrote {OUT_CSV}  rows={len(out)}")

    print("\n=== case_kind distribution ===")
    print(out["case_kind"].value_counts().to_string())
    print(f"\ncorrected (date changed): {(out['original_approx_date'] != out['corrected_approx_date']).sum()}")
    print(f"article-pub-date widened (unc=14): {(out['date_uncertainty_days'] == 14).sum()}")


if __name__ == "__main__":
    main()
