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
