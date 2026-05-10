from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import pandas as pd
import requests
from pandas.errors import EmptyDataError

from kline_course_backtest import add_features, add_signals, load_bars


OUT_DIR = Path("data/analysis/kline_course_backtest")
REPORT_PATH = Path("docs/K線力量判斷入門/backtests/finmind_intraday_check.md")
API_URL = "https://api.finmindtrade.com/api/v4/data"
DEFAULT_SHARED_CACHE_DIR = Path.home() / ".four_seasons" / "finmind_kbar_cache"


def get_cache_dir() -> Path:
    cache_dir_raw = os.environ.get("FINMIND_KBAR_CACHE_DIR")
    cache_dir = Path(cache_dir_raw).expanduser() if cache_dir_raw else DEFAULT_SHARED_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def fetch_kbar(ticker: str, trade_date: str, token: str, sleep_seconds: float) -> pd.DataFrame:
    cache_dir = get_cache_dir()
    cache_path = cache_dir / f"{ticker}_{trade_date}.csv"
    if cache_path.exists():
        try:
            cached = pd.read_csv(cache_path)
            if not cached.empty:
                return cached
        except EmptyDataError:
            pass
        cache_path.unlink(missing_ok=True)

    params = {
        "dataset": "TaiwanStockKBar",
        "data_id": ticker,
        "start_date": trade_date,
        "end_date": trade_date,
    }
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(API_URL, params=params, headers=headers, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != 200:
        raise RuntimeError(f"FinMind error for {ticker} {trade_date}: {payload.get('msg')}")
    data = payload.get("data") or []
    df = pd.DataFrame(data)
    df.to_csv(cache_path, index=False)
    time.sleep(sleep_seconds)
    return df


def intraday_features(kbar: pd.DataFrame) -> dict[str, float | int | str | bool]:
    if kbar.empty:
        return {"intraday_rows": 0}

    df = kbar.copy()
    df["dt"] = pd.to_datetime(df["date"] + " " + df["minute"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("dt")
    if df.empty:
        return {"intraday_rows": 0}

    day_open = float(df.iloc[0]["open"])
    day_close = float(df.iloc[-1]["close"])
    day_high = float(df["high"].max())
    day_low = float(df["low"].min())
    high_idx = df["high"].idxmax()
    low_idx = df["low"].idxmin()
    high_time = df.loc[high_idx, "dt"]
    low_time = df.loc[low_idx, "dt"]
    rng = day_high - day_low
    close_pos = (day_close - day_low) / rng if rng else 0.5

    after_1130 = df[df["dt"].dt.time >= pd.Timestamp("11:30").time()]
    low_after_high = df[df["dt"] > high_time]["low"].min()
    if pd.isna(low_after_high):
        low_after_high = day_low

    first_30 = df[df["dt"].dt.time <= pd.Timestamp("09:30").time()]
    first_60 = df[df["dt"].dt.time <= pd.Timestamp("10:00").time()]

    return {
        "intraday_rows": int(len(df)),
        "intraday_return_pct": round((day_close / day_open - 1) * 100, 3),
        "intraday_range_pct": round((day_high / day_open - 1) * 100, 3),
        "intraday_drawdown_pct": round((day_low / day_open - 1) * 100, 3),
        "intraday_close_pos": round(close_pos, 3),
        "high_time": high_time.strftime("%H:%M"),
        "low_time": low_time.strftime("%H:%M"),
        "first_30_high_pct": round((first_30["high"].max() / day_open - 1) * 100, 3) if not first_30.empty else None,
        "first_60_return_pct": round((first_60.iloc[-1]["close"] / day_open - 1) * 100, 3) if not first_60.empty else None,
        "below_open_after_1130": bool((after_1130["low"] < day_open).any()) if not after_1130.empty else False,
        "low_after_high_break_open": bool(low_after_high < day_open),
        "intraday_strong_attack": bool((day_close > day_open) and (close_pos >= 0.7) and (low_after_high >= day_open * 0.99)),
        "intraday_attack_failure": bool((day_high > day_open * 1.01) and ((day_close < day_open) or (close_pos <= 0.35) or (low_after_high < day_open))),
    }


def build_signal_sample(limit_per_signal: int, signals: list[str]) -> pd.DataFrame:
    df = add_signals(add_features(load_bars()))
    rows = []
    for signal in signals:
        sample = (
            df[df[signal]]
            .sort_values(["trade_date", "ticker"], ascending=[False, True])
            .head(limit_per_signal)
            .copy()
        )
        sample.insert(0, "signal", signal)
        rows.append(sample[["signal", "ticker", "trade_date", "open", "high", "low", "close", "volume"]])
    return pd.concat(rows, ignore_index=True)


def write_report(result: pd.DataFrame, limit_per_signal: int) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result_path = OUT_DIR / "finmind_intraday_signal_check.csv"
    result.to_csv(result_path, index=False)

    grouped = (
        result.groupby("signal")
        .agg(
            n=("ticker", "count"),
            strong_attack_rate=("intraday_strong_attack", "mean"),
            failure_rate=("intraday_attack_failure", "mean"),
            below_open_after_1130_rate=("below_open_after_1130", "mean"),
            mean_intraday_return_pct=("intraday_return_pct", "mean"),
            mean_close_pos=("intraday_close_pos", "mean"),
        )
        .reset_index()
    )
    for col in grouped.columns:
        if col.endswith("_rate"):
            grouped[col] = (grouped[col] * 100).round(2)
        elif col.startswith("mean_"):
            grouped[col] = grouped[col].round(3)

    summary_path = OUT_DIR / "finmind_intraday_signal_summary.csv"
    grouped.to_csv(summary_path, index=False)

    cols = list(grouped.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for row in grouped.itertuples(index=False):
        lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |")

    md = f"""# FinMind 分K課程情境抽樣驗證

資料集：FinMind `TaiwanStockKBar`。官方文件說明台股分 K 資料表單次請求只提供一天資料，因此本報告採抽樣驗證。

每個日K訊號抽樣上限：{limit_per_signal}

輸出：

- `data/analysis/kline_course_backtest/finmind_intraday_signal_summary.csv`
- `data/analysis/kline_course_backtest/finmind_intraday_signal_check.csv`

## 分K摘要

{chr(10).join(lines)}

## 課程情境補充判讀

- 突破組：`breakout_next_not_low_open` 與 `breakout_next_low_open` 在訊號當日分K都呈現高比例強攻，這代表「突破當日有攻擊」與日K條件一致；但它無法單獨解釋隔日開高/開低差異，隔日行為仍要用日K或隔日分K延伸驗證。
- 創高上影線：`upper_shadow_new_high` 的 `failure_rate` 明顯較高，支持課程說法中的關鍵點：上影線不是必然看空，但它代表盤中攻擊沒有完整延續，必須再看壓力區與隔日確認。
- 假性跌破收回：`false_breakdown_reclaim` 當日分K多數盤中偏弱，這和日K回測的後續轉強並不衝突；它更像是急跌後賣壓耗盡或收回關鍵價，而不是當天立即展開攻擊。
- 午盤後跌破開盤：`below_open_after_1130_rate` 可作為攻擊品質濾網。若突破訊號午盤後仍反覆跌破開盤，應降低攻擊分數。

## 判讀方式

- `intraday_strong_attack`: 當日收紅、收盤接近日內高點，且高點後沒有明顯跌破開盤價。
- `intraday_attack_failure`: 盤中曾上攻超過 1%，但收盤轉弱、收盤位置偏低，或高點後跌破開盤價。
- `below_open_after_1130_rate`: 午盤後跌破開盤價的比例，用來檢查課程提到的攻擊不應給太多低接機會。

## 限制

- FinMind `TaiwanStockKBar` 是 sponsor 資料，且單次一天；此處只抽樣，不做全市場逐筆分K回測。
- 分K規則仍是自動化代理，尚未加入人工圖形標註，例如壓力區、頸線、江波轉折點。
"""
    REPORT_PATH.write_text(md, encoding="utf-8")
    print(REPORT_PATH)
    print(summary_path)
    print(result_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-per-signal", type=int, default=20)
    parser.add_argument("--sleep-seconds", type=float, default=0.2)
    parser.add_argument(
        "--signals",
        nargs="+",
        default=[
            "breakout_next_not_low_open",
            "breakout_next_low_open",
            "upper_shadow_new_high",
            "false_breakdown_reclaim",
        ],
    )
    args = parser.parse_args()

    token = os.environ.get("FINMIND_TOKEN")
    if not token:
        raise SystemExit("FINMIND_TOKEN is required")

    sample = build_signal_sample(args.limit_per_signal, args.signals)
    records = []
    for row in sample.itertuples(index=False):
        trade_date = pd.Timestamp(row.trade_date).strftime("%Y-%m-%d")
        kbar = fetch_kbar(str(row.ticker), trade_date, token, args.sleep_seconds)
        record = row._asdict()
        record["trade_date"] = trade_date
        record.update(intraday_features(kbar))
        records.append(record)
    result = pd.DataFrame(records)
    write_report(result, args.limit_per_signal)


if __name__ == "__main__":
    main()
