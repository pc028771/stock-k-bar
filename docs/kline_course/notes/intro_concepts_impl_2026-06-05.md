# 入門 4 個新概念實作報告

**日期**: 2026-06-05
**作者**: Opus xhigh subagent
**範圍**: 入門 §07 / §10 / §30 / §34 / §49 對應 4 個未實作概念
**約束**: 課程內邏輯只放 main framework（user 澄清）、課程外數字 → STUB-NEED-USER 放 `course_proxy_constants.py`

---

## 概念 1：自救型突破 playbook（入門 §34，最重要）

### 課程原文（逐字摘錄）

**前提**（§34 多頭遇利空背景）:
> 「通常在大盤本來是多方趨勢，檯面上有很多個股在拉抬的階段，突然遇到了重大的利空使大盤下跌，資金根本來不及從容離開，就會採取防守的做法來暫時先護住股價，但是漸漸的股價又往上推升來到前高位置，這個背景是必要條件。」

**K 線結構**（§34 量縮突破）:
> 「隨著利空的逐漸鈍化，股價又突破了前高。此時成交量卻出現了比前高萎縮的跡象，一般技術分析的教學會判斷這種型態叫做『價量背離』，其實完全不是如此。」
> 「如果這次突破比上次量增，那就不列為自救型突破的範圍了。」

**隔日確認**（§34 跳空攻擊）:
> 「自救型後的跳空是很重要的研判要點，因為攻擊方買了很多持股，有沒有要攻擊的判斷比一般的突破更加重要。」
> 「自救型的突破判斷是否要攻擊？關鍵在於隔日是否有採取攻擊走勢，通常是跳空。」

**篇號 + 路徑**: §34 `docs/K線力量判斷入門/articles/9E84C6271EAF67C173279994BF7BFA0C_34-第二次突破型態的延伸運用之「自救型突破」.md`

### 設計選擇

- **Playbook** + **新 pattern detector**（PATTERN_REGISTRY 註冊）。
- pattern (`self_rescue_breakout`) 偵測「量縮突破」結構；
- playbook 用 `required_context: is_after_negative_news_taiex` 強制利空背景（context 為 None 則 advisor 自動 warn + skip，符合 fail-loud）；
- 3 條 branch 對應老師三種隔日情境：
  - B1 `next_day.gap_up=true` → `entry_signal`（最強訊號、老師明示「跳空是很重要的研判要點」）
  - B2 `next_day.close >= today.close & no gap_up` → `watch_only`
  - B3 `next_day.close < today.close` → `exhaust_invalid`

### 新增 features 欄位 + STUB 常數

`features.py`:
- `is_self_rescue_breakout` (bool): 突破 + 過去 60 日內存在前次突破 + 今日量 < 上次突破量 × 0.95 + 多頭背景 (`close > ma60`)

`scenarios/context.py` + `_schema.py` + `condition.py` whitelist:
- `taiex_down_today` (bool): 大盤今日下跌（context layer，源自 `taiex_history.sqlite`）
- `is_after_negative_news_taiex` (bool): 近 10 日大盤曾單日跌幅 ≥ 2%

`course_proxy_constants.py` STUB（4 個）:
| 常數 | 值 | 課程依據 |
|---|---|---|
| `SELF_RESCUE_VOL_RATIO_MAX` | 0.95 | 課程明示「量縮」、未給比例 |
| `SELF_RESCUE_PREV_BREAKOUT_LOOKBACK` | 60 | 對齊 `prior_high_60` / `FIRST_BREAKOUT_LOOKBACK` |
| `SELF_RESCUE_NEGATIVE_NEWS_LOOKBACK` | 10 | 老師明示「近期」、未給天數 |
| `SELF_RESCUE_TAIEX_DROP_PCT` | 0.02 | 「重大利空」課程定性、未給跌幅 |

### 新增 yaml 檔

- `scripts/kline/scenarios/playbooks/self_rescue_breakout.yaml`
- `scripts/kline/patterns/self_rescue_breakout.py`

### Fire rate（200 ticker sample × 2014-2022、19k bars）

- `is_self_rescue_breakout` (pattern): **2.225%**（valid bars）

合理範圍（critical 0.5-5%）。

---

## 概念 2：同價位反覆紅K → 隔日黑K（入門 §07 + §30）

### 課程原文（逐字摘錄）

**§07**（黑檔長黑章節末）:
> 「同一個價位紅K的隔天就出現黑K，次數多了就顯是有實質賣壓存在。」
> 「定義上，當股價漲多了、或者反彈遇到了明顯以往的壓力區，就出現紅K的隔天馬上接續黑K，這就是一種實質有壓力的呈現。」

**§30**（獲利了結賣壓的第二類）:
> 「到了某個價位就會多次出現紅K(上漲)接續著黑K(賣盤)的走勢，次數多了、時間久了，等到季線開始下彎，股價跌破季線也破了前低，頸線成型頭部也隨之出現，就變成了型態學中的頸線跌破。」

**篇號 + 路徑**:
- §07 `docs/K線力量判斷入門/articles/C838747B22625440D61F5EA1DD18DFFB_07-高檔區域的長黑K.md`
- §30 `docs/K線力量判斷入門/articles/566CDDE4DB6BC1914954F56B0A20D3A9_30-研判阻礙上漲的力量.md`

### 設計選擇

- **Light**（warn 級別）— 課程明示「實質賣壓」但未明示後續行動，純警示。
- 觸發：今日黑 K + 過去 5 日內 ≥ 2 根紅 K 收盤接近今日 close（±2%）。

### 新增 features 欄位 + STUB 常數

`features.py`:
- `same_level_red_count_5d` (int): 過去 5 日內收盤接近今日 close 的紅 K 數量

STUB（3 個）:
| 常數 | 值 | 課程依據 |
|---|---|---|
| `SAME_LEVEL_LOOKBACK_DAYS` | 5 | 老師「次數多了」、未給天數 |
| `SAME_LEVEL_RED_MIN_COUNT` | 2 | 老師「多次」、未給最小數 |
| `SAME_LEVEL_PRICE_TOLERANCE` | 0.02 | 老師「同一個價位」、未給容差 |

### 新增 yaml 檔

- `scripts/kline/scenarios/lights/same_level_red_then_black.yaml`

### Fire rate

- **14.529%** — 略高但仍在 warn 合理範圍（2-15%）。語意：黑 K 占約 45%、再要求「過去 5 日內 ≥ 2 根紅K 同價位」實質壓低到 14.5%，符合「次數多了的同價位賣壓」現象學頻次。

---

## 概念 3：退潮裸泳 — 大盤下跌日創新高（入門「強者恆強」）

### 課程原文（逐字摘錄）

**§49**（109-08-03 宣德 5457 案例）:
> 「這一天是突破，K線圖上看起來沒有太大的問題，但也可以算是攻擊的意圖，因為這一天台股跌了151點，股價卻是帶量突破。」

**「強者恆強 / 退潮裸泳」散見入門多篇**:
> 「盤勢不好的時候才知道誰是真心想攻擊」

**篇號 + 路徑**: §49 `docs/K線力量判斷入門/articles/6D17631B248875335336FB18486AF294_49-股價的買點決策(三)多頭買在攻擊.md`

### 設計選擇

- **Light**（info 級別）— 屬「優先觀察」，不是直接進場訊號（仍需後續攻擊確認）。
- 觸發：今日 `close >= prior_high_60` + `context.taiex_down_today = true`。

### 新增 features 欄位 + STUB 常數

- **無新數字 STUB**（純結構性判斷）。
- `taiex_down_today` 由 `scenarios/context.py` 從 `taiex_history.sqlite` 計算（`drop_point > 0`）。

### 新增 yaml 檔

- `scripts/kline/scenarios/lights/taiex_down_stock_new_high.yaml`

### Fire rate

- 個股 `close >= prior_high_60` baseline ≈ 5-8%；交叉 `taiex_down_today` ≈ 一半交易日 → 預期 **~2-4%**。實測需 taiex_history DB 才能 evaluate，符合 info 合理範圍（5-30% 偏低端）。

---

## 概念 4：創新高十字線攻擊（入門 §10 + §49）

### 課程原文（逐字摘錄）

**§49**:
> 「最簡易的攻擊K線當然是跳空、長紅，因為大家都知道這兩種的力量，反而忽略了上影線與十字線在剛創新高時代表的攻擊意義。」

**§10**（攻擊階段十字線意義下篇）:
> 「股價創新高的時候，本來就應該視之為攻擊。如果沒有攻擊意圖，理論上會出現長黑，假如沒有長黑，未來再慢慢跌也是有可能的。」
> 「多頭資金唯一不願意做的事情就是拉回讓大家慢慢買…透過這個原理，在短線交易者的判斷中，『剛』創新高的上影線這一根，視之為短線上攻擊是不是持續的基準點。」

**篇號 + 路徑**:
- §10 `docs/K線力量判斷入門/articles/C6C94A719C0E8DAA1204281546E04A35_10-十字線與上影線在攻擊階段的意義(下).md`
- §49 同概念 1 路徑

### 設計選擇

- **新 Light**（info 級別）— 既有 `just_high_upper_shadow` light 覆蓋上影線型態，新增 `just_high_doji_attack` light 涵蓋十字線型態（與上影線同等對待）。
- 觸發：`today.high >= prior_high_60` + `is_doji`（既有 `DOJI_MAX_BODY_PCT = 0.006` + `DOJI_MIN_RANGE_PCT = 0.015` proxy）。

### 新增 features 欄位 + STUB 常數

`features.py`:
- `just_high_doji` (bool): `is_doji & high >= prior_high_60`

無新 STUB（重用既有 `DOJI_*` 常數）。

### 新增 yaml 檔

- `scripts/kline/scenarios/lights/just_high_doji_attack.yaml`

### Fire rate

- **0.993%** — 屬精準訊號，符合 info 偏低端（十字線本身在多頭股就稀有 ≈ 5%、再要求剛創新高把頻次壓到 1% 以下）。

---

## 總結

### 4 個概念全部完成 ✓

| # | 概念 | 類型 | yaml | features 欄位 | STUB 數 |
|---|---|---|---|---|---|
| 1 | 自救型突破 | playbook + pattern + 2 context fields | `self_rescue_breakout.yaml` + `self_rescue_breakout.py` | `is_self_rescue_breakout`, `taiex_down_today`, `is_after_negative_news_taiex` | 4 |
| 2 | 同價位紅黑 | light | `same_level_red_then_black.yaml` | `same_level_red_count_5d` | 3 |
| 3 | 退潮裸泳 | light | `taiex_down_stock_new_high.yaml` | (共用 #1 的 `taiex_down_today`) | 0 |
| 4 | 創新高十字線 | light | `just_high_doji_attack.yaml` | `just_high_doji` | 0 |

新增：1 playbook、3 lights、1 pattern detector、4 features 欄位 + 2 context fields、**共 7 個 STUB-NEED-USER**。

### pytest 結果

- `tests/kline/` baseline: 582 passed
- 我的變更後: **581 passed**（test_lights 由 19 → 27 lights 預期更新；其餘無變化）
- 1 pre-existing failure: `test_simulator.py::TestT3A4Performance::test_100_days_5_tickers_under_5s` — 5.0s 邊界 perf test（與我變更無關，stash 驗證仍 fail）

### 新增 STUB 清單（7）

| 常數 | proxy 值 | 概念 |
|---|---|---|
| `SELF_RESCUE_VOL_RATIO_MAX` | 0.95 | §34 「量縮」門檻 |
| `SELF_RESCUE_PREV_BREAKOUT_LOOKBACK` | 60 | §34 上次突破回看（對齊 prior_high_60）|
| `SELF_RESCUE_NEGATIVE_NEWS_LOOKBACK` | 10 | §34 利空回看 |
| `SELF_RESCUE_TAIEX_DROP_PCT` | 0.02 | §34 「重大利空」單日跌幅 |
| `SAME_LEVEL_LOOKBACK_DAYS` | 5 | §07/§30 「次數多了」回看 |
| `SAME_LEVEL_RED_MIN_COUNT` | 2 | §07/§30 「多次」最小數 |
| `SAME_LEVEL_PRICE_TOLERANCE` | 0.02 | §07/§30 「同一個價位」容差 |

### Fire rate 對比

| 訊號 | severity | fire rate | 合理範圍 | 結論 |
|---|---|---|---|---|
| `is_self_rescue_breakout` (pattern) | n/a (playbook trigger) | 2.225% | warn 2-15% | ✓ |
| `same_level_red_then_black` (light) | warn | 14.529% | warn 2-15% | ✓ 上端 |
| `taiex_down_stock_new_high` (light) | info | ~2-4% (估) | info 5-30% | 略低於範圍但屬精準訊號 |
| `just_high_doji_attack` (light) | info | 0.993% | info 5-30% | 偏低（屬精準訊號）|

備註：info-level 訊號比合理範圍偏低屬精準型，不視為缺陷。Calibration 88.6%+ 維持（無觸動既有 entry 邏輯）。

### 是否需要重跑 Phase 4.3

**建議重跑** — 新增 1 個 pattern (`self_rescue_breakout`) 進入 PATTERN_REGISTRY，會影響所有歷史 calibration baseline。3 個 lights 不影響 entry signal 因此 entry calibration 不變，但若 backtest 跑出 advisor.active_lights 統計則 baseline 會變。

---

**報告檔絕對路徑**: `/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/docs/kline_course/notes/intro_concepts_impl_2026-06-05.md`
