"""Manual-judgment hints — defensive_stance + record_decline_rebound.

These are not detect() patterns because the course explicitly says they
require human judgment ("交易藝術"). Instead, when a stock's context
matches the "疑似情境", we emit a hint to guide user's manual decision.

Course sources
--------------
- 明日 K 線 §26「防守姿態」 — EF7308E2336BF7BCE94142944DB580B1
- 明日 K 線 §30「創紀錄的跌點之後」 — 77DC434EC71DB04553752A44C9354680

Design constraints (per CLAUDE.md)
-----------------------------------
- 課程關鍵句必須逐字摘錄、不重述。
- 不可自創課程沒給的數字 → STUB-NEED-USER 明標。
- 不可改既有 detect() / playbook / scenario 邏輯。
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from ._schema import ContextSnapshot

# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------
#
# Each hint function returns either None (not triggered) or a dict:
#
#   {
#       "name":          str,   # "defensive_stance" | "record_decline_rebound"
#       "course_source": str,   # 課程來源標記
#       "trigger_reason": str,  # 人讀的觸發說明
#       "manual_checks": list[str],  # 使用者需自行判斷的項目
#       "course_quotes": list[str],  # 逐字引用老師原話
#   }
#
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# §26 防守姿態 hint
# ---------------------------------------------------------------------------


def check_defensive_stance_hint(
    row: "pd.Series",
    ctx: ContextSnapshot,
) -> dict[str, Any] | None:
    """Return hint dict if defensive_stance situation likely present, else None.

    Trigger conditions (based strictly on course text — §26):
    1. ctx.taiex_recent_weak is True
       → 大盤近期呈現弱勢 / 悲觀氣氛（老師原話：「大盤環境不佳、甚至是悲觀氣氛濃厚時」）
       STUB-NEED-USER: 具體 N 天 / 跌幅閾值課程未明示，由呼叫端注入 taiex_recent_weak。

    2. ctx.defensive_low is not None
       → 課程已有此欄位（attack/defensive_low），代表個股有明確防守價位。

    3. ctx.stock_outperforms_taiex is True（個股相對強勢）
       STUB-NEED-USER: 相對強勢量化標準課程未明示，由呼叫端注入 stock_outperforms_taiex。

    If both taiex_recent_weak and defensive_low are None (no context at all),
    we do NOT emit a hint to avoid noise.
    """
    # Need at least one of the two primary signals to avoid false positive flood
    has_taiex_signal = ctx.taiex_recent_weak is True
    has_defensive_price = ctx.defensive_low is not None

    if not has_taiex_signal and not has_defensive_price:
        return None

    # Build trigger_reason from available context
    reasons: list[str] = []
    if has_taiex_signal:
        reasons.append("大盤近期弱勢 / 悲觀氣氛 (taiex_recent_weak=True)")
    if has_defensive_price:
        reasons.append(f"個股有明確防守價位 (defensive_low={ctx.defensive_low})")
    if ctx.stock_outperforms_taiex is True:
        reasons.append("個股相對大盤強勢 (stock_outperforms_taiex=True)")

    trigger_reason = "；".join(reasons)

    return {
        "name": "defensive_stance",
        "course_source": "明日 K 線 §26「防守姿態」（EF7308E2336BF7BCE94142944DB580B1）",
        "trigger_reason": trigger_reason,
        "manual_checks": [
            "1. 主力是否已介入（觀察前期是否有跳空漲停、攻擊拉抬等形跡）",
            "2. 大盤悲觀氣氛是否將消失（隔日大盤是否趨穩）",
            "3. 股價是否出現跳空攻擊 / 推升攻擊企圖",
            "4. 防守價位是否守住（跌破 defensive_low 則無效）",
        ],
        "course_quotes": [
            "悲觀氣氛消失的時候」就是攻擊時點",
            "跌破防守價就是根本沒有要攻擊的意思",
            "條件一：要有主力已經介入，開始花力氣拉抬股價。條件二：在市場悲觀的氣氛中，股價明顯守住某個價位。",
        ],
        # STUB-NEED-USER list — for transparency
        "stubs": [
            "STUB-NEED-USER: taiex_recent_weak — 大盤近 N 天弱勢的 N 值及跌幅閾值課程未明示",
            "STUB-NEED-USER: stock_outperforms_taiex — 相對強勢量化標準課程未明示",
        ],
    }


# ---------------------------------------------------------------------------
# §30 創紀錄的跌點之後 hint
# ---------------------------------------------------------------------------


def check_record_decline_rebound_hint(
    row: "pd.Series",
    ctx: ContextSnapshot,
) -> dict[str, Any] | None:
    """Return hint dict if record_decline_rebound situation likely present, else None.

    Trigger conditions (based strictly on course text — §30):

    Primary trigger (today):
        ctx.taiex_record_any_criterion is True
        → 今日大盤 = 歷史跌點 / 跌幅 / 跌停家數任一創紀錄
        （老師原話：「歷史跌點、跌幅、跌停家數，只要有其中一項」）
        ContextSnapshot 已有此欄位。

    D+1 confirmation (optional, not required to emit hint):
        ctx.taiex_no_new_low_next_day is True
        → 隔日不再創新低 → 進場機會更強
        （老師原話：「隔日不再創新低」時，是進場機會）

    If taiex_record_any_criterion is None or False → return None.
    """
    if not ctx.taiex_record_any_criterion:
        return None

    # Build trigger_reason
    parts: list[str] = ["今日大盤創歷史跌點 / 跌幅 / 跌停家數紀錄 (taiex_record_any_criterion=True)"]
    if ctx.taiex_record_drop_point is True:
        parts.append("• 加權指數單日跌點創歷史新高")
    if ctx.taiex_record_drop_pct is True:
        parts.append("• 加權指數單日跌幅創歷史新高")
    if ctx.taiex_record_limit_down_count is True:
        parts.append("• 跌停家數創歷史新高")

    # D+1 confirmation status
    if ctx.taiex_no_new_low_next_day is True:
        parts.append("✅ D+1 確認：隔日不再創新低 → 進場訊號強化")
    elif ctx.taiex_no_new_low_next_day is False:
        parts.append("❌ D+1：隔日仍創新低 → 跌勢尚未結束，暫不進場")
    else:
        parts.append("⏳ D+1 尚未確認：需隔日觀察是否「不再創新低」")

    trigger_reason = "\n    ".join(parts)

    return {
        "name": "record_decline_rebound",
        "course_source": "明日 K 線 §30「創紀錄的跌點之後」（77DC434EC71DB04553752A44C9354680）",
        "trigger_reason": trigger_reason,
        "manual_checks": [
            "1. 隔日是否「不再創新低」（不是技術分析、是交易藝術）",
            "2. 個股本質是否非常爛（若是 → 排除，不適用本篇邏輯）",
            "3. 定位短線進場 OR 投資？（兩者均可，差別只在持有時間）",
            "4. 隔日未創新低但後續又再創低 → 退出，此次機會不成立",
        ],
        "course_quotes": [
            "隔日不再創新低」時，因為都已經大幅度的短期下跌，會產生出賣壓中空的區段",
            "除了本質非常爛的公司之外，買進的差別只不過是後來漲多、漲少的問題而已",
            "往往是千載難逢的短線機會，不是技術分析，而是「交易的藝術」",
        ],
        # No stubs: ContextSnapshot already has all required fields for this hint
        "stubs": [],
    }
