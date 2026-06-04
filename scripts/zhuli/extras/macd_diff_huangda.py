"""extras.macd_diff_huangda — 黃大 MACD DIF 多框架共振 indicator。

> 來源：黃大（Messenger 暱稱 Chihming）
> 文件：docs/huangda/
> ⚠️ 非主力大課程內容、屬其他老師個人實戰方法
> 預設 OFF、必須由 --extras macd_diff_huangda 明確啟用

策略核心（黃大原話確認）：
- 「macd的dif」(3/4) — 確認核心指標為 MACD DIF（非 KD）
- 「小時最重要」(4/1 09:20) — 60 分 DIF 為主信號
- 「小時翻正 我就全補 賺賠都補」(4/1 11:23) — 60m DIF 翻正 = 強制回補空單
- 「南亞科 日 小時 30分 5分 都在零軸下」(3/24) — 多框架共振判斷

三個訊號：
- bear_resonance: 60m + 30m + 5m DIF 都 < 0 → 強空方環境（過濾 long entry）
- h1_flip_long: 60m DIF 由負翻正 → 強制空單回補 hint
- bull_resonance: 60m + 30m DIF 都 > 0 → 弱多方訊號（scoring 加分、不過濾）

紀律：
- 不寫進主力大課程 spec
- 不混用主力大停損邏輯
- 訊號 key 永遠帶 'extras.macd_diff_huangda.' 前綴
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd


# ── 訊號等級 ──────────────────────────────────────────────────────────────────


class HuangdaSignalLevel(str, Enum):
    """黃大訊號強度等級。"""
    NONE = "none"
    WEAK = "weak"        # 1 個框架符合
    PARTIAL = "partial"  # 2 個框架符合
    FULL = "full"        # 全部框架符合（共振）


# ── MACD DIF 計算 ────────────────────────────────────────────────────────────


def calc_dif(
    closes: pd.Series,
    fast: int = 12,
    slow: int = 26,
) -> pd.Series:
    """計算 MACD DIF = EMA(fast) - EMA(slow)。

    黃大原話確認用標準參數 12/26（3/4 對話：「就 macd 的 dif」）。

    Args:
        closes: 收盤價序列
        fast: 快線週期
        slow: 慢線週期

    Returns:
        DIF 序列（與 closes 同 index）
    """
    if closes.empty or len(closes) < slow:
        return pd.Series(dtype=float, index=closes.index)

    ema_fast = closes.ewm(span=fast, adjust=False).mean()
    ema_slow = closes.ewm(span=slow, adjust=False).mean()
    return ema_fast - ema_slow


def resample_to_timeframe(
    k1m: pd.DataFrame,
    timeframe_minutes: int,
) -> pd.DataFrame:
    """把 1 分 K resample 到指定時間框架。

    支援 5 / 30 / 60 分（黃大用的 3 個框架）。

    Args:
        k1m: 1 分 K DataFrame、需 datetime index 或 datetime 欄位
        timeframe_minutes: 目標框架（5 / 30 / 60）

    Returns:
        resample 後的 K 棒 DataFrame（OHLCV）
    """
    if k1m.empty:
        return k1m

    df = k1m.copy()
    if "datetime" in df.columns and not isinstance(df.index, pd.DatetimeIndex):
        df = df.set_index("datetime")

    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("k1m 需要 datetime index 或 datetime 欄位")

    rule = f"{timeframe_minutes}min"
    agg = {"open": "first", "high": "max", "low": "min",
           "close": "last", "volume": "sum"}
    available = {k: v for k, v in agg.items() if k in df.columns}

    return df.resample(rule, label="right", closed="right").agg(available).dropna(how="all")


# ── 核心 indicator：多框架共振訊號 ──────────────────────────────────────────


@dataclass
class HuangdaResult:
    """黃大訊號計算結果。"""
    dif_5m:  Optional[float]
    dif_30m: Optional[float]
    dif_60m: Optional[float]
    bear_resonance:    bool
    bull_resonance:    bool
    h1_flip_long:      bool   # 60m DIF 剛由負翻正
    level:             HuangdaSignalLevel
    reason:            str


def huangda_multiframe_signals(
    k1m_today: pd.DataFrame,
    k1m_prev: Optional[pd.DataFrame] = None,
) -> HuangdaResult:
    """計算黃大三時間框架（5m/30m/60m）DIF + 三個訊號。

    Args:
        k1m_today: 當日 1 分 K（含 datetime / 收盤）
        k1m_prev:  前一個交易日 1 分 K（用來判 60m DIF 翻正、可選）

    Returns:
        HuangdaResult dataclass
    """
    if k1m_today.empty:
        return HuangdaResult(
            dif_5m=None, dif_30m=None, dif_60m=None,
            bear_resonance=False, bull_resonance=False, h1_flip_long=False,
            level=HuangdaSignalLevel.NONE,
            reason="當日 1 分 K 為空",
        )

    # 計算三框架 DIF
    def _dif_for(tf: int) -> Optional[float]:
        try:
            rk = resample_to_timeframe(k1m_today, tf)
            if len(rk) < 26:
                # 不足 EMA 暖機、若有前日資料則合併
                if k1m_prev is not None and not k1m_prev.empty:
                    combined = pd.concat([k1m_prev, k1m_today])
                    rk = resample_to_timeframe(combined, tf)
                if len(rk) < 26:
                    return None
            dif = calc_dif(rk["close"])
            return float(dif.iloc[-1]) if not dif.empty else None
        except Exception:
            return None

    dif_5m  = _dif_for(5)
    dif_30m = _dif_for(30)
    dif_60m = _dif_for(60)

    # 三訊號判定
    difs = [dif_5m, dif_30m, dif_60m]
    avail = [d for d in difs if d is not None]

    bear_resonance = (len(avail) == 3 and all(d < 0 for d in avail))
    bull_resonance = (len(avail) >= 2 and dif_60m is not None and dif_60m > 0
                      and dif_30m is not None and dif_30m > 0)

    # 60m DIF 翻正判定（需前一根 60m DIF）
    h1_flip_long = False
    try:
        if k1m_prev is not None and not k1m_prev.empty:
            combined = pd.concat([k1m_prev, k1m_today])
            rk60 = resample_to_timeframe(combined, 60)
            if len(rk60) >= 27:
                dif60_series = calc_dif(rk60["close"])
                if len(dif60_series) >= 2:
                    prev_dif = float(dif60_series.iloc[-2])
                    curr_dif = float(dif60_series.iloc[-1])
                    h1_flip_long = (prev_dif < 0 and curr_dif > 0)
    except Exception:
        pass

    # 等級
    if bear_resonance:
        level = HuangdaSignalLevel.FULL
        reason = (f"60m={dif_60m:+.3f} / 30m={dif_30m:+.3f} / 5m={dif_5m:+.3f} "
                  f"三框架共振空方 → 過濾 long entry")
    elif bull_resonance:
        level = HuangdaSignalLevel.PARTIAL
        reason = (f"60m={dif_60m:+.3f} / 30m={dif_30m:+.3f} 共振多方 "
                  f"→ scoring 加分")
    elif h1_flip_long:
        level = HuangdaSignalLevel.FULL
        reason = f"60m DIF 由負翻正 ({dif_60m:+.3f}) → 空單強制回補 hint"
    else:
        level = HuangdaSignalLevel.NONE
        reason = (f"無共振 "
                  f"(60m={dif_60m}, 30m={dif_30m}, 5m={dif_5m})")

    return HuangdaResult(
        dif_5m=dif_5m, dif_30m=dif_30m, dif_60m=dif_60m,
        bear_resonance=bear_resonance,
        bull_resonance=bull_resonance,
        h1_flip_long=h1_flip_long,
        level=level,
        reason=reason,
    )


# ── Registry hooks（透過 extras/__init__ register_macd_diff_huangda 註冊）──


def bear_resonance_filter(
    k1m_today: pd.DataFrame,
    k1m_prev: Optional[pd.DataFrame] = None,
    **kwargs,
) -> dict:
    """ENTRY_FILTER：三框架 DIF 都 < 0 → 過濾 long entry。

    Returns:
        {"triggered": bool, "level": str, "reason": str}
        triggered=True 代表「應過濾、不開 long」
    """
    r = huangda_multiframe_signals(k1m_today, k1m_prev)
    return {
        "triggered": r.bear_resonance,
        "level": "filter_long" if r.bear_resonance else "watch",
        "reason": f"extras.macd_diff_huangda.bear_resonance: {r.reason}",
        "dif_60m": r.dif_60m,
        "dif_30m": r.dif_30m,
        "dif_5m": r.dif_5m,
    }


def h1_flip_long_exit(
    k1m_today: pd.DataFrame,
    k1m_prev: Optional[pd.DataFrame] = None,
    position_side: str = "short",
    **kwargs,
) -> dict:
    """EXIT：60m DIF 由負翻正 → 空單強制回補 hint。

    Args:
        position_side: 'short' / 'long' — 只對 short 部位回傳 triggered=True

    Returns:
        {"triggered": bool, "level": str, "reason": str}
        triggered=True 代表「空單應強制回補」
    """
    r = huangda_multiframe_signals(k1m_today, k1m_prev)
    triggered = r.h1_flip_long and position_side == "short"
    return {
        "triggered": triggered,
        "level": "exit_short" if triggered else "watch",
        "reason": f"extras.macd_diff_huangda.h1_flip_long: {r.reason}",
        "dif_60m": r.dif_60m,
    }


def bull_resonance_score(
    k1m_today: pd.DataFrame,
    k1m_prev: Optional[pd.DataFrame] = None,
    bonus_points: int = 10,
    **kwargs,
) -> dict:
    """SCORING：60m + 30m DIF 都 > 0 → scoring 加分（不過濾）。

    Returns:
        {"triggered": bool, "level": str, "reason": str, "bonus": int}
    """
    r = huangda_multiframe_signals(k1m_today, k1m_prev)
    return {
        "triggered": r.bull_resonance,
        "level": "scoring_bonus" if r.bull_resonance else "watch",
        "reason": f"extras.macd_diff_huangda.bull_resonance: {r.reason}",
        "bonus": bonus_points if r.bull_resonance else 0,
        "dif_60m": r.dif_60m,
        "dif_30m": r.dif_30m,
    }
