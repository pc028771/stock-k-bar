"""Advisor result formatter — ASCII + emoji output for human readability.

Formats AdvisorResult into colour-coded ASCII for daily use.
Pure presentation layer — no logic changes to advisor.analyze() or schema.

Action type colour coding:
  🟢  entry_signal
  🟡  watch_only, context_only_signal
  ⚪  exhaust_invalid  (事後標籤、非進場訊號)
  🔴  stop_loss_trigger, partial_exit, exit_signal
  ⚫  其他未分類

Severity colour coding:
  🔴  critical
  🟡  warn
  ⚪  info
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from ._schema import (
    Action,
    ActionType,
    AdvisorResult,
    Branch,
    ContextSnapshot,
    Light,
    Playbook,
    Scenario,
    Severity,
)
from .loader import load_playbooks, load_lights
from pathlib import Path

# ---------------------------------------------------------------------------
# Colour mappings
# ---------------------------------------------------------------------------

_ACTION_EMOJI: dict[str, str] = {
    "entry_signal": "🟢",
    "watch_only": "🟡",
    "context_only_signal": "🟡",
    "exhaust_invalid": "⚪",
    "stop_loss_trigger": "🔴",
    "partial_exit": "🔴",
    "exit_signal": "🔴",
}
_ACTION_EMOJI_DEFAULT = "⚫"

_SEVERITY_EMOJI: dict[str, str] = {
    "critical": "🔴",
    "warn": "🟡",
    "info": "⚪",
}

# ---------------------------------------------------------------------------
# MA 扣抵狀態 emoji
# ---------------------------------------------------------------------------

def _ma_will_rise_emoji(will_rise: Optional[bool], close: Optional[float], ma_val: Optional[float]) -> str:
    """Return 🟢/🔴/🟡 based on will_rise flag; 🟡 for borderline (diff < 1%)."""
    if will_rise is None:
        return "—"
    if will_rise is True:
        # Check if borderline (close vs ma within 1%)
        if close is not None and ma_val is not None and ma_val > 0:
            diff_pct = abs(close - ma_val) / ma_val
            if diff_pct < 0.01:
                return "🟡"
        return "🟢"
    else:
        if close is not None and ma_val is not None and ma_val > 0:
            diff_pct = abs(close - ma_val) / ma_val
            if diff_pct < 0.01:
                return "🟡"
        return "🔴"


# ---------------------------------------------------------------------------
# Internal helper: format a single branch
# ---------------------------------------------------------------------------

_SCENARIOS_DIR = Path(__file__).parent


def _format_branch(branch: Branch, indent: str = "    ") -> list[str]:
    """Return lines for a single branch block."""
    action = branch.action
    emoji = _ACTION_EMOJI.get(action.type, _ACTION_EMOJI_DEFAULT)
    lines: list[str] = []

    # Headline
    exhaust_warn = ""
    if action.type == "exhaust_invalid":
        exhaust_warn = "  ⚠️ 衰竭標籤、非進場訊號"
    lines.append(f"{indent}{emoji} {branch.id} ({action.type}){exhaust_warn}")

    # Description
    lines.append(f'{indent}   "{action.description}"')

    # Course citation
    citation = action.course_citation
    lines.append(f"{indent}   課程來源: {citation.source}")
    if citation.quote:
        lines.append(f'{indent}   老師原話: 「{citation.quote}」')

    # confirm_at / next_day_n
    confirm_label = branch.confirm_at
    if branch.next_day_n > 1:
        confirm_label += f"  (next_day_n: {branch.next_day_n})"
    lines.append(f"{indent}   確認時點: {confirm_label}")

    # Human-readable when condition (key highlight)
    when = branch.when
    if when:
        when_str = _humanize_when(when)
        if when_str:
            lines.append(f"{indent}   條件: {when_str}")

    # Notes
    for note in action.notes:
        lines.append(f"{indent}   ※ {note}")

    return lines


def _humanize_when(when: dict) -> str:
    """Convert mini-DSL when dict to human-readable string (best effort)."""
    if not when:
        return ""
    parts: list[str] = []
    for k, v in when.items():
        if k in ("all", "any", "not"):
            if isinstance(v, list):
                sub_parts = [_humanize_when(item) if isinstance(item, dict) else str(item) for item in v]
                joiner = " AND " if k == "all" else " OR "
                parts.append(f"({joiner.join(p for p in sub_parts if p)})")
            else:
                parts.append(f"{k}: {v}")
        else:
            parts.append(f"{k} {v}")
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Main formatter
# ---------------------------------------------------------------------------


def format_advisor_result(
    result: AdvisorResult,
    ticker: str,
    today_date: str,
    bars: "pd.DataFrame | None" = None,
) -> str:
    """Format an AdvisorResult into human-readable ASCII + emoji output.

    Parameters
    ----------
    result:
        AdvisorResult from advisor.analyze().
    ticker:
        Ticker symbol (for header display).
    today_date:
        'YYYY-MM-DD' (for header display).
    bars:
        Optional enriched DataFrame; used to extract close / MA values for display.

    Returns
    -------
    str
        Multi-line formatted string ready for print().
    """
    lines: list[str] = []
    sep = "═" * 63

    # ------------------------------------------------------------------
    # Extract today's OHLC + MA for header display
    # ------------------------------------------------------------------
    close_val: Optional[float] = None
    ma5_val: Optional[float] = None
    ma10_val: Optional[float] = None
    ma20_val: Optional[float] = None
    ma60_val: Optional[float] = None

    if bars is not None:
        try:
            ticker_rows = bars[bars["ticker"] == ticker] if "ticker" in bars.columns else bars
            date_mask = ticker_rows["trade_date"].astype(str) == today_date
            today_rows = ticker_rows[date_mask]
            if not today_rows.empty:
                row = today_rows.iloc[0]
                close_val = _safe_float(row.get("close"))
                ma5_val = _safe_float(row.get("ma5"))
                ma10_val = _safe_float(row.get("ma10"))
                ma20_val = _safe_float(row.get("ma20"))
                ma60_val = _safe_float(row.get("ma60"))
        except Exception:
            pass

    ctx = result.context_snapshot

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------
    lines.append(sep)
    lines.append(f"  Advisor: {ticker}  @ {today_date}")

    close_str = f"{close_val:.2f}" if close_val is not None else "—"
    ma5_str = f"{ma5_val:.2f}" if ma5_val is not None else "—"
    ma10_str = f"{ma10_val:.2f}" if ma10_val is not None else "—"
    ma20_str = f"{ma20_val:.2f}" if ma20_val is not None else "—"
    ma60_str = f"{ma60_val:.2f}" if ma60_val is not None else "—"
    lines.append(f"  Close: {close_str}  | MA5/10/20/60: {ma5_str}/{ma10_str}/{ma20_str}/{ma60_str}")

    # 距 MA20 / MA60 百分比 — 讓 user 看到位階過熱與否
    if close_val is not None:
        dist_parts = []
        for ma_name, ma_v in (("MA20", ma20_val), ("MA60", ma60_val)):
            if ma_v is not None and ma_v != 0:
                pct = (close_val - ma_v) / ma_v * 100
                emoji = "🔴" if pct > 30 else ("🟡" if pct > 15 else "🟢")
                dist_parts.append(f"距 {ma_name} {pct:+.1f}%{emoji}")
        if dist_parts:
            lines.append(f"  {'  '.join(dist_parts)}")

    # MA 扣抵狀態
    if ctx is not None:
        ma5e = _ma_will_rise_emoji(ctx.ma5_will_rise, close_val, ma5_val)
        ma10e = _ma_will_rise_emoji(ctx.ma10_will_rise, close_val, ma10_val)
        ma20e = _ma_will_rise_emoji(ctx.ma20_will_rise, close_val, ma20_val)
        ma60e = _ma_will_rise_emoji(ctx.ma60_will_rise, close_val, ma60_val)
        lines.append(f"  扣抵趨勢 MA5{ma5e} MA10{ma10e} MA20{ma20e} MA60{ma60e}")
    else:
        lines.append("  扣抵趨勢  [TODO 扣抵 light wiring]")

    lines.append(sep)
    lines.append("")

    # ------------------------------------------------------------------
    # Fired patterns
    # ------------------------------------------------------------------
    lines.append("📊 觸發型態 (fired patterns)")
    if not result.fired_patterns:
        lines.append("  ⚪ 今日無觸發型態")
    else:
        for hit in result.fired_patterns:
            conf_str = f"  confidence={hit.confidence:.2f}" if hit.confidence is not None else ""
            lines.append(f"  • {hit.pattern}{conf_str}")
    lines.append("")

    # ------------------------------------------------------------------
    # Scenarios (grouped by pattern)
    # ------------------------------------------------------------------
    lines.append("📋 劇本 (scenarios)")

    if not result.scenarios:
        lines.append("  ⚪ 今日無觸發劇本")
    else:
        # Load playbooks to get branch details
        _SCENARIOS_DIR_LOCAL = Path(__file__).parent
        pb_by_name: dict[str, Playbook] = {}
        try:
            raw = _load_playbooks_by_name(_SCENARIOS_DIR_LOCAL / "playbooks")
            pb_by_name = raw
        except Exception:
            pass

        for scenario in result.scenarios:
            hit = scenario.pattern_hit
            lines.append(f"  [{hit.pattern}]  劇本: {scenario.playbook_name}")

            if not scenario.enabled_branches:
                lines.append("    ⚪ （無啟用分支）")
                continue

            # Find playbook to get branch details
            playbook = pb_by_name.get(scenario.playbook_name)
            branch_map: dict[str, Branch] = {}
            if playbook:
                branch_map = {b.id: b for b in playbook.branches}

            for branch_id in scenario.enabled_branches:
                branch = branch_map.get(branch_id)
                if branch is None:
                    lines.append(f"    ⚫ {branch_id} (branch detail not found)")
                    continue
                branch_lines = _format_branch(branch, indent="    ")
                lines.extend(branch_lines)
                lines.append("")

        # Remove trailing blank if any
        while lines and lines[-1] == "":
            lines.pop()
        lines.append("")

    # ------------------------------------------------------------------
    # Manual-judgment hints (§26 防守姿態 / §30 創紀錄的跌點之後)
    # ------------------------------------------------------------------
    if result.manual_hints:
        lines.append("🧭 人工判斷情境 (manual-judgment patterns)")
        for hint in result.manual_hints:
            name = hint.get("name", "unknown")
            course_source = hint.get("course_source", "")
            trigger_reason = hint.get("trigger_reason", "")
            manual_checks: list[str] = hint.get("manual_checks", [])
            course_quotes: list[str] = hint.get("course_quotes", [])
            stubs: list[str] = hint.get("stubs", [])

            lines.append(f"  ⚠️ {name}")
            lines.append(f"    課程：{course_source}")
            lines.append(f"    觸發理由：{trigger_reason}")
            lines.append("")
            lines.append("    需自行判斷：")
            for check in manual_checks:
                lines.append(f"      {check}")
            lines.append("")
            lines.append("    課程關鍵句：")
            for quote in course_quotes:
                lines.append(f'      「{quote}」')
            if stubs:
                lines.append("")
                lines.append("    📌 STUB-NEED-USER：")
                for stub in stubs:
                    lines.append(f"      {stub}")
            lines.append("")
        lines.append("")

    # ------------------------------------------------------------------
    # Active lights
    # ------------------------------------------------------------------
    lines.append("🚨 警示 (lights)")
    if not result.active_lights:
        lines.append("  ⚪ 今日無警示燈號")
    else:
        for light in result.active_lights:
            sev_emoji = _SEVERITY_EMOJI.get(light.severity, "⚫")
            lines.append(f"  {sev_emoji} {light.light_id} — \"{light.recommendation_text}\"")
            lines.append(f"     來源: {light.course_citation.source}")
    lines.append("")

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------
    meaningful_notes = [n for n in result.notes if n and not n.startswith("WARN: ContextSnapshot field")]
    warn_notes = [n for n in result.notes if n.startswith("WARN: ContextSnapshot field")]

    if meaningful_notes or warn_notes:
        lines.append("📝 備註 (notes)")
        for note in meaningful_notes:
            lines.append(f"  • {note}")
        if warn_notes:
            import re as _re
            field_names = set()
            for n in warn_notes:
                m = _re.search(r"field '([^']+)'", n)
                if m:
                    field_names.add(m.group(1))
            if field_names:
                lines.append(f"  • Context 欄位缺失：{', '.join(sorted(field_names))}")
            else:
                lines.append(f"  • [{len(warn_notes)} 個 context 欄位缺失]")
        lines.append("")

    # ------------------------------------------------------------------
    # 重要提醒 (only when exhaust_invalid branch exists)
    # ------------------------------------------------------------------
    has_exhaust = any(
        _scenario_has_action_type(scenario, result, pb_by_name if result.scenarios else {}, "exhaust_invalid")
        for scenario in result.scenarios
    )
    if has_exhaust:
        lines.append("⚠️ 重要提醒")
        lines.append("  • ⚪ 衰竭標籤 (exhaust_invalid) 是事後確認標籤、非進場訊號")
        lines.append("  • branch hit rate ≠ 進場勝率（特別注意 ⚪ 衰竭標籤）")
        lines.append("  • 進場前請跑 feedback_trading_discipline_checklist")
        lines.append("")

    lines.append(sep)
    return "\n".join(lines)


def _safe_float(val: object) -> Optional[float]:
    """Convert value to float or return None."""
    if val is None:
        return None
    try:
        import math
        f = float(val)
        if math.isnan(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _load_playbooks_by_name(playbook_dir: Path) -> dict[str, "Playbook"]:
    """Load all playbooks and return dict keyed by setup.name."""
    from .loader import load_playbooks
    by_pattern = load_playbooks([playbook_dir])
    by_name: dict[str, "Playbook"] = {}
    for pbs in by_pattern.values():
        for pb in pbs:
            by_name[pb.setup.name] = pb
    return by_name


def _scenario_has_action_type(
    scenario: Scenario,
    result: AdvisorResult,
    pb_by_name: dict,
    action_type: str,
) -> bool:
    """Check if any enabled branch in this scenario has the given action type."""
    playbook = pb_by_name.get(scenario.playbook_name)
    if playbook is None:
        return False
    branch_map = {b.id: b for b in playbook.branches}
    for bid in scenario.enabled_branches:
        branch = branch_map.get(bid)
        if branch and branch.action.type == action_type:
            return True
    return False
