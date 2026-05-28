#!/usr/bin/env python3
"""Backfill TAIEX (加權指數) into standard_daily_bar as ticker='TAIEX'.

Used for 大盤方向 extras filter — backtest needs market direction proxy.
FinMind TaiwanStockPrice with stock_id='TAIEX' gives daily OHLC.
"""
import os
import sys
import sqlite3
import argparse
import time
from pathlib import Path

DB_PATH = Path.home() / '.four_seasons' / 'data.sqlite'


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--ticker-id", default="TAIEX", help="DB ticker key")
    p.add_argument("--finmind-id", default="TAIEX", help="FinMind stock_id")
    args = p.parse_args()

    token = os.environ.get("FINMIND_TOKEN")
    if not token:
        env = Path.home() / "Repository" / "four-seasons-investment" / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("FINMIND_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
    if not token:
        print("❌ FINMIND_TOKEN missing"); return 1

    from FinMind.data import DataLoader
    dl = DataLoader()
    dl.login_by_token(api_token=token)

    print(f"Fetching {args.finmind_id} {args.start} → {args.end}...")
    df = dl.taiwan_stock_daily(stock_id=args.finmind_id, start_date=args.start, end_date=args.end)
    if df is None or df.empty:
        print(f"❌ FinMind returned empty for {args.finmind_id}"); return 1
    print(f"  got {len(df)} rows")
    print(df.head(3))

    # 計算 MA20 等指標
    df = df.sort_values('date').reset_index(drop=True)
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma20'] = df['close'].rolling(20).mean()
    df['ma60'] = df['close'].rolling(60).mean()
    df['ma240'] = df['close'].rolling(240).mean()

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    # data_source_id 預設用 1（Fubon/FinMind 通用），看 schema
    src_id_row = db.execute("SELECT id FROM data_source LIMIT 1").fetchone()
    src_id = src_id_row[0] if src_id_row else 1

    inserted = 0
    for _, r in df.iterrows():
        try:
            cur.execute("""
                INSERT OR REPLACE INTO standard_daily_bar
                (ticker, trade_date, data_source_id, open, high, low, close, volume,
                 ma5, ma10, ma20, ma60, ma240, is_usable, is_conflicted)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
            """, (
                args.ticker_id, r['date'][:10], src_id,
                float(r.get('open', 0) or 0),
                float(r.get('max', r.get('high', 0)) or 0),
                float(r.get('min', r.get('low', 0)) or 0),
                float(r['close']),
                int(r.get('Trading_Volume', r.get('volume', 0)) or 0),
                float(r['ma5']) if r['ma5'] == r['ma5'] else None,
                float(r['ma10']) if r['ma10'] == r['ma10'] else None,
                float(r['ma20']) if r['ma20'] == r['ma20'] else None,
                float(r['ma60']) if r['ma60'] == r['ma60'] else None,
                float(r['ma240']) if r['ma240'] == r['ma240'] else None,
            ))
            inserted += 1
        except Exception as e:
            print(f"  err {r['date']}: {e}")
    db.commit()
    db.close()
    print(f"✅ Inserted/replaced {inserted} rows for ticker='{args.ticker_id}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
