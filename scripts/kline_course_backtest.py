from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


DB_PATH = Path("/Users/howard/.four_seasons/data.sqlite")
OUT_DIR = Path("data/analysis/kline_course_backtest")
REPORT_PATH = Path("docs/K線力量判斷入門/backtests/kline_course_backtest.md")


def load_bars() -> pd.DataFrame:
    query = """
        select
            ticker,
            trade_date,
            open,
            high,
            low,
            close,
            volume,
            ma20,
            ma60,
            ma240,
            vol_ma20,
            vol_ratio_20,
            is_attention_stock,
            is_disposition_stock,
            is_usable
        from standard_daily_bar
        where is_usable = 1
          and open is not null
          and high is not null
          and low is not null
          and close is not null
          and volume is not null
          and open > 0
          and high > 0
          and low > 0
          and close > 0
        order by ticker, trade_date
    """
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(query, conn, parse_dates=["trade_date"])
    return df


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    g = df.groupby("ticker", group_keys=False)

    df["prev_close"] = g["close"].shift(1)
    df["prev_open"] = g["open"].shift(1)
    df["prev_high"] = g["high"].shift(1)
    df["prev_low"] = g["low"].shift(1)

    df["prior_high_20"] = g["high"].shift(1).rolling(20, min_periods=20).max().reset_index(level=0, drop=True)
    df["prior_high_60"] = g["high"].shift(1).rolling(60, min_periods=60).max().reset_index(level=0, drop=True)
    df["prior_low_20"] = g["low"].shift(1).rolling(20, min_periods=20).min().reset_index(level=0, drop=True)
    df["prior_low_60"] = g["low"].shift(1).rolling(60, min_periods=60).min().reset_index(level=0, drop=True)
    df["avg_volume_20"] = g["volume"].shift(1).rolling(20, min_periods=20).mean().reset_index(level=0, drop=True)

    df["range_pct"] = (df["high"] - df["low"]) / df["open"].replace(0, np.nan)
    df["body_pct"] = (df["close"] - df["open"]).abs() / df["open"].replace(0, np.nan)
    df["body_abs"] = (df["close"] - df["open"]).abs()
    df["close_pos"] = (df["close"] - df["low"]) / (df["high"] - df["low"]).replace(0, np.nan)
    df["upper_shadow"] = df["high"] - df[["open", "close"]].max(axis=1)
    df["lower_shadow"] = df[["open", "close"]].min(axis=1) - df["low"]
    df["upper_shadow_ratio"] = df["upper_shadow"] / df["body_abs"].replace(0, np.nan)
    df["lower_shadow_ratio"] = df["lower_shadow"] / df["body_abs"].replace(0, np.nan)
    df["volume_ratio"] = df["volume"] / df["avg_volume_20"].replace(0, np.nan)
    df["ret_5d_past"] = df["close"] / g["close"].shift(5) - 1

    for h in (5, 10, 20):
        df[f"entry_open_1d"] = g["open"].shift(-1)
        df[f"future_close_{h}d"] = g["close"].shift(-h)
        df[f"ret_{h}d"] = df[f"future_close_{h}d"] / df["entry_open_1d"] - 1
        df[f"ret_close_basis_{h}d"] = df[f"future_close_{h}d"] / df["close"] - 1

    df["next_open_gap_vs_close"] = g["open"].shift(-1) / df["close"] - 1
    df["next_close"] = g["close"].shift(-1)
    return df


def add_signals(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    red = df["close"] > df["open"]
    black = df["close"] < df["open"]
    above_ma60 = df["ma60"].notna() & (df["close"] > df["ma60"])

    df["breakout_attack"] = (
        (df["close"] > df["prior_high_60"])
        & red
        & (df["close_pos"] >= 0.7)
        & (df["volume_ratio"] >= 1.2)
        & above_ma60
    )
    df["breakout_next_not_low_open"] = df["breakout_attack"] & (df["next_open_gap_vs_close"] >= 0)
    df["breakout_next_low_open"] = df["breakout_attack"] & (df["next_open_gap_vs_close"] < 0)

    df["upper_shadow_new_high"] = (
        (df["high"] > df["prior_high_60"])
        & (df["upper_shadow_ratio"] >= 1.0)
        & (df["close"] > df["prev_close"])
        & above_ma60
    )
    df["new_high_no_upper_shadow"] = (
        (df["high"] > df["prior_high_60"])
        & (df["upper_shadow_ratio"].fillna(0) < 0.5)
        & (df["close"] > df["prev_close"])
        & above_ma60
    )

    df["doji"] = (df["body_pct"] <= 0.006) & (df["range_pct"] >= 0.015)
    df["doji_at_pressure"] = df["doji"] & (df["high"] >= df["prior_high_60"] * 0.98)
    prior_doji = df.groupby("ticker")["doji"].shift(1).eq(True)
    df["doji_break_up"] = prior_doji & (df["close"] > df["prev_high"])
    df["doji_break_down"] = prior_doji & (df["close"] < df["prev_low"])

    key_level = df["prior_low_60"]
    df["panic_drop"] = df["ret_5d_past"] <= -0.07
    df["false_breakdown_reclaim"] = (
        df["panic_drop"]
        & (df["low"] < key_level)
        & (df["close"] >= key_level)
    )
    df["real_breakdown_after_range"] = (
        ~df["panic_drop"].fillna(False)
        & black
        & (df["close"] < key_level)
        & (df["range_pct"] >= 0.025)
    )

    return df


def summarize_signal(df: pd.DataFrame, signal: str) -> dict[str, float | int | str]:
    rows = df[df[signal]].copy()
    rows = rows.replace([np.inf, -np.inf], np.nan)
    valid = rows.dropna(subset=["entry_open_1d", "ret_5d", "ret_10d", "ret_20d"])
    valid = valid[valid["entry_open_1d"] > 0]
    out: dict[str, float | int | str] = {"signal": signal, "n": int(len(valid))}
    if valid.empty:
        return out
    for h in (5, 10, 20):
        r = valid[f"ret_{h}d"]
        out[f"mean_{h}d_pct"] = round(float(r.mean() * 100), 3)
        out[f"median_{h}d_pct"] = round(float(r.median() * 100), 3)
        out[f"win_rate_{h}d_pct"] = round(float((r > 0).mean() * 100), 2)
        cr = valid[f"ret_close_basis_{h}d"]
        out[f"mean_close_basis_{h}d_pct"] = round(float(cr.mean() * 100), 3)
        out[f"win_rate_close_basis_{h}d_pct"] = round(float((cr > 0).mean() * 100), 2)
    return out


def write_report(summary: pd.DataFrame, df: pd.DataFrame) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    sample_start = df["trade_date"].min().date()
    sample_end = df["trade_date"].max().date()
    ticker_count = df["ticker"].nunique()
    row_count = len(df)

    def table(rows: pd.DataFrame) -> str:
        cols = [
            "signal",
            "n",
            "mean_5d_pct",
            "win_rate_5d_pct",
            "mean_10d_pct",
            "win_rate_10d_pct",
            "mean_20d_pct",
            "win_rate_20d_pct",
            "mean_close_basis_10d_pct",
            "win_rate_close_basis_10d_pct",
        ]
        rows = rows[cols].copy()
        header = "| " + " | ".join(cols) + " |"
        divider = "| " + " | ".join(["---"] * len(cols)) + " |"
        lines = [header, divider]
        for row in rows.itertuples(index=False):
            values = ["" if pd.isna(v) else str(v) for v in row]
            lines.append("| " + " | ".join(values) + " |")
        return "\n".join(lines)

    by_signal = summary.set_index("signal")

    def val(signal: str, col: str) -> float:
        return float(by_signal.loc[signal, col])

    verdict = f"""## 課程情境符合度

| 課程情境 | 本次量化代理 | 判讀 |
| --- | --- | --- |
| 突破後隔日不開低代表攻擊品質較好 | `breakout_next_not_low_open` vs `breakout_next_low_open` 的 close-basis 10 日報酬 | 部分符合。收盤基準 10 日平均報酬為 {val("breakout_next_not_low_open", "mean_close_basis_10d_pct"):.3f}% vs {val("breakout_next_low_open", "mean_close_basis_10d_pct"):.3f}%，表示走勢延續較強；但若用隔日開盤進場，開低組因買價較低，交易報酬反而較高。 |
| 創高上影線不必然是賣壓 | `upper_shadow_new_high` vs `new_high_no_upper_shadow` | 大致符合。創高上影線 10 日 close-basis 平均仍為 {val("upper_shadow_new_high", "mean_close_basis_10d_pct"):.3f}%，不是明顯負向；但弱於無明顯上影線的新高組 {val("new_high_no_upper_shadow", "mean_close_basis_10d_pct"):.3f}%。 |
| 十字線需要隔日確認，不能單看十字線 | `doji_break_up` vs `doji_break_down` | 目前只部分支持。兩組 10 日 close-basis 報酬都偏正，方向差異不明顯；需要加入「前段已拉抬」「是否遇壓」「長/短十字線」等圖例標註。 |
| 急跌後跌破前低又收回是假性跌破，後續不宜直接看空 | `false_breakdown_reclaim` | 符合度最高。10 日 close-basis 平均 {val("false_breakdown_reclaim", "mean_close_basis_10d_pct"):.3f}%，勝率 {val("false_breakdown_reclaim", "win_rate_close_basis_10d_pct"):.2f}%；20 日 close-basis 平均 {val("false_breakdown_reclaim", "mean_close_basis_20d_pct"):.3f}%。 |
| 整理後長黑跌破偏真正轉弱 | `real_breakdown_after_range` | 本次簡化代理不支持。10 日 close-basis 平均仍為 {val("real_breakdown_after_range", "mean_close_basis_10d_pct"):.3f}%；代表單用 60 日前低與長黑不足以捕捉課程的「頸線/整理後跌破」。 |
"""

    md = f"""# K線力量課程情境回測

資料庫：`/Users/howard/.four_seasons/data.sqlite`

樣本：{sample_start} 至 {sample_end}，{ticker_count} 檔，{row_count:,} 筆可用日K。

回測假設：訊號在當日收盤後形成，隔日開盤進場，以第 5/10/20 個交易日收盤計算報酬。此版只使用日K OHLCV 與均線欄位，尚未納入人工標註的壓力區、賣壓中空圖形區段與 intraday 江波。

## 結果摘要

{table(summary)}

{verdict}

## 初步判讀

- `breakout_next_not_low_open` 對應課程中「突破後隔日不開低」的攻擊品質條件，可與 `breakout_next_low_open` 比較。
- `upper_shadow_new_high` 用來檢驗「創高上影線不必然是壓力」；若結果不顯著轉弱，較符合課程敘述。
- `doji_break_up` 與 `doji_break_down` 檢驗十字線隔日方向確認，而不是看到十字線就預測。
- `false_breakdown_reclaim` 檢驗急跌後跌破前低又收回的假性跌破情境。
- `real_breakdown_after_range` 檢驗整理後長黑跌破，與假性跌破相對。

## 限制

- 樣本只有 2025-01 至 2026-05，市場 regime 單一，不能直接視為長期結論。
- 賣壓中空、層層套牢、壓力區是否化解，需要 volume profile 或人工圖形標註；本次只保留為後續驗證項目。
- 注意股與處置股目前未排除；如果要做可交易策略，下一版應加入流動性、注意/處置、漲跌停買不到等限制。
"""
    REPORT_PATH.write_text(md, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = add_signals(add_features(load_bars()))
    signals = [
        "breakout_attack",
        "breakout_next_not_low_open",
        "breakout_next_low_open",
        "upper_shadow_new_high",
        "new_high_no_upper_shadow",
        "doji_at_pressure",
        "doji_break_up",
        "doji_break_down",
        "false_breakdown_reclaim",
        "real_breakdown_after_range",
    ]
    summary = pd.DataFrame([summarize_signal(df, s) for s in signals])
    summary.to_csv(OUT_DIR / "signal_summary.csv", index=False)
    examples = []
    for s in signals:
        cols = ["ticker", "trade_date", "open", "high", "low", "close", "volume", "ret_5d", "ret_10d", "ret_20d"]
        rows = df[df[s]].dropna(subset=["ret_10d"]).head(100).copy()
        rows.insert(0, "signal", s)
        examples.append(rows[["signal", *cols]])
    pd.concat(examples, ignore_index=True).to_csv(OUT_DIR / "signal_examples.csv", index=False)
    write_report(summary, df)
    print(REPORT_PATH)
    print(OUT_DIR / "signal_summary.csv")


if __name__ == "__main__":
    main()
