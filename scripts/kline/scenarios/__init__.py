"""scripts/kline/scenarios — Playbook / Scenario Advisor layer.

Public API re-exported from ``_schema``.  Downstream code should import
from this package rather than from ``_schema`` directly::

    from scripts.kline.scenarios import Playbook, Branch, AdvisorResult
"""

from ._schema import (
    Action,
    ActionType,
    AdvisorResult,
    Branch,
    ConfirmAt,
    ContextSnapshot,
    CourseCitation,
    Light,
    PatternHit,
    Playbook,
    PlaybookSetup,
    Scenario,
    Severity,
)

__all__ = [
    "Action",
    "ActionType",
    "AdvisorResult",
    "Branch",
    "ConfirmAt",
    "ContextSnapshot",
    "CourseCitation",
    "Light",
    "PatternHit",
    "Playbook",
    "PlaybookSetup",
    "Scenario",
    "Severity",
]
