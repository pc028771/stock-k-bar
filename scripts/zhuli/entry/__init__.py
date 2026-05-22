"""Entry signals for zhuli course strategies.

Public API:
    ENTRY_REGISTRY: dict mapping signal name to detect() function.
    FILTER_REGISTRY: 輔助過濾條件（非獨立進場策略，用於強化 ENTRY_REGISTRY 訊號）

分類原則：
  ENTRY_REGISTRY — 對應到完整課程策略章節，有明確進出場規則，可獨立 backtest
  FILTER_REGISTRY — 課程中為輔助判斷工具（如布林帶位置、開盤意圖），
                    不作為獨立進場訊號，應作為其他 scanner 的過濾條件使用

Course: 主力大全方位操盤教戰守則 (林家洋)

ENTRY_REGISTRY:
    suffocation            — H 窒息量策略 (Ex1-1 ~ Ex1-3)
    institutional_firstbuy — J 投信首買策略 (Ex2-3)
    swing_breakout         — A 大波段選股策略（族群+籌碼+技術三面）(Ch3-1, Ch3-2)
    overnight_swing        — G 隔日沖策略 (Ch6-1 + Ch6-2)
    reversal_breakout      — C 反轉形態策略 (Ch4-2)
    pennant_flag           — B 旗形策略 (Ch4-2)
    institutional_swing    — I 投信跟單策略 (Ex2-1 + Ex2-2)
    intraday               — F 當沖策略 (Ch5-1/Ch5-2/Ch5-3)

FILTER_REGISTRY（輔助過濾，非獨立進場）:
    bbands_upper_break     — D 布林上軌（課程輔助判斷，非獨立策略）
    bollinger_pullback     — E 布林回測（課程輔助判斷，backtest EV 為負）
    open_signal_filter     — M 主力意圖（Ch7-3 輔助判讀，子集用 open_signal_entry/exit）
    open_signal_entry      — M-Entry 收低開高訊號
    open_signal_exit       — M-Exit 出場警示
"""
from __future__ import annotations

from . import (
    bbands_upper_break,
    bollinger_pullback,
    institutional_firstbuy,
    institutional_swing,
    intraday,
    open_signal_entry,
    open_signal_exit,
    open_signal_filter,
    overnight_swing,
    pennant_flag,
    reversal_breakout,
    suffocation,
    swing_breakout,
)

ENTRY_REGISTRY = {
    # 完整課程策略 — 有明確進出場規則，可獨立 backtest
    "suffocation":              suffocation.detect,           # H 窒息量 (Ex1)
    "institutional_firstbuy":   institutional_firstbuy.detect, # J 投信首買 (Ex2-3)
    "swing_breakout":           swing_breakout.detect,        # A 大波段 (Ch3)
    "overnight_swing":          overnight_swing.detect,       # G 隔日沖 (Ch6)
    "reversal_breakout":        reversal_breakout.detect,     # C 反轉形態 (Ch4-2)
    "pennant_flag":             pennant_flag.detect,          # B 旗形 (Ch4-2)
    "institutional_swing":      institutional_swing.detect,   # I 投信跟單 (Ex2)
    "intraday":                 intraday.detect,              # F 當沖 (Ch5)
}

# 輔助過濾條件 — 非獨立進場策略，應作為 ENTRY_REGISTRY scanner 的過濾條件
FILTER_REGISTRY = {
    "bbands_upper_break":  bbands_upper_break.detect,   # D 布林上軌（輔助）
    "bollinger_pullback":  bollinger_pullback.detect,   # E 布林回測（輔助，backtest EV 為負）
    "open_signal_filter":  open_signal_filter.detect,  # M 主力意圖（輔助判讀）
    "open_signal_entry":   open_signal_entry.detect,   # M-Entry
    "open_signal_exit":    open_signal_exit.detect,    # M-Exit 出場警示
}

# Scanner 性質分類 (給 backtest 用)
EXIT_ONLY_SCANNERS = {"open_signal_exit"}
MASTER_SCANNERS = {"open_signal_filter"}  # 子集 wrapper 的 master，sanity 用、backtest 跳

__all__ = [
    "ENTRY_REGISTRY",
    "EXIT_ONLY_SCANNERS",
    "MASTER_SCANNERS",
    "bbands_upper_break",
    "bollinger_pullback",
    "institutional_firstbuy",
    "institutional_swing",
    "intraday",
    "open_signal_entry",
    "open_signal_exit",
    "open_signal_filter",
    "overnight_swing",
    "pennant_flag",
    "reversal_breakout",
    "suffocation",
    "swing_breakout",
]
