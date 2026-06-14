"""Backtest detector 1 (bb_squeeze), detector 2 (main_chip_holder), and the
cross signal — see if intersection improves Phase 2's +1.02% / 37% win rate.

Output:
- per-trade CSVs
- summary table for docs/權證小哥/籌碼技術分析/backtest_phase3.md
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.xiaoge.bars import load_bars, add_squeeze_flag
from scripts.xiaoge.entry.bb_squeeze_breakout import detect as detect_bb
from scripts.xiaoge.entry.main_chip_holder import detect as detect_chip
from scripts.xiaoge.scoring.cross_xiaoge_chip_bb import detect_cross
from scripts.xiaoge.exit.leave_upper_band import should_exit


REPO = Path(__file__).resolve().parents[2]


def simulate_trades(df: pd.DataFrame, signals: pd.Series, max_hold: int = 30) -> pd.DataFrame:
    df = df.copy()
    df["signal"] = signals
    grp = df.groupby("ticker")
    trades = []
    for ticker, sub in grp:
        sub = sub.reset_index(drop=True)
        sig_idxs = sub.index[sub["signal"]].tolist()
        # De-duplicate: skip signals while a previous trade is still open
        last_exit = -1
        for sig_idx in sig_idxs:
            if sig_idx + 1 >= len(sub) or sig_idx <= last_exit:
                continue
            entry_idx = sig_idx + 1
            entry_bar = sub.iloc[entry_idx]
            entry_price = entry_bar["open"]
            if pd.isna(entry_price) or entry_price <= 0:
                continue
            exit_idx = None
            for i in range(entry_idx, min(entry_idx + max_hold, len(sub))):
                bar = sub.iloc[i]
                if i > entry_idx and should_exit(bar["close"], bar["bb_upper"]):
                    exit_idx = i + 1 if (i + 1) < len(sub) else i
                    break
            if exit_idx is None:
                exit_idx = min(entry_idx + max_hold, len(sub) - 1)
            exit_bar = sub.iloc[exit_idx]
            exit_price = exit_bar["open"] if pd.notna(exit_bar["open"]) and exit_bar["open"] > 0 else exit_bar["close"]
            # Skip trades with bad data (exit price 0 = stock suspended / DB gap)
            if pd.isna(exit_price) or exit_price <= 0:
                continue
            ret_pct = (exit_price - entry_price) / entry_price * 100
            trades.append({
                "ticker": ticker,
                "signal_date": sub.iloc[sig_idx]["trade_date"].strftime("%Y-%m-%d"),
                "entry_date": entry_bar["trade_date"].strftime("%Y-%m-%d"),
                "entry_price": round(entry_price, 2),
                "exit_date": exit_bar["trade_date"].strftime("%Y-%m-%d"),
                "exit_price": round(exit_price, 2),
                "hold_days": exit_idx - entry_idx,
                "ret_pct": round(ret_pct, 2),
            })
            last_exit = exit_idx
    return pd.DataFrame(trades)


def summarize(name: str, trades: pd.DataFrame) -> dict:
    if len(trades) == 0:
        return {"name": name, "n": 0, "avg_ret": None, "win_rate": None, "avg_hold": None}
    return {
        "name": name,
        "n": len(trades),
        "avg_ret": round(trades["ret_pct"].mean(), 2),
        "median_ret": round(trades["ret_pct"].median(), 2),
        "win_rate": round((trades["ret_pct"] > 0).mean() * 100, 1),
        "avg_hold": round(trades["hold_days"].mean(), 1),
        "max_ret": round(trades["ret_pct"].max(), 2),
        "min_ret": round(trades["ret_pct"].min(), 2),
    }


def main():
    start, end = "2026-05-01", "2026-06-12"
    df = load_bars(start, end)
    df = add_squeeze_flag(df, lookback=10, threshold=15.0)

    # In-window filter
    in_window = df["trade_date"] >= pd.Timestamp(start)

    # detector 1 (best config from Phase 2)
    bb_sig = detect_bb(df, breakout_mode="shenglongquan") & in_window
    bb_trades = simulate_trades(df, bb_sig)
    bb_trades.to_csv(REPO / "data/analysis/xiaoge/backtest/phase3_bb_only.csv", index=False)

    # detector 2 (chip)
    chip_sig = detect_chip(df) & in_window
    chip_trades = simulate_trades(df, chip_sig)
    chip_trades.to_csv(REPO / "data/analysis/xiaoge/backtest/phase3_chip_only.csv", index=False)

    # cross variations
    cross_sig_1d = detect_cross(df, window=1,
                                 bb_kwargs={"breakout_mode": "shenglongquan"}) & in_window
    cross_1d_trades = simulate_trades(df, cross_sig_1d)
    cross_1d_trades.to_csv(REPO / "data/analysis/xiaoge/backtest/phase3_cross_1d.csv", index=False)

    cross_sig_5d = detect_cross(df, window=5,
                                 bb_kwargs={"breakout_mode": "shenglongquan"}) & in_window
    cross_5d_trades = simulate_trades(df, cross_sig_5d)
    cross_5d_trades.to_csv(REPO / "data/analysis/xiaoge/backtest/phase3_cross_5d.csv", index=False)

    # Tighter chip (10% ratio)
    tight_chip_sig = detect_chip(df, min_chip_ratio=0.10) & in_window
    tight_chip_trades = simulate_trades(df, tight_chip_sig)
    tight_chip_trades.to_csv(REPO / "data/analysis/xiaoge/backtest/phase3_chip_tight.csv", index=False)

    # Compare
    results = [
        summarize("detector 1: bb_squeeze (升龍拳)", bb_trades),
        summarize("detector 2: main_chip_holder (5% ratio)", chip_trades),
        summarize("detector 2 tight (10% ratio)", tight_chip_trades),
        summarize("cross (bb ∩ chip, 1d 同日)", cross_1d_trades),
        summarize("cross (bb ∩ chip, 5d window)", cross_5d_trades),
    ]
    res_df = pd.DataFrame(results)
    print(res_df.to_string(index=False))

    # Write report
    report = f"""# Phase 3 — chip + cross detector backtest

> Source: `scripts/xiaoge/backtest_phase3.py`
> Date: 2026-06-14

## 結果對比

| Detector | n | avg_ret | median | win_rate | avg_hold | max | min |
|---|---|---|---|---|---|---|---|
"""
    for r in results:
        report += (f"| {r['name']} | {r['n']} | "
                   f"{r['avg_ret']}% | {r.get('median_ret', '-')}% | "
                   f"{r['win_rate']}% | {r['avg_hold']} | "
                   f"{r.get('max_ret', '-')}% | {r.get('min_ret', '-')}% |\n")
    report += """

## 資料限制 (重要)

- **集保戶數**：DB `custody_accounts` 全 None、未匯入。detector 2 缺第 3 軸。
- **散戶賣超**：DB 無對應欄位、detector 2 缺第 2 軸。
- 目前 detector 2 = 主力買超（用 `main_force_5d` 機構代理）+ 月線上揚 + 站上月線。
- 真正的「主力 ≥ 20 張」分點門檻待 Phase 3b（FinMind 分點 audit）。

## 結論

見 detector 對比表 + 詳細交易 CSV：
- `data/analysis/xiaoge/backtest/phase3_bb_only.csv`
- `data/analysis/xiaoge/backtest/phase3_chip_only.csv`
- `data/analysis/xiaoge/backtest/phase3_cross.csv`

## 接下來

- 等 FinMind 分點 audit 完 → 補集保戶數 + 真正 detector 4（key_broker_signal）
- 試 cross 邏輯：bb ∩ chip ∩ kline_course 三軸（Phase 4）
"""
    (REPO / "docs/權證小哥/籌碼技術分析/backtest_phase3.md").write_text(report)
    print("\nReport → docs/權證小哥/籌碼技術分析/backtest_phase3.md")


if __name__ == "__main__":
    main()
