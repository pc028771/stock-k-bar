"""Tests for scripts/kline/scenarios/context.py — Task 1.5.

Coverage:
  T1.5.1  features.py 缺 attack_cost → ContextSnapshot.attack_cost = None + notes 有 warn
  T1.5.2  overrides 優先於 df 推算
  T1.5.3  完整 features → ContextSnapshot 滿值無 feature warn
  T1.5.4  ticker / today_date 不存在 → raise ValueError (fail loud)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.kline.scenarios.context import build_context_snapshot
from scripts.kline.scenarios._schema import ContextSnapshot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TODAY = "2026-06-01"
_TICKER = "2330"


def _make_df(
    ticker: str = _TICKER,
    today_date: str = _TODAY,
    n_bars: int = 10,
    extra_cols: dict | None = None,
) -> pd.DataFrame:
    """Minimal DataFrame with trade_date + ticker columns."""
    dates = pd.bdate_range(end=today_date, periods=n_bars, freq="B")
    df = pd.DataFrame({
        "ticker": ticker,
        "trade_date": dates.strftime("%Y-%m-%d"),
        "close": np.linspace(90.0, 100.0, n_bars),
        "open": np.linspace(89.0, 99.0, n_bars),
        "high": np.linspace(91.0, 101.0, n_bars),
        "low": np.linspace(88.0, 98.0, n_bars),
        "volume": 1_000_000,
        # sentinel col so advisor treats it as already-enriched
        "prev_close": np.linspace(89.0, 99.5, n_bars),
    })
    if extra_cols:
        for col, val in extra_cols.items():
            if isinstance(val, (list, np.ndarray)):
                df[col] = val
            else:
                df[col] = val
    return df


def _full_features_df(ticker: str = _TICKER, today_date: str = _TODAY) -> pd.DataFrame:
    """DataFrame with all ContextSnapshot features.py columns populated."""
    n = 10
    df = _make_df(ticker, today_date, n_bars=n)
    df["attack_cost"] = 95.0
    df["attack_intent_zone_high"] = 102.0
    df["attack_intent_zone_low"] = 98.0
    df["defensive_low"] = 88.0
    df["ma5_will_rise"] = True
    df["ma10_will_rise"] = True
    df["ma20_will_rise"] = False
    df["ma60_will_rise"] = True
    df["is_just_broke_high"] = False
    df["is_limit_up_locked"] = False
    df["is_anomalous_volume"] = False
    return df


# ---------------------------------------------------------------------------
# T1.5.1 — missing attack_cost → None + warn
# ---------------------------------------------------------------------------

def test_t151_missing_attack_cost_is_none_with_warn():
    """T1.5.1: features.py 缺 attack_cost → ContextSnapshot.attack_cost = None + notes 有 warn."""
    df = _make_df()  # no attack_cost column
    snapshot, warns = build_context_snapshot(df, _TODAY, _TICKER)

    assert snapshot.attack_cost is None
    attack_warns = [w for w in warns if "attack_cost" in w]
    assert len(attack_warns) >= 1, f"Expected warn for attack_cost, got: {warns}"
    assert "WARN" in attack_warns[0]


# ---------------------------------------------------------------------------
# T1.5.2 — overrides take priority over df
# ---------------------------------------------------------------------------

def test_t152_overrides_beat_df():
    """T1.5.2: overrides 優先於 df 推算."""
    df = _make_df(extra_cols={"attack_cost": 50.0})  # df says 50.0
    overrides = {
        "attack_cost": 999.0,  # override says 999.0
        "ma5_will_rise": True,
    }
    snapshot, warns = build_context_snapshot(df, _TODAY, _TICKER, overrides=overrides)

    assert snapshot.attack_cost == 999.0, "override must win over df value"
    assert snapshot.ma5_will_rise is True
    # No warn for attack_cost since override provided it
    attack_warns = [w for w in warns if "attack_cost" in w]
    assert len(attack_warns) == 0, f"Should not warn for overridden field, got: {attack_warns}"


# ---------------------------------------------------------------------------
# T1.5.3 — full features → no feature-level warns
# ---------------------------------------------------------------------------

def test_t153_full_features_no_feature_warn():
    """T1.5.3: 完整 features → no WARN for feature fields."""
    df = _full_features_df()
    overrides: dict = {}
    snapshot, warns = build_context_snapshot(df, _TODAY, _TICKER, overrides=overrides)

    # features.py fields should all be populated
    assert snapshot.attack_cost == 95.0
    assert snapshot.attack_intent_zone_high == 102.0
    assert snapshot.defensive_low == 88.0
    assert snapshot.ma5_will_rise is True
    assert snapshot.ma20_will_rise is False

    # No feature-column warns (only Phase 4 integration pending warns allowed)
    feature_warns = [
        w for w in warns
        if any(f in w for f in [
            "attack_cost", "attack_intent_zone", "defensive_low",
            "ma5_will_rise", "ma10_will_rise", "ma20_will_rise", "ma60_will_rise",
            "is_just_broke_high", "is_limit_up_locked", "is_anomalous_volume",
        ])
    ]
    assert feature_warns == [], f"Unexpected feature warns: {feature_warns}"


# ---------------------------------------------------------------------------
# T1.5.4 — ticker / today_date not found → raise ValueError (fail loud)
# ---------------------------------------------------------------------------

def test_t154_unknown_ticker_raises():
    """T1.5.4a: ticker not in df → ValueError."""
    df = _make_df(ticker=_TICKER)
    with pytest.raises(ValueError, match="not found in bars_df"):
        build_context_snapshot(df, _TODAY, "9999")


def test_t154_unknown_date_raises():
    """T1.5.4b: today_date not in df for ticker → ValueError."""
    df = _make_df(ticker=_TICKER, today_date="2026-05-01")
    with pytest.raises(ValueError, match="not found for ticker"):
        build_context_snapshot(df, "2099-01-01", _TICKER)


# ---------------------------------------------------------------------------
# Extra: NaN in df treated as None + warn
# ---------------------------------------------------------------------------

def test_nan_treated_as_none():
    """NaN values in feature columns are treated as missing → None + warn."""
    import math
    df = _make_df(extra_cols={"attack_cost": float("nan")})
    snapshot, warns = build_context_snapshot(df, _TODAY, _TICKER)

    assert snapshot.attack_cost is None
    attack_warns = [w for w in warns if "attack_cost" in w]
    assert len(attack_warns) >= 1

