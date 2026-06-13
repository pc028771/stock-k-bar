"""鍵盤瀏覽 candidate K 線圖.

用法:
    python scripts/zhuli/chart_viewer.py --tickers 1560,4958,3189,3037,4722,8046,4749
    python scripts/zhuli/chart_viewer.py --from-flag 2026-05-29   # 從 daily_scanner_job 結果讀

操作:
    ← / →     上一檔 / 下一檔
    j / k     同上 (vim-style)
    h / l     同上
    space     下一檔
    q / Esc   離開
    s         儲存當前圖到 /tmp/charts/
    w         開 wantgoo 連結 (default browser)
"""
from __future__ import annotations

from zhuli.db import get_conn, MAIN_DB

import argparse
import sys
import webbrowser
from pathlib import Path

import matplotlib
matplotlib.use("MacOSX")  # 或 'TkAgg' 跨平台
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import mplfinance as mpf
import pandas as pd

# 中文字型
plt.rcParams["font.family"] = ["Heiti TC", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

DB_PATH = MAIN_DB
def load_bars(ticker: str, start: str = "2026-04-01", end: str = "2026-05-29") -> pd.DataFrame:
    con = get_conn(DB_PATH)
    rows = con.execute(
        """SELECT trade_date, open, high, low, close, volume, ma5, ma10, ma20, ma60
           FROM standard_daily_bar
           WHERE ticker=? AND trade_date BETWEEN ? AND ?
           ORDER BY trade_date""",
        (ticker, start, end),
    ).fetchall()
    con.close()
    df = pd.DataFrame(
        rows, columns=["date", "Open", "High", "Low", "Close", "Volume", "ma5", "ma10", "ma20", "ma60"]
    )
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)
    return df


def load_stock_name(ticker: str) -> str:
    con = get_conn(DB_PATH)
    r = con.execute(
        "SELECT industry FROM standard_daily_bar WHERE ticker=? ORDER BY trade_date DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    con.close()
    return r[0] if r else ""


class ChartViewer:
    def __init__(self, items: list[dict]):
        self.items = items
        self.idx = 0
        self.fig, (self.ax_price, self.ax_vol) = plt.subplots(
            2, 1, figsize=(12, 7), gridspec_kw={"height_ratios": [3, 1]}, sharex=True
        )
        self.fig.canvas.mpl_connect("key_press_event", self.on_key)
        self.fig.canvas.manager.set_window_title("K-bar Viewer (← → 切換, q 離開)")
        self.render()

    def render(self):
        self.ax_price.clear()
        self.ax_vol.clear()
        item = self.items[self.idx]
        df = load_bars(item["ticker"])
        if df.empty:
            self.ax_price.text(0.5, 0.5, f"無資料: {item['ticker']}", ha="center", va="center")
            self.fig.canvas.draw_idle()
            return

        # K 棒 (蠟燭)
        ups = df[df["Close"] >= df["Open"]]
        dns = df[df["Close"] < df["Open"]]
        width, width_th = 0.6, 0.1
        # 上影 / 下影
        self.ax_price.vlines(ups.index, ups["Low"], ups["High"], color="red", linewidth=1)
        self.ax_price.vlines(dns.index, dns["Low"], dns["High"], color="green", linewidth=1)
        # 實體
        self.ax_price.bar(ups.index, ups["Close"] - ups["Open"], width, bottom=ups["Open"], color="red")
        self.ax_price.bar(dns.index, dns["Open"] - dns["Close"], width, bottom=dns["Close"], color="green")

        # MA 線
        self.ax_price.plot(df.index, df["ma5"], color="red", linewidth=1.2, label="MA5")
        self.ax_price.plot(df.index, df["ma10"], color="orange", linewidth=1.2, label="MA10")
        self.ax_price.plot(df.index, df["ma20"], color="green", linewidth=1.2, label="MA20")
        self.ax_price.plot(df.index, df["ma60"], color="blue", linewidth=1.0, alpha=0.6, label="MA60")
        self.ax_price.legend(loc="upper left", fontsize=9)

        # 量
        self.ax_vol.bar(ups.index, ups["Volume"], width, color="red", alpha=0.6)
        self.ax_vol.bar(dns.index, dns["Volume"], width, color="green", alpha=0.6)
        self.ax_vol.set_ylabel("Vol")

        # title
        title = f"{item['ticker']} {item.get('name', '')} — {item.get('label', '')}  ({self.idx+1}/{len(self.items)})"
        self.ax_price.set_title(title, fontsize=13)
        self.ax_price.grid(True, alpha=0.3)
        self.ax_vol.grid(True, alpha=0.3)
        self.ax_price.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        self.ax_price.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
        plt.setp(self.ax_vol.xaxis.get_majorticklabels(), rotation=45, ha="right")

        # 副資訊
        last = df.iloc[-1]
        info = (
            f"5/29 close ${last['Close']:.2f}  "
            f"MA5={last['ma5']:.1f}  MA10={last['ma10']:.1f}  MA20={last['ma20']:.1f}\n"
            f"距 MA10: {(last['Close']/last['ma10']-1)*100:+.1f}%   "
            f"操作: ← → 切換, q 離開, w 開 wantgoo, s 存圖"
        )
        self.fig.text(0.5, 0.02, info, ha="center", fontsize=10, color="#333")

        self.fig.tight_layout(rect=[0, 0.05, 1, 1])
        self.fig.canvas.draw_idle()

    def on_key(self, event):
        if event.key in ("right", "l", " ", "j"):
            self.idx = (self.idx + 1) % len(self.items)
            self.render()
        elif event.key in ("left", "h", "k"):
            self.idx = (self.idx - 1) % len(self.items)
            self.render()
        elif event.key in ("q", "escape"):
            plt.close(self.fig)
        elif event.key == "w":
            url = f"https://www.wantgoo.com/stock/{self.items[self.idx]['ticker']}/technical-chart"
            webbrowser.open(url)
        elif event.key == "s":
            out_dir = Path("/tmp/charts")
            out_dir.mkdir(exist_ok=True)
            item = self.items[self.idx]
            fname = out_dir / f"{item['ticker']}_{item.get('name','')}.png"
            self.fig.savefig(fname, dpi=120, bbox_inches="tight")
            print(f"saved → {fname}")


DEFAULT_8 = [
    {"ticker": "1560", "name": "中砂", "label": "短週期攻擊+微整理"},
    {"ticker": "4958", "name": "臻鼎-KY", "label": "短週期攻擊+微整理"},
    {"ticker": "3189", "name": "景碩", "label": "長週期整理+突破尾巴"},
    {"ticker": "3037", "name": "欣興", "label": "長週期整理+突破尾巴"},
    {"ticker": "4722", "name": "國精化", "label": "N字回測中"},
    {"ticker": "8046", "name": "南電", "label": "突破失敗/W底"},
    {"ticker": "4749", "name": "新應材", "label": "突破失敗/W底"},
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", type=str, help="逗號分隔 ticker (e.g. 1560,4958)")
    p.add_argument("--demo", action="store_true", help="用 8 個 ground truth case")
    args = p.parse_args()

    if args.demo or not args.tickers:
        items = DEFAULT_8
    else:
        items = [{"ticker": t.strip(), "name": "", "label": ""} for t in args.tickers.split(",")]

    ChartViewer(items)
    plt.show()


if __name__ == "__main__":
    main()
