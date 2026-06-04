# Entry Threshold Grid Search Calibration Report

生成時間：2026-06-04 00:37:01

---

## 執行摘要

- **可調常數**：10 個
- **Grid 組合數**：41
- **執行時間**：24.0 分鐘
- **目標函數**：`score = hit_rate × log(1 + n_runs)`（平衡命中率與樣本數）

### Baseline（原始常數）

| 指標 | 值 |
|---|---|
| entry_signal.B1_gap_up_attack n_runs | 79 |
| entry_signal.B1_gap_up_attack hit_rate | 49.4% |
| entry_signal.B1_gap_up_attack score | 2.1633 |
| gap_fill_up n_fires | 4615 |
| gap_fill_down n_fires | 4682 |
| **total_score** | **16.2656** |
| calibration runner case hit rate | 88.6% |

---

## Sanity Check

| 項目 | 結果 |
|---|---|
| pytest 554 tests | ✅ 全綠 |
| calibration runner baseline hit rate | 88.6% |
| calibration runner (post-search) hit rate | 88.6% |
| baseline ≥ 85% 保護 | ✅ PASS |

---

## ⚠️ 重要修正：GAP_FILL_WINDOW_DAYS 分析的根本誤差

Grid search 腳本在計算 `GAP_FILL_WINDOW_DAYS` 的 score 時，誤用了錯誤的 hit_rate：

| 誤用值 | 正確來源 |
|---|---|
| 83% (B1_next_day_gap_fills_up) | 來自 **gap_reversal.yaml**（不依賴 GAP_FILL_WINDOW_DAYS） |
| 84% (B2_next_day_gap_filled) | 來自 **gap_under_pressure_reversal.yaml**（不依賴 GAP_FILL_WINDOW_DAYS） |
| **實際受影響的 branches** | gap_fill_up.yaml B1=25.2%, gap_fill_down.yaml B1=22.0% |

**正確解讀**：`GAP_FILL_WINDOW_DAYS` 只影響 `gap_fill_up.yaml` 和 `gap_fill_down.yaml` 的 playbook，其 branches 命中率僅 22–25%（context_only_signal 等級），不是高命中率的 exhaust_invalid branches。以正確 hit_rate 重算：

- 正確 score_gfu = 0.252 × log(1+4642) ≈ 2.12（原誤算 7.00）
- 正確 score_gfd = 0.220 × log(1+4698) ≈ 1.86（原誤算 7.10）
- GAP_FILL_WINDOW_DAYS=45 的 score 提升約 +0.12，且高度依賴「更多更遠的缺口命中率維持 22-25%」的假設

**結論**：GAP_FILL_WINDOW_DAYS 20→45 的改善幅度被嚴重高估。建議保留現有值 20，或獨立做 window 分析確認舊缺口的 hit_rate 是否維持。

---

## 推薦套用的 Changeset

**本次 grid search 無可靠推薦套用的常數。**

所有 `course_proxy_constants.py` 中的常數（除 GAP_FILL_WINDOW_DAYS 外）對目標 branches 完全無影響（n_runs=79 恆定）。GAP_FILL_WINDOW_DAYS 的建議因 hit_rate 計算誤差不予採納。

---

## 不推薦套用的常數

- **`GAP_FILL_WINDOW_DAYS`** (`20` → `45`): 評分誤差（見上方修正說明）— 使用錯誤的 83%/84% hit_rate，實際受影響 branches 僅 22-25%；且 window 增大引入更遠舊缺口（可能降低 hit_rate）
- **`DOJI_MAX_BODY_PCT`** (`0.006` → 任何值): **根本無效** — merged_doji 的 binding constraint 是 `just_broke_high + shadow 組合`，不是 doji 門檻；全格點 n_runs 恆定為 79
- **`DOJI_MIN_RANGE_PCT`** (`0.015` → 任何值): **根本無效** — 同上
- **`ATTACK_WINDOW_DAYS`** (`5` → 任何值): **根本無效** — 不影響目標 branches 的 pattern 觸發
- **`ATTACK_HIGHER_LOW_MIN_5DAY`** (`4` → 任何值): **根本無效** — 只影響 scoring 輸出，不影響 pattern 觸發
- **`RISING_LOWS_MIN_FRAC`** (`0.5` → 任何值): **根本無效** — 只影響 is_pattern_breakout feature
- **`STABLE_UPPER_MAX_SPREAD`** (`0.05` → 任何值): **根本無效** — 只影響 is_pattern_breakout feature
- **`FIRST_BREAKOUT_LOOKBACK`** (`60` → 任何值): **根本無效** — 只影響 breakout_attack scoring
- **`REBOUND_LOOKBACK_N`** (`5` → 任何值): **根本無效** — 只影響 rebound pattern，非目標 branch
- **`ISLAND_MAX_BARS`** (`10` → 任何值): **根本無效** — 只影響 island reversal patterns，非目標 branch

---

## 逐常數 Grid 明細

### DOJI_MAX_BODY_PCT

**說明**：十字線最大實體比例 (body/open ≤ X)
**影響**：merged_doji → entry_signal.B1_gap_up_attack

| value | is_current | entry_B1 n_runs | entry_B1 hit_rate | gfu_n | gfd_n | total_score |
|---|---|---|---|---|---|---|
| 0.004 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 0.005 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 0.006 | ✅ | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 0.008 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 0.01 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |

### DOJI_MIN_RANGE_PCT

**說明**：十字線最小振幅比例 (range/open ≥ X)
**影響**：merged_doji → entry_signal.B1_gap_up_attack

| value | is_current | entry_B1 n_runs | entry_B1 hit_rate | gfu_n | gfd_n | total_score |
|---|---|---|---|---|---|---|
| 0.01 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 0.012 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 0.015 | ✅ | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 0.018 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 0.02 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |

### GAP_FILL_WINDOW_DAYS

**說明**：缺口回補時間窗 (看回幾個交易日的缺口)
**影響**：gap_fill_up/down → exhaust_invalid.B1_B2_gap_fills

| value | is_current | entry_B1 n_runs | entry_B1 hit_rate | gfu_n | gfd_n | total_score |
|---|---|---|---|---|---|---|
| 10 |  | 79 | 0.494 | 3374 | 3378 | **15.7316** |
| 15 |  | 79 | 0.494 | 4075 | 4103 | **16.0515** |
| 20 | ✅ | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 30 |  | 79 | 0.494 | 5399 | 5663 | **16.5556** |
| 45 |  | 79 | 0.494 | 6329 | 6634 | **16.8204** |

### ATTACK_WINDOW_DAYS

**說明**：推升攻擊視窗天數
**影響**：attack_intensity features → merged_doji context

| value | is_current | entry_B1 n_runs | entry_B1 hit_rate | gfu_n | gfd_n | total_score |
|---|---|---|---|---|---|---|
| 4 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 5 | ✅ | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 6 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 7 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |

### ATTACK_HIGHER_LOW_MIN_5DAY

**說明**：5日內低點墊高最少天數
**影響**：attack_intensity feature → scoring

| value | is_current | entry_B1 n_runs | entry_B1 hit_rate | gfu_n | gfd_n | total_score |
|---|---|---|---|---|---|---|
| 3 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 4 | ✅ | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 5 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |

### RISING_LOWS_MIN_FRAC

**說明**：60日內低點墊高最低比例
**影響**：is_pattern_breakout feature

| value | is_current | entry_B1 n_runs | entry_B1 hit_rate | gfu_n | gfd_n | total_score |
|---|---|---|---|---|---|---|
| 0.4 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 0.5 | ✅ | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 0.6 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 0.65 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |

### STABLE_UPPER_MAX_SPREAD

**說明**：箱型上緣穩定最大散差
**影響**：is_pattern_breakout feature

| value | is_current | entry_B1 n_runs | entry_B1 hit_rate | gfu_n | gfd_n | total_score |
|---|---|---|---|---|---|---|
| 0.03 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 0.05 | ✅ | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 0.07 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 0.1 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |

### FIRST_BREAKOUT_LOOKBACK

**說明**：首次突破判斷回看天數
**影響**：breakout_attack → scoring

| value | is_current | entry_B1 n_runs | entry_B1 hit_rate | gfu_n | gfd_n | total_score |
|---|---|---|---|---|---|---|
| 40 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 60 | ✅ | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 80 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |

### REBOUND_LOOKBACK_N

**說明**：反撲短期N天上限
**影響**：rebound pattern

| value | is_current | entry_B1 n_runs | entry_B1 hit_rate | gfu_n | gfd_n | total_score |
|---|---|---|---|---|---|---|
| 3 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 5 | ✅ | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 7 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 10 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |

### ISLAND_MAX_BARS

**說明**：島狀反轉孤島K數上限
**影響**：morning/evening star island reversal

| value | is_current | entry_B1 n_runs | entry_B1 hit_rate | gfu_n | gfd_n | total_score |
|---|---|---|---|---|---|---|
| 5 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 8 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 10 | ✅ | 79 | 0.494 | 4615 | 4682 | **16.2656** |
| 15 |  | 79 | 0.494 | 4615 | 4682 | **16.2656** |

---

## 根因分析：為何所有常數對 entry_signal 無效

### entry_signal.B1_gap_up_attack (n=79)

Pattern: `merged_doji`。觸發條件分解：

1. **`just_broke_high`**：prev_close > prior_high_60 OR close > prior_high_60 — 純價格條件，不受任何常數控制
2. **`prev_upper_dominant`**：前根上影線 > 下影線 — 純價格條件
3. **`today_lower_dominant`**：今根下影線 > 上影線 — 純價格條件
4. **`is_merged_doji`**：|merged_body| / merged_range ≤ `MERGED_DOJI_BODY_RATIO`(0.25) AND shadow_min ≥ 0.2 — 這才受 module-level 常數控制，但 `MERGED_DOJI_BODY_RATIO` 和 `MERGED_DOJI_SHADOW_MIN_RATIO` 不在 `course_proxy_constants.py`，在 `scripts/kline/patterns/merged_doji.py`

**結論**：`course_proxy_constants.py` 中沒有任何常數控制 merged_doji 的觸發條件。可調的 `DOJI_MAX_BODY_PCT` 只用於 `is_doji` feature（單根十字線），與合併十字線判斷完全分離。

### 真正可調整 entry_signal 的路徑

若要提升 entry_signal.B1_gap_up_attack 的 n_runs（從 79 → 更多）或 hit_rate（從 49.4% → 更高），需要修改：

1. `merged_doji.py` 的 module-level 常數 `MERGED_DOJI_BODY_RATIO`（0.25）和 `MERGED_DOJI_SHADOW_MIN_RATIO`（0.2）
2. 或放寬 `just_broke_high` 的位置條件（但這是課程明示規則，不可放寬）

建議：將 `MERGED_DOJI_BODY_RATIO` 和 `MERGED_DOJI_SHADOW_MIN_RATIO` 移入 `course_proxy_constants.py`，再重跑 grid search。

---

## 注意事項

1. **本報告不寫回 `course_proxy_constants.py`** — 請 user 確認後再手動套用 changeset
2. **entry_signal.B1_gap_up_attack hit_rate** 在此計算為「merged_doji 觸發日隔日有跳空」的比率，
   與 phase4_advisor_history.db 記錄的 57% 略有差異（phase4 範圍 2024-2026 top-200，
   本報告同範圍）
3. **gap_fill 分析** 使用固定 baseline hit_rate (B1=83%, B2=84%)，
   GAP_FILL_WINDOW_DAYS 的 score 改善僅反映 n_runs 的增減，非 hit_rate 的變化
4. **merged_doji 不在 course_proxy_constants.py** — MERGED_DOJI_BODY_RATIO /
   MERGED_DOJI_SHADOW_MIN_RATIO 是 merged_doji.py 的 module-level 常數，
   需要獨立調整（此次 grid search 範圍不含）

---
_Report generated by `scripts/calibrate_entry_thresholds.py`_