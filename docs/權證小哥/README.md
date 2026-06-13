# 權證小哥課程

兩堂同一講師（**權證小哥**）的課程。本目錄為單一講師的單一入口。

| 子目錄 | 課程 | 年代 | 章節 | prefix | 工程狀態 |
|---|---|---|---|---|---|
| `四季投資法/` | 四季投資法 — 透視股票生命週期，掌握你的獲利公式 | 2026 | 31（+月度觀測） | `four_seasons_` | scanner + backtest 已有 |
| `籌碼技術分析/` | 籌碼+技術分析 — 用中長線波段多空交易累積財富 | 2019 | 19 | `xiaoge_` | spec 完成、待 Phase 1+ |

## 為什麼兩個 prefix？

歷史脈絡：
- 2026-05 抓四季投資法時用 `four_seasons_` prefix（當時的架構決策、把它跟主力大/K 線力量完全拆開）
- 2026-06-13 抓籌碼技術分析時，因為兩課內容沒衝突、改用 `xiaoge_` prefix
- DB schema、scripts 都已用 `four_seasons_*` 命名、改名成本高
- 兩 prefix 共存、不衝突；但 docs 合併到此目錄 / memory 從同一個 entry 切入

## 跨課程關係（audit 結論）

詳細見 `籌碼技術分析/cross_course_overlap_audit.md`。摘要：

- **完全一致：** 布林軌道、主力買賣超門檻（0/10/20）、集保戶數、分點、量價
- **新課（四季）獨有：** 可轉債（CB）整套教學、四季敘事、嘉賓觀點、月度觀測
- **舊課（籌碼技術）獨有：** 6 種布林型態命名（升龍拳/降龍掌/曲終人散等）、9+6 多策略交叉、權證教學、進場順序「關鍵分點→投信→外資」
- **衝突：** 零（同一講師、概念一致）

## 工程命名

- `four_seasons_*` — 四季投資法相關 scanner / backtest 模組
- `xiaoge_*` — 籌碼技術分析衍生 detector（**待實作**）
- 跨課程 cross 邏輯 → `cross_xiaoge_*`（同一講師、可融合）

## 入口檔案

**四季投資法**：
- `四季投資法/course_principles.md` — 主 spec
- `四季投資法/pressplay_four_seasons_article_index.md` — 章節索引
- `四季投資法/chapter_summaries/` — 31 章逐章摘要

**籌碼技術分析**：
- `籌碼技術分析/快速上手筆記.md` — 課程精華
- `籌碼技術分析/detector_spec.md` — 6 個 detector 規格
- `籌碼技術分析/implementation_plan.md` — Phase 0-6 計畫
- `籌碼技術分析/pressplay_xiaoge_article_index.md` — 19 章索引
- `籌碼技術分析/cross_course_overlap_audit.md` — 跟四季的 overlap audit

## User 決策摘要（2026-06-13）

1. **分點資料** — 走 FinMind（不爬 Goodinfo、不付費 CMoney）
2. **權證** — 不操作、只當輔助資訊（不做 Phase 6 工程）
3. **權證小哥獨立 tab** — 兩課合併在此目錄、跟 K 線力量 / 主力大平級
