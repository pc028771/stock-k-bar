"""Exit groups based on course rally types.

Course source: 入門 出場點(一)(二) + 出場點(三)(下一個買點).

Each rally type has its own exit strategy per course. An exit can belong
to multiple groups (e.g., high_long_black is also relevant for trend_change).

Entry signals map to one or more groups; simulator builds the active exit
priority from the union of groups assigned to the entry.
"""
from __future__ import annotations

# === Rally-type groups (per course) ===

STRONG_ATTACK_EXITS = [
    # 轉折組合K線 (primary exit for strong attack) — 出場點(二)
    "reversal_k.dark_double_star",
    "reversal_k.bearish_engulfing",
    "reversal_k.enemy_at_gate",
    "reversal_k.evening_star",
    "reversal_k.two_crows",
    "reversal_k.gap_reversal",
    # 高檔長黑 (high-zone long black) — 黑K篇二
    "high_long_black",
    # 日出攻擊結束 — 紅K篇七 + 事件十 (sub-type of strong attack)
    "sunrise_attack_end",
    # 攻擊失敗停損 — 課程 attack failure exits
    # NOTE: former `gap_fill` (market-adjusted excess gap) was removed (audit C2);
    # course-faithful version = gap_attack_filled (跳空篇二). To compare,
    # enable via `--extras gap_fill_excess_market_adjusted`.
    "breakout_low_break",        # E4
    "breakout_price_break",      # 紅K篇五
    "gap_attack_filled",         # 跳空篇二
]

TREND_CHANGE_EXITS = [
    # 季線下彎 / 末升低 / 趨勢線 — 出場點(一) (slow trend change)
    # NOTE: former crude `neckline_break` (prior_low_20 proxy) was removed
    # (audit C3); course-precise version = ma60_neckline (季線+套牢). To compare,
    # enable via `--extras neckline_break_crude_proxy`.
    "trend_change",
    "ma60_neckline",
]

SLOW_PUSH_EXITS = [
    # 移動停利 — 出場點(二) for 緩慢推升型
    "trailing_stop",
]

ABNORMAL_CHARACTER_EXITS: list[str] = [
    # TODO: two_stage_exit not yet implemented
]

SHORT_TERM_EXITS = [
    # 短線 only — 買點與攻擊研判 (前一日低點停利)
    "prev_day_low_break",
]

SUPPLY_ZONE_EXITS = [
    # 賣壓區到達 (standalone, applies to all) — 下一個買點
    "supply_zone_reach",
]

# NOTE: `consolidation` group removed (audit C7) — 型態學 06 中樞型態 is
# explicitly NOT for trade entry/exit per course. Detector moved to
# extras.consolidation_breakdown for backtest comparison only.


# === Group registry ===

EXIT_GROUPS: dict[str, list[str]] = {
    "strong_attack": STRONG_ATTACK_EXITS,
    "trend_change": TREND_CHANGE_EXITS,
    "slow_push": SLOW_PUSH_EXITS,
    "abnormal_character": ABNORMAL_CHARACTER_EXITS,
    "short_term": SHORT_TERM_EXITS,
    "supply_zone": SUPPLY_ZONE_EXITS,
}


# === Entry → group mapping ===
# Default groups for each entry signal per course interpretation.
# Per course "型態突破 = 起點" + "強勢攻擊型 = 轉折組合K線出場"

ENTRY_EXIT_GROUPS: dict[str, list[str]] = {
    # All breakout/attack-style entries map to strong_attack + supply_zone.
    # NOTE: `consolidation` group removed (audit C7) — 中樞型態 NOT for trade
    # entry/exit per course.
    "breakout_attack": ["strong_attack", "supply_zone"],
    "pattern_breakout_only": ["strong_attack", "supply_zone"],
    "tweezer_top_breakout": ["strong_attack", "supply_zone"],
    "tweezer_top_breakout_strict": ["strong_attack", "supply_zone"],
    "shoulder_gap_up_pullback": ["strong_attack", "supply_zone"],
    "sunrise_attack": ["strong_attack", "supply_zone"],
    "combined_pattern_or_tweezer": ["strong_attack", "supply_zone"],
    # trend_reversal (currently STUB; would map to trend_change when implemented)
    "trend_reversal": ["trend_change", "supply_zone"],
}


def get_exit_priority(entry_name: str) -> list[str]:
    """Build EXIT_PRIORITY for a given entry by merging its groups.

    Course rule: a stock can be in multiple states; check transitional
    (rally-type specific) exits first, then attack-failure stops.
    """
    groups = ENTRY_EXIT_GROUPS.get(entry_name)
    if groups is None:
        raise ValueError(
            f"No exit groups defined for entry '{entry_name}'. "
            f"Available: {list(ENTRY_EXIT_GROUPS.keys())}"
        )
    # Flatten preserving order; dedup
    priority: list[str] = []
    seen: set[str] = set()
    for g in groups:
        if g not in EXIT_GROUPS:
            raise ValueError(f"Unknown exit group '{g}' for entry '{entry_name}'")
        for exit_name in EXIT_GROUPS[g]:
            if exit_name not in seen:
                priority.append(exit_name)
                seen.add(exit_name)
    return priority


__all__ = ["EXIT_GROUPS", "ENTRY_EXIT_GROUPS", "get_exit_priority"]
