# 「明日 K 線」INVENTORY（47 篇分類 + 實作規格草稿）

> 來源：PressPlay《K 線力量判斷入門》延伸講座「明日 K 線」增修版 47 篇
> 路徑：`docs/kline_course/mingri_kline/`
> 觀念定義：見 `DEFINITIONS.md`
> 分類框架：A 新型態 / B 進出場規則 / C 既有補充 / D 純觀念
> 嚴格：**不寫 code、不修現有 patterns/entry/exit**；本文件只整理

---

## 0. 分類分布

| 類別 | 數量 | 比例 | 說明 |
|---|---:|---:|---|
| **A — 新型態 / 新訊號**（可實作 patterns/）| 2 | 4% | 合併十字線、類外側三黑（外側三黑擴充）|
| **B — 進出場規則**（可實作 entry/ exit/）| 8 | 17% | 攻擊成本顯現/跌破、防守姿態、合併十字線後攻擊、不攻擊系列、創紀錄跌點之後…|
| **C — 既有 pattern/feature 補充**（修現有檔）| 14 | 30% | 既有 detect 邏輯的補充條件、屬性區分、組合運用 |
| **D — 純觀念 / 心法**（只寫 DEFINITIONS）| 23 | 49% | 沙盤推演、人性弱點、進場 vs 出場、下山、定義延伸 |

**重點結論**：明日 K 線 ≈ 「應變劇本層」(playbook layer)。**幾乎沒有獨立新型態**（只 1 個合併十字線 + 1 個外側三黑擴充）；大部分是既有概念的「隔日該如何看待」的劇本應變。

---

## 1. 共用術語（沿用 long_short_turning_point/PATTERN_INVENTORY.md 已建立的詞彙）

新增（明日 K 線獨有）：

- **攻擊意圖區 (intent zone)**：從低檔往上靠近前高的賣壓化解區段（突破前高之前）
- **攻擊企圖區 (intention zone)**：突破前高之後的價位區段（不可跌回意圖區）
- **攻擊成本 (attack cost)**：突破前高當日漲停鎖住、最大量在漲停價的價位
- **防守低點 (defensive low)**：股價在大盤悲觀期間明顯守住的價位（瀚荃 7d、潤泰新 6d）
- **明顯放量 (anomalous volume)**：本來無量，突然出現的大量；**[STUB-NEED-USER]** 數字定義
- **力量型 K 線 (power bar)**：沿用 long_short_turning_point 既有定義
- **剛創新高 (just-broke-high)**：今日或前 1~2 日為 60 日新高（合併十字線、抵抗意義都要用此位置條件）

---

# 【A 類】新型態 / 新訊號（2 個）

## A01: merged_doji — 合併十字線

- **Source**: 第 24 篇 / E9A6F935298C7C5C2E269AA952AA1BB2
- **Direction**: bull
- **Signal Class**: entry candidate (剛創新高位置 + 明日攻擊預期)
- **K-bar 數量**: 2 → 合併
- **識別規則**（老師明示）:
  1. **位置條件**：今日或前 1 日為剛創新高（`prev_high == prior_high_60` 或 `high == prior_high_60`）
  2. **K 棒組成**：兩根 K 線中，**一根有上影線、一根有下影線**
  3. **合併條件**：兩根合併後上影線 + 下影線形成「長十字線」
     - `merged_high = max(prev_high, high)`
     - `merged_low = min(prev_low, low)`
     - `merged_open = prev_open`
     - `merged_close = close`
     - 判定 = is_doji(merged_open, merged_close, merged_high, merged_low)
  4. **方向偏好**：先上影線、後下影線**力量意義最強**；先下影線、後上影線退化為「上影線單獨判斷」（已有 features）
- **不適用**（老師明示）:
  - 位置不對（兩根不在剛創新高）→ 沒有意義
- **建議放法**: `scripts/kline/patterns/merged_doji.py`（新增）
- **跨課程適用**: 是
- **不確定**: 無（老師定義清晰）

---

## A02: outside_three_black_like — 類外側三黑

- **Source**: 第 43 篇 / 3995DDF008E3E1B600A9D920E6FFC07C（補充說明段）
- **Direction**: bear
- **Signal Class**: exit / context（既有 outside_three_black.py 的擴充）
- **K-bar 數量**: 4~N
- **識別規則**（老師明示）:
  1. 前面有明確多方拉抬（power 紅 K 序列、漲幅 ≥ X% — 沿用既有 outside_three_black 力竭條件）
  2. **最近一根創新高紅 K 之後，連續 N 根黑 K (N ≥ 3)**
  3. **第 N 根黑 K 收盤跌破該最近一根紅 K 的低點**
  4. 老師範例展示 N=4、N=9 都成立（「外側九黑」也可叫「類外側三黑」）
- **建議放法**: 修改既有 `scripts/kline/patterns/outside_three_black.py`，把 N=3 hard-code 改成 N ∈ [3, M]（M 待定）— 詳見 C 類 C01
- **跨課程適用**: 是
- **不確定**: 連續黑 K 之間是否可容忍小紅 K（老師範例皆連續黑）→ 預設「全黑」

---

# 【B 類】進出場規則（8 個）

## B01: attack_cost_displayed_day — 攻擊成本顯現日 (entry)

- **Source**: 第 20 篇 / B44741FE824D0798CC91C1521D5B0FF7
- **Signal Class**: entry candidate
- **識別規則**（老師明示）:
  1. 突破前高（`high == prior_high_60` 或 close 創新高）
  2. 鎖住漲停（`close == limit_up_price` 且 `high == close`）
  3. **最大量就在漲停板價位**（盤中 tick 資料需求 — **[STUB-NEED-USER]** 退化版：`vol > vol_ma_20 * 1.5` 作為 proxy？）
- **明日 K 線判斷**：
  - 隔天**沒跌破攻擊成本** → 持續持有，等待跳空攻擊 / 推升攻擊
  - 隔天**跌破攻擊成本（隔天 low < 攻擊成本）** → 不攻擊（觸發 B02 exit）
- **不適用**（老師明示）:
  - 漲幅太大已脫離基本面、散戶不會回來買 → 不看攻擊成本
  - 利空當日突破 → 不用攻擊成本（強烈企圖）
- **建議放法**: `scripts/kline/entry/attack_cost_displayed.py`（新增）
- **不確定**: tick 級「最大量」需要 fubon api 分價量表（見 `reference_fubon_api`、`reference_finmind_api`）

---

## B02: attack_cost_break — 攻擊成本跌破 (exit)

- **Source**: 第 20 篇 + 第 28 篇 / E4383C1F106A64F729CAD12E0D4B25F2
- **Signal Class**: exit（短線價差交易者用）
- **識別規則**：
  1. 前日為 B01 攻擊成本顯現日
  2. 今日 close < 前日 close（漲停鎖住價）
- **建議放法**: `scripts/kline/exit/attack_cost_break.py`（新增）；標註「短線專用」，與 attack_assumption_break 並存
- **跨課程適用**: 是（主力大短線出場用）

---

## B03: merged_doji_attack — 合併十字線後攻擊企圖 (entry)

- **Source**: 第 24 篇
- **Signal Class**: entry
- **識別規則**：A01 合併十字線出現 → 隔日符合下列任一即觸發 entry
  - **跳空攻擊**：`open > prev_high`（其中 prev_high = 合併十字線的 merged_high）
  - **推升攻擊**：盤中 `high > 早盤第一個高點 (15min high)` → 退化版 `today_close > prev_high`
- **失效**：隔日 low < 合併十字線 merged_low → 不攻擊
- **建議放法**: `scripts/kline/entry/merged_doji_attack.py`（新增）
- **不確定**: 「早盤第一個高點」是 9:00~9:15 盤中資料 — 日 K 退化版需文件化

---

## B04: defensive_stance — 防守姿態 (entry / context)

- **Source**: 第 26 篇 / EF7308E2336BF7BCE94142944DB580B1
- **Signal Class**: entry candidate（大盤反彈日進場）
- **識別規則**（老師明示兩個必要條件）:
  1. **已有主力拉抬**：股價已創 60 日新高、近 N 日漲幅 ≥ X%（**[STUB-NEED-USER]**）
  2. **大盤悲觀期間股價守住某個價位**：近 5~10 日大盤跌幅 ≥ Y%，個股 `min(low_5d)` 對比前波低點未跌破
  3. **防守低點識別**：個股近 6~7 日 (`prior_low_7`) 低點
- **明日 K 線判斷**：
  - 大盤穩定當日 → 該股應出現攻擊企圖（跳空或推升攻擊）
  - 跌破防守低點 → 沒有防守，不進場
- **建議放法**: `scripts/kline/entry/defensive_stance_attack.py`（新增）
- **跨課程適用**: ⭐⭐ 是 — 跟主力大「站前哥/管錢哥 override」高度契合
- **不確定**: N、X、Y 數字（**[STUB-NEED-USER]**）

---

## B05: defensive_low_break — 防守低點跌破 (exit)

- **Source**: 第 26 篇
- **Signal Class**: exit
- **識別規則**：今日 close < B04 防守低點
- **建議放法**: `scripts/kline/exit/defensive_low_break.py`（新增）
- **跨課程適用**: 是

---

## B06: no_attack_after_breakout — 突破後不攻擊 (exit)

- **Source**: 第 28 篇 / E4383C1F106A64F729CAD12E0D4B25F2
- **Signal Class**: exit
- **識別規則**（三類）:
  1. **跳空攻擊缺口回補 + 跌破攻擊假設**：今日盤中曾跳空 → 回補 → close < 前日攻擊假設低點
  2. **高檔推升整理被一根長黑改變**：股價已維持高檔狹幅 N 日（推升低點）→ 一根黑 K close < min(prior_N_lows)
  3. **跌回攻擊意圖區**：close 跌回到突破前高之前的賣壓化解區段
- **建議放法**: `scripts/kline/exit/no_attack.py`（新增；或拆三個小檔）
- **不確定**: 「攻擊意圖區」邊界定義（賣壓化解的起點）→ 退化版用 `prior_high_60` 突破前 N 日的最低點

---

## B07: record_decline_then_no_new_low — 創紀錄跌點之後不再破底 (entry)

- **Source**: 第 30 篇 / 77DC434EC71DB04553752A44C9354680
- **Signal Class**: entry（價值投資 / 短線抄底）
- **識別規則**（老師明示）:
  1. 大盤（或個股）出現「創紀錄跌點」：單日跌幅 / 跌停家數 / 跌點 創歷史紀錄
  2. **隔日不再創新低**（隔日 low > 前日 low）
  3. 排除「本質非常爛的公司」（基本面 filter）
- **建議放法**: `scripts/kline/entry/record_decline_rebound.py`（新增）
- **跨課程適用**: 是 — 跟「打擊區哲學」高度契合
- **不確定**: 「創紀錄」定義 — 全市場歷史 max？近 5 年 max？（**[STUB-NEED-USER]**）

---

## B08: bullish_reversal_in_long_bear_market — 空頭買在趨勢改變 (entry)

- **Source**: 第 45、46 篇 / C160510B27C815265E2B0DD319101A7A、37BCA73C79C3970B05E6AC9A17FAE417
- **Signal Class**: entry（投資目的，非短線）
- **識別規則**（老師明示）:
  1. **背景條件**：大盤已走空 ≥ 3 個月（or 個股已走空 ≥ 3 個月）
  2. **多方轉折組合出現**：multipler — 母子晨星、紅 K 吞噬、孤島型態、母子雙星 之一（皆已實作於 `patterns/`）
  3. **基本面 filter**：股價低於應有價值（EPS、本益比 — 跨資料源 filter）
  4. **失效（停損）**：再破底（close < 多方轉折組合的最低點）
- **建議放法**: 不新增 entry；放在 `scripts/kline/extras/extras.bullish_reversal_long_bear/` — 因為需要基本面資料融合
- **跨課程適用**: ⭐ 是 — 對應「打擊區」minimal entry 哲學
- **不確定**: 基本面 filter 數字、3 個月背景的精確計算（**[STUB-NEED-USER]**）

---

# 【C 類】既有 pattern / feature / scoring 補充（14 項）

## C01: outside_three_black.py — 擴充為 N=3..M

- **Source**: 第 43 篇補充說明
- **影響檔案**: `scripts/kline/patterns/outside_three_black.py`
- **怎麼改**:
  - 現行只看 N=3；改為「最近一根創新高紅 K 之後，連續黑 K (3 ≤ N ≤ M)，第 N 根 close 跌破紅 K 低點」
  - 老師明示 N 沒有上限（外側九黑也成立）
  - 重命名 detect → detect_outside_three_black; 新增 detect_outside_three_black_like
- **跨課程適用**: 是

---

## C02: high_long_black.py / 高檔長黑 exit — 加入「跳空攻擊缺口回補」條件

- **Source**: 第 03、11 篇
- **影響檔案**: `scripts/kline/exit/high_long_black.py`
- **怎麼改**: 加入「開盤跳空 + 盤中回補缺口 → 收盤跌破前日紅 K 低點」的盤中 path（日 K 退化版：`open > prev_close AND today_low < prev_close AND close < prev_low`）

---

## C03: features.py — 新增「攻擊意圖區 / 攻擊企圖區」邊界

- **Source**: 第 23、32 篇
- **影響檔案**: `scripts/kline/features.py`
- **新增 features**:
  - `attack_intent_zone_high` = 突破前高的 K 棒 close（= 突破當日 K 棒高點）
  - `attack_intent_zone_low` = 突破前高之前 N 日的最低 close（賣壓化解區段起點）
  - `intent_zone_break` = today_close < attack_intent_zone_high（跌回意圖區）

---

## C04: features.py — 新增「剛創新高」label

- **Source**: 第 03、10、24、40 篇
- **影響檔案**: `scripts/kline/features.py`
- **新增 features**:
  - `is_just_broke_high` = `(high == prior_high_60) OR (prev_high == prior_high_60.shift(1)) OR (prev_prev_high == prior_high_60.shift(2))`
  - 「明日 K 線」很多劇本要這個位置條件，現有 features 沒有單獨欄位

---

## C05: features.py — 新增「漲停鎖住」label

- **Source**: 第 20、28 篇
- **影響檔案**: `scripts/kline/features.py`
- **新增**: `is_limit_up_locked` = `(close == limit_up_price) AND (high == close) AND (low ≥ ref_price)`

---

## C06: high_hanging_man.py — 投機股場景下接受

- **Source**: 第 36 篇（得利影 6144 範例）
- **影響檔案**: `scripts/kline/patterns/high_hanging_man.py`
- **怎麼改**: 加 metadata（不改 detect）標註 — 「主力自演」場景下高檔吊首頻發，需另用「股價不再創新高」濾鏡（明日 K 線判斷重點）

---

## C07: features.py — 新增「異常放量」flag

- **Source**: 第 40 篇 / 「明顯放量創新高後」
- **影響檔案**: `scripts/kline/features.py`
- **新增**: `is_anomalous_volume` = `vol > vol_ma_60 * K AND vol > vol_max_60.shift(1) * J`
- **[STUB-NEED-USER]**: K, J 數字（老師說「異常」但無數字）

---

## C08: scoring — 新增「攻擊延續性」打分

- **Source**: 第 18、32、40 篇
- **影響檔案**: `scripts/kline/scoring/`（新增 `attack_continuity.py`）
- **scoring 邏輯**:
  - +1 if 創新高隔日跳空攻擊
  - +1 if 攻擊企圖隔日無回到意圖區
  - +1 if 異常放量 + 不回檔量縮（兩天放量）
  - −1 if 跌回缺口
  - −1 if 攻擊成本跌破

---

## C09: scoring — 新增「型態壓力」打分

- **Source**: 第 17、29 篇
- **影響檔案**: `scripts/kline/scoring/`（新增 `pattern_pressure.py`）
- **scoring 邏輯**:
  - +1 if 頸線剛跌破（頭部壓力出現）
  - +1 if 反彈遇頸線不過（反彈阻礙）
  - +1 if 連層套牢（每多一層壓力 +1，上限 +3）

---

## C10: ma60_rolloff.py — 加入「明日 K 線」表態檢視

- **Source**: 第 06 篇 / 「季線扣抵」
- **影響檔案**: `scripts/kline/scoring/ma60_rolloff.py`
- **怎麼改**: 季線即將下彎（扣抵高、close 低）狀態 + 隔日無紅 K 表態 → 加分（多方力量不足）

---

## C11: features.py — 新增「下降中樞型態 / 上升中樞型態」detect

- **Source**: 第 02、21、41 篇
- **影響檔案**: 新增 `scripts/kline/patterns/zhongshu_pattern.py`
- **規格**:
  - 上升中樞：前段紅 K 拉抬 → 中間 N 日（3 < N < 60）價格在區間內未跌破前段紅 K 低點 → 未發生突破亦未跌破
  - 下降中樞：對稱
  - 「明日 K 線」用法：偵測進入中樞狀態，標記為「等待突破/跌破」context
- **跨課程適用**: 是（型態學 18 子課程已有頸線；中樞是型態學的子集）

---

## C12: patterns/inner_trapped_to_gap_reversal.py — 內困翻黑變跳空反轉

- **Source**: 第 13 篇
- **影響檔案**: 已有 `gap_reversal.py` / `trapped.py`；新增 link feature `transition_inner_to_gap`
- **怎麼改**: 內困型態（孕線）翻黑後，若隔日向下跳空 → trigger 既有 gap_reversal 並標註是「內困演進」（這是「明日 K 線」對既有兩個 pattern 的串接）

---

## C13: patterns/two_crow_gap.py — 大盤場景加 cross-market filter

- **Source**: 第 34、36 篇
- **影響檔案**: `scripts/kline/patterns/two_crow_gap.py`
- **怎麼改**: 在大盤 K 上偵測雙鴉躍空時，加 metadata「需檢查當下是否權值股單一主導」（明日 K 線判斷補充）— 不影響 detect 主邏輯，僅 docstring 補充

---

## C14: exit/trailing_stop.py — 微弱多方趨勢退化版

- **Source**: 第 05 篇 / 「微弱的多方趨勢」
- **影響檔案**: `scripts/kline/exit/trailing_stop.py`
- **怎麼改**: 在「無轉折組合可用」「股價 K 棒重疊度高」的狀態下，採用短期上升趨勢線（簡化版：5 日 SMA 跌破）作為最後停利 — 老師明示「不得已才使用」

---

# 【D 類】純觀念 / 心法（23 項）

均寫入 `DEFINITIONS.md`。逐篇列出（不重複內容）：

| # | 文章 | 核心觀念 |
|---|---|---|
| §01 | 明日 K 線意義 | 「沙盤推演」原則（DEFINITIONS §1.1）|
| §02 (D 部分) | 中樞型態 | 對抗近因偏誤 |
| §03 (D 部分) | 再創新高的隔天 | 隔天必看跳空攻擊 / 推升攻擊；攻擊起源於「攻擊企圖」|
| §04 | 遇壓狀態 | 利多氣氛 + 遇壓 = 反向看；遇壓不化解 = 多一層套牢 |
| §05 (D 部分) | 微弱多方趨勢 | 不得已才用短期趨勢線；對抗未實現損益的「想賣」心理 |
| §07 | 賣壓化解 | 利多需配合化解，否則只是被消息帶上 |
| §08 | 壓力的分類 | 套牢 / 波動 / 獲利了結 三類賣壓；K 線「無支撐」 |
| §09 | 低價股的處理節奏 | 「第一次的拉抬結束」就離場；箱型誤謬 |
| §10 | 剛創新高上影線高點 | 創新高上影線位置的明日預期 |
| §11 (D 部分) | 當黑 K 出現的時候 | 高檔黑 K 後的劇本 |
| §12 | 漲停板後再漲機率 | 統計觀念（無實作）|
| §14 | 出現向下跳空的下降三法 | 既有 pattern 的隔日續演 |
| §15 | 面對高檔推升型態下一步 | 推升型態的隔日攻擊 / 跌破雙劇本 |
| §16 | 日出攻擊結束與上升三法判斷矛盾 | 老師釐清兩者邊界 |
| §17 (D 部分) | 頭部成型 | 三要件：大盤 / 基本面 / 是否被拉過 |
| §19 | 下山 | 四類成山特徵（DEFINITIONS §2.8）|
| §22 | 破底股糾結 | 跌破後反彈遇壓的劇本 |
| §27 | 明日股價不樂觀的個股 K 線 | 結構性弱勢盤點 |
| §31 (D 部分) | 主力出貨的秘密 | 箱型區間誤謬、五檔買單假象（DEFINITIONS §2.9）|
| §35 | 領先環境出現趨勢反向 | 大盤領先 / 個股獨自反向的解讀 |
| §37 | 缺乏力量的判斷 | 賣壓中空 / 缺乏攻擊企圖 對比 |
| §42 | 人性的弱點 | 心法（無實作）|
| §44 | 進場 vs 出場 | 非對稱（DEFINITIONS §2.12）|

---

# 4. 對 `scripts/kline` 的影響（總結 — 給後續實作參考）

## 4.1 建議「優先實作」順序（高 ROI）

1. **C03 + C04 + C05**：features.py 三個基礎欄位（攻擊意圖/企圖區、剛創新高、漲停鎖住）—— 其他規則都依賴
2. **A01 / B03**：合併十字線 + 後續攻擊 entry — 老師定義最清晰、實證範例最多
3. **B01 + B02**：攻擊成本顯現日 + 跌破 — 「明日 K 線」最具操作性的單一概念
4. **B04 + B05**：防守姿態 entry + 跌破 exit — 與主力大「站前哥 override」整合潛力最高
5. **B06**：突破後不攻擊 exit — 第 28 篇核心、補既有 exit 缺口
6. **C01**：類外側三黑（outside_three_black 擴充）— 一行改動、影響大
7. **C07 + C08**：異常放量 flag + 攻擊延續 scoring
8. **B07**：創紀錄跌點不再破底 entry — 罕見但「打擊區」打到就大
9. **C11**：中樞型態 detect — 補既有頸線之外的中繼判斷
10. **C09**：型態壓力 scoring

## 4.2 待 user 確認的 [STUB-NEED-USER] 清單

| 編號 | 項目 | 來源 |
|---|---|---|
| S1 | 「異常放量」K / J 數字 | C07、第 40 篇 |
| S2 | 防守姿態三條件數字（漲幅、大盤跌幅、防守低點窗口）| B04、第 26 篇 |
| S3 | 「最大量在漲停板」tick 級判定 → 日 K 退化版接受度 | B01、第 20 篇 |
| S4 | 「創紀錄跌點」歷史 max 範圍（全市場 / 近 5 年）| B07、第 30 篇 |
| S5 | 「空頭已超過 3 個月」的精確計算 | B08、第 46 篇 |
| S6 | 攻擊意圖區起點（賣壓化解區段邊界）| C03、B06、第 23 篇 |
| S7 | 類外側三黑 N 上限 M | C01、第 43 篇 |
| S8 | 「股價已脫離基本面」filter（B01 不適用條件）| B01、第 20 篇 |

## 4.3 命名前綴規範

按 `CLAUDE.md` 既有規範：
- 本子課程的純內部概念可用 `kline_course_` 前綴（或無前綴沿用）
- 跟主力大整合的層（如 B04、B07）寫到 `extras/` 並用 `extras.` 前綴，預設 OFF
- 跟 K 線力量入門完全相容的（如 A01、B01、B03、C01-C14）放原本路徑

## 4.4 「不寫」清單（明確排除）

以下觀念不可實作（純心法）：
- §42 人性的弱點 / §44 進場 vs 出場非對稱 / §19 下山的 4 類成山故事
- §03 §22 §27 §35 §37 §42 等純解讀觀念
- 任何盤中價格（早盤第一個高點、09:03 走勢等）只能退化為日 K 版本，並標註退化來源
