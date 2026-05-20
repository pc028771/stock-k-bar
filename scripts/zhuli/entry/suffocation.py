"""窒息量 entry signal (H 策略) — 主力大 Ex1-1 ~ Ex1-3.

Course source: 主力大全方位操盤教戰守則 (林家洋)
  - strategy-indicators.md §H 窒息量策略
  - course_principles.md §16 窒息量加碼
  - phase1_scanner_proposal.md §3 H 窒息量最小可行版

Logic:
    1. 前一根 K (suffocation bar) 滿足窒息量：
         volume < max(vol_20d) * max20_volume_ratio  (課程定義 10%)
    2. 月線 (MA20) 必須上彎：
         ma20_slope > 0
         （即使價已跌破月線，月線本身斜率 > 0 仍算，見情境 B）
    3. 今日為「出量 K」：
         volume > prev_bar.volume  (比前一根窒息量多)
         形態：紅K，或下影線 > 實體長度的綠K
         排除：實體黑K、實體綠K（下影線不夠長）
    4. 兩情境皆輸出，由 scenario 欄位區分：
         A — close >= ma20（價在月線上）
         B — close < ma20（價已跌破月線，但月線仍上彎）
       ⚠️ scanner 不因「價 < 月線」過濾掉情境 B

Output columns:
    ticker          — 股票代號
    signal_date     — 出量 K 日期（今日）
    scenario        — 'A' or 'B'
    suffocation_date — 窒息量 K 日期（前一根）
    suffocation_vol  — 窒息量 K 的成交量
    suffocation_vol_ratio — suffocation_vol / max_vol_20d
    breakout_close  — 出量 K 收盤價
    breakout_vol    — 出量 K 成交量
    breakout_bar_type — 'red' | 'green_long_lower_shadow'
    ma20            — 月線數值
    ma20_slope      — 月線斜率（DB 欄位或 5d proxy）
    ideal_ma_align  — 是否理想多頭排列（5>10>20>60 全上彎）
    stop_loss       — 出量 K 低點（停損參考）
"""
from __future__ import annotations

import pandas as pd

from zhuli.config import SuffocationConfig


def _classify_breakout_bar(df: pd.DataFrame) -> pd.Series:
    """Classify each bar as valid breakout bar type.

    Returns Series of str: 'red', 'green_long_lower_shadow', or 'invalid'.

    Course rules (strategy-indicators.md §H):
      - 紅K → 'red'
      - 綠K 且 下影線 > 實體長度 → 'green_long_lower_shadow'
      - 實體黑K → 'invalid'
      - 實體綠K（下影線不夠長）→ 'invalid'

    Implementation note:
      - 紅K: close > open
      - 綠K: close < open (including doji close == open treated as invalid)
      - 下影線 = min(open, close) - low
      - 實體 = abs(close - open)
    """
    is_red = df["close"] > df["open"]
    is_green = df["close"] < df["open"]

    lower_shadow = df[["open", "close"]].min(axis=1) - df["low"]
    body_abs = (df["close"] - df["open"]).abs()

    green_long_lower = is_green & (lower_shadow > body_abs)

    result = pd.Series("invalid", index=df.index)
    result = result.mask(is_red, "red")
    result = result.mask(green_long_lower, "green_long_lower_shadow")
    return result


def detect(
    df: pd.DataFrame,
    cfg: SuffocationConfig | None = None,
) -> pd.DataFrame:
    """Detect 窒息量 entry signals.

    Args:
        df: Features DataFrame after add_features() + add_zhuli_features().
            Required columns: ticker, trade_date, open, high, low, close,
            volume, ma20, ma20_slope, max_vol_20d, prev_volume,
            ideal_ma_align, vol_ratio_20d.
        cfg: SuffocationConfig. Uses defaults if None.

    Returns:
        DataFrame of signal rows, one row per detected signal.
        Columns: see module docstring.
        Sorted by signal_date desc, then ticker.
    """
    if cfg is None:
        cfg = SuffocationConfig()

    g = df.groupby("ticker", group_keys=False)

    # === Suffocation bar (yesterday / lookback_days ago) ===
    # Candidate suffocation K = the bar cfg.lookback_days before today.
    # Default: lookback_days=1 → yesterday.
    shift_n = cfg.lookback_days

    # Yesterday's volume and max_vol_20d at yesterday's position
    prev_vol = g["volume"].shift(shift_n)
    prev_max_vol_20d = g["max_vol_20d"].shift(shift_n)
    prev_trade_date = g["trade_date"].shift(shift_n)

    # 窒息量條件: volume < max_vol_20d * 10%
    prev_vol_ratio = prev_vol / prev_max_vol_20d.replace(0, float("nan"))
    is_suffocation_bar = prev_vol_ratio < cfg.max20_volume_ratio

    # === MA20 上彎: must be upward (扣抵預判 — 比 slope 提早 1-2 天) ===
    # Source: course_principles.md §16 — 「必要：月線上彎」
    #         K 線力量入門 §季線扣抵原理 — 用扣抵 close 預判明日 MA 方向
    if "ma20_will_rise" in df.columns:
        ma20_up = df["ma20_will_rise"].fillna(False)
        ma20_slope_series = df.get(
            "ma20_rolloff_pressure", df.get("ma20_slope", df.get("ma20_slope_5d"))
        )
    elif "ma20_slope" in df.columns:
        ma20_slope_series = df["ma20_slope"]
        ma20_up = ma20_slope_series.fillna(0) > 0
    elif "ma20_slope_5d" in df.columns:
        ma20_slope_series = df["ma20_slope_5d"]
        ma20_up = ma20_slope_series.fillna(0) > 0
    else:
        raise KeyError(
            "None of 'ma20_will_rise', 'ma20_slope', 'ma20_slope_5d' found. "
            "Ensure add_zhuli_features() was called."
        )

    # === Breakout bar (today) ===
    bar_type = _classify_breakout_bar(df)
    is_valid_breakout_bar = bar_type != "invalid"

    # Volume must exceed the suffocation bar's volume
    vol_exceeds_prev = df["volume"] > prev_vol * cfg.breakout_volume_multiplier

    # === Liquidity filters ===
    # vol_ma20 may come from DB or from avg_volume_20 (kline.features).
    if "vol_ma20" in df.columns:
        avg_vol = df["vol_ma20"]
    elif "avg_volume_20" in df.columns:
        avg_vol = df["avg_volume_20"]
    else:
        avg_vol = pd.Series(float("nan"), index=df.index)

    liquid_enough = (
        avg_vol.fillna(0) >= cfg.min_avg_volume_20
    ) & (
        df["close"] >= cfg.min_close
    )

    # === Ideal MA alignment (boost / filter) ===
    ideal_align = df.get("ideal_ma_align", pd.Series(False, index=df.index))
    if cfg.ideal_ma_alignment_required:
        ma_ok = ideal_align.fillna(False)
    else:
        ma_ok = pd.Series(True, index=df.index)

    # === Combined signal mask ===
    signal_mask = (
        is_suffocation_bar.fillna(False)
        & ma20_up
        & is_valid_breakout_bar
        & vol_exceeds_prev.fillna(False)
        & liquid_enough
        & ma_ok
        & df["max_vol_20d"].notna()
        & df["ma20"].notna()
    )

    if not signal_mask.any():
        return _empty_output()

    hits = df[signal_mask].copy()
    hits_prev_vol = prev_vol[signal_mask]
    hits_prev_max = prev_max_vol_20d[signal_mask]
    hits_prev_date = prev_trade_date[signal_mask]
    hits_bar_type = bar_type[signal_mask]

    # === Scenario classification ===
    # A: price >= ma20 (on or above the monthly MA)
    # B: price < ma20 (below monthly MA, but MA still rising)
    scenario = pd.Series("A", index=hits.index)
    scenario = scenario.mask(hits["close"] < hits["ma20"], "B")

    # === Build output DataFrame ===
    out = pd.DataFrame(
        {
            "ticker": hits["ticker"].values,
            "signal_date": hits["trade_date"].values,
            "scenario": scenario.values,
            "suffocation_date": hits_prev_date.values,
            "suffocation_vol": hits_prev_vol.values,
            "suffocation_vol_ratio": (
                hits_prev_vol.values / hits_prev_max.values
            ),
            "breakout_close": hits["close"].values,
            "breakout_vol": hits["volume"].values,
            "breakout_bar_type": hits_bar_type.values,
            "ma20": hits["ma20"].values,
            "ma20_slope": ma20_slope_series[signal_mask].values,
            "ideal_ma_align": ideal_align[signal_mask].fillna(False).values,
            "stop_loss": hits["low"].values,
        }
    )

    return out.sort_values(
        ["signal_date", "ticker"], ascending=[False, True]
    ).reset_index(drop=True)


def _empty_output() -> pd.DataFrame:
    """Return empty DataFrame with correct output schema."""
    return pd.DataFrame(
        columns=[
            "ticker",
            "signal_date",
            "scenario",
            "suffocation_date",
            "suffocation_vol",
            "suffocation_vol_ratio",
            "breakout_close",
            "breakout_vol",
            "breakout_bar_type",
            "ma20",
            "ma20_slope",
            "ideal_ma_align",
            "stop_loss",
        ]
    )
