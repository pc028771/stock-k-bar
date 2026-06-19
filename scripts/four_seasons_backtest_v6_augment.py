"""Four-Seasons backtest v6 augmentation — 套用 2026-06-08 校正方法論.

Input: 既有 v5 final trades CSV (backtest_2025_final_trades.csv).
Reads trade list (245 entries), 加上新維度後產出 v6 report.

依 memory `feedback_scanner_evaluation_correction_20260608` + `small_sample_preference`:

  1. 雙維度 (WR + capture)
     - WR = win rate conditional on entry firing (既有)
     - cap10 = ≥ +10% trade 的比率 (大魚抓到率)
     - cap20 = ≥ +20% (主升段)
     - **WR 高但 cap10 低 = 小贏漏大魚、不是真 edge**

  2. Segment audit (per season × exit_reason 已有、保留)

  3. 小樣本可信原則：n 小 + 穩定 > n 大 + 稀釋；不放寬條件「擴大樣本」

  4. Per-trade max drawdown：補課程外但實用、看 trail-stop 設定是否吃到太深虧

  5. **K 線 Tier-A 升等 cross** (本 v6 新增)：
     - 對 long 進場日 (春/立夏/盛夏)、檢查當日是否亮 K1 (attack_cost_displayed)
       或 K2 (morning_star_island_reversal)
     - 比 boosted (有 K 線命中) vs control (沒命中) 的 WR/cap10/mean
     - 若 boosted 顯著贏 → 加入 four-seasons production filter

Output:
  - data/analysis/four_seasons/backtest_2026_v6_report.md
  - data/analysis/four_seasons/backtest_2026_v6_trades_aug.csv
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).parent.parent
_SCRIPTS = _REPO / "scripts"
for _p in [str(_REPO), str(_SCRIPTS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kline.features import add_features  # noqa: E402
from kline.patterns.attack_cost_displayed import detect as detect_attack_cost  # noqa: E402
from kline.patterns.morning_star_island_reversal import detect as detect_msir  # noqa: E402


DB_PATH = Path.home() / ".four_seasons" / "data.sqlite"
TRADES_CSV = _REPO / "data" / "analysis" / "four_seasons" / "backtest_2025_final_trades.csv"
OUT_REPORT = _REPO / "data" / "analysis" / "four_seasons" / "backtest_2026_v6_report.md"
OUT_AUG_TRADES = _REPO / "data" / "analysis" / "four_seasons" / "backtest_2026_v6_trades_aug.csv"


def load_bars_for_ticker(ticker: str, start: str, end: str) -> pd.DataFrame:
    uri = f"file:{DB_PATH}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=10)
    df = pd.read_sql(
        """SELECT ? as ticker, trade_date, open, high, low, close, volume,
                  vol_ratio_20, ma5, ma10, ma20, ma60
           FROM standard_daily_bar
           WHERE ticker = ? AND trade_date >= date(?, '-90 days')
             AND trade_date <= ?
           ORDER BY trade_date""",
        con, params=(ticker, ticker, start, end),
    )
    con.close()
    return df


def kline_tier_a_on_entry(trade_row: pd.Series, bars_cache: dict) -> tuple[bool, bool]:
    """Return (k1_fired, k2_fired) on entry_date for given trade."""
    ticker = str(trade_row["ticker"])
    entry_date = str(trade_row["entry_date"])[:10]
    cache_key = (ticker, entry_date)
    if cache_key in bars_cache:
        return bars_cache[cache_key]

    df = load_bars_for_ticker(ticker, entry_date, entry_date)
    if df.empty or len(df) < 60:
        bars_cache[cache_key] = (False, False)
        return False, False

    # Add derived cols required by attack_cost (prior_high_60 + minute db handled internally)
    df["prior_high_60"] = df["high"].rolling(60, min_periods=20).max().shift(1)

    try:
        df = add_features(df, groups=["basic", "volume", "historical", "pattern"])
    except Exception:
        bars_cache[cache_key] = (False, False)
        return False, False

    # 找 entry_date 那行
    date_mask = df["trade_date"].astype(str).str[:10] == entry_date
    if not date_mask.any():
        bars_cache[cache_key] = (False, False)
        return False, False

    try:
        sig_k1 = detect_attack_cost(df).fillna(False)
        sig_k2 = detect_msir(df).fillna(False)
    except Exception:
        bars_cache[cache_key] = (False, False)
        return False, False

    k1 = bool(sig_k1[date_mask].any())
    k2 = bool(sig_k2[date_mask].any())
    bars_cache[cache_key] = (k1, k2)
    return k1, k2


def compute_drawdown(trade_row: pd.Series, dd_cache: dict) -> float:
    """Min (close / entry_close - 1) during hold period — most negative = max dd.

    回傳 negative pct (e.g. -8.5 表示 hold 期間最大跌幅 -8.5%).
    """
    ticker = str(trade_row["ticker"])
    entry_date = str(trade_row["entry_date"])[:10]
    exit_date = str(trade_row["exit_date"])[:10]
    cache_key = (ticker, entry_date, exit_date)
    if cache_key in dd_cache:
        return dd_cache[cache_key]

    uri = f"file:{DB_PATH}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=10)
    df = pd.read_sql(
        """SELECT close, low FROM standard_daily_bar
           WHERE ticker = ? AND trade_date >= ? AND trade_date <= ?
           ORDER BY trade_date""",
        con, params=(ticker, entry_date, exit_date),
    )
    con.close()
    if df.empty:
        dd_cache[cache_key] = 0.0
        return 0.0
    entry_close = float(trade_row["entry_close"])
    # 用 low 取最壞情況
    min_low = float(df["low"].min())
    dd = (min_low - entry_close) / entry_close * 100
    dd_cache[cache_key] = dd
    return dd


def summarize(sub: pd.DataFrame, label: str) -> dict:
    n = len(sub)
    if n == 0:
        return {"label": label, "n": 0, "wr": None, "mean": None, "median": None,
                "cap10": None, "cap20": None, "median_dd": None, "worst_dd": None,
                "median_days": None}
    rets = sub["return_pct"]
    return {
        "label": label,
        "n": n,
        "wr": float((rets > 0).mean()),
        "mean": float(rets.mean()),
        "median": float(rets.median()),
        "cap10": float((rets >= 10).mean()),
        "cap20": float((rets >= 20).mean()),
        "median_dd": float(sub["max_dd_pct"].median()),
        "worst_dd": float(sub["max_dd_pct"].min()),
        "median_days": float(sub["days_held"].median()),
    }


def fmt_pct(v, plus=True, decimals=2):
    if v is None or pd.isna(v):
        return "—"
    if plus and v >= 0:
        return f"+{v:.{decimals}f}%"
    return f"{v:.{decimals}f}%"


def fmt_rate(v, decimals=1):
    if v is None or pd.isna(v):
        return "—"
    return f"{v*100:.{decimals}f}%"


def row_md(r: dict) -> str:
    days = "—" if r['median_days'] is None else f"{r['median_days']:.0f}d"
    return (
        f"| {r['label']} | {r['n']} | {fmt_rate(r['wr'])} | "
        f"{fmt_pct(r['mean'])} | {fmt_pct(r['median'])} | "
        f"{fmt_rate(r['cap10'])} | {fmt_rate(r['cap20'])} | "
        f"{fmt_pct(r['median_dd'], plus=False)} | "
        f"{fmt_pct(r['worst_dd'], plus=False)} | "
        f"{days} |"
    )


def main():
    trades = pd.read_csv(TRADES_CSV)
    # 只看 closed (censored 等於還在場上、return_pct 是 MTM 不算實現)
    closed = trades[~trades["censored"]].copy()
    print(f"Closed trades: {len(closed)}", flush=True)

    # Augment: max drawdown + K 線 tier-A on entry
    dd_cache: dict = {}
    bars_cache: dict = {}
    k1_list, k2_list, dd_list = [], [], []
    for i, row in closed.iterrows():
        dd = compute_drawdown(row, dd_cache)
        if row["side"] == "long":
            k1, k2 = kline_tier_a_on_entry(row, bars_cache)
        else:
            k1, k2 = False, False  # short side 不適用 bull kline
        k1_list.append(k1)
        k2_list.append(k2)
        dd_list.append(dd)
        if (i + 1) % 50 == 0:
            print(f"  augmented {i+1}/{len(closed)}", flush=True)

    closed["max_dd_pct"] = dd_list
    closed["kline_k1"] = k1_list
    closed["kline_k2"] = k2_list
    closed["kline_any"] = closed["kline_k1"] | closed["kline_k2"]
    closed.to_csv(OUT_AUG_TRADES, index=False)
    print(f"\nAugmented trades CSV: {OUT_AUG_TRADES}", flush=True)

    long_trades = closed[closed["side"] == "long"]

    # === 主表 by season ===
    season_rows: list[dict] = []
    for season in ["春", "立夏", "盛夏", "秋"]:
        sub = closed[closed["season"] == season]
        season_rows.append(summarize(sub, season))

    # === Segment by season × exit_reason ===
    seg_rows: list[dict] = []
    for (season, exit_r), sub in closed.groupby(["season", "exit_reason"]):
        seg_rows.append(summarize(sub, f"{season} / {exit_r}"))
    seg_rows.sort(key=lambda r: -r["n"])

    # === K 線 tier-A cross (long only) ===
    kline_rows = [
        summarize(long_trades[long_trades["kline_any"]],
                  "A: long + K1/K2 (boosted)"),
        summarize(long_trades[~long_trades["kline_any"]],
                  "B: long, no K1/K2 (control)"),
        summarize(long_trades[long_trades["kline_k1"]],
                  "  A1: long + K1 attack_cost"),
        summarize(long_trades[long_trades["kline_k2"]],
                  "  A2: long + K2 morning_star_island"),
    ]

    # === K 線 tier-A cross × season ===
    kline_season_rows = []
    for season in ["春", "立夏", "盛夏"]:
        sub_s = long_trades[long_trades["season"] == season]
        kline_season_rows.append(
            summarize(sub_s[sub_s["kline_any"]], f"{season}: boosted (K1/K2)")
        )
        kline_season_rows.append(
            summarize(sub_s[~sub_s["kline_any"]], f"{season}: control")
        )

    # === Per-ticker quadrant (Q1 = WR ≥ 50% AND cap10 ≥ 20%) ===
    per_ticker: list[dict] = []
    for (ticker, name), sub in closed.groupby(["ticker", "name"]):
        if len(sub) < 2:
            continue
        per_ticker.append({
            "ticker": str(ticker),
            "name": name,
            "n": int(len(sub)),
            "wr": float((sub["return_pct"] > 0).mean()),
            "cap10": float((sub["return_pct"] >= 10).mean()),
            "mean": float(sub["return_pct"].mean()),
        })
    pt_df = pd.DataFrame(per_ticker)
    if len(pt_df):
        q1 = pt_df[(pt_df["wr"] >= 0.5) & (pt_df["cap10"] >= 0.2)].sort_values("mean", ascending=False)
        q1_text = "\n".join(
            f"| {r['ticker']} | {r['name']} | {r['n']} | "
            f"{r['wr']*100:.0f}% | {r['cap10']*100:.0f}% | {r['mean']:+.2f}% |"
            for _, r in q1.iterrows()
        )
    else:
        q1 = pd.DataFrame()
        q1_text = ""

    # === Compose markdown ===
    lines = [
        "# Four-Seasons Backtest v6 — 2026-06-08 校正方法論 + K 線 Tier-A cross",
        "",
        f"- Total trades: {len(trades)} (closed: {len(closed)}, censored: {len(trades) - len(closed)})",
        f"- Entry-day range: {closed['entry_date'].min()} → {closed['entry_date'].max()}",
        f"- 套用方法論: feedback_scanner_evaluation_correction_20260608 "
        f"(雙維度 WR + cap10 + segment audit) + small_sample_preference",
        f"- K 線 tier-A: attack_cost_displayed (K1) + morning_star_island_reversal (K2)",
        "",
        "## 1. 各季節主表 (closed only)",
        "",
        "| 季節 | n | WR | mean ret | median ret | **cap10** | **cap20** | median_dd | worst_dd | median 持倉 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in season_rows:
        lines.append(row_md(r))

    lines += [
        "",
        "**判讀 (per `feedback_small_sample_preference` 雙維度):**",
        "- cap10 (大魚抓到率) ≥ 20% + WR ≥ 45% = 真 edge",
        "- WR 高但 cap10 低 = 小贏稀釋大魚、四季 trend rider 邏輯失效",
        "- worst_dd < -15% = 中途吃過大套牢、需檢視 trailing-stop 設定",
        "",
        "## 2. By 季節 × exit_reason segment",
        "",
        "| 季節 / exit | n | WR | mean | median | cap10 | cap20 | median_dd | worst_dd | 持倉 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in seg_rows:
        lines.append(row_md(r))

    lines += [
        "",
        "## 3. K 線 Tier-A 升等 cross (long only) — 新增、本 v6 重點",
        "",
        "| group | n | WR | mean | median | cap10 | cap20 | median_dd | worst_dd | 持倉 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in kline_rows:
        lines.append(row_md(r))

    # boost delta
    a = kline_rows[0]
    b = kline_rows[1]
    if a["n"] and b["n"]:
        lines += [
            "",
            f"**A vs B 升等效果:**",
            f"- mean delta: **{(a['mean'] - b['mean']):+.2f}pp**",
            f"- WR delta: **{(a['wr'] - b['wr'])*100:+.1f}pp**",
            f"- cap10 delta: **{(a['cap10'] - b['cap10'])*100:+.1f}pp**",
            f"- A 樣本: n={a['n']} {'(夠決策、≥30)' if a['n'] >= 30 else '(偏小 < 30、需更多資料)'}",
        ]

    lines += [
        "",
        "### 3.1 K 線 cross × 季節",
        "",
        "| group | n | WR | mean | median | cap10 | cap20 | median_dd | worst_dd | 持倉 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in kline_season_rows:
        lines.append(row_md(r))

    lines += [
        "",
        "## 4. Per-ticker quadrant — Q1 真 edge (WR ≥ 50% AND cap10 ≥ 20%, n ≥ 2)",
        "",
        "| ticker | name | n | WR | cap10 | mean ret |",
        "|---|---|---|---|---|---|",
        q1_text or "| _(無 Q1 ticker)_ | | | | | |",
        "",
        f"- Q1 tickers: {len(q1)} / {len(pt_df)} ({len(q1)/max(1, len(pt_df))*100:.0f}%)",
        "",
        "## 5. 判讀與行動",
        "",
        "(待 user 看完上方數字後判讀；本檔不寫死結論、避免 AI 過度詮釋。)",
        "",
        "## Files",
        "",
        f"- Augmented trades: `{OUT_AUG_TRADES.relative_to(_REPO)}`",
        f"- This report: `{OUT_REPORT.relative_to(_REPO)}`",
        f"- Source trades (v5 unchanged): `{TRADES_CSV.relative_to(_REPO)}`",
    ]

    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {OUT_REPORT}", flush=True)
    print("\n=== Summary ===")
    for r in season_rows:
        print(f"{r['label']}: n={r['n']} WR={fmt_rate(r['wr'])} "
              f"mean={fmt_pct(r['mean'])} cap10={fmt_rate(r['cap10'])} "
              f"worst_dd={fmt_pct(r['worst_dd'], plus=False)}")
    print()
    print(f"K 線 boost: A n={a['n']} mean={fmt_pct(a['mean'])} cap10={fmt_rate(a['cap10'])}")
    print(f"            B n={b['n']} mean={fmt_pct(b['mean'])} cap10={fmt_rate(b['cap10'])}")
    if a['n'] and b['n']:
        print(f"            delta: mean {(a['mean']-b['mean']):+.2f}pp, "
              f"cap10 {(a['cap10']-b['cap10'])*100:+.1f}pp")


if __name__ == "__main__":
    main()
