"""2303 聯電盤中即時監控 — shakeout 框架關鍵 level 檢核.

執行: python scripts/watch_2303.py [--loop SECS]

依 K線力量 5 停損 + shakeout 結構 + 5/20 法人對作背景，逐 level 檢核.

⚠️ CLAUDE.md 紅線:
  - 不指定進場/出場價、倉位
  - 收盤確認原則：盤中震盪僅預警
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, "/Users/howard/Repository/stock-analysis-system")
from common.finmind_client import get_client

TICKER = "2303"
NAME = "聯電"
PREV_CLOSE = 108.00
PREV_VOL = 227_934_000  # 5/20 收盤量（股）

# 關鍵 level (descending)
LEVELS = [
    (120.50, "5/19 high — 突破 = 動能延續但 ch2 警示敏感"),
    (115.50, "5/20 high — 上影警示來源"),
    (110.00, "ma5 — 5/20 已跌破，站回 = 短期回穩"),
    (108.00, "平盤線 / 5/20 收"),
    (107.00, "5/20 low — 跌破 = 連 3 天低點下降"),
    (105.70, "ma10 — 短期重要支撐"),
    (104.50, "★ 5/12 shakeout 進場 K 高 — 結構底線（收盤跌破 = ① 5 停損）"),
    ( 94.50, "5/13 深防線"),
    ( 90.89, "ma20 — 中期"),
]


def fetch_intraday() -> dict | None:
    """嘗試 Fubon → FinMind 1 分 K fallback.

    Fubon 盤前會回 close (試撮) 但 OHL=0，這時降級為 pre-market quote.
    """
    # 1. Fubon snapshot
    try:
        from clients.fubon_client import FubonClient
        c = FubonClient()
        snap = c.get_realtime_snapshot(TICKER)
        if snap and snap.get("close"):
            # 盤前: open=0 表示尚未開盤，僅有試撮 close
            if not snap.get("open"):
                return {
                    "src": "Fubon 試撮（盤前）",
                    "premarket": True,
                    "close": snap["close"],
                    "change_pct": snap.get("change_rate", 0),
                }
            return {"src": "Fubon", **snap}
    except Exception:
        pass

    # 2. FinMind 1 分 K
    try:
        today = date.today().isoformat()
        df = get_client().fetch_dataset(
            dataset="TaiwanStockKBar",
            data_id=TICKER,
            start_date=today,
            end_date=today,
            bypass_cache=True,
        )
        if df.empty:
            return None
        return {
            "src": f"FinMind 1m K (×{len(df)} bars, last {df['minute'].iloc[-1]})",
            "open": float(df["open"].iloc[0]),
            "high": float(df["high"].max()),
            "low":  float(df["low"].min()),
            "close": float(df["close"].iloc[-1]),
            "volume": int(df["volume"].sum()),
        }
    except Exception as exc:
        return {"err": str(exc)}


def render(snap: dict | None):
    print(f"\n{'='*70}")
    print(f"  2303 {NAME}  即時監控  {datetime.now():%H:%M:%S}")
    print(f"{'='*70}")
    if not snap:
        print("  ⏸ 盤前尚未開盤（FinMind / Fubon 都無資料）")
        print(f"  昨收 {PREV_CLOSE:.2f}")
        return
    if "err" in snap:
        print(f"  ⚠ {snap['err']}")
        return
    if snap.get("premarket"):
        c = snap["close"]
        d1 = snap.get("change_pct", 0)
        arrow = "🟢" if d1 > 1 else ("🔴" if d1 < -1 else "─")
        print(f"  [{snap['src']}]")
        print(f"  試撮 {c:.2f} {arrow} ({d1:+.2f}% vs 昨收 {PREV_CLOSE:.2f})")
        print(f"  ⏰ 開盤前無 OHL，僅 reference quote\n")
        print(f"  Level 對照 (試撮 {c:.2f}):")
        for lv, desc in LEVELS:
            mark = "✓ 在上" if c >= lv else "✗ 已破"
            print(f"    {lv:>7.2f}  [{mark}]  {desc}")
        return
    o, h, l, c = snap["open"], snap["high"], snap["low"], snap["close"]
    vol = snap.get("volume", 0)
    d1 = (c / PREV_CLOSE - 1) * 100
    upper = (h - max(o, c)) / c * 100
    body = (c - o) / o * 100
    arrow = "🟢" if d1 > 1 else ("🔴" if d1 < -1 else "─")

    print(f"  [{snap['src']}]")
    print(f"  即時 {c:.2f} {arrow} ({d1:+.2f}% vs 昨收 {PREV_CLOSE:.2f})")
    print(f"  OHL: O{o:.2f}  H{h:.2f}  L{l:.2f}  body{body:+.1f}%  上影{upper:.1f}%")
    print(f"  量: {vol:,} 股")

    print(f"\n  Level 檢核 (即時 {c:.2f}):")
    for lv, desc in LEVELS:
        if c >= lv:
            mark = "✓ 在上"
        else:
            mark = "✗ 已破"
        print(f"    {lv:>7.2f}  [{mark}]  {desc}")

    # Ch2 警示
    print(f"\n  ⚠️ Ch2 盤中警示:")
    triggered = []
    if upper > 5:
        triggered.append(f"上影 {upper:.1f}% (>5% Ch2-1 賣壓)")
    if body < -3 and vol > PREV_VOL * 1.3 if vol else False:
        triggered.append(f"大量黑K body {body:+.1f}% (Ch2-4 出場訊號)")
    if c < 107:
        triggered.append("收 < 5/20 low 107 → 連 3 天低點下降 (5 停損 ③)")
    if c < 104.50:
        triggered.append("★ 收 < shakeout 進場 K 高 104.50 → 結構性破壞 (5 停損 ①)")
    if not triggered:
        print(f"    ─ 暫無警示")
    else:
        for t in triggered:
            print(f"    🚨 {t}")
    print(f"\n  紅線：以收盤確認為準（13:30 後）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, default=0, help="loop 每 N 秒重抓，預設 0 (single shot)")
    args = ap.parse_args()
    while True:
        snap = fetch_intraday()
        render(snap)
        if args.loop <= 0:
            break
        time.sleep(args.loop)


if __name__ == "__main__":
    main()
