"""ma60_rolloff.score: §C10 季線下彎無紅K表態額外懲罰."""
from __future__ import annotations

from kline.scoring.ma60_rolloff import score

from tests.conftest import make_bars


def test_c10_ma60_about_to_fall_and_no_red_k_extra_penalty():
    """§C10: rolloff > close AND today is black K → extra -3 penalty."""
    rows = [{"open": 100, "high": 101, "low": 98, "close": 99}]
    df = make_bars(rows)
    df["ma60_rolling_off_close"] = [105.0]  # rolloff > close → MA60 falls
    df["is_red"] = [False]  # today is black (not red)
    out = score(df)
    # base: delta = 99-105 = -6, norm ≈ -0.6 → -6; extra = -3 → total ≈ -9
    assert out.iloc[0] < -6  # significantly below base-only


def test_c10_no_extra_penalty_when_red_k():
    """§C10: rolloff > close but today is red K → no extra penalty."""
    rows = [{"open": 100, "high": 103, "low": 99, "close": 102}]
    df = make_bars(rows)
    df["ma60_rolling_off_close"] = [105.0]
    df["is_red"] = [True]
    out_with_red = score(df)

    df["is_red"] = [False]
    out_without_red = score(df)

    # Without red K, extra penalty applies → lower score
    assert out_without_red.iloc[0] < out_with_red.iloc[0]


def test_c10_no_penalty_when_rolloff_below_close():
    """§C10: rolloff < close → MA60 rises → no extra penalty."""
    rows = [{"open": 100, "high": 101, "low": 99, "close": 104}]
    df = make_bars(rows)
    df["ma60_rolling_off_close"] = [90.0]  # rolloff < close → MA60 rises
    df["is_red"] = [False]
    out = score(df)
    # base is positive; no extra penalty
    assert out.iloc[0] > 0
