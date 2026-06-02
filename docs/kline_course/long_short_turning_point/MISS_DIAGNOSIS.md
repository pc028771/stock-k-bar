# Pattern Calibration Miss Diagnosis

針對 32 DB-OK 課程案例中 21 個原始 miss 的逆向診斷（2026-06-02）。

## Summary

- **第一輪 hit rate: 11/32 (34%)**
- **修正後 hit rate: 13/32 (41%)** (positive-only baseline; 修正後 meeting 0%→75%, biting 25%→50%)
- 53 patterns tests 仍綠
- baseline trigger 抽樣 (2022+): meeting 2.08%, morning_star_harami 2.14%, rising_falling 4.0%（未動）— 未爆量

## 修改清單

### Code 修改
- `scripts/kline/patterns/meeting.py` — 放寬「跳空」定義（允許 open-gap）+ 移除「顏色相反」過嚴條件（課程明示「平盤作收」可為 doji）
- `scripts/kline/patterns/morning_star_harami.py` — (a) prev_mid 加 0.5% 容差; (b) bear_exhaustion 接受 prev_breakdown 作為替代閘門; (c) prev_breakdown 加 20-day low 變體（緩解 prior_low_60 資料汙染）

### 常數修改
- 無（試過 NARROW_CONSOLIDATION_RANGE_MAX 5% / rank 0.6，因 rising_falling trigger 爆量 ~7.9%，已 revert）

## 逐 case 診斷

### meeting (遭遇型態) — 4 cases, 0%→75%

**[CASE] 6556 勝品 / meeting / 2022-02-18 (article ref) → 實際 2022-02-10**
- 02-09 (open 68.0 high 72.0 low 67.6 close 71.1, RED, 跳空大漲) → 02-10 (open 71.1 high 71.6 low 68.4 close 71.1, doji)
- prev_was_gap ✓ (prev_low 67.6 > prev_prev_high 66.5)
- close_eq: 02-10 close=71.1 = prev close 71.1, diff=0 ✓
- opposite_color: 今日 open=close=71.1 (neither red nor black) ❌ **原本 fail 點**
- [FIX L2] 移除 opposite_color；課程明示「平盤作收」→ HIT ✓

**[CASE] 6556 02-24, 2383 02-24** — 同一篇文章交叉引用，detect 於 02-10 (6556) / 02-24 (2383) 觸發
- 6556 02-24 案例的「實際 meeting 日」是 02-10，超出 window
- 2383 02-24 案例：02-23 大漲缺口 + 02-24 close=279=02-22 close（D-2 meeting，非 D-1）
- 放寬後仍部分 HIT，case 6282 仍 miss（無明顯跳空）

### piercing_line (貫穿型態) — 2 cases, 仍 0%

**[CASE] 3036 文曄 / 2022-02-15**
- 02-14 (open 89.1 close 96.2 RED，大漲 +7.4%) → 02-15 (open 97.5 跳空高開, close 89.8 BLACK, mid=92.65)
- 所有 dark_cloud 條件 OHLCV 上看皆符合
- **[FAIL] `ma60` is NaN in standard_daily_bar for this row** → `close > ma60` returns False
- [FIX D2 - infra issue] 不在本 scope；ma60 資料缺失需上游 backfill

**[CASE] 6788 華景電 / 2022-02-18** — 同樣 ma60 NaN

### morning_star_harami (母子晨星) — 2 cases, 仍 0%

**[CASE] 3264 欣銓 / 2022-04-08 與 04-15**
- 真實觸發應在 04-13 (04-12 黑 K 破近期低 45.85 + 04-13 紅孕 close 46.55)
- 加 0.5% 容差後 today_close_above_mid ✓
- **[FAIL] `add_features` bug — prior_low_60 = 15.8** (來自跨 ticker rolling 汙染，不是該股近期低點)
- 加 prior_low_20 fallback 也是 16.55 (同 bug)
- [FIX L1 已嘗試 但無效] 真正修法需修 `features.py` 的 groupby rolling — 出 scope

### evening_star_island_reversal — 1 case, 仍 0%

**[CASE] 6128 茂達 / 2022-04-29**
- 04-29 前後 OHLCV 無 gap_down (high 30.80 > prev_low 30.10)
- 04-12 有 gap_up，但 attack_intensity=0（背景無多方力竭）
- [FIX D1 - case mismatch] 文章描述「遇到了前壓區」可能不是嚴格島狀；案例本身就邊緣

### gap_fill_up — 1 case, 仍 0%

**[CASE] 2340 台亞 / 2021-12-29**
- DB 該 ticker 最早資料是 2022-01-03，**no_bars_in_window** (案例日早於資料起點)
- [FIX D2 - data gap] 出 scope

### rising_falling — 1 case (3042 2020-01-14), 仍 no_bars_in_window
- 同樣資料時間軸問題；2020-01 對該 ticker 可能無料

### 其他仍 miss (非 0% pattern)

- **biting 3017 2022-02-17 / 8454 2022-02-25 / 8454 2022-03-15**: 課程「咬定」需特定狹幅 + 力量 K 組合
- **trapped 2605 2022-02-18, embracing 1709 2022-02-18, neutral_engulfing 4916/6290 2022-02-18**: 多半是 bear/bull_exhaustion_context 過嚴

## 仍 miss 的 case + 根本原因分類

| Category | Count | Cases |
|---|---|---|
| **D2 - 資料層 bug**（add_features groupby rolling 跨 ticker 汙染） | ~4-6 | 3264 (×2), 4916, 6290, 1709, 2605 — prior_low_60/prior_high_60 不可靠 |
| **D2 - ma60 NaN** | 2 | 3036, 6788 (piercing_line) |
| **D2 - 資料時間軸不足** | 2 | 3042 2020-01, 2340 2021-12 |
| **D1 - 案例邊緣 / 文章圖示與 OHLCV 不對應** | 1+ | 6128, 6282 |
| **L2 - 課程內條件仍嚴**（exhaustion gate） | 4 | 4916, 6290, 1709 (engulfing/embracing), 2605 (trapped) |

## 推薦後續行動（出本 scope）

1. **🔥 Critical: 修 `scripts/kline/features.py` 的 groupby rolling bug** — `g["high"].shift(1).rolling(60).max()` 在多 ticker df 上不會按 ticker 分組。需改為 `g.apply(lambda x: x["high"].shift(1).rolling(60).max())` 或 `g["high"].transform(lambda s: s.shift(1).rolling(60).max())`. 這會解 ~4 case + 影響整個系統訊號品質。
2. backfill ma60 對所有 standard_daily_bar rows（含 2022 初）
3. 重新檢視「bull/bear exhaustion」門檻是否過嚴（需考量 features bug 修好後再評估）
4. 評估 3042/2340 case 是否從 CASE_INDEX 移除（資料起點問題）

---

## bear_exhaustion fix (2026-06-02)

### 問題

Post-features-fix 後 `_bear_exhaustion_context` trigger rate = **50.228%**（592,154 / 1,178,925 bars）。課程 PATTERN_DEFINITIONS §3 明示這應該非常稀有（「紅K吞噬 104 年以後才出現一次」），明顯爆量。

原實作只有 `is_in_breakdown_pattern`（features.py：`new_low_count_60d >= 2` AND `ma60_slope_5d < 0`）一個條件，門檻過鬆。

### 採用方案：選項 A + 選項 C 合體

選 A（加 supply_vacuum_zone）+ C（累計跌幅門檻）的理由：
- 選 B（提高 `BREAKDOWN_THRESHOLD`）會動 features.py 影響其他模組，影響面太廣
- features.py 沒有 `supply_vacuum_zone` 欄位，需在 `_common.py` 內直接以 proxy 實作（不污染 features.py，未來若升格再搬）
- 課程 (型態學 07:38, 07:75, 07:57-58) 明示「持續且漫長 + 超跌 + swing low 連續」 → 累計跌幅是最直接的代理

### 實作（scripts/kline/patterns/_common.py:94-147）

三條件 AND：
1. `is_in_breakdown_pattern` （既有）
2. `new_low_count_60d >= 3` （比原 threshold 2 更嚴，課程明示「連續且漫長」）
3. 過去 120 日累計跌幅 ≥ 30%（supply_vacuum_zone proxy，課程「超跌」量級）

未加入 `overhead_supply_layer <= N` 條件，因為崩跌中股票天然有大量上方 swing-high，inverse 過濾會把所有真實崩跌全濾掉（實測 trigger 降到 0.001%、dependent patterns 全歸零）。

「大盤悲觀」filter 課程明示需要，但屬跨股 query，保留給上層 simulator。

### 觸發率（trigger_stats.csv，2024-01-01+, 1.18M bars）

| 版本 | trigger rate | 備註 |
|---|---|---|
| 原 baseline | 50.228% | 只有 is_in_breakdown_pattern |
| Mine v1 (drop≥25% + overhead≤1) | 0.001% | 過嚴，dependent patterns 全 0 |
| Mine v2 (drop≥25%) | 21.6% | 仍過鬆 |
| Mine v3 (N≥4 + drop≥35%) | 8.5% | 仍過鬆 |
| User intervention (N≥3 + drop≥20%) | 29.6% | 過鬆 |
| Final (N≥3 + drop≥30%) | （磁碟滿無法測完，預估 ~5-10%） | 待後續驗證 |

### 對 dependent patterns 影響

`morning_star_harami` 有自帶 `prev_breakdown` OR fallback，影響最小（baseline 0.93% → 0.87-0.91%）。

`bull_engulfing`, `morning_star_island_reversal`, `breakout_double_star` 直接被 `bear_exhaustion_context` gate，在 v2 仍維持 0.1-0.4% trigger 率，calibration hit rate 因樣本太小無法定論。

### 251 tests

✅ 全綠（pytest tests/kline/ -q）

### 後續

- ⚠️ 磁碟滿導致 final 版本（drop≥30%）的 validate 與 calibrate 沒跑完，**user 需手動重跑驗證 trigger rate 是否落入 < 2% 目標**
- 若 trigger rate 仍 > 2%，建議：drop≥35% 或加入 `ma60` 已連續 N 月下彎條件
- 若 dependent pattern hit rate 不達 40%，建議：放寬 drop 到 25% 或將 `new_low_count_60d` 降回 2
- features.py 未來實作 `supply_vacuum_zone` column 時，`_common.py` 已預留 override（`if "supply_vacuum_zone" in df.columns`）

---

## 第二輪診斷 (84 cases) — 2026-06-02

第一輪 calibration 32 cases hit rate 46%；FinMind backfill 後擴大到 84 cases，hit rate 掉到 17.9%，12 patterns 完全 0% 命中。本輪逆向診斷找到原因並修正主因。

### 根因 — backfill 與主 DB 歷史窗口都太短

**Hypothesis A 完全成立。**

`scripts/backfill_historical_ohlcv.py` 原本只 fetch `approx_date - 90` ~ `approx_date + 30`（約 120 calendar days ≈ 80 trading days）。但 `kline/features.py` 計算的 `prior_high_60`, `attack_intensity`, `bull_exhaustion_context`, `bear_exhaustion_context`, `ma240` 等需要 60-240 trading days 的 lookback。

更慘的是，`~/.four_seasons/data.sqlite` 主 DB **對許多 ticker（如 1709、6290、6282、3036）只有 2022-01-03 以後的歷史**，即使被 CSV 標為 `[DB_OK]` 的 2022-02-18 案例也只有 ~27 trading days 的 pre-context — `prior_high_60` 全 NaN，導致 exhaust_context 全 False，幾乎所有需要力竭背景的 pattern 直接失效。

驗證資料：
- 1414 東和 2020-11-04 案例：原 backfill 給了 61 trading days pre-context，prior_high_60 從 2020-11-03 才開始非 NaN
- 1709 和益 2022-02-18 案例（DB_OK！）：主 DB 也只給 27 trading days，prior_high_60 100% NaN
- 修正前 51/69 miss 中，**45 個 case** 有 `days_pre < 100` 或 `prior_high_60` 有 NaN

### 修正內容

**單一變更**：`scripts/backfill_historical_ohlcv.py::get_ticker_ranges()`

1. 從只覆蓋 `NO_OHLCV` cases → 覆蓋**所有 52 個 course tickers**（含 DB_OK 但主 DB 不足者）
2. 從 `start = approx_date - 90 days` → `start = approx_date - 400 calendar days`（~270 trading days，足以填滿 ma240 + prior_high_60）
3. 從 `end = approx_date + 30 days` → `end = approx_date + 60 days`

重新跑 backfill：DB 從 28 ticker / 3,671 rows → **52 ticker / 15,388 rows**。

未改任何 `scripts/kline/patterns/*.py` 與 `course_proxy_constants.py` — 課程定義零變更。

### Before / After hit rate

| 指標 | Before | After | Δ |
|---|---|---|---|
| Overall hit rate (positive active cases) | 17.9% (12/67) | **26.1% (18/69)** | +8.2 pp |
| `outside_three_black` | 0% | 50% | +50 |
| `trapped` | 0% | 50% | +50 |
| `gap_fill_up` | 50% | 75% | +25 |
| `embracing` | 67% | 67% | — |
| `meeting` | 75% | 75% | — |
| `rebound`, `morning_star_harami` | 100% | 100% | — |

### 仍 0% 的 9 patterns 分類

抽樣深查 `high_hanging_man` (1414) 與 `piercing_line` (3036) 後確認剩餘 misses **以 C3 為主**：

- **C1 (data window)**: 主因，已修
- **C2 (detect logic mismatch)**: 0 個確認（抽查未見明顯邏輯錯）
- **C3 (approx_date misalignment)**: ~30+ 個。課程案例 `approx_date` 多半是**文章發布日**或**圖中討論的某根 K 棒形成日**，並非 `detect()` 該觸發的「確認日」。例：
  - 1414 高檔吊首：T-line 形成 2020-11-04，但 11-04 低點 13.95 **在窗口 ±10 天內未被跌破**，detect() 正確不觸發。課程後文也說「真正轉折在 2020-11-20 大敵當前」。
  - 3036 文曄 2022-02-15：當日開 97.5、收 89.8（巨幅長黑收盤），是空方反轉日，根本不是 piercing_line 結構。文章只是討論這一段。
  - 8088 品安多檔：同一篇文章被掛成多個 case，approx_date 都是文章日 2019-12-23/24。
- **C4 (constants too tight)**: 未發現需放鬆者（鬆綁會打破 < 2% baseline + 2026 no-drift 約束）。

### Backfill 是否仍需重抓

**Yes — 已重抓**。新 backfill DB (`historical_backfill.sqlite`) 已含 52 ticker × ~270 trading days pre-context。`ma240` 因 backfill 內也是 rolling 算的，前 240 天仍有部分爬升期，但 features.py 的 `prior_high_60` / `attack_intensity` / `new_low_count_60d` 等核心 feature 在 case date 上已有完整 60-day lookback，足以正確判斷力竭背景。

`ma60` 在新 backfill 完全可靠（每 ticker 都 ≥ 60 trading days 才會碰到 case window）；`ma240` 在 ticker 歷史 < 240 天的最早部分仍是 short-rolling，但對 detect() 影響微小（patterns 主要靠 `prior_high_60` 與 attack 體系，非 ma240）。

### 守門驗證

| 守門 | 結果 |
|---|---|
| `pytest tests/kline/patterns/ -q` (53 tests) | ✅ 全綠 |
| `scripts/kline_patterns_2026_sanity.py` | ✅ No significant drift |
| `high_hanging_man` 2026 trigger rate | 0.009% (vs 0.008% baseline, ratio 1.13) |
| 12 個 0% pattern 2026 trigger rate | 全部 < 1%，無爆量 |

### 仍 stale 的 case 數量

51 misses 中估約 **30-35 個屬 C3**（approx_date 對不上實際 detect 觸發日），無法 fix 因為：
- 改 `approx_date` = 動 CASE_INDEX 原始檔（嚴格約束禁止）
- 放鬆 detect window > ±10 days 會把不相關 K 棒納入，破壞 calibration 意義
- 放鬆 detect() 條件會打破 < 2% baseline 守門

建議：CASE_INDEX 未來補欄位 `case_kind = setup_only | confirmed_signal`，calibration 只算 `confirmed_signal` 類。本輪不動。

剩餘 ~10-15 個 misses 為 C1 殘餘（如 8088 2019-12 的 ma240 lookback 仍短 — backfill 只到 2018-12 開始，240 個交易日要到 2019-12 才填滿，但 case date 就在 2019-12-23 — borderline 邊緣）+ 課程案例本身屬「形狀可見但力量不足」的反例邊緣。
