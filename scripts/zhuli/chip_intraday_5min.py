"""5 分 K 盤中量價結構警示模組。

公開 API：
    intraday_5min_warnings(ticker, target_date=None) -> tuple[int, list[str]]

警示邏輯依據主力大課程；盤中只作預警，最終判斷以日收盤確認為準。
"""
from __future__ import annotations

import os
from datetime import date, datetime
from typing import Optional

import pandas as pd
import requests


def _fetch_1min_kbar(ticker: str, target_date: str) -> pd.DataFrame:
    """從 FinMind TaiwanStockKBar 取指定日期 1 分 K 資料。

    Returns DataFrame，欄位：date, minute, open, high, low, close, volume
    """
    token = os.environ.get("FINMIND_TOKEN", "")
    try:
        r = requests.get(
            "https://api.finmindtrade.com/api/v4/data",
            params={
                "dataset": "TaiwanStockKBar",
                "data_id": ticker,
                "start_date": target_date,
                "end_date": target_date,
                "token": token,
            },
            timeout=20,
        )
        r.raise_for_status()
        payload = r.json()
        records = payload.get("data", [])
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        return df
    except Exception as exc:
        raise RuntimeError(f"FinMind API 失敗: {exc}") from exc


def _build_5min_bars(df1m: pd.DataFrame) -> pd.DataFrame:
    """將 1 分 K 聚合為 5 分 K。

    minute 欄位格式為 'HH:MM:00'；以 target_date + minute 組成完整 timestamp，
    再 resample 到 5 分鐘（label='left'）。
    """
    # 取得 target_date（用第一列 date 欄）
    target_date_str = str(df1m["date"].iloc[0])

    # 組合 datetime index
    df1m = df1m.copy()
    df1m["ts"] = pd.to_datetime(
        target_date_str + " " + df1m["minute"].str.strip()
    )
    df1m = df1m.set_index("ts").sort_index()

    # 只保留 09:00 ~ 13:24（開盤至收盤前；不含尾盤揭示）
    df1m = df1m.between_time("09:00", "13:24")

    # 數值轉型
    for col in ("open", "high", "low", "close", "volume"):
        df1m[col] = pd.to_numeric(df1m[col], errors="coerce")

    # Resample 5 分 K
    df5m = df1m.resample("5min", label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna(subset=["open", "close"])

    return df5m


def _detect_warnings(df5m: pd.DataFrame) -> tuple[int, list[str]]:
    """對 5 分 K DataFrame 執行警示偵測，回傳 (score, warning_lines)。"""
    total_score = 0
    lines: list[str] = []

    n = len(df5m)
    if n < 5:
        return 0, ["  ? 5min K 資料不足（< 5 根）"]

    # 移動平均 (20 根)
    window = min(20, n)
    df5m = df5m.copy()
    df5m["vma20"] = df5m["volume"].rolling(window, min_periods=1).mean()
    df5m["ma20"]  = df5m["close"].rolling(window, min_periods=1).mean()

    # ---------- 規則 1：5 分黑 K 量爆 [2 分] ----------
    # 條件：body < -1%（收黑）且 vol > vma20 × 2
    df5m["body_pct"] = (df5m["close"] - df5m["open"]) / df5m["open"]
    black_big = df5m[(df5m["body_pct"] < -0.01) & (df5m["volume"] > df5m["vma20"] * 2)]
    if not black_big.empty:
        row = black_big.iloc[-1]  # 最近一根
        ts_str = row.name.strftime("%H:%M")
        body_pct = row["body_pct"] * 100
        vol_x = row["volume"] / row["vma20"] if row["vma20"] > 0 else 0
        total_score += 2
        lines.append(
            f"[2分] 5min 黑 K 量爆 — {ts_str} body {body_pct:.1f}% vol×{vol_x:.1f}"
        )

    # ---------- 規則 2：連 3 根上影 > 1% [1 分] ----------
    # 上影 = (high - max(open, close)) / close
    df5m["upper_shadow"] = (
        df5m["high"] - df5m[["open", "close"]].max(axis=1)
    ) / df5m["close"]
    # 找連續 3 根以上上影 > 1% 的情況
    df5m["upper_over1"] = df5m["upper_shadow"] > 0.01
    # 用 rolling sum 找連續三根都超標
    consecutive3 = (
        df5m["upper_over1"].rolling(3).sum() == 3
    )
    if consecutive3.any():
        # 取最後一組連續 3 根的結尾位置
        last_idx = consecutive3[consecutive3].index[-1]
        pos = df5m.index.get_loc(last_idx)
        three_rows = df5m.iloc[pos - 2 : pos + 1]
        pcts = [f"{v*100:.1f}%" for v in three_rows["upper_shadow"].values]
        total_score += 1
        lines.append(f"[1分] 連 3 根上影 — {'/'.join(pcts)}")

    # ---------- 規則 3：攻擊失敗 [2 分] ----------
    # 最近 1 小時（12 根 5 分 K）最高點，被跌破超過 1%
    last_12 = df5m.tail(12)
    if len(last_12) >= 3:
        hour_high = last_12["high"].max()
        current_close = df5m["close"].iloc[-1]
        drop_pct = (current_close / hour_high - 1) * 100
        if drop_pct < -1.0:
            total_score += 2
            lines.append(
                f"[2分] 攻擊失敗 — 近 1H 高 {hour_high:.2f} 跌破 {drop_pct:.1f}% > 1%"
            )

    # ---------- 規則 4：量縮跌破均 K [1 分] ----------
    # 條件：最後一根 close < ma20 且 vol < vma20
    last = df5m.iloc[-1]
    if last["close"] < last["ma20"] and last["volume"] < last["vma20"]:
        ts_str = last.name.strftime("%H:%M")
        total_score += 1
        lines.append(
            f"[1分] 量縮跌破均 K — {ts_str} close {last['close']:.2f} < ma20 {last['ma20']:.2f}，"
            f"vol {last['volume']:.0f} < vma20 {last['vma20']:.0f}"
        )

    # ---------- 規則 5：開盤後最低 K 量 > vma20 × 3 [1 分] ----------
    # 找量最大的 K 棒，若其 close < open（下跌） 且 vol > vma20 × 3
    # （課程 Ch2-4：開盤大量急跌 = 量大跌）
    max_vol_idx = df5m["volume"].idxmax()
    max_vol_row = df5m.loc[max_vol_idx]
    if (
        max_vol_row["volume"] > max_vol_row["vma20"] * 3
        and max_vol_row["close"] < max_vol_row["open"]
    ):
        ts_str = max_vol_idx.strftime("%H:%M")
        vol_x = max_vol_row["volume"] / max_vol_row["vma20"] if max_vol_row["vma20"] > 0 else 0
        total_score += 1
        lines.append(
            f"[1分] 開盤量大跌 K — {ts_str} vol×{vol_x:.1f} > 3x，收黑"
        )

    return total_score, lines


def intraday_5min_warnings(
    ticker: str,
    target_date: Optional[str] = None,
) -> tuple[int, list[str]]:
    """從 FinMind TaiwanStockKBar 抓當日 1 分 K，聚合 5 分 K，做警示偵測。

    Args:
      ticker: 股號
      target_date: 預設 today (YYYY-MM-DD)；盤後/隔日測試可指定歷史日期

    Returns (score, warning_lines).

    level：
      0 = 無
      1 = 🟡 觀察
      2 = ⚠️ 盤中警示
      3+ = 🔴 強警示（建議檢核出場）

    課程紅線：本警示不指定出場價，只標「應檢核」。
    所有判斷仍以日收盤確認為準（盤中只是預警）。
    """
    if target_date is None:
        target_date = date.today().strftime("%Y-%m-%d")

    # --- 取 1 分 K ---
    try:
        df1m = _fetch_1min_kbar(ticker, target_date)
    except Exception as exc:
        return (0, [f"  ? 5min K 取資料失敗: {exc}"])

    if df1m.empty:
        return (0, ["  ? 非交易日無 5min K"])

    # --- 聚合 5 分 K ---
    try:
        df5m = _build_5min_bars(df1m)
    except Exception as exc:
        return (0, [f"  ? 5min K 聚合失敗: {exc}"])

    if len(df5m) < 5:
        return (0, ["  ? 5min K 資料不足"])

    # --- 偵測警示 ---
    try:
        score, warn_lines = _detect_warnings(df5m)
    except Exception as exc:
        return (0, [f"  ? 5min 警示偵測失敗: {exc}"])

    # --- 組合輸出 ---
    if score == 0:
        return (0, [])

    if score >= 3:
        level_icon = "🔴 強警示（建議檢核出場）"
    elif score == 2:
        level_icon = "⚠️ 盤中警示"
    else:
        level_icon = "🟡 觀察"

    header = f"{level_icon} 5min score={score}"
    output_lines = [header] + [f"  {ln}" for ln in warn_lines]
    output_lines.append("  ※ 盤中預警；最終仍以日收盤確認為準（課程紅線）")

    return (score, output_lines)
