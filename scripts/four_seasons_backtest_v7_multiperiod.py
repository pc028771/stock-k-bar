"""Multi-period four-seasons v7 portfolio sim — 2023 / 2024 / 2026 H1 對照.

借 v7_portfolio.py 的真實操作框架、套到三個不同大盤環境：

  - 2023 (年初 14000 → 年底 17500)：年漲 24%、但**震盪上行**、有 4-5 月 / 9-10 月兩次回檔
  - 2024 (17500 → 22700)：年漲 30%、但**震盪劇烈**、Q3 整理半年
  - 2026 H1 (22000 → 46500 → 40000)：**強多頭**、AI 飆漲 + 5 月急殺

對照目的: 看 v7 在 2026 H1 漂亮的 +63% 結果、在震盪市能不能撐住、
還是只是 beta 灌水.

per memory `feedback_small_sample_preference`:
  穩定 cross-period > 單期極端報酬

per memory `feedback_scanner_evaluation_correction_20260608`:
  雙維度 + segment audit
"""
from __future__ import annotations

import math
import sqlite3
import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).parent.parent
_SCRIPTS = _REPO / "scripts"
for _p in [str(_REPO), str(_SCRIPTS), "/Users/howard/Repository/stock-analysis-system"]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

DB_PATH = Path.home() / ".four_seasons" / "data.sqlite"
OUT_DIR = _REPO / "data" / "analysis" / "four_seasons"
OUT_REPORT = OUT_DIR / "backtest_2026_v7_multiperiod_report.md"

INITIAL_CAPITAL = 3_200_000
SLOTS = 4
SIZING_PER_SLOT = INITIAL_CAPITAL // SLOTS

PERIODS = [
    ("2023 震盪上行", OUT_DIR / "backtest_2023_trades.csv"),
    ("2024 震盪劇烈", OUT_DIR / "backtest_2024_trades.csv"),
    ("2026 H1 強多頭", OUT_DIR / "backtest_2025_final_trades.csv"),
]


def taiex_period_stats(start: str, end: str) -> dict | None:
    """TAIEX 期間漲幅 + max DD、確認大盤 regime."""
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=10)
        df = pd.read_sql(
            """SELECT trade_date, close FROM standard_daily_bar
               WHERE ticker='TAIEX' AND trade_date >= ? AND trade_date <= ?
               ORDER BY trade_date""",
            con, params=(start, end),
        )
        con.close()
        if df.empty:
            return None
        start_close = float(df.iloc[0]["close"])
        end_close = float(df.iloc[-1]["close"])
        peak = df["close"].cummax()
        dd = (df["close"] - peak) / peak * 100
        return {
            "start": start, "end": end,
            "start_close": start_close, "end_close": end_close,
            "return_pct": (end_close / start_close - 1) * 100,
            "max_dd_pct": float(dd.min()),
        }
    except Exception:
        return None


def simulate_portfolio(trades_df: pd.DataFrame, slots: int = SLOTS,
                       sizing: int = SIZING_PER_SLOT) -> tuple[pd.DataFrame, pd.DataFrame]:
    if trades_df.empty:
        return pd.DataFrame(), pd.DataFrame()
    trades_df = trades_df.copy().sort_values("entry_date").reset_index(drop=True)
    trades_df["entry_date"] = pd.to_datetime(trades_df["entry_date"])
    trades_df["exit_date"] = pd.to_datetime(trades_df["exit_date"])

    open_positions: list[dict] = []
    executed: list[dict] = []
    skipped: list[dict] = []

    for _, row in trades_df.iterrows():
        still_open = []
        for op in open_positions:
            if op["exit_date"] <= row["entry_date"]:
                executed.append(op)
            else:
                still_open.append(op)
        open_positions = still_open

        if len(open_positions) >= slots:
            skipped.append({**row.to_dict(), "skip_reason": "slots_full"})
            continue

        entry_close = float(row["entry_close"])
        if entry_close <= 0:
            skipped.append({**row.to_dict(), "skip_reason": "bad_price"})
            continue
        shares = math.floor(sizing / entry_close)
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


def summarize_portfolio(exe: pd.DataFrame, n_skipped: int = 0,
                        initial: int = INITIAL_CAPITAL) -> dict:
    n = len(exe)
    if n == 0:
        return {"n_exec": 0, "n_skip": n_skipped, "total_pnl": 0,
                "final_water": initial, "return_pct": 0, "wr": 0,
                "cap10": 0, "cap20": 0, "max_dd": 0, "median_days": 0}
    pnl = exe["pnl_dollar"].sum()
    pnl_pcts = exe["pnl_pct_actual"]
    sorted_e = exe.sort_values("exit_date")
    equity = initial + sorted_e["pnl_dollar"].cumsum()
    running_max = equity.cummax()
    dd_series = (equity - running_max) / running_max * 100
    max_dd_pct = float(dd_series.min())
    days = pd.to_datetime(exe["exit_date"]) - pd.to_datetime(exe["entry_date"])
    return {
        "n_exec": int(n),
        "n_skip": int(n_skipped),
        "total_pnl": int(pnl),
        "final_water": int(initial + pnl),
        "return_pct": round(pnl / initial * 100, 2),
        "wr": float((pnl_pcts > 0).mean()),
        "cap10": float((pnl_pcts >= 10).mean()),
        "cap20": float((pnl_pcts >= 20).mean()),
        "max_dd": round(max_dd_pct, 2),
        "median_days": float(days.dt.days.median()),
    }


def fmt_money(v: int) -> str:
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


def section_row(label: str, s: dict) -> str:
    return (
        f"| {label} | {s['n_exec']} | {s['n_skip']} | "
        f"{fmt_money(s['total_pnl'])} | {fmt_pct(s['return_pct'])} | "
        f"{fmt_pct(s['max_dd'], plus=False)} | "
        f"{fmt_rate(s['wr'])} | {fmt_rate(s['cap10'])} | {fmt_rate(s['cap20'])} | "
        f"{s['median_days']:.0f}d |"
    )


def run_period(period_name: str, trades_csv: Path) -> dict:
    if not trades_csv.exists():
        print(f"[{period_name}] trades CSV 不存在: {trades_csv}", flush=True)
        return None

    trades = pd.read_csv(trades_csv)
    closed = trades[~trades["censored"]].copy()
    print(f"\n=== {period_name} === ", flush=True)
    print(f"Source: {trades_csv.name} closed={len(closed)} censored={len(trades)-len(closed)}", flush=True)

    # 取 TAIEX
    if len(closed):
        start = str(closed["entry_date"].min())[:10]
        end = str(closed["exit_date"].max())[:10]
        taiex = taiex_period_stats(start, end)
    else:
        taiex = None

    # sub-strategy slices
    long_all = closed[closed["side"] == "long"]
    long_spring = closed[(closed["side"] == "long") & (closed["season"] == "春")]
    long_lixia = closed[(closed["side"] == "long") & (closed["season"] == "立夏")]
    long_sxia = closed[(closed["side"] == "long") & (closed["season"] == "盛夏")]
    short_qiu = closed[(closed["side"] == "short") & (closed["season"] == "秋")]
    lixia_trail = closed[(closed["side"] == "long") & (closed["season"] == "立夏") &
                          (closed["exit_reason"] == "trailing_stop")]
    sxia_trail = closed[(closed["side"] == "long") & (closed["season"] == "盛夏") &
                         (closed["exit_reason"] == "trailing_stop")]

    strategies = [
        ("LONG all", long_all),
        ("  └ 春 only", long_spring),
        ("  └ 立夏 only", long_lixia),
        ("    └ 立夏 trailing exit", lixia_trail),
        ("  └ 盛夏 only", long_sxia),
        ("    └ 盛夏 trailing exit", sxia_trail),
        ("SHORT 秋 only", short_qiu),
    ]

    results = []
    for lbl, sub in strategies:
        exe, skp = simulate_portfolio(sub)
        s = summarize_portfolio(exe, len(skp))
        results.append((lbl, s))
        print(f"  {lbl:30s}  exec={s['n_exec']:>3} skip={s['n_skip']:>3} "
              f"pnl={fmt_money(s['total_pnl']):>15} ret={fmt_pct(s['return_pct']):>8} "
              f"dd={fmt_pct(s['max_dd'], plus=False):>8}")

    return {
        "period": period_name,
        "source": trades_csv.name,
        "taiex": taiex,
        "results": results,
        "n_trades_total": len(trades),
        "n_closed": len(closed),
    }


def main():
    period_data = []
    for pname, csv in PERIODS:
        d = run_period(pname, csv)
        if d:
            period_data.append(d)

    if not period_data:
        print("無資料、abort")
        return

    # === Cross-period markdown ===
    lines = [
        "# Four-Seasons Backtest v7 Multi-Period — 2023 / 2024 / 2026 H1 對照",
        "",
        f"- 起始水位: ${INITIAL_CAPITAL:,}, {SLOTS} 倉 × ${SIZING_PER_SLOT:,}/倉",
        "- 進場/出場: 課程定義 (warning / ma20_break / trailing_stop / season_change)",
        "- 倉位滿 → SKIP，不擠舊倉",
        "",
        "## 0. 大盤 regime (TAIEX)",
        "",
        "| 期間 | 起 | 迄 | 期初 close | 期末 close | 漲跌 | TAIEX max DD |",
        "|---|---|---|---|---|---|---|",
    ]
    for pd_ in period_data:
        t = pd_["taiex"]
        if t:
            lines.append(
                f"| {pd_['period']} | {t['start']} | {t['end']} | "
                f"{t['start_close']:.0f} | {t['end_close']:.0f} | "
                f"{fmt_pct(t['return_pct'])} | {fmt_pct(t['max_dd_pct'], plus=False)} |"
            )

    # 各 strategy per-period 比較
    strategy_labels = [r[0] for r in period_data[0]["results"]]
    for lbl in strategy_labels:
        lines += [
            "",
            f"## {lbl.strip()}",
            "",
            "| 期間 | exec | skip | 累計 P&L | 報酬 | max DD | WR | cap10 | cap20 | 持倉 |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for pd_ in period_data:
            s = next(s for l, s in pd_["results"] if l == lbl)
            lines.append(section_row(pd_["period"], s))

    # Cross-period TAIEX-relative
    lines += [
        "",
        "## 主結論 — 各 sub-strategy 對 TAIEX 的 excess return (策略報酬 − TAIEX 報酬)",
        "",
        "| sub-strategy | 2023 vs TAIEX | 2024 vs TAIEX | 2026 H1 vs TAIEX |",
        "|---|---|---|---|",
    ]
    for lbl in strategy_labels:
        cells = []
        for pd_ in period_data:
            s = next(s for l, s in pd_["results"] if l == lbl)
            t = pd_["taiex"]
            if t:
                excess = s["return_pct"] - t["return_pct"]
                cells.append(fmt_pct(excess))
            else:
                cells.append("—")
        lines.append(f"| {lbl.strip()} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## 判讀重點 (per `feedback_small_sample_preference` cross-period 穩定 > 單期高報酬)",
        "",
        "- 三期都 + 的 strategy = 穩定可投入",
        "- 只有 2026 H1 + 其他兩期 - = 多頭灌水、不穩",
        "- max DD cross-period 一致性 > 單期低 = 真實風險控制",
        "- (本檔留 user 判讀)",
        "",
        "## Files",
        "",
        f"- This report: `{OUT_REPORT.relative_to(_REPO)}`",
    ]
    for pd_ in period_data:
        lines.append(f"- {pd_['period']} trades: `data/analysis/four_seasons/{pd_['source']}`")

    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {OUT_REPORT}", flush=True)


if __name__ == "__main__":
    main()
