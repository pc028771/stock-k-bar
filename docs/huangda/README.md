# 黃大（Chihming）盤中 MACD DIF 策略 — 文件索引

## 誰是黃大

黃大（Facebook Messenger 暱稱 Chihming Huang）是一位獨立的個人投資者，與本專案 user 為私交。他教授的是**多時間框架 MACD DIF 共振 + 盤中即時執行**的操作策略，以記憶體族群（南亞科 2408、力積電 6770）為主要實戰標的，亦操作群創（3481）、台積電（2330）等。

內容來源：2026-02-01 ~ 2026-04-02 的 Facebook Messenger 直接對話與群組對話，由 user 整理至 `stock-analysis-system/notes/` 目錄。

## 為什麼獨立成 docs/huangda/

黃大策略與本專案現有兩套課程體系在**指標工具、時間框架、操作哲學**上均有本質差異：

| 面向 | 主力大課程（老師）| K 線力量入門 | 黃大策略 |
|------|-----------------|------------|---------|
| 核心工具 | 籌碼 + 主力分點 | K 棒型態 + 位階 | MACD DIF 多框架共振 |
| 主操作框架 | 日線 / 週線 | 日線收盤確認 | 60 分 K（盤中即時）|
| 多空操作 | 以做多為主 | 以做多為主 | 多空雙向 |
| 執行節奏 | 收盤確認 次日執行 | 收盤確認 | 盤中 DIF 穿越即刻執行 |

若混入主力大課程的進場 / 出場 / 評分邏輯，會直接污染課程內架構，違反 CLAUDE.md 核心紀律。因此所有黃大相關內容只放 `docs/huangda/`，不寫進 `docs/主力大課程/` 或 K 線力量入門任何目錄。

## 來源檔案對應關係

| 來源檔案 | 性質 | 在本 docs 的對應 |
|---------|------|----------------|
| `intraday_strategy.md`（273 行）| 已結構化 SOP，逆向推導自實際交易 | `intraday_macd_dif_strategy.md` 的骨幹 |
| `macd_dif_strategy_research_2026Q1.md` | EOD 回測研究（251 筆）+ §8 老師對話確認 | `backtest_2026q1_summary.md` |
| `空單操作規則.md` | 從力積電 3/24~3/27 實戰提煉的空單條件 | 補充進 `intraday_macd_dif_strategy.md` §3 |
| `messenger_chihming_20260331_20260401.md` | 4/1 開盤等待 + 小時優先確認 | `teacher_quotes.md` + SOP §2 §4 |
| `messenger_chihming_20260304_20260401.md` | 完整直接對話（3/4 ~ 4/2）| `teacher_quotes.md` 主要來源 |
| `messenger_group_20260201_20260401.md` | 群組對話（含 line 1007 的 30 分框架）| `teacher_quotes.md` + SOP §1 補充 |
| `trading_signals.md` | 訊號紀錄整理（含實戰案例）| `backtest_2026q1_summary.md` 對齊率表 |

## 各文件簡介

- **`intraday_macd_dif_strategy.md`**：核心 SOP 清版。包含 4 時間框架、進出場規則、底單架構、當沖、連動操作等，每段都有黃大原話佐證。
- **`teacher_quotes.md`**：逐句抓出黃大在 Messenger 說的原話，格式為表格，含日期、來源、對應 SOP 段落，方便日後查核。
- **`backtest_2026q1_summary.md`**：EOD 策略回測核心結論（251 筆、勝率 45%、EV +1.85%），以及盤中策略與 EOD 策略的邊界聲明。

## ⚠️ CLAUDE.md 紅線聲明

根據 CLAUDE.md「不可自行加入課程以外的條件」的核心紀律：

- 黃大策略**不是課程**，是私人 Messenger 對話中的操作實踐
- 所有黃大相關內容**禁止**寫進 `scripts/kline/entry/`、`scripts/kline/exit/`、`scripts/kline/scoring/`，也禁止寫進 `scripts/zhuli/` 的課程核心邏輯
- 未來若要將黃大 DIF 過濾器實作為輔助工具，必須放在 `scripts/zhuli/extras/` 並以 `extras.huangda_` 為命名前綴，預設 OFF，透過 CLI `--extras` 啟用
- 黃大的停損邏輯（指標翻轉即出）與主力大的結構底停損、K 線力量入門的收盤確認，**不可交叉混用**

## 🚫 永不升格主力大 Ch5 spec（2026-05-29 user 明示）

**黃大方法永遠停留在 extras 隔離區、永不升格進主力大 Ch5 或任何主課程 spec**。

即使未來在主力大的當沖復盤課中聽到老師偶然提及 MACD / DIF / 紅綠柱等概念，那也只算「老師個人偶用」、不代表主力大課程體系規範。黃大方法論獨立於：

- `docs/主力大課程/course_map_from_scripts.md`（Ch5 spec 主檔）
- `docs/主力大課程/intraday_sop.md`（盤中執行 SOP）
- `docs/主力大課程/ch5_audit_report_20260528.md`（Ch5 audit）
- 任何 `scripts/zhuli/{entry,exit,scoring}/` 目錄

**驗證證據（2026-05-29）**：主力大 5/19 + 5/1 兩堂當沖復盤課逐字稿（1476 行）grep `MACD|DIF|DEA|柱狀|背離|快慢線` — **零命中**。確認黃大 MACD 與主力大 Ch5 是完全獨立的方法論。

理由：兩位老師的工具集、時間框架、操作哲學本質不同。混用會導致兩套系統都失去解釋力。寧可平行運行、用 `--extras` 開關獨立啟用、可清楚 attribute 績效來源。
