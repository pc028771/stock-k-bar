"""MA60 neckline break exit signal — course-precise version.

Course source:
  - 型態學 頭部型態 (complete neckline definition with 3-month overhead supply)
  - K線行進ing 關鍵K線×移動平均線 (季線下彎判定)
  - K線行進ing 事件七 中期持有 (3-month overhead requirement)

Neckline definition (空方):
  1. 季線下彎 (ma60_slope_5d turns from >= 0 to < 0)
  2. The most recent confirmed swing low BEFORE the MA60 downturn
  3. The swing low's price level must have >= 60 trading days of overhead
     pressure (at least one swing-high peak above it in that window)

Exit triggers when close < neckline_price.

This replaces the crude `prior_low_20` proxy used in `neckline_break.py`.

Required df columns: ticker, close, low, high, ma60_slope_5d.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

OVERHEAD_MONTHS_DAYS = 60      # 3 months in trading days


def _detect_swing_lows(low_series: pd.Series) -> pd.Series:
    """Returns bool Series marking 5-bar local minima within a single ticker."""
    is_local_min = (
        (low_series < low_series.shift(1))
        & (low_series < low_series.shift(2))
        & (low_series < low_series.shift(-1))
        & (low_series < low_series.shift(-2))
    )
    return is_local_min.fillna(False)


def _detect_swing_highs(high_series: pd.Series) -> pd.Series:
    """Returns bool Series marking 5-bar local maxima within a single ticker."""
    is_local_max = (
        (high_series > high_series.shift(1))
        & (high_series > high_series.shift(2))
        & (high_series > high_series.shift(-1))
        & (high_series > high_series.shift(-2))
    )
    return is_local_max.fillna(False)


def _has_overhead_supply(
    candidate_price: float,
    candidate_pos: int,
    high_series: pd.Series,
    swing_highs: pd.Series,
    downturn_pos: int,
) -> bool:
    """Check if swing low at candidate_pos has >= 60 days of overhead supply.

    Condition: at least one swing-high peak above candidate_price occurring
    more than OVERHEAD_MONTHS_DAYS bars before the MA60 downturn, and also
    before the swing low itself (套牢 = trapped buyers above the low).

    The overhead window is: bars 0 .. min(candidate_pos, downturn_pos - OVERHEAD_MONTHS_DAYS).
    This ensures peaks occurred BEFORE the swing low and the trapped buyers
    have been waiting >= 3 months.
    """
    overhead_cutoff = min(candidate_pos, downturn_pos - OVERHEAD_MONTHS_DAYS)
    if overhead_cutoff <= 0:
        return False

    # Search all swing highs before the overhead_cutoff
    window_swing_highs = swing_highs.iloc[:overhead_cutoff]
    window_highs = high_series.iloc[:overhead_cutoff]

    return bool((window_swing_highs & (window_highs > candidate_price)).any())


def _find_neckline_for_downturn(
    low_series: pd.Series,
    high_series: pd.Series,
    swing_lows: pd.Series,
    swing_highs: pd.Series,
    downturn_pos: int,
) -> float:
    """Given a MA60 downturn position, find the neckline price.

    Algorithm:
      1. Collect all swing low positions before downturn_pos.
      2. For each candidate swing low (most recent first), verify it has
         >= 60 trading days of overhead supply (a swing high above its price,
         occurring before the swing low AND > OVERHEAD_MONTHS_DAYS bars before
         the downturn).
      3. Return the first qualifying swing low's price, or NaN if none.
    """
    swing_low_positions = np.where(swing_lows.values)[0]
    # Filter to those strictly before downturn_pos
    candidates = swing_low_positions[swing_low_positions < downturn_pos]
    # Iterate from most recent to oldest
    for i in reversed(candidates):
        candidate_price = low_series.iloc[int(i)]
        if _has_overhead_supply(candidate_price, int(i), high_series, swing_highs, downturn_pos):
            return candidate_price

    return float("nan")


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    """Returns bool Series. True = neckline broken on that bar.

    Implementation note: this is a per-ticker iterative algorithm wrapping
    a vectorized core. It is O(n_swing_lows x n_bars) in the worst case,
    but typical case is much faster because most days have no MA60 downturn.
    """
    result = pd.Series(False, index=df.index, dtype=bool)

    for _ticker, grp in df.groupby("ticker", group_keys=False):
        idx = grp.index
        low_s = grp["low"].reset_index(drop=True)
        high_s = grp["high"].reset_index(drop=True)
        close_s = grp["close"].reset_index(drop=True)
        slope = grp["ma60_slope_5d"].reset_index(drop=True)

        # Detect swing points
        swing_lows = _detect_swing_lows(low_s)
        swing_highs = _detect_swing_highs(high_s)

        # Detect MA60 downturn moments: slope transitions from >= 0 to < 0
        prev_slope = slope.shift(1).fillna(0)
        is_downturn = (prev_slope >= 0) & (slope < 0) & slope.notna()
        downturn_positions = np.where(is_downturn)[0]

        if len(downturn_positions) == 0:
            continue

        # Build neckline_series: for each bar, what is the active neckline price?
        neckline_series = pd.Series(float("nan"), index=range(len(grp)))

        for downturn_pos in downturn_positions:
            neckline_price = _find_neckline_for_downturn(
                low_s, high_s, swing_lows, swing_highs, int(downturn_pos)
            )
            if np.isnan(neckline_price):
                continue

            # Apply this neckline from downturn_pos onward, until next downturn
            next_positions = downturn_positions[downturn_positions > downturn_pos]
            end_pos = int(next_positions[0]) if len(next_positions) > 0 else len(grp)
            # Invariant: downturn_positions is monotonically increasing from np.where,
            # so windows [downturn_pos:end_pos] are disjoint — writes don't clobber prior necklines.
            neckline_series.iloc[downturn_pos:end_pos] = neckline_price

        # Mark exit where close < active neckline
        ticker_result = (close_s < neckline_series).fillna(False)
        result.loc[idx] = ticker_result.values

    return result
