"""剛創新高上影線低點跌破 — exit (短線交易者停損).

Course source: K線力量入門 §49 多頭買在攻擊
  Article: 6D17631B248875335336FB18486AF294
  File: docs/K線力量判斷入門/articles/6D17631B248875335336FB18486AF294_49-股價的買點決策(三)多頭買在攻擊.md

Course quote (逐字):
  「剛創新高的上影線低點作為短線交易者的停損位置」

Concept distinct from `breakout_low_break`:
  - `breakout_low_break` 以「突破紅 K 低點」為停損；
  - 本 exit 以「剛創新高上影線那一根 K 的低點」為停損 — 老師 §49 明示
    上影線雖然「攻擊力量未消失」，但若連這根的低點都跌破 = 攻擊瓦解。
  - 此 exit 配對的進場 = `just_high_upper_shadow` light（剛創新高上影線
    被視為攻擊型態之一）。

Implementation:
  - 找到 entry 後最近一次「剛創新高的上影線 K」的低點 (just_high_upper_shadow_low)
  - 後續任一日 close < 此低點 → 停損訊號
  - 若 entry 後從未出現「剛創新高的上影線 K」→ 不啟動本 exit（不誤觸）

Required df columns: ticker, close, low, is_just_broke_high, upper_shadow,
                     lower_shadow, body_abs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _is_just_high_upper_shadow(df: pd.DataFrame) -> pd.Series:
    """Identify bars that are '剛創新高的上影線 K'.

    Definition (aligned with features.py prev_bar_had_attack_meaning cond_b):
      - high reached prior_high_60 (intraday) → is_just_broke_high_intraday
      - upper_shadow > body_abs (上影線為主)
      - upper_shadow > lower_shadow (上影線顯著於下影線)
    """
    intraday = df.get("is_just_broke_high_intraday")
    if intraday is None:
        intraday = df.get("is_just_broke_high")
    if intraday is None:
        return pd.Series(False, index=df.index)
    intraday = intraday.fillna(False).astype(bool)

    body = df["body_abs"].replace(0, np.nan)
    upper_dominant = (df["upper_shadow"] > body) & (df["upper_shadow"] > df["lower_shadow"])
    return (intraday & upper_dominant).fillna(False)


def mark(df: pd.DataFrame, entries: pd.Series) -> pd.Series:
    """Returns bool Series. True = close fell below the latest 「剛創新高上影線 K」low.

    Per trade (delineated by entries):
      shadow_low = expanding max of (low on bars where is_just_high_upper_shadow=True
                                     since entry, else NaN)
      Note: we use the *earliest occurring* such low — but expanding-max gives
      the most-recent-elevated low. Course intends "the upper-shadow bar that
      defines the just-created high" — use rolling forward-fill of the low at
      each trigger bar.
    """
    if entries is None or entries.sum() == 0:
        return pd.Series(False, index=df.index)

    flag = _is_just_high_upper_shadow(df)
    # The "stop low" = low on flag-True bars; else NaN
    shadow_low_at_event = df["low"].where(flag, other=np.nan)

    # Per-trade forward-fill: within each trade, take the latest shadow_low_at_event
    trade_id = entries.groupby(df["ticker"]).cumsum()
    trade_id = trade_id.where(trade_id > 0)
    if trade_id.isna().all():
        return pd.Series(False, index=df.index)

    work = df.assign(_tid=trade_id, _slow=shadow_low_at_event)
    # Forward-fill within (ticker, _tid) group
    ffilled = (
        work.groupby(["ticker", "_tid"])["_slow"]
        .ffill()
        .reindex(df.index)
    )
    return (df["close"] < ffilled).fillna(False)
