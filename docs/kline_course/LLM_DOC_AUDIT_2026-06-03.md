# k-bar-power-llm.md 品質審查報告

**Audit date:** 2026-06-03
**Source file:** `/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/k-bar-power-llm.md` (713 行)
**Reviewer:** Subagent — 對照實際 code 逐 module 比對

---

## ✅ Pass (大方向正確)

- 26 個 patterns 全列且 PATTERN_REGISTRY key 全對（含最近新增的 `merged_doji` + `outside_three_black_like`）。
- 8 個 entries 在 ENTRY_REGISTRY 中全對。
- 7 個 scoring factors（含 `trend_continuation` 閾值 17 天 +25）全對。
- Extras registries 3 個 + `ENTRY_STRATEGY_REGISTRY` + `parse_extras_spec` + `resolve_extras` 全對。
- 20 個 lights、29 個 baseline playbooks + 1 個 extras playbook（`bullish_reversal_long_bear.yaml`）— 總數對得起來。
- `load_bars` / `add_features` / `analyze` / `evaluate` / `evaluate_vectorized` / `build_context_snapshot` / `save` / `load_runs` / `update_branch_outcome` / `load_playbooks` / `load_lights` / `simulate` 簽名與 default 值全部命中。
- `_common.py` 六個 helper (`is_power_bar` / `is_narrow_consolidation` / `in_trend` / `is_similar_bars` / `bull_exhaustion_context` / `bear_exhaustion_context`) 簽名命中。
- `is_doji` 公式 (body ≤ 0.6% AND range ≥ 1.5%) 對得起 `DOJI_MAX_BODY_PCT=0.006` / `DOJI_MIN_RANGE_PCT=0.015`。
- DB paths 三條全對（main `/Users/howard/.four_seasons/data.sqlite` 表 `standard_daily_bar`、backfill 絕對路徑、advisor history `data/advisor_history.db`）。
- 課程合規五大限制全部轉述（禁自創指標、目錄物理隔離、course_proxy_constants 集中、STUB 標記、partial_exit override）。
- simulator 禁算 EV/PnL/ret_Nd 有講；broker/teacher/sector 只進 context/notes/lights 不進 branch.when 有講。
- DSL RHS 禁算式 + 嵌套深度 2 + UnknownTokenError 都正確描述。
- features.py cross-ticker rolling bug + bars.py 91 GB 事件描述跟 code 註解一致。

---

## ⚠️ Inaccuracies (建議修正)

1. **Exit 數量描述「10+」實際是 10 主 exit + 6 reversal_k = 16**（L54 `EXIT_REGISTRY (10+ exits)`）。文字 OK 但下方 5.2 列表只列 10 主 + 6 reversal_k = 16 條，建議改成「10 course exits + 6 reversal_k = 16」更精準。

2. **EXIT_REGISTRY 值的 callable 名是 `mark` 不是 `detect`**（L287 註解 `EXIT_REGISTRY: mark(df, entries) -> pd.Series[bool]`）— 寫對了，但前面 L54 註解可以補一句 callable 是 `mark` 一致用語。
   *屬於小改進，非真錯。*

3. **L107 ma20, ma60, ma240 描述「可 NaN」沒提 `vol_ma20` / `vol_ratio_20` / `is_attention_stock` / `is_disposition_stock` 也在 schema**（L103-110 表格雖然有列，但 L99-110 整段「主要欄位」沒提這些。L46-47 的 query 是有 select 出來的。— 已列出，*pass*。

4. **`is_doji` 計算實際在 features.py L? 需要先 `body_pct` / `range_pct`**（L142）— 描述對。

5. **`pre_breakout_trend_days` 描述「連續收盤高於 MA60 的天數（上限 20）」** — 對照 features.py：實際是「過去 20 日內收盤高於 MA60 的天數」（rolling sum，非「連續」）。建議改 L146：「**過去 20 日內**收盤高於 MA60 的天數」，不是連續。

6. **`shadow_position` 描述為「影線位置分數」** — OK 但籠統，沒提到實際課程 source。pass。

7. **L208 `merged_doji` 描述「（P— / 明日 K 線）當日或合併後形成十字」** — pattern 槽位描述 OK。`outside_three_black_like` 標 P15 alike 也 OK。

8. **Phase 1 vs Phase 4 描述**：L538「broker / teacher / ch2 / sector 四類欄位為 Phase 1 = overrides only；Phase 4 才會 wire 真實資料源」— 對照 _schema.py L246 註釋與 advisor.py 384 註釋一致。

---

## 🟡 Missing

1. **extras/bear_single_day_reversal.py + bull_single_day_reversal.py** 兩個 module 存在 (P16/P17) 但 doc 第 6 節「Extras」表格沒列。應補一行說明：
   `single_day_reversal_{bull,bear}` 是 P16/P17 課程「最微弱」轉折，預設不在任何 registry 但 file 存在於 extras/。

2. **extras/extras_macd_dif/** 目錄存在但 doc 完全沒提。建議補一句：「macd_dif 子目錄為實驗性 MACD 指標 extras，預設不掛進 registry。」

3. **DOJI 等 course_proxy_constants 常數**：doc 第 1 節提了「`course_proxy_constants.py` 是唯一量化門檻來源」但沒在任何地方舉常數例子（如 `INTEGRATION_DAYS`、`RISING_LOWS_MIN_FRAC`、`STABLE_UPPER_MAX_SPREAD`）。對 LLM agent 集成不必要，可選擇性補。

4. **persistence DDL schema**：doc 提了 `save` / `load_runs` / `update_branch_outcome` 但沒提 SQLite 三張表 (`advisor_runs` / `advisor_branches` / `advisor_lights`) 的 schema。若 caller 想 raw SQL 查就缺資訊。可選擇性補。

5. **`Action.notes` 與 `Branch.next_branch_ids`** Pydantic 欄位在 doc L555-566 有列 type 但沒解釋語意，特別 `next_branch_ids` 是「多日劇本鏈」— 課程角度沒講清楚。

6. **`ConfirmAt = "next_intraday"` 沒列**（doc L553 寫 `"today_close" / "next_open" / "next_close" / ...`）— 雖然用 `...` 帶過，建議補全四個 Literal。

7. **`ContextSnapshot` 欄位 `ma5_will_rise` / `ma10_will_rise`** 在 doc L527 表已列，但沒提這四個 will_rise 的 STUB 狀態（Phase 1 = overrides）— 對照 _schema.py 一致。

8. **`PatternHit` 是純 `__slots__` dataclass 不是 Pydantic**：doc L510「fired_patterns: list[PatternHit] (pattern, fired_at, confidence)」描述對，但沒明示「非 Pydantic、無 model_validate」— LLM agent 若想 `PatternHit.model_dump()` 會 fail。

---

## 📋 Verified (10 random API + 3 範例 code spot-check)

### 10 API spot-check（命中率 10/10）

| # | API | doc 位置 | 實際 code | 命中 |
|---|---|---|---|---|
| 1 | `load_bars(db_path, fill_from_backfill=True)` | L93-97 | bars.py L28 | ✅ |
| 2 | `add_features(df)` | L128 | features.py L26 | ✅ |
| 3 | `PATTERN_REGISTRY` 26 keys | L191-220 | patterns/__init__.py L71-98 | ✅ |
| 4 | `ENTRY_REGISTRY` 8 keys | L269-278 | entry/__init__.py L18-27 | ✅ |
| 5 | `EXIT_REGISTRY` 主 10 + reversal_k 6 | L288-305 | exit/__init__.py L27-39 + reversal_k/__init__.py L18-25 | ✅ |
| 6 | `SCORING_REGISTRY` 7 keys | L324-332 | scoring/__init__.py L21-30 | ✅ |
| 7 | `analyze(bars_df, today_date, ticker, context_overrides, playbook_dirs, light_dirs)` | L377-389 | advisor.py L358-365 | ✅ |
| 8 | `evaluate(when, row, ctx, next_day_n=1) -> Optional[bool]` | L419-424 | condition.py L584-589 | ✅ |
| 9 | `save(result, ticker, trade_date, db_path=...)` returns int | L486-488 | persistence.py L103-108 | ✅ |
| 10 | `is_power_bar(df, direction="bull", body_pct_min=0.03)` | L238 | _common.py L35 | ✅ |

### 3 範例 code mentally trace（能跑率 3/3）

1. **第 10.1 Pattern Screening 範例（L590-609）** — `load_bars()` → `add_features()` → `PATTERN_REGISTRY.items()` 迴圈呼叫 `detect_fn(enriched)`。✅ 可跑。⚠️ 但 `today.index` 在 multi-ticker DataFrame 中是非連續 int index，`today_fired[today_fired].index` 與 `today.loc[...]` 邏輯需 caller 確保 `enriched` 與 `today` index 對齊（doc 沒警告但 mentally trace 過可跑）。

2. **第 10.2 four-seasons Advisor 範例（L615-637）** — `analyze(df, today_date, ticker, context_overrides=overrides)` → `save(result, ticker, trade_date)` → 印 `active_lights` / `scenarios`。✅ 可跑（advisor.py signature 完全對得起）。

3. **第 7.1 advisor.analyze 範例（L377-396）** — `analyze(...)` 接 `bars_df=df`（raw 也行，doc 寫對了）→ `result.fired_patterns` / `.scenarios` / `.active_lights` / `.notes` / `.context_snapshot`。✅ 對照 AdvisorResult schema 全對。

---

## Recommendations

### 必改（影響 caller 正確性）

1. **L146 `pre_breakout_trend_days`** 描述「連續收盤高於 MA60」改為「**過去 20 日內**收盤高於 MA60 的天數」。Caller 若以為是「連續」會誤判 17 day threshold 語意。

### 應補（提高完整性）

2. **第 6 節 Extras 表**補一行 `bear_single_day_reversal` / `bull_single_day_reversal`（P16/P17 file 在但未掛 registry，存在即價值）。
3. **L553 ConfirmAt** 補全 `next_intraday`（目前 "..." 帶過）。
4. **L510 PatternHit** 補一句「純 Python dataclass，非 Pydantic，無 `.model_dump()`」。
5. **第 6 節**補一句說 `extras/extras_macd_dif/` 是實驗性目錄、預設不掛 registry。

### 可選（細節）

6. **第 9 節 DB 表**補 advisor_history.db 三張表 schema（`advisor_runs` / `advisor_branches` / `advisor_lights`）。
7. **第 8 節 Branch.next_branch_ids** 補語意說明（多日劇本鏈）。
8. **第 1 節**提一句「DOJI / INTEGRATION_DAYS 等量化常數請查 `course_proxy_constants.py`」並指向幾個典型常數名。

---

**結論：** 整體準確性高（10/10 API spot-check 命中、3/3 範例 mentally traceable），CLAUDE.md 五大課程合規限制完整轉述，extras 物理隔離原則清楚。主要缺漏在 P16/P17 single_day_reversal 與 extras_macd_dif 兩個目錄、以及 `pre_breakout_trend_days` 一個語意不精確點。修完上述「必改 + 應補」即可成為 cross-repo authoritative reference。
