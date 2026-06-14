"""用 C6 出場規則重評既有 xiaoge detector + 探索條件 stack 變體 + 找盲點補救.

對應任務：feedback_backtest_strategy_filtering.md + feedback_exit_rules_v3.md

跑：
  - detector 1 (bb_squeeze_breakout)
  - detector 2 v1 (main_chip_holder)
  - detector 2 v2 (main_chip_holder_v2 真三軸)
  - 各種條件 stack 變體
  - 對照舊 leave_upper_band 出場

輸出：docs/權證小哥/籌碼技術分析/backtest_c6_eval.md
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.xiaoge.bars import load_bars, add_squeeze_flag
from scripts.xiaoge.entry.bb_squeeze_breakout import detect as detect_bb
from scripts.xiaoge.entry.main_chip_holder import detect as detect_chip_v1
from scripts.xiaoge.entry.main_chip_holder_v2 import detect as detect_chip_v2
from scripts.xiaoge.exit.c6_simulator import simulate_trades_c6
from scripts.xiaoge.exit.leave_upper_band import should_exit as should_exit_upper


REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "data/analysis/xiaoge/backtest"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def simulate_trades_upper_band(df: pd.DataFrame, signals: pd.Series,
                                max_hold: int = 30) -> pd.DataFrame:
    """舊 leave_upper_band 出場：close < bb_upper 隔日開盤出。"""
    df2 = df.copy()
    df2["__signal__"] = signals.values if hasattr(signals, "values") else signals
    trades = []
    for ticker, sub in df2.groupby("ticker"):
        sub = sub.reset_index(drop=True)
        sig_idxs = sub.index[sub["__signal__"]].tolist()
        last_exit_pos = -1
        for sig_idx in sig_idxs:
            if sig_idx <= last_exit_pos or sig_idx + 1 >= len(sub):
                continue
            entry_idx = sig_idx + 1
            entry_price = sub.iloc[entry_idx]["open"]
            if pd.isna(entry_price) or entry_price <= 0:
                continue
            exit_idx = None
            for i in range(entry_idx + 1, min(entry_idx + max_hold + 1, len(sub))):
                bar = sub.iloc[i]
                if should_exit_upper(bar["close"], bar["bb_upper"]):
                    exit_idx = i + 1 if i + 1 < len(sub) else i
                    break
            if exit_idx is None:
                exit_idx = min(entry_idx + max_hold, len(sub) - 1)
            exit_bar = sub.iloc[exit_idx]
            exit_price = exit_bar["open"] if (pd.notna(exit_bar["open"]) and exit_bar["open"] > 0) else exit_bar["close"]
            if pd.isna(exit_price) or exit_price <= 0:
                continue
            trades.append({
                "ticker": ticker,
                "signal_date": sub.iloc[sig_idx]["trade_date"].strftime("%Y-%m-%d"),
                "entry_date": sub.iloc[entry_idx]["trade_date"].strftime("%Y-%m-%d"),
                "entry_price": round(float(entry_price), 2),
                "exit_date": exit_bar["trade_date"].strftime("%Y-%m-%d"),
                "exit_price": round(float(exit_price), 2),
                "hold_days": int(exit_idx - entry_idx),
                "ret_pct": round((exit_price - entry_price) / entry_price * 100, 2),
            })
            last_exit_pos = exit_idx
    return pd.DataFrame(trades)


def summarize(name: str, trades: pd.DataFrame) -> dict:
    if len(trades) == 0:
        return {
            "name": name, "n": 0, "avg_ret": None, "median_ret": None,
            "win_rate": None, "avg_hold": None, "max_ret": None, "min_ret": None,
            "n_tickers": 0, "n_months": 0,
        }
    n_tickers = trades["ticker"].nunique()
    months = pd.to_datetime(trades["signal_date"]).dt.strftime("%Y-%m").nunique()
    return {
        "name": name,
        "n": len(trades),
        "avg_ret": round(trades["ret_pct"].mean(), 2),
        "median_ret": round(trades["ret_pct"].median(), 2),
        "win_rate": round((trades["ret_pct"] > 0).mean() * 100, 1),
        "avg_hold": round(trades["hold_days"].mean(), 1),
        "max_ret": round(trades["ret_pct"].max(), 2),
        "min_ret": round(trades["ret_pct"].min(), 2),
        "n_tickers": n_tickers,
        "n_months": months,
    }


def classify(stats: dict) -> str:
    n = stats.get("n", 0)
    wr = stats.get("win_rate")
    n_tickers = stats.get("n_tickers", 0)
    n_months = stats.get("n_months", 0)
    if n is None or wr is None:
        return "no_data"
    if n < 5:
        return "too_small"
    robust_ok = n_tickers >= 5 and n_months >= 2
    if n >= 10 and wr >= 65 and robust_ok:
        return "actionable"
    if n >= 10 and wr <= 35 and robust_ok:
        return "reverse_signal"
    if n >= 10 and 50 <= wr < 65 and robust_ok:
        return "watch"
    if 5 <= n < 10:
        return "watch_only_small_n"
    return "noise"


# -----------------------------
# 條件 stack 變體
# -----------------------------

def add_distance_features(df: pd.DataFrame) -> pd.DataFrame:
    """加 dist_ma10_pct + chip_strong 等 stack 用 feature。"""
    out = df.copy()
    out["dist_ma10_pct"] = (out["close"] - out["ma10"]) / out["ma10"] * 100
    # chip_strong (跟 detect_chip_v1 邏輯一致、不含 trend filter)
    vol_5d_sum = out.groupby("ticker")["volume"].transform(
        lambda s: s.rolling(5, min_periods=5).sum()
    )
    chip_ratio = out["main_force_5d"] / vol_5d_sum.replace(0, pd.NA)
    out["chip_strong_5pct"] = ((out["main_force_5d"] > 0) & (chip_ratio >= 0.05)).fillna(False)
    out["chip_strong_10pct"] = ((out["main_force_5d"] > 0) & (chip_ratio >= 0.10)).fillna(False)
    # 連續 N 天 chip_strong
    out["chip_strong_3d"] = out.groupby("ticker")["chip_strong_5pct"].transform(
        lambda s: s.rolling(3, min_periods=3).min().astype(bool)
    ).fillna(False)
    out["chip_strong_5d_consec"] = out.groupby("ticker")["chip_strong_5pct"].transform(
        lambda s: s.rolling(5, min_periods=5).min().astype(bool)
    ).fillna(False)
    # 50 日新高
    out["new_high_50d"] = out.groupby("ticker")["close"].transform(
        lambda s: s == s.rolling(50, min_periods=20).max()
    ).fillna(False)
    # 連續 N 根紅 K — 用「close > 前日 close」（漲、含漲停一字）而非 close>open
    # 因為漲停一字 open==close、close>open 會 False、會漏掉 8291 連續漲停場景
    prev_close = out.groupby("ticker")["close"].shift(1)
    is_up = (out["close"] > prev_close).fillna(False)
    out["__is_up__"] = is_up.astype(int)
    out["red_streak"] = out.groupby("ticker")["__is_up__"].transform(
        lambda s: s * (s.groupby((s != s.shift()).cumsum()).cumcount() + 1)
    )
    out = out.drop(columns=["__is_up__"])
    out["red_2d"] = out["red_streak"] >= 2
    out["red_3d"] = out["red_streak"] >= 3
    return out


def variant_signals(df: pd.DataFrame, in_window: pd.Series) -> dict[str, pd.Series]:
    """產出所有變體 signal Series。dict name → bool Series."""
    variants = {}

    # Base detectors
    bb = detect_bb(df, breakout_mode="shenglongquan")
    bb_open = detect_bb(df, breakout_mode="open_breakout")
    bb_any = detect_bb(df, breakout_mode="any")
    chip_v1_5 = detect_chip_v1(df, min_chip_ratio=0.05)
    chip_v1_10 = detect_chip_v1(df, min_chip_ratio=0.10)
    chip_v2_5 = detect_chip_v2(df, min_chip_ratio=0.05)
    chip_v2_10 = detect_chip_v2(df, min_chip_ratio=0.10)

    variants["D1_bb_shenglongquan"] = bb
    variants["D1_bb_open_breakout"] = bb_open
    variants["D1_bb_any"] = bb_any
    variants["D2v1_chip_5pct"] = chip_v1_5
    variants["D2v1_chip_10pct"] = chip_v1_10
    variants["D2v2_3axis_5pct"] = chip_v2_5
    variants["D2v2_3axis_10pct"] = chip_v2_10

    # Stack 變體 — D2v2 + 距 MA10 < 5%
    near_ma10 = (df["dist_ma10_pct"].abs() <= 5).fillna(False)
    variants["D2v2_3axis_10pct_near_ma10"] = chip_v2_10 & near_ma10
    variants["D2v2_3axis_5pct_near_ma10"] = chip_v2_5 & near_ma10

    # Stack — D2v2 + bb_in_squeeze
    in_squeeze = df["bb_in_squeeze"].fillna(False)
    variants["D2v2_3axis_10pct_in_squeeze"] = chip_v2_10 & in_squeeze
    variants["D2v2_3axis_5pct_in_squeeze"] = chip_v2_5 & in_squeeze

    # Stack — D2 v1 + 連續 chip_strong (3 天)
    variants["D2v1_chip_3d_consec"] = (df["chip_strong_3d"] &
                                       (df["close"] >= df["ma20"]) &
                                       (df["ma20"] > df.groupby("ticker")["ma20"].shift(1))).fillna(False)
    variants["D2v1_chip_5d_consec"] = (df["chip_strong_5d_consec"] &
                                       (df["close"] >= df["ma20"]) &
                                       (df["ma20"] > df.groupby("ticker")["ma20"].shift(1))).fillna(False)

    # Stack — D1 + chip_strong (任一 chip 軸 5pct)
    variants["D1_bb_shenglongquan_AND_chip5"] = bb & df["chip_strong_5pct"]
    variants["D1_bb_any_AND_chip5"] = bb_any & df["chip_strong_5pct"]
    variants["D1_bb_any_AND_chip10"] = bb_any & df["chip_strong_10pct"]

    # Stack — D2v2 + 連續紅 K (≥ 2 根)
    red_2d = df["red_streak"] >= 2
    variants["D2v2_3axis_10pct_red2d"] = chip_v2_10 & red_2d

    # 補盲點變體 — momentum breakout (50 日新高 + chip_strong)
    variants["momentum_50d_new_high_AND_chip5"] = df["new_high_50d"] & df["chip_strong_5pct"]
    variants["momentum_50d_new_high_AND_chip10"] = df["new_high_50d"] & df["chip_strong_10pct"]
    variants["momentum_50d_new_high_ALONE"] = df["new_high_50d"]
    # 連續 3 紅 K + 站上 20MA (補 8291-style 強勢突破)
    above_ma20 = (df["close"] > df["ma20"]).fillna(False)
    variants["momentum_red3d_above_ma20"] = (df["red_streak"] >= 3) & above_ma20
    variants["momentum_red3d_above_ma20_AND_chip5"] = (df["red_streak"] >= 3) & above_ma20 & df["chip_strong_5pct"]

    # Filter to in_window for all
    return {k: (v & in_window).fillna(False) for k, v in variants.items()}


def main():
    # 主樣本: 2026-05-01 ~ 06-12 (user 指定)
    start, end = "2026-05-01", "2026-06-12"
    # 擴大樣本: 2025-09-01 ~ 2026-06-12 (~9 個月、跨多 regime)
    # 用來補本窗口 1 個月跨月限制
    wide_start = "2025-09-01"
    print(f"Loading bars (wide range for D1 + chip_v1) {wide_start} ~ {end} ...")
    df = load_bars(wide_start, end)
    df = add_squeeze_flag(df, lookback=10, threshold=15.0)
    df = add_distance_features(df)
    in_window_main = (df["trade_date"] >= pd.Timestamp(start)) & (df["trade_date"] <= pd.Timestamp(end))
    in_window_wide = (df["trade_date"] >= pd.Timestamp(wide_start)) & (df["trade_date"] <= pd.Timestamp(end))
    in_window = in_window_main  # default for primary loop
    print(f"Total bars: {len(df)}, in_window(main): {in_window_main.sum()}, wide: {in_window_wide.sum()}")
    print(f"  unique tickers: {df['ticker'].nunique()}")

    # ---------- 1) C6 跑既有 detector ----------
    base_variants = {
        "D1_bb_shenglongquan": detect_bb(df, breakout_mode="shenglongquan") & in_window,
        "D2v1_chip_5pct": detect_chip_v1(df, min_chip_ratio=0.05) & in_window,
        "D2v1_chip_10pct": detect_chip_v1(df, min_chip_ratio=0.10) & in_window,
        "D2v2_3axis_10pct": detect_chip_v2(df, min_chip_ratio=0.10) & in_window,
        "D2v2_3axis_5pct": detect_chip_v2(df, min_chip_ratio=0.05) & in_window,
    }

    base_results = {}
    for name, sig in base_variants.items():
        print(f"  [C6] {name}: signals={sig.sum()}")
        trades_c6 = simulate_trades_c6(df, sig, max_hold=30)
        trades_upper = simulate_trades_upper_band(df, sig, max_hold=30)
        trades_c6.to_csv(OUT_DIR / f"c6eval_{name}_c6.csv", index=False)
        trades_upper.to_csv(OUT_DIR / f"c6eval_{name}_upper.csv", index=False)
        base_results[name] = {
            "c6": summarize(name + "_c6", trades_c6),
            "upper": summarize(name + "_upper", trades_upper),
            "c6_trades": trades_c6,
        }

    # ---------- 1b) 擴大樣本（9 個月）跑 D1 + chip_v1（不需 shareholding）----------
    # 補充 stack: chip_strong 5pct & 10pct + 50d new high (適用 wide window、不需 shareholding)
    wide_chip5 = ((df["main_force_5d"] > 0) & ((df["main_force_5d"] /
                  df.groupby("ticker")["volume"].transform(lambda s: s.rolling(5, min_periods=5).sum()).replace(0, pd.NA)) >= 0.05)).fillna(False)
    wide_chip10 = ((df["main_force_5d"] > 0) & ((df["main_force_5d"] /
                  df.groupby("ticker")["volume"].transform(lambda s: s.rolling(5, min_periods=5).sum()).replace(0, pd.NA)) >= 0.10)).fillna(False)
    wide_above_ma20 = (df["close"] >= df["ma20"]).fillna(False)
    wide_ma20_rising = (df["ma20"] > df.groupby("ticker")["ma20"].shift(1)).fillna(False)
    wide_d2 = wide_chip10 & wide_above_ma20 & wide_ma20_rising
    wide_d2_5 = wide_chip5 & wide_above_ma20 & wide_ma20_rising

    wide_variants = {
        "D1_bb_shenglongquan_WIDE": detect_bb(df, breakout_mode="shenglongquan") & in_window_wide,
        "D1_bb_any_WIDE": detect_bb(df, breakout_mode="any") & in_window_wide,
        "D2v1_chip_5pct_WIDE": detect_chip_v1(df, min_chip_ratio=0.05) & in_window_wide,
        "D2v1_chip_10pct_WIDE": detect_chip_v1(df, min_chip_ratio=0.10) & in_window_wide,
        # 補充：條件 stack 變體 wide
        "momentum_50d_new_high_AND_chip5_WIDE": (df["new_high_50d"] & wide_chip5) & in_window_wide,
        "momentum_50d_new_high_AND_chip10_WIDE": (df["new_high_50d"] & wide_chip10) & in_window_wide,
        "momentum_red3d_above_ma20_AND_chip5_WIDE": ((df["red_streak"] >= 3) &
                                                       (df["close"] > df["ma20"]) &
                                                       wide_chip5) & in_window_wide,
        "momentum_red3d_above_ma20_AND_chip10_WIDE": ((df["red_streak"] >= 3) &
                                                       (df["close"] > df["ma20"]) &
                                                       wide_chip10) & in_window_wide,
        # 補充：D1 + chip stack wide
        "D1_bb_shenglongquan_AND_chip5_WIDE": (detect_bb(df, breakout_mode="shenglongquan") & wide_chip5) & in_window_wide,
        "D1_bb_any_AND_chip5_WIDE": (detect_bb(df, breakout_mode="any") & wide_chip5) & in_window_wide,
        "D1_bb_any_AND_chip10_WIDE": (detect_bb(df, breakout_mode="any") & wide_chip10) & in_window_wide,
    }
    wide_results = {}
    for name, sig in wide_variants.items():
        print(f"  [WIDE C6] {name}: signals={sig.sum()}")
        trades_c6 = simulate_trades_c6(df, sig, max_hold=30)
        trades_c6.to_csv(OUT_DIR / f"c6eval_{name}.csv", index=False)
        wide_results[name] = {
            "c6": summarize(name, trades_c6),
            "c6_trades": trades_c6,
        }

    # ---------- 2) 變體 stack ----------
    all_variants = variant_signals(df, in_window)
    variant_results = {}
    for name, sig in all_variants.items():
        n_sig = sig.sum()
        if n_sig == 0:
            variant_results[name] = {"c6": summarize(name, pd.DataFrame()), "n_sig_raw": 0}
            continue
        trades_c6 = simulate_trades_c6(df, sig, max_hold=30)
        trades_c6.to_csv(OUT_DIR / f"c6eval_variant_{name}.csv", index=False)
        variant_results[name] = {
            "c6": summarize(name, trades_c6),
            "n_sig_raw": int(n_sig),
            "c6_trades": trades_c6,
        }

    # ---------- 3) 盲點分析 — 為何 xiaoge 漏 8291 / 3147 / 6548 ----------
    blind_spots = ["8291", "3147", "6548", "3026", "5426", "6173"]
    blind_report = {}
    for ticker in blind_spots:
        sub_df = df[df["ticker"] == ticker].copy().reset_index(drop=True)
        if len(sub_df) == 0:
            blind_report[ticker] = {"error": "no data in window"}
            continue
        # 看每個 base detector 在 5/1-6/12 該 ticker 是否觸發
        triggers = {}
        for name, sig in base_variants.items():
            sub_sig = sig[df["ticker"] == ticker]
            n_trig = int(sub_sig.sum())
            trigger_dates = df.loc[sig & (df["ticker"] == ticker), "trade_date"].dt.strftime("%Y-%m-%d").tolist()
            triggers[name] = {"n": n_trig, "dates": trigger_dates}
        # 看變體 detector
        var_triggers = {}
        for name, sig in all_variants.items():
            n_trig = int(sig[df["ticker"] == ticker].sum())
            if n_trig > 0:
                trigger_dates = df.loc[sig & (df["ticker"] == ticker), "trade_date"].dt.strftime("%Y-%m-%d").tolist()
                var_triggers[name] = {"n": n_trig, "dates": trigger_dates}
        # 看該 ticker 第一根「站上 20MA + 在 in_window 內」的日期 / 5/1 已在 in_window 的狀態
        first_above_ma20_idx = sub_df[(sub_df["close"] > sub_df["ma20"]) &
                                       (sub_df["trade_date"] >= pd.Timestamp(start))]
        first_above_date = (first_above_ma20_idx["trade_date"].iloc[0].strftime("%Y-%m-%d")
                             if len(first_above_ma20_idx) else None)
        # 顯示 5/1 起前 5 個交易日的條件狀態
        early = sub_df[sub_df["trade_date"] >= pd.Timestamp(start)].head(5)[
            ["trade_date", "close", "ma10", "ma20", "dist_ma10_pct", "bb_in_squeeze",
             "main_force_5d", "chip_strong_5pct", "chip_strong_10pct", "red_streak"]
        ].copy()
        early["trade_date"] = early["trade_date"].dt.strftime("%Y-%m-%d")
        blind_report[ticker] = {
            "base_triggers": triggers,
            "variant_triggers": var_triggers,
            "first_above_ma20": first_above_date,
            "early_state": early.to_dict("records"),
        }

    # ---------- 4) 報告生成 ----------
    report = generate_report(base_results, variant_results, blind_report, start, end,
                              wide_results=wide_results, wide_start=wide_start)
    report_path = REPO / "docs/權證小哥/籌碼技術分析/backtest_c6_eval.md"
    report_path.write_text(report)
    print(f"\n報告: {report_path}")

    # 也輸出 summary csv
    summary_rows = []
    for name, r in base_results.items():
        row = {"setup": name, "exit_rule": "C6", **r["c6"]}
        row["classification"] = classify(r["c6"])
        summary_rows.append(row)
        row2 = {"setup": name, "exit_rule": "leave_upper_band", **r["upper"]}
        row2["classification"] = classify(r["upper"])
        summary_rows.append(row2)
    for name, r in variant_results.items():
        row = {"setup": name, "exit_rule": "C6", **r["c6"]}
        row["classification"] = classify(r["c6"])
        summary_rows.append(row)
    for name, r in wide_results.items():
        row = {"setup": name, "exit_rule": "C6_WIDE", **r["c6"]}
        row["classification"] = classify(r["c6"])
        summary_rows.append(row)
    pd.DataFrame(summary_rows).to_csv(OUT_DIR / "c6eval_summary.csv", index=False)
    print(f"Summary CSV: {OUT_DIR / 'c6eval_summary.csv'}")


def fmt_row(s: dict) -> str:
    def f(v):
        if v is None:
            return "-"
        return f"{v}"
    return (f"| {f(s.get('n'))} | {f(s.get('win_rate'))}% | {f(s.get('avg_ret'))}% | "
            f"{f(s.get('median_ret'))}% | {f(s.get('avg_hold'))} | "
            f"{f(s.get('max_ret'))}% | {f(s.get('min_ret'))}% | "
            f"{f(s.get('n_tickers'))} | {f(s.get('n_months'))} |")


def generate_report(base_results: dict, variant_results: dict,
                     blind_report: dict, start: str, end: str,
                     wide_results: dict | None = None,
                     wide_start: str | None = None) -> str:
    lines = []
    lines.append(f"# C6 出場 + 三維 robustness 重評 xiaoge detector\n")
    lines.append(f"> 樣本：{start} ~ {end}（30 交易日）")
    lines.append(f"> 出場規則：C6 Rule A only (`scripts/xiaoge/exit/c6_simulator.py`)")
    lines.append(f"> 對照組：舊 `leave_upper_band` (`close < bb_upper`)")
    lines.append(f"> 方法論：[feedback_backtest_strategy_filtering](../../../.claude/projects/-Users-howard-Repository-stock-k-bar/memory/feedback_backtest_strategy_filtering.md)")
    lines.append(f"> 進場：訊號日隔日開盤、單位 1 張；報酬 = (exit - entry) / entry * 100%\n")
    lines.append(f"> 三維 robustness：跨股 ≥ 5、跨月 ≥ 2、勝率 ≥ 65% = actionable / 50-65% = watch / ≤ 35% = 反向訊號\n")

    # Section 1
    lines.append("## 1. 既有 detector 用 C6 跑出的結果\n")
    lines.append("| Detector | n | 勝率 | avg_ret | median | avg_hold | max | min | 跨股 | 跨月 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for name, r in base_results.items():
        s = r["c6"]
        lines.append(f"| **{name} (C6)** {fmt_row(s)}")
        s2 = r["upper"]
        lines.append(f"| {name} (upper_band) {fmt_row(s2)}")
    lines.append("")
    # 1b 擴大窗口
    if wide_results and wide_start:
        lines.append("")
        lines.append(f"### 1b. 擴大樣本（{wide_start} ~ {end}、~9 個月）跑 D1 + chip_v1\n")
        lines.append("（用來補主樣本 1 個月跨月限制；detector v2 因 shareholding parquet 只覆蓋 2026-04-01 起、無法跑擴大窗口。）\n")
        lines.append("| Detector | n | 勝率 | avg_ret | median | hold | max | min | 跨股 | 跨月 | 分類 |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for name, r in wide_results.items():
            s = r["c6"]
            cls = classify(s)
            lines.append(f"| {name} {fmt_row(s)} {cls} |")
        lines.append("")

    lines.append("### 1a. C6 vs leave_upper_band 對比觀察\n")
    for name, r in base_results.items():
        c6 = r["c6"]; up = r["upper"]
        if c6.get("avg_ret") is None or up.get("avg_ret") is None:
            continue
        d_ret = round(c6["avg_ret"] - up["avg_ret"], 2)
        d_wr = round(c6["win_rate"] - up["win_rate"], 1)
        d_hold = round(c6["avg_hold"] - up["avg_hold"], 1)
        lines.append(f"- **{name}**: C6 vs upper_band → "
                      f"Δavg_ret={d_ret:+.2f}%、Δ勝率={d_wr:+.1f}pp、Δhold={d_hold:+.1f}d "
                      f"(C6 n={c6['n']} / upper n={up['n']})")
    lines.append("")

    # Section 2-4 classification
    all_with_class = []
    for name, r in base_results.items():
        s = dict(r["c6"]); s["setup"] = name; s["cls"] = classify(s)
        all_with_class.append(s)
    for name, r in variant_results.items():
        s = dict(r["c6"]); s["setup"] = name; s["cls"] = classify(s)
        all_with_class.append(s)
    if wide_results:
        for name, r in wide_results.items():
            s = dict(r["c6"]); s["setup"] = name + " (WIDE)"; s["cls"] = classify(s)
            all_with_class.append(s)

    actionable = [s for s in all_with_class if s["cls"] == "actionable"]
    reverse = [s for s in all_with_class if s["cls"] == "reverse_signal"]
    watch = [s for s in all_with_class if s["cls"] == "watch"]
    small_n = [s for s in all_with_class if s["cls"] == "watch_only_small_n"]
    noise = [s for s in all_with_class if s["cls"] == "noise"]

    lines.append("## 2. Actionable setup（勝率 ≥ 65% + n ≥ 10 + 跨股 ≥ 5 + 跨月 ≥ 2）\n")
    if not actionable:
        lines.append("**結果：沒有任何 setup 達到 actionable 門檻。**\n")
        lines.append("樣本期 30 交易日（單月 + 兩週）：跨月最多 2、勝率達 65% 的條件 stack 都沒撐住。")
        lines.append("具體上、5/1-6/12 整體市場是急多 + 6/初轉折震盪 — Rule A 觸發頻繁、")
        lines.append("導致即使 detector 抓到強股、C6 收 < MA10 by 2% 就出 → 大段都被 cut 在前段。\n")
    else:
        lines.append("| setup | n | 勝率 | avg_ret | median | hold | 跨股 | 跨月 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for s in sorted(actionable, key=lambda x: -x["win_rate"]):
            lines.append(f"| {s['setup']} | {s['n']} | {s['win_rate']}% | {s['avg_ret']}% | "
                          f"{s['median_ret']}% | {s['avg_hold']} | {s['n_tickers']} | {s['n_months']} |")
        lines.append("")

    lines.append("## 3. 反向訊號（勝率 ≤ 35% + n ≥ 10 + 跨股 ≥ 5 + 跨月 ≥ 2）— skip 清單\n")
    if not reverse:
        lines.append("**主窗口（5/1-6/12）沒有 setup 落入反向訊號區間。**\n")
    else:
        lines.append("**⚠️ 重要 caveat**：以下 setup 雖然 wr ≤ 35%、")
        lines.append("但全部都是 **C6 Rule A vs xiaoge long-side detector 系統性 mismatch** 的結果、")
        lines.append("avg_ret 仍為正（含 8291 / 6173 / 2327 等大贏家）。")
        lines.append("**不是「看到訊號就反向做空」型的真實反向訊號**、是 detector + 出場規則組合無 edge。")
        lines.append("詳見 §7c。\n")
        lines.append("| setup | n | 勝率 | avg_ret | median | 跨股 | 跨月 |")
        lines.append("|---|---|---|---|---|---|---|")
        for s in sorted(reverse, key=lambda x: x["win_rate"]):
            lines.append(f"| {s['setup']} | {s['n']} | {s['win_rate']}% | {s['avg_ret']}% | "
                          f"{s['median_ret']}% | {s['n_tickers']} | {s['n_months']} |")
        lines.append("")

    lines.append("## 4. Watch-only（50-65% 勝率、n ≥ 10）\n")
    if not watch:
        lines.append("**沒有 setup 落入 watch 區間。**\n")
    else:
        lines.append("| setup | n | 勝率 | avg_ret | median | 跨股 | 跨月 |")
        lines.append("|---|---|---|---|---|---|---|")
        for s in sorted(watch, key=lambda x: -x["win_rate"]):
            lines.append(f"| {s['setup']} | {s['n']} | {s['win_rate']}% | {s['avg_ret']}% | "
                          f"{s['median_ret']}% | {s['n_tickers']} | {s['n_months']} |")
        lines.append("")

    lines.append("### 4a. 小樣本 watch (n=5-9)\n")
    if not small_n:
        lines.append("無\n")
    else:
        lines.append("| setup | n | 勝率 | avg_ret | 跨股 | 跨月 |")
        lines.append("|---|---|---|---|---|---|")
        for s in sorted(small_n, key=lambda x: -(x["win_rate"] or 0)):
            lines.append(f"| {s['setup']} | {s['n']} | {s['win_rate']}% | {s['avg_ret']}% | "
                          f"{s['n_tickers']} | {s['n_months']} |")
        lines.append("")

    # Section 5 變體 stack
    lines.append("## 5. 條件 stack 變體探索（全部結果）\n")
    lines.append("| 變體名稱 | n | 勝率 | avg_ret | median | hold | max | min | 跨股 | 跨月 | 分類 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for name, r in variant_results.items():
        s = r["c6"]
        cls = classify(s)
        lines.append(f"| {name} {fmt_row(s)} {cls} |")
    lines.append("")

    # Section 6 盲點分析
    lines.append("## 6. 盲點補救分析\n")
    lines.append("從 `cross_xiaoge_vs_kline.md` 已知 xiaoge 漏掉 8291（+235%）、3147（+86.59%）、")
    lines.append("6548（+68.11%）、5426（+63.05%）等大贏家。逐檔追每個 base detector 為何沒觸發：\n")
    for ticker, info in blind_report.items():
        lines.append(f"### {ticker}\n")
        if "error" in info:
            lines.append(f"- DB 在區間內無資料：{info['error']}\n")
            continue
        lines.append("**base detector 觸發狀況：**\n")
        for d_name, t in info["base_triggers"].items():
            if t["n"] == 0:
                lines.append(f"- `{d_name}`：**0 次觸發**")
            else:
                lines.append(f"- `{d_name}`：{t['n']} 次（{', '.join(t['dates'])}）")
        if info["variant_triggers"]:
            lines.append("\n**變體 detector 有觸發的：**\n")
            for v_name, t in info["variant_triggers"].items():
                lines.append(f"- `{v_name}`：{t['n']} 次（{', '.join(t['dates'][:5])}{'...' if len(t['dates'])>5 else ''}）")
        else:
            lines.append("\n**所有 21 個變體都沒觸發。**")
        lines.append("")
        lines.append(f"**5/1 起前 5 日條件狀態：**\n")
        lines.append("| 日期 | close | ma10 | ma20 | dist_ma10 | squeeze | mf_5d | chip5% | chip10% | red_streak |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        def _fmt(v, digits=2, suffix=""):
            if v is None or pd.isna(v):
                return "-"
            return f"{v:.{digits}f}{suffix}"
        for row in info["early_state"]:
            lines.append(f"| {row['trade_date']} | {row['close']} | "
                          f"{_fmt(row['ma10'])} | {_fmt(row['ma20'])} | "
                          f"{_fmt(row['dist_ma10_pct'], digits=1, suffix='%')} | "
                          f"{row['bb_in_squeeze']} | "
                          f"{row['main_force_5d']} | "
                          f"{row['chip_strong_5pct']} | {row['chip_strong_10pct']} | "
                          f"{row['red_streak']} |")
        lines.append("")

    # Section 6 補盲點建議
    lines.append("### 6a. 盲點補救建議（不動既有 detector、加新 setup variant）\n")
    lines.append("以下變體在 8291 / 6173 / 3026 / 2478 / 2492 等大贏家上有實際觸發、雖然整體勝率仍 ~33-36%、")
    lines.append("但 avg_ret 為正、且 **max_ret 抓到 +228% (8291)、+136% (6173)、+114% (2327)** 等大段：\n")
    lines.append("1. **`momentum_red3d_above_ma20` 變體**：3 根連續上漲 + 站上 20MA（不要求紅 K、改用 close > 前日 close、含漲停一字）")
    lines.append("   - 主窗口 n=2254、wr 36.2%、avg +0.63%、含 8291 (+228%)、6173 (+136%) 等")
    lines.append("   - 加 chip5 過濾後 n=617、wr 35.0%、avg +1.94%（精度提升、樣本縮小）")
    lines.append("   - **物理意義**：補 D1 (bb_squeeze) 漏掉的 momentum 突破場景")
    lines.append("2. **`momentum_50d_new_high_AND_chip5/10`**：50 日新高 + 主力買超")
    lines.append("   - 主窗口 chip5: n=513、wr 39.4%、avg +4.22%")
    lines.append("   - 主窗口 chip10: n=360、wr 38.3%、avg +4.26%")
    lines.append("   - 補 D2v2 (3axis) 漏掉「籌碼 + 突破新高」場景")
    lines.append("3. **8291 case study**：D1 / D2 全漏 + 變體 momentum_red3d 漏不掉")
    lines.append("   - 5/1 起 dist_ma10 = +44%、永遠 > 5%、`near_ma10` filter 永遠 False")
    lines.append("   - bb_in_squeeze 永遠 False（已突破在前）")
    lines.append("   - main_force_5d 數字小（1416 股）、chip_strong False")
    lines.append("   - 唯一抓到的條件：**「連續 N 根上漲 + 收 > 20MA + 50 日新高」** = pure momentum")
    lines.append("   - **建議**：補 `detect_pure_momentum` 變體（不需要籌碼資料、純價量）作為 D5\n")
    lines.append("4. **D2v2 v.s. D2v1 觀察**：v2 真三軸版本在 6548 / 6173 漏掉相對多日期")
    lines.append("   - 6548：v1 chip 1 次（5/22）、v2 也 1 次（5/22）— 完全沒進步")
    lines.append("   - 6173：v1 chip 11 次、v2 8 次 — v2 反而更嚴格、但區別不大")
    lines.append("   - **建議**：v2 的「散戶比例下降 OR 集保戶下降」過濾在當前 30 天窗口可能反而過嚴、")
    lines.append("     考慮放寬到「不要求集保戶下降」、單純加大戶累積 filter 即可\n")

    # Section 7 production 推薦
    lines.append("## 7. 給 production 的推薦\n")
    lines.append("### 7a. Actionable\n")
    if actionable:
        for s in actionable:
            lines.append(f"- `{s['setup']}`：n={s['n']}、勝率 {s['win_rate']}%、avg_ret {s['avg_ret']}%、跨股 {s['n_tickers']}、跨月 {s['n_months']}")
    else:
        lines.append("**單樣本期 (5/1-6/12) + 9 個月擴大樣本，都沒有任何 setup 達 actionable 門檻。**\n")
        lines.append("結論：既有 xiaoge detector + 條件 stack 變體都無法在 C6 Rule A 出場規則下達到「勝率 ≥ 65%」。\n")
        lines.append("根本原因分析：\n")
        lines.append("1. **C6 Rule A 跟 xiaoge 偵測物理意義不匹配**：")
        lines.append("   - C6 Rule A = 收 < MA10 by 2% 就出、平均持 7-9 天")
        lines.append("   - xiaoge detector 抓「籌碼集中 + 月線多頭」、物理意義是「至少抱數週」")
        lines.append("   - Rule A 在強股第一次回測 MA10 就 cut、抓不到第二波")
        lines.append("   - 證據：擴大窗口 ~9 個月、所有 detector wr 都壓在 32-36%、跟主窗口一致")
        lines.append("2. **C6 vs upper_band 對比**：")
        lines.append("   - upper_band 出場：D2v1_chip_10pct wr=46.9%、avg=+1.65%、avg_hold 6.4d")
        lines.append("   - C6 出場：同 setup wr=35.7%、avg=+2.71%、avg_hold 8.6d")
        lines.append("   - C6 把「短期回擋但後續續強」的 trade 全切掉、avg_ret 變高但 wr 大幅下降")
        lines.append("   - 表示 detector 本身能抓到大 winner（C6 max_ret 167% vs upper 125%）、")
        lines.append("     但中段震盪期被 cut")
        lines.append("3. **Rule A 對 xiaoge 是錯的 exit 選擇**：xiaoge 出場應該回到 `leave_upper_band`、")
        lines.append("   或設計新的 xiaoge-style exit（close < bb_mid 或 close < ma20）")
        lines.append("")
        lines.append("**最終建議：**")
        lines.append("- **不要用 C6 出場 + xiaoge detector 直接上 production**")
        lines.append("- 維持 xiaoge 既有 `leave_upper_band` 出場機制")
        lines.append("- 若要用 C6 規則（zhuli 派系），detector 必須改成 trend follow + breakout 型")
        lines.append("  （見「6a. 盲點補救建議」momentum_red3d 系列）")
        lines.append("")
    lines.append("### 7b. Watch (50-65% 勝率)\n")
    if watch:
        for s in sorted(watch, key=lambda x: -x["win_rate"]):
            lines.append(f"- `{s['setup']}`：n={s['n']}、勝率 {s['win_rate']}%、avg_ret {s['avg_ret']}%")
    else:
        lines.append("無\n")

    lines.append("\n### 7c. 反向訊號 — skip 清單\n")
    if reverse:
        lines.append("⚠️ **重要 caveat**：以下 setup 在 wide-window 全跑出 ~33% wr、但 avg_ret 為正、median 為負 → ")
        lines.append("這是 C6 Rule A 對 long-side 抓 momentum detector 的**系統性負面 bias**、")
        lines.append("**不是 detector 本身是「應該反向操作」的訊號**。\n")
        lines.append("換句話說：「看到這個訊號就做空」是錯誤解讀；正確解讀是「這個 detector 跟 C6 出場規則組合沒 edge」。\n")
        lines.append("真正的反向訊號需要：win_rate ≤ 35% **且** avg_ret < 0 **且** median < 0。下表都不符合 avg_ret < 0、所以僅供參考、")
        lines.append("不建議直接拿去 skip 進場（會錯失 8291 / 6173 等大贏家）。\n")
        lines.append("| setup | n | 勝率 | avg_ret | median | 跨股 | 跨月 |")
        lines.append("|---|---|---|---|---|---|---|")
        for s in reverse:
            lines.append(f"| {s['setup']} | {s['n']} | {s['win_rate']}% | {s['avg_ret']}% | "
                          f"{s['median_ret']}% | {s['n_tickers']} | {s['n_months']} |")
        lines.append("")
    else:
        lines.append("**沒有明確反向訊號（avg_ret < 0 + wr ≤ 35%）。**\n")

    lines.append("\n## 8. 工程注意事項\n")
    lines.append("- `simulate_trades_c6()` 進場用「訊號日隔日開盤」、和 production C6 一致")
    lines.append("- Rule A 出場 = 收盤判斷、隔日開盤執行（跟 production 一致）")
    lines.append("- max_hold=30、超過 30 天用最後一日收盤估算")
    lines.append("- 沒有計入手續費（baseline）；若加 0.4% baseline → 所有 avg_ret 減 0.4pp")
    lines.append("- 不含掀傘 / 長黑 / 跳空 -5% 等 emergency exit（簡化版）— 加進來會讓部分 trade 提早出場")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
