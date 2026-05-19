# 主力大課程 — 策略可用性分流

> **評估日期：** 2026-05-17
> **依據：** `course_map_from_scripts.md` + `strategy-indicators.md`
> **分流邏輯：** 是否所有量化參數齊備、是否可直接寫成 daily scanner / backtest。

---

## 第一象限：已成熟原型（可立即動工 Backtest）

這些策略講稿明確給出可量化的進場、出場、停損條件，可以直接寫 scanner + backtest。

### 1. 大波段選股策略（Swing Breakout）— Ch3-1 + Ch3-2

- **量化參數齊備：** 籌碼門檻（1/3 或 2 萬張）、20ma/60ma 上彎、離 20ma ≤ 5%、停損跌破 20ma。
- **檔名建議：** `zhuli_swing_breakout_daily_scanner.py`
- **可立即動工。**

### 2. 形態一：奇形（Pennant）— Ch4-2 line 9-216

- **量化參數齊備：** 旗杆/旗子 K 棒型態、5ma 站立、量增/量縮判定、進場時機（第三天尾盤或第四天 5ma 接）、停損（跌破 5ma）。
- **檔名建議：** `zhuli_pennant_daily_scanner.py`
- **可立即動工。**

### 3. 形態三：布林上軌（BBands Upper Break）— Ch4-2 line 357-493

- **量化參數齊備：** 通道窄度 10%、收 > 上軌、出量、出場（綠K 跌入上軌之內）。
- **檔名建議：** `zhuli_bbands_break_daily_scanner.py`
- **可立即動工。**

### 4. 窒息量加碼（Suffocation）— Ex1-2 + Ex1-3

- **量化參數齊備：** 量 < 20 日最大量 × 10%、月線上彎、出量 K 型態限定、停損為出量 K 低點。
- **檔名建議：** `zhuli_suffocation_daily_scanner.py`
- **可立即動工。**

### 5. 投信跟單策略（Institutional Swing）— Ex2-2

- **量化參數齊備：** 5 日累計投信買超 ≥ 1.5% 股本、剛上榜（前 N 日未上榜）、均線排列、十日線進出。
- **檔名建議：** `zhuli_institutional_swing_daily_scanner.py`
- **可立即動工。**

### 6. 投信首買策略（Institutional First-Buy）— Ex2-3

- **量化參數齊備：** 首日 ≥ 200 張、前 60-90 日無投信買超、價籌背離判定。
- **檔名建議：** `zhuli_institutional_firstbuy_daily_scanner.py`
- **可立即動工。**

### 7. 主力意圖（收高開低 / 收低開高）— Ch7-3

- **量化參數齊備：** K 棒型態（出量實紅/實黑收最高/最低）+ 開盤價判斷。
- **用途：** 不單獨進場，作為「出場過濾器」。
- **檔名建議：** `zhuli_open_signal_filter.py`
- **可立即動工。**

### 8. 隔日沖（Overnight）— Ch6-1 + Ch6-2

- **量化參數齊備：** 大盤紅K + 量增 + 站上 5ma、個股紅K + 量、月線斜率 > 0.4、突破布林高軌、距上軌 < 6%、1:20-1:25 進場、開盤預掛賣。
- **檔名建議：** `zhuli_overnight_daily_scanner.py`
- **可立即動工。**
- **注意：** 出場為盤前預掛跌停賣，回測時可用 `next_open` 模擬。

### 9. 當沖前夜篩 + 兩大精選（Intraday Pre-screen）— Ch5-1-1 + Ch5-2

- **量化參數齊備：** 5/10/20 多頭排列、2 萬張、振幅 8%、周轉率 20%、離月線 30%、距前高 < 10%、近期量 > 前波高點量。
- **檔名建議：** `zhuli_intraday_prescan_daily_scanner.py`
- **可立即動工（前夜清單）。**
- **盤中 SOP（Ch5-3）需要分鐘 K 資料，回測複雜度較高，但條件齊備。**

---

## 第二象限：還要繼續驗證（缺量化參數）

這些策略講稿給了概念，但有部分參數需釐清才能完整自動化。

### 1. 形態二：反轉形態（Reversal Breakout）— Ch4-2 line 217-356

- **缺：** 「兩個前高連線」的高點如何選（哪兩個前高？最近的？最高的兩個？）講稿用肉眼判斷。
- **缺：** 「短均線開始上彎」的扣底值判斷需要實作。
- **可寫但需用簡化規則：** 例如「最近 30 個交易日的兩個明顯高點」。
- **檔名建議：** `zhuli_reversal_breakout_daily_scanner.py`
- **驗證重點：** 與訊號圖比對，看是否抓對紅K。

### 2. 缺口策略（Gap）— Ch2-3

- **本身是支援工具，不獨立進場。**
- **缺：** 「量縮回測缺口附近」的「附近」距離未量化（5%? 3%?）。
- **可寫但需自定義「附近」門檻。**

### 3. 量價支撐策略（Volume Profile）— Ch2-4

- **「大量」是課程設計上的相對概念**（與前一根/前一波比較），講稿與 PDF 皆無絕對倍數定義（PDF 驗證 2026-05-17）。
- **實作建議：** `volume > MA(volume, 5/10) * N`，N 為可調 CLI 參數（不需硬給單一值）。
- **驗證重點：** 大量 K 棒高點/低點作為支撐壓力的可量化判定。

### 4. 當沖盤中 SOP（Intraday Live）— Ch5-3

- **量化條件齊備（5 分 K、均價線、江波圖），但需要分鐘 K 資料源 + 即時運算引擎。**
- **不是「缺參數」，是「實作成本較高」。**
- **可獨立寫 paper trading simulator 先驗證。**

### 5. 慣性支撐策略（Habitual Support）— Ch2-2

- **缺：** 「歷史驗證次數」門檻未量化（要多少次站回才算？2 次？3 次？）。
- **可定義為 `≥ 2 次回測該均線後反彈` 作為慣性支撐確認。**

---

## 第三象限：後續工作順序（Phase 1 / 2 / 3）

### Phase 1（立即動工，1-2 週內）

1. `zhuli_swing_breakout`（A 大波段 SOP）— 與既有 K 線力量框架最像，可重用 `kline_course_backtest.py` 基礎建設。
2. `zhuli_suffocation`（H 窒息量）— 參數最完整，回測週期短，最容易驗證。
3. `zhuli_institutional_firstbuy`（J 投信首買）— 單一條件高勝率，最容易做 Top-N summary。

### Phase 2（Phase 1 完成後 2-4 週）

4. `zhuli_pennant`（B 奇形）— 形態識別有些細節需要實作（旗杆/旗子型態判斷）。
5. `zhuli_bbands_break`（D 布林上軌）— 通道窄度判定 + 出量定義（已齊備）。
6. `zhuli_bbands_pullback`（E 形態四：布林回測）— 已從 PDF 補完，前置需符合形態三，可緊接 D 之後實作。
7. `zhuli_institutional_swing`（I 投信跟單）— 五日累計買超 + 十日線進出。
8. `zhuli_overnight`（G 隔日沖）— 速篩 + 個股精選；需確認還原日K 資料源。

### Phase 3（Phase 2 完成後）

9. `zhuli_reversal_breakout`（C 反轉形態）— 需先決定「兩個前高」演算法（POC 見 §風險警示 #2）。
10. `zhuli_intraday`（F 當沖）— 需分鐘 K 即時資料層 + paper trading simulator。

---

## 第四象限：策略化邊界（不適合自動化的）

這些內容不應該寫成 scanner / backtest，屬於人為判斷或心法層次。

### 1. 心態與觀念（Ch7-1、Ch7-2、Ex1-1 等）

- 「活下來比什麼都重要」、「沒有 100% 只有機率」、「投資是一輩子的事」。
- 這些是操作心法，不可量化。

### 2. 資金配置（Ch7-2）

- 沒有標準答案，依交易屬性調配。
- 主力大明確說「沒有一個標準的答案」。
- 不適合寫成自動化規則。

### 3. 族群題材判斷（Ch3-1）

- 「漲價題材、缺貨題材、轉單題材」屬於新聞事件解讀。
- 主力大歸類的族群（面板、航運、鋼鐵…）需要產業知識維護。
- 可半自動：建立產業對應表 + 法人買超族群密度判斷，但需人工維護產業表。

### 4. 漲停解鎖次數判斷（Ch5-1-2）

- 「開開關關 3-4 次考慮減碼」需要即時資料 + 主觀判斷。
- 不適合純量化，可寫成提醒工具。

### 5. 思維切換（當沖 → 短線 → 波段）（Ch5-1-2）

- 屬於投資人個人風險偏好決策。
- 系統可提供建議但不應自動執行。

### 6. 國際利空例外（Ch7-3）

- 收高開低法則「國際利空不適用」需要人工事件判斷。
- 可半自動：用大盤跳空幅度、夜盤波動度判斷，但邊界模糊。

### 7. 「盤勢判斷能力」（Ch7-1）

- 「多頭做多、空方做空或空手、盤整低買高賣」屬於資深操盤心法。
- 系統可提供 regime tag 輔助，但「會做的盤勢」屬個人能力判斷。

---

## 摘要表格

| 策略 | 章節 | 成熟度 | Phase | 檔名建議 |
|------|------|--------|-------|----------|
| 大波段 SOP | Ch3-2 | ✅ 完整 | 1 | `zhuli_swing_breakout` |
| 窒息量 | Ex1-2 | ✅ 完整 | 1 | `zhuli_suffocation` |
| 投信首買 | Ex2-3 | ✅ 完整 | 1 | `zhuli_institutional_firstbuy` |
| 奇形 | Ch4-2-1 | ✅ 完整 | 2 | `zhuli_pennant` |
| 布林上軌 | Ch4-2-3 | ✅ 完整 | 2 | `zhuli_bbands_break` |
| 投信跟單 | Ex2-2 | ✅ 完整 | 2 | `zhuli_institutional_swing` |
| 隔日沖 | Ch6 | ✅ 完整 | 2 | `zhuli_overnight` |
| 反轉形態 | Ch4-2-2 | ⚠️ 缺前高選擇 | 3 | `zhuli_reversal_breakout` |
| 形態四（布林回測） | Ch4-2-4 / PDF p.127 | ✅ 完整（從 PDF 補完） | 2 | `zhuli_bbands_pullback` |
| 當沖 | Ch5 | ✅ 條件完整需分鐘K | 3 | `zhuli_intraday` |
| 收高開低 | Ch7-3 | ✅ 完整（過濾器） | 1 | `zhuli_open_signal_filter` |
| 缺口 | Ch2-3 | ⚠️ 「附近」需定義 | 2 | `zhuli_gap` |
| 量價支撐 | Ch2-4 | ⚠️ 「大量」需定義 | 2 | `zhuli_volume_profile` |
| 慣性支撐 | Ch2-2 | ⚠️ 驗證次數需定義 | 2 | `zhuli_habitual_support` |

---

## 風險警示

1. ~~**形態四為唯一真實 STUB**~~ → **✅ 已解（2026-05-17）**：從 PDF `1627272942273-` p.127 補完，名稱為「布林回測策略」，已寫進 strategy-indicators §E。Phase 2 可動工 `zhuli_bbands_pullback`。

2. **反轉形態的「兩高點」演算法 → 用視覺輔助 POC 校準**：
   - 講稿肉眼判斷「兩個明顯高點連線」，沒有精準演算法定義。
   - **POC 計畫：**
     a. Python 用 `scipy.signal.find_peaks` 或 rolling local max 算 swing high 候選（如 5/10/20 日 window）。
     b. `mplfinance` 畫日 K 線圖並標出候選點 → 存 PNG。
     c. 把講稿明確點名的案例（如華訊 6237 的某幾天）人工標 ground truth。
     d. 把演算法選的「兩高點」與人工標 ground truth 對齊，調 window 參數。
     e. 規模化後，把不確定的圖丟給 Claude vision 二次判讀「這兩點符合主力大『反轉形態兩高點』定義嗎？」。
   - 動工前先跑 POC，不要硬寫 scanner。

3. **大量 K 棒的「大量」不是缺漏，是課程設計上的相對概念**（PDF 驗證 2026-05-17）：
   - 講稿與 PDF 皆無「MA20 的 N 倍」這類絕對門檻。
   - 「大量/爆量/量增」一律「與前一根/前一波比較」。
   - **實作策略：** 把 `LARGE_VOL_RATIO` 設成 CLI 可調參數（如 `> MA(volume, 5) × N`），N 預設值可參考 POC #2 的 5 筆案例分布（P25=3.8、Median=4.3），但**不要硬編一個值當「老師說的標準」**。
   - 既有 POC：`scripts/zhuli_large_volume_threshold_poc.py` 已產出 `large_volume_threshold_report.md`，可補進 PDF 提到的 20+ 個新案例（華新科 2019/12/24 等）擴大樣本。

4. **隔日沖 1:20 進場時間窗**：需要分鐘 K 資料或盤後計算「1:20 當時的價格」。
