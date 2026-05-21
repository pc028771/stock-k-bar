"""Non-course extras — optional filters and toggles. Default OFF.

See `README.md` in this directory. CLAUDE.md mandates that any non-course
condition lives here, separated from `entry/`, `exit/`, `scoring/`.

## Registries

Three registries, one per kind. Each registry maps `name` → factory that
takes an optional string arg (from CLI `name=arg`) and returns the actual
callable.

  ENTRY_FILTER_REGISTRY: arg → callable(df, entries) -> entries
  EXIT_REGISTRY:         arg → callable(df, entries) -> bool Series
  SCORING_REGISTRY:      arg → callable(df)         -> float Series

(Currently no scoring extras; placeholder kept for future moves.)

## Parsing

`parse_extras_spec("intensity_floor=2,hold_days_cap=20")` returns
`[("intensity_floor", "2"), ("hold_days_cap", "20")]`.
"""
from __future__ import annotations

from . import (
    attack_quality_anti_course_penalties,
    consolidation_breakdown,
    gap_fill_excess_market_adjusted,
    hold_days_cap,
    inst_direction_score,
    intensity_floor,
    neckline_break_crude,
    shakeout_strong,
    strict_breakout,
)


def _strict_breakout_factory(_arg: str | None):
    # Existing strict_breakout has no arg; wrap to match factory signature.
    def apply(df, entries):
        return entries & strict_breakout.filter(df).reindex(df.index).fillna(False)
    apply.__name__ = "strict_breakout"
    return apply


ENTRY_FILTER_REGISTRY = {
    "intensity_floor": intensity_floor.make_filter,
    "strict_breakout": _strict_breakout_factory,
}

EXIT_REGISTRY = {
    "hold_days_cap": hold_days_cap.make_mark,
    # Moved from scripts/kline/exit/ — non-course detectors (audit C2/C3/C7).
    "gap_fill_excess_market_adjusted": gap_fill_excess_market_adjusted.make_mark,
    "neckline_break_crude_proxy": neckline_break_crude.make_mark,
    "consolidation_breakdown": consolidation_breakdown.make_mark,
}

SCORING_REGISTRY: dict = {
    # Moved from scripts/kline/scoring/attack_quality.py (audit C4).
    # Split (audit option B): the course-aligned +25 trend_days contribution
    # is now scoring/trend_continuation.py (default ON). This module retains
    # only the three anti-course penalties (volume_ratio, body_pct, close_pos).
    "attack_quality_anti_course_penalties": attack_quality_anti_course_penalties.make_score,
    # User-created inst-direction tiebreaker for shakeout_strong (NOT course-defined).
    "inst_direction_score": inst_direction_score.score,
}

# --- Shakeout Strong strategy registries (user-created, NOT course-defined) ---
# These are separate from ENTRY_FILTER_REGISTRY / EXIT_REGISTRY / SCORING_REGISTRY
# because shakeout_strong is a full entry *strategy* (not a filter on top of course entries).

ENTRY_STRATEGY_REGISTRY: dict = {
    "shakeout_strong": shakeout_strong.detect,
}

INST_SCORING_REGISTRY: dict = {
    "inst_direction_score": inst_direction_score.score,
}


def parse_extras_spec(spec: str | None) -> list[tuple[str, str | None]]:
    """Parse '--extras' CLI value: 'name[=arg],name[=arg],...' → list of pairs.

    Empty / None → [].
    """
    if not spec:
        return []
    out: list[tuple[str, str | None]] = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        if "=" in token:
            name, arg = token.split("=", 1)
            out.append((name.strip(), arg.strip()))
        else:
            out.append((token, None))
    return out


def resolve_extras(spec: str | None) -> dict:
    """Resolve --extras spec into ready-to-use callables, grouped by kind.

    Returns dict with keys: 'entry_filters', 'exits', 'scoring',
    each a list of (extras-prefixed name, callable).

    Raises ValueError if a name is unknown.
    """
    entry_filters: list[tuple[str, callable]] = []
    exits: list[tuple[str, callable]] = []
    scoring: list[tuple[str, callable]] = []

    for name, arg in parse_extras_spec(spec):
        full = f"extras.{name}"
        if name in ENTRY_FILTER_REGISTRY:
            entry_filters.append((full, ENTRY_FILTER_REGISTRY[name](arg)))
        elif name in EXIT_REGISTRY:
            exits.append((full, EXIT_REGISTRY[name](arg)))
        elif name in SCORING_REGISTRY:
            scoring.append((full, SCORING_REGISTRY[name](arg)))
        else:
            known = (
                list(ENTRY_FILTER_REGISTRY)
                + list(EXIT_REGISTRY)
                + list(SCORING_REGISTRY)
            )
            raise ValueError(f"Unknown extra: {name!r}. Known: {known}")

    return {"entry_filters": entry_filters, "exits": exits, "scoring": scoring}


__all__ = [
    "ENTRY_FILTER_REGISTRY",
    "EXIT_REGISTRY",
    "SCORING_REGISTRY",
    "ENTRY_STRATEGY_REGISTRY",
    "INST_SCORING_REGISTRY",
    "parse_extras_spec",
    "resolve_extras",
]
