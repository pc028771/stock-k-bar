# 四季投資法 — 後續流程說明

> 建立日期：2026-05-19
> 當前 worktree：`/Users/howard/Repository/stock-k-bar/.claude/worktrees/four-seasons-redesign/`
> 分支：`worktree-four-seasons-redesign`（從 main @ 4c2bd90）

---

## 一、已完成

### 1. 章節索引（Step 1）
- 31 篇已發布 + 7 篇月度排程
- 輸出：`docs/四季投資法/pressplay_four_seasons_article_index.md`

### 2. PDF 講義萃取（Step 4）
- CH1-6（共 31 頁），0 OCR 失敗
- CH7-10 講義不存在（只能靠 VTT）
- 輸出：`docs/四季投資法/pdf_extracted/CH1.md ~ CH6.md + INDEX.md`

### 3. VTT 字幕（Step 2-3）
- 29 章（跳過第 1 篇專訪、第 3 篇講義 — 兩篇無影片）
- 12,590 cues、1,906 triggers，全用 textTracks 路徑（無 m3u8 fallback）
- 輸出：`data/analysis/four_seasons/subtitles/{ch}_{raw.vtt,cues,triggers,shot_timestamps}.json`

### 4. 章節摘要 + course_principles 初稿
- 29 個 chapter summaries
- `course_principles.md`（401 行，31 條量化條件）
- `READING_REPORT.md`

### 5. 截圖（Step 5）
- ch3-2（59）、ch4-2（33）、ch9-1（24）、ch9-2（20）= 136 張 L3 1080p
- ch6-4（10）：第一次 L1 sprite 太小（87×49）讀不出文字，已升級為 L3 1080p；L1 備份在 `video_screenshots/ch6-4/L1_sprite_backup/`
- 輸出：`data/analysis/four_seasons/video_screenshots/{ch}/`

---

## 二、待辦（未完成的 workflow 步驟）

### A. Vision 比對（Step 6）⏳

**目標**：每章 jpg vs cues 比對，寫 `handwritten_extracts.md`，撈出畫面有但講師沒明說的條目。

**建議優先序**（依資訊密度）：
1. **ch3-2** — 59 shots，立夏 8 案例 + 選股軟體參數 + 30+ 預設子策略名稱；vision 收穫最大
2. **ch4-2** — 33 shots，CB 案例 + 融券圖、代號字幕不全
3. **ch9-1 / ch9-2** — 工具介面（CB 主力分析系統、盤中當沖神器）— 補完軟體 UI 跟欄位
4. **ch6-4** — 10 shots，量價籌碼框架圖

**派 agent**：
- 用 Sonnet subagent，每章一個 agent（避免單 agent context 爆掉）
- 讀 jpg + 同 timestamp ±15s cues → Edit handwritten_extracts.md
- 末尾加 `## 統整：影響 scanner 的條目`

**已知 sample 發現**（避免 vision 漏看）：
- 講師有兩套自製軟體：**權證小哥 盤中當沖神器**、**可轉債主力分析及套利系統™**、**建財寶籌碼盤**
- 立夏案例三檔具體代號（從 ch3-2_01-25）：6218 豪勉、2884 玉山金、3508 位速
- ch9-1 CB 案例：5245 智晶
- ch6-4 案例：6116 彩晶
- 軟體有 30+ 預設子策略（颮風向上、布林多/空喇叭、剛飆、高息低波 等）— 課程沒明講但畫面有

### B. course_principles 補完 ⏳

當前 `course_principles.md` 是純字幕+PDF 抽取，**還沒整合 vision 發現**。Vision 比對完後要：
- 把畫面確認的個股代號 / 具體價位 / 軟體欄位 補回
- 把 30+ 子策略列入「附錄：選股軟體預設策略名稱」
- 標 ✅（已 vision 驗證）vs ⏳（待驗證）
- 補上講師「沒明說但畫面有」的條件（如位階 / 主力天數的具體欄位定義）

### C. 框架明顯缺口（4 個）需要決定怎麼處理 ⏳

READING_REPORT 已標出：
1. **停利規則模糊** — 夏季沒有「跌破幾日線出場」明確規則
2. **加碼條件未定義** — 沒講加碼間隔 / 觸發條件
3. **資金配置比例完全沒講** — 春夏秋冬各放幾成？課程完全未提
4. **秋季短空 SOP 只適用特定型態**，非通用秋天策略

→ 這些是課程本身的缺漏，**不可自行補完**（CLAUDE.md 規範）。需 user 決定：
- (a) 留白標「課程未說」
- (b) 從週邊資源（葉芷娟 / 股魚 / 邱沁宜 對談章節 ch10 可能有提）找補充
- (c) 跑回測自行決定參數，但要明確標「非課程內容、實證得出」

### D. Strategy / Scanner（最遠程） ⏳

依 CLAUDE.md：「寫 scanner 前 user 確認當前策略完備程度」。Vision 比對 + course_principles 補完後，再跟 user 確認是否動手寫 scanner。

可能的 scanner 切入點：
- 春季「立夏」進場 scanner（量 > 500、月線斜率 < 0.5、上軌斜率 > 1、位階 > 8、乖離年線 < 30%、主力 1/5/10/20 日 > 0）
- 秋季「高檔出貨」警訊 scanner（量價背離、月線下彎、高檔長黑）

### E. 整合層（最遠程，跨課程） ⏳

四季投資法 + 主力大 + K 線力量 的整合是「策略之上的另一個 task」，**不在這個 worktree 做**。
參考 memory：`project_four_seasons_course.md`。

---

## 三、關鍵 gotcha / 經驗（給後續 session 看）

### URL pattern（前例已踩）
- 課程 URL 用 `/project/{project_id}/articles/{article_id}`（單數 project）
- workflow 文件寫的 `/member/learning/projects/...` 會回 404
- 已派 subagent 都記住這個了，但若 workflow 文件下次重寫要修正

### L1 sprite 解析度
- workflow 文件寫 4697×2640，但四季投資法實測是 **960×544**（11×11 grid，每 frame 87×49）
- **87×49 對含文字的章節完全不夠用**（連標題都讀不出來）
- 規則：只要該章「有文字 / 個股代號 / 數字」，直接 L3，不要試 L1

### L3 下載細節
- workflow 寫「iwin.eval() 同步 XHR」 — 實測 async XHR + responseType='blob' 從 parent page 跑更穩
- 5 並發 segment download 全程 0 失敗
- `pgrep -f save_server.js || (start server)` 比每次重啟好

### SPA 自動進下一篇
- 影片播完 SPA 會跳下一篇（ch9-1 處理一半被跳到 ch9-2）
- workaround：sessionStorage 累積資料、re-navigate 回原章續做

### Vision 比對的省 token 規則
- 「畫面顯示」完全同字幕 → 寫「同字幕」
- 「手寫補充」無 → 寫「無」
- 有手寫 / 錯字 / 具體價位 → 詳細記錄
- 不要 padding

---

## 四、檔案布局速查

```
docs/四季投資法/
├── pressplay_four_seasons_article_index.md  # 章節索引
├── pdf_extracted/
│   ├── CH1.md ~ CH6.md
│   └── INDEX.md
├── chapter_summaries/
│   └── ch_trial.md, ch1-1.md ~ monthly_202605.md   # 29 個
├── course_principles.md          # 整合 spec（401 行，待 vision 補完）
├── READING_REPORT.md             # 通讀感想 + 框架缺口
└── NEXT_SESSION.md               # 本文件

data/analysis/four_seasons/
├── subtitles/
│   ├── {ch}_raw.vtt              # 29 章
│   ├── {ch}_cues.json
│   ├── {ch}_triggers.json
│   └── {ch}_shot_timestamps.json
└── video_screenshots/
    ├── ch3-2/  (59 張 L3 1080p)
    ├── ch4-2/  (33 張 L3 1080p)
    ├── ch6-4/  (10 張 L3 1080p, L1_sprite_backup/ 內為舊版)
    ├── ch9-1/  (24 張 L3 1080p)
    └── ch9-2/  (20 張 L3 1080p)
```

---

## 五、開新 session 怎麼接

1. 切回 worktree：
   ```bash
   cd /Users/howard/Repository/stock-k-bar/.claude/worktrees/four-seasons-redesign
   ```
2. 讀本文件 + `course_principles.md` + `READING_REPORT.md` 進入狀況
3. 從「二、待辦」挑下一步開做
4. 切記 CLAUDE.md 規範：**禁止自行加入課程以外的條件**（針對個股操作分析）；spec 缺漏照課程原樣標明，不要自己補完
