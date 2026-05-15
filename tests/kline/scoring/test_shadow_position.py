"""shadow_position.score: position-based shadow scoring."""
from __future__ import annotations

from kline.scoring.shadow_position import score

from tests.conftest import make_bars


def _df_for_shadow(*, high, prior_high_60, upper_shadow_ratio,
                   overhead_layer, is_red):
    df = make_bars([{"open": 100, "high": high, "low": 99, "close": 100}])
    df["prior_high_60"] = [prior_high_60]
    df["upper_shadow_ratio"] = [upper_shadow_ratio]
    df["overhead_supply_layer"] = [overhead_layer]
    df["is_red"] = [is_red]
    return df


def test_upper_shadow_at_new_high_with_red_k_is_positive():
    df = _df_for_shadow(high=110, prior_high_60=100, upper_shadow_ratio=2.0,
                        overhead_layer=0, is_red=True)
    assert score(df).iloc[0] > 0


def test_upper_shadow_at_overhead_not_new_high_is_negative():
    df = _df_for_shadow(high=100, prior_high_60=105, upper_shadow_ratio=2.0,
                        overhead_layer=2, is_red=False)
    assert score(df).iloc[0] < 0


def test_upper_shadow_at_new_high_but_black_k_neutral():
    df = _df_for_shadow(high=110, prior_high_60=100, upper_shadow_ratio=2.0,
                        overhead_layer=0, is_red=False)
    # Course says attack shadow requires red K; black K with upper shadow alone
    # is neither attack nor pressure (assuming no overhead) -> 0
    assert score(df).iloc[0] == 0.0


def test_small_upper_shadow_below_threshold_is_neutral():
    df = _df_for_shadow(high=110, prior_high_60=100, upper_shadow_ratio=0.3,
                        overhead_layer=0, is_red=True)
    assert score(df).iloc[0] == 0.0
