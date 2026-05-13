"""
Shakeout Strong 兩種進場策略比較
A. 開盤進場：進場日開盤價買入（需盯盤確認開低）
B. 收盤確認進場：進場日收盤前5分鐘確認 close >= open 才買（不用盯盤）

用法：python scripts/shakeout_intraday_analysis.py
"""
from __future__ import annotations

import sys
import os
import time
import requests
from pathlib import Path
from datetime import date, timedelta

import pandas as pd

# ── 路徑設定 ─────────────────────────────────────────────────────────────
SAS_PATH = Path(__file__).parent.parent.parent / "stock-analysis-system"
sys.path.insert(0, str(SAS_PATH.resolve()))

TOKEN = os.environ.get(
    "FINMIND_TOKEN",
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJkYXRlIjoiMjAyNi0wMy0yMyAxNDowMToyMCIsInVzZXJfaWQiOiJwYzAyODc3MSIsImVtYWlsIjoicGMwMjg3NzFAZ21haWwuY29tIiwiaXAiOiI2MC4yNTAuMzcuMTEyIn0.TevLwnL4uIon6qu-ARDTKvrxLpCyX5nmRTN0rhBUyMU",
)
API_URL    = "https://api.finmindtrade.com/api/v4/data"
CACHE_DIR  = Path.home() / ".four_seasons" / "finmind_kbar_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

from clients import finmind_client as fm

# ── 設定 ──────────────────────────────────────────────────────────────────
SIGNAL_CSV = Path("data/analysis/kline_course_backtest/archive/breakout_daily_scanner/2026-05-12/breakout_daily_scanner.csv")

PERIODS = {
    "近期（5/4~5/12）":    ("2026-05-04", "2026-05-12"),
    "大跌後（4/7~4/21）": ("2026-04-07", "2026-04-21"),
}

CLOSE_CONFIRM_TIME = "13:25"   # 收盤前幾分鐘確認
SLEEP_SEC          = 1.5       # FinMind 分K API 請求間隔


# ── 分K取法 ───────────────────────────────────────────────────────────────
def fetch_kbar(ticker: str, trade_date: str) -> pd.DataFrame:
    """用 FinMind TaiwanStockKBar 取單日 1 分K，有 cache。"""
    cache_path = CACHE_DIR / f"{ticker}_{trade_date}.csv"
    if cache_path.exists():
        df = pd.read_csv(cache_path)
        if not df.empty:
            return df
        cache_path.unlink(missing_ok=True)

    resp = requests.get(
        API_URL,
        params={"dataset": "TaiwanStockKBar", "data_id": ticker,
                "start_date": trade_date, "end_date": trade_date},
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=30,
    )
    payload = resp.json()
    if payload.get("status") != 200:
        return pd.DataFrame()
    df = pd.DataFrame(payload.get("data") or [])
    if not df.empty:
        df.to_csv(cache_path, index=False)
    time.sleep(SLEEP_SEC)
    return df


def parse_kbar(df: pd.DataFrame) -> pd.DataFrame:
    """統一欄位：dt(datetime), open, high, low, close, volume"""
    if df.empty:
        return df
    df = df.copy()
    # FinMind 格式：date="2026-05-07", minute="09:01"
    if "minute" in df.columns:
        df["dt"] = pd.to_datetime(df["date"].astype(str) + " " + df["minute"].astype(str))
    elif "Time" in df.columns:
        df["dt"] = pd.to_datetime(df["date"].astype(str) + " " + df["Time"].astype(str))
    else:
        return pd.DataFrame()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df.get(col, 0), errors="coerce")
    return df.sort_values("dt").reset_index(drop=True)


def get_price_at(kbar: pd.DataFrame, time_str: str) -> float | None:
    """取某時間點（含）前最後一根的 close。"""
    mask = kbar["dt"].dt.strftime("%H:%M") <= time_str
    sub  = kbar[mask]
    return float(sub.iloc[-1]["close"]) if not sub.empty else None


def next_trading_date(d: date) -> date:
    nd = d + timedelta(days=1)
    while nd.weekday() >= 5:
        nd += timedelta(days=1)
    return nd


# ── 主流程 ────────────────────────────────────────────────────────────────
def run():
    sig = pd.read_csv(SIGNAL_CSV)
    sig = sig[sig["shakeout_strong"] == True].copy()
    sig["trade_date"] = pd.to_datetime(sig["trade_date"])

    rows = []

    for period_name, (start, end) in PERIODS.items():
        period_sig = sig[
            (sig["trade_date"] >= start) & (sig["trade_date"] <= end)
        ].copy()

        print(f"\n{'='*65}")
        print(f"  {period_name}  ({len(period_sig)} 筆訊號)")
        print(f"{'='*65}")
        print(f"  {'代號':6} {'訊號日':12} {'前收':>7} {'開盤':>7} "
              f"{'gap':>6} {'13:25價':>8} {'收盤守?':>7} "
              f"{'A開盤報':>8} {'B收盤報':>8}")
        print(f"  {'-'*65}")

        for _, row in period_sig.iterrows():
            ticker      = str(row["ticker"])
            signal_date = row["trade_date"].strftime("%Y-%m-%d")
            entry_dt    = next_trading_date(row["trade_date"].date())
            entry_date  = entry_dt.strftime("%Y-%m-%d")

            # 前收（訊號日收盤）
            price_df = fm.get_price(ticker, signal_date, signal_date, TOKEN)
            if price_df.empty:
                continue
            prev_close = float(price_df["close"].iloc[-1])

            # 進場日日K
            entry_price_df = fm.get_price(ticker, entry_date, entry_date, TOKEN)
            if entry_price_df.empty:
                continue
            day_open  = float(entry_price_df["open"].iloc[-1])
            day_close = float(entry_price_df["close"].iloc[-1])
            day_high  = float(entry_price_df["high"].iloc[-1])
            day_low   = float(entry_price_df["low"].iloc[-1])

            gap_pct = (day_open - prev_close) / prev_close * 100
            if day_open >= prev_close:          # 未開低，策略本就不進
                continue

            # 取分K確認 13:25 價格
            kbar_raw  = fetch_kbar(ticker, entry_date)
            kbar      = parse_kbar(kbar_raw)
            price_1325 = get_price_at(kbar, CLOSE_CONFIRM_TIME) if not kbar.empty else None

            # 若無分K，用日K收盤近似
            if price_1325 is None:
                price_1325 = day_close

            held = price_1325 >= day_open   # 13:25 仍守住開盤 → 策略B進場

            # 隔日收盤（計算報酬基準）
            next_dt   = next_trading_date(entry_dt)
            next_date = next_dt.strftime("%Y-%m-%d")
            next_df   = fm.get_price(ticker, next_date, next_date, TOKEN)
            next_close = float(next_df["close"].iloc[-1]) if not next_df.empty else None

            # 報酬
            ret_A = (day_close - day_open)  / day_open  * 100          # 開盤進，當日收出
            ret_B = ((next_close - price_1325) / price_1325 * 100
                     if held and next_close else None)                   # 收盤前進，次日收出

            held_str = "✅" if held else "❌"
            ret_b_str = f"{ret_B:+.1f}%" if ret_B is not None else "─不進"
            print(f"  {ticker:6} {signal_date:12} {prev_close:>7.2f} {day_open:>7.2f} "
                  f"{gap_pct:>+5.1f}% {price_1325:>8.2f} {held_str:>7} "
                  f"{ret_A:>+7.1f}% {ret_b_str:>8}")

            rows.append({
                "period": period_name, "ticker": ticker,
                "signal_date": signal_date, "entry_date": entry_date,
                "prev_close": prev_close, "day_open": day_open,
                "gap_pct": round(gap_pct, 2),
                "price_1325": price_1325, "held": held,
                "day_close": day_close,
                "next_close": next_close,
                "ret_A_open_to_dayclose": round(ret_A, 2),
                "ret_B_1325_to_nextclose": round(ret_B, 2) if ret_B else None,
            })

    # ── 彙整 ──────────────────────────────────────────────────────────────
    if not rows:
        return
    df_r = pd.DataFrame(rows)

    print(f"\n\n{'='*65}")
    print("  彙整比較：開盤進 vs 收盤確認進")
    print(f"{'='*65}")

    for period in df_r["period"].unique():
        sub = df_r[df_r["period"] == period]
        a_all  = sub["ret_A_open_to_dayclose"]
        b_held = sub[sub["held"]]["ret_B_1325_to_nextclose"].dropna()
        b_skip = (~sub["held"]).sum()

        print(f"\n  【{period}】")
        print(f"  策略A（開盤進，當日收出）：n={len(a_all)}  "
              f"均報{a_all.mean():+.1f}%  勝率{(a_all>0).mean()*100:.0f}%  "
              f"min{a_all.min():+.1f}%  max{a_all.max():+.1f}%")
        if len(b_held):
            print(f"  策略B（13:25確認，次日收出）：進場{len(b_held)}筆 跳過{b_skip}筆  "
                  f"均報{b_held.mean():+.1f}%  勝率{(b_held>0).mean()*100:.0f}%  "
                  f"min{b_held.min():+.1f}%  max{b_held.max():+.1f}%")
        else:
            print(f"  策略B：無確認進場的樣本")

    print(f"\n  明細：")
    print(df_r[["ticker","signal_date","held","ret_A_open_to_dayclose","ret_B_1325_to_nextclose"]].to_string(index=False))


if __name__ == "__main__":
    run()
