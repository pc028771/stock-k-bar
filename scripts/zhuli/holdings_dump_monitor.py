"""持倉拉高出貨即時監控（Fubon WebSocket）.

監控所有持倉，偵測「拉高出貨」訊號並即時警示：
  1. 開盤跳空 +3% 拉低到 0% 以下 (主力倒貨)
  2. 上影 5%+ 且量爆 (高檔出貨)
  3. 跌破停損位 (持倉守則破)
  4. 12 點殺盤未恢復
  5. 距 MA10 過高 (拉高警示)

Usage:
    python scripts/zhuli/holdings_dump_monitor.py
    python scripts/zhuli/holdings_dump_monitor.py --mock  # 不連 WS、用 standard_daily_bar 模擬今日 close
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich import box

_REPO = Path(__file__).parent.parent.parent
_SYS = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_SYS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

DB = Path.home() / ".four_seasons" / "data.sqlite"
HOLDINGS = _REPO / "docs" / "主力大課程" / "holdings.json"


def load_holdings() -> dict:
    """讀 holdings.json，回傳 {ticker: {name, cost, shares, stop_loss}}."""
    data = json.loads(HOLDINGS.read_text())
    out = {}
    for t, d in data.get("holdings", {}).items():
        out[t] = {
            "name": d["name"],
            "cost": d["cost"],
            "shares": d["shares"],
            "stop_loss": d.get("stop_loss"),
        }
    return out


def load_yesterday_close_and_ma(tickers: list[str]) -> dict:
    """從 DB 取每檔最近收盤、MA5/MA10、5/27 高低."""
    conn = sqlite3.connect(DB)
    result = {}
    for t in tickers:
        rows = conn.execute(
            "SELECT trade_date, open, high, low, close FROM standard_daily_bar "
            "WHERE ticker=? ORDER BY trade_date DESC LIMIT 10",
            (t,),
        ).fetchall()
        if not rows:
            continue
        closes = [r[4] for r in rows]
        result[t] = {
            "yesterday_date": rows[0][0],
            "yesterday_close": closes[0],
            "yesterday_high": rows[0][2],
            "yesterday_low": rows[0][3],
            "ma5": sum(closes[:5]) / 5,
            "ma10": sum(closes[:10]) / 10,
        }
    conn.close()
    return result


class DumpMonitor:
    """每檔即時狀態 + 出貨訊號評估."""

    def __init__(self, holdings: dict, baseline: dict):
        self.holdings = holdings
        self.baseline = baseline  # {ticker: {yesterday_close, ma10, ...}}
        # 即時狀態
        self.state: dict[str, dict] = {}
        for t in holdings:
            self.state[t] = {
                "open": None, "high": None, "low": None, "close": None,
                "volume": 0, "last_price": None, "last_update": None,
            }

    def update_tick(self, ticker: str, price: float, volume: int = 0):
        s = self.state.get(ticker)
        if s is None:
            return
        if s["open"] is None:
            s["open"] = price
        s["high"] = max(s["high"] or price, price)
        s["low"] = min(s["low"] or price, price)
        s["close"] = price
        s["last_price"] = price
        s["volume"] += volume
        s["last_update"] = datetime.now().strftime("%H:%M:%S")

    def signals(self, ticker: str) -> list[str]:
        """評估該檔當前出貨訊號、回傳警示 list."""
        s = self.state[ticker]
        b = self.baseline.get(ticker, {})
        h = self.holdings[ticker]
        warnings = []

        cur = s["close"]
        if cur is None:
            return ["⚪ 無報價"]

        yc = b.get("yesterday_close", 0)
        ma10 = b.get("ma10", 0)
        op = s["open"]
        hi = s["high"]
        lo = s["low"]
        stop = h.get("stop_loss")

        # 1. 跌破停損
        if stop and isinstance(stop, (int, float)) and cur < stop:
            warnings.append(f"🚨 跌破停損 ${stop}")

        # 2. 開盤跳空 +3% 拉低 0% 以下
        if op and yc:
            gap_pct = (op - yc) / yc * 100
            cur_vs_yc = (cur - yc) / yc * 100
            if gap_pct >= 3 and cur_vs_yc <= 0:
                warnings.append(f"🚨 跳空 +{gap_pct:.1f}% 拉回 {cur_vs_yc:+.1f}% (主力倒貨)")
            elif gap_pct >= 5:
                warnings.append(f"⚠️ 跳空 +{gap_pct:.1f}% (注意拉回)")

        # 3. 上影 5%+ 量爆 (近似：高 vs 現價差距)
        if op and hi:
            upper_shadow_pct = (hi - cur) / op * 100
            if upper_shadow_pct >= 5:
                warnings.append(f"⚠️ 上影 {upper_shadow_pct:.1f}% (高檔出貨)")

        # 4. 跌破 MA10
        if ma10 and cur < ma10:
            warnings.append(f"⚠️ 現價 < MA10 ${ma10:.2f}")

        # 5. 12 點殺盤未恢復
        now = datetime.now()
        if now.hour == 12 and now.minute >= 30:
            if lo and op:
                dip = (op - lo) / op * 100
                recovery = (cur - lo) / lo * 100 if lo > 0 else 0
                if dip >= 1.5 and recovery < 0.5:
                    warnings.append(f"⚠️ 12 點殺 {dip:.1f}% 未恢復")

        if not warnings:
            warnings.append("🟢 正常")

        return warnings

    def render_table(self) -> Table:
        t = Table(box=box.ROUNDED, title=f"持倉拉高出貨監控 [{datetime.now().strftime('%H:%M:%S')}]")
        t.add_column("Ticker", style="cyan")
        t.add_column("名稱")
        t.add_column("成本", justify="right")
        t.add_column("現價", justify="right")
        t.add_column("損益%", justify="right")
        t.add_column("距開盤", justify="right")
        t.add_column("距MA10", justify="right")
        t.add_column("日內H/L", justify="right")
        t.add_column("警示", style="bold")

        for ticker, h in self.holdings.items():
            s = self.state[ticker]
            b = self.baseline.get(ticker, {})
            cur = s["close"]
            if cur is None:
                cur_str = "—"
                pnl = "—"
                dist_open = "—"
                dist_ma10 = "—"
                hl = "—"
            else:
                cur_str = f"${cur:.2f}"
                pnl = f"{(cur - h['cost']) / h['cost'] * 100:+.1f}%"
                dist_open = f"{(cur - s['open']) / s['open'] * 100:+.1f}%" if s['open'] else "—"
                ma10 = b.get("ma10", 0)
                dist_ma10 = f"{(cur - ma10) / ma10 * 100:+.1f}%" if ma10 else "—"
                hl = f"{s['high']:.2f}/{s['low']:.2f}" if s['high'] else "—"

            warnings = self.signals(ticker)
            warn_str = " | ".join(warnings[:2])  # 最多顯示 2 個
            warn_style = "red" if any("🚨" in w for w in warnings) else "yellow" if any("⚠️" in w for w in warnings) else "green"

            t.add_row(
                ticker, h["name"], f"${h['cost']:.2f}", cur_str, pnl,
                dist_open, dist_ma10, hl,
                f"[{warn_style}]{warn_str}[/{warn_style}]",
            )
        return t


def run_live(monitor: DumpMonitor):
    """連 Fubon WS、即時更新."""
    from clients.fubon_client import FubonClient
    client = FubonClient()

    def on_message(message: str):
        try:
            msg = json.loads(message) if isinstance(message, str) else message
            data = msg.get("data", msg)
            ticker = data.get("symbol") or data.get("code")
            price = data.get("price") or data.get("close") or data.get("last")
            vol = data.get("volume", 0) or 0
            if ticker and price:
                monitor.update_tick(str(ticker), float(price), int(vol))
        except Exception as e:
            pass  # silent ignore parse errors

    tickers = list(monitor.holdings.keys())
    print(f"連 Fubon WebSocket、subscribe {len(tickers)} 檔...")
    ws = client.subscribe_quotes(tickers, on_message, channel="aggregates")
    if ws is None:
        print("❌ WS 連線失敗")
        return

    console = Console()
    try:
        with Live(monitor.render_table(), refresh_per_second=2, console=console) as live:
            while True:
                time.sleep(0.5)
                live.update(monitor.render_table())
    except KeyboardInterrupt:
        print("\n停止監控")
        if hasattr(ws, "disconnect"):
            ws.disconnect()


def run_mock(monitor: DumpMonitor, date: str):
    """Mock 模式：用 DB 5/28 today's bar 模擬即時 tick (假日測試)."""
    conn = sqlite3.connect(DB)
    today_bars = {}
    for t in monitor.holdings:
        r = conn.execute(
            "SELECT open, high, low, close, volume FROM standard_daily_bar "
            "WHERE ticker=? AND trade_date=?", (t, date),
        ).fetchone()
        if r:
            today_bars[t] = r
    conn.close()

    # 假裝 tick by tick: open → high/low → close (4 個 tick 模擬)
    for ticker, bar in today_bars.items():
        op, hi, lo, cl, vol = bar
        monitor.update_tick(ticker, op, 0)
        monitor.update_tick(ticker, hi, vol // 4)
        monitor.update_tick(ticker, lo, vol // 4)
        monitor.update_tick(ticker, cl, vol // 2)

    console = Console()
    console.print(monitor.render_table())
    console.print(f"\n[dim]Mock 模式、用 {date} 收盤資料模擬[/dim]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="Mock 模式（不連 WS）")
    ap.add_argument("--date", default=None, help="Mock 用的日期 (default: 昨天)")
    args = ap.parse_args()

    holdings = load_holdings()
    tickers = list(holdings.keys())
    baseline = load_yesterday_close_and_ma(tickers)
    monitor = DumpMonitor(holdings, baseline)

    print(f"監控 {len(tickers)} 檔持倉: {', '.join(tickers)}")
    print(f"Baseline: 取自 {baseline[tickers[0]]['yesterday_date']}")
    print()

    if args.mock:
        date = args.date or baseline[tickers[0]]["yesterday_date"]
        run_mock(monitor, date)
    else:
        run_live(monitor)


if __name__ == "__main__":
    main()
