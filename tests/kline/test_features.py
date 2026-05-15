"""features.add_features: derives all columns per spec §3.2."""
from __future__ import annotations

import pandas as pd
from kline.features import add_features

from tests.conftest import make_bars


def test_basic_derived_columns():
    rows = [
        {"open": 100, "high": 105, "low": 99,  "close": 104, "volume": 1000},
        {"open": 104, "high": 110, "low": 103, "close": 109, "volume": 2000},
        {"open": 109, "high": 112, "low": 105, "close": 106, "volume": 1500},
    ]
    df = add_features(make_bars(rows))

    # prev_*
    assert pd.isna(df.loc[0, "prev_close"])
    assert df.loc[1, "prev_close"] == 104
    assert df.loc[2, "prev_low"] == 103

    # body_pct
    assert abs(df.loc[0, "body_pct"] - 0.04) < 1e-9  # |104-100|/100

    # close_pos
    assert abs(df.loc[0, "close_pos"] - (104 - 99) / (105 - 99)) < 1e-9

    # is_red / is_black
    assert df.loc[0, "is_red"]
    assert df.loc[2, "is_black"]

    # is_doji: body_pct <= 0.006 and range_pct >= 0.015
    # row 0: body 0.04, range 0.06 — not doji
    assert not df.loc[0, "is_doji"]


def test_groupby_ticker_does_not_leak():
    rows_a = [{"open": 100, "high": 105, "low": 99, "close": 104, "volume": 1000} for _ in range(3)]
    rows_b = [{"open": 50, "high": 52, "low": 49, "close": 51, "volume": 500} for _ in range(3)]
    df_a = make_bars(rows_a, ticker="A")
    df_b = make_bars(rows_b, ticker="B")
    combined = pd.concat([df_a, df_b]).reset_index(drop=True)
    out = add_features(combined)

    # B's first row prev_close should be NaN, not leak from A
    b_first = out[out["ticker"] == "B"].iloc[0]
    assert pd.isna(b_first["prev_close"])


def test_prior_high_60_uses_shifted_window():
    # 65 bars, ascending close — prior_high_60 at row 64 = high of row 4
    rows = [{"open": float(i), "high": float(i + 1),
             "low": float(i - 1), "close": float(i + 0.5),
             "volume": 1000.0} for i in range(100, 165)]
    df = add_features(make_bars(rows))
    # prior_high_60 at index 64 = max(high[4:64]) = high at index 63 = 164
    assert df.loc[64, "prior_high_60"] == 164.0


def test_doji_detected_when_body_tiny_and_range_large():
    rows = [{"open": 100.0, "high": 102.0, "low": 98.0, "close": 100.3, "volume": 1000}]
    df = add_features(make_bars(rows))
    # body_pct = 0.3/100 = 0.003 (<= 0.006), range_pct = 4/100 = 0.04 (>= 0.015)
    assert df.loc[0, "is_doji"]


def test_prior_low_20_uses_shifted_window():
    # 25 bars with ascending lows (low[i] = i).  At row 24, prior_low_20 is
    # min(low[4:24]) = low[4] = 4.0 — today (row 24) must NOT be included.
    rows = [
        {
            "open": float(i + 1), "high": float(i + 2),
            "low": float(i), "close": float(i + 0.5), "volume": 1000.0,
        }
        for i in range(25)
    ]
    df = add_features(make_bars(rows))
    # row 19: shift(1) covers rows 0-18 (19 values) → below min_periods=20
    assert pd.isna(df.loc[19, "prior_low_20"])
    assert df.loc[24, "prior_low_20"] == 4.0


def test_avg_volume_20_excludes_today():
    # 21 bars: first 20 bars volume=1000, bar 21 volume=2000.
    # avg_volume_20[20] = mean(volume[0:20]) = 1000  →  volume_ratio = 2.0
    base = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0}
    rows = [base.copy() for _ in range(20)]
    rows.append({**base, "volume": 2000.0})
    df = add_features(make_bars(rows))
    assert pd.isna(df.loc[19, "avg_volume_20"])  # needs 20 prior bars, row 19 has only 19
    assert df.loc[20, "avg_volume_20"] == 1000.0
    assert abs(df.loc[20, "volume_ratio"] - 2.0) < 1e-9


def test_shadow_metrics_on_red_and_black_k():
    rows = [
        # Red K: close > open
        {"open": 100.0, "high": 108.0, "low": 98.0, "close": 105.0, "volume": 1000.0},
        # Black K: close < open
        {"open": 105.0, "high": 108.0, "low": 97.0, "close": 100.0, "volume": 1000.0},
    ]
    df = add_features(make_bars(rows))

    # Red K (row 0): body=5, upper_shadow=108-105=3, lower_shadow=100-98=2
    assert df.loc[0, "upper_shadow"] == 3.0
    assert df.loc[0, "lower_shadow"] == 2.0
    assert abs(df.loc[0, "upper_shadow_ratio"] - 3.0 / 5.0) < 1e-9
    assert abs(df.loc[0, "lower_shadow_ratio"] - 2.0 / 5.0) < 1e-9

    # Black K (row 1): body=5, upper_shadow=108-105=3, lower_shadow=100-97=3
    assert df.loc[1, "upper_shadow"] == 3.0
    assert df.loc[1, "lower_shadow"] == 3.0
    assert abs(df.loc[1, "upper_shadow_ratio"] - 3.0 / 5.0) < 1e-9
    assert abs(df.loc[1, "lower_shadow_ratio"] - 3.0 / 5.0) < 1e-9


def test_ma60_slope_and_rolling_off():
    # 65 bars; ma60 defaults to close (i+1 for i in 0..64).
    # At row 64: slope_5d = ma60[64]/ma60[59] - 1 = 65/60 - 1 ≈ 0.08333...
    # At row 64: ma60_rolling_off_close = close[4] = 5.0
    rows = [
        {
            "open": float(i + 1), "high": float(i + 2),
            "low": float(i), "close": float(i + 1), "volume": 1000.0,
        }
        for i in range(65)
    ]
    df = add_features(make_bars(rows))
    expected_slope = 65.0 / 60.0 - 1.0
    assert abs(df.loc[64, "ma60_slope_5d"] - expected_slope) < 1e-9
    assert df.loc[64, "ma60_rolling_off_close"] == 5.0


def test_pre_breakout_trend_days_counts_prior_above_ma60():
    # 5 bars: close always above ma60. Today (row 4) should count 4 prior days
    # (bars 0-3 shifted by 1, rolling sum of 4 days capped at 20).
    rows = [
        {"open": 100.0, "high": 105.0, "low": 99.0, "close": 102.0, "volume": 1000.0}
        for _ in range(5)
    ]
    # ma60 defaults to close in make_bars, so close > ma60 is False (equal).
    # Override: set ma60 below close so all bars qualify.
    df = make_bars(rows)
    df["ma60"] = 90.0
    from kline.features import add_features as _add
    out = _add(df)
    # row 0: shift(1) gives NaN → 0 prior days above
    assert out.loc[0, "pre_breakout_trend_days"] == 0
    # row 4: 4 prior days (rows 0-3) all above ma60
    assert out.loc[4, "pre_breakout_trend_days"] == 4


def test_pre_breakout_trend_days_does_not_leak_across_tickers():
    # Ticker A: 5 bars all above ma60. Ticker B: 5 bars all below ma60.
    # B's pre_breakout_trend_days should remain 0 regardless of A's values.
    rows_a = [
        {"open": 100.0, "high": 105.0, "low": 99.0, "close": 102.0, "volume": 1000.0}
        for _ in range(5)
    ]
    rows_b = [
        {"open": 100.0, "high": 105.0, "low": 99.0, "close": 102.0, "volume": 1000.0}
        for _ in range(5)
    ]
    df_a = make_bars(rows_a, ticker="A")
    df_a["ma60"] = 90.0  # close > ma60

    df_b = make_bars(rows_b, ticker="B")
    df_b["ma60"] = 110.0  # close < ma60

    combined = pd.concat([df_a, df_b]).reset_index(drop=True)
    from kline.features import add_features as _add
    out = _add(combined)

    b_rows = out[out["ticker"] == "B"]
    assert (b_rows["pre_breakout_trend_days"] == 0).all()


def test_overhead_supply_layer_nan_before_history():
    # With fewer than 20 bars, overhead_supply_layer should be NaN.
    rows = [
        {"open": 100.0, "high": 105.0, "low": 99.0, "close": 102.0, "volume": 1000.0}
        for _ in range(10)
    ]
    df = add_features(make_bars(rows))
    # All rows have cumcount < 20, so all should be NaN.
    assert df["overhead_supply_layer"].isna().all()


def test_overhead_supply_layer_counts_peaks_above_close():
    # Build a bar series with a clear swing high well above later closes.
    # 30 bars: first 10 bars have high=200 (much higher than later closes of ~102),
    # then 20 bars with low close ~102. The 5-bar-local-max peak detection should
    # mark the high-bars as peaks; overhead_supply_layer at the end should be > 0.
    high_rows = [
        {"open": 190.0, "high": 200.0, "low": 188.0, "close": 195.0, "volume": 1000.0}
        for _ in range(10)
    ]
    low_rows = [
        {"open": 100.0, "high": 105.0, "low": 99.0, "close": 102.0, "volume": 1000.0}
        for _ in range(20)
    ]
    df = add_features(make_bars(high_rows + low_rows))
    # Last row: 20th bar in the low section (index 29), cumcount >= 20.
    last = df.iloc[-1]
    assert not pd.isna(last["overhead_supply_layer"])
    # There must be at least some peaks from the high section above close=102.
    assert last["overhead_supply_layer"] > 0
