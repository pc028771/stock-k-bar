# Lights 全面 Audit 報告 — 2026-06-04

## 審查範圍

`scripts/kline/scenarios/lights/` 下 19 個 YAML（純讀檔審查、不改任何檔案）。

對照：
- `scripts/kline/scenarios/condition.py` 欄位白名單（line 46–97）
- `scripts/kline/features.py` 實際產出欄位
- `docs/kline_course/mingri_kline/` 47 篇原文

## 重要前置發現（影響先前判斷）

**`prev_high_60` ≠ typo。** `features.py:42-45` 已明確 alias：

```
df["prior_high_60"] = ...
df["prev_high_60"] = df["prior_high_60"]    # DSL alias
```

且 `condition.py:62` 將 `prev_high_60` 列入 `_TOPLEVEL_FIELDS` 白名單。

→ 任務 brief 中「`prev_high_60` 欄位不存在」的前提需重新驗證；目前 codebase 顯示欄位存在。
→ 若 v2 fire rate 已重測（new_high 4.4%、pressure_meeting 3.4%、pressure_layer 90.9% 待重測），代表 alias 修補已生效。

`pressure_layer_no_support` 目前 YAML 條件 = `today.at_pressure_retest: true`，不再依賴「不破前低 = 有支撐」自創條件。bug 已修正、待 fire rate 重測（預期 ~38%）。

---

## 逐 light 審查

### 1. bottom_break_struggle (warn, fire 未列)

- 條件：`today.close < prior_low_60 AND today.close > prev.close`
- 課程 §22「破底股糾結」：跌破 60 日低點後反彈為套牢賣壓
- 欄位：`prior_low_60` ✅ 存在
- 評斷：✅ **OK** — 條件對應「破底後小紅 K」吻合原文「破底反彈非翻多」
- 備註：條件略寬（任何破底 + 紅 K 都觸發），但屬 warn 合理

### 2. gap_down_falling_three (warn, 18.3%)

- 條件：`today.open < prev.close AND today.close < prev.close`
- 課程 §14：「先有向下跳空，整理 2-3 天，再一根黑 K」
- 評斷：⚠️ **需修正**
  - 條件只抓「跳空 + 收黑」單日，**沒抓中繼整理 2-3 天 + 再黑 K** 的完整序列
  - 原文：「下降三法的文字定義：先有下跌黑K，然後整理兩到三天，再往下出現一根黑K」
  - 目前條件等同「向下跳空黑 K」訊號、不是「下降三法」
- 建議：改名為 `gap_down_warning` 或加 lookback 抓中繼結構

### 3. high_black_k_warning (warn, 2.5%)

- 條件：`today.close < today.open AND today.high >= prev_high_60`
- 課程 §11：高檔長黑 / 包覆 / 實質賣壓
- 評斷：⚠️ **需修正**
  - 課程明示「**高檔長黑**」、「**包覆**」、「**上下震幅超過 10%**」
  - 目前條件只有「黑 K + 觸 60 日高」、沒有「長黑 / 包覆」幅度判斷
  - 過嚴（2.5%）合理、但**性質可能錯誤**：只抓「高位黑 K」≠ 課程教的「高檔長黑」
- 建議：加 body size 或 prev.body 包覆條件

### 4. high_pushup_next_step (info, 4.3%)

- 條件：`today.close >= prev_high_60 AND today.close > prev.close`
- 課程 §15：「高檔推升 = 連續數日股價暫時沒持續大幅拉抬、沒回檔、低點有些許推高」
- 評斷：❌ **違背課程**
  - 條件抓「突破前高 + 紅 K」= 一般攻擊突破，**不是**高檔推升
  - 課程定義是「短期內股價看似橫向、連續 K 線低點有些許推高」=「整理 + 緩推」
  - light 觸發後的 recommendation 寫的是「攻擊延續 vs 跌破」雙劇本、跟「高檔推升下一步」原文吻合的是「跌破推升結構」這一面
- 建議：改抓「N 日 close 窄幅 + 低點墊高」+「今日跌破推升結構」

### 5. just_high_upper_shadow (info, 4.1%)

- 條件：`today.high >= prev_high_60 AND today.close < today.high AND today.close > prev.close`
- 課程 §10：剛創新高 + 上影線 → **「通常還是會越過」**
- 評斷：⚠️ **recommendation 偏離**
  - 條件吻合「剛創新高上影線」
  - 但 recommendation 寫「明日需觀察攻擊企圖，否則遇壓」傾向警示
  - **課程結論其實是「上影線高點通常會越過」（多方傾向）**
  - severity=info 合理、但 recommendation 語氣應調整為「通常會越過、設停損即可」

### 6. lack_of_power_distinction (info, 42.5%)

- 條件：`today.close > prev.close AND today.close < prev_high_60 AND context.ma5_will_rise == false`
- 課程 §37：「賣壓中空結束 vs 缺乏攻擊企圖」
- 評斷：⚠️ **過寬 + 性質偏差**
  - fire 42.5%（每 2.4 天一次）= 設計失誤等級
  - 原文「缺乏攻擊企圖」指「跌破推升 + 越過攻擊意圖區又黑 K 跌回」
  - 目前條件只是「小紅 + MA5 不升」→ 太籠統、任何弱勢盤整都觸發
- 建議：須加「曾觸前高 + 跌回」或「跌破推升」結構

### 7. limit_up_next_day_stats (info, 6.1%)

- 條件：`today.close >= prev.close AND today.high >= prev_high_60`
- 課程 §12：漲停板隔日機率、強勢 vs 弱勢對比
- 評斷：⚠️ **欄位偏離**
  - 條件「close ≥ prev.close + 觸前高」**不是漲停**、是「平盤以上 + 觸前高」
  - 課程明示「漲停板的當日」、「股價回到第一根創新高漲停板之下」
  - 沒有用 limit_up flag、無法抓真正漲停
- 建議：加「today.close / prev.close ≥ 1.099」或新增 limit_up bool feature

### 8. lowprice_first_pull_exit (warn, 44.7%)

- 條件：`today.close < prev.close AND today.close < prev_high_60 AND today.close > prior_low_60`
- 課程 §09：「第一次的拉抬結束就離場」、「低價股」
- 評斷：❌ **違背課程 + 過寬**
  - 條件完全沒判斷「低價股」（價格 < N）
  - 條件等同「中樞下跌」、所有區間黑 K 都觸發
  - 44.7% fire rate 顯示完全沒有篩出低價股
  - 課程明示「**低價股**」是前提
- 建議：加 `today.close < LOW_PRICE_THRESHOLD`（e.g. < 30）+ 「曾出現拉抬」前提

### 9. manipulator_distribution_warning (critical, 42.5%)

- 條件：`today.close < prev_high_60 AND today.close < prev.close AND today.close < today.open`
- 課程 §31：「主力出貨 = 拉高出貨謬論、主力出順變一座山、出不順變箱型」
- 評斷：❌ **過寬 + critical 等級失當**
  - 條件「跌破前高 + 黑 K 下跌」→ 任何高檔黑 K 都觸發
  - critical severity + 42.5% fire = 每 2.4 天「critical 出貨警示」、實質失去警示意義
  - 課程主旨在於「箱型區間」識別、非單日黑 K
- 建議：(a) 降為 warn，或 (b) 加箱型整理 N 日 + 高檔黑 K 序列條件

### 10. mountain_descent_four_types (warn, 47.7%)

- 條件：`today.close < prev_high_60 AND today.close < prev.close AND context.ma20_will_rise == false`
- 課程 §19「下山」：四類股票會變一座山（題材無未來 / 一次性利多 / 再次突破熱度股 / 利用環境話題）
- 評斷：⚠️ **條件無法辨識「四類」+ 過寬**
  - 四類分類屬於**敘事性質**、K 線難以辨識（除非加 fundamental flag）
  - 47.7% fire = 任何高檔回檔 + MA20 走平都觸發
  - light 本質可保留為「下山風險訊號」、但 recommendation 不該說「需確認屬於四類」（無法從 K 線判斷）
- 建議：rec 改為「下山風險 → 結合基本面 / 題材熱度評估」、並加「曾出現攻擊」前提

### 11. new_high_next_day_attack_required (info, 4.4%)

- 條件：`today.high >= prev_high_60 AND today.close >= prev_high_60`
- 課程 §03：「創新高隔天必看跳空攻擊或推升攻擊」
- 評斷：✅ **OK**
  - 條件吻合「創新高第一天」
  - 4.4% fire 合理（創新高本身偏稀有事件）
  - rec 文字「明日必須出現攻擊企圖」忠於原文

### 12. pessimistic_stock_structural (warn, 2.7%)

- 條件：`today.close < prior_low_60 AND context.ma20_will_rise == false`
- 課程 §27：明日不樂觀的個股 K 線
- 評斷：⚠️ **citation quote 不存在原文**
  - YAML quote：「結構性弱勢：跌破 60 日低點且均線走弱，不樂觀的個股特徵」
  - 原文中沒找到此字串、屬解讀性 paraphrase
  - 原文 §27 主要談「絕對、優先、盡快避開」的個股特質、未具體列「跌破 60 低 + MA20 走弱」
  - 條件本身（破底 + MA20 不升）邏輯合理、但 quote 應改為原文逐字
- 建議：quote 改為「明日股價不樂觀的企業，是絕對、優先、盡快怎樣都要避開的投資」

### 13. pressure_layer_no_support (warn, 90.9% 待重測)

- 條件：`today.at_pressure_retest: true`
- 課程 §08：「K 線上只有壓力沒有支撐」、套牢 / 波動 / 獲利了結三類
- 欄位 `at_pressure_retest`：features.py:625 確實產生（close 接近 prev_high_60 但未突破）
- 評斷：✅ **OK（先前 bug 已修）**
  - 原條件曾用「不破前低 = 有支撐」自創支撐 → 違背課程、已被改掉
  - 目前單一條件吻合「回測壓力區未突破」
  - 90.9% fire 是舊版數據、需重跑驗證
- 備註：rec 引用「K 線上只有壓力沒有支撐」逐字命中原文 ✅

### 14. pressure_meeting_unresolved (warn, 3.4%)

- 條件：`today.close < prev_high_60 AND today.high >= prev_high_60`
- 課程 §04：「遇壓沒化解就是多一層套牢」
- 評斷：✅ **OK**
  - 條件吻合「盤中觸前高、收盤未突破 = 遇壓未化解」
  - quote「遇壓沒化解就是多一層套牢」在 INVENTORY.md 列入（解讀）、§04 原文中精確逐字未找到但屬合理 paraphrase
  - 3.4% fire 合理
- 備註：可考慮把 quote 換成 §04 原文逐字（如「沒有資金願意幫別人解套」）

### 15. selling_pressure_dissolution_required (info, 42.5%)

- 條件：`today.close < prev_high_60 AND today.close > prior_low_60 AND today.close > prev.close`
- 課程 §07：「賣壓化解」需配合化解力量、非只靠消息
- 評斷：⚠️ **過寬**
  - 條件等同「區間內小紅」、無法辨識「正在化解 vs 被消息帶上」
  - 42.5% fire 證實過寬
- 建議：加量能條件（化解需要量）或「接近前高 N% 內」過濾

### 16. sunrise_vs_rising_three_boundary (info, 4.3%)

- 條件：`today.close > prev.close AND today.close >= prev_high_60`
- 課程 §16：日出攻擊結束 vs 上升三法
- 評斷：⚠️ **條件偏離**
  - 條件抓「紅 K + 站上前高」= 一般突破、不是「日出攻擊結束 vs 上升三法」邊界判斷
  - 原文邊界判斷需先有「日出攻擊狀態 + 短十字結束」or「黑 K 整理 + 隔日長紅」
  - 目前條件**無法區辨兩種狀態**、rec 文字反而正確（描述邊界）→ 條件 vs rec mismatch
- 建議：抓「N 日連紅後 + 短十字 / 黑 K」做為日出結束判斷

### 17. top_formation_three_criteria (critical, 47.7%)

- 條件：`today.close < prev_high_60 AND today.close < prev.close AND context.ma60_will_rise == false`
- 課程 §17：頭部三要件 = (1) 大盤狀況 (2) 基本面 (3) 是否被拉過頭
- 評斷：❌ **嚴重違背課程 + critical 過寬**
  - 原文三要件**沒有一個**是「60 日高 / MA60 走弱」
  - 原文核心是「**跌破頸線**」、不是「跌破 60 日高」
  - critical + 47.7% fire = 每 2.1 天一次「頭部成型 critical」、警示完全失能
  - quote「頭部三要件：大盤走弱、基本面轉差、是否被拉過頭」屬正確 paraphrase、但條件根本沒檢驗這三件事
- 建議：(a) 必須加「跌破頸線」型態識別，(b) 拿掉 critical 或徹底重設計

### 18. weak_bull_trendline_only (info, 42.5%)

- 條件：`today.close > prev.close AND today.close < prev_high_60 AND context.ma5_will_rise == true`
- 課程 §05：「微弱多方趨勢、不得已才用短期趨勢線」
- 評斷：⚠️ **過寬**
  - 條件「小紅 + MA5 升」等同任何弱勢反彈、42.5% fire 過寬
  - 課程語境是「高檔區域沒有任何標準可用」才用、不是任何小紅
- 建議：加「曾出現攻擊 + 後續沒有轉折組合」前提

### 19. zhongshu_recency_bias (info, 44.7%)

- 條件：`today.close < prev_high_60 AND today.close > prior_low_60 AND today.close < prev.close`
- 課程 §02：中樞整理 + 對抗近因偏誤
- 評斷：⚠️ **過寬**
  - 條件等同「區間內黑 K」、任何盤整黑 K 都觸發、44.7% fire 過寬
  - 課程「中樞型態」有明確結構（先上漲 + 橫向 + 不破紅 K 低點）
  - 目前條件**無中樞結構識別**
- 建議：加「N 日不破最近紅 K 低點 + 維持窄幅」識別中樞結構

---

## 總表

### ✅ OK (5)

- `bottom_break_struggle`
- `new_high_next_day_attack_required`
- `pressure_layer_no_support`（先前 bug 已修、待 fire rate 重測）
- `pressure_meeting_unresolved`
- （`just_high_upper_shadow` 條件 OK 但 rec 偏離 → 列入 ⚠️）

### ⚠️ 需修正 (10)

| Light | 主要問題 |
|---|---|
| gap_down_falling_three | 沒抓中繼整理 + 再黑 K 序列 |
| high_black_k_warning | 沒有「長黑/包覆/震幅 10%」幅度判斷 |
| just_high_upper_shadow | rec 語氣偏警示、課程結論偏多 |
| lack_of_power_distinction | 過寬 42.5%、沒抓攻擊意圖區 |
| limit_up_next_day_stats | 沒抓真正漲停、用「平盤以上」代替 |
| mountain_descent_four_types | 無法辨識四類、需結合基本面 |
| pessimistic_stock_structural | quote 非原文逐字 |
| selling_pressure_dissolution_required | 過寬 42.5%、無量能 |
| sunrise_vs_rising_three_boundary | 條件無法辨識邊界 |
| weak_bull_trendline_only | 過寬 42.5%、任何小紅都觸發 |
| zhongshu_recency_bias | 過寬 44.7%、無中樞結構識別 |

### ❌ 違背課程（高優先修） (4)

| Light | severity | fire | 違背點 |
|---|---|---|---|
| **top_formation_three_criteria** | critical | 47.7% | 三要件條件**完全沒檢驗**（無頸線 / 無基本面 / 無拉過頭）、critical + 47.7% 警示失能 |
| **high_pushup_next_step** | info | 4.3% | 條件抓「突破前高 + 紅 K」≠ 課程「橫向 + 低點墊高」推升結構 |
| **lowprice_first_pull_exit** | warn | 44.7% | 條件**完全沒判斷低價股**、所有中樞下跌都觸發 |
| **manipulator_distribution_warning** | critical | 42.5% | 條件抓單日黑 K ≠ 課程箱型出貨識別、critical + 42.5% 警示失能 |

---

## 額外發現 / Anomaly

1. **`prev_high_60` typo 不再是 bug**：features.py:45 已 alias、condition.py:62 已白名單。任務 brief 此前提需更新。
2. **5 個 lights fire rate ≥ 42.5%**：lack_of_power, selling_pressure_dissolution, weak_bull, mountain_descent, top_formation, manipulator, zhongshu, lowprice → 共 8 個。系統設計上每天必有 50% lights 亮燈、降低警示價值。建議全面提高條件特異性。
3. **2 個 critical lights 都過寬**（top_formation 47.7%、manipulator 42.5%）→ critical 階級**目前完全失能**。
4. **47.7% fire rate 在 top_formation / mountain_descent 完全相同**：條件結構相同（跌前高 + 黑 K + MA 走弱）、差別只在 MA20 vs MA60 → 可能高度共現、應確認是否真的提供獨立訊號。
5. **`pessimistic_stock_structural` 與 `bottom_break_struggle` 都用 `prior_low_60`**：前者加 MA20 條件、後者加紅 K 條件、合理區分。
6. **無 light 使用 `attack_cost / attack_intent_zone / defensive_low / merged_high / merged_low`** — 這些 features.py 產出的 advanced 欄位未被任何 light 利用、可能有低垂果實。

## 報告路徑

絕對路徑：`/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/docs/kline_course/notes/lights_audit_2026-06-04.md`
