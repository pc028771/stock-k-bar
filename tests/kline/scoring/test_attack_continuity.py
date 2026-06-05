"""attack_continuity.score: INVENTORY §C08 攻擊延續性打分."""
from __future__ import annotations

import pandas as pd
from kline.scoring.attack_continuity import score

from tests.conftest import make_bars
from kline.features import add_features


def _make_df_with_features(**col_overrides):
    """Helper: build a minimal df with required columns for attack_continuity."""
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(3)]
    df = make_bars(rows)
    df = add_features(df)
    for k, v in col_overrides.items():
        if isinstance(v, list):
            df[k] = v
        else:
            df[k] = v
    return df


def test_gap_attack_after_breakout_adds_one():
    """+1 when prev bar had is_just_broke_high=True and today opens above prev_high."""
    rows = [
        {"open": 100, "high": 105, "low": 99, "close": 104},
        {"open": 106, "high": 110, "low": 105, "close": 109},  # gap up above prev_high 105
    ]
    df = make_bars(rows)
    df = add_features(df)
    # Force is_just_broke_high on row 0 so the shift works on row 1
    df.loc[0, "is_just_broke_high"] = True
    # Force intent_zone_break=False, is_anomalous_volume=False, is_limit_up_locked=False
    df["intent_zone_break"] = False
    df["attack_intent_zone_high"] = [float("nan"), float("nan")]
    df["is_limit_up_locked"] = False
    out = score(df)
    # Row 1: gap_attack += 1; stayed_above: attack_intent_zone_high is NaN → 0
    assert out.iloc[1] >= 1


def test_intent_zone_break_subtracts_one():
    """-1 when intent_zone_break=True."""
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100}]
    df = make_bars(rows)
    df = add_features(df)
    df["intent_zone_break"] = [True]
    df["attack_intent_zone_high"] = [float("nan")]
    df["is_just_broke_high"] = [False]
    df["is_limit_up_locked"] = [False]
    df["is_anomalous_volume"] = [False]
    out = score(df)
    assert out.iloc[0] <= -1


def test_attack_cost_break_subtracts_one():
    """-1 when prev day was limit_up_locked and today close < prev_close."""
    rows = [
        {"open": 100, "high": 110, "low": 100, "close": 110},  # limit up locked
        {"open": 108, "high": 109, "low": 105, "close": 107},  # close < prev_close
    ]
    df = make_bars(rows)
    df = add_features(df)
    df.loc[0, "is_limit_up_locked"] = True
    df["intent_zone_break"] = [False, False]
    df["attack_intent_zone_high"] = [float("nan"), float("nan")]
    df["is_just_broke_high"] = [False, False]
    df["is_anomalous_volume"] = [False, False]
    out = score(df)
    assert out.iloc[1] <= -1


def test_no_signals_returns_zero_or_positive():
    """Neutral day: no gap attack, no intent break, no cost break."""
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100}]
    df = make_bars(rows)
    df = add_features(df)
    df["intent_zone_break"] = [False]
    df["attack_intent_zone_high"] = [float("nan")]
    df["is_just_broke_high"] = [False]
    df["is_limit_up_locked"] = [False]
    df["is_anomalous_volume"] = [False]
    out = score(df)
    # stayed_above: no intent zone (NaN) → 0; all others 0
    assert out.iloc[0] == 0.0
