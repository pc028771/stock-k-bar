"""FinMind sanity backtest for high-hit advisor branches.

事件驅動、課程出場 — 不算固定 N 日報酬。

Usage:
    uv run python scripts/finmind_sanity_backtest.py
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

# ── Paths ────────────────────────────────────────────────────────────────────
WORKTREE = Path("/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power")
PHASE4_DB = WORKTREE / "data/analysis/kline_patterns/phase4_advisor_history.db"
PRICE_DB = Path("/Users/howard/.four_seasons/data.sqlite")
OUT_DIR = WORKTREE / "data/analysis/kline_patterns"
TRADES_CSV = OUT_DIR / "finmind_sanity_trades.csv"
REPORT_MD = OUT_DIR / "finmind_sanity_report.md"

TARGET_BRANCHES = ["B2_next_day_gap_filled", "B1_next_day_gap_fills_up"]
ACTION_TYPE = "exhaust_invalid"
SAFETY_CAP = 60  # trading days

# ── Load entry signals ────────────────────────────────────────────────────────
def load_signals() -> pd.DataFrame:
    conn = sqlite3.connect(PHASE4_DB)
    df = pd.read_sql_query(
        """
        SELECT r.ticker, r.trade_date AS signal_date, b.branch_id
        FROM advisor_branches b
        JOIN advisor_runs r ON b.run_id = r.run_id
        WHERE b.branch_id IN ('B2_next_day_gap_filled', 'B1_next_day_gap_fills_up')
          AND b.action_type = 'exhaust_invalid'
          AND b.matched_after_n_days >= 0
        """,
        conn
    )
    conn.close()
    # Deduplicate: same (ticker, signal_date) across branches → one trade
    df = df.sort_values(["ticker", "signal_date", "branch_id"])
    # Keep both branch_id for attribution but deduplicate trade entry
    # (branch_id priority: if both, pick B1 first by alphabetical → B1 < B2)
    df_dedup = df.drop_duplicates(subset=["ticker", "signal_date"], keep="first").copy()
    # Attach branch_ids (comma-joined) for multi-branch fires
    branch_map = df.groupby(["ticker", "signal_date"])["branch_id"].apply(lambda x: ",".join(sorted(x))).to_dict()
    df_dedup["branches_fired"] = df_dedup.apply(lambda r: branch_map[(r.ticker, r.signal_date)], axis=1)
    return df_dedup.reset_index(drop=True)


# ── Load price data ───────────────────────────────────────────────────────────
def load_prices(tickers: list) -> pd.DataFrame:
    placeholders = ",".join("?" * len(tickers))
    conn = sqlite3.connect(PRICE_DB)
    df = pd.read_sql_query(
        f"""
        SELECT ticker, trade_date, open, high, low, close
        FROM standard_daily_bar
        WHERE ticker IN ({placeholders})
          AND is_usable = 1
        ORDER BY ticker, trade_date
        """,
        conn,
        params=tickers
    )
    conn.close()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df


# ── Simulate one trade ────────────────────────────────────────────────────────
def simulate_trade(ticker: str, signal_date: str, price_df: pd.DataFrame) -> dict:
    """
    Entry: next trading day after signal_date (open price)
    Exit rules (course-based, event-driven):
      Cond1: close < entry_day_low  → exit next_open
      Cond2: black engulf (today.open >= entry_day.high AND today.close < entry_day.open AND today.close < today.open) → exit next_open
      Cond3: 攻擊失敗 (entry_day_open > prev_close AND entry_day_close <= prev_close) → exit today_close
      Timeout: 60 trading days → forced exit at close
    """
    sig_dt = pd.Timestamp(signal_date)
    ticker_df = price_df[price_df["ticker"] == ticker].sort_values("trade_date").reset_index(drop=True)

    if ticker_df.empty:
        return None

    # Find signal_date row
    sig_idx_arr = ticker_df.index[ticker_df["trade_date"] == sig_dt].tolist()
    if not sig_idx_arr:
        return None
    sig_idx = sig_idx_arr[0]

    # Entry = next trading day after signal
    entry_idx = sig_idx + 1
    if entry_idx >= len(ticker_df):
        return None

    entry_row = ticker_df.iloc[entry_idx]
    entry_price = entry_row["open"]
    if pd.isna(entry_price) or entry_price <= 0:
        return None

    entry_date = entry_row["trade_date"]
    entry_day_low = entry_row["low"]
    entry_day_high = entry_row["high"]
    entry_day_open = entry_row["open"]
    entry_day_close = entry_row["close"]

    # Check Cond3 on entry day itself
    # 攻擊失敗: entry_day_open > prev_close AND entry_day_close <= prev_close
    prev_close = ticker_df.iloc[sig_idx]["close"]
    if (not pd.isna(entry_day_open) and not pd.isna(prev_close) and
            entry_day_open > prev_close and entry_day_close <= prev_close):
        exit_price = entry_day_close
        ret = (exit_price - entry_price) / entry_price * 100
        return {
            "ticker": ticker,
            "signal_date": signal_date,
            "entry_date": str(entry_date.date()),
            "entry_price": round(entry_price, 2),
            "exit_date": str(entry_date.date()),
            "exit_price": round(exit_price, 2),
            "exit_cond": "cond3_attack_fail",
            "hold_days": 0,
            "ret_pct": round(ret, 4),
            "is_win": ret > 0,
        }

    # Walk forward from next day
    max_idx = min(entry_idx + SAFETY_CAP, len(ticker_df) - 1)

    for i in range(entry_idx + 1, max_idx + 1):
        row = ticker_df.iloc[i]
        today_open = row["open"]
        today_high = row["high"]
        today_low = row["low"]
        today_close = row["close"]
        today_date = row["trade_date"]
        hold_days = i - entry_idx

        # Safety cap check (timeout on this day)
        if hold_days >= SAFETY_CAP:
            exit_price = today_close
            ret = (exit_price - entry_price) / entry_price * 100
            return {
                "ticker": ticker,
                "signal_date": signal_date,
                "entry_date": str(entry_date.date()),
                "entry_price": round(entry_price, 2),
                "exit_date": str(today_date.date()),
                "exit_price": round(exit_price, 2),
                "exit_cond": "timeout",
                "hold_days": hold_days,
                "ret_pct": round(ret, 4),
                "is_win": None,  # timeout = not counted as win/loss
            }

        # Cond3: 攻擊失敗 — gap up open but close fills gap (today is not entry day here)
        prev_row = ticker_df.iloc[i - 1]
        prev_close_i = prev_row["close"]
        if (not pd.isna(today_open) and not pd.isna(prev_close_i) and
                today_open > prev_close_i and today_close <= prev_close_i):
            exit_price = today_close
            ret = (exit_price - entry_price) / entry_price * 100
            return {
                "ticker": ticker,
                "signal_date": signal_date,
                "entry_date": str(entry_date.date()),
                "entry_price": round(entry_price, 2),
                "exit_date": str(today_date.date()),
                "exit_price": round(exit_price, 2),
                "exit_cond": "cond3_attack_fail",
                "hold_days": hold_days,
                "ret_pct": round(ret, 4),
                "is_win": ret > 0,
            }

        # Cond1: close < entry_day_low → exit next open
        if today_close < entry_day_low:
            # exit at NEXT day's open
            next_i = i + 1
            if next_i < len(ticker_df):
                next_row = ticker_df.iloc[next_i]
                exit_price = next_row["open"]
                exit_date = next_row["trade_date"]
            else:
                exit_price = today_close
                exit_date = today_date
            if pd.isna(exit_price) or exit_price <= 0:
                exit_price = today_close
                exit_date = today_date
            ret = (exit_price - entry_price) / entry_price * 100
            return {
                "ticker": ticker,
                "signal_date": signal_date,
                "entry_date": str(entry_date.date()),
                "entry_price": round(entry_price, 2),
                "exit_date": str(exit_date.date()),
                "exit_price": round(exit_price, 2),
                "exit_cond": "cond1_break_low",
                "hold_days": hold_days,
                "ret_pct": round(ret, 4),
                "is_win": ret > 0,
            }

        # Cond2: black engulf — today.open >= entry_day.high AND today.close < entry_day.open AND today.close < today.open
        if (not pd.isna(today_open) and not pd.isna(today_close) and
                today_open >= entry_day_high and
                today_close < entry_day_open and
                today_close < today_open):
            next_i = i + 1
            if next_i < len(ticker_df):
                next_row = ticker_df.iloc[next_i]
                exit_price = next_row["open"]
                exit_date = next_row["trade_date"]
            else:
                exit_price = today_close
                exit_date = today_date
            if pd.isna(exit_price) or exit_price <= 0:
                exit_price = today_close
                exit_date = today_date
            ret = (exit_price - entry_price) / entry_price * 100
            return {
                "ticker": ticker,
                "signal_date": signal_date,
                "entry_date": str(entry_date.date()),
                "entry_price": round(entry_price, 2),
                "exit_date": str(exit_date.date()),
                "exit_price": round(exit_price, 2),
                "exit_cond": "cond2_black_engulf",
                "hold_days": hold_days,
                "ret_pct": round(ret, 4),
                "is_win": ret > 0,
            }

    # Should not reach here (safety cap handles last day)
    return None


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("Loading entry signals...")
    signals = load_signals()
    print(f"  Total unique (ticker, signal_date) pairs: {len(signals)}")

    tickers = signals["ticker"].unique().tolist()
    print(f"  Unique tickers: {len(tickers)}")

    print("Loading price data...")
    prices = load_prices(tickers)
    covered = set(prices["ticker"].unique())
    missing = set(tickers) - covered
    print(f"  Covered tickers: {len(covered)}, Missing: {len(missing)}")

    print("Simulating trades...")
    trades = []
    skipped = 0
    for _, row in signals.iterrows():
        if row["ticker"] not in covered:
            skipped += 1
            continue
        result = simulate_trade(row["ticker"], row["signal_date"], prices)
        if result is None:
            skipped += 1
            continue
        result["branches_fired"] = row["branches_fired"]
        trades.append(result)

    print(f"  Trades simulated: {len(trades)}, Skipped: {skipped}")

    df_trades = pd.DataFrame(trades)
    df_trades.to_csv(TRADES_CSV, index=False)
    print(f"  Saved trades CSV: {TRADES_CSV}")

    # ── Aggregate ──────────────────────────────────────────────────────────────
    def branch_label(row_branches):
        """Label a trade by which branch(es) fired."""
        if "B1_next_day_gap_fills_up" in row_branches and "B2_next_day_gap_filled" in row_branches:
            return "both"
        elif "B1_next_day_gap_fills_up" in row_branches:
            return "B1_only"
        else:
            return "B2_only"

    df_trades["branch_label"] = df_trades["branches_fired"].apply(branch_label)

    def stats_for(df_sub, label):
        non_timeout = df_sub[df_sub["exit_cond"] != "timeout"]
        n_total = len(df_sub)
        n_timeout = (df_sub["exit_cond"] == "timeout").sum()
        n_evaluated = len(non_timeout)
        win_rate = non_timeout["is_win"].mean() if n_evaluated > 0 else float("nan")
        avg_ret = non_timeout["ret_pct"].mean() if n_evaluated > 0 else float("nan")
        med_ret = non_timeout["ret_pct"].median() if n_evaluated > 0 else float("nan")
        std_ret = non_timeout["ret_pct"].std() if n_evaluated > 0 else float("nan")
        max_dd = non_timeout["ret_pct"].min() if n_evaluated > 0 else float("nan")
        max_gain = non_timeout["ret_pct"].max() if n_evaluated > 0 else float("nan")
        avg_hold = df_sub["hold_days"].mean()
        med_hold = df_sub["hold_days"].median()

        cond_dist = df_sub["exit_cond"].value_counts().to_dict()

        return {
            "label": label,
            "n_total": n_total,
            "n_timeout": n_timeout,
            "n_evaluated": n_evaluated,
            "win_rate_pct": round(win_rate * 100, 1) if not np.isnan(win_rate) else "N/A",
            "avg_ret_pct": round(avg_ret, 2) if not np.isnan(avg_ret) else "N/A",
            "median_ret_pct": round(med_ret, 2) if not np.isnan(med_ret) else "N/A",
            "std_ret_pct": round(std_ret, 2) if not np.isnan(std_ret) else "N/A",
            "max_dd_pct": round(max_dd, 2) if not np.isnan(max_dd) else "N/A",
            "max_gain_pct": round(max_gain, 2) if not np.isnan(max_gain) else "N/A",
            "avg_hold_days": round(avg_hold, 1),
            "median_hold_days": round(med_hold, 1),
            "exit_dist": cond_dist,
        }

    # Per-branch stats (attribute to original branch, not dedup label)
    # For single-branch attributing: a trade with "both" counts toward both B1 and B2
    def get_branch_df(branch_id):
        return df_trades[df_trades["branches_fired"].str.contains(branch_id)]

    stats_b1 = stats_for(get_branch_df("B1_next_day_gap_fills_up"), "B1_next_day_gap_fills_up")
    stats_b2 = stats_for(get_branch_df("B2_next_day_gap_filled"), "B2_next_day_gap_filled")
    stats_all = stats_for(df_trades, "all_trades")

    # ── Write report ──────────────────────────────────────────────────────────
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    def fmt_stat(s):
        exit_str = "\n".join(f"    - {k}: {v}" for k, v in s["exit_dist"].items())
        return f"""
### {s["label"]}

| 指標 | 值 |
|---|---|
| n_total (trades) | {s["n_total"]} |
| n_timeout (60d cap) | {s["n_timeout"]} |
| n_evaluated (non-timeout) | {s["n_evaluated"]} |
| **win_rate** | **{s["win_rate_pct"]}%** |
| avg_return | {s["avg_ret_pct"]}% |
| median_return | {s["median_ret_pct"]}% |
| std_return | {s["std_ret_pct"]}% |
| max_DD | {s["max_dd_pct"]}% |
| max_gain | {s["max_gain_pct"]}% |
| avg_hold_days | {s["avg_hold_days"]} d |
| median_hold_days | {s["median_hold_days"]} d |

**出場條件分布：**
{exit_str}
"""

    phase4_hit_rates = {
        "B1_next_day_gap_fills_up": "83.0% (n=3949)",
        "B2_next_day_gap_filled": "84.2% (n=2737)",
    }

    b1_win = stats_b1["win_rate_pct"]
    b2_win = stats_b2["win_rate_pct"]

    report = f"""# FinMind Sanity Backtest Report

生成時間：{now}

## 說明

- Entry signal：Phase 4.3 advisor_branches，兩個高命中率 branch（exhaust_invalid）
- Entry timing：signal_date 隔日開盤（next_open）
- Exit rules：課程事件驅動（禁用固定 N 日報酬）
  - **Cond1**：收盤跌破進場日 low → 隔日開盤出場
  - **Cond2**：大黑K包覆（today.open ≥ entry.high AND today.close < entry.open AND today.close < today.open）→ 隔日開盤出場
  - **Cond3**：攻擊失敗（gap-up open 當日收盤回補）→ 當日收盤出場
  - **Timeout**：持有 60 交易日未觸發 → 強制結算（不計勝負）
- 資料來源：`~/.four_seasons/data.sqlite` standard_daily_bar（FinMind）
- 同一 (ticker, signal_date) 兩個 branch 都觸發 → 視為一筆 trade

---

## Phase 4.3 命中率 vs 實際勝率對比

| Branch | Phase 4.3 hit_rate | 實際 win_rate | 差異方向 |
|---|---|---|---|
| B1_next_day_gap_fills_up | {phase4_hit_rates["B1_next_day_gap_fills_up"]} | {b1_win}% | {"⚠️ 劇本≠賺錢" if isinstance(b1_win, float) and b1_win < 60 else "✅ 一致" if isinstance(b1_win, (int,float)) else "N/A"} |
| B2_next_day_gap_filled | {phase4_hit_rates["B2_next_day_gap_filled"]} | {b2_win}% | {"⚠️ 劇本≠賺錢" if isinstance(b2_win, float) and b2_win < 60 else "✅ 一致" if isinstance(b2_win, (int,float)) else "N/A"} |

> Phase 4.3 hit_rate = 「劇本在 matched_after_n_days 內成真」的比率（非獲利勝率）。
> 本 backtest win_rate = 依課程出場後實際報酬 > 0 的比率。

---

## 各 Branch 統計

{fmt_stat(stats_b1)}

{fmt_stat(stats_b2)}

{fmt_stat(stats_all)}

---

## 輸出檔案

- Trades CSV: `data/analysis/kline_patterns/finmind_sanity_trades.csv`
- Report: `data/analysis/kline_patterns/finmind_sanity_report.md`
"""

    REPORT_MD.write_text(report, encoding="utf-8")
    print(f"  Saved report: {REPORT_MD}")

    # Print summary to stdout
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    for s in [stats_b1, stats_b2, stats_all]:
        print(f"\n{s['label']}:")
        print(f"  n_total={s['n_total']} n_evaluated={s['n_evaluated']} n_timeout={s['n_timeout']}")
        print(f"  win_rate={s['win_rate_pct']}%  avg_ret={s['avg_ret_pct']}%  median_ret={s['median_ret_pct']}%")
        print(f"  hold_days: avg={s['avg_hold_days']} median={s['median_hold_days']}")
        print(f"  exit_dist: {s['exit_dist']}")


if __name__ == "__main__":
    main()
