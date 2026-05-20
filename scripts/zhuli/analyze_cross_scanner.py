"""跨 scanner pairwise 共識分析.

對每對 (主策略, 過濾策略) 計算: 主策略 trades 中,
過去 30 天有過 過濾策略 signal 的 subset 的 EV / hit rate.

用於發現「波段 + 動能/籌碼確認」最強組合.

Usage:
    python scripts/zhuli/analyze_cross_scanner.py [--lookback 30]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

_WORKTREE = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_WORKTREE / "scripts"))

SCANNERS = {
    "A 大波段":      "swing_breakout_trades.csv",
    "I 投信跟單":     "institutional_swing_trades.csv",
    "G 隔日沖":      "overnight_swing_trades.csv",
    "J 投信首買":     "institutional_firstbuy_trades.csv",
    "F 當沖":        "intraday_trades.csv",
    "M+ 收低開高":   "open_signal_entry_trades.csv",
    "H 窒息量":      "suffocation_trades.csv",
    "C 反轉形態":    "reversal_breakout_trades.csv",
    "B 旗形":        "pennant_flag_trades.csv",
    "D 布林上軌":    "bbands_upper_break_trades.csv",
    "E 布林回測":    "bollinger_pullback_trades.csv",
}


def load_all(backtest_dir: Path) -> dict:
    dfs = {}
    for name, fname in SCANNERS.items():
        p = backtest_dir / fname
        if not p.exists():
            continue
        df = pd.read_csv(p, dtype={"ticker": str})
        df["entry_dt"] = pd.to_datetime(df["entry_date"])
        dfs[name] = df
    return dfs


def consensus_subset(main_df: pd.DataFrame, filt_df: pd.DataFrame, lookback_days: int) -> pd.DataFrame:
    """嚴格 T-1 共識: filt 在 main entry 前 1~N 天有同 ticker signal."""
    idx_list = []
    for idx, row in main_df.iterrows():
        nearby = filt_df[
            (filt_df["ticker"] == row["ticker"])
            & (filt_df["entry_dt"] >= row["entry_dt"] - pd.Timedelta(days=lookback_days))
            & (filt_df["entry_dt"] < row["entry_dt"])
        ]
        if not nearby.empty:
            idx_list.append(idx)
    return main_df.loc[idx_list]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback", type=int, default=30)
    ap.add_argument("--min-trades", type=int, default=10)
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    backtest_dir = _WORKTREE / "data" / "analysis" / "zhuli" / "backtest"
    dfs = load_all(backtest_dir)
    print(f"Loaded {len(dfs)} scanners")

    combos = []
    for main_name, main_df in dfs.items():
        base_ev = main_df["return_pct"].mean()
        base_hit = (main_df["return_pct"] > 0).mean() * 100
        for filt_name, filt_df in dfs.items():
            if filt_name == main_name:
                continue
            sub = consensus_subset(main_df, filt_df, args.lookback)
            if len(sub) < args.min_trades:
                continue
            ev = sub["return_pct"].mean()
            hit = (sub["return_pct"] > 0).mean() * 100
            combos.append({
                "主策略": main_name, "過濾": filt_name,
                "n": len(sub),
                "base_EV": base_ev, "with_EV": ev,
                "improve": ev - base_ev,
                "base_Hit": base_hit, "with_Hit": hit,
            })

    df = pd.DataFrame(combos).sort_values("improve", ascending=False)
    print(f"\n🏆 Top {args.top} 最強組合 (lookback {args.lookback} 天, ≥ {args.min_trades} trades)")
    print(f"{'主策略':<15}{'過濾':<15} {'n':>4} {'單獨 EV':>8} {'+過濾 EV':>9} {'改善':>8} {'Hit%':>6}")
    for _, r in df.head(args.top).iterrows():
        print(f"{r['主策略']:<15}{r['過濾']:<15} {r['n']:>4} {r['base_EV']:>+7.2f}% {r['with_EV']:>+8.2f}% {r['improve']:>+7.2f}% {r['with_Hit']:>5.1f}%")

    # 儲存完整 CSV
    out = backtest_dir / "cross_scanner_consensus.csv"
    df.to_csv(out, index=False)
    print(f"\n完整結果 → {out}")


if __name__ == "__main__":
    main()
