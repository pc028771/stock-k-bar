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


def test_is_pattern_breakout_fires_after_rising_low_consolidation():
    """
    60+ bars where lows are rising (>= 30 of 60 days higher_low) and highs are
    bounded (stable ceiling), then breakout → is_pattern_breakout = True.

    Course source: 型態學 05-三角收斂 + 14-推升攻擊
    低點漸漸墊高 + 上緣穩定 = 主力收貨三角收斂 → 突破上緣 = 起點
    """
    rows = []
    base_low = 95.0
    for i in range(61):
        # Lows climb steadily: every bar has a higher low → 60/60 days satisfy higher_low
        low = base_low + i * 0.1
        # Highs are stable / capped at 102 (the ceiling that will be broken)
        rows.append({
            "open": low + 2.0,
            "high": 102.0,
            "low": low,
            "close": low + 1.5,
            "volume": 1000.0,
            "ma60": 90.0,
        })
    # Breakout day: close > prior_high_60 (102) and above ma60 (90)
    rows.append({
        "open": 103.0,
        "high": 106.0,
        "low": 102.5,
        "close": 105.0,
        "volume": 2000.0,
        "ma60": 90.0,
    })

    df = add_features(make_bars(rows))
    # higher_low_count_60d at row 61 should be 60 (all 60 days in window have higher_low)
    assert df.loc[61, "higher_low_count_60d"] >= 30
    # upper_band_spread should be near 0 (highs were flat at 102)
    assert df.loc[61, "upper_band_spread_60d"] <= 0.05
    assert df.loc[61, "is_pattern_breakout"]


def test_is_pattern_breakout_does_not_fire_on_oscillating_stock():
    """
    60 bars with strongly oscillating lows (no rising trend) + breakout → False.

    Uses a 3-step down cycle: lows cycle 105→80→60→105→... so only 1/3 of transitions
    are higher_low (= 20 of 60 days), clearly below the 30-day threshold.
    """
    rows = []
    cycle_lows = [105.0, 80.0, 60.0]
    for i in range(60):
        lo = cycle_lows[i % 3]
        hi = lo + 40.0 if lo == 60.0 else lo + 15.0
        rows.append({"open": lo + 5.0, "high": hi, "low": lo, "close": lo + 3.0,
                     "volume": 1000.0, "ma60": 100.0})
    # Breakout day: close > prior_high_60
    rows.append({"open": 115.0, "high": 125.0, "low": 110.0, "close": 124.0,
                 "volume": 1000.0, "ma60": 100.0})

    df = add_features(make_bars(rows))
    # Only 20 of 60 days have higher_low — well below RISING_LOWS_MIN=30
    assert df.loc[60, "higher_low_count_60d"] < 30
    assert not df.loc[60, "is_pattern_breakout"]


def test_is_pattern_breakout_does_not_fire_on_sleeping_stock():
    """
    60+ bars of dead-flat price (low never moves) → higher_low_count_60d near 0 → False.

    Course: 「sleeping stocks」 have no rising lows and are not 主力收貨 patterns.
    The 60 consolidation bars all have the same low (98), so rising-lows count = 0.
    The breakout bar itself may add 1 (its low 101.5 > prev 98) but that's well below 30.
    """
    rows = [{"open": 100.0, "high": 102.0, "low": 98.0, "close": 100.0,
             "volume": 1000.0, "ma60": 90.0} for _ in range(60)]
    # Breakout day above the flat 102 ceiling
    rows.append({"open": 102.0, "high": 106.0, "low": 101.5, "close": 105.0,
                 "volume": 2000.0, "ma60": 90.0})

    df = add_features(make_bars(rows))
    # Dead flat: 60 bars at same low → higher_low_count well below 30
    assert df.loc[60, "higher_low_count_60d"] < 30
    assert not df.loc[60, "is_pattern_breakout"]


def test_is_pattern_breakout_does_not_fire_when_upper_band_unstable():
    """
    Lows rising BUT highs also rising significantly (ceiling not stable) → False.

    Course: 上緣穩定 is required. If the upper boundary keeps climbing, it's a
    trending stock, not a 三角收斂 accumulation pattern.
    """
    rows = []
    for i in range(61):
        # Both lows AND highs rise steeply — no stable ceiling
        low = 80.0 + i * 0.5
        high = 90.0 + i * 1.0  # highs rise faster — spread between 30d/60d max will be large
        rows.append({
            "open": low + 3.0,
            "high": high,
            "low": low,
            "close": low + 4.0,
            "volume": 1000.0,
            "ma60": 70.0,
        })
    # Breakout day
    last_high = 90.0 + 60 * 1.0  # = 150
    rows.append({
        "open": last_high + 1,
        "high": last_high + 5,
        "low": last_high,
        "close": last_high + 4,
        "volume": 2000.0,
        "ma60": 70.0,
    })

    df = add_features(make_bars(rows))
    # upper_band_spread_60d should be > 5% because prior_high_60 >> prior_high_30
    assert df.loc[61, "upper_band_spread_60d"] > 0.05
    assert not df.loc[61, "is_pattern_breakout"]


def test_is_pattern_breakout_requires_above_ma60():
    """
    Rising lows + stable ceiling + breakout but close < ma60 → not pattern breakout.
    """
    rows = []
    base_low = 95.0
    for i in range(61):
        low = base_low + i * 0.1
        rows.append({
            "open": low + 2.0,
            "high": 102.0,
            "low": low,
            "close": low + 1.5,
            "volume": 1000.0,
            "ma60": 200.0,  # far above close → below ma60
        })
    # Breakout day — still below ma60 = 200
    rows.append({
        "open": 103.0,
        "high": 106.0,
        "low": 102.5,
        "close": 105.0,
        "volume": 2000.0,
        "ma60": 200.0,
    })

    df = add_features(make_bars(rows))
    assert not df.loc[61, "is_pattern_breakout"]


def test_is_in_breakdown_pattern_fires_after_multiple_new_lows():
    """
    Stock with >= 2 new-low events in 60 days + MA60 down → in breakdown pattern.
    """
    n = 120
    rows = []
    # Start at 100, then progressively break lower with 4 new-low events
    for i in range(n):
        offset = i * 0.5
        # Every 20 bars after bar 30: force a new-low event (low << prior_low_20)
        if i % 20 == 0 and i > 30:
            rows.append({
                "open": 95 - offset, "high": 96 - offset,
                "low": 88 - offset, "close": 90 - offset,
                "volume": 1000.0,
            })
        else:
            rows.append({
                "open": 95 - offset, "high": 96 - offset,
                "low": 92 - offset, "close": 94 - offset,
                "volume": 1000.0,
            })

    df = add_features(make_bars(rows))
    # By bar 80+, should have accumulated >= 2 new-low events and MA60 declining
    later_bars = df.iloc[80:]
    assert later_bars["is_in_breakdown_pattern"].any(), (
        "Expected breakdown pattern detection in late bars"
    )


def test_is_in_breakdown_pattern_does_not_fire_in_bull_trend():
    """
    Pure bull trend → no new lows → not in breakdown pattern.
    """
    rows = [
        {"open": 100 + i * 0.3, "high": 102 + i * 0.3,
         "low": 98 + i * 0.3, "close": 101 + i * 0.3, "volume": 1000.0}
        for i in range(120)
    ]
    df = add_features(make_bars(rows))
    # In a continuously rising trend, low never undercuts prior_low_20
    assert not df["is_in_breakdown_pattern"].any()


def test_is_in_breakdown_pattern_requires_two_new_lows():
    """Single new-low event in 60 days + MA60 down → NOT in breakdown.

    After the single spike low at bar 90, prices recover and then stabilise
    above the bar-90 low (93.5) so no further new-low events occur within
    the rolling 60-day window.
    """
    rows = []
    # Bars 0-89: stable price
    for _i in range(90):
        rows.append({"open": 100.0, "high": 102.0, "low": 98.0,
                     "close": 100.0, "volume": 1000.0})
    # Bar 90: SINGLE new low (low=92, well below prior_low_20 of 98)
    rows.append({"open": 99, "high": 100, "low": 92, "close": 95,
                 "volume": 1000.0})
    # Bars 91-129: flat at ~96/97 — lows stay at 94.5, above the bar-90 low of 92.
    # This prevents any further new-low events because prior_low_20 will drop to 92
    # (bar 90's low) and our lows (94.5) stay above it.
    for _i in range(91, 130):
        rows.append({"open": 96.0, "high": 97.0, "low": 94.5, "close": 96.0,
                     "volume": 1000.0})
    df = add_features(make_bars(rows))
    # With only 1 new-low event, even if MA60 is down, should NOT fire
    assert not df["is_in_breakdown_pattern"].iloc[90:].any(), \
        "Single new-low event should not trigger breakdown pattern"


def test_is_in_breakdown_pattern_requires_ma60_down():
    """2+ new lows in 60d but MA60 flat/up → NOT in breakdown."""
    rows = []
    # Bars 0-89: stable price ~ 100
    for _i in range(90):
        rows.append({"open": 100.0, "high": 102.0, "low": 98.0,
                     "close": 100.0, "volume": 1000.0})
    # Bar 90: new low
    rows.append({"open": 99, "high": 100, "low": 92, "close": 95,
                 "volume": 1000.0})
    # Bars 91-109: strong recovery back to ~105+ (so MA60 stays roughly flat)
    for i in range(91, 110):
        rows.append({"open": 100.0 + (i - 91) * 0.5, "high": 102.0 + (i - 91) * 0.5,
                     "low": 99.0 + (i - 91) * 0.5, "close": 101.0 + (i - 91) * 0.5,
                     "volume": 1000.0})
    # Bar 110: another new low (below prior_low_20 of the recovery window)
    rows.append({"open": 99, "high": 100, "low": 87, "close": 90,
                 "volume": 1000.0})
    # Bars 111-129: strong recovery again → MA60 trend is NOT clearly negative
    for i in range(111, 130):
        rows.append({"open": 100.0 + (i - 111) * 0.8, "high": 102.0 + (i - 111) * 0.8,
                     "low": 99.0 + (i - 111) * 0.8, "close": 101.0 + (i - 111) * 0.8,
                     "volume": 1000.0})
    df = add_features(make_bars(rows))
    # After strong recovery, MA60 slope should be positive → breakdown should NOT fire
    # Check bars 125-129 where MA60 is clearly rising (5d slope > 0)
    tail = df.iloc[125:]
    assert not tail["is_in_breakdown_pattern"].any(), \
        "With MA60 rising (positive slope), breakdown pattern should not fire"


def test_is_pattern_breakout_does_not_fire_with_overhead_supply():
    """Rising lows + stable ceiling + breakout BUT overhead supply present → False.

    Course source: 型態學 08-騙線型態
    「上有壓力的突破 = 最常見的陷阱」
    「依照頸線的定義的確是有符合突破，可是股價的上方還有著明顯套牢區……
     可以被視為騙線型態的一種」

    Setup: first 20 bars spike to high=200 (creating overhead peaks at ~200),
    then 41+ bars of rising-low consolidation at ~100-105, then a breakout
    to 106. The overhead_supply_layer from the spike remains > 0, so
    is_pattern_breakout must be False even though the other 4 conditions pass.
    """
    rows = []
    # Bars 0–19: spike phase — creates overhead peaks at high=200 (5-bar local max)
    for _ in range(20):
        rows.append({
            "open": 190.0, "high": 200.0, "low": 188.0, "close": 195.0,
            "volume": 1000.0, "ma60": 90.0,
        })
    # Bars 20–80: rising-low consolidation at ~100, highs stable at 105
    for i in range(61):
        low = 95.0 + i * 0.1
        rows.append({
            "open": low + 2.0,
            "high": 105.0,
            "low": low,
            "close": low + 1.5,
            "volume": 1000.0,
            "ma60": 90.0,
        })
    # Bar 81: breakout above 105 ceiling, but overhead from the 200-spike remains
    rows.append({
        "open": 106.0, "high": 108.0, "low": 105.5, "close": 107.0,
        "volume": 2000.0, "ma60": 90.0,
    })

    df = add_features(make_bars(rows))
    last_idx = len(df) - 1

    # Confirm all other conditions pass (rising lows, stable ceiling, above MA60, breakout)
    assert df.loc[last_idx, "higher_low_count_60d"] >= 30, "rising-low condition must pass"
    assert df.loc[last_idx, "upper_band_spread_60d"] <= 0.05, "stable-ceiling must pass"
    assert df.loc[last_idx, "close"] > df.loc[last_idx, "prior_high_60"], "breakout must pass"
    assert df.loc[last_idx, "close"] > df.loc[last_idx, "ma60"], "above MA60 must pass"

    # The overhead from the spike must be present
    assert df.loc[last_idx, "overhead_supply_layer"] > 0, \
        "overhead_supply_layer must be > 0 due to prior spike at 200"

    # Clean overhead condition fails → pattern breakout must NOT fire
    assert not df.loc[last_idx, "is_pattern_breakout"], \
        "is_pattern_breakout must be False when overhead supply exists (騙線型態)"


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
