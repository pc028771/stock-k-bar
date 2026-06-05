# 多空轉折 Pattern 共用定義（跨課程查證版）

**Captured:** 2026-06-01
**Cross-checked sources:**
- 入門課程：`docs/K線力量判斷入門/course_principles.md` + 58 篇 pressplay 文章
- 行進ing 課程：`docs/K線行進ing/course_principles.md` + 39 篇文章
- 型態學課程：`docs/型態學/course_principles.md` + 18 篇文章
- 多空轉折篇：`.claude/worktrees/k-bar-power/docs/kline_course/long_short_turning_point/` 26 篇 + PATTERN_INVENTORY.md
- 既有實作：`scripts/kline/features.py`

**Scope:** 釐清 PATTERN_INVENTORY.md 三大共用觀念，作為 detect() 規格依據。**不動 scripts/kline。**

---

## 1. 力量型 K 線（power_bar）

### 結論：**C — 課程有明顯內部矛盾**

最接近真相的綜合解讀是：
> 「**力量型 K 線」這個術語在課程內並沒有被嚴格定義為一個獨立、可量化的 K 線分類。** 課程要的是「力量的判斷」，而力量判斷靠的是 **位置 + context（吞噬、跌破中值、創新高、攻擊背景）**，不是 K 線形狀本身。

但同時，課程描述具體型態（暗夜雙星、夜星棄嬰、大敵當前、跳空反轉、咬定、升降）時的「核心動作 K 棒」**一律用「長黑」或「長紅」字眼**，且這些字眼隱含「實體足夠完成關鍵動作」的最小門檻（如「摜破」、「跌破中值」、「拉不出距離」）。

→ 兩種立場並存，需 user 拍板採哪一條。

### 課程原文證據（兩方）

#### A 派：形狀不重要 / 不要靠形狀分類

- `docs/K線行進ing/01-關鍵K線的定義與使用目的.md:38`
  > 「**關鍵K線的形狀並不重要——並非長紅或長黑才算得上關鍵K線。**」
- `docs/K線行進ing/course_principles.md:22`
  > 「**形狀不重要**：並非長紅或長黑才算」
- `docs/K線行進ing/15-黑K篇一_定義黑K.md:16`
  > 「**黑K的組成與紅K不同……四種的區別很小。**」（黑K不必再細分長黑/短黑/上影線黑/十字黑）
- `docs/K線行進ing/07-紅K篇一_定義與三連紅.md:14-16`
  > 「**重點往往是價格而不是形狀**……若要細判這四種哪一種強？其實一點用途都沒有。」
- `docs/K線力量判斷入門/course_principles.md:259-263`（突破不需長紅/不需量）
  > 「與這一根突破的K線是否**長紅、有沒有上影線都無關**，研判的重點在於關鍵價位。」
- 入門 §"認知篇" 對指標 / 形狀分類的整體否定（`docs/K線行進ing/06-認知篇.md`）

#### B 派：型態定義內隱含「長 K」要求

- `docs/K線行進ing/course_principles.md:62`（暗夜雙星）
  > 「**長黑摜破兩根形狀相似的併排 K 線**」
- `docs/K線行進ing/course_principles.md:67`（夜星棄嬰）
  > 「高檔遇壓紅K → 十字線 → **長黑跌破紅K的中值**，且回補跳空缺口」
- `docs/K線行進ing/course_principles.md:70-75`（大敵當前）
  > 「連續紅K拉不出距離 + 隔天**長黑跌破第一根紅K的中值**」
- `docs/K線行進ing/25-跳空篇四_轉折組合裡的跳空.md:16-19`
  > 「前一天仍是**長紅K**或創新高格局…K1：**長紅K** 或 創新高」
- `docs/K線行進ing/09-紅K篇三_上升三法的成功與失敗.md:10`
  > 「上升三法 = 一根紅K…再拉一根**長紅**。」
- `long_short_turning_point/E79401532D60CC63B302926C2C33FB50_02-baofuxian-tunshi.md:44`
  > 「**這根黑K更強，自然是轉折意義更大**」← 強弱有別
- `docs/K線行進ing/16-黑K篇二_高檔長黑.md`：通篇「高檔長黑」獨立為訊號

#### 矛盾的化解（課程內部唯一明確的標準）

`E79401532D60CC63B302926C2C33FB50_02-baofuxian-tunshi.md:44`：
> 「黑包紅的包覆線，力量意義有多大？那就要看這根『**被包覆**』的紅K代表的力量意義有多強？而這根黑K更強，自然是轉折意義更大；但如果**被包覆的紅K本身沒有任何力量上的意義**，那這個包覆就沒有力竭意義。」

→ 課程定義「力量」不靠 body_pct 數字，而是靠**「這根 K 是否是攻擊意義發揮的那一根」**（features.py 已有 `prev_bar_had_attack_meaning`）。

### 規格建議（雙軌）

```python
# scripts/kline/patterns/_common.py 提議
def is_power_bar(df, direction='bull'):
    """
    課程沒有嚴格 body 門檻。本 helper 提供「結構代理」：
    bull → 該 K 是攻擊意義發揮（features.py prev_bar_had_attack_meaning 的當期版）
    bear → 該 K 完成「摜破前 K 中值」或「跌破前根低點」這類關鍵結構動作

    NOTE: 這不是課程明示，是把「形狀不重要」與「結構 K 要夠強」兩條
    指引整合的工程代理。任何 body_pct 數字門檻必須標 [NEEDS-USER-CONFIRM]。
    """
    raise NotImplementedError  # 待 user 拍版
```

**Option B（如果 user 真要 body 門檻）建議數字**：
```
body_pct ≥ percentile_70(body_pct over 20d)  AND  body_pct ≥ 1.5%
```
理由：percentile-70 把「相對近期較強的實體」拉出來；1.5% 絕對下限避免低波動股觸發（features.py 既有 `body_pct` 已 daily-level normalized）。

**[NEEDS-USER-CONFIRM]** 兩個數字門檻純屬工程提議，課程沒講。

### 對 detect() 的建議

1. 凡 PATTERN_INVENTORY 內標「力量型紅 K / 黑 K」當作前置 → **預設不加 body 門檻**，僅靠該 K 完成的結構動作判定（如「摜破」「跌破中值」「實體包覆」）。
2. 例外：高檔長黑 (P15 outside_three_black, `high_long_black` exit) 因課程明示「未創新高的高檔長黑」也算，**仍需 body 門檻**才能避免短黑 K 觸發。建議此單一情境採 body_pct ≥ 3-4%（沿用既存 `course_principles.md:701` 的 `body_pct ≥ 0.04`）。
3. 力量強度（轉折意義大小）不放在 detect() bool 結果裡，**改在 scoring 層處理**（如 P19 inventory 第 700 個 line 提到的 score 函式）。

---

## 2. 多方力竭背景（bull_exhaustion_context）

### 結論：**A + 結構（不是純價格百分比）— 課程明示「攻擊狀態 + 拉抬過後」是唯一判斷**

課程**完全沒有**「過去 N 日漲幅 ≥ X%」這類定量定義。
取而代之是兩條結構性條件：

1. **股價過去處於「攻擊狀態」**（features.py `attack_intensity ≥ 1` 對應 4 種攻擊型態之一）
2. **「拉抬過後」**（過往曾出現明顯漲段；無法用數字嚴格定義，只能用 prior_high_60 多次推進、或日出/跳空攻擊曾觸發過作代理）

### 課程原文證據

- `docs/型態學/07-反轉型態.md:19`
  > 「所謂的高檔，已經結合了**過去一段時間股價是在攻擊狀態的**，那麼力竭代表了主力準備開始出貨的跡象。」
- `docs/K線行進ing/16-黑K篇二_高檔長黑.md:16-18`
  > 「**高檔這兩個字沒有辦法用數字或者比例來定義**，所以只能回顧過去有沒有拉抬漲勢出現過。」
- `long_short_turning_point/B2E7A4597B7D1B50CF88163C892204D1_01-duokong-zhuanzhe-qianyan.md:30`
  > 「所謂的力竭指的是『**明顯的多頭走勢時期**』多方無力無意再往上拉抬」
- `long_short_turning_point/E79401532D60CC63B302926C2C33FB50_02-baofuxian-tunshi.md:22`
  > 「組合要產生某種力量上的意義，出現的位置往往是在一段時期**明確方向走勢的高低點**，例如在『**創新高或者破底**』的位置。」
- `long_short_turning_point/E79401532D60CC63B302926C2C33FB50_02-baofuxian-tunshi.md:54`（康控案例）
  > 「被包覆的紅K除了創新高之外，**過去兩個月股價足足漲了超過一倍**，也就是攻擊最氣盛的時候」← 唯一接近「定量」描述，但「超過一倍 / 兩個月」**是案例描述，不是定義**
- `docs/K線行進ing/19-黑K篇五_破底之後的黑K觀察要點.md:14`
  > 「攻擊的走勢屢創新高到了又一根長紅，當然就是多方力量的極度發揮，是不是力竭光看紅K看不出來，但若出現了黑K吞噬，當然就是力竭的意義。」← **力竭的判定靠下一根的轉折 K 完成、不靠當下的漲幅數字**

### 規格

```python
# scripts/kline/patterns/_common.py 提議
def bull_exhaustion_context(df):
    """
    課程內最精確的代理：股價處於攻擊狀態 + 拉抬過後高檔。

    依據（無數字）：
      - features.py attack_intensity ≥ 1（過去/當下處於 4 種攻擊型態之一）
      - 過去 60 日內曾突破過 prior_high_60（拉抬過的痕跡）
      - 當下 close 接近 prior_high_60（在拉抬之後的位置而非腰斬後）

    NOTE: 不採用「過去 N 日漲幅 ≥ X%」這類門檻 — 課程明示
    「高檔沒辦法用數字或比例定義」（黑K篇二）。
    """
    g = df.groupby("ticker")
    # 條件 1：當前或過去 5 日內處於攻擊狀態
    in_attack_recent = (
        g["attack_intensity"].rolling(5, min_periods=1).max() >= 1
    ).reset_index(0, drop=True)

    # 條件 2：過去 60 日內曾經 close > prior_high_60（拉抬發生過）
    was_breakout_60d = (
        ((df["close"] > df["prior_high_60"]).fillna(False).astype(int))
        .groupby(df["ticker"]).rolling(60, min_periods=1).max()
        .reset_index(0, drop=True) > 0
    )

    # 條件 3：今日 close 仍位於 prior_high_60 的 95% 以上（沒有跌離高檔）
    near_high = df["close"] >= df["prior_high_60"] * 0.95

    return in_attack_recent & was_breakout_60d & near_high
```

**[NEEDS-USER-CONFIRM]：**
- 「過去 5 日」「過去 60 日」「95%」三個 window/threshold 都是工程選擇，課程沒講
- 是否要 AND 大盤 regime filter（「明顯的多頭走勢時期」隱含大盤狀況）— 課程沒明示是否要市場 filter，建議**先不加**（個股獨立判斷符合課程「個股 vs 大盤」分離精神）

### 矛盾 / 不確定

- 課程案例「兩個月漲一倍」這種強案例 vs「股價在創新高位置」這種寬條件之間有強度梯度。若 detect() 只回 bool，會把強案例（康控 +100% 兩個月）和弱案例（剛突破 prior_high_60）視為同等。建議**強度交給 scoring 層**處理（如距 ma60 的距離百分位）。

---

## 3. 空方力竭背景（bear_exhaustion_context）

### 結論：**A + 結構 — 與多方對稱但「再加邏輯」**

課程明示空方力竭的**結構性**判斷比多方力竭**更嚴格**（因為紅 K 需要追高買盤、黑 K 不需要主動賣盤）：

1. **連續且漫長的崩跌**（features.py `is_in_breakdown_pattern` 對應）
2. **賣壓中空區段**已存在（features.py `supply_vacuum_zone` 對應）
3. 反轉那根紅 K 需有「買盤力量」（無法量化，課程明示）

### 課程原文證據

- `docs/型態學/07-反轉型態.md:25`
  > 「多方反轉之前的背景，通常都是**環境氣氛不佳，股價連續且漫長的崩跌，人心最脆弱的時期**出現。」
- `docs/型態學/07-反轉型態.md:38`
  > 「股價如果遇到了空頭趨勢下跌，只要持續得夠久加上環境因素，往往會**超跌**……可以看出**空方的力竭已經是很大的幫助**。」
- `docs/型態學/07-反轉型態.md:51`（多方反轉的「再加邏輯」）
  > 「多方反轉型態需要再加上一個邏輯，就是紅K與黑K組成的要素不同，紅K需要有買盤的力量進駐，但是下跌往往沒人買就可以再跌下去。」
- `docs/型態學/07-反轉型態.md:57`
  > 「多方反轉的必要前置：1. 連續且漫長的崩跌；2. **賣壓中空區段**已存在（不在套牢區）；3. 紅K要有買盤力量」
- `long_short_turning_point/E79401532D60CC63B302926C2C33FB50_02-baofuxian-tunshi.md:118-122`（佳必琪 6197 案例）
  > 「破底(再創新低)的黑K出現時……同時環境的背景也是在空方氣盛的狀況……假如這樣的狀況出現的大盤背景並不是空頭氣盛，那麼低接意願還是存在的，就沒有這麼籌碼穩定，**這是背景定義上需要符合同時是大盤環境悲觀、股價也破底，這是讓紅K吞噬很少出現的原因**。」 ← 課程明示空方力竭**需要大盤 filter**（與多方不同！）
- `docs/K線行進ing/26-跳空篇五_空方趨勢的向下跳空.md:38`
  > 「指當環境極度的悲觀……賣盤再也無法冷靜不出手賣掉，買盤都在觀望狀態下形成開盤直接跳空下去長黑也破底的現象。」

### 規格

```python
# scripts/kline/patterns/_common.py 提議
def bear_exhaustion_context(df):
    """
    課程明示比多方力竭更嚴格的三條件：
      1. 處於破底型態（features.py is_in_breakdown_pattern）
      2. 賣壓中空存在（features.py supply_vacuum_zone）
      3. （建議但 [NEEDS-USER-CONFIRM]）大盤背景悲觀 — 課程明示需要

    NOTE: 課程案例「紅K吞噬 104 年以後才出現一次」說明這個 filter
    非常嚴格，detect() 觸發次數應該遠少於 bull_exhaustion_context。
    """
    in_breakdown = df["is_in_breakdown_pattern"].fillna(False)
    has_supply_vacuum = df.get("supply_vacuum_zone", pd.Series(False, index=df.index)).fillna(False)
    # 大盤 filter 留給上層 simulator 套用，patterns/ 層不做跨股 query
    return in_breakdown & has_supply_vacuum
```

**[NEEDS-USER-CONFIRM]：**
- 大盤背景是否要進 detect() — 建議**不要**，理由：patterns/ 層應保持 per-ticker 純函數，大盤 filter 由上層 scanner / simulator 在組合層套用（與「老師有買 + scanner 共識」的多層 filter 設計一致）
- features.py `supply_vacuum_zone` 是否已 production-ready — 需確認；若未實作則 fallback 為「過去 N 日跌幅 + 連續黑 K 比例 ≥ X」

### 既有實作評估

`scripts/kline/features.py:191` 的 `is_in_breakdown_pattern` 已可作 (1)。
建議 detect() 規格採此 + supply_vacuum_zone（若可用）作為「課程認可」的最小組合。

---

## 4. 對 PATTERN_INVENTORY.md 的修正建議

本節對應 inventory 內 12 個標 `[STUB-NEED-USER]` 的條目，給出基於 §1-3 結論的填法。

| Inventory 位置 | STUB 內容 | 建議填法 | 依據 |
|---|---|---|---|
| L10 共用術語：力量型 K 線數字 | body_pct ≥ percentile_70 等 | **採 §1 結論 C 雙軌**：detect() 預設不加 body 門檻、靠結構判定；唯獨 `high_long_black` 採 body_pct ≥ 0.04 | §1 |
| L20 多方力竭 | 過去 N 日漲幅 / close > prior_high_60 | **採 §2 規格**：attack_intensity ≥ 1 (5d max) AND was_breakout_60d AND close ≥ prior_high_60 × 0.95 | §2 |
| L21 空方力竭 | is_in_breakdown_pattern + 創新低 | **採 §3 規格**：is_in_breakdown_pattern AND supply_vacuum_zone | §3 |
| P02 L64：力量型 K 線數字 | — | 不需數字，靠「黑 K 實體包覆 prev 紅 K」結構動作判定 | §1 |
| P02 L65：攻擊意義 prev_bar_had_attack_meaning vs prior_high_60 | — | **採 features.py 既有 prev_bar_had_attack_meaning**（features.py L355 起已涵蓋「紅 K 創新高 / 創新高上影線 / 紅 K 隔日十字」三類），課程 §"紅 K 篇" 即此設計依據 | §1, course_principles |
| P03 L84：大盤悲觀 cross-market filter | — | **不放在 detect()**，由上層 simulator 套用 | §3 |
| P03 L85：is_in_breakdown_pattern as proxy | — | **是**，採 §3 規格 | §3 |
| P04 L97, L103：低檔定義 | prev_low ≤ prior_low_60 | **採 §3 規格**：bear_exhaustion_context() AND prev_low ≤ prior_low_60.shift(1) | §3 |
| P05 L114：「明顯拉抬」 | close > prior_high_60 or 漲幅 ≥ X% | **採 §2 規格** bull_exhaustion_context() | §2 |
| P05 L118：T 字線下影線 2x、上影線 0.3x | — | **保留工程提議**標 `[NEEDS-USER-CONFIRM]`，課程無依據 | (課程無) |
| P06 同 P04 | — | 同 P04 | §3 |
| P07 L165：拉不開數字 | max(high) - high_K1 < 0.5% | **保留工程提議**，課程僅說「拉不出距離」，建議 body_pct < 2% per bar + max(high) 距 K1 high < 1.5% | (課程無強數字) |
| P08 L185：併排相似度 0.3% | — | **保留工程提議**標 `[NEEDS-USER-CONFIRM]`；既有 `scripts/kline/exit/reversal_k/dark_double_star.py` 提議 2%，課程僅說「形狀相似」 | (課程無) |
| P11 L259：低檔量化 | is_in_breakdown_pattern.shift(N) | **採 §3 規格** bear_exhaustion_context | §3 |
| P12 dot：強弱差別 | doji strict vs 短 K | 建議 doji OR body_pct < 1%（涵蓋短 K 變體）— 課程描述「十字線」較寬 | (課程寬) |
| P13 L298：島中 K 數上限 | ≤ 10 天 | **保留** ≤ 10 天工程提議，課程未明示 | (課程無) |
| P14 L317：失敗判定 | detect vs detect_with_failure | 建議 **patterns/ 只回形狀 bool**，失敗判定由 simulator 處理（同「失效條件」設計原則） | §1 結論 4 |
| P16/P17：單日反轉是否實作 | A/B/C | **C：放 extras/**，課程明示「最微弱、需外部輔助」，符合 CLAUDE.md「課程外條件隔離」精神 | (專案規範) |
| P19 L409：量比門檻 1.5 | — | **保留** 1.5 工程提議，課程僅說「有量」 | (課程無) |
| P22 L468：收盤相等容差 0.1% | — | **保留** 0.1% 工程提議標 `[NEEDS-USER-CONFIRM]` | (課程無) |
| P25 L529：狹幅至少一週 + 3% | — | **保留**「5 根 K 線 + range < 3%」工程提議，課程僅說「狹幅整理」 | (課程無) |
| P26 L548：時間窗 | — | 建議 20 個交易日（約一個月），課程未明示 | (課程無) |
| P27 L566：N 上限 5 | — | **保留** N ≤ 5 工程提議，課程僅說「短期內」 | (課程無) |

### 整體影響統計

- **共 22 個 STUB-NEED-USER 條目**（含 inventory 內 L10/L20/L21 三個共用層）
- **§2/§3 結論直接解掉**：8 個（與「力竭背景」相關）
- **§1 結論部分解掉**（雙軌設計）：6 個（與「力量型 K 線」相關）
- **仍需 user 拍版**（純工程提議）：8 個（併排相似度、拉不開、容差、N 上限、單日反轉是否上線等）

---

## 5. 給 reviewer / user 的 TL;DR

1. **「力量型 K 線」課程內部矛盾**：認知篇 / 紅黑 K 篇 / 入門 §突破 三處都說「形狀不重要」；但暗夜雙星 / 夜星棄嬰 / 大敵當前 / 高檔長黑 四個型態定義字面寫「長黑」「長紅」。建議採雙軌：detect() 內 **不放 body 門檻**，由「結構動作」（摜破、跌破中值、實體包覆）來保證 K 棒夠強；唯一例外是 high_long_black 必須 body_pct ≥ 0.04。
2. **「多方力竭背景」課程明確拒絕用百分比**：「高檔沒辦法用數字或比例定義」（黑 K 篇二）。建議用 attack_intensity ≥ 1 (5d max) + was_breakout_60d + close 仍在高檔（≥ prior_high_60 × 0.95），三項 AND。
3. **「空方力竭背景」比多方更嚴格**：課程明示需「連續漫長崩跌 + 賣壓中空 + 紅 K 真有買盤」三項，案例「104 年以後才出現一次」。建議用 is_in_breakdown_pattern AND supply_vacuum_zone；大盤悲觀 filter **不放 detect()**，由上層處理。
4. **22 個 STUB 中 14 個可直接套上述結論解掉**，剩 8 個是純工程數字提議（併排相似度、容差等），課程無依據，需 user 拍板數字（可先採提議數字、回測再調）。
