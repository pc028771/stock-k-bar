# Stock K-Bar 專案 Claude 工作準則

## 🚫 核心限制：不可自行加入課程以外的條件

**所有針對個股的操作分析（進場、停損、停利、加碼、出場），只能使用課程明確教過的概念與邏輯。**

### 禁止行為

- 禁止自行發明「減碼比例」（如 1/3、1/2）等課程未提及的倉位管理規則
- 禁止自行加入「盤中確認時機」（如等幾分鐘、等量縮再出）等課程未說明的執行規則
- 禁止自行加入「連續 N 天」等時間型失效條件，除非課程有明確說明
- 禁止將回測分析結論（如 ATR14 停損）套用在個股操作建議上，除非使用者明確要求
- 禁止以「常識」或「一般交易慣例」補完課程沒有說的部分

### 課程框架範圍

目前課程（K線力量判斷入門）明確教過的停損邏輯：

1. **收盤確認**：所有跌破與站回，均以**收盤價**為準，不以盤中價格判斷
2. **結構支撐跌破**：收盤跌破關鍵低點或頸線 → 停損出清
3. **K棒型態**：大黑K完整包覆前段漲幅 → 停損訊號
4. **趨勢特徵消失**：低點越來越高的規律不再成立 → 停損出清
5. **攻擊失敗**：跳空缺口當天回補失敗 → 出場訊號

### 遇到課程沒說的問題

若使用者問到課程未涵蓋的執行細節（如盤中如何判斷、倉位如何分配），應如實回答：

> 「這部分課程沒有明確說明，無法依課程框架給出答案。」

不可自行補完或推測。

## 🔴 交易紀律強制執行

> ## 🚨🚨 必讀復盤（評估老師標的前一定要看）：[`docs/主力大課程/stop_review/2026-06_skip對帳.md`](docs/主力大課程/stop_review/2026-06_skip對帳.md)
> **6 月被我 reflex skip 擋掉的老師明示標的、後來幾乎全噴**（上上週 10 檔被動+封測+光學中位數 +20%、四檔 +45~54%；聯電 120→145.5）。
> **鐵則:老師明示「可參與」的族群名單 = 預設參與。reflex skip 前必先自證「為什麼這檔是例外」、舉證責任在「不參與」那一方。** 選對了才敢大口咬（老師 6/21「大口吃肉 = 對股票+對買點+對部位、少賺要人命」）。詳見 memory `feedback_reflex_skip_pattern` Pattern 4。

**推薦個股 / 評估進場 / 加碼 / 出場前必跑：** memory `feedback_trading_discipline_checklist`（master checklist）

### 紅線（不准踩）

1. 漲停隔日跳空 ≥ +3% → 一律不推（4526 教訓 -12,860）
2. **位階高度判定（依老師原話、不用 strict %）**：
   - ✅ 可進: 在 MA5 上 + 視覺「第 1-2 段紅 K」（波段初期）
   - ⚠️ 灰色: 視覺「第 3 段」紅 K（老師原話「給你賣的」）
   - ❌ 不進: 視覺「第 4 段」末端 / 「離均線非常遠」 / 距 20ma > 30%
   - 來源: 5/19 當沖實戰課 + 5/28 老師「五日線上的都可以」
3. 09:00–12:00 → 不推「快追」、只列 watchlist；13:00 後再評估
4. Core 持倉停損用**結構底**、不是 MA5（8064 東捷教訓）
5. 出清前必跑 `feedback_past_premature_exits` checklist（累積 ~80–90 萬學費）
6. **加碼判準 = 漏斗 3 軸（老師明示 + 籌碼未轉空 + 技術未崩）、漏斗過任何位階都可加。** `feedback_5347_add_position_condition`
   - 🔴 **「漲 +10% 才能加碼」硬門檻已移除**（2026-06-22 user 兩次校正、AI 屢次退回此舊規則）
   - 老師原話「沒漲 10% 加碼沒意義」(5/29) 本質 = **防盲目攤平**、不是位階門檻；6/16 重新解讀 = 漏斗
   - **籌碼 last-mile 轉空（外資/投信在倒）= 漏斗 FAIL → 不加**（即使老師明示 + 技術好）
   - +10% 只在「完全無漏斗憑據（純攤平/我覺得會反彈）」時當擋盲目最後防線
   - 加碼**時點**仍等回測守均線/結構底（別追噴出新高）— 但這是時點、不是「+10% 前提」

### 短線進場三鐵（含當沖）

7. **雙錨停損** = 開盤價 + 昨日收盤價 + 第一根 5 分 K 低（取最高、`feedback_short_swing_entry_discipline`）
8. **前 10 分鐘不切入**（09:00–09:10 只觀察、等回踩 MA10）
9. **前 5 分鐘漲幅 > 5% = skip**（一票否決、整檔今天不碰）

### 訊號分級

- 老師「明示時點」(看進場/今天買) ≠ 只 mention
- broker tier 1（管錢哥/站前哥）confirm 才算強訊號
- 老師代名詞指向必須正確（5347 vs 2476 不准搞混）

## 📺 課程內容解讀分流（強制 Opus xhigh）

**🔥 所有課程講稿 + PressPlay 文章內容、一律派 Opus xhigh subagent 解讀。**

涵蓋：觀盤重點 / 資訊統整培訓 / 全方位培訓班 / 法人籌碼課程 / PressPlay 文章（本週市場資訊報、教學文等）/ 任何老師講稿、直播逐字稿、線上課程字幕。

例外：純資料 lookup（stock_info、broker 名單）可用 Sonnet。判準是「需要綜合推論 vs 純資料查詢」。

| 課程類型 | 模型 | 產出 |
|---|---|---|
| **資訊統整培訓**（觀盤重點）| Opus xhigh | 焦點清單 + **明日盤勢預判**（倒貨/蜜月/整理/蓄勢） |
| **全方位培訓班 / 法人籌碼** | Opus xhigh | **敘事 + 族群方向 + 法人框架**（不看個股、戰略優先） |
| **PressPlay 文章** | Opus xhigh | 看文章類型決定產出（教學/週報/盤前報告各有對應）|

- 戰略結論寫入 `docs/主力大課程/全方位培訓筆記/YYYY-MM-DD_主題.md`
- 老師關鍵句必須**逐字摘錄**（避免解讀走樣）
- 戰略 vs 戰術分歧時**戰略優先**

### 🔴🔴 週報解讀必交叉驗證（user 沒提醒也要自動做、見 memory `feedback_weekly_report_interpretation`）

1. **週報有文字 + 影片兩部分、文字別漏**（很多週報文字含完整本週重點/分點筆記/統計表）。
2. **文字週報列的標的（尤其「波段分點籌碼筆記」）常是掛很久的舊筆記** → 看到「某分點買回某股」**必先用 `scripts/zhuli/broker_tracker.py` 查近 5-6 日該分點是否還在買**、別直接當 actionable 訊號叫 user 抱/進。
3. **優先序：即時籌碼（外資/分點）> 影片最新口徑 > 文字週報舊筆記。** 同檔矛盾時以影片+即時籌碼為準（6/28 華新教訓：文字週報「館前買回」是 6/18-24 舊事、6/25-26 分點已停手、影片老師「洗盤照跌有籌碼也救不了」→ 該砍非抱）。
4. 諧音術語校正（處置股≠儲值/儲滯股）；「大賣超後第 N 天」從**最新一次大賣超日**重算；催化日（法說）是「漲上去了不是買點」、布局在催化前低點。

## 🇹🇼 中文輸出規則（嚴格）

**所有跟使用者互動的中文內容必須是繁體中文台灣用語。**

- 禁止簡體字、大陸用語（如「计算机/屏幕/程序/数据/网络/鼠标」）
- AskUserQuestion 選項 label/description 特別小心：
  - 用詞要短、避免複雜句式
  - 直接打全形括號「（）」即可，不用 Unicode escape `（）`
  - 沒有合適台灣用語時直接用英文（如 backtest、scanner、commit、worktree）
- 工程術語可保留英文（git、commit、subagent、scanner）— 不必硬翻
- 詞彙對照：
  | 台灣用語（用這個）| 大陸用語（避免）|
  |---|---|
  | 電腦 | 计算机 |
  | 螢幕 | 屏幕 |
  | 程式 | 程序 |
  | 資料 | 数据 |
  | 網路 | 网络 |
  | 滑鼠 | 鼠标 |
  | 影片 | 视频 |
  | 軟體 | 软件 |

## 📦 課程外條件隔離規則

**課程內邏輯與課程外邏輯必須物理隔離。**

- `scripts/kline/{entry,exit,scoring}/` 只放**課程內**內容。任何「我們自己定義／回測導出／非課程明說」的條件**禁止**寫進這裡。
- 任何課程外條件**必須**放在 `scripts/kline/extras/`，並以 `extras.` 為命名前綴，預設 OFF，透過 CLI `--extras` 啟用。
- 詳見 `scripts/kline/extras/README.md`。
- 若 audit 發現某個 extra 其實有課程依據，可「升格」搬到課程目錄；反之亦然。

---

## 📥 課程內容擷取工作流程

未來要抓取**任何 PressPlay 線上課程**，依照已驗證的標準流程：

📖 **完整文件：** [`docs/COURSE_EXTRACTION_WORKFLOW.md`](docs/COURSE_EXTRACTION_WORKFLOW.md)

### 7 階段 Pipeline 概要

1. **章節索引** — Chrome MCP navigate + 抓 `.article-card` + 分頁迴圈 → markdown 索引
2. **字幕 VTT** — videojs `textTracks().cues` 首選；EME 卡時走 VHS m3u8 + XHR (`withCredentials + Referer`) fallback
3. **講稿** — 字幕 cues 本身即時間戳講稿；**字幕未生成或無字幕軌時、走 [🔴 SOP `feedback_pressplay_audio_extraction.md`](../../.claude/projects/-Users-howard-Repository-stock-k-bar/memory/feedback_pressplay_audio_extraction.md): m3u8 + ffmpeg + mlx_whisper（5/31 cookie 簡化版、< 5 分完成、禁 QuickTime、必加 `--condition-on-previous-text False`、必 spot-check 股名）**
4. **講義 PDF** — pypdf 文字層 + pdftoppm + tesseract `chi_tra+eng` OCR
5. **截圖** — 三層策略（依需求選）：
   - **L1 Sprite Thumbnail（首選）：** `media-v2.pressplay.cc` sprite + fetch + slice，**繞 DRM**、427×240 native（縮放至 960×540），適用投影片文字/SOP
   - **L2 Canvas drawImage：** per-shot navigate + canvas，1280×720~1920×1080，部分章節會踩 DRM
   - **L3 JWT m3u8 + iframe XHR + ffmpeg：** **iframe context `iwin.XMLHttpRequest`** + 本地 server + ffmpeg per-segment（`-pix_fmt yuvj420p`），**1080p native**，HD 細節需求用
6. **Vision 比對** — Read jpg + 字幕 ±15s → 填回 `handwritten_extracts.md`
7. **Spec 整合** — dedupe vs 現有 docs → 補新條目並標來源時間戳

### 關鍵規範（不可違反）

- ✋ **外部任務（chrome / API）優先派 Sonnet，禁 Haiku**（Haiku 有偽造前科）
- ✋ **外部呼叫產出必須 spot-check 驗證**（檔案是否存在、schema 真實性、數量合理）
- ✋ **Worktree 路徑用絕對路徑**（subagent 易誤寫到主 repo）
- ✋ **每張截圖間 sleep 3s、每 20 張小冷卻 30s、章間 60s、Batch 上限 ≤ 120 張**（L2）
- ✋ **連 2 張 avgRGB 相同 → DRM 觸發，立即停下**（L2）
- ✋ **JWT segment URL 只認 iframe context XHR**（L3，不是 parent page）
- 🔴 **PressPlay session 只能 1 個**：派 agent 抓影片前必 reuse user 既有 tab、禁開新 window 登入（會擠掉 user session）
- 🔴 **m3u8 + ffmpeg + mlx_whisper = audio 轉錄唯一 SOP**：禁走 QuickTime 即時錄音、Whisper 必加 `--condition-on-previous-text False` 避免無限 hallucinate
- ✋ **補完課程內容前不更新主 spec 文件**（避免 churning）
- ✋ **寫 scanner 前先讓 user 確認策略完備度**

### 命名前綴（跨課程整合）

| 課程 | 前綴 |
|---|---|
| K線力量入門 | `kline_course_`（或無）|
| 主力大全方位 | `zhuli_` |
| 未來其他課程 | 各自獨立前綴 |
| 跨課程 | `cross_course_` |
