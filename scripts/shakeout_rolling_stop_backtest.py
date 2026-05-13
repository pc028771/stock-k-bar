"""
Shakeout Strong — Exit Strategy Backtest
比較不同停損策略的實際持有結果

策略：
  A:  固定停損 prior_high_60 × 0.995（原始基準）
  B:  Rolling min N=5  closes × 0.995
  C:  Rolling min N=10 closes × 0.995
  D:  Rolling min N=20 closes × 0.995
  E1: Trailing stop from peak 10%
  E2: Trailing stop from peak 15%
  E3: Trailing stop from peak 20%
  E4: Trailing stop from peak 25%

訊號條件：shakeout_strong=True + strength≥9%，排除建材營造
進場：訊號日隔天開盤
出場：收盤 < 停損 → 次日開盤；最長持有 60 交易日
停損只升不降：所有策略均以 max(initial_stop, new_stop) 更新
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

DB_PATH = "/Users/howard/.four_seasons/data.sqlite"
SCANNER_CSV = Path("data/analysis/kline_course_backtest/breakout_daily_scanner.csv")
STOCK_INFO_CSV = Path("data/analysis/kline_course_backtest/finmind_stock_info_cache.csv")
OUT_DIR = Path("data/analysis/kline_course_backtest")
MAX_HOLD = 60
MIN_STRENGTH = 9.0


def load_signals() -> pd.DataFrame:
    df = pd.read_csv(SCANNER_CSV, parse_dates=["trade_date"])
    info = pd.read_csv(STOCK_INFO_CSV)[["stock_id", "industry_category"]].rename(
        columns={"stock_id": "ticker"}
    )
    info["ticker"] = info["ticker"].astype(str)
    df["ticker"] = df["ticker"].astype(str)

    df = df.merge(info.drop_duplicates("ticker"), on="ticker", how="left")

    mask = (
        df["shakeout_strong"].fillna(False)
        & (df["breakout_strength_pct"] >= MIN_STRENGTH)
        & (df["industry_category"] != "建材營造")
    )
    signals = df[mask].copy()
    print(f"Signals after filter: {len(signals)}")
    return signals


def load_bars(tickers: list[str]) -> pd.DataFrame:
    placeholders = ",".join("?" * len(tickers))
    query = f"""
        SELECT ticker, trade_date, open, high, low, close
        FROM standard_daily_bar
        WHERE ticker IN ({placeholders})
          AND is_usable = 1
          AND open > 0 AND close > 0
        ORDER BY ticker, trade_date
    """
    with sqlite3.connect(DB_PATH) as conn:
        bars = pd.read_sql_query(query, conn, params=tickers, parse_dates=["trade_date"])
    bars["ticker"] = bars["ticker"].astype(str)
    return bars


def simulate_trade(
    entry_open: float,
    initial_stop: float,
    forward_bars: pd.DataFrame,
    rolling_n: int | None = None,
    trail_pct: float | None = None,
    close_exit: bool = False,
) -> dict:
    """
    Simulate a single trade. Stop only goes up, never down.

    rolling_n=None, trail_pct=None → 固定停損 (initial_stop only)
    rolling_n=N                    → rolling min of last N closes × 0.995
    trail_pct=X                    → peak close × (1 - X)
    close_exit=True                → 收盤確認 + 盤後交易（收盤價出場，避開日內 wick）
    close_exit=False               → 條件單（開盤跳空用開盤價，盤中觸及用停損價）
    """
    stop = initial_stop
    peak_close = entry_open
    bars = forward_bars.reset_index(drop=True)

    for i, row in bars.iterrows():
        if rolling_n is not None and i >= rolling_n:
            recent_closes = bars.loc[i - rolling_n : i - 1, "close"]
            stop = max(stop, recent_closes.min() * 0.995)

        if trail_pct is not None:
            stop = max(stop, peak_close * (1 - trail_pct))

        if close_exit:
            # 收盤確認 + 盤後交易：收盤跌破停損 → 以收盤價出場
            if row["close"] < stop:
                return {"days": i + 1, "ret": row["close"] / entry_open - 1, "stopped_out": True}
        else:
            # 條件單：開盤跳空跌破 → 開盤價；盤中觸及 → 停損價
            if row["open"] <= stop:
                return {"days": i + 1, "ret": row["open"] / entry_open - 1, "stopped_out": True}
            if row["low"] <= stop:
                return {"days": i + 1, "ret": stop / entry_open - 1, "stopped_out": True}

        if i + 1 >= MAX_HOLD:
            return {"days": i + 1, "ret": row["close"] / entry_open - 1, "stopped_out": False}

        if trail_pct is not None:
            peak_close = max(peak_close, row["close"])

    last = bars.iloc[-1]
    return {"days": len(bars), "ret": last["close"] / entry_open - 1, "stopped_out": False}


def simulate_dynamic(entry_open: float, initial_stop: float, forward_bars: pd.DataFrame) -> dict:
    """
    動態策略（收盤確認＋盤後交易）：
    - 收盤價 < 進場價（賠錢）→ 用固定停損 initial_stop
    - 收盤價 ≥ 進場價（賺錢）→ 用 trailing 25%（max(initial_stop, peak×0.75)）
    """
    peak_close = entry_open
    bars = forward_bars.reset_index(drop=True)

    for i, row in bars.iterrows():
        if row["close"] >= entry_open:
            stop = max(initial_stop, peak_close * 0.75)
        else:
            stop = initial_stop

        if row["close"] < stop:
            return {"days": i + 1, "ret": row["close"] / entry_open - 1, "stopped_out": True}

        if i + 1 >= MAX_HOLD:
            return {"days": i + 1, "ret": row["close"] / entry_open - 1, "stopped_out": False}

        peak_close = max(peak_close, row["close"])

    last = bars.iloc[-1]
    return {"days": len(bars), "ret": last["close"] / entry_open - 1, "stopped_out": False}


def run_backtest(signals: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    bars_by_ticker = {t: g.sort_values("trade_date").reset_index(drop=True)
                      for t, g in bars.groupby("ticker")}

    roll_strategies = {"A_fixed": None, "B_roll5": 5, "C_roll10": 10, "D_roll20": 20}
    trail_strategies = {"E1_trail10": 0.10, "E2_trail15": 0.15, "E3_trail20": 0.20, "E4_trail25": 0.25}
    # 收盤確認 + 盤後交易版本（固定停損 & trailing 25%）
    close_strategies = {"F_fixed_close": (None, None), "G_trail25_close": (None, 0.25)}
    # 動態策略：賠錢用固定停損，賺錢用 trailing 25%
    dynamic_strategies = {"H_dynamic_close": True}

    results = []
    skipped = 0

    for _, sig in signals.iterrows():
        ticker = str(sig["ticker"])
        signal_date = sig["trade_date"]
        prior_high_60 = sig["prior_high_60"]
        initial_stop = prior_high_60 * 0.995

        if ticker not in bars_by_ticker:
            skipped += 1
            continue

        tb = bars_by_ticker[ticker]
        future = tb[tb["trade_date"] > signal_date].reset_index(drop=True)

        if len(future) < 2:
            skipped += 1
            continue

        entry_open = future.iloc[0]["open"]
        forward = future.iloc[1:].reset_index(drop=True)

        if len(forward) == 0:
            skipped += 1
            continue

        row = {
            "ticker": ticker,
            "signal_date": signal_date,
            "strength_pct": sig["breakout_strength_pct"],
            "prior_high_60": prior_high_60,
            "entry_open": entry_open,
        }

        for name, n in roll_strategies.items():
            r = simulate_trade(entry_open, initial_stop, forward.copy(), rolling_n=n)
            row[f"{name}_ret"] = r["ret"]
            row[f"{name}_days"] = r["days"]
            row[f"{name}_stopped"] = r["stopped_out"]

        for name, pct in trail_strategies.items():
            r = simulate_trade(entry_open, initial_stop, forward.copy(), trail_pct=pct)
            row[f"{name}_ret"] = r["ret"]
            row[f"{name}_days"] = r["days"]
            row[f"{name}_stopped"] = r["stopped_out"]

        for name, (rn, pct) in close_strategies.items():
            r = simulate_trade(entry_open, initial_stop, forward.copy(), rolling_n=rn, trail_pct=pct, close_exit=True)
            row[f"{name}_ret"] = r["ret"]
            row[f"{name}_days"] = r["days"]
            row[f"{name}_stopped"] = r["stopped_out"]

        # 動態策略：每天依持倉損益選擇停損方式
        r = simulate_dynamic(entry_open, initial_stop, forward.copy())
        row["H_dynamic_close_ret"] = r["ret"]
        row["H_dynamic_close_days"] = r["days"]
        row["H_dynamic_close_stopped"] = r["stopped_out"]

        results.append(row)

    print(f"Simulated: {len(results)}, Skipped: {skipped}")
    return pd.DataFrame(results)


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    strategies = ["A_fixed", "B_roll5", "C_roll10", "D_roll20",
                  "E1_trail10", "E2_trail15", "E3_trail20", "E4_trail25",
                  "F_fixed_close", "G_trail25_close", "H_dynamic_close"]
    labels = {
        "A_fixed":         "A  固定停損（條件單）",
        "B_roll5":         "B  Rolling Min N=5（條件單）",
        "C_roll10":        "C  Rolling Min N=10（條件單）",
        "D_roll20":        "D  Rolling Min N=20（條件單）",
        "E1_trail10":      "E1 Trailing 10%（條件單）",
        "E2_trail15":      "E2 Trailing 15%（條件單）",
        "E3_trail20":      "E3 Trailing 20%（條件單）",
        "E4_trail25":      "E4 Trailing 25%（條件單）",
        "F_fixed_close":   "F  固定停損（收盤確認＋盤後）",
        "G_trail25_close": "G  Trailing 25%（收盤確認＋盤後）",
        "H_dynamic_close": "H  動態：賠→固定 / 賺→Trail25%（收盤確認＋盤後）",
    }

    rows = []
    for s in strategies:
        rets = df[f"{s}_ret"].dropna()
        rows.append({
            "策略": labels[s],
            "樣本數": len(rets),
            "均報": f"{rets.mean()*100:+.1f}%",
            "中位數": f"{rets.median()*100:+.1f}%",
            "勝率": f"{(rets > 0).mean()*100:.1f}%",
            "平均持有(日)": f"{df[f'{s}_days'].mean():.1f}",
            "被停損出%": f"{df[f'{s}_stopped'].mean()*100:.1f}%",
            "最大虧損": f"{rets.min()*100:+.1f}%",
        })
    return pd.DataFrame(rows)


def print_markdown_table(df: pd.DataFrame) -> None:
    cols = list(df.columns)
    header = " | ".join(cols)
    sep = " | ".join(["---"] * len(cols))
    print(f"| {header} |")
    print(f"| {sep} |")
    for _, row in df.iterrows():
        print("| " + " | ".join(str(row[c]) for c in cols) + " |")


def main() -> None:
    signals = load_signals()
    tickers = signals["ticker"].unique().tolist()
    print(f"Loading bars for {len(tickers)} tickers...")
    bars = load_bars(tickers)

    df = run_backtest(signals, bars)

    summary = summarize(df)
    print("\n## Exit Strategy 比較（shakeout_strong + strength≥9%，排除建材營造）\n")
    print_markdown_table(summary)

    out = OUT_DIR / "shakeout_exit_strategy_detail.csv"
    df.to_csv(out, index=False)
    summary.to_csv(OUT_DIR / "shakeout_exit_strategy_comparison.csv", index=False)
    print(f"\nDetail saved to {out}")


if __name__ == "__main__":
    main()
