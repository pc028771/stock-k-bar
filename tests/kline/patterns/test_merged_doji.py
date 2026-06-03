"""Tests for merged_doji pattern.

Course source: 明日 K 線 第 24 篇 / E9A6F935298C7C5C2E269AA952AA1BB2
INVENTORY §A01
"""
from __future__ import annotations

import pytest
import pandas as pd

from kline.features import add_features
from kline.patterns import merged_doji

from tests.conftest import make_bars


def _bull_rally_then(rows_after, n_priming: int = 80):
    """80 根上升 priming 棒 + 測試 rows。

    priming 末尾 close 約 180，確保 prior_high_60 被建立。
    """
    priming = []
    for i in range(n_priming):
        low = 100.0 + i * 1.0
        priming.append({
            "open": low + 0.2, "high": low + 1.5, "low": low,
            "close": low + 1.2, "volume": 1000.0, "ma60": 90.0,
        })
    return add_features(make_bars(priming + rows_after))


def test_merged_doji_positive():
    """正面案例：剛創新高 + 前根上影線 + 今根下影線 + 合併後為十字線。

    前根（D-1）：上影線主導（高點遠高於收盤）
    今根（D-0）：下影線主導（低點遠低於開盤），收盤回到 merged 中段

    合併後：
      merged_open  = D-1.open  ≈ 181.0
      merged_close = D-0.close ≈ 181.5
      merged_high  = max(184.5, 182.0) = 184.5
      merged_low   = min(180.0, 178.5) = 178.5

      range = 184.5 - 178.5 = 6.0
      body  = |181.0 - 181.5| = 0.5  → ratio = 0.5/6 ≈ 0.08  ≤ 0.25 ✓
      upper = 184.5 - max(181, 181.5) = 3.0  → 3/6 = 0.5 ≥ 0.2 ✓
      lower = min(181, 181.5) - 178.5 = 2.5  → 2.5/6 ≈ 0.42 ≥ 0.2 ✓
    """
    # priming 末尾：close = 180.2, high = 180.5（prior_high_60 ≈ 180.5）
    # D-1：前根上影線主導（紅 K，close > open 或不限色）
    d_minus_1 = {
        "open": 181.0, "high": 184.5, "low": 180.0, "close": 181.2,
        "volume": 1000.0, "ma60": 90.0,
    }
    # D-0：今根下影線主導（close 回到中段附近），創新高（close > 前日 prior_high_60）
    d_0 = {
        "open": 181.8, "high": 182.0, "low": 178.5, "close": 181.5,
        "volume": 1000.0, "ma60": 90.0,
    }
    df = _bull_rally_then([d_minus_1, d_0])
    sig = merged_doji.detect(df)
    assert sig.iloc[-1], (
        f"merged_doji should fire at last bar; tail = {sig.iloc[-5:].tolist()}"
    )


def test_merged_doji_negative_flat():
    """Flat market — 無創新高，不觸發。"""
    rows = [
        {"open": 100, "high": 101, "low": 99, "close": 100,
         "volume": 1000.0, "ma60": 100.0}
        for _ in range(80)
    ]
    df = add_features(make_bars(rows))
    assert not merged_doji.detect(df).any(), "flat market should not trigger merged_doji"


def test_merged_doji_negative_wrong_shadow_order():
    """負面案例：影線順序反向（前下影線、後上影線）→ 不觸發（課程明示退化）。

    前根（D-1）：下影線主導
    今根（D-0）：上影線主導

    INVENTORY §A01: 先下影線、後上影線退化為「上影線單獨判斷」，不觸發此 pattern。
    """
    d_minus_1 = {
        "open": 181.5, "high": 182.0, "low": 178.5, "close": 181.8,
        "volume": 1000.0, "ma60": 90.0,
    }
    d_0 = {
        "open": 181.5, "high": 184.5, "low": 181.0, "close": 181.3,
        "volume": 1000.0, "ma60": 90.0,
    }
    df = _bull_rally_then([d_minus_1, d_0])
    sig = merged_doji.detect(df)
    assert not sig.iloc[-1], (
        "wrong shadow order (down then up) should NOT trigger merged_doji"
    )


def test_merged_doji_negative_no_new_high():
    """負面案例：影線組合正確但不在剛創新高位置 → 不觸發。"""
    # 先建立高點然後大幅下跌，再出現十字線組合（位置不在創新高）
    priming = []
    for i in range(80):
        low = 100.0 + i * 1.0
        priming.append({
            "open": low + 0.2, "high": low + 1.5, "low": low,
            "close": low + 1.2, "volume": 1000.0, "ma60": 90.0,
        })
    # 大跌後出現十字線組合，但 close 遠低於 prior_high_60
    low_rows = [
        {"open": 120.0, "high": 121.0, "low": 115.0, "close": 117.0,
         "volume": 1000.0, "ma60": 90.0},
        # D-1: 上影線主導但位置不在創新高
        {"open": 117.0, "high": 121.0, "low": 116.0, "close": 117.2,
         "volume": 1000.0, "ma60": 90.0},
        # D-0: 下影線主導
        {"open": 117.5, "high": 118.0, "low": 113.0, "close": 117.3,
         "volume": 1000.0, "ma60": 90.0},
    ]
    df = add_features(make_bars(priming + low_rows))
    sig = merged_doji.detect(df)
    assert not sig.iloc[-1], "no-new-high position should NOT trigger merged_doji"


def test_merged_doji_detect_with_metadata_columns():
    """detect_with_metadata 回傳 merged_doji_high / merged_doji_low 欄位。"""
    d_minus_1 = {
        "open": 181.0, "high": 184.5, "low": 180.0, "close": 181.2,
        "volume": 1000.0, "ma60": 90.0,
    }
    d_0 = {
        "open": 181.8, "high": 182.0, "low": 178.5, "close": 181.5,
        "volume": 1000.0, "ma60": 90.0,
    }
    df = _bull_rally_then([d_minus_1, d_0])
    out = merged_doji.detect_with_metadata(df)
    assert "merged_doji" in out.columns
    assert "merged_doji_high" in out.columns
    assert "merged_doji_low" in out.columns

    if out["merged_doji"].iloc[-1]:
        assert out["merged_doji_high"].iloc[-1] == pytest.approx(
            max(d_minus_1["high"], d_0["high"]), rel=1e-6
        )
        assert out["merged_doji_low"].iloc[-1] == pytest.approx(
            min(d_minus_1["low"], d_0["low"]), rel=1e-6
        )
