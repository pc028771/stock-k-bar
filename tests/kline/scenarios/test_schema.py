"""Tests for scripts/kline/scenarios/_schema.py — Task 1.1.

T1.1.1  CourseCitation.source < 5 chars → ValidationError
T1.1.2  Action without course_citation → ValidationError
T1.1.3  Branch.next_day_n > 3 → ValidationError
T1.1.4  Light.severity not in whitelist → ValidationError
T1.1.5  Playbook full round-trip (dict → model → model_dump() structure matches)
"""

import pytest
from pydantic import ValidationError

from scripts.kline.scenarios import (
    Action,
    AdvisorResult,
    Branch,
    ContextSnapshot,
    CourseCitation,
    Light,
    PatternHit,
    Playbook,
    PlaybookSetup,
    Scenario,
)

# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------


def _valid_citation(**overrides) -> dict:
    base = {"source": "PATTERN_DEFINITIONS §3"}
    base.update(overrides)
    return base


def _valid_action(**overrides) -> dict:
    base = {
        "type": "watch_only",
        "description": "觀察中，等待後續確認",
        "course_citation": _valid_citation(),
    }
    base.update(overrides)
    return base


def _valid_branch(branch_id: str = "B1_test", **overrides) -> dict:
    base = {
        "id": branch_id,
        "when": {"next_day.close": "> today.high"},
        "confirm_at": "next_close",
        "action": _valid_action(),
    }
    base.update(overrides)
    return base


def _valid_playbook(**overrides) -> dict:
    base = {
        "pattern": "bull_engulfing",
        "setup": {"name": "bear_exhaustion_after_engulfing"},
        "branches": [_valid_branch()],
        "course_sources": [_valid_citation(source="明日 K 線 §06 力竭後反彈")],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# T1.1.1 — CourseCitation.source too short
# ---------------------------------------------------------------------------


class TestCourseCitationValidation:
    def test_source_too_short_raises(self):
        """T1.1.1: source with < 5 characters must raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            CourseCitation(source="§3")  # only 2 chars
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("source",) for e in errors)

    def test_source_exactly_5_chars_passes(self):
        """Boundary: exactly 5 chars is valid."""
        c = CourseCitation(source="§3 §4")  # 5 chars
        assert c.source == "§3 §4"

    def test_source_long_passes(self):
        c = CourseCitation(source="PATTERN_DEFINITIONS §3 空方力竭背景")
        assert "PATTERN_DEFINITIONS" in c.source

    def test_extra_fields_forbidden(self):
        """extra='forbid' must reject unknown fields."""
        with pytest.raises(ValidationError):
            CourseCitation(source="PATTERN_DEFINITIONS §3", unknown_field="x")

    def test_optional_fields_default_none(self):
        c = CourseCitation(source="明日 K 線 §20 攻擊成本")
        assert c.article_id is None
        assert c.quote is None


# ---------------------------------------------------------------------------
# T1.1.2 — Action requires course_citation
# ---------------------------------------------------------------------------


class TestActionValidation:
    def test_missing_course_citation_raises(self):
        """T1.1.2: Action without course_citation must raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            Action(type="watch_only", description="觀察中")  # missing course_citation
        errors = exc_info.value.errors()
        assert any("course_citation" in str(e["loc"]) for e in errors)

    def test_valid_action_passes(self):
        a = Action(**_valid_action())
        assert a.type == "watch_only"
        assert a.notes == []

    def test_partial_exit_type_accepted(self):
        """partial_exit is a user-approved ActionType override."""
        a = Action(
            type="partial_exit",
            description="先賣一半 — 老師明示原話",
            course_citation=CourseCitation(source="明日 K 線 §26 防守姿態"),
        )
        assert a.type == "partial_exit"

    def test_invalid_action_type_raises(self):
        with pytest.raises(ValidationError):
            Action(
                type="magic_exit",
                description="發明的 action",
                course_citation=CourseCitation(source="PATTERN_DEFINITIONS §3"),
            )


# ---------------------------------------------------------------------------
# T1.1.3 — Branch.next_day_n > 3
# ---------------------------------------------------------------------------


class TestBranchValidation:
    def test_next_day_n_above_3_raises(self):
        """T1.1.3: next_day_n > 3 must raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            Branch(**_valid_branch(next_day_n=4))
        errors = exc_info.value.errors()
        assert any("next_day_n" in str(e["loc"]) for e in errors)

    def test_next_day_n_0_raises(self):
        with pytest.raises(ValidationError):
            Branch(**_valid_branch(next_day_n=0))

    def test_next_day_n_3_passes(self):
        b = Branch(**_valid_branch(next_day_n=3))
        assert b.next_day_n == 3

    def test_default_next_day_n_is_1(self):
        b = Branch(**_valid_branch())
        assert b.next_day_n == 1

    def test_next_branch_ids_defaults_empty(self):
        b = Branch(**_valid_branch())
        assert b.next_branch_ids == []


# ---------------------------------------------------------------------------
# T1.1.4 — Light.severity whitelist
# ---------------------------------------------------------------------------


class TestLightValidation:
    def test_invalid_severity_raises(self):
        """T1.1.4: severity not in ['info','warn','critical'] must raise."""
        with pytest.raises(ValidationError) as exc_info:
            Light(
                light_id="test_light",
                trigger_condition={"today.close": "< prev_high_60"},
                course_citation=CourseCitation(source="明日 K 線 §04 遇壓狀態"),
                recommendation_text="遇壓未化解，反向看待",
                severity="danger",  # not in whitelist
            )
        errors = exc_info.value.errors()
        assert any("severity" in str(e["loc"]) for e in errors)

    @pytest.mark.parametrize("sev", ["info", "warn", "critical"])
    def test_valid_severities_pass(self, sev):
        light = Light(
            light_id=f"test_{sev}",
            trigger_condition={"today.close": "< prev_high_60"},
            course_citation=CourseCitation(source="明日 K 線 §04 遇壓狀態"),
            recommendation_text="提醒文字",
            severity=sev,
        )
        assert light.severity == sev

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            Light(
                light_id="x",
                trigger_condition={},
                course_citation=CourseCitation(source="明日 K 線 §04 遇壓狀態"),
                recommendation_text="test",
                severity="info",
                unknown="y",
            )


# ---------------------------------------------------------------------------
# T1.1.5 — Playbook round-trip
# ---------------------------------------------------------------------------


class TestPlaybookRoundTrip:
    def test_dict_to_model_to_dict_structure_consistent(self):
        """T1.1.5: dict → Playbook → model_dump() must preserve structure."""
        raw = _valid_playbook()
        model = Playbook(**raw)

        dumped = model.model_dump()

        # Top-level keys preserved
        assert dumped["pattern"] == raw["pattern"]
        assert dumped["setup"]["name"] == raw["setup"]["name"]
        assert dumped["relevant_lights"] == []

        # Branch structure
        assert len(dumped["branches"]) == 1
        branch = dumped["branches"][0]
        assert branch["id"] == "B1_test"
        assert branch["confirm_at"] == "next_close"
        assert branch["next_day_n"] == 1
        assert branch["action"]["type"] == "watch_only"
        assert branch["action"]["course_citation"]["source"] == "PATTERN_DEFINITIONS §3"
        assert branch["action"]["notes"] == []

        # course_sources
        assert len(dumped["course_sources"]) == 1
        assert dumped["course_sources"][0]["source"] == "明日 K 線 §06 力竭後反彈"

    def test_playbook_with_multiple_branches(self):
        branches = [
            _valid_branch("B1_續強", action=_valid_action(type="entry_signal")),
            _valid_branch("B2_跌破", action=_valid_action(type="exit_signal")),
            _valid_branch("B3_整理", action=_valid_action(type="watch_only")),
        ]
        raw = _valid_playbook(branches=branches)
        model = Playbook(**raw)
        assert len(model.branches) == 3
        assert model.branches[0].action.type == "entry_signal"

    def test_relevant_lights_round_trips(self):
        raw = _valid_playbook(relevant_lights=["pressure_meeting_unresolved", "high_black_k_warning"])
        model = Playbook(**raw)
        assert model.relevant_lights == ["pressure_meeting_unresolved", "high_black_k_warning"]
        dumped = model.model_dump()
        assert dumped["relevant_lights"] == model.relevant_lights

    def test_extra_fields_in_playbook_forbidden(self):
        raw = _valid_playbook(extra_field="forbidden")
        with pytest.raises(ValidationError):
            Playbook(**raw)


# ---------------------------------------------------------------------------
# Additional: ContextSnapshot all-optional + AdvisorResult basic
# ---------------------------------------------------------------------------


class TestContextSnapshot:
    def test_empty_snapshot_all_none(self):
        ctx = ContextSnapshot()
        assert ctx.broker_tier1_buy is None
        assert ctx.attack_cost is None
        assert ctx.is_anomalous_volume is None

    def test_partial_fill_passes(self):
        ctx = ContextSnapshot(ma5_will_rise=True, ch2_warning_score=3)
        assert ctx.ma5_will_rise is True
        assert ctx.ch2_warning_score == 3
        assert ctx.ma10_will_rise is None


class TestAdvisorResult:
    def test_empty_result(self):
        r = AdvisorResult()
        assert r.fired_patterns == []
        assert r.scenarios == []
        assert r.active_lights == []
        assert r.notes == []
        assert r.context_snapshot is None

    def test_result_with_snapshot(self):
        ctx = ContextSnapshot(ma5_will_rise=True)
        r = AdvisorResult(context_snapshot=ctx, notes=["test note"])
        assert r.context_snapshot.ma5_will_rise is True
        assert "test note" in r.notes


class TestPatternHit:
    def test_basic_creation(self):
        hit = PatternHit(pattern="bull_engulfing", fired_at="2026-06-03")
        assert hit.pattern == "bull_engulfing"
        assert hit.confidence is None

    def test_with_confidence(self):
        hit = PatternHit(pattern="morning_star", fired_at="2026-06-03", confidence=0.85)
        assert hit.confidence == 0.85

    def test_equality(self):
        h1 = PatternHit("bull_engulfing", "2026-06-03", 0.9)
        h2 = PatternHit("bull_engulfing", "2026-06-03", 0.9)
        assert h1 == h2
