"""Fetch TaiwanStockHoldingSharesPer from FinMind, cache as parquet.

Output: data/analysis/xiaoge/shareholding/{start}_{end}.parquet
Schema: ticker, date, retail_ratio (1-999 持股比例), bigholder_ratio (>1M 比例),
        total_people (集保戶總人數), retail_people, bigholder_people
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import requests


REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "data/analysis/xiaoge/shareholding"


def fetch_all(start: str, end: str, token: str | None = None) -> pd.DataFrame:
    """Fetch shareholding for all tickers, looping per week.

    Multi-week all-market fetch returns 0 rows (row limit); per-week works
    (~67K rows/week). We loop weekly to stay under limit.
    """
    token = token or os.getenv("FINMIND_TOKEN")
    if not token:
        raise RuntimeError("FINMIND_TOKEN not set")

    # Generate weekly snapshot dates (Fridays in the range — shareholding
    # publishes weekly on Friday).
    dates = pd.date_range(start, end, freq="W-FRI").strftime("%Y-%m-%d").tolist()
    if not dates:
        # Fallback: try every 7 days from start
        dates = pd.date_range(start, end, freq="7D").strftime("%Y-%m-%d").tolist()

    all_rows = []
    for d in dates:
        print(f"  fetching {d}…", end=" ", flush=True)
        r = requests.get(
            "https://api.finmindtrade.com/api/v4/data",
            params={"dataset": "TaiwanStockHoldingSharesPer",
                    "start_date": d, "end_date": d, "token": token},
            timeout=60
        )
        if r.status_code != 200:
            print(f"status={r.status_code}, skipping")
            continue
        rows = r.json().get("data", [])
        print(f"{len(rows)} rows")
        all_rows.extend(rows)
    df = pd.DataFrame(all_rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df["people"] = pd.to_numeric(df["people"], errors="coerce")
    df["percent"] = pd.to_numeric(df["percent"], errors="coerce")
    df["unit"] = pd.to_numeric(df["unit"], errors="coerce")
    return df


def derive_axes(raw: pd.DataFrame) -> pd.DataFrame:
    """Pivot raw shareholding rows into one row per (ticker, date) with the
    three axes 老師 cares about."""
    if raw.empty:
        return pd.DataFrame()

    # Filter out metadata rows
    raw = raw[~raw["HoldingSharesLevel"].isin(["total", "差異數調整（說明4）"])].copy()

    # 散戶 = 1-999 (less than 1 lot)
    retail = raw[raw["HoldingSharesLevel"] == "1-999"][["stock_id", "date", "people", "percent"]]
    retail = retail.rename(columns={"people": "retail_people", "percent": "retail_pct"})

    # 大戶 = more than 1,000,001 shares (> 1000 lots)
    big = raw[raw["HoldingSharesLevel"] == "more than 1,000,001"][["stock_id", "date", "people", "percent"]]
    big = big.rename(columns={"people": "bigholder_people", "percent": "bigholder_pct"})

    # 總人數 — sum people across all non-metadata levels
    total = raw.groupby(["stock_id", "date"])["people"].sum().reset_index()
    total = total.rename(columns={"people": "total_people"})

    out = retail.merge(big, on=["stock_id", "date"], how="outer")
    out = out.merge(total, on=["stock_id", "date"], how="outer")
    out = out.rename(columns={"stock_id": "ticker"})
    out["date"] = pd.to_datetime(out["date"])
    return out.sort_values(["ticker", "date"]).reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-04-01",
                    help="Includes warm-up so weekly cadence covers backtest window")
    ap.add_argument("--end", default="2026-06-12")
    args = ap.parse_args()

    print(f"Fetching TaiwanStockHoldingSharesPer {args.start} ~ {args.end}…")
    raw = fetch_all(args.start, args.end)
    print(f"Got {len(raw)} raw rows")
    out = derive_axes(raw)
    print(f"Derived {len(out)} (ticker, date) rows")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{args.start}_{args.end}.parquet"
    out.to_parquet(out_path, index=False)
    print(f"→ {out_path}")
    print("\nSample:")
    print(out.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
