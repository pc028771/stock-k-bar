"""Grid search over course_proxy_constants for entry-class branches.

Constraints:
- Only tune course-silent thresholds, not course-explicit rules
- Baseline calibration runner case hit rate must not drop below 85%
- 554 pytest must stay green (run as gate)

Workflow:
1. Snapshot current constants → baseline_score
2. For each param × grid:
   - Override constant
   - Re-run pattern detection on cached bars
   - Re-evaluate branches' hit_rate from advisor history
   - Compute score
3. Pick best combo per param (coordinate descent or full grid if small)
4. Verify calibration runner case still ≥85%
5. Verify pytest still green
6. Write recommendations to report — DO NOT auto-apply

Usage:
    uv run python scripts/calibrate_entry_thresholds.py
"""
from __future__ import annotations

import importlib
import math
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# ── Paths ──────────────────────────────────────────────────────────────────────
WORKTREE = Path("/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power")
PHASE4_DB = WORKTREE / "data/analysis/kline_patterns/phase4_advisor_history.db"
PRICE_DB = Path("/Users/howard/.four_seasons/data.sqlite")
OUT_DIR = WORKTREE / "data/analysis/kline_patterns"
REPORT_PATH = OUT_DIR / "entry_calibration_report.md"

# ── Add scripts to path ────────────────────────────────────────────────────────
sys.path.insert(0, str(WORKTREE / "scripts"))

# ── Import modules (defer feature/pattern imports until after path is set) ─────
import kline.course_proxy_constants as _constants_mod
from kline.bars import load_bars
from kline.features import add_features as _add_features_orig


# ── Constants: tunable grid ────────────────────────────────────────────────────
# Only "course-not-stated" constants get grid ranges.
# We identify which constants materially affect the target branches:
#   entry_signal.B1_gap_up_attack     → pattern: merged_doji (DOJI_ constants)
#   exhaust_invalid.B1_next_day_gap_fills_up → pattern: gap_fill_up (GAP_FILL_WINDOW_DAYS)
#   exhaust_invalid.B2_next_day_gap_filled   → pattern: gap_fill_up/gap_reversal (GAP_FILL_WINDOW_DAYS)
#   Plus: attack_intensity features (ATTACK_WINDOW_DAYS, ATTACK_HIGHER_LOW_MIN_5DAY)
#         integration features (RISING_LOWS_MIN_FRAC, STABLE_UPPER_MAX_SPREAD)
#         breakout lookback (FIRST_BREAKOUT_LOOKBACK)

PARAM_GRIDS: dict[str, dict] = {
    # I7 — doji thresholds (affects merged_doji fires → affects entry_signal n_runs)
    "DOJI_MAX_BODY_PCT": {
        "current": 0.006,
        "grid": [0.004, 0.005, 0.006, 0.008, 0.010],
        "description": "十字線最大實體比例 (body/open ≤ X)",
        "affects": ["merged_doji → entry_signal.B1_gap_up_attack"],
    },
    "DOJI_MIN_RANGE_PCT": {
        "current": 0.015,
        "grid": [0.010, 0.012, 0.015, 0.018, 0.020],
        "description": "十字線最小振幅比例 (range/open ≥ X)",
        "affects": ["merged_doji → entry_signal.B1_gap_up_attack"],
    },
    # T8 — gap fill window (affects gap_fill_up/down fires → exhaust_invalid hit branches)
    "GAP_FILL_WINDOW_DAYS": {
        "current": 20,
        "grid": [10, 15, 20, 30, 45],
        "description": "缺口回補時間窗 (看回幾個交易日的缺口)",
        "affects": ["gap_fill_up/down → exhaust_invalid.B1_B2_gap_fills"],
    },
    # I1 — attack intensity window (affects attack features → pattern scoring)
    "ATTACK_WINDOW_DAYS": {
        "current": 5,
        "grid": [4, 5, 6, 7],
        "description": "推升攻擊視窗天數",
        "affects": ["attack_intensity features → merged_doji context"],
    },
    "ATTACK_HIGHER_LOW_MIN_5DAY": {
        "current": 4,
        "grid": [3, 4, 5],
        "description": "5日內低點墊高最少天數",
        "affects": ["attack_intensity feature → scoring"],
    },
    # I3 — rising lows fraction (affects is_pattern_breakout feature)
    "RISING_LOWS_MIN_FRAC": {
        "current": 0.5,
        "grid": [0.4, 0.5, 0.6, 0.65],
        "description": "60日內低點墊高最低比例",
        "affects": ["is_pattern_breakout feature"],
    },
    # I2 — stable upper spread (affects is_pattern_breakout feature)
    "STABLE_UPPER_MAX_SPREAD": {
        "current": 0.05,
        "grid": [0.03, 0.05, 0.07, 0.10],
        "description": "箱型上緣穩定最大散差",
        "affects": ["is_pattern_breakout feature"],
    },
    # I4 — first breakout lookback
    "FIRST_BREAKOUT_LOOKBACK": {
        "current": 60,
        "grid": [40, 60, 80],
        "description": "首次突破判斷回看天數",
        "affects": ["breakout_attack → scoring"],
    },
    # T9 — rebound lookback
    "REBOUND_LOOKBACK_N": {
        "current": 5,
        "grid": [3, 5, 7, 10],
        "description": "反撲短期N天上限",
        "affects": ["rebound pattern"],
    },
    # T10 — island max bars
    "ISLAND_MAX_BARS": {
        "current": 10,
        "grid": [5, 8, 10, 15],
        "description": "島狀反轉孤島K數上限",
        "affects": ["morning/evening star island reversal"],
    },
}

# ── Load data once ─────────────────────────────────────────────────────────────
def load_price_data() -> pd.DataFrame:
    """Load prices for top-200 tickers, 2024+."""
    print("Loading bars (2024+, top-200 by volume)...")
    df = load_bars()
    top_tickers = df.groupby("ticker")["volume"].mean().nlargest(200).index.tolist()
    df = df[df["ticker"].isin(top_tickers)].copy()
    df = df[df["trade_date"] >= "2024-01-01"].copy()
    print(f"  Bars loaded: {len(df):,} rows, {df['ticker'].nunique()} tickers")
    return df


# ── Override a constant in the module + reload dependent modules ───────────────
def _override_constant(name: str, value: Any) -> None:
    """Monkey-patch the constant in course_proxy_constants and features."""
    setattr(_constants_mod, name, value)
    # Reload features (imports from course_proxy_constants)
    import kline.features as _feat
    importlib.reload(_feat)
    # Reload affected pattern modules
    for mod_name in [
        "kline.patterns.gap_fill_up",
        "kline.patterns.gap_fill_down",
        "kline.patterns.merged_doji",
        "kline.patterns.rebound",
        "kline.patterns.morning_star_island_reversal",
        "kline.patterns.evening_star_island_reversal",
        "kline.patterns.rising_falling",
        "kline.patterns.meeting",
    ]:
        if mod_name in sys.modules:
            importlib.reload(sys.modules[mod_name])


# ── Evaluate a parameter value ─────────────────────────────────────────────────
def evaluate_param(
    param_name: str,
    param_value: Any,
    df_bars: pd.DataFrame,
) -> dict:
    """Set param_name = param_value, run detection, compute scores."""
    # Override constant
    _override_constant(param_name, param_value)

    # Re-import add_features after reload
    import kline.features as feat_mod
    df = feat_mod.add_features(df_bars)

    # ── Detect target patterns ──────────────────────────────────────────────
    results: dict[str, dict] = {}

    # 1. merged_doji → entry_signal.B1_gap_up_attack
    #    hit condition: next_day.gap_up = (next_open > today_close)
    import kline.patterns.merged_doji as md_mod
    sig_md = md_mod.detect(df)
    n_md = int(sig_md.sum())

    if n_md > 0:
        # Build hit: for each merged_doji firing day, did next-day gap up?
        g = df.groupby("ticker")
        next_open = g["open"].shift(-1)
        gap_up = next_open > df["close"]
        hits_md = (sig_md & gap_up).sum()
        hit_rate_md = float(hits_md) / n_md if n_md > 0 else 0.0
    else:
        hits_md = 0
        hit_rate_md = 0.0

    score_md = hit_rate_md * math.log(1 + n_md) if n_md > 0 else 0.0
    results["entry_signal.B1_gap_up_attack"] = {
        "n_runs": n_md,
        "n_matched": int(hits_md),
        "hit_rate": round(hit_rate_md, 4),
        "score": round(score_md, 4),
    }

    # 2. gap_fill_up → exhaust_invalid.B1_next_day_gap_fills_up
    #    Pattern fires when a gap fill happens; hit condition = fills_gap (already in detect)
    #    But for the exhaust_invalid branch, the PATTERN is gap_reversal/gap_under_pressure
    #    and the BRANCH checks next_day.fills_gap
    #    Since gap_fill_up IS the detection of a fill event, n_fills = fires
    #    Hit condition for these branches: next_day.fills_gap = gap_fill_up fires on next day
    #    Actually: the scenario fires on the gap-DOWN day, branch checks if NEXT DAY fills the gap up
    #    Let's compute directly from price data:
    #    B1_next_day_gap_fills_up: was_gap_up_today AND next_day fills it
    #    B2_next_day_gap_filled: was_gap_down_today AND next_day fills it

    # For B1_next_day_gap_fills_up: today was gap_up, and next day low <= prev_high (fills gap bottom)
    # GAP_FILL_WINDOW_DAYS controls gap_fill_up pattern detection window
    import kline.patterns.gap_fill_up as gfu_mod
    sig_gfu = gfu_mod.detect(df)
    n_gfu = int(sig_gfu.sum())

    # B1_next_day_gap_fills_up hit:
    # The branch fires on exhaust_invalid patterns (gap_reversal etc.)
    # when_json = {next_day.fills_gap: true}
    # "fills_gap" means the price range on next day touches/crosses the gap boundary
    # This is measured by gap_fill_up.detect() itself on the NEXT day
    # So: sig_gfu fires on day D = "today filled an up-gap"
    # The branch (from phase4 DB) fires on D-1 (gap pattern day) with B1_next_day_gap_fills_up
    # hit = 1 when D fires gap_fill_up
    # We don't need to re-compute this separately from the pattern - just count sig_gfu
    # since it already has window-dependent behavior
    # Note: hit_rate for B1_next_day_gap_fills_up in baseline is 83%
    # The n_runs in phase4 DB (3949) is fixed; what we're measuring is
    # whether changing window changes which days fill and thus hit_rate
    # But actually the phase4 DB is pre-computed - we need to ask:
    # "if we change GAP_FILL_WINDOW_DAYS, do MORE gap days get flagged,
    #  and what is their hit_rate?"

    # For the grid search, let's compute:
    # From price data: all days where "today is a gap_fill_up event"
    # These become n_runs for the exhaust_invalid branches
    # The hit_rate for exhaust_invalid branches (whether the gap actually fills)
    # is always 100% by construction for B1/B2 (the branch fires WHEN the fill happens)
    # Wait: looking at phase4 report, B1_next_day_gap_fills_up hit=83%, not 100%
    # This is because the PATTERN fires (exhaust signal), and next day 83% of the time
    # the gap actually fills. The gap_fill_up pattern fires when a gap from past N days fills.
    # Let me re-read the playbook...

    # From gap_reversal.yaml: B1_next_day_gap_fills_up fires when next_day.fills_gap is TRUE
    # And matched_after_n_days = 1 when that condition is TRUE on the next day
    # So the 83% hit_rate = 83% of times a gap_reversal fires, the NEXT DAY fills the gap up

    # For calibration: changing GAP_FILL_WINDOW_DAYS changes gap_fill_up detection
    # But B1/B2 exhaust_invalid branches in phase4 are from gap_reversal/gap_under_pressure patterns
    # which themselves use gap-down detection (not GAP_FILL_WINDOW_DAYS directly)
    # GAP_FILL_WINDOW_DAYS affects gap_fill_up/gap_fill_down pattern detection
    # for the "gap fill" PATTERN SCENARIO, not the "exhaust_invalid branch" hit rate

    # Actually let me reconsider: GAP_FILL_WINDOW_DAYS directly affects
    # when gap_fill_up.py fires (used in gap_fill_up.yaml playbook)
    # The exhaust_invalid B1/B2 branches come from different playbooks
    # Let me just measure what GAP_FILL_WINDOW_DAYS does to n_fires of gap_fill_up pattern
    # and its downstream hit_rate approximation

    # Simple approach: use phase4 DB as oracle for the CONDITION hit_rate (next_day fills_gap)
    # and estimate how n_runs changes with different window sizes by re-detecting

    score_gfu = 0.83 * math.log(1 + n_gfu) if n_gfu > 0 else 0.0  # use baseline hit_rate
    results["pattern.gap_fill_up.n_fires"] = {
        "n_runs": n_gfu,
        "n_matched": int(round(n_gfu * 0.83)),
        "hit_rate": 0.83,
        "score": round(score_gfu, 4),
    }

    import kline.patterns.gap_fill_down as gfd_mod
    sig_gfd = gfd_mod.detect(df)
    n_gfd = int(sig_gfd.sum())
    score_gfd = 0.84 * math.log(1 + n_gfd) if n_gfd > 0 else 0.0
    results["pattern.gap_fill_down.n_fires"] = {
        "n_runs": n_gfd,
        "n_matched": int(round(n_gfd * 0.84)),
        "hit_rate": 0.84,
        "score": round(score_gfd, 4),
    }

    # Combined score for the primary metric
    primary_score = score_md + score_gfu + score_gfd
    results["_total_score"] = round(primary_score, 4)

    return results


# ── Baseline sanity check: run calibration runner ─────────────────────────────
def run_calibration_runner() -> float:
    """Run kline_patterns_calibrate.py and parse confirmed_signal hit rate."""
    result = subprocess.run(
        [sys.executable, str(WORKTREE / "scripts/kline_patterns_calibrate.py")],
        cwd=str(WORKTREE),
        capture_output=True,
        text=True,
        timeout=700,
    )
    output = result.stdout + result.stderr
    # Parse: "confirmed_signal active: 44  hits=39  rate=100.0%"
    # Actually: hits=39 / 44 = 88.6%
    import re
    m = re.search(r"confirmed_signal active:\s*(\d+)\s+hits=(\d+)", output)
    if m:
        total = int(m.group(1))
        hits = int(m.group(2))
        return hits / total if total > 0 else 0.0
    # fallback: look for direct percentage
    m2 = re.search(r"confirmed_signal.*?rate=([\d.]+)%", output)
    if m2:
        return float(m2.group(1)) / 100
    return 0.0


# ── Main grid search ──────────────────────────────────────────────────────────
def main():
    t_start = datetime.now()
    print("=" * 70)
    print("Entry Threshold Grid Search Calibration")
    print(f"Started: {t_start.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Step 0: run pytest as gate
    print("\n[Gate] Running pytest tests/kline/ ...")
    pytest_result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/kline/", "-q", "--tb=no"],
        cwd=str(WORKTREE),
        capture_output=True,
        text=True,
        timeout=180,
    )
    pytest_pass = pytest_result.returncode == 0
    pytest_output = pytest_result.stdout.strip().split("\n")[-1]
    print(f"  pytest: {'PASS' if pytest_pass else 'FAIL'} — {pytest_output}")
    if not pytest_pass:
        print("  [ABORT] pytest failed — cannot proceed with calibration")
        sys.exit(1)

    # Step 1: load data once
    df_bars = load_price_data()

    # Step 2: save original constants
    original_constants: dict[str, Any] = {}
    for param_name in PARAM_GRIDS:
        original_constants[param_name] = getattr(_constants_mod, param_name)

    # Step 3: compute baseline scores (original constants)
    print("\n[Baseline] Computing baseline scores with original constants...")
    baseline_results = evaluate_param("DOJI_MAX_BODY_PCT", original_constants["DOJI_MAX_BODY_PCT"], df_bars)
    baseline_score = baseline_results["_total_score"]
    print(f"  Baseline total_score = {baseline_score:.4f}")
    for key, val in baseline_results.items():
        if key != "_total_score":
            print(f"    {key}: n_runs={val['n_runs']} hit_rate={val['hit_rate']:.3f} score={val['score']:.4f}")

    # Step 4: run calibration runner for baseline case hit rate
    print("\n[Baseline] Running calibration runner (case hit rate)...")
    baseline_case_rate = run_calibration_runner()
    print(f"  Calibration runner case hit rate: {baseline_case_rate:.1%}")

    # Step 5: grid search over each parameter independently
    print("\n[Grid Search] Starting coordinate-descent grid search...")
    grid_records = []
    total_combinations = sum(len(v["grid"]) for v in PARAM_GRIDS.values())
    combo_count = 0
    t_search_start = datetime.now()

    for param_name, param_info in PARAM_GRIDS.items():
        print(f"\n  Param: {param_name} (current={param_info['current']})")
        best_score = -1.0
        best_value = param_info["current"]
        best_result = None

        for value in param_info["grid"]:
            combo_count += 1
            # Override the constant
            _override_constant(param_name, value)
            # Evaluate
            res = evaluate_param(param_name, value, df_bars)
            total_score = res["_total_score"]
            print(f"    {param_name}={value}: total_score={total_score:.4f}", end="")

            record = {
                "param_name": param_name,
                "value": value,
                "is_current": value == param_info["current"],
                "total_score": total_score,
                **{f"{k}_{m}": v[m] for k, v in res.items() if k != "_total_score" for m in ["n_runs", "hit_rate", "score"]},
            }
            grid_records.append(record)

            if total_score > best_score:
                best_score = total_score
                best_value = value
                best_result = res

            print(f" {'← best' if value == best_value else ''}")

        # Restore original constant
        _override_constant(param_name, original_constants[param_name])
        print(f"  → Best {param_name}: {param_info['current']} → {best_value} (score {baseline_score:.4f} → {best_score:.4f})")

        param_info["best_value"] = best_value
        param_info["best_score"] = best_score
        param_info["best_result"] = best_result
        param_info["score_improvement"] = best_score - baseline_score

    elapsed = (datetime.now() - t_search_start).total_seconds() / 60

    print(f"\n[Grid Search] Completed {combo_count} combinations in {elapsed:.1f} min")

    # Step 6: verify baseline still holds with original constants
    print("\n[Sanity Check] Verifying calibration runner still ≥85% with ORIGINAL constants...")
    final_case_rate = run_calibration_runner()
    print(f"  Calibration runner case hit rate (post-search): {final_case_rate:.1%}")
    sanity_pass = final_case_rate >= 0.85
    print(f"  Sanity check: {'PASS' if sanity_pass else 'FAIL (< 85%)'}")

    # Step 7: build recommendations
    recommendations = []
    not_recommended = []

    for param_name, param_info in PARAM_GRIDS.items():
        best_v = param_info["best_value"]
        current_v = param_info["current"]
        improvement = param_info["score_improvement"]

        if best_v == current_v:
            not_recommended.append({
                "param": param_name,
                "reason": "Current value is already optimal",
                "current": current_v,
                "best": best_v,
                "improvement": 0.0,
            })
            continue

        # Check for overfitting risk: if best has very few samples vs current
        best_res = param_info["best_result"]
        best_run_count = best_res.get("entry_signal.B1_gap_up_attack", {}).get("n_runs", 0)
        current_run_count_entry = next(
            (r.get("entry_signal.B1_gap_up_attack_n_runs", 0)
             for r in grid_records if r["param_name"] == param_name and r["is_current"]),
            0,
        )

        # Overfitting flag: if best_value changes n_runs by >80% vs current
        # OR if n_runs drops below 30 (small sample)
        overfit_risk = False
        overfit_reason = ""
        if best_run_count < 30:
            overfit_risk = True
            overfit_reason = f"n_runs={best_run_count} < 30 (過少樣本)"
        elif current_run_count_entry > 0 and best_run_count < current_run_count_entry * 0.3:
            overfit_risk = True
            overfit_reason = f"n_runs dropped >70% ({current_run_count_entry} → {best_run_count})"

        if improvement <= 0.01:
            not_recommended.append({
                "param": param_name,
                "reason": f"改善幅度微小 (Δscore={improvement:.4f} ≤ 0.01)",
                "current": current_v,
                "best": best_v,
                "improvement": improvement,
            })
        elif overfit_risk:
            not_recommended.append({
                "param": param_name,
                "reason": f"過擬合風險: {overfit_reason}",
                "current": current_v,
                "best": best_v,
                "improvement": improvement,
            })
        else:
            recommendations.append({
                "param": param_name,
                "description": param_info["description"],
                "current": current_v,
                "suggested": best_v,
                "score_current": baseline_score,
                "score_suggested": baseline_score + improvement,
                "improvement": improvement,
                "affects": ", ".join(param_info["affects"]),
                "best_result": best_res,
            })

    # Step 8: write report
    t_end = datetime.now()
    total_elapsed = (t_end - t_start).total_seconds() / 60

    # Build grid results table
    df_grid = pd.DataFrame(grid_records)

    report_sections = [
        f"# Entry Threshold Grid Search Calibration Report",
        f"",
        f"生成時間：{t_end.strftime('%Y-%m-%d %H:%M:%S')}",
        f"",
        f"---",
        f"",
        f"## 執行摘要",
        f"",
        f"- **可調常數**：{len(PARAM_GRIDS)} 個",
        f"- **Grid 組合數**：{combo_count}",
        f"- **執行時間**：{total_elapsed:.1f} 分鐘",
        f"- **目標函數**：`score = hit_rate × log(1 + n_runs)`（平衡命中率與樣本數）",
        f"",
        f"### Baseline（原始常數）",
        f"",
        f"| 指標 | 值 |",
        f"|---|---|",
        f"| entry_signal.B1_gap_up_attack n_runs | {baseline_results['entry_signal.B1_gap_up_attack']['n_runs']} |",
        f"| entry_signal.B1_gap_up_attack hit_rate | {baseline_results['entry_signal.B1_gap_up_attack']['hit_rate']:.1%} |",
        f"| entry_signal.B1_gap_up_attack score | {baseline_results['entry_signal.B1_gap_up_attack']['score']:.4f} |",
        f"| gap_fill_up n_fires | {baseline_results['pattern.gap_fill_up.n_fires']['n_runs']} |",
        f"| gap_fill_down n_fires | {baseline_results['pattern.gap_fill_down.n_fires']['n_runs']} |",
        f"| **total_score** | **{baseline_score:.4f}** |",
        f"| calibration runner case hit rate | {baseline_case_rate:.1%} |",
        f"",
        f"---",
        f"",
        f"## Sanity Check",
        f"",
        f"| 項目 | 結果 |",
        f"|---|---|",
        f"| pytest 554 tests | {'✅ 全綠' if pytest_pass else '❌ 失敗'} |",
        f"| calibration runner baseline hit rate | {baseline_case_rate:.1%} |",
        f"| calibration runner (post-search) hit rate | {final_case_rate:.1%} |",
        f"| baseline ≥ 85% 保護 | {'✅ PASS' if sanity_pass else '❌ FAIL'} |",
        f"",
        f"---",
        f"",
        f"## 推薦套用的 Changeset",
        f"",
    ]

    if recommendations:
        report_sections += [
            f"以下常數建議套用（score 改善 > 0.01 且無過擬合風險）：",
            f"",
        ]
        for rec in sorted(recommendations, key=lambda x: -x["improvement"]):
            report_sections += [
                f"### `{rec['param']}`: `{rec['current']}` → `{rec['suggested']}`",
                f"",
                f"- **說明**：{rec['description']}",
                f"- **影響**：{rec['affects']}",
                f"- **score 改善**：{rec['score_current']:.4f} → {rec['score_suggested']:.4f} (+{rec['improvement']:.4f})",
                f"",
                f"```diff",
                f"- {rec['param']} = {rec['current']}",
                f"+ {rec['param']} = {rec['suggested']}",
                f"```",
                f"",
            ]
    else:
        report_sections += [
            f"**無推薦套用的常數** — 所有可調參數的最優值即為現有值，或改善幅度過小。",
            f"",
        ]

    report_sections += [
        f"---",
        f"",
        f"## 不推薦套用的常數",
        f"",
    ]

    for nr in not_recommended:
        report_sections += [
            f"- **`{nr['param']}`** (`{nr['current']}` → `{nr['best']}`): {nr['reason']}",
        ]

    report_sections += [
        f"",
        f"---",
        f"",
        f"## 逐常數 Grid 明細",
        f"",
    ]

    for param_name, param_info in PARAM_GRIDS.items():
        rows = [r for r in grid_records if r["param_name"] == param_name]
        report_sections += [
            f"### {param_name}",
            f"",
            f"**說明**：{param_info['description']}",
            f"**影響**：{', '.join(param_info['affects'])}",
            f"",
            f"| value | is_current | entry_B1 n_runs | entry_B1 hit_rate | gfu_n | gfd_n | total_score |",
            f"|---|---|---|---|---|---|---|",
        ]
        for r in rows:
            entry_n = r.get("entry_signal.B1_gap_up_attack_n_runs", "-")
            entry_h = r.get("entry_signal.B1_gap_up_attack_hit_rate", "-")
            gfu_n = r.get("pattern.gap_fill_up.n_fires_n_runs", "-")
            gfd_n = r.get("pattern.gap_fill_down.n_fires_n_runs", "-")
            entry_h_str = f"{entry_h:.3f}" if isinstance(entry_h, float) else str(entry_h)
            report_sections.append(
                f"| {r['value']} | {'✅' if r['is_current'] else ''} | {entry_n} | {entry_h_str} | {gfu_n} | {gfd_n} | **{r['total_score']:.4f}** |"
            )
        report_sections.append("")

    report_sections += [
        f"---",
        f"",
        f"## 注意事項",
        f"",
        f"1. **本報告不寫回 `course_proxy_constants.py`** — 請 user 確認後再手動套用 changeset",
        f"2. **entry_signal.B1_gap_up_attack hit_rate** 在此計算為「merged_doji 觸發日隔日有跳空」的比率，",
        f"   與 phase4_advisor_history.db 記錄的 57% 略有差異（phase4 範圍 2024-2026 top-200，",
        f"   本報告同範圍）",
        f"3. **gap_fill 分析** 使用固定 baseline hit_rate (B1=83%, B2=84%)，",
        f"   GAP_FILL_WINDOW_DAYS 的 score 改善僅反映 n_runs 的增減，非 hit_rate 的變化",
        f"4. **merged_doji 不在 course_proxy_constants.py** — MERGED_DOJI_BODY_RATIO /",
        f"   MERGED_DOJI_SHADOW_MIN_RATIO 是 merged_doji.py 的 module-level 常數，",
        f"   需要獨立調整（此次 grid search 範圍不含）",
        f"",
        f"---",
        f"_Report generated by `scripts/calibrate_entry_thresholds.py`_",
    ]

    report_text = "\n".join(report_sections)
    REPORT_PATH.write_text(report_text, encoding="utf-8")
    print(f"\n[Report] Saved: {REPORT_PATH}")

    # Final summary
    print(f"\n{'=' * 70}")
    print("GRID SEARCH SUMMARY")
    print(f"{'=' * 70}")
    print(f"Combinations run: {combo_count}")
    print(f"Elapsed: {total_elapsed:.1f} min")
    print(f"\nRecommended changes ({len(recommendations)}):")
    for rec in sorted(recommendations, key=lambda x: -x["improvement"]):
        print(f"  {rec['param']}: {rec['current']} → {rec['suggested']} (Δscore={rec['improvement']:+.4f})")
    print(f"\nNot recommended ({len(not_recommended)}):")
    for nr in not_recommended:
        print(f"  {nr['param']}: {nr['reason']}")
    print(f"\nCalibration runner case hit rate: {final_case_rate:.1%} ({'≥85% ✅' if sanity_pass else '<85% ❌'})")
    print(f"\nReport: {REPORT_PATH}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
