from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd
import shutil

from breakout_attack_strategy_check import MIN_AVG_VOLUME_20, MIN_CLOSE, add_trade_fields
from kline_course_backtest import add_features, load_bars


OUT_DIR = Path("data/analysis/zhuli_suffocation")
REPORT_PATH = Path("docs/主力大課程/backtests/zhuli_suffocation_scanner.md")
ARCHIVE_DIR = OUT_DIR / "archive" / "zhuli_suffocation_scanner"
DB_PATH = "/Users/howard/.four_seasons/data.sqlite"


def zhuli_add_ma_slopes(df: pd.DataFrame, periods: list[int] = [5, 10, 20, 60]) -> pd.DataFrame:
    """計算 MA 斜率（當日 MA - 前一日 MA）。

    來源：主力大全方位操盤教戰守則 Ex1-1 ~ Ex1-3

    Args:
        df: 含 ma5, ma10, ma20, ma60 欄位的 DataFrame
        periods: MA 週期列表

    Returns:
        加入 ma{period}_slope 欄位的 DataFrame
    """
    df = df.copy()
    g = df.groupby("ticker", group_keys=False)

    for period in periods:
        ma_col = f"ma{period}"
        slope_col = f"ma{period}_slope"
        if ma_col in df.columns:
            df[slope_col] = g[ma_col].diff()
        else:
            df[slope_col] = np.nan
    return df


def zhuli_add_suffocation_check(df: pd.DataFrame) -> pd.DataFrame:
    """標註窒息量 K 棒。

    來源：主力大全方位操盤教戰守則 Ex1-1 ~ Ex1-3 §H 窒息量策略
    - Ex1-1: 05:00 SOP 投影片窒息量定義
    - Ex1-2: 10:32 ~ 14:00 反轉案例 2338 光罩
    - Ex1-3: 05:00 出量定義、16:00 月線上彎定義補充

    條件：
    - Ex1-X: 窒息量定義（必要）
      量 < 20 日內最大量的 10%
    - Ex1-X: 月線上彎判定（必要）
      ma20_slope > 0（即使價已跌破月線，月線本身斜率 > 0 仍算）
    - Ex1-X: 理想條件
      5/10/20/60ma 排列且皆上彎
    """
    df = df.copy()
    g = df.groupby("ticker", group_keys=False)

    # 計算 20 日內最大量
    df["vol_max_20d"] = g["volume"].rolling(20, min_periods=20).max().reset_index(level=0, drop=True)

    # Ex1-X: 窒息量判定（量 < 20 日內最大量的 10%）
    df["zhuli_is_suffocation_vol"] = (
        df["volume"] < df["vol_max_20d"] * 0.10
    ).astype(int)

    # Ex1-X: 月線上彎判定（ma20_slope > 0）
    df["zhuli_ma20_is_upslope"] = (df["ma20_slope"] > 0).astype(int)

    # Ex1-X: 理想條件檢查（5/10/20/60ma 排列正確且皆上彎）
    # 從 Ex1-3 25:32 口說 + 26:00 手寫補充
    ma_order_ok = (
        (df["ma5"] > df["ma10"]) &
        (df["ma10"] > df["ma20"]) &
        (df["ma20"] > df["ma60"])
    )
    all_slopes_positive = (
        (df["ma5_slope"] > 0) &
        (df["ma10_slope"] > 0) &
        (df["ma20_slope"] > 0) &
        (df["ma60_slope"] > 0)
    )
    df["zhuli_ideal_ma_alignment"] = (ma_order_ok & all_slopes_positive).astype(int)

    return df


def zhuli_check_breakout_bar(df: pd.DataFrame) -> pd.DataFrame:
    """檢查當日是否為出量 K。

    來源：主力大全方位操盤教戰守則 Ex1-3 05:00 SOP 投影片

    出量 K 的定義：
    - Ex1-X: 出量 K 必須是：紅K，或下影線 > 實體長度的綠 K
    - Ex1-X: 不可：實體黑 K、實體綠 K
    - Ex1-X: 出量定義：成交量比前一根窒息量多

    Returns:
        加入 zhuli_is_breakout_bar, zhuli_breakout_bar_type 欄位
    """
    df = df.copy()
    g = df.groupby("ticker", group_keys=False)

    is_red = df["close"] >= df["open"]
    is_green = df["close"] < df["open"]

    df["body_length"] = (df["close"] - df["open"]).abs()
    df["lower_shadow"] = df[["open", "close"]].min(axis=1) - df["low"]

    # Ex1-X: 紅K 判定
    is_red_bar = is_red.astype(int)

    # Ex1-X: 下影線 > 實體長度的綠 K 判定
    is_green_with_long_lower = (
        is_green &
        (df["lower_shadow"] > df["body_length"])
    ).astype(int)

    # Ex1-X: 實體黑 K（開高收低、實體 > 0）
    is_solid_black = (is_green & (df["body_length"] > 0)).astype(int)

    # Ex1-X: 實體綠 K（開低收高、實體 > 0）
    is_solid_green = (is_red & (df["body_length"] > 0)).astype(int)

    # Ex1-X: 出量定義（量 > 前一日量）
    prev_volume = g["volume"].shift(1)
    has_more_volume = df["volume"] > prev_volume.fillna(0)

    # 綜合判定：出量 K = (紅K OR (綠K with 長下影)) AND 有更大成交量
    df["zhuli_is_breakout_bar"] = (
        (is_red_bar | is_green_with_long_lower) & has_more_volume
    ).astype(int)

    # 記錄出量 K 的類型
    df["zhuli_breakout_bar_type"] = None
    df.loc[is_red_bar & has_more_volume, "zhuli_breakout_bar_type"] = "red"
    df.loc[is_green_with_long_lower & has_more_volume, "zhuli_breakout_bar_type"] = "green_with_long_lower"

    return df


def zhuli_find_suffocation_signals(df: pd.DataFrame) -> pd.DataFrame:
    """找出窒息量 → 出量切入的訊號組合。

    來源：主力大全方位操盤教戰守則 Ex1-1 ~ Ex1-3 §H 窒息量策略

    掃描兩種情境：
    - 情境 A：月線上彎時的窒息量（主要情境）
      前一日是窒息量 + 月線上彎 + 今日是出量 K
    - 情境 B：跌破上升月線後的窒息量（反轉情境）
      月線本身上彎（斜率 > 0）但價已跌破月線
      前一日是窒息量 + 今日是出量 K

    進場條件檢查：
    - 必要：當日成交量 < 20 日內最大量的 10%（窒息量 K）
    - 必要：月線（20MA）上彎
    - 理想：5/10/20/60ma 排列正確且皆上彎
    - 進場時機：下一根出量 K
    - 停損：出量 K 的低點
    """
    df = df.copy()
    g = df.groupby("ticker", group_keys=False)

    # 前一日的窒息量、月線狀態
    prev_is_suffocation = g["zhuli_is_suffocation_vol"].shift(1).fillna(0)
    prev_ma20_slope = g["ma20_slope"].shift(1).fillna(0)
    prev_close = g["close"].shift(1).fillna(0)
    prev_ma20 = g["ma20"].shift(1).fillna(0)

    # 情境 A：前一日窒息量 + (前一日)月線上彎 + 前一日價在月線上
    scenario_a = (
        (prev_is_suffocation > 0) &
        (prev_ma20_slope > 0) &
        (prev_close >= prev_ma20)
    )

    # 情境 B：前一日窒息量 + 月線本身上彎（當日）+ 前一日價跌破月線
    scenario_b = (
        (prev_is_suffocation > 0) &
        (df["ma20_slope"] > 0) &
        (prev_close < prev_ma20)
    )

    # 當日是出量 K
    is_breakout = df["zhuli_is_breakout_bar"] > 0

    # 綜合：是出量 K，且符合情境 A 或 B
    has_scenario = scenario_a | scenario_b
    df["zhuli_has_signal"] = (is_breakout & has_scenario).astype(int)
    df["zhuli_scenario"] = None
    df.loc[scenario_a & is_breakout, "zhuli_scenario"] = "A"
    df.loc[scenario_b & is_breakout & (df["zhuli_scenario"].isna()), "zhuli_scenario"] = "B"

    # 進場訊號詳細資訊
    df["zhuli_suffocation_date"] = None
    df["zhuli_suffocation_volume"] = np.nan
    df["zhuli_suffocation_to_max20_pct"] = np.nan
    df["zhuli_breakout_date"] = None
    df["zhuli_breakout_close"] = np.nan
    df["zhuli_breakout_volume"] = np.nan
    df["zhuli_breakout_low"] = np.nan

    signal_mask = df["zhuli_has_signal"] > 0
    df.loc[signal_mask, "zhuli_suffocation_date"] = (
        g["trade_date"].shift(1).fillna(df["trade_date"])
    )[signal_mask]
    df.loc[signal_mask, "zhuli_suffocation_volume"] = (
        g["volume"].shift(1).fillna(df["volume"])
    )[signal_mask]
    df.loc[signal_mask, "zhuli_suffocation_to_max20_pct"] = (
        (g["volume"].shift(1).fillna(df["volume"]) / g["vol_max_20d"].shift(1).fillna(df["vol_max_20d"]) * 100)
    )[signal_mask]
    df.loc[signal_mask, "zhuli_breakout_date"] = df["trade_date"][signal_mask]
    df.loc[signal_mask, "zhuli_breakout_close"] = df["close"][signal_mask]
    df.loc[signal_mask, "zhuli_breakout_volume"] = df["volume"][signal_mask]
    df.loc[signal_mask, "zhuli_breakout_low"] = df["low"][signal_mask]

    return df


def prepare_output(df: pd.DataFrame) -> pd.DataFrame:
    """準備輸出的掃描結果。

    篩選出有信號的列，並整理欄位。
    """
    result = df[df["zhuli_has_signal"] > 0].copy()

    if result.empty:
        return pd.DataFrame(columns=[
            "ticker", "trade_date", "suffocation_date", "suffocation_volume",
            "suffocation_to_max20_pct", "breakout_date", "breakout_close",
            "breakout_volume", "breakout_bar_type", "ma20_slope", "ideal_ma_alignment",
            "scenario", "stop_loss_price"
        ])

    output = result[[
        "ticker",
        "trade_date",
        "zhuli_suffocation_date",
        "zhuli_suffocation_volume",
        "zhuli_suffocation_to_max20_pct",
        "zhuli_breakout_date",
        "zhuli_breakout_close",
        "zhuli_breakout_volume",
        "zhuli_breakout_bar_type",
        "ma20_slope",
        "zhuli_ideal_ma_alignment",
        "zhuli_scenario",
        "zhuli_breakout_low",
    ]].copy()

    output.columns = [
        "ticker",
        "trade_date",
        "suffocation_date",
        "suffocation_volume",
        "suffocation_to_max20_pct",
        "breakout_date",
        "breakout_close",
        "breakout_volume",
        "breakout_bar_type",
        "ma20_slope",
        "ideal_ma_alignment",
        "scenario",
        "stop_loss_price",
    ]

    # 數值精度調整
    output["suffocation_volume"] = output["suffocation_volume"].astype(int)
    output["suffocation_to_max20_pct"] = output["suffocation_to_max20_pct"].round(2)
    output["breakout_close"] = output["breakout_close"].round(2)
    output["breakout_volume"] = output["breakout_volume"].astype(int)
    output["ma20_slope"] = output["ma20_slope"].round(4)
    output["ideal_ma_alignment"] = output["ideal_ma_alignment"].astype(bool)
    output["stop_loss_price"] = output["stop_loss_price"].round(2)

    return output


def load_finmind_stock_info(force_refresh: bool = False) -> pd.DataFrame:
    """從 FinMind 取得股票基本資訊（代號、名稱、市場類別）。

    若無 token 或下載失敗，回傳空 DataFrame。
    """
    import requests

    STOCK_INFO_CACHE_PATH = OUT_DIR / "finmind_stock_info_cache.csv"
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if STOCK_INFO_CACHE_PATH.exists() and not force_refresh:
        age_hours = (time.time() - STOCK_INFO_CACHE_PATH.stat().st_mtime) / 3600
        if age_hours <= 24:
            return pd.read_csv(STOCK_INFO_CACHE_PATH, dtype=str)

    token = os.environ.get("FINMIND_TOKEN")
    if not token:
        if STOCK_INFO_CACHE_PATH.exists():
            return pd.read_csv(STOCK_INFO_CACHE_PATH, dtype=str)
        return pd.DataFrame(columns=["stock_id", "stock_name", "market_category"])

    try:
        headers = {"Authorization": f"Bearer {token}"}
        params = {"dataset": "TaiwanStockInfo"}
        response = requests.get(
            "https://api.finmindtrade.com/api/v4/data",
            params=params,
            headers=headers,
            timeout=30
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != 200:
            if STOCK_INFO_CACHE_PATH.exists():
                return pd.read_csv(STOCK_INFO_CACHE_PATH, dtype=str)
            return pd.DataFrame(columns=["stock_id", "stock_name", "market_category"])

        info = pd.DataFrame(payload.get("data") or [])
        if info.empty:
            if STOCK_INFO_CACHE_PATH.exists():
                return pd.read_csv(STOCK_INFO_CACHE_PATH, dtype=str)
            return pd.DataFrame(columns=["stock_id", "stock_name", "market_category"])

        info.to_csv(STOCK_INFO_CACHE_PATH, index=False)
        return info
    except Exception:
        if STOCK_INFO_CACHE_PATH.exists():
            return pd.read_csv(STOCK_INFO_CACHE_PATH, dtype=str)
        return pd.DataFrame(columns=["stock_id", "stock_name", "market_category"])


def enrich_with_stock_names(result: pd.DataFrame, stock_info: pd.DataFrame) -> pd.DataFrame:
    """併入股票名稱。"""
    if stock_info.empty:
        result["stock_name"] = ""
        return result

    stock_info = stock_info.rename(columns={"stock_id": "ticker"})
    result = result.merge(
        stock_info[["ticker", "stock_name"]],
        on="ticker",
        how="left"
    )
    return result


def write_report(result: pd.DataFrame, as_of_date: str | None) -> None:
    """輸出掃描報告 markdown。"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    if result.empty:
        scan_date = as_of_date or pd.Timestamp.today().strftime("%Y-%m-%d")
        md = f"""# 窒息量進場掃描器（Suffocation Volume Scanner）

資料庫：`/Users/howard/.four_seasons/data.sqlite`

掃描日期：{scan_date}

## 掃描結果

當天無符合窒息量 → 出量切入訊號的標的。

來源：主力大全方位操盤教戰守則 Ex1-1 ~ Ex1-3 §H 窒息量策略

---

輸出檔：`data/analysis/zhuli_suffocation/zhuli_suffocation_scanner.csv`
"""
        REPORT_PATH.write_text(md, encoding="utf-8")
        return

    scan_date = as_of_date or str(pd.to_datetime(result["trade_date"]).max().date())

    # 建立 markdown 表格
    table_cols = [
        "ticker", "trade_date", "suffocation_date", "suffocation_to_max20_pct",
        "breakout_bar_type", "ideal_ma_alignment", "scenario", "stop_loss_price"
    ]
    table_data = result[table_cols].copy()
    header = "| " + " | ".join(table_cols) + " |"
    divider = "| " + " | ".join(["---"] * len(table_cols)) + " |"
    lines = [header, divider]
    for row in table_data.itertuples(index=False):
        lines.append("| " + " | ".join(str(v) if not pd.isna(v) else "" for v in row) + " |")
    table_md = "\n".join(lines)

    md = f"""# 窒息量進場掃描器（Suffocation Volume Scanner）

資料庫：`/Users/howard/.four_seasons/data.sqlite`

掃描日期：{scan_date}

## 進場條件

來源：主力大全方位操盤教戰守則 Ex1-1 ~ Ex1-3 §H 窒息量策略

- **必要：** 當日成交量 < 20 日內最大量的 10%（窒息量 K）
- **必要：** 月線（20MA）上彎（斜率 > 0，即使價跌破月線仍算）
- **理想：** 5/10/20/60ma 排列且皆上彎
- **進場時機：** 下一根出量 K（紅 K，或下影線 > 實體長度的綠 K）
- **停損：** 出量 K 的低點

### 兩種有效情境

| 情景 | 說明 |
|---|---|
| A | 月線上彎且價在月線上方時出現窒息量，隔日出量進場 |
| B | 月線上彎但價已跌破月線（反轉情境），窒息量後隔日出量進場 |

## 掃描結果

樣本總數：{len(result)}

{table_md}

---

輸出檔：`data/analysis/zhuli_suffocation/zhuli_suffocation_scanner.csv`
"""
    REPORT_PATH.write_text(md, encoding="utf-8")


def archive_output(result: pd.DataFrame, as_of_date: str | None) -> Path:
    """存檔輸出結果。"""
    if as_of_date:
        day_key = as_of_date
    elif result.empty:
        day_key = pd.Timestamp.today().strftime("%Y-%m-%d")
    else:
        day_key = str(pd.to_datetime(result["trade_date"]).max().date())

    archive_path = ARCHIVE_DIR / day_key
    archive_path.mkdir(parents=True, exist_ok=True)

    output_path = archive_path / "zhuli_suffocation_scanner.csv"
    result.to_csv(output_path, index=False)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="窒息量進場掃描器 — 掃描所有上市櫃股票，列出符合『窒息量 → 出量切入』訊號的清單。"
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="掃描日期 (YYYY-MM-DD)；不指定則使用最新交易日"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="輸出 CSV 檔案路徑；不指定則存到預設位置"
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=None,
        help="只輸出前 N 檔；不指定則輸出全部"
    )
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 載入日K數據
    print("載入日K數據...")
    df = load_bars()
    df = add_features(df)
    df = add_trade_fields(df)

    # 過濾掃描日期
    if args.date:
        cutoff = pd.Timestamp(args.date)
        df = df[pd.to_datetime(df["trade_date"]) <= cutoff].copy()

    # 新增 MA 斜率
    print("計算 MA 斜率...")
    df = zhuli_add_ma_slopes(df)

    # 窒息量判定
    print("檢查窒息量條件...")
    df = zhuli_add_suffocation_check(df)

    # 出量 K 判定
    print("檢查出量 K 條件...")
    df = zhuli_check_breakout_bar(df)

    # 找出窒息量 → 出量的訊號組合
    print("掃描窒息量進場訊號...")
    df = zhuli_find_suffocation_signals(df)

    # 準備輸出
    result = prepare_output(df)

    if args.top_n:
        result = result.head(args.top_n)

    # 併入股票名稱
    if not result.empty:
        stock_info = load_finmind_stock_info()
        result = enrich_with_stock_names(result, stock_info)

    # 輸出 CSV
    output_path = args.output or str(OUT_DIR / "zhuli_suffocation_scanner.csv")
    result.to_csv(output_path, index=False)
    print(f"輸出：{output_path}")

    # 輸出報告
    write_report(result, args.date)
    print(f"報告：{REPORT_PATH}")

    # 存檔
    archive_path = archive_output(result, args.date)
    print(f"存檔：{archive_path}")


if __name__ == "__main__":
    main()
