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

## Phase 4：策略整合與可交易化

| Task | 狀態 | 建議模型 | 目標 | 產出物 |
| --- | --- | --- | --- | --- |
| 13. overhead_supply_layer 加入 breakout_daily_scanner 評分 | 待做 | `haiku` | layer ≤ 1 加分、layer ≥ 4 扣分，改善掃描器排序品質。 | `scripts/breakout_daily_scanner.py` 更新 |
| 14. supply_zone_absorbed 可交易版本 | 待做 | `sonnet` | 改為 breakout 後 t+5 確認守住、t+6 進場，回測與原版比較。 | 回測報告 |
| 15. supply_vacuum_zone 移植到 false_breakdown 場景 | 待做 | `sonnet` | 驗證假跌破收回時，上方賣壓中空是否改善後續報酬。 | 回測報告 |
| 16. real_breakdown_after_range 做空方向 regime 分組驗證 | 待做 | `sonnet` | 確認新版是否適合作「多方迴避訊號」或 bear regime 下的做空訊號。 | 驗證報告 |

Phase 4 完成標準：

- Task 13 完成後，掃描器輸出要能呈現 overhead_supply_layer 欄位。
- Task 14/15 需有可執行的進場時機（不再是前瞻欄位）。
- Task 16 需明確結論：real_breakdown 是「迴避訊號」還是「做空訊號」。

## Phase 5：課程放空策略開發

背景：課程第 50 篇「放空與回補的要點講解」教導以「弱勢、跌破、反彈遇壓、買盤不繼」判斷放空進場，以「趨勢改變、跌勢攻擊消失、假跌破收回」判斷回補。目前專案策略均為多方，尚未實作放空。Phase 3 完成的頭部型態、頸線、真正跌破標註規格可作為放空進場依據。

| Task | 狀態 | 建議模型 | 目標 | 產出物 |
| --- | --- | --- | --- | --- |
| 17. 課程放空教學萃取與量化代理設計 | 待做 | `opus` | 讀取課程第 50 篇「放空與回補」、第 7 篇「高檔區域長黑K」、相關跌破圖片，將「弱勢、跌破、反彈遇壓、買盤不繼」與回補條件轉為可量化的 OHLCV 代理。每個代理需引用圖片或課程文字出處。 | `backtests/short_strategy_spec.md` |
| 18. 放空進場與回補訊號實作 | 待做 | `haiku` | 依據 Task 17 規格，在 `kline_course_backtest.py` 的 `add_signals` 函式中實作 `short_entry`、`cover_signal` 訊號欄位。 | `scripts/kline_course_backtest.py` 更新 |
| 19. 放空策略回測（含 regime 分組） | 待做 | `haiku` | 隔日開盤放空進場，遇到 cover_signal 開盤回補，計算反向報酬。分 bull/range/bear regime 比較，確認哪些環境適合放空。 | `backtests/short_strategy_check.md` |
| 20. 台股放空可交易性處理 | 待做 | `sonnet` | 處理券源限制、強制回補日、漲跌停無法平倉等實務限制。檢查 FinMind 是否提供融券、借券資料，產出可交易標的篩選邏輯。**明確標註此部分為「課程未涵蓋」。** | `backtests/short_tradability_spec.md` |
| 21. 放空每日掃描清單 | 待做 | `haiku` | 依據 Task 18-20，產出每日放空候選清單（進場價、回補價、結構失效條件、可交易性過濾）。 | `backtests/short_daily_scanner.md`、`short_daily_scanner.csv` |

Phase 5 完成標準：

- Task 17 所有量化代理必須引用課程明確出處，禁止自行補完。
- 課程強調「放空與多方非鏡像」，禁止直接把 `breakout_attack` 反向當放空訊號。
- 假跌破收回是回補訊號，不是放空進場訊號，實作時要區分清楚。
- Task 20 需明確區分「課程語意」與「台股實務限制」。
- Task 21 每日掃描必須能自動執行，可與現有 `false_breakdown_daily_scanner` 並列。

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
| `haiku` | 實作、回測、資料處理、掃描器、報告輸出 | Tasks 1、2、3、5、6、7、9、13、18、19、21 |
| `sonnet` | 研究判斷與工程並重，尤其是失敗樣本、分K品質、規則調整 | Tasks 4、8、11、14、15、16、20 |
| `opus` | 高層策略理解、課程語意轉量化、圖形與壓力區規則設計 | Tasks 10、12、17，以及 Phase 3、5 規劃 |
