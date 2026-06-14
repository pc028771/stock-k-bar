"""Standard vs trailing-only 出場機制 side-by-side cross-period (2023 / 2024 / 2026 H1).

驗證 v7 multiperiod 看到的 hypothesis:
  「立夏/盛夏 trailing_stop subset 三期全 + + DD < 1%」
  → 若 production 只認 trailing_stop exit (砍掉 ma20_break / warning / season_change)、
    報酬會更好嗎？還是會被「不出場的爛倉」拖死？

借 v7_multiperiod.py 的真實 portfolio sim (4 slots × $800k)、跑兩組 CSV side-by-side.

Input:
  standard CSVs: backtest_{period}_trades.csv (已有)
  trail CSVs:    backtest_{period}_trail_trades.csv (這次新跑)
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

OUT_DIR = _REPO / "data" / "analysis" / "four_seasons"
OUT_REPORT = OUT_DIR / "backtest_2026_v8_trail_compare_report.md"
DB_PATH = Path.home() / ".four_seasons" / "data.sqlite"

INITIAL = 3_200_000
SLOTS = 4
SIZING = INITIAL // SLOTS

# 期間結束日：超過的 exit 強制 clip 到此日、用當日 close MTM 換現
# 避免 2023 backtest 的 censored 倉位 hold 到 2026 → 偷吃未來報酬
PERIOD_PAIRS = [
    ("2023 震盪上行", OUT_DIR / "backtest_2023_trades.csv",
     OUT_DIR / "backtest_2023_trail_trades.csv", pd.Timestamp("2023-12-31")),
    ("2024 震盪劇烈", OUT_DIR / "backtest_2024_trades.csv",
     OUT_DIR / "backtest_2024_trail_trades.csv", pd.Timestamp("2024-12-31")),
    ("2026 H1 強多頭", OUT_DIR / "backtest_2025_final_trades.csv",
     OUT_DIR / "backtest_2026H1_trail_trades.csv", pd.Timestamp("2026-05-14")),
]

# 預載 close 表給 clip 用 — (ticker, date) → close
_CLOSE_CACHE: dict[tuple[str, str], float] = {}


def lookup_close(ticker: str, date: pd.Timestamp) -> float | None:
    """找 ticker 在 date 或之前最近的交易日 close (period_end 可能不是交易日)."""
    date_s = date.strftime("%Y-%m-%d")
    key = (str(ticker), date_s)
    if key in _CLOSE_CACHE:
        return _CLOSE_CACHE[key]
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=10)
    rows = con.execute(
        """SELECT close FROM standard_daily_bar
           WHERE ticker = ? AND trade_date <= ?
           ORDER BY trade_date DESC LIMIT 1""",
        (str(ticker), date_s),
    ).fetchone()
    con.close()
    if not rows or rows[0] is None:
        _CLOSE_CACHE[key] = None
        return None
    val = float(rows[0])
    _CLOSE_CACHE[key] = val
    return val


def clip_to_period_end(trades_df: pd.DataFrame, period_end: pd.Timestamp) -> pd.DataFrame:
    """For trades whose exit_date > period_end, force-close at period_end with MTM close."""
    if trades_df.empty:
        return trades_df
    trades_df = trades_df.copy()
    trades_df["entry_date"] = pd.to_datetime(trades_df["entry_date"])
    trades_df["exit_date"] = pd.to_datetime(trades_df["exit_date"])
    # 先過濾 entry > period_end (理論上不該發生、保險)
    trades_df = trades_df[trades_df["entry_date"] <= period_end]
    over_mask = trades_df["exit_date"] > period_end
    if over_mask.any():
        for idx in trades_df[over_mask].index:
            t = trades_df.at[idx, "ticker"]
            close = lookup_close(str(t), period_end)
            if close is None or close <= 0:
                # 無資料 → 用 entry_close 等同 0 PnL
                close = trades_df.at[idx, "entry_close"]
            trades_df.at[idx, "exit_date"] = period_end
            trades_df.at[idx, "exit_close"] = close
            trades_df.at[idx, "exit_reason"] = "period_clip"
            trades_df.at[idx, "censored"] = False  # 強制 close 視為已結算
    return trades_df


def sim_portfolio(trades_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if trades_df.empty:
        return pd.DataFrame(), pd.DataFrame()
    trades_df = trades_df.copy().sort_values("entry_date").reset_index(drop=True)
    trades_df["entry_date"] = pd.to_datetime(trades_df["entry_date"])
    trades_df["exit_date"] = pd.to_datetime(trades_df["exit_date"])

    open_positions = []
    executed = []
    skipped = []

    for _, row in trades_df.iterrows():
        still_open = []
        for op in open_positions:
            if op["exit_date"] <= row["entry_date"]:
                executed.append(op)
            else:
                still_open.append(op)
        open_positions = still_open

        if len(open_positions) >= SLOTS:
            skipped.append({**row.to_dict(), "skip_reason": "slots_full"})
            continue

        entry_close = float(row["entry_close"])
        if entry_close <= 0:
            skipped.append({**row.to_dict(), "skip_reason": "bad_price"})
            continue
        shares = math.floor(SIZING / entry_close)
        if shares < 1:
            skipped.append({**row.to_dict(), "skip_reason": "too_expensive"})
            continue

        exit_close = float(row["exit_close"])
        pnl_dollar = (exit_close - entry_close) * shares
        if row["side"] == "short":
            pnl_dollar = -pnl_dollar

        op = {
            **row.to_dict(),
            "shares": int(shares),
            "pnl_dollar": round(pnl_dollar),
            "pnl_pct_actual": round(pnl_dollar / (entry_close * shares) * 100, 2),
        }
        open_positions.append(op)

    for op in open_positions:
        executed.append(op)
    return pd.DataFrame(executed), pd.DataFrame(skipped)


def summarize(exe: pd.DataFrame, n_skip: int = 0) -> dict:
    n = len(exe)
    if n == 0:
        return {"n_exec": 0, "n_skip": n_skip, "total_pnl": 0,
                "return_pct": 0, "wr": 0, "cap10": 0, "cap20": 0,
                "max_dd": 0, "median_days": 0}
    pnl = exe["pnl_dollar"].sum()
    pnl_pcts = exe["pnl_pct_actual"]
    sorted_e = exe.sort_values("exit_date")
    equity = INITIAL + sorted_e["pnl_dollar"].cumsum()
    running_max = equity.cummax()
    dd = (equity - running_max) / running_max * 100
    days = pd.to_datetime(exe["exit_date"]) - pd.to_datetime(exe["entry_date"])
    return {
        "n_exec": int(n),
        "n_skip": int(n_skip),
        "total_pnl": int(pnl),
        "return_pct": round(pnl / INITIAL * 100, 2),
        "wr": float((pnl_pcts > 0).mean()),
        "cap10": float((pnl_pcts >= 10).mean()),
        "cap20": float((pnl_pcts >= 20).mean()),
        "max_dd": round(float(dd.min()), 2),
        "median_days": float(days.dt.days.median()),
    }


def fmt_money(v):
    return f"+${v:,}" if v >= 0 else f"-${abs(v):,}"


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


def row(label, s):
    return (f"| {label} | {s['n_exec']} | {s['n_skip']} | "
            f"{fmt_money(s['total_pnl'])} | {fmt_pct(s['return_pct'])} | "
            f"{fmt_pct(s['max_dd'], plus=False)} | "
            f"{fmt_rate(s['wr'])} | {fmt_rate(s['cap10'])} | "
            f"{s['median_days']:.0f}d |")


def slice_strategy(closed: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    """各 sub-strategy slice."""
    return [
        ("LONG all", closed[closed["side"] == "long"]),
        ("  └ 春 only", closed[(closed["side"] == "long") & (closed["season"] == "春")]),
        ("  └ 立夏 only", closed[(closed["side"] == "long") & (closed["season"] == "立夏")]),
        ("  └ 盛夏 only", closed[(closed["side"] == "long") & (closed["season"] == "盛夏")]),
        # SHORT 秋 trailing_only 沒改 short 邏輯、不分組
    ]


def run_one(csv_path: Path, period_end: pd.Timestamp) -> dict[str, dict]:
    """Portfolio sim 含 censored、但 clip 到 period_end (MTM 換現、避免偷未來)."""
    if not csv_path.exists():
        return {}
    df = pd.read_csv(csv_path)
    df = clip_to_period_end(df, period_end)
    out = {}
    for lbl, sub in slice_strategy(df):
        exe, skp = sim_portfolio(sub)
        out[lbl] = summarize(exe, len(skp))
    return out


def main():
    period_results = []
    for period, std_csv, trl_csv, period_end in PERIOD_PAIRS:
        print(f"\n--- {period} (clip 至 {period_end.date()}) ---", flush=True)
        std_summary = run_one(std_csv, period_end)
        trl_summary = run_one(trl_csv, period_end)
        std_n_total = std_n_closed = trl_n_total = trl_n_closed = 0
        if std_csv.exists():
            d = pd.read_csv(std_csv)
            std_n_total = len(d)
            std_n_closed = int((~d["censored"]).sum())
        if trl_csv.exists():
            d = pd.read_csv(trl_csv)
            trl_n_total = len(d)
            trl_n_closed = int((~d["censored"]).sum())
        period_results.append({
            "period": period,
            "std": std_summary,
            "trl": trl_summary,
            "std_n_total": std_n_total, "std_n_closed": std_n_closed,
            "trl_n_total": trl_n_total, "trl_n_closed": trl_n_closed,
        })

    # === Markdown ===
    lines = [
        "# Four-Seasons v8 — Standard vs Trailing-only Exit 對照 (3 期)",
        "",
        f"- ${INITIAL:,} 起始、{SLOTS} 倉 × ${SIZING:,}/倉",
        "- standard: 課程全部 exit (warning / ma20_break / trailing / season_change)",
        "- trailing_only: 只認 trailing_stop、忽略其他 exit",
        "- 春多在 trailing_only 模式改成「也用 trailing」(原本不用價格停損)",
        "",
        "## 0. closed trades 數量對照 (trailing_only 應 < standard、因為很多 entry 沒到 trail trigger 變 censored)",
        "",
        "| 期間 | std total | std closed | trail total | trail closed | trail closed / std closed |",
        "|---|---|---|---|---|---|",
    ]
    for pr in period_results:
        ratio = pr["trl_n_closed"] / max(1, pr["std_n_closed"]) * 100
        lines.append(
            f"| {pr['period']} | {pr['std_n_total']} | {pr['std_n_closed']} | "
            f"{pr['trl_n_total']} | {pr['trl_n_closed']} | {ratio:.0f}% |"
        )

    # Per-strategy comparison
    strategy_labels = ["LONG all", "  └ 春 only", "  └ 立夏 only", "  └ 盛夏 only"]
    for lbl in strategy_labels:
        lines += [
            "",
            f"## {lbl.strip()}",
            "",
            "| 期間 | mode | exec | skip | 累計 P&L | 報酬 | max DD | WR | cap10 | 持倉 |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for pr in period_results:
            s_std = pr["std"].get(lbl, {"n_exec": 0, "n_skip": 0, "total_pnl": 0, "return_pct": 0,
                                       "max_dd": 0, "wr": 0, "cap10": 0, "median_days": 0})
            s_trl = pr["trl"].get(lbl, {"n_exec": 0, "n_skip": 0, "total_pnl": 0, "return_pct": 0,
                                       "max_dd": 0, "wr": 0, "cap10": 0, "median_days": 0})
            lines.append(
                f"| {pr['period']} **standard** | std | {s_std['n_exec']} | {s_std['n_skip']} | "
                f"{fmt_money(s_std['total_pnl'])} | {fmt_pct(s_std['return_pct'])} | "
                f"{fmt_pct(s_std['max_dd'], plus=False)} | {fmt_rate(s_std['wr'])} | "
                f"{fmt_rate(s_std['cap10'])} | {s_std['median_days']:.0f}d |"
            )
            lines.append(
                f"| {pr['period']} **trail_only** | trail | {s_trl['n_exec']} | {s_trl['n_skip']} | "
                f"{fmt_money(s_trl['total_pnl'])} | {fmt_pct(s_trl['return_pct'])} | "
                f"{fmt_pct(s_trl['max_dd'], plus=False)} | {fmt_rate(s_trl['wr'])} | "
                f"{fmt_rate(s_trl['cap10'])} | {s_trl['median_days']:.0f}d |"
            )
            lines.append("| | | | | | | | | | |")

    # Trail delta summary
    lines += [
        "",
        "## 主結論 — Trailing-only Δ vs Standard",
        "",
        "| 期間 | LONG all Δ報酬 | LONG all Δmax DD | 立夏 Δ報酬 | 立夏 Δmax DD | 盛夏 Δ報酬 | 盛夏 Δmax DD |",
        "|---|---|---|---|---|---|---|",
    ]
    for pr in period_results:
        deltas = []
        for lbl in ["LONG all", "  └ 立夏 only", "  └ 盛夏 only"]:
            s_std = pr["std"].get(lbl, {})
            s_trl = pr["trl"].get(lbl, {})
            d_ret = s_trl.get("return_pct", 0) - s_std.get("return_pct", 0)
            d_dd = s_trl.get("max_dd", 0) - s_std.get("max_dd", 0)
            deltas.append(fmt_pct(d_ret))
            deltas.append(fmt_pct(d_dd, plus=False))
        lines.append(f"| {pr['period']} | " + " | ".join(deltas) + " |")

    lines += [
        "",
        "## 判讀 (留 user)",
        "",
        "- trailing-only **報酬 ↑ + max DD 不爆**：production 可直接砍 standard exits、用這個",
        "- trailing-only **報酬 ↑ 但 max DD ↑↑**：trailing 給爛倉留太久、需要 hybrid (中間放 1 個 stop)",
        "- trailing-only **報酬 ↓**：standard 的 ma20_break / season_change 有救命功能、不能砍",
    ]

    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report: {OUT_REPORT}")

    # console summary
    for pr in period_results:
        print(f"\n=== {pr['period']} ===")
        for lbl in strategy_labels:
            s = pr["std"].get(lbl, {})
            t = pr["trl"].get(lbl, {})
            print(f"{lbl:25s}  std ret={fmt_pct(s.get('return_pct', 0)):>8} dd={fmt_pct(s.get('max_dd', 0), plus=False):>8} | "
                  f"trail ret={fmt_pct(t.get('return_pct', 0)):>8} dd={fmt_pct(t.get('max_dd', 0), plus=False):>8}")


if __name__ == "__main__":
    main()
