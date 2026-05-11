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

    # --- Task 12 代理：壓力區、套牢區、賣壓中空 ---
    # 設計依據：strategy-indicators.md 第 4 節
    #   - 「壓力來自過往套牢區、密集成交區、前高附近」
    #   - 「賣壓化解要觀察股價是否能有效穿越過往套牢區，且穿越後不快速跌回」
    #   - 「層層套牢表示上方不同價位都有潛在賣壓」
    #   - 「賣壓中空表示中間區段籌碼壓力較少」
    # 注意：以下皆為 OHLCV 代理，volume profile 級別的「密集成交區」無法
    # 用日K完整捕捉；具體限制見 supply_zone_spec_report.md。

    # (1) overhead_supply_layer 與 (2) supply_vacuum_zone：
    # 透過 lag 1..LOOKBACK 的逐 offset 累加，正確比較「歷史 N 個 bar 的價/量」與「今日 close」。
    # 使用 240 日 (~1 年) 視窗，原因：breakout_attack 由 close > prior_high_60 定義，
    # 若用 60 日視窗，breakout 當下上方必無套牢，代理退化。240 日可涵蓋更早的套牢區間。
    LOOKBACK = 240
    n = len(df)
    overhead_layer_acc = np.zeros(n, dtype=float)
    overlap_vol_acc = np.zeros(n, dtype=float)
    above_vol_acc = np.zeros(n, dtype=float)
    total_vol_acc = np.zeros(n, dtype=float)

    close_today = df["close"].to_numpy()
    band_low_arr = close_today
    band_high_arr = close_today * 1.10

    for lag in range(1, LOOKBACK + 1):
        past_high_l = g["high"].shift(lag).to_numpy()
        past_low_l = g["low"].shift(lag).to_numpy()
        past_vol_l = g["volume"].shift(lag).fillna(0).to_numpy()
        past_max5_l = g["high"].shift(lag).rolling(5, min_periods=5).max().reset_index(level=0, drop=True).to_numpy()
        is_peak_l = (past_high_l == past_max5_l) & ~np.isnan(past_max5_l)

        overhead_layer_acc += ((past_high_l > close_today) & is_peak_l).astype(float)
        in_band = (past_high_l >= band_low_arr) & (past_low_l <= band_high_arr)
        overlap_vol_acc += np.where(in_band, past_vol_l, 0.0)
        above_vol_acc += np.where(past_high_l > close_today, past_vol_l, 0.0)
        total_vol_acc += past_vol_l

    has_history = (g.cumcount().to_numpy() >= 20)
    df["overhead_supply_layer"] = np.where(has_history, overhead_layer_acc, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        band_ratio = np.where(total_vol_acc > 0, overlap_vol_acc / total_vol_acc, np.nan)
        above_ratio = np.where(total_vol_acc > 0, above_vol_acc / total_vol_acc, np.nan)
    df["overhead_band_vol_ratio"] = np.where(has_history, band_ratio, np.nan)
    df["overhead_above_vol_ratio"] = np.where(has_history, above_ratio, np.nan)

    # supply_vacuum_zone：上方任意位置存在賣壓 (above_ratio > 5%)，但
    # 近價 0~10% 帶的成交量佔上方總量比率 < 20%，視為「賣壓中空」。
    band_share_of_above = pd.Series(
        np.where(above_vol_acc > 0, overlap_vol_acc / above_vol_acc, np.nan),
        index=df.index,
    )
    df["supply_vacuum_zone"] = (
        has_history
        & (df["overhead_above_vol_ratio"].fillna(0) >= 0.05)
        & (band_share_of_above.fillna(1.0) < 0.20)
    ).astype(int)

    # (3) supply_zone_absorbed
    #     代理：今日「有效穿越」前 60 日高點（close > prior_high_60）
    #     且 5 日後仍未跌回該高點下方（連續 5 日 close >= prior_high_60 * 0.98）。
    #     注意：此為前瞻欄位，僅用於回測標註，不可作為當下交易訊號使用。
    # 取未來 1~5 天的最小收盤
    fwd_closes = pd.concat([g["close"].shift(-i) for i in range(1, 6)], axis=1)
    fwd_min_close = fwd_closes.min(axis=1)
    df["supply_zone_absorbed"] = (
        (df["close"] > df["prior_high_60"])
        & df["prior_high_60"].notna()
        & (fwd_min_close >= df["prior_high_60"] * 0.98)
    )

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
    )
    df["breakout_next_not_low_open"] = df["breakout_attack"] & (df["next_open_gap_vs_close"] >= 0)
    df["breakout_next_low_open"] = df["breakout_attack"] & (df["next_open_gap_vs_close"] < 0)

    # Task 12：突破時上方是否有套牢壓力 / 是否賣壓中空
    layer = df.get("overhead_supply_layer")
    if layer is not None:
        df["breakout_low_overhead"] = df["breakout_attack"] & (layer.fillna(0) <= 1)
        df["breakout_high_overhead"] = df["breakout_attack"] & (layer.fillna(0) >= 4)
    vacuum = df.get("supply_vacuum_zone")
    if vacuum is not None:
        df["breakout_vacuum_above"] = df["breakout_attack"] & (vacuum == 1)
        df["breakout_dense_above"] = df["breakout_attack"] & (vacuum == 0)

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

    # ------------------------------------------------------------------
    # 舊版 real_breakdown_after_range（保留供對比）
    # 條件：無急跌 + 黑K + 收盤跌破60日前低 + 長K線（振幅>=2.5%）
    # 缺點：過於粗糙，未考慮整理後跌破頸線與季線方向
    # ------------------------------------------------------------------
    df["real_breakdown_after_range_old"] = (
        ~df["panic_drop"].fillna(False)
        & black
        & (df["close"] < key_level)
        & (df["range_pct"] >= 0.025)
    )

    # ------------------------------------------------------------------
    # 新版 real_breakdown_after_range
    # 根據 pattern_labeling_spec.md §2「頸線」與 strategy-indicators.md L310
    # 課程定義：「整理後長黑跌破頸線，反彈站不回」
    #
    # 量化代理（只用 OHLCV 日K）：
    #   1. 前段整理（箱型存在）：過去 20 日 high/low 之差 <= 15%，且至少 10 日
    #      → 代理為 prior_high_20 / prior_low_20 之比例
    #   2. 跌破關鍵價（頸線代理 = prior_low_20）：close < prior_low_20
    #   3. 隔日確認跌破（收盤仍在關鍵價下方）：next_close < prior_low_20
    #   4. 長黑K：黑K且振幅 >= 2%（body_pct >= 0.015）
    #   5. 季線下彎（ma60_slope < 0）：ma60 / ma60.shift(5) - 1 < 0
    #   6. 非急跌後彈回（排除 panic_drop）
    #
    # 對應 pattern_labeling_spec.md §2：
    #   neckline_break        = close(t) < neckline_price
    #   neckline_break_confirm = close(t+1) < neckline_price
    #   ma60_direction_at_break = down
    # ------------------------------------------------------------------
    g = df.groupby("ticker", group_keys=False)

    # 箱型代理：20日高低範圍 <= 15%（區間整理的上下緣）
    range_width_20 = (df["prior_high_20"] - df["prior_low_20"]) / df["prior_low_20"].replace(0, np.nan)
    in_range_20 = range_width_20.fillna(1.0) <= 0.15

    # 頸線代理：20日前低（區間下緣，最近的整理低點）
    neckline_proxy = df["prior_low_20"]

    # 季線斜率：5日視窗
    ma60_slope = df["ma60"] / g["ma60"].shift(5) - 1
    ma60_down = ma60_slope.fillna(0) < 0

    # 隔日收盤確認（next_close 已在 add_features 計算）
    next_close_below_neckline = df["next_close"] < neckline_proxy

    df["real_breakdown_after_range"] = (
        ~df["panic_drop"].fillna(False)   # 非急跌情境
        & black                            # 黑K
        & (df["body_pct"] >= 0.015)       # 長黑（實體 >= 1.5%）
        & (df["close"] < neckline_proxy)  # 收盤跌破頸線代理
        & next_close_below_neckline        # 隔日確認跌破
        & in_range_20                      # 前段處於箱型整理
        & ma60_down                        # 季線下彎
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
| 整理後長黑跌破偏真正轉弱（舊版代理） | `real_breakdown_after_range_old` | 舊版不支持。10 日 close-basis 平均仍為 {val("real_breakdown_after_range_old", "mean_close_basis_10d_pct"):.3f}%；代表單用 60 日前低與長黑不足以捕捉課程的「頸線/整理後跌破」。 |
| 整理後長黑跌破偏真正轉弱（新版代理） | `real_breakdown_after_range` | 新版加入箱型整理、季線下彎、隔日確認條件。10 日 close-basis 平均為 {val("real_breakdown_after_range", "mean_close_basis_10d_pct"):.3f}%，勝率 {val("real_breakdown_after_range", "win_rate_close_basis_10d_pct"):.2f}%。 |
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
- `real_breakdown_after_range_old` 舊版代理：單用 60 日前低 + 長黑，不足以捕捉課程頸線跌破語意。
- `real_breakdown_after_range` 新版代理：加入箱型整理、季線下彎、隔日確認，更接近課程定義。

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
        "real_breakdown_after_range_old",
        "real_breakdown_after_range",
        "breakout_low_overhead",
        "breakout_high_overhead",
        "breakout_vacuum_above",
        "breakout_dense_above",
        "supply_zone_absorbed",
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
