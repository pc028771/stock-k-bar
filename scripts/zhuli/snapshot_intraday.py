"""一次性 intraday snapshot：印 HELD + WATCH (or 指定 ticker) 的即時 + 5K 軌跡。

User Office 沒 VPN 時、Claude 用此 script 自己抓資料、不必 user 餵數據。

用法:
  python3 scripts/zhuli/snapshot_intraday.py            # HELD only
  python3 scripts/zhuli/snapshot_intraday.py --all      # HELD + WATCH
  python3 scripts/zhuli/snapshot_intraday.py 2303 1605  # 指定 ticker
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "zhuli"))
sys.path.insert(0, "/Users/howard/Repository/stock-analysis-system")

from clients.fubon_client import FubonClient
import pandas as pd


def fmt_k_color(o: float, c: float) -> str:
    if c < o:
        return "🟢"
    if c > o:
        return "🔴"
    return "⚪"


def _load_held() -> list[dict]:
    from zhuli.positions import HELD
    return HELD


def _load_watch() -> list[dict]:
    from zhuli.positions import WATCH
    return WATCH


def snapshot_ticker(client: FubonClient, ticker: str, cost: float | None = None,
                     stop: float | None = None, name: str = "") -> None:
    snap = client.get_realtime_snapshot(ticker) or {}
    close = float(snap.get("close") or 0)
    open_ = float(snap.get("open") or 0)
    high = float(snap.get("high") or 0)
    low = float(snap.get("low") or 0)
    vol = snap.get("total_volume") or 0
    chg_pct = snap.get("change_rate") or 0

    print(f"\n=== {ticker} {name} ===")
    print(f"  即時: O={open_:.2f} H={high:.2f} L={low:.2f} C={close:.2f} V={vol:,}")
    print(f"  漲跌: {chg_pct:+.2f}%")
    if cost:
        pnl = (close - cost) / cost * 100 if cost else 0
        print(f"  Cost ${cost} → P&L {pnl:+.2f}%")
    if stop and close:
        gap = (close - stop) / stop * 100
        flag = "🚨" if close < stop else ("⚠️" if gap < 1 else "✅")
        print(f"  Stop ${stop} → 距 stop {gap:+.2f}% {flag}")

    # 5K data
    candles_dict = client.fetch_intraday_candles([ticker], timeframes=["5"])
    df = candles_dict.get(ticker, {}).get("5")
    if df is not None and not df.empty:
        print(f"\n  5K (最新 {min(8, len(df))} 根):")
        last_rows = df.tail(8)
        for _, r in last_rows.iterrows():
            dt = r["datetime"].strftime("%H:%M") if hasattr(r["datetime"], "strftime") else str(r["datetime"])[-8:-3]
            o, h, l, c, v = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]), int(r["volume"])
            body_pct = (c - o) / o * 100 if o else 0
            k = fmt_k_color(o, c)
            print(f"    {dt} O={o:.2f} H={h:.2f} L={l:.2f} C={c:.2f} V={v:,} {k} body{body_pct:+.2f}%")

        # 收盤位置
        last = last_rows.iloc[-1]
        last_pos = (float(last["close"]) - float(last["low"])) / (float(last["high"]) - float(last["low"])) if float(last["high"]) > float(last["low"]) else 0.5
        print(f"  最新 5K 收盤位置: {last_pos:.2f}")
    else:
        print(f"  ⚠️ 5K 資料抓不到")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("tickers", nargs="*", help="指定 ticker (空=用 HELD)")
    p.add_argument("--all", action="store_true", help="跑 HELD + WATCH")
    args = p.parse_args()

    print(f"=== Intraday Snapshot @ {datetime.now().strftime('%H:%M:%S')} ===")
    client = FubonClient()

    if args.tickers:
        targets = [(t, None, None, "") for t in args.tickers]
    elif args.all:
        held = _load_held()
        watch = _load_watch()
        targets = [(h["ticker"], h.get("cost"), h.get("stop"), h.get("name", ""))
                   for h in held]
        targets += [(w["ticker"], None, None, w.get("name", "")) for w in watch]
    else:
        held = _load_held()
        targets = [(h["ticker"], h.get("cost"), h.get("stop"), h.get("name", ""))
                   for h in held]

    for t, cost, stop, name in targets:
        try:
            snapshot_ticker(client, t, cost, stop, name)
        except Exception as e:
            print(f"\n=== {t} ===\n  ❌ {e}")


if __name__ == "__main__":
    main()
