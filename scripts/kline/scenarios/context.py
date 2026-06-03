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
- 大盤創紀錄跌點欄位（taiex_record_drop_point / taiex_record_drop_pct /
  taiex_record_limit_down_count / taiex_no_new_low_next_day）由
  ``_TaiexContext`` 從 taiex_history.sqlite + limit_down_history.sqlite 讀取，
  亦可透過 overrides 注入（測試用）。
  若 DB 不存在，欄位為 None + warn（fail-loud，不 crash）。
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

from ._schema import ContextSnapshot

# ---------------------------------------------------------------------------
# TAIEX / Limit-down DB paths
# ---------------------------------------------------------------------------
_WORKTREE = Path(__file__).resolve().parents[3]
_TAIEX_DB = _WORKTREE / "data/analysis/kline_patterns/taiex_history.sqlite"
_LIMIT_DOWN_DB = _WORKTREE / "data/analysis/kline_patterns/limit_down_history.sqlite"


class _TaiexContext:
    """Lazy-loaded helper that computes the four §30 大盤欄位.

    Loads taiex_daily + limit_down_daily once per process and caches them in
    class-level attributes.  If either DB is missing, the corresponding fields
    return None.
    """

    _taiex_df: "pd.DataFrame | None" = None
    _ld_df: "pd.DataFrame | None" = None
    _loaded: bool = False

    @classmethod
    def _load(cls) -> None:
        if cls._loaded:
            return
        cls._loaded = True  # mark early to avoid re-entrant loads
        # TAIEX
        if _TAIEX_DB.exists():
            try:
                conn = sqlite3.connect(str(_TAIEX_DB))
                df = pd.read_sql_query(
                    "SELECT trade_date, open, high, low, close FROM taiex_daily ORDER BY trade_date",
                    conn,
                )
                conn.close()
                cls._taiex_df = df
            except Exception as e:
                cls._taiex_df = None
                print(f"WARN: _TaiexContext failed to load taiex DB: {e}")
        # Limit-down
        if _LIMIT_DOWN_DB.exists():
            try:
                conn = sqlite3.connect(str(_LIMIT_DOWN_DB))
                df = pd.read_sql_query(
                    "SELECT trade_date, limit_down_count FROM limit_down_daily ORDER BY trade_date",
                    conn,
                )
                conn.close()
                cls._ld_df = df
            except Exception as e:
                cls._ld_df = None
                print(f"WARN: _TaiexContext failed to load limit_down DB: {e}")

    @classmethod
    def compute(cls, today_date: str) -> dict[str, Optional[bool]]:
        """Return dict of the four taiex §30 fields for *today_date*.

        All four fields are Optional[bool].  Returns None for any field whose
        source data is unavailable.

        Fields:
          taiex_record_drop_point     — today's point drop is historical max
          taiex_record_drop_pct       — today's pct drop is historical max
          taiex_record_limit_down_count — today's limit-down count is historical max
          taiex_no_new_low_next_day   — tomorrow's low > today's low (進場確認)
        """
        cls._load()
        result: dict[str, Optional[bool]] = {
            "taiex_record_drop_point": None,
            "taiex_record_drop_pct": None,
            "taiex_record_limit_down_count": None,
            "taiex_no_new_low_next_day": None,
        }

        if cls._taiex_df is not None and not cls._taiex_df.empty:
            tdf = cls._taiex_df.copy()
            tdf["prev_close"] = tdf["close"].shift(1)
            tdf["drop_point"] = tdf["prev_close"] - tdf["close"]  # positive = drop
            tdf["drop_pct"] = tdf["drop_point"] / tdf["prev_close"]

            today_mask = tdf["trade_date"] == today_date
            if today_mask.any():
                idx = tdf.index[today_mask][0]
                today_row = tdf.loc[idx]

                # All historical rows BEFORE today
                hist = tdf.loc[:idx - 1] if idx > 0 else tdf.iloc[0:0]

                # taiex_record_drop_point: today drop_point > historical max drop_point
                if pd.notna(today_row["drop_point"]) and not hist.empty and hist["drop_point"].notna().any():
                    result["taiex_record_drop_point"] = bool(
                        today_row["drop_point"] > hist["drop_point"].max()
                    )

                # taiex_record_drop_pct: today drop_pct > historical max drop_pct
                if pd.notna(today_row["drop_pct"]) and not hist.empty and hist["drop_pct"].notna().any():
                    result["taiex_record_drop_pct"] = bool(
                        today_row["drop_pct"] > hist["drop_pct"].max()
                    )

                # taiex_no_new_low_next_day: next trading day low > today low
                next_rows = tdf.loc[idx + 1:]
                if not next_rows.empty:
                    next_row = next_rows.iloc[0]
                    if pd.notna(today_row["low"]) and pd.notna(next_row["low"]):
                        result["taiex_no_new_low_next_day"] = bool(
                            next_row["low"] > today_row["low"]
                        )

        if cls._ld_df is not None and not cls._ld_df.empty:
            ld = cls._ld_df.copy()
            today_ld_mask = ld["trade_date"] == today_date
            if today_ld_mask.any():
                idx = ld.index[today_ld_mask][0]
                today_count = ld.loc[idx, "limit_down_count"]
                hist_ld = ld.loc[:idx - 1] if idx > 0 else ld.iloc[0:0]
                if not hist_ld.empty and hist_ld["limit_down_count"].notna().any():
                    result["taiex_record_limit_down_count"] = bool(
                        today_count > hist_ld["limit_down_count"].max()
                    )

        # Composite: any one of the three record flags is True
        # 老師原話：「只要有其中一項」
        three = [
            result["taiex_record_drop_point"],
            result["taiex_record_drop_pct"],
            result["taiex_record_limit_down_count"],
        ]
        if any(v is True for v in three):
            result["taiex_record_any_criterion"] = True
        elif all(v is False for v in three):
            result["taiex_record_any_criterion"] = False
        # else: at least one is None → composite remains None

        return result

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
    # 4b. Resolve taiex §30 fields (from DB or overrides)
    # ------------------------------------------------------------------
    _TAIEX_FIELDS = [
        "taiex_record_drop_point",
        "taiex_record_drop_pct",
        "taiex_record_limit_down_count",
        "taiex_record_any_criterion",
        "taiex_no_new_low_next_day",
    ]

    # If any of the four taiex fields is in overrides, use overrides only
    # (test injection path — no DB load needed).
    _taiex_all_in_overrides = all(f in overrides for f in _TAIEX_FIELDS)
    if _taiex_all_in_overrides:
        taiex_vals = {f: overrides[f] for f in _TAIEX_FIELDS}
    else:
        # Load from DB; overrides can still override individual fields
        db_vals = _TaiexContext.compute(today_date)
        taiex_vals = {}
        for f in _TAIEX_FIELDS:
            if f in overrides:
                taiex_vals[f] = overrides[f]
            else:
                val = db_vals.get(f)
                if val is None:
                    warn_notes.append(
                        f"WARN: ContextSnapshot field '{f}' is None "
                        f"(taiex/limit_down DB missing or date not found for {today_date!r})"
                    )
                taiex_vals[f] = val

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
        # --- 大盤創紀錄跌點 §30 (taiex DB) ---
        taiex_record_drop_point=taiex_vals["taiex_record_drop_point"],
        taiex_record_drop_pct=taiex_vals["taiex_record_drop_pct"],
        taiex_record_limit_down_count=taiex_vals["taiex_record_limit_down_count"],
        taiex_record_any_criterion=taiex_vals["taiex_record_any_criterion"],
        taiex_no_new_low_next_day=taiex_vals["taiex_no_new_low_next_day"],
    )

    return snapshot, warn_notes
