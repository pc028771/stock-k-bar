from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd

from breakout_attack_strategy_check import add_trade_fields
from breakout_daily_scanner import (
    add_pre_rank_score,
    load_exclusion_tickers_from_db,
    load_finmind_stock_info,
    prepare_finmind_filters,
    tradable_breakout_mask,
)
from false_breakdown_strategy_check import add_market_regime
from finmind_intraday_kline_check import fetch_kbar, get_cache_dir, intraday_features
from kline_course_backtest import add_features, add_signals, load_bars


OUT_DIR = Path("data/analysis/kline_course_backtest")
SUMMARY_PATH = OUT_DIR / "finmind_intraday_cache_warmup_summary.csv"


def build_candidates(
    days_back: int,
    max_per_date: int,
    excluded_tickers: set[str],
    listed_otc_tickers: set[str],
    construction_tickers: set[str],
) -> pd.DataFrame:
    df = add_market_regime(add_trade_fields(add_signals(add_features(load_bars()))))
    mask = tradable_breakout_mask(df, excluded_tickers, listed_otc_tickers, construction_tickers)
    rows = df[mask].copy()
    rows = rows[
        [
            "ticker",
            "trade_date",
            "market_regime",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "avg_volume_20",
            "volume_ratio",
            "close_pos",
            "prior_high_60",
            "breakout_next_not_low_open",
        ]
    ]
    rows["trade_date"] = pd.to_datetime(rows["trade_date"])
    if rows.empty:
        return rows

    max_date = rows["trade_date"].max()
    min_date = max_date - pd.Timedelta(days=days_back)
    rows = rows[rows["trade_date"] >= min_date].copy()
    rows = add_pre_rank_score(rows)
    rows = (
        rows.sort_values(["trade_date", "pre_rank_score", "volume"], ascending=[False, False, False])
        .groupby("trade_date", as_index=False, group_keys=False)
        .head(max_per_date)
        .copy()
    )
    rows["trade_date"] = rows["trade_date"].dt.strftime("%Y-%m-%d")
    return rows


def warmup_cache(candidates: pd.DataFrame, sleep_seconds: float, max_requests: int) -> pd.DataFrame:
    token = os.environ.get("FINMIND_TOKEN")
    if not token:
        raise SystemExit("FINMIND_TOKEN is required")

    cache_dir = get_cache_dir()
    records: list[dict[str, object]] = []
    req_count = 0

    for row in candidates.itertuples(index=False):
        if req_count >= max_requests:
            break
        ticker = str(row.ticker)
        trade_date = str(row.trade_date)
        cache_path = cache_dir / f"{ticker}_{trade_date}.csv"
        existed_before = cache_path.exists()
        kbar = fetch_kbar(ticker, trade_date, token, sleep_seconds)
        req_count += 0 if existed_before else 1
        feat = intraday_features(kbar)
        records.append(
            {
                "ticker": ticker,
                "trade_date": trade_date,
                "market_regime": row.market_regime,
                "pre_rank_score": row.pre_rank_score,
                "breakout_next_not_low_open": row.breakout_next_not_low_open,
                "cache_hit": existed_before,
                "intraday_rows": feat.get("intraday_rows", 0),
                "intraday_strong_attack": feat.get("intraday_strong_attack"),
                "below_open_after_1130": feat.get("below_open_after_1130"),
            }
        )

    result = pd.DataFrame(records)
    if not result.empty:
        result = result.sort_values(["trade_date", "pre_rank_score"], ascending=[False, False])
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days-back", type=int, default=90)
    parser.add_argument("--max-per-date", type=int, default=30)
    parser.add_argument("--max-requests", type=int, default=5000)
    parser.add_argument("--sleep-seconds", type=float, default=0.2)
    parser.add_argument("--refresh-stock-info", action="store_true")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    stock_info = load_finmind_stock_info(force_refresh=args.refresh_stock_info)
    listed_otc_tickers, construction_tickers = prepare_finmind_filters(stock_info)
    excluded_tickers = load_exclusion_tickers_from_db()

    candidates = build_candidates(
        days_back=args.days_back,
        max_per_date=args.max_per_date,
        excluded_tickers=excluded_tickers,
        listed_otc_tickers=listed_otc_tickers,
        construction_tickers=construction_tickers,
    )
    result = warmup_cache(candidates, sleep_seconds=args.sleep_seconds, max_requests=args.max_requests)
    result.to_csv(SUMMARY_PATH, index=False)

    cache_hit = int(result["cache_hit"].sum()) if not result.empty else 0
    cache_miss = int((~result["cache_hit"]).sum()) if not result.empty else 0
    print(f"cache_dir={get_cache_dir()}")
    print(f"candidates={len(candidates)} warmed={len(result)} cache_hit={cache_hit} cache_miss={cache_miss}")
    print(SUMMARY_PATH)


if __name__ == "__main__":
    main()
