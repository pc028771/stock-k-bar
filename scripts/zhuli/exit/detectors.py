"""Phase 1 出場 Detector 實作。

課程來源:
  掀傘:       docs/主力大課程/主力大_5分K規則_spec審查_20260528.md L48-51
  高檔長黑:   K線力量判斷入門 單一K線(7) 高檔區域的長黑K
  分批停利:   memory feedback_swing_stop_profit_rules + 老師教法
  隔日急殺:   老師「跳空缺口回補失敗」+ memory feedback_dump_signal

使用方式 (daily bar 版 — 給 backtest 用):
  import pandas as pd
  from scripts.zhuli.exit.detectors import (
      check_umbrella_exit,
      check_high_long_black,
      check_profit_milestone,
      check_gap_down_emergency,
  )

  # 每個 function 接受一個「到當日為止的 daily DataFrame」
  # df 欄位: open, high, low, close, volume, [ma10]
  # 回傳 dict {triggered: bool, reason: str, ...}

5 分 K 版 (即時 monitor 用):
  check_umbrella_exit_5k 接受 5 分 K DataFrame
"""
from __future__ import annotations

import pandas as pd
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# 1. 🌂 掀傘 (Open_umbrella)
# ─────────────────────────────────────────────────────────────────────────────

def check_umbrella_exit(
    k5: pd.DataFrame,
    entry_price: float,
    vol_ratio_threshold: float = 0.7,
    no_new_high_bars: int = 3,
) -> dict:
    """掀傘出場偵測 — 5 分 K 版 (即時 monitor 用)。

    課程來源: 主力大_5分K規則_spec審查_20260528.md L48-51
    精神: 「主力收手了、不等被動停損」

    條件 (持倉中、賺中):
      - 連續 2-3 根 5K 不創新高
      - 量縮 (vol_ratio < 0.7 vs 前 10 根均)
      - 無人推升 (沒連續紅K)
      → 主動全出

    Args:
        k5:                   5 分 K DataFrame (index=datetime)
        entry_price:          進場均價
        vol_ratio_threshold:  量縮門檻 (預設 0.7)
        no_new_high_bars:     不創新高需求 N 根 (預設 3)

    Returns:
        dict: {triggered, level, reason, price}
    """
    result = {"triggered": False, "level": "watch", "reason": "", "price": 0.0, "detector": "掀傘"}

    if len(k5) < no_new_high_bars + 2:
        result["reason"] = f"5K 資料不足 ({len(k5)} 根)"
        return result

    current_close = float(k5["close"].iloc[-1])
    result["price"] = current_close

    # 必須在賺中
    if current_close <= entry_price:
        result["reason"] = f"未在賺中 (現 {current_close:.2f} ≤ 進場 {entry_price:.2f})"
        return result

    # 取最後 N+1 根 (含當根)
    recent = k5.tail(no_new_high_bars + 1)
    highs  = recent["high"].values

    # 連續 N 根不創前段最高
    prior_high = float(k5.iloc[-(no_new_high_bars + 1)]["high"])
    tail_highs = [float(h) for h in highs[1:]]  # 最後 N 根
    no_new_high = all(h <= prior_high for h in tail_highs)

    if not no_new_high:
        new_high_val = max(tail_highs)
        result["reason"] = f"仍有創新高 (最高 {new_high_val:.2f} > 前段高 {prior_high:.2f})"
        return result

    # 量縮
    vol_mean10 = float(k5["volume"].tail(max(len(k5), 10)).mean())
    last_vol   = float(k5["volume"].iloc[-1])
    vol_ratio  = last_vol / vol_mean10 if vol_mean10 > 0 else 1.0

    if vol_ratio >= vol_ratio_threshold:
        result["reason"] = f"量未縮 (×{vol_ratio:.2f} ≥ {vol_ratio_threshold})"
        return result

    # 無連續紅K (最後 N 根中不能有連續 2+ 紅K)
    tail_bars = k5.tail(no_new_high_bars)
    reds = (tail_bars["close"] > tail_bars["open"]).values
    consecutive_reds = any(reds[i] and reds[i+1] for i in range(len(reds)-1))
    if consecutive_reds:
        result["reason"] = "仍有連續紅K、尚未確認主力收手"
        return result

    profit_pct = (current_close / entry_price - 1) * 100
    result["triggered"] = True
    result["level"] = "confirmed"
    result["reason"] = (
        f"連 {no_new_high_bars} 根不創高 (前高 {prior_high:.2f})"
        f" + 量縮×{vol_ratio:.2f}"
        f" | 浮盈 +{profit_pct:.1f}%、主動出清"
    )
    return result


def check_umbrella_exit_daily(
    df: pd.DataFrame,
    entry_price: float,
    vol_ratio_threshold: float = 0.7,
    no_new_high_bars: int = 3,
) -> dict:
    """掀傘出場偵測 — Daily K 版 (backtest 用)。

    Args:
        df:           Daily bar DataFrame (sorted asc, index 任意)
        entry_price:  進場均價
    """
    result = {"triggered": False, "level": "watch", "reason": "", "price": 0.0, "detector": "掀傘"}

    if len(df) < no_new_high_bars + 2:
        result["reason"] = "資料不足"
        return result

    current_close = float(df["close"].iloc[-1])
    result["price"] = current_close

    if current_close <= entry_price:
        result["reason"] = f"未在賺中 (現 {current_close:.2f} ≤ 進場 {entry_price:.2f})"
        return result

    # 連續 N 根不創新高 (日線版: 不創前 N+1 根最高)
    prior_high = float(df.iloc[-(no_new_high_bars + 1)]["high"])
    tail_highs = [float(df.iloc[-(no_new_high_bars - i)]["high"]) for i in range(no_new_high_bars)]
    no_new_high = all(h <= prior_high for h in tail_highs)

    if not no_new_high:
        result["reason"] = f"仍有創新高 (前高 {prior_high:.2f})"
        return result

    # 量縮
    vol_mean = float(df["volume"].tail(max(len(df), 10)).mean())
    last_vol  = float(df["volume"].iloc[-1])
    vol_ratio = last_vol / vol_mean if vol_mean > 0 else 1.0

    if vol_ratio >= vol_ratio_threshold:
        result["reason"] = f"量未縮 (×{vol_ratio:.2f})"
        return result

    # 無連續紅K
    tail_bars = df.tail(no_new_high_bars)
    reds = (tail_bars["close"] > tail_bars["open"]).values
    consecutive_reds = any(reds[i] and reds[i+1] for i in range(len(reds)-1)) if len(reds) >= 2 else False
    if consecutive_reds:
        result["reason"] = "仍有連續紅K"
        return result

    profit_pct = (current_close / entry_price - 1) * 100
    result["triggered"] = True
    result["level"] = "confirmed"
    result["reason"] = (
        f"連 {no_new_high_bars} 根不創高 (前高 {prior_high:.2f})"
        f" + 量縮×{vol_ratio:.2f}"
        f" | 浮盈 +{profit_pct:.1f}%"
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 2. 🦘 高檔長黑 K (High_long_black)
# ─────────────────────────────────────────────────────────────────────────────

def check_high_long_black(
    df: pd.DataFrame,
    lookback_days: int = 60,
    long_black_pct: float = 0.04,
    high_zone_ratio: float = 1.3,
) -> dict:
    """高檔長黑 K 出場偵測 — Daily K 版。

    課程來源: K線力量判斷入門 單一K線(7) 高檔區域的長黑K

    3 種意義 (≥2 種 = 攻擊結束):
      M1 缺口回補: 收盤 < 最近 gap-up 下緣 (前日最高)
      M2 包覆創高紅K: 前 1 根紅 K 創 60d 高 + 今天大黑 K 包覆
      M3 吃下前 5 根: 收盤 < min(前 5 收)

    加上 high zone 過濾:
      過去 60d 高/低 ratio ≥ 1.3 (確認在高檔)

    Args:
        df:             Daily bar DataFrame (sorted asc, 至少 lookback_days + 2 行)
                        欄位: open, high, low, close
        lookback_days:  高檔判定回顧天數
        long_black_pct: 長黑實體門檻 (預設 4%)
        high_zone_ratio: 高低比門檻 (預設 1.3)

    Returns:
        dict: {triggered, level, reason, price, meanings: [M1, M2, M3]}
    """
    result = {
        "triggered": False,
        "level": "watch",
        "reason": "",
        "price": 0.0,
        "detector": "高檔長黑",
        "meanings": [],
    }

    if len(df) < 7:
        result["reason"] = "資料不足"
        return result

    today = df.iloc[-1]
    prev  = df.iloc[-2]
    result["price"] = float(today["close"])

    # Long-black 判斷
    body_pct = (float(today["open"]) - float(today["close"])) / float(today["open"]) if float(today["open"]) > 0 else 0
    is_long_black = (float(today["close"]) < float(today["open"])) and (body_pct >= long_black_pct)

    if not is_long_black:
        result["reason"] = f"非長黑K (實體 {body_pct*100:.1f}% < {long_black_pct*100:.0f}%)"
        return result

    # High zone 過濾
    lookback_df = df.tail(min(len(df), lookback_days + 1)).iloc[:-1]  # 不含今日
    if len(lookback_df) < 20:
        result["reason"] = "回顧資料不足 (高檔判定需 ≥20 日)"
        return result

    prior_max = float(lookback_df["high"].max())
    prior_min = float(lookback_df["low"].min())
    zone_ratio = prior_max / prior_min if prior_min > 0 else 0
    is_high_zone = zone_ratio >= high_zone_ratio

    if not is_high_zone:
        result["reason"] = f"非高檔區域 (高低比 {zone_ratio:.2f} < {high_zone_ratio})"
        return result

    meanings = []

    # M1: 最近缺口回補
    # 找最近 20 根內的 gap-up (open > prev_high)
    recent_lookback = df.tail(min(len(df), 21)).reset_index(drop=True)
    last_gap_lower: Optional[float] = None
    for i in range(len(recent_lookback) - 2, 0, -1):
        prev_bar = recent_lookback.iloc[i - 1]
        curr_bar = recent_lookback.iloc[i]
        if float(curr_bar["open"]) > float(prev_bar["high"]):
            last_gap_lower = float(prev_bar["high"])
            break
    m1 = False
    if last_gap_lower is not None and float(today["close"]) < last_gap_lower:
        m1 = True
        meanings.append(f"M1 缺口回補 (收 {today['close']:.2f} < gap下緣 {last_gap_lower:.2f})")

    # M2: 包覆創高紅K
    prev_open  = float(prev["open"])
    prev_close = float(prev["close"])
    prev_high  = float(prev["high"])
    prev_low   = float(prev["low"])
    prev_is_red = prev_close > prev_open
    # 前根是否創 60d 新高
    hist_60 = df.tail(min(len(df), 62)).iloc[:-2]  # 不含今日和前日
    prev_made_new_high = (prev_close >= float(hist_60["high"].max())) if not hist_60.empty else False
    # 今日包覆: open >= prev_high AND close <= prev_low (嚴格包覆)
    engulfs = (float(today["open"]) >= prev_high) and (float(today["close"]) <= prev_low)
    m2 = prev_is_red and prev_made_new_high and engulfs
    if m2:
        meanings.append(f"M2 包覆創高紅K (前高 {prev_high:.2f}→今收 {today['close']:.2f})")

    # M3: 吃下前 5 根
    if len(df) >= 7:
        prior_5_closes = df.iloc[-7:-2]["close"]  # 前 5 根 (不含前日和今日)
        min_5 = float(prior_5_closes.min())
        m3 = float(today["close"]) < min_5
        if m3:
            meanings.append(f"M3 吃下前5根 (收 {today['close']:.2f} < 前5最低收 {min_5:.2f})")
    else:
        m3 = False

    meaning_count = sum([m1, m2, m3])

    if meaning_count < 2:
        result["reason"] = (
            f"長黑K (實體 {body_pct*100:.1f}%) + 高檔區"
            f" 但意義數 {meaning_count}/3 < 2"
            + (f" | {'; '.join(meanings)}" if meanings else "")
        )
        return result

    result["triggered"] = True
    result["level"] = "confirmed"
    result["reason"] = (
        f"高檔長黑K (實體 {body_pct*100:.1f}%) | {meaning_count}/3 意義: "
        + " ; ".join(meanings)
    )
    result["meanings"] = meanings
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 3. 💰 分批停利里程碑 (Profit_taking_milestone)
# ─────────────────────────────────────────────────────────────────────────────

# ⚠️ 不指定減碼比例：CLAUDE.md 紅線「禁止自行發明減碼比例（如 1/3、1/2）」
# 原文案「鎖 1/3」違反、v1.6 改純里程碑提示、比例由 user 依課程框架決定
PROFIT_MILESTONES = [
    (0.10, "分批停利_10%", "💰 +10% 達標、考慮分批停利（比例課程未定、自行決定）"),
    (0.20, "分批停利_20%", "💰 +20% 達標、考慮再分批停利"),
    (0.30, "分批停利_30%", "💰 +30% 達標、剩餘部位看結構"),
]


def check_profit_milestone(
    current_price: float,
    entry_price: float,
    milestones_hit: set | None = None,
) -> dict:
    """分批停利里程碑偵測。

    課程來源: memory feedback_swing_stop_profit_rules

    +10% → 通知「考慮鎖利 1/3」
    +20% → 通知「再鎖 1/3」
    +30% → 通知「最後 1/3 看結構」

    每個里程碑只提示 1 次、不重複。

    Args:
        current_price:   當前價格
        entry_price:     進場均價
        milestones_hit:  已觸發過的里程碑 set (由呼叫方維護)

    Returns:
        dict: {triggered, level, reason, milestone_key, threshold_pct, action}
              triggered = True 代表新里程碑觸發
    """
    if milestones_hit is None:
        milestones_hit = set()

    result = {
        "triggered": False,
        "level": "info",
        "reason": "",
        "price": current_price,
        "detector": "分批停利",
        "milestone_key": None,
        "threshold_pct": 0.0,
        "action": "",
    }

    if entry_price <= 0:
        result["reason"] = "進場價無效"
        return result

    profit_pct = (current_price / entry_price - 1)

    for threshold, key, action in PROFIT_MILESTONES:
        if profit_pct >= threshold and key not in milestones_hit:
            result["triggered"] = True
            result["level"] = "info"
            result["reason"] = (
                f"浮盈 +{profit_pct*100:.1f}% 達 {threshold*100:.0f}% 里程碑"
            )
            result["milestone_key"] = key
            result["threshold_pct"] = threshold * 100
            result["action"] = action
            return result  # 一次只報一個里程碑

    result["reason"] = (
        f"浮盈 {profit_pct*100:.1f}% 未達下一里程碑"
        + (f" (已過 {sorted(milestones_hit)})" if milestones_hit else "")
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 4. 📉 隔日跳空大跌 (Gap_down_alert)
# ─────────────────────────────────────────────────────────────────────────────

def check_gap_down_emergency(
    open_price: float,
    prev_close: float,
    emergency_threshold: float = -0.05,
    warning_threshold:   float = -0.03,
) -> dict:
    """隔日跳空大跌偵測 — 9:00-9:05 開盤後立即評估。

    課程來源: 老師「跳空缺口回補失敗」+ memory feedback_dump_signal

    觸發條件:
      跳空 ≤ -5%  → 緊急: 立即出
      跳空 -3~-5% → 警示: 注意
      跳空 > -3%  → 正常: 不通知

    Args:
        open_price:           今日開盤價
        prev_close:           前日收盤價
        emergency_threshold:  緊急閾值 (預設 -5%)
        warning_threshold:    警示閾值 (預設 -3%)

    Returns:
        dict: {triggered, level, reason, gap_pct, action}
              level: 'emergency' / 'warning' / 'normal'
    """
    result = {
        "triggered": False,
        "level": "normal",
        "reason": "",
        "price": open_price,
        "detector": "隔日急殺",
        "gap_pct": 0.0,
        "action": "",
    }

    if prev_close <= 0:
        result["reason"] = "前收無效"
        return result

    gap_pct = (open_price / prev_close - 1)
    result["gap_pct"] = gap_pct

    if gap_pct <= emergency_threshold:
        result["triggered"] = True
        result["level"] = "emergency"
        result["reason"] = f"跳空 {gap_pct*100:.1f}% ≤ -5% 急殺"
        result["action"] = f"📉 隔日大跌 {gap_pct*100:.1f}% 立即出"
        return result

    if gap_pct <= warning_threshold:
        result["triggered"] = True
        result["level"] = "warning"
        result["reason"] = f"跳空 {gap_pct*100:.1f}% (-3% ~ -5%) 警示"
        result["action"] = f"⚠️ 隔日跳空 {gap_pct*100:.1f}% 注意"
        return result

    result["reason"] = f"開盤跳空 {gap_pct*100:.1f}% 正常範圍"
    return result
