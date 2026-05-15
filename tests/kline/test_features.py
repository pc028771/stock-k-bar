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
