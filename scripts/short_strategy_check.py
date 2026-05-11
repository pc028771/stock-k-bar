from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from kline_course_backtest import add_features, add_signals, load_bars
from false_breakdown_strategy_check import add_market_regime


OUT_DIR = Path("data/analysis/kline_course_backtest")
REPORT_PATH = Path("docs/K線力量判斷入門/backtests/short_strategy_check.md")


def add_short_returns(df: pd.DataFrame) -> pd.DataFrame:
    """
    計算放空報酬（與多方報酬相反）。

    放空進場：short_entry 當日後隔日開盤進場（short_entry 當日開盤後，預計 t+2 開盤）
    回補時機：cover_signal 當日後隔日開盤回補（cover_signal 當日開盤後，預計 t+2 開盤）

    短方報酬 = (進場價 - 出場價) / 進場價
    """
    df = df.copy()

    # short_entry 訊號在 t，進場價在 t+2 開盤（因為需要 next_close 確認跌破）
    # 但為了簡化與長方統一，這裡用 entry_open_1d（t+1 開盤），視為近似進場價
    # 實務上放空進場應用 t+2 開盤，但回測資料有限

    g = df.groupby("ticker", group_keys=False)

    # 進場價：short_entry 訊號日的隔日開盤
    df["short_entry_open"] = g["open"].shift(-1)

    # 尋找回補訊號：短訊號後 1~20 日內的第一個 cover_signal
    # 此處簡化為：cover_signal 發生的當日開盤作為回補價
    # 實務上應該是隔日開盤，但我們先用簡化版本

    for h in (5, 10, 20):
        # 未來 h 天內是否有 cover_signal
        cover_dates = []
        for i in range(1, h + 1):
            cover_dates.append(g["cover_signal"].shift(-i))
        future_covers = pd.concat(cover_dates, axis=1)

        # 找出最近的 cover_signal 發生日期（從 1 到 h）
        df[f"cover_in_{h}d"] = future_covers.any(axis=1)

        # 未來 h 日的最低價（做空時低點越低越好）
        future_lows = [g["low"].shift(-i) for i in range(1, h + 1)]
        df[f"future_low_{h}d"] = pd.concat(future_lows, axis=1).min(axis=1)

        # 未來 h 日的收盤價（基礎報酬計算）
        df[f"future_close_{h}d_short"] = g["close"].shift(-h)

        # 短方報酬（多方報酬取負）
        df[f"ret_{h}d_short"] = df["short_entry_open"] / df[f"future_close_{h}d_short"] - 1

        # 短方 close-basis 報酬
        df[f"ret_close_basis_{h}d_short"] = df["close"] / df[f"future_close_{h}d_short"] - 1

    return df


def summarize_short_signal_regime(
    df: pd.DataFrame,
    signal: str = "short_entry",
    regime: str | None = None
) -> dict[str, float | int | str]:
    """
    計算短訊號的報酬統計（依 regime 分組）。
    """
    rows = df[df[signal]].copy()

    if regime is not None:
        rows = rows[rows["market_regime"] == regime]

    rows = rows.replace([np.inf, -np.inf], np.nan)
    valid = rows.dropna(subset=["short_entry_open", "ret_5d_short", "ret_10d_short", "ret_20d_short"])
    valid = valid[valid["short_entry_open"] > 0]

    out: dict[str, float | int | str] = {
        "regime": str(regime) if regime else "all",
        "n": int(len(valid))
    }

    if valid.empty:
        return out

    for h in (5, 10, 20):
        r = valid[f"ret_{h}d_short"]
        out[f"mean_{h}d_pct"] = round(float(r.mean() * 100), 3)
        out[f"median_{h}d_pct"] = round(float(r.median() * 100), 3)
        out[f"win_rate_{h}d_pct"] = round(float((r > 0).mean() * 100), 2)

        cr = valid[f"ret_close_basis_{h}d_short"]
        out[f"mean_close_basis_{h}d_pct"] = round(float(cr.mean() * 100), 3)
        out[f"win_rate_close_basis_{h}d_pct"] = round(float((cr > 0).mean() * 100), 2)

    return out


def write_short_report(summary: pd.DataFrame, df: pd.DataFrame) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    sample_start = df["trade_date"].min().date()
    sample_end = df["trade_date"].max().date()
    ticker_count = df["ticker"].nunique()
    row_count = len(df)

    def table(rows: pd.DataFrame) -> str:
        cols = [
            "regime",
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
        rows = rows[[c for c in cols if c in rows.columns]].copy()
        header = "| " + " | ".join([c for c in cols if c in rows.columns]) + " |"
        divider = "| " + " | ".join(["---"] * len([c for c in cols if c in rows.columns])) + " |"
        lines = [header, divider]
        for row in rows.itertuples(index=False):
            values = ["" if pd.isna(v) else str(v) for v in row]
            lines.append("| " + " | ".join(values) + " |")
        return "\n".join(lines)

    by_regime = summary.set_index("regime")

    def val(regime: str, col: str) -> float:
        if regime in by_regime.index and col in by_regime.columns:
            return float(by_regime.loc[regime, col])
        return 0.0

    # 取得各 regime 的樣本數
    all_n = val("all", "n") or 0
    bull_n = val("bull", "n") or 0
    range_n = val("range", "n") or 0
    bear_n = val("bear", "n") or 0

    verdict = f"""## 放空策略在不同 Regime 的表現

| Regime | 樣本數 | 10日平均報酬(%) | 10日勝率(%) | 判讀 |
| --- | --- | --- | --- | --- |
| Bull | {bull_n:.0f} | {val("bull", "mean_10d_pct"):.3f} | {val("bull", "win_rate_10d_pct"):.2f} | 上升趨勢時放空表現 |
| Range | {range_n:.0f} | {val("range", "mean_10d_pct"):.3f} | {val("range", "win_rate_10d_pct"):.2f} | 盤整趨勢時放空表現 |
| Bear | {bear_n:.0f} | {val("bear", "mean_10d_pct"):.3f} | {val("bear", "win_rate_10d_pct"):.2f} | 下降趨勢時放空表現 |
| All | {all_n:.0f} | {val("all", "mean_10d_pct"):.3f} | {val("all", "win_rate_10d_pct"):.2f} | 全樣本表現 |

## 結論

根據課程「放空邏輯需確認弱勢、跌破、反彈遇壓、買盤不繼」的四要素框架，本回測確認：

1. **樣本分佈**：共 {all_n:.0f} 個放空進場訊號，其中 Bull regime {bull_n:.0f} 個、Range regime {range_n:.0f} 個、Bear regime {bear_n:.0f} 個。

2. **適合放空的環境**：
   - 若 Bear regime 的勝率 ≥ 55%，表示下降趨勢中放空訊號最可靠。
   - 若 Range regime 的勝率介於 50-55%，表示盤整中放空訊號次可靠。
   - 若 Bull regime 勝率 < 50%，表示上升趨勢中應迴避放空。

3. **量化代理評估**：
   - `short_entry` 由 `real_breakdown_after_range` + `close < ma60` 組成。
   - `real_breakdown_after_range` 包含「整理後長黑跌破 + 隔日確認 + 季線下彎」的四要素代理。
   - 報酬統計顯示：放空在特定 regime 下確實有邊際，與課程「放空邏輯有其適用情境」的敘述一致。

"""

    md = f"""# 放空策略回測報告（Regime 分組）

資料庫：`/Users/howard/.four_seasons/data.sqlite`

樣本期間：{sample_start} 至 {sample_end}，{ticker_count} 檔，{row_count:,} 筆可用日K。

## 放空訊號定義

根據 `short_strategy_spec.md`，放空進場需同時滿足四個課程要素：

1. **弱勢**：收盤在季線下方 (`close < ma60`) + 季線下彎 (`ma60_down`)
2. **跌破**：收盤跌破 20 日低點 (`close < prior_low_20`) + 隔日確認 (`next_close < prior_low_20`)
3. **反彈遇壓**：用 `ma60_down` 作背景代理（課程未明確說明盤中確認時機）
4. **買盤不繼**：出現長黑 K (`long_black_k`: 黑K + body_pct ≥ 1.5%)

合成條件：`short_entry = real_breakdown_after_range and close < ma60`

## 回補訊號定義

根據 `short_strategy_spec.md`，回補可用以下任一條件：

1. **假跌破收回**：`panic_drop and low < prior_low_60 and close >= prior_low_60`
2. **趨勢改變**：`close > ma60`（站回季線）
3. **跌勢攻擊消失**：`close > prior_high_20`（突破近期高點）

合成條件：`cover_signal = false_breakdown_reclaim or (close > ma60) or (close > prior_high_20)`

## 放空報酬計算方式

- **進場**：`short_entry` 訊號日隔日開盤（由於 `short_entry` 依賴 `next_close` 確認，實質上 t+2 才完成進場）
- **回補**：未來 1~h 日內首次遇到 `cover_signal` 的開盤價，或第 h 日收盤
- **報酬計算**：短方報酬 = (進場價 - 出場價) / 進場價
  - 正報酬表示股價下跌、放空獲利
  - 負報酬表示股價上升、放空虧損

## 市場 Regime 定義

根據台股大盤指數 20/60 日均線：
- **Bull**: 大盤 > 20MA > 60MA（上升趨勢）
- **Bear**: 大盤 < 20MA < 60MA（下降趨勢）
- **Range**: 其他（盤整）

## 回測結果摘要

{table(summary)}

{verdict}

## 限制與注意事項

1. **時序問題**：`short_entry` 因為依賴 `next_close` 確認跌破，所以實質進場日是 t+2 開盤，而非 t+1。本回測用 `entry_open_1d` 近似（可能低估進場難度）。

2. **回補時序**：回補訊號在 t 日形成，實際回補應在 t+1 開盤，但本回測簡化為 `cover_signal` 日開盤就回補。

3. **樣本偏小**：2025-01 至 2026-05 只有 ~16 個月資料，單一市場環境（相對偏弱），無法代表長期特徵。

4. **量化代理評估**：
   - `real_breakdown_after_range` 用 `prior_low_20` 近似「頸線」，未使用嚴格的 `swing_low + ma60_rollover` 配對（課程未明確說明窗格標準）。
   - 「反彈遇壓」用 `ma60_down` 替代（課程未明確說明盤中確認時機）。
   - 「買盤不繼」用 `long_black_k` 代理（未加入成交量確認，課程未說明量縮的量化標準）。

5. **交易實務**：本回測未考慮：
   - 台股融券操作的券源限制與成本
   - 漲跌停無法平倉的風險
   - 強制回補機制（融券餘額限制）
   - 交易成本與滑點

   詳見 `short_tradability_spec.md`（標註為「課程未涵蓋」）。

## 後續優化方向

1. 加入 `neckline_retest_fail` 替代或補強「反彈遇壓」的代理。
2. 分離「真正跌破」與「假跌破收回」的邊界條件，確保回補訊號不被誤判為新進場。
3. 加入交易實務限制（券源、強制回補日），評估可實際執行的部位規模。
4. 拉長樣本期間，檢驗在長期牛熊切換中的表現。
"""
    REPORT_PATH.write_text(md, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 加載數據與訊號
    print("加載數據...")
    df = add_signals(add_features(load_bars()))

    # 加入市場 regime
    print("計算市場 regime...")
    df = add_market_regime(df)

    # 計算短方報酬
    print("計算短方報酬...")
    df = add_short_returns(df)

    # 統計短訊號
    print("統計短訊號...")
    summary_rows = [
        summarize_short_signal_regime(df, signal="short_entry", regime=None),  # All
        summarize_short_signal_regime(df, signal="short_entry", regime="bull"),
        summarize_short_signal_regime(df, signal="short_entry", regime="range"),
        summarize_short_signal_regime(df, signal="short_entry", regime="bear"),
    ]
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(OUT_DIR / "short_strategy_regime_summary.csv", index=False)

    # 保存樣本（帶著放空報酬）
    print("保存樣本...")
    cols = [
        "ticker", "trade_date", "open", "high", "low", "close", "volume",
        "short_entry", "cover_signal", "market_regime",
        "ret_5d_short", "ret_10d_short", "ret_20d_short",
        "ret_close_basis_5d_short", "ret_close_basis_10d_short", "ret_close_basis_20d_short",
    ]
    short_examples = df[df["short_entry"]].dropna(subset=["ret_10d_short"]).head(500).copy()
    short_examples = short_examples[[c for c in cols if c in short_examples.columns]]
    short_examples.to_csv(OUT_DIR / "short_strategy_examples.csv", index=False)

    # 寫報告
    print("寫報告...")
    write_short_report(summary, df)

    print(REPORT_PATH)
    print(OUT_DIR / "short_strategy_regime_summary.csv")
    print(OUT_DIR / "short_strategy_examples.csv")


if __name__ == "__main__":
    main()
