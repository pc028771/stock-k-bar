"""Unit tests for each pattern in patterns/.

每個 pattern 至少一個 positive 構造 (透過 synthetic OHLCV) + 一個 negative
(flat market). 全部走真實 features.add_features() 確保依賴的 derived
columns 完整.
"""
from __future__ import annotations

import pandas as pd

from kline.features import add_features
from kline.patterns import (
    bear_engulfing,
    biting,
    breakout_double_star,
    bull_engulfing,
    dark_double_star_anye,
    embracing,
    evening_star_abandoned,
    evening_star_island_reversal,
    gap_fill_down,
    gap_fill_up,
    gap_reversal,
    gap_under_pressure_reversal,
    high_hanging_man,
    meeting,
    morning_star_harami,
    morning_star_island_reversal,
    neutral_engulfing,
    outside_three_black,
    piercing_line,
    rebound,
    rising_falling,
    three_red_dadi_dangqian,
    trapped,
    two_crow_gap,
)

from tests.conftest import make_bars


def _flat_frame(n: int = 80, price: float = 100.0):
    rows = [
        {"open": price, "high": price + 1, "low": price - 1, "close": price,
         "volume": 1000.0, "ma60": price}
        for _ in range(n)
    ]
    return add_features(make_bars(rows))


def _bull_rally_then(rows_after, n_priming=80):
    """80 priming bars of rising attack + then the test rows.

    Designed so close[i] > prior_high_60[i] (creates breakout history) and
    sunrise pattern (high[i] > high[i-1], low[i] > low[i-1]) → attack_intensity ≥ 1.
    """
    priming = []
    for i in range(n_priming):
        low = 100.0 + i * 1.0
        priming.append({
            "open": low + 0.2, "high": low + 1.5, "low": low,
            "close": low + 1.2, "volume": 1000.0, "ma60": 90.0,
        })
    return add_features(make_bars(priming + rows_after))


def _bear_breakdown_then(rows_after, n_priming=130):
    """130 bars with progressive new-low spikes + explicitly declining MA60."""
    priming = []
    for i in range(n_priming):
        offset = i * 0.5
        ma60 = 100.0 - offset  # declining MA60
        if i % 20 == 0 and i > 30:
            priming.append({
                "open": 95 - offset, "high": 96 - offset,
                "low": 88 - offset, "close": 90 - offset, "volume": 1000.0,
                "ma60": ma60,
            })
        else:
            priming.append({
                "open": 95 - offset, "high": 96 - offset,
                "low": 92 - offset, "close": 94 - offset, "volume": 1000.0,
                "ma60": ma60,
            })
    return add_features(make_bars(priming + rows_after))


# ---------------- P02 bear_engulfing ----------------
def test_bear_engulfing_positive():
    # Build rally to set up bull exhaustion.
    # Last priming bar i=79: low=179, high=180.5, close=180.2
    # attack-meaning red K creating new 60-day high, then engulfing black K
    # Keep prices close to priming level so near_high (>= prior_high_60 * 0.95) holds.
    after = [
        {"open": 181.0, "high": 184.0, "low": 180.0, "close": 183.5, "volume": 1000.0, "ma60": 90.0},
        # bear engulf: open >= 183.5, close <= 181, black; close ≈ 180.5 ≥ 184*0.95=174.8 ✓
        {"open": 184.0, "high": 184.5, "low": 178.0, "close": 180.0, "volume": 1000.0, "ma60": 90.0},
    ]
    df = _bull_rally_then(after)
    sig = bear_engulfing.detect(df)
    # Last row should trigger
    assert sig.iloc[-1], f"bear_engulfing should fire at last bar; series tail = {sig.iloc[-5:].tolist()}"


def test_bear_engulfing_negative_flat():
    df = _flat_frame()
    assert not bear_engulfing.detect(df).any()


# ---------------- P03 bull_engulfing ----------------
def test_bull_engulfing_positive():
    # bear breakdown then new-low black K then engulfing red K.
    # ma60 must stay declining to preserve is_in_breakdown_pattern.
    after = [
        # Force a new 60-day low black K (last priming ma60 ~ 35.5)
        {"open": 28.0, "high": 28.5, "low": 20.0, "close": 22.0, "volume": 1000.0, "ma60": 34.5},
        {"open": 20.0, "high": 30.0, "low": 19.0, "close": 29.0, "volume": 1000.0, "ma60": 33.5},
    ]
    df = _bear_breakdown_then(after)
    sig = bull_engulfing.detect(df)
    assert sig.iloc[-1], f"bull_engulfing should fire; tail = {sig.iloc[-5:].tolist()}"


def test_bull_engulfing_negative_flat():
    df = _flat_frame()
    assert not bull_engulfing.detect(df).any()


# ---------------- P04/P06 morning_star_harami ----------------
def test_morning_star_harami_positive():
    after = [
        # Force breakdown long-black K (ma60 stays declining)
        {"open": 30.0, "high": 31.0, "low": 18.0, "close": 20.0, "volume": 1000.0, "ma60": 34.5},
        # red K harami inside prev K, closing above midpoint=(30+20)/2=25
        {"open": 22.0, "high": 28.0, "low": 21.0, "close": 27.0, "volume": 1000.0, "ma60": 33.5},
    ]
    df = _bear_breakdown_then(after)
    sig = morning_star_harami.detect(df)
    assert sig.iloc[-1], f"morning star should fire; tail = {sig.iloc[-5:].tolist()}"


def test_morning_star_harami_negative_flat():
    df = _flat_frame()
    assert not morning_star_harami.detect(df).any()


# ---------------- P05 high_hanging_man ----------------
def test_high_hanging_man_positive():
    after = [
        # T-line: open=182, close=183 (body 1), high=183.2 (upper 0.2),
        # low=175 (lower 7). lower>=2*body=2 ✓, upper<=0.3*body=0.3 ✓
        {"open": 182.0, "high": 183.2, "low": 175.0, "close": 183.0, "volume": 1000.0, "ma60": 90.0},
        # Sunset confirmation: today's high < prev high AND low < prev low
        {"open": 181.0, "high": 182.5, "low": 174.0, "close": 177.0, "volume": 1000.0, "ma60": 90.0},
    ]
    df = _bull_rally_then(after)
    sig = high_hanging_man.detect(df)
    assert sig.iloc[-1], f"hanging man should fire; tail = {sig.iloc[-5:].tolist()}"


def test_high_hanging_man_negative_flat():
    df = _flat_frame()
    assert not high_hanging_man.detect(df).any()


# ---------------- P07 three_red_dadi_dangqian ----------------
def test_three_red_dadi_positive():
    # No bull_exhaust gate in this pattern, so price range only needs to satisfy shape.
    after = [
        # D-3 long red K
        {"open": 181.0, "high": 185.0, "low": 181.0, "close": 184.8, "volume": 1000.0, "ma60": 90.0},
        # D-2 small red K, body < 2%, high <= D-3 high + 1.5%
        {"open": 184.8, "high": 185.5, "low": 183.5, "close": 185.0, "volume": 1000.0, "ma60": 90.0},
        # D-1 small red K
        {"open": 185.0, "high": 185.7, "low": 184.0, "close": 185.3, "volume": 1000.0, "ma60": 90.0},
        # D-0 black K breaks D-3 midpoint = (181+184.8)/2 = 182.9
        {"open": 185.3, "high": 185.5, "low": 178.0, "close": 180.0, "volume": 1000.0, "ma60": 90.0},
    ]
    df = _bull_rally_then(after)
    sig = three_red_dadi_dangqian.detect(df)
    assert sig.iloc[-1], f"dadi dangqian should fire; tail = {sig.iloc[-5:].tolist()}"


def test_three_red_dadi_negative_flat():
    df = _flat_frame()
    assert not three_red_dadi_dangqian.detect(df).any()


# ---------------- P08 dark_double_star_anye ----------------
def test_dark_double_star_positive():
    after = [
        # D-2, D-1 similar (highs within 3% of each other, lows similar)
        {"open": 182.0, "high": 185.0, "low": 181.0, "close": 184.0, "volume": 1000.0, "ma60": 90.0},
        {"open": 184.0, "high": 185.3, "low": 181.3, "close": 183.0, "volume": 1000.0, "ma60": 90.0},
        # D-0 black, close < min(181, 181.3) = 181; keep close high enough for bull_exhaust:
        # prior_high_60 ~ 185.3, near_high needs close >= 185.3*0.95 = 176.0 ✓
        {"open": 183.0, "high": 184.0, "low": 176.0, "close": 178.0, "volume": 1000.0, "ma60": 90.0},
    ]
    df = _bull_rally_then(after)
    sig = dark_double_star_anye.detect(df)
    assert sig.iloc[-1]


def test_dark_double_star_negative_flat():
    df = _flat_frame()
    assert not dark_double_star_anye.detect(df).any()


# ---------------- P08b gap_under_pressure_reversal ----------------
def test_gap_under_pressure_positive():
    # Need overhead_supply_layer > 0 then today gap down
    rows = []
    # 20 bars with high=200 (creates overhead peaks)
    for _ in range(20):
        rows.append({"open": 195.0, "high": 200.0, "low": 188.0, "close": 195.0,
                     "volume": 1000.0, "ma60": 90.0})
    # 30 bars at lower level (~100) to allow features to settle
    for _ in range(30):
        rows.append({"open": 100.0, "high": 105.0, "low": 98.0, "close": 102.0,
                     "volume": 1000.0, "ma60": 90.0})
    # Prev day: prev_low established
    rows.append({"open": 100.0, "high": 105.0, "low": 98.0, "close": 102.0,
                 "volume": 1000.0, "ma60": 90.0})
    # Today: gap down (high < prev_low=98) and close < prev_low
    rows.append({"open": 92.0, "high": 96.0, "low": 88.0, "close": 90.0,
                 "volume": 1000.0, "ma60": 90.0})
    df = add_features(make_bars(rows))
    sig = gap_under_pressure_reversal.detect(df)
    assert sig.iloc[-1]


def test_gap_under_pressure_negative_flat():
    df = _flat_frame()
    assert not gap_under_pressure_reversal.detect(df).any()


# ---------------- P09 gap_reversal ----------------
def test_gap_reversal_positive():
    after = [
        # Reference day with prev_low established at 181
        {"open": 182.0, "high": 184.0, "low": 181.0, "close": 183.0, "volume": 1000.0, "ma60": 90.0},
        # Gap down: open < prev_low (181), close < prev_low; close >= 184*0.95=174.8 for exhaust
        {"open": 179.0, "high": 180.0, "low": 175.0, "close": 176.0, "volume": 1000.0, "ma60": 90.0},
    ]
    df = _bull_rally_then(after)
    sig = gap_reversal.detect(df)
    assert sig.iloc[-1]


def test_gap_reversal_negative_flat():
    df = _flat_frame()
    assert not gap_reversal.detect(df).any()


# ---------------- P10 two_crow_gap ----------------
def test_two_crow_gap_positive():
    # Need overhead supply on D-3
    rows = []
    for _ in range(20):
        rows.append({"open": 195.0, "high": 200.0, "low": 188.0, "close": 195.0,
                     "volume": 1000.0, "ma60": 90.0})
    for _ in range(30):
        rows.append({"open": 100.0, "high": 105.0, "low": 98.0, "close": 102.0,
                     "volume": 1000.0, "ma60": 90.0})
    # D-4 to set up D-3 open-high
    rows.append({"open": 100.0, "high": 102.0, "low": 98.0, "close": 101.0,
                 "volume": 1000.0, "ma60": 90.0})
    # D-3 red K, open > prev_close=101
    rows.append({"open": 102.0, "high": 108.0, "low": 101.5, "close": 107.0,
                 "volume": 1000.0, "ma60": 90.0})
    # D-2 black K
    rows.append({"open": 107.0, "high": 107.5, "low": 103.0, "close": 104.0,
                 "volume": 1000.0, "ma60": 90.0})
    # D-1 black K — prev_low established as 103
    rows.append({"open": 104.0, "high": 105.0, "low": 100.0, "close": 101.0,
                 "volume": 1000.0, "ma60": 90.0})
    # D-0 open < prev_low (100): open=98
    rows.append({"open": 98.0, "high": 99.0, "low": 95.0, "close": 96.0,
                 "volume": 1000.0, "ma60": 90.0})
    df = add_features(make_bars(rows))
    sig = two_crow_gap.detect(df)
    assert sig.iloc[-1]


def test_two_crow_gap_negative_flat():
    df = _flat_frame()
    assert not two_crow_gap.detect(df).any()


# ---------------- P11 breakout_double_star ----------------
def test_breakout_double_star_positive():
    after = [
        # D-3, D-2 similar — keep ma60 declining
        {"open": 25.0, "high": 27.0, "low": 24.0, "close": 26.0, "volume": 1000.0, "ma60": 34.5},
        {"open": 26.0, "high": 27.3, "low": 24.2, "close": 25.5, "volume": 1000.0, "ma60": 34.0},
        # D-1 red, close > max(27, 27.3) = 27.3
        {"open": 25.5, "high": 30.0, "low": 25.0, "close": 29.0, "volume": 1000.0, "ma60": 33.5},
        # D-0 gap up: open > prev_high (30)
        {"open": 31.0, "high": 33.0, "low": 30.5, "close": 32.0, "volume": 1000.0, "ma60": 33.0},
    ]
    df = _bear_breakdown_then(after)
    sig = breakout_double_star.detect(df)
    assert sig.iloc[-1]


def test_breakout_double_star_negative_flat():
    df = _flat_frame()
    assert not breakout_double_star.detect(df).any()


# ---------------- P12 evening_star_abandoned ----------------
def test_evening_star_positive():
    after = [
        # D-2 red K (closer to priming level)
        {"open": 181.0, "high": 187.0, "low": 181.0, "close": 186.0, "volume": 1000.0, "ma60": 90.0},
        # D-1 doji-like (body_pct < 1%)
        {"open": 186.5, "high": 188.0, "low": 185.0, "close": 186.6, "volume": 1000.0, "ma60": 90.0},
        # D-0 black, close < D-2 midpoint = (181+186)/2 = 183.5
        # near_high: prior_high_60 ~ 188; close >= 188*0.95 = 178.6 → close=181 ✓
        {"open": 186.0, "high": 187.0, "low": 180.0, "close": 181.0, "volume": 1000.0, "ma60": 90.0},
    ]
    df = _bull_rally_then(after)
    sig = evening_star_abandoned.detect(df)
    assert sig.iloc[-1]


def test_evening_star_negative_flat():
    df = _flat_frame()
    assert not evening_star_abandoned.detect(df).any()


# ---------------- P13 evening_star_island_reversal ----------------
def test_evening_star_island_positive():
    # Last priming bar i=79: low=179, high=180.5
    # Need gap up day (low > 180.5), then today gap down
    after = [
        # Gap up: low > 180.5; keep modest so prior_high_60 doesn't shoot up
        {"open": 184.0, "high": 187.0, "low": 183.0, "close": 186.0, "volume": 1000.0, "ma60": 90.0},
        # filler bar
        {"open": 186.0, "high": 189.0, "low": 185.0, "close": 187.0, "volume": 1000.0, "ma60": 90.0},
        # gap down today (high < prev_low=185); close near high to satisfy near_high (prior_high_60 ~ 189; 189*0.95=179.6)
        {"open": 183.0, "high": 184.0, "low": 180.0, "close": 181.0, "volume": 1000.0, "ma60": 90.0},
    ]
    df = _bull_rally_then(after)
    sig = evening_star_island_reversal.detect(df)
    assert sig.iloc[-1]


def test_evening_star_island_negative_flat():
    df = _flat_frame()
    assert not evening_star_island_reversal.detect(df).any()


# ---------------- P14 morning_star_island_reversal ----------------
def test_morning_star_island_positive():
    # Need bear exhaustion + recent gap_down + today gap_up
    # ma60 must keep declining to preserve breakdown.
    after = [
        # Gap down from priming low (high < 27.5)
        {"open": 22.0, "high": 25.0, "low": 20.0, "close": 21.0, "volume": 1000.0, "ma60": 34.5},
        # filler
        {"open": 21.0, "high": 23.0, "low": 19.0, "close": 22.0, "volume": 1000.0, "ma60": 34.0},
        # gap up today (low > prev_high=23)
        {"open": 25.0, "high": 28.0, "low": 24.0, "close": 27.0, "volume": 1000.0, "ma60": 33.5},
    ]
    df = _bear_breakdown_then(after)
    sig = morning_star_island_reversal.detect(df)
    assert sig.iloc[-1]


def test_morning_star_island_negative_flat():
    df = _flat_frame()
    assert not morning_star_island_reversal.detect(df).any()


# ---------------- P15 outside_three_black ----------------
def test_outside_three_black_positive():
    # outside_three_black does NOT have bull_exhaust gate — only structural conditions.
    # Priming high tail ~ 180.5 so D-3 close must > prior_high_60 ≈ 180.5.
    after = [
        # D-3 red K creating new 60-day high
        {"open": 181.0, "high": 186.0, "low": 181.0, "close": 185.0, "volume": 1000.0, "ma60": 90.0},
        # D-2 black
        {"open": 185.0, "high": 186.0, "low": 180.0, "close": 182.0, "volume": 1000.0, "ma60": 90.0},
        # D-1 black, no gap (high >= prev_low=180)
        {"open": 182.0, "high": 183.0, "low": 175.0, "close": 177.0, "volume": 1000.0, "ma60": 90.0},
        # D-0 long black (body_pct >= 0.04), close < D-3 low (181)
        # body_pct = (177-170)/177 = 0.04 → need body >= 4%; open=177 close=165 body=12/177=0.068 ✓
        {"open": 177.0, "high": 178.0, "low": 164.0, "close": 165.0, "volume": 1000.0, "ma60": 90.0},
    ]
    df = _bull_rally_then(after)
    sig = outside_three_black.detect(df)
    assert sig.iloc[-1]


def test_outside_three_black_negative_flat():
    df = _flat_frame()
    assert not outside_three_black.detect(df).any()


# ---------------- P19 neutral_engulfing ----------------
def test_neutral_engulfing_positive():
    rows = [
        {"open": 100, "high": 102, "low": 98, "close": 100, "volume": 1000.0, "ma60": 100.0}
        for _ in range(25)
    ]
    # Red K
    rows.append({"open": 100, "high": 104, "low": 99, "close": 103, "volume": 1000.0, "ma60": 100.0})
    # Black engulfing K with volume
    rows.append({"open": 104, "high": 105, "low": 98, "close": 99, "volume": 5000.0, "ma60": 100.0})
    df = add_features(make_bars(rows))
    sig = neutral_engulfing.detect(df)
    assert sig.iloc[-1]


def test_neutral_engulfing_negative_flat():
    df = _flat_frame()
    assert not neutral_engulfing.detect(df).any()


# ---------------- P20 piercing_line ----------------
def test_piercing_line_positive_dark_cloud():
    # Need bull trend (close > ma60, ma60 rising). Build progressive rising ma60.
    rows = []
    for i in range(80):
        c = 100 + i * 0.5
        rows.append({"open": c, "high": c + 2, "low": c - 1, "close": c + 0.5,
                     "volume": 1000.0, "ma60": 50 + i * 0.3})
    # D-1: red K creating new high
    rows.append({"open": 140, "high": 150, "low": 139, "close": 148,
                 "volume": 1000.0, "ma60": 75})
    # D-0: black K, open > prev_close (148), close < prev midpoint (140+148)/2=144, but close > prev_open (140)
    rows.append({"open": 149, "high": 150, "low": 142, "close": 143,
                 "volume": 1000.0, "ma60": 75})
    df = add_features(make_bars(rows))
    sig = piercing_line.detect(df)
    assert sig.iloc[-1]


def test_piercing_line_negative_flat():
    df = _flat_frame()
    assert not piercing_line.detect(df).any()


# ---------------- P21 embracing ----------------
def test_embracing_positive():
    rows = [
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000.0, "ma60": 100.0}
        for _ in range(20)
    ]
    # Power K (large body)
    rows.append({"open": 100, "high": 110, "low": 99, "close": 109,
                 "volume": 1000.0, "ma60": 100.0})
    # Today: harami doji (high <= 110, low >= 99, body small)
    rows.append({"open": 105, "high": 106, "low": 104, "close": 105.1,
                 "volume": 1000.0, "ma60": 100.0})
    df = add_features(make_bars(rows))
    sig = embracing.detect(df)
    assert sig.iloc[-1]


def test_embracing_negative_flat():
    df = _flat_frame()
    assert not embracing.detect(df).any()


# ---------------- P22 meeting ----------------
def test_meeting_positive():
    # Pattern: downtrend → black K → red K with close ≈ prev_close.
    # 2026-06-02 update: meeting.detect requires close materially off ma20
    # (略顯跌勢 / 漲勢 context). Set ma20 above close for downtrend signal.
    rows = []
    for _ in range(20):
        rows.append({"open": 110, "high": 112, "low": 108, "close": 110,
                     "volume": 1000.0, "ma20": 110.0, "ma60": 110.0})
    # D-1: black K dropping to 101 (start of downtrend)
    rows.append({"open": 105, "high": 106, "low": 100, "close": 101,
                 "volume": 1000.0, "ma20": 109.6, "ma60": 110.0})
    # D-0: red K, close ≈ prev_close (101), ma20 still well above (down-context)
    rows.append({"open": 99, "high": 102, "low": 98.5, "close": 101.05,
                 "volume": 1000.0, "ma20": 109.1, "ma60": 110.0})
    df = add_features(make_bars(rows))
    sig = meeting.detect(df)
    assert sig.iloc[-1]


def test_meeting_negative_flat():
    df = _flat_frame()
    assert not meeting.detect(df).any()


# ---------------- P23 rebound ----------------
def test_rebound_positive_bull():
    rows = [
        {"open": 100, "high": 102, "low": 99, "close": 100, "volume": 1000.0, "ma60": 100.0}
        for _ in range(20)
    ]
    # Drop to new low — black K
    rows.append({"open": 100, "high": 101, "low": 95, "close": 96,
                 "volume": 1000.0, "ma60": 100.0})
    # Today: red K, open >= prev_open (100)
    rows.append({"open": 100, "high": 105, "low": 99, "close": 104,
                 "volume": 1000.0, "ma60": 100.0})
    df = add_features(make_bars(rows))
    sig = rebound.detect(df)
    assert sig.iloc[-1]


def test_rebound_negative_flat():
    df = _flat_frame()
    assert not rebound.detect(df).any()


# ---------------- P24 trapped ----------------
def test_trapped_positive_to_black():
    # Need D-2 red K creating new 60-day high
    rows = []
    for _ in range(70):
        rows.append({"open": 100, "high": 102, "low": 98, "close": 100,
                     "volume": 1000.0, "ma60": 95.0})
    # D-2: red K new high
    rows.append({"open": 100, "high": 115, "low": 99, "close": 113,
                 "volume": 1000.0, "ma60": 95.0})
    # D-1: harami inside D-2 (high <= 115, low >= 99)
    rows.append({"open": 108, "high": 112, "low": 105, "close": 110,
                 "volume": 1000.0, "ma60": 95.0})
    # D-0: black K, close < D-2 low (99)
    rows.append({"open": 110, "high": 111, "low": 95, "close": 97,
                 "volume": 1000.0, "ma60": 95.0})
    df = add_features(make_bars(rows))
    sig = trapped.detect(df)
    assert sig.iloc[-1]


def test_trapped_negative_flat():
    df = _flat_frame()
    assert not trapped.detect(df).any()


# ---------------- P25 biting ----------------
def test_biting_positive_bull():
    # 25 priming bars in narrow range
    rows = [
        {"open": 100, "high": 101, "low": 99.5, "close": 100.2,
         "volume": 1000.0, "ma60": 100.0}
        for _ in range(25)
    ]
    # Today: red K breaking high=101
    rows.append({"open": 100.5, "high": 105, "low": 100, "close": 104,
                 "volume": 1000.0, "ma60": 100.0})
    df = add_features(make_bars(rows))
    sig = biting.detect(df)
    assert sig.iloc[-1]


def test_biting_negative_flat():
    # Flat market — no breakout
    df = _flat_frame()
    assert not biting.detect(df).any()


# ---------------- P26 rising_falling ----------------
def test_rising_falling_positive():
    # Need: 過去 20 日內出現一根 power red K + 然後狹幅整理 + 今日突破
    rows = []
    # 20 flat bars to establish baseline
    for _ in range(20):
        rows.append({"open": 100, "high": 100.5, "low": 99.5, "close": 100,
                     "volume": 1000.0, "ma60": 100.0})
    # Power red K (big body, large pct_rank)
    rows.append({"open": 100, "high": 110, "low": 99, "close": 109,
                 "volume": 1000.0, "ma60": 100.0})
    # 5 narrow bars
    for _ in range(5):
        rows.append({"open": 109, "high": 110, "low": 108, "close": 109.3,
                     "volume": 1000.0, "ma60": 100.0})
    # Today: red K breaking high=110
    rows.append({"open": 109.5, "high": 115, "low": 109, "close": 114,
                 "volume": 1000.0, "ma60": 100.0})
    df = add_features(make_bars(rows))
    sig = rising_falling.detect(df)
    assert sig.iloc[-1]


def test_rising_falling_negative_flat():
    df = _flat_frame()
    assert not rising_falling.detect(df).any()


# ---------------- P27 gap_fill_up ----------------
def test_gap_fill_up_positive():
    rows = []
    for _ in range(20):
        rows.append({"open": 100, "high": 102, "low": 98, "close": 100,
                     "volume": 1000.0, "ma60": 100.0})
    # Gap up day: low > prev_high=102
    rows.append({"open": 105, "high": 110, "low": 103, "close": 108,
                 "volume": 1000.0, "ma60": 100.0})
    # Hold above gap_bottom=102 (which is prev_high)
    rows.append({"open": 107, "high": 109, "low": 105, "close": 106,
                 "volume": 1000.0, "ma60": 100.0})
    # Today: fill the gap — close <= 102
    rows.append({"open": 105, "high": 106, "low": 99, "close": 100,
                 "volume": 1000.0, "ma60": 100.0})
    df = add_features(make_bars(rows))
    sig = gap_fill_up.detect(df)
    assert sig.iloc[-1]


def test_gap_fill_up_negative_flat():
    df = _flat_frame()
    assert not gap_fill_up.detect(df).any()


# ---------------- P27 gap_fill_down ----------------
def test_gap_fill_down_positive():
    rows = []
    for _ in range(20):
        rows.append({"open": 100, "high": 102, "low": 98, "close": 100,
                     "volume": 1000.0, "ma60": 100.0})
    # Gap down day: high < prev_low=98
    rows.append({"open": 93, "high": 95, "low": 88, "close": 90,
                 "volume": 1000.0, "ma60": 100.0})
    # Hold below gap_top=98
    rows.append({"open": 92, "high": 95, "low": 89, "close": 92,
                 "volume": 1000.0, "ma60": 100.0})
    # Today: fill the gap — close >= 98
    rows.append({"open": 95, "high": 100, "low": 94, "close": 99,
                 "volume": 1000.0, "ma60": 100.0})
    df = add_features(make_bars(rows))
    sig = gap_fill_down.detect(df)
    assert sig.iloc[-1]


def test_gap_fill_down_negative_flat():
    df = _flat_frame()
    assert not gap_fill_down.detect(df).any()
