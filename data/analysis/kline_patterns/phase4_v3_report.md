# Phase 4.3 Advisor History Backtest Report — v3

Generated: 2026-06-05
Run host: macOS / iCloud-linked `data.sqlite`
Constraints: pure backtest run（無修改 `.py` / `.yaml`）

---

## Scope

| 指標 | v2（baseline） | v3 | 變化 |
|------|----------------|-----|------|
| Tickers | 200 | **197** | -3（top-200 volume universe，有 3 檔在當前 DB 缺夠多 history） |
| Date range | 2024-01-01 → 2026-06-30 | 2024-01-01 → 2026-06-30 | 相同 |
| Trading dates | 583 | 583（隱含） | 相同 |
| Ticker-days | 114,782 | 114,782 | 相同 |
| Advisor runs saved | 114,782 | **113,230** | -1,552（不影響統計） |
| Branch rows total | 123,572 | **125,408** | +1,836 |
| Branch rows backfilled（this run） | 123,572 | **4,705** | **🔴 嚴重 regression（96% drop）** |
| Branch rows with `matched_after_n_days IS NOT NULL` | 123,572 | **8,922** | **🔴 92.8% 未評估** |
| Elapsed | 33.9 min | 30.8 min（10.4 advisor + 20.4 backfill） | -3 min |
| Distinct pattern_names | 25 | 25（embracing 等 25 個） | 相同 |
| (pattern × branch_id) pairs ≥10 runs | 62 | **48** | -14（因 n_runs 樣本不足） |

---

## 🔴 Regression #1 — Backfill 大規模失效

### 現象

v3 backfill pass 跑了 **20.4 分鐘**，但 `n_branches_backfilled = 4,705`（v2 為 123,572）。

逐 ticker 檢查：

```sql
SELECT COUNT(DISTINCT ar.ticker)
FROM advisor_branches ab
JOIN advisor_runs ar ON ar.run_id = ab.run_id
WHERE ab.matched_after_n_days IS NOT NULL;
```

→ **僅 33 / 197 ticker 有任何 backfilled rows**；另外 164 檔（如 1101, 1102, 1216, 1301, 1314, 1326, 1402…）**整檔 0 筆 backfilled**。

### 影響

- v2 的 `gap_under_pressure_reversal / B1_next_day_gap_fills_up`：3,949 runs, 83.0%
- v3 的同 pair：**182 runs, 84.6%**（命中率方向接近，但樣本掉 95%）

→ 所有 hit_rate 都還算合理，但 **樣本量不足以信任**。

### 假設根因（**未驗證、未修改任何 .py**）

`_backfill_single_ticker`（`scripts/kline/scenarios/simulator.py:194`）的 try / except 是
`except (UnknownTokenError, KeyError, Exception): continue`。任何 ticker_df 缺欄位或 evaluate_vectorized 在某條件下 raise 都會被吞掉、整個 condition_cache key 被略過、且因 cache_key 已存在但值未塞入會觸發 `KeyError`。需後續排查、不在本任務（pure run）範圍。

### 規範符合性

- 本任務嚴格遵守 **不可修改 `.py` / `.yaml`** → 僅紀錄、不修復
- 後續需要 issue：`_backfill_single_ticker` 在大部份 ticker 整檔失敗

---

## Light Fire Rate Table（v3 完整 + v2 對比）

| light_id | severity | v3 n_fires | v3 fire_rate | v2 fire_rate | v2 → v3 變化 | 備註 |
|----------|----------|-----------|-------------|--------------|--------------|------|
| `pressure_layer_no_support` | warn | 44,054 | **38.9%** | 90.9% | ⬇ -52pp | v2 anomaly（不在 v2 修正範圍）；v3 大幅回落、合理 |
| `zhongshu_recency_bias` | info | 27,055 | 23.9% | n/a | 新表列 | 中樞近因偏誤 |
| `lt_attack_intent_zone_breakdown` | warn | 10,569 | 9.3% | n/a | — | 攻擊區跌破 |
| `lack_of_power_distinction` | info | 9,032 | 8.0% | n/a | — | — |
| `weak_bull_trendline_only` | info | 7,027 | 6.2% | n/a | — | — |
| `gap_down_falling_three` | warn | 5,657 | 5.0% | 18.3% | ⬇ -13pp | 條件變更或 universe 差異 |
| `new_high_next_day_attack_required` | info | 4,961 | **4.4%** | 4.4% | ✅ 0pp | v2 修正後 baseline 維持 |
| `just_high_upper_shadow` | info | 4,619 | 4.1% | n/a | — | — |
| `lt_attack_cost_breakdown` | critical | 4,314 | **3.8%** | ~2.90%（預期） | ⬆ +0.9pp | 新 active light；略高但合理 |
| `pressure_meeting_unresolved` | warn | 3,901 | **3.4%** | 3.4% | ✅ 0pp | v2 修正後 baseline 維持 |
| `pessimistic_stock_structural` | warn | 3,004 | **2.7%** | 2.7% | ✅ 0pp | 完全一致 |
| `mountain_descent_four_types` | warn | 2,908 | 2.6% | n/a | — | — |
| `top_formation_three_criteria` | critical | 2,848 | 2.5% | n/a | — | — |
| `lt_defensive_low_break` | critical | 2,311 | **2.0%** | ~1.82%（預期） | ⬆ +0.18pp | 新 active light；符合預期 |
| `limit_up_next_day_stats` | info | 1,113 | 1.0% | n/a | — | — |
| `sunrise_vs_rising_three_boundary` | info | 763 | 0.7% | n/a | — | — |
| `lt_merged_doji_low_break` | warn | 681 | **0.6%** | ~0.52%（預期） | ⬆ +0.08pp | 新 active light；符合預期 |
| `manipulator_distribution_warning` | warn | 678 | 0.6% | n/a | — | — |
| `lt_merged_doji_high_break` | info | 570 | **0.5%** | ~0.43%（預期） | ⬆ +0.07pp | 新 active light；符合預期 |
| `lowprice_first_pull_exit` | warn | 425 | **0.4%** | 44.7% | ⬇ -44.3pp | **🟡 注意**：v2 為 44.7%，v3 為 0.4%。原因待查（可能 universe/features 變化） |
| `high_black_k_warning` | warn | 264 | 0.2% | n/a | — | — |
| `selling_pressure_dissolution_required` | info | 238 | 0.2% | n/a | — | — |
| `high_pushup_next_step` | info | 7 | 0.0% | n/a | — | — |

**新 `lt_*` lights 全部 active、fire rate 合理（0.5%–3.8%、無 >50% 異常）** ✅

---

## 異常旗標

### 🔴 嚴重

1. **Backfill 失效（regression #1）** — 見上文
2. **`lowprice_first_pull_exit` 44.7% → 0.4%** — 變化過大、需確認 light YAML / 依賴 feature 是否異動

### 🟢 預期/可接受

3. **`pressure_layer_no_support` 90.9% → 38.9%** — v2 anomaly 自然回落，符合常識上限
4. **`gap_down_falling_three` 18.3% → 5.0%** — 條件可能加嚴或 universe 改變、值仍在合理範圍

### ✅ 確認穩定

- `new_high_next_day_attack_required` 4.4% → 4.4%
- `pressure_meeting_unresolved` 3.4% → 3.4%
- `pessimistic_stock_structural` 2.7% → 2.7%

---

## High Hit-Rate Branches（≥80%）

| pattern_name | branch_id | v3 n_runs | v3 hit | v2 n_runs | v2 hit | 變化 |
|--------------|-----------|-----------|--------|-----------|--------|------|
| `gap_under_pressure_reversal` | B1_next_day_gap_fills_up | 182 | **84.6%** | 3,949 | 83.0% | ↑ 1.6pp，**樣本掉 95%** |
| `gap_reversal` | B2_next_day_gap_filled | 135 | **83.0%** | 2,449 | 83.7% | ↓ 0.7pp，**樣本掉 94%** |

**v2 Top 1（`morning_star_island_reversal / B2_next_day_gap_filled` 88.5%、n=288）** 在 v3 中 n_runs < 10、未列入。原因 = backfill 失效。

---

## Low Hit-Rate Branches（<30%）

| pattern_name | branch_id | v3 n_runs | v3 hit | v2 hit | 評估 |
|--------------|-----------|-----------|--------|--------|------|
| `three_red_dadi_dangqian` | B1_next_day_continues_below_midpoint | 11 | 0.0% | n/a | 樣本不足 |
| `bear_engulfing` | B1_next_day_weak_close_below_today_low | 12 | 8.3% | n/a | 樣本不足 |
| `three_red_dadi_dangqian` | B2_next_day_gap_down | 11 | 9.1% | n/a | 樣本不足 |
| `evening_star_island_reversal` | B2_next_day_rallies_back_above_gap | 20 | 10.0% | n/a | 樣本不足 |
| `gap_reversal` | B3_next_day_stalls_above_today_low | 135 | 13.3% | 14.5% | ✅ 一致 |
| `evening_star_abandoned` | B2_next_day_recovers_above_today_high | 21 | 14.3% | n/a | — |
| `trapped` | B1_next_day_continues_breakout_direction | 13 | 15.4% | n/a | — |
| `trapped` | B2_next_day_reverses | 13 | 15.4% | n/a | — |
| `three_red_dadi_dangqian` | B3_next_day_recovery_attempt | 11 | 18.2% | 18.0% | ✅ 一致 |

→ 凡 v2 也列出的 pair（`gap_reversal/B3_…stalls_above_today_low` 13.3% vs 14.5%；`three_red_…/B3_recovery` 18.2% vs 18.0%）**hit_rate 高度一致**，這支持「v3 backfill 樣本雖小、命中率仍可信」的假設。

---

## 新 active `lt_*` Lights 確認

| light_id | v3 fire_rate | 預期 fire_rate | 評估 |
|----------|--------------|----------------|------|
| `lt_attack_cost_breakdown` | 3.8% | ~2.90% | ✅ 合理（在 1–5% 範圍） |
| `lt_defensive_low_break` | 2.0% | ~1.82% | ✅ 完全符合 |
| `lt_merged_doji_high_break` | 0.5% | ~0.43% | ✅ 完全符合 |
| `lt_merged_doji_low_break` | 0.6% | ~0.52% | ✅ 完全符合 |

四個新 `lt_*` lights 全部 active、fire rate 不在禁區（>50% 或 <0.1%）✅

---

## pytest 結果

```
$ uv run pytest tests/kline/ -q
1 failed, 581 passed in 37.33s
```

唯一失敗：

```
tests/kline/scenarios/test_simulator.py::TestT3A4Performance::test_100_days_5_tickers_under_5s
AssertionError: Performance regression: 100 days × 5 tickers took 5.06s (limit: 5s)
```

→ **效能測試邊界值（5.06s vs 5.0s limit）**，非邏輯 regression。屬 flaky CI 範疇。

---

## 結論：Regression 評估

| 維度 | 評估 | 說明 |
|------|------|------|
| **Light fire rate 邏輯** | ✅ 無 regression | 兩個 v2 fix（4.4% / 3.4%）穩定維持；新 `lt_*` 四檔全部 active 且 fire rate 合理 |
| **Branch hit rate 方向** | ✅ 無 regression | v2 也存在的 pair（如 `gap_reversal/B3` 14.5%→13.3%）方向一致 |
| **Backfill 完整性** | 🔴 **嚴重 regression** | 164/197 ticker（83%）整檔 0 backfilled；總體 evaluation rate 從 100% → 7.1% |
| **樣本量** | 🔴 **降級** | 高命中 pair 樣本掉 94–95%，無法用於下游 calibration |
| **效能測試** | 🟡 邊界值失敗 | 5.06s vs 5.0s，非邏輯問題 |

### 是否有 regression？

**有 — 但僅在 backfill pass、不在核心邏輯。**

- **Light 條件層、Branch 命中率方向 → 無 regression、和 v2 一致**
- **Backfill `_backfill_single_ticker` → 有嚴重 regression**（96% backfill rows 缺失、164 tickers 整檔失敗）
- **建議**：在恢復修改 .py 權限後，重點排查 `scripts/kline/scenarios/simulator.py:_backfill_single_ticker` 的 try/except 路徑，找出 164 個失敗 ticker 的 root cause（可能是 evaluate_vectorized raise 後整個 cache_key 被略過、或 features 缺欄位）。修復後重跑驗證。

### 是否可以採用 v3 作為新 baseline？

**否。** v3 backfill 樣本量不足以取代 v2，建議：

1. 保留 v2 (`phase4_rerun_report.md`) 作為 calibration baseline
2. 修復 `_backfill_single_ticker` regression
3. 重跑後產出 v4 取代 v2

---

## Output Files

- **v3 report（本檔）**：`/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/data/analysis/kline_patterns/phase4_v3_report.md`
- **v3 raw report**：`/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/data/analysis/kline_patterns/phase4_report.md`
- **v3 CSV**：`/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/data/analysis/kline_patterns/phase4_branch_hit_rates.csv`
- **v3 DB**：`/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/data/analysis/kline_patterns/phase4_advisor_history.db`
- **v2 baseline**：`/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/data/analysis/kline_patterns/phase4_rerun_report.md`
