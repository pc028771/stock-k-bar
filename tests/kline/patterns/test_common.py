"""Tests for patterns/_common.py — bull/bear_exhaustion_context + is_power_bar gate."""
from __future__ import annotations

import pandas as pd
import pytest

from kline.features import add_features
from kline.patterns._common import (
    bear_exhaustion_context,
    bull_exhaustion_context,
    is_anomalous_volume,
    is_power_bar,
)

from tests.conftest import make_bars


def _build_bull_exhaust_frame():
    """80 bars: rising trend with close > prior_high_60 + sunrise pattern."""
    rows = []
    for i in range(80):
        low = 100.0 + i * 1.0
        rows.append({
            "open": low + 0.2,
            "high": low + 1.5,
            "low": low,
            "close": low + 1.2,
            "volume": 1000.0,
            "ma60": 90.0,
        })
    return add_features(make_bars(rows))


def _build_breakdown_frame():
    """130 bars with progressive new-low spikes + explicitly declining MA60."""
    rows = []
    for i in range(130):
        offset = i * 0.5
        ma60 = 100.0 - offset
        if i % 20 == 0 and i > 30:
            rows.append({
                "open": 95 - offset, "high": 96 - offset,
                "low": 88 - offset, "close": 90 - offset,
                "volume": 1000.0, "ma60": ma60,
            })
        else:
            rows.append({
                "open": 95 - offset, "high": 96 - offset,
                "low": 92 - offset, "close": 94 - offset,
                "volume": 1000.0, "ma60": ma60,
            })
    return add_features(make_bars(rows))


def test_is_power_bar_filters_by_body_pct():
    # 2026-06-03 refactor: is_power_bar is now implemented (body_pct >= 3% + color).
    # Build a frame with a single bull power bar (body > 5%) — should detect.
    rows = []
    for _ in range(20):
        rows.append({"open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000.0, "ma60": 100.0})
    # Bull power bar: open 100, close 106 → body +6%
    rows.append({"open": 100, "high": 107, "low": 99, "close": 106, "volume": 1000.0, "ma60": 100.0})
    df = add_features(make_bars(rows))
    sig = is_power_bar(df, "bull")
    assert sig.iloc[-1], "last bar should be classified as bull power bar"
    assert not sig.iloc[:-1].any(), "flat bars should not be power bars"


def test_bull_exhaustion_context_fires_in_rising_trend():
    df = _build_bull_exhaust_frame()
    ctx = bull_exhaustion_context(df)
    # Latter half should have a True somewhere — stock is in attack + near high
    assert ctx.iloc[60:].any(), "bull_exhaustion_context should fire during sustained rally"


def test_bull_exhaustion_context_false_in_flat_market():
    rows = [
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000.0, "ma60": 100.0}
        for _ in range(80)
    ]
    df = add_features(make_bars(rows))
    ctx = bull_exhaustion_context(df)
    assert not ctx.any(), "flat market should not trigger bull exhaustion"


def test_bear_exhaustion_context_fires_in_breakdown():
    df = _build_breakdown_frame()
    ctx = bear_exhaustion_context(df)
    assert ctx.iloc[80:].any(), "bear_exhaustion_context should fire during breakdown"


def test_bear_exhaustion_context_false_in_bull_trend():
    rows = [
        {"open": 100 + i * 0.3, "high": 102 + i * 0.3,
         "low": 98 + i * 0.3, "close": 101 + i * 0.3, "volume": 1000.0}
        for i in range(120)
    ]
    df = add_features(make_bars(rows))
    ctx = bear_exhaustion_context(df)
    assert not ctx.any()


# =====================================================================
# T_S1: is_anomalous_volume — C07 異常放量 [STUB-NEED-USER S1]
# =====================================================================


def _build_volume_frame(base_vol: float = 1000.0, spike_vol: float = None) -> pd.DataFrame:
    """70 bars: first 65 bars with base_vol, last bar optionally spike_vol."""
    rows = []
    for i in range(65):
        rows.append({
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
            "volume": base_vol, "ma60": 100.0,
        })
    final_vol = spike_vol if spike_vol is not None else base_vol
    rows.append({
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
        "volume": final_vol, "ma60": 100.0,
    })
    return add_features(make_bars(rows))


def test_s1_1_default_kj_matches_features_behavior():
    """T_S1.1: is_anomalous_volume(df) default K=2.0/J=1.5 與 features.py 結果一致。"""
    base_vol = 1000.0
    # spike > base * K=2.0 AND spike > base * J=1.5 → 3100 > 2000 AND 3100 > 1500 → True
    spike_vol = 3100.0
    df = _build_volume_frame(base_vol=base_vol, spike_vol=spike_vol)

    # features.py 計算的 is_anomalous_volume
    feature_result = df["is_anomalous_volume"]

    # _common.is_anomalous_volume 預設 K/J
    common_result = is_anomalous_volume(df)

    pd.testing.assert_series_equal(
        feature_result.reset_index(drop=True),
        common_result.reset_index(drop=True),
        check_names=False,
        obj="T_S1.1: default K/J must match features.py",
    )
    # Last bar should be True (spike triggers)
    assert common_result.iloc[-1], "spike bar should be anomalous with default K/J"


def test_s1_2_different_kj_yields_different_trigger():
    """T_S1.2: 不同 K/J 參數產生不同觸發結果。"""
    base_vol = 1000.0
    # Spike = 2200: triggers K=2.0 (2200 > 2000) but NOT K=3.0 (2200 < 3000)
    spike_vol = 2200.0
    df = _build_volume_frame(base_vol=base_vol, spike_vol=spike_vol)

    loose = is_anomalous_volume(df, K=2.0, J=1.5)
    strict = is_anomalous_volume(df, K=3.0, J=2.0)

    assert loose.iloc[-1], "K=2.0 should trigger for 2200 vs base 1000"
    assert not strict.iloc[-1], "K=3.0 should NOT trigger for 2200 vs base 1000"


def test_s1_3_missing_vol_ma60_falls_back_gracefully():
    """T_S1.3: df 無 vol_ma_60 欄位時 helper 自行計算（fallback），不 raise。"""
    base_vol = 1000.0
    spike_vol = 3100.0
    df = _build_volume_frame(base_vol=base_vol, spike_vol=spike_vol)

    # Ensure vol_ma_60 / vol_max_60_prev are NOT pre-computed in df
    assert "vol_ma_60" not in df.columns, "frame should not have vol_ma_60 pre-computed"
    assert "vol_max_60_prev" not in df.columns

    # Should compute internally without raising
    result = is_anomalous_volume(df)
    assert isinstance(result, pd.Series)
    assert result.iloc[-1], "spike should still be detected via fallback computation"
