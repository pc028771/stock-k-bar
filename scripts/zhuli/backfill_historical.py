"""Backfill 2020-2021 historical daily K data for sanity-check cases.

Downloads TaiwanStockPrice via FinMindClient (throttled) for the 5 instructor
case tickers and inserts rows into standard_daily_bar with computed MA/vol
derived columns.

Usage:
    python scripts/zhuli/backfill_historical.py [--db PATH] [--dry-run]

Tickers: 3533, 8150, 6284, 2338, 1590
Date range: 2020-06-01 ~ 2021-06-30  (includes MA60 warmup + post-signal buffer)
"""
from __future__ import annotations

from zhuli.db import get_conn

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

# ── path setup ─────────────────────────────────────────────────────────────────
_WORKTREE = Path(__file__).parent.parent.parent  # phase1-scanner/
_SCRIPTS_DIR = _WORKTREE / "scripts"             # phase1-scanner/scripts/
_SYS_DIR = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_WORKTREE), str(_SCRIPTS_DIR), str(_SYS_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from clients.finmind_client import FinMindClient  # noqa: E402
from kline.bars import DEFAULT_DB_PATH  # noqa: E402

# ── constants ──────────────────────────────────────────────────────────────────
TICKERS = [
    # H 窒息量（5+1）
    "3533", "8150", "6284", "2338", "1590",
    "1536",   # 和大 2021/03/22 月線下彎失敗 vs 上彎對比 (HD audit Ex1-3 25:00)
    # M 收高開低（2）：Ch7-3 揚智 2020-10-21、海光 2021-06-23
    "3041", "2038",
    # J 投信首買（2+3）
    "3707", "3552",
    "6672",   # 騰輝電子-KY 2021/05/28 (HD vision Ch4-2 37:15)
    "3006",   # 晶豪科 2021/02/17 大買 7,407 張 (HD vision Ch4-2 39:32)
    "6237",   # 華訊 2020/12/17 大買 4,183 張 (HD vision Ch4-2 42:36)
    # A 大波段（3）：中鋼 2021-03-09 + 2021-06-30、群創 2021-03-09、開發金 2021-03-09
    "2002", "2409", "2886",
    # G 隔日沖（3）：Ch6-2 案例 2021-06-22
    "2351",   # 順德 進 117 → 出 125
    "6271",   # 同欣電 ~210.5 → 211 隔日開盤
    "3149",   # 立達 漲停
    # C 反轉形態（3）：Ch4-2 案例
    "1904",   # 正隆 2020-08-11 反轉紅K
    "6441",   # 廣錠 2020-09-16 失敗對比
    "3042",   # 晶技 2021-01-08 反轉成功
    # B 旗形（1+1）：Ch4-2 案例
    # 2492 華新科 已在 J 案例清單（複用）
    "2108",   # 南帝 2020-09-29 第二實例
    # F 當沖（4）：Ch5-2 案例
    "3141",   # 晶宏 2021-06-07 準突破示範
    "2314",   # 台揚 2021-07 接近邊界
    "2010",   # 春源 2021-07-25 量 57,792
    # 3006 晶豪科 已在 (Ch5-2 案例 2021-07-01 + Ch4-2 D 案例 2021-02-17)
]
START_DATE = "2019-09-01"   # 涵蓋 2492 華新科 2019-12-24 旗杆 + ma60 warmup
END_DATE   = "2021-12-31"
DATA_SOURCE_ID = 1           # finmind source row in data_source table


# ── helpers ────────────────────────────────────────────────────────────────────
def _compute_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Add MA and vol columns expected by standard_daily_bar + load_bars query.

    Input df must be sorted by trade_date asc for a single ticker.
    """
    df = df.sort_values("trade_date").copy()

    df["ma5"]   = df["close"].rolling(5,   min_periods=1).mean()
    df["ma10"]  = df["close"].rolling(10,  min_periods=1).mean()
    df["ma20"]  = df["close"].rolling(20,  min_periods=1).mean()
    df["ma60"]  = df["close"].rolling(60,  min_periods=1).mean()
    df["ma240"] = df["close"].rolling(240, min_periods=1).mean()

    # ma20_slope: (ma20[t] - ma20[t-5]) / ma20[t-5]  (5-day proxy)
    ma20_prev5 = df["ma20"].shift(5)
    df["ma20_slope"] = (df["ma20"] - ma20_prev5) / ma20_prev5.replace(0, float("nan"))
    df["ma20_slope_proxy"] = df["ma20_slope"]

    # vol_ma20: 20-day average volume
    df["vol_ma20"] = df["volume"].rolling(20, min_periods=1).mean()
    # vol_ratio_20: today / 20d avg
    df["vol_ratio_20"] = df["volume"] / df["vol_ma20"].replace(0, float("nan"))

    return df


def fetch_and_prepare(ticker: str, client: FinMindClient) -> pd.DataFrame:
    """Fetch OHLCV for one ticker; return rows ready for DB insert."""
    print(f"  Fetching {ticker} …", end=" ", flush=True)
    raw = client.get_price(ticker, START_DATE, END_DATE)
    if raw.empty:
        print("EMPTY — skipping.")
        return pd.DataFrame()

    print(f"{len(raw)} rows fetched.")

    # FinMind columns: date, open, high, low, close, volume  (after rename max/min)
    # Normalise column names
    col_map = {
        "date": "trade_date",
        "Trading_Volume": "volume",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
    }
    raw = raw.rename(columns={k: v for k, v in col_map.items() if k in raw.columns})

    # Keep only needed columns
    needed = ["trade_date", "open", "high", "low", "close", "volume"]
    missing = [c for c in needed if c not in raw.columns]
    if missing:
        print(f"    WARNING: missing columns {missing}; available: {list(raw.columns)}")
        return pd.DataFrame()

    df = raw[needed].copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["ticker"] = ticker
    df["data_source_id"] = DATA_SOURCE_ID
    df["is_usable"] = 1

    # Numeric
    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").astype("Int64")

    # Drop bad rows
    df = df.dropna(subset=["open", "high", "low", "close", "volume"])
    df = df[(df["close"] > 0) & (df["volume"] > 0)]

    # Compute derived columns (sorted by date already)
    df = _compute_derived(df)

    return df


def insert_into_db(df: pd.DataFrame, db_path: Path, dry_run: bool = False) -> int:
    """Insert/replace rows into standard_daily_bar. Returns rows written."""
    if df.empty:
        return 0

    rows = df.to_dict("records")

    cols = [
        "ticker", "trade_date", "data_source_id",
        "open", "high", "low", "close", "volume",
        "ma5", "ma10", "ma20", "ma60", "ma240",
        "ma20_slope", "ma20_slope_proxy",
        "vol_ma20", "vol_ratio_20",
        "is_usable",
        "is_attention_stock", "is_disposition_stock",
    ]

    if dry_run:
        print(f"    DRY RUN — would insert {len(rows)} rows for {df['ticker'].iloc[0]}")
        return len(rows)

    placeholders = ", ".join(f":{c}" for c in cols)
    sql = (
        f"INSERT OR REPLACE INTO standard_daily_bar ({', '.join(cols)}) "
        f"VALUES ({placeholders})"
    )

    with get_conn(db_path, readonly=False, timeout=30) as conn:
        conn.executemany(
            sql,
            [
                {
                    c: (
                        # Use pure YYYY-MM-DD format to match existing DB rows;
                        # isoformat() on a Timestamp gives YYYY-MM-DDTHH:MM:SS
                        # which parse_dates cannot handle consistently in bulk loads.
                        row.get(c).date().isoformat()
                        if c == "trade_date" and hasattr(row.get(c), "date")
                        else (None if pd.isna(row.get(c)) else row.get(c))
                    )
                    for c in cols
                }
                for row in rows
            ],
        )
        conn.commit()

    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill 2020-2021 historical daily K data into standard_daily_bar."
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch data and compute features but do NOT write to DB.",
    )
    args = parser.parse_args()

    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        sys.exit("ERROR: FINMIND_TOKEN env var not set.")

    client = FinMindClient(token=token)

    print(f"DB: {args.db}")
    print(f"Tickers: {TICKERS}")
    print(f"Date range: {START_DATE} ~ {END_DATE}")
    print()

    total_written = 0
    for ticker in TICKERS:
        df = fetch_and_prepare(ticker, client)
        written = insert_into_db(df, args.db, dry_run=args.dry_run)
        total_written += written
        print(f"    → {written} rows {'would be written' if args.dry_run else 'written'} for {ticker}")

    print()
    print(f"Done. Total rows: {total_written}")

    # Verify
    if not args.dry_run:
        with get_conn(args.db, readonly=False, timeout=15) as conn:
            result = conn.execute(
                "SELECT ticker, COUNT(*) as cnt, MIN(trade_date) as min_d, MAX(trade_date) as max_d "
                "FROM standard_daily_bar "
                f"WHERE ticker IN ({', '.join(repr(t) for t in TICKERS)}) "
                "  AND trade_date < '2022-01-01' "
                "GROUP BY ticker ORDER BY ticker"
            ).fetchall()
        print()
        print("DB verification (historical rows < 2022):")
        for row in result:
            print(f"  {row[0]:6s}  {row[1]:4d} rows  {row[2]} ~ {row[3]}")


if __name__ == "__main__":
    main()
