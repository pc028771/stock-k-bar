"""
Comparative analysis: tweezer_top_breakout vs pattern_breakout_only.

Run:
  uv run python scripts/analysis_tweezer_vs_pattern.py
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

TWEEZER_CSV = Path("data/analysis/kline/backtest_trades_tweezer.csv")
PATTERN_CSV = Path("data/analysis/kline/backtest_trades_pattern.csv")

# ── load ──────────────────────────────────────────────────────────────────────

tw = pd.read_csv(TWEEZER_CSV, parse_dates=["entry_date", "exit_date"])
pt = pd.read_csv(PATTERN_CSV, parse_dates=["entry_date", "exit_date"])

tw["strategy"] = "tweezer"
pt["strategy"] = "pattern"

print(f"Tweezer trades : {len(tw):,}")
print(f"Pattern trades : {len(pt):,}")
print()

# ── 1. Overall stats ──────────────────────────────────────────────────────────

def overall_stats(df: pd.DataFrame, name: str) -> dict:
    n = len(df)
    wins = (df["trade_return_net"] > 0).sum()
    wr = wins / n
    mean_r = df["trade_return_net"].mean()
    med_r  = df["trade_return_net"].median()
    mean_h = df["hold_days"].mean()
    return {
        "strategy": name,
        "n_trades": n,
        "win_rate": round(wr, 4),
        "mean_return_net": round(mean_r, 5),
        "median_return_net": round(med_r, 5),
        "mean_hold_days": round(mean_h, 2),
    }

stats_tw = overall_stats(tw, "tweezer_top_breakout")
stats_pt = overall_stats(pt, "pattern_breakout_only")

OVERALL = pd.DataFrame([stats_tw, stats_pt])
print("=== 1. OVERALL STATS ===")
print(OVERALL.to_string(index=False))
print()

# deciles
print("--- Trade return deciles (trade_return_net) ---")
for name, df in [("tweezer", tw), ("pattern", pt)]:
    q = df["trade_return_net"].quantile([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
    q_str = "  ".join(f"D{int(p*10)}={v:.4f}" for p, v in q.items())
    print(f"  {name:10s}: {q_str}")
print()

# ── 2. Exit reason breakdown ──────────────────────────────────────────────────

def exit_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("exit_reason")
    out = g["trade_return_net"].agg(
        count="count",
        win_rate=lambda x: (x > 0).mean(),
        mean_return="mean",
        mean_hold=lambda x: df.loc[x.index, "hold_days"].mean(),
    ).reset_index()
    out = out.sort_values("count", ascending=False)
    out["win_rate"]    = out["win_rate"].round(4)
    out["mean_return"] = out["mean_return"].round(5)
    out["mean_hold"]   = out["mean_hold"].round(1)
    out["count_pct"]   = (out["count"] / len(df) * 100).round(1)
    return out

print("=== 2. EXIT REASON BREAKDOWN ===")
print("--- Tweezer ---")
exit_tw = exit_breakdown(tw)
print(exit_tw.to_string(index=False))
print()
print("--- Pattern ---")
exit_pt = exit_breakdown(pt)
print(exit_pt.to_string(index=False))
print()

# ── 3. Ticker overlap ─────────────────────────────────────────────────────────

tickers_tw = set(tw["ticker"].unique())
tickers_pt = set(pt["ticker"].unique())
both       = tickers_tw & tickers_pt
only_tw    = tickers_tw - tickers_pt
only_pt    = tickers_pt - tickers_tw

print("=== 3. TICKER OVERLAP ===")
print(f"  Tickers in tweezer only : {len(tickers_tw):,}")
print(f"  Tickers in pattern only : {len(tickers_pt):,}")
print(f"  Tickers in BOTH         : {len(both):,}")
print(f"  ONLY tweezer            : {len(only_tw):,}")
print(f"  ONLY pattern            : {len(only_pt):,}")
print()

# Stats for only-tweezer vs only-pattern
def subset_stats(df, ticker_set, label):
    sub = df[df["ticker"].isin(ticker_set)]
    if len(sub) == 0:
        return f"  {label}: no trades"
    wr = (sub["trade_return_net"] > 0).mean()
    mr = sub["trade_return_net"].mean()
    return (f"  {label}: {len(sub):,} trades, "
            f"win_rate={wr:.2%}, mean_net={mr:.4%}")

print(subset_stats(tw, only_tw,  "tweezer_exclusive trades in tweezer"))
print(subset_stats(pt, only_pt,  "pattern_exclusive trades in pattern"))
print(subset_stats(tw, both,     "shared-ticker trades in tweezer"))
print(subset_stats(pt, both,     "shared-ticker trades in pattern"))
print()

# ── 4. Same-ticker trade comparison ──────────────────────────────────────────

print("=== 4. SAME-TICKER TRADE COMPARISON ===")
# Match on (ticker, entry_date)
tw_keyed = tw.set_index(["ticker", "entry_date"])
pt_keyed = pt.set_index(["ticker", "entry_date"])
same_day_idx = tw_keyed.index.intersection(pt_keyed.index)
print(f"  Trades with exact same ticker + entry_date: {len(same_day_idx):,}")

if len(same_day_idx) > 0:
    tw_same = tw_keyed.loc[same_day_idx, ["trade_return_net", "exit_reason", "hold_days"]].add_suffix("_tw")
    pt_same = pt_keyed.loc[same_day_idx, ["trade_return_net", "exit_reason", "hold_days"]].add_suffix("_pt")
    merged = tw_same.join(pt_same)
    tw_wins = (merged["trade_return_net_tw"] > merged["trade_return_net_pt"]).mean()
    print(f"  Tweezer wins (higher return) on same-day trades: {tw_wins:.2%}")
    print(f"  Avg return tweezer={merged['trade_return_net_tw'].mean():.4%}, "
          f"pattern={merged['trade_return_net_pt'].mean():.4%}")

# Non-overlapping entry dates on shared tickers
tw_shared = tw[tw["ticker"].isin(both)].copy()
pt_shared = pt[pt["ticker"].isin(both)].copy()
# Entry dates unique to each on shared tickers
tw_unique_dates_shared = len(tw_shared) - len(same_day_idx)
pt_unique_dates_shared = len(pt_shared) - len(same_day_idx)
print(f"  Shared-ticker trades unique to tweezer: {tw_unique_dates_shared:,}")
print(f"  Shared-ticker trades unique to pattern: {pt_unique_dates_shared:,}")
print()

# ── 5. Time distribution ─────────────────────────────────────────────────────

print("=== 5. TIME DISTRIBUTION ===")
tw["ym"] = tw["entry_date"].dt.to_period("M")
pt["ym"] = pt["entry_date"].dt.to_period("M")

tw_monthly = tw.groupby("ym").agg(
    n=("trade_return_net", "count"),
    wr=("trade_return_net", lambda x: (x > 0).mean()),
    mean_r=("trade_return_net", "mean"),
)
pt_monthly = pt.groupby("ym").agg(
    n=("trade_return_net", "count"),
    wr=("trade_return_net", lambda x: (x > 0).mean()),
    mean_r=("trade_return_net", "mean"),
)

monthly = tw_monthly.add_suffix("_tw").join(pt_monthly.add_suffix("_pt"), how="outer").fillna(0)
monthly["n_tw"] = monthly["n_tw"].astype(int)
monthly["n_pt"] = monthly["n_pt"].astype(int)
print(monthly[["n_tw", "wr_tw", "mean_r_tw", "n_pt", "wr_pt", "mean_r_pt"]].to_string())
print()

# ── 6. Attack intensity at entry ──────────────────────────────────────────────

print("=== 6. ATTACK INTENSITY AT ENTRY ===")

# Load features with attack_intensity
try:
    from kline.bars import DEFAULT_DB_PATH
    from kline.features import load_features_cached

    feats = load_features_cached(db_path=DEFAULT_DB_PATH).copy()
    feats["market_open_ret"] = 0.0

    # Build a lookup: (ticker, trade_date) → attack_intensity
    # Normalise ticker to str so it matches the trade CSV int tickers when cast
    feats_for_join = feats.copy()
    feats_for_join["ticker_str"] = feats_for_join["ticker"].astype(str)
    feats_indexed = feats_for_join.set_index(["ticker_str", "trade_date"])[["attack_intensity"]]

    def attach_attack_intensity(trades_df: pd.DataFrame) -> pd.DataFrame:
        df2 = trades_df.copy()
        df2["entry_date_ts"] = pd.to_datetime(df2["entry_date"])
        df2["ticker_str"] = df2["ticker"].astype(str)
        idx = pd.MultiIndex.from_arrays([df2["ticker_str"], df2["entry_date_ts"]])
        df2["attack_intensity"] = feats_indexed.reindex(idx)["attack_intensity"].values
        return df2

    tw2 = attach_attack_intensity(tw)
    pt2 = attach_attack_intensity(pt)

    def intensity_breakdown(df, name):
        g = df.groupby("attack_intensity")["trade_return_net"]
        out = g.agg(
            count="count",
            win_rate=lambda x: (x > 0).mean(),
            mean_return="mean",
        ).reset_index()
        out["win_rate"]    = out["win_rate"].round(4)
        out["mean_return"] = out["mean_return"].round(5)
        print(f"  --- {name} ---")
        print(out.to_string(index=False))

    intensity_breakdown(tw2, "tweezer")
    intensity_breakdown(pt2, "pattern")

    # Percentage of trades with intensity > 0
    tw_high = (tw2["attack_intensity"] > 0).mean()
    pt_high = (pt2["attack_intensity"] > 0).mean()
    print(f"\n  Tweezer trades with intensity>0: {tw_high:.2%}")
    print(f"  Pattern trades with intensity>0: {pt_high:.2%}")
    print()

    ATTACK_LOADED = True
    feats_snapshot = feats  # save for Hypothesis B

except Exception as e:
    print(f"  [Could not load bars for attack_intensity: {e}]")
    ATTACK_LOADED = False
    tw2 = tw.copy()
    pt2 = pt.copy()

# ── 7. Hypothesis tests ───────────────────────────────────────────────────────

print("=== 7. HYPOTHESIS EVALUATION ===")

print("--- Hypothesis A: Tweezer triggers more often in mid-attack mode (intensity>0) ---")
if ATTACK_LOADED:
    tw_int_pos = tw2[tw2["attack_intensity"] > 0]
    tw_int_zero = tw2[tw2["attack_intensity"] == 0]
    pt_int_pos = pt2[pt2["attack_intensity"] > 0]
    pt_int_zero = pt2[pt2["attack_intensity"] == 0]

    print(f"  Tweezer with intensity>0: {len(tw_int_pos):,} trades ({len(tw_int_pos)/len(tw2):.2%}), "
          f"win={( tw_int_pos['trade_return_net']>0).mean():.2%}, "
          f"mean_net={(tw_int_pos['trade_return_net'].mean()):.4%}")
    print(f"  Tweezer with intensity=0: {len(tw_int_zero):,} trades ({len(tw_int_zero)/len(tw2):.2%}), "
          f"win={(tw_int_zero['trade_return_net']>0).mean():.2%}, "
          f"mean_net={(tw_int_zero['trade_return_net'].mean()):.4%}")
    print(f"  Pattern with intensity>0: {len(pt_int_pos):,} trades ({len(pt_int_pos)/len(pt2):.2%}), "
          f"win={(pt_int_pos['trade_return_net']>0).mean():.2%}, "
          f"mean_net={(pt_int_pos['trade_return_net'].mean()):.4%}")
    print(f"  Pattern with intensity=0: {len(pt_int_zero):,} trades ({len(pt_int_zero)/len(pt2):.2%}), "
          f"win={(pt_int_zero['trade_return_net']>0).mean():.2%}, "
          f"mean_net={(pt_int_zero['trade_return_net'].mean()):.4%}")

    # Difference in mean_net for intensity>0 trades between strategies
    if len(pt_int_pos) > 0:
        diff_high = tw_int_pos["trade_return_net"].mean() - pt_int_pos["trade_return_net"].mean()
        print(f"\n  Delta (tweezer vs pattern) among intensity>0 trades: {diff_high:.4%}")
else:
    print("  [Skipped — bars not loaded]")

print()
print("--- Hypothesis B: Tweezer captures high-vol consolidation before breakout ---")
# Proxy: check volume_ratio at entry in feats for tweezer vs pattern entries
if ATTACK_LOADED:
    # Build volume_ratio lookup
    feats_snap2 = feats_snapshot.copy()
    feats_snap2["ticker_str"] = feats_snap2["ticker"].astype(str)
    feats2 = feats_snap2.set_index(["ticker_str", "trade_date"])[
        ["volume_ratio", "upper_band_spread_60d", "higher_low_count_60d",
         "overhead_supply_layer", "unfilled_gap_down_count_240d",
         "body_pct", "range_pct", "close_pos"]
    ].copy()

    def attach_feats(trades_df, feats2):
        df2 = trades_df.copy()
        dt = pd.to_datetime(df2["entry_date"])
        df2["ticker_str"] = df2["ticker"].astype(str)
        idx = pd.MultiIndex.from_arrays([df2["ticker_str"], dt])
        for col in feats2.columns:
            df2[col] = feats2[col].reindex(idx).values
        return df2

    tw3 = attach_feats(tw2, feats2)
    pt3 = attach_feats(pt2, feats2)

    # Compare volume_ratio at entry
    for label, df3 in [("tweezer", tw3), ("pattern", pt3)]:
        vr = df3["volume_ratio"].dropna()
        print(f"  {label:10s} volume_ratio at entry — "
              f"median={vr.median():.2f}  mean={vr.mean():.2f}  "
              f">2x: {(vr>2).mean():.2%}  >3x: {(vr>3).mean():.2%}")

    print()
    # Upper band spread (tightness of consolidation range)
    for label, df3 in [("tweezer", tw3), ("pattern", pt3)]:
        ubs = df3["upper_band_spread_60d"].dropna()
        print(f"  {label:10s} upper_band_spread_60d — "
              f"median={ubs.median():.4f}  mean={ubs.mean():.4f}  "
              f"<=0.03 (tight): {(ubs<=0.03).mean():.2%}  <=0.05: {(ubs<=0.05).mean():.2%}")

    print()
    # higher_low_count at entry
    for label, df3 in [("tweezer", tw3), ("pattern", pt3)]:
        hlc = df3["higher_low_count_60d"].dropna()
        print(f"  {label:10s} higher_low_count_60d — "
              f"median={hlc.median():.1f}  mean={hlc.mean():.1f}  "
              f">=30 (course min): {(hlc>=30).mean():.2%}")

    print()
    # Overhead supply at entry for tweezer (pattern requires 0 by definition)
    for label, df3 in [("tweezer", tw3), ("pattern", pt3)]:
        osl = df3["overhead_supply_layer"].dropna()
        ug = df3["unfilled_gap_down_count_240d"].dropna()
        print(f"  {label:10s} overhead_supply_layer — "
              f"median={osl.median():.1f}  ==0: {(osl==0).mean():.2%}")
        print(f"  {label:10s} unfilled_gap_down    — "
              f"median={ug.median():.1f}  ==0: {(ug==0).mean():.2%}")

    print()
    # Win rate analysis by vol_ratio bucket for tweezer
    tw3["vr_bucket"] = pd.cut(
        tw3["volume_ratio"].fillna(0),
        bins=[0, 1, 1.5, 2, 3, 5, 999],
        labels=["<1x","1-1.5x","1.5-2x","2-3x","3-5x","5x+"]
    )
    vr_stats_tw = tw3.groupby("vr_bucket", observed=False)["trade_return_net"].agg(
        count="count",
        win_rate=lambda x: (x>0).mean(),
        mean_return="mean",
    )
    vr_stats_tw["win_rate"] = vr_stats_tw["win_rate"].round(4)
    vr_stats_tw["mean_return"] = vr_stats_tw["mean_return"].round(5)
    print("  Tweezer by volume_ratio bucket:")
    print(vr_stats_tw.to_string())

else:
    print("  [Skipped — bars not loaded]")

print()
print("=== DONE ===")
