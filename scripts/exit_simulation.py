from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


ROUND_TRIP_COST = 0.00585  # 手續費 + 交易稅
OUT_DIR = Path("data/analysis/kline_course_backtest")
TAIEX_PATH = OUT_DIR / "taiex_daily.csv"

# E1 跳空回補：超額跳空門檻
# 用 (stock_gap - market_gap) 排除大盤整體帶動，只看個股自身的攻擊跳空
# 課程定義「不計代價的買進」，應相對於市場背景判斷
EXCESS_GAP_MIN_PCT = 0.02  # 預設 2%，待掃描決定

# E2 暗夜雙星最小實體門檻
REVERSAL_BLACK_BODY_PCT = 0.04


def load_taiex() -> dict[pd.Timestamp, float]:
    """載入 TAIEX 每日開盤跳幅（open/prev_close - 1），回傳 {date: open_gap_pct}。"""
    if not TAIEX_PATH.exists():
        return {}
    taiex = pd.read_csv(TAIEX_PATH, parse_dates=["date"])
    taiex = taiex.sort_values("date")
    taiex["market_open_ret"] = taiex["open"] / taiex["close"].shift(1) - 1
    return dict(zip(taiex["date"], taiex["market_open_ret"].fillna(0)))


def _check_exits(
    bars: pd.DataFrame,
    entry_open: float,
    breakout_bar_low: float,
    excess_gap_min_pct: float = EXCESS_GAP_MIN_PCT,
    market_open_ret: dict | None = None,
) -> tuple[str, pd.Timestamp, float, int]:
    """逐日掃描出場條件，回傳 (exit_reason, exit_date, exit_price, hold_days)。

    bars: 進場日之後的所有日K（含 prev_close, prev_low, prior_low_20 欄位），已排序。
    exit_price = 出場日的 open（隔日開盤），若到資料末日則用末日 close。
    excess_gap_min_pct: E1 超額跳空門檻（個股跳空 - 大盤跳空 >= 此值才算）。
    market_open_ret: {date: market_gap_pct}，無則視大盤跳空為 0。
    """
    if market_open_ret is None:
        market_open_ret = {}
    neckline_pending = False  # E3 等待隔日確認

    for i in range(len(bars)):
        row = bars.iloc[i]
        hold_days = i + 1
        date = bars.index[i]

        # E3 確認日（前一日已收破頸線，今日再確認）
        if neckline_pending:
            if row["close"] < row["prior_low_20"]:
                exit_price, exit_date = _next_open(bars, i)
                return "neckline_break", exit_date, exit_price, hold_days
            neckline_pending = False  # 收回 → 假跌破，繼續持有

        # E1 超額跳空回補
        # 個股跳空幅度 - 大盤開盤跳幅 >= excess_gap_min_pct，且當日收回前收
        mkt_gap = float(market_open_ret.get(date, 0.0) or 0.0)
        stock_gap = (row["open"] / row["prev_close"] - 1) if row["prev_close"] > 0 else 0.0
        excess_gap = stock_gap - mkt_gap
        gap_up = excess_gap >= excess_gap_min_pct
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

    # 無出場訊號：持有至末日，用末日開盤價（上班族只能在開盤執行）
    last = bars.iloc[-1]
    last_price = float(last["open"]) if last["open"] > 0 else float(last["close"])
    return "open", pd.Timestamp(last.name), last_price, len(bars)


def _next_open(bars: pd.DataFrame, idx: int) -> tuple[float, pd.Timestamp]:
    """取 idx 的隔日開盤；若已是最後一日則用當日收盤。"""
    if idx + 1 < len(bars):
        nxt = bars.iloc[idx + 1]
        return float(nxt["open"]), pd.Timestamp(nxt.name)
    last = bars.iloc[idx]
    return float(last["close"]), pd.Timestamp(last.name)


def simulate_exits(df: pd.DataFrame, excess_gap_min_pct: float = EXCESS_GAP_MIN_PCT) -> pd.DataFrame:
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

    # 載入大盤開盤跳幅（用於超額跳空計算）
    mkt_open_ret = load_taiex()

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
            entry_open = float(sig_row["entry_open_1d"])
            breakout_bar_low = float(sig_row["low"])

            after_mask = dates > sig_date
            bars_after = group.loc[after_mask, [
                "open", "high", "low", "close",
                "prev_close", "prev_low", "prior_low_20",
            ]]
            if bars_after.empty:
                continue

            reason, exit_date, exit_price, hold_days = _check_exits(
                bars_after, entry_open, breakout_bar_low,
                excess_gap_min_pct=excess_gap_min_pct,
                market_open_ret=mkt_open_ret,
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


def sweep_gap_threshold(
    df: pd.DataFrame,
    thresholds: list[float] | None = None,
) -> pd.DataFrame:
    """掃描不同跳空門檻對出場分布的影響。

    回傳每個門檻下各出場原因的統計，用於決定最合理的 GAP_MIN_PCT。
    """
    if thresholds is None:
        thresholds = [i / 200 for i in range(1, 11)]  # 0.5% ~ 5%（超額跳空門檻）

    rows = []
    for pct in thresholds:
        trades = simulate_exits(df, excess_gap_min_pct=pct)
        for reason, grp in trades.groupby("exit_reason"):
            valid = grp.dropna(subset=["trade_return_net"])
            rows.append({
                "gap_pct": pct,
                "exit_reason": reason,
                "n": int(len(valid)),
                "mean_return_pct": round(float(valid["trade_return_net"].mean() * 100), 3),
                "win_rate_pct": round(float((valid["trade_return_net"] > 0).mean() * 100), 2),
                "mean_hold_days": round(float(valid["hold_days"].mean()), 1),
            })
    return pd.DataFrame(rows)


def main() -> None:
    import argparse
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from kline_course_backtest import add_features, add_signals, load_bars

    parser = argparse.ArgumentParser()
    parser.add_argument("--sweep", action="store_true", help="掃描 1%%~10%% 跳空門檻")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = add_signals(add_features(load_bars()))

    if args.sweep:
        sweep = sweep_gap_threshold(df)
        sweep_path = OUT_DIR / "exit_gap_threshold_sweep.csv"
        sweep.to_csv(sweep_path, index=False)
        # 顯示 gap_fill 在各門檻下的均報與勝率
        gf = sweep[sweep["exit_reason"] == "gap_fill"][
            ["gap_pct", "n", "mean_return_pct", "win_rate_pct", "mean_hold_days"]
        ].reset_index(drop=True)
        print("=== gap_fill 在不同門檻下的表現 ===")
        print(gf.to_string(index=False))
        print(sweep_path)
        return

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
