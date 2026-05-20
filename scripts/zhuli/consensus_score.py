"""跨 scanner 共識分數系統 — 為每筆潛在進場算「共識強度」.

對任一 (ticker, date)，共識分數 = 過去 30 天 unique scanner 命中數
  - 1 = 單 scanner 命中（低共識）
  - 2 = 兩個 scanner 重疊（中共識）
  - 3+ = 多 scanner 重疊（高共識）

Backtest 驗證各 score level 的 EV / hit / PF.

⚠️ CLAUDE.md 紅線:
  - 不指定具體倉位比例（課程沒教）
  - 不指定進場價 / 停損價
  - 只提供「歷史共識 score 對應績效」的數據證據

User 依自己風險偏好決定如何運用 score:
  - 大資金保守: 高 score 加重、低 score 減量
  - 多元分散: 各 score 等權
  - 看 EV / Sharpe / hit rate 三者取捨

Usage:
    python scripts/zhuli/consensus_score.py [--lookback 30]
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
    "J 投信首買":     "institutional_firstbuy_trades.csv",
    "H 窒息量":      "suffocation_trades.csv",
    "M+ 收低開高":   "open_signal_entry_trades.csv",
    "B 旗形":        "pennant_flag_trades.csv",
    "C 反轉形態":    "reversal_breakout_trades.csv",
    "D 布林上軌":    "bbands_upper_break_trades.csv",
    "E 布林回測":    "bollinger_pullback_trades.csv",
    # F / G 因時間框架不同, 從共識分數移除避免雜訊
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback", type=int, default=30)
    args = ap.parse_args()

    backtest_dir = _WORKTREE / "data" / "analysis" / "zhuli" / "backtest"

    # Load 所有 scanner trades + 標記 scanner name
    all_trades = []
    for name, fname in SCANNERS.items():
        p = backtest_dir / fname
        if not p.exists():
            continue
        df = pd.read_csv(p, dtype={"ticker": str})
        df["scanner"] = name
        df["entry_dt"] = pd.to_datetime(df["entry_date"])
        all_trades.append(df)

    combined = pd.concat(all_trades, ignore_index=True)
    print(f"Loaded {len(SCANNERS)} scanners / {len(combined):,} total trades")

    # 對每筆 trade，計算共識分數: 過去 N 天 unique scanner 命中數 (含當下)
    print(f"\n計算共識分數 (lookback {args.lookback} 天)...")
    scores = []
    for idx, row in combined.iterrows():
        if idx % 2000 == 0:
            print(f"  {idx:,}/{len(combined):,}...")
        t = row["ticker"]
        entry = row["entry_dt"]
        # 找同 ticker 過去 30 天到當下，unique scanner 命中數
        window = combined[
            (combined["ticker"] == t)
            & (combined["entry_dt"] >= entry - pd.Timedelta(days=args.lookback))
            & (combined["entry_dt"] <= entry)
        ]
        unique_scanners = window["scanner"].nunique()
        scores.append(unique_scanners)
    combined["consensus_score"] = scores

    # Per score 統計
    print("\n" + "=" * 90)
    print("📊 共識分數 → 績效對應 (歷史 backtest 證據)")
    print("=" * 90)
    print(f"{'Score':<8}{'Trades':>9}{'Hit%':>8}{'Avg EV':>10}{'Win%':>8}{'Loss%':>10}{'Sharpe':>9}{'PF':>6}")
    print("-" * 90)

    for score in sorted(combined["consensus_score"].unique()):
        sub = combined[combined["consensus_score"] == score]
        n = len(sub)
        if n < 10:
            continue
        hit = (sub["return_pct"] > 0).mean() * 100
        avg_ev = sub["return_pct"].mean()
        wins = sub[sub["return_pct"] > 0]
        losses = sub[sub["return_pct"] <= 0]
        avg_win = wins["return_pct"].mean() if len(wins) > 0 else 0
        avg_loss = losses["return_pct"].mean() if len(losses) > 0 else 0
        std = sub["return_pct"].std()
        sharpe = (avg_ev / std) * (252 / sub["hold_days"].mean()) ** 0.5 if std > 0 else 0
        pf = abs(wins["return_pct"].sum() / losses["return_pct"].sum()) if len(losses) > 0 and losses["return_pct"].sum() != 0 else 99
        print(f"{score:<8}{n:>9} {hit:>6.1f}% {avg_ev:>+8.2f}% {avg_win:>+6.2f}% {avg_loss:>+8.2f}% {sharpe:>8.2f} {pf:>5.2f}")
    print("=" * 90)

    # 高 score 是什麼 scanner combination?
    print("\n🔍 高共識分數 (≥3) 常見 scanner 組合:")
    high = combined[combined["consensus_score"] >= 3]
    # 對每筆高 score trade, 找該 (ticker, 過去 30 天) 涵蓋的 scanners
    combos = {}
    for _, row in high.iterrows():
        t = row["ticker"]; entry = row["entry_dt"]
        window = combined[
            (combined["ticker"] == t)
            & (combined["entry_dt"] >= entry - pd.Timedelta(days=args.lookback))
            & (combined["entry_dt"] <= entry)
        ]
        combo = tuple(sorted(window["scanner"].unique()))
        combos[combo] = combos.get(combo, 0) + 1

    top_combos = sorted(combos.items(), key=lambda x: -x[1])[:8]
    for combo, n in top_combos:
        combo_str = " + ".join(combo)
        print(f"  ({n}x) {combo_str}")

    # 儲存
    combined[["scanner", "ticker", "entry_date", "consensus_score", "return_pct", "hold_days"]].to_csv(
        backtest_dir / "consensus_score_per_trade.csv", index=False
    )
    print(f"\n完整資料 → consensus_score_per_trade.csv")

    # 使用建議（依 CLAUDE.md 紅線：只提供數據，不指定倉位）
    print("\n" + "=" * 90)
    print("📝 使用建議（CLAUDE.md 紅線：不指定具體倉位比例）")
    print("=" * 90)
    print("""
本分數系統提供「歷史共識強度 → 預期績效」的數據證據:
  - Score 1: 單 scanner 命中 — baseline 預期值
  - Score 2: 兩個 scanner 重疊 — 中度確認
  - Score 3+: 多 scanner 重疊 — 高度確認 (但樣本通常較少)

⚠️ 課程沒明確指定「共識分數 X → 倉位 Y%」對應。
   user 應依自己風險偏好 + 倉位策略決定:
   - 高 Score → 高信心訊號（但仍需依個股結構檢核）
   - Low Score → 標準倉位 / 觀察級
   - 跨多策略時間框架（A 波段 vs G 短線）不該混合算 score

CLAUDE.md 紅線提醒:
  - 具體進場價、停損價、加碼比例: 依各 scanner 自帶 stop_loss
  - 盤中執行時機: 課程未明說則保留人工判斷
""")


if __name__ == "__main__":
    main()
