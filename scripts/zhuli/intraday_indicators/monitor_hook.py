"""monitor 整合層 — 把新 indicator 接到 live_position_monitor 的 trigger cascade。

設計目標：
- 不動 StageTrigger 既有邏輯（向後相容）
- Ch5 補強 always-on（屬主力大課程內、cheap）
- 黃大 MACD extras default OFF、需 --extras macd_diff_huangda

回傳格式對齊 check_trigger_inline:
    (trigger_key: str, reason: str)
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple

import pandas as pd

from .ch5_complement import (
    check_first5min_skip,
    check_ma_divergence,
    check_b5_1_stop_profit,
    check_b5_2_limit_up_pattern,
    check_b5_3_quarterly_ma_short_filter,
)


# ── extras 解析 ──────────────────────────────────────────────────────────────


def parse_extras(extras_arg: Optional[str]) -> set[str]:
    """把 --extras 'macd_diff_huangda,foo=bar' 拆成 set。

    Returns:
        set of extras names（不含 =arg 部分）
    """
    if not extras_arg:
        return set()
    return {
        item.split("=", 1)[0].strip()
        for item in extras_arg.split(",")
        if item.strip()
    }


# ── Ch5 補強優先序：skip > exit > filter > none ──────────────────────────────


def run_ch5_complement(
    ticker: str,
    k1m: Optional[pd.DataFrame] = None,
    k5: Optional[pd.DataFrame] = None,
    daily_closes: Optional[pd.Series] = None,
    prev_close: Optional[float] = None,
    prev_was_limit_up: bool = False,
    position_side: str = "long",
) -> Tuple[str, str]:
    """跑 Ch5 補強 indicator cascade、回傳第一個 triggered 的訊號。

    優先序：
      1. 紅線 #9 前 5 分 > 5% skip → 'Ch5_skip'
      2. B5-1 大紅棒必停利 (5 分 K 5%) → 'Ch5_B5-1_exit'
      3. B5-2 漲停隔日 B 型 → 'Ch5_B5-2_skip'
      4. B5-3 季線往上不空（僅 short 持倉適用）→ 'Ch5_B5-3_filter'
      5. 均線發散硬性過濾 → 'Ch5_divergence_filter'

    Args:
        k1m: 當日 1 分 K
        k5:  當日 5 分 K
        daily_closes: 近 N 日日 K 收盤（用於 B5-3 季線）
        prev_close: 昨日收盤
        prev_was_limit_up: 昨日是否漲停
        position_side: 'long' / 'short'（B5-3 只對 short 過濾）

    Returns:
        (trigger_key, reason)、無觸發時回 ('none', '')
    """
    # 1. 前 5 分 > 5% skip
    if k1m is not None and not k1m.empty:
        r = check_first5min_skip(k1m)
        if r["triggered"]:
            return "Ch5_skip", r["reason"]

    # 2. B5-1 大紅棒必停利（5 分 K）
    if k5 is not None and not k5.empty:
        r = check_b5_1_stop_profit(k5, timeframe="5m")
        if r["triggered"]:
            return "Ch5_B5-1_exit", r["reason"]

    # 3. B5-2 A/B 型識別（僅 prev_was_limit_up=True 適用）
    if (prev_was_limit_up and k5 is not None and not k5.empty
            and prev_close is not None and prev_close > 0):
        r = check_b5_2_limit_up_pattern(k5, prev_close, prev_was_limit_up)
        if r["triggered"] and r.get("level") == "B":
            return "Ch5_B5-2_skip", r["reason"]
        # A 型不過濾、僅作 info、不回傳 trigger

    # 4. B5-3 季線往上不空（只對 short 持倉）
    if (position_side == "short" and daily_closes is not None
            and not daily_closes.empty):
        r = check_b5_3_quarterly_ma_short_filter(daily_closes)
        if r["triggered"]:
            return "Ch5_B5-3_filter", r["reason"]

    # 5. 均線發散
    if k5 is not None and not k5.empty:
        r = check_ma_divergence(k5)
        if r["triggered"]:
            return "Ch5_divergence_filter", r["reason"]

    return "none", ""


# ── 黃大 extras 包裝 ─────────────────────────────────────────────────────────


def run_huangda_if_enabled(
    extras_enabled: set[str],
    ticker: str,
    k1m_today: Optional[pd.DataFrame] = None,
    k1m_prev: Optional[pd.DataFrame] = None,
    position_side: str = "long",
) -> Tuple[str, str]:
    """若 --extras macd_diff_huangda 啟用、跑黃大 indicator。

    Returns:
        (trigger_key, reason)、未啟用或無觸發時回 ('none', '')
    """
    if "macd_diff_huangda" not in extras_enabled:
        return "none", ""

    if k1m_today is None or k1m_today.empty:
        return "none", "(無 1m K)"

    # lazy import 避免 monitor 啟動成本
    from zhuli.extras.macd_diff_huangda import (
        bear_resonance_filter,
        h1_flip_long_exit,
        bull_resonance_score,
    )

    # 優先序：h1_flip_long (空單回補) > bear_resonance (long 過濾) > bull_resonance (scoring)
    if position_side == "short":
        r = h1_flip_long_exit(k1m_today, k1m_prev, position_side="short")
        if r["triggered"]:
            return "extras.macd_diff_huangda.h1_flip_long", r["reason"]

    if position_side == "long":
        r = bear_resonance_filter(k1m_today, k1m_prev)
        if r["triggered"]:
            return "extras.macd_diff_huangda.bear_resonance", r["reason"]

    r = bull_resonance_score(k1m_today, k1m_prev)
    if r["triggered"]:
        return "extras.macd_diff_huangda.bull_resonance", r["reason"]

    return "none", ""


# ── 合成 trigger（給 monitor 直接呼叫） ──────────────────────────────────────


def compose_trigger(
    base_trigger: Tuple[str, str],
    ticker: str,
    extras_enabled: set[str],
    k1m: Optional[pd.DataFrame] = None,
    k5: Optional[pd.DataFrame] = None,
    daily_closes: Optional[pd.Series] = None,
    k1m_prev: Optional[pd.DataFrame] = None,
    prev_close: Optional[float] = None,
    prev_was_limit_up: bool = False,
    position_side: str = "long",
) -> Tuple[str, str]:
    """合成總 trigger：StageTrigger base → Ch5 補強 → extras。

    優先序：base StageTrigger > Ch5 補強 > extras
    （base 有 triggered 就回傳、不執行後續 indicator）

    Args:
        base_trigger: (trigger_key, reason) from check_trigger_inline
        其他: 餵給 Ch5 補強 + extras 的資料

    Returns:
        (final_trigger_key, combined_reason)
    """
    base_key, base_reason = base_trigger

    if base_key != "none":
        return base_key, base_reason

    # Ch5 補強
    ch5_key, ch5_reason = run_ch5_complement(
        ticker=ticker, k1m=k1m, k5=k5, daily_closes=daily_closes,
        prev_close=prev_close, prev_was_limit_up=prev_was_limit_up,
        position_side=position_side,
    )
    if ch5_key != "none":
        return ch5_key, ch5_reason

    # extras
    extras_key, extras_reason = run_huangda_if_enabled(
        extras_enabled, ticker, k1m, k1m_prev, position_side,
    )
    if extras_key != "none":
        return extras_key, extras_reason

    return "none", base_reason  # 用 base 的 reason 當解釋
