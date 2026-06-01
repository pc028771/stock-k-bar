# DB 缺失資料清單 — `standard_daily_bar`

> 生成日期：2026-05-22
> 用途：給 DB 寫入腳本參考；backtest 暫不寫 DB
> 影響：strict filter 結論不可信（filter 變成「有資料」filter 而非「品質」filter）

---

## 一、全欄位 NULL 統計（671,108 rows total）

| 欄位 | 非 NULL 數 | 覆蓋率 | 影響評估 |
|---|---|---|---|
| close | 671,108 | 100.0% | ✅ 完整 |
| ma5 | 663,615 | 98.9% | ✅ 可用 |
| ma10 | 654,259 | 97.5% | ✅ 可用 |
| ma20 | 635,549 | 94.7% | ✅ 可用 |
| ma60 | 560,752 | 83.6% | 🟡 可用但有缺 |
| **ma240** | **224,622** | **33.5%** | 🔴 **大量缺失** |
| ma20_slope | 614,288 | 91.5% | ✅ |
| bb_upper_slope | 425,970 | 63.5% | 🟡 |
| **bb_lower_slope** | **0** | **0.0%** | 🔴 **完全缺失**（已知，classifier 已 workaround）|
| bb_position | 435,393 | 64.9% | 🟡 |
| bb_width_pct | 435,340 | 64.9% | 🟡 |
| vol_ratio_20 | 635,536 | 94.7% | ✅ |
| **dev_ma240_pct** | **24,916** | **3.7%** | 🔴 **幾乎全缺**（可由 close/ma240 計算）|
| main_force_1d | 455,854 | 67.9% | 🟡 |
| main_force_5d | 453,376 | 67.6% | 🟡 |
| main_force_10d | 450,915 | 67.2% | 🟡 |
| **main_force_20d** | **444,867** | **66.3%** | 🟡 部分缺失 |

---

## 二、按月份缺失分布（2025-01 ~ 2026-05）

### `dev_ma240_pct` — 致命缺失

| 月份 | total | 有值率 | 狀態 |
|---|---|---|---|
| 2025-01~11 | ~410,000 | **0.0%** | ❌ 完全缺失 |
| 2025-12 | 41,104 | 17.8% | ⚠️ 部分 |
| 2026-01 | 45,192 | 37.0% | ⚠️ 部分 |
| 2026-02 | 27,609 | **0.7%** | ❌ 又消失 |
| 2026-03 | 50,608 | **0.7%** | ❌ |
| 2026-04 | 46,139 | **0.6%** | ❌ |
| 2026-05 | 30,045 | **0.3%** | ❌ |

→ **整個 17 個月實質可用 ≈ 0**

### `ma240` — 大部分缺失但 2026 後恢復

| 月份 | 有值率 |
|---|---|
| 2025-01~11 | **0.0%** ❌ |
| 2025-12 | 17.8% ⚠️ |
| 2026-01 | 99.6% ✅ |
| 2026-02~04 | 100% ✅ |
| 2026-05 | 98.5% ✅ |

→ **2026-01 後 ma240 已 ok，但 dev_240 沒被計算回填**

### `main_force_20d` — 2026 後消失

| 月份 | 有值率 |
|---|---|
| 2025-01~12 | 87.9% ~ 97.2% ✅ |
| 2026-01 | 36.5% ⚠️ |
| 2026-02~05 | **0.1% ~ 0.6%** ❌ |

→ **2026 開始整個欄位停止更新**

### `bb_upper_slope` / `bb_position` / `bb_width_pct`
- 全期間 ~64% 覆蓋率
- 沒有按月份明確斷點，可能跟 standard_daily_bar 計算腳本針對特定 ticker 沒跑有關

---

## 三、必須回填清單（按優先序）

### P0 — backtest 立刻需要

1. **`dev_ma240_pct`**（公式：`(close - ma240) / ma240 * 100`）
   - 補哪些列：所有 `ma240 is not null AND dev_ma240_pct is null` 的列
   - 預估補入數：~199,706 列（ma240 有值 224,622 - dev_240 有值 24,916）
   - 這個直接由 close 跟 ma240 算就好，**不需外部來源**

2. **`main_force_20d`**（外資+投信+自營 20 日累積買賣超 - 或對應計算）
   - 補哪些列：2026-01 後缺失（~150,000 列）
   - 需確認原始來源跟計算邏輯，可能要重跑 ETL

### P1 — classifier 已用 workaround，但回填會更乾淨

3. **`bb_lower_slope`**（0% 覆蓋，全表都缺）
   - 公式：`(bb_lower_今 - bb_lower_5天前) / bb_lower_5天前 * 100`
   - 已知 classifier 自己重算過（commit 3fc6a77）

### P2 — 較長期回填

4. **`ma240`** 2025-01~11 缺失
   - 需要 2024-01 之前的 close 才能算 240MA
   - 如果 DB 沒回溯到 2024，這段 ma240 無法計算

5. **`bb_upper_slope` / `bb_position` / `bb_width_pct`** ~36% 缺失
   - 看哪些 ticker / 日期完全沒值，確認原因

---

## 四、Backtest 因應做法（不寫 DB，read-only 解法）

在 `four_seasons_backtest.py` 的 `load_panel()` SQL 加上 inline computation：

```sql
SELECT ticker, trade_date, close, ma20, ma240,
       COALESCE(dev_ma240_pct,
                CASE WHEN ma240 > 0 THEN (close - ma240) / ma240 * 100 END)
         AS dev_ma240_pct,
       main_force_20d,
       volume, vol_ratio_20
FROM standard_daily_bar WHERE is_usable=1
```

對 `main_force_20d` 暫時無法補（除非從其他原始 table 算）→ 缺失列就放棄做 filter（或先不用這條 filter）。

---

## 五、Strict filter 結論的修正

之前報告 strict (dev≤10 + mf20≥1M) 「3 筆 100% win」是基於極小有效樣本：
- 2026-01-06 ~ 2026-01-14 共 9 天
- 是 dev_240 + mf20 都有值的唯一窗口

**真正結論需 dev_240 補齊後重跑**，PARAM_TUNING_LOG.md 結論暫不採用。
