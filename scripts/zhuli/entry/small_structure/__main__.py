"""CLI 入口 — python -m zhuli.entry.small_structure.

用法:
    # Detect mode (與舊版相容)
    python -m zhuli.entry.small_structure --date 2026-05-29

    # Watchlist mode (全市場三級分類)
    python -m zhuli.entry.small_structure --date 2026-05-29 --watchlist

    # Watchlist + sector universe 過濾
    python -m zhuli.entry.small_structure --date 2026-05-29 --watchlist --universe sector_week

    # Validation (4+1 個 backtest)
    python -m zhuli.entry.small_structure --validate
    python -m zhuli.entry.small_structure --validate --case A B E
"""
from __future__ import annotations

from zhuli.db import get_conn, MAIN_DB

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).parent.parent.parent.parent.parent
_DB = MAIN_DB
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.entry.small_structure.detector import detect
from zhuli.entry.small_structure.watchlist import (
    run_watchlist,
    format_watchlist_report,
    run_post_attack_watchlist,
    format_post_attack_report,
)


def _all_tickers(con: sqlite3.Connection) -> list[str]:
    rows = con.execute("SELECT DISTINCT ticker FROM standard_daily_bar WHERE is_usable=1").fetchall()
    return [r[0] for r in rows]


def _load_bars(con: sqlite3.Connection, ticker: str, target_date: str) -> pd.DataFrame:
    df = pd.read_sql("""
        SELECT ticker, trade_date, trade_date as date,
               open, high, low, close, volume,
               vol_ratio_20, ma5, ma10, ma20, ma60
        FROM standard_daily_bar
        WHERE ticker = ? AND trade_date >= date(?, '-200 days') AND trade_date <= ?
        ORDER BY trade_date
    """, con, params=(ticker, target_date, target_date))
    return df


def _stock_info(con: sqlite3.Connection) -> dict[str, str]:
    rows = con.execute("SELECT ticker, stock_name FROM stock_info").fetchall()
    return {r[0]: r[1] for r in rows}


def run_detect_mode(args) -> None:
    """全市場掃描並輸出 detect()=True 清單."""
    target_date = args.date
    con = get_conn(_DB)

    tickers = _all_tickers(con)
    info = _stock_info(con)
    print(f"[小結構 scanner] {target_date}  掃描 {len(tickers)} 檔...")

    candidates = []
    for tkr in tickers:
        df = _load_bars(con, tkr, target_date)
        if len(df) < 30:
            continue
        try:
            sig = detect(df)
            if sig.iloc[-1]:
                last = df.iloc[-1]
                candidates.append({
                    "ticker": tkr,
                    "name": info.get(tkr, ""),
                    "close": last['close'],
                    "vol_ratio_20": last['vol_ratio_20'],
                })
        except Exception:
            continue

    con.close()

    print(f"\n[小結構] {target_date} 候選: {len(candidates)} 檔\n")
    for c in sorted(candidates, key=lambda x: x['ticker']):
        print(f"  {c['ticker']} {c['name']:12s}  ${c['close']:.1f}  vol_ratio={c['vol_ratio_20']:.2f}")


def run_watchlist_mode(args) -> None:
    """Watchlist 三級分類輸出."""
    target_date = args.date
    universe = args.universe
    con = get_conn(_DB)

    tickers = _all_tickers(con)
    info = _stock_info(con)
    print(f"[小結構 Watchlist] {target_date}  universe={universe}  掃描 {len(tickers)} 檔...")

    # 載入全市場資料並合併
    all_dfs = []
    for tkr in tickers:
        df = _load_bars(con, tkr, target_date)
        if len(df) < 30:
            continue
        all_dfs.append(df)

    con.close()

    if not all_dfs:
        print("  無資料")
        return

    # 逐一跑 watchlist（watchlist.py 內部已處理）
    # 為了 sector_week universe 過濾，傳整個合併 df
    combined = pd.concat(all_dfs, ignore_index=True)

    tier = getattr(args, 'tier', None)
    if tier == 'post_attack_consol':
        # 攻擊後盤整模式
        wl = run_post_attack_watchlist(combined, universe=universe, target_date=target_date, ticker_col='ticker')
        report = format_post_attack_report(wl, stock_info=info, target_date=target_date, universe=universe)
        print("\n" + report)
    else:
        wl = run_watchlist(combined, universe=universe, target_date=target_date, ticker_col='ticker')
        # 加名稱
        if not wl.empty and 'ticker' in wl.columns:
            wl['name'] = wl['ticker'].map(lambda t: info.get(t, ''))
        report = format_watchlist_report(wl, universe=universe, target_date=target_date)
        print("\n" + report)


def run_validate_mode(args) -> None:
    """執行 validation suite."""
    from zhuli.entry.small_structure.validation import run_all
    cases = args.case if args.case else None
    run_all(cases)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="小結構整理 scanner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--date", default="2026-05-29", help="目標日期 YYYY-MM-DD")
    parser.add_argument("--watchlist", action="store_true", help="Watchlist 三級分類模式")
    parser.add_argument("--universe", default="all",
                        choices=["all", "sector_all", "sector_week"],
                        help="老師族群 universe 過濾")
    parser.add_argument("--validate", action="store_true", help="執行 validation suite")
    parser.add_argument("--case", nargs="+", help="指定 validation case (A B C D E)")
    parser.add_argument("--db", default=str(_DB), help="DB 路徑")

    args = parser.parse_args()

    if args.validate:
        run_validate_mode(args)
    elif args.watchlist:
        run_watchlist_mode(args)
    else:
        run_detect_mode(args)


if __name__ == "__main__":
    main()
