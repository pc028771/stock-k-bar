# K線力量判斷入門：後續驗證任務計畫

狀態日期：2026-05-10

目的：把後續策略研究拆成可執行 task，並標註每個 task 建議使用的模型，避免後續工作偏離「先做可驗證、可交易的策略原型」這條主線。

模型選擇原則：

- `haiku`（claude-haiku-4-5）：明確的 Python、SQLite、CSV、回測、掃描器與報告產出。
- `sonnet`（claude-sonnet-4-6）：需要一些研究判斷與工程實作並重，例如失敗樣本歸因、策略參數整理、資料結構設計。
- `opus`（claude-opus-4-7）：需要高度策略語意理解、主觀圖形規則轉量化、研究方向取捨或跨文件整合。

## Phase 1：假跌破收回策略補強

| Task | 狀態 | 建議模型 | 目標 | 產出物 |
| --- | --- | --- | --- | --- |
| 1. 交易成本、流動性、注意/處置排除、隔日確認、簡單停損 | 已完成 | `haiku` | 確認 `false_breakdown_reclaim` 在基本可交易限制下是否仍有邊際。 | `backtests/false_breakdown_strategy_check.md`、`false_breakdown_strategy_summary.csv` |
| 2. 加入市場環境 regime | 已完成 | `haiku` | 分開檢查大盤月線/季線上方、下方、盤整時的策略表現。 | `backtests/false_breakdown_strategy_check.md`、`false_breakdown_strategy_regime_summary.csv` |
| 3. 改良停損 | 已完成（第一輪） | `haiku` | 測 ATR 停損、箱型低點停損、跌破後隔日不站回停損。 | `backtests/false_breakdown_strategy_check.md`、`false_breakdown_strategy_stop_model_summary.csv` |
| 4. 失敗樣本分析 | 已完成 | `sonnet` | 找出假跌破後 10 日仍下跌的共同特徵，形成排除條件。 | `backtests/false_breakdown_failure_analysis.md`、`false_breakdown_failure_filter_candidates.csv` |
| 5. 每日掃描輸出 | 已完成（第一輪） | `haiku` | 產生可每日使用的 watchlist：候選股、關鍵價、確認狀態、停損價、分數。 | `backtests/false_breakdown_daily_scanner.md`、`false_breakdown_daily_scanner.csv`、`false_breakdown_daily_scanner_recent20d.csv` |

Phase 1 完成標準：

- 不是只知道訊號有效，而是能每天產生候選清單。
- 每檔候選股至少要有進場觀察價、關鍵價、停損參考與排序分數。
- 報告要清楚說明策略適合的大盤環境與不適合的情境。

## Phase 2：突破攻擊策略

| Task | 狀態 | 建議模型 | 目標 | 產出物 |
| --- | --- | --- | --- | --- |
| 6. 驗證 `breakout_attack` 可交易版本 | 已完成 | `haiku` | 加入交易成本、流動性、注意/處置排除，確認創高突破是否仍有邊際。 | `backtests/breakout_attack_strategy_check.md`、`breakout_attack_strategy_summary.csv` |
| 7. 驗證 `breakout_next_not_low_open` | 已完成 | `haiku` | 確認「突破後隔日不開低」能否作為攻擊品質濾網。結果顯示它改善 close-basis 走勢品質，但沒有改善實際隔日開盤進場報酬。 | `backtests/breakout_next_open_quality_check.md`、`breakout_next_open_quality_summary.csv` |
| 8. 加入分K攻擊品質 | 已完成（第一輪） | `sonnet` | 用 FinMind 分K檢查午盤後是否跌破開盤、收盤是否接近日高。結果顯示 `next_not_low_open` 在近期分層樣本中具有更強攻擊品質與較佳 10 日報酬，但仍不足以推翻全樣本日K結果。 | `backtests/breakout_intraday_quality_check.md`、`breakout_intraday_quality_summary.csv` |
| 9. 建立強勢股觀察清單 | 已完成（第一輪） | `haiku` | 把突破攻擊訊號做成每日強勢股 watchlist，並加入 `breakout_next_not_low_open`、`intraday_strong_attack`、`below_open_after_1130` 排序加權。 | `backtests/breakout_daily_scanner.md`、`breakout_daily_scanner.csv`、`breakout_daily_scanner_recent20d.csv` |

Task 9 第二輪補強（已完成）：

- 新增 `--strict-filter-profile`（`off` / `balanced` / `aggressive`）硬過濾模式。
- 新增 `breakout_daily_scanner_topn_summary.csv`，用 `Top5/Top10/Top20` 歷史報酬檢查排序品質。
- `balanced` 版目前 `Top5` 優於全體候選（10 日與 20 日平均淨報酬較高）。

Phase 2 完成標準：

- 突破策略要和假跌破策略分開，避免反轉與趨勢邏輯混在一起。
- `breakout_next_not_low_open` 不直接當獨立買點；可先作為近期市場、特別是 `range` regime 的條件式品質加分項。
- 分K資料只用來確認攻擊品質，不先把規則做得過度複雜。

## Phase 3：圖形與壓力區

| Task | 狀態 | 建議模型 | 目標 | 產出物 |
| --- | --- | --- | --- | --- |
| 10. 建立箱型、頸線、頭部、底部標註格式 | 已完成 | `opus` | 把課程圖形語意轉成可標註欄位與資料格式。 | `backtests/pattern_labeling_spec.md` |
| 11. 驗證真正跌破與假跌破差異 | 已完成 | `sonnet` | 用標註後的箱型/頸線資料重新檢查 `real_breakdown_after_range`。新版加入箱型整理、季線下彎、隔日確認，做多勝率降至 45.64%（10日），做空中位數報酬轉正。 | `backtests/breakdown_comparison_report.md` |
| 12. 驗證壓力區、套牢區、賣壓中空 | 已完成 | `opus` | 設計 volume profile 或成交密集區代理，驗證壓力是否影響續航。 | `backtests/supply_zone_spec_report.md` |

Phase 3 完成標準：

- 圖形型態不能只靠口語描述，要有明確標註欄位。
- 壓力區、套牢區、賣壓中空要先定義資料代理，才進入回測。
- 這一階段需要較多策略語意判斷，優先用 `opus` 做規則設計，再用 `haiku` 實作回測。

## 建議執行順序

1. 視需要回頭擴大 `Task 8` 樣本，確認近期分K結論是否能在更長期間成立。
2. 進入 Phase 3：先定義箱型/頸線標註規格，再做 `real_breakdown_after_range`。

## 模型使用摘要

| 模型 | 最適合任務 | 本計畫中主要負責 |
| --- | --- | --- |
| `haiku` | 實作、回測、資料處理、掃描器、報告輸出 | Task 1、2、3、5、6、7、9 |
| `sonnet` | 研究判斷與工程並重，尤其是失敗樣本、分K品質、規則調整 | Task 4、8、11 |
| `opus` | 高層策略理解、課程語意轉量化、圖形與壓力區規則設計 | Task 10、12，以及 Phase 3 規劃 |
