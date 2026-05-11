# 真正跌破 vs 假跌破：定義重設與對比報告

狀態日期：2026-05-11

Phase 3 Task 11 產出物。

資料庫：`/Users/howard/.four_seasons/data.sqlite`

樣本：2025-01-02 至 2026-05-08

---

## 1. 問題背景

原版 `real_breakdown_after_range` 的量化代理（條件：非急跌 + 黑K + 收盤跌破60日前低 + 振幅 >= 2.5%）在 `kline_course_backtest.md` 回測中**不支持**課程預期的弱勢結果：10 日 close-basis 平均為正，勝率超過 50%，代理過於粗糙。

根據 `pattern_labeling_spec.md` Task 10 規格，本次重新設計代理條件。

---

## 2. 新舊定義對比

### 舊版（`real_breakdown_after_range_old`）

課程語意：「整理後長黑跌破偏真正轉弱」

量化代理：
```
real_breakdown_after_range_old =
    ~panic_drop          # 無急跌（5日跌幅 < 7%）
    and black_k          # 黑K
    and close < prior_low_60     # 收盤跌破 60 日前低
    and range_pct >= 0.025       # 振幅 >= 2.5%（長黑代理）
```

**問題**：
- `prior_low_60` 是過去 60 日的最低點，不等於課程說的「頸線」（整理區間下緣）
- 未確認前段是否處於箱型整理（可能在急跌段就觸發）
- 無隔日確認（課程明確要求收盤確認 + 隔日再確認）
- 未要求季線方向（課程強調季線下彎是頭部確認的必要條件）

### 新版（`real_breakdown_after_range`）

根據 `pattern_labeling_spec.md` §2「頸線確認條件」與 `strategy-indicators.md` L310：

```
real_breakdown = close < neckline_price
              and close(t+1) < neckline_price         # 隔日確認
              and rebound_high_next_m <= neckline_price  # 反彈站不回（可量化代理：隔日收盤）
```

量化代理（只用 OHLCV 日K）：

```
# 箱型整理代理：過去 20 日高低差 <= 15%
in_range_20 = (prior_high_20 - prior_low_20) / prior_low_20 <= 0.15

# 頸線代理：20 日前低（區間下緣，最近整理低點）
neckline_proxy = prior_low_20

# 季線斜率（5日視窗）
ma60_slope = ma60 / ma60.shift(5) - 1
ma60_down = ma60_slope < 0

real_breakdown_after_range =
    ~panic_drop                         # 非急跌情境
    and black_k                          # 黑K
    and body_pct >= 0.015               # 長黑（實體 >= 1.5%）
    and close < neckline_proxy          # 收盤跌破頸線代理
    and next_close < neckline_proxy     # 隔日確認跌破
    and in_range_20                     # 前段箱型整理
    and ma60_down                       # 季線下彎
```

**對應課程概念**（來源：`strategy-indicators.md` L310、`pattern_labeling_spec.md` §2）：

| 新版條件 | 對應課程概念 |
| --- | --- |
| `in_range_20` | 箱型整理存在（§1 觸發條件） |
| `close < neckline_proxy` | 頸線跌破（§2 L124 `neckline_break`） |
| `next_close < neckline_proxy` | 隔日確認（§2 L144 `neckline_break_confirm`） |
| `ma60_down` | 季線下彎（§2 L134 `ma60_direction_at_break = down`） |
| `body_pct >= 0.015` | 長黑K（課程強調整理後長黑跌破） |
| `~panic_drop` | 排除假跌破的急跌情境 |

---

## 3. 回測結果

### 3.1 做多方向（隔日開盤進場，固定持有）

| 訊號 | n | 5日均報酬% | 5日勝率% | 10日均報酬% | 10日勝率% | 20日均報酬% | 20日勝率% | 10日close-basis均% | 10日close-basis勝率% |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `false_breakdown_reclaim` | 1359 | 1.047 | 54.30 | 1.690 | 56.07 | 4.148 | 59.01 | 2.541 | 59.16 |
| `real_breakdown_after_range_old`（舊版） | 3297 | 0.445 | 49.65 | 1.023 | 51.68 | 1.298 | 47.89 | 1.486 | 54.17 |
| `real_breakdown_after_range`（新版） | 2809 | **-0.240** | **42.76** | **0.110** | **45.64** | **0.075** | **42.54** | 0.218 | 46.89 |

> 報酬計算：訊號日收盤後成立，隔日開盤進場，第 5/10/20 交易日收盤出場。未扣除交易成本。

### 3.2 做空方向（取反：新版 `real_breakdown_after_range` 做空）

| 持有期 | 做空平均報酬%（= 負的做多均值） | 做空中位報酬%（= 負的做多中位） | 空方勝率%（= 100% - 做多勝率） |
| --- | --- | --- | --- |
| 5日 | +0.240 | +0.388 | 57.24 |
| 10日 | -0.110 | +0.329 | 54.36 |
| 20日 | -0.075 | +1.015 | 57.46 |

> **中位數報酬**更能反映分布集中趨勢（排除少數極端值干擾）：
> - 5日 median 做多 -0.388%（做空 +0.388%）
> - 10日 median 做多 -0.329%（做空 +0.329%）
> - 20日 median 做多 -1.015%（做空 +1.015%）

### 3.3 方向對比：假跌破（做多）vs 真正跌破（做空）

| 策略 | 方向 | 10日平均報酬% | 10日勝率% | 20日平均報酬% | 20日勝率% |
| --- | --- | --- | --- | --- | --- |
| `false_breakdown_reclaim` | 做多（反彈） | +1.690 | 56.07 | +4.148 | 59.01 |
| `real_breakdown_after_range`（新版） | 做空（看空） | 做空 -0.110（均值） | 54.36 | 做空 -0.075（均值） | 57.46 |
| `real_breakdown_after_range`（新版） | 做空（看空） | **做空中位 +0.329** | — | **做空中位 +1.015** | — |

---

## 4. 結論

### 4.1 新版代理是否更符合課程預期？

**部分符合，但有重要限制。**

新版 `real_breakdown_after_range` 在做多方向的勝率明顯低於舊版（42.76% vs 51.68%，10日），且 5日均報酬轉負（-0.240%）。這代表加入箱型整理、季線下彎、隔日確認三個條件後，篩出的樣本的確更偏弱勢。

**做空方向的中位數報酬為正**（5日 +0.388%、10日 +0.329%、20日 +1.015%），代表新版對應的股票整體有向下的傾向，與課程「真正跌破後反彈站不回、持續走弱」的敘述方向一致。

然而，做空方向的**平均報酬**在 10 日和 20 日仍接近零（-0.110%、-0.075%），代表：
1. 新版條件未到「顯著空方優勢」的水準，不適合直接作為做空策略。
2. 部分樣本（特別是 2025 上半年熊市）可能拉高空方績效，分布偏斜嚴重。

### 4.2 方向對比是否符合課程預期？

**假跌破（做多）vs 真正跌破（做空）方向相反，符合課程邏輯。**

- 假跌破：10日 +1.69%，勝率 56%（做多有邊際）
- 真正跌破：10日 median 空方 +0.329%，勝率 54%（做空方向中位數有邊際）

課程強調「同一關鍵位跌破後若快速收回是假跌破（多方）；若整理後長黑跌破且站不回是真正轉空（空方）」，新舊兩訊號的方向對比與此描述一致。

### 4.3 代理的主要局限

1. **`in_range_20` 為粗糙代理**：只用 20 日高低差 <= 15% 判斷箱型，未嚴格計算 `touch_count_high >= 2` 與 `touch_count_low >= 2`（`pattern_labeling_spec.md` §1 觸發條件）。
2. **`prior_low_20` 非嚴格頸線**：課程的頸線是 `ma60_rollover` 前的 `swing_low`，此處用 20 日前低替代，可能混入一般波動的低點。
3. **`next_close` 代理「反彈站不回」**：課程定義是 M 日內 `retest_close_after_break <= neckline_price`，此處只用隔日確認，時間視窗過短。
4. **樣本期間偏空**：2025 年 3-8 月為台股大回調期間，任何做空訊號都可能受市場 regime 放大，應加入 regime 分組驗證（後續 Task）。

---

## 5. 後續建議

1. **加入 regime 分組**：分開檢查 bull / bear / range 三種市場環境下，新版真正跌破的做空表現是否集中在 bear 環境。
2. **嚴格實作箱型代理**：加入 `swing_high`/`swing_low` 計算與 `touch_count` 條件，縮小樣本量但提升精準度。
3. **加入反彈視窗確認**：改用 M=5 日內最高 close 是否站回頸線作為最終確認，而非只用隔日收盤。
4. **Task 12 接續**：箱型上緣（`range_high`）、頸線（`neckline_proxy`）可作為做空後的壓力反彈目標區，結合 volume profile 評估出場時機。
