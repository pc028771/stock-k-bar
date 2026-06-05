# K線力量判斷入門 — 擷取報告

**執行時間**: 2026-06-05  
**執行方式**: Chrome MCP + 本地 Python HTTP server (port 7788)  
**目標課程**: K線力量判斷入門 (58篇)

---

## 結果摘要

| 項目 | 數值 |
|---|---|
| 總篇數 | 58 |
| 成功 | 58 |
| 失敗 | 0 |
| 平均檔案大小 | 6,481 bytes |
| 最小檔案大小 | 3,860 bytes |
| 總資料量 | ~375 KB |

---

## 失敗清單

無失敗。全部 58 篇成功擷取。

---

## 重試清單（初次失敗後重試成功）

| order | 文章 | 原因 | 處理 |
|---|---|---|---|
| 10 | 十字線與上影線在攻擊階段的意義(下) | browser_batch race condition (0 chars) | 單獨重試成功 (2691 chars) |
| 14 | 季線與K線高低點 | browser_batch race condition (empty_content) | 單獨重試成功 (1997 chars) |

**原因分析**: `browser_batch` 中 navigate+javascript 連續執行時，SPA 頁面內容尚未完成 React render。改為分開執行 navigate 然後再 javascript 可避免此問題。

---

## Spot-Check 結果

| order | 文章 | 內容長度 | 結論 |
|---|---|---|---|
| 3 | 十字線蘊含的轉折與延續意義 | 2,869 chars | 真實內容確認 |
| 10 | 十字線與上影線(下) | 2,691 chars | 真實內容確認（重試後） |
| 20 | 築底的應對與實務意義 | 4,689 chars | 真實內容確認 |
| 50 | 放空與回補的要點講解 | 2,704 chars | 真實內容確認 |

所有抽查文章均有：
- 完整 frontmatter (title, article_id, source_url, captured_at, course, order, category)
- 實質課程內容（繁體中文說明 + bold 重點 + 圖片連結）
- 無佔位符（「Lorem ipsum」「TODO」「無法載入」等）
- 無偽造跡象

---

## 技術細節

- **選器**: `.article-content`（正確，所有 58 篇均可使用）
- **HTML to Markdown**: 自製 JS 遞迴函式，支援 h1-h4, p, strong, em, a, img, ul/ol/li, blockquote, hr
- **圖片**: 保留為 `![](<url>)` 格式（不下載實體檔案）
- **寫檔方式**: 瀏覽器 `fetch POST` → 本地 Python server → 寫 .md
- **Rate limit**: 每篇各自 navigate+JS，未超過 PressPlay 限制，無 DRM 觸發
- **DRM 狀況**: 無觸發（純文字 + 圖片 URL，不涉及影片 DRM）

---

## 輸出位置

```
docs/K線力量判斷入門/articles/
├── {ARTICLE_ID}_{order:02d}-{標題}.md  (×58)
```

所有文章依 order 01-58 命名，category 分類：
- 單一K線 (1-13)
- 移動平均 (14-15)
- 關鍵K線 (16-17)
- 型態判斷 (18-24)
- 賣壓化解 (25-26)
- 突破跌破 (27-36)
- 價量關係 (37-38)
- 買點賣點 (39-53)
- 停損 (54-55)
- 成本原理 (56-58)
