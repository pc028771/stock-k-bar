from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

import sys
sys.path.insert(0, str(Path(__file__).parent))
from kline_course_backtest import add_features, add_signals, load_bars
from exit_simulation import simulate_exits

OUT_DIR = Path("data/analysis/kline_course_backtest")
REPORT_PATH = Path("docs/K線力量判斷入門/backtests/attack_quality_analysis.md")

ATTACK_QUALITY_FEATURES = [
    "higher_low_count",
    "gap_open",
    "pre_breakout_trend_days",
    "body_pct",
    "close_pos",
    "volume_ratio",
]


def compute_correlations(df: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    """計算攻擊品質特徵與課程出場報酬的 Spearman 相關係數。

    trades: simulate_exits() 回傳的交易結果，含 signal_date, ticker, trade_return_net。
    """
    # 合併訊號特徵與實際出場報酬
    sig = df[df["breakout_attack"]].copy()
    sig["signal_date"] = pd.to_datetime(sig["trade_date"])
    trades_indexed = trades.copy()
    trades_indexed["signal_date"] = pd.to_datetime(trades_indexed["signal_date"])
    sample = sig.merge(
        trades_indexed[["ticker", "signal_date", "trade_return_net"]],
        on=["ticker", "signal_date"],
        how="inner",
    ).dropna(subset=["trade_return_net"])

    rows = []
    for feat in ATTACK_QUALITY_FEATURES:
        if feat not in sample.columns:
            rows.append({"feature": feat, "n": 0, "spearman_r": float("nan"), "p_value": float("nan")})
            continue
        valid = sample[[feat, "trade_return_net"]].dropna()
        if len(valid) < 30:
            rows.append({"feature": feat, "n": int(len(valid)), "spearman_r": float("nan"), "p_value": float("nan")})
            continue
        r, p = spearmanr(valid[feat], valid["trade_return_net"])
        rows.append({
            "feature": feat,
            "n": int(len(valid)),
            "spearman_r": round(float(r), 4),
            "p_value": round(float(p), 4),
        })
    return pd.DataFrame(rows).sort_values("spearman_r", ascending=False, na_position="last")


def write_report(corr: pd.DataFrame, df: pd.DataFrame) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    n_breakouts = int(df["breakout_attack"].sum())
    sample_start = str(df["trade_date"].min().date())
    sample_end = str(df["trade_date"].max().date())

    def _md_table(rows: pd.DataFrame) -> str:
        cols = list(rows.columns)
        lines = ["| " + " | ".join(cols) + " |",
                 "| " + " | ".join(["---"] * len(cols)) + " |"]
        for row in rows.itertuples(index=False):
            lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |")
        return "\n".join(lines)

    md = f"""# 攻擊品質特徵相關係數分析

樣本：{sample_start} 至 {sample_end}，突破樣本 {n_breakouts:,} 筆。

目標變數：`trade_return_net`（課程出場條件模擬後的淨報酬，含手續費）。

所有特徵為突破當下可知資料，不含未來資訊。

## Spearman 相關係數

{_md_table(corr)}

## 建議加權方向

正相關特徵加分、負相關扣分，係數絕對值 < 0.02 不納入。
"""
    REPORT_PATH.write_text(md, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = add_signals(add_features(load_bars()))
    trades = simulate_exits(df)
    corr = compute_correlations(df, trades)
    corr.to_csv(OUT_DIR / "attack_quality_correlation.csv", index=False)
    write_report(corr, df)
    print(REPORT_PATH)
    print(corr.to_string(index=False))


if __name__ == "__main__":
    main()
