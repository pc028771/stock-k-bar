from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from breakout_attack_strategy_check import MIN_AVG_VOLUME_20, MIN_CLOSE, ROUND_TRIP_COST, add_trade_fields
from false_breakdown_strategy_check import add_market_regime
from kline_course_backtest import add_features, add_signals, load_bars


OUT_DIR = Path("data/analysis/kline_course_backtest")
REPORT_PATH = Path("docs/K線力量判斷入門/backtests/breakout_next_open_quality_check.md")


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


def add_gap_bucket(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    gap = df["next_open_gap_vs_close"]
    df["gap_bucket"] = np.select(
        [
            gap >= 0.01,
            (gap >= 0.0) & (gap < 0.01),
            (gap >= -0.01) & (gap < 0.0),
            (gap >= -0.03) & (gap < -0.01),
            gap < -0.03,
        ],
        [">=+1%", "0~+1%", "0~-1%", "-1%~-3%", "<-3%"],
        default="unknown",
    )
    return df


def summarize_group(rows: pd.DataFrame, label: str) -> dict[str, float | int | str]:
    valid = rows.replace([np.inf, -np.inf], np.nan).dropna(
        subset=[
            "next_open_gap_vs_close",
            "ret_10d_net",
            "ret_20d_net",
            "ret_10d_stop_atr14_net",
            "ret_20d_stop_atr14_net",
            "ret_close_basis_10d",
            "ret_close_basis_20d",
        ]
    )
    out: dict[str, float | int | str] = {"group": label, "n": int(len(valid))}
    if valid.empty:
        return out
    out["mean_gap_pct"] = round(float(valid["next_open_gap_vs_close"].mean() * 100), 3)
    out["mean_close_basis_10d_pct"] = round(float(valid["ret_close_basis_10d"].mean() * 100), 3)
    out["win_close_basis_10d_pct"] = round(float((valid["ret_close_basis_10d"] > 0).mean() * 100), 2)
    out["mean_10d_net_pct"] = round(float(valid["ret_10d_net"].mean() * 100), 3)
    out["win_10d_net_pct"] = round(float((valid["ret_10d_net"] > 0).mean() * 100), 2)
    out["mean_10d_atr_stop_net_pct"] = round(float(valid["ret_10d_stop_atr14_net"].mean() * 100), 3)
    out["mean_20d_net_pct"] = round(float(valid["ret_20d_net"].mean() * 100), 3)
    out["win_20d_net_pct"] = round(float((valid["ret_20d_net"] > 0).mean() * 100), 2)
    out["mean_20d_atr_stop_net_pct"] = round(float(valid["ret_20d_stop_atr14_net"].mean() * 100), 3)
    return out


def summarize_regime(rows: pd.DataFrame) -> pd.DataFrame:
    valid = rows.replace([np.inf, -np.inf], np.nan).dropna(subset=["market_regime", "ret_10d_net", "ret_close_basis_10d"])
    out = []
    for (group, regime), g in valid.groupby(["group", "market_regime"], dropna=False):
        out.append(
            {
                "group": group,
                "market_regime": regime,
                "n": int(len(g)),
                "mean_close_basis_10d_pct": round(float(g["ret_close_basis_10d"].mean() * 100), 3),
                "mean_10d_net_pct": round(float(g["ret_10d_net"].mean() * 100), 3),
                "win_10d_net_pct": round(float((g["ret_10d_net"] > 0).mean() * 100), 2),
            }
        )
    return pd.DataFrame(out).sort_values(["group", "market_regime"])


def summarize_gap_buckets(rows: pd.DataFrame) -> pd.DataFrame:
    valid = rows.replace([np.inf, -np.inf], np.nan).dropna(subset=["gap_bucket", "ret_10d_net", "ret_close_basis_10d"])
    out = []
    for bucket, g in valid.groupby("gap_bucket", dropna=False):
        out.append(
            {
                "gap_bucket": bucket,
                "n": int(len(g)),
                "mean_gap_pct": round(float(g["next_open_gap_vs_close"].mean() * 100), 3),
                "mean_close_basis_10d_pct": round(float(g["ret_close_basis_10d"].mean() * 100), 3),
                "mean_10d_net_pct": round(float(g["ret_10d_net"].mean() * 100), 3),
                "win_10d_net_pct": round(float((g["ret_10d_net"] > 0).mean() * 100), 2),
                "mean_20d_net_pct": round(float(g["ret_20d_net"].mean() * 100), 3),
            }
        )
    return pd.DataFrame(out)


def markdown_table(rows: pd.DataFrame, cols: list[str]) -> str:
    rows = rows[cols].copy()
    header = "| " + " | ".join(cols) + " |"
    divider = "| " + " | ".join(["---"] * len(cols)) + " |"
    lines = [header, divider]
    for row in rows.itertuples(index=False):
        values = ["" if pd.isna(v) else str(v) for v in row]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def write_report(summary: pd.DataFrame, regime_summary: pd.DataFrame, gap_summary: pd.DataFrame, sample_start: str, sample_end: str) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    summary_idx = summary.set_index("group")
    not_low = summary_idx.loc["next_not_low_open"]
    low_open = summary_idx.loc["next_low_open"]
    md = f"""# 突破隔日開盤品質驗證

資料庫：`/Users/howard/.four_seasons/data.sqlite`

樣本：{sample_start} 至 {sample_end}

目的：檢查 `breakout_next_not_low_open` 應該被當成什麼。

- 如果它主要提升 `close_basis`，但沒有提升 `next_open` 交易報酬，它比較像持股品質或觀察欄位。
- 如果它連 `next_open` 報酬也更好，才有資格當突破策略濾網。

## 主比較

{markdown_table(summary, ["group", "n", "mean_gap_pct", "mean_close_basis_10d_pct", "win_close_basis_10d_pct", "mean_10d_net_pct", "win_10d_net_pct", "mean_10d_atr_stop_net_pct", "mean_20d_net_pct"])}

## Regime 分組

{markdown_table(regime_summary, ["group", "market_regime", "n", "mean_close_basis_10d_pct", "mean_10d_net_pct", "win_10d_net_pct"])}

## Gap Bucket 分組

{markdown_table(gap_summary, ["gap_bucket", "n", "mean_gap_pct", "mean_close_basis_10d_pct", "mean_10d_net_pct", "win_10d_net_pct", "mean_20d_net_pct"])}

## 判讀

- `next_not_low_open` 的 close-basis 10 日平均為 {not_low["mean_close_basis_10d_pct"]:.3f}%，高於 `next_low_open` 的 {low_open["mean_close_basis_10d_pct"]:.3f}%。
- 但 `next_open` 實際交易 10 日平均報酬，`next_not_low_open` 只有 {not_low["mean_10d_net_pct"]:.3f}%，低於 `next_low_open` 的 {low_open["mean_10d_net_pct"]:.3f}%。
- 這代表「隔日不開低」目前更像走勢品質標籤，而不是更好的進場價格條件。
- 若後續要保留它，應該與分K攻擊品質一起驗證，而不是單獨當作突破策略買點濾網。
"""
    REPORT_PATH.write_text(md, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = add_gap_bucket(add_market_regime(add_trade_fields(add_signals(add_features(load_bars())))))
    mask = tradable_mask(df)
    all_rows = df[mask].copy()
    all_rows["group"] = "all_breakout_tradable"
    not_low_rows = df[mask & df["breakout_next_not_low_open"].fillna(False)].copy()
    not_low_rows["group"] = "next_not_low_open"
    low_rows = df[mask & df["breakout_next_low_open"].fillna(False)].copy()
    low_rows["group"] = "next_low_open"

    summary = pd.DataFrame(
        [
            summarize_group(all_rows, "all_breakout_tradable"),
            summarize_group(not_low_rows, "next_not_low_open"),
            summarize_group(low_rows, "next_low_open"),
        ]
    )
    summary.to_csv(OUT_DIR / "breakout_next_open_quality_summary.csv", index=False)

    regime_summary = summarize_regime(pd.concat([not_low_rows, low_rows], ignore_index=True))
    regime_summary.to_csv(OUT_DIR / "breakout_next_open_quality_regime_summary.csv", index=False)

    gap_summary = summarize_gap_buckets(all_rows)
    gap_summary.to_csv(OUT_DIR / "breakout_next_open_gap_bucket_summary.csv", index=False)

    sample_start = str(df["trade_date"].min().date())
    sample_end = str(df["trade_date"].max().date())
    write_report(summary, regime_summary, gap_summary, sample_start, sample_end)
    print(REPORT_PATH)
    print(OUT_DIR / "breakout_next_open_quality_summary.csv")
    print(OUT_DIR / "breakout_next_open_quality_regime_summary.csv")
    print(OUT_DIR / "breakout_next_open_gap_bucket_summary.csv")


if __name__ == "__main__":
    main()
