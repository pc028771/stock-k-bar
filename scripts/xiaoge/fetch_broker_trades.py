"""Fetch TaiwanStockTradingDailyReport (分點日報) for a curated ticker universe.

策略選擇背景：
  - 原本嘗試 `taiwan_stock_trading_daily_report(date=X, use_async=True)` 全市場單日 fetch
  - 第 1 天成功 (513k rows, 62s)，第 2 天起 DataLoader 內部 TaiwanStockInfo 重複 lookup 卡住
  - 退而求其次：限制 ticker universe 到 detector 1+2 候選集 (bb_squeeze ∪ chip_v2)
  - 每 (ticker, date) 用直接 HTTP API + async fan-out (concurrent ~10)

Output: data/analysis/xiaoge/broker_trades/{start}_{end}.parquet
Schema: date, ticker, broker_id, broker_name, net_shares, buy_shares, sell_shares
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "data/analysis/xiaoge/broker_trades"
sys.path.insert(0, str(REPO / "scripts"))
from common.clients.finmind_client import get_client


def _trading_dates(start: str, end: str) -> list[str]:
    sys.path.insert(0, str(REPO))
    from scripts.xiaoge.bars import load_bars
    df = load_bars(start, end)
    in_w = (df["trade_date"] >= pd.Timestamp(start)) & (df["trade_date"] <= pd.Timestamp(end))
    return sorted(df.loc[in_w, "trade_date"].dt.strftime("%Y-%m-%d").unique().tolist())


def _candidate_tickers(start: str, end: str) -> list[str]:
    """Tickers that triggered detector 1 (bb_squeeze) or detector 2 v2 (chip)
    at any point in the backtest window."""
    sys.path.insert(0, str(REPO))
    from scripts.xiaoge.bars import load_bars, add_squeeze_flag
    from scripts.xiaoge.entry.bb_squeeze_breakout import detect as detect_bb
    from scripts.xiaoge.entry.main_chip_holder_v2 import detect as detect_chip_v2

    df = load_bars(start, end)
    df = add_squeeze_flag(df, lookback=10, threshold=15.0)
    in_window = df["trade_date"] >= pd.Timestamp(start)
    bb_sig = detect_bb(df, breakout_mode="shenglongquan") & in_window
    chip_sig = detect_chip_v2(df, min_chip_ratio=0.10) & in_window
    tickers = sorted(set(df.loc[bb_sig | chip_sig, "ticker"].unique()))
    # Filter to pure 4-digit codes (exclude ETF/warrant/TDR)
    return [t for t in tickers if len(t) == 4 and t.isdigit() and t[0] != '0']


# Shared state across tasks for failure visibility
_FAIL_COUNTS: dict[int, int] = {}


def _fetch_one_sync(ticker: str, date_str: str) -> pd.DataFrame:
    try:
        df = get_client().fetch_dataset(
            dataset="TaiwanStockTradingDailyReport",
            data_id=ticker,
            start_date=date_str,
            end_date=date_str,
            bypass_cache=True,
        )
    except Exception:
        _FAIL_COUNTS[-1] = _FAIL_COUNTS.get(-1, 0) + 1
        return pd.DataFrame()
    if df.empty:
        return pd.DataFrame()
    df["buy"] = pd.to_numeric(df["buy"], errors="coerce").fillna(0)
    df["sell"] = pd.to_numeric(df["sell"], errors="coerce").fillna(0)
    agg = df.groupby(
        ["date", "stock_id", "securities_trader_id", "securities_trader"],
        as_index=False
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


async def _fetch_one(ticker: str, date_str: str,
                     sem: asyncio.Semaphore,
                     per_call_sleep: float = 0.0) -> pd.DataFrame:
    async with sem:
        df = await asyncio.to_thread(_fetch_one_sync, ticker, date_str)
        if per_call_sleep > 0:
            await asyncio.sleep(per_call_sleep)
        return df


async def _fetch_all(tickers: list[str], dates: list[str],
                     concurrency: int = 3, per_call_sleep: float = 0.5,
                     between_day_sleep: float = 10.0,
                     out_path: Path | None = None) -> pd.DataFrame:
    """Fetch all (ticker, date) combos with conservative pacing.

    - concurrency: max in-flight requests
    - per_call_sleep: sleep after each successful 200 response within a task
    - between_day_sleep: pause between trading days

    Will incrementally flush parquet to `out_path` after each day (resume-safe).
    """
    sem = asyncio.Semaphore(concurrency)
    # Resume: skip dates already in parquet
    done_dates: set[str] = set()
    if out_path and out_path.exists():
        existing = pd.read_parquet(out_path)
        if not existing.empty:
            done_dates = set(existing["date"].astype(str).str[:10].unique().tolist())
        print(f"  Resume: {len(done_dates)} dates already cached, will skip")

    all_chunks: list[pd.DataFrame] = []
    total = len(tickers) * len(dates)
    done = 0
    t0 = time.time()
    for i, date_str in enumerate(dates):
        if date_str in done_dates:
            done += len(tickers)
            continue
        tasks = [_fetch_one(t, date_str, sem, per_call_sleep)
                 for t in tickers]
        chunks = await asyncio.gather(*tasks)
        day_rows = sum(len(c) for c in chunks)
        valid = [c for c in chunks if len(c) > 0]
        if valid:
            all_chunks.extend(valid)
        done += len(tasks)
        elapsed = time.time() - t0
        print(f"  {date_str}: {len(valid)}/{len(tickers)} tickers, {day_rows} rows, "
              f"cumulative {done}/{total} calls, elapsed={elapsed:.1f}s, "
              f"fails={_FAIL_COUNTS}", flush=True)
        # Abort hard if too many 403s (IP ban) or 402s (quota)
        if _FAIL_COUNTS.get(403, 0) >= 10:
            print(f"  ABORT: too many 403 (IP banned). Stopping. "
                  f"Wait 1h+ before retry.", flush=True)
            break
        if _FAIL_COUNTS.get(402, 0) >= 50:
            print(f"  ABORT: too many 402 (quota exhausted). Stopping.", flush=True)
            break
        # Flush after each day for resume safety
        if out_path and all_chunks:
            _flush_chunks(all_chunks, out_path)
            all_chunks = []
        if i < len(dates) - 1 and between_day_sleep > 0:
            await asyncio.sleep(between_day_sleep)
    if not all_chunks:
        if out_path and out_path.exists():
            return pd.read_parquet(out_path)
        return pd.DataFrame(columns=["date", "ticker", "broker_id", "broker_name",
                                     "net_shares", "buy_shares", "sell_shares"])
    return pd.concat(all_chunks, ignore_index=True)


def _flush_chunks(chunks: list[pd.DataFrame], out_path: Path):
    new_df = pd.concat(chunks, ignore_index=True)
    if out_path.exists():
        old = pd.read_parquet(out_path)
        combined = pd.concat([old, new_df], ignore_index=True).drop_duplicates(
            subset=["date", "ticker", "broker_id"], keep="last"
        )
    else:
        combined = new_df
    combined.to_parquet(out_path, index=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-04-01")
    ap.add_argument("--end", default="2026-06-12")
    # Candidate universe range — typically same as broker window
    ap.add_argument("--universe-start", default="2026-05-01")
    ap.add_argument("--universe-end", default="2026-06-12")
    ap.add_argument("--concurrency", type=int, default=3,
                    help="保守值 3、避免觸發 IP ban (實測 8 會被 ban)")
    ap.add_argument("--per-call-sleep", type=float, default=0.5,
                    help="每筆 200 後 sleep N 秒、降頻")
    ap.add_argument("--between-day-sleep", type=float, default=10.0,
                    help="日與日之間 sleep N 秒")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else OUT_DIR / f"{args.start}_{args.end}.parquet"

    dates = _trading_dates(args.start, args.end)
    tickers = _candidate_tickers(args.universe_start, args.universe_end)
    print(f"Will fetch {len(dates)} trading days × {len(tickers)} candidate tickers "
          f"= {len(dates) * len(tickers)} calls (concurrency={args.concurrency})")
    print(f"Output: {out_path}")

    df = asyncio.run(_fetch_all(tickers, dates,
                                 concurrency=args.concurrency,
                                 per_call_sleep=args.per_call_sleep,
                                 between_day_sleep=args.between_day_sleep,
                                 out_path=out_path))
    # Re-read final parquet (flushes happened during run)
    if out_path.exists():
        df = pd.read_parquet(out_path)
    print(f"\nTotal: {len(df)} rows, "
          f"{df['ticker'].nunique() if len(df) else 0} tickers, "
          f"{df['date'].nunique() if len(df) else 0} dates")
    print(f"Saved → {out_path}")


if __name__ == "__main__":
    main()
