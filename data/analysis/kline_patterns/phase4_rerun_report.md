# Phase 4.3 Backtest Re-run Report (v2 — Bug Fixes)

Generated: 2026-06-04

---

## Task 1: 2 Always-True Lights 修正

### 根本原因

`features.py` 使用欄位名稱 `prior_high_60`，但 condition DSL YAML 引用 `prev_high_60`（兩者為不同名稱）。

在 `_resolve_scalar` / `_resolve_vectorized` 中，`prev_high_60` 為頂層欄位（whitelist 中），但 df 裡不存在此欄，因此：
- 純量模式：`row.get("prev_high_60")` → `None` → condition 回傳 `None`（pending）
- `_evaluate_lights` 中 `result is None` 被視為「active」→ **100% 觸發**

### 修正

在 `scripts/kline/features.py` 中，於 `prior_high_60` 建立之後加一行 alias：

```python
df["prior_high_60"] = g["high"].transform(...)  # 原有
df["prev_high_60"] = df["prior_high_60"]        # 新增 alias
```

YAML 條件保持不變（仍使用 `prev_high_60`），僅補上 df 欄位。

### Fire Rate 對比

| light_id | v1 (修正前) | v2 (修正後) | 說明 |
|----------|------------|------------|------|
| `new_high_next_day_attack_required` | 100.0% | **4.4%** | 只在 close+high >= 60日高點時觸發 |
| `pressure_meeting_unresolved` | 100.0% | **3.4%** | 只在 high 觸及但 close 未突破時觸發 |
| `lowprice_first_pull_exit` (reference) | 44.7% | 44.7% | 不變（有其他決定性條件） |
| `gap_down_falling_three` (reference) | 18.3% | 18.3% | 不變 |
| `pessimistic_stock_structural` (reference) | 2.7% | 2.7% | 不變 |

---

## Task 2: Schema 加 pattern_name

### 改動摘要

1. **`scripts/kline/scenarios/persistence.py`** — DDL 新增欄位：
   ```sql
   pattern_name TEXT NOT NULL DEFAULT ''
   ```
   `save()` 函數中從 `scenario.pattern_hit.pattern` 取值存入。

2. **`scripts/kline/scenarios/simulator.py`** — `_batch_save_runs()` 改動：
   - 每個 scenario 取 `scenario.pattern_hit.pattern` 存為 `pattern_name`
   - INSERT 語句新增 `pattern_name` 欄位

3. **`compute_branch_hit_rates()`** — 改用 `pattern_name` 分組（向下相容：偵測欄位是否存在，舊 DB 回退到 `action_type`）：
   ```sql
   COALESCE(NULLIF(ab.pattern_name, ''), ab.action_type, 'unknown') as pattern
   ```

4. **`scripts/run_phase4_backtest.py`** — `_get_pattern_trigger_stats()` 偵測 schema 版本並選擇性查詢 `pattern_name`。

---

## Task 3: 重跑 Phase 4.3 Backtest 統計

| 指標 | 數值 |
|------|------|
| Tickers | 200 |
| Date range | 2024-01-01 → 2026-06-30 |
| Trading dates | 583 |
| Ticker-days | 114,782 |
| Advisor runs saved | 114,782 |
| Branches total | 123,572 |
| Branch rows backfilled | 123,572 |
| Distinct pattern_names | 25 |
| Elapsed time | 33.9 minutes |

### 涵蓋的 pattern_name（25 個）

`bear_engulfing`, `biting`, `breakout_double_star`, `bull_engulfing`, `dark_double_star_anye`, `embracing`, `evening_star_abandoned`, `evening_star_island_reversal`, `gap_fill_down`, `gap_fill_up`, `gap_reversal`, `gap_under_pressure_reversal`, `high_hanging_man`, `meeting`, `merged_doji`, `morning_star_harami`, `morning_star_island_reversal`, `neutral_engulfing`, `outside_three_black`, `piercing_line`, `rebound`, `rising_falling`, `three_red_dadi_dangqian`, `trapped`, `two_crow_gap`

---

## 高命中率 Branches Top 5（含 pattern_name）

| pattern_name | branch_id | n_runs | hit_rate |
|-------------|-----------|--------|----------|
| `morning_star_island_reversal` | B2_next_day_gap_filled | 288 | **88.5%** |
| `gap_reversal` | B2_next_day_gap_filled | 2,449 | **83.7%** |
| `gap_under_pressure_reversal` | B1_next_day_gap_fills_up | 3,949 | **83.0%** |
| `breakout_double_star` | B1_next_day_gap_up_holds | 327 | **66.7%** |
| `morning_star_island_reversal` | B3_next_day_encounters_overhead_supply | 288 | **66.0%** |

**關鍵發現**：v1 的 Top 2（`exhaust_invalid / B2_next_day_gap_filled` 84.2% 和 `exhaust_invalid / B1_next_day_gap_fills_up` 83.0%）在 v2 中歸屬到真正的 pattern_name：
- `exhaust_invalid` → `morning_star_island_reversal` (88.5%) 和 `gap_reversal` (83.7%)
- `exhaust_invalid / B1_next_day_gap_fills_up` → `gap_under_pressure_reversal` (83.0%)

這 3 個 pattern 都是「gap 相關反轉型態在隔日確認」邏輯，物理意義清晰。

---

## 低命中率 Branches Top 5（含 pattern_name）

| pattern_name | branch_id | n_runs | hit_rate |
|-------------|-----------|--------|----------|
| `morning_star_island_reversal` | B1_next_day_gap_holds_no_fill | 288 | 11.5% |
| `gap_reversal` | B3_next_day_stalls_above_today_low | 2,449 | 14.5% |
| `outside_three_black` | B3_next_day_attempts_recovery | 75 | 14.7% |
| `three_red_dadi_dangqian` | B3_next_day_recovery_attempt | 389 | 18.0% |
| `dark_double_star_anye` | B2_next_day_recovers_above_twin_high | 1,469 | 19.9% |

---

## 對比 v1（舊 report）

| 指標 | v1 | v2 |
|------|----|----|
| `new_high_next_day_attack_required` fire rate | 100.0% | **4.4%** |
| `pressure_meeting_unresolved` fire rate | 100.0% | **3.4%** |
| High confidence branches | 2 | **3** |
| (pattern × branch_id) pairs ≥10 runs | 52 | **62** |
| `pattern` column 來源 | action_type（proxy） | **pattern_name（真實 K-bar pattern）** |
| Top 2 高命中率 pattern 歸屬 | `exhaust_invalid` (無意義) | `morning_star_island_reversal`, `gap_reversal` |

---

## Baseline + pytest

- **Calibration runner**: `confirmed_signal active: 44  hits=39  rate=88.6%` ✅ (≥ 88.6%)
- **pytest**: `560 passed` ✅（新增 2 個 bug fix 測試：T2.3.2i + T2.3.2j）

---

## Anomalies

1. **`pressure_layer_no_support` 90.9%**：此 light 未修正（不在本次任務範圍），fire rate 偏高需後續審查。
2. **avg_matched_days = 1.00 for all branches**：所有 playbook 用 `next_day_n=1`，建議後續增加 next_day_n=2 或 3 的 multi-day branches。
3. **25 個 pattern_name 全部涵蓋**：backtest 成功對所有 pattern 記錄。
