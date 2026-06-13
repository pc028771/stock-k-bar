"""Backtest: K 線力量 Tier-A 升等訊號實際 EV 驗證.

研究問題：把 attack_cost_displayed / morning_star_island_reversal /
morning_star_harami 三支 phase4 高 follow-through 的 K 線 detector 當作
「升等訊號」(別的 scanner 命中 + 同日亮這個 pattern → tier 升等)，
**實際 forward return 是否優於沒升等的對照組？**

設計
----
- Universe: teacher 332 (teacher_sector_tickers ∪ teacher_picks_2026)
- Period: 2024-01-01 → 2026-05-31 (避開 2026-06 的 in-sample 風險)
- Scanner proxy: shakeout_strong OR w_bottom_launch (daily_scanner_job 主流 bull layer)
- K 線 tier-A: attack_cost_displayed / morning_star_island_reversal / morning_star_harami
- Forward return: 1d / 5d / 10d / 20d close-to-close

對照組
-----
A. boosted   = scanner_fire AND kline_fire   (升等候選)
B. control   = scanner_fire AND NOT kline_fire (沒升等的 scanner 命中)
C. kline_only = NOT scanner_fire AND kline_fire (純 K 線命中、未被 scanner 抓)
D. baseline  = 整個 universe × 所有日 (任意 day-stock 抽樣)

指標
----
- mean / median forward return
- win rate (fr > 0)
- capture (fr > 10% 比率)

決策
----
- A > B 顯著 → 升等機制有效、維持
- A ≈ B → 改成只加 ✨ badge、不升 tier
- C > B → kline 單獨命中其實是訊號、考慮獨立 watchlist
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

_REPO = Path(__file__).parent.parent.parent
_SCRIPTS = _REPO / "scripts"
for _p in [str(_REPO), str(_SCRIPTS), "/Users/howard/Repository/stock-analysis-system"]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kline.features import add_features  # noqa: E402
from kline.extras.shakeout_strong import detect as detect_shakeout  # noqa: E402
from zhuli.entry.w_bottom_launch import detect as detect_wbottom  # noqa: E402
from kline.patterns.attack_cost_displayed import detect as detect_attack_cost  # noqa: E402
from kline.patterns.morning_star_island_reversal import detect as detect_msir  # noqa: E402
from kline.patterns.morning_star_harami import detect as detect_msh  # noqa: E402


DB_PATH = Path.home() / ".four_seasons" / "data.sqlite"
START_DATE = "2024-01-01"
END_DATE = "2026-05-31"


def load_universe() -> set[str]:
    """Load teacher 332 universe (sector + picks_2026 union)."""
    sec_path = _REPO / "docs" / "主力大課程" / "teacher_sector_tickers.json"
    pick_path = _REPO / "docs" / "主力大課程" / "teacher_picks_2026.json"
    universe: set[str] = set()
    if sec_path.exists():
        data = json.loads(sec_path.read_text())
        for tickers in data.values():
            universe.update(tickers)
    if pick_path.exists():
        data = json.loads(pick_path.read_text())
        for k in data:
            if k != "_meta":
                universe.add(k)
    return universe


def load_bars_for_ticker(ticker: str) -> pd.DataFrame:
    """Load standard_daily_bar columns daily_scanner_job uses."""
    import sqlite3
    uri = f"file:{DB_PATH}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=10)
    df = pd.read_sql(
        """SELECT ? as ticker, trade_date, open, high, low, close, volume,
                  vol_ratio_20, ma5, ma10, ma20, ma60,
                  vol_ma20, bb_upper, bb_lower, bb_mid,
                  ma20_slope, ma20_slope_proxy
           FROM standard_daily_bar
           WHERE ticker = ? AND trade_date >= ? AND trade_date <= date(?, '+30 days')
           ORDER BY trade_date""",
        con, params=(ticker, ticker, START_DATE, END_DATE),
    )
    con.close()
    return df


def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Mirror what daily_scanner_job.run_scanners adds before running detectors."""
    df = df.copy()
    df["prev_close"] = df["close"].shift(1)
    df["prev_open"] = df["open"].shift(1)
    df["prev_high"] = df["high"].shift(1)
    df["prev_low"] = df["low"].shift(1)
    df["volume_ratio"] = df["vol_ratio_20"]  # alias for shakeout_strong
    # prior_high_60 / shakeout-specific cols
    df["prior_high_60"] = df["high"].rolling(60, min_periods=20).max().shift(1)
    df["breakout_strength_pct"] = (
        df["close"] / df["prior_high_60"].replace(0, np.nan) - 1
    ) * 100
    df["breakout_next_low_open"] = (df["open"].shift(-1) < df["close"]).fillna(False)
    # overhead_supply_layer 簡化計算 (with rolling 240)
    LOOKBACK = 240
    n = len(df)
    peak_count = np.zeros(n, dtype=float)
    close_arr = df["close"].to_numpy()
    high_arr = df["high"].to_numpy()
    for lag in range(1, LOOKBACK + 1):
        past_high = pd.Series(high_arr).shift(lag).to_numpy()
        past_max5 = pd.Series(high_arr).shift(lag).rolling(5, min_periods=5).max().to_numpy()
        is_peak = (past_high == past_max5) & ~np.isnan(past_max5)
        peak_count += ((past_high > close_arr) & is_peak).astype(float)
    has_history = np.arange(n) >= 20
    df["overhead_supply_layer"] = np.where(has_history, peak_count, np.nan)
    return df


def process_one_ticker(ticker: str) -> pd.DataFrame | None:
    """Load bars + add features + run all detectors + forward returns."""
    try:
        df = load_bars_for_ticker(ticker)
    except Exception:
        return None
    if len(df) < 100:
        return None
    df = add_derived_columns(df)
    # kline.features.add_features adds the cols needed by attack_cost / msir / msh
    df = add_features(df, groups=["basic", "volume", "historical", "pattern"])

    # 5 detectors
    df["sig_shakeout"] = detect_shakeout(df).fillna(False)
    df["sig_wbottom"] = detect_wbottom(df).fillna(False)
    df["sig_attack_cost"] = detect_attack_cost(df).fillna(False)
    df["sig_msir"] = detect_msir(df).fillna(False)
    df["sig_msh"] = detect_msh(df).fillna(False)

    # K3 with filters (探討哪個條件能救 K3)
    vol_ratio = df.get("vol_ratio_20", pd.Series(np.nan, index=df.index))
    df["sig_msh_volup"] = df["sig_msh"] & (vol_ratio >= 1.5).fillna(False)
    df["sig_msh_maalign"] = (
        df["sig_msh"]
        & (df["ma5"] >= df["ma10"]).fillna(False)
    )
    df["sig_msh_both"] = (
        df["sig_msh"]
        & (vol_ratio >= 1.5).fillna(False)
        & (df["ma5"] >= df["ma10"]).fillna(False)
    )

    # 組合 mask
    df["scanner_fire"] = df["sig_shakeout"] | df["sig_wbottom"]
    df["kline_fire"] = df["sig_attack_cost"] | df["sig_msir"] | df["sig_msh"]
    df["kline_fire_k12"] = df["sig_attack_cost"] | df["sig_msir"]  # 移除 K3

    # Forward returns (close-to-close, shift -N)
    close = df["close"]
    for n in (1, 5, 10, 20):
        df[f"fr_{n}d"] = close.shift(-n) / close - 1.0

    # 只回 START..END 範圍 (避免 +30 days buffer 計算 fr_20d 但落在 backtest 區間外)
    df = df[(df["trade_date"] >= START_DATE) & (df["trade_date"] <= END_DATE)]
    # 過濾髒資料 (close <= 0 會造成 forward return = +/-inf)
    df = df[df["close"] > 0]
    return df


def aggregate(df_all: pd.DataFrame, mask: pd.Series, label: str) -> dict:
    sub = df_all[mask]
    out = {"group": label, "n": int(len(sub))}
    for n in (1, 5, 10, 20):
        col = f"fr_{n}d"
        vals = sub[col].dropna()
        if len(vals) == 0:
            out[f"mean_{n}d"] = None
            out[f"median_{n}d"] = None
            out[f"wr_{n}d"] = None
            out[f"cap10_{n}d"] = None
        else:
            out[f"mean_{n}d"] = float(vals.mean())
            out[f"median_{n}d"] = float(vals.median())
            out[f"wr_{n}d"] = float((vals > 0).mean())
            out[f"cap10_{n}d"] = float((vals > 0.10).mean())
    return out


def main():
    universe = load_universe()
    print(f"Universe: {len(universe)} tickers", flush=True)

    all_frames: list[pd.DataFrame] = []
    n_done = 0
    n_fail = 0
    for t in sorted(universe):
        df = process_one_ticker(t)
        if df is None or df.empty:
            n_fail += 1
            continue
        all_frames.append(df)
        n_done += 1
        if n_done % 50 == 0:
            print(f"  processed {n_done}/{len(universe)}", flush=True)

    if not all_frames:
        print("No data, abort.")
        return

    big = pd.concat(all_frames, ignore_index=True)
    print(f"\nTotal rows: {len(big):,}  (tickers processed={n_done}, failed={n_fail})", flush=True)

    # 各組 mask
    scanner = big["scanner_fire"]
    kline = big["kline_fire"]
    kline_k12 = big["kline_fire_k12"]
    boosted = scanner & kline           # A
    boosted_k12 = scanner & kline_k12   # A' (no K3)
    control = scanner & ~kline          # B
    control_k12 = scanner & ~kline_k12  # B' (treats K3 as control)
    kline_only = ~scanner & kline       # C
    baseline = pd.Series(True, index=big.index)  # D

    # 進一步分 scanner 子類 (shakeout vs wbottom)
    sk_only = big["sig_shakeout"]
    wb_only = big["sig_wbottom"]

    results = [
        aggregate(big, boosted,     "A:  boosted K1+K2+K3 (current)"),
        aggregate(big, boosted_k12, "A': boosted K1+K2 only (drop K3)"),
        aggregate(big, control,     "B:  control vs A (scanner only, no K123)"),
        aggregate(big, control_k12, "B': control vs A' (scanner only, no K12)"),
        aggregate(big, kline_only,  "C:  kline_only (K1+K2+K3, no scanner)"),
        aggregate(big, baseline,    "D:  baseline (all rows)"),
        aggregate(big, sk_only & kline, "  A1: shakeout × K1+K2+K3"),
        aggregate(big, sk_only & ~kline, "  B1: shakeout × no_kline"),
        aggregate(big, wb_only & kline, "  A2: w_bottom × K1+K2+K3"),
        aggregate(big, wb_only & ~kline, "  B2: w_bottom × no_kline"),
        # 分 pattern 子分組 — raw
        aggregate(big, big["sig_attack_cost"], "K1: attack_cost_displayed (raw)"),
        aggregate(big, big["sig_msir"], "K2: morning_star_island_reversal (raw)"),
        aggregate(big, big["sig_msh"], "K3: morning_star_harami (raw)"),
        # K3 帶條件版本（探討 K3 救援）
        aggregate(big, big["sig_msh_volup"], "K3a: msh + vol_ratio_20 ≥ 1.5"),
        aggregate(big, big["sig_msh_maalign"], "K3b: msh + ma5 ≥ ma10"),
        aggregate(big, big["sig_msh_both"], "K3c: msh + vol + ma_align"),
        # K3 帶條件版本 × scanner
        aggregate(big, scanner & big["sig_msh_volup"], "  A3a: scanner × K3a (msh+vol)"),
        aggregate(big, scanner & big["sig_msh_maalign"], "  A3b: scanner × K3b (msh+ma)"),
        aggregate(big, scanner & big["sig_msh_both"], "  A3c: scanner × K3c (msh+vol+ma)"),
    ]

    # 印 + 寫
    out_path = _REPO / "data" / "analysis" / "kline_patterns" / "kline_tier_a_boost_backtest.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path = out_path.with_suffix(".csv")

    df_results = pd.DataFrame(results)
    df_results.to_csv(csv_path, index=False)
    print(f"\nCSV: {csv_path}")

    # markdown
    lines = [
        "# K 線力量 Tier-A 升等訊號 — Boost EV Backtest",
        "",
        f"- Universe: teacher 332 ({n_done} processed)",
        f"- Period: {START_DATE} → {END_DATE}",
        f"- Scanner proxy: shakeout_strong OR w_bottom_launch (daily_scanner_job main bull layer)",
        f"- K 線 tier-A: attack_cost_displayed / morning_star_island_reversal / morning_star_harami",
        f"- Forward returns: close[d+N] / close[d+0] - 1",
        "",
        "## 主表（boosted vs control vs kline_only vs baseline）",
        "",
        "| group | n | mean_5d | median_5d | wr_5d | cap10_5d | mean_20d | wr_20d |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        def fmt(k, pct=True):
            v = r.get(k)
            if v is None:
                return "—"
            return f"{v*100:+.2f}%" if pct else f"{v:.2%}"
        lines.append(
            f"| {r['group']} | {r['n']:,} | "
            f"{fmt('mean_5d')} | {fmt('median_5d')} | "
            f"{fmt('wr_5d', pct=False)} | {fmt('cap10_5d', pct=False)} | "
            f"{fmt('mean_20d')} | {fmt('wr_20d', pct=False)} |"
        )

    # 主結論：A vs B
    r_a = next(r for r in results if r["group"].startswith("A:  "))
    r_a12 = next(r for r in results if r["group"].startswith("A': "))
    r_b = next(r for r in results if r["group"].startswith("B:  "))
    r_b12 = next(r for r in results if r["group"].startswith("B': "))
    r_c = next(r for r in results if r["group"].startswith("C:  "))
    r_d = next(r for r in results if r["group"].startswith("D:  "))

    def safe(v): return v if v is not None else 0.0

    lines += [
        "",
        "## 升等是否有效？",
        "",
        f"- **A  (current K1+K2+K3) n={r_a['n']}**, mean_5d={safe(r_a['mean_5d'])*100:+.2f}%, mean_20d={safe(r_a['mean_20d'])*100:+.2f}%, wr_5d={safe(r_a['wr_5d']):.1%}",
        f"- **A' (K1+K2 only)       n={r_a12['n']}**, mean_5d={safe(r_a12['mean_5d'])*100:+.2f}%, mean_20d={safe(r_a12['mean_20d'])*100:+.2f}%, wr_5d={safe(r_a12['wr_5d']):.1%}",
        f"- **B  (control vs A)     n={r_b['n']}**, mean_5d={safe(r_b['mean_5d'])*100:+.2f}%, mean_20d={safe(r_b['mean_20d'])*100:+.2f}%, wr_5d={safe(r_b['wr_5d']):.1%}",
        f"- **B' (control vs A')    n={r_b12['n']}**, mean_5d={safe(r_b12['mean_5d'])*100:+.2f}%, mean_20d={safe(r_b12['mean_20d'])*100:+.2f}%, wr_5d={safe(r_b12['wr_5d']):.1%}",
        "",
        f"- A  vs B  : 5d delta=**{(safe(r_a['mean_5d'])-safe(r_b['mean_5d']))*100:+.2f}pp**, 20d delta=**{(safe(r_a['mean_20d'])-safe(r_b['mean_20d']))*100:+.2f}pp**, wr_5d delta=**{(safe(r_a['wr_5d'])-safe(r_b['wr_5d']))*100:+.1f}pp**",
        f"- A' vs B' : 5d delta=**{(safe(r_a12['mean_5d'])-safe(r_b12['mean_5d']))*100:+.2f}pp**, 20d delta=**{(safe(r_a12['mean_20d'])-safe(r_b12['mean_20d']))*100:+.2f}pp**, wr_5d delta=**{(safe(r_a12['wr_5d'])-safe(r_b12['wr_5d']))*100:+.1f}pp**",
        "",
        "## 判讀",
        "",
        "- A' > A → 移除 K3 對升等有效性正面、production 用 K1+K2",
        "- A' ≈ A → K3 可留作 ✨ badge-only、不升 tier",
        "- A' < A → K3 仍貢獻 (反直覺、可能與其他訊號互補)",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report: {out_path}")
    print("\n=== Summary ===")
    print(f"A  (K1+K2+K3) n={r_a['n']:>4}  mean_5d={safe(r_a['mean_5d']):+.2%}  mean_20d={safe(r_a['mean_20d']):+.2%}  wr_5d={safe(r_a['wr_5d']):.1%}")
    print(f"A' (K1+K2)    n={r_a12['n']:>4}  mean_5d={safe(r_a12['mean_5d']):+.2%}  mean_20d={safe(r_a12['mean_20d']):+.2%}  wr_5d={safe(r_a12['wr_5d']):.1%}")
    print(f"B  (no K123)  n={r_b['n']:>4}  mean_5d={safe(r_b['mean_5d']):+.2%}  mean_20d={safe(r_b['mean_20d']):+.2%}  wr_5d={safe(r_b['wr_5d']):.1%}")
    print(f"B' (no K12)   n={r_b12['n']:>4}  mean_5d={safe(r_b12['mean_5d']):+.2%}  mean_20d={safe(r_b12['mean_20d']):+.2%}  wr_5d={safe(r_b12['wr_5d']):.1%}")
    print()
    print(f"A  vs B  : 5d delta={(safe(r_a['mean_5d'])-safe(r_b['mean_5d'])):+.2%}  20d delta={(safe(r_a['mean_20d'])-safe(r_b['mean_20d'])):+.2%}  wr_5d={(safe(r_a['wr_5d'])-safe(r_b['wr_5d']))*100:+.1f}pp")
    print(f"A' vs B' : 5d delta={(safe(r_a12['mean_5d'])-safe(r_b12['mean_5d'])):+.2%}  20d delta={(safe(r_a12['mean_20d'])-safe(r_b12['mean_20d'])):+.2%}  wr_5d={(safe(r_a12['wr_5d'])-safe(r_b12['wr_5d']))*100:+.1f}pp")
    # K3 rescue analysis
    print("\n=== K3 rescue ===")
    for r in results:
        if r["group"].startswith("K3") or "K3" in r["group"]:
            print(f"  {r['group']:50s} n={r['n']:>5}  mean_5d={safe(r['mean_5d']):+.2%}  wr_5d={safe(r['wr_5d']):.1%}  cap10={safe(r['cap10_5d']):.1%}")


if __name__ == "__main__":
    main()
