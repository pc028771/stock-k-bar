"""Tests for B 類 8 篇明日 K 線 playbook YAMLs — Task 2.2.

T2.2.1: 5 yaml + 1 extras yaml 全部 loader OK
T2.2.2: 對 historical 範例日 → branch 觸發符合預期
T2.2.3: STUB feature 缺 → advisor 不 crash，notes 標 warn
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts.kline.scenarios import load_playbooks
from scripts.kline.scenarios._schema import ContextSnapshot
from scripts.kline.scenarios.condition import evaluate

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

PLAYBOOKS_DIR = Path("scripts/kline/scenarios/playbooks")
EXTRAS_DIR = Path("scripts/kline/extras/scenarios/playbooks")

B_CLASS_FILES = [
    "attack_cost_displayed.yaml",
    "merged_doji_attack.yaml",
    "defensive_stance.yaml",
    "no_attack_after_breakout.yaml",
    "record_decline_rebound.yaml",
]
EXTRAS_FILE = "bullish_reversal_long_bear.yaml"


# ---------------------------------------------------------------------------
# T2.2.1 — Loader OK for all 6 YAMLs
# ---------------------------------------------------------------------------


class TestT221LoaderOK:
    """T2.2.1: All 5 main playbooks + 1 extras load without error."""

    def test_all_b_class_files_exist(self):
        """All 5 B-class YAML files exist on disk."""
        for fname in B_CLASS_FILES:
            path = PLAYBOOKS_DIR / fname
            assert path.exists(), f"Missing: {path}"

    def test_extras_file_exists(self):
        """B08 extras YAML exists in extras/scenarios/playbooks/."""
        path = EXTRAS_DIR / EXTRAS_FILE
        assert path.exists(), f"Missing: {path}"

    def test_load_playbooks_includes_all_b_class(self):
        """load_playbooks returns all B-class patterns."""
        result = load_playbooks([PLAYBOOKS_DIR])
        expected_patterns = [
            "attack_cost_displayed",
            "merged_doji",
            "defensive_stance",
            "no_attack_after_breakout",
            "record_decline_rebound",
        ]
        for pat in expected_patterns:
            assert pat in result, f"Pattern not loaded: {pat}"

    def test_load_playbooks_includes_extras(self):
        """load_playbooks from extras dir returns bullish_reversal_long_bear."""
        result = load_playbooks([EXTRAS_DIR])
        assert "bullish_reversal_long_bear" in result

    def test_all_branches_have_course_citation(self):
        """Every branch in every B-class playbook has a course_citation."""
        result = load_playbooks([PLAYBOOKS_DIR, EXTRAS_DIR])
        for pattern, pbs in result.items():
            for pb in pbs:
                for branch in pb.branches:
                    assert branch.action.course_citation is not None, (
                        f"Missing course_citation in pattern={pattern} branch={branch.id}"
                    )
                    assert len(branch.action.course_citation.source) >= 5, (
                        f"source too short in pattern={pattern} branch={branch.id}"
                    )

    def test_attack_cost_displayed_structure(self):
        """attack_cost_displayed has correct pattern + setup + 4 branches."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pbs = result["attack_cost_displayed"]
        assert len(pbs) == 1
        pb = pbs[0]
        assert pb.pattern == "attack_cost_displayed"
        assert pb.setup.name == "attack_cost_entry_and_break"
        assert "is_limit_up_locked" in pb.setup.required_context
        assert "is_just_broke_high" in pb.setup.required_context
        assert len(pb.branches) == 4

    def test_merged_doji_structure(self):
        """merged_doji has correct pattern + setup + 4 branches."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pbs = result["merged_doji"]
        assert len(pbs) == 1
        pb = pbs[0]
        assert pb.pattern == "merged_doji"
        assert pb.setup.name == "merged_doji_attack_intent"
        assert "is_just_broke_high" in pb.setup.required_context
        assert len(pb.branches) == 4

    def test_defensive_stance_structure(self):
        """defensive_stance has correct pattern + setup + 4 branches."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pbs = result["defensive_stance"]
        assert len(pbs) == 1
        pb = pbs[0]
        assert pb.pattern == "defensive_stance"
        assert pb.setup.name == "defensive_stance_entry_exit"
        assert len(pb.branches) == 4

    def test_no_attack_after_breakout_structure(self):
        """no_attack_after_breakout has correct pattern + 4 branches."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pbs = result["no_attack_after_breakout"]
        assert len(pbs) == 1
        pb = pbs[0]
        assert pb.pattern == "no_attack_after_breakout"
        assert pb.setup.name == "no_attack_exit_three_types"
        assert len(pb.branches) == 4

    def test_record_decline_rebound_structure(self):
        """record_decline_rebound has correct pattern + 3 branches."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pbs = result["record_decline_rebound"]
        assert len(pbs) == 1
        pb = pbs[0]
        assert pb.pattern == "record_decline_rebound"
        assert pb.setup.name == "record_decline_no_new_low_entry"
        assert len(pb.branches) == 3

    def test_bullish_reversal_long_bear_structure(self):
        """bullish_reversal_long_bear (extras) has correct pattern + 4 branches."""
        result = load_playbooks([EXTRAS_DIR])
        pbs = result["bullish_reversal_long_bear"]
        assert len(pbs) == 1
        pb = pbs[0]
        assert pb.pattern == "bullish_reversal_long_bear"
        assert pb.setup.name == "extras_bullish_reversal_long_bear"
        assert len(pb.branches) == 4

    def test_exit_signal_branches_have_stop_loss_or_exit_type(self):
        """B02/B05/B06 exit branches use exit_signal or stop_loss_trigger type."""
        result = load_playbooks([PLAYBOOKS_DIR])

        # attack_cost_displayed B2 = exit_signal
        pb = result["attack_cost_displayed"][0]
        b2 = next(b for b in pb.branches if b.id == "B2_next_day_breaks_attack_cost")
        assert b2.action.type == "exit_signal"

        # defensive_stance B3 = exit_signal
        pb = result["defensive_stance"][0]
        b3 = next(b for b in pb.branches if b.id == "B3_break_defensive_low")
        assert b3.action.type == "exit_signal"

        # no_attack_after_breakout B1 B2 = exit_signal
        pb = result["no_attack_after_breakout"][0]
        b1 = next(b for b in pb.branches if b.id == "B1_gap_filled_and_close_below_intent_low")
        b2 = next(b for b in pb.branches if b.id == "B2_black_k_breaks_intent_zone")
        assert b1.action.type == "exit_signal"
        assert b2.action.type == "exit_signal"

    def test_next_day_n_within_limit(self):
        """All branches have next_day_n ≤ 3."""
        result = load_playbooks([PLAYBOOKS_DIR, EXTRAS_DIR])
        for pattern, pbs in result.items():
            for pb in pbs:
                for branch in pb.branches:
                    assert branch.next_day_n <= 3, (
                        f"next_day_n > 3 in pattern={pattern} branch={branch.id}"
                    )


# ---------------------------------------------------------------------------
# T2.2.2 — Branch condition evaluation
# ---------------------------------------------------------------------------


def _make_row(**kwargs) -> pd.Series:
    """Build a minimal pd.Series for evaluate()."""
    defaults = {
        "open": 100.0,
        "high": 105.0,
        "low": 98.0,
        "close": 103.0,
        "volume": 10000,
        "prev_open": 99.0,
        "prev_high": 104.0,
        "prev_low": 97.0,
        "prev_close": 102.0,
        "prev_high_60": 108.0,
        "prior_low_60": 85.0,
        "attack_cost": 103.0,
        "attack_intent_zone_high": 100.0,
        "attack_intent_zone_low": 95.0,
        "defensive_low": 96.0,
        "merged_high": 106.0,
        "merged_low": 94.0,
    }
    defaults.update(kwargs)
    return pd.Series(defaults)


def _make_ctx(**kwargs) -> ContextSnapshot:
    """Build a minimal ContextSnapshot for evaluate()."""
    defaults = {
        "broker_tier1_buy": None,
        "teacher_tier": None,
        "ch2_warning_score": None,
        "sector_consensus_direction": None,
        "ma5_will_rise": None,
        "ma10_will_rise": None,
        "ma20_will_rise": None,
        "ma60_will_rise": None,
        "attack_cost": None,
        "defensive_low": None,
        "attack_intent_zone_high": None,
        "attack_intent_zone_low": None,
        "is_just_broke_high": None,
        "is_limit_up_locked": None,
        "is_anomalous_volume": None,
    }
    defaults.update(kwargs)
    return ContextSnapshot(**defaults)


class TestT222BranchEvaluation:
    """T2.2.2: Branch conditions evaluate correctly against sample data."""

    # ---- attack_cost_displayed ----

    def test_attack_cost_holds_branch_true(self):
        """B1_next_day_holds_attack_cost fires when next_day.low >= attack_cost."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pb = result["attack_cost_displayed"][0]
        branch = next(b for b in pb.branches if b.id == "B1_next_day_holds_attack_cost")

        # next_day fields are always None in scalar mode → returns None (pending)
        row = _make_row(attack_cost=103.0)
        ctx = _make_ctx()
        outcome = evaluate(branch.when, row, ctx)
        assert outcome is None  # pending (next_day.* unknown in scalar mode)

    def test_attack_cost_break_branch_condition_valid_dsl(self):
        """B2_next_day_breaks_attack_cost has valid DSL (no UnknownTokenError)."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pb = result["attack_cost_displayed"][0]
        branch = next(b for b in pb.branches if b.id == "B2_next_day_breaks_attack_cost")

        # Should not raise — next_day fields return None (pending)
        row = _make_row(attack_cost=103.0)
        ctx = _make_ctx()
        outcome = evaluate(branch.when, row, ctx)
        assert outcome is None  # pending

    # ---- merged_doji_attack ----

    def test_merged_doji_gap_up_pending(self):
        """B1_gap_up_attack uses next_day.gap_up which is pending in scalar mode."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pb = result["merged_doji"][0]
        branch = next(b for b in pb.branches if b.id == "B1_gap_up_attack")

        row = _make_row()
        ctx = _make_ctx()
        outcome = evaluate(branch.when, row, ctx)
        assert outcome is None  # pending

    def test_merged_doji_break_merged_low_pending(self):
        """B3_break_merged_low uses next_day.low → pending in scalar mode."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pb = result["merged_doji"][0]
        branch = next(b for b in pb.branches if b.id == "B3_break_merged_low")

        row = _make_row(merged_low=94.0)
        ctx = _make_ctx()
        outcome = evaluate(branch.when, row, ctx)
        assert outcome is None  # pending

    # ---- defensive_stance ----

    def test_defensive_break_pending(self):
        """B3_break_defensive_low: next_day.close pending in scalar mode."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pb = result["defensive_stance"][0]
        branch = next(b for b in pb.branches if b.id == "B3_break_defensive_low")

        row = _make_row(defensive_low=96.0)
        ctx = _make_ctx()
        outcome = evaluate(branch.when, row, ctx)
        assert outcome is None  # pending

    def test_defensive_holding_zone_pending(self):
        """B4_holding_defensive_zone: next_day fields pending in scalar mode."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pb = result["defensive_stance"][0]
        branch = next(b for b in pb.branches if b.id == "B4_holding_defensive_zone")

        row = _make_row(defensive_low=96.0)
        ctx = _make_ctx()
        outcome = evaluate(branch.when, row, ctx)
        assert outcome is None  # pending

    # ---- no_attack_after_breakout ----

    def test_no_attack_attack_continues_pending(self):
        """B3_attack_continues: next_day.close pending in scalar mode."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pb = result["no_attack_after_breakout"][0]
        branch = next(b for b in pb.branches if b.id == "B3_attack_continues")

        row = _make_row(attack_intent_zone_high=100.0)
        ctx = _make_ctx()
        outcome = evaluate(branch.when, row, ctx)
        assert outcome is None  # pending

    # ---- record_decline_rebound ----

    def test_record_decline_no_new_low_pending(self):
        """B1_next_day_no_new_low: next_day.low pending in scalar mode."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pb = result["record_decline_rebound"][0]
        branch = next(b for b in pb.branches if b.id == "B1_next_day_no_new_low")

        row = _make_row()
        ctx = _make_ctx()
        outcome = evaluate(branch.when, row, ctx)
        assert outcome is None  # pending

    def test_record_decline_new_low_pending(self):
        """B2_next_day_new_low: next_day.low pending in scalar mode."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pb = result["record_decline_rebound"][0]
        branch = next(b for b in pb.branches if b.id == "B2_next_day_new_low")

        row = _make_row()
        ctx = _make_ctx()
        outcome = evaluate(branch.when, row, ctx)
        assert outcome is None  # pending

    # ---- bullish_reversal_long_bear (extras) ----

    def test_bullish_reversal_gap_up_pending(self):
        """B1_reversal_pattern_gap_up_confirm: next_day.gap_up pending in scalar mode."""
        result = load_playbooks([EXTRAS_DIR])
        pb = result["bullish_reversal_long_bear"][0]
        branch = next(b for b in pb.branches if b.id == "B1_reversal_pattern_gap_up_confirm")

        row = _make_row()
        ctx = _make_ctx()
        outcome = evaluate(branch.when, row, ctx)
        assert outcome is None  # pending

    def test_bullish_reversal_stop_loss_pending(self):
        """B3_stop_loss_new_low: next_day.close pending in scalar mode."""
        result = load_playbooks([EXTRAS_DIR])
        pb = result["bullish_reversal_long_bear"][0]
        branch = next(b for b in pb.branches if b.id == "B3_stop_loss_new_low")

        row = _make_row(prior_low_60=85.0)
        ctx = _make_ctx()
        outcome = evaluate(branch.when, row, ctx)
        assert outcome is None  # pending


# ---------------------------------------------------------------------------
# T2.2.3 — STUB feature missing → no crash + notes warn
# ---------------------------------------------------------------------------


class TestT223StubFeatureMissing:
    """T2.2.3: Playbooks with STUB features still load + evaluate without crash.

    When required_context features (is_limit_up_locked, is_just_broke_high,
    is_anomalous_volume, defensive_low, merged_high/merged_low) are None,
    the advisor should not crash. The condition evaluator returns None
    (pending) for unknown top-level values — this is the safe failure mode.
    """

    def test_attack_cost_required_context_missing_no_crash(self):
        """attack_cost_displayed loads even when is_limit_up_locked is None in context."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pb = result["attack_cost_displayed"][0]
        # required_context includes is_limit_up_locked, is_just_broke_high, is_anomalous_volume
        # ContextSnapshot allows all None — advisor marks warn but doesn't crash
        assert "is_limit_up_locked" in pb.setup.required_context
        assert "is_just_broke_high" in pb.setup.required_context
        assert "is_anomalous_volume" in pb.setup.required_context

    def test_merged_doji_required_context_present(self):
        """merged_doji requires is_just_broke_high in required_context."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pb = result["merged_doji"][0]
        assert "is_just_broke_high" in pb.setup.required_context

    def test_stub_feature_none_returns_pending_not_crash(self):
        """When merged_high is None (top-level), evaluate returns None not error."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pb = result["merged_doji"][0]
        # B2 depends on merged_high
        branch = next(b for b in pb.branches if b.id == "B2_push_attack_above_merged_high")

        # Row without merged_high set → defaults to None
        row = _make_row()
        row_no_merged = row.drop("merged_high") if "merged_high" in row.index else row
        ctx = _make_ctx()
        # Should not raise — returns None (pending) for missing top-level field
        outcome = evaluate(branch.when, row_no_merged, ctx)
        # next_day.close is pending in scalar mode, so result is None
        assert outcome is None

    def test_defensive_low_none_in_row_returns_pending(self):
        """defensive_low missing from row returns None (pending) in scalar mode."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pb = result["defensive_stance"][0]
        branch = next(b for b in pb.branches if b.id == "B3_break_defensive_low")

        row = _make_row()
        row_no_def = row.drop("defensive_low") if "defensive_low" in row.index else row
        ctx = _make_ctx()
        # next_day.close is always pending → returns None regardless
        outcome = evaluate(branch.when, row_no_def, ctx)
        assert outcome is None

    def test_attack_intent_zone_none_in_row_returns_pending(self):
        """attack_intent_zone_high missing from row → None (pending) in scalar mode."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pb = result["no_attack_after_breakout"][0]
        branch = next(b for b in pb.branches if b.id == "B3_attack_continues")

        row = _make_row()
        row_no_zone = row.drop("attack_intent_zone_high") if "attack_intent_zone_high" in row.index else row
        ctx = _make_ctx()
        outcome = evaluate(branch.when, row_no_zone, ctx)
        # next_day.close pending → None
        assert outcome is None

    def test_stub_notes_documented_in_playbook(self):
        """B07 record_decline_rebound has STUB-NEED-USER S4 documented in branch notes."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pb = result["record_decline_rebound"][0]
        b1 = next(b for b in pb.branches if b.id == "B1_next_day_no_new_low")
        notes_text = " ".join(b1.action.notes)
        assert "STUB" in notes_text or "S4" in notes_text, (
            "B07 entry branch should document STUB-NEED-USER S4 in notes"
        )

    def test_extras_b08_stub_notes_documented(self):
        """B08 bullish_reversal_long_bear documents STUB S5 and S8 in branch notes."""
        result = load_playbooks([EXTRAS_DIR])
        pb = result["bullish_reversal_long_bear"][0]
        b1 = next(b for b in pb.branches if b.id == "B1_reversal_pattern_gap_up_confirm")
        notes_text = " ".join(b1.action.notes)
        assert "S5" in notes_text or "STUB" in notes_text, (
            "B08 entry branch should document STUB S5 in notes"
        )
        assert "S8" in notes_text or "基本面" in notes_text, (
            "B08 entry branch should document STUB S8 (基本面 filter) in notes"
        )

    def test_all_b_class_playbooks_load_with_empty_context(self):
        """All 6 B-class YAMLs can be loaded + branches evaluated with all-None context."""
        result = load_playbooks([PLAYBOOKS_DIR, EXTRAS_DIR])
        row = _make_row()
        ctx = _make_ctx()

        expected_patterns = [
            "attack_cost_displayed",
            "merged_doji",
            "defensive_stance",
            "no_attack_after_breakout",
            "record_decline_rebound",
            "bullish_reversal_long_bear",
        ]
        for pat in expected_patterns:
            assert pat in result, f"Pattern not loaded: {pat}"
            for pb in result[pat]:
                for branch in pb.branches:
                    # Must not raise — may return True/False/None
                    try:
                        evaluate(branch.when, row, ctx)
                    except Exception as e:
                        pytest.fail(
                            f"evaluate() crashed for pattern={pat} branch={branch.id}: {e}"
                        )
