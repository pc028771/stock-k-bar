"""Scoring factors for K-line course system.

Public API:
    SCORING_REGISTRY: dict mapping factor name to score(df) function.

External repos can also import individual factors directly:
    from kline.scoring.shadow_position import score
"""
from __future__ import annotations

from . import (
    attack_intensity,
    high_zone_narrow_consolidation,
    ma60_rolloff,
    overhead_supply,
    pattern_breakout,
    shadow_position,
)

SCORING_REGISTRY = {
    "overhead_supply":                  overhead_supply.score,
    "ma60_rolloff":                     ma60_rolloff.score,
    "shadow_position":                  shadow_position.score,
    "pattern_breakout":                 pattern_breakout.score,
    "attack_intensity":                 attack_intensity.score,
    "high_zone_narrow_consolidation":   high_zone_narrow_consolidation.score,
}

__all__ = [
    "SCORING_REGISTRY",
    "attack_intensity", "high_zone_narrow_consolidation",
    "ma60_rolloff", "overhead_supply", "pattern_breakout", "shadow_position",
]
