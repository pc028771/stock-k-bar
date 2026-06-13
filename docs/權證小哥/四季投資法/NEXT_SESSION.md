# 四季投資法 — 後續流程說明

> 最後更新：2026-05-21（含 scanner + backtest session）
> 分支：`worktree-four-seasons-redesign`
> 上次 NEXT_SESSION 為 2026-05-19，已過時，本檔取代

---

## 一、已完成（截至 2026-05-21）

### 1. 章節索引 + PDF + VTT（Step 1-4）
- 31 篇已發布 + 7 篇月度排程
- PDF：CH1-6 共 31 頁（CH7-10 無講義）
- VTT：29 章字幕（12,590 cues、1,906 triggers）

### 2. 截圖（Step 5）— **29/29 章完成**
- **26 章 L3 1920×1080**：ch_trial / ch1-1 / ch1-2 / ch2-1 / ch2-2 / ch2-3 / ch3-1 / ch3-2 / ch3-3 / ch4-1 / ch4-2 / ch5-1 / ch5-2 / ch6-1 / ch6-2 / ch6-3 / ch6-4 / ch7-1 / ch7-2 / ch8-1 / ch9-1 / ch9-2 / ch9-3 / monthly_202603-05
- **3 章對談式（保留 L1）**：ch10-1 / ch10-2 / ch10-3 — 確認無投影片字卡，L1 thumbnail 已足夠
- 總截圖數：約 530+ 張

### 3. Vision 比對（Step 6）— **29/29 章完成**
- 每章 `handwritten_extracts.md` 已產出
- 個股名稱幻覺已修 3 筆：6148 群宏資→驊宏資、3189 瑞碁→景碩、3324 建興電→雙鴻

### 4. course_principles 整合（Step 7）— **22 章 vision 已整合**
- 404 → 904 行
- 新增章節：軟體策略按鈕（24 個）/ 盤中異動 7 訊號 / 波段主力分點 / 軟體欄位字典 / CB 代號↔母股對照表
- 個股案例彙整 61+ 檔
- 主要矛盾修正：豪勉 60 日 13%→13.7%、秋季月線斜率 < 0→介於 -1~0、策略按鈕 30+→24
- ch4-1 秋天短空倉位修正：50%→10%/20%（commit 728b67f，課程外條件移除）

### 5. Audit
- `VISION_AUDIT_2026-05-20.md`：5 章 68 配對代號名稱審查
- `L1_SCAN_REPORT_2026-05-20.md`：L1 sprite 掃描 21 章分類

---

## 二、真正待辦（2026-05-21）

### A. CB 代號確認 — ✅ **全部解決（2026-05-21）**

所有 5 筆原始疑問均已確認：
1. **49163** → 事欣科三 / 4916 事欣科 ✅
2. **36451** → 達邁一 / 3645 達邁 ✅（vision 誤讀為「迅得」）
3. **26107**（原誤記 26100）→ 華航七 / 2610 華航 ✅（末碼 7 誤讀為 0）
4. **允強** → 20341 允強一 / 2034 允強 ✅（原誤記 6020）
5. **2230 春池** → 實為 2230 泰茂 ✅（vision 名稱欄幻覺）

詳見 `course_principles.md §十八` CB 對應表及 `⚠️ 截圖確認` 區段。

### B. 4 個框架缺口（課程本身缺漏，不可自行補完）⏳

READING_REPORT 已標出：

1. **停利規則模糊** — 夏季沒有「跌破幾日線出場」明確規則
2. **加碼條件未定義** — 沒講加碼間隔 / 觸發條件
3. **資金配置比例完全沒講** — 春夏秋冬各放幾成？
4. **秋季短空 SOP 只適用特定型態** — 非通用秋天策略

依 CLAUDE.md「禁止自行加入課程以外的條件」原則，**不可自行補完**。需 user 決策：

- (a) 留白標「課程未說」
- (b) 從 ch10 對談章節（葉芷娟 / 股魚 / 邱沁宜）找補充
- (c) 跑回測自行決定參數，明確標「非課程內容、實證得出」並隔離到 `scripts/kline/extras/`

### C. Scanner / Strategy 寫作 — **第一版已完成 2026-05-21** ✅

#### 已交付（2025-01 ~ 2026-05-14 共 17 個月實證）

1. **`scripts/four_seasons_classify.py`** — 全市場 5 季硬分類器（春/立夏/盛夏/秋/冬/未分類）
   - 100% 課程條件，無外加邏輯
   - 所有「策略/指標方向」hard-coded（§9.1 固定）
   - 所有「具體數值門檻」抽到 `SeasonConfig` dataclass，CLI `--config foo.json` 可調（§9.2）
   - 修補 DB 缺陷：`bb_lower_slope` 全 NULL → 用 DB 同公式 `(latest-5d_ago)/5d_ago*100` 重算
   - CLI：`--date`、`--range START END`、`--season`、`--tickers`、`--config`、`--dump-config`

2. **`scripts/four_seasons_backtest.py`** — 課程化退場規則回測
   - 多單退場：state_change / ma20_break / trailing_stop (8%/6%/2%)
   - 春多單僅 state_change（§三 春停損是基本面非價格）
   - 短空退場：state_change / new_high / limit_up
   - 進場品質閘門：盛夏 must-follow-立夏 + vol_ratio>5 + 量>1000 張；秋短空反彈紅 K >3%
   - 同樣的 config dataclass `BacktestConfig`（trailing 8/6、漲停 9.5、紅 K 3、20 日 lookback）
   - censored cohort 獨立統計

3. **17 個月實證結論**（`backtest_2025_final_*`）：
   - **立夏多 125 筆**：trailing_stop **14 筆勝率 92.9%、中位 +9.19%、8 天**（精華訊號）
   - **盛夏多 27 筆**：trailing_stop 7 筆勝率 57.1%、中位 +9.19%、7 天
   - **秋短空 47 筆**：season_change 24 筆勝率 95.8% +3.40%、2 天；new_high 23 筆 0% 勝率
   - **春多 27 筆**：勝率 25.9%，全部 state_change，課程預設值未證實在這段強市內可靠

4. **configs/strict.json** — 立夏精準版（bb_upper_slope >3）範例

#### 已釐清的設計原則（2026-05-21）

`course_principles.md §九` 已重整為 **§9.1 固定（指標+方向）** vs **§9.2 可調（示範數值）**。
依據 15+ 條講師原話佐證（@ch2/3/5/10/monthly），講師明示：
- **策略結構與指標選擇 固定**（用「必須」「一定要」「規則是」「一律」）
- **具體數值門檻 為示範起點**（用「你可以」「我希望」「至少」「就看你的取向」）

→ 未來改動：只能改 §9.2 表內的「示範數值」，不能改 §9.1 表內的「指標/方向」。

#### 接下來可做

1. **~~`warning_signals_triggered()` stub~~** — ✅ **已實作（2026-05-22）**
   - 量價背離A：price ≥ peak×98% AND vol_ratio_20 < 0.6 → 高點量縮出場
   - 量價背離B：vol_ratio_20 > 3.0 AND 日漲跌 < 1% → 大量滯漲出場
   - **結果**（17個月實證）：盛夏 4 筆 75% win +25.35% / 立夏 19 筆 68.4% win +0.99%
   - 未實作：領頭羊力竭（需跨股資料）/ 情緒指標（無資料）/ 月線兩次跌破（與 ma20_break 優先序衝突）
   - 門檻皆在 BacktestConfig（§9.2 可調），預設 warn_near_peak_pct=2.0 / warn_vol_low_ratio=0.6 / warn_vol_high_ratio=3.0 / warn_price_stall_pct=1.0
   - 輸出：`backtest_2025_v2_trades.csv` / `backtest_2025_v2_report.md`
2. **春多策略待重思** — 預設條件下 25.9% 勝率太低；建議：(a) 春多只在「春→立夏切換」時換倉、不直接平倉，(b) 用更長時段（含完整冬→春→夏 cycle）的歷史資料重測，目前 2025-01 起樣本不足。
3. **盛夏 25% 假突破殘餘** — 7 筆 ma20_break 大虧 -9.03%，需更嚴進場濾鏡或位置管理。
4. **數值調優** — 用 `--config` 嘗試不同參數組合，例如：(a) 立夏 bb_upper_slope 3 vs 1，(b) 盛夏 vol_ratio 8 vs 5，看 win rate / median ret / trailing 觸發比例變化。

### D. 整合層（跨課程，不在本 worktree 做）
四季投資法 + 主力大 + K 線力量整合，參考 memory `project_four_seasons_course.md`。

---

## 三、關鍵 gotcha（給後續 session 看）

### URL pattern
- 課程 URL 用 `/project/{project_id}/articles/{article_id}`（單數 project）
- workflow 文件寫的 `/member/learning/projects/...` 會回 404

### L1 sprite 解析度
- workflow 文件寫 4697×2640，實測 **960×544**（11×11 grid，每 frame 87×49）
- **87×49 對含文字章節完全不夠用**（連標題都讀不出）
- 規則：只要該章「有文字 / 個股代號 / 數字」，**直接 L3**，不要試 L1
- 例外：對談式章節（ch10-1/10-3）無投影片，L1 即可

### L3 下載
- workflow 寫 iframe 同步 XHR；實測 async XHR + responseType='blob' 從 parent page 更穩
- 5 並發 segment download 全程 0 失敗
- `pgrep -f save_server.js || (start server)` 比每次重啟好

### Vision 幻覺模式
- **代號欄讀對、名稱欄誤讀**：監控列表小字 vision 易誤讀（已修 3 筆）
- 同一幻覺會在多個截圖重複出現（如 6148 群宏資 出現 2 次）
- audit 策略：交叉比對「字幕提名稱 vs 畫面寫名稱」分歧處

### SPA 自動跳下一篇
- 影片播完 SPA 跳下一篇 → sessionStorage 累積 + re-navigate 回原章

---

## 四、檔案布局

```
docs/四季投資法/
├── pressplay_four_seasons_article_index.md
├── pdf_extracted/{CH1.md ~ CH6.md, INDEX.md}
├── chapter_summaries/{29 個 ch_*.md}
├── course_principles.md              # 904 行 spec（22 章 vision 已整合）
├── READING_REPORT.md                 # 通讀感想 + 框架缺口
├── L1_SCAN_REPORT_2026-05-20.md      # L1 sprite 分類
├── VISION_AUDIT_2026-05-20.md        # 5 章代號名稱 audit
└── NEXT_SESSION.md                   # 本文件

data/analysis/four_seasons/
├── subtitles/{ch}_{raw.vtt,cues,triggers,shot_timestamps}.json
├── video_screenshots/
│   ├── ch_trial/ ~ ch9-3/            # 26 章 L3 1080p + handwritten_extracts.md
│   ├── ch10-1/, ch10-3/              # 對談章 L1 thumbnail + extracts
│   ├── ch10-2/                       # 部分 L3 + 確認無字卡
│   └── monthly_202603-05/            # 月度排程 L3
├── season_2025_final.csv             # 全市場 17 個月分類（161k 列）
├── backtest_2025_final_trades.csv    # 245 筆交易明細
└── backtest_2025_final_report.md     # 最終回測 markdown 報告

scripts/
├── four_seasons_classify.py          # 全市場 5 季分類器
├── four_seasons_backtest.py          # 課程化退場回測
└── four_seasons_accuracy.py          # forward-return 評估（早期版本，已被 backtest 取代）

configs/
└── strict.json                       # 立夏精準版範例
```

---

## 五、開新 session 怎麼接

1. 讀本文件 + `course_principles.md`
2. 從「二、真正待辦」挑下一步：
   - 想清 CB 代號 → A
   - 想決策框架缺口 → B（討論題，非執行題）
   - 寫 scanner → 先做 B 才能做 C
3. **CLAUDE.md 核心限制**：禁止自行加入課程以外的條件（針對個股操作分析）；spec 缺漏照課程原樣標明，不可自行補完
