"""Context snapshot builder — Task 1.5.

Responsibility
--------------
Build a ``ContextSnapshot`` from a features-enriched DataFrame row + optional
overrides dict.  This module is the single source of truth for:

1. Which feature columns map to which ContextSnapshot fields.
2. Which fields require ``overrides`` injection (broker / teacher / ch2 / sector
   — Phase 4 will wire real sources; Phase 1 uses overrides only).
3. Fail-loud behaviour for missing fields: each ``None`` field appended to
   ``warn_notes`` but does NOT crash (per feedback_no_silent_imputation,
   missing fields must be reported, not silently patched).

Public API
----------
::

    snapshot, warn_notes = build_context_snapshot(bars_df, today_date, ticker)
    snapshot, warn_notes = build_context_snapshot(bars_df, today_date, ticker,
                                                   overrides={"broker_tier1_buy": True})

Notes
-----
- Fields absent from ``bars_df`` → ``None`` (with warn).
- NaN values are treated as missing → ``None`` (with warn).
- ``overrides`` always wins over the df value; no warn is emitted for
  override-injected fields (the caller is responsible for providing them).
- Do NOT add computation / inference for missing values — that violates
  ``feedback_no_silent_imputation``.
"""

from __future__ import annotations

import math
from typing import Optional

import pandas as pd

from ._schema import ContextSnapshot

# ---------------------------------------------------------------------------
# Fields sourced from features.py columns (extracted, NOT re-computed)
# ---------------------------------------------------------------------------

# These fields come from features.py enriched df.
# If absent or NaN → None + warn.
_FEATURES_FIELDS: list[str] = [
    "attack_cost",
    "attack_intent_zone_high",
    "attack_intent_zone_low",
    "defensive_low",
    "ma5_will_rise",
    "ma10_will_rise",
    "ma20_will_rise",
    "ma60_will_rise",
    "prior_high_60",
    "prior_low_60",
    "is_just_broke_high",
    "is_limit_up_locked",
    "is_anomalous_volume",
    # merged_* fields (variable set depending on features.py version)
    # included dynamically via _MERGED_PREFIX below
]

_MERGED_PREFIX = "merged_"

# ---------------------------------------------------------------------------
# Fields that MUST come from overrides in Phase 1
# (broker / teacher / ch2 / sector — no features.py source yet)
# ---------------------------------------------------------------------------

_OVERRIDES_ONLY_FIELDS: list[str] = [
    "broker_tier1_buy",
    "teacher_tier",
    "broker_concentration",
    "ch2_warning_score",
    "sector_consensus_direction",
]


def _scalar(val: object) -> object:
    """Convert numpy scalar / NaN → Python None; pass through other values."""
    if val is None:
        return None
    try:
        if math.isnan(float(val)):  # type: ignore[arg-type]
            return None
    except (TypeError, ValueError):
        pass
    return val


def build_context_snapshot(
    bars_df: pd.DataFrame,
    today_date: str,
    ticker: str,
    overrides: dict | None = None,
) -> tuple[ContextSnapshot, list[str]]:
    """Build a ContextSnapshot for *ticker* on *today_date*.

    Parameters
    ----------
    bars_df:
        Features-enriched DataFrame.  Must contain a ``ticker`` column (or be
        pre-filtered to a single ticker) and a ``trade_date`` column (or a
        DatetimeIndex).
    today_date:
        Target date as ``'YYYY-MM-DD'`` string.
    ticker:
        Ticker symbol.
    overrides:
        Optional dict of ``ContextSnapshot`` field → value.  These values
        take priority over anything found in ``bars_df``.  Use this for
        broker / teacher / ch2 / sector fields in Phase 1.

    Returns
    -------
    tuple[ContextSnapshot, list[str]]
        ``(snapshot, warn_notes)``  where ``warn_notes`` contains a ``WARN:``
        line for every field that resolved to ``None`` from the df (not from
        overrides).

    Raises
    ------
    ValueError
        If *ticker* is not found in *bars_df*, or *today_date* is not found
        for that ticker.  (fail loud — caller must ensure data is present.)
    """
    overrides = overrides or {}
    warn_notes: list[str] = []

    # ------------------------------------------------------------------
    # 1. Filter to ticker
    # ------------------------------------------------------------------
    if "ticker" in bars_df.columns:
        ticker_df = bars_df[bars_df["ticker"] == ticker]
    else:
        ticker_df = bars_df

    if ticker_df.empty:
        raise ValueError(f"ticker {ticker!r} not found in bars_df")

    # ------------------------------------------------------------------
    # 2. Extract today's row
    # ------------------------------------------------------------------
    if "trade_date" in ticker_df.columns:
        today_rows = ticker_df[ticker_df["trade_date"] == today_date]
    else:
        today_rows = ticker_df[ticker_df.index.astype(str) == today_date]

    if today_rows.empty:
        raise ValueError(
            f"today_date {today_date!r} not found for ticker {ticker!r}"
        )

    row: pd.Series = today_rows.iloc[0]

    # ------------------------------------------------------------------
    # 3. Helper: resolve a field (overrides > df > None+warn)
    # ------------------------------------------------------------------
    def _get(field: str, *, warn_if_missing: bool = True) -> object:
        """Resolve field value: overrides > row > None (+warn)."""
        if field in overrides:
            return overrides[field]
        val = _scalar(row.get(field))
        if val is None and warn_if_missing:
            warn_notes.append(
                f"WARN: ContextSnapshot field '{field}' is missing from "
                f"features df for ticker={ticker!r} date={today_date!r}"
            )
        return val

    # ------------------------------------------------------------------
    # 4. Resolve overrides-only fields (no warn when None — Phase 1 expected)
    # ------------------------------------------------------------------
    def _get_override_only(field: str) -> object:
        """Phase 1 fields: only from overrides; no warn if absent."""
        if field in overrides:
            return overrides[field]
        # Not in overrides → None, but warn so caller knows integration pending
        warn_notes.append(
            f"WARN: ContextSnapshot field '{field}' not provided via overrides "
            f"(Phase 4 integration pending); set to None"
        )
        return None

    # ------------------------------------------------------------------
    # 5. Build snapshot
    # ------------------------------------------------------------------
    snapshot = ContextSnapshot(
        # --- Overrides-only fields (broker / teacher / ch2 / sector) ---
        broker_tier1_buy=_get_override_only("broker_tier1_buy"),
        teacher_tier=_get_override_only("teacher_tier"),
        broker_concentration=_get_override_only("broker_concentration"),
        ch2_warning_score=_get_override_only("ch2_warning_score"),
        sector_consensus_direction=_get_override_only("sector_consensus_direction"),
        # --- MA 扣抵 (features.py columns, may be absent pre-Phase 3) ---
        ma5_will_rise=_get("ma5_will_rise"),
        ma10_will_rise=_get("ma10_will_rise"),
        ma20_will_rise=_get("ma20_will_rise"),
        ma60_will_rise=_get("ma60_will_rise"),
        # --- Attack zone / defensive low (C03/C04/C05 features) ---
        attack_cost=_get("attack_cost"),
        defensive_low=_get("defensive_low"),
        attack_intent_zone_high=_get("attack_intent_zone_high"),
        attack_intent_zone_low=_get("attack_intent_zone_low"),
        # --- Current bar status flags ---
        is_just_broke_high=_get("is_just_broke_high"),
        is_limit_up_locked=_get("is_limit_up_locked"),
        is_anomalous_volume=_get("is_anomalous_volume"),
    )

    return snapshot, warn_notes
