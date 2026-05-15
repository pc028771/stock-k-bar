from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


ROUND_TRIP_COST = 0.00585  # 手續費 + 交易稅
OUT_DIR = Path("data/analysis/kline_course_backtest")

# E1 跳空回補：最小跳空門檻（肉眼在日線圖上可見）
# 課程定義跳空為「不計代價的買進」，0.1% 的細微差距不算跳空
GAP_MIN_PCT = 0.01  # 1%

# E2 暗夜雙星最小實體門檻
REVERSAL_BLACK_BODY_PCT = 0.04


def _check_exits(
    bars: pd.DataFrame,
    entry_open: float,
    breakout_bar_low: float,
) -> tuple[str, pd.Timestamp, float, int]:
    """逐日掃描出場條件，回傳 (exit_reason, exit_date, exit_price, hold_days)。

    bars: 進場日之後的所有日K（含 prev_close, prev_low, prior_low_20 欄位），已排序。
    exit_price = 出場日的 open（隔日開盤），若到資料末日則用末日 close。
    """
    neckline_pending = False  # E3 等待隔日確認

    for i in range(len(bars)):
        row = bars.iloc[i]
        hold_days = i + 1

        # E3 確認日（前一日已收破頸線，今日再確認）
        if neckline_pending:
            if row["close"] < row["prior_low_20"]:
                # 確認跌破：出場在今日的隔日開盤
                exit_price, exit_date = _next_open(bars, i)
                return "neckline_break", exit_date, exit_price, hold_days
            neckline_pending = False  # 收回 → 假跌破，繼續持有

        # E1 跳空回補（需≥1%跳空才算，避免微小開盤差誤判）
        gap_up = row["prev_close"] > 0 and row["open"] >= row["prev_close"] * (1 + GAP_MIN_PCT)
        if gap_up and row["close"] < row["prev_close"]:
            exit_price, exit_date = _next_open(bars, i)
            return "gap_fill", exit_date, exit_price, hold_days

        # E2 暗夜雙星（黑K + 開在前日低點以下 + 長實體）
        body_pct = (row["open"] - row["close"]) / row["open"] if row["open"] > 0 else 0.0
        if (row["close"] < row["open"]
                and row["open"] < row["prev_low"]
                and body_pct >= REVERSAL_BLACK_BODY_PCT):
            exit_price, exit_date = _next_open(bars, i)
            return "reversal_black_k", exit_date, exit_price, hold_days

        # E4 突破K低點跌破
        if row["close"] < breakout_bar_low:
            exit_price, exit_date = _next_open(bars, i)
            return "breakout_low_break", exit_date, exit_price, hold_days

        # E3 頸線跌破（等待明日確認）
        if row["close"] < row["prior_low_20"]:
            neckline_pending = True

    # 無出場訊號：持有至末日，用末日收盤計算
    last = bars.iloc[-1]
    return "open", pd.Timestamp(last.name), float(last["close"]), len(bars)


def _next_open(bars: pd.DataFrame, idx: int) -> tuple[float, pd.Timestamp]:
    """取 idx 的隔日開盤；若已是最後一日則用當日收盤。"""
    if idx + 1 < len(bars):
        nxt = bars.iloc[idx + 1]
        return float(nxt["open"]), pd.Timestamp(nxt.name)
    last = bars.iloc[idx]
    return float(last["close"]), pd.Timestamp(last.name)


def simulate_exits(df: pd.DataFrame) -> pd.DataFrame:
    """對每個 breakout_attack 訊號模擬課程出場條件，回傳交易結果 DataFrame。

    輸入：add_signals(add_features(load_bars())) 的完整 DataFrame。
    所需欄位：ticker, trade_date, open, high, low, close, prev_close, prev_low,
               prior_low_20, entry_open_1d, breakout_attack。

    回傳欄位：
        ticker, signal_date, entry_open, breakout_bar_low,
        exit_reason, exit_date, exit_price, hold_days,
        trade_return, trade_return_net
    """
    required = {
        "ticker", "trade_date", "open", "high", "low", "close",
        "prev_close", "prev_low", "prior_low_20", "entry_open_1d", "breakout_attack",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"simulate_exits: 缺少欄位 {missing}")

    signals = df[df["breakout_attack"]].copy()
    signals = signals.dropna(subset=["entry_open_1d", "prior_low_20"])
    signals = signals[signals["entry_open_1d"] > 0]

    records = []
    for ticker, group in df.groupby("ticker", sort=False):
        group = group.set_index("trade_date").sort_index()
        sig_group = signals[signals["ticker"] == ticker].set_index("trade_date").sort_index()
        if sig_group.empty:
            continue

        dates = group.index
        for sig_date, sig_row in sig_group.iterrows():
            # 進場日在訊號日次日（entry_open_1d 已計算）
            entry_open = float(sig_row["entry_open_1d"])
            breakout_bar_low = float(sig_row["low"])

            # 取進場日之後的所有日K
            after_mask = dates > sig_date
            bars_after = group.loc[after_mask, [
                "open", "high", "low", "close",
                "prev_close", "prev_low", "prior_low_20",
            ]]
            if bars_after.empty:
                continue

            reason, exit_date, exit_price, hold_days = _check_exits(
                bars_after, entry_open, breakout_bar_low
            )
            trade_return = exit_price / entry_open - 1
            records.append({
                "ticker": ticker,
                "signal_date": sig_date,
                "entry_open": round(entry_open, 2),
                "breakout_bar_low": round(breakout_bar_low, 2),
                "exit_reason": reason,
                "exit_date": exit_date,
                "exit_price": round(exit_price, 2),
                "hold_days": hold_days,
                "trade_return": round(trade_return, 6),
                "trade_return_net": round(trade_return - ROUND_TRIP_COST, 6),
            })

    return pd.DataFrame(records)


def summarize_exits(trades: pd.DataFrame) -> pd.DataFrame:
    """依出場原因分組，計算平均報酬、勝率、平均持有天數。"""
    if trades.empty:
        return pd.DataFrame()
    rows = []
    for reason, grp in trades.groupby("exit_reason"):
        valid = grp.dropna(subset=["trade_return_net"])
        rows.append({
            "exit_reason": reason,
            "n": int(len(valid)),
            "mean_return_pct": round(float(valid["trade_return_net"].mean() * 100), 3),
            "win_rate_pct": round(float((valid["trade_return_net"] > 0).mean() * 100), 2),
            "mean_hold_days": round(float(valid["hold_days"].mean()), 1),
            "median_hold_days": int(valid["hold_days"].median()),
        })
    return pd.DataFrame(rows).sort_values("mean_return_pct", ascending=False)


def main() -> None:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from kline_course_backtest import add_features, add_signals, load_bars

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = add_signals(add_features(load_bars()))
    trades = simulate_exits(df)
    summary = summarize_exits(trades)

    trades_path = OUT_DIR / "exit_simulation_trades.csv"
    summary_path = OUT_DIR / "exit_simulation_summary.csv"
    trades.to_csv(trades_path, index=False)
    summary.to_csv(summary_path, index=False)

    print(f"訊號數：{len(trades)}")
    print(summary.to_string(index=False))
    print(trades_path)
    print(summary_path)


if __name__ == "__main__":
    main()
