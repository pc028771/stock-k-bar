"""Merge ~/.zhuli_cache/broker/*.json into xiaoge broker_trades parquet.

zhuli 課程也用 TaiwanStockTradingDailyReport、disk cache 共 2.1 GB / 955 ticker / 18 date。
Schema 跟 FinMind 原 response 一樣、aggregate 後 align 到 xiaoge parquet。

CLI:
    python -m scripts.xiaoge.merge_zhuli_broker_cache \
        --start 2026-04-01 --end 2026-06-12 \
        --out data/analysis/xiaoge/broker_trades/2026-04-01_2026-06-12.parquet
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[2]
CACHE_DIR = Path.home() / ".zhuli_cache" / "broker"


def _aggregate_one(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    needed = {"date", "stock_id", "securities_trader_id", "securities_trader", "buy", "sell"}
    if not needed.issubset(df.columns):
        return pd.DataFrame()
    df["buy"] = pd.to_numeric(df["buy"], errors="coerce").fillna(0)
    df["sell"] = pd.to_numeric(df["sell"], errors="coerce").fillna(0)
    agg = df.groupby(
        ["date", "stock_id", "securities_trader_id", "securities_trader"],
        as_index=False,
    ).agg(buy_shares=("buy", "sum"), sell_shares=("sell", "sum"))
    agg["net_shares"] = agg["buy_shares"] - agg["sell_shares"]
    agg = agg.rename(columns={
        "stock_id": "ticker",
        "securities_trader_id": "broker_id",
        "securities_trader": "broker_name",
    })
    agg["date"] = agg["date"].astype(str).str[:10]
    return agg[["date", "ticker", "broker_id", "broker_name",
                "net_shares", "buy_shares", "sell_shares"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-04-01")
    ap.add_argument("--end", default="2026-06-12")
    ap.add_argument("--out", required=True)
    ap.add_argument("--candidate-only", action="store_true",
                    help="只 merge bb_squeeze ∪ chip_v2 候選 ticker (default off)")
    args = ap.parse_args()

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)

    candidates: set[str] | None = None
    if args.candidate_only:
        sys.path.insert(0, str(REPO))
        from scripts.xiaoge.fetch_broker_trades import _candidate_tickers
        candidates = set(_candidate_tickers("2026-05-01", "2026-06-12"))
        print(f"Candidate filter ON: {len(candidates)} tickers")

    files = sorted(CACHE_DIR.glob("*.json"))
    print(f"Cache files: {len(files):,}")

    chunks: list[pd.DataFrame] = []
    skipped_date = 0
    skipped_ticker = 0
    skipped_schema = 0
    for f in files:
        # filename: {ticker}_{YYYY-MM-DD}.json
        stem = f.stem
        if "_" not in stem:
            continue
        ticker, date_str = stem.rsplit("_", 1)
        if not (len(date_str) == 10 and date_str[4] == "-"):
            continue
        try:
            d = pd.Timestamp(date_str)
        except Exception:
            continue
        if d < start or d > end:
            skipped_date += 1
            continue
        if candidates is not None and ticker not in candidates:
            skipped_ticker += 1
            continue
        try:
            rows = json.loads(f.read_text())
        except Exception:
            continue
        if not isinstance(rows, list):
            continue
        agg = _aggregate_one(rows)
        if agg.empty:
            skipped_schema += 1
            continue
        chunks.append(agg)

    print(f"Skipped (date out of window): {skipped_date:,}")
    print(f"Skipped (ticker not in candidates): {skipped_ticker:,}")
    print(f"Skipped (schema bad): {skipped_schema:,}")
    print(f"Aggregated chunks: {len(chunks):,}")

    if not chunks:
        print("Nothing to merge.")
        return

    new_df = pd.concat(chunks, ignore_index=True)
    print(f"New rows from zhuli cache: {len(new_df):,}")
    print(f"  tickers: {new_df['ticker'].nunique()}")
    print(f"  dates: {sorted(new_df['date'].unique())}")

    out_path = Path(args.out)
    if out_path.exists():
        old = pd.read_parquet(out_path)
        print(f"\nExisting parquet: {len(old):,} rows, {old['ticker'].nunique()} tickers, "
              f"{old['date'].nunique()} dates")
        combined = pd.concat([old, new_df], ignore_index=True).drop_duplicates(
            subset=["date", "ticker", "broker_id"], keep="last"
        )
    else:
        combined = new_df

    combined.to_parquet(out_path, index=False)
    print(f"\nFinal: {len(combined):,} rows, {combined['ticker'].nunique()} tickers, "
          f"{combined['date'].nunique()} dates")
    print(f"  dates: {sorted(combined['date'].unique())}")
    print(f"Saved → {out_path}")


if __name__ == "__main__":
    main()
