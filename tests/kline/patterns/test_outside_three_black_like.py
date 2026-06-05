"""Tests for outside_three_black_like pattern.

Course source: 明日 K 線 第 43 篇 / 3995DDF008E3E1B600A9D920E6FFC07C
INVENTORY §A02 + §C01
"""
from __future__ import annotations

import pandas as pd

from kline.features import add_features
from kline.patterns import outside_three_black_like

from tests.conftest import make_bars


def _bull_rally_then(rows_after, n_priming: int = 80):
    """80 根上升 priming 棒 + 測試 rows。"""
    priming = []
    for i in range(n_priming):
        low = 100.0 + i * 1.0
        priming.append({
            "open": low + 0.2, "high": low + 1.5, "low": low,
            "close": low + 1.2, "volume": 1000.0, "ma60": 90.0,
        })
    return add_features(make_bars(priming + rows_after))


def _make_black_k(open_: float, body_pct: float = 0.06) -> dict:
    """建立 body_pct = 6% 的黑 K。"""
    close_ = open_ * (1 - body_pct)
    return {
        "open": open_, "high": open_ + 0.5, "low": close_ - 0.3,
        "close": close_, "volume": 1000.0, "ma60": 90.0,
    }


# ------- N=3 案例（等同 outside_three_black P15）-------

def test_outside_three_black_like_n3_positive():
    """N=3：創新高紅 K + 連三黑 K + 今日 close 跌破紅 K 低點。

    對應既有 P15 邏輯。
    """
    # 創新高紅 K（priming 末 close ≈ 180.2，prior_high_60 ≈ 179.5）
    new_high_red = {
        "open": 180.5, "high": 185.0, "low": 179.0, "close": 184.0,
        "volume": 1000.0, "ma60": 90.0,
    }  # low = 179.0 → 需要跌破
    black1 = _make_black_k(183.0)  # D-2
    black2 = _make_black_k(181.0)  # D-1
    # D-0：跌破 new_high_red.low = 179.0，且 body_pct = |184/176| ≈ 4.3% ≥ HIGH_LONG_BLACK_BODY_PCT_MIN
    black3 = {
        "open": 184.0, "high": 184.5, "low": 174.0, "close": 176.0,
        "volume": 1000.0, "ma60": 90.0,
    }
    df = _bull_rally_then([new_high_red, black1, black2, black3])
    sig = outside_three_black_like.detect(df)
    assert sig.iloc[-1], (
        f"N=3 outside_three_black_like should fire; tail = {sig.iloc[-5:].tolist()}"
    )


def test_outside_three_black_like_n3_no_break():
    """N=3 連黑 K 但今日 close 未跌破創新高紅 K 低點 → 不觸發。"""
    new_high_red = {
        "open": 180.5, "high": 185.0, "low": 179.0, "close": 184.0,
        "volume": 1000.0, "ma60": 90.0,
    }
    black1 = _make_black_k(183.0)
    black2 = _make_black_k(181.5)
    # D-0 close = 179.5 > new_high_red.low = 179.0 → 未跌破
    black3 = {
        "open": 180.5, "high": 181.0, "low": 179.2, "close": 179.5,
        "volume": 1000.0, "ma60": 90.0,
    }
    df = _bull_rally_then([new_high_red, black1, black2, black3])
    sig = outside_three_black_like.detect(df)
    assert not sig.iloc[-1], "no break of red-K low should NOT fire"


# ------- N=4 案例（課程第 43 篇明示範例）-------

def test_outside_three_black_like_n4_positive():
    """N=4：外側四黑 — 老師第 43 篇明示範例。"""
    new_high_red = {
        "open": 180.5, "high": 185.0, "low": 179.0, "close": 184.0,
        "volume": 1000.0, "ma60": 90.0,
    }
    black1 = _make_black_k(183.0)  # D-3
    black2 = _make_black_k(181.5)  # D-2
    black3 = _make_black_k(180.0)  # D-1
    # D-0 跌破 low = 179.0，body_pct ≥ 4%
    black4 = {
        "open": 184.0, "high": 184.5, "low": 175.0, "close": 176.5,
        "volume": 1000.0, "ma60": 90.0,
    }
    df = _bull_rally_then([new_high_red, black1, black2, black3, black4])
    sig = outside_three_black_like.detect(df)
    assert sig.iloc[-1], (
        f"N=4 (外側四黑) should fire; tail = {sig.iloc[-5:].tolist()}"
    )


# ------- N=9 案例（課程第 43 篇明示「外側九黑也成立」）-------

def test_outside_three_black_like_n9_positive():
    """N=9：外側九黑 — 老師第 43 篇明示「也可以叫類外側三黑」。"""
    new_high_red = {
        "open": 180.5, "high": 185.0, "low": 179.0, "close": 184.0,
        "volume": 1000.0, "ma60": 90.0,
    }
    blacks = []
    price = 183.0
    for _ in range(8):
        blacks.append(_make_black_k(price))
        price = price * (1 - 0.03)

    # D-0 跌破 low = 179.0，body_pct ≥ 4%
    final_black = {
        "open": 184.0, "high": 184.5, "low": 175.0, "close": 176.5,
        "volume": 1000.0, "ma60": 90.0,
    }
    df = _bull_rally_then([new_high_red] + blacks + [final_black])
    sig = outside_three_black_like.detect(df)
    assert sig.iloc[-1], (
        f"N=9 (外側九黑) should fire; tail = {sig.iloc[-5:].tolist()}"
    )


# ------- 負面案例 -------

def test_outside_three_black_like_negative_flat():
    """Flat market — 無創新高，不觸發。"""
    rows = [
        {"open": 100, "high": 101, "low": 99, "close": 100,
         "volume": 1000.0, "ma60": 100.0}
        for _ in range(80)
    ]
    df = add_features(make_bars(rows))
    assert not outside_three_black_like.detect(df).any(), (
        "flat market should not trigger outside_three_black_like"
    )


def test_outside_three_black_like_negative_only_two_blacks():
    """只有 2 根黑 K（N < 3）→ 不觸發。"""
    new_high_red = {
        "open": 180.5, "high": 185.0, "low": 179.0, "close": 184.0,
        "volume": 1000.0, "ma60": 90.0,
    }
    black1 = _make_black_k(183.0)
    # D-0 跌破但只有 2 連黑
    black2 = {
        "open": 180.0, "high": 180.5, "low": 177.0, "close": 178.0,
        "volume": 1000.0, "ma60": 90.0,
    }
    df = _bull_rally_then([new_high_red, black1, black2])
    sig = outside_three_black_like.detect(df)
    assert not sig.iloc[-1], "only 2 black Ks should NOT fire (need N >= 3)"


def test_outside_three_black_like_negative_interrupting_red():
    """連黑中間插入一根紅 K → 不觸發（課程範例皆連續黑，預設全黑）。"""
    new_high_red = {
        "open": 180.5, "high": 185.0, "low": 179.0, "close": 184.0,
        "volume": 1000.0, "ma60": 90.0,
    }
    black1 = _make_black_k(183.0)
    # 插入小紅 K
    red_interrupt = {
        "open": 181.0, "high": 182.0, "low": 180.5, "close": 181.5,
        "volume": 1000.0, "ma60": 90.0,
    }
    black2 = _make_black_k(180.5)
    # D-0 跌破
    black3 = {
        "open": 179.5, "high": 180.0, "low": 177.5, "close": 178.0,
        "volume": 1000.0, "ma60": 90.0,
    }
    df = _bull_rally_then([new_high_red, black1, red_interrupt, black2, black3])
    sig = outside_three_black_like.detect(df)
    assert not sig.iloc[-1], (
        "interrupting red K should break the consecutive-black sequence and NOT fire"
    )
