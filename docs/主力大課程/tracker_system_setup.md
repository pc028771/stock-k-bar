# 主力大每日追蹤系統 — Setup 指南

## 系統架構概覽

```
┌──────────────────────────────────────────────────────────────────────────┐
│  DB: ~/.four_seasons/data.sqlite                                         │
│                                                                          │
│  zhuli_holdings        — 持股 (ticker, avg_cost, shares, is_active)      │
│  zhuli_articles        — 文章 metadata (url, title, source, date)        │
│  zhuli_mentions        — 老師提及記錄 (ticker, level, status, ...)       │
│  zhuli_stance_shifts   — 大方向轉折記錄                                   │
│  zhuli_metadata        — 系統 metadata (last_check_ts 等)                │
│  publish_queue         — 推送佇列 (pending/done, notion/slack)            │
└──────────────────────────────────────────────────────────────────────────┘

launchd (週一~五 07:00)                    launchd (每小時)
       │                                          │
       ▼                                          ▼
morning_report.py                     article_watcher.py check-interval
  讀 holdings + DB baseline                寫 /tmp/*trigger*.flag
  算停損訊號 + Ch2 警示
  寫 /tmp/morning_report_<date>.md
  寫 /tmp/morning_report_<date>_summary.md

       │                                          │
       ▼                                          ▼
publish.py enqueue (可選)          Claude session 看到 flag
  加入 publish_queue                   chrome MCP 抓 PressPlay
                                       tracker.py add
                                       publish.py enqueue
                                              │
                                              ▼
                                    Claude session 跑 publish.py drain
                                       Notion MCP 建頁面
                                       Slack MCP 推摘要
                                       mark-done
```

## 各 Script 說明

### `scripts/zhuli/tracker.py` — 核心追蹤 DB

**新增 holdings 功能（Phase 1 擴展）**：

```bash
# 初始化 schema（首次使用）
python scripts/zhuli/tracker.py init

# 加入持股
python scripts/zhuli/tracker.py add-holding 8064 \
    --name 東捷 --avg-cost 130.21 --shares 7000 --entry-date 2026-05-18

# 列出 active 持股
python scripts/zhuli/tracker.py list-holdings

# 出場（標記 is_active=0）
python scripts/zhuli/tracker.py close-holding 8064
```

**原有功能（老師追蹤記錄）**：

```bash
# 手動加老師 mention
python scripts/zhuli/tracker.py add 8064 \
    --name 東捷 --date 2026-05-18 --level L4 --status 主推

# 顯示 dashboard
python scripts/zhuli/tracker.py dashboard --window 14

# 列所有 mentions
python scripts/zhuli/tracker.py list
```

---

### `scripts/zhuli/morning_report.py` — 每日晨報

**功能**：
1. 讀 `zhuli_holdings` active 持股
2. 對每檔：
   - 老師最新 stance（從 zhuli_mentions）
   - 課程 5 大停損訊號檢核（昨收基準）
   - Ch2 + 籌碼警示（`baseline_ch2_warnings`）
   - MA5/10/20/60 扣抵預判亮燈
   - 開盤情境預備動作 A/B/C/D

**輸出**：
- `/tmp/morning_report_<YYYY-MM-DD>.md` — 詳細版
- `/tmp/morning_report_<YYYY-MM-DD>_summary.md` — 摘要版（Slack 用）

**用法**：

```bash
# 今天的報告
python scripts/zhuli/morning_report.py

# 指定日期（補跑）
python scripts/zhuli/morning_report.py --date 2026-05-20

# 指定輸出路徑
python scripts/zhuli/morning_report.py --output /tmp/my_report.md
```

**限制**：
- 只用 DB baseline（昨收），不呼叫 Fubon 即時 API
- 即時盤中監控請搭配 `watchlist_intraday.py`
- 報告基準是昨收，非當日即時價

---

### `scripts/zhuli/article_watcher.py` — 文章監控（觸發器）

**設計說明**：
此 script 是「觸發器」而非「爬蟲」。PressPlay 文章抓取需要 Claude session + chrome MCP，
daemon 環境無法執行。因此採用 Trigger-Flag 模式。

**用法**：

```bash
# 觸發 check（launchd 自動呼叫）
python scripts/zhuli/article_watcher.py check-interval

# 查狀態
python scripts/zhuli/article_watcher.py status

# 列待處理 flags
python scripts/zhuli/article_watcher.py list-flags

# 標記 flag 已處理
python scripts/zhuli/article_watcher.py mark-done /tmp/article_watcher_trigger_*.flag

# 手動記錄一篇文章（Claude session 抓到後）
python scripts/zhuli/article_watcher.py record-article \
    --url "https://pressplay.cc/..." --title "老師文章標題" --date 2026-05-21
```

---

### `scripts/zhuli/publish.py` — 推送佇列

**設計說明**：
Notion + Slack 推送需要 Claude session + MCP。此 script 提供 SQLite 佇列，
daemon 只 enqueue，Claude session 跑 drain 實際推送。

**用法**：

```bash
# 加入 Notion 推送佇列
python scripts/zhuli/publish.py enqueue \
    --type notion \
    --title "晨報 2026-05-21" \
    --content-file /tmp/morning_report_2026-05-21.md \
    --parent-id <notion_page_uuid>

# 加入 Slack 推送佇列
python scripts/zhuli/publish.py enqueue \
    --type slack \
    --title "晨報摘要" \
    --content-file /tmp/morning_report_2026-05-21_summary.md \
    --channel-id C08XXXXXXXX

# 列佇列
python scripts/zhuli/publish.py list

# Drain（Claude session 跑）
python scripts/zhuli/publish.py drain

# 標記完成
python scripts/zhuli/publish.py mark-done 1 --notion-url "https://notion.so/..."
```

---

## launchd 安裝步驟

### 1. 複製 plist

```bash
cp scripts/zhuli/launchd/com.howard.zhuli.morning_report.plist ~/Library/LaunchAgents/
cp scripts/zhuli/launchd/com.howard.zhuli.article_watcher.plist ~/Library/LaunchAgents/
```

### 2. 載入

```bash
launchctl load ~/Library/LaunchAgents/com.howard.zhuli.morning_report.plist
launchctl load ~/Library/LaunchAgents/com.howard.zhuli.article_watcher.plist
```

### 3. 確認

```bash
launchctl list | grep zhuli
# 應看到 com.howard.zhuli.morning_report 和 com.howard.zhuli.article_watcher
```

### 4. 手動測試

```bash
launchctl start com.howard.zhuli.morning_report
launchctl start com.howard.zhuli.article_watcher
```

### 5. 查 log

```bash
tail -f /tmp/zhuli_morning_report.log
tail -f /tmp/zhuli_morning_report_err.log
tail -f /tmp/zhuli_article_watcher.log
```

### 停用

```bash
launchctl unload ~/Library/LaunchAgents/com.howard.zhuli.morning_report.plist
launchctl unload ~/Library/LaunchAgents/com.howard.zhuli.article_watcher.plist
```

---

## Claude Session Orchestration

### 晨報推送流程（每日開盤前）

```
1. launchd 07:00 → morning_report.py 產出 /tmp/morning_report_<date>.md

2. Claude session 手動觸發（或 loop skill）:
   python scripts/zhuli/publish.py enqueue \
       --type notion --title "晨報 2026-05-21" \
       --content-file /tmp/morning_report_2026-05-21.md \
       --parent-id <notion_page_uuid>

   python scripts/zhuli/publish.py enqueue \
       --type slack --title "晨報摘要" \
       --content-file /tmp/morning_report_2026-05-21_summary.md \
       --channel-id C08XXXXXXXX

3. python scripts/zhuli/publish.py drain
   → Claude session 讀 pending，用 MCP 推:

   # Notion
   mcp__claude_ai_Notion__notion-create-pages(...)

   # Slack
   mcp__claude_ai_Slack__slack_send_message(...)

4. python scripts/zhuli/publish.py mark-done <id> \
       --notion-url "https://notion.so/..."
```

### 文章監控流程（每日 Claude session 開啟時）

```
1. python scripts/zhuli/article_watcher.py list-flags
   → 若有 flag 表示 daemon 已觸發

2. Claude session 用 chrome MCP 抓 PressPlay 最新文章:
   mcp__claude-in-chrome__navigate + get_page_text

3. 比對 zhuli_articles DB，找新文章

4. 解析老師內容:
   python scripts/zhuli/article_watcher.py record-article \
       --url "..." --title "..." --date 2026-05-21

   python scripts/zhuli/tracker.py add 8064 \
       --name 東捷 --date 2026-05-21 --level L4 --status 主推 \
       --quote "老師原話..."

5. python scripts/zhuli/article_watcher.py mark-done <flag_path>

6. （可選）加入 publish 佇列推送 Notion/Slack
```

---

## 首次設定 Checklist

- [ ] `python scripts/zhuli/tracker.py init` — 建立所有 schema
- [ ] 加入現有持股（`tracker.py add-holding`）
- [ ] 加入老師近期 mentions（`tracker.py add`）
- [ ] 複製 plist 到 `~/Library/LaunchAgents/` 並 load
- [ ] 手動測試：`launchctl start com.howard.zhuli.morning_report`
- [ ] 確認 `/tmp/morning_report_<today>.md` 產出正確
- [ ] 設定 Notion parent page id（`--parent-id`）
- [ ] 設定 Slack channel id（`--channel-id`）

---

## 限制 / Caveats

| 項目 | 說明 |
|------|------|
| 即時股價 | morning_report.py 只用 DB 昨收，不呼叫 Fubon API |
| Notion 推送 | 需 Claude session + Notion MCP（不能 daemon 直接呼叫） |
| Slack 推送 | 需 Claude session + Slack MCP |
| PressPlay 抓取 | 需 Claude session + chrome MCP（不能 daemon 執行） |
| 停損訊號 | 基於 DB 昨收；課程規定**收盤確認**，不以盤中判斷 |
| Ch2 警示 | 需 standard_daily_bar + institutional_investors 資料 |
| launchd Python | plist 用 `/usr/bin/env python3`，若用 conda/venv 需調整路徑 |
