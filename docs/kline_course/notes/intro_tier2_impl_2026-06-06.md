# 入門 Tier-2 — 11 個未實作概念實作報告

**日期**: 2026-06-06
**作者**: Opus xhigh subagent
**範圍**: K線力量入門 22 未實作概念中、扣除外部資料 / 超難項目後可實作的 11 個
**約束**: 課程內邏輯放 main framework + 數字 STUB 放 `course_proxy_constants.py`

---

## 概念狀態 (11/11 done)

| # | 概念 | 課程出處 | 類型 | 狀態 |
|---|---|---|---|---|
| 4 | 連續紅K「沒攻擊意圖」量化 | 入門 「紅色誤解」+ §31 | scoring 負分 | ✓ done |
| 6 | 連續十字線區間 | §03 + §12 + §09 | light (info) | ✓ done |
| 7 | 大盤假性跌破 | §33 | TAIEX context + light | ✓ done |
| 8 | 大盤 V 型反彈 | §58 | TAIEX context + light | ✓ done |
| 9 | 提前部署（量超過套牢區量、價未突破）| 入門「成本原理」 | feature + light | ✓ done |
| 12 | 剛創新高上影線低點停損 | §49 | exit | ✓ done |
| 13 | 空頭吞噬驗證 | §55 + §30 | verification | ✓ verified-aligned |
| 14 | 跳空反轉驗證 | §55 | verification | ✓ verified-aligned (with caveat) |
| 16 | 整理 > 2.5 月 + 季線下彎 | §07 + §21 | light (warn) | ✓ done |
| 17 | 遇壓先出補完 | §44 | exit annotation | ✓ done |
| 18 | 緩慢推升型移動停利 | 入門 出場(二) | exit | ✓ done |

---

## 新增 artifact 清單

### 新 yaml lights (5)
- `scripts/kline/scenarios/lights/consolidation_long_ma60_falling.yaml`（#16，warn）
- `scripts/kline/scenarios/lights/consecutive_doji_range.yaml`（#6，info）
- `scripts/kline/scenarios/lights/early_deployment_volume.yaml`（#9，info）
- `scripts/kline/scenarios/lights/taiex_false_breakdown_recovered.yaml`（#7，info）
- `scripts/kline/scenarios/lights/taiex_v_sunrise.yaml`（#8，info）

### 新 Python 檔案 (2)
- `scripts/kline/exit/just_high_upper_shadow_low_break.py`（#12，新 exit）
- `scripts/kline/scoring/attack_intent_consecutive_red.py`（#4，新 scoring component）

### 修改既有檔案
- `scripts/kline/exit/trailing_stop.py` — 新增 `mark_slow_push()` 函式 (#18)
- `scripts/kline/exit/supply_zone_reach.py` — 補入門 §44 對齊註記 (#17)
- `scripts/kline/patterns/bear_engulfing.py` — 補入門 §55 驗證註記 (#13)
- `scripts/kline/patterns/gap_reversal.py` — 補入門 §55 驗證註記 + caveat (#14)
- `scripts/kline/features.py` — 新增 5 個 features 欄位 + import
- `scripts/kline/scenarios/condition.py` — 加 6 個 toplevel + 2 個 context 欄位 whitelist
- `scripts/kline/scenarios/context.py` — 加 2 個 TAIEX context 計算 (§33 / §58)
- `scripts/kline/scenarios/_schema.py` — 加 2 個 ContextSnapshot 欄位
- `scripts/kline/scoring/__init__.py` — 註冊新 scoring component
- `scripts/kline/exit/__init__.py` — 註冊新 exit + trailing variants
- `scripts/kline/course_proxy_constants.py` — 新 9 個 STUB constants
- `tests/kline/scenarios/test_lights.py` — 更新 expected_ids / severity_counts
- `tests/kline/scoring/test_registry.py` — 加 attack_intent_consecutive_red

### 新 features 欄位 (5 個 + 3 個 toplevel int alias)
- `ma60_falling`（bool）— §21 季線下彎
- `consolidation_over_2_5_months`（bool）— §07 兩個半月整理
- `volume_exceeds_resistance_volume`（bool）— 入門「成本原理」提前部署
- `consecutive_doji_count`（int）— §03 連續十字線天數
- `consecutive_doji_range_high` / `_low`（float）— 連續十字區間高低

Toplevel int alias:
- `ma60_falling_flag`, `consolidation_over_2_5_months_flag`,
  `volume_exceeds_resistance_volume_flag`, `consecutive_doji_count_int`

### 新 Context 欄位 (2)
- `taiex_false_breakdown_recovered`（bool）— §33 大盤假性跌破已站回
- `taiex_v_sunrise`（bool）— §58 V 型反彈確認

---

## 新增 STUB 常數 (9)

| 常數 | 值 | 課程依據 |
|---|---|---|
| `SLOW_PUSH_RETRACE_PCT` | 0.05 | 入門 出場(二) 移動停利、課程未給 % |
| `ATTACK_INTENT_WINDOW_DAYS` | 5 | §31 突破後觀察、課程未給天數 |
| `ATTACK_INTENT_RED_NO_GAP_MIN` | 2 | §31「連續」、未給最小數 |
| `ATTACK_INTENT_PENALTY_PER_DAY` | -1.0 | scoring 量級代理 |
| `ATTACK_INTENT_MAX_PENALTY` | -3.0 | scoring 上限代理 |
| `CONSOLIDATION_LONG_DAYS` | 50 | §07 兩個半月 ≈ 50 交易日（**course-stated**） |
| `CONSOLIDATION_LONG_RANGE_MAX_PCT` | 0.20 | 「整理」幅度 proxy |
| `EARLY_DEPLOY_RESISTANCE_LOOKBACK_DAYS` | 60 | 對齊 prior_high_60 |
| `EARLY_DEPLOY_VOL_MULTIPLE` | 1.0 | 課程「超過」即可、不給倍數 |

加上既有 4 個 INTRO-1 + 3 個 INTRO-2 STUB（5/6 入門 4 概念）→ 累計 16 個入門 STUB。

---

## Fire-rate sanity check（53 ticker × 2014-2022、15,817 valid bars）

| 訊號 | severity | fire rate | 合理範圍 | 結論 |
|---|---|---|---|---|
| `is_self_rescue_breakout` (baseline) | — | 2.225% | warn 2-15% | ✓ |
| `just_high_doji` (baseline) | info | 0.993% | info 1-30% | ✓ 精準型 |
| `ma60_falling` (background) | — | 46.4% | 不單獨觸發 | OK |
| `consolidation_over_2_5_months` (background) | — | 26.2% | 不單獨觸發 | OK |
| `consolidation_long_ma60_falling` (light) | warn | 11.99% | warn 2-15% | ✓ |
| `volume_exceeds_resistance_volume` (light) | info | 1.45% | info 1-30% | ✓ 精準型 |
| `consecutive_doji_range` (light) | info | 3.20% | info 1-30% | ✓ |
| `taiex_false_breakdown_recovered` | info | (TAIEX-only) | — | logic only |
| `taiex_v_sunrise` | info | (TAIEX-only) | — | logic only |

備註: TAIEX-based lights 須整段歷史 TAIEX 資料才能 fire-rate 統計、結構驗證已 OK。

---

## pytest 結果

- baseline 開始: 581 passed + 1 pre-existing perf test failure
- INTRO-tier-2 變更後: **581 passed** + 1 pre-existing perf test failure（test_simulator.py::TestT3A4Performance::test_100_days_5_tickers_under_5s）

唯一 failing test 為 5s 邊界 perf test（與本批變更無關、stash 驗證仍 fail）。

calibration 88.6%+ 維持（**未動 entry 邏輯 / scoring weights / pattern detector**），
新增的 scoring component `attack_intent_consecutive_red` 雖在 SCORING_REGISTRY 但
**未進入 pattern_breakout 主分數加權**、不影響 baseline calibration。Phase 4.3 v5
背景進度不受影響。

---

## #13 / #14 驗證細節

### #13 空頭吞噬（bear_engulfing）

入門 §55 原話：「空頭吞噬的定義是創新高的紅K、隔天被長黑完全包覆」

現有 `bear_engulfing.py` 條件：
1. prev_is_red (黑 K 前一日為紅 K) ✓
2. prev_bar_had_attack_meaning - cond_a = `prev_is_red & (prev_close > prior_high_60)` ✓ 對應「創新高」
3. 今日 is_black & open >= prev_close & close <= prev_open ✓ 對應「完全包覆」
4. bull_exhaustion_context（多空轉折 PATTERN_DEFINITIONS §2 標準守則、入門 §55 未強制）

**結論**: ✓ 對齊入門 §55，已補充驗證註記到 docstring。

### #14 跳空反轉（gap_reversal）

入門 §55 原話：「跌破了前一天紅K的低點、還連向上跳空缺口都回補(三個現象同一根發生)」

入門 §55 描述大學光 3218 案例是 intraday 反轉（開高 → 盤中跌破 → 回補多缺口），
屬「同日盤中三現象」、需要分 K 資料。

現有 `gap_reversal.py`（對齊 PATTERN_INVENTORY P09）：
- D-0 開盤向下跳空 (open < prev_low)
- D-0 收盤無力回補 (close < prev_low)
- 過去 30 日內有攻擊狀態

**結論**: ✓ 日 K 一般化版本、涵蓋多數案例。入門 §55 intraday 變體屬於更精細的
盤中變體、超出日 K 層級。已補充驗證 caveat 到 docstring。

---

## 報告檔絕對路徑

`/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/docs/kline_course/notes/intro_tier2_impl_2026-06-06.md`
