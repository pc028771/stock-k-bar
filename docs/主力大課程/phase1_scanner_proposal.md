# Phase 1 Scanner 拍板建議

> 日期：2026-05-19
> 課程內容狀態：23 章字幕全補完 + 截圖 78% + HD vision 升級整合完成
> spec 完備度：HD vision 升級後隔日沖三條件精確數值已補（布林窄率 6%、長紅 3.5%、月線斜率 0.4）

---

## 1. 三套「立即可動工」候選 scanner

依 `integration_status.md §4` 的解鎖條件判斷，以下四個策略所有必要量化參數均已定義，無真實 spec blocker。

---

### H 窒息量（zhuli_suffocation）

**定義：** 當日成交量 < 20 日最大量的 10%，等下一根「出量 K」（紅K 或下影 > 實體的綠K）進場；停損出量 K 低點。

**Spec 完備度：**

| 維度 | 狀態 | 說明 |
|---|:---:|---|
| 定義 | ✅ | 10% 閾值 PDF 雙確認 |
| 進場 | ✅ | 兩情境（月線上彎情境 A + 跌破月線後情境 B）均已定義 |
| 出場 | ✅ | 跌破出量 K 低點 |
| 停損 | ✅ | 出量 K 低點（收盤確認） |
| 量化參數 | ✅ 4/4 | `vol < max_20d * 0.10`、`ma20_slope > 0`、出量 K 型態判定、`stop_loss = next_bar.low` |

**額外優勢：** 既有 `scripts/zhuli_suffocation_scanner.py`（527 行），搬到新目錄後依規範重構即可，不是從零寫起。

**預估 LOC：** 150-200 行（重構既有 527 行至模組化版本）
**預估 spec ambiguity：** 1 個（「弧形整理」視覺特徵不量化，但課程本身也未要求）
**預估實作週期：** 2-3 天（含 backtest 驗證）

---

### G 隔日沖（zhuli_overnight）

**定義：** 今天 1:20-1:25 尾盤買、隔天預掛跌停開盤賣；個股速篩三條件 + 大盤條件雙重確認。

**Spec 完備度：**

| 維度 | 狀態 | 說明 |
|---|:---:|---|
| 定義 | ✅ | 「今買隔賣」紀律明確 |
| 進場 | ✅ | 大盤條件（加權 + OTC 量增紅K + 站上 5ma）+ 個股速篩三條件 |
| 出場 | ✅ | 盤前預掛跌停賣（開盤成交） |
| 停損 | ✅ | 預掛跌停等同固定停損；進階版第一根 5 分 K 低點 |
| 量化參數 | ✅ 5/5 | 布林窄率 < 6%、長紅 > 3.5%、量 > 1,000 張、量增 > 0.1%、月線斜率 > 0.4（HD vision 全部確認）|

**注意：** 截圖 ch6-1/6-2 各僅 1 張，vision stub 比例高（67/94），可能有盤中心法細節未補。但核心速篩參數已由 PDF + HD vision 雙確認，動工安全。進場時間窗 1:20-1:25 需用收盤價近似（日K 回測模式）。

**預估 LOC：** 200-250 行（含大盤條件查詢邏輯）
**預估 spec ambiguity：** 2 個（1:20 進場時間近似方式、「量增 > 0.1%」實務閾值調整空間）
**預估實作週期：** 3-4 天（含大盤指數資料源確認）

---

### A 大波段（zhuli_swing_breakout）

**定義：** 族群+籌碼+技術三面交叉確認的中長期波段進場 SOP；收盤跌破月線停損。

**Spec 完備度：**

| 維度 | 狀態 | 說明 |
|---|:---:|---|
| 定義 | ✅ | 三面分析框架明確 |
| 進場 | ✅ | 籌碼門檻（≥1/3 成交量 or ≥2萬張）+ 技術面（20/60ma 上彎 + 距月線 ≤5%）|
| 出場 | ✅ | 收盤跌破 20ma；大量黑K 跌破前紅K 低點 |
| 停損 | ✅ | 跌破月線（20ma） |
| 量化參數 | ✅ 3/3（主軸）⚠️ 1 缺 | 距月線 5%、20/60ma 斜率、籌碼門檻均已定義；族群密度（幾檔算族群性）未量化 |

**注意：** 族群密度 gap（「同族群幾檔以上」）課程無定義，建議預設 ≥ 3 檔作為可調參數先行。此策略與既有 K 線力量框架最像，共用底層路徑最短。

**預估 LOC：** 180-230 行（含籌碼資料源整合）
**預估 spec ambiguity：** 2 個（族群密度門檻、籌碼確認後延遲進場時機待截圖驗證）
**預估實作週期：** 3-4 天（含 FinMind 投信/外資買超整合）

---

### M 收高開低 filter（zhuli_open_signal_filter）

**定義：** 純出場過濾器，非獨立進場策略；前日出量實紅K 收最高 + 次日開平/綠 → 已持有開盤離場。

**Spec 完備度：**

| 維度 | 狀態 | 說明 |
|---|:---:|---|
| 定義 | ✅ | 轉弱/轉強兩個方向均已定義 |
| 觸發條件 | ✅ | 前日 K 棒型態 + 次日開盤價判斷 |
| 出場 | ✅ | 開盤離場（已持有）|
| 停損 | n/a | 本身是出場訊號，不獨立進場 |
| 量化參數 | ✅ 2/2 | 前日實體紅K 收最高 + 今日開盤 ≤ 前日收盤 |

**注意：** 最輕量，純過濾器。國際利空例外邏輯難完全自動化（可用大盤跳空幅度 > N% 近似）。適合先寫完整合進其他策略，不單獨跑 backtest。

**預估 LOC：** 60-80 行
**預估 spec ambiguity：** 1 個（國際利空例外的大盤跳空門檻）
**預估實作週期：** 1 天

---

## 2. 各候選比較表

| 維度 | H 窒息量 | G 隔日沖 | A 大波段 | M 收高開低 |
|---|:---:|:---:|:---:|:---:|
| 進場條件完整 | ✅ | ✅ HD 補完 | ✅ | ✅（無需進場）|
| 量化參數精確數量 | 4 條完整 | 5 條精確 | 3 條（+1 缺）| 2 條 |
| 出場/停損 | ✅ | ✅ | ✅ | n/a（過濾器）|
| 截圖 + Vision 覆蓋 | ✅ 全三章 | ⚠️ 截圖僅 1/21+1/30 | ✅ Ch3-1/3-2 完整 | ✅ Ch7-3 完整 |
| 既有 scanner 可重構 | ✅ 527 行 | ❌ 從零寫 | ❌ 從零寫 | ❌ 從零寫 |
| 共用底層需求 | ma5/10/20/60、20日 max vol、K 棒型態判定 | 布林帶、ma20 斜率、大盤指數資料 | ma20/60、FinMind 法人買超 | 前日 K 型態、開盤價 |
| 需外部資料源 | 日K（現有）| 日K + 大盤指數 | 日K + 法人買超（現有）| 日K（現有）|
| 預估 LOC | 150-200 | 200-250 | 180-230 | 60-80 |
| 預估 PoC 時間 | 2-3 天 | 3-4 天 | 3-4 天 | 1 天 |
| 適合獨立 backtest | ✅ | ✅（next_open 近似）| ✅ | ❌（附屬工具）|

---

## 3. 各候選的「最小可行版本」描述

### H 窒息量（最小可行版）

```
輸入：所有上市上櫃日K（FinMind TaiwanStockPrice）
輸出：每日清單，欄位：date / stock_id / suffocation_date / vol_ratio（量/max20d）
      / ma20_slope / scenario（A or B）/ signal_bar_type / stop_loss
必要 schema 欄位：open, high, low, close, volume, ma5/10/20/60（可由 features.py 計算）
CLI：python -m scripts.zhuli.entry.suffocation --date 2026-05-19 --top 20
```

Version 0 不做回測，只輸出當日有「窒息量 K」的清單供人工確認。Version 1 接 backtest engine，模擬出量 K 進場 + 跌破低點停損。

---

### G 隔日沖（最小可行版）

```
輸入：日K + 大盤加權/OTC 指數（需確認 FinMind 是否有大盤 TaiwanStockInfo）
輸出：每日速篩清單，欄位：date / stock_id / bb_bandwidth / gain_pct / volume
      / ma20_slope / signal（pass/fail）/ 大盤pass（bool）
必要 schema 欄位：close, high, low, volume, BBands（需 features.py 支援），ma20_slope
CLI：python -m scripts.zhuli.entry.overnight --date 2026-05-19
```

回測時以 `next_open`（隔日開盤價）模擬出場，無法精確模擬 1:20 進場與 8:30 預掛，但可近似計算期望值。

---

### A 大波段（最小可行版）

```
輸入：日K + FinMind 法人買超（TWT38U002 投信；外資需確認 dataset 名稱）
輸出：每日清單，欄位：date / stock_id / inst_buy_ratio / vol_absolute
      / dist_to_ma20 / ma20_slope / ma60_slope / industry_group_count
必要 schema 欄位：close, volume, ma20/60（features.py）+ 法人買超（FinMind）
CLI：python -m scripts.zhuli.entry.swing_breakout --date 2026-05-19 --min-inst-ratio 0.33
族群密度預設：--min-group-count 3（前 N 名買超清單同族群出現 ≥ 3 檔）
```

族群密度判定需要「產業分類」對照表（上市上櫃公司產業碼），FinMind TaiwanStockInfo 已有此欄位。

---

### M 收高開低 filter（最小可行版）

```
輸入：日K（現有）
輸出：輔助標籤，欄位：date / stock_id / signal（bullish_open / bearish_open / neutral）
必要 schema 欄位：open, close, volume（前日）；今日開盤
CLI：以 module 形式 import，不獨立 CLI
    from scripts.zhuli.extras.open_signal import calc_open_signal
    df['open_signal'] = calc_open_signal(df)
```

整合進 H 窒息量 or A 大波段 scanner 的出場輔助訊號；不單獨 backtest。

---

## 4. 共用底層需求清單

Phase 1 四個 scanner 共用以下模組，建議先確認這些底層再動工：

| 模組 | 現況 | Phase 1 可複用程度 |
|---|---|---|
| `scripts/kline/bars.py`（日K 載入）| ✅ main branch 已有 | 100% 直接複用 |
| `scripts/kline/features.py`（MA 系列、布林）| ✅ main branch 已有 MA5/10/20/60、BBands | 100% 直接複用，主力大 ma20_slope 計算可直接取 |
| FinMind throttle client | ✅ stock-analysis-system 已封裝 | 100% 直接複用 |
| 法人買超資料（TWT38U002 投信）| ✅ 已有既有 scanner 使用 | 直接複用 |
| 外資買超資料 | ⚠️ 需確認 dataset 名稱 | 查 FinMind API 一次即可 |
| 大盤加權 + OTC 指數日K | ⚠️ 需確認是否 FinMind 已有 | 隔日沖專用，先查 |
| 流動性過濾（MIN_AVG_VOLUME_20）| ✅ 既有 scanner 已有常數 | 複用，主力大設為 CLI 可調 |
| 20 日最大量計算（rolling max）| ❌ 需新增 | 窒息量策略專用，5-10 行 |

**建議動工前先做的確認（30 分鐘）：**
1. 確認 FinMind 是否有大盤加權 + OTC 指數日K，或需改用其他來源
2. 確認外資買超的 FinMind dataset 名稱（for 大波段策略）
3. 確認 `scripts/kline/features.py` 的 `add_features()` 輸出欄位是否已含 `ma20_slope`

---

## 5. 推薦動工順序

### Top Pick：H 窒息量（zhuli_suffocation）

**動工週期：** 2-3 天
**驗證 metric：**
- 以 `integration_status.md §H` 的 5 個講師案例作 sanity check（嘉澤 3533、南茂 8150、佳邦 6284、光罩 2338、亞德克 1590）
- 期望：5 個案例全部能被 scanner 抓到窒息量 K；出量 K 日期與老師案例誤差 ≤ 2 個交易日
- Backtest：勝率 > 50%（課程宣稱高勝率），平均 MFE（Max Favorable Excursion）> 5%

**動工後接著：M 收高開低 filter（1 天）→ A 大波段（3-4 天）→ G 隔日沖（3-4 天）**

**總 Phase 1 估計週期：** 10-12 工作天（含 backtest 驗證與 Top-N summary 輸出格式）

---

## 6. 給 User 的決策清單

User 拍板前需要確認以下 **9 個決策**：

### 6.1 動工目標（必須拍板）

**[決策 1] 先寫哪個 scanner？**
建議選項：H 窒息量（立即可動工，既有 527 行可重構）
替代選項：M 收高開低 filter（最輕量，適合先練底層整合）

**[決策 2] Phase 1 是一次一個還是並行？**
建議：一次一個（避免共用底層未穩定時多個 scanner 同時踩坑）
替代：H 窒息量 + M 收高開低 filter 同時動工（M 很輕量，幾乎沒有衝突風險）

**[決策 3] 動工在哪個 worktree？**
現況：此 worktree（`course-zhuli-integration`）base master；另有 `course-zhuli-on-main` base main
建議：等截圖 + vision 全補完後才整批搬 docs/，scanner 建議在 `course-zhuli-on-main` 上開發（base main，可直接 PR）

---

### 6.2 量化參數預設值（必須拍板）

**[決策 4] 「大量」倍數 N 預設值**
現況：POC 反推 P25=3.8、Median=4.3（相對於 MA20 的倍數）
需決定：N=4.0 作為預設值是否接受？（CLI 可調，不是固定值）
影響策略：A 大波段、L 量價支撐（輔助）、D 布林上軌（Phase 2）

**[決策 5] 族群密度門檻（大波段策略）**
現況：課程未量化，老師用「同族群多檔」形容
需決定：「≥ 3 檔同族群同日出現在法人買超前列」是否可接受作為預設值？（CLI 可調）

**[決策 6] 「剛上榜」N 天定義（投信策略，Phase 2 會用到）**
現況：課程說「前幾天未上榜」，無精確天數
建議預設：前 10 個交易日無投信買超（CLI 可調）
可現在拍或 Phase 2 前拍

---

### 6.3 回測設計（影響 backtest 引擎的選擇）

**[決策 7] 隔日沖回測是否接受「收盤價近似 1:20 進場」？**
現況：課程要求 1:20-1:25 進場，日K 回測只能用收盤價近似
選項 A：接受（回測快，但有偏差）
選項 B：要求分鐘 K（更準確，但資料成本高）
建議：Phase 1 先用收盤價近似，Phase 2 再接分鐘 K 驗證

**[決策 8] Backtest 是否加 walk-forward validation？**
建議：Phase 1 先不做 walk-forward，用 2019-2023 整段 in-sample 驗證；Phase 2 再加
理由：walk-forward 需要先確認 sanity check 通過，否則疊加複雜度沒有意義

---

### 6.4 補拍截圖（scanner 完備度 vs 現在就動工的取捨）

**[決策 9] 是否先補 ch6-1/6-2 截圖（21+30 張）再動工隔日沖 scanner？**
現況：ch6-1/6-2 各僅 1 張截圖，vision stub 高（67/94），但核心速篩參數已由 PDF + HD vision 確認
選項 A：先動工 scanner，等補拍截圖後確認無額外條件再修正（速度優先）
選項 B：先補拍截圖（API overload 中斷，重拍即可）再動工（準確性優先）
建議：選項 A，隔日沖的核心三條件已精確確認，補拍主要是「心法案例驗證」，不影響 scanner 核心邏輯

---

## 附錄：Phase 1 不動工清單（for 確認範圍）

以下策略明確不在 Phase 1，此次不需拍板：

| 策略 | 原因 | Phase |
|---|---|---|
| B 奇形旗形 | ch4-2 末段 18 張截圖 pending，旗杆上影線門檻需 vision 確認 | 2 |
| D 布林上軌 | 同上，待 ch4-2 補拍 | 2 |
| E 布林回測 | 形態三前置 + 急漲段錨點需 POC | 2 |
| I 投信跟單 | ex2-1/2-2 vision stub 高（76 個），可能有細節缺漏 | 2 |
| C 反轉形態 | 兩高點演算法未定義，需先跑 POC | 3 |
| F 當沖（盤中）| 需分鐘 K 即時資料層 | 3 |
