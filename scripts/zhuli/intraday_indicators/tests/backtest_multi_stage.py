"""Multi-stage 選 1 檔 backtest vs baseline rank 1.

每天最多 1 trade（從 top 10 雙確認後選最強者）。
比較與 baseline (盲目做 rank 1) 的 EV / 勝率 / trade 次數。

Usage:
    PYTHONPATH=scripts python -m zhuli.intraday_indicators.tests.backtest_multi_stage \
        --start 2026-05-01 --end 2026-06-04
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

_HERE = Path(__file__).parent
_REPO = _HERE.parent.parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def get_kline_history(ticker: str, target_date: str, db_path: Path) -> pd.DataFrame:
    """抓 ticker 200 日歷史日 K（給 K-line classifier 用）。"""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
    df = pd.read_sql(
        """SELECT trade_date, trade_date as date, open, high, low, close, volume,
                  vol_ratio_20, ma5, ma10, ma20, ma60
           FROM standard_daily_bar
           WHERE ticker=? AND trade_date >= date(?, '-200 days') AND trade_date <= ?
           ORDER BY trade_date""",
        con, params=(ticker, target_date, target_date),
    )
    con.close()
    if df.empty:
        return df
    df["ticker"] = ticker
    df["prev_close"] = df["close"].shift(1)
    df["prev_open"] = df["open"].shift(1)
    df["prev_high"] = df["high"].shift(1)
    df["prev_low"] = df["low"].shift(1)
    df["ma5_slope_5d"] = df["ma5"].diff(5)
    df["ma10_slope_5d"] = df["ma10"].diff(5)
    df["ma20_slope_5d"] = df["ma20"].diff(5)
    df["volume_ratio"] = df["vol_ratio_20"]
    # shakeout 用 prior_high_60
    df["prior_high_60"] = df["high"].rolling(60, min_periods=20).max().shift(1)
    return df


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--target", type=float, default=2.5)
    p.add_argument("--require-breakout-vol", action="store_true",
                   help="啟用 Ch5-2 量能突破過濾")
    args = p.parse_args()

    from kline.bars import DEFAULT_DB_PATH
    from zhuli.intraday_indicators.tests.backtest_top10_intraday import (
        get_top10_for_date, _fetch_1m, simulate_daytrade,
    )
    from zhuli.intraday_indicators.multi_stage_selector import (
        classify_kline_patterns, confirm_open, pick_one,
    )

    con = sqlite3.connect(f"file:{DEFAULT_DB_PATH}?mode=ro", uri=True, timeout=15)
    trade_dates = [r[0] for r in con.execute(
        "SELECT DISTINCT trade_date FROM standard_daily_bar "
        "WHERE trade_date >= ? AND trade_date <= ? ORDER BY trade_date",
        (args.start, args.end),
    ).fetchall()]
    con.close()
    print(f"交易日 {args.start} ~ {args.end}: {len(trade_dates)} 天")

    multi_stage_results = []
    baseline_rank1_results = []

    for i in range(len(trade_dates) - 1):
        sig = trade_dates[i]
        nxt = trade_dates[i + 1]

        top10 = get_top10_for_date(
            sig, DEFAULT_DB_PATH, scoring="v3_2",
            require_breakout_vol=args.require_breakout_vol,
        )
        if not top10:
            continue

        # 對 top 10 各 ticker：classify_kline_patterns + confirm_open
        enriched = []
        for pick in top10:
            t = pick["ticker"]
            df_hist = get_kline_history(t, sig, DEFAULT_DB_PATH)
            kp = classify_kline_patterns(df_hist, lookback=3)

            k1m_next = _fetch_1m(t, nxt)
            open_result = confirm_open(k1m_next, pick.get("close", 0))

            enriched.append({
                **pick,
                "kline_branches": [b["name"] for b in kp["branches"]],
                "bull_count": kp["bull_count"],
                "bear_count": kp["bear_count"],
                "net_bias": kp["net_bias"],
                "kline_strength": kp["strength"],
                "open_verdict": open_result["verdict"],
                "open_score": open_result["open_score"],
                "open_reason": open_result["reason"],
                "_k1m_next": k1m_next,  # cache for sim
            })

        # Multi-stage pick
        chosen = pick_one(enriched)
        if chosen is not None:
            sim = simulate_daytrade(chosen["_k1m_next"], chosen["close"],
                                    target_pct=args.target, stop_variant="A")
            multi_stage_results.append({
                "sig_date": sig, "next_date": nxt,
                "ticker": chosen["ticker"],
                "rank": next((i + 1 for i, h in enumerate(top10)
                              if h["ticker"] == chosen["ticker"]), 0),
                "score": chosen.get("confidence_score", 0),
                "kline_branches": ",".join(chosen.get("kline_branches", [])),
                "kline_strength": chosen.get("kline_strength", 0),
                "open_verdict": chosen.get("open_verdict", ""),
                "selection_score": chosen.get("selection_score", 0),
                **sim,
            })
            tag = "✅" if sim.get("entered") and sim.get("pnl_pct", 0) > 0 else (
                "❌" if sim.get("entered") else "⏸"
            )
            print(f"  {sig}→{nxt} {tag} {chosen['ticker']} "
                  f"(rank={multi_stage_results[-1]['rank']}, "
                  f"bias={chosen.get('net_bias',0):+d}, "
                  f"open={chosen.get('open_verdict','')}, "
                  f"sel={chosen.get('selection_score',0):.0f}) "
                  f"pnl={sim.get('pnl_pct', 0):+.2f}% [{sim['exit_reason']}]")
        else:
            print(f"  {sig}→{nxt} ⏸ skip (無 bullish open confirm)")

        # Baseline: 盲做 rank 1
        rank1 = top10[0]
        k1m_r1 = _fetch_1m(rank1["ticker"], nxt)
        if not k1m_r1.empty:
            sim_b = simulate_daytrade(k1m_r1, rank1["close"],
                                      target_pct=args.target, stop_variant="A")
            baseline_rank1_results.append({
                "sig_date": sig, "next_date": nxt,
                "ticker": rank1["ticker"],
                "score": rank1.get("confidence_score", 0),
                **sim_b,
            })

    # 統計
    print("\n=== Multi-stage 結果 ===")
    df_ms = pd.DataFrame(multi_stage_results)
    if not df_ms.empty:
        entered = df_ms[df_ms["entered"] == True]
        wins = entered[entered["pnl_pct"] > 0]
        print(f"trade 數: {len(df_ms)} (skip 日不算)")
        print(f"進場: {len(entered)}/{len(df_ms)} ({len(entered)/max(1,len(df_ms))*100:.0f}%)")
        print(f"進場勝率: {len(wins)}/{len(entered)} = "
              f"{len(wins)/max(1,len(entered))*100:.0f}%")
        print(f"平均 pnl (含未進場 0): {df_ms['pnl_pct'].mean():+.2f}%")
        print(f"平均 pnl (僅進場): {entered['pnl_pct'].mean() if not entered.empty else 0:+.2f}%")
        print(f"累積 pnl: {df_ms['pnl_pct'].sum():+.2f}%")

    print("\n=== Baseline Rank 1 結果 ===")
    df_b = pd.DataFrame(baseline_rank1_results)
    if not df_b.empty:
        entered_b = df_b[df_b["entered"] == True]
        wins_b = entered_b[entered_b["pnl_pct"] > 0]
        print(f"trade 數: {len(df_b)} (每天都做 rank 1)")
        print(f"進場: {len(entered_b)}/{len(df_b)} "
              f"({len(entered_b)/max(1,len(df_b))*100:.0f}%)")
        print(f"進場勝率: {len(wins_b)}/{len(entered_b)} = "
              f"{len(wins_b)/max(1,len(entered_b))*100:.0f}%")
        print(f"平均 pnl (含未進場 0): {df_b['pnl_pct'].mean():+.2f}%")
        print(f"累積 pnl: {df_b['pnl_pct'].sum():+.2f}%")

    # CSV
    df_ms.to_csv("/tmp/multi_stage_results.csv", index=False)
    df_b.to_csv("/tmp/baseline_rank1_results.csv", index=False)
    print("\nCSV: /tmp/multi_stage_results.csv, /tmp/baseline_rank1_results.csv")


if __name__ == "__main__":
    main()
