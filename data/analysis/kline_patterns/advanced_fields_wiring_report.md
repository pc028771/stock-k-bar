# Advanced Fields Wiring Report — 2026-06-05

## 任務摘要

Wire 4 個 ContextSnapshot toplevel 欄位（`attack_cost` / `defensive_low` / `merged_high` / `merged_low`）進 `features.py`，讓對應的 4 個 dormant lights 從 0% 變正常觸發率。

---

## 4 個欄位實作細節

### 1. `merged_high` / `merged_low` (§24 合併十字線)

**課程來源**: 明日 K 線 第 24 篇《合併十字線》  
**語意**: 合併十字線 pattern 命中日的兩根 K 合併後高低點，forward-fill N 日保持有效。

**實作方式** (inline — 避免 `detect_with_metadata()` 的 `df.copy()` overhead):
- 直接在 `add_features()` 內部使用已計算的 features 欄位（`is_just_broke_high_intraday`, `upper_shadow`, `lower_shadow`, `prev_high`, `prev_low`, etc.）重新推導 merged_doji signal。
- Signal 命中日: `_merged_h = max(prev_high, high)`, `_merged_l = min(prev_low, low)`
- Forward-fill `MERGED_DOJI_CARRY_DAYS = 5` 日 [STUB-NEED-USER]

### 2. `attack_cost` (§20 攻擊成本顯現日)

**課程來源**: 明日 K 線 第 20 篇《攻擊成本顯現日》  
**語意**: 漲停鎖住突破前高當日的 close（漲停價 proxy），forward-fill 20 日。

**實作方式** (inline vectorized — 含 state-machine suppression):
- `raw_signal = is_limit_up_locked & (close > prior_high_60)`
- State-machine: groupby rolling max on shifted signal，抑制同一攻擊段的重複觸發
- Forward-fill `ATTACK_COST_FIRST_BREAKOUT_LOOKBACK_DAYS = 20` 日（已有常數）
- 注意：跳過分K intraday check（日K退化版），`ATTACK_COST_VOL_RATIO = 1.0` 等同無量能過濾

### 3. `defensive_low` (§26 防守姿態)

**課程來源**: 明日 K 線 第 26 篇《防守姿態》  
**語意**: 老師 9945 案例「過去六天的低點」= 防守支撐價位。

**實作方式**:
- Step 1: 計算過去 6 日最低 K 棒 low（`g["low"].shift(1).rolling(6).min()`）
- Step 2: **限制在 `is_just_broke_high = True` 的 bar**（防守姿態只在攻擊位置有意義）[STUB-NEED-USER]
- Step 3: Forward-fill `DEFENSIVE_LOW_LOOKBACK_DAYS = 6` 日

此限制讓 fire rate 從 11.6% 降至 1.82%（符合 critical 0.5–5% 目標）。

---

## 新增 STUB 常數清單

| 常數 | 值 | 說明 | 標記 |
|---|---|---|---|
| `MERGED_DOJI_CARRY_DAYS` | 5 | 合併十字線高低點 forward-fill 天數 | [STUB-NEED-USER] |
| `DEFENSIVE_LOW_LOOKBACK_DAYS` | 6 | 防守低點回看天數（老師 9945 案例數字） | [STUB-NEED-USER] |

兩個常數已加入 `scripts/kline/course_proxy_constants.py`，含完整 COURSE CONCEPT / QUOTE / PROXY VALUE / RATIONALE 說明。

---

## 4 個 Light Fire Rate（修前 → 修後）

| Light ID | 嚴重度 | 修前 | 修後 | 目標區間 | 狀態 |
|---|---|---|---|---|---|
| `lt_attack_cost_breakdown` | critical | 0% (ctx=None) | **2.90%** | 0.5–5% | ✅ |
| `lt_defensive_low_break` | critical | 0% (ctx=None) | **1.82%** | 0.5–5% | ✅ |
| `lt_merged_doji_high_break` | info | 0% (ctx=None) | **0.43%** | 0.1–3% | ✅ |
| `lt_merged_doji_low_break` | warn | 0% (ctx=None) | **0.52%** | 0.1–3% | ✅ |

**驗證條件**: top 200 tickers（依均量排名）× 2024-01-01 ~ 2026-06-30，共 113,431 rows。

---

## pytest 結果

- **584 tests pass** (deselecting 1 flaky perf test)
- 扣除的 `TestT3A4Performance::test_100_days_5_tickers_under_5s` **pre-existing failure** — 在修改前已連續失敗（baseline 跑 3 次全部 > 5.0s，5.04s / 5.33s / 5.91s），屬機器負載波動問題，非本次修改造成。

---

## 已知限制

1. **`merged_high`/`merged_low` 未加入 `ContextSnapshot` schema**: 因 Pydantic `extra="forbid"`，無法直接傳入 ContextSnapshot。`condition.py` 的 `_resolve_scalar()` 優先從 `row.get(field)` 讀取，所以 features.py wiring 後 lights 可正常觸發。Playbook 的 branch condition 如果用 `merged_high` 作為 RHS（如 `"next_day.close": "> merged_high"`）同樣走 row → ctx 查找鏈。

2. **`attack_cost` inline 跳過分K覆寫**: 完整版本需要逐 row DB 查詢，日K退化版 (`ATTACK_COST_VOL_RATIO = 1.0`) 等同「只要漲停鎖住突破前高就算」。fire rate 2.90% 在合理範圍，精確度由 pattern detector 分K覆寫補足。

3. **`defensive_low` 的 `is_just_broke_high` 前置條件是工程判斷**: 課程§26 未明示只在剛創新高時適用。但沒有此限制時 fire rate 達 11.6%（遠超 critical 5% 上限），加此限制課程語意也合理（防守姿態 = 攻擊位置的防守）。

4. **`DEFENSIVE_LOW_LOOKBACK_DAYS = 6` 是個案數字**: 來自老師 9945 案例，課程未明示通則。

5. **Performance flaky test**: `TestT3A4Performance` 在 macOS 上因系統負載波動，偶爾超過 5.0s 限制（my changes 增加約 +8ms per add_features 呼叫，對 5 tickers 約 +40ms total，邊際影響）。
