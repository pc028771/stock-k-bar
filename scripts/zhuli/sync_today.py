"""快速同步今日（或指定日）全市場日 K — 一次 call 搞定.

原理：
  1. Fubon get_snapshot_quotes（TSE + OTC）→ 即時收盤資料，收盤後停留在收盤價
  2. 對每個 ticker 讀 DB 現有資料計算 MA（不需重抓 80 天 warmup）
  3. INSERT OR REPLACE 新一天的資料

法人資料仍走 FinMind（TWSE 收盤後才公布，時效性要求低）。

Usage:
    python scripts/zhuli/sync_today.py
    python scripts/zhuli/sync_today.py --date 2026-05-22
    python scripts/zhuli/sync_today.py --skip-institutional
    python scripts/zhuli/sync_today.py --dry-run   # 盤中跑：只顯示不寫入 DB
"""
from __future__ import annotations

from zhuli.db import get_conn, MAIN_DB

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

DB_PATH = MAIN_DB
DATA_SOURCE_ID = 1


def fetch_whole_market_fubon(target_date: str) -> pd.DataFrame:
    """Fubon snapshot（TSE + OTC）→ 全市場當日收盤 OHLCV.

    收盤後 snapshot 停留在收盤價，無需等 FinMind 延遲更新。
    """
    from clients.fubon_client import FubonClient

    print(f"抓 Fubon snapshot {target_date}...")
    client = FubonClient()
    rows = []

    for market in ["TSE", "OTC"]:
        data = client.get_snapshot_quotes(market)
        for d in data:
            symbol = d.get("symbol") or d.get("code") or ""
            if not str(symbol).isdigit() or len(str(symbol)) != 4:
                continue  # 排除 ETF / 權證等非 4 位數 ticker

            close_p = d.get("closePrice") or d.get("lastPrice") or d.get("close")
            if not close_p:
                continue

            rows.append({
                "ticker":     str(symbol),
                "trade_date": target_date,
                "open":       float(d.get("openPrice")  or d.get("open")  or close_p),
                "high":       float(d.get("highPrice")  or d.get("high")  or close_p),
                "low":        float(d.get("lowPrice")   or d.get("low")   or close_p),
                "close":      float(close_p),
                # tradeVolume 單位為張（lots），× 1000 → 股（shares）與 FinMind 歷史資料一致
                "volume":     int(d.get("tradeVolume") or 0) * 1000,
            })

    client.disconnect()
    print(f"  → {len(rows)} 檔")
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def compute_mas_and_upsert(new_df: pd.DataFrame, db_path: Path, dry_run: bool = False) -> dict:
    """對每個 ticker 從 DB 讀取舊資料，計算 MA，插入新一天.

    dry_run=True 時跳過 INSERT、只回傳統計（用於盤中只看不存）.
    """
    con = get_conn(db_path, readonly=False, timeout=30)
    tickers = new_df["ticker"].unique()
    upserted = 0
    skipped = 0
    preview_rows = []

    existing_set = set(r[0] for r in con.execute(
        "SELECT DISTINCT ticker FROM standard_daily_bar WHERE is_usable=1"
    ).fetchall())

    for t in tickers:
        row = new_df[new_df["ticker"] == t].iloc[0]
        if t not in existing_set:
            skipped += 1
            continue

        hist = pd.read_sql("""
            SELECT trade_date, open, high, low, close, volume
            FROM standard_daily_bar
            WHERE ticker=? AND trade_date < ?
            ORDER BY trade_date DESC LIMIT 240
        """, con, params=(t, row["trade_date"]))
        hist = hist.iloc[::-1].reset_index(drop=True)

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
        vol_ma20  = v.rolling(20).mean().iloc[-1]
        vol_ratio = (v.iloc[-1] / vol_ma20) if vol_ma20 else None

        ma20_series = c.rolling(20).mean()
        slope = (ma20_series.iloc[-1] - ma20_series.iloc[-6]) / 5 if len(ma20_series) >= 6 else None

        if dry_run:
            preview_rows.append({
                "ticker": t, "close": row["close"], "volume": int(row["volume"]),
                "ma5": ma5, "ma10": ma10, "ma20": ma20,
                "vol_ratio": vol_ratio,
            })
            upserted += 1
            continue

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

    if not dry_run:
        con.commit()
    con.close()
    return {"upserted": upserted, "skipped": skipped, "preview": preview_rows}


def fetch_institutional_whole(target_date: str, token: str, valid_tickers: set | None = None) -> pd.DataFrame:
    """FinMind → 全市場當日法人資料（TWSE 收盤後公布，時效性要求低）."""
    print(f"抓全市場法人 {target_date}...")
    r = requests.get("https://api.finmindtrade.com/api/v4/data", params={
        "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
        "start_date": target_date,
        "end_date": target_date,
        "token": token,
    }, timeout=60)
    data = r.json().get("data", [])
    print(f"  → {len(data)} 筆原始")
    if valid_tickers and data:
        data = [d for d in data if d.get("stock_id") in valid_tickers]
        print(f"  → 過濾後 {len(data)} 筆")
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    fi = df[df["name"] == "Foreign_Investor"].groupby("stock_id").agg(
        foreign_buy=("buy", "sum"), foreign_sell=("sell", "sum")
    )
    it = df[df["name"] == "Investment_Trust"].groupby("stock_id").agg(
        sitc_buy=("buy", "sum"), sitc_sell=("sell", "sum")
    )
    merged = fi.join(it, how="outer").fillna(0).reset_index()
    merged.columns = ["ticker", "foreign_buy", "foreign_sell", "sitc_buy", "sitc_sell"]
    merged["foreign_net"] = (merged["foreign_buy"] - merged["foreign_sell"]) / 1000
    merged["sitc_net"]    = (merged["sitc_buy"]    - merged["sitc_sell"])    / 1000
    merged["trade_date"]  = target_date
    print(f"  → {len(merged)} ticker")
    return merged


def upsert_institutional(df: pd.DataFrame, db_path: Path, dry_run: bool = False) -> int:
    if dry_run:
        return len(df)
    con = get_conn(db_path, readonly=False, timeout=30)
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
    ap.add_argument("--dry-run", action="store_true",
                    help="盤中跑：抓資料 + 計算 MA，但不寫入 DB（只顯示）")
    args = ap.parse_args()

    # 非交易日提早退出
    try:
        from zhuli.trading_calendar import is_trading_day
        if not is_trading_day(args.date):
            print(f"ℹ️  {args.date} 非交易日，略過同步")
            sys.exit(0)
    except Exception:
        pass

    import time
    t0 = time.time()
    banner = " [DRY RUN — 不寫 DB]" if args.dry_run else ""
    print(f"\n=== sync_today {args.date}{banner} ===")

    # 日K：Fubon snapshot（收盤即時，無延遲）
    bars = fetch_whole_market_fubon(args.date)
    if bars.empty:
        print("無資料（可能是假日或 Fubon 連線失敗）")
        sys.exit(1)

    result = compute_mas_and_upsert(bars, Path(args.db), dry_run=args.dry_run)
    verb = "會 upsert" if args.dry_run else "upserted"
    print(f"日K {verb}: {result['upserted']}  skipped(新股): {result['skipped']}")

    # Dry-run 給個 sample 預覽（前 10 + 任意指定 holdings）
    if args.dry_run and result.get("preview"):
        watch = {"5347", "2464", "3149", "6282", "2476", "2481", "6285", "6138"}
        preview = result["preview"]
        print("\n預覽（指定 holdings/watchlist）：")
        print(f"  {'ticker':<8} {'close':>8} {'volume':>12} {'MA5':>8} {'MA10':>8} {'MA20':>8} {'vol_ratio':>10}")
        for p in preview:
            if p["ticker"] in watch:
                fmt = lambda x: f"{x:.2f}" if x is not None and pd.notna(x) else "-"
                print(f"  {p['ticker']:<8} {p['close']:>8.2f} {p['volume']:>12} "
                      f"{fmt(p['ma5']):>8} {fmt(p['ma10']):>8} {fmt(p['ma20']):>8} {fmt(p['vol_ratio']):>10}")

    # 法人：FinMind（TWSE 收盤後公布，不需要即時）
    if not args.skip_institutional:
        token = os.environ.get("FINMIND_TOKEN", "")
        if not token:
            print("⚠️  FINMIND_TOKEN 未設定，跳過法人資料")
        else:
            con_r = get_conn(Path(args.db), timeout=5)
            valid_tickers = set(r[0] for r in con_r.execute(
                "SELECT DISTINCT ticker FROM standard_daily_bar WHERE is_usable=1"
            ).fetchall())
            con_r.close()
            inst = fetch_institutional_whole(args.date, token, valid_tickers)
            if not inst.empty:
                n = upsert_institutional(inst, Path(args.db), dry_run=args.dry_run)
                verb = "會 upsert" if args.dry_run else "upserted"
                print(f"法人 {verb}: {n}")

    print(f"\n完成！耗時 {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
