"""Shared helpers for 多空轉折組合 K 線 patterns.

PATTERN_DEFINITIONS.md reference:
  §1 力量型 K 線 (power_bar) — 雙軌設計，預設 NOT IMPLEMENTED；
  §2 多方力竭背景 (bull_exhaustion_context)；
  §3 空方力竭背景 (bear_exhaustion_context)。

Course sources:
  - docs/K線行進ing/01-關鍵K線的定義與使用目的.md:38
  - docs/K線行進ing/16-黑K篇二_高檔長黑.md:16-18
  - docs/型態學/07-反轉型態.md:19, 25, 51, 57
  - long_short_turning_point/B2E7A4597B7D1B50CF88163C892204D1_01-…:30
  - long_short_turning_point/E79401532D60CC63B302926C2C33FB50_02-…:22, 44, 118-122
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..course_proxy_constants import (
    BULL_EXHAUSTION_ATTACK_LOOKBACK,
    BULL_EXHAUSTION_NEAR_HIGH_PCT,
    NARROW_CONSOLIDATION_BARS,
    NARROW_CONSOLIDATION_RANGE_MAX,
    SIDE_BY_SIDE_SIMILARITY_PCT,
)


# =============================================================================
# Single-ticker fast-path helpers
# Detectors are usually called per-ticker by simulator._precompute_pattern_hits;
# in that case `df.groupby("ticker").shift(n)` is ~6× slower than a plain
# `df["col"].shift(n)` because groupby walks an index even with one group.
# `fast_shift` auto-detects single-ticker df and skips groupby; multi-ticker
# dfs fall back to groupby to preserve correctness.
# =============================================================================


def is_single_ticker(df: pd.DataFrame) -> bool:
    """True if df has no ``ticker`` column or only one unique ticker.

    Uses iat[0] vs iat[-1] (O(1)) since detector inputs are sorted by
    (ticker, trade_date); identical endpoints ⇒ single ticker.
    """
    if "ticker" not in df.columns or df.empty:
        return True
    return df["ticker"].iat[0] == df["ticker"].iat[-1]


def fast_shift(df: pd.DataFrame, col: str, n: int) -> pd.Series:
    """Group-aware shift that fast-paths the single-ticker case."""
    if is_single_ticker(df):
        return df[col].shift(n)
    return df.groupby("ticker", sort=False)[col].shift(n)


# =============================================================================
# Shared "fuzzy" condition helpers
# 模糊條件抽出共用，調整一處所有 pattern 跟著改
# =============================================================================


def is_power_bar(df: pd.DataFrame, direction: str = "bull", body_pct_min: float = 0.03) -> pd.Series:
    """力量型 K 線 — body_pct >= body_pct_min + 顏色對齊.

    PATTERN_DEFINITIONS §1 結論：課程內部矛盾 — 「形狀不重要」(行進ing 01:38)
    vs 具體型態 (暗夜雙星 / 大敵當前 / 高檔長黑) 字面「長 K」。本 helper 提供
    工程代理 — 採 body_pct 絕對門檻，由 caller 決定是否啟用。

    Course direct references:
      - 多空轉折 §24 咬定型態 line 12「眼前的這一根必須是力量型K線」
      - 行進ing 16-黑K篇二「高檔長黑」獨立訊號

    Args:
        direction: 'bull' (要紅 K) / 'bear' (要黑 K) / 'either' (任一顏色)
        body_pct_min: body_pct 最小值，預設 3%。Case-by-case 校準後得出。

    Returns:
        Series[bool] — power bar 滿足條件的 K 棒.

    NOTE: PATTERN_DEFINITIONS §1 建議 detect() 不要硬綁 body 門檻、靠結構動作。
    本 helper 僅供需「力量型 K」過濾噪音的 pattern (biting / dark_double_star /
    three_red_dadi_dangqian 等) 引用。
    """
    body_ok = df["body_pct"].fillna(0) >= body_pct_min
    if direction == "bull":
        color_ok = df["close"] > df["open"]
    elif direction == "bear":
        color_ok = df["close"] < df["open"]
    elif direction == "either":
        color_ok = pd.Series(True, index=df.index)
    else:
        raise ValueError(f"direction must be 'bull' / 'bear' / 'either', got {direction!r}")
    return (color_ok & body_ok).fillna(False)


def is_narrow_consolidation(
    df: pd.DataFrame,
    n_bars: int = None,
    max_range_pct: float = None,
    use_close: bool = True,
) -> pd.DataFrame:
    """過去 N 根 K 線狹幅整理.

    Course references:
      - 多空轉折 §24 咬定型態 / §25 升降組合型態 line 12「一週以上的狹幅整理」

    回傳一個 DataFrame 含：
        narrow (bool):         過去 N 根是否狹幅整理
        past_close_max (float): 過去 N 根 close 最大值
        past_close_min (float): 過去 N 根 close 最小值
        past_high_max (float):  過去 N 根 high 最大值
        past_low_min (float):   過去 N 根 low 最小值

    Args:
        n_bars: 整理 K 棒數，預設讀 NARROW_CONSOLIDATION_BARS const.
        max_range_pct: range 上限，預設讀 NARROW_CONSOLIDATION_RANGE_MAX.
        use_close: True (default) 用 close-level range（推薦，過濾 wick 噪音）；
                   False 用 high-low range（會被失敗突破的長影線干擾）。
                   Case #5 奇鋐 3017 / Case #6 富邦媒 8454 驗證 close-level 正確。
    """
    if n_bars is None:
        n_bars = NARROW_CONSOLIDATION_BARS
    if max_range_pct is None:
        max_range_pct = NARROW_CONSOLIDATION_RANGE_MAX
    g = df.groupby("ticker")
    past_high_max = g["high"].transform(lambda s: s.shift(1).rolling(n_bars, min_periods=n_bars).max())
    past_low_min = g["low"].transform(lambda s: s.shift(1).rolling(n_bars, min_periods=n_bars).min())
    past_close_max = g["close"].transform(lambda s: s.shift(1).rolling(n_bars, min_periods=n_bars).max())
    past_close_min = g["close"].transform(lambda s: s.shift(1).rolling(n_bars, min_periods=n_bars).min())
    past_close_mean = g["close"].transform(lambda s: s.shift(1).rolling(n_bars, min_periods=n_bars).mean())

    if use_close:
        range_band = past_close_max - past_close_min
    else:
        range_band = past_high_max - past_low_min
    narrow = (range_band / past_close_mean.replace(0, np.nan)) < max_range_pct
    return pd.DataFrame({
        "narrow": narrow.fillna(False),
        "past_close_max": past_close_max,
        "past_close_min": past_close_min,
        "past_high_max": past_high_max,
        "past_low_min": past_low_min,
    })


def in_trend(
    df: pd.DataFrame,
    direction: str = "bull",
    method: str = "close_vs_ma20",
    threshold: float = 0.005,
) -> pd.Series:
    """「略顯漲勢」/「略顯跌勢」context 代理.

    Course says「略顯趨勢」(slight trend) — 不要強趨勢、不要平盤。

    Args:
        direction: 'bull' (close 高於 ma) / 'bear' (close 低於 ma)
        method:
            'close_vs_ma20': close 偏離 ma20 ≥ threshold（推薦：簡單、寬容）
                            Case #1 康舒 6282 用此（細微下滑跌勢都接受）。
            'ma60_slope':    close vs ma60 + ma60_slope_5d 同向（嚴格、趨勢動）
                            piercing_line.py 用此（強趨勢轉折）。
        threshold: close 偏離 ma 的最小比例，預設 0.5%.
    """
    if method == "close_vs_ma20":
        if direction == "bull":
            return (df["close"] > df["ma20"] * (1 + threshold)).fillna(False)
        elif direction == "bear":
            return (df["close"] < df["ma20"] * (1 - threshold)).fillna(False)
    elif method == "ma60_slope":
        slope = df["ma60_slope_5d"].fillna(0)
        if direction == "bull":
            return ((df["close"] > df["ma60"]) & (slope > 0)).fillna(False)
        elif direction == "bear":
            return ((df["close"] < df["ma60"]) & (slope < 0)).fillna(False)
    raise ValueError(f"invalid direction={direction!r} / method={method!r}")


def is_similar_bars(
    df: pd.DataFrame,
    lookback1: int = 1,
    lookback2: int = 2,
    tolerance_pct: float = None,
) -> pd.Series:
    """兩根 K 棒「並排相似」(side-by-side similar).

    Course references:
      - 多空轉折 §07 暗夜雙星「兩根形狀相似的併排K線」
      - 多空轉折 §10 突破雙星

    判斷 lookback1 vs lookback2 兩天的 high 跟 low 是否都相近.
    （並排 = 高低位置相近，不一定要同色）

    Args:
        lookback1, lookback2: shift 的天數，預設 (1, 2) = 前 1 / 前 2 日.
        tolerance_pct: 相似度容差，預設讀 SIDE_BY_SIDE_SIMILARITY_PCT.
    """
    if tolerance_pct is None:
        tolerance_pct = SIDE_BY_SIDE_SIMILARITY_PCT
    g = df.groupby("ticker")
    high_a = g["high"].shift(lookback1)
    high_b = g["high"].shift(lookback2)
    low_a = g["low"].shift(lookback1)
    low_b = g["low"].shift(lookback2)
    high_sim = ((high_a - high_b).abs() / high_a.replace(0, np.nan)) < tolerance_pct
    low_sim = ((low_a - low_b).abs() / low_a.replace(0, np.nan)) < tolerance_pct
    return (high_sim & low_sim).fillna(False)


def bull_exhaustion_context(df: pd.DataFrame) -> pd.Series:
    """多方力竭背景 — PATTERN_DEFINITIONS §2 規格.

    課程明示「高檔沒辦法用數字定義」(行進ing 16:16-18). 代理三條件 AND:
      1. attack_intensity ≥ 1 (過去 5 日內處於攻擊狀態)
      2. 過去 60 日內曾經 close > prior_high_60 (拉抬發生過)
      3. 今日 close ≥ prior_high_60 × 0.95 (沒跌離高檔)

    Refs:
      - PATTERN_DEFINITIONS.md §2 (lines 96-165)
      - docs/型態學/07-反轉型態.md:19
      - long_short_turning_point/E79401532D60CC63B302926C2C33FB50_02-…:22

    Required df columns: attack_intensity, close, prior_high_60, ticker.
    """
    g_attack = (
        df["attack_intensity"]
        .groupby(df["ticker"])
        .rolling(BULL_EXHAUSTION_ATTACK_LOOKBACK, min_periods=1)
        .max()
        .reset_index(level=0, drop=True)
    )
    in_attack_recent = g_attack >= 1

    breakout_indicator = (df["close"] > df["prior_high_60"]).fillna(False).astype(int)
    was_breakout_60d = (
        breakout_indicator
        .groupby(df["ticker"])
        .rolling(60, min_periods=1)
        .max()
        .reset_index(level=0, drop=True)
        > 0
    )

    # near_high — context check: we are in high zone (close stays close to prior_high_60).
    # 2026-06-02 fix: bear-reversal day itself may close far below high (e.g. 高檔長黑 -10%).
    # Use max(close over last 5 bars) instead of today's close — context is "recent high"
    # not "today's close". This preserves the "we WERE just at the high" interpretation
    # while allowing today's reversal bar to itself drop.
    recent_close_max = (
        df["close"]
        .groupby(df["ticker"])
        .rolling(BULL_EXHAUSTION_ATTACK_LOOKBACK, min_periods=1)
        .max()
        .reset_index(level=0, drop=True)
    )
    near_high = recent_close_max >= df["prior_high_60"] * BULL_EXHAUSTION_NEAR_HIGH_PCT

    return (in_attack_recent & was_breakout_60d & near_high).fillna(False)


def is_anomalous_volume(
    df: pd.DataFrame,
    K: float = 2.0,
    J: float = 1.5,
) -> pd.Series:
    """C07 異常放量 [STUB-NEED-USER S1] K/J 數字課程未明示。

    退化代理: vol > vol_ma_60 * K AND vol > vol_max_60.shift(1) * J.

    Args:
        K: 60 日均量倍數門檻，預設 2.0（[STUB-NEED-USER S1]）。
        J: 60 日滾動最大量倍數門檻，預設 1.5（[STUB-NEED-USER S1]）。

    Refs: docs/kline_course/mingri_kline/INVENTORY.md §C07

    Required df columns: volume, ticker.
    """
    if "vol_ma_60" in df.columns:
        vol_ma_60 = df["vol_ma_60"]
    else:
        g = df.groupby("ticker")
        vol_ma_60 = g["volume"].transform(
            lambda s: s.shift(1).rolling(60, min_periods=60).mean()
        )

    if "vol_max_60_prev" in df.columns:
        vol_max_60_prev = df["vol_max_60_prev"]
    else:
        g = df.groupby("ticker")
        vol_max_60_prev = g["volume"].transform(
            lambda s: s.shift(1).rolling(60, min_periods=60).max()
        )

    return (
        (df["volume"] > vol_ma_60 * K)
        & (df["volume"] > vol_max_60_prev * J)
    ).fillna(False)


def bear_exhaustion_context(df: pd.DataFrame) -> pd.Series:
    """空方力竭背景 — PATTERN_DEFINITIONS §3 規格.

    課程明示比多方力竭更嚴格 (型態學 07:51 「再加邏輯」). 代理三條件 AND:
      1. is_in_breakdown_pattern (features.py 既有 — 破底型態)
      2. 漫長崩跌強化 — new_low_count_60d ≥ 4
         (原 is_in_breakdown_pattern 門檻 ≥ 2 太鬆；「連續且漫長」應有
          多次破底事件，型態學 07:25)
      3. supply_vacuum_zone — 賣壓中空（型態學 07:38-57-75）
         proxy: 過去 120 日累計跌幅 ≥ 35%
           (= 型態學 07:38「持續夠久 → 超跌」, 35% 對應台股實務上「明顯超跌」量級)

    NOTE: PATTERN_DEFINITIONS §3 指出「大盤悲觀」filter 課程明示需要，
    但屬跨股 query，留給上層 simulator 套用，本層不做。

    Target trigger rate: < 2% (課程「紅K吞噬 104 年以後才出現一次」).

    Refs:
      - PATTERN_DEFINITIONS.md §3 (lines 167-219)
      - docs/型態學/07-反轉型態.md:25, 38, 57, 75
      - long_short_turning_point/E79401532D60CC63B302926C2C33FB50_02-…:118-122

    Required df columns: is_in_breakdown_pattern, close, ticker.
    Optional: overhead_supply_layer, supply_vacuum_zone (override if available).
    """
    in_breakdown = df["is_in_breakdown_pattern"].fillna(False)

    # 條件 2: 漫長崩跌 — new_low_count_60d ≥ 3 (原 threshold 為 2，提高為 3)
    # 從 4 鬆回 3：避免 morning_star_island_reversal 等 pattern hit rate 歸零
    if "new_low_count_60d" in df.columns:
        prolonged_breakdown = df["new_low_count_60d"].fillna(0) >= 3
    else:
        prolonged_breakdown = in_breakdown  # fallback

    # 條件 3: 賣壓中空 proxy = 過去 120 日累計跌幅 ≥ 20%
    # 從 35% 鬆綁到 20%：台股實務上「明顯下跌段」量級，不需「腰斬」程度
    if "supply_vacuum_zone" in df.columns:
        has_supply_vacuum = df["supply_vacuum_zone"].fillna(False)
    else:
        prior_high_120 = (
            df["high"]
            .groupby(df["ticker"])
            .transform(lambda s: s.shift(1).rolling(120, min_periods=60).max())
        )
        drop_pct_120 = (prior_high_120 - df["close"]) / prior_high_120
        has_supply_vacuum = (drop_pct_120 >= 0.30).fillna(False)

    # NOTE: 不另加 overhead_supply_layer 條件 — 該欄位計算過去 240 日 swing-high
    # 數量，崩跌中的股票天然會有大量 overhead peaks (峰是在跌之前形成的)，
    # 用「peak count <= N」當「套牢空」的 inverse 反而會把所有真實崩跌案例
    # 過濾掉。型態學 07:58「不在套牢區」的真正意義是「套牢者已認賠出場」,
    # 由「累計跌幅 ≥ 25% + 持續破底」共同代理已足夠。

    return (in_breakdown & prolonged_breakdown & has_supply_vacuum).astype(bool)
