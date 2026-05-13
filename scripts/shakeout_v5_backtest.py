"""
v5 收盤確認進場 vs v4 開盤進場 — 全樣本回測
===============================================
核心邏輯：
  ret_Nd_net 是以進場日開盤（entry_open）為基準
  future_close_Nd = entry_open * (1 + ret_Nd_net + RC)

Strategy A：entry_open 進場
Strategy B：entry_close（≈13:25）進場，only when entry_close >= entry_open
  ret_B = future_close / entry_close - 1 - RC
        = entry_open * (1 + ret_Nd + RC) / entry_close - 1 - RC
"""
from __future__ import annotations

import sys, os, time
from pathlib import Path
from datetime import timedelta
import pandas as pd
import numpy as np

SAS_PATH = Path(__file__).parent.parent.parent / "stock-analysis-system"
sys.path.insert(0, str(SAS_PATH.resolve()))
TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJkYXRlIjoiMjAyNi0wMy0yMyAxNDowMToyMCIsInVzZXJfaWQiOiJwYzAyODc3MSIsImVtYWlsIjoicGMwMjg3NzFAZ21haWwuY29tIiwiaXAiOiI2MC4yNTAuMzcuMTEyIn0.TevLwnL4uIon6qu-ARDTKvrxLpCyX5nmRTN0rhBUyMU"

from clients import finmind_client as fm

ROUND_TRIP_COST = 0.00585
RC = ROUND_TRIP_COST
CSV = Path("data/analysis/kline_course_backtest/breakout_daily_scanner.csv")
PRICE_CACHE = Path("/tmp/shakeout_entry_day_cache.csv")


def next_trading_date(d: pd.Timestamp) -> pd.Timestamp:
    nd = d + timedelta(days=1)
    while nd.weekday() >= 5:
        nd += timedelta(days=1)
    return nd


def load_or_fetch_entry_prices(signals: pd.DataFrame) -> pd.DataFrame:
    """拉每筆訊號的進場日 OHLC，有 cache 就用 cache。"""
    if PRICE_CACHE.exists():
        cached = pd.read_csv(PRICE_CACHE)
        cached_keys = set(zip(cached["ticker"], cached["entry_date"]))
        needed = signals[
            ~signals.apply(lambda r: (str(r["ticker"]), r["entry_date"]) in cached_keys, axis=1)
        ]
        print(f"  Cache 命中 {len(signals)-len(needed)} 筆，需補抓 {len(needed)} 筆")
        frames = [cached]
    else:
        needed = signals
        frames = []
        print(f"  無 cache，抓全部 {len(needed)} 筆")

    total = len(needed)
    for i, (_, row) in enumerate(needed.iterrows(), 1):
        sid = str(row["ticker"])
        edate = row["entry_date"]
        if i % 20 == 0 or i == total:
            print(f"  [{i}/{total}] {sid} {edate}")
        try:
            df = fm.get_price(sid, edate, edate, TOKEN)
            if not df.empty:
                rec = {
                    "ticker": sid,
                    "entry_date": edate,
                    "entry_open": float(df["open"].iloc[-1]),
                    "entry_high": float(df["high"].iloc[-1]),
                    "entry_low":  float(df["low"].iloc[-1]),
                    "entry_close": float(df["close"].iloc[-1]),
                }
                frames.append(pd.DataFrame([rec]))
        except Exception as e:
            print(f"    ⚠ {sid} {edate}: {e}")
        time.sleep(0.3)

    if not frames:
        return pd.DataFrame()
    result = pd.concat(frames, ignore_index=True).drop_duplicates(["ticker","entry_date"])
    result.to_csv(PRICE_CACHE, index=False)
    return result


def stats(series, label=""):
    s = series.dropna()
    if len(s) == 0:
        return f"{label}: n=0"
    return (f"{label}: n={len(s):3d}  均報{s.mean():+6.2f}%  "
            f"勝率{(s>0).mean()*100:5.1f}%  "
            f"中位{s.median():+6.2f}%  "
            f"min{s.min():+7.2f}%  max{s.max():+6.2f}%")


def run():
    # ── 1. 讀訊號 ──────────────────────────────────────────────────────────
    df = pd.read_csv(CSV)
    sig = df[df["shakeout_strong"] == True].copy()
    sig = sig.dropna(subset=["ret_10d_net", "ret_20d_net"])
    sig["trade_date"] = pd.to_datetime(sig["trade_date"])
    sig["entry_date"] = sig["trade_date"].apply(next_trading_date).dt.strftime("%Y-%m-%d")
    sig["ticker"] = sig["ticker"].astype(str)
    print(f"shakeout_strong 總筆數：{len(sig)}")

    # ── 2. 拉進場日 OHLC ───────────────────────────────────────────────────
    print("\n拉進場日 OHLC...")
    entry_prices = load_or_fetch_entry_prices(sig[["ticker","entry_date"]].drop_duplicates())
    sig = sig.merge(entry_prices, on=["ticker","entry_date"], how="left")
    sig = sig.dropna(subset=["entry_open", "entry_close"])
    print(f"有效樣本：{len(sig)}\n")

    # ── 3. 計算報酬 ────────────────────────────────────────────────────────
    # 進場日的 open→close 報酬（用於分組）
    sig["entry_day_ret"] = (sig["entry_close"] / sig["entry_open"] - 1) * 100

    # future_close 從 ret_Nd_net 還原
    for h in (10, 20):
        col = f"ret_{h}d_net"
        sig[f"future_close_{h}d"] = sig["entry_open"] * (1 + sig[col] + RC)

    # Strategy A：開盤進
    sig["ret_A_10d"] = sig["ret_10d_net"] * 100
    sig["ret_A_20d"] = sig["ret_20d_net"] * 100

    # Strategy B：收盤進（only when entry_close >= entry_open）
    sig["held"] = sig["entry_close"] >= sig["entry_open"]
    for h in (10, 20):
        sig[f"ret_B_{h}d"] = np.where(
            sig["held"],
            (sig[f"future_close_{h}d"] / sig["entry_close"] - 1 - RC) * 100,
            np.nan,
        )

    # 漲幅分組
    def bucket(x):
        if x < 0:    return "❌ 跌破"
        if x < 3:    return "0~3%"
        if x < 8:    return "3~8%"
        return ">8%"
    sig["entry_bucket"] = sig["entry_day_ret"].apply(bucket)

    # ── 4. 輸出 ────────────────────────────────────────────────────────────
    print("=" * 68)
    print("  一、整體比較（A開盤 vs B收盤確認）")
    print("=" * 68)
    for h in (10, 20):
        held = sig[sig["held"]]
        not_held = sig[~sig["held"]]
        print(f"\n  【{h}日持有】")
        print(" ", stats(sig[f"ret_A_{h}d"],       "A 全進   "))
        print(" ", stats(held[f"ret_B_{h}d"],       f"B 確認進 ({len(held)}/{len(sig)} 筆)"))
        if len(not_held):
            print(f"  B 跳過 {len(not_held)} 筆，若 A 進：{stats(not_held[f'ret_A_{h}d'],'')}")

    print()
    print("=" * 68)
    print("  二、進場日漲幅分組")
    print("=" * 68)
    for bkt in ["0~3%", "3~8%", ">8%", "❌ 跌破"]:
        sub = sig[sig["entry_bucket"] == bkt]
        if len(sub) == 0:
            continue
        sub_b = sub[sub["held"]]
        print(f"\n  【{bkt}】  A全進 n={len(sub)}，B確認 n={len(sub_b)}")
        for h in (10, 20):
            print(f"    {h}d  ", stats(sub[f"ret_A_{h}d"], "A"), " | ",
                  stats(sub_b[f"ret_B_{h}d"], "B"))

    print()
    print("=" * 68)
    print("  三、大漲 >8% 明細")
    print("=" * 68)
    big = sig[sig["entry_bucket"] == ">8%"].sort_values("entry_day_ret", ascending=False)
    if len(big):
        print(f"  共 {len(big)} 筆，20d 正{(big['ret_A_20d']>0).sum()} 負{(big['ret_A_20d']<=0).sum()}")
        print(f"  {'訊號日':12} {'代號':6} {'盤中漲':>8} {'A10d':>8} {'A20d':>8} {'B10d':>8} {'B20d':>8} {'市場'}")
        for _, r in big.iterrows():
            print(f"  {str(r['trade_date'].date()):12} {r['ticker']:6} "
                  f"{r['entry_day_ret']:>+7.1f}% "
                  f"{r['ret_A_10d']:>+7.1f}% {r['ret_A_20d']:>+7.1f}% "
                  f"{r['ret_B_10d']:>+7.1f}% {r['ret_B_20d']:>+7.1f}%  "
                  f"{r.get('market_regime','')}")

    print()
    print("=" * 68)
    print("  四、市場環境分組")
    print("=" * 68)
    for regime in sorted(sig["market_regime"].dropna().unique()):
        sub = sig[sig["market_regime"] == regime]
        sub_b = sub[sub["held"]]
        print(f"\n  【{regime}】  A n={len(sub)}，B n={len(sub_b)}")
        for h in (10, 20):
            print(f"    {h}d  ", stats(sub[f"ret_A_{h}d"], "A"), " | ",
                  stats(sub_b[f"ret_B_{h}d"], "B"))


if __name__ == "__main__":
    run()
