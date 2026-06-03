# Playbook Layer — 應變劇本架構設計

> **狀態**：DESIGN ONLY，不寫 code，不修 `scripts/kline/` 任何檔案
> **日期**：2026-06-03
> **依據**：`docs/kline_course/mingri_kline/INVENTORY.md`（47 篇分類）+ `DEFINITIONS.md`
> **作者**：playbook layer architecture subagent
> **嚴格性**：每個 action 必須有課程引用出處（CLAUDE.md 核心原則）；禁止自行發明規則

---

## 1. Context

### 1.1 為何需要一個新的層

現有 `scripts/kline/` 拆成 4 個區塊：
- `patterns/` — 24 個轉折型態的 `detect()`（純事實判定）
- `entry/` — 進場條件（純事實判定）
- `exit/` — 出場條件（純事實判定）
- `scoring/` — 多因子打分

這四者都是「**今天發生了什麼**」的層級。讀完「明日 K 線」47 篇後，老師的核心觀念**不在「發現什麼」，而在「發現之後，明天怎麼演、各種演法該怎麼做」**：

> （第 01 篇老師原話）「明日K線並不是預測未來走勢，而是基於所有的K線理論與組合判斷，**今天就已經知道明天起K線若有怎樣出現，就代表怎樣的變化**。」

INVENTORY 結論已經給了關鍵分類：
- **A 類**（新型態）2 篇 → 可走既有 patterns/
- **B 類**（進出場規則）8 篇 → 部分可走既有 entry/exit
- **C 類**（既有補充）14 篇 → 改既有檔案
- **D 類**（純觀念心法）23 篇 → 49% **沒有獨立 detect 可寫，本質就是 playbook**

換句話說，**47 篇中接近一半本質上是「fact → branch → action」三段式的劇本**，不是 boolean detect。硬塞到 patterns/entry/exit 會被擠爆且失真。

### 1.2 跟既有 patterns/ 的關係

- patterns/*.detect() **仍然是事實源** (fact source)，不動
- playbook layer 是 patterns/entry/exit 的 **上層**
- patterns/detect = 「今天 X 成立」（事實）
- playbook = 「X 成立 → 明天可能 Y/Z/W → 對應 action A/B/C」（劇本應變）

### 1.3 跟主力大課程的整合

主力大課程（站前哥/管錢哥/集中分點/警示分數）**也是 context layer**，不是 fact layer。
- 主力大訊號 → 影響某些 branch 的成立（如「明日續強且 + 站前哥重大買盤」是強訊號分支）
- 引用記憶：`feedback_zhanqian_overrides.md`、`project_ch2_warning_score_system.md`、`project_zhuli_hitting_zone_philosophy.md`

---

## 2. Core Concept — Scenario Advisor

### 2.1 三段式資料流

```
[today's bars + features]
        │
        ▼
   patterns/*.detect()  ← fact source（既有，不動）
   entry/*.detect()
   exit/*.mark()
        │
        ▼  fired_patterns: List[PatternHit]
        │
        ▼
   scenario_advisor.analyze()   ← 新層
        │
        ├── load playbook for each fired pattern
        ├── build ContextSnapshot (broker, sector, ch2_score, MA 扣抵 ...)
        ├── enumerate branches (per playbook)
        └── attach actions (with course citation)
        │
        ▼  result: List[Scenario] → branches → actions
```

### 2.2 核心原則（取自 DEFINITIONS）

1. **沒有預測**：advisor 不算機率、不算 EV、不做 ML
2. **只列舉**：列出隔天可能出現的所有狀態 + 每個狀態對應的動作
3. **動作必有課程出處**：每個 Action 必須引用 `course_citation`（哪一篇、哪一段）
4. **進場 vs 出場非對稱**（DEFINITIONS §2.12）：
   - 進場 action → 需考慮明日走勢（branch 條件較嚴）
   - 出場 action → 不需考慮明日走勢（branch 條件較寬，直接觸發）
5. **明日 K 線判斷的兩種發生時點**（DEFINITIONS §1.1）：
   - 「今天就知道答案」（今日 K 已足夠）
   - 「明日一開盤確認」（看 open）
   - 「明日盤中或收盤確認」（看 close）
   - 這三類在 schema 中以 `confirm_at` 區分

---

## 3. Architecture

### 3.1 目錄結構（規劃）

```
scripts/kline/scenarios/         ← 新目錄（DESIGN，未實作）
├── __init__.py
├── _base.py                     ← Scenario / Branch / Action / ContextSnapshot 資料結構
├── advisor.py                   ← 主入口 analyze()
├── branch_evaluator.py          ← 解析 branch when 條件 (vectorizable)
├── playbook_loader.py           ← 讀 YAML → 編譯成 callable
├── context_builder.py           ← 組合 ContextSnapshot
├── broker_integration.py        ← 主力大訊號接點
├── ch2_warning_integration.py   ← 警示分數累積整合
├── notes/                       ← D 類純觀念的 markdown 引用（給 advisor 載入）
│   └── mingri_d_class_notes.md
└── playbooks/                   ← per pattern × per setup 的劇本
    ├── attack_cost_displayed.yaml    (B01)
    ├── attack_cost_break.yaml        (B02)
    ├── merged_doji.yaml              (A01 + B03)
    ├── defensive_stance.yaml         (B04 + B05)
    ├── no_attack_after_breakout.yaml (B06)
    ├── record_decline_rebound.yaml   (B07)
    ├── outside_three_black_like.yaml (A02 + C01)
    ├── bull_engulfing.yaml           (既有 pattern + 明日 K 線 §06)
    ├── ... （24 個既有 patterns 各一個 baseline）
    └── _shared_branches.yaml         ← 共用 branch templates
```

### 3.2 為何用 YAML 而非 Python DSL（重要 architecture decision）

| 選項 | 優點 | 缺點 |
|---|---|---|
| **YAML**（建議）| 非工程人也能 review/編輯、課程引用直觀、playbook count 多時清晰、ROC 改條件不需要 ship code | 條件表達力受限，需要一個 schema spec |
| Python DSL | 條件表達力最強、可直接 vectorize | 47 篇 → 80+ branches，分散在 .py 中難 review |
| Pydantic class | type-safe、IDE 友善 | 對非工程 review 不友善，定義膨脹 |

**決定：YAML + Pydantic schema validation**。YAML 作為 source of truth，loader 用 Pydantic 校驗。Branch 的 `when` 條件用受限 mini-language（見 §5.2）以保證 vectorizability。

### 3.3 Branch condition 寫死 vs 參數化（重要 architecture decision）

**決定：DSL 化、但有限**。

- ✅ 允許參數：`next_day.close`, `today.high`, `today.low`, `prev_high_60`, `merged_high`, `attack_cost`, `defensive_low`, `attack_intent_zone_low/high`
- ✅ 允許運算子：`>`, `<`, `>=`, `<=`, `==`, `between`, `gap_up`, `gap_down`, `fills_gap`
- ✅ 允許邏輯：`AND`, `OR`, `NOT`（巢狀有限）
- ❌ 不允許：任意 Python expression、callable lookup、外部 IO

理由：未來 `simulator.py` 要對歷史資料 vectorize 跑 playbook（驗證劇本準確度）；條件如果是任意 Python 就無法 vectorize。

---

## 4. Data Structures

### 4.1 Pydantic schemas（規劃）

```python
# scripts/kline/scenarios/_base.py

from typing import Literal, Optional, List
from pydantic import BaseModel, Field

ConfirmAt = Literal["today_close", "next_open", "next_intraday", "next_close"]
ActionType = Literal[
    "entry_signal",          # 進場
    "exit_signal",           # 出場
    "add_position_signal",   # 加碼（需先脫離成本 ≥ 10%，引用 feedback_add_position_rule）
    "context_only_signal",   # 純 context（既有 bull_engulfing 即此類）
    "exhaust_invalid",       # 力竭失效（如 §06）
    "watch_only",            # 觀察，不動
    "stop_loss_trigger",     # 停損
]

class CourseCitation(BaseModel):
    source: str               # 例："明日 K 線 §20"
    article_id: Optional[str] # PressPlay article hash（INVENTORY 中的 B44741...）
    quote: Optional[str]      # 老師原話節錄

class Action(BaseModel):
    type: ActionType
    description: str          # 給人讀
    course_citation: CourseCitation  # 強制；無 citation 不准存在
    notes: List[str] = []     # 補充細節（如「短線專用」「不適用於 ETF」）

class Branch(BaseModel):
    id: str                   # 例 "B1_明日續強"
    when: dict                # mini-language DSL（branch_evaluator 解析）
    confirm_at: ConfirmAt
    action: Action
    next_branch_ids: List[str] = []  # 可串多日劇本

class PlaybookSetup(BaseModel):
    name: str                 # 例 "bear_exhaustion_context"
    required_context: List[str] = []  # 必要 context flag

class Playbook(BaseModel):
    pattern: str              # 觸發 pattern id（對應 patterns/<name>.detect 或 entry/<name>）
    setup: PlaybookSetup
    branches: List[Branch]
    course_sources: List[CourseCitation]  # 整個 playbook 的來源（可多篇）

class ContextSnapshot(BaseModel):
    ticker: str
    trade_date: str
    # K-line course context
    is_just_broke_high: bool
    attack_cost_displayed: Optional[float]
    attack_intent_zone_high: Optional[float]
    attack_intent_zone_low: Optional[float]
    defensive_low: Optional[float]
    is_limit_up_locked: bool
    is_anomalous_volume: bool
    # MA 扣抵狀態（記憶 project_kouvalue_principle）
    ma5_will_rise: bool
    ma10_will_rise: bool
    ma20_will_rise: bool
    ma60_will_rise: bool
    # 主力大 context
    broker_tier1_buy: bool          # 站前哥/管錢哥 重大買盤
    broker_concentration: float     # 集中分點分數
    teacher_picked: bool             # 老師當日 line/直播點名
    teacher_tier: Optional[str]      # core / strong / mention / context
    # Sector
    sector_consensus_direction: Optional[Literal["bull", "bear", "mixed"]]
    # 警示分數累積（ch2_warning_score）
    ch2_warning_score: int           # 0~6

class PatternHit(BaseModel):
    pattern_id: str
    confidence: Optional[float] = None
    metadata: dict = {}

class Scenario(BaseModel):
    fired_pattern: PatternHit
    context: ContextSnapshot
    playbook_id: str
    branches: List[Branch]   # 從 playbook 載入，已套用 context filter

class AdvisorResult(BaseModel):
    ticker: str
    trade_date: str
    fired_patterns: List[PatternHit]
    scenarios: List[Scenario]
    notes: List[str]         # D 類純觀念的人話提醒
```

### 4.2 Branch when DSL spec（mini-language）

```yaml
# 範例 1：簡單
when:
  next_day.close: "> today.high"

# 範例 2：AND
when:
  all:
    - next_day.close: "> today.high"
    - next_day.gap_up: true

# 範例 3：OR
when:
  any:
    - next_day.close: "< attack_cost"
    - next_day.close: "< today.low"

# 範例 4：巢狀（限 2 層）
when:
  all:
    - any:
        - next_day.close: "> attack_intent_zone_high"
        - next_day.gap_up: true
    - context.broker_tier1_buy: true
```

支援 fields（白名單）：
- `today.{open,high,low,close,volume}`
- `prev.{open,high,low,close}`
- `next_day.{open,high,low,close,gap_up,gap_down,fills_gap}`
- `prev_high_60`, `prior_low_60`
- `attack_cost`, `attack_intent_zone_high/low`, `defensive_low`, `merged_high/low`
- `context.broker_tier1_buy`, `context.teacher_tier`, `context.ch2_warning_score`, `context.sector_consensus_direction`, `context.ma{5,10,20,60}_will_rise`

---

## 5. API Design

```python
from kline.scenarios import advisor

result = advisor.analyze(
    bars_df=df,                # 已含 features
    today_date='2026-06-03',
    ticker='2330',
    context_overrides={        # 可選：手動傳主力大 / 老師訊號
        'teacher_picked': True,
        'teacher_tier': 'core',
        'broker_tier1_buy': True,
    },
    playbook_dirs=['scripts/kline/scenarios/playbooks'],  # 可加 extras
)

# result.fired_patterns: List[PatternHit]
# result.scenarios: List[Scenario]
# for each scenario:
#   scenario.branches[i].action.course_citation  ← 強制存在
#   scenario.branches[i].when
#   scenario.branches[i].confirm_at
```

### 5.1 Simulator integration（規劃）

```python
from kline.scenarios import advisor, simulator

# 對歷史回測：跑 playbook 在每一天，記錄 branch 命中率
sim = simulator.PlaybookSimulator(advisor)
report = sim.run(
    bars_df=df_full_history,
    start='2024-01-01',
    end='2026-06-03',
)
# report 內容：branch_X 命中 N 次、命中後 action 真實準確度
```

### 5.2 整合到既有 backtest / scanner（不破壞）

advisor 是 **append-only** layer。既有 `scripts/scanner.py`、`scripts/backtest.py` 不需改。新增 `scripts/scenario_scanner.py` 作為使用者入口。

---

## 6. Playbook YAML 範例

### 6.1 bull_engulfing.yaml（既有 pattern + 明日 K 線 §06 §11）

```yaml
pattern: bull_engulfing
setup:
  name: bear_exhaustion_after_engulfing
  required_context:
    - bear_exhaustion_context
course_sources:
  - source: "明日 K 線 §06"
    article_id: "08B2F8497AAE44CAF4C9DAC348608575"  # 第 01 篇（沙盤推演原則）
  - source: "PATTERN_DEFINITIONS §3"
    quote: "多頭吞噬本身不是買點"

branches:
  - id: "B1_明日續強且站前哥買"
    when:
      all:
        - next_day.close: "> today.high"
        - context.broker_tier1_buy: true
    confirm_at: next_close
    action:
      type: context_only_signal
      description: "空單回補力量 + 站前哥背書，仍不是直接進場訊號；列入 watchlist"
      course_citation:
        source: "PATTERN_DEFINITIONS §3 + feedback_zhanqian_overrides"
        quote: "多頭吞噬本身不是買點 / 站前哥重大買盤 override 老師震盪警語"

  - id: "B2_明日跌破今日 low"
    when:
      next_day.close: "< today.low"
    confirm_at: next_close
    action:
      type: exhaust_invalid
      description: "空方力竭意義被打破，回到下跌走勢預期"
      course_citation:
        source: "明日 K 線 §07 賣壓化解失敗"

  - id: "B3_明日小幅整理"
    when:
      all:
        - next_day.close: ">= today.low"
        - next_day.close: "<= today.high"
    confirm_at: next_close
    action:
      type: watch_only
      description: "力竭觀察期，等待後續確認；不進場"
      course_citation:
        source: "PATTERN_DEFINITIONS §3"
```

### 6.2 attack_cost_displayed.yaml（B01 + B02）

```yaml
pattern: attack_cost_displayed
setup:
  name: just_broke_high_and_limit_up_locked
  required_context:
    - is_just_broke_high
    - is_limit_up_locked
course_sources:
  - source: "明日 K 線 §20 攻擊成本顯現日"
    article_id: "B44741FE824D0798CC91C1521D5B0FF7"
  - source: "明日 K 線 §28 不攻擊"
    article_id: "E4383C1F106A64F729CAD12E0D4B25F2"

branches:
  - id: "B1_明日未跌破攻擊成本"
    when:
      next_day.close: ">= attack_cost"
    confirm_at: next_close
    action:
      type: watch_only
      description: "攻擊成本未跌破，持續持有等待攻擊延續"
      course_citation:
        source: "明日 K 線 §20"

  - id: "B2_明日跌破攻擊成本"
    when:
      next_day.close: "< attack_cost"
    confirm_at: next_close
    action:
      type: exit_signal
      description: "短線價差交易者出場；中期投資仍以攻擊假設（前日紅K低點）為停損"
      notes:
        - "短線專用"
        - "中期投資不適用，沿用 prev_day_low_break"
      course_citation:
        source: "明日 K 線 §20 + §28"
        quote: "這一次創新高股價並沒有要攻擊"

  - id: "B3_明日跳空攻擊"
    when:
      all:
        - next_day.gap_up: true
        - next_day.open: "> today.high"
    confirm_at: next_open
    action:
      type: context_only_signal
      description: "攻擊延續確認；非新進場訊號（已在攻擊中）"
      course_citation:
        source: "明日 K 線 §20 + §32 休息一天的攻擊"
```

### 6.3 defensive_stance.yaml（B04 + B05，跟主力大整合最深）

```yaml
pattern: defensive_stance
setup:
  name: stock_held_during_market_pessimism
  required_context:
    - is_just_broke_high
    - defensive_low_established
course_sources:
  - source: "明日 K 線 §26 防守姿態"
    article_id: "EF7308E2336BF7BCE94142944DB580B1"

branches:
  - id: "B1_大盤穩定且出現攻擊企圖"
    when:
      all:
        - context.sector_consensus_direction: "bull"
        - any:
            - next_day.gap_up: true
            - next_day.close: "> today.high"
    confirm_at: next_close
    action:
      type: entry_signal
      description: "防守姿態 + 大盤恢復 → 進場訊號（與站前哥重大買盤可疊加為強訊號）"
      course_citation:
        source: "明日 K 線 §26"
      notes:
        - "如同時 broker_tier1_buy=true，升級為強訊號（引用 feedback_zhanqian_overrides）"

  - id: "B2_跌破防守低點"
    when:
      next_day.close: "< defensive_low"
    confirm_at: next_close
    action:
      type: exit_signal
      description: "「主力沒有要攻擊的意思」 — 出清"
      course_citation:
        source: "明日 K 線 §26"
        quote: "跌破防守價就是根本沒有要攻擊的意思"

  - id: "B3_續守無動作"
    when:
      all:
        - next_day.close: ">= defensive_low"
        - next_day.close: "<= today.high"
    confirm_at: next_close
    action:
      type: watch_only
      description: "繼續持有，等大盤氣氛轉變"
      course_citation:
        source: "明日 K 線 §26"
```

---

## 7. Integration Points

### 7.1 跟 patterns/ 的關係

- patterns/*.detect() 的輸出 → `PatternHit`
- advisor 對每個 PatternHit，從 `playbooks/<pattern_id>.yaml` 載入劇本
- 一個 pattern 可有多個 playbook（不同 setup） — advisor 透過 `setup.required_context` 過濾

### 7.2 跟主力大 broker integration（broker_integration.py）

```python
class BrokerIntegration:
    def fetch_today_signals(self, ticker: str, date: str) -> dict:
        # 來源：data/zhuli_articles.db / broker_activity_notes / 主力大 daily focus
        return {
            'broker_tier1_buy': ...,    # 站前哥/管錢哥重大買盤
            'broker_concentration': ..., # 集中分點分數
            'teacher_picked': ...,
            'teacher_tier': ...,
        }
```

**關鍵規則（引用 feedback_zhanqian_overrides）**：
- `broker_tier1_buy=true` → 可 override 老師「震盪」警語
- 任何 `entry_signal` 分支若同時 `broker_tier1_buy=true` → metadata 升級為 `"強訊號"`
- 不影響 branch when，只在 action.notes 加註

### 7.3 跟 ch2_warning_score 整合（ch2_warning_integration.py）

引用 `project_ch2_warning_score_system.md`：6 個 ch2 trigger AND 條件。

整合方式：
- `ContextSnapshot.ch2_warning_score` 0~6 帶入 advisor
- 高分（≥ 4）→ 任何 `exit_signal` 分支提前觸發、`entry_signal` 分支抑制
- 在 playbook YAML 用 `context.ch2_warning_score: ">= 4"` 顯式啟用

### 7.4 跟 features.py 的關係

advisor 不算新 feature，**所有 context 欄位都需要 features.py 先算**：
- C03 attack_intent_zone_high/low
- C04 is_just_broke_high
- C05 is_limit_up_locked
- C07 is_anomalous_volume
- 既有 MA 扣抵相關（`ma{5,10,20,60}_will_rise`）

playbook layer **不擅自加 features**，缺欄位則 advisor 報錯（fail loud，引用 `feedback_no_silent_imputation`）。

### 7.5 跟 extras/ 的關係

- 課程內 playbook → `scripts/kline/scenarios/playbooks/`
- 課程外 playbook（如基本面 filter 的 B08）→ `scripts/kline/extras/scenarios/playbooks/`，預設 OFF
- advisor 用 `playbook_dirs` 參數控制載入哪些目錄

---

## 8. 47 篇對應 scenarios 規劃表

### 8.1 A 類（2 篇）→ 新 playbook
- §24 合併十字線 → `playbooks/merged_doji.yaml`（含 B03 攻擊分支）
- §43 類外側三黑 → `playbooks/outside_three_black_like.yaml`

### 8.2 B 類（8 篇）→ 新 playbook
- §20 攻擊成本顯現 → `attack_cost_displayed.yaml`（B01+B02）
- §26 防守姿態 → `defensive_stance.yaml`（B04+B05）
- §28 不攻擊 → `no_attack_after_breakout.yaml`（B06）
- §30 創紀錄跌點不再破底 → `record_decline_rebound.yaml`（B07）
- §45+§46 空頭買在趨勢改變 → `extras/scenarios/playbooks/bullish_reversal_long_bear.yaml`（B08，需基本面）

### 8.3 C 類（14 項）→ 補充既有 playbook 的分支
- C02 高檔長黑 加缺口回補分支 → `playbooks/high_long_black.yaml` 新增 B_缺口回補分支
- C06 高檔吊首投機股場景 → `playbooks/high_hanging_man.yaml` 加 setup `speculative_stock`
- C13 雙鴉躍空大盤場景 → `playbooks/two_crow_gap.yaml` 加 setup `index_with_weighted_dominance`
- C11 中樞型態 → 新 `playbooks/zhongshu_pattern.yaml`
- C12 內困翻黑變跳空反轉 → 跨 playbook 串接（trapped → gap_reversal next_branch_ids）

### 8.4 D 類（23 項）→ `notes/mingri_d_class_notes.md`
- advisor 載入此檔，根據 fired_pattern 拼接相關提醒到 `AdvisorResult.notes`
- 不是 branch 條件，只是「給人看的補充」

### 8.5 24 個既有 patterns 各對應 scenarios 粗估

| Pattern | Playbook 數 | 主要 branches |
|---|---|---|
| bull_engulfing | 1 | 3 (續強/跌破/整理) |
| bear_engulfing | 1 | 3 (續弱/反彈/整理) |
| dark_double_star_anye | 1 | 3 |
| morning_star_island_reversal | 1 | 3 |
| morning_star_harami | 1 | 3 |
| evening_star_island_reversal | 1 | 3 |
| evening_star_abandoned | 1 | 3 |
| breakout_double_star | 1 | 3 |
| outside_three_black | 1（擴充至 like 形成 2） | 3+ |
| three_red_dadi_dangqian | 1 | 3 |
| high_hanging_man | 2（一般 + speculative）| 3+3 |
| neutral_engulfing | 1 | 2 (context only) |
| meeting / biting / embracing | 1 each | 各 2 |
| piercing_line | 1 | 3 |
| rebound | 1 | 2 |
| gap_reversal / gap_fill_up/down / gap_under_pressure_reversal / two_crow_gap | 1 each | 各 2~3 |
| trapped | 1（接 gap_reversal） | 2 |
| rising_falling | 1 | 2 |

**粗估**：24 個 patterns → 約 25~28 個 playbook（高檔吊首拆 2）；branches 總數約 70~85。
加上 A/B 類新 playbook ~7 個 → 總 playbook 約 32~35。

---

## 9. 實作優先順序（Phase 規劃）

### Phase 1：基礎 scenarios infra （估 2~3 天）
- `_base.py` schemas (Pydantic)
- `playbook_loader.py` (YAML → Playbook，含 schema validation)
- `branch_evaluator.py` (DSL mini-language parser + vectorizable evaluator)
- `context_builder.py` skeleton（先只接 features.py 已有欄位，主力大 stub）
- `advisor.py` analyze() 主邏輯
- unit tests for parser / evaluator
- **產出**：一個能讀 YAML、parse when DSL、輸出 branches 的 advisor

### Phase 2：24 個既有 patterns 各寫 baseline playbook（估 3~4 天）
- 每個 playbook 至少 2~3 個 branches（續強/跌破/整理）
- 所有 action 都引用課程出處
- 大量 action type = `context_only_signal` 或 `watch_only`（保守 baseline）
- 對 24 個 patterns 跑 advisor.analyze() 跨 365 個歷史日，confirm 不 crash

**Phase 1+2 工作量估計：5~7 天工程時間**（含 review + 修正 YAML schema 細節）

### Phase 3：高優先 B 類 entry/exit（估 3~4 天）
- B01/B02 attack_cost
- B03 merged_doji_attack
- B04/B05 defensive_stance
- B06 no_attack
- 需先補 features.py 的 C03/C04/C05（attack_intent_zone, is_just_broke_high, is_limit_up_locked）

### Phase 4：broker_integration（估 2~3 天）
- 從 `data/zhuli_articles.db` + `docs/主力大課程/` 抽取每日訊號
- 站前哥/管錢哥/集中分點欄位
- 整合 `feedback_zhanqian_overrides` 升級邏輯

### Phase 5：警示分數 + ch2 整合（估 1~2 天）
- 引用 `project_ch2_warning_score_system.md` 既有實作

### Phase 6：simulator + 回測歷史劇本（估 3~5 天）
- 對歷史日跑 advisor，記錄 branch 命中分布
- 跟 simulator.py（exit 模擬）合併輸出整合 report

---

## 10. Critical files to be created（未來實作時）

絕對路徑：

- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/__init__.py`
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/_base.py`
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/advisor.py`
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/branch_evaluator.py`
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/playbook_loader.py`
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/context_builder.py`
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/broker_integration.py`
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/ch2_warning_integration.py`
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/playbooks/*.yaml` (~32 個)
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/notes/mingri_d_class_notes.md`
- `/Users/howard/Repository/stock-k-bar/tests/kline/scenarios/test_*.py`

修現有檔（Phase 3 前置）：
- `/Users/howard/Repository/stock-k-bar/scripts/kline/features.py` （加 C03/C04/C05/C07）
- `/Users/howard/Repository/stock-k-bar/scripts/kline/course_proxy_constants.py` （補 STUB-NEED-USER 數字）

---

## 11. Open Questions（待 user 拍板）

1. **Playbook format**：YAML（建議）vs Python DSL vs Pydantic class？本文件已建議 YAML，但要確認非工程人是否真的會 review YAML。

2. **Branch 條件 — `next_day` 是否參數化「天數」**？目前 DSL 只有 `next_day`（隔日）。老師有些劇本是「兩日內」（如「休息一天的攻擊」§32），是否要支援 `next_day_n: 1/2/3`？影響 vectorize 複雜度。

3. **Scenario 歷史記錄**：是否需要把每天 advisor 的輸出存進 DB（給 simulator 回看）？若要，schema 怎麼設計？儲存量估計？

4. **Action types 是否完備**？目前 7 個 type（entry/exit/add/context/exhaust_invalid/watch/stop_loss）。是否需要再分 `partial_exit`、`scale_in`？**注意 CLAUDE.md 規則**：「禁止自行發明減碼比例（如 1/3、1/2）」— 若加 `partial_exit`，老師必須有明示比例才能用，否則違規。建議**不加**，先用 `exit_signal`。

5. **D 類純觀念怎麼讓 advisor「主動提醒」**？目前設計是 advisor 根據 fired_pattern 撈相關 D 類 notes，但「相關性」如何決定？建議在 YAML playbook 加 `relevant_notes: ["D §42 人性弱點"]` 顯式引用。

---

## 12. Out of scope

- ❌ **預測 / ML / EV 計算** — 應變劇本不做預測（DEFINITIONS §1.1 老師原話禁止）
- ❌ **Action 真正執行（下單）** — playbook 只輸出建議
- ❌ **Position sizing**（倉位多少）— CLAUDE.md 禁止自行發明
- ❌ **盤中執行細節**（等幾分鐘、量縮再出）— CLAUDE.md 禁止
- ❌ **連續 N 天失效條件** — 除非課程明示，否則不可寫
- ❌ **Branch 機率 ranking** — 老師劇本不附機率，advisor 也不附

---

## 13. Risk & 防範

| 風險 | 防範 |
|---|---|
| YAML 累積後條件互斥不全（branches 漏掉某種隔日狀態）| `branch_evaluator` 加 `assert_branches_exhaustive=true` 模式，未覆蓋區間時 warn |
| Course citation 被空字串繞過 | Pydantic `CourseCitation.source` 設 `min_length=5`；loader 拒絕載入 |
| 主力大訊號污染課程內 playbook | playbook 中只允許 `context.broker_*` 在 action.notes，不能影響 branch when（branch 只用 K 線 fact）|
| advisor 隨意推論「常識」分支 | code review checklist：每個新 branch PR 必須引用 INVENTORY 中對應的篇章 |
| 主力大 DB lock | `broker_integration.fetch_today_signals` 用 read-only connection + 立即 close（引用 `feedback_db_unlock`）|

---

## 14. 與既有設計文件的關係

- `2026-05-15-kline-system-redesign-design.md`：本文件是其延伸，scenarios/ 是 redesign 的第 5 層（patterns/entry/exit/scoring 之上）
- `2026-05-27-shared-data-layer-design.md`：advisor 依賴 shared data layer 提供 features + 主力大 daily signals

---

**END OF DESIGN**
