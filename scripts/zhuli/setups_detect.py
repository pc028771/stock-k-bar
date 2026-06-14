"""Multi-TF + KD setup detectors — 7 個達標 setup（強多 F1-F4 + 震盪 S1-S3）.

依據:
  - [[feedback-multitf-diff-kd-setups]] 強多盤 4 setup
  - [[feedback-chop-regime-setups]] 震盪盤 3 setup
  - [[feedback-backtest-strategy-filtering]] 篩選標準
  - 樣本 / exit 對比結果見 /tmp/dual_regime_out.txt

Regime gate:
  strong_bull = TAIEX 20d > +5%
  chop        = |TAIEX 60d| < 5% AND 60d range < 12%

⚠️ 黃大方法、非老師課程；接 monitor 顯示時標 extras。
"""
from __future__ import annotations

from typing import Literal

import pandas as pd

Regime = Literal["strong_bull", "chop", "other"]


def classify_regime(taiex_ret20: float | None,
                    taiex_ret60: float | None,
                    taiex_range60_pct: float | None) -> Regime:
    """大盤 regime 判定（用 EOD daily K）。

    Args:
        taiex_ret20: TAIEX 20 日報酬 (%)
        taiex_ret60: TAIEX 60 日報酬 (%)
        taiex_range60_pct: TAIEX 60 日 (high-low)/mean × 100 (%)
    """
    if taiex_ret20 is not None and taiex_ret20 > 5.0:
        return "strong_bull"
    if (taiex_ret60 is not None and taiex_range60_pct is not None
            and abs(taiex_ret60) < 5.0 and taiex_range60_pct < 12.0):
        return "chop"
    return "other"


# ── 強多盤 F+ stack 4 個 setup ────────────────────────────────────────────

def detect_F1(*, is_leader: bool, taiex_ret5: float | None,
              trend_d: str, trend_60m: str, trend_30m: str, trend_5m: str) -> bool:
    """F1: F+ 殺盤 + 健康回檔（trend = 日上 60m 上 30m 下 5m 下）。

    強多盤、勝率 81%、平均 +19.48%、n=21、持有 5.4 天、exit = K 線 playbook。
    """
    if not is_leader: return False
    if taiex_ret5 is None or taiex_ret5 > -2.0: return False
    return (trend_d == "up" and trend_60m == "up"
            and trend_30m == "down" and trend_5m == "down")


def detect_F2(*, is_leader: bool, taiex_ret5: float | None,
              dif_d_streak: int) -> bool:
    """F2: F+ 殺盤 + streak 11+ (日 DIF 連續上行 ≥ 11 天)。

    強多盤、勝率 82%、平均 +18.44%、n=33、持有 4.5 天、exit = K 線 playbook。
    """
    if not is_leader: return False
    if taiex_ret5 is None or taiex_ret5 > -2.0: return False
    return dif_d_streak >= 11


def detect_F3(*, is_leader: bool, taiex_ret5: float | None,
              trend_d: str, trend_60m: str) -> bool:
    """F3: F+ 殺盤 + 反轉型 (日 DIF down + 60m DIF up)。

    強多盤、勝率 81%、平均 +9.75%、n=36、持有 3.3 天、exit = K 線 playbook。
    """
    if not is_leader: return False
    if taiex_ret5 is None or taiex_ret5 > -2.0: return False
    return trend_d == "down" and trend_60m == "up"


def detect_F4(*, is_leader: bool, taiex_ret5: float | None,
              K_5m: float | None) -> bool:
    """F4: F+ 殺盤 + 5m K < 30 (短期超賣)。

    強多盤、勝率 80%、平均 +12.16%、n=25、持有 4.7 天、exit = K 線 playbook。
    """
    if not is_leader: return False
    if taiex_ret5 is None or taiex_ret5 > -2.0: return False
    return K_5m is not None and K_5m < 30


# ── 震盪盤 3 個 setup ──────────────────────────────────────────────────

def detect_S1(*, is_leader: bool, taiex_ret5: float | None,
              K_5m: float | None, K_60m: float | None) -> bool:
    """S1: Leader 殺盤 + 雙超賣（5m K<30 AND 60m K<30）。

    震盪盤、勝率 83%、平均 +5.27%、n=12、持有 11.8 天、exit = Rule A only。
    """
    if not is_leader: return False
    if taiex_ret5 is None or taiex_ret5 > -2.0: return False
    if K_5m is None or K_60m is None: return False
    return K_5m < 30 and K_60m < 30


def detect_S2(*, is_laggard: bool,
              trend_d: str, trend_60m: str, trend_30m: str, trend_5m: str,
              K_5m: float | None) -> bool:
    """S2: Laggard 對齊上 + 5m K ≥ 80。

    震盪盤、勝率 87%、平均 +4.71%、n=23、持有 19 天、exit = +5% 鎖利。
    """
    if not is_laggard: return False
    if not (trend_5m == "up" and trend_30m == "up"
            and trend_60m == "up" and trend_d == "up"):
        return False
    return K_5m is not None and K_5m >= 80


def detect_S3(*, is_laggard: bool,
              trend_d: str, trend_60m: str, trend_30m: str, trend_5m: str,
              taiex_ret5: float | None) -> bool:
    """S3: Laggard 對齊上 + 大盤微弱（-2% < 5d ≤ 0%）。

    震盪盤、勝率 94%、平均 +7.11%、n=17、持有 20 天、exit = +5% 鎖利。
    """
    if not is_laggard: return False
    if not (trend_5m == "up" and trend_30m == "up"
            and trend_60m == "up" and trend_d == "up"):
        return False
    if taiex_ret5 is None: return False
    return -2.0 < taiex_ret5 <= 0.0


# ── 整合 dispatcher ────────────────────────────────────────────────────

SETUP_META = {
    "F1": {"setup_name": "F+ 殺盤+健康回檔", "regime": "strong_bull", "exit": "kline_playbook",
           "perf": "81%/+19.48%/n=21/持5.4d"},
    "F2": {"setup_name": "F+ 殺盤+streak11+", "regime": "strong_bull", "exit": "kline_playbook",
           "perf": "82%/+18.44%/n=33/持4.5d"},
    "F3": {"setup_name": "F+ 殺盤+反轉型", "regime": "strong_bull", "exit": "kline_playbook",
           "perf": "81%/+9.75%/n=36/持3.3d"},
    "F4": {"setup_name": "F+ 殺盤+5mK<30", "regime": "strong_bull", "exit": "kline_playbook",
           "perf": "80%/+12.16%/n=25/持4.7d"},
    "S1": {"setup_name": "Leader 殺盤+雙超賣", "regime": "chop", "exit": "rule_a",
           "perf": "83%/+5.27%/n=12/持11.8d"},
    "S2": {"setup_name": "Laggard 對齊上+5mK≥80", "regime": "chop", "exit": "profit_target_5pct",
           "perf": "87%/+4.71%/n=23/持19d"},
    "S3": {"setup_name": "Laggard 對齊上+大盤微弱", "regime": "chop", "exit": "profit_target_5pct",
           "perf": "94%/+7.11%/n=17/持20d"},
}


def detect_all_setups(
    regime: Regime,
    is_leader: bool,
    is_laggard: bool,
    taiex_ret5: float | None,
    trend_d: str,
    trend_60m: str,
    trend_30m: str,
    trend_5m: str,
    dif_d_streak: int,
    K_5m: float | None,
    K_60m: float | None,
) -> list[dict]:
    """對單一 ticker 跑全 7 個 detector、回傳觸發的 setup list.

    regime gate:
      strong_bull → 跑 F1-F4
      chop        → 跑 S1-S3
      other       → 都不跑（不在驗證範圍）
    """
    hits = []
    if regime == "strong_bull":
        if detect_F1(is_leader=is_leader, taiex_ret5=taiex_ret5,
                     trend_d=trend_d, trend_60m=trend_60m,
                     trend_30m=trend_30m, trend_5m=trend_5m):
            hits.append({"setup_id": "F1", **SETUP_META["F1"]})
        if detect_F2(is_leader=is_leader, taiex_ret5=taiex_ret5,
                     dif_d_streak=dif_d_streak):
            hits.append({"setup_id": "F2", **SETUP_META["F2"]})
        if detect_F3(is_leader=is_leader, taiex_ret5=taiex_ret5,
                     trend_d=trend_d, trend_60m=trend_60m):
            hits.append({"setup_id": "F3", **SETUP_META["F3"]})
        if detect_F4(is_leader=is_leader, taiex_ret5=taiex_ret5, K_5m=K_5m):
            hits.append({"setup_id": "F4", **SETUP_META["F4"]})
    elif regime == "chop":
        if detect_S1(is_leader=is_leader, taiex_ret5=taiex_ret5,
                     K_5m=K_5m, K_60m=K_60m):
            hits.append({"setup_id": "S1", **SETUP_META["S1"]})
        if detect_S2(is_laggard=is_laggard,
                     trend_d=trend_d, trend_60m=trend_60m,
                     trend_30m=trend_30m, trend_5m=trend_5m, K_5m=K_5m):
            hits.append({"setup_id": "S2", **SETUP_META["S2"]})
        if detect_S3(is_laggard=is_laggard,
                     trend_d=trend_d, trend_60m=trend_60m,
                     trend_30m=trend_30m, trend_5m=trend_5m,
                     taiex_ret5=taiex_ret5):
            hits.append({"setup_id": "S3", **SETUP_META["S3"]})
    return hits
