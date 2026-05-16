"""attack_intensity scoring factor tests."""
from __future__ import annotations

from kline.scoring.attack_intensity import score

from tests.conftest import make_bars


def _df_with_intensity(level):
    rows = [{"open": 100, "high": 102, "low": 99, "close": 100, "volume": 1000.0}]
    df = make_bars(rows)
    df["attack_intensity"] = [level]
    return df


def test_sunrise_attack_top_score():
    df = _df_with_intensity(4)
    assert score(df).iloc[0] == 20.0


def test_gap_attack_score():
    df = _df_with_intensity(3)
    assert score(df).iloc[0] == 15.0


def test_push_attack_score():
    df = _df_with_intensity(2)
    assert score(df).iloc[0] == 10.0


def test_wave_forward_lowest_attack_score():
    df = _df_with_intensity(1)
    assert score(df).iloc[0] == 5.0


def test_no_attack_zero():
    df = _df_with_intensity(0)
    assert score(df).iloc[0] == 0.0
