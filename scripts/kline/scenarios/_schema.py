"""Pydantic v2 schema definitions for the Playbook / Scenario Advisor layer.

This module defines the data structures used by the playbook layer.  Every
``Action`` *must* carry a ``CourseCitation`` that points back to a concrete
course article or section — fabricating rules or omitting citations is
forbidden per CLAUDE.md core constraints.

ActionType note on ``partial_exit``
-------------------------------------
``partial_exit`` is a **user-approved override** of the CLAUDE.md rule that
prohibits inventing position-sizing fractions.  Usage is permitted **only when**
``action.description`` quotes the teacher's exact phrase specifying the fraction
(e.g. "先賣一半" / "三分之一先出").  Loaders do not enforce this automatically;
enforcement is via code-review + grep.  Every ``partial_exit`` action still
requires a ``course_citation`` with ``min_length=5``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Literals / Enums
# ---------------------------------------------------------------------------

ConfirmAt = Literal["today_close", "next_open", "next_intraday", "next_close"]
"""When to check / confirm a branch condition.

- ``today_close``  — 今天收盤即可判定
- ``next_open``    — 明日一開盤確認
- ``next_intraday``— 明日盤中確認
- ``next_close``   — 明日收盤確認（最常用）
"""

ActionType = Literal[
    "entry_signal",          # 進場訊號
    "exit_signal",           # 出場訊號
    "add_position_signal",   # 加碼 (需先脫離成本 ≥ 10%, feedback_add_position_rule)
    "context_only_signal",   # 純 context 觀察，不直接下行動
    "exhaust_invalid",       # 力竭意義失效 (e.g. §06 力竭出現後反向打破)
    "watch_only",            # 持續觀察，不動
    "stop_loss_trigger",     # 停損觸發
    "partial_exit",          # **user override CLAUDE.md** — 允許但 description 必須
                             # 引用老師明示比例的原話 (e.g. "先賣一半", "三分之一先出")
                             # loader 不自動校驗；靠 code review + grep 確認
]

Severity = Literal["info", "warn", "critical"]
"""燈號嚴重程度 — 對應 Scanner UI 顏色：info=藍 / warn=黃 / critical=紅."""


# ---------------------------------------------------------------------------
# Core models
# ---------------------------------------------------------------------------


class CourseCitation(BaseModel):
    """Mandatory reference back to a concrete course source.

    ``source`` must be at least 5 characters long to prevent empty / trivial
    citations (e.g. "§3" alone is rejected; "PATTERN_DEFINITIONS §3" passes).
    """

    model_config = ConfigDict(frozen=False, extra="forbid")

    source: str = Field(
        ...,
        min_length=5,
        description="課程來源篇章，例：'明日 K 線 §20' / 'PATTERN_DEFINITIONS §3'",
    )
    article_id: Optional[str] = Field(
        default=None,
        description="PressPlay article hash (INVENTORY 中的 hex id)",
    )
    quote: Optional[str] = Field(
        default=None,
        description="老師原話節錄",
    )


class Action(BaseModel):
    """An advisor action recommendation attached to a Branch.

    Every action MUST carry a ``course_citation``; there is no default.
    """

    model_config = ConfigDict(frozen=False, extra="forbid")

    type: ActionType
    description: str = Field(..., description="給人讀的行動說明")
    course_citation: CourseCitation = Field(
        ...,
        description="必填 — 無引用則 ValidationError",
    )
    notes: list[str] = Field(default_factory=list, description="補充細節")


class Branch(BaseModel):
    """One scenario branch within a Playbook.

    ``when`` stores the mini-DSL condition dict (parsed by
    ``scenarios/condition.py``).  ``next_day_n`` controls which future bar
    shift(-N) ``next_day.*`` fields resolve to; default is 1 (隔日).
    """

    model_config = ConfigDict(frozen=False, extra="forbid")

    id: str = Field(..., description="唯一 branch id，例：'B1_明日續強'")
    when: dict[str, Any] = Field(..., description="mini-DSL 條件 dict")
    confirm_at: ConfirmAt
    next_day_n: int = Field(
        default=1,
        ge=1,
        le=3,
        description="next_day.* 對應 shift(-N)；上限 3 避免 advisor 變成 forecaster",
    )
    action: Action
    next_branch_ids: list[str] = Field(
        default_factory=list,
        description="可串多日劇本的後繼 branch ids",
    )


class PlaybookSetup(BaseModel):
    """Metadata about the setup context that activates a Playbook."""

    model_config = ConfigDict(frozen=False, extra="forbid")

    name: str = Field(..., description="setup 名稱，例：'bear_exhaustion_after_engulfing'")
    required_context: list[str] = Field(
        default_factory=list,
        description="需要 ContextSnapshot 中為 truthy 的 flag 清單",
    )


class Playbook(BaseModel):
    """A complete playbook for one pattern × one setup combination.

    ``relevant_lights`` lists ``Light.light_id`` values that should be
    surfaced alongside this playbook in the Scanner UI.
    """

    model_config = ConfigDict(frozen=False, extra="forbid")

    pattern: str = Field(..., description="觸發 pattern id，對應 patterns/<id>.detect()")
    setup: PlaybookSetup
    branches: list[Branch] = Field(..., description="應變分支清單（至少 1 個）")
    course_sources: list[CourseCitation] = Field(
        ...,
        description="整個 playbook 的來源（可多篇）",
    )
    relevant_lights: list[str] = Field(
        default_factory=list,
        description="配套燈號 light_id 清單",
    )


class Light(BaseModel):
    """A standalone advisory light evaluated independently of fired patterns.

    Corresponds to D-class 'pure concept' articles in the INVENTORY — each
    maps to exactly one light with a ``trigger_condition`` expressed in the
    same mini-DSL as ``Branch.when``.
    """

    model_config = ConfigDict(frozen=False, extra="forbid")

    light_id: str = Field(..., description="唯一燈號 id，例：'pressure_meeting_unresolved'")
    trigger_condition: dict[str, Any] = Field(
        ...,
        description="mini-DSL 觸發條件 dict",
    )
    course_citation: CourseCitation
    recommendation_text: str = Field(..., description="給人讀的提醒文字")
    severity: Severity


# ---------------------------------------------------------------------------
# Runtime / result models
# ---------------------------------------------------------------------------


class PatternHit:
    """Lightweight dataclass for a fired pattern hit.

    Kept as a plain Python dataclass (not Pydantic) for speed — advisor
    constructs many of these when scanning historical data.
    """

    __slots__ = ("pattern", "fired_at", "confidence")

    def __init__(
        self,
        pattern: str,
        fired_at: datetime | str,
        confidence: Optional[float] = None,
    ) -> None:
        self.pattern = pattern
        self.fired_at = fired_at
        self.confidence = confidence

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PatternHit):
            return NotImplemented
        return (
            self.pattern == other.pattern
            and self.fired_at == other.fired_at
            and self.confidence == other.confidence
        )

    def __repr__(self) -> str:
        return (
            f"PatternHit(pattern={self.pattern!r}, fired_at={self.fired_at!r}, "
            f"confidence={self.confidence!r})"
        )


class Scenario(BaseModel):
    """An activated playbook for a specific fired pattern."""

    model_config = ConfigDict(frozen=False, extra="forbid")

    pattern_hit: Any = Field(..., description="PatternHit instance (not Pydantic-typed)")
    playbook_name: str = Field(..., description="Playbook.setup.name")
    enabled_branches: list[str] = Field(
        default_factory=list,
        description="Branch ids whose when-condition was satisfied or pending",
    )


class ContextSnapshot(BaseModel):
    """A snapshot of all context available at the time advisor runs.

    All fields are Optional so that features.py gaps result in ``None``
    rather than a ValidationError.  The advisor logs a warning for each
    ``None`` field that a required playbook branch depends on
    (fail-loud, per feedback_no_silent_imputation).
    """

    model_config = ConfigDict(frozen=False, extra="forbid")

    # MA 扣抵狀態 (project_kouvalue_principle)
    ma5_will_rise: Optional[bool] = None
    ma10_will_rise: Optional[bool] = None
    ma20_will_rise: Optional[bool] = None
    ma60_will_rise: Optional[bool] = None

    # 攻擊區間 / 防守低點 (C03/C04/C05 features)
    attack_cost: Optional[float] = None
    defensive_low: Optional[float] = None
    attack_intent_zone_high: Optional[float] = None
    attack_intent_zone_low: Optional[float] = None

    # 當日特殊狀態 (C04/C05 features)
    is_just_broke_high: Optional[bool] = None
    is_limit_up_locked: Optional[bool] = None
    is_anomalous_volume: Optional[bool] = None  # C07 — [STUB-NEED-USER] 數字待拍板

    # 大盤創紀錄跌點 (明日 K 線 §30 / 77DC434EC71DB04553752A44C9354680)
    # 老師原話：「歷史跌點、跌幅、跌停家數，只要有其中一項」— 三個欄位獨立判斷
    taiex_record_drop_point: Optional[bool] = None   # 加權指數今日創歷史最大跌點（點數）
    taiex_record_drop_pct: Optional[bool] = None     # 加權指數今日創歷史最大跌幅（百分比）
    taiex_record_limit_down_count: Optional[bool] = None  # 跌停家數創歷史新高
    # 三項任一成立的複合旗標（OR of above three, for required_context use）
    taiex_record_any_criterion: Optional[bool] = None
    # 進場確認條件（隔日）: 「不再創新低」
    taiex_no_new_low_next_day: Optional[bool] = None  # 加權指數隔日不再創新低

    # 防守姿態判斷輔助 (明日 K 線 §26 / EF7308E2336BF7BCE94142944DB580B1)
    # STUB-NEED-USER: 大盤近期弱勢 — 具體 N 天 / 跌幅閾值課程未明示，由呼叫端注入
    taiex_recent_weak: Optional[bool] = None
    # STUB-NEED-USER: 個股相對大盤強勢 — 量化標準課程未明示，由呼叫端注入
    stock_outperforms_taiex: Optional[bool] = None

    # INTRO concepts impl (2026-06-05)
    # taiex_down_today — 大盤今日下跌（close < prev_close）
    #   用途: INTRO-3 退潮裸泳 light（大盤跌 + 個股創新高 = 強訊號）
    #   來源: taiex_history.sqlite (taiex_daily.close)
    taiex_down_today: Optional[bool] = None
    # is_after_negative_news_taiex — 近 N 日大盤曾單日大跌（利空背景）
    #   用途: INTRO-1 自救型突破 playbook required context
    #   來源: taiex_history.sqlite + SELF_RESCUE_TAIEX_DROP_PCT proxy
    #   [STUB-NEED-USER]: 「重大利空」課程定性、proxy 2% drop 待確認
    is_after_negative_news_taiex: Optional[bool] = None

    # INTRO-tier-2 (2026-06-06)
    # taiex_false_breakdown_recovered — 入門 §33 大盤假性跌破
    #   昨日急跌破過去 60 日最低收盤 + 今日跳空 + 收盤站回 = 假性跌破
    #   用途: market-regime light（規避大盤級利空恐慌）
    taiex_false_breakdown_recovered: Optional[bool] = None
    # taiex_v_sunrise — 入門 §58 V 型反彈 → V 型反轉
    #   昨日強彈（紅 K > 1%）+ 今日日出（high/low 雙高）= V 型反彈確認
    #   用途: market-regime light（強反彈確認、scanner trigger）
    taiex_v_sunrise: Optional[bool] = None


class AdvisorResult(BaseModel):
    """The full output of ``advisor.analyze()`` for one ticker × one date."""

    model_config = ConfigDict(frozen=False, extra="forbid")

    fired_patterns: list[Any] = Field(
        default_factory=list,
        description="List[PatternHit] from patterns/*.detect()",
    )
    scenarios: list[Scenario] = Field(default_factory=list)
    active_lights: list[Light] = Field(
        default_factory=list,
        description="Lights sorted critical → warn → info",
    )
    notes: list[str] = Field(
        default_factory=list,
        description="D-class 觀念提醒 + 缺 feature 的 warn 訊息",
    )
    context_snapshot: Optional[ContextSnapshot] = None
    manual_hints: list[dict] = Field(
        default_factory=list,
        description=(
            "人工判斷情境 hints — 課程明說需人工判斷的 pattern（§26 防守姿態 / §30 創紀錄跌點）。"
            "每個 hint 包含 name / course_source / trigger_reason / manual_checks / course_quotes。"
        ),
    )
