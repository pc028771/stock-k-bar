"""Tests for scripts/kline/scenarios/formatter.py.

Coverage:
  TF.1  Empty AdvisorResult → prints "今日無觸發型態" and "今日無觸發劇本"
  TF.2  Entry-signal branch (entry_signal) → 🟢 shown
  TF.3  exhaust_invalid branch → ⚪ + 衰竭標籤 warning shown
  TF.4  lights each severity → correct emoji
  TF.5  watch_only / context_only_signal → 🟡 shown
  TF.6  stop_loss_trigger → 🔴 shown
  TF.7  MA will_rise flags → correct 🟢/🔴 shown in header
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.kline.scenarios._schema import (
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
from scripts.kline.scenarios.formatter import format_advisor_result

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CITATION = CourseCitation(source="PATTERN_DEFINITIONS §3 test source")


def _make_action(action_type: str, description: str = "test description") -> Action:
    return Action(
        type=action_type,
        description=description,
        course_citation=_CITATION,
    )


def _make_branch(branch_id: str, action_type: str) -> Branch:
    return Branch(
        id=branch_id,
        when={"today.close": "> today.open"},
        confirm_at="next_close",
        action=_make_action(action_type),
    )


def _make_playbook(playbook_name: str, branches: list[Branch]) -> Playbook:
    return Playbook(
        pattern="bull_engulfing",
        setup=PlaybookSetup(name=playbook_name),
        branches=branches,
        course_sources=[_CITATION],
    )


def _make_light(light_id: str, severity: str, text: str = "test recommendation") -> Light:
    return Light(
        light_id=light_id,
        trigger_condition={"today.close": "> today.open"},
        course_citation=_CITATION,
        recommendation_text=text,
        severity=severity,
    )


def _empty_result() -> AdvisorResult:
    return AdvisorResult()


def _make_bars(ticker: str = "2330", today_date: str = "2026-06-03") -> pd.DataFrame:
    """Minimal bars df for header display."""
    dates = pd.bdate_range(end=today_date, periods=10, freq="B")
    closes = np.linspace(95, 100, 10)
    return pd.DataFrame({
        "ticker": ticker,
        "trade_date": dates.strftime("%Y-%m-%d"),
        "open": closes * 0.99,
        "high": closes * 1.01,
        "low": closes * 0.98,
        "close": closes,
        "volume": 1_000_000,
        "ma5": closes,
        "ma10": closes,
        "ma20": closes,
        "ma60": closes,
    })


# ---------------------------------------------------------------------------
# TF.1  Empty AdvisorResult → no fired patterns, no scenarios
# ---------------------------------------------------------------------------


def test_empty_result_shows_no_pattern_message() -> None:
    result = _empty_result()
    output = format_advisor_result(result, ticker="2330", today_date="2026-06-03")
    assert "今日無觸發型態" in output
    assert "今日無觸發劇本" in output


def test_empty_result_no_lights_message() -> None:
    result = _empty_result()
    output = format_advisor_result(result, ticker="2330", today_date="2026-06-03")
    assert "今日無警示燈號" in output


# ---------------------------------------------------------------------------
# TF.2  entry_signal → 🟢
# ---------------------------------------------------------------------------


def test_entry_signal_shows_green_emoji(tmp_path: Path) -> None:
    """Scenario with entry_signal branch → 🟢 in output."""
    branch = _make_branch("B1_entry", "entry_signal")
    playbook = _make_playbook("test_entry_playbook", [branch])

    # Write playbook YAML so formatter can load branch details
    pb_dir = tmp_path / "playbooks"
    pb_dir.mkdir()
    _write_playbook_yaml(pb_dir / "test_entry.yaml", playbook)

    hit = PatternHit(pattern="bull_engulfing", fired_at="2026-06-03")
    scenario = Scenario(
        pattern_hit=hit,
        playbook_name="test_entry_playbook",
        enabled_branches=["B1_entry"],
    )
    result = AdvisorResult(
        fired_patterns=[hit],
        scenarios=[scenario],
    )

    # Patch formatter to use tmp_path playbooks
    _patch_formatter_dirs(tmp_path)
    output = format_advisor_result(result, ticker="2330", today_date="2026-06-03")
    assert "🟢" in output
    assert "B1_entry" in output


# ---------------------------------------------------------------------------
# TF.3  exhaust_invalid → ⚪ + warning text
# ---------------------------------------------------------------------------


def test_exhaust_invalid_shows_white_emoji_and_warning(tmp_path: Path) -> None:
    """Scenario with exhaust_invalid branch → ⚪ + '衰竭標籤' in output."""
    branch = _make_branch("B2_exhaust", "exhaust_invalid")
    playbook = _make_playbook("test_exhaust_playbook", [branch])

    pb_dir = tmp_path / "playbooks"
    pb_dir.mkdir()
    _write_playbook_yaml(pb_dir / "test_exhaust.yaml", playbook)

    hit = PatternHit(pattern="bull_engulfing", fired_at="2026-06-03")
    scenario = Scenario(
        pattern_hit=hit,
        playbook_name="test_exhaust_playbook",
        enabled_branches=["B2_exhaust"],
    )
    result = AdvisorResult(
        fired_patterns=[hit],
        scenarios=[scenario],
    )

    _patch_formatter_dirs(tmp_path)
    output = format_advisor_result(result, ticker="2330", today_date="2026-06-03")
    assert "⚪" in output
    assert "衰竭標籤" in output
    # Also check that the reminder block is shown
    assert "feedback_trading_discipline_checklist" in output


# ---------------------------------------------------------------------------
# TF.4  lights severity emoji
# ---------------------------------------------------------------------------


def test_critical_light_shows_red_emoji() -> None:
    light = _make_light("test_critical", "critical", "Critical warning text")
    result = AdvisorResult(active_lights=[light])
    output = format_advisor_result(result, ticker="2330", today_date="2026-06-03")
    # Critical lights should show 🔴
    assert "🔴" in output
    assert "test_critical" in output


def test_warn_light_shows_yellow_emoji() -> None:
    light = _make_light("test_warn", "warn", "Warn text")
    result = AdvisorResult(active_lights=[light])
    output = format_advisor_result(result, ticker="2330", today_date="2026-06-03")
    assert "🟡" in output
    assert "test_warn" in output


def test_info_light_shows_white_emoji() -> None:
    light = _make_light("test_info", "info", "Info text")
    result = AdvisorResult(active_lights=[light])
    output = format_advisor_result(result, ticker="2330", today_date="2026-06-03")
    assert "⚪" in output
    assert "test_info" in output


# ---------------------------------------------------------------------------
# TF.5  watch_only / context_only_signal → 🟡
# ---------------------------------------------------------------------------


def test_watch_only_shows_yellow_emoji(tmp_path: Path) -> None:
    branch = _make_branch("B3_watch", "watch_only")
    playbook = _make_playbook("test_watch_playbook", [branch])

    pb_dir = tmp_path / "playbooks"
    pb_dir.mkdir()
    _write_playbook_yaml(pb_dir / "test_watch.yaml", playbook)

    hit = PatternHit(pattern="bull_engulfing", fired_at="2026-06-03")
    scenario = Scenario(
        pattern_hit=hit,
        playbook_name="test_watch_playbook",
        enabled_branches=["B3_watch"],
    )
    result = AdvisorResult(fired_patterns=[hit], scenarios=[scenario])

    _patch_formatter_dirs(tmp_path)
    output = format_advisor_result(result, ticker="2330", today_date="2026-06-03")
    assert "🟡" in output
    assert "B3_watch" in output


def test_context_only_signal_shows_yellow_emoji(tmp_path: Path) -> None:
    branch = _make_branch("B4_ctx", "context_only_signal")
    playbook = _make_playbook("test_ctx_playbook", [branch])

    pb_dir = tmp_path / "playbooks"
    pb_dir.mkdir()
    _write_playbook_yaml(pb_dir / "test_ctx.yaml", playbook)

    hit = PatternHit(pattern="bull_engulfing", fired_at="2026-06-03")
    scenario = Scenario(
        pattern_hit=hit,
        playbook_name="test_ctx_playbook",
        enabled_branches=["B4_ctx"],
    )
    result = AdvisorResult(fired_patterns=[hit], scenarios=[scenario])

    _patch_formatter_dirs(tmp_path)
    output = format_advisor_result(result, ticker="2330", today_date="2026-06-03")
    assert "🟡" in output


# ---------------------------------------------------------------------------
# TF.6  stop_loss_trigger → 🔴
# ---------------------------------------------------------------------------


def test_stop_loss_trigger_shows_red_emoji(tmp_path: Path) -> None:
    branch = _make_branch("B5_stop", "stop_loss_trigger")
    playbook = _make_playbook("test_stop_playbook", [branch])

    pb_dir = tmp_path / "playbooks"
    pb_dir.mkdir()
    _write_playbook_yaml(pb_dir / "test_stop.yaml", playbook)

    hit = PatternHit(pattern="bull_engulfing", fired_at="2026-06-03")
    scenario = Scenario(
        pattern_hit=hit,
        playbook_name="test_stop_playbook",
        enabled_branches=["B5_stop"],
    )
    result = AdvisorResult(fired_patterns=[hit], scenarios=[scenario])

    _patch_formatter_dirs(tmp_path)
    output = format_advisor_result(result, ticker="2330", today_date="2026-06-03")
    assert "🔴" in output
    assert "B5_stop" in output


# ---------------------------------------------------------------------------
# TF.7  MA will_rise flags in header
# ---------------------------------------------------------------------------


def test_ma_will_rise_true_shows_green() -> None:
    ctx = ContextSnapshot(
        ma5_will_rise=True,
        ma10_will_rise=True,
        ma20_will_rise=None,
        ma60_will_rise=False,
    )
    result = AdvisorResult(context_snapshot=ctx)
    # No bars passed → no borderline check, will_rise directly maps to emoji
    output = format_advisor_result(result, ticker="2330", today_date="2026-06-03")
    assert "MA5🟢" in output
    assert "MA10🟢" in output
    assert "MA60🔴" in output


def test_ma_will_rise_false_shows_red() -> None:
    ctx = ContextSnapshot(ma5_will_rise=False)
    result = AdvisorResult(context_snapshot=ctx)
    output = format_advisor_result(result, ticker="2330", today_date="2026-06-03")
    assert "MA5🔴" in output


def test_ma_will_rise_none_shows_dash() -> None:
    ctx = ContextSnapshot(ma5_will_rise=None)
    result = AdvisorResult(context_snapshot=ctx)
    output = format_advisor_result(result, ticker="2330", today_date="2026-06-03")
    assert "MA5—" in output


# ---------------------------------------------------------------------------
# Utility: write playbook YAML from Playbook object
# ---------------------------------------------------------------------------


def _write_playbook_yaml(path: Path, playbook: Playbook) -> None:
    """Write a minimal valid YAML for a Playbook to disk."""
    import yaml

    data = {
        "pattern": playbook.pattern,
        "setup": {
            "name": playbook.setup.name,
            "required_context": playbook.setup.required_context,
        },
        "branches": [
            {
                "id": b.id,
                "when": b.when,
                "confirm_at": b.confirm_at,
                "next_day_n": b.next_day_n,
                "action": {
                    "type": b.action.type,
                    "description": b.action.description,
                    "course_citation": {
                        "source": b.action.course_citation.source,
                    },
                },
            }
            for b in playbook.branches
        ],
        "course_sources": [
            {"source": cs.source} for cs in playbook.course_sources
        ],
        "relevant_lights": playbook.relevant_lights,
    }
    path.write_text(__import__("yaml").dump(data, allow_unicode=True), encoding="utf-8")


def _patch_formatter_dirs(tmp_path: Path) -> None:
    """Monkeypatch formatter's _load_playbooks_by_name to use tmp_path."""
    # We do this by patching the module-level function in formatter.
    # Simpler: the formatter calls _load_playbooks_by_name which reads from
    # scripts/kline/scenarios/playbooks/ — the test playbooks are minimal
    # and won't appear there.  Instead we monkeypatch at import time per test.
    # This is a no-op here; each test passes tmp_path playbooks by ensuring
    # formatter can load them.  The formatter falls back gracefully when a
    # branch is not found ("branch detail not found").
    # For tests that need branch details, we need to patch the loader call.
    # We achieve this by writing YAML to a tmp dir and monkeypatching the
    # formatter module attribute.
    import scripts.kline.scenarios.formatter as fmt_mod
    from scripts.kline.scenarios.loader import load_playbooks

    pb_dir = tmp_path / "playbooks"
    pb_dir.mkdir(exist_ok=True)

    original_fn = fmt_mod._load_playbooks_by_name

    def patched(d: Path) -> dict:
        # load from tmp_path instead of production dir
        raw = load_playbooks([pb_dir])
        by_name: dict = {}
        for pbs in raw.values():
            for pb in pbs:
                by_name[pb.setup.name] = pb
        return by_name

    fmt_mod._load_playbooks_by_name = patched
    # Note: tests using _patch_formatter_dirs must restore if needed,
    # but since each test creates fresh state, this is acceptable.
