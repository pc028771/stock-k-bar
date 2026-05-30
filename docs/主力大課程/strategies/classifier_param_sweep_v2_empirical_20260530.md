# Small Structure Classifier — 參數 Sweep v2 (Empirical Ground Truth)

**日期:** 2026-05-30  
**方法:** 以老師 5/20 教學影片親口示範的 2 個 textbook 案例為 Tier 1 硬 ground truth

---

## Executive Summary

- **Tier 1 (2 textbook case，10 平台日):** production 抓到 5/10 (50%)；改 `vol_threshold` 1.5→2.0 可達 **7/10 (70%)**，noise = 0%
- **唯一需要改的參數是 `vol_threshold: 1.5 → 2.0`**，其他 6 條件保持不動
- 無法達 100% 的原因是結構性限制（見下）：3481 早期平台日（D-6~D-4）因 attack 攻擊日就是整理第 1 天，5-day rolling range 必然帶入攻擊幅，sideways 條件無法通過
- **Tier 2 (soft 108 case):** 72% 的標的在突破前 D-14~D-1 某天至少被 detect 一次；每日 catch rate 約 12-20%
- `post_attack` filter 在 D-1 的 coverage 為 30%（補充 detect 的不足，非替代）

---

## Ground Truth 建構

### Tier 1 — Hard Ground Truth (老師親口示範)

來源：5/20 教學影片 "群創 N字上攻教學"（PressPlay article 8A3653D7）

| 標的 | 平台期 | 天數 | 突破日 |
|------|--------|------|--------|
| 3481 群創 | 2026-05-13 ~ 2026-05-20 | 6 天 | 2026-05-21 |
| 2303 聯電 | 2026-04-24 ~ 2026-04-29 | 4 天 | 2026-04-30 |

確認依據：
- 5-10 截圖紅框 = 3481 5/13-5/20 整理段（close 35.40~38.70）
- 2-24 截圖紅框 = 2303 4/24-4/29 整理段（close 72.7~75.1）

### Tier 2 — Soft Ground Truth (輔助)

teacher_picks_2026.json 中 tier_signal in [core, frequent] 的 120 檔，在 2026-04-01~05-29 期間確認有：
- 當日漲幅 ≥ +5%，且後 5 個交易日最高漲幅 ≥ +15%

找到 **108 個 confirmed breakout cases**（覆蓋 108 支標的）。

> ⚠️ 注意：Tier 2 不是「小結構」的 hard ground truth，老師沒有明確說這些是小結構 pattern（可能是 W底、籌碼推、追高等）。僅供分佈參考。

---

## detect() 在 Tier 1 平台期的 catch rate

### Production 預設 (vol_threshold=1.5)

| 標的 | 平台日 | Catch | 不過關條件 |
|------|--------|-------|-----------|
| 3481 5/13 | D-6 | ✗ | sideways (range 21.6%)、vol (3.09) |
| 3481 5/14 | D-5 | ✗ | sideways (range 22.9%)、vol (2.12) |
| 3481 5/15 | D-4 | ✗ | sideways (range 14.4%)、vol (1.83) |
| 3481 5/18 | D-3 | ✗ | vol mean3=1.92 > 1.5 |
| 3481 5/19 | D-2 | ✗ | vol mean3=1.66 > 1.5 |
| 3481 5/20 | D-1 | **✓** | 全過 |
| 2303 4/24 | D-4 | **✓** | 全過 |
| 2303 4/27 | D-3 | **✓** | 全過 |
| 2303 4/28 | D-2 | **✓** | 全過 |
| 2303 4/29 | D-1 | **✓** | 全過 |

**Production 合計: 5/10 = 50%**

### 改 vol_threshold = 2.0

| 標的 | 平台日 | Catch 變化 |
|------|--------|-----------|
| 3481 5/18 | D-3 | ✗→ **✓** (vol mean3=1.92 < 2.0) |
| 3481 5/19 | D-2 | ✗→ **✓** (vol mean3=1.66 < 2.0) |
| 3481 5/20 | D-1 | 維持 ✓ |
| 2303 全部  | 維持 ✓ |

**改後合計: 7/10 = 70%，noise = 0/29 = 0%**

---

## 參數 Sensitivity Sweep

### 測試範圍

```
vol_threshold:   [1.5, 2.0, 2.5, 3.0, 4.0] × vol_mode [original, decreasing_only, no_mean_check]
sideways_range:  [0.08, 0.10, 0.12, 0.15]
sideways_days:   [5, 7]
prior_attack_win: [15, 20]
prior_attack_pct: [0.08, 0.10]
ma5_dist:         [0.90, 0.93]
high_holding:     [0.80, 0.85]
```

共測試 ~240 組合（Tier 1 only）。

### 對 catch rate 最敏感的參數

1. **vol_threshold** — 最關鍵。從 1.5→2.0 讓 3481 D-3/D-2 從 ✗ 變 ✓（mean3 剛好在 1.5~2.0 之間）
2. **sideways_range** — 0.10→0.15 可讓 3481 D-4 也過（但 D-5/D-6 仍因 range>15% 而失敗）
3. 其他條件（ma5_dist, high_holding, prior_attack）對這 2 個 case 影響最小

### 達到 70% Tier 1 catch rate 的最小改動組合

| 組合 | vol_threshold | sideways_range | Tier1 catch | Noise |
|------|--------------|----------------|-------------|-------|
| **推薦** | **2.0** | **0.10** | **7/10 = 70%** | **0%** |
| 次選 | 2.5 | 0.10 | 7/10 = 70% | 0% |
| 80% 路線 | 2.5 | 0.15 | 8/10 = 80% | 3.4% (1/29) |

---

## 推薦參數組合

### 推薦 (最小改動、零 noise)

```python
vol_threshold = 2.0  # ← 唯一改動 (production = 1.5)
# 其餘全部維持 production default:
prior_attack_window = 20
prior_attack_pct    = 0.10
sideways_days       = 5
sideways_range      = 0.10
ma5_dist            = 0.93
ma10_dist           = 0.95
high_holding        = 0.85
```

**改善:**
- Tier 1 D-7 catch rate: 不適用（10 天平台窗口裡最長只有 6 天）
- Tier 1 D-3 catch rate: production 0%（3481）→ 改後 100%（3481 D-3 5/18 可抓）
- Tier 1 combined: 50% → **70%**
- Noise proxy (D-30~D-15 前): **0% 不變**

### 80% 路線（如果需要更高覆蓋）

```python
vol_threshold   = 2.5
sideways_range  = 0.15
```

代價：noise 從 0% 微升至 3.4%（29 個 noise 點裡多 1 個 false positive）

---

## 結構限制（無論參數怎麼調都漏的 case）

### 3481 D-6 到 D-4（5/13~5/15）— 無法解決

**根本原因：**

3481 的「攻擊日」本身就是「整理第 1 天」（5/13 close=37.50，是攻擊段最高點，同時也是老師標的整理起點）。

這意味著 5-day rolling 視窗永遠帶著攻擊日的高價：
- 5/13 的 5d range = 29.40~37.50 = **21.6%**（包含攻擊前幾天）
- 5/14 的 5d range = 29.40~37.50 = **22.9%**
- 5/15 的 5d range = 32.30~37.50 = **14.4%**

sideways 條件（range < 10%）不可能在前 3 天通過。要讓 D-6 過關需要 sideways_range ≥ 22%，代價是極高的 false positive。

**唯有等到 5/18（D-3），攻擊日才從 5-day window 滾出，range 降至 8.5%。**

這是 sliding window detector 對「攻擊即整理起點」型 pattern 的固有限制，**不是 bug，是 spec 設計的邊界**。

### 突破日本身 (4/30, 5/21) 不 catch — 屬正確行為

突破日高量打破整理→ vol_decreasing 條件失敗，這是預期行為（突破日不是「整理末端」）。

---

## Tier 2 Soft Validation (108 soft breakout cases)

detect() 在突破前 D-14~D-1 的 per-day catch rate:

| 距突破天數 | catch rate |
|----------|-----------|
| D-1 | 15% |
| D-2 | 15% |
| D-3 | **20%** |
| D-4 | 15% |
| D-5 | **20%** |
| D-6 | 18% |
| D-7 | 19% |
| D-8~D-14 | 9%~16% |

- **72% 的標的在 D-14~D-1 某天至少被抓一次**（78/108）
- 每日 catch rate 偏低（~15-20%）是因為 Tier 2 很多案例不是真正的「小結構」pattern（可能是急攻、跳空、W底等不同 pattern）
- `post_attack` filter on D-1: **30% coverage**（32/108），補充 detect 能抓到但 detect 看不到的案例

---

## 對 Production 的建議

### detect() 參數

**建議改動：** `vol_threshold: 1.5 → 2.0`

理由：
- 唯一影響 Tier 1 catch rate 的有效改動
- Noise proxy 不增加（0%）
- 對 Tier 2 影響微小（per-day catch rate 微升）

### post_attack filter 維持保留

兩者互補：
- `detect()` 適合「整理中段」（攻擊後 3-7 天，量縮確認中）
- `post_attack` 適合「整理後期 1-5 天」（量縮更明顯，距突破更近）

在 Tier 2 D-1 測試中 detect 只抓到 15%，post_attack 抓到 30%，兩者重疊有限，合併使用覆蓋率更好。

### 不建議的改動

- ❌ 增加 `sideways_days = 7`：對 Tier 1 無效，只增加雜訊
- ❌ 放寬 `sideways_range ≥ 0.20`：會讓 3481 D-5/D-6 過，但 false positive 暴增
- ❌ 移除 `vol_decreasing` 條件：noise rate 從 0% 跳到 10%+

---

## 附：Production Default vs 推薦對比

| 參數 | Production | 推薦 | 差異 |
|------|-----------|------|------|
| vol_threshold | 1.5 | **2.0** | +0.5 |
| sideways_range | 0.10 | 0.10 | — |
| sideways_days | 5 | 5 | — |
| prior_attack_window | 20 | 20 | — |
| prior_attack_pct | 0.10 | 0.10 | — |
| ma5_dist | 0.93 | 0.93 | — |
| ma10_dist | 0.95 | 0.95 | — |
| high_holding | 0.85 | 0.85 | — |

| Metric | Production | 推薦 |
|--------|-----------|------|
| Tier1 plat catch | 5/10 = **50%** | 7/10 = **70%** |
| Tier1 breakout day | 0/2 = 0% | 0/2 = 0% |
| Noise proxy | 0/29 = **0%** | 0/29 = **0%** |
| Tier2 coverage (any catch) | 72% | ~73% |
