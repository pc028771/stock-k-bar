"""快速同步今日（或指定日）全市場日 K — 一次 API call 搞定.

原理：
  1. FinMind TaiwanStockPrice（不指定 data_id）→ 一次拿全市場當日所有股票
  2. 對每個 ticker 讀 DB 現有資料計算 MA（不需重抓 80 天 warmup）
  3. INSERT OR REPLACE 新一天的資料

vs sync_missing_daily_bars.py:
  - sync_missing_daily_bars: 逐 ticker、80 天 warmup、適合補歷史
  - sync_today: 一次全市場、只補最新一天、速度快 10-20x

Usage:
    python scripts/zhuli/sync_today.py
    python scripts/zhuli/sync_today.py --date 2026-05-22
    python scripts/zhuli/sync_today.py --skip-institutional
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import requests

_REPO = Path(__file__).parent.parent.parent
_SYS = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_REPO), str(_REPO / "scripts"), str(_SYS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

DB_PATH = Path.home() / ".four_seasons" / "data.sqlite"
DATA_SOURCE_ID = 1


def fetch_whole_market(target_date: str, token: str) -> pd.DataFrame:
    """一次 call 拿全市場當日收盤資料."""
    print(f"抓 FinMind 全市場 {target_date}...")
    r = requests.get("https://api.finmindtrade.com/api/v4/data", params={
        "dataset": "TaiwanStockPrice",
        "start_date": target_date,
        "end_date": target_date,
        "token": token,
    }, timeout=60)
    data = r.json().get("data", [])
    print(f"  → {len(data)} 筆")
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    df = df.rename(columns={
        "stock_id": "ticker", "date": "trade_date",
        "max": "high", "min": "low",
        "Trading_Volume": "volume",
    })
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
    return df[["ticker", "trade_date", "open", "high", "low", "close", "volume"]]


def compute_mas_and_upsert(new_df: pd.DataFrame, db_path: Path) -> dict:
    """對每個 ticker 從 DB 讀取舊資料，計算 MA，插入新一天."""
    con = sqlite3.connect(str(db_path), timeout=30)
    tickers = new_df["ticker"].unique()
    upserted = 0
    skipped = 0

    # 先確認 data_source_id 1 存在
    existing = [r[0] for r in con.execute(
        "SELECT DISTINCT ticker FROM standard_daily_bar WHERE is_usable=1"
    ).fetchall()]
    existing_set = set(existing)

    for t in tickers:
        row = new_df[new_df["ticker"] == t].iloc[0]
        if t not in existing_set:
            skipped += 1
            continue

        # 讀近 240 天現有資料計算 MA
        hist = pd.read_sql("""
            SELECT trade_date, open, high, low, close, volume
            FROM standard_daily_bar
            WHERE ticker=? AND trade_date < ?
            ORDER BY trade_date DESC LIMIT 240
        """, con, params=(t, row["trade_date"]))
        hist = hist.iloc[::-1].reset_index(drop=True)

        # 接上新一天
        new_row = pd.DataFrame([{
            "trade_date": row["trade_date"],
            "open": row["open"], "high": row["high"],
            "low": row["low"], "close": row["close"],
            "volume": row["volume"],
        }])
        full = pd.concat([hist, new_row], ignore_index=True)
        c = full["close"]
        v = full["volume"].astype(float)

        ma5   = c.rolling(5).mean().iloc[-1]
        ma10  = c.rolling(10).mean().iloc[-1]
        ma20  = c.rolling(20).mean().iloc[-1]
        ma60  = c.rolling(60).mean().iloc[-1]
        ma240 = c.rolling(240).mean().iloc[-1]
        vol_ma20 = v.rolling(20).mean().iloc[-1]
        vol_ratio = (v.iloc[-1] / vol_ma20) if vol_ma20 else None

        # ma20_slope (5d proxy)
        ma20_series = c.rolling(20).mean()
        slope = (ma20_series.iloc[-1] - ma20_series.iloc[-6]) / 5 if len(ma20_series) >= 6 else None

        con.execute("""
            INSERT OR REPLACE INTO standard_daily_bar
            (ticker, trade_date, data_source_id, open, high, low, close, volume,
             ma5, ma10, ma20, ma60, ma240, vol_ma20, vol_ratio_20, ma20_slope,
             is_usable, is_conflicted)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,0)
        """, (t, row["trade_date"], DATA_SOURCE_ID,
              float(row["open"]), float(row["high"]),
              float(row["low"]), float(row["close"]), int(row["volume"]),
              float(ma5) if pd.notna(ma5) else None,
              float(ma10) if pd.notna(ma10) else None,
              float(ma20) if pd.notna(ma20) else None,
              float(ma60) if pd.notna(ma60) else None,
              float(ma240) if pd.notna(ma240) else None,
              float(vol_ma20) if pd.notna(vol_ma20) else None,
              float(vol_ratio) if vol_ratio and pd.notna(vol_ratio) else None,
              float(slope) if slope and pd.notna(slope) else None))
        upserted += 1

    con.commit()
    con.close()
    return {"upserted": upserted, "skipped": skipped}


def fetch_institutional_whole(target_date: str, token: str) -> pd.DataFrame:
    """一次拿全市場當日法人資料."""
    print(f"抓全市場法人 {target_date}...")
    r = requests.get("https://api.finmindtrade.com/api/v4/data", params={
        "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
        "start_date": target_date,
        "end_date": target_date,
        "token": token,
    }, timeout=60)
    data = r.json().get("data", [])
    print(f"  → {len(data)} 筆原始")
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    # 聚合成每個 ticker 一行
    fi = df[df["name"] == "Foreign_Investor"].groupby("stock_id").agg(
        foreign_buy=("buy", "sum"), foreign_sell=("sell", "sum")
    )
    it = df[df["name"] == "Investment_Trust"].groupby("stock_id").agg(
        sitc_buy=("buy", "sum"), sitc_sell=("sell", "sum")
    )
    merged = fi.join(it, how="outer").fillna(0).reset_index()
    merged.columns = ["ticker", "foreign_buy", "foreign_sell", "sitc_buy", "sitc_sell"]
    merged["foreign_net"] = (merged["foreign_buy"] - merged["foreign_sell"]) / 1000
    merged["sitc_net"] = (merged["sitc_buy"] - merged["sitc_sell"]) / 1000
    merged["trade_date"] = target_date
    print(f"  → {len(merged)} ticker")
    return merged


def upsert_institutional(df: pd.DataFrame, db_path: Path) -> int:
    con = sqlite3.connect(str(db_path), timeout=30)
    n = 0
    for _, r in df.iterrows():
        con.execute("""
            INSERT OR REPLACE INTO institutional_investors
            (ticker, trade_date, foreign_buy, foreign_sell, foreign_net,
             sitc_buy, sitc_sell, sitc_net)
            VALUES (?,?,?,?,?,?,?,?)
        """, (r["ticker"], r["trade_date"],
              r["foreign_buy"], r["foreign_sell"], r["foreign_net"],
              r["sitc_buy"], r["sitc_sell"], r["sitc_net"]))
        n += 1
    con.commit()
    con.close()
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--skip-institutional", action="store_true")
    args = ap.parse_args()

    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        print("⚠️  FINMIND_TOKEN 未設定"); sys.exit(1)

    import time
    t0 = time.time()
    print(f"\n=== sync_today {args.date} ===")

    # 日K
    bars = fetch_whole_market(args.date, token)
    if bars.empty:
        print("無資料（可能是假日或尚未收盤）")
        sys.exit(0)

    result = compute_mas_and_upsert(bars, Path(args.db))
    print(f"日K upserted: {result['upserted']}  skipped(新股): {result['skipped']}")

    # 法人
    if not args.skip_institutional:
        inst = fetch_institutional_whole(args.date, token)
        if not inst.empty:
            n = upsert_institutional(inst, Path(args.db))
            print(f"法人 upserted: {n}")

    print(f"\n完成！耗時 {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
