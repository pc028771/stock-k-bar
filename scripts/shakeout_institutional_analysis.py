"""
Shakeout Strong — 券商分點行為分析
=====================================
問題：哪些特定券商分點，在 shakeout 訊號日反覆出現在淨買方？

分析框架：
  1. 對每筆 shakeout_strong 訊號，取當天各券商買賣超彙總
  2. 標記每個券商在該事件是否為淨買方（net_buy > 0）
  3. 跨事件統計：哪些券商出現在最多 shakeout 買方陣列？
  4. 輸出：出現次數排行 × 事件後 10d/20d 報酬

使用方法：
  python scripts/shakeout_institutional_analysis.py
"""
from __future__ import annotations

import sys, os, time
from pathlib import Path

import pandas as pd

SAS_PATH = Path(__file__).parent.parent.parent / "stock-analysis-system"
sys.path.insert(0, str(SAS_PATH.resolve()))

TOKEN = os.environ.get(
    "FINMIND_TOKEN",
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJkYXRlIjoiMjAyNi0wMy0yMyAxNDowMToyMCIsInVzZXJfaWQiOiJwYzAyODc3MSIsImVtYWlsIjoicGMwMjg3NzFAZ21haWwuY29tIiwiaXAiOiI2MC4yNTAuMzcuMTEyIn0.TevLwnL4uIon6qu-ARDTKvrxLpCyX5nmRTN0rhBUyMU",
)

from clients import finmind_client as fm

# ── 參數 ─────────────────────────────────────────────────────────────────
SIGNAL_CSV    = Path("data/analysis/kline_course_backtest/breakout_daily_scanner.csv")
BROKER_CACHE  = Path("/tmp/shakeout_broker_cache")
TOP_N         = 20
MIN_EVENTS    = 3    # 出現幾次以上才列入排行


# ── 資料載入 ──────────────────────────────────────────────────────────────
def load_signals() -> pd.DataFrame:
    df = pd.read_csv(SIGNAL_CSV)
    shakeout = df[df["shakeout_strong"] == True].copy()
    shakeout["ticker"] = shakeout["ticker"].astype(str)
    return shakeout.reset_index(drop=True)


# ── 券商資料（含 cache）────────────────────────────────────────────────────
def fetch_broker(ticker: str, date: str) -> pd.DataFrame:
    """取得彙總後的券商淨買超，有 cache 則直接讀。"""
    BROKER_CACHE.mkdir(exist_ok=True)
    cache_path = BROKER_CACHE / f"{ticker}_{date}.csv"
    if cache_path.exists():
        return pd.read_csv(cache_path)

    df = fm.get_stock_broker_daily(ticker, date, TOKEN)
    if not df.empty:
        df.to_csv(cache_path, index=False)
    return df


# ── 主程式 ────────────────────────────────────────────────────────────────
def main() -> None:
    print("=== Shakeout 券商分點行為分析 ===\n")

    print("1. 載入訊號...")
    signals = load_signals()
    print(f"   共 {len(signals)} 筆 shakeout_strong 訊號\n")

    print("2. 抓取各訊號日券商資料（有 cache 則跳過）...")
    all_records: list[dict] = []
    total = len(signals)

    for i, row in signals.iterrows():
        ticker = row["ticker"]
        date   = str(row["trade_date"])
        if (i + 1) % 20 == 0 or (i + 1) == total:
            print(f"  [{i+1}/{total}] {ticker} {date}")

        brokers = fetch_broker(ticker, date)
        if brokers.empty:
            continue

        buyers = brokers[brokers["net_buy"] > 0]
        for _, b in buyers.iterrows():
            all_records.append({
                "ticker":                ticker,
                "trade_date":            date,
                "breakout_strength_pct": row.get("breakout_strength_pct"),
                "ret_10d_net":           row.get("ret_10d_net"),
                "ret_20d_net":           row.get("ret_20d_net"),
                "securities_trader_id":  b["securities_trader_id"],
                "securities_trader":     b["securities_trader"],
                "net_buy":               b["net_buy"],
            })

        time.sleep(0.2)

    if not all_records:
        print("無券商資料，請確認 FinMind 帳號為 Sponsor tier 且 Token 正確。")
        return

    df = pd.DataFrame(all_records)
    print(f"\n   取得 {len(df)} 筆買方記錄，涵蓋 {df['ticker'].nunique()} 檔個股")

    # ── 統計：哪些券商出現最多 ──────────────────────────────────────────
    print("\n" + "="*60)
    print(f"\n3. 券商出現次數排行（淨買方，至少 {MIN_EVENTS} 次）\n")

    stats = (
        df.groupby(["securities_trader_id", "securities_trader"])
        .agg(
            events        = ("ticker", "count"),
            avg_net_buy   = ("net_buy", "mean"),
            avg_ret_10d   = ("ret_10d_net", "mean"),
            win_rate_10d  = ("ret_10d_net", lambda x: (x.dropna() > 0).mean()
                             if x.notna().any() else float("nan")),
        )
        .reset_index()
        .query(f"events >= {MIN_EVENTS}")
        .sort_values("events", ascending=False)
        .head(TOP_N)
    )

    stats["avg_net_buy"]  = stats["avg_net_buy"].map(lambda x: f"{x:.0f} 張")
    stats["avg_ret_10d"]  = stats["avg_ret_10d"].map(
        lambda x: f"{x*100:.1f}%" if pd.notna(x) else "N/A")
    stats["win_rate_10d"] = stats["win_rate_10d"].map(
        lambda x: f"{x*100:.0f}%" if pd.notna(x) else "N/A")

    print(stats.rename(columns={
        "securities_trader_id": "券商代碼",
        "securities_trader":    "券商名稱",
        "events":               "出現次數",
        "avg_net_buy":          "平均淨買",
        "avg_ret_10d":          "事件均報(10d)",
        "win_rate_10d":         "事件勝率(10d)",
    }).to_string(index=False))

    # ── 子集：高強度訊號 ──────────────────────────────────────────────────
    strong = df[df["breakout_strength_pct"] >= 9]
    if len(strong) >= 10:
        print("\n" + "="*60)
        print("\n4. 高強度訊號（strength ≥ 9%）\n")
        strong_stats = (
            strong.groupby(["securities_trader_id", "securities_trader"])
            .agg(events=("ticker", "count"), avg_net_buy=("net_buy", "mean"))
            .reset_index()
            .query("events >= 2")
            .sort_values("events", ascending=False)
            .head(10)
        )
        strong_stats["avg_net_buy"] = strong_stats["avg_net_buy"].map(lambda x: f"{x:.0f} 張")
        print(strong_stats.rename(columns={
            "securities_trader_id": "券商代碼",
            "securities_trader":    "券商名稱",
            "events":               "出現次數",
            "avg_net_buy":          "平均淨買",
        }).to_string(index=False))

    print("\n完成。")


if __name__ == "__main__":
    os.chdir(Path(__file__).parent.parent)
    main()
