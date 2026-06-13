"""
Swing Turning-Point Capture Rate Analysis
2026 YTD — Teacher Universe

Measures whether the scanner identifies pivot points (能不能抓到轉折),
not trade frequency or win rate.
"""
import os
import pandas as pd
import numpy as np
from datetime import datetime

from zhuli.db import get_conn

# ─── Config ───────────────────────────────────────────────────────────────────
DB_PATH        = "/Users/howard/.four_seasons/data.sqlite"
UNIVERSE_CSV   = "/Users/howard/Repository/stock-k-bar/data/analysis/zhuli/universe_accuracy_2026ytd_filtered.csv"
YTD_DIR        = "/Users/howard/Repository/stock-k-bar/data/analysis/zhuli/backtest_ytd/"
OUT_CSV        = "/Users/howard/Repository/stock-k-bar/data/analysis/zhuli/swing_capture_rate_2026ytd.csv"
OUT_MD         = "/Users/howard/Repository/stock-k-bar/docs/主力大課程/analysis/swing_capture_rate_2026ytd.md"
START_DATE     = "2026-01-01"
END_DATE       = "2026-06-07"

# Pivot detection parameters
SHORT_WINDOW   = 5   # ±5 trading days
MEDIUM_WINDOW  = 10  # ±10 trading days
SHORT_MIN_PCT  = 5.0
MEDIUM_MIN_PCT = 10.0
SIGNAL_WINDOW  = 2   # ±2 business days for hit check
MIN_MEDIUM_PIVOTS = 3  # require ≥3 medium pivots

# Score weights
SHORT_WEIGHT   = 0.4
MEDIUM_WEIGHT  = 0.6


# ─── Load data ────────────────────────────────────────────────────────────────
print("Loading universe...")
universe = pd.read_csv(UNIVERSE_CSV)
tickers = universe["ticker"].astype(str).str.zfill(4).unique().tolist()
print(f"  Universe tickers: {len(tickers)}")

print("Loading stock names...")
conn = get_conn(DB_PATH)
names_df = pd.read_sql("SELECT ticker, name FROM stock_name", conn)
names_df["ticker"] = names_df["ticker"].astype(str).str.zfill(4)
names_map = dict(zip(names_df["ticker"], names_df["name"]))

print(f"Loading daily bars {START_DATE} to {END_DATE}...")
placeholders = ",".join(["?" for _ in tickers])
price_df = pd.read_sql(
    f"""
    SELECT ticker, trade_date, close
    FROM standard_daily_bar
    WHERE trade_date >= ? AND trade_date <= ?
      AND ticker IN ({placeholders})
    ORDER BY ticker, trade_date
    """,
    conn,
    params=[START_DATE, END_DATE] + tickers,
)
conn.close()
price_df["ticker"] = price_df["ticker"].astype(str).str.zfill(4)
price_df["trade_date"] = pd.to_datetime(price_df["trade_date"])
print(f"  Loaded {len(price_df)} rows for {price_df['ticker'].nunique()} tickers")

print("Loading scanner signals...")
signal_dfs = []
for f in os.listdir(YTD_DIR):
    if f.endswith("_trades.csv"):
        df = pd.read_csv(YTD_DIR + f)
        df["source"] = f.replace("_trades.csv", "")
        signal_dfs.append(df)
signals = pd.concat(signal_dfs, ignore_index=True)
signals["ticker"] = signals["ticker"].astype(str).str.zfill(4)
signals["signal_date"] = pd.to_datetime(signals["signal_date"])
print(f"  Total signal rows: {len(signals)} from {signals['source'].nunique()} scanners")


# ─── Zigzag pivot detection ────────────────────────────────────────────────────
def detect_pivots(prices: pd.Series, dates: pd.Series, window: int, min_pct: float) -> list:
    """
    Detect swing pivots using rolling window approach.
    A date is a HIGH pivot if it is the maximum of [i-window .. i+window].
    A date is a LOW  pivot if it is the minimum of [i-window .. i+window].
    Then apply zigzag filter: consecutive pivots of same direction are collapsed
    to keep only the extreme one. Alternating H/L pairs are kept only if the
    price move between them is >= min_pct%.

    Returns list of (date, price, direction) where direction is 'H' or 'L'.
    """
    n = len(prices)
    vals = prices.values
    dt   = dates.values

    # Find local maxima and minima
    raw_pivots = []  # (idx, price, 'H'|'L')
    for i in range(window, n - window):
        lo = max(0, i - window)
        hi = min(n, i + window + 1)
        if vals[i] == vals[lo:hi].max() and vals[i] > vals[lo:hi].min():
            raw_pivots.append((i, vals[i], "H"))
        if vals[i] == vals[lo:hi].min() and vals[i] < vals[lo:hi].max():
            raw_pivots.append((i, vals[i], "L"))

    if not raw_pivots:
        return []

    # Sort by index, resolve ties: prefer extremes
    raw_pivots.sort(key=lambda x: x[0])

    # Zigzag: collapse consecutive same-direction pivots
    zigzag = [raw_pivots[0]]
    for p in raw_pivots[1:]:
        if p[2] == zigzag[-1][2]:
            # same direction: keep extreme
            if p[2] == "H" and p[1] > zigzag[-1][1]:
                zigzag[-1] = p
            elif p[2] == "L" and p[1] < zigzag[-1][1]:
                zigzag[-1] = p
        else:
            zigzag.append(p)

    # Filter: only keep pairs where move >= min_pct
    filtered = [zigzag[0]]
    for p in zigzag[1:]:
        prev = filtered[-1]
        move = abs(p[1] - prev[1]) / prev[1] * 100
        if move >= min_pct:
            filtered.append(p)
        else:
            # collapse: update filtered[-1] if same direction
            if p[2] == filtered[-1][2]:
                if p[2] == "H" and p[1] > filtered[-1][1]:
                    filtered[-1] = p
                elif p[2] == "L" and p[1] < filtered[-1][1]:
                    filtered[-1] = p
            # if different direction but move too small, drop

    return [(dt[idx], price, direction) for idx, price, direction in filtered]


# ─── Per-ticker analysis ───────────────────────────────────────────────────────
print("\nAnalyzing pivots per ticker...")
results = []
ticker_pivot_details = {}  # for spot-check

for ticker in tickers:
    tdf = price_df[price_df["ticker"] == ticker].sort_values("trade_date").reset_index(drop=True)
    if len(tdf) < 20:
        continue  # not enough data

    prices = tdf["close"]
    dates  = tdf["trade_date"]

    # Detect pivots
    short_pivots  = detect_pivots(prices, dates, SHORT_WINDOW,  SHORT_MIN_PCT)
    medium_pivots = detect_pivots(prices, dates, MEDIUM_WINDOW, MEDIUM_MIN_PCT)

    n_short  = len(short_pivots)
    n_medium = len(medium_pivots)

    if n_medium < MIN_MEDIUM_PIVOTS:
        continue  # not enough swing to score

    # Get scanner signals for this ticker
    tsig = signals[signals["ticker"] == ticker]["signal_date"].values

    def count_caught(pivots, sig_dates, window_days=SIGNAL_WINDOW):
        if len(sig_dates) == 0:
            return 0, []
        caught = 0
        hit_pivots = []
        for pdate, pprice, pdir in pivots:
            pdate_ts = pd.Timestamp(pdate)
            lo = pdate_ts - pd.offsets.BusinessDay(window_days)
            hi = pdate_ts + pd.offsets.BusinessDay(window_days)
            hits = [d for d in sig_dates if lo <= pd.Timestamp(d) <= hi]
            if hits:
                caught += 1
                hit_pivots.append((pdate_ts, pprice, pdir, hits))
        return caught, hit_pivots

    short_caught,  short_hits  = count_caught(short_pivots,  tsig)
    medium_caught, medium_hits = count_caught(medium_pivots, tsig)

    short_rate  = short_caught  / n_short  if n_short  > 0 else 0.0
    medium_rate = medium_caught / n_medium if n_medium > 0 else 0.0
    combined    = SHORT_WEIGHT * short_rate + MEDIUM_WEIGHT * medium_rate

    # YTD return
    ytd_ret = None
    if len(tdf) >= 2:
        ytd_ret = (tdf["close"].iloc[-1] / tdf["close"].iloc[0] - 1) * 100

    # Universe info
    uni_row = universe[universe["ticker"].astype(str).str.zfill(4) == ticker]
    sector = uni_row["sector"].values[0] if len(uni_row) > 0 else "未知"
    name   = names_map.get(ticker, uni_row["name"].values[0] if (len(uni_row) > 0 and pd.notna(uni_row["name"].values[0])) else "")

    results.append({
        "ticker": ticker,
        "name": name,
        "sector": sector,
        "short_pivots": n_short,
        "short_caught": short_caught,
        "short_capture_rate": round(short_rate, 4),
        "medium_pivots": n_medium,
        "medium_caught": medium_caught,
        "medium_capture_rate": round(medium_rate, 4),
        "combined_score": round(combined, 4),
        "ytd_return_pct": round(ytd_ret, 2) if ytd_ret is not None else None,
    })

    ticker_pivot_details[ticker] = {
        "short_pivots": short_pivots,
        "medium_pivots": medium_pivots,
        "short_hits": short_hits,
        "medium_hits": medium_hits,
        "n_signals": len(tsig),
    }

print(f"  Tickers with ≥{MIN_MEDIUM_PIVOTS} medium pivots: {len(results)}")

# ─── Build results DataFrame ──────────────────────────────────────────────────
res = pd.DataFrame(results)
res = res.sort_values(["combined_score", "medium_pivots"], ascending=[False, False]).reset_index(drop=True)

# Save CSV
os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
res.to_csv(OUT_CSV, index=False)
print(f"\nSaved CSV: {OUT_CSV}")

# ─── Spot-check top-1 ─────────────────────────────────────────────────────────
top1 = res.iloc[0]["ticker"]
top1_name = res.iloc[0]["name"]
print(f"\nSpot-check top-1: {top1} {top1_name}")
detail = ticker_pivot_details[top1]
print(f"  Short pivots ({len(detail['short_pivots'])}):")
for pdate, pprice, pdir in detail["short_pivots"]:
    ts = pd.Timestamp(pdate)
    print(f"    {ts.date()} {pdir} @ {pprice:.1f}")
print(f"  Short hits: {len(detail['short_hits'])}")
for pdate, pprice, pdir, hits in detail["short_hits"]:
    print(f"    PIVOT {pdate.date()} {pdir}@{pprice:.1f}  ← signals: {[str(pd.Timestamp(h).date()) for h in hits]}")
print(f"  Medium pivots ({len(detail['medium_pivots'])}):")
for pdate, pprice, pdir in detail["medium_pivots"]:
    ts = pd.Timestamp(pdate)
    print(f"    {ts.date()} {pdir} @ {pprice:.1f}")
print(f"  Medium hits: {len(detail['medium_hits'])}")
for pdate, pprice, pdir, hits in detail["medium_hits"]:
    print(f"    PIVOT {pdate.date()} {pdir}@{pprice:.1f}  ← signals: {[str(pd.Timestamp(h).date()) for h in hits]}")

# ─── Sector breakdown ─────────────────────────────────────────────────────────
sector_agg = (
    res[res["sector"] != "其他"]  # focus on named sectors
    .groupby("sector")
    .agg(
        n_tickers=("ticker", "count"),
        avg_short_capture=("short_capture_rate", "mean"),
        avg_medium_capture=("medium_capture_rate", "mean"),
        avg_combined=("combined_score", "mean"),
    )
    .round(4)
    .sort_values("avg_combined", ascending=False)
    .reset_index()
)

print("\nSector breakdown (excl. 其他):")
print(sector_agg.to_string())

# ─── Correlation with win_rate ranking ────────────────────────────────────────
compare = res.merge(
    universe[["ticker", "win_rate", "avg_pnl_pct"]].assign(
        ticker=lambda x: x["ticker"].astype(str).str.zfill(4)
    ),
    on="ticker",
    how="left",
)
corr_combined_winrate = compare["combined_score"].corr(compare["win_rate"])
corr_combined_pnl     = compare["combined_score"].corr(compare["avg_pnl_pct"])
print(f"\ncorr(combined_score, win_rate) = {corr_combined_winrate:.4f}")
print(f"corr(combined_score, avg_pnl)  = {corr_combined_pnl:.4f}")

# ─── Write MD report ──────────────────────────────────────────────────────────
os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)

top20 = res.head(20)
bottom10 = res.tail(10).sort_values("combined_score")

# Prepare spot-check text
spot_lines = []
detail = ticker_pivot_details[top1]
spot_lines.append(f"**Ticker**: {top1} {top1_name}")
spot_lines.append("")
spot_lines.append("**Medium pivots** (10%+ / ±10d window):")
for pdate, pprice, pdir in detail["medium_pivots"]:
    ts = pd.Timestamp(pdate)
    spot_lines.append(f"- {ts.date()} **{pdir}** @ {pprice:.1f}")
spot_lines.append("")
spot_lines.append("**Scanner hits near medium pivots (±2 bdays)**:")
if detail["medium_hits"]:
    for pdate, pprice, pdir, hits in detail["medium_hits"]:
        hstrs = ", ".join([str(pd.Timestamp(h).date()) for h in hits])
        spot_lines.append(f"- Pivot {pdate.date()} {pdir}@{pprice:.1f} ← hit on: {hstrs}")
else:
    spot_lines.append("- (none)")

spot_lines.append("")
spot_lines.append("**Short pivots** (5%+ / ±5d window):")
for pdate, pprice, pdir in detail["short_pivots"]:
    ts = pd.Timestamp(pdate)
    spot_lines.append(f"- {ts.date()} **{pdir}** @ {pprice:.1f}")
spot_lines.append("")
spot_lines.append("**Scanner hits near short pivots**:")
if detail["short_hits"]:
    for pdate, pprice, pdir, hits in detail["short_hits"]:
        hstrs = ", ".join([str(pd.Timestamp(h).date()) for h in hits])
        spot_lines.append(f"- Pivot {pdate.date()} {pdir}@{pprice:.1f} ← hit on: {hstrs}")
else:
    spot_lines.append("- (none)")


def df_to_md_table(df, cols=None):
    if cols:
        df = df[cols]
    lines = ["| " + " | ".join(str(c) for c in df.columns) + " |"]
    lines.append("| " + " | ".join(["---"] * len(df.columns)) + " |")
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(v) for v in row.values) + " |")
    return "\n".join(lines)


top20_cols = ["ticker","name","sector","short_pivots","short_caught","short_capture_rate",
              "medium_pivots","medium_caught","medium_capture_rate","combined_score","ytd_return_pct"]
bottom10_cols = top20_cols

# Interpretation paragraph
if corr_combined_winrate > 0.3:
    corr_interp = (
        f"Combined_score correlates moderately with win_rate (r={corr_combined_winrate:.2f}), "
        "suggesting the scanner tends to fire near real swings for the same tickers it wins on — consistent signal quality."
    )
elif corr_combined_winrate < -0.1:
    corr_interp = (
        f"Combined_score has a negative or near-zero correlation with win_rate (r={corr_combined_winrate:.2f}). "
        "This is a significant finding: the tickers where the scanner has high win-rate are NOT the same tickers "
        "where it captures actual swing pivots. We may have been measuring the wrong dimension all along — "
        "high win-rate could be driven by lucky timing on small moves rather than genuine pivot detection."
    )
else:
    corr_interp = (
        f"Combined_score has a weak correlation with win_rate (r={corr_combined_winrate:.2f}). "
        "The two metrics measure meaningfully different things: win_rate reflects trade-level outcome, "
        "while capture_rate reflects alignment with structural pivot points regardless of trade outcome."
    )

sector_top3    = sector_agg.head(3)[["sector","n_tickers","avg_medium_capture","avg_combined"]].to_string(index=False)
sector_bottom3 = sector_agg.tail(3)[["sector","n_tickers","avg_medium_capture","avg_combined"]].to_string(index=False)

sample_base = len(res)

md = f"""# Swing Turning-Point Capture Rate — 2026 YTD

> Sibling analysis to `scanner_diagnostics_6282_6285_passive_2026ytd.md`.
> This analysis measures **pivot capture**, not win rate or trade frequency.

Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}

---

## Method

### Data Sources
- **Price data**: `standard_daily_bar` in `~/.four_seasons/data.sqlite`, {START_DATE} to {END_DATE}
- **Scanner signals**: all 8 `backtest_ytd/*_trades.csv` files combined (total {len(signals):,} rows)
- **Universe**: `universe_accuracy_2026ytd_filtered.csv` (teacher universe minus financials, {len(universe)} tickers)

### Pivot Detection (Zigzag-style)

For each ticker:

1. **Short-term pivot** (`short`): local max/min in rolling ±{SHORT_WINDOW} trading-day window,
   filtered so consecutive same-direction extremes collapse to one, and adjacent H→L (or L→H)
   move must be **≥ {SHORT_MIN_PCT}%** to count as a real pivot.

2. **Medium-term pivot** (`medium`): same logic with ±{MEDIUM_WINDOW} trading-day window,
   **≥ {MEDIUM_MIN_PCT}%** move required.

Both use a zigzag algorithm: scan for local extremes → collapse consecutive same-direction → keep only
alternating H/L pairs where the move meets the minimum threshold.

### Signal Hit Check

For each pivot date P, check if **any** scanner fired a signal within `[P − {SIGNAL_WINDOW} bdays, P + {SIGNAL_WINDOW} bdays]`.
Direction-agnostic on first pass (any signal near any pivot counts as hit).

### Score

```
short_capture_rate  = short_caught / short_pivots
medium_capture_rate = medium_caught / medium_pivots
combined_score      = {SHORT_WEIGHT} × short_capture + {MEDIUM_WEIGHT} × medium_capture
```

Tickers with **< {MIN_MEDIUM_PIVOTS} medium_pivots** are excluded (sideways stocks, no real swing to test).

---

## Sample Base

**{sample_base} tickers** had ≥ {MIN_MEDIUM_PIVOTS} medium pivots (10%+ swings) in 2026 YTD.

---

## Top 20 by Combined Score

{df_to_md_table(top20[top20_cols])}

---

## Bottom 10 (Scanner Missed All/Most Swings)

{df_to_md_table(bottom10[bottom10_cols])}

---

## Spot-Check: Top-1 Ticker

{"  " + chr(10) + "  ".join(spot_lines)}

---

## Sector Breakdown (avg capture rate, excl. 其他)

{df_to_md_table(sector_agg)}

**Top 3 sectors by avg combined score:**
```
{sector_top3}
```

**Bottom 3 sectors by avg combined score:**
```
{sector_bottom3}
```

---

## Key Insight: Capture Rate vs Win Rate Ranking

Correlation of `combined_score` with `win_rate` (from universe_accuracy file): **r = {corr_combined_winrate:.3f}**
Correlation of `combined_score` with `avg_pnl_pct`: **r = {corr_combined_pnl:.3f}**

{corr_interp}

The capture-rate metric specifically answers: *"When this stock made a real swing, did the scanner notice?"*
Win-rate answers: *"When the scanner fired, did it make money?"*
These are orthogonal quality dimensions. A scanner can have high win-rate but miss major pivots
(fires on noise but gets lucky), or high capture-rate but low win-rate (detects pivots but enters at wrong price).
The ideal scanner scores well on BOTH axes.
"""

with open(OUT_MD, "w", encoding="utf-8") as f:
    f.write(md)
print(f"\nSaved MD: {OUT_MD}")

# Print summary to stdout
print("\n" + "="*60)
print("SUMMARY")
print("="*60)
print(f"Sample base (≥{MIN_MEDIUM_PIVOTS} medium pivots): {sample_base}")
print(f"\nTop 5:")
print(res[top20_cols].head(5).to_string(index=False))
print(f"\nBottom 3:")
print(res[top20_cols].tail(3).to_string(index=False))
print(f"\ncorr(combined, win_rate) = {corr_combined_winrate:.4f}")
print(f"corr(combined, avg_pnl)  = {corr_combined_pnl:.4f}")
