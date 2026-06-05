# STUB Fix Batch — 2026-06-05

依 `stub_resolution_2026-06-05.md` Opus 報告，完成 4 個課程對齊修改。

## 修改摘要

### Fix 1 ✓ — MERGED_DOJI_CARRY_DAYS: 5 → 1

**檔案：** `scripts/kline/course_proxy_constants.py`、`scripts/kline/features.py`

**課程依據：**
- §24「明天的重點就得要攻擊，且這是一定要發生的，無法變成後天、大後天」
- §26「明日就得開始攻擊，或者如果不打算攻擊，跌破合併十字線的低點作為確認不攻擊。」

**影響：** `merged_high`/`merged_low` 只在觸發隔日有值，之後即為 NaN。
- Fire rate: 1.63% → 0.56%（約 1/3）
- 這是正確的：課程明示只看「明日」，5 天 forward-fill 嚴重違反課程精神。

---

### Fix 2 ✓ — ATTACK_COST_FIRST_BREAKOUT_LOOKBACK_DAYS: 20 → 60

**檔案：** `scripts/kline/course_proxy_constants.py`

**課程依據：**
- 行進ing §39「突破新高價的當天，前面要有兩個半月到三個月的整理區間」
- 明日 K 線 §20「整理期間超過三個月」

**影響：** 攻擊成本顯現日的狀態機抑制窗口拉長，3693 連續漲停段 FP 抑制更穩。
- Attack cost notna: 1.43% → 4.13%（因 forward-fill 時間更長）
- 3693 2023-04-11：確認此案例在 60 日窗口內（距 2023-01-16 只有 48 個交易日），正確被抑制。

---

### Fix 3 ✓ — AT_PRESSURE_RETEST_PCT 廢棄，改用二元觸及判斷

**檔案：** `scripts/kline/course_proxy_constants.py`、`scripts/kline/features.py`、`scripts/kline/scenarios/lights/pressure_layer_no_support.yaml`

**課程依據：**
- §08「股價第二次又來到 170 元附近，倘若對於壓力有正確的體認，應該就可以推演出來，隔天要確認是攻擊，必須就是一開盤開在 176.5 元以上的跳空攻擊...」
- 老師只談「碰到」（觸及）vs「越過」（突破），用具體價位而非 % 距離。

**新條件：** `high >= prior_high_60 AND close < prior_high_60`

**影響：**
- Fire rate: 54.59% → 1.99%（大幅降低，舊版含大量「接近但未觸」FP）
- YAML course_citation 補老師原話。

---

### Fix 4 ✓ — LOW_PRICE_THRESHOLD 從 course_proxy_constants.py 搬至 extras/low_price.py

**檔案：**
- 新建：`scripts/kline/extras/low_price.py`（含 `LOW_PRICE_THRESHOLD = 30.0` [EXTRAS]）
- 移除：`scripts/kline/course_proxy_constants.py` 中的 `LOW_PRICE_THRESHOLD`
- 更新：`scripts/kline/features.py` 改從 extras 匯入
- 更新：`scripts/kline/scenarios/lights/lowprice_first_pull_exit.yaml` 加 [EXTRAS] 標籤

**課程依據（為何移出）：**
- §09 只用「低/中/高」相對描述，課程未明示任何價格門檻數字。
- 30 元是業界 proxy，屬課程外條件，必須物理隔離。

**影響：**
- low_price_flag fire rate 不變（36.27%）— 計算邏輯相同，只移動了常數來源
- YAML 加 [EXTRAS] 標記，user 看到此 light 時知道含課程外條件

---

## Fire Rate 對比表

| Feature | 改前 | 改後 | 預期範圍 |
|---|---|---|---|
| `merged_high` notna | 1.63% | 0.56% | 低（只隔日有效） |
| `attack_cost` notna | 1.43% | 4.13% | 較高（60 日 fill） |
| `at_pressure_retest` | 54.59% | 1.99% | ~5-15%（課程二元觸及） |
| `low_price_flag` | 36.27% | 36.27% | 不變（常數值同） |

樣本：50 隻股票 × 2024-01-01 起，共 24,893 rows。

---

## pytest 結果

```
582 passed in 33.77s
```

全綠。包含原本就 timing-flaky 的 `test_100_days_5_tickers_under_5s`（本次跑通）。

---

## 建議

### 是否需要重跑 Phase 4.3？

**是，建議重跑 calibration。**

原因：
1. `at_pressure_retest` fire rate 從 ~55% 降至 ~2%，會直接影響 `pressure_layer_no_support` light 的 calibration 結論。
2. `merged_high`/`merged_low` carry 縮短（5→1 天），凡依賴合併十字線 breakout 信號的 light 命中率都會改變。

`attack_cost` 和 `low_price_flag` 影響相對小（前者 forward-fill 更長、後者常數值不變）。

### 後續項目

- `AT_PRESSURE_RETEST_PCT` 常數區塊在 `course_proxy_constants.py` 已改為純說明性 comment（不可 import），保留作 audit 紀錄。
- `LOW_PRICE_THRESHOLD` 在主 constants 保留說明性 comment 指向 extras。
- MERGED_DOJI_BODY_RATIO / MERGED_DOJI_SHADOW_MIN_RATIO 仍為 STUB（課程無數字），待後續處理。

---

**報告檔：** `/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/docs/kline_course/notes/stub_fix_batch_2026-06-05.md`
