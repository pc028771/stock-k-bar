# Playbook Layer Phase 3 — 驗證 / 整合 / 補完 Plan

> **日期**：2026-06-03
> **承接**：`docs/superpowers/plans/2026-06-03-playbook-layer-phase1-plan.md`（Phase 1+2 已完工）
> **依據 audit**：`docs/kline_course/COMPLIANCE_AUDIT_2026-06-03.md`（Phase 2 pass，8 項 warning 延後）
> **依據 INVENTORY**：`docs/kline_course/mingri_kline/INVENTORY.md`（B/C 類完整清單）
> **作者**：Phase 3 implementation plan subagent
> **狀態**：PLAN（只規劃工作項，不寫 code）

---

## Context

Phase 1+2 完成後：
- advisor / playbook / lights infra 在位（29 baseline playbooks + 20 lights + features.py C03–C07）
- Audit 確認零 CLAUDE.md 違反，但留 8 項 warning（W1–W8）+ 8 個 STUB-NEED-USER（S1–S8）
- 三大整合 (simulator / broker / ch2_warning) 全部 stub，advisor 只能接受 `context_overrides` 注入
- A 類 patterns（merged_doji、outside_three_black_like）尚未實作；C 類 14 項只完成 C03/C04/C05/C07 part

Phase 3 目標：**讓 advisor 可量化、可連動主力大、可整合 ch2 警示，並補齊課程明示但仍缺的條目**。本 plan 嚴守 CLAUDE.md：每個 task 都標明課程／memory 出處；不自創條件；broker 訊號**只進 action.notes，禁止進 branch.when**（spec 既定）。

**為何不再延後**：
- W1/W7 article_id 缺失影響後續 trace 成本，順手修
- Simulator 整合是「能不能繼續做 playbook」的回饋迴路：沒有 matched_after_n_days 回填，後續新增 branch 無從調整
- broker_integration 是主力大課程框架實際發揮 ROI 的關鍵（`feedback_zhanqian_overrides`）
- ch2_warning 已在 memory 中標 🔥🔥（`project_ch2_warning_score_system.md`），「5/19 虛擬時光機對 8064/8027 都亮燈救得了」

---

## Quick Wins — Audit Warnings + STUB 分類（~0.5 d）

### Task 3.0.1 — 修 W1+W7 補齊 article_id

**File（修現有）**：
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/playbooks/merged_doji_attack.yaml`（5 處：line 21/36/52/70/88）
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/lights/*.yaml`（19 個檔案缺 article_id；`pressure_meeting_unresolved.yaml` 已有可作範例）

**對照表**（依 INVENTORY §D + 既有 light 檔名）：

| Light file | source 篇 | article_id |
|---|---|---|
| `weak_bull_trendline_only.yaml` | 明日 K 線 §05 | `DFA0948468F5B51D57D0E841F5EC4F9B` |
| `selling_pressure_dissolution_required.yaml` | §07 | `910E8BDF113C42643EF26394CDD14007` |
| `pressure_layer_no_support.yaml` | §08 | `B5DB7A687DA4FA572833411DE9CD88D8` |
| `lowprice_first_pull_exit.yaml` | §09 | `5710C4E8D0ACFBD5926A74A54853999C` |
| `just_high_upper_shadow.yaml` | §10 | `BDD39904FC85EE1BC6724C77C45AD522` |
| `high_black_k_warning.yaml` | §11 | `4C255C33FBEC3AD05DE05F8C0284C4F8` |
| `limit_up_next_day_stats.yaml` | §12 | `805F4E23E8C9E61F2020B0FFB014B706` |
| `gap_down_falling_three.yaml` | §14 | `3399437067F7B90C0A6B4AED8B76FA3E` |
| `high_pushup_next_step.yaml` | §15 | `73F058E5D6CDC343602018D337587568` |
| `sunrise_vs_rising_three_boundary.yaml` | §16 | `C9F8EF65E8072450293F3F72D12320D6` |
| `top_formation_three_criteria.yaml` | §17 | `77FF4B575AD8B56778449430C25BC47D` |
| `mountain_descent_four_types.yaml` | §19 | `C71C9461F7EDEE5DB8CC0C66D8399F2E` |
| `bottom_break_struggle.yaml` | §22 | `ED82A7EC88ADA783258983AF87116CC7` |
| `pessimistic_stock_structural.yaml` | §27 | `9375FF47DE0C5F2BBF06B74D713EA790` |
| `manipulator_distribution_warning.yaml` | §31 | `AE72522C4C2B878F6E62595496366E10` |
| `leading_env_reverse.yaml` | §35 | `BD6691B48489C339ADE3CA383F814B70` |
| `lack_of_power_distinction.yaml` | §37 | `10A0886DB3EA30F09114543C88450BBF` |
| `new_high_next_day_attack_required.yaml` | §03 | `6EDAE3B7DBB1A4B273C930871361CBCA` |
| `zhongshu_recency_bias.yaml` | §02 | `98207726BFC111243984494E08275765` |

`merged_doji_attack.yaml` 5 處全部加 `article_id: "E9A6F935298C7C5C2E269AA952AA1BB2"`（明日 K 線 §24）。

**Acceptance**：grep 確認所有 playbook + light yaml 內 course_citation 區塊都含 `article_id:` 一行；無 `[TODO_real_id]`；既有 loader test 仍綠。

---

### Task 3.0.2 — 修 W4 / W8

**Files（修現有）**：
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/playbooks/morning_star_island_reversal.yaml`（line 14–16）
  - `"next_day.gap_down": false` → `"next_day.fills_gap": false`
- `/Users/howard/Repository/stock-k-bar/scripts/kline/extras/scenarios/playbooks/bullish_reversal_long_bear.yaml`（line 48, 86）
  - line 86 branch id `B3_hold_stop_loss_watch` → `B4_hold_stop_loss_watch`
  - 同步 line 48 `next_branch_ids` 引用

**Acceptance**：loader 對兩檔仍綠；schema 不再有 branch id 重複。

---

### Task 3.0.3 — STUB-NEED-USER S1–S8 分類

**File（新建）**：`/Users/howard/Repository/stock-k-bar/docs/kline_course/STUB_RESOLUTION_PLAN.md`

分三類：

**(a) 等 user 拍板（必須）**
- **S1**（C07「異常放量」K=2.0/J=1.5 數字）— 課程明示「異常」但無數字，必須 user 給；目前用 proxy。
- **S2**（防守姿態 N/X/Y 數字 — 漲幅、大盤跌幅、防守低點窗口）— `defensive_stance.yaml` 直接受影響。
- **S4**（「創紀錄跌點」歷史範圍：全市場 max / 近 5 年 max）。
- **S5**（B08「空頭已 ≥ 3 個月」精確計算窗口 — 月曆月 / trading days）。
- **S8**（B01/B08 基本面 filter — 漲幅大已脫離基本面 / EPS 與本益比門檻）。

**(b) 課程查證可解（subagent 可做）**
- **S3**（「最大量在漲停板」tick 級判定 + 日 K 退化版接受度）— 查第 20、28 篇原文是否提及退化版接受規則，若無則同 S1 標 STUB 並 fallback。
- **S6**（攻擊意圖區下緣 — 賣壓化解區段起點退化）— 第 23、32 篇原文可能已有「N 日最低 close」說法，需 evidence。
- **S7**（類外側三黑 N 上限 M）— 第 43 篇明示「沒有上限」，所以 M = ∞，直接 deferred；確認後寫入 PATTERN_DEFINITIONS 即可。

**(c) Deferred（不阻擋 Phase 3）**
- 暫保留 proxy + STUB 標記，advisor warn 機制已涵蓋

**Acceptance**：STUB_RESOLUTION_PLAN.md 列三類；課程查證類各跑一次原文 grep 結果記錄；user 拍板類整理成可供 AskUserQuestion 的選項。

---

## Phase 3.A — Simulator 整合（估 1.5 d）

**目標**：跑歷史 advisor 對歷史 bars，量化每個 enabled_branch 的 `matched_after_n_days` 命中率。

### Task 3A.1 — 設計 `simulate_advisor_history()`

**File（新建）**：`/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/simulator.py`

職責：
```python
def simulate_advisor_history(
    bars_df: pd.DataFrame,        # multi-ticker, sorted (ticker, date)
    start_date: str,
    end_date: str,
    playbook_dirs: list[Path] | None = None,
    light_dirs: list[Path] | None = None,
    context_provider: BrokerContextProvider | None = None,  # Task 3B.2
    save_to_db: bool = True,
) -> pd.DataFrame  # one row per (run_id, scenario_idx, branch_id)
```

流程：
1. 對每個 (ticker, trade_date) in [start, end] 跑 `advisor.analyze(...)`
2. 每個 run 寫入 `advisor_history.db`（Phase 1 Task 1.6 已建表）
3. 收集所有 `branches`，留待 Task 3A.2 回填 `matched_after_n_days`

**約束**：禁止把 simulator 與既有 `scripts/kline/exit/simulator.py` 邏輯混在一起 — `exit/simulator.py` 是 entry→exit trade simulator（賺虧計算），advisor simulator 是 branch outcome verifier；兩者目的不同、輸出 schema 不同。**只共用 bars_df loader 與時間順序遍歷邏輯**，不共用 trade DataFrame。

**Tests**：`/Users/howard/Repository/stock-k-bar/tests/kline/scenarios/test_simulator.py`
- T3A.1.1：5 ticker × 20 日 fixture → 跑得通；每個 advisor run 都進 DB
- T3A.1.2：相同輸入跑兩次 → idempotent（不重複塞 DB；用 ticker+date dedupe）
- T3A.1.3：context_provider=None 仍可跑（無 broker 注入）

**Acceptance**：pytest 全綠；單 ticker 252 個交易日跑 < 30 s。

---

### Task 3A.2 — `matched_after_n_days` 回填邏輯

**File（同上）**：`scripts/kline/scenarios/simulator.py`

```python
def backfill_branch_outcomes(
    run_ids: list[int] | None = None,
    bars_df: pd.DataFrame | None = None,
) -> int  # rows updated
```

對每個 branch：
1. 找出 `confirm_at` + `next_day_n` 推出實際確認日 `t + N`
2. 重 evaluate `branch.when` 對 `bars[t+1..t+N]`（vectorize 版 condition.evaluate，Phase 1 Task 1.3 已有）
3. 若有任一 N' ≤ N 命中 → `matched_after_n_days = N'`
4. 若全部不命中 → `matched_after_n_days = -1`（明確「未命中」標記，跟 NULL「未檢驗」區分）
5. 用 `persistence.update_branch_outcome()` 寫回

**約束**：禁止「合理推測」branch 是否命中；只用 vectorize condition evaluate，跟 advisor 當下用的同一個 DSL，避免 leak。

**Tests**：
- T3A.2.1：人工構造 branch `next_day.close > today.high`，後續 bars 第 1 日確實 > → matched_after_n_days = 1
- T3A.2.2：未命中 → -1（不是 None）
- T3A.2.3：兩次 backfill idempotent

**Acceptance**：pytest 全綠；DB lock 不發生（前後 close connection）。

---

### Task 3A.3 — branch 命中率 report

**File（新建）**：`/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/report.py`

職責：
- `branch_hit_rate(start, end) -> pd.DataFrame`（columns: pattern, setup, branch_id, n_fired, n_matched, hit_rate, avg_n_days）
- `playbook_summary(pattern) -> pd.DataFrame`
- CLI：`python -m kline.scenarios.report --start 2024-01-01 --end 2026-05-31 --out reports/advisor_hit_rate.csv`

**約束**：只 report 命中率，**不計算 EV / PnL / 報酬率**（CLAUDE.md + spec §12 + `feedback_backtest_methodology` — 課程要求用實際出場條件，非 N 日報酬）。

**Tests**：`tests/kline/scenarios/test_report.py`
- T3A.3.1：fixture DB → hit_rate 計算正確
- T3A.3.2：CLI 跑出 csv

**Acceptance**：pytest 全綠；report 可手跑出檔。

---

## Phase 3.B — broker_integration 主力大連動（估 1.5 d）

**依據**：`feedback_zhanqian_overrides`、`project_zhuli_hitting_zone_philosophy`、`project_zhuli_course`、`reference_broker_aliases`、`data/zhuli_articles.db`。

**Spec 既定原則**：**broker 訊號只進 `action.notes` 與 `Light`，禁止進 `branch.when`**（保持 K 線課程與主力大課程隔離）。advisor 從 ContextSnapshot 拿值後，notes 自動附加，但 branch 邏輯不參考。

### Task 3B.1 — 從 `zhuli_articles.db` + `docs/主力大課程/` 抽當日訊號

**File（新建）**：`/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/broker_context.py`

職責：
- `ZhuliSignalProvider(db_path, docs_dir)`
  - `get_signals(ticker, trade_date) -> ZhuliSignals` (dataclass)
- `ZhuliSignals` 欄位（spec §4.1 對應）：
  - `broker_tier1_buy: bool`（站前哥/管錢哥/凱基站前主買）
  - `broker_concentration: Literal["high","mid","low","none"]`
  - `teacher_tier: Literal["explicit_pick","mentioned","none"]`（依 `feedback_signal_attribution` 四級分類）
  - `sector_consensus_direction: Literal["long","short","mixed","none"]`
  - `evidence: list[str]`（quote + article_id 來源）

來源優先序：
1. `docs/主力大課程/teacher_picks_2026.json`（既有 — 明示點名）
2. `docs/主力大課程/teacher_current_stance.json`（既有 — 當前態度）
3. `data/zhuli_articles.db`（每日文章 — 主力分點關鍵字 grep）

**約束**：
- DB 操作後立刻 close（`feedback_db_unlock`）
- 找不到訊號 → 回傳全 `none/none/false` ZhuliSignals + evidence=[]，**禁止編造**
- 主力分點命名嚴格用 `reference_broker_aliases`（如「管錢哥」=元大館前；混用為 bug）

**Tests**：`tests/kline/scenarios/test_broker_context.py`
- T3B.1.1：fixture DB → 已知 ticker/date 有正確訊號
- T3B.1.2：找不到 → 全 none
- T3B.1.3：DB 反覆 query 不 lock

**Acceptance**：pytest 全綠；對 2026-05-25 trade_journal 已記錄個股做 spot-check 對應。

---

### Task 3B.2 — `BrokerContextProvider` 介面

**File（同上）**：`scripts/kline/scenarios/broker_context.py`

```python
class BrokerContextProvider(Protocol):
    def get_context_overrides(self, ticker: str, trade_date: str) -> dict: ...

class ZhuliBrokerContextProvider(BrokerContextProvider):
    """Wrap ZhuliSignalProvider to advisor-compatible dict."""
```

回傳 dict 直接餵 `advisor.analyze(..., context_overrides=...)`。

**Acceptance**：Protocol 與既有 advisor signature 相容；mypy 過。

---

### Task 3B.3 — advisor wire context_overrides 自動填

**File（修現有）**：`/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/advisor.py`

修改：
- `analyze()` 新增可選參數 `broker_provider: BrokerContextProvider | None = None`
- 若提供 → 內部 call `provider.get_context_overrides(ticker, today_date)` 並 merge 進 `context_overrides`（user-passed overrides 優先）
- 每個 fired playbook 的 `action.notes` 在 advisor 層補一條 broker 摘要（不改 yaml；以 runtime augmentation 附加）
- 若 `broker_tier1_buy=True` 且既有 K 線 lights 包含 critical/warn（如 `manipulator_distribution_warning`）→ 不抑制 light，但在 advisor.notes 加「broker 反向訊號，注意 override」（依 `feedback_zhanqian_overrides`：站前哥/管錢哥可 override 老師「震盪」警語，但**不 override K 線課程結構訊號**）

**約束**：
- 嚴禁修改 branch.when DSL 白名單去吃 `context.broker_*`（DSL 白名單已有但只供 lights 用 — 確認 audit 範圍）
- 實際上 Phase 1 condition 白名單已加 `context.broker_tier1_buy` 等：審視 audit W 範圍後可能需要把 K 線 branch.when 把這些 fields 鎖掉（只允許 lights 用）。**Task 3B.3 應追加 condition.py 一個 `branch_disallowed_fields` set，把 `context.broker_*` / `context.teacher_*` / `context.sector_*` 從 branch evaluator 排除（lights evaluator 不排除）**

**Tests**：`tests/kline/scenarios/test_advisor_broker.py`
- T3B.3.1：broker_provider 提供 tier1_buy=True → advisor.notes 含 broker 摘要
- T3B.3.2：playbook branch.when 試圖使用 `context.broker_tier1_buy` → loader 拒絕（schema fail loud）
- T3B.3.3：lights trigger_condition 用 `context.broker_tier1_buy` → 正常工作
- T3B.3.4：critical light 與 broker buy 並存 → notes 雙列，無抑制

**Acceptance**：pytest 全綠；現有 24+5 playbooks loader 全綠（無 branch.when 用 broker 欄位）。

---

## Phase 3.C — ch2_warning_integration（估 1 d）

**依據**：`project_ch2_warning_score_system.md`（6 trigger Ch2 多條件 AND；5/19 虛擬時光機對 8064/8027 都亮燈救得了）。

### Task 3C.1 — 6 個 ch2 trigger detect

**File（新建）**：`/Users/howard/Repository/stock-k-bar/scripts/kline/features.py`（加在檔尾）+ `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/ch2_warning.py`

6 triggers（依 memory `project_ch2_warning_score_system.md` 既定，user 已驗證；本 plan 不重新發明）：
1. 連續 3 日紅 K 後第 4 日量縮（課程 §02 中樞 + §11 高檔黑 K 銜接）
2. 創新高隔日上影線 ≥ 實體 2 倍（§10）
3. 跳空向上後當日回補（§13、§34）
4. 高檔吊首 + 隔日無紅 K 表態（§04 吊首 + §03 隔天）
5. 漲停隔日開低跌破前日 close（§12、§20、§28）
6. 季線扣抵高、close 低、隔日無紅 K（§06）

每個 trigger 寫成 features.py 一個欄位（`ch2_trigger_{1..6}: bool`），全部用收盤確認。

**約束**：
- 6 個 trigger 都引用 INVENTORY / 課程篇章 article_id
- 不自創 trigger；只實作 memory 中已列、且能對應到課程條文者
- 若 6 個中有任一找不到課程明示對應 → 標 `[STUB-NEED-USER S9]`、加 docstring warn、不進 score

**Tests**：`tests/kline/scenarios/test_ch2_warning.py`
- T3C.1.1：對 8064 東捷 / 8027 鈦昇 5/19 前後 bars → 至少有 trigger 亮燈（memory 已驗證）
- T3C.1.2：每個 trigger 個別 fixture 驗算

**Acceptance**：pytest 全綠；INVENTORY 引用全部 trace 通過。

---

### Task 3C.2 — score 累積

**File（同上）**：`scripts/kline/scenarios/ch2_warning.py`

```python
def compute_ch2_warning_score(row: pd.Series) -> int  # 0–6
```

純加總（AND-of-OR：每個 trigger 個別計分，最後加總）。

**Tests**：
- T3C.2.1：6 全亮 → score=6
- T3C.2.2：對歷史 8064/8027 至少 score ≥ 4 在 memory 標的日

**Acceptance**：pytest 全綠。

---

### Task 3C.3 — 用 light 機制承載，不寫成 modifier

**決策**：用既有 light 機制（避免改 advisor 架構）。
- 新增 light：`ch2_warning_score_high.yaml`（severity=critical），trigger_condition 用新加白名單 field `context.ch2_warning_score >= 4`
- ContextSnapshot 增 `ch2_warning_score: int`，由 `context.py` 從 features.py 抽
- advisor 注意：若 light fired 且當下有任何 `action.type=entry_signal` branch → 在 advisor.notes 標「ch2_warning_score ≥ 4，建議抑制進場」（**advisor 不主動停掉 branch；只標警示**，由 user 決策）

**約束**：
- 不寫進 spec §12 禁止的 modifier / ML 機制
- score 閾值 4 引用 memory（user 拍板的數字），不是自創；docstring 寫明出處

**File**：
- 新建 `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/lights/ch2_warning_score_high.yaml`
- 修現有 `scripts/kline/scenarios/condition.py` 白名單加 `context.ch2_warning_score`
- 修現有 `scripts/kline/scenarios/context.py` 填 score
- 修現有 `scripts/kline/scenarios/advisor.py` 加 notes augmentation

**Tests**：`tests/kline/scenarios/test_ch2_light.py`
- T3C.3.1：fixture score=5 → ch2_warning_score_high light 觸發
- T3C.3.2：同 fired + entry branch → advisor.notes 含建議抑制字串

**Acceptance**：pytest 全綠。

---

## Phase 3.D — A 類 patterns 實作（估 1 d）

### Task 3D.1 — `patterns/merged_doji.py`（A01）

**File（新建）**：`/Users/howard/Repository/stock-k-bar/scripts/kline/patterns/merged_doji.py`

依 INVENTORY §A01（明日 K 線 §24 / `E9A6F935298C7C5C2E269AA952AA1BB2`）：
- 合併十字線：連續 N 根 (2 ≤ N ≤ 5) 實體極小（`|close − open| / atr_14 < threshold`），合併後 `merged_high = max(highs)`、`merged_low = min(lows)`
- N、threshold 課程未明示精確值 → `[STUB-NEED-USER S10]`；初值用 N∈[2,5]、threshold=0.3，docstring 標 STUB

**File（新建）**：`/Users/howard/Repository/stock-k-bar/tests/kline/patterns/test_merged_doji.py`
- T3D.1.1~3：標準三日合併、五日合併、非合併 fixture

**接 playbook**：`merged_doji_attack.yaml`（Phase 2 已存）`required_context` 標明 `merged_high/merged_low`；advisor 在 patterns/ 跑 detect 後可正確注入 ContextSnapshot.merged_high/low。

**Acceptance**：pytest 全綠；merged_doji_attack.yaml advisor 端從 warn 升級為實際觸發。

---

### Task 3D.2 — `patterns/outside_three_black_like.py`（A02）

**File（新建）**：`/Users/howard/Repository/stock-k-bar/scripts/kline/patterns/outside_three_black_like.py`

依 INVENTORY §A02 + §C01（第 43 篇 / `3995DDF008E3E1B600A9D920E6FFC07C`）：
- 起點：最近一根「創新高紅 K」
- 連續 N 根 (3 ≤ N，**無上限**，依 INVENTORY S7 課程明示)
- 第 N 根 close 跌破起點紅 K 低點

C01 同時要求重命名既有 `outside_three_black.py` detect → `detect_outside_three_black`，新增 `detect_outside_three_black_like`；本 task 一併處理。

**File（修現有）**：`scripts/kline/patterns/outside_three_black.py`（重命名 detect）+ `scripts/kline/patterns/__init__.py`（register 新 detect）

**Tests**：`/Users/howard/Repository/stock-k-bar/tests/kline/patterns/test_outside_three_black_like.py`
- T3D.2.1：N=3 退化測（與原 outside_three_black 結果一致）
- T3D.2.2：N=5、N=9 fixture
- T3D.2.3：未跌破起點低 → 不觸發

**Acceptance**：pytest 全綠；既有 `outside_three_black.yaml` playbook 不破。

---

### Task 3D.3 — 接 baseline playbooks

**File（新建）**：`/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/playbooks/outside_three_black_like.yaml`

依 outside_three_black.yaml 架構複製、改 pattern id、引用 §43 article_id（已在 Task 3.0.1 對照表）。

**Tests**：併入 `tests/kline/scenarios/test_baseline_playbooks.py`

**Acceptance**：advisor 對 N=5 fixture → 觸發新 playbook。

---

## Phase 3.E — C 類其他項補完（估 2 d，含優先順序）

### 分類三層

| Task | 類別 | 估時 | 是否阻擋 advisor |
|---|---|---|---|
| **C02** high_long_black 跳空缺口回補 | exit 補條件 | 0.3 d | 否 |
| **C06** high_hanging_man 投機股 metadata | docstring | 0.1 d | 否 |
| **C08** scoring `attack_continuity.py` | scoring 新增 | 0.5 d | 否 |
| **C09** scoring `pattern_pressure.py` | scoring 新增 | 0.5 d | 否 |
| **C10** ma60_rolloff 明日 K 線表態檢視 | scoring 修 | 0.2 d | 否 |
| **C11** `patterns/zhongshu_pattern.py` 中樞 | pattern 新增 | 0.5 d | 否（但解鎖 zhongshu_recency_bias light 精度）|
| **C12** inner_trapped_to_gap_reversal link | feature 串接 | 0.2 d | 否 |
| **C13** two_crow_gap 大盤 metadata | docstring | 0.1 d | 否 |
| **C14** trailing_stop 微弱多方退化版 | exit 修 | 0.3 d | 否 |

C01/C03/C04/C05/C07 已在 Phase 2 / Phase 3D 處理。

### Tasks

**3E.1 — C08 `scoring/attack_continuity.py`**（新建）
- 依 INVENTORY 規格（第 18、32、40 篇）
- +1 / +1 / +1 / −1 / −1（INVENTORY 已明示）
- 引用 article_id：`8019274F54025F125834940D77F3136B`（§18）、`C4AEB608041A1492DBB4DA00D974E0FC`（§32）、`97FF6136E59005DE4C265B71CF382D88`（§40）
- Tests：`tests/kline/scoring/test_attack_continuity.py`

**3E.2 — C09 `scoring/pattern_pressure.py`**（新建）
- 第 17、29 篇 / `77FF4B575AD8B56778449430C25BC47D`、`330DEA1881DE840124D325701E9CC5E6`
- +1 頸線剛跌破、+1 反彈遇頸線不過、+1 連層套牢（上限 +3）
- 依賴 features.py 既有頸線欄位（C 類其他 task 不阻擋此項）

**3E.3 — C11 `patterns/zhongshu_pattern.py`**（新建）
- 第 02、21、41 篇 / `98207726BFC111243984494E08275765`、`E4E1829D511BB89A02E81552699FC7B1`、`9B869595F18C4330003D8CE4372B4A2D`
- N 區間 3 < N < 60 課程明示
- detect 上升/下降中樞各一函式
- 解鎖 `zhongshu_recency_bias` light 精度（從純哲學提醒升級為條件觸發）

**3E.4 — C02 / C10 / C12 / C14 修現有**（順手修）
- 各自獨立 PR；都跟既有 patterns/exit/scoring 銜接，每個一個 acceptance test

**3E.5 — C06 / C13 docstring metadata**（純文件）
- 不改邏輯，標 metadata + 引用 INVENTORY

**Acceptance**（Phase 3.E 整體）：
- 新建檔案各自 pytest 綠
- 既有 patterns/scoring tests 不破
- INVENTORY §C 全部 14 項標記 `done` 或保留 `[STUB-NEED-USER]`

---

## Critical Files 總清單

### 新建

**Phase 3.0**：
- `/Users/howard/Repository/stock-k-bar/docs/kline_course/STUB_RESOLUTION_PLAN.md`

**Phase 3.A**：
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/simulator.py`
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/report.py`
- `/Users/howard/Repository/stock-k-bar/tests/kline/scenarios/test_simulator.py`
- `/Users/howard/Repository/stock-k-bar/tests/kline/scenarios/test_report.py`

**Phase 3.B**：
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/broker_context.py`
- `/Users/howard/Repository/stock-k-bar/tests/kline/scenarios/test_broker_context.py`
- `/Users/howard/Repository/stock-k-bar/tests/kline/scenarios/test_advisor_broker.py`

**Phase 3.C**：
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/ch2_warning.py`
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/lights/ch2_warning_score_high.yaml`
- `/Users/howard/Repository/stock-k-bar/tests/kline/scenarios/test_ch2_warning.py`
- `/Users/howard/Repository/stock-k-bar/tests/kline/scenarios/test_ch2_light.py`

**Phase 3.D**：
- `/Users/howard/Repository/stock-k-bar/scripts/kline/patterns/merged_doji.py`
- `/Users/howard/Repository/stock-k-bar/scripts/kline/patterns/outside_three_black_like.py`
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scenarios/playbooks/outside_three_black_like.yaml`
- `/Users/howard/Repository/stock-k-bar/tests/kline/patterns/test_merged_doji.py`
- `/Users/howard/Repository/stock-k-bar/tests/kline/patterns/test_outside_three_black_like.py`

**Phase 3.E**：
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scoring/attack_continuity.py`
- `/Users/howard/Repository/stock-k-bar/scripts/kline/scoring/pattern_pressure.py`
- `/Users/howard/Repository/stock-k-bar/scripts/kline/patterns/zhongshu_pattern.py`
- 對應 tests

### 修現有

- `merged_doji_attack.yaml` + 19 個 lights yaml（W1/W7 補 article_id）
- `morning_star_island_reversal.yaml`（W4）
- `bullish_reversal_long_bear.yaml`（W8 branch ID）
- `scripts/kline/scenarios/condition.py`（加 `context.ch2_warning_score` 白名單；加 `branch_disallowed_fields` 對 broker/teacher/sector）
- `scripts/kline/scenarios/context.py`（填 ch2_warning_score）
- `scripts/kline/scenarios/advisor.py`（broker_provider wire；ch2 警示 notes）
- `scripts/kline/features.py`（加 6 個 ch2_trigger 欄位）
- `scripts/kline/patterns/outside_three_black.py` + `patterns/__init__.py`（C01 重命名 detect）
- `scripts/kline/exit/high_long_black.py`（C02）
- `scripts/kline/patterns/high_hanging_man.py`（C06 docstring）
- `scripts/kline/scoring/ma60_rolloff.py`（C10）
- `scripts/kline/patterns/inner_trapped.py` + `gap_reversal.py`（C12 link feature）
- `scripts/kline/patterns/two_crow_gap.py`（C13 docstring）
- `scripts/kline/exit/trailing_stop.py`（C14）

---

## Verification Plan

**Phase 3.0 acceptance**：grep 全部 yaml `article_id:` 至少 50 行；W4/W8 修正後 loader 全綠。

**Phase 3.A acceptance**：
- 跑 `python -m kline.scenarios.simulator --start 2024-01-01 --end 2026-05-31 --tickers 2330,2317,8064,8027`
- 跑 `python -m kline.scenarios.report` 產出 `reports/advisor_hit_rate.csv`
- 對 5 個高曝光 patterns 手 inspect hit_rate；異常（如 100% 或 0%）回頭 debug branch.when

**Phase 3.B acceptance**：
- ZhuliBrokerContextProvider 對 2026-05-25 trade_journal 個股注入 → advisor.notes 與 journal 描述一致
- 嘗試在 playbook branch.when 加 `context.broker_tier1_buy` → loader 拒絕（schema fail loud）

**Phase 3.C acceptance**：
- 對 8064/8027 5/19 前後跑 advisor → `ch2_warning_score_high` light fired
- 對 trade_journal 已記錄 ch2 score 案例對比一致

**Phase 3.D acceptance**：
- merged_doji_attack.yaml advisor 端不再 warn「merged_high/low 缺」
- outside_three_black_like playbook 對 N=5 fixture 觸發

**Phase 3.E acceptance**：
- INVENTORY §C 14 項全標 done 或 STUB
- 既有 patterns/scoring tests 不破

**Code review checklist 補充**（接 Phase 2）：
- [ ] Phase 3.B broker context 不滲透到 branch.when
- [ ] Phase 3.C ch2 警示用 light 機制，不寫成 modifier
- [ ] Phase 3.A simulator 不算 EV/PnL
- [ ] 所有新 patterns / scoring 引用 INVENTORY article_id

---

## Out of Scope（Phase 4+）

- ❌ A 類 / B 類 / C 類「升格」決策（哪些 extras 可搬回 scripts/kline/）
- ❌ Scanner UI 整合 advisor 輸出
- ❌ EV / win-rate 上的策略選擇（CLAUDE.md + spec §12 禁）
- ❌ Position sizing（CLAUDE.md 禁）
- ❌ Real-time advisor service（本地 batch only）
- ❌ 主力大 patterns 獨立 playbook（`project_zhuli_course` 軌道，獨立 plan）
- ❌ 四季投資法整合（`project_four_seasons_course` 軌道）

---

## 工作量總估

| Phase | 內容 | 估計 |
|---|---|---|
| 3.0 | Quick wins（W1/W4/W7/W8 + STUB 分類）| 0.5 d |
| 3.A | Simulator 整合 + report | 1.5 d |
| 3.B | broker_integration | 1.5 d |
| 3.C | ch2_warning_integration | 1.0 d |
| 3.D | A 類 patterns + 接 playbook | 1.0 d |
| 3.E | C 類 14 項補完 | 2.0 d |
| **Total Phase 3** | | **~7.5 d** |

---

## Open Sub-Questions（給 user 拍板，不阻擋 Phase 3 起步）

1. **STUB S1（C07「異常放量」K/J 數字）**：用 K=2.0 / J=1.5 proxy 繼續，還是先暫停 advisor 套用 C07 直到 user 拍板？
2. **STUB S2（防守姿態 N/X/Y）**：是否能先參考 `data/zhuli_articles.db` 老師近期實例反推（如 1605 兩週分析）？或必須 user 親自從課程影片摘錄？
3. **STUB S4（「創紀錄跌點」歷史範圍）**：全市場單日跌停家數 vs 個股單日跌幅，哪個指標優先？課程偏向哪個？
4. **broker_integration 範圍**：Phase 3.B 是否只接 `teacher_picks_2026.json` + `teacher_current_stance.json`（user-curated），暫不解析 zhuli_articles.db 全文（NLP 風險大）？
5. **ch2_warning trigger 數量**：memory 列 6 個 trigger，若課程 grep 只能對應到 4 個明示版（其餘 2 個是 user 推論）→ 是否暫只實作 4 個 + 標 STUB S9？

---

**END OF PLAN**
