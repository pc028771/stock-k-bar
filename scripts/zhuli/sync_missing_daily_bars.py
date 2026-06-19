"""Sync missing daily bars + institutional data per ticker up to today.

Strategy:
1. For each ticker in DB, find max trade_date in standard_daily_bar
2. Fetch FinMind TaiwanStockPrice from (max_date - 80 trading days) to today
   - 80-day warmup ensures MA60 / ma20_slope are recomputed correctly
3. Recompute MA + vol derived columns
4. INSERT OR REPLACE last 80 days + insert new dates
5. Same for institutional data (TaiwanStockInstitutionalInvestorsBuySell)

Usage:
    python scripts/zhuli/sync_missing_daily_bars.py [--db PATH] [--dry-run]
                                                    [--tickers 2330,2454] [--limit N]
                                                    [--skip-bars] [--skip-institutional]

⚠️ 必須走 common.clients.finmind_compat.FinMindClient（含 throttle）— 禁止 curl API
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

# Path setup
_WORKTREE = Path(__file__).parent.parent.parent
for _p in [str(_WORKTREE), str(_WORKTREE / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.db import get_conn
from common.clients.finmind_compat import FinMindClient  # noqa: E402
from kline.bars import DEFAULT_DB_PATH  # noqa: E402

DATA_SOURCE_ID = 1
WARMUP_DAYS = 80  # 交易日 buffer 確保 MA60 + slope 重算對
TODAY = date.today().isoformat()


def get_ticker_max_dates(db_path: Path) -> dict[str, str]:
    """Return {ticker: max_trade_date} for all tickers in standard_daily_bar."""
    with get_conn(db_path, readonly=False) as conn:
        df = pd.read_sql_query(
            "SELECT ticker, MAX(trade_date) AS max_date FROM standard_daily_bar GROUP BY ticker",
            conn,
        )
    return dict(zip(df["ticker"], df["max_date"]))


def get_ticker_inst_max_dates(db_path: Path) -> dict[str, str]:
    """Return {ticker: max_trade_date} for institutional_investors."""
    with get_conn(db_path, readonly=False) as conn:
        df = pd.read_sql_query(
            "SELECT ticker, MAX(trade_date) AS max_date FROM institutional_investors GROUP BY ticker",
            conn,
        )
    return dict(zip(df["ticker"], df["max_date"]))


def compute_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Recompute MA/vol features. Input: single ticker sorted asc by trade_date."""
    df = df.sort_values("trade_date").copy()
    df["ma5"] = df["close"].rolling(5, min_periods=1).mean()
    df["ma10"] = df["close"].rolling(10, min_periods=1).mean()
    df["ma20"] = df["close"].rolling(20, min_periods=1).mean()
    df["ma60"] = df["close"].rolling(60, min_periods=1).mean()
    df["ma240"] = df["close"].rolling(240, min_periods=1).mean()
    ma20_prev5 = df["ma20"].shift(5)
    df["ma20_slope"] = (df["ma20"] - ma20_prev5) / ma20_prev5.replace(0, float("nan"))
    df["ma20_slope_proxy"] = df["ma20_slope"]
    df["vol_ma20"] = df["volume"].rolling(20, min_periods=1).mean()
    df["vol_ratio_20"] = df["volume"] / df["vol_ma20"].replace(0, float("nan"))
    return df


def fetch_bars_for_ticker(client: FinMindClient, ticker: str, start: str, end: str) -> pd.DataFrame:
    raw = client.get_price(ticker, start, end)
    if raw.empty:
        return pd.DataFrame()
    col_map = {"date": "trade_date", "Trading_Volume": "volume"}
    raw = raw.rename(columns={k: v for k, v in col_map.items() if k in raw.columns})
    needed = ["trade_date", "open", "high", "low", "close", "volume"]
    missing = [c for c in needed if c not in raw.columns]
    if missing:
        return pd.DataFrame()
    df = raw[needed].copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date.astype(str)
    df["ticker"] = ticker
    df["data_source_id"] = DATA_SOURCE_ID
    df["is_usable"] = 1
    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["open", "high", "low", "close", "volume"])
    df = df[(df["close"] > 0) & (df["volume"] > 0)]
    return compute_derived(df)


def upsert_bars(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    cols = [
        "ticker", "trade_date", "data_source_id",
        "open", "high", "low", "close", "volume",
        "ma5", "ma10", "ma20", "ma60", "ma240",
        "ma20_slope", "ma20_slope_proxy",
        "vol_ma20", "vol_ratio_20",
        "is_usable",
    ]
    rows = df[cols].to_dict("records")
    placeholders = ", ".join(f":{c}" for c in cols)
    sql = f"INSERT OR REPLACE INTO standard_daily_bar ({', '.join(cols)}) VALUES ({placeholders})"
    conn.executemany(sql, rows)
    return len(rows)


def fetch_institutional_for_ticker(client: FinMindClient, ticker: str, start: str, end: str) -> pd.DataFrame:
    """Returns aggregated DF: ticker, trade_date, sitc_*, foreign_*."""
    try:
        raw = client.get_institutional(ticker, start, end)  # FinMindClient v2 method name
    except Exception as e:
        print(f"    inst fetch FAIL: {e}")
        return pd.DataFrame()
    if raw.empty:
        return pd.DataFrame()

    # FinMind 回傳每天每法人類別一列
    raw = raw.rename(columns={"date": "trade_date", "stock_id": "ticker"})
    raw["trade_date"] = pd.to_datetime(raw["trade_date"]).dt.date.astype(str)
    raw["buy"] = pd.to_numeric(raw["buy"], errors="coerce").fillna(0)
    raw["sell"] = pd.to_numeric(raw["sell"], errors="coerce").fillna(0)

    # Pivot to wide format with Investment_Trust + Foreign_Investor
    rows = []
    for date_val, grp in raw.groupby("trade_date"):
        sitc = grp[grp["name"] == "Investment_Trust"]
        foreign = grp[grp["name"] == "Foreign_Investor"]
        sitc_buy = sitc["buy"].sum() / 1000  # 股 → 張
        sitc_sell = sitc["sell"].sum() / 1000
        foreign_buy = foreign["buy"].sum() / 1000
        foreign_sell = foreign["sell"].sum() / 1000
        if sitc_buy == 0 and sitc_sell == 0 and foreign_buy == 0 and foreign_sell == 0:
            continue  # 全零跳過
        rows.append({
            "ticker": ticker,
            "trade_date": date_val,
            "sitc_buy": sitc_buy,
            "sitc_sell": sitc_sell,
            "sitc_net": sitc_buy - sitc_sell,
            "foreign_buy": foreign_buy,
            "foreign_sell": foreign_sell,
            "foreign_net": foreign_buy - foreign_sell,
        })
    return pd.DataFrame(rows)


def upsert_institutional(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    cols = ["ticker", "trade_date", "sitc_buy", "sitc_sell", "sitc_net",
            "foreign_buy", "foreign_sell", "foreign_net"]
    rows = df[cols].to_dict("records")
    placeholders = ", ".join(f":{c}" for c in cols)
    sql = f"INSERT OR REPLACE INTO institutional_investors ({', '.join(cols)}) VALUES ({placeholders})"
    conn.executemany(sql, rows)
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--tickers", help="Comma-separated list (default: all)")
    ap.add_argument("--teacher-only", action="store_true",
                    help="只跑老師 universe (~344 檔、~3-5 分鐘) + HELD/PLAN/WATCH 持倉")
    ap.add_argument("--limit", type=int, help="Process only first N tickers (test)")
    ap.add_argument("--end-date", default=TODAY, help=f"Default {TODAY}")
    ap.add_argument("--skip-bars", action="store_true", help="Skip TaiwanStockPrice sync")
    ap.add_argument("--skip-institutional", action="store_true", help="Skip institutional sync")
    ap.add_argument("--sleep-every", type=int, default=10, help="Sleep 1s every N tickers (rate limit)")
    args = ap.parse_args()

    end_date = args.end_date

    print(f"=== Sync to {end_date} ===")
    print(f"DB: {args.db}")
    print(f"Dry run: {args.dry_run}")
    print()

    # Build ticker list — restrict to regular stocks only (exclude warrants/derivatives)
    bar_max = get_ticker_max_dates(args.db)
    inst_max = get_ticker_inst_max_dates(args.db)
    # Filter to tickers in standard_daily_bar (regular stocks only, ~2321 tickers)
    # institutional_investors has 19k+ entries incl. warrants/ETF derivatives
    all_tickers = sorted(set(bar_max.keys()))

    if args.tickers:
        wanted = set(args.tickers.split(","))
        all_tickers = [t for t in all_tickers if t in wanted]
    elif args.teacher_only:
        # 老師 universe + 持倉 universe (HELD/PLAN_PRIMARY/WATCH)
        import json as _json
        wanted: set[str] = set()
        try:
            _picks = _json.loads(
                (_WORKTREE / "docs" / "主力大課程" / "teacher_picks_2026.json").read_text())
            wanted.update(k for k in _picks.keys() if not k.startswith("_"))
            _sectors = _json.loads(
                (_WORKTREE / "docs" / "主力大課程" / "teacher_sector_tickers.json").read_text())
            for v in _sectors.values():
                if isinstance(v, list):
                    wanted.update(v)
        except Exception as _e:
            print(f"⚠️ teacher_picks load failed: {_e}", flush=True)
        # 加 HELD / PLAN / WATCH 確保自己持倉一定同步
        try:
            sys.path.insert(0, str(_WORKTREE / "scripts"))
            from zhuli.live_position_monitor import HELD, PLAN_PRIMARY, WATCH
            for src in (HELD, PLAN_PRIMARY, WATCH):
                for item in src:
                    if isinstance(item, dict) and item.get("ticker"):
                        wanted.add(str(item["ticker"]))
        except Exception as _e:
            print(f"⚠️ HELD/WATCH load failed: {_e}", flush=True)
        all_tickers = [t for t in all_tickers if t in wanted]
        print(f"[teacher-only] universe = {len(wanted)} (老師 + 持倉)、與 DB 交集 = {len(all_tickers)}")
    if args.limit:
        all_tickers = all_tickers[:args.limit]

    print(f"Tickers to process: {len(all_tickers)}")
    print()

    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        sys.exit("ERROR: FINMIND_TOKEN env var not set.")
    client = FinMindClient(token=token)

    total_bar_rows = 0
    total_inst_rows = 0
    failed_bars = []
    failed_inst = []

    with get_conn(args.db, readonly=False) as conn:
        for i, ticker in enumerate(all_tickers, 1):
            # Bars
            if not args.skip_bars:
                cur_max = bar_max.get(ticker)
                if cur_max is None:
                    start = "2024-01-01"
                else:
                    # warmup: 拉前 80 個交易日 (估約 110 calendar days)
                    cur_max_date = date.fromisoformat(cur_max)
                    start = (cur_max_date - timedelta(days=120)).isoformat()
                if cur_max != end_date:
                    try:
                        df = fetch_bars_for_ticker(client, ticker, start, end_date)
                        if not df.empty and not args.dry_run:
                            n = upsert_bars(conn, df)
                            total_bar_rows += n
                        elif not df.empty:
                            total_bar_rows += len(df)
                        print(f"[{i}/{len(all_tickers)}] {ticker} bars: {len(df)} rows ({start}~{end_date})")
                    except Exception as e:
                        print(f"[{i}/{len(all_tickers)}] {ticker} bars FAIL: {e}")
                        failed_bars.append(ticker)
                else:
                    pass  # up to date

            # Institutional
            if not args.skip_institutional:
                inst_cur_max = inst_max.get(ticker)
                if inst_cur_max is None:
                    inst_start = "2024-01-01"
                else:
                    inst_cur_max_date = date.fromisoformat(inst_cur_max)
                    inst_start = (inst_cur_max_date + timedelta(days=1)).isoformat()
                if inst_start <= end_date:
                    try:
                        df = fetch_institutional_for_ticker(client, ticker, inst_start, end_date)
                        if not df.empty and not args.dry_run:
                            n = upsert_institutional(conn, df)
                            total_inst_rows += n
                        elif not df.empty:
                            total_inst_rows += len(df)
                        if not df.empty:
                            print(f"[{i}/{len(all_tickers)}] {ticker} inst: {len(df)} rows ({inst_start}~{end_date})")
                    except Exception as e:
                        print(f"[{i}/{len(all_tickers)}] {ticker} inst FAIL: {e}")
                        failed_inst.append(ticker)

            # Rate limit
            if i % args.sleep_every == 0:
                time.sleep(1)

        if not args.dry_run:
            conn.commit()

    print()
    print(f"=== Summary ===")
    print(f"Total bar rows upserted: {total_bar_rows}")
    print(f"Total inst rows upserted: {total_inst_rows}")
    print(f"Failed bars: {len(failed_bars)} {failed_bars[:5]}")
    print(f"Failed inst: {len(failed_inst)} {failed_inst[:5]}")
    print()
    print("Verify:")
    print("  sqlite3 ~/.four_seasons/data.sqlite \\")
    print("    'SELECT MAX(trade_date), COUNT(DISTINCT ticker) FROM standard_daily_bar'")
    print("  sqlite3 ~/.four_seasons/data.sqlite \\")
    print("    'SELECT MAX(trade_date), COUNT(DISTINCT ticker) FROM institutional_investors'")


if __name__ == "__main__":
    main()
