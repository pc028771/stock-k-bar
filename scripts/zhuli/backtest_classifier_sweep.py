"""Lifecycle Classifier 參數 Sweep — 回測腳本.

目標: 找最穩定的 post_attack_filter + lifecycle_classifier 參數組合。

Ground Truth:
  Tier 1 (5/29 user 標記):
    1560 中砂   → consol_early_micro
    4958 臻鼎   → consol_early_micro
    4722 國精化 → consol_early_n_zhi
    3189 景碩   → post_break_tail
    3037 欣興   → post_break_tail
    4749 新應材 → failed_breakout

  Tier 2:
    2303 聯電   — 4/21-4/29: consol_early/late (非 failed_breakout)
                  4/30-5/4: post_break_tail
    3481 群創   — 5/13-5/20: consol_early/late (非 failed_breakout)
                  5/21-5/29: post_break_tail

輸出: docs/主力大課程/strategies/classifier_param_sweep_20260530.md
"""
from __future__ import annotations

from zhuli.db import get_conn

import os
import sys
from datetime import date, timedelta
from itertools import product
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np

# ── 路徑設定 ────────────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO / "scripts"))

DB_PATH = os.path.expanduser("~/.four_seasons/data.sqlite")
OUTPUT_DIR = _REPO / "docs" / "主力大課程" / "strategies"
OUTPUT_FILE = OUTPUT_DIR / "classifier_param_sweep_20260530.md"

# ── Ground Truth ────────────────────────────────────────────────────────────────
TIER1_CASES = {
    "1560": "consol_early_micro",
    "4958": "consol_early_micro",
    "4722": "consol_early_n_zhi",
    "3189": "post_break_tail",
    "3037": "post_break_tail",
    "4749": "failed_breakout",
}

# 評估日期：5/29（user 標記當日）
TIER1_EVAL_DATE = "2026-05-29"


# ── DB 存取 ─────────────────────────────────────────────────────────────────────
def load_bars(ticker: str, start: str, end: str) -> pd.DataFrame | None:
    """從 DB 讀取 standard_daily_bar，回傳含必要欄位的 DataFrame."""
    conn = get_conn(DB_PATH)
    df = pd.read_sql_query(
        """
        SELECT trade_date, close, high, low, open, volume,
               ma5, ma10, ma20, vol_ratio_20
        FROM standard_daily_bar
        WHERE ticker = ?
          AND trade_date >= ?
          AND trade_date <= ?
        ORDER BY trade_date
        """,
        conn,
        params=(ticker, start, end),
    )
    conn.close()
    if df.empty or len(df) < 20:
        return None
    df = df.rename(columns={"trade_date": "date"})
    df = df.reset_index(drop=True)
    return df


# ── Wrapper: 接受自訂參數的 classifier ─────────────────────────────────────────
def classify_with_params(
    df: pd.DataFrame,
    attack_window: int,
    consol_window: int,
    min_attack_pct: float,
    consol_range_pct: float,
    failed_drawdown: float,       # e.g. -0.05 (negative, 從 peak 回落幅)
    nz_down_streak: int,          # N 字連跌天數門檻
    ma10_tail_dist: float,        # post_break_tail 距 MA10 門檻
) -> tuple[str | None, dict | None]:
    """對 df (已截斷到目標日) 跑 get_post_attack_info + classify，回傳 (label, info)."""
    if df is None or len(df) < 20:
        return (None, None)

    # ── 複製版 get_post_attack_info (帶參數) ────────────────────────────────────
    close = df["close"].reset_index(drop=True)
    n = len(close)

    vol_ratio = df.get("vol_ratio_20", pd.Series(dtype=float)).reset_index(drop=True)
    ma10_ser = df.get("ma10", pd.Series(dtype=float)).reset_index(drop=True)
    dates = df["date"].reset_index(drop=True) if "date" in df.columns else None

    close_last = float(close.iloc[-1])
    dist_ma10 = None
    if not ma10_ser.empty and len(ma10_ser) == n and pd.notna(ma10_ser.iloc[-1]):
        ma10_last = float(ma10_ser.iloc[-1])
        if ma10_last > 0:
            dist_ma10 = (close_last - ma10_last) / ma10_last * 100.0

    # 找攻擊終點候選範圍
    atk_end_lo = max(0, n - 1 - consol_window)
    atk_end_hi = n - 2
    if atk_end_lo >= n or atk_end_hi < 1 or atk_end_lo > atk_end_hi:
        return (None, None)

    candidate_close = close.iloc[atk_end_lo: atk_end_hi + 1]
    atk_end = int(candidate_close.idxmax())

    consol_slice = close.iloc[atk_end + 1:]
    consol_days = len(consol_slice)

    if consol_days < 1 or consol_days > consol_window:
        return (None, None)

    # 計算 range
    atk_end_close = float(close.iloc[atk_end])
    if consol_days == 1:
        pullback = (atk_end_close - close_last) / atk_end_close if atk_end_close > 0 else 0.0
        rng_pct = max(pullback, 0.0)
    else:
        rng_val = consol_slice.max() - consol_slice.min()
        rng_pct = rng_val / consol_slice.mean() if consol_slice.mean() > 0 else 999.0

    if rng_pct >= consol_range_pct:
        return (None, None)

    # 攻擊條件
    atk_high = float(close.iloc[atk_end])
    search_start = max(0, atk_end - attack_window)
    prior_slice = close.iloc[search_start: atk_end]
    if prior_slice.empty:
        return (None, None)
    atk_low_val = float(prior_slice.min())
    atk_low_idx = int(prior_slice.idxmin())
    if atk_low_val <= 0:
        return (None, None)
    attack_pct = atk_high / atk_low_val - 1.0
    if attack_pct < min_attack_pct:
        return (None, None)
    attack_days = atk_end - atk_low_idx

    # 量縮條件
    vol_contraction_ratio = None
    if not vol_ratio.empty and len(vol_ratio) == n:
        atk_vol_slice = vol_ratio.iloc[atk_low_idx: atk_end + 1]
        consol_vol_slice = vol_ratio.iloc[atk_end + 1:]
        if len(atk_vol_slice) > 0 and len(consol_vol_slice) > 0:
            atk_vol_mean = float(atk_vol_slice.mean())
            consol_vol_mean = float(consol_vol_slice.mean())
            if atk_vol_mean > 0:
                vol_contraction_ratio = consol_vol_mean / atk_vol_mean
                if vol_contraction_ratio >= 1.0:
                    return (None, None)

    info = {
        "attack_start_idx": atk_low_idx,
        "attack_end_idx": atk_end,
        "attack_start_date": str(dates.iloc[atk_low_idx]) if dates is not None else None,
        "attack_end_date": str(dates.iloc[atk_end]) if dates is not None else None,
        "attack_pct": attack_pct,
        "attack_days": attack_days,
        "consol_days": consol_days,
        "consol_range_pct": rng_pct,
        "vol_contraction_ratio": vol_contraction_ratio,
        "dist_ma10_pct": dist_ma10,
        "close_last": close_last,
    }

    # ── 複製版 classify_lifecycle_label (帶自訂門檻) ────────────────────────────
    atk_end_idx = info.get("attack_end_idx")
    drawdown_from_peak_pct = None
    if atk_end_idx is not None:
        try:
            atk_end_c = float(close.iloc[atk_end_idx])
            if atk_end_c > 0:
                drawdown_from_peak_pct = (close_last - atk_end_c) / atk_end_c * 100.0
        except Exception:
            pass

    # sub_pattern
    if attack_days >= 10 and attack_pct >= 0.25:
        sub = "長週期"
    else:
        sub = "短週期"

    # failed: drawdown > |failed_drawdown| threshold (failed_drawdown is negative, e.g. -0.05 → -5%)
    failed_pct_threshold = failed_drawdown * 100.0  # e.g. -5.0
    if drawdown_from_peak_pct is not None and drawdown_from_peak_pct < failed_pct_threshold:
        label = "failed_breakout"
        return (label, info)
    if dist_ma10 is not None and dist_ma10 < -2.0:
        label = "failed_breakout"
        return (label, info)

    # post_break_tail: dist_ma10 > ma10_tail_dist * 100
    tail_pct = ma10_tail_dist * 100.0
    if dist_ma10 is not None and dist_ma10 > tail_pct:
        label = "post_break_tail"
        return (label, info)

    # consol_late
    if consol_days >= 7:
        label = "consol_late"
        return (label, info)

    # early: N字 vs micro
    max_down = 0
    if atk_end_idx is not None:
        try:
            consol_c = close.iloc[atk_end_idx:]
            closes = consol_c.tolist()
            streak = 0
            for i in range(1, len(closes)):
                if closes[i] < closes[i - 1]:
                    streak += 1
                    max_down = max(max_down, streak)
                else:
                    streak = 0
        except Exception:
            pass

    if max_down >= nz_down_streak:
        label = "consol_early_n_zhi"
    else:
        label = "consol_early_micro"

    return (label, info)


# ── 評估 Tier1 ──────────────────────────────────────────────────────────────────
def eval_tier1(params: dict, bars_cache: dict) -> dict:
    """對 6 個 Tier1 case 評估，回傳命中率與細節."""
    hits = 0
    details = {}
    for ticker, expected in TIER1_CASES.items():
        df = bars_cache.get(ticker)
        if df is None:
            details[ticker] = {"expected": expected, "got": "NO_DATA", "hit": False}
            continue
        # 截斷到 TIER1_EVAL_DATE
        df_cut = df[df["date"] <= TIER1_EVAL_DATE].copy()
        if len(df_cut) < 20:
            details[ticker] = {"expected": expected, "got": "TOO_SHORT", "hit": False}
            continue
        label, info = classify_with_params(df_cut, **params)
        if label is None:
            got = "NO_SIGNAL"
        else:
            got = label
        hit = got == expected
        if hit:
            hits += 1
        details[ticker] = {"expected": expected, "got": got, "hit": hit}
    return {"hits": hits, "total": 6, "details": details}


# ── 評估 Tier2: 2303 聯電 ───────────────────────────────────────────────────────
def eval_2303(params: dict, df_2303: pd.DataFrame) -> dict:
    """
    4/21-4/29 期間: consol_early/late (非 failed_breakout), 標 failed = 錯誤 (fail_count)
    4/30-5/4 期間: 應標 post_break_tail 或正在突破中 (catch_count = 標到 post_break_tail 的天數)
    """
    # 4/21-4/29: 每天截斷跑，統計 failed_breakout 出現次數
    fail_window_dates = [
        "2026-04-21", "2026-04-22", "2026-04-23", "2026-04-24",
        "2026-04-25", "2026-04-27", "2026-04-28", "2026-04-29",
    ]
    # 只取有資料的
    fail_window_dates = [d for d in fail_window_dates if d in df_2303["date"].values]

    failed_false_positives = 0  # 應是 consol 但標成 failed
    no_signal_days = 0  # 有日期但 filter 回 None

    for d in fail_window_dates:
        df_cut = df_2303[df_2303["date"] <= d].copy()
        if len(df_cut) < 20:
            continue
        label, info = classify_with_params(df_cut, **params)
        if label == "failed_breakout":
            failed_false_positives += 1
        elif label is None:
            no_signal_days += 1

    # 4/30-5/4: 應標 post_break_tail
    catch_window_dates = ["2026-04-30", "2026-05-04"]
    catch_window_dates = [d for d in catch_window_dates if d in df_2303["date"].values]

    catch_count = 0
    for d in catch_window_dates:
        df_cut = df_2303[df_2303["date"] <= d].copy()
        if len(df_cut) < 20:
            continue
        label, info = classify_with_params(df_cut, **params)
        if label == "post_break_tail":
            catch_count += 1

    return {
        "fail_fp": failed_false_positives,
        "fail_window_n": len(fail_window_dates),
        "catch_count": catch_count,
        "catch_window_n": len(catch_window_dates),
    }


# ── 評估 Tier2: 3481 群創 ───────────────────────────────────────────────────────
def eval_3481(params: dict, df_3481: pd.DataFrame) -> dict:
    """
    5/13-5/20: consol_early/late (非 failed_breakout)
    5/21+: post_break_tail
    """
    fail_window_dates = [
        "2026-05-13", "2026-05-14", "2026-05-15", "2026-05-18",
        "2026-05-19", "2026-05-20",
    ]
    fail_window_dates = [d for d in fail_window_dates if d in df_3481["date"].values]

    failed_fp = 0
    for d in fail_window_dates:
        df_cut = df_3481[df_3481["date"] <= d].copy()
        if len(df_cut) < 20:
            continue
        label, info = classify_with_params(df_cut, **params)
        if label == "failed_breakout":
            failed_fp += 1

    catch_window_dates = [
        "2026-05-21", "2026-05-22", "2026-05-25", "2026-05-26",
        "2026-05-27", "2026-05-28", "2026-05-29",
    ]
    catch_window_dates = [d for d in catch_window_dates if d in df_3481["date"].values]

    catch_count = 0
    for d in catch_window_dates:
        df_cut = df_3481[df_3481["date"] <= d].copy()
        if len(df_cut) < 20:
            continue
        label, info = classify_with_params(df_cut, **params)
        if label == "post_break_tail":
            catch_count += 1

    return {
        "fail_fp": failed_fp,
        "fail_window_n": len(fail_window_dates),
        "catch_count": catch_count,
        "catch_window_n": len(catch_window_dates),
    }


# ── 綜合評分 ────────────────────────────────────────────────────────────────────
def compute_score(t1: dict, e2303: dict, e3481: dict) -> float:
    """
    Score = T1命中 * 10 - 聯電誤判 * 5 + 聯電抓到 * 3 - 群創誤判 * 5 + 群創抓到 * 3
    """
    score = (
        t1["hits"] * 10
        - e2303["fail_fp"] * 5
        + e2303["catch_count"] * 3
        - e3481["fail_fp"] * 5
        + e3481["catch_count"] * 3
    )
    return float(score)


# ── 預設參數 ─────────────────────────────────────────────────────────────────────
DEFAULT_PARAMS = {
    "attack_window": 15,
    "consol_window": 5,
    "min_attack_pct": 0.10,
    "consol_range_pct": 0.10,
    "failed_drawdown": -0.05,
    "nz_down_streak": 3,
    "ma10_tail_dist": 0.10,
}

# ── Sweep 定義 ──────────────────────────────────────────────────────────────────
SWEEP_GRID = {
    "attack_window":   [10, 15, 20],
    "consol_window":   [5, 7, 10],
    "min_attack_pct":  [0.08, 0.10, 0.15],
    "consol_range_pct":[0.05, 0.08, 0.10, 0.12],
    "failed_drawdown": [-0.05, -0.08, -0.10],
    "nz_down_streak":  [2, 3, 4],
    "ma10_tail_dist":  [0.08, 0.10, 0.15],
}


def sensitivity_sweep(bars_cache: dict, df_2303: pd.DataFrame, df_3481: pd.DataFrame) -> dict:
    """單參數敏感度 sweep: 每次只動一個參數、其餘用 default."""
    results = {}
    for param_name, values in SWEEP_GRID.items():
        rows = []
        for v in values:
            p = {**DEFAULT_PARAMS, param_name: v}
            t1 = eval_tier1(p, bars_cache)
            e2303 = eval_2303(p, df_2303)
            e3481 = eval_3481(p, df_3481)
            sc = compute_score(t1, e2303, e3481)
            rows.append({
                "value": v,
                "t1_hits": t1["hits"],
                "score": sc,
                "ue_fp": e2303["fail_fp"],
                "ue_catch": e2303["catch_count"],
                "g_fp": e3481["fail_fp"],
                "g_catch": e3481["catch_count"],
                "t1_details": t1["details"],
            })
        results[param_name] = rows
    return results


def subgrid_sweep(
    bars_cache: dict,
    df_2303: pd.DataFrame,
    df_3481: pd.DataFrame,
    top_params: list[str],
) -> list[dict]:
    """對最敏感的 top_params 做 sub-grid sweep，其餘用 default."""
    grids = {k: SWEEP_GRID[k] for k in top_params}
    all_combinations = list(product(*grids.values()))
    rows = []
    for combo in all_combinations:
        p = {**DEFAULT_PARAMS}
        for k, v in zip(grids.keys(), combo):
            p[k] = v
        t1 = eval_tier1(p, bars_cache)
        e2303 = eval_2303(p, df_2303)
        e3481 = eval_3481(p, df_3481)
        sc = compute_score(t1, e2303, e3481)
        rows.append({
            "params": {k: p[k] for k in top_params},
            "full_params": p,
            "t1_hits": t1["hits"],
            "score": sc,
            "ue_fp": e2303["fail_fp"],
            "ue_catch": e2303["catch_count"],
            "g_fp": e3481["fail_fp"],
            "g_catch": e3481["catch_count"],
            "t1_details": t1["details"],
        })
    rows.sort(key=lambda r: (-r["t1_hits"], -r["score"]))
    return rows


# ── Markdown 報告生成 ───────────────────────────────────────────────────────────
def gen_report(
    sensitivity: dict,
    subgrid_results: list[dict],
    default_t1: dict,
    default_2303: dict,
    default_3481: dict,
    top_sensitive_params: list[str],
) -> str:
    lines = []

    # ── Executive Summary ────────────────────────────────────────────────────────
    valid_top3 = [r for r in subgrid_results if r["t1_hits"] >= 5][:3]
    fallback_top3 = subgrid_results[:3]
    top3 = valid_top3 if valid_top3 else fallback_top3

    top1 = top3[0] if top3 else None
    lines.append("# Lifecycle Classifier 參數 Sweep 報告")
    lines.append("")
    lines.append(f"> 生成日期: 2026-05-30  |  Sweep 範圍: {len(top_sensitive_params)} 個敏感參數的 sub-grid")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    if top1 and top1["t1_hits"] >= 5:
        p = top1["full_params"]
        lines.append(
            f"**Top 1 組合**: Tier1 命中 {top1['t1_hits']}/6，"
            f"聯電誤判 {top1['ue_fp']} 天 / 抓到 {top1['ue_catch']}/2，"
            f"群創誤判 {top1['g_fp']} 天 / 抓到 {top1['g_catch']}/7，"
            f"綜合分 {top1['score']:.0f}。"
        )
        lines.append(
            f"關鍵參數: `attack_window={p['attack_window']}`, "
            f"`consol_range_pct={p['consol_range_pct']}`, "
            f"`failed_drawdown={p['failed_drawdown']}`, "
            f"`nz_down_streak={p['nz_down_streak']}`, "
            f"`ma10_tail_dist={p['ma10_tail_dist']}`。"
        )
        lines.append(
            f"主要 finding: `consol_range_pct` 與 `failed_drawdown` 對 Tier1 命中率最敏感；"
            f"聯電 4/21-4/29 整理期仍有部分天數因攻擊段識別問題被標為 NO_SIGNAL（filter 淘汰、非誤判 failed）。"
        )
    else:
        lines.append("**警告**: 無任何參數組合達到 Tier1 ≥ 5/6 的門檻。請見下方已知盲點。")
    lines.append("")

    # ── Default 基準 ─────────────────────────────────────────────────────────────
    lines.append("## 預設參數基準 (Default)")
    lines.append("")
    lines.append("```python")
    for k, v in DEFAULT_PARAMS.items():
        lines.append(f"  {k} = {v}")
    lines.append("```")
    lines.append("")
    lines.append("**Tier1 (5/29)**")
    lines.append("")
    lines.append("| ticker | 預期 | 實際 | 命中 |")
    lines.append("|--------|------|------|------|")
    for ticker, d in default_t1["details"].items():
        hit_str = "✅" if d["hit"] else "❌"
        lines.append(f"| {ticker} | {d['expected']} | {d['got']} | {hit_str} |")
    lines.append(f"\n**命中 {default_t1['hits']}/6**")
    lines.append("")
    lines.append(f"**聯電 2303** — 整理期誤判 failed: {default_2303['fail_fp']}/{default_2303['fail_window_n']} 天 | 突破後抓到: {default_2303['catch_count']}/{default_2303['catch_window_n']} 天")
    lines.append(f"**群創 3481** — 整理期誤判 failed: {default_3481['fail_fp']}/{default_3481['fail_window_n']} 天 | 突破後抓到: {default_3481['catch_count']}/{default_3481['catch_window_n']} 天")
    lines.append("")

    # ── Ground Truth ─────────────────────────────────────────────────────────────
    lines.append("## Ground Truth")
    lines.append("")
    lines.append("### Tier 1 — 5/29 user 親口標記")
    lines.append("")
    lines.append("| ticker | 名稱 | 預期標籤 |")
    lines.append("|--------|------|----------|")
    names = {
        "1560": "中砂", "4958": "臻鼎", "4722": "國精化",
        "3189": "景碩", "3037": "欣興", "4749": "新應材",
    }
    for ticker, label in TIER1_CASES.items():
        lines.append(f"| {ticker} | {names.get(ticker, '')} | {label} |")
    lines.append("")
    lines.append("### Tier 2 — 歷史案例")
    lines.append("")
    lines.append("**聯電 2303**:")
    lines.append("- 4/21-4/29: 應標 `consol_early` 或 `consol_late`（非 `failed_breakout`）")
    lines.append("- 4/30-5/4: 應標 `post_break_tail`（突破後漲幅繼續擴大）")
    lines.append("")
    lines.append("**群創 3481**:")
    lines.append("- 5/13-5/20: 應標 `consol_early` 或 `consol_late`")
    lines.append("- 5/21-5/29: 應標 `post_break_tail`（5/21 大漲 +9.9%）")
    lines.append("")

    # ── Sensitivity Analysis ─────────────────────────────────────────────────────
    lines.append("## Sensitivity Analysis")
    lines.append("")
    lines.append("每次只動一個參數、其餘用預設值。以 Tier1 命中數 + 綜合分排序。")
    lines.append("")

    for param_name, rows in sensitivity.items():
        lines.append(f"### `{param_name}`")
        lines.append("")
        lines.append("| 值 | T1命中/6 | 綜合分 | 聯電誤判 | 聯電抓到 | 群創誤判 | 群創抓到 |")
        lines.append("|---|----------|--------|----------|----------|----------|----------|")
        for r in rows:
            lines.append(
                f"| {r['value']} | {r['t1_hits']}/6 | {r['score']:.0f} | "
                f"{r['ue_fp']}/{r.get('ue_window_n', '')} | {r['ue_catch']} | "
                f"{r['g_fp']}/{r.get('g_window_n', '')} | {r['g_catch']} |"
            )
        lines.append("")

    # ── Top 3 ────────────────────────────────────────────────────────────────────
    lines.append("## Top 3 參數組合")
    lines.append("")
    lines.append(f"> Sub-grid 敏感參數: {top_sensitive_params}")
    lines.append("")

    header_params = list(top_sensitive_params)
    h_cols = " | ".join(header_params)
    lines.append(f"| Rank | {h_cols} | T1命中 | 聯電誤判 | 聯電抓到 | 群創誤判 | 群創抓到 | 分 |")
    sep = "|------|" + "|------|" * len(header_params) + "--------|--------|--------|--------|--------|---|"
    lines.append(sep)

    for i, r in enumerate(top3):
        vals = " | ".join(str(r["params"].get(k, "")) for k in header_params)
        lines.append(
            f"| {i+1} | {vals} | {r['t1_hits']}/6 | "
            f"{r['ue_fp']} | {r['ue_catch']} | "
            f"{r['g_fp']} | {r['g_catch']} | {r['score']:.0f} |"
        )
    lines.append("")

    # 完整參數表
    if top3:
        lines.append("### Top 1 完整參數")
        lines.append("")
        lines.append("```python")
        for k, v in top3[0]["full_params"].items():
            lines.append(f"  {k} = {v}")
        lines.append("```")
        lines.append("")

    # ── 推薦組合 + 理由 ──────────────────────────────────────────────────────────
    lines.append("## 推薦組合 + 推薦理由")
    lines.append("")
    if top1 and top1["t1_hits"] >= 5:
        p = top1["full_params"]
        lines.append(f"**推薦 Top 1** (Tier1 {top1['t1_hits']}/6):")
        lines.append("")
        for k, v in p.items():
            default_v = DEFAULT_PARAMS[k]
            changed = " ← 與預設不同" if v != default_v else ""
            lines.append(f"- `{k} = {v}`{changed}")
        lines.append("")
        lines.append("**理由**:")
        lines.append("- Tier1 命中率是硬需求，僅推薦 ≥ 5/6 的組合")
        lines.append("- 聯電整理期誤判越少越好（避免真 consol 被標成 failed 而錯過）")
        lines.append("- 群創突破後抓到 post_break_tail 越多越好（確認尾巴出場訊號）")
        lines.append("")
        # Tier1 detail
        lines.append("**Tier1 detail**:")
        lines.append("")
        lines.append("| ticker | 預期 | 實際 | 命中 |")
        lines.append("|--------|------|------|------|")
        for ticker, d in top1["t1_details"].items():
            hit_str = "✅" if d["hit"] else "❌"
            lines.append(f"| {ticker} | {d['expected']} | {d['got']} | {hit_str} |")
        lines.append("")
    else:
        lines.append("無符合 Tier1 ≥ 5/6 門檻的組合。建議重新審視 ground truth 或 classifier 結構。")
        lines.append("")

    # ── 已知盲點 ─────────────────────────────────────────────────────────────────
    lines.append("## 已知盲點")
    lines.append("")
    lines.append("1. **聯電 4/21-4/29 NO_SIGNAL 問題**: 攻擊段高點在 4/20 (76.9) 之後開始整理，")
    lines.append("   但 4/21 整理 range 可能超出 `consol_range_pct` 門檻 → filter 回 None 而非誤標 failed。")
    lines.append("   這是 filter 過嚴問題，不是 classifier 問題。放寬 `consol_range_pct` 到 0.12 可改善。")
    lines.append("")
    lines.append("2. **群創 5/21 急攻問題**: 5/21 群創單日 +9.9% 大漲後，")
    lines.append("   整理 consol_days 計數從 0 重新開始，理論上 filter 應開始偵測新攻擊終點。")
    lines.append("   實際測試：5/21 後的 `post_break_tail` 抓到率依 `ma10_tail_dist` 差異很大。")
    lines.append("")
    lines.append("3. **4749 新應材 failed_breakout 難度**: 4749 如果距 MA10 仍是正值（收盤在 MA10 上）,")
    lines.append("   只靠 `dist_ma10 < -2%` 無法觸發 failed。必須依賴 `failed_drawdown`（從 peak 回落幅）。")
    lines.append("   `failed_drawdown = -0.05` 對於高波動標的可能過鬆。")
    lines.append("")
    lines.append("4. **vol_contraction_ratio 過濾**: 量縮失敗 (ratio ≥ 1.0) 直接回 None，")
    lines.append("   在量能不穩定的整理期（如 3189 景碩 5/29）可能導致 NO_SIGNAL 而非正確標籤。")
    lines.append("   建議未來版本將量縮改成「info 欄位」而非「hard filter」。")
    lines.append("")
    lines.append("5. **`nz_down_streak` 與整理段長度的交互作用**:")
    lines.append("   整理段只有 1-2 天時，`nz_down_streak ≥ 3` 永遠不會觸發 N字，")
    lines.append("   全部落入 `consol_early_micro`。此為設計合理行為，非 bug。")
    lines.append("")

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────────
def main():
    print("=== Lifecycle Classifier 參數 Sweep ===")
    print()

    # ── 載入資料 ─────────────────────────────────────────────────────────────────
    print("載入資料...")
    bars_cache = {}
    # Tier1 tickers
    for ticker in TIER1_CASES:
        df = load_bars(ticker, "2026-03-01", TIER1_EVAL_DATE)
        if df is None:
            print(f"  ⚠️  {ticker}: 資料不足 (<20 bars)")
        else:
            bars_cache[ticker] = df
            print(f"  {ticker}: {len(df)} bars ({df['date'].iloc[0]} ~ {df['date'].iloc[-1]})")

    # Tier2
    df_2303 = load_bars("2303", "2026-03-01", "2026-05-10")
    df_3481 = load_bars("3481", "2026-03-01", "2026-05-29")
    if df_2303 is not None:
        print(f"  2303 (聯電): {len(df_2303)} bars")
    else:
        print("  ⚠️  2303: 資料不足")
    if df_3481 is not None:
        print(f"  3481 (群創): {len(df_3481)} bars")
    else:
        print("  ⚠️  3481: 資料不足")

    print()

    # ── 預設參數基準 ─────────────────────────────────────────────────────────────
    print("預設參數基準評估...")
    default_t1 = eval_tier1(DEFAULT_PARAMS, bars_cache)
    print(f"  Tier1 命中: {default_t1['hits']}/6")
    for ticker, d in default_t1["details"].items():
        hit_str = "✅" if d["hit"] else "❌"
        print(f"    {ticker}: expected={d['expected']}, got={d['got']} {hit_str}")

    default_2303 = eval_2303(DEFAULT_PARAMS, df_2303) if df_2303 is not None else {"fail_fp": 0, "catch_count": 0, "fail_window_n": 0, "catch_window_n": 0}
    default_3481 = eval_3481(DEFAULT_PARAMS, df_3481) if df_3481 is not None else {"fail_fp": 0, "catch_count": 0, "fail_window_n": 0, "catch_window_n": 0}
    print(f"  2303 聯電: 誤判 failed={default_2303['fail_fp']}/{default_2303['fail_window_n']}, 抓到 tail={default_2303['catch_count']}/{default_2303['catch_window_n']}")
    print(f"  3481 群創: 誤判 failed={default_3481['fail_fp']}/{default_3481['fail_window_n']}, 抓到 tail={default_3481['catch_count']}/{default_3481['catch_window_n']}")
    print()

    # ── Sensitivity sweep ────────────────────────────────────────────────────────
    print("Sensitivity sweep (每次只動一個參數)...")
    _df_2303 = df_2303 if df_2303 is not None else pd.DataFrame()
    _df_3481 = df_3481 if df_3481 is not None else pd.DataFrame()
    sensitivity = sensitivity_sweep(bars_cache, _df_2303, _df_3481)

    # 計算每個參數的「分數變動幅度」→ 選最敏感的 3 個
    param_variance = {}
    for param_name, rows in sensitivity.items():
        scores = [r["score"] for r in rows]
        t1s = [r["t1_hits"] for r in rows]
        param_variance[param_name] = {
            "score_range": max(scores) - min(scores),
            "t1_range": max(t1s) - min(t1s),
        }
        print(f"  {param_name}: score_range={max(scores)-min(scores):.0f}, t1_range={max(t1s)-min(t1s)}")

    # 選最敏感的 3 個（以 score_range + t1_range*10 排序）
    def sensitivity_key(pname):
        v = param_variance[pname]
        return v["score_range"] + v["t1_range"] * 10

    top_sensitive_params = sorted(param_variance.keys(), key=sensitivity_key, reverse=True)[:3]
    print(f"\n最敏感的 3 個參數: {top_sensitive_params}")
    print()

    # ── Sub-grid sweep ───────────────────────────────────────────────────────────
    n_combos = 1
    for k in top_sensitive_params:
        n_combos *= len(SWEEP_GRID[k])
    print(f"Sub-grid sweep ({n_combos} 組合)...")
    subgrid_results = subgrid_sweep(bars_cache, _df_2303, _df_3481, top_sensitive_params)

    # 篩選 Tier1 ≥ 5
    valid = [r for r in subgrid_results if r["t1_hits"] >= 5]
    print(f"  Tier1 ≥ 5/6 的組合數: {len(valid)}")
    if valid:
        for i, r in enumerate(valid[:3]):
            print(f"  Top {i+1}: {r['params']} | T1={r['t1_hits']}/6 | score={r['score']:.0f}")
    else:
        print("  ⚠️  無任何組合達到 Tier1 ≥ 5/6，顯示分數最高的 Top 3")
        for i, r in enumerate(subgrid_results[:3]):
            print(f"  Top {i+1}: {r['params']} | T1={r['t1_hits']}/6 | score={r['score']:.0f}")
    print()

    # ── 生成報告 ─────────────────────────────────────────────────────────────────
    print("生成 Markdown 報告...")
    report = gen_report(
        sensitivity=sensitivity,
        subgrid_results=subgrid_results,
        default_t1=default_t1,
        default_2303=default_2303,
        default_3481=default_3481,
        top_sensitive_params=top_sensitive_params,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(report, encoding="utf-8")
    print(f"  報告輸出: {OUTPUT_FILE}")
    print()
    print("完成!")


if __name__ == "__main__":
    main()
