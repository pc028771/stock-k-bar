"""Four-Seasons backtest v7 — 真實操作版（portfolio simulation + 水位 + P&L $）.

借 `scripts/zhuli/tools/backtest_standard_workflow.py` 的真實交易概念，
不硬套程式碼。重點：

  - $3.2M 起始水位 (per memory user_capital_size)
  - 4 倉 / $800k 一倉 (跟主力大 C6-4 對齊)
  - shares = floor(sizing / entry_close)
  - P&L $ = (exit_close - entry_close) × shares
  - 倉位滿時新訊號 → SKIP (不擠掉舊倉)、忠實反映「不是每個訊號都能執行」
  - 持倉中用 last close mark-to-market

Per memory `feedback_small_sample_preference`:
  - 樣本少 + 穩定 > 樣本大 + 稀釋
  - 分 sub-strategy 看 (只做春 / 只做立夏 / 只做盛夏 / boosted only) 找穩定路徑

Per memory `feedback_scanner_evaluation_correction_20260608`:
  - cap10 維度補上 (大魚抓到率)
  - segment audit 保留

Per memory `feedback_backtest_methodology`:
  - 不用固定 N 日報酬、用課程出場 (已在 v5 trades CSV 內)

Input:  data/analysis/four_seasons/backtest_2025_final_trades.csv (v5 source)
Output: data/analysis/four_seasons/backtest_2026_v7_report.md
        data/analysis/four_seasons/backtest_2026_v7_executed.csv (被執行的 trade)
        data/analysis/four_seasons/backtest_2026_v7_skipped.csv (slot 滿被略過)
"""
from __future__ import annotations

import math
import sqlite3
import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).parent.parent
_SCRIPTS = _REPO / "scripts"
for _p in [str(_REPO), str(_SCRIPTS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kline.features import add_features  # noqa: E402
from kline.patterns.attack_cost_displayed import detect as detect_attack_cost  # noqa: E402
from kline.patterns.morning_star_island_reversal import detect as detect_msir  # noqa: E402


DB_PATH = Path.home() / ".four_seasons" / "data.sqlite"
TRADES_CSV = _REPO / "data" / "analysis" / "four_seasons" / "backtest_2025_final_trades.csv"
OUT_REPORT = _REPO / "data" / "analysis" / "four_seasons" / "backtest_2026_v7_report.md"
OUT_EXECUTED = _REPO / "data" / "analysis" / "four_seasons" / "backtest_2026_v7_executed.csv"
OUT_SKIPPED = _REPO / "data" / "analysis" / "four_seasons" / "backtest_2026_v7_skipped.csv"

# Per memory user_capital_size (~$3.2M) 與 backtest_standard_workflow.py 對齊
INITIAL_CAPITAL = 3_200_000
SLOTS = 4
SIZING_PER_SLOT = INITIAL_CAPITAL // SLOTS  # $800,000


def load_bars_for_ticker(ticker: str, start: str, end: str) -> pd.DataFrame:
    uri = f"file:{DB_PATH}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=10)
    df = pd.read_sql(
        """SELECT ? as ticker, trade_date, open, high, low, close, volume,
                  vol_ratio_20, ma5, ma10, ma20, ma60
           FROM standard_daily_bar
           WHERE ticker = ? AND trade_date >= date(?, '-90 days')
             AND trade_date <= ?
           ORDER BY trade_date""",
        con, params=(ticker, ticker, start, end),
    )
    con.close()
    return df


def kline_tier_a_on_entry(trade_row: pd.Series, cache: dict) -> tuple[bool, bool]:
    ticker = str(trade_row["ticker"])
    entry_date = str(trade_row["entry_date"])[:10]
    key = (ticker, entry_date)
    if key in cache:
        return cache[key]
    df = load_bars_for_ticker(ticker, entry_date, entry_date)
    if df.empty or len(df) < 60:
        cache[key] = (False, False)
        return False, False
    df["prior_high_60"] = df["high"].rolling(60, min_periods=20).max().shift(1)
    try:
        df = add_features(df, groups=["basic", "volume", "historical", "pattern"])
        sig_k1 = detect_attack_cost(df).fillna(False)
        sig_k2 = detect_msir(df).fillna(False)
    except Exception:
        cache[key] = (False, False)
        return False, False
    mask = df["trade_date"].astype(str).str[:10] == entry_date
    if not mask.any():
        cache[key] = (False, False)
        return False, False
    k1 = bool(sig_k1[mask].any())
    k2 = bool(sig_k2[mask].any())
    cache[key] = (k1, k2)
    return k1, k2


def simulate_portfolio(
    trades_df: pd.DataFrame,
    slots: int = SLOTS,
    sizing: int = SIZING_PER_SLOT,
    label: str = "all",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Portfolio sim: walk by entry_date, slot 滿就 skip 新訊號.

    回傳 (executed, skipped) — 兩個 DataFrame.
    """
    trades_df = trades_df.copy().sort_values("entry_date").reset_index(drop=True)
    trades_df["entry_date"] = pd.to_datetime(trades_df["entry_date"])
    trades_df["exit_date"] = pd.to_datetime(trades_df["exit_date"])

    open_positions: list[dict] = []
    executed: list[dict] = []
    skipped: list[dict] = []

    for _, row in trades_df.iterrows():
        # 釋放已出場的倉位 (exit_date 早於本筆 entry_date)
        still_open = []
        for op in open_positions:
            if op["exit_date"] <= row["entry_date"]:
                executed.append(op)
            else:
                still_open.append(op)
        open_positions = still_open

        if len(open_positions) >= slots:
            skipped.append({**row.to_dict(), "skip_reason": f"slots_full ({slots})"})
            continue

        entry_close = float(row["entry_close"])
        if entry_close <= 0:
            skipped.append({**row.to_dict(), "skip_reason": "bad_entry_price"})
            continue
        shares = math.floor(sizing / entry_close)
        if shares < 1:
            skipped.append({**row.to_dict(), "skip_reason": "too_expensive"})
            continue

        exit_close = float(row["exit_close"])
        pnl_dollar = (exit_close - entry_close) * shares
        if row["side"] == "short":
            pnl_dollar = -pnl_dollar  # short: 反向 P&L

        op = {
            **row.to_dict(),
            "shares": int(shares),
            "cost": round(entry_close * shares),
            "proceeds": round(exit_close * shares),
            "pnl_dollar": round(pnl_dollar),
            "pnl_pct_actual": round(pnl_dollar / (entry_close * shares) * 100, 2),
        }
        open_positions.append(op)

    # 收尾還沒結算的
    for op in open_positions:
        executed.append(op)

    exe_df = pd.DataFrame(executed)
    skp_df = pd.DataFrame(skipped)
    exe_df["sub_strategy"] = label
    skp_df["sub_strategy"] = label if not skp_df.empty else label
    return exe_df, skp_df


def summarize_portfolio(exe: pd.DataFrame, skipped_count: int = 0,
                        initial: int = INITIAL_CAPITAL) -> dict:
    n = len(exe)
    if n == 0:
        return {"n_executed": 0, "n_skipped": skipped_count, "total_pnl": 0,
                "final_water": initial, "total_return_pct": 0, "wr": 0,
                "cap10": 0, "cap20": 0, "max_dd": 0, "median_days": 0,
                "mean_pnl_pct": 0, "median_pnl_pct": 0}
    pnl = exe["pnl_dollar"].sum()
    pnl_pcts = exe["pnl_pct_actual"]
    # Equity curve drawdown — sort by exit_date, cumulate
    sorted_e = exe.sort_values("exit_date")
    equity = initial + sorted_e["pnl_dollar"].cumsum()
    running_max = equity.cummax()
    dd_series = (equity - running_max) / running_max * 100
    max_dd_pct = float(dd_series.min()) if len(dd_series) else 0
    days = pd.to_datetime(exe["exit_date"]) - pd.to_datetime(exe["entry_date"])
    median_days = float(days.dt.days.median())
    return {
        "n_executed": int(n),
        "n_skipped": int(skipped_count),
        "total_pnl": int(pnl),
        "final_water": int(initial + pnl),
        "total_return_pct": round(pnl / initial * 100, 2),
        "wr": float((pnl_pcts > 0).mean()),
        "cap10": float((pnl_pcts >= 10).mean()),
        "cap20": float((pnl_pcts >= 20).mean()),
        "max_dd": round(max_dd_pct, 2),
        "median_days": median_days,
        "mean_pnl_pct": round(float(pnl_pcts.mean()), 2),
        "median_pnl_pct": round(float(pnl_pcts.median()), 2),
    }


def fmt_money(v: int) -> str:
    if v >= 0:
        return f"${v:,}"
    return f"-${abs(v):,}"


def fmt_pct(v, plus=True, decimals=2):
    if v is None or pd.isna(v):
        return "—"
    if plus and v >= 0:
        return f"+{v:.{decimals}f}%"
    return f"{v:.{decimals}f}%"


def fmt_rate(v, decimals=1):
    if v is None or pd.isna(v):
        return "—"
    return f"{v*100:.{decimals}f}%"


def section_md(label: str, s: dict) -> str:
    return (
        f"| {label} | {s['n_executed']} | {s['n_skipped']} | "
        f"{fmt_money(s['total_pnl'])} | {fmt_money(s['final_water'])} | "
        f"{fmt_pct(s['total_return_pct'])} | {fmt_pct(s['max_dd'], plus=False)} | "
        f"{fmt_rate(s['wr'])} | {fmt_rate(s['cap10'])} | {fmt_rate(s['cap20'])} | "
        f"{s['median_days']:.0f}d |"
    )


def main():
    trades = pd.read_csv(TRADES_CSV)
    print(f"Source trades: {len(trades)} (closed: {(~trades['censored']).sum()}, "
          f"censored: {trades['censored'].sum()})", flush=True)
    closed = trades[~trades["censored"]].copy()

    # K 線 tier-A 標記 (long only)
    cache: dict = {}
    k1_list, k2_list = [], []
    for i, row in closed.iterrows():
        if row["side"] == "long":
            k1, k2 = kline_tier_a_on_entry(row, cache)
        else:
            k1, k2 = False, False
        k1_list.append(k1)
        k2_list.append(k2)
        if (i + 1) % 50 == 0:
            print(f"  kline cross {i+1}/{len(closed)}", flush=True)
    closed["kline_k1"] = k1_list
    closed["kline_k2"] = k2_list
    closed["kline_any"] = closed["kline_k1"] | closed["kline_k2"]

    # Sub-strategy splits
    long_all = closed[closed["side"] == "long"]
    long_spring = closed[(closed["side"] == "long") & (closed["season"] == "春")]
    long_lixia = closed[(closed["side"] == "long") & (closed["season"] == "立夏")]
    long_sxia = closed[(closed["side"] == "long") & (closed["season"] == "盛夏")]
    long_boosted = closed[(closed["side"] == "long") & (closed["kline_any"])]
    short_qiu = closed[(closed["side"] == "short") & (closed["season"] == "秋")]
    # 立夏 only trailing-exit subset = 真 edge candidate
    lixia_trail = closed[(closed["side"] == "long") & (closed["season"] == "立夏") &
                          (closed["exit_reason"] == "trailing_stop")]

    strategies = [
        ("LONG all (春+立夏+盛夏)", long_all),
        ("  └ 春 only", long_spring),
        ("  └ 立夏 only", long_lixia),
        ("    └ 立夏 trailing exit only", lixia_trail),
        ("  └ 盛夏 only", long_sxia),
        ("  └ K 線 boosted only (K1/K2)", long_boosted),
        ("SHORT 秋 only", short_qiu),
    ]

    print("\n=== Portfolio Sim (4 slots × $800k) ===")
    results: list[tuple[str, dict, pd.DataFrame, pd.DataFrame]] = []
    for label, sub in strategies:
        exe, skp = simulate_portfolio(sub, slots=SLOTS, sizing=SIZING_PER_SLOT, label=label.strip())
        summary = summarize_portfolio(exe, skipped_count=len(skp))
        results.append((label, summary, exe, skp))
        print(f"{label:40s}  exec={summary['n_executed']:>3} "
              f"skip={summary['n_skipped']:>3} "
              f"pnl={fmt_money(summary['total_pnl']):>15} "
              f"ret={fmt_pct(summary['total_return_pct']):>8} "
              f"dd={fmt_pct(summary['max_dd'], plus=False):>8} "
              f"cap10={fmt_rate(summary['cap10']):>6}")

    # 主表 LONG all + sub 寫進 executed CSV 給審計
    main_exe = results[0][2]
    main_skp = results[0][3]
    main_exe.to_csv(OUT_EXECUTED, index=False)
    main_skp.to_csv(OUT_SKIPPED, index=False)
    print(f"\nExecuted trades: {OUT_EXECUTED}")
    print(f"Skipped trades: {OUT_SKIPPED}")

    # === Report ===
    lines = [
        "# Four-Seasons Backtest v7 — 真實操作版 (Portfolio Simulation)",
        "",
        f"- 起始水位: **${INITIAL_CAPITAL:,}** (per memory `user_capital_size`)",
        f"- 倉位數: **{SLOTS}** 倉 × ${SIZING_PER_SLOT:,}/倉 (跟主力大 C6-4 對齊、per `feedback_exit_rules_v3`)",
        f"- 進場/出場價: 取 v5 trades CSV (course-defined exit、per `feedback_backtest_methodology`)",
        f"- 倉位滿時新訊號 → SKIP (不擠掉舊倉、模擬「不是每個訊號都能執行」)",
        f"- 持倉中按出場價 mark-to-market (censored 同 v5)",
        f"- 期間: {trades['entry_date'].min()} → {trades['exit_date'].max()}",
        "",
        "## 1. 各 sub-strategy 真實水位 (照時間排程 + 4 倉 slot)",
        "",
        "| Strategy | 執行筆 | 略過 | 累計 P&L | 最終水位 | 累計報酬 | max DD | WR | cap10 | cap20 | median 持倉 |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for label, s, _, _ in results:
        lines.append(section_md(label, s))

    # 主表 (LONG all) Top winners/losers by P&L $
    if not main_exe.empty:
        winners = main_exe.sort_values("pnl_dollar", ascending=False).head(5)
        losers = main_exe.sort_values("pnl_dollar", ascending=True).head(5)
        lines += [
            "",
            "## 2. LONG all — Top 5 Winners (by P&L $)",
            "",
            "| ticker | name | season | entry | exit | shares | days | P&L % | P&L $ | exit_reason |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for _, r in winners.iterrows():
            lines.append(
                f"| {r['ticker']} | {r.get('name', '')} | {r['season']} | "
                f"{r['entry_close']:.2f} | {r['exit_close']:.2f} | {r['shares']} | "
                f"{int(r['days_held'])} | {r['pnl_pct_actual']:+.2f}% | "
                f"{fmt_money(int(r['pnl_dollar']))} | {r['exit_reason']} |"
            )
        lines += [
            "",
            "## 3. LONG all — Top 5 Losers (by P&L $)",
            "",
            "| ticker | name | season | entry | exit | shares | days | P&L % | P&L $ | exit_reason |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for _, r in losers.iterrows():
            lines.append(
                f"| {r['ticker']} | {r.get('name', '')} | {r['season']} | "
                f"{r['entry_close']:.2f} | {r['exit_close']:.2f} | {r['shares']} | "
                f"{int(r['days_held'])} | {r['pnl_pct_actual']:+.2f}% | "
                f"{fmt_money(int(r['pnl_dollar']))} | {r['exit_reason']} |"
            )

    # K 線 boost cross 真實 P&L 對比 (long sub-strategy)
    lines += [
        "",
        "## 4. K 線 Tier-A 升等 — 真實 P&L 對比 (long only)",
        "",
        "| group | n_exec | n_skip | 累計 P&L | 最終水位 | 累計報酬 | WR | cap10 | cap20 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    boost_set = closed[(closed["side"] == "long") & (closed["kline_any"])]
    control_set = closed[(closed["side"] == "long") & (~closed["kline_any"])]
    exe_b, skp_b = simulate_portfolio(boost_set, label="A_boosted")
    exe_c, skp_c = simulate_portfolio(control_set, label="B_control")
    s_b = summarize_portfolio(exe_b, len(skp_b))
    s_c = summarize_portfolio(exe_c, len(skp_c))
    for lbl, s in (("A: long + K1/K2 boosted", s_b), ("B: long, no K1/K2", s_c)):
        lines.append(
            f"| {lbl} | {s['n_executed']} | {s['n_skipped']} | "
            f"{fmt_money(s['total_pnl'])} | {fmt_money(s['final_water'])} | "
            f"{fmt_pct(s['total_return_pct'])} | {fmt_rate(s['wr'])} | "
            f"{fmt_rate(s['cap10'])} | {fmt_rate(s['cap20'])} |"
        )

    lines += [
        "",
        "## 5. 判讀重點 (per `feedback_small_sample_preference`)",
        "",
        "- 看「累計報酬 vs max DD」、不只看 WR",
        "- 「執行筆/略過筆」反映 slot 限制下這個策略多常有訊號",
        "- 樣本少 + 累計報酬正 + max DD 控制好 = 穩定可投入",
        "- 樣本大但累計報酬接近 0 = 稀釋、不該耗注意力",
        "- (本檔留 user 判讀、AI 不寫死結論)",
        "",
        "## Files",
        "",
        f"- This report: `{OUT_REPORT.relative_to(_REPO)}`",
        f"- Main exec trades: `{OUT_EXECUTED.relative_to(_REPO)}`",
        f"- Main skipped trades: `{OUT_SKIPPED.relative_to(_REPO)}`",
        f"- Source v5 trades: `{TRADES_CSV.relative_to(_REPO)}`",
    ]

    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {OUT_REPORT}")


if __name__ == "__main__":
    main()
