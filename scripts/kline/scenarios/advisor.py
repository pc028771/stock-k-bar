"""Scenario Advisor — main entry point for the playbook layer.

Public API
----------
- ``analyze(bars_df, today_date, ticker, ...)`` → ``AdvisorResult``

Design notes
------------
- Pure function — no side effects, no DB writes (persistence is Task 1.6).
- fires patterns via ``PATTERN_REGISTRY`` from ``scripts/kline/patterns``.
- ContextSnapshot fields are built from today's enriched row + context_overrides.
  Missing feature columns → field stays None + notes warn (fail-loud per
  feedback_no_silent_imputation; NOT silent imputation).
- Playbooks are loaded from default dirs each call (fast; no global cache needed
  at this stage).  Default dirs: ``scripts/kline/scenarios/playbooks/`` and
  ``scripts/kline/scenarios/lights/``.
- Branch when-conditions that reference ``next_day.*`` return None (pending) in
  scalar mode; such branches are included in ``enabled_branches`` (marked pending)
  so downstream (simulator) can verify later.

Performance
-----------
Target: < 200 ms per single ticker × single date call.
Loop over 24 patterns is O(1) (constant patterns × O(bars) detect pass).
Most cost is in ``add_features`` if df is raw (≈ 100–150 ms for 300-row df);
advisor detects enriched vs raw by checking for a sentinel feature column.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from ..features import add_features
from ..patterns import PATTERN_REGISTRY
from ._schema import (
    AdvisorResult,
    ContextSnapshot,
    Light,
    PatternHit,
    Scenario,
)
from .condition import UnknownTokenError, evaluate
from .context import build_context_snapshot as _build_context_snapshot_external
from .loader import LoaderError, load_lights, load_playbooks
from .manual_hints import check_defensive_stance_hint, check_record_decline_rebound_hint

# ---------------------------------------------------------------------------
# Sentinel column: if this is absent the df needs add_features() first.
# We use a column that add_features() always produces.
# ---------------------------------------------------------------------------
_FEATURES_SENTINEL = "prev_close"

# ---------------------------------------------------------------------------
# Default playbook / light directories
# ---------------------------------------------------------------------------
_SCENARIOS_DIR = Path(__file__).parent
_DEFAULT_PLAYBOOK_DIRS = [_SCENARIOS_DIR / "playbooks"]
_DEFAULT_LIGHT_DIRS = [_SCENARIOS_DIR / "lights"]

# ---------------------------------------------------------------------------
# Severity sort order for active_lights (critical → warn → info)
# ---------------------------------------------------------------------------
_SEVERITY_ORDER = {"critical": 0, "warn": 1, "info": 2}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_features(df: pd.DataFrame) -> pd.DataFrame:
    """Return a features-enriched DataFrame.

    If ``df`` already contains the sentinel feature column (``prev_close``),
    it is returned as-is to avoid double-enrichment.  Otherwise,
    ``add_features`` is called on a copy.
    """
    if _FEATURES_SENTINEL in df.columns:
        return df
    return add_features(df)


def _build_context_snapshot(
    row: pd.Series,
    overrides: dict | None,
    notes: list[str],
) -> ContextSnapshot:
    """Build a ContextSnapshot from today's enriched row + overrides.

    Fields that features.py does NOT produce (attack_cost, defensive_low,
    ma*_will_rise, etc.) default to None unless provided via overrides.
    Each missing required field that a branch depends on is warned
    at eval time (not here), per fail-loud principle.

    Parameters
    ----------
    row:
        pd.Series for today's bar (already features-enriched).
    overrides:
        Optional dict of field name → value to inject / override.
    notes:
        Mutable list; warnings appended here.

    Returns
    -------
    ContextSnapshot
    """
    overrides = overrides or {}

    # Helper: get field from overrides first, then row, else None.
    def _get(field: str):
        if field in overrides:
            return overrides[field]
        val = row.get(field)
        # Convert numpy scalars / NaN → Python None
        if val is None:
            return None
        try:
            import math
            if math.isnan(float(val)):
                return None
        except (TypeError, ValueError):
            pass
        return val

    # Build the snapshot field by field.
    # Features.py does NOT produce ma*_will_rise, attack_cost, etc. —
    # those must come from overrides.
    snapshot = ContextSnapshot(
        ma5_will_rise=_get("ma5_will_rise"),
        ma10_will_rise=_get("ma10_will_rise"),
        ma20_will_rise=_get("ma20_will_rise"),
        ma60_will_rise=_get("ma60_will_rise"),
        attack_cost=_get("attack_cost"),
        defensive_low=_get("defensive_low"),
        attack_intent_zone_high=_get("attack_intent_zone_high"),
        attack_intent_zone_low=_get("attack_intent_zone_low"),
        is_just_broke_high=_get("is_just_broke_high"),
        is_limit_up_locked=_get("is_limit_up_locked"),
        is_anomalous_volume=_get("is_anomalous_volume"),
    )
    return snapshot


def _collect_fired_patterns(
    enriched_df: pd.DataFrame,
    today_date: str,
    ticker: str,
    notes: list[str],
) -> list[PatternHit]:
    """Run all PATTERN_REGISTRY detectors and return PatternHit list for today.

    Design: simple loop over 24 patterns (not parallel — Python GIL + small N
    makes threading overhead worse; pandas operations are already vectorized).
    Each detector receives the full enriched_df for the ticker to allow
    lookback windows.  We then check today's row.

    Parameters
    ----------
    enriched_df:
        Features-enriched DataFrame filtered to ``ticker`` only.
    today_date:
        'YYYY-MM-DD' string.
    ticker:
        Ticker symbol (for PatternHit metadata).
    notes:
        Mutable list; warnings appended here.

    Returns
    -------
    list[PatternHit]
        One entry per pattern that fired True on ``today_date``.
    """
    hits: list[PatternHit] = []

    for pattern_name, detect_fn in PATTERN_REGISTRY.items():
        try:
            fired_series: pd.Series = detect_fn(enriched_df)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"WARN: pattern {pattern_name!r} raised during detect: {exc}")
            continue

        # Check today's date in the result index / column
        if "trade_date" in enriched_df.columns:
            mask = enriched_df["trade_date"] == today_date
            today_values = fired_series[mask]
        elif isinstance(enriched_df.index, pd.DatetimeIndex):
            today_values = fired_series[fired_series.index == today_date]
        else:
            # Fall back: try matching string index
            today_values = fired_series[fired_series.index.astype(str) == today_date]

        if today_values.empty:
            notes.append(
                f"WARN: pattern {pattern_name!r}: today_date {today_date!r} not found in df"
            )
            continue

        if bool(today_values.iloc[0]):
            hits.append(
                PatternHit(
                    pattern=pattern_name,
                    fired_at=today_date,
                    confidence=None,
                )
            )

    return hits


def _build_scenarios(
    fired_patterns: list[PatternHit],
    playbooks_by_pattern: dict,
    today_row: pd.Series,
    ctx: ContextSnapshot,
    notes: list[str],
) -> list[Scenario]:
    """Map fired patterns to scenarios by finding matching playbooks.

    For each fired pattern:
    1. Look up playbook(s) for that pattern.
    2. Filter playbooks by required_context (skip if ContextSnapshot lacks it).
    3. Evaluate each branch's when-condition (scalar mode).
    4. Collect enabled_branch ids (True or None/pending).

    Parameters
    ----------
    fired_patterns:
        List of PatternHit from ``_collect_fired_patterns``.
    playbooks_by_pattern:
        Dict[str, List[Playbook]] from loader.load_playbooks.
    today_row:
        pd.Series for today's enriched bar.
    ctx:
        ContextSnapshot for today.
    notes:
        Mutable list; warnings appended here.

    Returns
    -------
    list[Scenario]
    """
    scenarios: list[Scenario] = []

    for hit in fired_patterns:
        playbook_list = playbooks_by_pattern.get(hit.pattern, [])
        if not playbook_list:
            continue

        for playbook in playbook_list:
            # --- Check required_context ---
            skip_playbook = False
            for req_ctx_field in playbook.setup.required_context:
                ctx_val = getattr(ctx, req_ctx_field, None)
                if ctx_val is None:
                    notes.append(
                        f"WARN: playbook '{playbook.setup.name}' skipped — "
                        f"required context '{req_ctx_field}' is None"
                    )
                    skip_playbook = True
                    break
            if skip_playbook:
                continue

            # --- Evaluate each branch ---
            enabled_branch_ids: list[str] = []
            for branch in playbook.branches:
                try:
                    result = evaluate(
                        when=branch.when,
                        row=today_row,
                        ctx=ctx,
                        next_day_n=branch.next_day_n,
                    )
                except UnknownTokenError as exc:
                    notes.append(
                        f"WARN: branch '{branch.id}' condition error: {exc}"
                    )
                    continue

                # True = condition met today; None = pending (next_day.* unknown)
                # False = condition not met → exclude
                if result is True or result is None:
                    enabled_branch_ids.append(branch.id)

            if enabled_branch_ids:
                scenarios.append(
                    Scenario(
                        pattern_hit=hit,
                        playbook_name=playbook.setup.name,
                        enabled_branches=enabled_branch_ids,
                    )
                )

    return scenarios


def _evaluate_lights(
    lights: dict,
    today_row: pd.Series,
    ctx: ContextSnapshot,
    notes: list[str],
) -> list[Light]:
    """Evaluate all lights against today's row and return active ones.

    Active = trigger_condition evaluates to True.

    Semantic note (2026-06-04):
      Previously None/pending was also treated as active to handle next_day.*
      pending semantics. But this caused lights referencing toplevel context
      fields (attack_cost, defensive_low, merged_high/low) to always fire when
      those fields were None (not yet populated). Since no current light uses
      next_day.* in its trigger_condition, None now skips (data-missing
      semantic). If a future light needs pending semantics, handle it
      explicitly.

    Sorted by severity: critical → warn → info.

    Parameters
    ----------
    lights:
        Dict[str, Light] from loader.load_lights.
    today_row:
        pd.Series for today's enriched bar.
    ctx:
        ContextSnapshot.
    notes:
        Mutable list; warnings appended here.

    Returns
    -------
    list[Light] — active lights sorted by severity
    """
    active: list[Light] = []

    for light_id, light in lights.items():
        try:
            result = evaluate(
                when=light.trigger_condition,
                row=today_row,
                ctx=ctx,
                next_day_n=1,
            )
        except UnknownTokenError as exc:
            notes.append(f"WARN: light '{light_id}' condition error: {exc}")
            continue

        if result is True:
            active.append(light)

    # Sort critical → warn → info
    active.sort(key=lambda l: _SEVERITY_ORDER.get(l.severity, 99))
    return active


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze(
    bars_df: pd.DataFrame,
    today_date: str,
    ticker: str,
    context_overrides: dict | None = None,
    playbook_dirs: list[Path] | None = None,
    light_dirs: list[Path] | None = None,
) -> AdvisorResult:
    """Analyze a single ticker × single date and return an AdvisorResult.

    Parameters
    ----------
    bars_df:
        OHLCV DataFrame.  May be raw (will be enriched by add_features) or
        already features-enriched.  Must contain a ``ticker`` column (or be
        pre-filtered to a single ticker).  Must contain either a ``trade_date``
        column or a DatetimeIndex.
    today_date:
        Target date as 'YYYY-MM-DD' string.
    ticker:
        Ticker symbol to analyze.
    context_overrides:
        Optional dict of ContextSnapshot field → value to inject.  These
        override anything computed from the df (Phase 1: broker/ch2/MA will-rise
        fields all live here until Phase 4 wires real sources).
    playbook_dirs:
        Directories to scan for playbook YAML files.  Defaults to
        ``scripts/kline/scenarios/playbooks/``.
    light_dirs:
        Directories to scan for light YAML files.  Defaults to
        ``scripts/kline/scenarios/lights/``.

    Returns
    -------
    AdvisorResult
        Contains fired_patterns, scenarios, active_lights, notes, and the
        context_snapshot used.

    Raises
    ------
    LoaderError
        If any YAML file fails Pydantic schema validation (fail loud).
    ValueError
        If ticker not found in bars_df or today_date not found.
    """
    notes: list[str] = []

    # ------------------------------------------------------------------
    # 1. Ensure features are present
    # ------------------------------------------------------------------
    enriched_df = _ensure_features(bars_df)

    # ------------------------------------------------------------------
    # 2. Filter to ticker
    # ------------------------------------------------------------------
    if "ticker" in enriched_df.columns:
        ticker_df = enriched_df[enriched_df["ticker"] == ticker].copy()
    else:
        # Assume caller pre-filtered; add ticker column for pattern detectors
        ticker_df = enriched_df.copy()
        ticker_df["ticker"] = ticker

    if ticker_df.empty:
        raise ValueError(f"ticker {ticker!r} not found in bars_df")

    # ------------------------------------------------------------------
    # 3. Extract today's row
    # ------------------------------------------------------------------
    if "trade_date" in ticker_df.columns:
        today_mask = ticker_df["trade_date"] == today_date
        today_rows = ticker_df[today_mask]
    else:
        today_rows = ticker_df[ticker_df.index.astype(str) == today_date]

    if today_rows.empty:
        raise ValueError(
            f"today_date {today_date!r} not found for ticker {ticker!r}"
        )

    today_row: pd.Series = today_rows.iloc[0]

    # ------------------------------------------------------------------
    # 4. Build ContextSnapshot
    # ------------------------------------------------------------------
    # Delegate to context.py (Task 1.5 extract).
    # Pass a single-row df (ticker_df filtered to today) so context.py can
    # do its own ticker/date validation — but we already validated above,
    # so this won't raise.  We pass ticker_df (full ticker history) so
    # context.py can locate today's row itself.
    ctx, ctx_warns = _build_context_snapshot_external(
        ticker_df, today_date, ticker, overrides=context_overrides
    )
    notes.extend(ctx_warns)

    # ------------------------------------------------------------------
    # 5. Collect fired patterns (loop over PATTERN_REGISTRY)
    # ------------------------------------------------------------------
    fired_patterns = _collect_fired_patterns(ticker_df, today_date, ticker, notes)

    # ------------------------------------------------------------------
    # 6. Load playbooks + lights (fail loud on schema error)
    # ------------------------------------------------------------------
    pb_dirs = playbook_dirs if playbook_dirs is not None else _DEFAULT_PLAYBOOK_DIRS
    lt_dirs = light_dirs if light_dirs is not None else _DEFAULT_LIGHT_DIRS

    # LoaderError propagates up (fail loud per spec)
    playbooks_by_pattern = load_playbooks(pb_dirs)
    lights = load_lights(lt_dirs)

    # ------------------------------------------------------------------
    # 7. Build scenarios from fired patterns × playbooks
    # ------------------------------------------------------------------
    scenarios = _build_scenarios(
        fired_patterns, playbooks_by_pattern, today_row, ctx, notes
    )

    # ------------------------------------------------------------------
    # 8. Evaluate lights
    # ------------------------------------------------------------------
    active_lights = _evaluate_lights(lights, today_row, ctx, notes)

    # ------------------------------------------------------------------
    # 9. Collect manual-judgment hints (§26 defensive_stance, §30 record_decline_rebound)
    # ------------------------------------------------------------------
    manual_hints: list[dict] = []
    for hint_fn in (check_defensive_stance_hint, check_record_decline_rebound_hint):
        hint = hint_fn(today_row, ctx)
        if hint is not None:
            manual_hints.append(hint)

    # ------------------------------------------------------------------
    # 10. Assemble AdvisorResult
    # ------------------------------------------------------------------
    return AdvisorResult(
        fired_patterns=fired_patterns,
        scenarios=scenarios,
        active_lights=active_lights,
        notes=notes,
        context_snapshot=ctx,
        manual_hints=manual_hints,
    )
