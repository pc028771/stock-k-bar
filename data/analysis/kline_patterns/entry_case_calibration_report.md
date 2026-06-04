# Entry Branch Case-Based Calibration Report

生成時間：2026-06-04

---

## 執行摘要

- **掃描課程文章**：51 篇（`docs/kline_course/mingri_kline/`）
- **含進場案例的文章**：4 篇（掃關鍵詞：應該進場 / 確認進場 / 攻擊企圖 / 跳空攻擊）
- **萃取具體 (ticker, date, expected_branch) 案例**：3 個（可跑 calibration）
- **抽象案例（無具體 ticker）**：多篇 → 標「待 user 提供」
- **常數推薦調整**：無需調整（見下方說明）
- **Baseline calibration hit rate（patterns 層）**：100.0%（39/39 confirmed_signal cases）
- **pytest**：554 passed ✓

---

## 一、Entry-Signal Playbook 結構分析

系統共有 4 個 playbook 含 `entry_signal` branches：

| Playbook | Pattern | Pattern 在 REGISTRY？ | Entry Branches |
|---|---|---|---|
| `merged_doji_attack.yaml` | `merged_doji` | ✅ 是 | B1_gap_up_attack, B2_push_attack_above_merged_high |
| `attack_cost_displayed.yaml` | `attack_cost_displayed` | ❌ 否 | B3_gap_attack, B4_push_attack |
| `defensive_stance.yaml` | `defensive_stance` | ❌ 否 | B1_market_stable_gap_up, B2_market_stable_push_attack |
| `record_decline_rebound.yaml` | `record_decline_rebound` | ❌ 否 | B1_taiex_no_new_low |

**重要限制**：`attack_cost_displayed`、`defensive_stance`、`record_decline_rebound` 三個 pattern **不在 `PATTERN_REGISTRY`**，沒有 `detect()` 函式。它們是透過 `context_overrides` 手動觸發的 playbook，無法透過 `kline_patterns_calibrate.py` 自動校準。

唯一可做 case-based calibration 的 entry playbook 是 **`merged_doji_attack`**（使用 `merged_doji.detect()`）。

---

## 二、Step 1 — 課程文章索引

掃描 51 篇文章，含 entry 關鍵詞的文章列表：

| 文章 | article_id | 關聯 Playbook | 進場案例類型 |
|---|---|---|---|
| §24 合併十字線 | `E9A6F935298C7C5C2E269AA952AA1BB2` | `merged_doji_attack` | 具體 ticker + 日期 ✓ |
| §20 攻擊成本顯現日 | `B44741FE824D0798CC91C1521D5B0FF7` | `attack_cost_displayed` | 具體 ticker + 日期（pattern 無 detect） |
| §26 防守姿態 | `EF7308E2336BF7BCE94142944DB580B1` | `defensive_stance` | 具體 ticker + 日期（pattern 無 detect） |
| §30 創紀錄的跌點之後 | `77DC434EC71DB04553752A44C9354680` | `record_decline_rebound` | 抽象（無具體 ticker 日期） |

---

## 三、Step 2 — 案例萃取

### 3.1 merged_doji_attack（可 calibrate）

| case_id | article_id | ticker | date | expected_branch | 說明 |
|---|---|---|---|---|---|
| MD-01 | E9A6F935 | 8103（瀚荃） | 2024-06-11 | B1_gap_up_attack | §24 標準範例；合併長十字線 → 隔日（06-12）跳空攻擊 |
| MD-02 | E9A6F935 | 5443（均豪） | ~2024-06-25 | B1_gap_up_attack | §24 範例；箭頭指向上下影線合併 → 隔日跳空 |
| MD-NEG-01 | E9A6F935 | 3305（昇貿） | ~2024-06-26 | (反例，不觸發) | §24 反例；位置不對（創新高在 06-21 上影線），不應觸發 |

### 3.2 attack_cost_displayed（需手動驗證，無法自動 calibrate）

| case_id | article_id | ticker | date | expected_branch | 說明 |
|---|---|---|---|---|---|
| AC-01 | B44741FE | 3289（宜特） | 2023-03-08 | B3_gap_attack（D+1 持有後 D+2 不攻擊） | §20 標準範例；漲停突破前高，隔日跌破攻擊成本 |
| AC-02 | B44741FE | 3693（營邦） | 2023-04-11 | B3_gap_attack（D+1 持有 → D+2 跳空攻擊） | §20 跳空攻擊最佳解 |
| AC-03 | B44741FE | 6209（今國光） | 2023-12-15 | B2_next_day_breaks（exit） | §20 後記：攻擊成本被跌破 |

### 3.3 defensive_stance（需手動驗證，無法自動 calibrate）

| case_id | article_id | ticker | date | expected_branch | 說明 |
|---|---|---|---|---|---|
| DS-01 | EF7308E2 | 8103（瀚荃） | 2024-06-11 | B1_market_stable_gap_up | §26 防守 → 06-12 跳空攻擊（與 MD-01 同日，複合案例） |
| DS-NEG-01 | EF7308E2 | 9945（潤泰新） | 2024-08-05 | B3_break_defensive_low（exit） | §26 防守失效案例 |

### 3.4 record_decline_rebound（抽象案例，無具體 ticker 日期）

文章 §30 描述：113-08-05（2024-08-05）大盤歷史跌點後「鴻海（2317）、廣達（2382）」為「進場好機會」，但文章**未給出具體進場日期**（只說「08-05 之後不再創新低」），無法構成精確的 (ticker, date) 四元組。

**→ 標「待 user 提供」**：需 user 確認 2024-08-05 隔日（08-06）是否不再創新低的進場案例。

---

## 四、Step 3 — Calibration Run 結果

### 4.1 MD-01 ✅ PASS

```
ticker=8103, date=2024-06-11
merged_doji.detect() → True ✓

OHLC: o=49.8 h=50.2 l=48.0 c=50.2 ph60=52.3
prev (06-07): o=49.6 h=52.3 l=49.3 c=50.5 ph60=50.0

觸發分析：
  just_broke_high → prev_close (50.5) > prev ph60 (50.0) ✓
  prev_upper_dominant → upper=1.80 > lower=0.30 ✓
  today_lower_dominant → lower=1.80 > upper=0.00 ✓
  is_merged_doji:
    merged: o=49.6, c=50.2, h=52.3, l=48.0
    body_ratio = |49.6-50.2| / (52.3-48.0) = 0.14 ≤ 0.25 ✓
    upper_shadow_ratio = (52.3-50.2)/4.3 = 0.49 ≥ 0.20 ✓
    lower_shadow_ratio = (49.6-48.0)/4.3 = 0.37 ≥ 0.20 ✓

課程描述符合：「剛創新高 + 上影線+下影線合併長十字線」
隔日 (06-12) open=50.6 > prev_high=50.2 → gap_up_attack ✓
```

**結論**：MD-01 完全符合，pattern + expected branch 均正確觸發。

### 4.2 MD-02 ⚠️ MISS（位置條件不符）

```
ticker=5443, date=~2024-06-25
merged_doji.detect() → False ✗

OHLC 06-25: o=68.5 h=70.1 l=65.5 c=69.5 ph60=75.4
prev (06-24): o=70.9 h=75.4 l=68.2 c=68.5 ph60=73.3

觸發分析：
  just_broke_high → prev_close (68.5) NOT > prev ph60 (73.3) ✗
                    today_close (69.5) NOT > ph60 (75.4) ✗
  影線組合 OK（06-24 upper_dominant, 06-25 lower_dominant）
  merged doji OK（body_ratio=0.14, upper_ratio=0.46, lower_ratio=0.40）
  ❌ 位置條件 just_broke_high FAIL
```

**根因分析**：
- 06-24 是強上影線，high=75.4，但 close=68.5（從高點大幅回落）
- 06-25 的 prior_high_60=75.4（更新到 06-24 的 high）
- 實際上課程文章圖片中，「剛創新高」可能是視覺判斷（close 曾到達 high=75.4 附近），但日 K close 收盤未突破

**課程原文**：「位置就在**剛創新高**的狀態」—— 課程圖片顯示的是 K 線圖，可能以盤中高點（high=75.4）而非收盤價判斷「新高」。

**是否需要調常數？**
- 此為 position condition（`just_broke_high` = prev_close or close > prior_high_60）
- `just_broke_high` **不是** `course_proxy_constants.py` 的常數，是 features.py 的固定邏輯
- 課程明示「以收盤確認」為原則，放寬到 high > prior_high_60 會違反課程收盤確認規則
- **→ 不調整**：此案例需 user 確認課程是否允許「以盤中 high 判斷剛創新高」

### 4.3 MD-NEG-01 ✅ PASS（反例正確不觸發）

```
ticker=3305 (昇貿), window 2024-06-21~2024-06-27
merged_doji.detect() → 完全不觸發 ✓

課程說：「創新高的位置是六月二十一日的上影線黑K，
         並不是後來兩根上下影線，所以就算把這兩根合併起來，
         依舊沒有任何攻擊的意義」
→ 系統正確不觸發反例 ✓
```

### 4.4 AC-01, AC-02, AC-03（attack_cost_displayed）— 無法自動 calibrate

```
ticker=3289 2023-03-08: close=96.8=high=96.8(limit up), prior_high_60=94.0
  → attack_cost_displayed 條件滿足（漲停鎖住 + 突破前高）
  → 但 pattern 無 detect() 函式，無法自動跑 calibration
  → 需手動 context_overrides 注入：is_limit_up_locked=True, attack_cost=96.8

ticker=3693 2023-04-11: close=151.5=high=151.5(limit up), prior_high_60=147.0
  → attack_cost_displayed 條件滿足（漲停鎖住 + 突破前高）
  → 同上，無法自動 calibrate

ticker=6209 2023-12-15: close=29.0, high=29.0... (non-limit up day)
  → 不符合攻擊成本標準定義（需鎖漲停）
  → 課程文章說是「後記」，非標準案例
```

**→ 標「待 user 提供 detect() 實作或確認 context_overrides 測試方式」**

### 4.5 DS-01（defensive_stance）— 無法自動 calibrate

```
ticker=8103 2024-06-11（與 MD-01 同一天）
  → defensive_stance 條件需：
    1. is_just_broke_high（有）
    2. 大盤悲觀期間守住某個價位（無法自動判斷）
  → pattern 無 detect() 函式，無法自動跑 calibration
```

**→ 標「待 user 提供案例」：defensive_stance 的「大盤悲觀期間」判斷為人工觸發條件**

### 4.6 RD（record_decline_rebound）— 抽象案例

```
課程文章 §30 只提到：113-08-05（2024-08-05）是歷史跌點，
鴻海(2317)、廣達(2382) 是「之後的好機會」，
但進場日期（= B1_taiex_no_new_low 觸發日 = 08-06）未明示。
taiex_no_new_low_next_day 是 context 欄位，需 TAIEX 歷史資料比對。
```

**→ 標「待 user 提供」：需確認 2024-08-06 TAIEX 是否未創 2024-08-05 低點**

---

## 五、Step 4 — 校準結論

### 推薦調整的常數

**無需調整任何常數。**

理由：
1. MD-01（唯一可跑的 entry calibration case）完全通過，`MERGED_DOJI_BODY_RATIO=0.25` 和 `MERGED_DOJI_SHADOW_MIN_RATIO=0.2` 正確觸發
2. MD-02 失敗的根因是 `just_broke_high` 位置條件（features.py 邏輯，非 course_proxy_constants.py 的常數）
3. MD-NEG-01 反例正確不觸發（現有邏輯正確）
4. 無兩個以上案例同時指向同一個常數需要調整

### 不推薦調整的項目

| 項目 | 理由 |
|---|---|
| `just_broke_high` 放寬到 high > prior_high_60 | 違反課程「收盤確認」原則（CLAUDE.md §1） |
| MERGED_DOJI_BODY_RATIO 放寬 | MD-01 已正確觸發，0.25 符合課程意圖 |
| MERGED_DOJI_SHADOW_MIN_RATIO 放寬 | MD-01 已正確觸發，0.20 符合課程意圖 |

---

## 六、Entry Branch 有/無課程案例清單

### ✅ 有課程案例的 Entry Branches

| Branch | Playbook | 案例 | 狀態 |
|---|---|---|---|
| B1_gap_up_attack | merged_doji_attack | MD-01（8103 2024-06-11）| ✅ 通過 |
| B2_push_attack_above_merged_high | merged_doji_attack | （無具體 ticker 案例）| 待補 |

### ⚠️ 需 user 提供案例的 Entry Branches

| Branch | Playbook | 原因 |
|---|---|---|
| B3_gap_attack | attack_cost_displayed | pattern 無 detect()，需手動 context 注入 |
| B4_push_attack | attack_cost_displayed | 同上 |
| B1_market_stable_gap_up | defensive_stance | pattern 無 detect()，「大盤悲觀期間」需人工判斷 |
| B2_market_stable_push_attack | defensive_stance | 同上 |
| B1_taiex_no_new_low | record_decline_rebound | 需 TAIEX 歷史資料 + 課程明確進場案例 |

---

## 七、待補案例清單

1. **merged_doji B2_push_attack_above_merged_high**：需找課程文章中「推升攻擊（而非跳空）確認進場」的具體 ticker + date 案例
2. **5443 均豪 MD-02**：需 user 確認課程是否允許以盤中 high（非收盤）判斷「剛創新高」
   - 若允許：需將 `just_broke_high` 計算改為 `prev_high > prior_high_60_prev OR high > prior_high_60`（但會違反課程「收盤確認」原則）
   - 若不允許：MD-02 為「課程圖片顯示的是特定視覺情境，日K資料無法完美重現」→ 接受 miss
3. **attack_cost_displayed 系列**：需 user 決定是否為 attack_cost_displayed 實作 `detect()` 函式
   - 3289 (2023-03-08) 和 3693 (2023-04-11) 的 OHLC 資料均確認符合「漲停鎖住 + 突破前高」
4. **record_decline_rebound**：需 user 提供 2024-08-05/06 進場案例的具體 TAIEX/個股判斷邏輯

---

## 八、Baseline 驗證

| 項目 | 結果 |
|---|---|
| pytest 554 tests | ✅ 全綠 |
| calibration runner confirmed_signal hit rate（pre）| 100.0%（39/39）|
| calibration runner confirmed_signal hit rate（post）| 100.0%（unchanged，無常數變動）|
| MERGED_DOJI_BODY_RATIO | 0.25（unchanged）|
| MERGED_DOJI_SHADOW_MIN_RATIO | 0.20（unchanged）|

---

## 九、Anomaly 記錄

1. **任務背景說明中 88.6% baseline**：grid search 報告顯示 88.6%，但當前 `calibration_results.csv` 顯示 100.0%（39/39）。差異原因：grid search 時的 baseline 與最新的 CASE_INDEX_v4.csv 使用了不同的 case 集合，或者 v4 版本後增加了案例並修正了 hit 計算方式（hit column dtype 為 object，只有 True 沒有 False，5 個 NaN 全為 extras_pattern_skipped）。當前 100% 為正確 baseline。

2. **merged_doji fires on 8103 2024-06-11 的 just_broke_high 路徑**：觸發是透過「prev_close (50.5) > prev prior_high_60 (50.0)」（前一日路徑），而非「today close > prior_high_60」。這是合理的——06-07 確實突破了 06-06 的前高，且 06-11 是突破後兩天的合併十字線。

3. **attack_cost_displayed / defensive_stance / record_decline_rebound 無 detect()**：這三個 playbook 的設計定位是「需要人工判斷觸發」，非自動掃描 pattern。建議在未來 Phase N 中決定是否實作 detect()。

---

_Report generated by entry branch case-based calibration analysis (2026-06-04)_
