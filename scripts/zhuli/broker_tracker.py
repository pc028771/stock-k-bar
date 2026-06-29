#!/usr/bin/env python
"""老師重要分點每日買盤追蹤 — 用 FinMind SDK 券商層級查詢。

🔴 券商層級查詢只能走 FinMind SDK `taiwan_stock_trading_daily_report(securities_trader_id=...)`、
   raw HTTP /data endpoint 不支援 (要 data_id=股票、broker id 當 data_id 回 0 筆)。

用法: python scripts/zhuli/broker_tracker.py [YYYY-MM-DD]  (預設最近交易日)
輸出: 每個老師分點的 top 黑K個股淨買 (排 ETF、黑K=老師「站前哥買黑K隔天勝率高」訊號)
"""
import os
import sqlite3
import sys

sys.path.insert(0, "scripts")
from zhuli.db import MAIN_DB  # noqa: E402

# 老師講課/文章提過的重要分點 (reference_broker_aliases)
# nature: 短沖=見開高分批停利不抱波段 / 波段=收貨守均線抱 / 自營=性質介紹非訊號
TEACHER_BROKERS = {
    "920F": ("凱基站前 站前哥🥇", "🔴短沖→分批停利、別抱波段"),
    "984K": ("元大館前 館前哥🥈", "🟢波段收貨→守均線抱"),
    "982C": ("元大六合", "🟢波段收貨"),
    "962A": ("富邦南港", "🟢波段收貨"),
    "9A9q": ("永豐潮州 戰隊", "🟡戰隊"),
    "9A69": ("永豐屏東 戰隊", "🟡戰隊"),
    "7030": ("致和", "⚪自營/性質介紹非訊號"),
}


def _is_etf(tk: str) -> bool:
    return tk.startswith("00") or len(tk) >= 5


def run(date: str, min_lots: int = 80, topn: int = 8):
    from FinMind.data import DataLoader

    api = DataLoader()
    tok = os.environ.get("FINMIND_TOKEN")
    if tok:
        api.login_by_token(api_token=tok)
    c = sqlite3.connect(str(MAIN_DB))
    for bid, (name, nature) in TEACHER_BROKERS.items():
        try:
            df = api.taiwan_stock_trading_daily_report(securities_trader_id=bid, date=date)
        except Exception as e:
            print(f"[{name} {bid}] 查詢失敗: {e}")
            continue
        if df is None or not len(df):
            print(f"[{name} {bid}] {date} 無資料")
            continue
        df["net"] = df["buy"] - df["sell"]
        g = df.groupby("stock_id", as_index=False)["net"].sum()
        g["net"] = g["net"] / 1000
        g = g[~g["stock_id"].astype(str).apply(_is_etf)]  # 排 ETF
        top = g[g["net"] >= min_lots].nlargest(topn, "net")
        print(f"\n=== {name} ({bid}) {date} 淨買超個股 top{topn} (≥{min_lots}張、排ETF) ===")
        print(f"    性質: {nature}")
        if not len(top):
            print("  (無明顯個股買超)")
        for row in top.itertuples():
            tk = str(row.stock_id)
            k = c.execute(
                "SELECT open,close FROM standard_daily_bar WHERE ticker=? AND trade_date=?",
                (tk, date),
            ).fetchone()
            blk = bool(k and k[1] < k[0])
            col = "🖤黑K⭐" if blk else ("🔴紅K" if k else "?")
            chg = f"{(k[1]-k[0])/k[0]*100:+.1f}%" if k and k[0] else ""
            nm = c.execute("SELECT stock_name FROM stock_info WHERE ticker=? LIMIT 1", (tk,)).fetchone()
            print(f"  {tk} {(nm[0] if nm else ''):<8} 淨{row.net:>+7,.0f}張  {col} {chg}")
    c.close()


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else None
    if not d:
        cx = sqlite3.connect(str(MAIN_DB))
        d = cx.execute("SELECT MAX(trade_date) FROM standard_daily_bar").fetchone()[0]
        cx.close()
    run(d)
