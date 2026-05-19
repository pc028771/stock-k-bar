# 下次 Session 接手清單

> **最後 session 結束：** 2026-05-19
> **當前 worktree：** `.claude/worktrees/course-zhuli-on-main`（基於 main，K線力量最新模組化結構）
>
> ✅ **課程內容已全部補完 + 搬到新 worktree**。25 章字幕、26 章 658 張 1080p 截圖、26 章 vision 比對、4 份主 spec + 整合報告。
> ⚠️ 舊 worktree（`course-zhuli-integration`）保留作備份，不要動。Phase 1 scanner 開發在這個 worktree 進行。

## ✅ 已完成

| 項目 | 狀態 |
|---|---|
| 字幕 + triggers + shot_timestamps（25 章）| ✅ |
| 26 章 658 張截圖（全 1920×1080）| ✅ |
| 26 章 vision 比對 + handwritten_extracts.md | ✅ |
| 主 spec（course_principles / strategy-indicators / strategy-readiness）含 HD 整合 | ✅ |
| WORKFLOW（L1/L2/L3 + 解析度判別表）| ✅ `docs/COURSE_EXTRACTION_WORKFLOW.md` |
| Phase 1 scanner 拍板建議 | ✅ `docs/主力大課程/phase1_scanner_proposal.md` |

## 🎯 Phase 1 開發起點

讀 `docs/主力大課程/phase1_scanner_proposal.md` — 4 個候選 scanner（H 窒息量 top pick）+ user 拍板 9 項決策。

進 scanner 開發前需拍板:
1. 先寫哪個 scanner（H 窒息量推薦）
2. 並行 vs 順序
3. 量化預設值（大量 N 倍 / 族群密度 / 投信首買「剛上榜」N 天）

---

## ⚠️ 工作流閘門（不要違反）

1. **補完課程內容前**不更新 `course_principles.md` / `strategy-indicators.md`
2. **寫 scanner 前**先讓 user 確認當前策略完備程度
3. **截圖補抓是 user 親手安排的工作** — 不要自動派 chrome subagent，需 user 明確指示
4. **外部任務（chrome / API）優先派 Sonnet，不要 Haiku**（Haiku 有偽造前科）
5. **外部呼叫產出必須 spot-check 驗證**（檔案數、cue 真實性、檔案 schema）

---

## 已完成（不要重做）

### 字幕（23 章）
全部存在 `data/analysis/zhuli/subtitles/{ch}_{cues,triggers,shot_timestamps}.json`

### 截圖（13 章完整 + 1 章部分）
- ch2-1 (25), ch2-2 (44), ch2-3 (32), ch2-4 (13), ch2-5 (18)
- ch3-1 (12), ch3-2 (17)
- ch4-2_reversal (14), **ch4-2 (45)** — 含補拍部分
- ch5-1 (21), ch5-1-2 (13), ch5-3 (46)
- ch7-1 (17), ch7-2 (3), ch7-3 (23)
- ex1-1 (38), ex1-2 (24), ex1-3 (28)
- ex2-1 (25), ex2-2 (25), ex2-3 (27)
- ch1 (45)

### Vision 已填回 stub（7 章 + 部分）
- ch2-1/2/3/5、ch3-1/2、ch4-2_reversal、ch5-3、ch7-1/2/3、ex1-3、ex1-1/2（字幕版）
- 其餘章節是「字幕版 stub」（畫面欄待補）

### 主文件（4 份，整合到 master scripts/ 結構）
- `docs/主力大課程/course_principles.md`
- `docs/主力大課程/strategy-indicators.md`
- `docs/主力大課程/strategy-readiness.md`
- `docs/主力大課程/course_map_from_scripts.md`

### POC + Scanner
- `scripts/zhuli_large_volume_threshold_poc.py`（22 案例反推大量閾值）
- `scripts/zhuli_swing_high_viewer_poc.py`（mplfinance K圖標 swing high）
- `scripts/zhuli_suffocation_scanner.py`（Phase 1 第一個 scanner，527 行）— ⚠️ **基於 master 舊 import**，搬到 main 後要重寫

---

## 🟡 下次 session 待補

### A. 截圖補拍（共 90 張，9 章）

| 章 | 缺 | 來源 | 備註 |
|---|---|---|---|
| ch4-1 | 8 | `ch4-1_shot_timestamps.json` | B1 時 DRM 卡 readyState=0；Chrome 重啟可能解 |
| ch5-2 | 13 | `ch5-2_shot_timestamps.json` | 同上，canvas 純白 |
| ch6-1 | 21 | `ch6-1_shot_timestamps.json` | B2 開頭只跑 1 張 API overload 中斷 |
| ch6-2 | 30 | `ch6-2_shot_timestamps.json` | 同上 |
| ch4-2 補拍 | 18 | `ch4-2_pending_shot_timestamps.json`（已記前已截 timestamps，pending 自動排除）| B2 跑 45/63 後 overload |

**操作建議：**
1. 確認 Chrome session 健康（user 介入：重啟 Chrome）
2. 派 Sonnet subagent 分小批跑（每 batch ≤ 60 張）
3. ch4-1 / ch5-2 是 EME 卡的，**Chrome 完全重啟後重試**
4. 跑完 vision 比對填回 stub

### B. Vision 比對填回 stub（補拍完才能做）

各章 `data/analysis/zhuli/video_screenshots/{ch}/handwritten_extracts.md` 是「字幕版 stub」，畫面欄是 `[⚠️ 待重拍]`。
補拍完後派 Sonnet 看 jpg + 對字幕 ±15s 填回「畫面顯示」「手寫補充」欄。

### C. 整合到新 worktree（基於 main）

- 新 worktree 已建：`.claude/worktrees/course-zhuli-on-main`（branch `worktree-course-zhuli-on-main`，base main commit `159512c`）
- **只搬 docs + data**（不搬 Python scripts，main 結構不同，scanner 要重寫）
- 廢棄舊 worktree（branch 留 git history）

### D. 重寫 framework_reuse_map_v2.md（基於 main 的 `scripts/kline/` 模組化結構）

main 結構：
- `scripts/kline/bars.py / features.py / course_proxy_constants.py`
- `scripts/kline/{entry,exit,scoring,extras}/` 各種 module
- `scripts/scanner.py` / `scripts/backtest.py` 統一 entry

建議主力大平行結構：
- `scripts/zhuli/{entry,exit,scoring,extras}/`
- `scripts/cross_course/aggregator.py`（跨課程 intersect/union）

### E. 重寫 scanner（在新 worktree）

- `zhuli_suffocation_scanner.py` 改成新模組結構 `scripts/zhuli/entry/suffocation.py`
- 跟 main 統一 `scripts/scanner.py` 整合（CLI `--strategy zhuli_suffocation`）
- 寫前**先 user 確認策略完備程度**（依閘門 #2）

### F. 跨課程 aggregator

`scripts/cross_course/aggregator.py` — 把 kline / zhuli scanner CSV intersect/union/weighted score。

---

## 重要參考檔案

- `docs/主力大課程/README.md` — Worktree 總覽（最後更新 2026-05-18）
- `docs/主力大課程/integration_evaluation.md` — 整合評估 + 24 個策略單元清單
- `docs/主力大課程/framework_reuse_map.md` — ⚠️ **基於 master 已過時**
- `docs/主力大課程/pdf_extracted_parameters.md` — PDF 補完形態四等
- `docs/主力大課程/video_screenshot_necessity.md` — 截圖必要性分析

---

## Memory 提醒（已存）

下次 session 開頭應該已自動載入這些 memory：
- 主力大課程 — 補完前不進 spec、寫 scanner 前 user 確認
- Subagent 在 worktree 寫檔用絕對路徑
- 外部存取必須注意 rate limit
- Haiku 對外部任務可能完全偽造
- 量縮 ≠ 窒息量
