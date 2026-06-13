"""Backtest xiaoge_bb_squeeze_breakout on 2026-05-01 ~ 2026-06-12.

Rules:
- Entry: signal day t → enter at open of t+1 (next-day-open execution)
- Exit (course-defined): when close < bb_upper, exit at open of next day
- Max hold: 30 trading days (safety cap, not course-defined)
- No stop loss (course doesn't define one; leave_upper_band serves as both
  profit-take and risk control)

Output:
- per-trade CSV: data/analysis/xiaoge/backtest/bb_squeeze_trades.csv
- summary markdown: docs/權證小哥/籌碼技術分析/backtest_bb_squeeze.md
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from scripts.xiaoge.bars import load_bars, add_squeeze_flag, vol_ma5
from scripts.xiaoge.entry.bb_squeeze_breakout import detect as detect_entry
from scripts.xiaoge.exit.leave_upper_band import should_exit


REPO = Path(__file__).resolve().parents[2]
OUT_TRADES = REPO / "data/analysis/xiaoge/backtest/bb_squeeze_trades.csv"
OUT_REPORT = REPO / "docs/權證小哥/籌碼技術分析/backtest_bb_squeeze.md"


def run_backtest(start: str = "2026-05-01", end: str = "2026-06-12",
                 squeeze_threshold: float = 12.0,
                 squeeze_lookback: int = 10,
                 vol_multiple: float = 1.5,
                 breakout_mode: str = "any",
                 max_hold: int = 30,
                 tickers: list[str] | None = None) -> pd.DataFrame:
    df = load_bars(start, end, tickers=tickers)
    df = add_squeeze_flag(df, lookback=squeeze_lookback, threshold=squeeze_threshold)

    signals = detect_entry(df, breakout_mode=breakout_mode, vol_multiple=vol_multiple)
    df["signal"] = signals

    # Filter signals within backtest window (after warm-up)
    in_window = df["trade_date"] >= pd.Timestamp(start)
    signal_rows = df[df["signal"] & in_window].copy()
    print(f"Signal count in window: {len(signal_rows)}")

    # Walk each ticker → for each signal, simulate trade
    trades = []
    grp = df.groupby("ticker")
    for _, row in signal_rows.iterrows():
        ticker = row["ticker"]
        sig_date = row["trade_date"]
        sub = grp.get_group(ticker).reset_index(drop=True)
        sig_idx = sub.index[sub["trade_date"] == sig_date]
        if len(sig_idx) == 0 or sig_idx[0] + 1 >= len(sub):
            continue  # no next bar
        entry_idx = sig_idx[0] + 1
        entry_bar = sub.iloc[entry_idx]
        entry_price = entry_bar["open"]
        if pd.isna(entry_price) or entry_price <= 0:
            continue

        # Walk forward until exit
        exit_idx = None
        for i in range(entry_idx, min(entry_idx + max_hold, len(sub))):
            bar = sub.iloc[i]
            if i > entry_idx and should_exit(bar["close"], bar["bb_upper"]):
                exit_idx = i + 1 if (i + 1) < len(sub) else i
                break
        if exit_idx is None:
            exit_idx = min(entry_idx + max_hold, len(sub) - 1)
        exit_bar = sub.iloc[exit_idx]
        exit_price = exit_bar["open"]
        if pd.isna(exit_price) or exit_price <= 0:
            exit_price = exit_bar["close"]

        ret_pct = (exit_price - entry_price) / entry_price * 100
        hold_days = exit_idx - entry_idx

        trades.append({
            "ticker": ticker,
            "signal_date": sig_date.strftime("%Y-%m-%d"),
            "entry_date": entry_bar["trade_date"].strftime("%Y-%m-%d"),
            "entry_price": round(entry_price, 2),
            "exit_date": exit_bar["trade_date"].strftime("%Y-%m-%d"),
            "exit_price": round(exit_price, 2),
            "hold_days": hold_days,
            "ret_pct": round(ret_pct, 2),
            "signal_bb_width": round(row["bb_width_pct"], 2) if pd.notna(row["bb_width_pct"]) else None,
            "signal_close": round(row["close"], 2),
        })

    trades_df = pd.DataFrame(trades)
    OUT_TRADES.parent.mkdir(parents=True, exist_ok=True)
    trades_df.to_csv(OUT_TRADES, index=False)
    print(f"Wrote {len(trades_df)} trades → {OUT_TRADES}")
    return trades_df


def summarize(trades: pd.DataFrame, params: dict) -> str:
    if len(trades) == 0:
        return "No trades."
    avg_ret = trades["ret_pct"].mean()
    median_ret = trades["ret_pct"].median()
    win_rate = (trades["ret_pct"] > 0).mean() * 100
    max_ret = trades["ret_pct"].max()
    min_ret = trades["ret_pct"].min()
    avg_hold = trades["hold_days"].mean()
    by_ticker = trades.groupby("ticker").size().sort_values(ascending=False).head(10)
    top_winners = trades.nlargest(10, "ret_pct")[["ticker", "signal_date", "entry_price", "exit_price", "hold_days", "ret_pct"]]
    top_losers = trades.nsmallest(10, "ret_pct")[["ticker", "signal_date", "entry_price", "exit_price", "hold_days", "ret_pct"]]
    return f"""# xiaoge_bb_squeeze_breakout — backtest report

> Source: `scripts/xiaoge/backtest_bb_squeeze.py`
> Detector: `scripts/xiaoge/entry/bb_squeeze_breakout.py`
> Exit rule: `scripts/xiaoge/exit/leave_upper_band.py` (close < bb_upper)
> 課程來源：ch06-ch08, ch12 + ch07/ch13 出場規則

## 參數

| 參數 | 值 | 來源 |
|---|---|---|
| backtest 區間 | {params['start']} ~ {params['end']} | user 指定 |
| squeeze_threshold (bb_width_pct ≤) | {params['squeeze_threshold']} | 老師「正常 10 / 寬 20」延伸、加 2 容差 |
| squeeze_lookback (連續 N 日) | {params['squeeze_lookback']} | detector_spec 建議 |
| vol_multiple (open_breakout 量倍) | {params['vol_multiple']} | detector_spec |
| breakout_mode | {params['breakout_mode']} | 升龍拳 ∪ 開布林表態 |
| max_hold (safety cap) | {params['max_hold']} | 非課程、防止無上限持有 |

## 結果摘要

| 指標 | 值 |
|---|---|
| **訊號數（=交易數）** | **{len(trades)}** |
| **平均報酬率** | **{avg_ret:.2f}%** |
| 中位數報酬率 | {median_ret:.2f}% |
| **勝率（>0%）** | **{win_rate:.1f}%** |
| 最佳單筆 | {max_ret:.2f}% |
| 最差單筆 | {min_ret:.2f}% |
| 平均持有 | {avg_hold:.1f} 天 |

## 觸發次數 Top 10 (依 ticker)

{by_ticker.to_string()}

## Top 10 winners

{top_winners.to_string(index=False)}

## Top 10 losers

{top_losers.to_string(index=False)}

## 詳細交易

完整 CSV：`data/analysis/xiaoge/backtest/bb_squeeze_trades.csv`

## 已知限制

1. **樣本期太短** — 2026-05-01 ~ 2026-06-12 只有 30 個交易日、訊號數量不足以做統計顯著性判斷。
2. **沒有 stop loss** — 課程沒明說停損、若遇大跌會吃滿 30 日 max_hold；未來可在 extras/ 加結構停損試。
3. **沒有 universe filter** — 全市場、可能有低流動性股票造成 noise。
4. **訊號生效窗** — bb_in_squeeze 需要 10 天 warm-up、所以 5/初的 squeeze 判定靠 4 月底資料、warm-up 已含 120 天。
5. **沒對照組** — 跟 kline_course / zhuli 的同期表現對比待後續做。

## 後續

- Phase 2 完成、可進 Phase 3（其他 detector）
- 參數調校（threshold 12 → 10 試）放 extras/
- 跟 cross_scanner / scanner_q1_top10 對照看 detector 是否搶到名單上的股
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-05-01")
    ap.add_argument("--end", default="2026-06-12")
    ap.add_argument("--squeeze-threshold", type=float, default=12.0)
    ap.add_argument("--squeeze-lookback", type=int, default=10)
    ap.add_argument("--vol-multiple", type=float, default=1.5)
    ap.add_argument("--breakout-mode", choices=["any", "shenglongquan", "open_breakout"],
                    default="any")
    ap.add_argument("--max-hold", type=int, default=30)
    ap.add_argument("--tickers", nargs="*", default=None)
    args = ap.parse_args()

    params = {
        "start": args.start,
        "end": args.end,
        "squeeze_threshold": args.squeeze_threshold,
        "squeeze_lookback": args.squeeze_lookback,
        "vol_multiple": args.vol_multiple,
        "breakout_mode": args.breakout_mode,
        "max_hold": args.max_hold,
    }
    trades = run_backtest(**params, tickers=args.tickers)
    report = summarize(trades, params)
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text(report)
    print(f"Report → {OUT_REPORT}")
    print("\n" + report.split("## 結果摘要")[1].split("## 觸發次數")[0])


if __name__ == "__main__":
    main()
