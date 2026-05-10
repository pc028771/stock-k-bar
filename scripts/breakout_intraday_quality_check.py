from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd

from breakout_attack_strategy_check import MIN_AVG_VOLUME_20, MIN_CLOSE, add_trade_fields
from false_breakdown_strategy_check import add_market_regime
from finmind_intraday_kline_check import fetch_kbar, intraday_features
from kline_course_backtest import add_features, add_signals, load_bars


OUT_DIR = Path("data/analysis/kline_course_backtest")
REPORT_PATH = Path("docs/K線力量判斷入門/backtests/breakout_intraday_quality_check.md")
GROUPS = ["next_not_low_open", "next_low_open"]
REGIMES = ["bull", "range", "bear"]


def tradable_mask(df: pd.DataFrame) -> pd.Series:
    attention = pd.to_numeric(df["is_attention_stock"], errors="coerce").fillna(0).astype(int)
    disposition = pd.to_numeric(df["is_disposition_stock"], errors="coerce").fillna(0).astype(int)
    return (
        df["breakout_attack"].fillna(False)
        & (attention == 0)
        & (disposition == 0)
        & (df["avg_volume_20"] >= MIN_AVG_VOLUME_20)
        & (df["close"] >= MIN_CLOSE)
    )


def add_group_flags(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    base = tradable_mask(df)
    df["next_not_low_open_group"] = base & df["breakout_next_not_low_open"].fillna(False)
    df["next_low_open_group"] = base & df["breakout_next_low_open"].fillna(False)
    return df


def sample_recent_by_regime(rows: pd.DataFrame, target_total: int) -> pd.DataFrame:
    rows = rows.sort_values(["trade_date", "ticker"], ascending=[False, True]).copy()
    grouped = {regime: rows[rows["market_regime"] == regime].copy() for regime in REGIMES}

    target_by_regime = {regime: target_total // len(REGIMES) for regime in REGIMES}
    for regime in REGIMES[: target_total % len(REGIMES)]:
        target_by_regime[regime] += 1

    chosen: list[pd.DataFrame] = []
    selected_counts = {regime: 0 for regime in REGIMES}

    for regime in REGIMES:
        take = min(target_by_regime[regime], len(grouped[regime]))
        if take > 0:
            chosen.append(grouped[regime].head(take))
            selected_counts[regime] = take

    selected_total = sum(selected_counts.values())
    remaining = target_total - selected_total
    if remaining > 0:
        extras = []
        for regime in REGIMES:
            available = grouped[regime].iloc[selected_counts[regime] :]
            if not available.empty:
                extras.append(available)
        if extras:
            extra_pool = pd.concat(extras, ignore_index=False).sort_values(["trade_date", "ticker"], ascending=[False, True])
            chosen.append(extra_pool.head(remaining))

    if not chosen:
        return rows.head(0).copy()

    sampled = pd.concat(chosen, ignore_index=False)
    sampled = sampled.drop_duplicates(subset=["ticker", "trade_date"]).sort_values(["trade_date", "ticker"], ascending=[False, True])
    return sampled.head(target_total).copy()


def build_sample(target_per_group: int) -> pd.DataFrame:
    df = add_group_flags(add_market_regime(add_trade_fields(add_signals(add_features(load_bars())))))
    samples = []
    for group in GROUPS:
        mask_col = f"{group}_group"
        rows = df[df[mask_col]].copy()
        rows = rows.dropna(subset=["ret_10d_net", "ret_close_basis_10d"])
        sampled = sample_recent_by_regime(rows, target_per_group)
        sampled.insert(0, "group", group)
        samples.append(
            sampled[
                [
                    "group",
                    "ticker",
                    "trade_date",
                    "market_regime",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "ret_10d_net",
                    "ret_20d_net",
                    "ret_close_basis_10d",
                    "ret_close_basis_20d",
                ]
            ]
        )
    return pd.concat(samples, ignore_index=True)


def enrich_intraday(sample: pd.DataFrame, token: str, sleep_seconds: float) -> pd.DataFrame:
    records = []
    for row in sample.itertuples(index=False):
        trade_date = pd.Timestamp(row.trade_date).strftime("%Y-%m-%d")
        kbar = fetch_kbar(str(row.ticker), trade_date, token, sleep_seconds)
        record = row._asdict()
        record["trade_date"] = trade_date
        record.update(intraday_features(kbar))
        records.append(record)
    return pd.DataFrame(records)


def summarize_group(rows: pd.DataFrame) -> pd.DataFrame:
    valid = rows.replace([float("inf"), float("-inf")], pd.NA).dropna(
        subset=[
            "intraday_return_pct",
            "intraday_close_pos",
            "intraday_drawdown_pct",
            "ret_10d_net",
            "ret_close_basis_10d",
        ]
    )
    out = []
    for group, g in valid.groupby("group", dropna=False):
        out.append(
            {
                "group": group,
                "n": int(len(g)),
                "mean_intraday_return_pct": round(float(g["intraday_return_pct"].mean()), 3),
                "mean_intraday_close_pos": round(float(g["intraday_close_pos"].mean()), 3),
                "mean_intraday_drawdown_pct": round(float(g["intraday_drawdown_pct"].mean()), 3),
                "strong_attack_rate_pct": round(float(g["intraday_strong_attack"].mean() * 100), 2),
                "attack_failure_rate_pct": round(float(g["intraday_attack_failure"].mean() * 100), 2),
                "below_open_after_1130_rate_pct": round(float(g["below_open_after_1130"].mean() * 100), 2),
                "low_after_high_break_open_rate_pct": round(float(g["low_after_high_break_open"].mean() * 100), 2),
                "mean_close_basis_10d_pct": round(float(g["ret_close_basis_10d"].mean() * 100), 3),
                "mean_10d_net_pct": round(float(g["ret_10d_net"].mean() * 100), 3),
            }
        )
    return pd.DataFrame(out)


def summarize_group_regime(rows: pd.DataFrame) -> pd.DataFrame:
    valid = rows.replace([float("inf"), float("-inf")], pd.NA).dropna(subset=["market_regime", "intraday_close_pos", "ret_10d_net"])
    out = []
    for (group, regime), g in valid.groupby(["group", "market_regime"], dropna=False):
        out.append(
            {
                "group": group,
                "market_regime": regime,
                "n": int(len(g)),
                "mean_intraday_close_pos": round(float(g["intraday_close_pos"].mean()), 3),
                "strong_attack_rate_pct": round(float(g["intraday_strong_attack"].mean() * 100), 2),
                "attack_failure_rate_pct": round(float(g["intraday_attack_failure"].mean() * 100), 2),
                "below_open_after_1130_rate_pct": round(float(g["below_open_after_1130"].mean() * 100), 2),
                "mean_close_basis_10d_pct": round(float(g["ret_close_basis_10d"].mean() * 100), 3),
                "mean_10d_net_pct": round(float(g["ret_10d_net"].mean() * 100), 3),
            }
        )
    return pd.DataFrame(out).sort_values(["group", "market_regime"])


def summarize_sample_mix(rows: pd.DataFrame) -> pd.DataFrame:
    counts = (
        rows.groupby(["group", "market_regime"], dropna=False)
        .size()
        .rename("n")
        .reset_index()
        .sort_values(["group", "market_regime"])
    )
    return counts


def markdown_table(rows: pd.DataFrame, cols: list[str]) -> str:
    table_rows = rows[cols].copy()
    header = "| " + " | ".join(cols) + " |"
    divider = "| " + " | ".join(["---"] * len(cols)) + " |"
    lines = [header, divider]
    for row in table_rows.itertuples(index=False):
        values = ["" if pd.isna(v) else str(v) for v in row]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def write_report(summary: pd.DataFrame, regime_summary: pd.DataFrame, sample_mix: pd.DataFrame, detail: pd.DataFrame, target_per_group: int) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    sample_start = str(pd.to_datetime(detail["trade_date"]).min().date())
    sample_end = str(pd.to_datetime(detail["trade_date"]).max().date())
    summary_idx = summary.set_index("group")
    not_low = summary_idx.loc["next_not_low_open"]
    low_open = summary_idx.loc["next_low_open"]
    total_rows = int(len(detail))
    valid_rows = int(summary["n"].sum())
    missing_rows = total_rows - valid_rows

    md = f"""# 突破策略分K攻擊品質驗證

資料庫：`/Users/howard/.four_seasons/data.sqlite` + FinMind `TaiwanStockKBar`

樣本：{sample_start} 至 {sample_end}

抽樣方式：每組目標 {target_per_group} 筆，依 `bull / range / bear` 分層，在各 regime 內從最新訊號往回抓。

目的：比較 `next_not_low_open` 與 `next_low_open` 在突破當天的分K攻擊品質差異，確認 `breakout_next_not_low_open` 是否值得保留為條件式標記。

有效分K樣本：{valid_rows} / {total_rows}（缺失 {missing_rows} 筆）

## 抽樣結構

{markdown_table(sample_mix, ["group", "market_regime", "n"])}

## 分K摘要

{markdown_table(summary, ["group", "n", "mean_intraday_return_pct", "mean_intraday_close_pos", "mean_intraday_drawdown_pct", "strong_attack_rate_pct", "attack_failure_rate_pct", "below_open_after_1130_rate_pct", "low_after_high_break_open_rate_pct", "mean_close_basis_10d_pct", "mean_10d_net_pct"])}

## Regime 分組

{markdown_table(regime_summary, ["group", "market_regime", "n", "mean_intraday_close_pos", "strong_attack_rate_pct", "attack_failure_rate_pct", "below_open_after_1130_rate_pct", "mean_close_basis_10d_pct", "mean_10d_net_pct"])}

## 判讀

- `next_not_low_open` 若在 `intraday_close_pos`、`strong_attack_rate_pct`、`below_open_after_1130_rate_pct` 上 consistently 優於 `next_low_open`，可視為突破當天的攻擊品質標記。
- 若它的分K品質較好，但 `mean_10d_net_pct` 仍不如 `next_low_open`，代表問題主要出在隔日進場價差，而不是突破當天不夠強。
- 只有在某些 regime 下同時呈現「分K品質更好」與「實際 10 日報酬不差」時，才值得升級為條件式濾網。

## 本輪重點

- `next_not_low_open` 分K收盤位置：{not_low["mean_intraday_close_pos"]:.3f}
- `next_low_open` 分K收盤位置：{low_open["mean_intraday_close_pos"]:.3f}
- `next_not_low_open` 強攻比例：{not_low["strong_attack_rate_pct"]:.2f}%
- `next_low_open` 強攻比例：{low_open["strong_attack_rate_pct"]:.2f}%
- `next_not_low_open` 午盤後跌破開盤比例：{not_low["below_open_after_1130_rate_pct"]:.2f}%
- `next_low_open` 午盤後跌破開盤比例：{low_open["below_open_after_1130_rate_pct"]:.2f}%
- `next_not_low_open` 10 日淨報酬：{not_low["mean_10d_net_pct"]:.3f}%
- `next_low_open` 10 日淨報酬：{low_open["mean_10d_net_pct"]:.3f}%

## 限制

- 本輪是近期市場的 regime 分層抽樣，不是全期間全樣本回測。
- 若分K資料缺失，該筆樣本會自動排除；因此分K結論應搭配全樣本日K結果一起看。
"""
    REPORT_PATH.write_text(md, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-per-group", type=int, default=100)
    parser.add_argument("--sleep-seconds", type=float, default=0.2)
    args = parser.parse_args()

    token = os.environ.get("FINMIND_TOKEN")
    if not token:
        raise SystemExit("FINMIND_TOKEN is required")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sample = build_sample(args.target_per_group)
    sample.to_csv(OUT_DIR / "breakout_intraday_quality_sample.csv", index=False)

    detail = enrich_intraday(sample, token, args.sleep_seconds)
    detail.to_csv(OUT_DIR / "breakout_intraday_quality_detail.csv", index=False)

    summary = summarize_group(detail)
    summary.to_csv(OUT_DIR / "breakout_intraday_quality_summary.csv", index=False)

    regime_summary = summarize_group_regime(detail)
    regime_summary.to_csv(OUT_DIR / "breakout_intraday_quality_regime_summary.csv", index=False)

    sample_mix = summarize_sample_mix(sample)
    sample_mix.to_csv(OUT_DIR / "breakout_intraday_quality_sample_mix.csv", index=False)

    write_report(summary, regime_summary, sample_mix, detail, args.target_per_group)
    print(REPORT_PATH)
    print(OUT_DIR / "breakout_intraday_quality_summary.csv")
    print(OUT_DIR / "breakout_intraday_quality_regime_summary.csv")
    print(OUT_DIR / "breakout_intraday_quality_detail.csv")


if __name__ == "__main__":
    main()
