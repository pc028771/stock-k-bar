"""high_long_black.mark: 課程定義的高檔長黑 → 攻擊結束訊號.

Course source: K線力量判斷入門 單一K線(7) 高檔區域的長黑K + 事件(二) 高檔長黑.

Course quote:
  「高檔長黑可同時帶 3 種意義：
     1. 最近的攻擊缺口回補
     2. 長黑包覆創新高紅K
     3. 一根黑K吃下前 5 根
   當 2-3 種同時呈現 = 攻擊結束。」
"""
from __future__ import annotations

import pandas as pd
from kline.exit.high_long_black import mark

from tests.conftest import make_bars


def _add_prev(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("ticker")
    df["prev_high"] = g["high"].shift(1)
    df["prev_low"] = g["low"].shift(1)
    df["prev_close"] = g["close"].shift(1)
    return df


def _high_zone_prior_60(close: float = 60.0) -> list[dict]:
    """60 flat-ish bars with high/low ratio ≈ 1.4 to satisfy high_zone gate."""
    return [{"open": 60, "high": 70, "low": 50, "close": close} for _ in range(60)]


def test_no_trigger_long_black_alone_in_high_zone():
    """Course-faithful: long black + high zone alone (no meanings) → no trigger.

    This is the regression that the audit identified: the previous
    implementation triggered on this case, but the course requires at least
    2 of the 3 meanings to be present.
    """
    rows = _high_zone_prior_60()
    rows.append({"open": 60, "high": 61, "low": 59, "close": 60})  # neutral
    rows.append({"open": 100, "high": 100, "low": 84, "close": 85})  # long black, body 15%
    df = _add_prev(make_bars(rows))
    out = mark(df)
    assert not out.iloc[-1], (
        "Long black + high zone alone must NOT trigger; course requires "
        "≥2 of {gap_fill, engulf_new_high_red, eat_5_prev_closes}."
    )


def test_triggers_when_eat_5_plus_engulf_new_high_red():
    """M2 + M3 hold → fire.

    Setup: 60 high-zone prior bars (close=60), then a red-K making new high,
    then a long black engulfing it AND eating 5 prev closes.
    """
    rows = _high_zone_prior_60(close=60)
    # Bar 60: red K closing above prior_high_60 (=70) → new high red
    rows.append({"open": 71, "high": 78, "low": 70, "close": 78})
    # Bar 61: long black engulfing prev + closing below min(prev 5 closes)
    # prev_high = 78, prev_low = 70; prev 5 closes ≈ 60,60,60,60,78 → min=60
    # We need today close < 60 and engulf (open >= 78 AND close <= 70).
    # close=55 (< 60 → M3 ✓; < 70 → engulf close-leg ✓), open=80 (>= 78 → engulf open-leg ✓).
    rows.append({"open": 80, "high": 81, "low": 54, "close": 55})
    df = _add_prev(make_bars(rows))
    out = mark(df)
    assert out.iloc[-1], "M2 (engulf new-high red) + M3 (eat 5 prev closes) should trigger"


def test_triggers_when_gap_fill_plus_eat_5():
    """M1 + M3 hold → fire.

    Setup: gap-up some bars ago, then a long black that closes below the
    gap's lower bound AND eats 5 prev closes.
    """
    rows = _high_zone_prior_60(close=60)
    # Bar 60: gap-up. open > prev_high (=70). gap_lower_bound = 70.
    rows.append({"open": 75, "high": 80, "low": 75, "close": 78})
    # Bars 61-64: stay up but not making new highs above bar 60.
    for _ in range(4):
        rows.append({"open": 78, "high": 80, "low": 76, "close": 78})
    # Bar 65: long black. close < 70 (gap fill → M1 ✓), close < min(prev 5 closes)=78 (M3 ✓).
    # Open >= prev_high (80)? No — we want M2 to NOT hold, so open just below 80.
    # body must be ≥ 4%. open=78, close=60 → body = 18/78 ≈ 23% ✓
    rows.append({"open": 78, "high": 79, "low": 59, "close": 60})
    df = _add_prev(make_bars(rows))
    out = mark(df)
    assert out.iloc[-1], "M1 (gap fill) + M3 (eat 5 prev closes) should trigger"


def test_no_trigger_when_body_is_small():
    """Small body never triggers regardless of meanings."""
    rows = _high_zone_prior_60()
    rows.append({"open": 71, "high": 78, "low": 70, "close": 78})  # new-high red
    rows.append({"open": 80, "high": 81, "low": 79, "close": 79.5})  # tiny black
    df = _add_prev(make_bars(rows))
    out = mark(df)
    assert not out.iloc[-1]


def test_no_trigger_in_flat_zone():
    """Flat zone fails high-zone gate regardless of meanings."""
    rows = [{"open": 50, "high": 51, "low": 49, "close": 50} for _ in range(61)]
    rows.append({"open": 50, "high": 51, "low": 44, "close": 47})  # long black 6%
    df = _add_prev(make_bars(rows))
    out = mark(df)
    assert not out.iloc[-1]
