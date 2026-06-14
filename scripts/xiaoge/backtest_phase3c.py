"""Backtest detector 4 (key_broker_signal) + cross (bb ∩ chip_v2 ∩ broker).

出場規則：C6 (見 memory feedback_exit_rules_v3)
  - 收盤 ≥ MA10 → 不出
  - 收 < MA10 by ≥ 2% (深破) → 隔日開盤出
  - 收 < MA10 by < 2% + 量比 ≥ 1.0 → 隔日開盤出
  - 容忍區 -2% ~ 0% 連 2 天 → 隔日開盤出

進場 = 訊號日隔日開盤、單位 1 張。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.xiaoge.bars import load_bars, add_squeeze_flag
from scripts.xiaoge.entry.bb_squeeze_breakout import detect as detect_bb
from scripts.xiaoge.entry.main_chip_holder_v2 import detect as detect_chip_v2
from scripts.xiaoge.entry.key_broker_signal import (
    detect as detect_broker,
    detect_short as detect_broker_short,
)


REPO = Path(__file__).resolve().parents[2]


def _exit_c6(sub: pd.DataFrame, entry_idx: int, max_hold: int = 30) -> int:
    """Return exit_idx per C6 rules.

    sub: per-ticker bars sorted by date, with cols close, open, ma10, volume.
    entry_idx: bar 進場日（已開盤）；從 entry_idx 開始持有，從 entry_idx+1 起評估出場。
    """
    n = len(sub)
    tolerance_streak = 0  # 容忍區連續天數
    # 5d avg volume baseline for vol ratio (excludes entry day to avoid lookahead)
    for i in range(entry_idx, min(entry_idx + max_hold, n)):
        bar = sub.iloc[i]
        close = bar["close"]
        ma10 = bar["ma10"]
        vol = bar["volume"]
        if pd.isna(close) or pd.isna(ma10) or ma10 <= 0:
            continue
        dist = (close - ma10) / ma10 * 100  # % deviation, negative = below ma10

        # 5d 量比 (use last 5d incl. today's vol)
        lo = max(0, i - 5)
        baseline = sub.iloc[lo:i]["volume"].mean() if i > lo else vol
        vol_ratio = (vol / baseline) if baseline and baseline > 0 else 1.0

        if dist >= 0:
            # 收盤 ≥ MA10 → 不出、容忍計數 reset
            tolerance_streak = 0
            continue
        # below ma10
        if dist <= -2.0:
            # 深破、隔日開盤出
            return i + 1 if (i + 1) < n else i
        # -2% < dist < 0
        if vol_ratio >= 1.0:
            return i + 1 if (i + 1) < n else i
        # 容忍區（量縮）
        tolerance_streak += 1
        if tolerance_streak >= 2:
            return i + 1 if (i + 1) < n else i
    return min(entry_idx + max_hold, n - 1)


def simulate_trades_c6(df: pd.DataFrame, signals: pd.Series,
                       max_hold: int = 30) -> pd.DataFrame:
    df = df.copy()
    df["signal"] = signals
    trades = []
    for ticker, sub in df.groupby("ticker"):
        sub = sub.reset_index(drop=True)
        sig_idxs = sub.index[sub["signal"]].tolist()
        last_exit = -1
        for sig_idx in sig_idxs:
            if sig_idx + 1 >= len(sub) or sig_idx <= last_exit:
                continue
            entry_idx = sig_idx + 1
            entry_bar = sub.iloc[entry_idx]
            entry_price = entry_bar["open"]
            if pd.isna(entry_price) or entry_price <= 0:
                continue
            exit_idx = _exit_c6(sub, entry_idx, max_hold=max_hold)
            exit_bar = sub.iloc[exit_idx]
            exit_price = exit_bar["open"] if pd.notna(exit_bar["open"]) and exit_bar["open"] > 0 else exit_bar["close"]
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


def simulate_trades_short_c6(df: pd.DataFrame, signals: pd.Series,
                             max_hold: int = 30) -> pd.DataFrame:
    """空頭：訊號隔日開盤放空、ret = -(exit-entry)/entry. Exit = MA10 站回 / 容忍."""
    df = df.copy()
    df["signal"] = signals
    trades = []
    for ticker, sub in df.groupby("ticker"):
        sub = sub.reset_index(drop=True)
        sig_idxs = sub.index[sub["signal"]].tolist()
        last_exit = -1
        for sig_idx in sig_idxs:
            if sig_idx + 1 >= len(sub) or sig_idx <= last_exit:
                continue
            entry_idx = sig_idx + 1
            entry_bar = sub.iloc[entry_idx]
            entry_price = entry_bar["open"]
            if pd.isna(entry_price) or entry_price <= 0:
                continue
            # Mirror C6 for shorts: 收盤 ≤ MA10 不出、收 > MA10 by ≥ 2% 出
            exit_idx = None
            tolerance_streak = 0
            for i in range(entry_idx, min(entry_idx + max_hold, len(sub))):
                bar = sub.iloc[i]
                close = bar["close"]
                ma10 = bar["ma10"]
                vol = bar["volume"]
                if pd.isna(close) or pd.isna(ma10) or ma10 <= 0:
                    continue
                dist = (close - ma10) / ma10 * 100
                lo = max(0, i - 5)
                baseline = sub.iloc[lo:i]["volume"].mean() if i > lo else vol
                vol_ratio = (vol / baseline) if baseline and baseline > 0 else 1.0
                if dist <= 0:
                    tolerance_streak = 0
                    continue
                if dist >= 2.0:
                    exit_idx = i + 1 if (i + 1) < len(sub) else i
                    break
                if vol_ratio >= 1.0:
                    exit_idx = i + 1 if (i + 1) < len(sub) else i
                    break
                tolerance_streak += 1
                if tolerance_streak >= 2:
                    exit_idx = i + 1 if (i + 1) < len(sub) else i
                    break
            if exit_idx is None:
                exit_idx = min(entry_idx + max_hold, len(sub) - 1)
            exit_bar = sub.iloc[exit_idx]
            exit_price = exit_bar["open"] if pd.notna(exit_bar["open"]) and exit_bar["open"] > 0 else exit_bar["close"]
            if pd.isna(exit_price) or exit_price <= 0:
                continue
            # Short return = (entry - exit) / entry
            ret_pct = (entry_price - exit_price) / entry_price * 100
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
        return {"name": name, "n": 0, "avg_ret": None, "median_ret": None,
                "win_rate": None, "avg_hold": None, "max_ret": None, "min_ret": None,
                "tickers": 0, "months": 0}
    return {
        "name": name,
        "n": len(trades),
        "avg_ret": round(trades["ret_pct"].mean(), 2),
        "median_ret": round(trades["ret_pct"].median(), 2),
        "win_rate": round((trades["ret_pct"] > 0).mean() * 100, 1),
        "avg_hold": round(trades["hold_days"].mean(), 1),
        "max_ret": round(trades["ret_pct"].max(), 2),
        "min_ret": round(trades["ret_pct"].min(), 2),
        "tickers": trades["ticker"].nunique(),
        "months": pd.to_datetime(trades["signal_date"]).dt.to_period("M").nunique(),
    }


def robustness_verdict(s: dict) -> str:
    """三維 robustness 判定（per feedback_backtest_strategy_filtering）：
       跨股 ≥ 5 + 跨月 ≥ 2 + win_rate ≥ 65% = actionable
       50-65% = watch-only
       ≤ 35% = 反向訊號 skip 清單
    """
    if s["n"] == 0:
        return "no signals"
    wr = s["win_rate"] or 0
    cross_stock = s["tickers"] >= 5
    cross_month = s["months"] >= 2
    base = f"tickers={s['tickers']}, months={s['months']}, win_rate={wr}%"
    if not cross_stock or not cross_month:
        return f"insufficient diversity ({base}) → not robust"
    if wr >= 65:
        return f"actionable ({base})"
    if wr <= 35:
        return f"reverse-signal candidate ({base}) — skip-list"
    return f"watch-only ({base})"


def main():
    start, end = "2026-05-01", "2026-06-12"
    df = load_bars(start, end)
    df = add_squeeze_flag(df, lookback=10, threshold=15.0)
    in_window = df["trade_date"] >= pd.Timestamp(start)

    # detector 4 (long)
    broker_long = detect_broker(df) & in_window
    broker_trades = simulate_trades_c6(df, broker_long)
    broker_trades.to_csv(REPO / "data/analysis/xiaoge/backtest/phase3c_broker_long.csv", index=False)

    # detector 4 (short)
    broker_short = detect_broker_short(df) & in_window
    short_trades = simulate_trades_short_c6(df, broker_short)
    short_trades.to_csv(REPO / "data/analysis/xiaoge/backtest/phase3c_broker_short.csv", index=False)

    # Cross: bb ∩ chip_v2 ∩ broker (long), 1-day same-day intersection
    bb_sig = detect_bb(df, breakout_mode="shenglongquan") & in_window
    chip_sig = detect_chip_v2(df, min_chip_ratio=0.10) & in_window

    # Rolling 5-day window intersect
    window = 5
    def _rolling_any(sig: pd.Series) -> pd.Series:
        return sig.groupby(df["ticker"]).transform(
            lambda s: s.rolling(window, min_periods=1).max()
        ).astype(bool)

    bb_w = _rolling_any(bb_sig)
    chip_w = _rolling_any(chip_sig)
    broker_w = _rolling_any(broker_long)
    cross_sig = (bb_w & chip_w & broker_w & in_window).fillna(False)
    cross_trades = simulate_trades_c6(df, cross_sig)
    cross_trades.to_csv(REPO / "data/analysis/xiaoge/backtest/phase3c_cross_3way.csv", index=False)

    # Also 2-way crosses for comparison
    cross_bb_broker = (bb_w & broker_w & in_window).fillna(False)
    cross_bb_broker_trades = simulate_trades_c6(df, cross_bb_broker)
    cross_chip_broker = (chip_w & broker_w & in_window).fillna(False)
    cross_chip_broker_trades = simulate_trades_c6(df, cross_chip_broker)

    # detector 1, 2 v2 single (for baseline comparison under C6 exit)
    bb_trades = simulate_trades_c6(df, bb_sig)
    chip_trades = simulate_trades_c6(df, chip_sig)

    results = [
        summarize("detector 1: bb_squeeze (升龍拳) [C6]", bb_trades),
        summarize("detector 2 v2: chip 真三軸 10% [C6]", chip_trades),
        summarize("detector 4: key_broker_signal (long) [C6]", broker_trades),
        summarize("detector 4: key_broker_signal (short) [C6]", short_trades),
        summarize("cross 2way: bb ∩ broker (5d) [C6]", cross_bb_broker_trades),
        summarize("cross 2way: chip ∩ broker (5d) [C6]", cross_chip_broker_trades),
        summarize("cross 3way: bb ∩ chip ∩ broker (5d) [C6]", cross_trades),
    ]
    res_df = pd.DataFrame(results)
    print(res_df.to_string(index=False))

    # Robustness verdicts
    verdicts = {r["name"]: robustness_verdict(r) for r in results}
    print("\n=== Robustness Verdicts ===")
    for k, v in verdicts.items():
        print(f"  {k}: {v}")

    # Quality observation: which tickers fire detector 4 most often?
    if len(broker_trades) > 0:
        print("\n=== Detector 4 (long) top winners ===")
        print(broker_trades.nlargest(min(10, len(broker_trades)), "ret_pct")[
            ["ticker", "signal_date", "entry_price", "exit_price", "hold_days", "ret_pct"]
        ].to_string(index=False))
        print("\n=== Detector 4 (long) top losers ===")
        print(broker_trades.nsmallest(min(10, len(broker_trades)), "ret_pct")[
            ["ticker", "signal_date", "entry_price", "exit_price", "hold_days", "ret_pct"]
        ].to_string(index=False))

    # 質性觀察：哪些股是「常常被同一分點關鍵性低買」
    pool = pd.read_parquet(REPO / "data/analysis/xiaoge/key_broker_pool.parquet")
    top_quality = pool.nlargest(15, "low_buy_count")[
        ["ticker", "broker_name", "low_buy_count", "high_sell_count", "score", "total_appearances"]
    ]
    print("\n=== Pool: 最常被低買的 (ticker, broker) pairs ===")
    print(top_quality.to_string(index=False))

    # Write report
    def _row(r: dict) -> str:
        return (f"| {r['name']} | {r['n']} | {r['avg_ret']}% | "
                f"{r.get('median_ret', '-')}% | {r['win_rate']}% | "
                f"{r['avg_hold']} | {r['tickers']} | {r['months']} | "
                f"{r.get('max_ret', '-')}% | {r.get('min_ret', '-')}% |\n")

    report = f"""# Phase 3c — key_broker_signal (detector 4) + 三軸 cross backtest

> Source: `scripts/xiaoge/backtest_phase3c.py`
> Date: 2026-06-14
> 樣本：2026-05-01 ~ 2026-06-12（30 trading days）
> 新增資料：`TaiwanStockTradingDailyReport`（分點日報、aggregate 後 (date, ticker, broker_id) → net_shares）
> Pool 建構：用 2026-04-01 ~ 2026-04-30 broker data 算「低買 + 高賣」分數，每股 top 5、最低 3 次出現
> 進場閾值：池內任一分點淨買 ≥ 50 張 + 月線上揚 + 站上月線
> 出場規則：**C6**（MA10 容忍 + 量比 + 連 2 天容忍 → 隔日開盤出）

## 結果對比

| Detector | n | avg_ret | median | win_rate | avg_hold | tickers | months | max | min |
|---|---|---|---|---|---|---|---|---|---|
"""
    for r in results:
        report += _row(r)

    report += """

## 三維 Robustness 判定

> 跨股 ≥ 5 + 跨月 ≥ 2 + win_rate ≥ 65% = actionable
> 50-65% = watch-only
> ≤ 35% = 反向訊號 skip 清單

"""
    for k, v in verdicts.items():
        report += f"- **{k}**: {v}\n"

    report += """

## 質性觀察：常被「關鍵分點低買」的股

下表是 pool 中 `low_buy_count` 最高的 (ticker, broker) pair（pool 用 4 月資料建）：

| ticker | broker | low_buy_count | high_sell_count | score | appearances |
|---|---|---|---|---|---|
"""
    for _, row in top_quality.iterrows():
        report += (f"| {row['ticker']} | {row['broker_name']} | "
                   f"{row['low_buy_count']} | {row['high_sell_count']} | "
                   f"{row['score']:.3f} | {row['total_appearances']} |\n")

    report += f"""

## 資料限制 / 已知問題

1. **Pool 樣本期短** — 只有 30 個交易日 (2026-04-01 ~ 2026-04-30) 用來判定哪些分點「持續低買高賣」。
   老師原始定義是「800-2000 天分點買賣超歷史」、實作受 FinMind rate limit 限制只能短期。
2. **沒排除外資 / 自營分點** — pool 用分數自然篩、不硬排外資。可能漏掉「庫藏股分點」加分項（detector_spec.md §4）。
3. **單張 = 1000 股閾值** — pool 動作 ≥ 10 張、訊號 ≥ 50 張、可能對小型股太嚴。
4. **C6 出場 vs leave_upper_band** — 改用 MA10 trail 後不再依賴 BB upper、適用非布林訊號（detector 4 本身不用 BB）。

## 後續

"""
    # Decide next-step recommendation based on verdicts
    if "actionable" in verdicts.get("detector 4: key_broker_signal (long) [C6]", ""):
        report += "- detector 4 long 達 actionable → 加入 daily scanner、納入 cross 升級規則\n"
    elif "reverse-signal" in verdicts.get("detector 4: key_broker_signal (long) [C6]", ""):
        report += "- detector 4 long 是反向訊號 → 寫入 skip 清單、不直接用、但作為「反向警示」可用\n"
    else:
        report += "- detector 4 long 樣本不足 / 不顯著 → watch-only、收集更長期資料再評估\n"

    if "actionable" in verdicts.get("cross 3way: bb ∩ chip ∩ broker (5d) [C6]", ""):
        report += "- cross 3way 達 actionable → 主推、升 cross_xiaoge_swing 三維對齊 A+ 等級\n"
    elif "reverse-signal" in verdicts.get("cross 3way: bb ∩ chip ∩ broker (5d) [C6]", ""):
        report += "- cross 3way 是反向訊號 → 寫入 skip 清單\n"
    else:
        report += "- cross 3way 樣本不足 → 持續觀察、不擅自合入主訊號\n"

    out_path = REPO / "docs/權證小哥/籌碼技術分析/backtest_phase3c.md"
    out_path.write_text(report)
    print(f"\nReport → {out_path}")


if __name__ == "__main__":
    main()
