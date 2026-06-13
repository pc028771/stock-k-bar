# 權證小哥 detector 實作計畫

> 對應 spec：`docs/權證小哥課程/detector_spec.md`
> 對應筆記：`docs/權證小哥課程/快速上手筆記.md`

---

## Phase 0 — 文件 + 課程整理（本階段、純文件）

- [x] 階段 1：抓章節索引（`docs/權證小哥課程/pressplay_xiaoge_article_index.md`）
- [x] 階段 2：抓所有字幕 VTT（`data/analysis/xiaoge/transcripts/ch01-19.txt`、19 章 ~ 180 分鐘）
- [x] 階段 3：講稿整理 + 截圖需求清單
- [ ] 階段 4：必要截圖補抓（見「需要截圖的章節」表、可派 subagent）
- [x] 階段 5：快速上手筆記
- [x] 階段 6：detector 規格書
- [x] 階段 7：implementation plan（本文件）
- [ ] 階段 8：commit to main

---

## Phase 1 — 資料源 audit（高優先）

> **這一步沒做完就不要開工程**。決定 detector 4/5 是否能做。

### Tasks

- **task 1.1**：列出 detector 1-6 需要的所有資料欄位（個股 K、分點買賣超、外資/投信/自營商、集保戶數、大戶持股、5MA/20MA 等）。
- **task 1.2**：對照 `stock-analysis-system/` 既有 client / DB schema 找出哪些已有、哪些缺。
- **task 1.3**：FinMind 完整盤點 — 確認 `TaiwanStockShareholding` (集保戶) / `TaiwanStockHoldingSharesPer` (大戶持股) / 機構買賣超 dataset 的 schema 與更新頻率。
- **task 1.4**：**最關鍵** — 分點資料 audit：
  - 確認 FinMind 是否有「個股 × 日 × 分點」買賣超表（目前 MEMORY 沒記錄這條）
  - 若無 → 給 user 三方案選擇：付費 CMoney API / 爬 Goodinfo / 用機構買賣超代理
- **task 1.5**：產出 `docs/權證小哥課程/data_audit.md`，列出每個 detector 的可行性 + 阻塞點。

### 預期產出
- `docs/權證小哥課程/data_audit.md`
- 對 user 提的決策請求清單（detector_spec.md 第 「待 user 決策的開放問題」 6 條）

### 依賴
- 需要 user 對「分點資料來源」拍板 → 才能繼續 Phase 2/3。

---

## Phase 2 — 單一 detector 原型：xiaoge_bb_squeeze_breakout

> 選最容易量化、資料依賴最少的先做（只需日 K + 布林指標）。

### Tasks

- **task 2.1**：寫 `scripts/xiaoge/entry/bb_squeeze_breakout.py`，輸入 ticker → 輸出觸發訊號 + 帶寬 + 突破日。
- **task 2.2**：寫 backtest 程式碼，跑 2026-05-01 ~ 2026-06-12 樣本，產出：
  - 訊號數
  - 平均報酬 / Win rate / Max DD
  - 對照 K 線力量 / zhuli 的同期表現
- **task 2.3**：對照「離開上軌 = 停利」規則跑出場（**這是課程明說、不要自加 ATR**）。
- **task 2.4**：spot check 5 檔已知強勢股（如 3037 欣興、3163 波若威等 scanner_q1_top10）是否被抓到。
- **task 2.5**：產出 `docs/權證小哥課程/backtest_bb_squeeze.md`。

### 預期產出
- `scripts/xiaoge/entry/bb_squeeze_breakout.py`
- backtest 報告

### 依賴
- Phase 1 完成
- 日 K + 布林指標資料可用（基本上已有）

---

## Phase 3 — 其他 detector

### 3a. xiaoge_main_chip_holder（中優先、半依賴分點資料）

- **task 3.1**：用「機構買賣超合計」代理「主力買賣超」實作 detector 2（先做、不等分點資料）。
- **task 3.2**：接 FinMind 集保戶數、做週粒度比對。
- **task 3.3**：backtest 同 Phase 2 程序。

### 3b. xiaoge_key_broker_signal（高依賴分點資料）

- **task 3.4**：等 Phase 1 task 1.4 拍板後再啟動。
- **task 3.5**：若拿到分點資料 → 對每檔股票建立關鍵分點池（離線、batch job）。
- **task 3.6**：每日 scanner 接入「池中分點 vs 今日 top 買賣方」比對。

### 3c. xiaoge_main_chip_distribution（exit / warn detector）

- **task 3.7**：依 detector_spec.md detector 3 條件實作、加進 daily_brief 持倉警示流程。

---

## Phase 4 — 整合 + cross_xiaoge_swing

- **task 4.1**：實作 `scripts/xiaoge/scoring/cross_xiaoge_swing.py` — 把 detector 1/2/4 三維打分 (A+ / A / B / C)。
- **task 4.2**：跟 `scripts/kline/scoring/` 既有 cross_scanner 對比 — 看 xiaoge 是否提供額外 edge / 純 duplicate。
- **task 4.3**：跑大樣本 backtest（2026 YTD），對比：
  - cross_xiaoge_swing alone
  - cross_kline alone
  - cross_xiaoge ∩ cross_kline（共識訊號）

---

## Phase 5 — 接入 daily scanner

- **task 5.1**：把 cross_xiaoge_swing 結果寫入 `data/analysis/xiaoge/daily_signals.json`。
- **task 5.2**：daily_brief 流程加入 xiaoge_signal section（A+ 推主筆、A watchlist、B 觀察）。
- **task 5.3**：跟既有 zhuli_ / kline_course_ 訊號 dedup + 一致性檢查。
- **task 5.4**：更新 CLAUDE.md / MEMORY 加進「xiaoge_」prefix 來源說明。

---

## Phase 6（選配）— xiaoge_warrant_pick_helper

> 老師 ch19 明確「差槓比低 + 比較價內 + 好券商」3 口訣。

- **task 6.1**：盤後抓元大權證網 / 凱基 / 統一權證列表（要不要做、user 決定）
- **task 6.2**：score = f(差槓比、價內外、發行商) 排序
- **task 6.3**：當 stage 2/3 加碼想用權證時、提供候選清單（**屬於 extras 範疇、不是進場 detector**）

---

## 依賴關係 + 風險

### 阻塞點
- **R1（最大）**：分點資料是否能取得 / 何種成本 → 影響 detector 4/5 是否能落地。
- **R2**：集保戶數只有週粒度（FinMind），detector 2/3 觸發精度受限。
- **R3**：「主力 ≥ 20 張」門檻在中小型股可能過鬆 / 過嚴 → 需 Phase 1-2 backtest 校正。

### 風險緩解
- **沒有分點資料時**：detector 1/2/3/5 都可以先做（用機構買賣超代理）；detector 4 暫緩。
- **集保戶數週粒度**：用「`本週 - 上週` 環比」+ 週末更新後生效，daily_brief 用最新可得值。

---

## Tasks 一覽

> 寫入 TaskCreate 時用這個清單；先別自動建、等 user 拍板再批次建。

### Phase 1 — 資料源 audit
- T1.1 列出 detector 1-6 資料欄位需求
- T1.2 stock-analysis-system schema 對照
- T1.3 FinMind dataset 盤點（集保戶 / 大戶持股 / 機構買賣超）
- T1.4 **分點資料三方案 (CMoney / 爬蟲 / 機構代理) 給 user 決策**
- T1.5 產出 `data_audit.md`

### Phase 2 — bb_squeeze_breakout 原型
- T2.1 實作 `scripts/xiaoge/entry/bb_squeeze_breakout.py`
- T2.2 backtest 2026-05-01 ~ 2026-06-12
- T2.3 「離開上軌停利」出場規則接線
- T2.4 spot check 對照 scanner_q1_top10
- T2.5 backtest 報告

### Phase 3 — 其他 detector
- T3.1 `main_chip_holder` 用機構代理先做
- T3.2 集保戶數接入
- T3.3 backtest
- T3.4 **（等 T1.4）** `key_broker_signal`
- T3.5 關鍵分點池離線 build
- T3.6 每日 scanner 接入
- T3.7 `main_chip_distribution` exit warn

### Phase 4 — cross_xiaoge_swing
- T4.1 三維打分實作
- T4.2 跟 cross_kline 對比 edge
- T4.3 大樣本 backtest

### Phase 5 — daily scanner 整合
- T5.1 寫 daily_signals.json
- T5.2 daily_brief 加 xiaoge section
- T5.3 跟既有訊號 dedup
- T5.4 更新 CLAUDE.md / MEMORY

### Phase 6 — 權證 helper（選配）
- T6.1 抓權證列表
- T6.2 score 排序
- T6.3 stage 2/3 加碼候選清單

---

## 開工前須確認（給 user 的問題）

1. **分點資料來源拍板**（detector 4/5 阻塞點）：付費 / 爬蟲 / 機構代理三選一
2. **xiaoge prefix 是否獨立 daily_brief section、還是 merge 進 cross_scanner**
3. **Phase 6（權證 helper）要不要做** — 還是只當文件保留、不工程化
4. **截圖**（detector_spec.md 列了 12 個必截章節）什麼時候派 subagent 抓
