# 箱型／頸線／頭部／底部 標註格式規格

狀態日期：2026-05-11
適用範圍：Phase 3 Task 10。把 PressPlay「K線力量判斷入門」課程裡的箱型、頸線、頭部、底部圖形語意，轉成可在 OHLCV 日K資料上計算、標註與回測的欄位。

## 來源與限制

- 課程圖例：`docs/K線力量判斷入門/images/`
  - `【型態判斷】頭部底部型態合併要點(一)-01..06.jpg`
  - `【型態判斷】頭部底部型態合併要點(二)-01..16.jpg`
  - `【型態判斷】區間整理走勢應有的認知-01..08.jpg`
  - `【型態判斷】築底的應對與實務意義-01..09.jpg`
  - `【突破跌破】假性跌破的實務意義-01..06.jpg`
  - `【突破跌破】整理趨勢進入型態判斷的關鍵-假性跌破之後-01..10.jpg`
- 課程指標摘要：`docs/K線力量判斷入門/strategy-indicators.md`（第 4 節「壓力、賣壓與成本」、第 6 節「型態判斷」、第 10 節「圖例補強後的規則」）

本規格**只使用課程明確教過的概念**：
- 多空力量改變、攻擊、突破、假跌破、假突破、頸線、區間上下緣、量縮、季線方向、解套紓壓、隔日確認。
- **不**新增課程未教的概念（例如：頭肩比例、黃金切割、波浪數、量價背離數值門檻等）。

所有確認都採「收盤確認 + 隔日再確認」的原則（`strategy-indicators.md` L131-133）。

## 通用欄位

所有型態共用的標註欄位（沿用 `strategy-indicators.md` 第 11 節「圖像標註資料表建議」）：

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `case_ticker` | string | 股票代號 |
| `pattern_id` | string | 唯一標註 ID，例如 `box_2330_20241011` |
| `pattern_family` | enum | `box`、`neckline`、`top`、`bottom` |
| `trigger_bar_date` | date | 型態開始日（區間最早被識別出的那一天，或關鍵K線當日） |
| `confirm_bar_date` | date | 收盤確認日；若需隔日再確認，取確認後的那一天 |
| `invalidation_date` | date | 失效日，若仍有效則為 `null` |
| `key_level_type` | enum | `range_high`、`range_low`、`neckline`、`prior_high`、`prior_low` |
| `key_level_price` | float | 該關鍵價位 |
| `expected_direction` | enum | `bullish`、`bearish`、`neutral_box`、`exit_only` |
| `strategy_usage` | enum | `entry`、`exit`、`stop`、`filter`、`watchlist` |
| `notes` | string | 自由欄位 |

---

## 1. 箱型（區間整理）

### 課程定義

- 課程第 6 節：「區間整理要觀察上下緣、量縮、假跌破後收回、突破後是否守住。」
- 圖例 `區間整理走勢應有的認知`：圖中以矩形框出整理區間，並以橘線標出上緣（前高）與下緣（前低）。`-04.jpg`、`-06.jpg` 顯示明顯的橫向矩形區，且伴隨量縮，整理結束會由「收盤突破上緣」或「收盤跌破下緣」決定方向。
- 圖例 `區間整理-04.jpg` 標註「沒量的區間」與「有量的區間」對比，課程強調量縮才算典型箱型整理。
- 圖例 `頭部底部型態合併要點(二)-12.jpg`：跌破頸線後反彈，若反彈進不回頸線，則進入新的下降箱型；若反彈站回頸線，則切換到「箱型模式」（`strategy-indicators.md` L356-358）。

### 觸發條件（trigger）

以「收盤確認」為準，不用盤中。

1. 過去 `N` 個交易日（建議 `N=20`，可調）內出現兩個以上「波段高點」與兩個以上「波段低點」。
   - 波段高點：`high` 為前後各 `k` 根 K 線（建議 `k=3`）的最高。
   - 波段低點：`low` 為前後各 `k` 根 K 線的最低。
2. 區間寬度 `(range_high - range_low) / range_low <= W`（建議 `W=0.15`，由樣本分布調整，並標示為可量化代理）。
3. 區間期間日均量小於前一段（趨勢段）日均量（對應「量縮」）。

### 關鍵欄位

| 欄位 | 計算 |
| --- | --- |
| `range_high` | 過去 `N` 日內最高的「波段高點」 |
| `range_low` | 過去 `N` 日內最低的「波段低點」 |
| `range_width_pct` | `(range_high - range_low) / range_low` |
| `range_duration` | 自第一個波段高/低到目前的交易日數 |
| `range_avg_volume` | 區間內 `volume` 平均 |
| `prior_trend_avg_volume` | 區間形成前 `N` 日的 `volume` 平均，用來判定量縮 |
| `touch_count_high` | `high >= range_high * (1 - tol)` 的根數（建議 `tol=0.005`） |
| `touch_count_low` | `low <= range_low * (1 + tol)` 的根數 |

### 確認條件（pattern 成立）

箱型本身是「整理中」的型態，視為已成立的條件：
- `touch_count_high >= 2 且 touch_count_low >= 2`
- `range_duration >= D_min`（建議 `D_min=10`）
- `range_avg_volume < prior_trend_avg_volume`

### 方向確認（箱型結束）

- 向上突破：`close > range_high`（突破當日收盤），且隔日收盤 `close_{t+1} >= range_high`（隔日不跌回）→ `box_breakout_to_bull`
- 向下跌破：`close < range_low`，且隔日收盤 `close_{t+1} <= range_low` → `box_breakdown_to_bear`
- 假跌破收回：`low < range_low` 且 `close >= range_low`（同日收回），對應 `strategy-indicators.md` L140 `false_breakdown_reclaim`
- 假突破失敗：`high > range_high` 且 `close < range_high`，對應 L141 `false_breakout_fail`

### 失效條件

- `range_duration > D_max`（建議 `D_max=120`）且無方向確認 → 標記為 `expired`
- 突破/跌破確認後，型態狀態改為 `closed`，並可衍生為「攻擊」或「頭部/底部」型態（見 §3、§4）

### 可量化代理（直接用 OHLCV 日K計算）

```
swing_high(i) = high(i) where high(i) == max(high[i-k:i+k+1])
swing_low(i)  = low(i)  where low(i)  == min(low[i-k:i+k+1])

range_high = max(swing_high in lookback_N)
range_low  = min(swing_low  in lookback_N)

box_breakout_confirm   = close(t) > range_high and close(t+1) >= range_high
box_breakdown_confirm  = close(t) < range_low  and close(t+1) <= range_low
false_breakdown_reclaim = low(t)  < range_low  and close(t)  >= range_low
false_breakout_fail     = high(t) > range_high and close(t)  <  range_high
```

---

## 2. 頸線

### 課程定義

- 課程第 6 節 + 第 10 節：頸線是「跌破後又站回」用來判斷型態切換的關鍵價位（`strategy-indicators.md` L294-302、L356-379）。
- 圖例 `整理趨勢進入型態判斷的關鍵-假性跌破之後-06.jpg`：明確以「頸線跌破」與「季線下彎」兩個標籤同時標出，頸線為前一波段低點延伸出的水平線。
- 課程強調：「正常多空易位是跌破頸線後轉空，若反彈回頸線但無法站回，反彈是離場機會而不是支撐成立。」
- 課程 L371：`neckline = prior_low_before_ma60_rollover`。

### 觸發條件

1. 識別 `ma60_rollover` 點：`ma60` 由上升轉為下降的第一根 K 線，定義為 `ma60_slope(t) < 0 and ma60_slope(t-1) >= 0`（`ma60_slope = ma60 / ma60.shift(5) - 1`，視窗 5 日可調）。
2. 頸線價位 `neckline_price = swing_low` 取於 `ma60_rollover` 之前最近的一個 `swing_low`。
3. 出現「收盤跌破頸線」：`close(t) < neckline_price` → `neckline_break` 觸發。

對應的多頭頸線（底部反轉用）：以 `ma60` 由下降轉上升前最近的 `swing_high` 為頸線，`close > neckline` 觸發。

### 關鍵欄位

| 欄位 | 計算 |
| --- | --- |
| `neckline_price` | 上述定義 |
| `neckline_break_date` | 收盤跌破當日 |
| `ma60_direction_at_break` | `down`、`up`、`flat`（`abs(slope) < eps`） |
| `retest_high_after_break` | 跌破後 `M` 日內（建議 `M=10`）的最高 `high` |
| `retest_close_after_break` | 同期間最高 `close` |

### 確認條件

- 真正跌破（`real_breakdown`）：
  - `close(t) < neckline_price`
  - `close(t+1) < neckline_price`（隔日確認）
  - 之後 `M` 日內 `retest_close_after_break <= neckline_price`（反彈站不回）
- 對應 `strategy-indicators.md` L310：`real_breakdown = close < key_level and close_next < key_level and rebound_high_next_m <= key_level`

### 失效條件（變成假跌破）

- `low < neckline_price` 且當日 `close >= neckline_price` → `false_breakdown_reclaim`
- 跌破後 `M` 日內 `close > neckline_price` → `neckline_reclaim`，型態切換為「箱型模式」（`box_mode_after_neckline_reclaim`，L373）
- 若反彈進到頸線但收黑（`high >= neckline_price and close < open and close < neckline_price`），標記 `neckline_retest_fail`（L379），仍維持 `real_breakdown` 預期方向。

### 可量化代理

```
ma60       = close.rolling(60).mean()
ma60_slope = ma60 / ma60.shift(5) - 1
ma60_rollover_down = ma60_slope(t) < 0 and ma60_slope(t-1) >= 0

neckline_price        = last_swing_low_before(ma60_rollover_down_date)
neckline_break        = close(t) < neckline_price
neckline_break_confirm = close(t+1) < neckline_price
neckline_reclaim      = (close in (t, t+M]) > neckline_price
neckline_retest_fail  = high(t) >= neckline_price and close(t) < open(t) and close(t) < neckline_price
```

---

## 3. 頭部型態

### 課程定義

- 課程第 6 節 L127：「頭部與底部不可只看形狀，要看多空力量是否改變。」
- 圖例 `頭部底部型態合併要點(二)-04.jpg`、`-08.jpg`：頭部不是單純的雙頂或頭肩，而是「拉抬到前高 → 出現停滯／無法續攻 → 跌破前一個波段低（頸線）→ 季線轉下彎」的組合。
- 對應 `strategy-indicators.md` L356-358：頭部成立必須結合**頸線跌破** + **季線方向** + **反彈站不回頸線**。

### 觸發條件

1. 前段為攻擊或上升趨勢：`close > ma60` 維持至少 `T_up` 日（建議 `T_up=40`）。
2. 出現「攻擊力量消失」訊號之一（沿用課程已定義條件）：
   - `breakout_k_low_violation`（`strategy-indicators.md` L88）：跌破突破K低點。
   - `failed_breakout`（L92）：突破後 5 日內收盤跌回突破前的關鍵價。
   - `upper_shadow_at_new_high` + 隔日收黑（L41、L255）。
3. 接著出現 `neckline_break_confirm`（§2）。

### 關鍵欄位

| 欄位 | 計算 |
| --- | --- |
| `head_peak_price` | 頭部期間最高 `high` |
| `head_peak_date` | 上述日期 |
| `neckline_price` | 同 §2 |
| `attack_fail_signal` | 觸發頭部的攻擊失敗訊號類型 |
| `ma60_direction_at_confirm` | `down`／`flat` |

### 確認條件

頭部 `confirmed` 需要全部滿足：
1. `neckline_break_confirm == true`
2. `ma60_direction_at_confirm in {down, flat}`
3. 跌破後 `M` 日內 `retest_close_after_break <= neckline_price`（反彈站不回）

### 失效條件

- `neckline_reclaim` 在 `M` 日內成立 → 改標為 `box_mode_after_neckline_reclaim`，頭部標記為 `invalidated`。
- 跌破後 `M` 日內出現 `close > head_peak_price` → 直接視為頭部失效並回到上升趨勢。

### 可量化代理

```
prior_uptrend       = (close > ma60).rolling(T_up).sum() >= T_up * 0.8
attack_fail         = breakout_k_low_violation or failed_breakout or
                      (upper_shadow_at_new_high and next_black_k)
top_confirmed       = prior_uptrend and attack_fail and
                      neckline_break_confirm and
                      ma60_direction_at_confirm in {down, flat} and
                      retest_close_after_break <= neckline_price
top_invalidated     = neckline_reclaim or close > head_peak_price (within M days)
```

---

## 4. 底部型態

### 課程定義

- 圖例 `築底的應對與實務意義-03.jpg`（「拉回佈局 → 解套紓壓」示意圖）：底部不是一次反彈完成，而是經過多次測試低點、量縮、再「攻擊」突破上方頸線（前波段高）。
- 課程 L128：「築底不是看到下影線或低檔整理就成立，需要確認攻擊或趨勢改變。」
- 課程 L189 `H5`：「假跌破後快速收回區間，後續突破成功率高於一般區間整理。」
- 課程 L294-302：底部常見前置是「急跌後假跌破收回」。

### 觸發條件

1. 前段為下降趨勢：`close < ma60` 維持至少 `T_down` 日（建議 `T_down=40`）。
2. 出現「假跌破收回」(`false_breakdown_reclaim`) 或「急跌後假跌破」(`false_breakdown_after_panic`，L306-309)。
3. 之後形成箱型整理（§1 條件成立）且 `range_avg_volume < prior_trend_avg_volume`（量縮）。

### 關鍵欄位

| 欄位 | 計算 |
| --- | --- |
| `bottom_trough_price` | 底部期間最低 `low` |
| `bottom_trough_date` | 上述日期 |
| `bottom_neckline_price` | 底部箱型上緣 `range_high` |
| `false_breakdown_count` | 期間 `false_breakdown_reclaim` 出現次數 |
| `ma60_direction_at_confirm` | `up`／`flat` |

### 確認條件

底部 `confirmed` 需要全部滿足：
1. 至少一次 `false_breakdown_reclaim` 或 `panic_break_reclaim`。
2. 收盤突破頸線：`close(t) > bottom_neckline_price` 且 `close(t+1) >= bottom_neckline_price`。
3. 突破日量能 > `range_avg_volume`（對應「攻擊」需要量；沿用 `strategy-indicators.md` L86 `breakout_volume_ratio`）。
4. `ma60_direction_at_confirm in {up, flat}` 或在 `M` 日內轉為 `up`。

### 失效條件

- 突破頸線後 `M` 日內 `close < bottom_neckline_price` → `failed_breakout`（L92），底部標記 `invalidated`，回到箱型或下降。
- 突破後若出現 `close < bottom_trough_price` → 直接視為底部失效（破前低）。

### 可量化代理

```
prior_downtrend         = (close < ma60).rolling(T_down).sum() >= T_down * 0.8
bottom_setup            = prior_downtrend and
                          (false_breakdown_reclaim or panic_break_reclaim) and
                          box_pattern_active and
                          range_avg_volume < prior_trend_avg_volume
bottom_confirmed        = bottom_setup and
                          close(t) > bottom_neckline_price and
                          close(t+1) >= bottom_neckline_price and
                          volume(t) / range_avg_volume >= V_ratio_min and
                          ma60_direction_at_confirm in {up, flat}
bottom_invalidated      = (close < bottom_neckline_price within M days) or
                          (close < bottom_trough_price)
```

---

## 5. 型態狀態機

四個型態之間的切換（對應 `strategy-indicators.md` L356-379）：

```
                +-------------------+
                |   trend (up/down) |
                +---------+---------+
                          | attack_fail or
                          | false_breakdown_reclaim
                          v
                +-------------------+
                |        box        |
                +---------+---------+
       neckline_break    |      box_breakout_to_bull
       confirm           |      box_breakdown_to_bear
            +------------+------------+
            v                         v
     +-------------+            +-------------+
     |    top      |            |   bottom    |
     +-------------+            +-------------+
            |  neckline_reclaim         |  failed_breakout
            +------> box <---------------+
```

每次狀態切換需要寫入一筆 `pattern` 紀錄；同一檔股票可以同時存在多個未失效的標註（例如 `box` 與其衍生的 `top` 候選），但只能有一個 `confirmed` 狀態。

---

## 6. 輸出資料表建議

建議以 CSV 或 SQLite 表 `patterns` 儲存，欄位：

```
pattern_id, case_ticker, pattern_family, status,
trigger_bar_date, confirm_bar_date, invalidation_date,
range_high, range_low, range_width_pct, range_duration,
neckline_price, ma60_direction_at_confirm,
head_peak_price, bottom_trough_price,
false_breakdown_count, attack_fail_signal,
volume_ratio_at_confirm,
expected_direction, strategy_usage, notes
```

`status` enum：`candidate`、`confirmed`、`invalidated`、`expired`、`closed`。

## 7. 後續任務銜接

- Task 11（真正跌破 vs 假跌破）：直接讀 `patterns` 表中 `pattern_family in {neckline, top, bottom}` 與 `false_breakdown_count`、`ma60_direction_at_confirm`、`retest_close_after_break` 欄位。
- Task 12（壓力區、套牢區）：將 `range_high`、`neckline_price`、`head_peak_price` 作為「上方壓力候選」，與 volume profile 對比，驗證 `strategy-indicators.md` 第 4 節 `overhead_supply_volume`、`supply_vacuum_zone` 等代理。
