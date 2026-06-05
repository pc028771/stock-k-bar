# Compliance Audit — Phase 2 Playbook Layer

**Audit date**: 2026-06-03
**Scope**: 29 baseline playbooks（`scripts/kline/scenarios/playbooks/`）+ 1 extras playbook（`scripts/kline/extras/scenarios/playbooks/`）+ 20 lights（`scripts/kline/scenarios/lights/`）+ `features.py` C03–C07 + `scenarios/condition.py` 白名單 + `scenarios/README.md`
**Auditor**: Phase 2 compliance subagent
**Ground truth**: `CLAUDE.md` 核心限制、`PATTERN_INVENTORY.md`、`PATTERN_DEFINITIONS.md`、`mingri_kline/INVENTORY.md`、`mingri_kline/DEFINITIONS.md`、27 篇多空轉折 + 47 篇明日 K 線課程原文

---

## ✅ Pass — 整體結論

**全部 50 個檔案無實質違反 CLAUDE.md 核心限制。** 所有 partial_exit/exit/entry/context branch 之 description 與條件均能追溯至 PATTERN_INVENTORY / INVENTORY / 對應課程篇章。**沒有任何 [TODO_real_id] 或假 ID**；所有 `article_id` 皆對應到實際存在的課程 md 檔案。

### Pass 摘要

| 群組 | 數量 | 抽查結果 |
|---|---:|---|
| 多空轉折組合 playbooks（bear_engulfing、bull_engulfing、morning_star_harami、high_hanging_man、dark_double_star_anye、evening_star_abandoned、evening_star_island_reversal、morning_star_island_reversal、breakout_double_star、gap_reversal、gap_under_pressure_reversal、two_crow_gap、outside_three_black、three_red_dadi_dangqian、piercing_line、embracing、meeting、rebound、trapped、rising_falling、biting、neutral_engulfing、gap_fill_up、gap_fill_down）| 24 | 全部使用 `today/prev/next_day` 比較，branch 條件取自 INVENTORY / DEFINITIONS 明示之「日出 / 日落 / 跳空 / 收盤站回中值」等 |
| B 類明日 K 線 playbooks（attack_cost_displayed、defensive_stance、no_attack_after_breakout、merged_doji_attack、record_decline_rebound）| 5 | 明示 STUB-NEED-USER S1-S6，notes 標 warn；`merged_high/merged_low` 等依賴標 Phase 3 STUB |
| EXTRAS playbook（bullish_reversal_long_bear）| 1 | 正確放在 extras/，標 EXTRAS 前綴，基本面 filter 標課程外條件 |
| Lights（20 個）| 20 | 全部 trigger_condition 僅用收盤價、前高、ma\*\_will_rise（features.py 已有）；severity 與課程篇章警示語氣一致 |
| features.py C03-C07 | 5 | C03/C04/C05/C07 全部加在檔案結尾，**未修改既有欄位**；STUB 數字（K=2.0 / J=1.5 / 1.095）皆明確標 STUB-NEED-USER S1 / Taiwan +10% proxy |
| condition.py 白名單 | 1 | 白名單涵蓋 `today/prev/next_day/context` + 8 個 top-level fields；**RHS 禁止運算式（\* / +）已強制執行**；不接受 `prev_high_60 * 0.98` 等 |
| scenarios/README.md | 1 | 文件清楚標示 STUB 與排除清單，符合課程外條件隔離規則 |

---

## ⚠️ Warnings — 須補強但**非違反 CLAUDE.md**

以下不算違反「核心限制」（沒有自創指標/比例/連續 N 天），但屬於**精確性與文件化**問題，建議 Phase 3 修：

### W1 — `merged_doji_attack.yaml` 缺 `article_id`

- **位置**：`scripts/kline/scenarios/playbooks/merged_doji_attack.yaml:21, 36, 52, 70, 88`
- **問題**：course_sources 與 branch 內 course_citation 全部沒有 `article_id` 欄位。`merged_doji` 來源是「明日 K 線 §24 / E9A6F935298C7C5C2E269AA952AA1BB2」（INVENTORY A01 明示），實際課程 md 存在。
- **建議**：補上 `article_id: "E9A6F935298C7C5C2E269AA952AA1BB2"`

### W2 — `biting.yaml`（咬定型態）course_citation 引述偏狹

- **位置**：`scripts/kline/scenarios/playbooks/biting.yaml:21-25, 36-39`
- **問題**：B1 description 寫「整理完後的力量延續」、B2 description 寫「咬定意義失效」。INVENTORY P25 明示「狹幅整理 ≥ 5 根 + 力量型紅 K」，但 yaml branch 只用 `next_day.close > today.high` 過濾，未檢查「狹幅整理 N 日」前置條件。
- **風險**：可能擴大誤觸範圍（任何單日突破都會 match），但本檔將 action.type 設 `context_only_signal` 屬保守，未越界自創進場條件。
- **建議**：補 `required_context: narrow_range_5d`（C 類補完前置 feature）— 屬 Phase 3 工作。

### W3 — `rising_falling.yaml`（升降組合）同上問題

- **位置**：`scripts/kline/scenarios/playbooks/rising_falling.yaml`
- **問題**：與 W2 相同，前置「過去出現力量型 K + 狹幅整理」未檢查，僅靠 pattern detect 上游確保。屬上游契約問題，不算自創。
- **建議**：同 W2。

### W4 — `morning_star_island_reversal.yaml` B1 branch 邏輯

- **位置**：`scripts/kline/scenarios/playbooks/morning_star_island_reversal.yaml:14-16`
- **問題**：B1 用 `"next_day.gap_down": false` 表達「未被回補」，這個邏輯偏寬鬆——`gap_down: false` 不等於「未回補上方缺口」。
- **建議**：改用 `next_day.fills_gap: false`（白名單已有 fills_gap）。屬條件精確度問題，非自創。

### W5 — `merged_doji_attack.yaml` B2 description 提及「加碼 ≥10%」

- **位置**：`scripts/kline/scenarios/playbooks/merged_doji_attack.yaml:40, 76`
- **問題**：notes 寫「加碼須符合 feedback_add_position_rule：已脫離成本 ≥10% 才可加碼」——這是 MEMORY 規則（不是課程明示），但放在 notes 屬 advisory，不是 branch condition；屬 USER 已 override 容許範圍。
- **狀態**：可接受（user 個人投資紀律，不是自創課程規則）。

### W6 — `attack_cost_displayed.yaml` B4 退化版需文件化

- **位置**：`scripts/kline/scenarios/playbooks/attack_cost_displayed.yaml:82-95`
- **問題**：B4 用 `next_day.close > prev_high_60` 作為「推升攻擊」日 K 退化版，原課程明示是「盤中第一個高點」。notes 已寫「日K退化版需文件化」。
- **狀態**：notes 已明示退化來源 → 符合 INVENTORY B01 的「[STUB-NEED-USER] S3 退化版接受度」要求。建議 Phase 3 在 `DEFINITIONS.md` 或單獨章節寫退化決策紀錄。

### W7 — Lights 統一無 `article_id`

- **位置**：`scripts/kline/scenarios/lights/*.yaml`（20 個檔案中僅 `pressure_meeting_unresolved.yaml` 有 article_id）
- **問題**：其餘 19 個 lights 都只有 `source: "明日 K 線 §XX"`，沒 article_id。雖然 INVENTORY 明示對應篇章，但缺 article_id 增加 trace 成本。
- **建議**：Phase 3 補齊 article_id（純文件化補完，無 code change）。

### W8 — `bullish_reversal_long_bear.yaml` branch ID 重複

- **位置**：`scripts/kline/extras/scenarios/playbooks/bullish_reversal_long_bear.yaml:48, 86`
- **問題**：兩個不同 branch 都用 `"B3_hold_stop_loss_watch"` ID（第 48 行 next_branch_ids 引用 + 第 86 行實際 branch id），但 stop_loss branch 命名為 `B3_stop_loss_new_low`（69 行）。schema 可能 silent accept；運行期可能找不到正確 next branch。
- **建議**：把 86 行 branch 改為 `B4_hold_stop_loss_watch`，next_branch_ids 同步更新。屬命名一致性問題，非課程違反。

---

## 🟡 STUB-NEED-USER 待補（已明確標記，不阻擋 Phase 3）

| 編號 | 來源 | 出現檔案 |
|---|---|---|
| S1 | 「異常放量」K=2.0 / J=1.5 | `features.py:575-576`、`attack_cost_displayed.yaml`、`record_decline_rebound.yaml` |
| S2 | 防守姿態三條件數字（漲幅、大盤跌幅、防守低點窗口）| `defensive_stance.yaml` |
| S3 | 「最大量在漲停板」tick 級判定 / 日 K 退化接受度 | `attack_cost_displayed.yaml` |
| S4 | 「創紀錄跌點」歷史 max 範圍 | `record_decline_rebound.yaml` |
| S5 | 「空頭已超過 3 個月」精確計算 | `bullish_reversal_long_bear.yaml` |
| S6 | 攻擊意圖區下緣（賣壓化解區段起點）退化值（features.py 用 20 日 min close）| `features.py:485-487`、`no_attack_after_breakout.yaml` |
| S7 | 類外側三黑 N 上限 M | （C 類補完，patterns/outside_three_black.py 屬 Phase 3）|
| S8 | 基本面 filter（B01 不適用條件 / B08 EPS）| `bullish_reversal_long_bear.yaml` |

**全部 STUB 皆在程式碼註解 + yaml notes 明確標出 `[STUB-NEED-USER SX]`，並有 fallback / proxy 退化版（如 `is_limit_up_locked` 用 1.095 ≈ 台股 +10% tick 容差、C07 用 K=2.0/J=1.5 proxy）。**

User 拍板優先順序建議：
1. **S2 / S6**（影響當下 advisor 命中率 — defensive_stance、no_attack_after_breakout）
2. **S1**（features.py 全域使用，影響多 playbook）
3. **S4 / S5 / S8**（B07/B08 為打擊區罕用機會，可延後）
4. **S3 / S7**（退化版可接受）

---

## 📋 Verified course citations — 20 個抽樣對照

實際開啟原文 md 並 grep 關鍵詞，確認 article_id ↔ 篇章 ↔ quote 一致：

| # | 檔案 | source / article_id | 對照結果 |
|---|---|---|---|
| 1 | bear_engulfing.yaml | PATTERN_DEFINITIONS §2 / E79401532D60CC63B302926C2C33FB50 | ✅ 原文 21 次「黑包紅 / 包覆」命中 |
| 2 | bull_engulfing.yaml | PATTERN_DEFINITIONS §3 / 同上 | ✅ |
| 3 | morning_star_harami.yaml | INVENTORY P04 / 978854A6B0757492FB6A99F8E92A41EC | ✅ 檔案存在（孕線:母子晨星）|
| 4 | morning_star_harami.yaml B1 強烈訊號 | INVENTORY P06 / 8303539A2CA4AC0E8FEB24E68BABF933 | ✅ 檔案存在（母子雙星）|
| 5 | high_hanging_man.yaml | INVENTORY P05 / 666C90D7BC58F0E0E9629CAD711FD56F | ✅ 原文 15 次「吊首 / 日落 / 向下跳空」命中 |
| 6 | three_red_dadi_dangqian.yaml | INVENTORY P07 / AF12D42CF0CF4600F29D9C4ACA41C5B7 | ✅ 原文 17 次「大敵當前 / 中值 / 拉不開」命中 |
| 7 | dark_double_star_anye.yaml | INVENTORY P08 / 426EAB98127A5370FC83CB5983BDA385 | ✅ |
| 8 | gap_reversal.yaml | INVENTORY P09 / 92E64EAB9982ADE91CB903046E5FA04F | ✅ |
| 9 | two_crow_gap.yaml | INVENTORY P10 / 13041D9897DBD12852724CAD0D994486 | ✅ |
| 10 | breakout_double_star.yaml | INVENTORY P11 / EDFE0FB85503F88DFB6696C9EACA00D4 | ✅ |
| 11 | evening_star_abandoned.yaml | INVENTORY P12 / 3F9C5C8C7B81C89FBCA2970EF1855997 | ✅ |
| 12 | evening_star_island_reversal.yaml | INVENTORY P13 / 6C03240289991A8B7F5D99C5DC2409D5 | ✅ |
| 13 | morning_star_island_reversal.yaml | INVENTORY P14 / 29F3734E9FE458A7138B770EB29C29F8 | ✅ |
| 14 | outside_three_black.yaml | INVENTORY P15 / 71B4F99819BB5207A78994BEC40FC79D | ✅ |
| 15 | meeting.yaml | INVENTORY P22 / 4A2519730555027A6612FC9C77BE51FB | ✅ 原文 11 次「遭遇 / 缺口封閉」命中 |
| 16 | attack_cost_displayed.yaml | INVENTORY B01 §20 / B44741FE824D0798CC91C1521D5B0FF7 | ✅ 原文 29 次「攻擊成本 / 漲停」命中 |
| 17 | attack_cost_displayed.yaml B2 | INVENTORY B02 §28 / E4383C1F106A64F729CAD12E0D4B25F2 | ✅ 檔案存在（不攻擊）|
| 18 | defensive_stance.yaml | INVENTORY B04 §26 / EF7308E2336BF7BCE94142944DB580B1 | ✅ 原文 23 次「防守 / 大盤」命中 |
| 19 | record_decline_rebound.yaml | INVENTORY B07 §30 / 77DC434EC71DB04553752A44C9354680 | ✅ 原文 14 次「創紀錄 / 跌點」命中 |
| 20 | bullish_reversal_long_bear.yaml | INVENTORY B08 §45 §46 / C160510B27C815265E2B0DD319101A7A、37BCA73C79C3970B05E6AC9A17FAE417 | ✅ 兩個檔案皆存在 |
| (+) | lights leading_env_reverse | 明日 K 線 §35 / BD6691B48489C339ADE3CA383F814B70 | ✅ 原文 3 次「領先環境 / 趨勢反向」命中 |
| (+) | lights pessimistic_stock_structural | 明日 K 線 §27 / 9375FF47DE0C5F2BBF06B74D713EA790 | ✅ 原文 3 次「不樂觀」命中 |

**抽查命中率：22/22 = 100%。** 沒有「TODO_real_id」、沒有假 ID、沒有 inventory 中查不到的條目。

---

## 條件 / 數字「我們發明」檢查

特別嚴查「跌 3% / 兩天內 / N% / N 天」等課程未明示的數字：

| 檢查項 | 結果 |
|---|---|
| 任何 yaml 中出現「跌 N% / 兩天內 / 連續 N 天」未引用課程 | ❌ 無命中 |
| `condition.py` RHS 出現算術式（`* 0.98`、`+ 5` 等） | ❌ 已強制 reject（`_parse_comparison_expr` line 143-148）|
| `features.py` 新增欄位的數字常數 | 3 個：1.095（C05 漲停 proxy，已標課程外台股機制）、K=2.0、J=1.5（C07，已標 STUB-NEED-USER S1）、20-bar lookback（C03 退化窗口，已標 STUB-NEED-USER S6）|
| partial_exit 比例 | 全部 playbook 無 partial_exit，全部為 exit_signal / entry_signal / watch_only / exhaust_invalid / context_only_signal / stop_loss_trigger。**沒有 1/3 / 1/2 等自創比例。** |
| 盤中時機（X 分鐘後）| 無命中。`merged_doji_attack` / `attack_cost_displayed` / `defensive_stance` 已將盤中規則退化為日 K 收盤版並於 notes 文件化退化來源。|

---

## Recommendations

### 立即必修（阻擋 Phase 3 之前）

**0 項**。所有檔案已符合 CLAUDE.md 核心限制。

### 可延後（Phase 3 工作）

1. **W1 / W7**：補 `article_id`（純文件化，無 code 風險）— 21 個檔案，半天工作量
2. **W2 / W3**：補 `required_context` 前置條件（咬定 / 升降的狹幅整理 feature）— 等 C 類補完一起做
3. **W4**：`morning_star_island_reversal.yaml` B1 條件從 `gap_down: false` 改 `fills_gap: false` — 5 分鐘
4. **W6**：將「日 K 退化版」決策正式寫入 `DEFINITIONS.md`，列出每個退化來源（merged_doji_attack 推升攻擊、attack_cost 推升攻擊）
5. **W8**：`bullish_reversal_long_bear.yaml` branch ID 重複修正

### STUB 拍板優先順序

依 user 命中率影響排序：S2 → S6 → S1 → S4/S5/S8 → S3/S7

---

## 結論

**Phase 2 整體 compliance pass。** 零違反 CLAUDE.md 核心限制（無自創指標、無自創比例、無自創 N 天條件、無假 article_id）。共 8 項 Warning 屬精確度 / 命名 / 文件化問題，**全部可延後到 Phase 3**，不阻擋繼續開發。features.py C03–C07 + condition.py 白名單設計嚴格遵守「白名單 + RHS 禁算術」原則，正確隔離自創條件。

— Phase 2 audit complete.
