# Playbook Layer Phase 1+2 — 實作 Plan

> **日期**：2026-06-03
> **依據 spec**：`docs/superpowers/specs/2026-06-03-playbook-layer-design.md`（含 2026-06-03 Updates section）
> **依據 INVENTORY**：`docs/kline_course/mingri_kline/INVENTORY.md`（47 篇分類）
> **嚴格性**：本 plan 嚴守 CLAUDE.md 核心限制 — 每個 action / branch / light 必須有 `course_citation`；禁止「我們自己定義」的條件；只放課程明示的概念。
> **作者**：playbook layer implementation plan subagent
> **狀態**：PLAN（不寫 code，僅規劃工作項與 acceptance criteria）

---

## Context

「明日 K 線」47 篇 INVENTORY 已 audit 完，結論：
- 47 篇 ≈ 「應變劇本層」(playbook layer)
- A 類 2 篇 / B 類 8 篇 / C 類 14 項 / D 類 23 篇純觀念
- 既有 `scripts/kline/{patterns,entry,exit,scoring}/` 都是「今天發生什麼」（fact layer），無法承載「fact → branch → action」三段劇本
- D 類 49% 屬於「給人讀的提醒」，本質就是燈號 / context note，不是 boolean detect

Spec 已給出 advisor / playbook / branch / lights 架構（含 5 條 user 拍板的 open question）。本 plan 把 Phase 1 (infra) + Phase 2 (24 個 baseline playbooks) 拆成可獨立執行的 tasks。

**Blocking 什麼？**
- 主力大整合（broker_integration）、ch2_warning_integration、simulator 都需要 playbook layer 先在位
- 明日 K 線 B01~B07 規則無法用既有 entry/exit 表達，等 playbook layer

**預期影響**：scanner 從「告訴你今天發生什麼」升級成「告訴你今天發生什麼 + 明天怎麼演 + 各演法怎麼做（含課程出處）」。

---

## Phase 1 — Infrastructure（預估 2-3 天）

### Task 1.1 — 資料結構定義（pydantic schema）

**File（新建）**：`/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/_schema.py`

內容：
- `ConfirmAt` Literal：`today_close / next_open / next_intraday / next_close`
- `ActionType` Literal：`entry_signal / exit_signal / add_position_signal / context_only_signal / exhaust_invalid / watch_only / stop_loss_trigger / partial_exit`
  - **`partial_exit` 為 user override CLAUDE.md** — schema 允許，但 usage 規範寫進 docstring：必須引用老師明示比例
- `CourseCitation`：`source` (min_length=5)、`article_id`、`quote`
- `Action`：`type`, `description`, `course_citation` (required), `notes: List[str]`
- `Branch`：`id`, `when: dict`, `confirm_at`, `next_day_n: int = 1` (上限 3), `action`, `next_branch_ids: List[str]`
- `PlaybookSetup`：`name`, `required_context: List[str]`
- `Playbook`：`pattern`, `setup`, `branches`, `course_sources: List[CourseCitation]`, `relevant_lights: List[str] = []`
- `ContextSnapshot`：依 spec §4.1 完整欄位
- `PatternHit`、`Scenario`
- `Light`：`light_id`, `trigger_condition: dict`, `course_citation`, `recommendation_text`, `severity: Literal["info","warn","critical"]`
- `AdvisorResult`：含 `fired_patterns`, `scenarios`, `active_lights: List[Light]`, `notes`

**Tests（新建）**：`/Users/howard/Repository/stock-k-bar/tests/kline/scenarios/test_schema.py`
- T1.1.1：`CourseCitation.source` < 5 字元 → ValidationError
- T1.1.2：`Action` 沒帶 `course_citation` → ValidationError
- T1.1.3：`Branch.next_day_n > 3` → ValidationError
- T1.1.4：`Light.severity` 不在白名單 → ValidationError
- T1.1.5：`Playbook` 完整 round-trip（dict → model → dict）

**Acceptance**：pytest 全綠；mypy 對 `_schema.py` 無 error。

---

### Task 1.2 — Playbook & Light YAML loader

**File（新建）**：`/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/loader.py`

職責：
- `load_playbooks(dirs: List[Path]) -> Dict[str, List[Playbook]]`（key = pattern_id；value = 該 pattern 的多個 playbook）
- `load_lights(dirs: List[Path]) -> Dict[str, Light]`
- 兩者用 Pydantic 驗證；schema 失敗 → 明確 error message（指出 yaml 檔名 + 欄位）
- 載入時 dedupe by `light_id` / `playbook (pattern, setup.name)` 組合 — 重複立刻 raise
- 不做任何 IO 以外的條件 evaluate（純資料載入）

**Tests**：`tests/kline/scenarios/test_loader.py`
- T1.2.1：載入 valid yaml fixture → 正確 dict 結構
- T1.2.2：缺 course_citation 的 yaml → ValidationError 且 error 指出檔名
- T1.2.3：重複 light_id → raise
- T1.2.4：載入空目錄 → 空 dict（不 raise）

**Acceptance**：pytest 全綠；fixture yaml ≥ 3 個放在 `tests/kline/scenarios/fixtures/`。

---

### Task 1.3 — Branch / Light condition mini-DSL

**File（新建）**：`/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/condition.py`

職責：
- 解析 `when` dict → callable `(row: pd.Series, ctx: ContextSnapshot) -> bool`
- 同時支援 vectorize 版本 `(df: pd.DataFrame, ctx_df: pd.DataFrame) -> pd.Series[bool]`
- 白名單 fields（spec §4.2 + multi-day）：
  - `today.{open,high,low,close,volume}`
  - `prev.{open,high,low,close}`
  - `next_day.{open,high,low,close,gap_up,gap_down,fills_gap}`（依 `next_day_n` shift -N）
  - `prev_high_60`, `prior_low_60`
  - `attack_cost`, `attack_intent_zone_high/low`, `defensive_low`, `merged_high/low`
  - `context.broker_tier1_buy`, `context.teacher_tier`, `context.ch2_warning_score`, `context.sector_consensus_direction`, `context.ma{5,10,20,60}_will_rise`
- 運算子：`>`, `<`, `>=`, `<=`, `==`, `between [lo, hi]`, `gap_up: true/false`, `gap_down`, `fills_gap`
- 邏輯：`all: [...]`, `any: [...]`, `not: {...}`（巢狀上限 2 層）
- **任何未知 field / 未知運算子 → raise `UnknownTokenError`**（不 silent ignore）

**Tests**：`tests/kline/scenarios/test_condition.py`
- T1.3.1：簡單 `next_day.close > today.high` 對假 df 正確
- T1.3.2：`all` + `any` 組合
- T1.3.3：`next_day_n=2` 正確 shift -2
- T1.3.4：未知欄位 raise `UnknownTokenError`
- T1.3.5：vectorize 版本與 scalar 版本結果一致（property test on fixture data）
- T1.3.6：`context.broker_tier1_buy: true` 走 ContextSnapshot 路徑

**Acceptance**：pytest 全綠；vectorize 路徑跑 1000-row df < 50ms。

---

### Task 1.4 — Advisor 主入口

**File（新建）**：`/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/advisor.py`

職責：
```python
def analyze(
    bars_df: pd.DataFrame,
    today_date: str,
    ticker: str,
    context_overrides: dict | None = None,
    playbook_dirs: list[Path] | None = None,
    light_dirs: list[Path] | None = None,
) -> AdvisorResult
```

流程：
1. 用既有 `patterns/*.detect()` + `entry/*.detect()` + `exit/*.mark()` 取得 `fired_patterns`
2. 透過 `context.py` 組 `ContextSnapshot`（套用 `context_overrides`）
3. 對每個 fired_pattern 載 playbook（過濾 `setup.required_context`）
4. 對每個 branch 跑 condition.evaluate（scalar，因為 advisor 只看「今日」當下）→ `enabled_branches`（注意：branch `when` 通常含 `next_day.*`，scalar 路徑允許「未知 next_day 值 → 標 pending」狀態）
5. 對所有 lights 跑 condition → `active_lights`
6. 組 `AdvisorResult`

**注意**：advisor 不下「branch 必然發生」結論，只列舉 + 標 confirm_at。

**Tests**：`tests/kline/scenarios/test_advisor.py`
- T1.4.1：fixture df + fixture playbook → AdvisorResult 結構正確
- T1.4.2：context_overrides 正確套用
- T1.4.3：fired_patterns 為空 → scenarios 為空但 active_lights 仍可有值
- T1.4.4：playbook YAML schema 錯 → analyze() raise（fail loud）

**Acceptance**：pytest 全綠；analyze() 對單一 ticker 單日 < 200ms。

---

### Task 1.5 — Context snapshot 載入

**File（新建）**：`/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/context.py`

職責：
- `build_context_snapshot(bars_df, today_date, ticker, overrides) -> ContextSnapshot`
- K 線課程 fields 從 `scripts/kline/features.py` 抽（不重算）
  - 若 features.py 尚未提供（C03/C04/C05/C07）→ `ContextSnapshot` 對應欄位填 `None`，並在 `AdvisorResult.notes` 加 warn（fail loud，不靜默補算 — 引用 `feedback_no_silent_imputation`）
- 主力大 fields（`broker_tier1_buy`, `teacher_picked`, ...）Phase 1 全部走 `overrides` 注入，broker_integration 留到 Phase 4
- ch2_warning_score Phase 1 直接讀 `context_overrides`，integration Phase 5

**Tests**：`tests/kline/scenarios/test_context.py`
- T1.5.1：features.py 缺 attack_cost → ContextSnapshot.attack_cost = None + notes 有 warn
- T1.5.2：overrides 優先於 df 推算

**Acceptance**：pytest 全綠。

---

### Task 1.6 — Historical advisor output storage

**File（新建）**：`/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/persistence.py`

職責：
- SQLite 連線到 `data/advisor_history.db`（首次建表）
- Schema（spec Update #3）：
  - `advisor_runs (run_id INTEGER PK, ticker TEXT, trade_date TEXT, fired_pattern_count INT, scenario_count INT, created_at TEXT)`
  - `advisor_branches (run_id INT FK, scenario_idx INT, branch_id TEXT, when_json TEXT, confirm_at TEXT, next_day_n INT, action_type TEXT, course_citation_json TEXT, matched_after_n_days INT NULL)`
  - `advisor_lights (run_id INT FK, light_id TEXT, severity TEXT)`
- API：
  - `save(result: AdvisorResult) -> int` (回 run_id)
  - `load_runs(ticker, start, end) -> List[dict]`
  - `update_branch_outcome(run_id, scenario_idx, branch_id, matched_after_n_days)`（給 simulator 回填）
- read-only connection 用 separate handle；寫入完立刻 close（引用 `feedback_db_unlock`）

**Tests**：`tests/kline/scenarios/test_persistence.py`
- T1.6.1：save → load round-trip
- T1.6.2：DB lock 不發生（多次 save + load 連續執行）
- T1.6.3：update_branch_outcome 正確更新

**Acceptance**：pytest 全綠。

---

## Phase 2 — Baseline Playbooks（預估 3-4 天）

### Task 2.1 — 24 個既有 patterns 各寫 minimum playbook

**Files（新建）**：`/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/playbooks/*.yaml`

24 個 patterns（依 spec §8.5）每個一支 yaml：

| Pattern | Playbook file | Branches (最少) |
|---|---|---|
| bull_engulfing | `bull_engulfing.yaml` | 3 (續強 / 跌破 / 整理) |
| bear_engulfing | `bear_engulfing.yaml` | 3 |
| dark_double_star_anye | `dark_double_star_anye.yaml` | 3 |
| morning_star_island_reversal | `morning_star_island_reversal.yaml` | 3 |
| morning_star_harami | `morning_star_harami.yaml` | 3 |
| evening_star_island_reversal | `evening_star_island_reversal.yaml` | 3 |
| evening_star_abandoned | `evening_star_abandoned.yaml` | 3 |
| breakout_double_star | `breakout_double_star.yaml` | 3 |
| outside_three_black | `outside_three_black.yaml` | 3 |
| three_red_dadi_dangqian | `three_red_dadi_dangqian.yaml` | 3 |
| high_hanging_man | `high_hanging_man.yaml` | 3 |
| neutral_engulfing | `neutral_engulfing.yaml` | 2 (context only) |
| meeting | `meeting.yaml` | 2 |
| biting | `biting.yaml` | 2 |
| embracing | `embracing.yaml` | 2 |
| piercing_line | `piercing_line.yaml` | 3 |
| rebound | `rebound.yaml` | 2 |
| gap_reversal | `gap_reversal.yaml` | 3 |
| gap_fill_up | `gap_fill_up.yaml` | 2 |
| gap_fill_down | `gap_fill_down.yaml` | 2 |
| gap_under_pressure_reversal | `gap_under_pressure_reversal.yaml` | 2 |
| two_crow_gap | `two_crow_gap.yaml` | 2 |
| trapped | `trapped.yaml` | 2 |
| rising_falling | `rising_falling.yaml` | 2 |

**規範**：
- 每個 playbook 至少有 1 branch + 1 action
- 大部分 baseline action type = `context_only_signal` 或 `watch_only`（保守）
- 不可用 `entry_signal` / `exit_signal` 除非該 pattern 在 PATTERN_DEFINITIONS / DEFINITIONS 中老師明示
- 每個 action 強制 `course_citation`，至少寫 source 篇章（如「PATTERN_DEFINITIONS §3」「明日 K 線 §06」）
- 範例已在 spec §6.1 `bull_engulfing.yaml`

**Tests**：`tests/kline/scenarios/test_baseline_playbooks.py`
- T2.1.1：所有 yaml 都能被 loader.load_playbooks 載入無錯
- T2.1.2：所有 action.course_citation.source 長度 ≥ 5
- T2.1.3：對 24 個 patterns 各 fixture df → advisor.analyze() 跑得通且 scenarios 非空（pattern fired 時）

**Acceptance**：pytest 全綠；24 個 yaml 都有人工 review checklist（每個有正確 INVENTORY 篇章引用）。

---

### Task 2.2 — B 類 8 篇明日 K 線新 playbook

**Files（新建）**：

依 INVENTORY §B 順序：

| ID | File | 依賴 |
|---|---|---|
| B01+B02 | `playbooks/attack_cost_displayed.yaml` | C03/C04/C05 features（Task 2.4 預埋）|
| B03 | `playbooks/merged_doji_attack.yaml` | A01 pattern（patterns/merged_doji.py — 列為 Phase 3 前置）|
| B04+B05 | `playbooks/defensive_stance.yaml` | C04 + defensive_low feature（**[STUB-NEED-USER] S2** 數字）|
| B06 | `playbooks/no_attack_after_breakout.yaml` | C03 |
| B07 | `playbooks/record_decline_rebound.yaml` | **[STUB-NEED-USER] S4** 創紀錄定義 |
| B08 | `extras/scenarios/playbooks/bullish_reversal_long_bear.yaml` | 基本面資料；預設 OFF |

**規範**：
- 引用 INVENTORY B01~B08 已寫好的「老師明示」條件
- 凡 STUB 未補 → playbook 仍可寫，但 `required_context` 標出依賴的 feature；feature 缺則 advisor 略過該 playbook 並在 notes warn（不自動補數字）
- 範例見 spec §6.2 / §6.3
- B08 放 extras/ 因需基本面（CLAUDE.md 課程外條件隔離規則）

**Tests**：`tests/kline/scenarios/test_b_class_playbooks.py`
- T2.2.1：8 個 yaml loader OK
- T2.2.2：對 historical 範例日（INVENTORY 中老師舉例的個股 + 日期）→ branch 觸發符合預期
- T2.2.3：STUB feature 缺 → advisor 不 crash，notes 標 warn

**Acceptance**：pytest 全綠；範例對照表記錄哪幾檔哪幾日對應 INVENTORY 範例。

---

### Task 2.3 — D 類 23 篇 → lights

**Files（新建）**：`/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/lights/*.yaml`

依 INVENTORY §D 23 條：

| 篇 | Light file（暫名）| Severity |
|---|---|---|
| §01 沙盤推演 | （非燈號，純哲學 — 寫進 advisor README，不建 light）| — |
| §04 遇壓狀態 | `pressure_meeting_unresolved.yaml` | warn |
| §05 微弱多方趨勢 | `weak_bull_trendline_only.yaml` | info |
| §07 賣壓化解 | `selling_pressure_dissolution_required.yaml` | info |
| §08 壓力分類 | `pressure_layer_no_support.yaml` | warn |
| §09 低價股節奏 | `lowprice_first_pull_exit.yaml` | warn |
| §10 剛創新高上影線 | `just_high_upper_shadow.yaml` | info |
| §11 黑 K 高檔 | `high_black_k_warning.yaml` | warn |
| §12 漲停板隔日機率 | `limit_up_next_day_stats.yaml` | info |
| §14 向下跳空下降三法 | `gap_down_falling_three.yaml` | warn |
| §15 高檔推升下一步 | `high_pushup_next_step.yaml` | info |
| §16 日出 vs 上升三法 | `sunrise_vs_rising_three_boundary.yaml` | info |
| §17 頭部三要件 | `top_formation_three_criteria.yaml` | critical |
| §19 下山四類 | `mountain_descent_four_types.yaml` | warn |
| §22 破底股糾結 | `bottom_break_struggle.yaml` | warn |
| §27 不樂觀個股 | `pessimistic_stock_structural.yaml` | warn |
| §31 主力出貨秘密 | `manipulator_distribution_warning.yaml` | critical |
| §35 領先環境反向 | `leading_env_reverse.yaml` | warn |
| §37 缺乏力量判斷 | `lack_of_power_distinction.yaml` | info |
| §42 人性弱點 | （非燈號，純心法 — 寫進 advisor README）| — |
| §44 進出非對稱 | （非燈號，DEFINITIONS §2.12 已涵蓋）| — |
| §03 D 部分 創新高隔天 | `new_high_next_day_attack_required.yaml` | info |
| §02 D 部分 中樞 | `zhongshu_recency_bias.yaml` | info |

**淨建立 ~20 lights**（純哲學 3 篇寫進 README，不建 light）

**每個 light yaml 規範**：
```yaml
light_id: pressure_meeting_unresolved
trigger_condition:
  all:
    - today.close: "< prev_high_60"
    - today.high: ">= prev_high_60 * 0.98"
severity: warn
course_citation:
  source: "明日 K 線 §04 遇壓狀態"
  article_id: "65999135E3ED38F3E48F94481D80F54E"
  quote: "遇壓沒化解就是多一層套牢"
recommendation_text: "遇壓未化解，明日若再無紅 K 表態，視為多一層套牢 — 反向看待"
```

**規範**：
- `trigger_condition` 用同一 mini-DSL（Task 1.3 已實作）
- 純哲學篇章不建 light，列入 advisor README
- 每個 light 強制 `course_citation`

**Tests**：`tests/kline/scenarios/test_lights.py`
- T2.3.1：所有 light yaml loader OK
- T2.3.2：trigger_condition 用受限白名單 fields，未知 field raise
- T2.3.3：advisor.analyze() 回傳 active_lights 結構正確

**Acceptance**：pytest 全綠；20 lights 都對 INVENTORY 篇章有正確引用。

---

### Task 2.4 — 補 features.py C03/C04/C05/C07（Phase 2 前置）

**File（修現有）**：`/Users/howard/Repository/stock-k-bar/scripts/kline/features.py`

**為何在這個 plan 列**：B 類 playbook (B01/B04/B06) 依賴這些 feature；不補則 advisor 會永遠 warn。

- C03 `attack_intent_zone_high/low`, `intent_zone_break`
- C04 `is_just_broke_high`
- C05 `is_limit_up_locked`
- C07 `is_anomalous_volume` — **[STUB-NEED-USER] S1** 數字暫用 INVENTORY 提的退化值 `vol > vol_ma_60 * 2 AND vol > vol_max_60.shift(1) * 1.5`，並在 docstring 明確標 STUB（待 user 拍板）

**Tests**：補進 `tests/kline/test_features.py`
- T2.4.1~4：4 個 feature 各 1 個 fixture test
- T2.4.5：fixture 對齊 INVENTORY 中老師舉例的個股日期

**Acceptance**：pytest 全綠；docstring 註明每個 feature 對應 INVENTORY 條目。

---

## Phase 3 — 驗證 + 整合（後續，本 plan 不展開）

- Simulator 整合（給 `persistence.py` 寫 `matched_after_n_days`）
- broker_integration（主力大連動 — 拉 `data/zhuli_articles.db` 站前哥/管錢哥/集中分點）
- ch2_warning_integration（引用 `project_ch2_warning_score_system.md`）
- Backtest：跑歷史 advisor 輸出 vs 實際走勢，量化 branch 命中率
- A 類 patterns 實作（merged_doji、outside_three_black_like）
- C 類其他 14 項（補既有 patterns/scoring）

---

## Critical Files

### 新建（Phase 1 + 2）

**Phase 1 — infra（6 files + tests）**

- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/__init__.py`
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/_schema.py`
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/loader.py`
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/condition.py`
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/advisor.py`
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/context.py`
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/persistence.py`
- `/Users/howard/Repository/stock-k-bar/tests/kline/scenarios/test_schema.py`
- `/Users/howard/Repository/stock-k-bar/tests/kline/scenarios/test_loader.py`
- `/Users/howard/Repository/stock-k-bar/tests/kline/scenarios/test_condition.py`
- `/Users/howard/Repository/stock-k-bar/tests/kline/scenarios/test_advisor.py`
- `/Users/howard/Repository/stock-k-bar/tests/kline/scenarios/test_context.py>`
- `/Users/howard/Repository/stock-k-bar/tests/kline/scenarios/test_persistence.py`
- `/Users/howard/Repository/stock-k-bar/tests/kline/scenarios/fixtures/*.yaml` (≥ 3)

**Phase 2 — playbooks + lights（~50 files）**

- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/playbooks/*.yaml` × 24（既有 patterns baseline）
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/playbooks/*.yaml` × 5（B01~B07，B03 / B08 列在依賴清單）
- `/Users/howard/Repository/stock-k-bar/scripts/kline/extras/scenarios/playbooks/bullish_reversal_long_bear.yaml`
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/lights/*.yaml` × ~20
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/README.md`（含「§01 §42 §44 純哲學收錄」+ 整體導覽）
- `/Users/howard/Repository/stock-k-bar/tests/kline/scenarios/test_baseline_playbooks.py`
- `/Users/howard/Repository/stock-k-bar/tests/kline/scenarios/test_b_class_playbooks.py`
- `/Users/howard/Repository/stock-k-bar/tests/kline/scenarios/test_lights.py`

### 修現有

- `/Users/howard/Repository/stock-k-bar/scripts/kline/features.py`（加 C03/C04/C05/C07，Task 2.4）
- `/Users/howard/Repository/stock-k-bar/tests/kline/test_features.py`

---

## Verification Plan

**Phase 1 acceptance**：
1. `pytest tests/kline/scenarios/` 全綠
2. `mypy scripts/kline/scenarios/` 無 error
3. 可手跑 demo：
   ```python
   from kline.scenarios import advisor
   r = advisor.analyze(df, '2026-06-03', '2330', context_overrides={'broker_tier1_buy': True})
   assert r.scenarios is not None
   ```
4. `advisor_history.db` 可建表、可 save + load

**Phase 2 acceptance**：
1. 24 個 baseline playbooks 全部 loader OK + advisor analyze 跑得通
2. 5 個 B 類 playbooks + 1 個 extras playbook loader OK
3. ~20 lights 全部 loader OK
4. 對 INVENTORY 中老師舉例的個股 + 日期跑 advisor → branch / light 觸發符合 INVENTORY 描述（至少 5 個案例 manual check + 寫進 test）
5. 全部 yaml 的 `course_citation.source` 都通過 grep 檢查（min_length=5 + 包含「§」或「PATTERN_DEFINITIONS」或「DEFINITIONS」）

**Code review checklist**（每個 playbook PR 必過）：
- [ ] 每個 action 都有 course_citation 且引用 INVENTORY 中具體篇章
- [ ] branch 條件只用 mini-DSL 白名單 fields
- [ ] 無「我們自己定義」的數字（如「跌 3%」「兩天內」）除非老師明示
- [ ] `partial_exit` 使用時 description 含老師原話的比例
- [ ] 主力大 context 只在 action.notes 出現，不在 branch.when

---

## Out of Scope

- ❌ 預測 / ML / EV 計算（spec §12）
- ❌ 真實下單
- ❌ Position sizing（CLAUDE.md 禁）
- ❌ 盤中執行細節（CLAUDE.md 禁）
- ❌ A 類 / C 類其他 14 項實作（Phase 3）
- ❌ Simulator、broker_integration、ch2_warning_integration（Phase 3+）
- ❌ Scanner UI 整合

---

## Phase 1 + 2 工作量估計

| Phase | Task | 估計 |
|---|---|---|
| 1 | 1.1 schema | 0.5 d |
| 1 | 1.2 loader | 0.5 d |
| 1 | 1.3 condition DSL | 1.0 d |
| 1 | 1.4 advisor | 0.5 d |
| 1 | 1.5 context | 0.3 d |
| 1 | 1.6 persistence | 0.5 d |
| **Phase 1 subtotal** | | **~3.3 d** |
| 2 | 2.1 24 baseline playbooks | 1.5 d |
| 2 | 2.2 B 類 playbooks | 1.0 d |
| 2 | 2.3 ~20 lights | 1.0 d |
| 2 | 2.4 features.py C03-C07 | 0.5 d |
| **Phase 2 subtotal** | | **~4.0 d** |
| **Total Phase 1 + 2** | | **~7-8 d** |

---

## Open Sub-Questions（給 user 拍板，不阻擋 Phase 1 起步）

1. **`partial_exit` 比例驗證**：loader 是否要自動 grep `action.description` 確認含老師原話的數字（如「一半」「三分之一」），不符就拒絕載入？目前計畫只走 code review，未強制。
2. **`next_day_n` 上限**：spec 寫 ≤ 3，是否要鎖 1 或 2 即可？老師最多提到「兩日內」「休息一天的攻擊」=隔兩日。
3. **STUB 數字暫定值**：C07 異常放量退化值 `vol > vol_ma_60 * 2 AND vol > vol_max_60.shift(1) * 1.5` 是否可接受作為 Phase 2 暫用？正式數字仍待 user 拍板。
4. **lights/ 燈號顯示順序**：advisor 輸出 `active_lights` 是否要按 severity 排序（critical → warn → info）？預設是。
5. **`advisor_history.db` 保留期**：是否需要 retention policy（如保留近 2 年）？預設 append-only 不清。

---

**END OF PLAN**
