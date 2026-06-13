"""Leaders detector + MACD diff metrics unit tests."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.leaders_detect import (  # noqa: E402
    build_leader_info,
    compute_dif_metrics,
    compute_dif_metrics_60m,
    detect_laggard,
    detect_leader,
)


def _make_df(closes: list[float]) -> pd.DataFrame:
    df = pd.DataFrame({"close": closes})
    df["ma5"] = df.close.rolling(5, min_periods=1).mean()
    df["ma10"] = df.close.rolling(10, min_periods=1).mean()
    df["ma20"] = df.close.rolling(20, min_periods=1).mean()
    return df


def test_leader_positive() -> None:
    df = _make_df([100 + i for i in range(30)])  # 100..129、單調上行
    assert detect_leader(df, foreign_5d=5000.0) is True
    assert detect_laggard(df) is False


def test_leader_negative_foreign_zero() -> None:
    df = _make_df([100 + i for i in range(30)])
    assert detect_leader(df, foreign_5d=0.0) is False
    assert detect_leader(df, foreign_5d=None) is False


def test_leader_negative_below_ma() -> None:
    closes = [100 + i for i in range(25)] + [80]  # 拉回跌破
    df = _make_df(closes)
    assert detect_leader(df, foreign_5d=5000.0) is False


def test_laggard_positive_three_red() -> None:
    df = _make_df([200 - i for i in range(30)])  # 單調下行
    assert detect_laggard(df) is True
    assert detect_leader(df, foreign_5d=5000.0) is False


def test_laggard_positive_below_ma20_3pct() -> None:
    # 收盤剛好低於 ma20*0.97
    closes = [100.0] * 19 + [96.0]
    df = _make_df(closes)
    assert detect_laggard(df) is True


def test_neither_leader_nor_laggard() -> None:
    # 收 > ma5 但外資負、且不到 laggard 門檻
    df = _make_df([100 + i * 0.1 for i in range(30)])
    assert detect_leader(df, foreign_5d=-100.0) is False
    assert detect_laggard(df) is False


def test_dif_metrics_uptrend() -> None:
    df = _make_df([100 + i for i in range(40)])
    m = compute_dif_metrics(df["close"])
    assert m["dif_d"] > 0
    assert m["dif_d_chg_1d"] > 0
    assert m["dif_d_trend"] == "up"
    assert m["dif_d_up_streak"] >= 5


def test_dif_metrics_downtrend() -> None:
    df = _make_df([200 - i for i in range(40)])
    m = compute_dif_metrics(df["close"])
    assert m["dif_d"] < 0
    assert m["dif_d_trend"] == "down"


def test_dif_metrics_insufficient_data() -> None:
    df = _make_df([100, 101, 102])
    assert compute_dif_metrics(df["close"]) == {}


def test_dif_metrics_60m_basic() -> None:
    idx = pd.date_range("2026-06-01 09:00", periods=60, freq="60min")
    closes = pd.Series([100 + i * 0.2 for i in range(60)], index=idx)
    m = compute_dif_metrics_60m(closes)
    assert "dif_60m" in m
    assert m["dif_60m_trend"] in {"up", "flat", "down"}


def test_build_leader_info_full() -> None:
    df = _make_df([100 + i for i in range(30)])
    info = build_leader_info("3624", df, foreign_5d=12345.0, name="光頡")
    assert info is not None
    assert info["is_leader"] is True
    assert info["is_laggard"] is False
    assert info["ticker"] == "3624"
    assert info["name"] == "光頡"
    assert info["close"] == 129.0
    assert info["ret20"] is not None
    assert info["dist_ma10_pct"] is not None
    assert info["dif_d_trend"] == "up"
    assert info["dif_d_up_streak"] >= 5


def test_build_leader_info_nan_close() -> None:
    df = _make_df([100 + i for i in range(30)])
    df.loc[df.index[-1], "close"] = np.nan
    info = build_leader_info("9999", df, foreign_5d=1000.0)
    assert info is None
