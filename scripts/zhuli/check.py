#!/usr/bin/env python3
"""[FOR AGENT USE] 快速個股檢查工具.

⚠️ This script is for AI agent use, NOT for interactive user.
   每次 user 問「看一下 XXXX」、agent 用這個替代寫 /tmp script。

Usage (agent 跑):
    python scripts/zhuli/check.py 8046                # 單檔
    python scripts/zhuli/check.py 8046 3264 1303      # 多檔
    python scripts/zhuli/check.py 8046 --cost 900 --shares 1000 --stop 856
    python scripts/zhuli/check.py 8046 --days 14      # 近 14 日 K
"""
from __future__ import annotations

import argparse
import datetime as _dt
import logging
import sqlite3
import sys
from pathlib import Path

# 系統路徑
_REPO = Path(__file__).resolve().parent.parent.parent
_SAS = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [_REPO, _SAS]:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

logging.basicConfig(level=logging.ERROR)
logging.getLogger("clients.fubon_client").setLevel(logging.ERROR)

from clients.fubon_client import FubonClient  # noqa: E402

DB = Path.home() / ".four_seasons" / "data.sqlite"


def check_one(c: FubonClient, ticker: str, cost: float | None = None,
              shares: int | None = None, stop: float | None = None,
              days: int = 7) -> None:
    """印出單檔分析."""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        # 取股名 + 最新日線
        r = con.execute(
            "SELECT stock_name FROM stock_info WHERE ticker=?", (ticker,)
        ).fetchone()
        name = r[0] if r else "?"

        row = con.execute(
            "SELECT close, ma5, ma10, ma20, ma60 "
            "FROM standard_daily_bar WHERE ticker=? "
            "ORDER BY trade_date DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        if not row:
            print(f"❌ {ticker} 無歷史資料")
            return
        pc, m5, m10, m20, m60 = row
        m60 = m60 or 0

        # 即時 snapshot
        snap = c.get_realtime_snapshot(ticker) or {}
        o  = float(snap.get("open")  or 0)
        h  = float(snap.get("high")  or 0)
        lo = float(snap.get("low")   or 0)
        cl = float(snap.get("close") or 0)

        # 若沒即時資料、用昨日收盤
        if cl == 0:
            cl = pc
            no_live = True
        else:
            no_live = False

        chg     = (cl - pc) / pc * 100 if pc else 0
        opn_chg = (o - pc) / pc * 100 if (pc and o) else 0
        now     = _dt.datetime.now().strftime("%H:%M:%S")

        # === 標題 ===
        flag = " ⚠️ 無即時" if no_live else ""
        print(f"\n=== {ticker} {name} — {now}{flag} ===")
        print(f"前收 ${pc}  MA5 ${m5:.1f}  MA10 ${m10:.1f}  MA20 ${m20:.1f}  MA60 ${m60:.1f}")
        print(f"今  O${o} ({opn_chg:+.2f}%)  H${h}  L${lo}  C${cl} ({chg:+.2f}%)")

        # === 距均線 ===
        if cl and m5:
            print(f"距  MA5 {(cl - m5) / m5 * 100:+.1f}%   "
                  f"MA10 {(cl - m10) / m10 * 100:+.1f}%   "
                  f"MA20 {(cl - m20) / m20 * 100:+.1f}%"
                  + (f"   MA60 {(cl - m60) / m60 * 100:+.1f}%" if m60 else ""))

        # === 日內 ===
        if h and lo and o:
            from_h = (cl - h) / h * 100
            from_l = (cl - lo) / lo * 100
            rng    = (h - lo) / o * 100
            print(f"日內 振幅 {rng:.1f}%   從高 {from_h:+.1f}%   從低 {from_l:+.1f}%")

        # === 持倉 P&L (若有 cost) ===
        if cost is not None and shares is not None:
            pnl     = (cl - cost) * shares
            pnl_pct = (cl - cost) / cost * 100 if cost else 0
            print(f"\n💰 持倉: {shares}股 × 均${cost} = ${cost * shares:,.0f}")
            print(f"   帳面 ${pnl:+,.0f} ({pnl_pct:+.2f}%)")
            if stop:
                dist_stop = (cl - stop) / cl * 100 if cl else 0
                max_loss  = (stop - cost) * shares
                print(f"   停損 ${stop}  距 +{dist_stop:.1f}%  "
                      f"最大損 ${max_loss:+,.0f}")

        # === 近 N 日 K ===
        print(f"\n近 {days} 日:")
        rows = con.execute(
            "SELECT trade_date, open, high, low, close, volume "
            "FROM standard_daily_bar WHERE ticker=? "
            "ORDER BY trade_date DESC LIMIT ?",
            (ticker, days),
        ).fetchall()
        rows.reverse()
        prev_close = None
        for d, o2, h2, l2, c2, v in rows:
            day_chg = (c2 - prev_close) / prev_close * 100 if prev_close else 0
            body    = c2 - o2
            k_tag   = "🟢" if body > 0 else ("🔴" if body < 0 else "⚪")
            chg_str = f"{day_chg:+5.2f}%" if prev_close else "  --  "
            print(f"  {d}  O${o2:>6.1f} H${h2:>6.1f} L${l2:>6.1f} C${c2:>6.1f} "
                  f"({chg_str}) Vol{v // 1000:>6,}k  {k_tag}")
            prev_close = c2
    finally:
        con.close()


def main() -> None:
    p = argparse.ArgumentParser(description="快速個股檢查")
    p.add_argument("tickers", nargs="+", help="股票代號 (可多個)")
    p.add_argument("--cost",   type=float, help="持倉均成本 (顯示 P&L)")
    p.add_argument("--shares", type=int,   help="持倉股數")
    p.add_argument("--stop",   type=float, help="停損價")
    p.add_argument("--days",   type=int, default=7, help="顯示近 N 日 K (預設 7)")
    args = p.parse_args()

    if len(args.tickers) > 1 and args.cost:
        print("⚠️ 多檔不支援 --cost、忽略")
        args.cost = None

    c = FubonClient()
    for tk in args.tickers:
        check_one(c, tk, args.cost, args.shares, args.stop, args.days)


if __name__ == "__main__":
    main()
