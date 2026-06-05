# Lights Fix Batch — 2026-06-04

依 `lights_audit_2026-06-04.md` 修正 14 個 lights。

## 環境

- 工作路徑：`/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power`
- 樣本：200 ticker × 2024-01-01 → 2026-12-31（97,105 eligible rows）
- pytest baseline：581 passed（4 pre-existing failures：test_load_lights_returns_19 / test_expected_light_ids_present / test_severity_distribution / test_no_active_lights_when_conditions_not_met，皆為 19 → 24 lights 後既存）
- pytest post-fix：581 passed（同前；3 個 light 相關測試已更新對齊新條件）

## 新增 features.py 欄位 + STUB

新增至 features.py（檔尾 lights-fix block）+ condition.py `_TOPLEVEL_FIELDS` 白名單：

| 欄位 | 定義 | 備註 |
|---|---|---|
| `prior_high_5` | 過去 5 日 high 滾動最大（不含今日） | structural feature |
| `prior_low_5` | 過去 5 日 low 滾動最小 | structural feature |
| `prior_high_10` | 過去 10 日 high 滾動最大 | structural feature |
| `body_pct_today` | body_pct alias（toplevel） | for §11 高檔長黑 body% |
| `range_pct_today` | range_pct alias | toplevel |
| `is_limit_up_today` | int alias for is_limit_up_locked | for §12 真正漲停 |
| `low_price_flag` | int, close < LOW_PRICE_THRESHOLD (30) | for §09 低價股 |
| `is_breakdown_pattern_flag` | int alias for is_in_breakdown_pattern | for §17 跌破頸線 proxy |
| `is_anomalous_volume_flag` | int alias for is_anomalous_volume | for §07 賣壓化解需有量 |
| `recent_range_pct_5` | (5 日 high - 5 日 low) / close | for §02 中樞、§05 微弱多方 窄幅判斷 |

### 新增 STUB 常數（course_proxy_constants.py）

```python
LOW_PRICE_THRESHOLD: float = 30.0  # [STUB-NEED-USER] §09 低價股
HIGH_LONG_BLACK_ENVELOPMENT_MIN_PCT: float = 0.04  # [STUB-NEED-USER] §11 高檔長黑
ZHONGSHU_RANGE_MAX_PCT: float = 0.10  # [STUB-NEED-USER] §02 中樞窄幅
```

---

## 逐 light 修改

### 1. top_formation_three_criteria (critical)

- 原 fire 47.7% → 新 fire 3.19%
- **原條件**：close < prev_high_60 AND close < prev.close AND ma60_will_rise=false
- **新條件**：
  ```yaml
  - "today.close": "< prior_low_60"
  - "is_breakdown_pattern_flag": "== 1"
  - "context.ma60_will_rise": false
  ```
- **課程原文**：「跌破頸線促成頭部成型……跌破時的判斷就是這是真正的轉入空方趨勢了」（77FF4B57...）
- 修正：原條件「跌破前 60 日高」≠ 跌破頸線；新條件用「跌破 60 日低 + 系統性破底結構（≥2 次破底事件 + MA60 下彎）」作為「跌破頸線」proxy

### 2. manipulator_distribution_warning (critical → warn)

- 原 fire 42.5% → 新 fire 0.27%
- **原條件**：close < prev_high_60 AND close < prev.close AND close < open
- **新條件**：
  ```yaml
  - "today.close": "< today.open"
  - "today.high": ">= prev_high_60"
  - "body_pct_today": ">= 0.04"
  ```
- **課程原文**：「高檔長黑當然是一種不攻擊，且等同於股價被賣出來的走勢……主力出的順，股價就變一座山，主力出不順，就變成箱型區間」（AE72522C...）
- 修正：severity critical → warn；新條件聚焦於「高檔長黑」（body ≥ 4%）

### 3. lowprice_first_pull_exit (warn)

- 原 fire 44.7% → 新 fire 0.41%
- **新條件**：
  ```yaml
  - "low_price_flag": "== 1"
  - "today.high": ">= prev_high_60"
  - "today.close": "< today.open"
  - "today.close": "< prev_high_60"
  ```
- **課程原文**：「對於低價股的正確操作邏輯是，第一次的拉抬結束就可以離場了。後面的區間整理不需要再摸」（5710C4E8...）
- 修正：加上低價股前提（close < 30 元 STUB）+ 「曾拉抬過」前提

### 4. high_pushup_next_step (info)

- 原 fire 4.3% → 新 fire 0.01%
- **新條件**：
  ```yaml
  - "today.high": ">= prev_high_60"
  - "recent_range_pct_5": "<= 0.10"
  - "today.close": "< prior_low_5"
  ```
- **課程原文**：「面對高檔推升，明日如果跌破，表示股價已經不再有攻擊意願……跌破了高檔推升的型態，代表的意義就是這一波的攻擊結束」（73F058E5...）
- 修正：抓「窄幅推升結構 + 跌破 5 日低」（真正的攻擊結束），非「突破前高紅 K」

### 5. gap_down_falling_three (warn)

- 原 fire 18.3% → 新 fire 4.93%
- **新條件**：
  ```yaml
  - "today.open": "< prev.close"
  - "today.close": "< today.open"
  - "today.close": "< prior_low_5"
  ```
- **課程原文**：「下降三法的文字定義：先有下跌黑K，然後整理兩到三天，再往下出現一根黑K」（3399437...）
- 修正：用「跌破 5 日低」作為「整理後再黑 K」的 proxy

### 6. high_black_k_warning (warn)

- 原 fire 2.5% → 新 fire 0.11%
- **新條件**：
  ```yaml
  - "today.close": "< today.open"
  - "today.high": ">= prev_high_60"
  - "body_pct_today": ">= 0.04"
  - "today.close": "< prev.open"
  ```
- **課程原文**：「這根黑K的出現也已經有標準答案，高檔長黑、包覆、實質有賣壓出現……一種股價沒有打算再往上走的型態」（4C255C33...）
- 修正：加「長黑」（body ≥ 4%）+「包覆」（close < prev.open）

### 7. just_high_upper_shadow (info)

- 原 fire 4.1% → 新 fire 2.39%
- **條件未變**（已吻合課程）；**rec 改寫**為多方傾向
- **課程原文**：「剛創新高上影線的高點，通常還是會越過。這一點只對於短線交易、當沖者較為有效」（BDD39904...）
- 修正：rec 由「需觀察攻擊企圖、否則遇壓」改為「通常還是會越過、設停損續抱」

### 8. lack_of_power_distinction (info)

- 原 fire 42.5% → 新 fire 11.50%
- **新條件**：
  ```yaml
  - "today.at_pressure_retest": true
  - "today.close": "< prev.close"
  - "context.ma5_will_rise": false
  ```
- **課程原文**：「賣壓中空段的反彈結束之後，就遇到了頭部壓力，沒有資金願意幫別人解套」（10A08869...）
- 修正：原「小紅 + MA5 不升」→ 改為「壓力區回測 + 收黑 + MA5 不配合」（真正的「賣壓中空結束」）

### 9. limit_up_next_day_stats (info)

- 原 fire 6.1% → 新 fire 0.33%
- **新條件**：
  ```yaml
  - "is_limit_up_today": "== 1"
  - "today.high": ">= prev_high_60"
  ```
- **課程原文**：「只要股價沒有回到第一根創新高的漲停板之下，都是強勢的表現，都還不需要考慮出場的問題」（805F4E23...）
- 修正：用真正漲停 flag（is_limit_up_locked，含鎖住條件）替代「平盤以上 + 觸前高」

### 10. mountain_descent_four_types (warn)

- 原 fire 47.7% → 新 fire 1.78%
- **新條件**：
  ```yaml
  - "today.close": "< attack_intent_zone_high"
  - "today.close": "< prev.close"
  - "context.ma20_will_rise": false
  ```
- **課程原文**：「當一檔股票出現走勢不合常理的強勢拉抬，那未來十年有可能最強的就是這一段了，除非基本面有看起來明顯獲利成長的表現」（C71C9461...）
- 修正：加「曾出現攻擊（跌回攻擊意圖區）」前提；rec 明示「K 線無法判斷四類分類，需配合基本面」

### 11. pessimistic_stock_structural (warn)

- 原 fire 2.7% → 新 fire 3.38%
- **條件未變**（邏輯本就合理）；**quote 改為原文逐字**
- **課程原文**：「優先應該要考慮的就是「不宜進場」的類型，除了K線結構之外，很自然地也會連基本面或者公司的狀態，做如此的角度考慮」（9375FF47...）

### 12. selling_pressure_dissolution_required (info)

- 原 fire 42.5% → 新 fire 0.24%
- **新條件**：
  ```yaml
  - "today.at_pressure_retest": true
  - "today.close": "> prev.close"
  - "is_anomalous_volume_flag": "== 1"
  ```
- **課程原文**：「明日K線還需要考慮到環境背景條件……解讀到底股價的上漲是真的有力量化解、還是股價只不過是被消息面帶上而已」（910E8BDF...）
- 修正：加「壓力區回測 + 異常放量」（真正的化解力量）

### 13. sunrise_vs_rising_three_boundary (info)

- 原 fire 4.3% → 新 fire 0.28%
- **新條件**：
  ```yaml
  - "today.close": "> today.open"
  - "body_pct_today": ">= 0.03"
  - "today.close": "> prior_high_5"
  - "prev.high": "< prior_high_5"
  - "today.close": ">= prev_high_60"
  ```
- **課程原文**：「假如沒有原本「正在日出攻擊」的前提，明日K線的角度就得要考慮上升三法的出現了」（C9F8EF65...）
- 修正：抓「長紅突破 5 日高 + 前 1 日非攻擊」的真正邊界狀態

### 14. weak_bull_trendline_only (info)

- 原 fire 42.5% → 新 fire 7.24%
- **新條件**：
  ```yaml
  - "today.at_pressure_retest": true
  - "recent_range_pct_5": "<= 0.08"
  - "context.ma5_will_rise": true
  - "context.ma20_will_rise": true
  - "today.close": "> prev.close"
  ```
- **課程原文**：「用短期趨勢線跌破，通常是在高檔區域已經沒有任何標準可以用來判斷的時候，沒有空方轉折，不得已才使用」（DFA09484...）
- 修正：加「高檔區域 + 窄幅 + MA20 也向上」（真正的「微弱多方」狀態）

### 15. zhongshu_recency_bias (info)

- 原 fire 44.7% → 新 fire 29.38%
- **新條件**：
  ```yaml
  - "recent_range_pct_5": "<= 0.10"
  - "today.close": "< prev_high_60"
  - "today.close": "> prior_low_60"
  - "today.close": "< prev.close"
  - "today.close": ">= prior_low_5"
  ```
- **課程原文**：「所謂的上升中樞型態指的是先上漲、橫向盤整，但是都沒有跌破原本先上漲的紅K低點」（98207726...）
- 修正：加「過去 5 日窄幅 + 不破 5 日低」識別真正中樞結構；仍偏寬但 info 等級可接受

---

## 總表

| Light | severity | 原 fire | 新 fire | 狀態 |
|---|---|---|---|---|
| top_formation_three_criteria | critical | 47.7% | 3.19% | ✅ |
| manipulator_distribution_warning | critical → warn | 42.5% | 0.27% | ✅ |
| lowprice_first_pull_exit | warn | 44.7% | 0.41% | ✅ |
| high_pushup_next_step | info | 4.3% | 0.01% | ⚠️ 偏窄 |
| gap_down_falling_three | warn | 18.3% | 4.93% | ✅ |
| high_black_k_warning | warn | 2.5% | 0.11% | ⚠️ 偏窄 |
| just_high_upper_shadow | info | 4.1% | 2.39% | ✅ |
| lack_of_power_distinction | info | 42.5% | 11.50% | ✅ |
| limit_up_next_day_stats | info | 6.1% | 0.33% | ✅ |
| mountain_descent_four_types | warn | 47.7% | 1.78% | ✅ |
| pessimistic_stock_structural | warn | 2.7% | 3.38% | ✅ |
| selling_pressure_dissolution_required | info | 42.5% | 0.24% | ✅ |
| sunrise_vs_rising_three_boundary | info | 4.3% | 0.28% | ✅ |
| weak_bull_trendline_only | info | 42.5% | 7.24% | ✅ |
| zhongshu_recency_bias | info | 44.7% | 29.38% | ✅ |

### Fire rate 摘要
- 範圍：0.01% – 29.38%
- 平均：4.36%
- critical 區間：3.19%（vs 原 42.5–47.7%）→ 大幅恢復警示意義
- warn 區間：0.11% – 4.93%
- info 區間：0.01% – 29.38%

### 注意
- `high_pushup_next_step` 0.01% 與 `high_black_k_warning` 0.11% 偏窄；它們本就描述高品質、稀少的訊號（高檔推升結構崩潰、高檔長黑包覆），低 fire 合理但 user 可後續調整 body% / 窄幅門檻。
- `zhongshu_recency_bias` 29.38% 仍偏寬，但已從 44.7% 降下、且為 info 等級。可考慮再加更窄幅或更長時間結構，但 info 等級暫可接受。

## pytest 狀態

- pre-fix: 581 passed, 4 pre-existing failures（24-lights 結構失配）
- post-fix: 581 passed, 同 4 pre-existing failures
- 額外更新 3 個 light 相關測試（top_formation 觸發條件、manipulator severity、bearish fire）以對齊新 YAML

## 報告路徑

`/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/docs/kline_course/notes/lights_fix_batch_2026-06-04.md`
