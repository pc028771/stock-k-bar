# 多空轉折組合 K 線 — Pattern Inventory

來源：26 篇 PressPlay《K 線力量判斷入門》延伸講座「多空轉折組合 K 線」+「非轉折組合 K 線補充篇」。
目標：把每一個型態整理為可實作的 `detect(df) → pd.Series[bool]` 規格。

## 共同術語與條件

下列詞彙在所有 pattern 中重複使用，為避免重述，先在此定義：

- **力量型 K 線（power bar）**：長紅或長黑，相對於近期 K 線實體明顯更長。課程文字描述為「實體長」、「除跳空缺口外當日力量的最強展現」。**[STUB-NEED-USER]** 課程無數字定義，建議 `body_pct ≥ percentile_70(20d body_pct)` 或 `body_pct ≥ 1.5 * ATR_body_20d`。
- **十字線 / 醞釀型 K 線（doji / indecision）**：features.py 已有 `is_doji`（`body_pct ≤ 0.6%` AND `range_pct ≥ 1.5%`）。
- **K 棒中值（midpoint）**：以實心 K 線計算 = `(open + close) / 2`。課程明示（第 03 篇）。
- **日出（sunrise bar）**：`high > prev_high AND low > prev_low`。features.py 已用此定義。
- **日落（sunset bar）**：`high < prev_high AND low < prev_low`。需新增 feature。
- **孕線（harami / 懷抱）**：`high ≤ prev_high AND low ≥ prev_low`（今日高低點都在前日範圍內）。需新增 feature。
- **包覆 / 吞噬（engulfing）**：實體包覆 = `max(open, close) ≥ prev_high AND min(open, close) ≤ prev_low`（嚴格實體包覆）；課程也接受「高低點都比昨天大」的弱包覆。
- **向下跳空（gap down）**：`high < prev_low`（K 線意義上的真實缺口）。features.py 已用此定義。
- **向上跳空（gap up）**：`low > prev_high`。
- **力竭背景（exhaustion context）**：課程一致強調，**轉折組合一定要有力竭背景**，否則只是「形狀符合但無意義」。具體分兩類：
  - **多方力竭**：股價先有明顯多方拉抬（漲幅 + 創新高 / 接近 60 日高）。**[STUB-NEED-USER]** 課程無數字，建議「過去 N 日漲幅 ≥ X%」或 `close > prior_high_60`。
  - **空方力竭**：股價先有明顯下跌（跌幅 + 創新低 / MA60 向下）。**[STUB-NEED-USER]** 同上。可借用 features.py 既有 `is_in_breakdown_pattern` + 「最近 N 日創 60 日新低」。
- **壓力區（overhead supply）**：features.py 已有 `overhead_supply_layer` 與 `unfilled_gap_down_count_240d`。
- **新增 feature 清單（在 inventory 結尾總結）**。

---

# 【多空轉折篇】16 個

---

## P01: 前言概念（duokong_zhuanzhe_intro / context_only）

- **Source**: 第 01 篇《多空轉折組合的觀念與關鍵K線前言篇》（B2E7A4597B7D1B50CF88163C892204D1）
- **Direction**: both
- **Signal Class**: context_only
- **K-bar 數量**: N/A
- **識別規則**: 無，純概念篇。重點：
  - 轉折組合是**多單出場**（多方力竭）或**空單回補**（空方力竭），**非反向進場訊號**
  - 力竭原理：原始趨勢的結束，不一定是反向開始
  - 三大關鍵觀念：力竭原理、紅 K 需要追高買盤 / 黑 K 不一定是賣壓沉重、組合需出現於明確方向走勢的高低點
- **建議放法**: 不需實作；在 `scripts/kline/patterns/__init__.py` docstring 註記為設計原則
- **跨課程適用**: 是（主力大也需此認知）
- **不確定**: 無

---

## P02: 空頭吞噬 / bear_engulfing

- **Source**: 第 02 篇《包覆線：空頭吞噬與多頭吞噬》（E79401532D60CC63B302926C2C33FB50）
- **Direction**: bear
- **Signal Class**: exit（多單出場） / context_only
- **K-bar 數量**: 2
- **識別規則**:
  1. 前一日紅 K：`prev_close > prev_open`
  2. 前一日紅 K **本身具備攻擊意義** — 課程明示：「被包覆的紅 K 如果本身不代表力量上的特別意義，那這個包覆就沒有任何以後股價漲跌的必然性」。可用 features.py 的 `prev_bar_had_attack_meaning`（已有）或 `prev_close > prior_high_60.shift(1)`（前日紅 K 創 60 日新高）
  3. 今日黑 K 實體包覆前日：`open ≥ prev_close AND close ≤ prev_open`（嚴格 = 黑包紅實體）；課程接受退讓版：`high > prev_high AND low < prev_low`（高低點包覆，盤中曾經實體包覆）
  4. 今日是「力量型黑 K」（黑 K 越強，意義越大）
  5. **失效條件**：若股價再次突破，原轉折意義消失（`subsequent close > engulfing_bar_high` 後失效）
- **需要的 features**: prev_close, prev_open, prev_high, prev_low, prior_high_60, prev_bar_had_attack_meaning（皆已有）; 力量型 K 線判定（需新增）
- **建議放法**: `scripts/kline/patterns/engulfing.py` — 提供 `detect_bear(df)`, `detect_bull(df)`
- **跨課程適用**: 是。主力大 scanner 可用於「老師點名後出現黑吞噬 → 老師可能停損」的訊號
- **不確定 / 缺資料**:
  - 力量型 K 線的數字定義（**[STUB-NEED-USER]**）
  - 「攻擊意義」是用 features.py `prev_bar_had_attack_meaning` 還是更寬鬆的 `prev_close > prior_high_60`？

---

## P03: 多頭吞噬 / bull_engulfing

- **Source**: 第 02 篇同上
- **Direction**: bull
- **Signal Class**: exit（空單回補） / context_only — 課程強調**不是進場訊號**
- **K-bar 數量**: 2
- **識別規則**:
  1. 前一日黑 K：`prev_close < prev_open`
  2. 前一日黑 K **創新低**：`prev_low < prior_low_60.shift(1)`（或 `prev_low == prior_low_60`）
  3. 今日紅 K 實體包覆：`open ≤ prev_close AND close ≥ prev_open`
  4. **空方力竭背景**：MA60 向下 + 大盤悲觀（後者課程提到但無數字 → **[STUB-NEED-USER]**）
  5. **失效條件**：後續 `close < engulfing_bar_low` 則失效（再創新低 = 沒有力竭）
- **需要的 features**: 同 P02 + `prior_low_60`（已有）
- **建議放法**: 同 P02，`engulfing.py`
- **跨課程適用**: 是
- **不確定 / 缺資料**:
  - 「大盤悲觀」是否要做 cross-market filter（**[STUB-NEED-USER]**）
  - 是否要求 `is_in_breakdown_pattern == True` 作 proxy？

---

## P04: 母子晨星 / morning_star_harami

- **Source**: 第 03 篇《孕線：母子晨星》（978854A6B0757492FB6A99F8E92A41EC）
- **Direction**: bull
- **Signal Class**: exit（空單回補）
- **K-bar 數量**: 2
- **識別規則**（課程明示定義）:
  1. **空方力竭背景**：股價先空頭 + 創新低（黑 K 是破底長黑）。`prev_low <= prior_low_60.shift(1)` AND `prev_close < prev_open`
  2. 前一日為長黑 K：`(prev_open - prev_close) / prev_open ≥ 力量型門檻`（**[STUB-NEED-USER]**）
  3. 今日為紅 K 孕線：`is_red AND high ≤ prev_high AND low ≥ prev_low`
  4. **今日收盤站在前日黑 K 中值之上**：`close ≥ (prev_open + prev_close) / 2`
- **需要的 features**: 力量型 K 線；harami bool
- **建議放法**: `scripts/kline/patterns/morning_star.py`
- **跨課程適用**: 是
- **不確定**: 「低檔」如何判斷 — 用 `prev_low == prior_low_60`？或更寬鬆 `close < ma60 AND ma60 declining`？（**[STUB-NEED-USER]**）

---

## P05: 高檔吊首 / hanging_man（高檔下影線）

- **Source**: 第 04 篇《高檔下影線：高檔吊首》（666C90D7BC58F0E0E9629CAD711FD56F）
- **Direction**: bear
- **Signal Class**: exit（多單出場）
- **K-bar 數量**: 2（吊首 K + 確認日）
- **識別規則**:
  1. **多方力竭背景**：股價先「明顯拉抬」（**[STUB-NEED-USER]**：「明顯」課程無數字；建議 `close > prior_high_60` 或近 20 日漲幅 ≥ X%）
  2. 前一日為 T 字 / 近 T 字線（紅黑不論）：
     - `prev_lower_shadow ≥ 2 * prev_body_abs`（下影線長）
     - `prev_upper_shadow ≤ 0.3 * prev_body_abs` 或近零（上影線小）
     - **[STUB-NEED-USER]** 上述 2x、0.3x 為提議數字
  3. 確認：今日為日落 `high < prev_high AND low < prev_low` 或今日 `open < prev_low`（向下跳空）
  4. **排除條件（課程明示）**：若隔日創新高（突破吊首 K 高點）則無此意義 → 「避免日出攻擊狀態被限制」
  5. **排除條件**：正在日出攻擊進行中時不適用（features.py `attack_intensity == 4` 時排除）
- **需要的 features**: prev_lower_shadow, prev_upper_shadow, prev_body_abs（已有 today 版，需 shift(1)）; attack_intensity（已有）
- **建議放法**: `scripts/kline/patterns/hanging_man.py`
- **跨課程適用**: 是
- **不確定**:
  - T 字線下影線 vs 實體比例的數字（**[STUB-NEED-USER]**）
  - 「高檔」定義（**[STUB-NEED-USER]**）

---

## P06: 母子雙星 / harami_double_star（三根版的母子晨星）

- **Source**: 第 05 篇《母子雙星》（8303539A2CA4AC0E8FEB24E68BABF933）
- **Direction**: bull
- **Signal Class**: exit（空單回補）
- **K-bar 數量**: 3
- **識別規則**:
  1. 第 1 日：低檔長黑 + 創新低（同 P04 條件 1, 2）
  2. 第 2 日：紅 K 孕線（同 P04 條件 3），但 **收盤未站上中值**：`close < (open_d1 + close_d1) / 2`
  3. 第 3 日：收盤站上 D1 中值：`close ≥ (open_d1 + close_d1) / 2`
  4. **強烈訊號變體**：第 3 日 `open > prev_high`（向上跳空），缺口越大力量越強
- **需要的 features**: 同 P04 + shift(2) 版本
- **建議放法**: `scripts/kline/patterns/morning_star.py`（與 P04 同檔，提供 `detect_double_star`）
- **跨課程適用**: 是
- **不確定**: 同 P04

---

## P07: 大敵當前 / enemy_at_gate

- **Source**: 第 06 篇《大敵當前》（AF12D42CF0CF4600F29D9C4ACA41C5B7）
- **Direction**: bear
- **Signal Class**: exit（多單出場） — 也是 `scripts/kline/exit/reversal_k/enemy_at_gate.py` 的目標
- **K-bar 數量**: 4（長紅 + 兩根拉不開的紅 K + 跌破中值的黑 K）
- **識別規則**:
  1. **遇壓背景**（注意：不是創新高的力竭，是反彈遇前壓）：股價接近 / 觸及前波高點壓力區 → `close 接近 prior_high_60` 或 `overhead_supply_layer > 0`
  2. D-3：長紅 K（力量型紅 K）：`is_red AND body_pct ≥ 力量門檻`
  3. D-2, D-1：兩根紅 K，**沒有把行情拉開**：`high_{D-2} 與 high_{D-1} 都未顯著突破 high_{D-3}`，例如 `max(high_{D-2}, high_{D-1}) - high_{D-3} < 0.5% * high_{D-3}`（**[STUB-NEED-USER]** 拉不開的數字）
  4. D-0：跌破 D-3 長紅中值：`close < (open_{D-3} + close_{D-3}) / 2`（課程明示「跌破中值已算第三天無力，不需等收盤」）
  5. **變形版**（重意不重形）：拉不開的紅 K 不一定是兩根，三根也算；中值未破但**跳空缺口被跌破**也算
- **需要的 features**: prior_high_60, overhead_supply_layer, 力量型 K 線
- **建議放法**: `scripts/kline/patterns/enemy_at_gate.py`，同步替換 `scripts/kline/exit/reversal_k/enemy_at_gate.py` STUB
- **跨課程適用**: 是
- **不確定**:
  - 「拉不開」的數字門檻（**[STUB-NEED-USER]**）
  - 「遇壓」的數字定義（用 overhead_supply_layer 或 close 距 prior_high 的距離）
  - 是否要求 2 根還是允許 2-4 根變形版

---

## P08: 暗夜雙星 / dark_night_two_star

- **Source**: 第 07 篇《暗夜雙星》（426EAB98127A5370FC83CB5983BDA385）
- **Direction**: bear
- **Signal Class**: exit
- **K-bar 數量**: 3
- **識別規則**:
  1. **多方力竭背景**：股價先大幅拉抬 + 創新高
  2. D-2, D-1：兩根**型態相似併排 K 線**（通常紅 K，課程沒嚴格紅黑）—「相似」可定義為 `|high_{D-2} - high_{D-1}| / high_{D-1} < 0.3%` 且 `|low_{D-2} - low_{D-1}| / low_{D-1} < 0.3%`（**[STUB-NEED-USER]** 相似度門檻）
  3. D-0：長黑 K 跌破兩根併排的低點：`is_black AND close < min(low_{D-2}, low_{D-1}) AND body_pct ≥ 力量門檻`
  4. **強烈訊號變體**：若 D-0 黑 K 同時實體包覆 D-1 → 同時成立空頭吞噬 + 暗夜雙星，雙重訊號
- **需要的 features**: 力量型 K 線；併排相似度
- **建議放法**: `scripts/kline/patterns/dark_night_two_star.py`
- **跨課程適用**: 是
- **不確定**: 併排「相似」數字（**[STUB-NEED-USER]**）

---

## P08b: 遇壓跳空 / overhead_resistance_gap（暗夜雙星附帶概念）

- **Source**: 第 07 篇附帶 + 第 08 篇延伸
- **Direction**: bear
- **Signal Class**: exit
- **K-bar 數量**: 2+
- **識別規則**:
  1. 股價上漲一段後遇前波高點壓力（`overhead_supply_layer.shift(1) > 0`）
  2. 出現紅 K 之後，幾日內出現向下跳空缺口：`high < prev_low`
  3. 不限制紅 K 後第幾天（課程說「四根 K 線都沒上去越過前壓，然後出現往下跳空」）
- **需要的 features**: overhead_supply_layer（已有）
- **建議放法**: `scripts/kline/patterns/resistance_gap_down.py` — 或合併到 gap_reversal
- **跨課程適用**: 是
- **不確定**: 紅 K 到跳空之間允許幾天

---

## P09: 跳空反轉 / gap_down_reversal

- **Source**: 第 08 篇《跳空反轉》（92E64EAB9982ADE91CB903046E5FA04F）
- **Direction**: bear
- **Signal Class**: exit
- **K-bar 數量**: 3（紅 K + 黑 K 或孕線 + 跳空黑 K）
- **識別規則**:
  1. **多方力竭或遇壓**：D-2 是創新高的紅 K 或長紅
  2. D-1：黑 K 或孕線黑 K（也可以是日出但收黑）
  3. D-0：開盤向下跳空：`open < prev_low`，且收盤無力回補：`close < prev_low`
  4. 缺口越大越強（量化：`(prev_low - open) / prev_low`）
- **需要的 features**: 已有 prev_low；缺口大小
- **建議放法**: `scripts/kline/patterns/gap_reversal.py`，提供 `detect_down`, `detect_up`
- **跨課程適用**: 是
- **不確定**: D-1 是否必要為黑 K — 課程說「也可能是孕線黑 K」，較寬鬆

---

## P10: 雙鴉躍空 / two_crows_gap

- **Source**: 第 09 篇《雙鴉躍空》（13041D9897DBD12852724CAD0D994486）
- **Direction**: bear
- **Signal Class**: exit
- **K-bar 數量**: 4（紅 K + 兩根黑 K + 跳空黑 K）
- **識別規則**:
  1. **遇壓背景**（不一定創新高）：`overhead_supply_layer > 0` 或 close 接近 prior_high
  2. D-3：紅 K，且開高（`open > prev_close`）
  3. D-2, D-1：兩根黑 K 併排（雙鴉），可以是短黑 K 或十字線
  4. D-0：開盤跳空向下：`open < prev_low`（**這是確認點**）
  5. **失敗條件**：若 D-0 開高拉長紅，變成「上升三法」，方向相反 → 不可只看雙黑就提前反應
- **需要的 features**: overhead_supply_layer
- **建議放法**: `scripts/kline/patterns/two_crows_gap.py`
- **跨課程適用**: 是
- **不確定**: 「雙鴉」黑 K 可否含短 K 線 / 十字線（課程文字說可以，需 user 確認彈性）

---

## P11: 突破雙星 / breakout_two_star（低檔築底突破）

- **Source**: 第 10 篇《突破雙星》（EDFE0FB85503F88DFB6696C9EACA00D4）
- **Direction**: bull
- **Signal Class**: exit（空單回補） / 弱勢進場觀察
- **K-bar 數量**: 4（兩根併排 + 突破紅 K + 確認日）
- **識別規則**:
  1. **低檔整理背景**：股價先空頭趨勢（MA60 向下 + 創新低過）然後進入狹幅整理
  2. D-3, D-2：兩根併排 K 線（型態類似 P08 的併排判斷）
  3. D-1：紅 K 突破兩根併排高點：`close > max(high_{D-3}, high_{D-2})`
  4. D-0：**隔日跳空向上確認**：`open > prev_high`（課程強調沒有跳空就沒意義）
  5. **失敗條件**：D-0 又回到併排區間 → 失敗
- **需要的 features**: 同 P08 + 跳空
- **建議放法**: `scripts/kline/patterns/breakout_two_star.py`
- **跨課程適用**: 是
- **不確定**:
  - 「低檔」量化（**[STUB-NEED-USER]**）— 用 `is_in_breakdown_pattern.shift(N)` 過？
  - 跳空缺口大小要求

---

## P12: 夜星棄嬰 / evening_star_abandoned

- **Source**: 第 11 篇《夜星棄嬰》（3F9C5C8C7B81C89FBCA2970EF1855997）
- **Direction**: bear
- **Signal Class**: exit
- **K-bar 數量**: 3
- **識別規則**:
  1. **遇壓或多方力竭背景**：股價漲勢後遇前波壓力（或創新高）
  2. D-2：長紅 K（力量型紅 K）
  3. D-1：小紅 / 小黑 / 十字線（醞釀 K）— `body_pct < 0.5%` 或 features.py `is_doji`
  4. D-0：**收盤跌破 D-2 紅 K 中值**：`close < (open_{D-2} + close_{D-2}) / 2`
  5. 強烈訊號：D-1 與 D-2 之間 / D-1 與 D-0 之間有對稱跳空缺口（傳統夜星型態 = 島狀反轉）
- **需要的 features**: is_doji（已有）, 力量型 K 線
- **建議放法**: `scripts/kline/patterns/evening_star.py`
- **跨課程適用**: 是
- **不確定**: 是否要求十字線必須 strict doji，或允許短 K 線

---

## P13: 夜星 + 島狀反轉（高檔） / island_reversal_bear

- **Source**: 第 12 篇《夜星與島狀反轉》（6C03240289991A8B7F5D99C5DC2409D5）
- **Direction**: bear
- **Signal Class**: exit
- **K-bar 數量**: 3+
- **識別規則**:
  1. **多方力竭背景**：股價先大幅拉抬
  2. **左缺口**：D-K 日有向上跳空 `low_{D-k} > high_{D-k-1}`，k ≥ 2
  3. **島中 K 線**：中間 1 根十字線（夜星）/ 1 根實體 K 線（孤島）/ 多根 K 線（島狀反轉），整體最低點未跌破左缺口的 `prev_high`
  4. **右缺口**：D-0 向下跳空 `high < prev_low`
  5. 比較常用版本：**只看右側向下跳空**就足夠（「重意不重形」課程明示）
- **需要的 features**: 跳空判定
- **建議放法**: `scripts/kline/patterns/island_reversal.py`（提供 bull/bear）
- **跨課程適用**: 是
- **不確定**: 中間允許 K 線數上限（**[STUB-NEED-USER]** — 課程未明示，建議 ≤ 10 天，超過就純粹當壓力判定）

---

## P14: 晨星 + 島狀反轉（低檔） / island_reversal_bull

- **Source**: 第 13 篇《晨星與島狀反轉》（29F3734E9FE458A7138B770EB29C29F8）
- **Direction**: bull
- **Signal Class**: exit（空單回補） — 課程明示**不是進場訊號**
- **K-bar 數量**: 3+
- **識別規則**:
  1. **空方力竭背景**：MA60 down + 創新低過
  2. 左缺口：向下跳空（`high < prev_low`），k 天前
  3. 中間：十字線 / 孤島 / 多根 K 線，整體最高點未越過左缺口的 `prev_low`
  4. 右缺口：向上跳空 `low > prev_high`
  5. **失敗條件（課程明示）**：右缺口隔天又被回補（`close < gap_open`），或上去馬上遇到套牢區（`overhead_supply_layer > 0` after gap） → 失敗
- **需要的 features**: 同 P13 + overhead_supply_layer
- **建議放法**: 同 P13
- **跨課程適用**: 是
- **不確定**: 失敗判定要不要納入主 detect 還是另開 `detect_with_failure_check`（**[STUB-NEED-USER]**）

---

## P15: 外側三黑 / outside_three_black

- **Source**: 第 14 篇《黑三兵與外側三黑》（71B4F99819BB5207A78994BEC40FC79D）
- **Direction**: bear
- **Signal Class**: exit
- **K-bar 數量**: 4（創新高紅 K + 三根連續黑 K）
- **識別規則**:
  1. D-3：創新高的紅 K：`close > prior_high_60 AND is_red`
  2. D-2, D-1, D-0：連續三根黑 K：`is_black` × 3
  3. D-2 與 D-1 之間**沒有向下跳空缺口**（否則已成立跳空反轉，不需等三根）：`high_{D-1} ≥ low_{D-2}`
  4. 三根黑 K 之後 D-3 紅 K 低點被跌破（自然推論）：`close_{D-0} < low_{D-3}` 或 `min(low_{D-2:D-0}) < low_{D-3}`
  5. 通常出現於「長期緩漲、冷門 / 高價股」（無 vectorized 條件可加 — 留註解）
- **需要的 features**: prior_high_60, is_red, is_black
- **建議放法**: `scripts/kline/patterns/outside_three_black.py`
- **跨課程適用**: 是
- **不確定**: 是否要求 D-3 紅 K 低點被跌破（課程示意圖如此但未明文）

---

## P16: 空方單日反轉 / bearish_one_day_reversal

- **Source**: 第 15 篇《空方單日反轉》（5FCAA3846B5C453F95D59CBFE7ECEE20）
- **Direction**: bear
- **Signal Class**: exit
- **K-bar 數量**: 2 + 確認日
- **識別規則**（課程明示）:
  1. **多方持續背景**：前一段持續上漲
  2. D-1：紅 K，且 `high_{D-1} == prior_high_60` 或創新高
  3. D-0：黑 K，當日股價曾觸 / 超過 D-1 高（`high_{D-0} > high_{D-1}` 也可），但**收盤價低於 D-1 最高價**：`close < high_{D-1}`
  4. **確認方式（取一）**：
     - (a) D+1 出現日落（`high_{D+1} < high_{D-0} AND low_{D+1} < low_{D-0}`）
     - (b) D+1 向下跳空（→ 已成立跳空反轉 P09）
     - (c) D-0 當日伴隨**利多消息**（無法 vectorized — 留註解，需外部 news feed）**[STUB-NEED-USER]**
     - (d) D-0 後續形成外側三黑 P15
- **需要的 features**: prior_high_60
- **建議放法**: `scripts/kline/patterns/one_day_reversal.py`（提供 bull/bear）
- **跨課程適用**: 是
- **不確定**: 課程明示這是「最微弱的轉折組合」，需多種輔助；要不要 detect 預設帶 (a) 條件還是只回傳「形狀符合」並讓上層 ORing？（**[STUB-NEED-USER]**）

---

## P17: 多方單日反轉 / bullish_one_day_reversal

- **Source**: 第 16 篇《多方單日反轉》（9D8B76607439F24FB8AD2026044D988B）
- **Direction**: bull
- **Signal Class**: exit（空單回補） — 課程明示**絕對不是買進訊號**
- **K-bar 數量**: 2 + 確認
- **識別規則**:
  1. **空方持續背景**：前一段持續下跌
  2. D-1：長黑 K 或跳空下跌黑 K，且 `low_{D-1} == prior_low_60` 或創新低
  3. D-0：紅 K，當日創新低後拉回，**收盤價高於 D-1 最低點**：`close > low_{D-1}`，且 `low_{D-0} < low_{D-1}`（盤中曾破低）
  4. **確認**：
     - (a) D+1 日出：`high_{D+1} > high_{D-0} AND low_{D+1} > low_{D-0}`
     - (b) D-0 接近多頭吞噬：實體包覆 D-1 但高點未過 → 較強訊號
     - (c) D-0 當日有利空（無法 vectorized）
  5. **使用警語**：課程明示「只能等不再破底，不可當買點」
- **需要的 features**: prior_low_60
- **建議放法**: 同 P16
- **跨課程適用**: 是
- **不確定**: 同 P16

---

# 【非轉折組合補充篇】10 個

主要 Signal Class 為 **context_only**（用於力量變化判斷，非單獨進出場訊號）。

---

## P18: 非轉折組合前言（context_only）

- **Source**: 第 17 篇（24890BBD457BF5A2E1B0A8E33390DDA6）
- **Direction**: both
- **Signal Class**: context_only
- 內容：K 線分類 — 漲勢中 / 跌勢中 / 盤整中；力量型 / 戰鬥型 / 醞釀型；MACD 輔助說明
- **建議放法**: 註解到 `patterns/__init__.py`

---

## P19: 包覆型態（無力竭背景的吞噬）/ engulfing_pattern_neutral

- **Source**: 第 18 篇《包覆型態》（2BA211D9CB1514E34D087249F9D627B7）
- **Direction**: both
- **Signal Class**: context_only
- **K-bar 數量**: 2
- **識別規則**:
  1. 同 P02/P03 包覆條件（實體包覆），但**沒有力竭背景**
  2. 包覆者必須是力量型 K 線
  3. **時機加強**：若前一根有利多 / 利空、且包覆 K 有量 → 力量意義更大（量化：`volume > avg_volume_20 * 1.5`，**[STUB-NEED-USER]** 量比門檻）
- **需要的 features**: 同 P02 + volume_ratio（已有）
- **建議放法**: `engulfing.py` 增加 `detect_neutral_engulfing(df)`
- **跨課程適用**: 是 — 主力大會把這視為「短期力量轉變」，需配合分點才有意義

---

## P20: 貫穿型態 / piercing_pattern（含烏雲罩頂、曙光乍現）

- **Source**: 第 19 篇《貫穿型態》（53E0BA326CBB753118E3F8C6232F7F0F）
- **Direction**: both
- **Signal Class**: context_only
- **K-bar 數量**: 2
- **識別規則**:
  - **烏雲罩頂（多方狀態的貫穿黑 K）**：
    1. 多方趨勢中（`close > ma60 AND ma60 rising`）
    2. D-1：紅 K，創新高：`prev_close > prior_high_60.shift(1)`
    3. D-0：黑 K，開高（`open > prev_close` 或 `open > prev_high`）但收盤跌破 D-1 中值：`close < (prev_open + prev_close) / 2`
    4. 注意：**沒到吞噬程度**（`close > prev_open`）
  - **曙光乍現（空方狀態的貫穿紅 K）**：
    1. 空方趨勢中
    2. D-1：黑 K，創新低
    3. D-0：紅 K，開低，但收盤站上 D-1 中值：`close > (prev_open + prev_close) / 2`，且 `close < prev_open`
- **需要的 features**: prior_high_60 / prior_low_60, ma60
- **建議放法**: `scripts/kline/patterns/piercing.py`
- **跨課程適用**: 是

---

## P21: 懷抱型態 / harami_neutral（無力竭背景的孕線）

- **Source**: 第 20 篇《懷抱型態》（161D653D96BB64939DE424B8B5162815）
- **Direction**: both
- **Signal Class**: context_only
- **K-bar 數量**: 2
- **識別規則**:
  1. 前一根是力量型 K 線（長紅 / 長黑）
  2. 隔日是醞釀型短 K 線（孕線：`high ≤ prev_high AND low ≥ prev_low`，且 `body_pct < 0.5%` 或近 doji）
  3. 紅黑顏色組合不限 — 重點是「力量型 + 醞釀」
- **需要的 features**: 力量型 K 線, harami bool
- **建議放法**: `scripts/kline/patterns/harami.py`
- **跨課程適用**: 是

---

## P22: 遭遇型態 / meeting_lines

- **Source**: 第 21 篇《遭遇型態》（4A2519730555027A6612FC9C77BE51FB）
- **Direction**: both
- **Signal Class**: context_only
- **K-bar 數量**: 2
- **識別規則**:
  1. 前一日是力量型 K 線（長紅或長黑），且帶跳空缺口（多方時為攻擊跳空 / 空方時為跳空下跌）
  2. 今日收盤價 **等於** 前一日收盤價：`abs(close - prev_close) / prev_close < 0.001`（允許微小誤差 — **[STUB-NEED-USER]** 容差）
  3. 顏色相反（多方時今日為黑、空方時今日為紅）
  4. 實際意義：缺口封閉（attack gap filled）
- **需要的 features**: 力量型 K 線
- **建議放法**: `scripts/kline/patterns/meeting_lines.py`
- **跨課程適用**: 是
- **不確定**: 收盤完全相等過於嚴格；容差數字（**[STUB-NEED-USER]**）

---

## P23: 反撲型態 / counterattack_pattern

- **Source**: 第 22 篇《反撲型態》（207FAB90A1222E9DCD7CCE2A26AB19B7）
- **Direction**: both
- **Signal Class**: context_only
- **K-bar 數量**: 2
- **識別規則**:
  - **空方趨勢反撲（多方反撲）**：
    1. 跌勢中：D-1 黑 K 創短期新低
    2. D-0 為紅 K，**開盤就站上 D-1 開盤 / 之上**：`open ≥ prev_open`（甚至 `open > prev_high` 跳空 = 更強）
    3. D-0 完全位於 D-1 之上（`low > prev_close` 強版本）
  - **多方趨勢反撲（空方反撲）**：
    1. 漲勢中：D-1 紅 K 創新高
    2. D-0 為黑 K，**開盤就跌破 D-1 開盤 / 之下**：`open ≤ prev_open`（`open < prev_low` 為更強跳空版）
    3. D-0 完全位於 D-1 之下
  - 區分於吞噬：吞噬是收盤實體包覆；反撲關鍵在**開盤就直接反向**
  - **失效**：若反撲伴隨「利多 / 利空消息」效果會消失（無法 vectorized）
- **需要的 features**: 已有
- **建議放法**: `scripts/kline/patterns/counterattack.py`
- **跨課程適用**: 是

---

## P24: 內困型態 / internal_trap（內困翻紅 / 翻黑）

- **Source**: 第 23 篇《內困型態》（EBD01861796168390992499149DFE0EE）
- **Direction**: both
- **Signal Class**: context_only
- **K-bar 數量**: 3
- **識別規則**:
  - **內困翻黑**：
    1. D-2：漲勢中創新高的力量型紅 K
    2. D-1：孕線（高低點都在 D-2 內），醞釀型
    3. D-0：黑 K 跌破 D-2 紅 K 低點：`close < low_{D-2}`
  - **內困翻紅**：方向相反，D-2 跌勢創新低的力量型黑 K，D-1 孕線，D-0 紅 K 突破 D-2 黑 K 高點
  - 課程明示：與母子晨星 / 雙星很像但**沒有力竭背景**，所以是 context only
- **需要的 features**: 同 P04 / P21
- **建議放法**: `scripts/kline/patterns/internal_trap.py`
- **跨課程適用**: 是

---

## P25: 咬定型態 / determined_break

- **Source**: 第 24 篇《咬定型態》（A5C5E3F242DCE38F0E9061E3FBC85B81）
- **Direction**: both
- **Signal Class**: context_only / entry-support（多方咬定可作為主力大「整理完突破」訊號）
- **K-bar 數量**: 1 + 整理背景
- **識別規則**:
  - **多方咬定**：
    1. **過去 ≥ 5 根 K 線狹幅整理**：`(max(high[-5:-1]) - min(low[-5:-1])) / mean(close[-5:-1]) < 3%`（**[STUB-NEED-USER]** 狹幅門檻）
    2. 今日為力量型紅 K：`is_red AND body_pct ≥ 力量門檻`
    3. 今日突破整理區高點：`close > max(high[-5:-1])`
  - **空方咬定**：方向反相 — 整理區 + 力量型黑 K + 跌破低點
- **需要的 features**: rolling high/low; 力量型 K 線
- **建議放法**: `scripts/kline/patterns/determined_break.py`
- **跨課程適用**: 是
- **不確定**: 「狹幅」「至少一週」的具體天數和幅度（**[STUB-NEED-USER]**）

---

## P26: 升降組合型態 / step_up_down（上升 / 下降一階）

- **Source**: 第 25 篇《升降組合型態》（0B1DD310D7685EE74123E5147BB7CFB2）
- **Direction**: both
- **Signal Class**: context_only
- **K-bar 數量**: 多（力量 K + 整理 + 同向力量 K）
- **識別規則**:
  - **上升一階**：
    1. 之前出現過力量型紅 K
    2. 後續 N 天狹幅整理（同 P25）
    3. 今日再出現一根同向力量型紅 K 並突破整理高點
  - 與咬定型態的差異：升降「之前先有一根原本方向的力量 K」
- **需要的 features**: 同 P25 + 力量 K 歷史標記
- **建議放法**: 可併入 `determined_break.py` 或單獨 `step_pattern.py`
- **跨課程適用**: 是
- **不確定**: 之前那根力量 K 的時間窗（多久前算數）（**[STUB-NEED-USER]**）

---

## P27: 上下缺回補 / gap_fill_pattern

- **Source**: 第 26 篇《上下缺回補型態組合的輔助》（5CB9CD820B2BEF0AC861FFEDB89CD6B0）
- **Direction**: both
- **Signal Class**: context_only
- **K-bar 數量**: 2-5
- **識別規則**:
  - **向上缺口被回補（多方力量消失）**：
    1. N 日前出現向上跳空：`low_{D-N} > high_{D-N-1}`
    2. 今日 close 回補缺口：`close < high_{D-N-1}` 或 `low < high_{D-N-1}`
    3. 攻擊跳空被回補意義更大（features.py `attack_intensity.shift(N) == 3`）
  - **向下缺口被回補（空方力量消失）**：
    1. N 日前出現向下跳空：`high_{D-N} < low_{D-N-1}`
    2. 今日 close > 缺口頂：`close > low_{D-N-1}` 或 `high > low_{D-N-1}`
  - N 通常 ≤ 5（短期內回補才有意義 → **[STUB-NEED-USER]** N 上限）
- **需要的 features**: features.py 已有 unfilled_gap_down_count_240d 邏輯類似，可衍生 attack_gap 標記（需新增 `recent_attack_gap_filled` / `recent_gap_down_filled`）
- **建議放法**: `scripts/kline/patterns/gap_fill.py`
- **跨課程適用**: 是
- **不確定**: N 上限（**[STUB-NEED-USER]**）

---

# 整體建議

## Pattern 總數彙整

| 編號 | Slug | 方向 | 類別 | 課程清晰度 |
|---|---|---|---|---|
| P02 | bear_engulfing | bear | exit | 高 |
| P03 | bull_engulfing | bull | exit | 高 |
| P04 | morning_star | bull | exit | 高（中值明確） |
| P05 | hanging_man | bear | exit | 中（T 字定義模糊）|
| P06 | harami_double_star | bull | exit | 高 |
| P07 | enemy_at_gate | bear | exit | 中（拉不開模糊）|
| P08 | dark_night_two_star | bear | exit | 中（併排相似度）|
| P08b | resistance_gap_down | bear | exit | 中 |
| P09 | gap_down_reversal | bear | exit | 高 |
| P10 | two_crows_gap | bear | exit | 高 |
| P11 | breakout_two_star | bull | exit | 中（低檔模糊）|
| P12 | evening_star | bear | exit | 高 |
| P13 | island_reversal_bear | bear | exit | 高 |
| P14 | island_reversal_bull | bull | exit | 高 |
| P15 | outside_three_black | bear | exit | 高 |
| P16 | bearish_one_day_reversal | bear | exit | 低（需外部輔助）|
| P17 | bullish_one_day_reversal | bull | exit | 低 |
| P19 | engulfing_pattern_neutral | both | context | 高 |
| P20 | piercing_pattern | both | context | 高 |
| P21 | harami_neutral | both | context | 高 |
| P22 | meeting_lines | both | context | 中（容差）|
| P23 | counterattack_pattern | both | context | 高 |
| P24 | internal_trap | both | context | 高 |
| P25 | determined_break | both | both | 中（狹幅模糊）|
| P26 | step_up_down | both | context | 中 |
| P27 | gap_fill_pattern | both | context | 中 |

共 **26 個可實作 pattern**（P01 / P18 是 context 篇，無單獨型態）。

- **可直接 vectorized pandas 寫**：21 個（規則明確）
- **需 STUB-NEED-USER 拍板數字**：12 個（標 `[STUB-NEED-USER]`）

---

## 提議的目錄結構

```
scripts/kline/patterns/
├── __init__.py                 # 公開 detect API + 設計原則 docstring
├── _common.py                  # 共用 helpers: is_power_bar(), is_harami(), is_sunset_bar() 等
├── engulfing.py                # P02 bear / P03 bull / P19 neutral
├── morning_star.py             # P04 / P06 (harami_double_star)
├── evening_star.py             # P12
├── hanging_man.py              # P05
├── enemy_at_gate.py            # P07（同步替換 exit/reversal_k/enemy_at_gate.py STUB）
├── dark_night_two_star.py      # P08
├── gap_reversal.py             # P09 / P08b resistance_gap_down
├── two_crows_gap.py            # P10
├── breakout_two_star.py        # P11
├── island_reversal.py          # P13 bear / P14 bull
├── outside_three_black.py      # P15
├── one_day_reversal.py         # P16 bear / P17 bull
├── piercing.py                 # P20（dark_cloud / piercing_line）
├── harami.py                   # P21
├── meeting_lines.py            # P22
├── counterattack.py            # P23
├── internal_trap.py            # P24
├── determined_break.py         # P25 + P26 step_up_down
└── gap_fill.py                 # P27
```

### 升級既有 STUB

- `scripts/kline/entry/trend_reversal.py` STUB → 升級為「組合多個 bull pattern detect 結果」的 wrapper（P03 + P04 + P14 + P17 OR + 必要的趨勢確認）
- `scripts/kline/exit/reversal_k/enemy_at_gate.py` STUB → 直接搬 patterns/enemy_at_gate.py 的 mark 版本

---

## 與主力大課程整合方式

`patterns/` 是 **pure 型態識別**，不含「該不該買 / 該不該賣」的語意層判斷。整合方式：

```python
# K 線力量 scanner
from scripts.kline.patterns import morning_star, bull_engulfing
entries = morning_star.detect(enriched_bars) | bull_engulfing.detect(enriched_bars)
# 再加 K 線力量課程的「化解賣壓 + MA60」filter

# 主力大 scanner
from scripts.kline.patterns import bear_engulfing
exits_for_teacher_picks = bear_engulfing.detect(enriched_bars) & teacher_holding_filter
# 用 patterns 做技術面 trigger，再疊主力大的 broker_activity / teacher_say filter
```

兩條 pipeline 共用同一份 enriched bars 與 features，**零重複計算**。

---

## features.py 需新增的欄位

| Feature | 用途 | Pattern |
|---|---|---|
| `is_power_red`, `is_power_black` | 力量型紅黑 K（body_pct 相對門檻 + ATR-normalized）| 所有 |
| `is_harami` | 高低點皆在前日範圍 | P04, P06, P21, P24 |
| `is_sunset_bar` | high < prev_high AND low < prev_low | P05, P16 |
| `midpoint` | (open + close) / 2 | P04, P06, P07, P12, P20 |
| `gap_up_today`, `gap_down_today` | open > prev_high / high < prev_low | P09, P10, P13, P14, P22, P27 |
| `recent_attack_gap_filled` | 過去 N 天攻擊跳空被回補 | P27 |
| `recent_gap_down_filled` | 過去 N 天向下跳空被回補 | P27 |
| `narrow_range_bar_count_5d` | 過去 5 日狹幅整理檢測 | P25, P26 |
| `bull_exhaustion_context`, `bear_exhaustion_context` | 力竭背景 flag（可組合 attack_intensity, is_in_breakdown_pattern）| 所有轉折篇 |

---

## 需 user 拍板的關鍵決策（5 個）

1. **「力量型 K 線」的數字定義**（影響 P02, P05, P07, P08, P11, P12, P19, P20, P21, P22, P25, P26 — 12 個 pattern 共用）— 提議：`body_pct ≥ percentile_70(body_pct, 20d)` AND `body_pct ≥ 1.5%` 兩條同時。請 user 拍板百分位 / 絕對門檻。

2. **「力竭背景」的具體 detection**（影響全部轉折篇 16 個 pattern）：
   - 多方力竭：`close > prior_high_60` 還是 + 「近 N 日漲幅 ≥ X%」？
   - 空方力竭：用 features.py `is_in_breakdown_pattern` 還是更寬鬆 `ma60 declining + 近期創新低`？
   - 「相對高 / 低檔」是否需大盤背景 filter（多方時加上「大盤多頭」、空方時加上「大盤悲觀」）？

3. **失效條件是否內建到 detect()**：例如 P02 黑吞噬「之後再創新高就失效」、P14 多方島狀反轉「右缺口被回補就失敗」。建議方案 A：detect 只回傳「當日形狀符合」的 bool series，失效判定放到上層 simulator；方案 B：另外提供 `detect_with_followup(df, lookahead_days)`。

4. **「單日反轉」(P16, P17) 是否實作**：課程明示「最微弱、需外部輔助、容易誤判」。建議方案：
   - A：只實作形狀 detect，由上層 OR 跳空反轉 / 外側三黑等強訊號使用
   - B：完全不做 detect，僅在 docs 內列為「應由人工判讀」
   - C：實作但 default 不上線（放 `extras/`）

5. **patterns/ 的 detect 回傳型別**：目前 entry/exit 都是 `pd.Series[bool]`。對於有強弱差別的型態（如雙星帶跳空 vs 沒跳空），是否要提供 `score(df) -> pd.Series[float]` 函式表示強度？建議：先全部都用 bool，強度交由 scoring/ 層次計算 — 但有些 pattern（P09 缺口大小、P13 中間 K 線數）天然有強弱維度，需確認。

---

## 暫時不做的範圍

- P01, P18 是觀念篇，不需 detect
- 課程明示「需要利多 / 利空消息」「需要成交量極端值（多空能量）」的輔助條件無法 vectorized — 留 docstring 註解
- 大盤背景 filter（如 P14 失敗條件「大盤悲觀」）需另開 cross-market feature，不放在 patterns/ 內
