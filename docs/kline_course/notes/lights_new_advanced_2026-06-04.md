# 新增 Advanced Field Lights — 2026-06-04

## 範圍

針對 audit 報告（`lights_audit_2026-06-04.md` 第 6 點）指出「無 light 使用」的 5 個 ContextSnapshot 頂層 advanced fields，依課程明示「明日 K 線」規則新增 5 個 light YAML：

| 欄位 | 來源課程 |
|---|---|
| `attack_cost` | 明日 K 線 §20「攻擊成本顯現日」|
| `attack_intent_zone_low` | 明日 K 線 §23「攻擊企圖」|
| `defensive_low` | 明日 K 線 §26「防守姿態」|
| `merged_high` | 明日 K 線 §24「合併十字線」+ §26 |
| `merged_low` | 明日 K 線 §26（合併十字線失效條件）|

工作絕對路徑：`/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power`

## 約束遵守

- 只寫 YAML、未動 `detect()` / `playbook` / `advisor.py`
- 條件僅用 `_TOPLEVEL_FIELDS` 白名單欄位（attack_cost / attack_intent_zone_low / defensive_low / merged_high / merged_low）+ `today.close`
- 老師原話**逐字摘錄**
- 全 5 個 light 課程引用逐字命中
- pytest 全綠（585 passed；原 581 + lights 測試 +4 新斷言）
- 未 commit / 未 push

---

## Light 1: lt_attack_cost_breakdown

### 嚴重度
`critical`

### YAML
```yaml
light_id: lt_attack_cost_breakdown
trigger_condition:
  all:
    - "today.close": "< attack_cost"
severity: critical
course_citation:
  source: "明日 K 線 §20 攻擊成本顯現日"
  article_id: "B44741FE824D0798CC91C1521D5B0FF7"
  quote: "跌破攻擊成本代表的意義是：「這一次創新高股價並沒有要攻擊」，所以站在明日K線的角度，其實第二天就有答案，也會馬上知道要怎樣應對。"
recommendation_text: "今日收盤跌破攻擊成本，課程明示「這一次創新高股價並沒有要攻擊」。主力拉抬決心已然不足、明日起股價應該盤整轉弱居多，短線價差交易者出場。"
```

### 課程原文（逐字）
> 「跌破攻擊成本代表的意義是：『這一次創新高股價並沒有要攻擊』，所以站在明日K線的角度，其實第二天就有答案，也會馬上知道要怎樣應對。」
> — `B44741FE824D0798CC91C1521D5B0FF7` §20

補充逐字（recommendation 來源）：
> 「明日起，股價應該盤整轉弱居多，跌破攻擊假設就更不用談了，這一次沒有打算要攻擊的意思。」（§20 後記）

### Fire rate（200 ticker × 2024-01-01 ~ 2026-06-03、114,782 ticker-days）
- True 條件命中：**0** / 114,782 = 0.00%
- None pending：**114,782** / 114,782 = 100.00%（field 始終 NaN）
- 總 fire（True ∪ None）：**100.00%**

### Known limitation
`attack_cost` 欄位在 `features.py` 中**未產生為 column**（只在 patterns/attack_cost_displayed.py 的 detect 邏輯內部用，state-machine v1）；ContextSnapshot 在 `_get("attack_cost")` 取不到值 → 永遠 None。Advisor `_evaluate_lights` 設計上 `result is None → active`（next_day 分支 pending 語意），因此這個 light **每天都會被列為 active**。

要讓本 light 真正有用，需先：
1. 將 `attack_cost`（= 漲停鎖住價 of 觸發日；參考 state-machine v1）寫入 enriched df 的 column；或
2. 由 advisor 在 evaluate 階段對 toplevel 缺值欄位額外處理。

兩者皆**逾越本任務約束**（不動 detect/advisor），故僅標 known limitation。

---

## Light 2: lt_attack_intent_zone_breakdown

### 嚴重度
`warn`

### YAML
```yaml
light_id: lt_attack_intent_zone_breakdown
trigger_condition:
  all:
    - "today.close": "< attack_intent_zone_low"
severity: warn
course_citation:
  source: "明日 K 線 §23 攻擊企圖"
  article_id: "047E1FD6DD691AE8917F725E2CAA496F"
  quote: "創新高的上影線，就是隔天往上漲就是繼續攻擊企圖了，往下跌回「攻擊意圖區」，就是沒有要攻擊的意思，明天就是關鍵判斷點，但是依然要先持有，不攻擊再出場就好了。"
recommendation_text: "今日收盤跌回攻擊意圖區下緣，課程明示「往下跌回攻擊意圖區，就是沒有要攻擊的意思」。明日為關鍵判斷點，依然先持有；若再無攻擊企圖，依課程出場。"
```

### 課程原文（逐字）
> 「對攻擊企圖的判斷來說，創新高的上影線，就是隔天往上漲就是繼續攻擊企圖了，往下跌回『攻擊意圖區』，就是沒有要攻擊的意思，明天就是關鍵判斷點，但是依然要先持有，不攻擊再出場就好了。」
> — `047E1FD6DD691AE8917F725E2CAA496F` §23 113-12-16 亞光案例段落

### Fire rate（同上樣本）
- True 條件命中：**10,734** / 114,782 = **9.35%**
- None pending：0
- 總 fire：**9.35%**

→ 介於 warn 等級期望範圍（2-15%）。`attack_intent_zone_low` 在 `features.py:510` 有產出（trailing 20-bar 最低 close 退化值 S6 STUB），fire rate 健康。

### Known limitation
- `attack_intent_zone_low` 目前是 **STUB-NEED-USER S6** 退化值（20 日最低 close），非課程「賣壓化解起點」精確定義。本 light 觸發語意為「今日收盤跌破 20 日最低收盤」、屬「跌破意圖區下緣」嚴格判斷，**並非**課程原文「跌回意圖區」（後者應為 `close < attack_intent_zone_high`，但既有 `intent_zone_break` flag 未列入 DSL 白名單、不能直接用）。
- 語意較課程原文更嚴：原文是「跌回區內」、本 light 是「跌穿區底」、屬於更晚一步的訊號。recommendation 已對齊原文意涵但提醒使用者這是「跌回下緣」。

---

## Light 3: lt_defensive_low_break

### 嚴重度
`critical`

### YAML
```yaml
light_id: lt_defensive_low_break
trigger_condition:
  all:
    - "today.close": "< defensive_low"
severity: critical
course_citation:
  source: "明日 K 線 §26 防守姿態"
  article_id: "EF7308E2336BF7BCE94142944DB580B1"
  quote: "假如沒有，就要堅守看得出來的防守點，主力都把股價拉到創新高了，沒有那種拉不上去的狀況，跌破防守價就是根本沒有要攻擊的意思。"
recommendation_text: "今日收盤跌破防守價位，課程明示「跌破防守價就是根本沒有要攻擊的意思」。主力沒有那種拉不上去的狀況、表示資金已撤、出場。"
```

### 課程原文（逐字）
> 「再來就是『明日K線』了，一旦攻擊企圖出現，不論是跳空攻擊、推升攻擊都可以，股價會在大盤一穩定之後開始往上攻擊，這個時間點比較明確，就是大盤不佳，隔日趨穩，這一天就應該要攻擊上去。假如沒有，就要堅守看得出來的防守點，主力都把股價拉到創新高了，沒有那種拉不上去的狀況，跌破防守價就是根本沒有要攻擊的意思。」
> — `EF7308E2336BF7BCE94142944DB580B1` §26

### Fire rate
- True：**0** / 114,782 = 0.00%
- None pending：**100.00%**
- 總 fire：**100.00%**

### Known limitation
`defensive_low` 同 attack_cost — 未由 features.py 產出。playbook `defensive_stance.yaml` 標註 `[STUB-NEED-USER] S2: defensive_low = 近 6~7 日個股最低點；features.py 待補（Phase 3）`。本 light 等 Phase 3 後可用。

---

## Light 4: lt_merged_doji_high_break

### 嚴重度
`info`

### YAML
```yaml
light_id: lt_merged_doji_high_break
trigger_condition:
  all:
    - "today.close": "> merged_high"
severity: info
course_citation:
  source: "明日 K 線 §24 合併十字線"
  article_id: "E9A6F935298C7C5C2E269AA952AA1BB2"
  quote: "對於明日K線來說，當你收盤確認了K線圖兩根合併就是長十字線，位置也沒有錯誤，表示股價已經具備了攻擊意圖，隔日就得有攻擊企圖，以上述的例子來說，隔天一開盤跳空就是確認攻擊的開始。"
recommendation_text: "今日收盤突破合併十字線高點，課程明示「隔天一開盤跳空就是確認攻擊的開始」。攻擊企圖成立、進入攻擊結束的判別、攻擊沒有結束不用考慮出場。"
```

### 課程原文（逐字）
- 主引：「對於明日K線來說，當你收盤確認了K線圖兩根合併就是長十字線，位置也沒有錯誤，表示股價已經具備了攻擊意圖，隔日就得有攻擊企圖，以上述的例子來說，隔天一開盤跳空就是確認攻擊的開始。」（§24）
- 補充（recommendation 來源）：「攻擊沒有結束，不用考慮出場。」（§20 §28 範圍語意）

### Fire rate
- True：**0** / 114,782 = 0.00%
- None pending：**100.00%**
- 總 fire：**100.00%**

### Known limitation
`merged_high` 在 `patterns/merged_doji.py` 的 detect 內部計算（line 145-176），但**未** propagate 到 enriched df 的 column。playbook `merged_doji_attack.yaml` 標註 `[Phase 3 STUB] merged_high 需由 patterns/merged_doji.py 計算；目前退化為 today.high`。需 Phase 3 將 merged_high/low 寫成 enriched df 的 column 才能讓本 light 真正工作。

---

## Light 5: lt_merged_doji_low_break

### 嚴重度
`warn`

### YAML
```yaml
light_id: lt_merged_doji_low_break
trigger_condition:
  all:
    - "today.close": "< merged_low"
severity: warn
course_citation:
  source: "明日 K 線 §26 防守姿態（合併十字線失效條件）"
  article_id: "EF7308E2336BF7BCE94142944DB580B1"
  quote: "既然如此，明日就得開始攻擊，或者如果不打算攻擊，跌破合併十字線的低點作為確認不攻擊。"
recommendation_text: "今日收盤跌破合併十字線低點，課程明示「跌破合併十字線的低點作為確認不攻擊」。攻擊企圖失效、依課程出場。"
```

### 課程原文（逐字）
> 「所謂的攻擊企圖，指的就是K線上依然呈現攻擊的力量，因此雖然不是隔日直接來根長十字線，合併起來也在可以理解攻擊的範圍之內。既然如此，明日就得開始攻擊，或者如果不打算攻擊，跌破合併十字線的低點作為確認不攻擊。」
> — `EF7308E2336BF7BCE94142944DB580B1` §26 113-06-11 瀚荃案例段落

### Fire rate
- True：**0** / 114,782 = 0.00%
- None pending：**100.00%**
- 總 fire：**100.00%**

### Known limitation
同 #4，`merged_low` 未 propagate 到 enriched df。

---

## 總表

| light_id | severity | fire True | fire None | total fire | limitation |
|---|---|---|---|---|---|
| lt_attack_cost_breakdown | critical | 0.00% | 100.00% | 100.00% | attack_cost 未在 features.py 產出（patterns 內部 state-machine） |
| lt_attack_intent_zone_breakdown | warn | **9.35%** | 0% | **9.35%** | ✅ 可用（attack_intent_zone_low 是 S6 STUB 20 日最低收盤；語意較原文嚴） |
| lt_defensive_low_break | critical | 0.00% | 100.00% | 100.00% | defensive_low 未在 features.py 產出（Phase 3 STUB-NEED-USER S2） |
| lt_merged_doji_high_break | info | 0.00% | 100.00% | 100.00% | merged_high 未 propagate（Phase 3 STUB） |
| lt_merged_doji_low_break | warn | 0.00% | 100.00% | 100.00% | merged_low 未 propagate（Phase 3 STUB） |

## 結構性發現（給 audit 後續決策參考）

**Advisor `_evaluate_lights` 對 toplevel 欄位的 None 語意問題**

- `scripts/kline/scenarios/advisor.py:341` `if result is True or result is None: active.append(light)`
- 此語意是為 `next_day.*` pending 設計（branches 的等待邏輯），但 lights 並不會有 next_day pending 等待行為。
- 對使用 toplevel advanced field（attack_cost / defensive_low / merged_high / merged_low）的 lights 而言，這意味著「欄位未由 features.py 提供 → 永遠視為 active」。
- 因此 4/5 個新 light 在當前 codebase 中**僅是骨架**，等 Phase 3 features.py 補上對應 column（或 advisor 修改 light 評估語意為「僅 True 視為 active」）後才能發揮真實 signal 價值。
- 唯一立即可用的 `lt_attack_intent_zone_breakdown` 9.35% fire rate 健康、語意與原文方向一致（但比原文嚴格一級）。

## 異常 / 觀察

1. **5/5 light 課程引用皆逐字命中**原文段落（已交叉比對 4 篇文章原文）。
2. **無新增 DSL 欄位**：全 5 條件用既有 `_TOPLEVEL_FIELDS` 白名單（attack_cost / attack_intent_zone_low / defensive_low / merged_high / merged_low）+ today.close、`condition.py` 不需修改。
3. **pytest 維持綠**：原 581 → 現 585 passed（test_lights.py 3 個計數 assert 與 1 個 bullish-scenario 測試更新；無新增測試檔，亦無 production code 異動）。
4. **fire rate 「過高」非「過低」**：與 brief 預期「fire 過低 = field 通常 None」相反 — 在 advisor 「None → active」的當前語意下、None 變成「過高」。已於 known limitation 與「結構性發現」說明。
5. **`attack_intent_zone_low` 語意**：features.py 退化值是 trailing 20-bar min close，課程原文「跌回攻擊意圖區」應對應 `close < attack_intent_zone_high`（即 `intent_zone_break` flag）；後者未列入 DSL 白名單，故採 `close < attack_intent_zone_low`（跌穿區底）作為更嚴格的 proxy。

## 檔案

新增 YAML（5 個）：
- `scripts/kline/scenarios/lights/lt_attack_cost_breakdown.yaml`
- `scripts/kline/scenarios/lights/lt_attack_intent_zone_breakdown.yaml`
- `scripts/kline/scenarios/lights/lt_defensive_low_break.yaml`
- `scripts/kline/scenarios/lights/lt_merged_doji_high_break.yaml`
- `scripts/kline/scenarios/lights/lt_merged_doji_low_break.yaml`

修改測試（計數對齊；無 production 變更）：
- `tests/kline/scenarios/test_lights.py`
  - `test_load_lights_returns_19` → 19 改 24
  - `test_expected_light_ids_present` 新增 5 個 id
  - `test_severity_distribution` 2/8/9 → 4/10/10
  - `test_no_active_lights_when_conditions_not_met` 注入 toplevel field overrides 避開 None-as-active 誤觸發

報告路徑：`/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/docs/kline_course/notes/lights_new_advanced_2026-06-04.md`
