"""Tests for scripts/kline/scenarios/manual_hints.py + formatter hint block.

Coverage:
  TMH.1  defensive_stance hint triggers when taiex_recent_weak=True
  TMH.2  defensive_stance hint triggers when defensive_low is set (even without taiex_recent_weak)
  TMH.3  defensive_stance hint does NOT trigger when both signals absent
  TMH.4  record_decline_rebound triggers when taiex_record_any_criterion=True
  TMH.5  record_decline_rebound does NOT trigger when taiex_record_any_criterion=False
  TMH.6  record_decline_rebound includes D+1 confirmation when taiex_no_new_low_next_day=True
  TMH.7  formatter renders 🧭 人工判斷情境 block when hints present
  TMH.8  formatter does NOT render hint block when no hints
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.kline.scenarios._schema import AdvisorResult, ContextSnapshot
from scripts.kline.scenarios.formatter import format_advisor_result
from scripts.kline.scenarios.manual_hints import (
    check_defensive_stance_hint,
    check_record_decline_rebound_hint,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_row() -> pd.Series:
    """Minimal row with dummy bar data."""
    return pd.Series(
        {"close": 100.0, "open": 98.0, "high": 102.0, "low": 97.0, "volume": 500_000}
    )


def _ctx(**kwargs) -> ContextSnapshot:
    """Build a ContextSnapshot with only the specified fields set."""
    return ContextSnapshot(**kwargs)


# ---------------------------------------------------------------------------
# TMH.1  defensive_stance triggers on taiex_recent_weak=True
# ---------------------------------------------------------------------------


def test_defensive_stance_triggers_on_taiex_recent_weak() -> None:
    row = _make_row()
    ctx = _ctx(taiex_recent_weak=True)
    hint = check_defensive_stance_hint(row, ctx)
    assert hint is not None
    assert hint["name"] == "defensive_stance"
    assert "taiex_recent_weak=True" in hint["trigger_reason"]


# ---------------------------------------------------------------------------
# TMH.2  defensive_stance triggers when defensive_low is set (no taiex_recent_weak)
# ---------------------------------------------------------------------------


def test_defensive_stance_triggers_on_defensive_low_only() -> None:
    row = _make_row()
    ctx = _ctx(defensive_low=95.0)
    hint = check_defensive_stance_hint(row, ctx)
    assert hint is not None
    assert hint["name"] == "defensive_stance"
    assert "defensive_low=95.0" in hint["trigger_reason"]


# ---------------------------------------------------------------------------
# TMH.3  defensive_stance does NOT trigger when both signals absent
# ---------------------------------------------------------------------------


def test_defensive_stance_no_trigger_when_no_signals() -> None:
    row = _make_row()
    ctx = _ctx()  # all fields None
    hint = check_defensive_stance_hint(row, ctx)
    assert hint is None


# ---------------------------------------------------------------------------
# TMH.4  record_decline_rebound triggers when taiex_record_any_criterion=True
# ---------------------------------------------------------------------------


def test_record_decline_rebound_triggers_on_record_criterion() -> None:
    row = _make_row()
    ctx = _ctx(taiex_record_any_criterion=True)
    hint = check_record_decline_rebound_hint(row, ctx)
    assert hint is not None
    assert hint["name"] == "record_decline_rebound"
    assert "taiex_record_any_criterion=True" in hint["trigger_reason"]


# ---------------------------------------------------------------------------
# TMH.5  record_decline_rebound does NOT trigger when criterion False
# ---------------------------------------------------------------------------


def test_record_decline_rebound_no_trigger_when_false() -> None:
    row = _make_row()
    ctx = _ctx(taiex_record_any_criterion=False)
    hint = check_record_decline_rebound_hint(row, ctx)
    assert hint is None


def test_record_decline_rebound_no_trigger_when_none() -> None:
    row = _make_row()
    ctx = _ctx()  # taiex_record_any_criterion is None
    hint = check_record_decline_rebound_hint(row, ctx)
    assert hint is None


# ---------------------------------------------------------------------------
# TMH.6  D+1 confirmation note appears when taiex_no_new_low_next_day=True
# ---------------------------------------------------------------------------


def test_record_decline_rebound_d1_confirmed() -> None:
    row = _make_row()
    ctx = _ctx(
        taiex_record_any_criterion=True,
        taiex_no_new_low_next_day=True,
    )
    hint = check_record_decline_rebound_hint(row, ctx)
    assert hint is not None
    assert "D+1 確認" in hint["trigger_reason"]
    # course_quotes must include the key phrase verbatim
    assert any("隔日不再創新低" in q for q in hint["course_quotes"])


def test_record_decline_rebound_d1_not_yet_confirmed() -> None:
    row = _make_row()
    ctx = _ctx(
        taiex_record_any_criterion=True,
        taiex_no_new_low_next_day=None,
    )
    hint = check_record_decline_rebound_hint(row, ctx)
    assert hint is not None
    assert "D+1 尚未確認" in hint["trigger_reason"]


# ---------------------------------------------------------------------------
# TMH.7  formatter renders 🧭 人工判斷情境 block when hints present
# ---------------------------------------------------------------------------


def test_formatter_renders_hint_block_when_hints_present() -> None:
    ctx = ContextSnapshot(
        taiex_recent_weak=True,
        defensive_low=90.0,
    )
    result = AdvisorResult(
        context_snapshot=ctx,
        manual_hints=[
            {
                "name": "defensive_stance",
                "course_source": "明日 K 線 §26「防守姿態」",
                "trigger_reason": "大盤弱勢；defensive_low=90.0",
                "manual_checks": ["1. 主力是否已介入"],
                "course_quotes": ["跌破防守價就是根本沒有要攻擊的意思"],
                "stubs": ["STUB-NEED-USER: taiex_recent_weak — N 值未明示"],
            }
        ],
    )
    output = format_advisor_result(result, ticker="2330", today_date="2026-06-04")
    assert "🧭 人工判斷情境" in output
    assert "defensive_stance" in output
    assert "明日 K 線 §26" in output
    assert "跌破防守價就是根本沒有要攻擊的意思" in output
    assert "STUB-NEED-USER" in output


# ---------------------------------------------------------------------------
# TMH.8  formatter does NOT render hint block when no hints
# ---------------------------------------------------------------------------


def test_formatter_no_hint_block_when_empty() -> None:
    result = AdvisorResult()
    output = format_advisor_result(result, ticker="2330", today_date="2026-06-04")
    assert "🧭 人工判斷情境" not in output


# ---------------------------------------------------------------------------
# Integration: hint has course_quotes with verbatim course text
# ---------------------------------------------------------------------------


def test_defensive_stance_course_quotes_verbatim() -> None:
    """Ensure the course quotes in the hint are verbatim from course text."""
    row = _make_row()
    ctx = _ctx(taiex_recent_weak=True)
    hint = check_defensive_stance_hint(row, ctx)
    assert hint is not None
    quotes = hint["course_quotes"]
    # Must contain the verbatim phrase from §26
    assert any("跌破防守價就是根本沒有要攻擊的意思" in q for q in quotes)
    # Must contain the necessary conditions verbatim
    assert any("主力已經介入" in q for q in quotes)


def test_record_decline_rebound_course_quotes_verbatim() -> None:
    """Ensure the course quotes in the hint are verbatim from §30 course text."""
    row = _make_row()
    ctx = _ctx(taiex_record_any_criterion=True)
    hint = check_record_decline_rebound_hint(row, ctx)
    assert hint is not None
    quotes = hint["course_quotes"]
    assert any("交易的藝術" in q for q in quotes)
    assert any("本質非常爛的公司" in q for q in quotes)
