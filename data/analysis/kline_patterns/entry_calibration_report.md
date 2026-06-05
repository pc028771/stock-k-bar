# Entry Threshold Grid Search Calibration Report

生成時間：2026-06-04 13:06:17

---

## 執行摘要

- **可調常數**：10 個
- **Grid 組合數**：41
- **執行時間**：24.3 分鐘
- **目標函數**：`score = hit_rate × log(1 + n_runs)`（平衡命中率與樣本數）

### Baseline（原始常數）

| 指標 | 值 |
|---|---|
| entry_signal.B1_gap_up_attack n_runs | 442 |
| entry_signal.B1_gap_up_attack hit_rate | 54.3% |
| entry_signal.B1_gap_up_attack score | 3.3087 |
| gap_fill_up n_fires | 4615 |
| gap_fill_down n_fires | 4682 |
| **total_score** | **17.4111** |
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

## 推薦套用的 Changeset

以下常數建議套用（score 改善 > 0.01 且無過擬合風險）：

### `GAP_FILL_WINDOW_DAYS`: `20` → `45`

- **說明**：缺口回補時間窗 (看回幾個交易日的缺口)
- **影響**：gap_fill_up/down → exhaust_invalid.B1_B2_gap_fills
- **score 改善**：17.4111 → 17.9659 (+0.5548)

```diff
- GAP_FILL_WINDOW_DAYS = 20
+ GAP_FILL_WINDOW_DAYS = 45
```

---

## 不推薦套用的常數

- **`DOJI_MAX_BODY_PCT`** (`0.006` → `0.004`): 改善幅度微小 (Δscore=0.0000 ≤ 0.01)
- **`DOJI_MIN_RANGE_PCT`** (`0.015` → `0.01`): 改善幅度微小 (Δscore=0.0000 ≤ 0.01)
- **`ATTACK_WINDOW_DAYS`** (`5` → `4`): 改善幅度微小 (Δscore=0.0000 ≤ 0.01)
- **`ATTACK_HIGHER_LOW_MIN_5DAY`** (`4` → `3`): 改善幅度微小 (Δscore=0.0000 ≤ 0.01)
- **`RISING_LOWS_MIN_FRAC`** (`0.5` → `0.4`): 改善幅度微小 (Δscore=0.0000 ≤ 0.01)
- **`STABLE_UPPER_MAX_SPREAD`** (`0.05` → `0.03`): 改善幅度微小 (Δscore=0.0000 ≤ 0.01)
- **`FIRST_BREAKOUT_LOOKBACK`** (`60` → `40`): 改善幅度微小 (Δscore=0.0000 ≤ 0.01)
- **`REBOUND_LOOKBACK_N`** (`5` → `3`): 改善幅度微小 (Δscore=0.0000 ≤ 0.01)
- **`ISLAND_MAX_BARS`** (`10` → `5`): 改善幅度微小 (Δscore=0.0000 ≤ 0.01)

---

## 逐常數 Grid 明細

### DOJI_MAX_BODY_PCT

**說明**：十字線最大實體比例 (body/open ≤ X)
**影響**：merged_doji → entry_signal.B1_gap_up_attack

| value | is_current | entry_B1 n_runs | entry_B1 hit_rate | gfu_n | gfd_n | total_score |
|---|---|---|---|---|---|---|
| 0.004 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 0.005 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 0.006 | ✅ | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 0.008 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 0.01 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |

### DOJI_MIN_RANGE_PCT

**說明**：十字線最小振幅比例 (range/open ≥ X)
**影響**：merged_doji → entry_signal.B1_gap_up_attack

| value | is_current | entry_B1 n_runs | entry_B1 hit_rate | gfu_n | gfd_n | total_score |
|---|---|---|---|---|---|---|
| 0.01 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 0.012 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 0.015 | ✅ | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 0.018 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 0.02 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |

### GAP_FILL_WINDOW_DAYS

**說明**：缺口回補時間窗 (看回幾個交易日的缺口)
**影響**：gap_fill_up/down → exhaust_invalid.B1_B2_gap_fills

| value | is_current | entry_B1 n_runs | entry_B1 hit_rate | gfu_n | gfd_n | total_score |
|---|---|---|---|---|---|---|
| 10 |  | 442 | 0.543 | 3374 | 3378 | **16.8771** |
| 15 |  | 442 | 0.543 | 4075 | 4103 | **17.1970** |
| 20 | ✅ | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 30 |  | 442 | 0.543 | 5399 | 5663 | **17.7011** |
| 45 |  | 442 | 0.543 | 6329 | 6634 | **17.9659** |

### ATTACK_WINDOW_DAYS

**說明**：推升攻擊視窗天數
**影響**：attack_intensity features → merged_doji context

| value | is_current | entry_B1 n_runs | entry_B1 hit_rate | gfu_n | gfd_n | total_score |
|---|---|---|---|---|---|---|
| 4 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 5 | ✅ | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 6 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 7 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |

### ATTACK_HIGHER_LOW_MIN_5DAY

**說明**：5日內低點墊高最少天數
**影響**：attack_intensity feature → scoring

| value | is_current | entry_B1 n_runs | entry_B1 hit_rate | gfu_n | gfd_n | total_score |
|---|---|---|---|---|---|---|
| 3 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 4 | ✅ | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 5 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |

### RISING_LOWS_MIN_FRAC

**說明**：60日內低點墊高最低比例
**影響**：is_pattern_breakout feature

| value | is_current | entry_B1 n_runs | entry_B1 hit_rate | gfu_n | gfd_n | total_score |
|---|---|---|---|---|---|---|
| 0.4 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 0.5 | ✅ | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 0.6 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 0.65 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |

### STABLE_UPPER_MAX_SPREAD

**說明**：箱型上緣穩定最大散差
**影響**：is_pattern_breakout feature

| value | is_current | entry_B1 n_runs | entry_B1 hit_rate | gfu_n | gfd_n | total_score |
|---|---|---|---|---|---|---|
| 0.03 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 0.05 | ✅ | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 0.07 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 0.1 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |

### FIRST_BREAKOUT_LOOKBACK

**說明**：首次突破判斷回看天數
**影響**：breakout_attack → scoring

| value | is_current | entry_B1 n_runs | entry_B1 hit_rate | gfu_n | gfd_n | total_score |
|---|---|---|---|---|---|---|
| 40 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 60 | ✅ | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 80 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |

### REBOUND_LOOKBACK_N

**說明**：反撲短期N天上限
**影響**：rebound pattern

| value | is_current | entry_B1 n_runs | entry_B1 hit_rate | gfu_n | gfd_n | total_score |
|---|---|---|---|---|---|---|
| 3 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 5 | ✅ | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 7 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 10 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |

### ISLAND_MAX_BARS

**說明**：島狀反轉孤島K數上限
**影響**：morning/evening star island reversal

| value | is_current | entry_B1 n_runs | entry_B1 hit_rate | gfu_n | gfd_n | total_score |
|---|---|---|---|---|---|---|
| 5 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 8 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 10 | ✅ | 442 | 0.543 | 4615 | 4682 | **17.4111** |
| 15 |  | 442 | 0.543 | 4615 | 4682 | **17.4111** |

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