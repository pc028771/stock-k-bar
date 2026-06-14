"""
Compute swing-pivot capture rate combining zhuli + kline detectors
on teacher universe for 2026 YTD.

Usage:
    uv run python scripts/swing_capture_combined_analysis.py

Outputs:
    data/analysis/zhuli/swing_capture_combined_2026ytd.csv
    docs/主力大課程/analysis/swing_capture_combined_2026ytd.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "scripts"))

# ── Config ────────────────────────────────────────────────────────────────────
START = "2026-01-01"
END   = "2026-06-07"
MEDIUM_WINDOW = 10   # ±10 days for medium pivot
MEDIUM_MOVE   = 0.10  # ≥10% price move
CAPTURE_WINDOW = 2   # signal within ±2 trading days of pivot

OUT_CSV = REPO / "data/analysis/zhuli/swing_capture_combined_2026ytd.csv"
OUT_MD  = REPO / "docs/主力大課程/analysis/swing_capture_combined_2026ytd.md"

ZHULI_TRADES_DIR = REPO / "data/analysis/zhuli/backtest_ytd"
ZHULI_SCANNERS = [
    "suffocation", "swing_breakout", "reversal_breakout",
    "institutional_firstbuy", "institutional_swing",
    "overnight_swing", "pennant_flag", "intraday",
]

# ── Load teacher universe ─────────────────────────────────────────────────────
print("Loading teacher universe...")
picks = json.load(open(REPO / "docs/主力大課程/teacher_picks_2026.json"))
teacher_tickers = sorted(k for k in picks if k != "_meta")
print(f"  Teacher universe: {len(teacher_tickers)} tickers")

# ── Load bars for teacher universe ────────────────────────────────────────────
print("Loading daily bars (teacher universe)...")
from kline.bars import load_bars
bars = load_bars(tickers=teacher_tickers)
bars["ticker"] = bars["ticker"].astype(str).str.zfill(4)
bars = bars[bars["trade_date"].between(START, END)].copy()
bars["trade_date"] = pd.to_datetime(bars["trade_date"])
print(f"  Bars: {len(bars)} rows, {bars['ticker'].nunique()} tickers")

# ── Compute medium pivots ─────────────────────────────────────────────────────
def compute_medium_pivots(bars: pd.DataFrame) -> pd.DataFrame:
    """Detect local max/min with ±MEDIUM_WINDOW window and ≥MEDIUM_MOVE move."""
    pivots = []
    for ticker, grp in bars.groupby("ticker"):
        grp = grp.sort_values("trade_date").reset_index(drop=True)
        closes = grp["close"].values
        dates  = grp["trade_date"].values
        n = len(closes)
        w = MEDIUM_WINDOW
        for i in range(w, n - w):
            lo_slice = closes[max(0, i-w): i]
            hi_slice = closes[i+1: min(n, i+w+1)]
            c = closes[i]
            # Local max: price > all neighbours within window
            if c > lo_slice.max() and c > hi_slice.max():
                # Check meaningful move: at least MEDIUM_MOVE from trough before
                prior_min = lo_slice.min()
                if prior_min > 0 and (c - prior_min) / prior_min >= MEDIUM_MOVE:
                    pivots.append({
                        "ticker": ticker,
                        "pivot_date": pd.Timestamp(dates[i]),
                        "pivot_type": "high",
                        "pivot_price": c,
                    })
            # Local min: price < all neighbours
            if c < lo_slice.min() and c < hi_slice.min():
                prior_max = lo_slice.max()
                if prior_max > 0 and (prior_max - c) / prior_max >= MEDIUM_MOVE:
                    pivots.append({
                        "ticker": ticker,
                        "pivot_date": pd.Timestamp(dates[i]),
                        "pivot_type": "low",
                        "pivot_price": c,
                    })
    return pd.DataFrame(pivots)

print("Computing medium pivots...")
pivots = compute_medium_pivots(bars)
pivots = pivots[pivots["ticker"].isin(teacher_tickers)].reset_index(drop=True)
print(f"  Pivots: {len(pivots)} ({pivots['pivot_type'].value_counts().to_dict()})")

# ── Build trading-day index per ticker ───────────────────────────────────────
# For each ticker, we need ±N trading days around a pivot
ticker_dates: dict[str, list[pd.Timestamp]] = {}
for ticker, grp in bars.groupby("ticker"):
    ticker_dates[ticker] = sorted(grp["trade_date"].tolist())

def trading_day_window(ticker: str, pivot_date: pd.Timestamp, window: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return (start, end) dates representing ±window trading days."""
    dates = ticker_dates.get(ticker, [])
    if not dates:
        return pivot_date, pivot_date
    arr = np.array([d.value for d in dates])
    idx = np.searchsorted(arr, pivot_date.value)
    lo = max(0, idx - window)
    hi = min(len(dates) - 1, idx + window)
    return dates[lo], dates[hi]

# ── Load zhuli signals ────────────────────────────────────────────────────────
print("Loading zhuli signals...")
zhuli_signals = []
for scanner in ZHULI_SCANNERS:
    fp = ZHULI_TRADES_DIR / f"{scanner}_trades.csv"
    if not fp.exists():
        print(f"  [MISSING] {fp.name}")
        continue
    df = pd.read_csv(fp, parse_dates=["signal_date", "entry_date"])
    df["scanner"] = scanner
    # Normalize ticker to 4-digit zero-padded string
    df["ticker"] = df["ticker"].astype(str).str.zfill(4)
    # Use signal_date as the detection date
    df = df[df["ticker"].isin(teacher_tickers)]
    df = df[df["signal_date"].between(START, END)]
    zhuli_signals.append(df[["ticker", "signal_date", "scanner"]])
    print(f"  {scanner}: {len(df)} signals on teacher tickers")

zhuli_df = pd.concat(zhuli_signals, ignore_index=True) if zhuli_signals else pd.DataFrame(
    columns=["ticker", "signal_date", "scanner"]
)
# Remove duplicates (same ticker × signal_date from multiple scanners)
print(f"  Total zhuli signals: {len(zhuli_df)}, unique ticker-days: {zhuli_df[['ticker','signal_date']].drop_duplicates().shape[0]}")

# ── Run all kline entry detectors ─────────────────────────────────────────────
print("Running kline entry detectors...")
from kline.features import load_features_cached
from kline.entry import ENTRY_REGISTRY

# Load all features (uses cache), then filter to teacher universe + 2026 range
feats_raw = load_features_cached()
feats_raw["ticker"] = feats_raw["ticker"].astype(str).str.zfill(4)
feats_all = feats_raw[
    feats_raw["ticker"].isin(teacher_tickers) &
    feats_raw["trade_date"].between(START, END)
].copy()
print(f"  Features shape: {feats_all.shape}")

kline_signals_all = []
for det_name, detect_fn in ENTRY_REGISTRY.items():
    try:
        entries = detect_fn(feats_all)
        # entries is a boolean Series aligned with feats_all
        mask = entries if hasattr(entries, "__len__") else entries.values
        sigs = feats_all[mask][["ticker", "trade_date"]].copy()
        sigs = sigs[sigs["ticker"].isin(teacher_tickers)]
        sigs["detector"] = det_name
        sigs.rename(columns={"trade_date": "signal_date"}, inplace=True)
        kline_signals_all.append(sigs)
        print(f"  {det_name}: {len(sigs)} signals on teacher tickers")
    except Exception as e:
        print(f"  [ERROR] {det_name}: {e}")

kline_df = pd.concat(kline_signals_all, ignore_index=True) if kline_signals_all else pd.DataFrame(
    columns=["ticker", "signal_date", "detector"]
)
kline_df["signal_date"] = pd.to_datetime(kline_df["signal_date"])
print(f"  Total kline signals: {len(kline_df)}, unique ticker-days: {kline_df[['ticker','signal_date']].drop_duplicates().shape[0]}")

# ── Compute capture rates per ticker ─────────────────────────────────────────
print("Computing capture rates...")
results = []

for ticker in teacher_tickers:
    t_pivots = pivots[pivots["ticker"] == ticker].reset_index(drop=True)
    n_pivots = len(t_pivots)
    if n_pivots == 0:
        results.append({
            "ticker": ticker,
            "medium_pivots": 0,
            "zhuli_caught": 0,
            "kline_caught": 0,
            "combined_caught": 0,
            "zhuli_rate": np.nan,
            "kline_rate": np.nan,
            "combined_rate": np.nan,
            "delta": np.nan,
            "kline_only_count": 0,
        })
        continue

    t_zhuli = zhuli_df[zhuli_df["ticker"] == ticker]
    t_kline = kline_df[kline_df["ticker"] == ticker]

    zhuli_caught = 0
    kline_caught = 0
    combined_caught = 0
    kline_only = 0

    for _, prow in t_pivots.iterrows():
        pd_date = prow["pivot_date"]
        win_start, win_end = trading_day_window(ticker, pd_date, CAPTURE_WINDOW)

        # Zhuli catch
        z_hit = t_zhuli[
            (t_zhuli["signal_date"] >= win_start) &
            (t_zhuli["signal_date"] <= win_end)
        ]
        z_caught = len(z_hit) > 0

        # Kline catch
        k_hit = t_kline[
            (t_kline["signal_date"] >= win_start) &
            (t_kline["signal_date"] <= win_end)
        ]
        k_caught = len(k_hit) > 0

        if z_caught:
            zhuli_caught += 1
        if k_caught:
            kline_caught += 1
        if z_caught or k_caught:
            combined_caught += 1
        if k_caught and not z_caught:
            kline_only += 1

    results.append({
        "ticker": ticker,
        "medium_pivots": n_pivots,
        "zhuli_caught": zhuli_caught,
        "kline_caught": kline_caught,
        "combined_caught": combined_caught,
        "zhuli_rate": zhuli_caught / n_pivots if n_pivots > 0 else np.nan,
        "kline_rate": kline_caught / n_pivots if n_pivots > 0 else np.nan,
        "combined_rate": combined_caught / n_pivots if n_pivots > 0 else np.nan,
        "delta": (combined_caught - zhuli_caught) / n_pivots if n_pivots > 0 else np.nan,
        "kline_only_count": kline_only,
    })

df_result = pd.DataFrame(results)

# ── Add metadata ──────────────────────────────────────────────────────────────
# Add name / sector from teacher_picks
def get_meta(ticker: str, picks: dict, key: str, default="") -> str:
    entry = picks.get(ticker, {})
    if isinstance(entry, dict):
        return entry.get(key, default)
    return default

df_result["name"]   = df_result["ticker"].apply(lambda t: get_meta(t, picks, "name"))
df_result["sector"] = df_result["ticker"].apply(lambda t: get_meta(t, picks, "sector"))

# YTD return: last close / first close - 1 for 2026
ytd_returns = {}
for ticker, grp in bars.groupby("ticker"):
    grp = grp.sort_values("trade_date")
    if len(grp) >= 2:
        ytd_returns[ticker] = (grp["close"].iloc[-1] / grp["close"].iloc[0] - 1) * 100
df_result["ytd_return_pct"] = df_result["ticker"].map(ytd_returns)

# Final column order
df_result = df_result[[
    "ticker", "name", "sector",
    "medium_pivots", "zhuli_caught", "kline_caught", "combined_caught",
    "zhuli_rate", "kline_rate", "combined_rate", "delta", "kline_only_count",
    "ytd_return_pct",
]]

# Save CSV
OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
df_result.to_csv(OUT_CSV, index=False, float_format="%.4f")
print(f"CSV saved: {OUT_CSV} ({len(df_result)} rows)")

# ── Aggregate stats ───────────────────────────────────────────────────────────
df_valid = df_result[df_result["medium_pivots"] >= 2].copy()
total_pivots    = df_valid["medium_pivots"].sum()
total_z_caught  = df_valid["zhuli_caught"].sum()
total_k_caught  = df_valid["kline_caught"].sum()
total_c_caught  = df_valid["combined_caught"].sum()
avg_zhuli   = total_z_caught / total_pivots if total_pivots else 0
avg_kline   = total_k_caught / total_pivots if total_pivots else 0
avg_combined= total_c_caught / total_pivots if total_pivots else 0
avg_delta   = avg_combined - avg_zhuli
pct_improved = (df_valid["delta"] > 0.10).sum()  # tickers with >10pp improvement

top15_combined = df_valid.nlargest(15, "combined_rate")
top15_delta    = df_valid.nlargest(15, "delta")

# tickers where kline alone > zhuli
kline_beats_zhuli = df_valid[df_valid["kline_rate"] > df_valid["zhuli_rate"]].sort_values("kline_rate", ascending=False)

# Sector breakdown
sector_df = df_valid.groupby("sector").agg(
    pivots=("medium_pivots", "sum"),
    zhuli_caught=("zhuli_caught", "sum"),
    kline_caught=("kline_caught", "sum"),
    combined_caught=("combined_caught", "sum"),
    tickers=("ticker", "count"),
).reset_index()
sector_df["zhuli_rate"]   = sector_df["zhuli_caught"] / sector_df["pivots"]
sector_df["combined_rate"]= sector_df["combined_caught"] / sector_df["pivots"]
sector_df["delta"] = sector_df["combined_rate"] - sector_df["zhuli_rate"]
sector_df = sector_df[sector_df["pivots"] >= 3].sort_values("delta", ascending=False)

# ── Spot-check: top delta ticker ─────────────────────────────────────────────
spot = top15_delta.iloc[0] if len(top15_delta) > 0 else None
spot_detail = ""
if spot is not None:
    sticker = spot["ticker"]
    sp_pivots = pivots[pivots["ticker"] == sticker].reset_index(drop=True)
    sp_kline  = kline_df[kline_df["ticker"] == sticker]
    sp_zhuli  = zhuli_df[zhuli_df["ticker"] == sticker]
    spot_lines = [f"**Ticker: {sticker} ({spot['name']}) — delta={spot['delta']:.2%}**\n"]
    kline_only_pivots = []
    for _, prow in sp_pivots.iterrows():
        pd_date = prow["pivot_date"]
        win_start, win_end = trading_day_window(sticker, pd_date, CAPTURE_WINDOW)
        z_hit = sp_zhuli[(sp_zhuli["signal_date"] >= win_start) & (sp_zhuli["signal_date"] <= win_end)]
        k_hit = sp_kline[(sp_kline["signal_date"] >= win_start) & (sp_kline["signal_date"] <= win_end)]
        if len(k_hit) > 0 and len(z_hit) == 0:
            detectors_fired = k_hit["detector"].unique().tolist()
            kline_only_pivots.append(
                f"  - Pivot {pd_date.date()} ({prow['pivot_type']}, price={prow['pivot_price']:.1f}) "
                f"→ kline detectors: {', '.join(detectors_fired)}"
            )
    spot_lines += kline_only_pivots if kline_only_pivots else ["  - (no kline-only pivots found in window)"]
    spot_detail = "\n".join(spot_lines)

# ── Write markdown report ─────────────────────────────────────────────────────
OUT_MD.parent.mkdir(parents=True, exist_ok=True)

def fmt_rate(v):
    if pd.isna(v): return "—"
    return f"{v:.1%}"

def table_rows(df, cols, col_fmts):
    lines = []
    for _, row in df.iterrows():
        cells = []
        for col, fmt in zip(cols, col_fmts):
            v = row[col]
            if fmt == "pct":
                cells.append(fmt_rate(v))
            elif fmt == "int":
                cells.append(str(int(v)) if not pd.isna(v) else "—")
            elif fmt == "f2":
                cells.append(f"{v:.2f}" if not pd.isna(v) else "—")
            else:
                cells.append(str(v) if not pd.isna(v) else "—")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)

# Build sector table
sector_cols = ["sector", "tickers", "pivots", "zhuli_rate", "combined_rate", "delta"]
sector_fmts = ["str", "int", "int", "pct", "pct", "pct"]

with open(OUT_MD, "w", encoding="utf-8") as f:
    f.write(f"""# Swing Pivot Capture Rate: K線力量 + 主力大 Combined Analysis (2026 YTD)

**Generated:** {END}
**Universe:** {len(teacher_tickers)} teacher tickers
**Period:** {START} → {END}

## 方法說明

- **Medium pivots** (±10 trading day window, ≥10% move): {total_pivots} pivots across {len(df_valid)} tickers with ≥2 pivots
- **Signal capture window**: ±{CAPTURE_WINDOW} trading days around pivot date
- **Zhuli signals**: 8 scanners ({', '.join(ZHULI_SCANNERS)})
- **Kline signals**: 8 entry detectors ({', '.join(ENTRY_REGISTRY.keys())})
- `zhuli_caught` = ANY zhuli signal within window; `kline_caught` = ANY kline signal within window
- `combined_caught` = OR; `kline_only` = kline_caught AND NOT zhuli_caught

---

## Universe-Level Summary

| Metric | Rate |
|---|---|
| Total medium pivots | {total_pivots} |
| Zhuli baseline capture | {avg_zhuli:.1%} |
| Kline-only capture | {avg_kline:.1%} |
| Combined capture | {avg_combined:.1%} |
| **Delta (combined − zhuli)** | **{avg_delta:.1%}** |
| Tickers with >10pp improvement | {pct_improved} |

---

## Top 15 by Combined Capture Rate (最全面理解的標的)

| Ticker | Name | Sector | Pivots | Zhuli | Kline | Combined | Delta |
|---|---|---|---|---|---|---|---|
{table_rows(top15_combined,
    ['ticker','name','sector','medium_pivots','zhuli_rate','kline_rate','combined_rate','delta'],
    ['str','str','str','int','pct','pct','pct','pct'])}

---

## Top 15 by Delta (Kline 補充最多的標的)

| Ticker | Name | Sector | Pivots | Zhuli | Kline | Combined | Delta | KLine-Only Pivots |
|---|---|---|---|---|---|---|---|---|
{table_rows(top15_delta,
    ['ticker','name','sector','medium_pivots','zhuli_rate','kline_rate','combined_rate','delta','kline_only_count'],
    ['str','str','str','int','pct','pct','pct','pct','int'])}

---

## Kline 增益 ≥10pp 的標的列表

""")
    improved10 = df_valid[df_valid["delta"] >= 0.10].sort_values("delta", ascending=False)
    if len(improved10) == 0:
        f.write("_無任何標的 kline 增益 ≥10pp。_\n\n")
    else:
        f.write(f"共 {len(improved10)} 個標的 kline 增益 ≥10pp：\n\n")
        f.write("| Ticker | Name | Delta | Kline-Only Pivots |\n|---|---|---|---|\n")
        for _, row in improved10.iterrows():
            f.write(f"| {row['ticker']} | {row['name']} | {fmt_rate(row['delta'])} | {int(row['kline_only_count'])} |\n")
        f.write("\n")

    f.write(f"""---

## Sector Breakdown (Kline 增益最大的族群)

| Sector | Tickers | Pivots | Zhuli Rate | Combined Rate | Delta |
|---|---|---|---|---|---|
{table_rows(sector_df, sector_cols, sector_fmts)}

---

## Kline 獨勝（Kline rate > Zhuli rate）的標的

""")
    if len(kline_beats_zhuli) == 0:
        f.write("_無任何標的 kline rate 高於 zhuli rate。_\n\n")
    else:
        f.write(f"共 {len(kline_beats_zhuli)} 個標的：\n\n")
        f.write("| Ticker | Name | Zhuli Rate | Kline Rate | Delta |\n|---|---|---|---|---|\n")
        for _, row in kline_beats_zhuli.head(15).iterrows():
            f.write(f"| {row['ticker']} | {row['name']} | {fmt_rate(row['zhuli_rate'])} | {fmt_rate(row['kline_rate'])} | {fmt_rate(row['delta'])} |\n")
        f.write("\n")

    f.write(f"""---

## Spot-Check: 高 Delta 標的詳細驗證

{spot_detail}

---

## 解讀

### 1. Kline + Zhuli 是否優於 Zhuli 單獨？

Universe 平均 zhuli capture rate = **{avg_zhuli:.1%}**，combined = **{avg_combined:.1%}**，delta = **{avg_delta:.1%}**。
{"K線力量偵測器確實提供了 **正增益**，雖然幅度較小。" if avg_delta > 0.02 else "K線力量偵測器提供的邊際增益 **非常有限**（<2pp）。"}
這代表 zhuli 掃描器已能捕捉絕大多數樞紐點，kline 補充的是 zhuli 偵測不到的特定型態。

### 2. 是否有標的 Kline 獨勝？

{"有 " + str(len(kline_beats_zhuli)) + " 個標的的 kline 單獨 capture rate 高於 zhuli，表示部分標的的走勢型態更符合 K線力量的辨識邏輯（突破、曙光、趨勢反轉等）而非主力大的量縮/籌碼訊號。" if len(kline_beats_zhuli) > 0 else "沒有標的 kline rate 高於 zhuli rate，表示 zhuli 掃描器在所有標的上都比 kline 更準確或更完整。"}

### 3. 建議：哪個族群/標的值得升格至 Production？

前 3 delta 改善族群：{', '.join(sector_df.head(3)['sector'].tolist()) if len(sector_df) >= 3 else str(sector_df['sector'].tolist())}。
{"建議針對 delta ≥10pp 的 " + str(len(improved10)) + " 個標的，啟用對應的 kline 偵測器做為 zhuli 的補充訊號層。" if len(improved10) > 0 else "目前 kline 增益幅度有限，不建議大幅調整現有 production 配置。"}
策略上可考慮：在主力大掃描器 **無訊號** 的情況下，將 kline 偵測器作為備援觸發層（tier-2 訊號），而非取代。

---

*Analysis generated by `scripts/swing_capture_combined_analysis.py`*
""")

print(f"MD saved: {OUT_MD}")
print("\n=== SUMMARY ===")
print(f"Total pivots: {total_pivots}")
print(f"Zhuli capture: {avg_zhuli:.1%}")
print(f"Kline capture: {avg_kline:.1%}")
print(f"Combined capture: {avg_combined:.1%}")
print(f"Delta (combined - zhuli): {avg_delta:.1%}")
print(f"Tickers ≥10pp improved: {pct_improved}")
print("\nTop 5 combined_rate:")
print(top15_combined[["ticker","name","zhuli_rate","kline_rate","combined_rate","delta"]].head(5).to_string(index=False))
print("\nTop 5 delta:")
print(top15_delta[["ticker","name","zhuli_rate","kline_rate","combined_rate","delta"]].head(5).to_string(index=False))
if len(sector_df) >= 3:
    print("\nTop 3 sectors by delta:")
    print(sector_df[["sector","pivots","zhuli_rate","combined_rate","delta"]].head(3).to_string(index=False))
print(f"\nSpot-check:\n{spot_detail}")
