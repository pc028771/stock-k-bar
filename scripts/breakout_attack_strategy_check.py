from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from false_breakdown_strategy_check import add_market_regime
from kline_course_backtest import add_features, add_signals, load_bars


OUT_DIR = Path("data/analysis/kline_course_backtest")
REPORT_PATH = Path("docs/K線力量判斷入門/backtests/breakout_attack_strategy_check.md")

ROUND_TRIP_COST = 0.00585
MIN_AVG_VOLUME_20 = 500_000
MIN_CLOSE = 10


def add_trade_fields(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    g = df.groupby("ticker", group_keys=False)
    df["entry_open_2d"] = g["open"].shift(-2)
    df["breakout_level"] = df["prior_high_60"]
    df["stop_price_breakout"] = np.minimum(df["low"], df["breakout_level"]) * 0.995

    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["prev_close"]).abs(),
            (df["low"] - df["prev_close"]).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["atr14"] = tr.groupby(df["ticker"]).transform(lambda s: s.rolling(14, min_periods=14).mean())
    df["stop_price_atr14"] = np.minimum(df["low"], df["breakout_level"]) - df["atr14"]

    for h in (5, 10, 20):
        lows = [g["low"].shift(-i) for i in range(1, h + 1)]
        future_low = pd.concat(lows, axis=1).min(axis=1)
        df[f"future_low_{h}d"] = future_low
        df[f"stop_hit_breakout_{h}d"] = future_low <= df["stop_price_breakout"]
        df[f"stop_hit_atr14_{h}d"] = future_low <= df["stop_price_atr14"]
        df[f"ret_{h}d_stop_breakout"] = np.where(
            df[f"stop_hit_breakout_{h}d"],
            df["stop_price_breakout"] / df["entry_open_1d"] - 1,
            df[f"ret_{h}d"],
        )
        df[f"ret_{h}d_stop_atr14"] = np.where(
            df[f"stop_hit_atr14_{h}d"],
            df["stop_price_atr14"] / df["entry_open_1d"] - 1,
            df[f"ret_{h}d"],
        )
        df[f"ret_{h}d_net"] = df[f"ret_{h}d"] - ROUND_TRIP_COST
        df[f"ret_{h}d_stop_breakout_net"] = df[f"ret_{h}d_stop_breakout"] - ROUND_TRIP_COST
        df[f"ret_{h}d_stop_atr14_net"] = df[f"ret_{h}d_stop_atr14"] - ROUND_TRIP_COST
    return df


def variant_masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    base = df["breakout_attack"].fillna(False)
    attention = pd.to_numeric(df["is_attention_stock"], errors="coerce").fillna(0).astype(int)
    disposition = pd.to_numeric(df["is_disposition_stock"], errors="coerce").fillna(0).astype(int)
    tradable = (
        base
        & (attention == 0)
        & (disposition == 0)
        & (df["avg_volume_20"] >= MIN_AVG_VOLUME_20)
        & (df["close"] >= MIN_CLOSE)
    )
    next_not_low = tradable & df["breakout_next_not_low_open"].fillna(False)
    next_low = tradable & df["breakout_next_low_open"].fillna(False)
    high_close = tradable & (df["close_pos"] >= 0.85)
    volume_strong = tradable & (df["volume_ratio"] >= 1.5)
    non_bull = tradable & (df["market_regime"] != "bull")
    return {
        "breakout_attack_base": base,
        "breakout_attack_tradable": tradable,
        "breakout_next_not_low_open": next_not_low,
        "breakout_next_low_open": next_low,
        "breakout_high_close": high_close,
        "breakout_volume_strong": volume_strong,
        "breakout_non_bull": non_bull,
    }


def summarize_variant(df: pd.DataFrame, name: str, mask: pd.Series) -> dict[str, float | int | str]:
    rows = df[mask].replace([np.inf, -np.inf], np.nan)
    rows = rows.dropna(subset=["entry_open_1d", "ret_5d_net", "ret_10d_net", "ret_20d_net"])
    rows = rows[rows["entry_open_1d"] > 0]
    out: dict[str, float | int | str] = {"variant": name, "n": int(len(rows))}
    if rows.empty:
        return out
    out["avg_volume_20_median"] = int(rows["avg_volume_20"].median())
    for h in (5, 10, 20):
        net = rows[f"ret_{h}d_net"]
        breakout_stop = rows[f"ret_{h}d_stop_breakout_net"]
        atr_stop = rows[f"ret_{h}d_stop_atr14_net"]
        out[f"mean_{h}d_net_pct"] = round(float(net.mean() * 100), 3)
        out[f"win_rate_{h}d_net_pct"] = round(float((net > 0).mean() * 100), 2)
        out[f"mean_{h}d_stop_breakout_net_pct"] = round(float(breakout_stop.mean() * 100), 3)
        out[f"mean_{h}d_stop_atr14_net_pct"] = round(float(atr_stop.mean() * 100), 3)
        out[f"stop_hit_breakout_{h}d_pct"] = round(float(rows[f"stop_hit_breakout_{h}d"].mean() * 100), 2)
        out[f"stop_hit_atr14_{h}d_pct"] = round(float(rows[f"stop_hit_atr14_{h}d"].mean() * 100), 2)
    return out


def summarize_regime(df: pd.DataFrame, name: str, mask: pd.Series) -> pd.DataFrame:
    rows = df[mask].replace([np.inf, -np.inf], np.nan)
    rows = rows.dropna(subset=["entry_open_1d", "ret_10d_net", "ret_20d_net", "market_regime"])
    rows = rows[rows["entry_open_1d"] > 0]
    if rows.empty:
        return pd.DataFrame(columns=["variant", "market_regime", "n", "mean_10d_net_pct", "win_rate_10d_net_pct", "mean_20d_net_pct"])
    out = []
    for regime, g in rows.groupby("market_regime", dropna=False):
        out.append(
            {
                "variant": name,
                "market_regime": str(regime),
                "n": int(len(g)),
                "mean_10d_net_pct": round(float(g["ret_10d_net"].mean() * 100), 3),
                "win_rate_10d_net_pct": round(float((g["ret_10d_net"] > 0).mean() * 100), 2),
                "mean_20d_net_pct": round(float(g["ret_20d_net"].mean() * 100), 3),
            }
        )
    return pd.DataFrame(out)


def markdown_table(rows: pd.DataFrame, cols: list[str]) -> str:
    table_rows = rows[cols].copy()
    header = "| " + " | ".join(cols) + " |"
    divider = "| " + " | ".join(["---"] * len(cols)) + " |"
    lines = [header, divider]
    for row in table_rows.itertuples(index=False):
        values = ["" if pd.isna(v) else str(v) for v in row]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def write_report(summary: pd.DataFrame, regime_summary: pd.DataFrame, df: pd.DataFrame) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    sample_start = df["trade_date"].min().date()
    sample_end = df["trade_date"].max().date()
    overview_cols = [
        "variant",
        "n",
        "mean_10d_net_pct",
        "win_rate_10d_net_pct",
        "mean_10d_stop_breakout_net_pct",
        "mean_10d_stop_atr14_net_pct",
        "mean_20d_net_pct",
        "win_rate_20d_net_pct",
    ]
    regime_cols = ["variant", "market_regime", "n", "mean_10d_net_pct", "win_rate_10d_net_pct", "mean_20d_net_pct"]
    summary_idx = summary.set_index("variant")
    tradable = summary_idx.loc["breakout_attack_tradable"]
    not_low = summary_idx.loc["breakout_next_not_low_open"]
    low_open = summary_idx.loc["breakout_next_low_open"]
    md = f"""# 突破攻擊策略原型驗證

資料庫：`/Users/howard/.four_seasons/data.sqlite`

樣本：{sample_start} 至 {sample_end}

本次驗證 `breakout_attack` 在加入可交易限制與停損模型後，是否仍能保留趨勢追蹤邊際。

## 假設

- 訊號：收盤突破 60 日前高、收紅、收盤接近日高、量比至少 1.2、且收盤在 MA60 上方。
- 進場：訊號日收盤後成立，隔日開盤買進。
- 可交易限制：排除注意股、處置股；20 日均量至少 {MIN_AVG_VOLUME_20:,} 股；收盤價至少 {MIN_CLOSE} 元。
- 停損模型：`breakout_stop = min(訊號日低點, 突破價) * 0.995`，以及 `ATR14` 停損。

## 核心結果

{markdown_table(summary, overview_cols)}

## 市場環境分組

{markdown_table(regime_summary, regime_cols)}

## 判讀

- `breakout_attack_tradable` 的 10 日淨報酬為 {tradable["mean_10d_net_pct"]:.3f}%，20 日淨報酬為 {tradable["mean_20d_net_pct"]:.3f}%。
- `breakout_next_not_low_open` 與 `breakout_next_low_open` 分開後，可以直接檢查「隔日不開低」是否真能改善交易報酬，而不是只改善 close-basis 延續。
- 若 `ATR14` 停損 consistently 優於突破低點停損，代表突破策略同樣不適合用過緊停損。

## 重點比較

- `breakout_next_not_low_open` 10 日淨報酬：{not_low["mean_10d_net_pct"]:.3f}%
- `breakout_next_low_open` 10 日淨報酬：{low_open["mean_10d_net_pct"]:.3f}%
- `breakout_next_not_low_open` 20 日淨報酬：{not_low["mean_20d_net_pct"]:.3f}%
- `breakout_next_low_open` 20 日淨報酬：{low_open["mean_20d_net_pct"]:.3f}%
"""
    REPORT_PATH.write_text(md, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = add_market_regime(add_trade_fields(add_signals(add_features(load_bars()))))
    masks = variant_masks(df)
    summary = pd.DataFrame([summarize_variant(df, name, mask) for name, mask in masks.items()])
    summary.to_csv(OUT_DIR / "breakout_attack_strategy_summary.csv", index=False)
    regime_rows = [summarize_regime(df, name, mask) for name, mask in masks.items()]
    regime_summary = pd.concat(regime_rows, ignore_index=True).sort_values(["variant", "market_regime"])
    regime_summary.to_csv(OUT_DIR / "breakout_attack_regime_summary.csv", index=False)

    examples = []
    for name, mask in masks.items():
        rows = df[mask].dropna(subset=["ret_10d_net"]).head(100).copy()
        rows.insert(0, "variant", name)
        examples.append(
            rows[
                [
                    "variant",
                    "ticker",
                    "trade_date",
                    "market_regime",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "breakout_level",
                    "stop_price_breakout",
                    "stop_price_atr14",
                    "ret_10d_net",
                    "ret_20d_net",
                ]
            ]
        )
    pd.concat(examples, ignore_index=True).to_csv(OUT_DIR / "breakout_attack_strategy_examples.csv", index=False)
    write_report(summary, regime_summary, df)
    print(REPORT_PATH)
    print(OUT_DIR / "breakout_attack_strategy_summary.csv")
    print(OUT_DIR / "breakout_attack_regime_summary.csv")


if __name__ == "__main__":
    main()
