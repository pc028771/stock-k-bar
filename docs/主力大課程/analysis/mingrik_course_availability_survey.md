# 明日K線課程 — 可用性調查報告

> 調查日期：2026-06-08  
> 調查範圍：`docs/kline_course/mingri_kline/` + `scripts/kline/` 已實作狀況

---

## 1. 現有課程素材（已完整擷取）

| 檔案 | 說明 | 行數 |
|---|---|---|
| `docs/kline_course/mingri_kline/INDEX.md` | 47 篇文章索引（含字數、圖片數、本地路徑）| 64 行 |
| `docs/kline_course/mingri_kline/INVENTORY.md` | 47 篇分類分析 + 實作規格草稿（A/B/C/D 四類）| 404 行 |
| `docs/kline_course/mingri_kline/DEFINITIONS.md` | 課程獨有術語定義（攻擊意圖/企圖、防守低點等）| 266 行 |
| `docs/kline_course/mingri_kline/*_NN-*.md` | 47 篇原始文章（已全部在地化）| 各約 1,400–3,200 字 |

**結論：47 篇文章 100% 已擷取，且 INVENTORY.md 已完成完整的規格分析。**

---

## 2. INVENTORY 分析結果（47 篇分類）

| 類別 | 數量 | 說明 |
|---|---:|---|
| **A — 新型態 / 新訊號** | 2 | 合併十字線 (A01)、類外側三黑 (A02) |
| **B — 進出場規則** | 8 | 攻擊成本顯現/跌破、防守姿態、不攻擊、創紀錄跌點…等 |
| **C — 既有 pattern 補充** | 14 | 修現有 detect 邏輯、新增 features 欄位、scoring |
| **D — 純觀念 / 心法** | 23 | 只寫 DEFINITIONS，不實作 |

核心結論（INVENTORY §0 語）：「明日K線 ≈ 應變劇本層 (playbook layer)。幾乎沒有獨立新型態，大部分是既有概念的隔日應變劇本。」

---

## 3. 已實作狀況（截至 2026-06-08）

### 3.1 Patterns 層（`scripts/kline/patterns/`）

| 規格 ID | 檔案 | 狀態 |
|---|---|---|
| A01 merged_doji | `patterns/merged_doji.py` | ✅ 已實作 |
| A02 outside_three_black_like | `patterns/outside_three_black_like.py` | ✅ 已實作 |
| B01 attack_cost_displayed | `patterns/attack_cost_displayed.py` | ✅ 已實作 |
| C11 zhongshu_pattern | `patterns/zhongshu_pattern.py` | ✅ 已實作 |

### 3.2 Features 層（`scripts/kline/features.py`）

| 規格 ID | 欄位 | 狀態 |
|---|---|---|
| C03 | `attack_intent_zone_high` / `attack_intent_zone_low` / `intent_zone_break` | ✅ 已實作 |
| C04 | `is_just_broke_high` / `is_just_broke_high_intraday` | ✅ 已實作 |
| C05 | `is_limit_up_locked` | ✅ 已實作 |
| C07 | `is_anomalous_volume` | ✅ 已實作 |

### 3.3 Scenarios / Playbooks 層（`scripts/kline/scenarios/playbooks/`）

| 規格 ID | Playbook YAML | 狀態 |
|---|---|---|
| B01/B02 attack_cost_displayed | `attack_cost_displayed.yaml` | ✅ 已實作 |
| B03 merged_doji_attack | `merged_doji_attack.yaml` | ✅ 已實作 |
| B04/B05 defensive_stance | `defensive_stance.yaml` | ✅ 已實作 |
| B06 no_attack_after_breakout | `no_attack_after_breakout.yaml` | ✅ 已實作 |
| B07 record_decline_rebound | `record_decline_rebound.yaml` | ✅ 已實作 |
| B08 — | `extras/` (跨課程基本面需求) | ✅ 正確放 extras（非 entry）|

### 3.4 Manual Hints（`scripts/kline/scenarios/manual_hints.py`）

- `check_defensive_stance_hint` ✅
- `check_record_decline_rebound_hint` ✅

### 3.5 尚未實作的 INVENTORY 項目

| 規格 ID | 說明 | 優先級 |
|---|---|---|
| C08 | `attack_continuity.py` scoring | 中 |
| C09 | `pattern_pressure.py` scoring | 中 |
| C10 | `ma60_rolloff.py` 季線扣抵補充 | 低 |
| C12 | `inner_trapped_to_gap_reversal` link feature | 低 |
| C13 | `two_crow_gap.py` metadata 補充 | 低（docstring 只）|
| C14 | `trailing_stop.py` 微弱多方退化版 | 低 |
| C02 | `high_long_black.py` 跳空回補條件 | 中 |
| S1–S8 | [STUB-NEED-USER] 數字待確認 | 待確認 |

---

## 4. 實作可行性評估

**可立即實作**的項目（無 STUB 卡住）：
- C02：`high_long_black.py` 加「開跳 + 盤中回補 + close < prev_low」→ 日 K 退化版一行邏輯
- C08/C09：scoring module — 邏輯清晰、只需 features 欄位（已全部就位）
- C10：`ma60_rolloff.py` docstring + 一個 condition 加分

**需 user 先確認 STUB 數字**的項目：
- S1 異常放量 K/J（C07 已有 proxy，但數字需拍板）
- S2 防守姿態三條件數字（B04 已有 playbook，但進場門檻數字未確認）
- S3 漲停鎖住日K退化版量比（B01 已有，但 vol_ma 倍數未正式確認）

**明確不實作**（INVENTORY §4.4）：B08 純基本面 filter、§42/§44/§19 心法類。

---

## 5. 推薦

**🟢 現有 core 規則（A01/B01–B07/C03–C07 + 全部 playbook）已完整實作，不需新的課程擷取工作。**

明日K線課程的素材 100% 到位（47 篇已下載），且 INVENTORY.md 規格分析已完成。主要 patterns（merged_doji、attack_cost_displayed、outside_three_black_like、zhongshu）和全部關鍵 features 欄位均已在 `scripts/kline/` 中實作；scenarios/playbooks 也對應 B01–B07 全部建立。

**剩餘工作是補強，不是補缺**：C08/C09 scoring module 和 C02 high_long_black 補充是值得做的 incremental 工作，但不構成「缺漏課程」的問題。若要新增 detector，建議優先從 **C08 attack_continuity scoring** 下手（依賴 features 全部就位，邏輯在 INVENTORY §C08 已有完整 spec，預估 2–3 小時）。

**action 前必須先確認 STUB S1–S3 數字**（per CLAUDE.md 「寫 scanner 前先讓 user 確認策略完備度」）。
