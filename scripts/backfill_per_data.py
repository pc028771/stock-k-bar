#!/usr/bin/env python3
"""Backfill pb_ratio + dividend_yield_pct into standard_daily_bar from FinMind TaiwanStockPER.

Strategy: sponsor by-date all-stock fetch (fast, 500 days × 1 call ≈ 50 min).
"""
import os
import sys
import argparse
import sqlite3
import time
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path.home() / '.four_seasons' / 'data.sqlite'


def get_trading_dates(db: sqlite3.Connection, start: str, end: str) -> list[str]:
    """Return distinct trade_dates available in standard_daily_bar within range."""
    rows = db.execute(
        "SELECT DISTINCT trade_date FROM standard_daily_bar "
        "WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date",
        (start, end)
    ).fetchall()
    return [r[0] for r in rows]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--dry-run", action="store_true", help="Fetch 5 days only")
    p.add_argument("--throttle", type=float, default=0.5,
                   help="Seconds between API calls (default 0.5)")
    args = p.parse_args()

    token = os.environ.get("FINMIND_TOKEN")
    if not token:
        env_path = Path.home() / "Repository" / "four-seasons-investment" / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("FINMIND_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
    if not token:
        print("❌ FINMIND_TOKEN not found", file=sys.stderr)
        return 1

    from FinMind.data import DataLoader
    dl = DataLoader()
    dl.login_by_token(api_token=token)

    db = sqlite3.connect(DB_PATH)
    dates = get_trading_dates(db, args.start, args.end)
    if args.dry_run:
        dates = dates[:5]

    print(f"📅 Trading dates to fetch: {len(dates)} ({dates[0]} → {dates[-1]})")

    total_updated = 0
    failed_dates = []
    t0 = time.time()

    for i, dt in enumerate(dates):
        time.sleep(args.throttle)
        try:
            df = dl.taiwan_stock_per_pbr(start_date=dt, end_date=dt)
            if df is None or df.empty:
                continue
            # Update rows
            updates = []
            for _, row in df.iterrows():
                stock_id = str(row.get("stock_id", ""))
                pb = row.get("PBR") or row.get("pbr")
                # dividend_yield is the column name in TaiwanStockPER
                div = row.get("dividend_yield")
                if not stock_id:
                    continue
                updates.append((
                    float(pb) if pb is not None else None,
                    float(div) if div is not None else None,
                    stock_id, dt
                ))
            cur = db.cursor()
            cur.executemany(
                "UPDATE standard_daily_bar SET pb_ratio=?, dividend_yield_pct=? "
                "WHERE ticker=? AND trade_date=?",
                updates
            )
            db.commit()
            total_updated += cur.rowcount

            elapsed = time.time() - t0
            rate = (i+1) / elapsed if elapsed > 0 else 0
            eta_min = (len(dates) - i - 1) / rate / 60 if rate > 0 else 0
            if (i+1) % 20 == 0 or i == 0:
                print(f"  [{i+1:>3}/{len(dates)}] {dt}: {len(updates)} rows, "
                      f"cum updated={total_updated}, rate={rate:.1f}/s, eta {eta_min:.1f}min")
        except Exception as e:
            print(f"  ⚠️  {dt}: {e}")
            failed_dates.append(dt)

    db.close()
    elapsed = time.time() - t0
    print(f"\n✅ Done. Updated {total_updated} rows in {elapsed:.1f}s ({len(failed_dates)} failed)")
    if failed_dates:
        print(f"   Failed dates: {failed_dates[:10]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
