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
3. **講稿** — 字幕 cues 本身即時間戳講稿
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
- ✋ **補完課程內容前不更新主 spec 文件**（避免 churning）
- ✋ **寫 scanner 前先讓 user 確認策略完備度**

### 命名前綴（跨課程整合）

| 課程 | 前綴 |
|---|---|
| K線力量入門 | `kline_course_`（或無）|
| 主力大全方位 | `zhuli_` |
| 未來其他課程 | 各自獨立前綴 |
| 跨課程 | `cross_course_` |
