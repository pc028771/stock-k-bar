"""Multi-stage 當沖標的選擇器.

3 stage filter:
1. F 當沖前夜篩 top 10 (from daily_scanner_job)
2. K-line 力量分支判斷 — 跑 8 個 kline entry signals、看哪些 fire
3. 隔日開盤確認 — gap + 第 1 根 5K 方向
4. 選 strength × open_score 最高的 1 檔

對齊 user「只能操作一檔」+「K 線力量框架雙確認」需求。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import pandas as pd

_HERE = Path(__file__).parent
_REPO = _HERE.parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ── Stage 2: K-line branch classifier ────────────────────────────────────────


def classify_kline_branch(df: pd.DataFrame) -> dict:
    """跑 K-line entry signals、回傳哪些分支 fired + 強度 score (V1 廢棄).

    保留為向後相容、實際用 classify_kline_patterns。
    """
    return classify_kline_patterns(df)


# Pattern 方向分類（依課程定義）
BULLISH_PATTERNS = {
    "bull_engulfing", "morning_star_harami", "morning_star_island_reversal",
    "piercing_line", "three_red_dadi_dangqian", "rebound",
    "self_rescue_breakout", "breakout_double_star", "gap_fill_up",
    "attack_cost_displayed",
}
BEARISH_PATTERNS = {
    "bear_engulfing", "evening_star_abandoned", "evening_star_island_reversal",
    "dark_double_star_anye", "outside_three_black", "outside_three_black_like",
    "two_crow_gap", "gap_under_pressure_reversal", "gap_fill_down",
    "high_hanging_man", "trapped",
}
NEUTRAL_PATTERNS = {
    "biting", "neutral_engulfing", "embracing", "meeting",
    "merged_doji", "rising_falling", "gap_reversal", "zhongshu_pattern",
}


def classify_kline_patterns(df: pd.DataFrame, lookback: int = 3) -> dict:
    """跑 K-line 31 個 patterns、回傳近 N 日多/空 fires + net_bias.

    Args:
        df: ticker 完整日 K 歷史
        lookback: 看近幾日（預設 3 = 今日 + 前 2 日）

    Returns:
        {
            "branches": [{"name": str, "direction": "bull"/"bear"/"neutral",
                         "days_ago": int}, ...],
            "bull_count": int,
            "bear_count": int,
            "net_bias": int (bull_count - bear_count),
            "strength": int (total fired count),
        }
    """
    import importlib

    pattern_names = list(BULLISH_PATTERNS) + list(BEARISH_PATTERNS) + list(NEUTRAL_PATTERNS)

    branches = []
    bull_count = 0
    bear_count = 0

    for name in pattern_names:
        try:
            mod = importlib.import_module(f"kline.patterns.{name}")
            sig = mod.detect(df)
            if not hasattr(sig, "iloc") or len(sig) == 0:
                continue
            # check last `lookback` days
            for days_ago in range(lookback):
                idx = -1 - days_ago
                if abs(idx) > len(sig):
                    break
                if bool(sig.iloc[idx]):
                    if name in BULLISH_PATTERNS:
                        direction = "bull"
                        bull_count += 1
                    elif name in BEARISH_PATTERNS:
                        direction = "bear"
                        bear_count += 1
                    else:
                        direction = "neutral"
                    branches.append({"name": name, "direction": direction,
                                     "days_ago": days_ago})
                    break  # 同一 pattern 只記最近一次
        except Exception:
            pass

    return {
        "branches": branches,
        "bull_count": bull_count,
        "bear_count": bear_count,
        "net_bias": bull_count - bear_count,
        "strength": len(branches),
    }


# ── Stage 3: 隔日開盤確認 ──────────────────────────────────────────────────


def confirm_open(k1m_next: pd.DataFrame, prev_close: float) -> dict:
    """隔日開盤後 5 分鐘確認、回傳 verdict.

    Args:
        k1m_next: 隔日 1m K (full day)
        prev_close: 前日收盤

    Returns:
        {
            "verdict": "strong_long" / "neutral_long" / "neutral" / "weak" / "strong_short",
            "open_score": int (-2~+2),
            "gap_pct": float,
            "first_5k_red": bool,
            "reason": str,
        }
    """
    if k1m_next.empty or prev_close <= 0:
        return {
            "verdict": "no_data", "open_score": 0,
            "gap_pct": 0.0, "first_5k_red": False,
            "reason": "資料缺",
        }

    open_price = float(k1m_next["open"].iloc[0])
    gap_pct = (open_price / prev_close - 1) * 100

    # 第 1 根 5K (前 5 分 1m K aggregate)
    first_5_bars = k1m_next.head(5)
    if first_5_bars.empty:
        return {
            "verdict": "no_data", "open_score": 0,
            "gap_pct": gap_pct, "first_5k_red": False,
            "reason": "前 5 分 K 缺",
        }

    first_5k_open = float(first_5_bars["open"].iloc[0])
    first_5k_close = float(first_5_bars["close"].iloc[-1])
    first_5k_red = first_5k_close > first_5k_open

    # Verdict 邏輯：
    # - 跳空 +1~+3% + 第 1 根紅 K → strong_long
    # - 跳空 -1~+1% + 第 1 根紅 K → neutral_long
    # - 跳空 ≥ +5% → weak（跳空鎖死風險、紅線 #1）
    # - 跳空 < -3% → weak（弱勢開低）
    # - 其他 → neutral
    if gap_pct >= 5:
        return {
            "verdict": "weak", "open_score": -2,
            "gap_pct": gap_pct, "first_5k_red": first_5k_red,
            "reason": f"跳空 +{gap_pct:.1f}% ≥ 5% (鎖死風險)",
        }
    if gap_pct <= -3:
        return {
            "verdict": "weak", "open_score": -1,
            "gap_pct": gap_pct, "first_5k_red": first_5k_red,
            "reason": f"開低 {gap_pct:.1f}% ≤ -3% (弱勢)",
        }
    if 1 <= gap_pct <= 3 and first_5k_red:
        return {
            "verdict": "strong_long", "open_score": 2,
            "gap_pct": gap_pct, "first_5k_red": True,
            "reason": f"跳空 +{gap_pct:.1f}% + 第 1 根紅 K (強多)",
        }
    if -1 <= gap_pct < 1 and first_5k_red:
        return {
            "verdict": "neutral_long", "open_score": 1,
            "gap_pct": gap_pct, "first_5k_red": True,
            "reason": f"開平 {gap_pct:+.1f}% + 第 1 根紅 K (溫和)",
        }
    if 3 < gap_pct < 5:
        return {
            "verdict": "neutral", "open_score": 0,
            "gap_pct": gap_pct, "first_5k_red": first_5k_red,
            "reason": f"跳空 +{gap_pct:.1f}% (偏高、慎)",
        }
    if not first_5k_red:
        return {
            "verdict": "weak", "open_score": -1,
            "gap_pct": gap_pct, "first_5k_red": False,
            "reason": f"跳空 {gap_pct:+.1f}% + 第 1 根黑 K (弱)",
        }

    return {
        "verdict": "neutral", "open_score": 0,
        "gap_pct": gap_pct, "first_5k_red": first_5k_red,
        "reason": f"中性 (gap {gap_pct:+.1f}%, red={first_5k_red})",
    }


# ── Stage 4: pick one ──────────────────────────────────────────────────────


def pick_one(top10_with_extras: list[dict]) -> Optional[dict]:
    """從 top 10 (各帶 net_bias + open_score) 選 1 檔.

    Selection v2 — confidence 為主、K-line bias + open 為 modifier、不喧賓奪主：
    Selection score = confidence_score
                    + net_bias × 3   (K-line 多空淨偏向、最多 ±3 × 3 = ±9)
                    + open_score × 5  (開盤確認、最多 2 × 5 = 10)

    Gate（任一觸發 → return None）:
    - 全部 picks 都 open_score <= 0
    - 全部 picks 都 net_bias < 0（多空 K-line patterns 都偏空）

    Args:
        top10_with_extras: list of dict with keys 'confidence_score',
                          'net_bias', 'open_score'

    Returns:
        最高 selection score 的 pick、或 None
    """
    if not top10_with_extras:
        return None

    enriched = []
    for h in top10_with_extras:
        h2 = dict(h)
        confidence = h2.get("confidence_score", 0)
        net_bias = h2.get("net_bias", 0)
        open_score = h2.get("open_score", 0)
        h2["selection_score"] = confidence + net_bias * 3 + open_score * 5
        enriched.append(h2)

    # Gate: 要求 open_score > 0 (至少 neutral_long+)
    bullish = [h for h in enriched if h.get("open_score", 0) > 0]
    if not bullish:
        return None
    # Gate: 要求 net_bias >= 0 (K-line 不偏空)
    bullish = [h for h in bullish if h.get("net_bias", 0) >= 0]
    if not bullish:
        return None

    bullish.sort(key=lambda x: -x["selection_score"])
    return bullish[0]
