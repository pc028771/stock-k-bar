"""Tests for xiaoge/scoring/screener.py — M1-M9, S1-S6 sub-detectors + combinators.

Course source: 權證小哥課程 ch12 (飆股口袋名單), ch13 (多策略交叉案例).
Reference: docs/權證小哥/籌碼技術分析/detector_spec.md §5.

課程原話 (verbatim):
> 「越多條件交集的選出來的股票越少，那選出來的股票越少呢，他的精準度會越高。」
>  (ch13 02:03–02:27)
> 「前十大主力買氣強 + 分點主力連續買超 + 波動上升且強勢 + KD 黃金交叉 →
>  超眾、亞光 兩檔後續沿上軌大漲。」 (ch13 案例)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from xiaoge.scoring.screener import (
    _build_features,
    detect_m1_top10_main_buying,
    detect_m2_max_broker_loading,
    detect_m3_main_buy_streak_n,
    detect_m4_foreign_buy_streak_n,
    detect_m5_invest_trust_buy_streak_n,
    detect_m6_volatility_rising_strong,
    detect_m7_break_20d_high,
    detect_m8_bb_open,
    detect_m9_bb_squeeze,
    detect_s1_top10_main_selling,
    detect_s2_max_broker_dumping,
    detect_s3_main_sell_streak_n,
    detect_s4_foreign_sell_streak_n,
    detect_s5_invest_trust_sell_streak_n,
    detect_s6_volatility_rising_weak,
    screen_long,
    screen_short,
)


# ---------------------------------------------------------------------------
# Fixture: a feature-complete DataFrame
# ---------------------------------------------------------------------------

def _build_test_df(n: int = 50, ticker: str = "A001") -> pd.DataFrame:
    """Build a synthetic DataFrame with all columns needed by screener."""
    dates = pd.bdate_range("2026-01-05", periods=n)
    idx = np.arange(n, dtype=float)
    close = 100.0 + idx * 0.5
    open_ = close * 0.99
    volume = 1000.0 + idx * 10.0

    ma5_vals  = pd.Series(close).rolling(5, min_periods=5).mean().values
    ma20_vals = pd.Series(close).rolling(20, min_periods=20).mean().values

    df = pd.DataFrame({
        "ticker":        ticker,
        "trade_date":    dates,
        "open":          open_,
        "high":          close * 1.02,
        "low":           open_  * 0.98,
        "close":         close,
        "volume":        volume,
        "ma5":           ma5_vals,
        "ma20":          ma20_vals,
        "bb_upper":      close * 1.05,
        "bb_mid":        close * 1.00,
        "bb_lower":      close * 0.95,
        "bb_width_pct":  5.0,           # narrow → squeeze-like
        "bb_in_squeeze": True,
        "main_force_1d": volume * 0.25,   # 25% daily buying
        "main_force_5d": volume * 0.30,   # positive 5-day buying
    })
    return df.reset_index(drop=True)


def _build_features_df(n: int = 50, ticker: str = "A001") -> pd.DataFrame:
    """Build df and run _build_features to add all derived columns."""
    df = _build_test_df(n, ticker)
    return _build_features(df)


# ===========================================================================
# M-series (多頭) sub-detector tests
# ===========================================================================

class TestM1TopMainBuying:
    """M1 — ch12 #1: 前 10 大主力買氣強."""

    def test_fires_when_main_strong_and_vol_high(self):
        df = _build_features_df()
        # main_force_5d = volume * 0.3; _vol_ma5 ≈ volume; ratio ≈ 0.3
        # After warmup, vol_ma5 ≥ 500 张 (1000+)
        df["main_force_5d"] = df["volume"] * 0.3
        sig = detect_m1_top10_main_buying(df, min_ratio=0.2, min_vol_ma5=500)
        assert sig.iloc[25:].any(), "ch12 #1: 主力買氣強 M1 應觸發"

    def test_no_fire_when_vol_ma5_too_low(self):
        df = _build_features_df()
        df["main_force_5d"] = df["volume"] * 0.3
        df["_vol_ma5"] = 100.0   # < min_vol_ma5=500
        sig = detect_m1_top10_main_buying(df, min_vol_ma5=500)
        assert not sig.any(), "ch12 #1: 5 日均量 < 500 張不應觸發"

    def test_no_fire_when_main_force_negative(self):
        df = _build_features_df()
        df["main_force_5d"] = -5_000.0
        sig = detect_m1_top10_main_buying(df)
        assert not sig.any(), "主力淨賣超 M1 不觸發"


class TestM2MaxBrokerLoading:
    """M2 — ch12 #2: 最大主力狂進貨."""

    def test_fires_when_large_single_day_buy(self):
        df = _build_features_df()
        df["main_force_1d"] = df["volume"] * 0.25   # 25% > 20% threshold
        df["volume"] = 1500.0   # > 1000 張 threshold
        sig = detect_m2_max_broker_loading(df, min_pct=0.20, min_volume=1000)
        assert sig.any(), "ch12 #2: 單日主力大買 ≥ 20% 成交量應觸發"

    def test_no_fire_below_pct_threshold(self):
        df = _build_features_df()
        df["main_force_1d"] = df["volume"] * 0.10   # 10% < 20%
        sig = detect_m2_max_broker_loading(df, min_pct=0.20)
        assert not sig.any(), "ch12 #2: 比例 < 20% 不觸發"

    def test_no_fire_below_volume_threshold(self):
        df = _build_features_df()
        df["main_force_1d"] = df["volume"] * 0.25
        df["volume"] = 500.0   # < 1000 張
        sig = detect_m2_max_broker_loading(df, min_volume=1000)
        assert not sig.any(), "ch12 #2: 成交量 < 1000 張不觸發"


class TestM3MainBuyStreak:
    """M3 — ch12 #3: 分點主力連續買超 N 天."""

    def test_fires_when_consecutive_buying(self):
        n = 20
        df = _build_test_df(n)
        df["main_force_1d"] = 500.0   # positive every day
        sig = detect_m3_main_buy_streak_n(df, n=5)
        assert sig.iloc[5:].any(), "ch12 #3: 連續 5 天買超應觸發 M3"

    def test_no_fire_when_interrupted(self):
        n = 20
        df = _build_test_df(n)
        df["main_force_1d"] = 500.0
        df.loc[df.index[15], "main_force_1d"] = -100.0  # interrupt at row 15
        sig = detect_m3_main_buy_streak_n(df, n=5)
        # Row 15 and 16-19 should not have 5-consecutive
        assert not sig.iloc[15:20].any(), "ch12 #3: 中斷連買後不應立刻觸發"

    def test_n_parameter_changes_result(self):
        n = 20
        df = _build_test_df(n)
        df["main_force_1d"] = 500.0
        sig_3 = detect_m3_main_buy_streak_n(df, n=3)
        sig_10 = detect_m3_main_buy_streak_n(df, n=10)
        assert sig_3.sum() >= sig_10.sum(), "n 越大觸發越少"


class TestM4M5ForeignInvestTrust:
    """M4/M5 — ch12 #4/#5: 外資/投信連續買超 (資料源待補)."""

    def test_m4_returns_false_when_column_missing(self):
        df = _build_test_df(20)
        # No foreign_net_1d column
        sig = detect_m4_foreign_buy_streak_n(df)
        assert not sig.any(), "ch12 #4: 無 foreign_net_1d 應全回傳 False"

    def test_m4_fires_when_column_present(self):
        df = _build_test_df(20)
        df["foreign_net_1d"] = 500.0   # positive every day
        sig = detect_m4_foreign_buy_streak_n(df, n=5)
        assert sig.iloc[5:].any(), "ch12 #4: 有 foreign_net_1d 且連續買 5 天應觸發"

    def test_m5_returns_false_when_column_missing(self):
        df = _build_test_df(20)
        sig = detect_m5_invest_trust_buy_streak_n(df)
        assert not sig.any(), "ch12 #5: 無 invest_trust_net_1d 應全回傳 False"


class TestM6VolatilityRisingStrong:
    """M6 — ch12 #6: 波動上升且強勢."""

    def test_fires_when_volatility_rising_and_above_ma5(self):
        df = _build_features_df(n=40)
        # Force all conditions True
        df["volatility_rising"] = True
        df["_ma5_rising"] = True
        df["_above_ma5"] = True
        sig = detect_m6_volatility_rising_strong(df)
        assert sig.all(), "ch12 #6: 波動上升 + 5MA 上揚 + 站上 5MA 全部 True 應全觸發"

    def test_no_fire_when_below_ma5(self):
        df = _build_features_df(n=40)
        df["volatility_rising"] = True
        df["_ma5_rising"] = True
        df["_above_ma5"] = False   # below ma5
        sig = detect_m6_volatility_rising_strong(df)
        assert not sig.any(), "ch12 #6: 低於 5MA 不應觸發 M6"


class TestM7Break20dHigh:
    """M7 — ch12 #7: 創 20 日新高."""

    def test_fires_when_is_20d_high_true(self):
        df = _build_features_df(n=30)
        df["is_20d_high"] = False
        df.loc[df.index[-1], "is_20d_high"] = True
        sig = detect_m7_break_20d_high(df)
        assert sig.iloc[-1], "ch12 #7: is_20d_high=True 應觸發 M7"

    def test_no_fire_when_not_high(self):
        df = _build_features_df(n=30)
        df["is_20d_high"] = False
        sig = detect_m7_break_20d_high(df)
        assert not sig.any(), "ch12 #7: 未創新高不觸發"


class TestM8BbOpen:
    """M8 — ch12 #8: 布林軌道打開."""

    def test_fires_when_bb_upper_rising(self):
        df = _build_features_df(n=30)
        df["_bb_upper_rising"] = True
        sig = detect_m8_bb_open(df)
        assert sig.all(), "ch12 #8: bb_upper 斜率正應觸發 M8"

    def test_no_fire_when_bb_upper_flat(self):
        df = _build_features_df(n=30)
        df["_bb_upper_rising"] = False
        sig = detect_m8_bb_open(df)
        assert not sig.any()


class TestM9BbSqueeze:
    """M9 — ch12 #9: 布林軌道壓縮."""

    def test_fires_when_bb_in_squeeze(self):
        df = _build_features_df(n=30)
        df["bb_in_squeeze"] = True
        sig = detect_m9_bb_squeeze(df)
        assert sig.all(), "ch12 #9: bb_in_squeeze=True 應觸發 M9"

    def test_fires_via_bb_width_pct_when_squeeze_absent(self):
        df = _build_features_df(n=30)
        df = df.drop(columns=["bb_in_squeeze"])
        df["bb_width_pct"] = 8.0   # < 10 default threshold
        sig = detect_m9_bb_squeeze(df, squeeze_threshold=10.0)
        assert sig.all(), "ch12 #9: bb_width_pct < 10 應觸發 (fallback)"


# ===========================================================================
# S-series (空頭) sub-detector tests
# ===========================================================================

class TestS1TopMainSelling:
    """S1 — ch12 空頭 #1."""

    def test_fires_when_main_selling_strong(self):
        df = _build_features_df()
        df["main_force_5d"] = -df["volume"] * 0.3  # strong selling
        sig = detect_s1_top10_main_selling(df, min_ratio=0.2, min_vol_ma5=500)
        assert sig.iloc[25:].any(), "ch12 空頭 #1: 主力賣壓重應觸發 S1"

    def test_no_fire_when_main_buying(self):
        df = _build_features_df()
        df["main_force_5d"] = df["volume"] * 0.3
        sig = detect_s1_top10_main_selling(df)
        assert not sig.any(), "主力淨買超時 S1 不觸發"


class TestS2MaxBrokerDumping:
    """S2 — ch12 空頭 #2."""

    def test_fires_when_large_single_day_sell(self):
        df = _build_features_df()
        df["main_force_1d"] = -df["volume"] * 0.25
        df["volume"] = 1500.0
        sig = detect_s2_max_broker_dumping(df, min_pct=0.20, min_volume=1000)
        assert sig.any(), "ch12 空頭 #2: 大賣超 20% 成交量應觸發 S2"

    def test_no_fire_when_buying(self):
        df = _build_features_df()
        df["main_force_1d"] = df["volume"] * 0.25  # positive
        sig = detect_s2_max_broker_dumping(df)
        assert not sig.any()


class TestS3MainSellStreak:
    """S3 — ch12 空頭 #3."""

    def test_fires_consecutive_selling(self):
        df = _build_test_df(20)
        df["main_force_1d"] = -500.0
        sig = detect_s3_main_sell_streak_n(df, n=5)
        assert sig.iloc[5:].any(), "ch12 空頭 #3: 連續 5 天賣超應觸發"

    def test_no_fire_when_interrupted(self):
        df = _build_test_df(20)
        df["main_force_1d"] = -500.0
        df.loc[df.index[10], "main_force_1d"] = 100.0  # interrupt
        sig = detect_s3_main_sell_streak_n(df, n=5)
        assert not sig.iloc[10:15].any()


class TestS4S5ForeignInvestTrustShort:
    """S4/S5 — ch12 空頭 #4/#5: 無欄位時全 False."""

    def test_s4_returns_false_when_column_missing(self):
        df = _build_test_df(20)
        sig = detect_s4_foreign_sell_streak_n(df)
        assert not sig.any()

    def test_s5_returns_false_when_column_missing(self):
        df = _build_test_df(20)
        sig = detect_s5_invest_trust_sell_streak_n(df)
        assert not sig.any()


class TestS6VolatilityRisingWeak:
    """S6 — ch12 空頭 #6: 波動上升且弱勢 + 創 20 日低."""

    def test_fires_when_all_conditions_weak(self):
        df = _build_features_df(n=40)
        df["volatility_rising"] = True
        df["_ma5_rising"] = False
        df["_above_ma5"] = False
        df["close"] = df["ma5"] - 1.0   # below ma5
        df["is_20d_low"] = True
        sig = detect_s6_volatility_rising_weak(df)
        assert sig.any(), "ch12 空頭 #6: 弱勢+創 20 日低應觸發 S6"

    def test_no_fire_when_ma5_rising(self):
        df = _build_features_df(n=40)
        df["volatility_rising"] = True
        df["_ma5_rising"] = True   # NOT falling → S6 requires ma5 NOT rising
        df["is_20d_low"] = True
        sig = detect_s6_volatility_rising_weak(df)
        assert not sig.any(), "5MA 上揚時 S6 不觸發"


# ===========================================================================
# Combinator tests: screen_long / screen_short
# ===========================================================================

class TestScreenLong:
    def test_returns_dataframe(self):
        df = _build_features_df(n=40)
        df["is_20d_high"] = True
        result = screen_long(df, strategies=["M7"], min_score=1)
        assert isinstance(result, pd.DataFrame), "screen_long 必須回傳 DataFrame"

    def test_required_columns_in_result(self):
        df = _build_features_df(n=40)
        df["is_20d_high"] = True
        result = screen_long(df, strategies=["M7"], min_score=1)
        for col in ["ticker", "trade_date", "score", "hit_strategies"]:
            assert col in result.columns, f"screen_long 結果欄位缺 {col}"

    def test_min_score_filters_correctly(self):
        df = _build_features_df(n=40)
        # Force M8 and M9 both True (bb_upper_rising + squeeze)
        df["_bb_upper_rising"] = True
        df["bb_in_squeeze"] = True
        result_2 = screen_long(df, strategies=["M8", "M9"], min_score=2)
        result_1 = screen_long(df, strategies=["M8", "M9"], min_score=1)
        assert len(result_2) <= len(result_1), "min_score=2 篩出的列應 ≤ min_score=1"

    def test_invalid_strategy_raises(self):
        df = _build_features_df(n=20)
        with pytest.raises(ValueError, match="Unknown long strategies"):
            screen_long(df, strategies=["M99"], min_score=1)

    def test_score_equals_number_of_hits(self):
        df = _build_features_df(n=40)
        df["_bb_upper_rising"] = True
        df["bb_in_squeeze"] = True
        result = screen_long(df, strategies=["M8", "M9"], min_score=2)
        if len(result) > 0:
            assert (result["score"] >= 2).all(), "score 應 ≥ min_score=2"

    def test_hit_strategies_contains_codes(self):
        df = _build_features_df(n=40)
        df["_bb_upper_rising"] = True
        result = screen_long(df, strategies=["M8"], min_score=1)
        if len(result) > 0:
            assert result["hit_strategies"].iloc[0].startswith("M8"), (
                "hit_strategies 應包含觸發的策略代碼"
            )

    def test_multi_strategy_score_sums_correctly(self):
        df = _build_features_df(n=40)
        # Force all of M7, M8, M9 to fire
        df["is_20d_high"] = True
        df["_bb_upper_rising"] = True
        df["bb_in_squeeze"] = True
        result = screen_long(df, strategies=["M7", "M8", "M9"], min_score=3)
        if len(result) > 0:
            assert (result["score"] == 3).all(), "3 策略全觸發 score 應等於 3"


class TestScreenShort:
    def test_returns_dataframe(self):
        df = _build_features_df(n=40)
        df["main_force_5d"] = -df["volume"] * 0.3
        result = screen_short(df, strategies=["S1"], min_score=1)
        assert isinstance(result, pd.DataFrame)

    def test_invalid_strategy_raises(self):
        df = _build_features_df(n=20)
        with pytest.raises(ValueError, match="Unknown short strategies"):
            screen_short(df, strategies=["S99"], min_score=1)

    def test_min_score_filter_short(self):
        df = _build_features_df(n=40)
        df["main_force_1d"] = -df["volume"] * 0.25
        df["volume"] = 1500.0
        df["main_force_5d"] = -df["volume"] * 0.3
        result_2 = screen_short(df, strategies=["S1", "S2"], min_score=2)
        result_1 = screen_short(df, strategies=["S1", "S2"], min_score=1)
        assert len(result_2) <= len(result_1)
