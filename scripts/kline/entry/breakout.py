"""Breakout attack entry signal — pure course definition.

Course source: 【突破跌破】突破意義的釐清, 【買點賣點】股價的買點決策(三)多頭買在攻擊

> 「對於K線圖來說，價格才是最重要的事情，不需要加上成交量」
> 「與這一根突破的K線是否長紅、有沒有上影線都無關」
> 「第一次突破，可以直接進攻；再次突破，需等隔日攻擊確認」

This implementation deliberately does NOT include:
  - is_red filter
  - close_pos threshold
  - volume_ratio threshold

Those are non-course filters; see kline/extras/strict_breakout.py if desired.

## First breakout vs re-breakout (audit I4)

Course distinguishes:
  - FIRST breakout (first close > prior_high_60 within lookback) →
    enter on the breakout bar (simulator executes on next-day open).
  - RE-breakout (a subsequent close > prior_high_60 within lookback) →
    must wait for NEXT-DAY attack confirmation before signalling entry;
    therefore the SIGNAL bar shifts forward by one (the confirmation bar)
    and the simulator executes on the bar AFTER that.

`is_first_breakout_above_level` is computed in features.py with a 60-bar
lookback. `is_attack_bar` is also defined there: a red K closing above
the prior close, OR gap-up, OR new prior_high_60 high.
"""
from __future__ import annotations

import pandas as pd


def detect(df: pd.DataFrame) -> pd.Series:
    """Returns bool Series. True = breakout attack entry signal on that bar.

    Updated 2026-05-16 to exclude stocks in 破底型態 (型態學 16).
    Updated 2026-05-16 (audit I4): re-breakouts require next-day attack
    confirmation; signal fires on the confirmation bar, not the breakout bar.

    Required df columns: close, prior_high_60, ma60, is_in_breakdown_pattern,
        is_first_breakout_above_level, is_attack_bar.
    """
    is_breakout = (df["close"] > df["prior_high_60"]).fillna(False)
    has_ma60 = df["ma60"].notna() & (df["close"] > df["ma60"])

    # Course exclusion: 破底型態 — layered supply, no legitimate entry until
    # overhead cleared or bearish trend ends.
    not_in_breakdown = ~df["is_in_breakdown_pattern"].fillna(False)

    # Case A: first breakout — fire on breakout bar itself.
    is_first = df["is_first_breakout_above_level"].fillna(False)
    first_breakout_signal = is_breakout & has_ma60 & is_first & not_in_breakdown

    # Case B: re-breakout — fire on the CONFIRMATION bar (the bar AFTER a
    # re-breakout bar, when that confirmation bar is itself an attack bar
    # and still satisfies the breakout/MA60 conditions). Simulator then
    # executes on the bar after the signal (i.e., one bar later than a
    # first-breakout entry, as the course requires).
    g = df.groupby("ticker", group_keys=False)
    prev_was_rebreakout = (is_breakout & ~is_first).groupby(df["ticker"]).shift(1).fillna(False)
    prev_had_ma60 = has_ma60.groupby(df["ticker"]).shift(1).fillna(False)
    prev_not_breakdown = not_in_breakdown.groupby(df["ticker"]).shift(1).fillna(False)
    is_attack = df["is_attack_bar"].fillna(False)

    rebreakout_signal = (
        prev_was_rebreakout
        & prev_had_ma60
        & prev_not_breakdown
        & is_attack
        & has_ma60
        & not_in_breakdown
    )

    return (first_breakout_signal | rebreakout_signal).fillna(False)
