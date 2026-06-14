"""Setups detector unit tests — 7 個達標 setup + regime gate."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.setups_detect import (  # noqa: E402
    classify_regime,
    detect_F1, detect_F2, detect_F3, detect_F4,
    detect_S1, detect_S2, detect_S3,
    detect_all_setups,
)


# ── Regime classification ────────────────────────────────────────────

def test_regime_strong_bull() -> None:
    assert classify_regime(taiex_ret20=8.0, taiex_ret60=10.0, taiex_range60_pct=15.0) == "strong_bull"


def test_regime_chop() -> None:
    assert classify_regime(taiex_ret20=2.0, taiex_ret60=1.5, taiex_range60_pct=7.0) == "chop"


def test_regime_other() -> None:
    # 20d <= 5%、但 60d range 太大
    assert classify_regime(taiex_ret20=3.0, taiex_ret60=2.0, taiex_range60_pct=15.0) == "other"
    # None inputs
    assert classify_regime(None, None, None) == "other"


# ── F1 健康回檔 ────────────────────────────────────────────────────────

def test_F1_positive() -> None:
    assert detect_F1(is_leader=True, taiex_ret5=-3.0,
                     trend_d="up", trend_60m="up",
                     trend_30m="down", trend_5m="down") is True


def test_F1_negative_not_leader() -> None:
    assert detect_F1(is_leader=False, taiex_ret5=-3.0,
                     trend_d="up", trend_60m="up",
                     trend_30m="down", trend_5m="down") is False


def test_F1_negative_market_not_killed() -> None:
    assert detect_F1(is_leader=True, taiex_ret5=-1.0,
                     trend_d="up", trend_60m="up",
                     trend_30m="down", trend_5m="down") is False


def test_F1_negative_wrong_trend() -> None:
    # 30m 上行不符
    assert detect_F1(is_leader=True, taiex_ret5=-3.0,
                     trend_d="up", trend_60m="up",
                     trend_30m="up", trend_5m="down") is False


# ── F2 streak 11+ ────────────────────────────────────────────────────

def test_F2_positive() -> None:
    assert detect_F2(is_leader=True, taiex_ret5=-2.5, dif_d_streak=12) is True


def test_F2_negative_streak_too_short() -> None:
    assert detect_F2(is_leader=True, taiex_ret5=-2.5, dif_d_streak=10) is False


# ── F3 反轉型 ──────────────────────────────────────────────────────────

def test_F3_positive() -> None:
    assert detect_F3(is_leader=True, taiex_ret5=-2.5,
                     trend_d="down", trend_60m="up") is True


def test_F3_negative() -> None:
    assert detect_F3(is_leader=True, taiex_ret5=-2.5,
                     trend_d="up", trend_60m="up") is False


# ── F4 5m K<30 ────────────────────────────────────────────────────────

def test_F4_positive() -> None:
    assert detect_F4(is_leader=True, taiex_ret5=-3.0, K_5m=25.0) is True


def test_F4_negative_K_too_high() -> None:
    assert detect_F4(is_leader=True, taiex_ret5=-3.0, K_5m=35.0) is False


# ── S1 雙超賣 ─────────────────────────────────────────────────────────

def test_S1_positive() -> None:
    assert detect_S1(is_leader=True, taiex_ret5=-3.0,
                     K_5m=22.0, K_60m=25.0) is True


def test_S1_negative_one_K_high() -> None:
    assert detect_S1(is_leader=True, taiex_ret5=-3.0,
                     K_5m=22.0, K_60m=45.0) is False


# ── S2 Laggard 對齊+5mK≥80 ────────────────────────────────────────────

def test_S2_positive() -> None:
    assert detect_S2(is_laggard=True,
                     trend_d="up", trend_60m="up",
                     trend_30m="up", trend_5m="up",
                     K_5m=85.0) is True


def test_S2_negative_not_laggard() -> None:
    assert detect_S2(is_laggard=False,
                     trend_d="up", trend_60m="up",
                     trend_30m="up", trend_5m="up",
                     K_5m=85.0) is False


def test_S2_negative_K_too_low() -> None:
    assert detect_S2(is_laggard=True,
                     trend_d="up", trend_60m="up",
                     trend_30m="up", trend_5m="up",
                     K_5m=75.0) is False


# ── S3 Laggard 對齊+大盤微弱 ──────────────────────────────────────────

def test_S3_positive() -> None:
    assert detect_S3(is_laggard=True,
                     trend_d="up", trend_60m="up",
                     trend_30m="up", trend_5m="up",
                     taiex_ret5=-1.5) is True


def test_S3_negative_market_too_strong() -> None:
    assert detect_S3(is_laggard=True,
                     trend_d="up", trend_60m="up",
                     trend_30m="up", trend_5m="up",
                     taiex_ret5=1.0) is False


def test_S3_negative_market_too_weak() -> None:
    # ≤ -2% 屬 S1 範圍、S3 不抓
    assert detect_S3(is_laggard=True,
                     trend_d="up", trend_60m="up",
                     trend_30m="up", trend_5m="up",
                     taiex_ret5=-2.5) is False


# ── dispatcher ────────────────────────────────────────────────────────

def test_dispatcher_strong_bull_F2_F3() -> None:
    hits = detect_all_setups(
        regime="strong_bull",
        is_leader=True, is_laggard=False,
        taiex_ret5=-3.0,
        trend_d="down", trend_60m="up", trend_30m="up", trend_5m="up",
        dif_d_streak=15, K_5m=50, K_60m=50,
    )
    ids = {h["setup_id"] for h in hits}
    assert "F2" in ids  # streak 15
    assert "F3" in ids  # 日下 60m 上
    assert "F1" not in ids  # 30m / 5m 不是 down
    assert "F4" not in ids  # 5m K=50 不 < 30
    assert "S1" not in ids  # chop only


def test_dispatcher_chop_S3() -> None:
    hits = detect_all_setups(
        regime="chop",
        is_leader=False, is_laggard=True,
        taiex_ret5=-1.0,
        trend_d="up", trend_60m="up", trend_30m="up", trend_5m="up",
        dif_d_streak=0, K_5m=60, K_60m=50,
    )
    ids = {h["setup_id"] for h in hits}
    assert "S3" in ids
    assert "F1" not in ids  # strong_bull only


def test_dispatcher_other_regime_no_hits() -> None:
    hits = detect_all_setups(
        regime="other",
        is_leader=True, is_laggard=False,
        taiex_ret5=-3.0,
        trend_d="up", trend_60m="up", trend_30m="down", trend_5m="down",
        dif_d_streak=15, K_5m=25, K_60m=25,
    )
    assert hits == []
