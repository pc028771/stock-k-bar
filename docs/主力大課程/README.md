# 主力大課程整理 — Worktree 總覽

> **Worktree:** `course-zhuli-integration`（branch: `worktree-course-zhuli-integration`）
> **起始日：** 2026-05-17 ｜ **最後更新：** 2026-05-18
> **目的：** 整理林家洋（主力大）老師兩套 PressPlay 課程內容，借用 stock-k-bar 框架結構，但 **內容完全獨立、不混入 K線力量教學**。
> **狀態：** 課程整理階段完成（零真實 STUB）；scanner 實作未開始。

---

## 兩套課程

| 課程 | PressPlay Project ID | 性質 | 抓取狀況 |
|---|---|---|---|
| 主力大全方位操盤教戰守則 | `65060FADFE44CB31DDB7175D6471A736` | 一次性教學 | 26 個影片講稿（含時間戳）+ 2 個簡報 PDF |
| 趨勢題材+族群金流+籌碼筆記=交易思維 | `486FF42F3707EF327074AC136F3CA819` | 持續更新訂閱 | 27 篇精華文章（490 篇索引） |

---

## 產出檔案地圖

### 📘 課程內容（4 份核心文件）
| 檔 | 行數 | 用途 |
|---|---|---|
| `course_map_from_scripts.md` | ~770 | 26 講稿 + PDF 補完的章節地圖（**單一事實來源**） |
| `course_principles.md` | ~270 | 三段式：完整規則 / 🔴核心主軸 / 命名規範 |
| `strategy-indicators.md` | ~430 | 13 個策略各自的定義/進場/出場/停損/參數 |
| `strategy-readiness.md` | ~210 | 四象限可用性分流 + Phase 1/2/3 順序 + 風險警示 |

### 📄 輔助資料
| 檔 | 內容 |
|---|---|
| `pdf_extracted_parameters.md` | 兩個 PDF 抓出的量化參數（補完形態四的關鍵） |
| `framework_reuse_map.md` | stock-k-bar 框架可複用結構盤點 |
| `integration_evaluation.md` | 整合評估報告（含 24 個策略單元表） |
| `video_screenshot_necessity.md` | 影片截圖必要性分析（部分章節必要） |
| `pressplay_article_index.md` | 趨勢思維課 490 篇文章索引 |
| `pressplay_jiaozhan_article_index.md` | 教戰守則 31 篇影片索引 |
| `pressplay_video_only_skipped.md` | 14 篇純影片跳過清單 |

### 📰 線上文章內文（補充素材，非主軸）
`pressplay_articles/` 共 **27 個檔**（200KB），來自「趨勢題材」課的本週市場資訊報 + 策略心法分享課 + 月直播課等。

### 🔧 POC 程式 + 資料
| 路徑 | 用途 |
|---|---|
| `scripts/zhuli_large_volume_threshold_poc.py` | 大量閾值反推：講稿+PDF 案例 → FinMind 量分布 |
| `scripts/zhuli_swing_high_viewer_poc.py` | swing high viewer（find_peaks / rolling max 三演算法） |
| `data/analysis/zhuli/large_volume_*.{csv,md}` | POC #2 案例+量比資料（16 筆有效樣本） |
| `data/analysis/zhuli/swing_high_poc/*.png` | POC #3 三個 ticker × 3 演算法 = 9 張比對圖 |

---

## 課程整理狀態

**✅ 零真實 STUB**（原 ch4-2 形態四已從 PDF p.127 補完為「布林回測策略」）

### 已知缺漏（不是 STUB，是課程設計）
- 「大量/爆量」沒給絕對倍數 → 是相對概念（與前一根/前一波比較）
- 「兩高點連線」是肉眼判斷 → POC #3 用 find_peaks 校準後可半自動
- 當沖 SOP 含「等到 10:30 後」這類時間規則 → 需分鐘 K 即時資料層

### 真實量化參數摘要（給 scanner 用）

| 概念 | 數值 | 來源 |
|---|---|---|
| 窒息量萎縮閾值 | 當日量 < 20日最大量的 **10%** | ex1-2 |
| 月線距離條件 | 收盤距 20MA ≤ **5%** | ch3-2 / PDF p.73 |
| 布林回測量縮閾值 | 回測量 ≤ 急漲段大量紅K 的 **1/5（20%）** | PDF p.127 |
| 量縮（短線級別）| 當日量 ≤ 前一根的 **1/2** | ch2-4 line 76-81 |
| 投信首買門檻 | 首日 ≥ **200 張**（可調至 50）| ex2-3 |
| 投信跟單 | 5 日累計 ≥ 股本 **1.5%** | ex2-2 |
| 投信持股預警 | > **12%** | ex2-1 |
| 當沖前夜篩選 | 兩天皆 > **2 萬張**、三天區間振幅 > **8%**、周轉率 > **20%** | ch5-1-1 |

---

## Scanner 實作優先順序（從 strategy-readiness.md）

### Phase 1（立即可動工）
1. `zhuli_swing_breakout`（A 大波段 SOP）
2. `zhuli_suffocation`（H 窒息量）
3. `zhuli_institutional_firstbuy`（J 投信首買）
4. `zhuli_open_signal_filter`（M 收高開低過濾器）

### Phase 2（細節需驗證）
5. `zhuli_pennant`（B 奇形）
6. `zhuli_bbands_break`（D 布林上軌）
7. `zhuli_bbands_pullback`（E 形態四：布林回測）← PDF 補完後可動
8. `zhuli_institutional_swing`（I 投信跟單）
9. `zhuli_overnight`（G 隔日沖）

### Phase 3（需先解 POC）
10. `zhuli_reversal_breakout`（C 反轉形態）— 需 POC #3 swing high 演算法定案
11. `zhuli_intraday`（F 當沖）— 需分鐘 K 即時資料層 + paper trading simulator

---

## 隔離原則 🛑

**主力大課程內容 ≠ K線力量課程內容**，兩者完全獨立：

- ❌ 不可在 `docs/主力大課程/` 引用 `docs/K線力量判斷入門/` 任何規則
- ❌ 不可把兩課程「型態一」「均線支撐」「投信跟單」等同名概念混定義
- ✅ Python 模組/函式/變數一律 `zhuli_` 前綴
- ✅ 共用底層（FinMind client、kline_course_backtest 引擎）可 import，但策略條件獨立
- ✅ docs / scripts / data 目錄結構沿用 stock-k-bar 慣例，內容隔離

詳見 `framework_reuse_map.md` §6。

---

## 下一階段建議

| 優先 | 工作 | 預估 |
|---|---|---|
| 🔴 | 動工 Phase 1 第一個 scanner（建議 `zhuli_suffocation`，參數最完整） | 1 週 |
| 🟡 | ex1-3 影片截圖 + 對講稿撈手寫補充（進行中） | 半天 |
| 🟡 | 補抓「趨勢題材」課剩 17 篇本週市場資訊報 | 半天 |
| 🟢 | 補 ch4-2 形態四口語細節（user 晚一點手動）| 待 user |

---

## Worktree 收尾選項

- **保留繼續用**：Phase 1 scanner 直接在此 worktree 動工
- **Merge 回 master**：4 份策略文件 + 2 個 POC + PDF 萃取資料合進主分支
- **歸檔 branch**：純文件整理階段已完整，可 merge 後留 branch 備查
