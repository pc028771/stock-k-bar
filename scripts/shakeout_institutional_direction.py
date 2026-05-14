"""
Shakeout Strong — 三大法人方向分析
=====================================
問題：shakeout 訊號日當天，三大法人（外資/投信/自營商）的買賣方向
      是否影響後續 10d/20d 報酬？

分析框架：
  1. 對每筆 shakeout_strong 訊號，取當天三大法人淨買超（股）
  2. 依方向分組（買超 / 賣超）比較後續均報與勝率
  3. 計算法人淨買超量與後續報酬的相關係數

資料來源：
  - 訊號：data/analysis/kline_course_backtest/breakout_daily_scanner.csv
  - 法人：FinMind TaiwanStockInstitutionalInvestorsBuySell (get_institutional)

使用方法：
  python scripts/shakeout_institutional_direction.py
"""
from __future__ import annotations

import sys, os, time
from pathlib import Path

import pandas as pd
import numpy as np

SAS_PATH = Path(__file__).parent.parent.parent / "stock-analysis-system"
sys.path.insert(0, str(SAS_PATH.resolve()))

TOKEN = os.environ.get(
    "FINMIND_TOKEN",
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJkYXRlIjoiMjAyNi0wMy0yMyAxNDowMToyMCIsInVzZXJfaWQiOiJwYzAyODc3MSIsImVtYWlsIjoicGMwMjg3NzFAZ21haWwuY29tIiwiaXAiOiI2MC4yNTAuMzcuMTEyIn0.TevLwnL4uIon6qu-ARDTKvrxLpCyX5nmRTN0rhBUyMU",
)

from clients import finmind_client as fm

# ── 參數 ─────────────────────────────────────────────────────────────────
SIGNAL_CSV  = Path("data/analysis/kline_course_backtest/breakout_daily_scanner.csv")
INST_CACHE  = Path("/tmp/shakeout_inst_cache.csv")


# ── 資料載入 ──────────────────────────────────────────────────────────────
def load_signals() -> pd.DataFrame:
    df = pd.read_csv(SIGNAL_CSV)
    shakeout = df[df["shakeout_strong"] == True].copy()
    shakeout = shakeout[shakeout["ret_10d_net"].notna()]
    shakeout["ticker"] = shakeout["ticker"].astype(str)
    return shakeout.reset_index(drop=True)


# ── 法人資料（含 cache）────────────────────────────────────────────────────
def fetch_institutional(signals: pd.DataFrame) -> pd.DataFrame:
    """
    對每筆訊號取 trade_date 當天的三大法人淨買超。
    回傳欄位：ticker, trade_date, foreign_net, sitc_net, dealer_net（股數）
    """
    needed = set(zip(signals["ticker"], signals["trade_date"]))

    if INST_CACHE.exists():
        cached = pd.read_csv(INST_CACHE)
        cached["ticker"] = cached["ticker"].astype(str)
        cached_keys = set(zip(cached["ticker"], cached["trade_date"].astype(str)))
    else:
        cached = pd.DataFrame()
        cached_keys = set()

    missing = [(t, d) for t, d in needed if (t, d) not in cached_keys]
    print(f"  Cache 命中 {len(needed)-len(missing)} 筆，補抓 {len(missing)} 筆")

    new_rows: list[dict] = []
    for i, (ticker, date) in enumerate(missing, 1):
        if i % 20 == 0 or i == len(missing):
            print(f"  [{i}/{len(missing)}] {ticker} {date}")
        try:
            df = fm.get_institutional(ticker, date, date)
            row = _extract_nets(ticker, str(date), df)
        except Exception as e:
            print(f"  ⚠ {ticker} {date}: {e}")
            row = {"ticker": ticker, "trade_date": str(date),
                   "foreign_net": None, "sitc_net": None, "dealer_net": None}
        new_rows.append(row)
        time.sleep(0.3)

    if new_rows:
        new_df = pd.DataFrame(new_rows)
        all_df = pd.concat([cached, new_df], ignore_index=True) if not cached.empty else new_df
        all_df.to_csv(INST_CACHE, index=False)
        return all_df

    return cached


def _extract_nets(ticker: str, date: str, df: pd.DataFrame) -> dict:
    """從 get_institutional 的 long-form 結果取當天淨買超。

    foreign_net / sitc_net 已由 get_institutional 彙總在每列，直接取值。
    dealer_net 需從 Dealer_self + Dealer_Hedging 手動加總。
    """
    base = {"ticker": ticker, "trade_date": date,
            "foreign_net": None, "sitc_net": None, "dealer_net": None}
    if df.empty:
        return base
    day = df[df["date"] == date]
    if day.empty:
        return base

    base["foreign_net"] = float(day["foreign_net"].iloc[0])
    base["sitc_net"]    = float(day["sitc_net"].iloc[0])

    dealer_rows = day[day["name"].isin({"Dealer_self", "Dealer_Hedging", "自營商"})]
    base["dealer_net"] = float((dealer_rows["buy"] - dealer_rows["sell"]).sum()) \
                         if not dealer_rows.empty else 0.0
    return base


# ── 統計函式 ──────────────────────────────────────────────────────────────
def direction_table(merged: pd.DataFrame, inst_col: str, ret_col: str) -> pd.DataFrame:
    """依法人方向（買超/賣超/持平）分組，計算均報與勝率。"""
    m = merged[merged[ret_col].notna()].copy()
    m["方向"] = m[inst_col].apply(lambda x: "買超" if x > 0 else ("賣超" if x < 0 else "持平"))
    rows = []
    for direction, g in m.groupby("方向"):
        ret = g[ret_col]
        rows.append({
            "方向": direction,
            "n":    len(ret),
            "均報": f"{ret.mean()*100:.1f}%",
            "勝率": f"{(ret > 0).mean()*100:.0f}%",
            "中位": f"{ret.median()*100:.1f}%",
        })
    return pd.DataFrame(rows).sort_values("方向")


def corr_analysis(merged: pd.DataFrame, ret_col: str) -> None:
    """三大法人淨買超量 vs 後續報酬的 Pearson 相關係數。"""
    print(f"\n  相關係數（{ret_col}）")
    for col, label in [("foreign_net", "外資"), ("sitc_net", "投信"), ("dealer_net", "自營商")]:
        valid = merged[[col, ret_col]].dropna()
        if len(valid) < 5:
            continue
        r = valid[col].corr(valid[ret_col])
        print(f"    {label}: r = {r:.3f}  (n={len(valid)})")


# ── 主程式 ────────────────────────────────────────────────────────────────
def main() -> None:
    print("=== Shakeout 三大法人方向分析 ===\n")

    print("1. 載入訊號...")
    signals = load_signals()
    print(f"   {len(signals)} 筆（含 ret_10d_net）\n")

    print("2. 抓取法人資料...")
    inst = fetch_institutional(signals)
    inst["ticker"] = inst["ticker"].astype(str)
    inst["trade_date"] = inst["trade_date"].astype(str)

    print("\n3. 合併資料...")
    merged = signals.merge(inst, on=["ticker", "trade_date"], how="left")
    covered = merged["foreign_net"].notna().sum()
    print(f"   覆蓋率：{covered}/{len(merged)}")

    merged = merged[merged["foreign_net"].notna()].copy()

    print("\n" + "="*60)
    for ret_col, label in [("ret_10d_net", "10日"), ("ret_20d_net", "20日")]:
        if ret_col not in merged.columns:
            continue
        m = merged[merged[ret_col].notna()]
        print(f"\n【{label}報酬分析】 n={len(m)}")

        for inst_col, inst_label in [
            ("foreign_net", "外資"),
            ("sitc_net",    "投信"),
            ("dealer_net",  "自營商"),
        ]:
            print(f"\n  ▸ {inst_label}")
            print(direction_table(m, inst_col, ret_col).to_string(index=False))

        corr_analysis(m, ret_col)

    # 高強度子集
    strong = merged[merged["breakout_strength_pct"] >= 9]
    if len(strong) >= 5:
        print("\n" + "="*60)
        print(f"\n【高強度 ≥9% 子集】 n={len(strong)}")
        for inst_col, inst_label in [("foreign_net", "外資"), ("sitc_net", "投信")]:
            print(f"\n  ▸ {inst_label} vs 10d")
            print(direction_table(strong, inst_col, "ret_10d_net").to_string(index=False))

    print("\n完成。")


if __name__ == "__main__":
    os.chdir(Path(__file__).parent.parent)
    main()
