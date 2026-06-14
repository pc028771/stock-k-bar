"""C6 出場規則模擬器（Rule A only 簡化版）.

依據 `feedback_exit_rules_v3.md` (production default) + `feedback_backtest_strategy_filtering.md`:

進場 = 訊號日隔日開盤、固定 1 張
出場 Rule A:
    - 收盤 ≥ MA10 → 不出（重置 days_below）
    - 收 < MA10 by ≥ 2%（深破）→ 隔日開盤出 (exit_reason="deep_break")
    - 收 < MA10 by < 2% + 量比 ≥ 1.0（放量小破）→ 隔日開盤出 (exit_reason="soft_break_with_vol")
    - 容忍區 -2% ~ 0% 連 2 天 → 隔日開盤出 (exit_reason="tolerance_2d")
    - max_hold (30 天) 到 → 用最後一日收盤出 (exit_reason="max_hold_30")

報酬 = (exit_price - entry_price) / entry_price * 100%
"""
from __future__ import annotations

import pandas as pd


def should_exit_rule_a(close: float, ma10: float, vol_ratio: float,
                       days_below: int) -> tuple[bool, str | None]:
    """Rule A 出場判斷。返回 (should_exit, reason)."""
    if pd.isna(ma10) or ma10 <= 0:
        return False, None
    dist_pct = (close - ma10) / ma10 * 100
    if dist_pct >= 0:
        return False, None
    if dist_pct <= -2.0:
        return True, "deep_break"
    # dist_pct in (-2%, 0%)
    if not pd.isna(vol_ratio) and vol_ratio >= 1.0:
        return True, "soft_break_with_vol"
    if days_below >= 2:
        return True, "tolerance_2d"
    return False, None


def simulate_c6(sub: pd.DataFrame, entry_idx: int, ticker: str,
                max_hold: int = 30) -> dict | None:
    """從 sub 中模擬 C6 出場。

    Parameters
    ----------
    sub : pd.DataFrame
        單一 ticker 的時序 bars、已 reset_index。columns required:
        trade_date, open, close, ma10, volume, vol_ma20
    entry_idx : int
        訊號日的 row index（不是 entry_idx）；進場用 entry_idx + 1 開盤
    ticker : str
        for logging
    max_hold : int
        最長持有日數（不含 entry_idx 本身）

    Returns
    -------
    dict or None
        含 entry_date / entry_price / exit_date / exit_price / hold_days /
        exit_reason / ret_pct。若資料不足返回 None.
    """
    entry_pos = entry_idx + 1
    if entry_pos >= len(sub):
        return None
    entry_bar = sub.iloc[entry_pos]
    entry_price = entry_bar["open"]
    if pd.isna(entry_price) or entry_price <= 0:
        return None
    entry_date = entry_bar["trade_date"]

    days_below = 0
    # 從進場日（entry_pos）開始追蹤、entry_pos 當日不檢查（剛進場）
    # 從 entry_pos+1 起檢查每日收盤
    for i in range(entry_pos + 1, min(entry_pos + max_hold + 1, len(sub))):
        bar = sub.iloc[i]
        cl = bar["close"]
        ma10 = bar["ma10"]
        vol = bar["volume"]
        vol_ma = bar["vol_ma20"] if "vol_ma20" in bar.index else None
        if pd.isna(cl) or pd.isna(ma10) or ma10 <= 0:
            continue
        vol_ratio = (vol / vol_ma) if (vol_ma and vol_ma > 0 and not pd.isna(vol_ma)) else 0.0

        dist_pct = (cl - ma10) / ma10 * 100
        if dist_pct >= 0:
            days_below = 0
            continue
        days_below += 1
        exit_now, reason = should_exit_rule_a(cl, ma10, vol_ratio, days_below)
        if exit_now:
            # 隔日開盤出
            if i + 1 < len(sub):
                exit_bar = sub.iloc[i + 1]
                exit_price = exit_bar["open"]
                exit_date = exit_bar["trade_date"]
                if pd.isna(exit_price) or exit_price <= 0:
                    # fallback to today's close
                    exit_price = cl
                    exit_date = bar["trade_date"]
            else:
                exit_price = cl
                exit_date = bar["trade_date"]
            hold_days = i + 1 - entry_pos if (i + 1 < len(sub)) else i - entry_pos
            return {
                "ticker": ticker,
                "entry_date": entry_date.strftime("%Y-%m-%d") if hasattr(entry_date, "strftime") else str(entry_date),
                "entry_price": round(float(entry_price), 2),
                "exit_date": exit_date.strftime("%Y-%m-%d") if hasattr(exit_date, "strftime") else str(exit_date),
                "exit_price": round(float(exit_price), 2),
                "hold_days": int(hold_days),
                "exit_reason": reason,
                "ret_pct": round((exit_price - entry_price) / entry_price * 100, 2),
            }

    # max_hold reached → 最後一日收盤出
    last_pos = min(entry_pos + max_hold, len(sub) - 1)
    last_bar = sub.iloc[last_pos]
    exit_price = last_bar["close"]
    if pd.isna(exit_price) or exit_price <= 0:
        return None
    return {
        "ticker": ticker,
        "entry_date": entry_date.strftime("%Y-%m-%d") if hasattr(entry_date, "strftime") else str(entry_date),
        "entry_price": round(float(entry_price), 2),
        "exit_date": last_bar["trade_date"].strftime("%Y-%m-%d") if hasattr(last_bar["trade_date"], "strftime") else str(last_bar["trade_date"]),
        "exit_price": round(float(exit_price), 2),
        "hold_days": int(last_pos - entry_pos),
        "exit_reason": "max_hold_30",
        "ret_pct": round((exit_price - entry_price) / entry_price * 100, 2),
    }


def simulate_trades_c6(df: pd.DataFrame, signals: pd.Series,
                       max_hold: int = 30) -> pd.DataFrame:
    """跑整份 df + signals 跑 C6 出場、輸出 trades DataFrame。

    De-duplicate: 同一 ticker、前一筆 trade 未出場前不接新訊號。
    """
    df2 = df.copy()
    df2["__signal__"] = signals.values if hasattr(signals, "values") else signals
    trades = []
    for ticker, sub in df2.groupby("ticker"):
        sub = sub.reset_index(drop=True)
        sig_idxs = sub.index[sub["__signal__"]].tolist()
        last_exit_pos = -1
        for sig_idx in sig_idxs:
            if sig_idx <= last_exit_pos:
                continue
            result = simulate_c6(sub, sig_idx, ticker, max_hold=max_hold)
            if result is None:
                continue
            result["signal_date"] = sub.iloc[sig_idx]["trade_date"].strftime("%Y-%m-%d")
            trades.append(result)
            # last_exit_pos = exit_idx in sub: rebuild from date
            exit_date_str = result["exit_date"]
            matching = sub.index[sub["trade_date"] == pd.Timestamp(exit_date_str)].tolist()
            last_exit_pos = matching[0] if matching else sig_idx + result["hold_days"]
    return pd.DataFrame(trades)
