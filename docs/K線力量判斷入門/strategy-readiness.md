# K線力量判斷入門：策略可用性分流

狀態日期：2026-05-10

依據：

- `strategy-indicators.md` 的課程指標整理
- `backtests/kline_course_backtest.md` 的日K回測
- `backtests/finmind_intraday_check.md` 的 FinMind 分K抽樣驗證

目的：把課程指標分成「已經可以形成策略原型」與「還要繼續驗證」兩類，避免後續股票分析系統把尚未驗證的圖形語意直接當成交易訊號。

## 已經可以形成策略原型

這一組不是代表已可直接上線交易，而是代表已經有足夠量化代理與初步回測支持，可以進入策略原型、參數掃描、交易成本與樣本外驗證。

| 指標 | 策略角色 | 目前驗證狀態 | 原型方向 |
| --- | --- | --- | --- |
| `false_breakdown_reclaim` | 主要進場訊號 | 日K符合度最高。10 日 close-basis 平均 2.521%，勝率 59.11%；20 日 close-basis 平均 5.100%。進一步策略原型驗證後，加入交易成本與可交易限制仍保留正向邊際，`tradable_filter` 10 日淨報酬 1.695%、勝率 57.25%。失敗樣本分析顯示，成功案例通常有更高的 `close_pos`、更深的短期 panic drop、更強的收回幅度，且 bull regime 表現明顯較差。 | 做「假跌破收回」反轉策略。優先測 `exclude_bull_regime`、`close_pos >= 0.7`、5 日跌幅至少 10%、隔日收盤確認與 `ATR14` 停損。 |
| `breakout_attack` | 趨勢追蹤候選訊號 | 日K 10 日 close-basis 平均 2.615%，20 日表現更好；分K抽樣有高比例強攻。可交易版回測後，`breakout_attack_tradable` 10 日淨報酬 0.775%、20 日淨報酬 4.127%，以 `range regime` 表現最佳。 | 做突破候選池，搭配區間/盤整後突破、量能與日內攻擊品質條件排名。 |
| `breakout_next_not_low_open` | 條件式攻擊品質濾網候選 | 全樣本日K回測裡，它改善 close-basis 延續，但未改善實際隔日開盤進場報酬；因此不能直接升級成通用買點濾網。第一輪分K驗證（近期市場、regime 分層樣本）則顯示它具有更高 `intraday_close_pos`、更高強攻比例、更低 `below_open_after_1130`，且 10 日淨報酬優於 `next_low_open`，尤其在 `range regime` 最明顯。 | 先作為條件式品質加分項，不當硬性買點規則；優先用在 breakout watchlist 排序，特別觀察 `range regime` 與強攻分K同時成立的個股。 |
| `new_high_no_upper_shadow` | 乾淨創高基準策略 | 表現略優於創高上影線組。10 日 close-basis 平均 2.769%，可作為創高突破基準組。 | 建立「創高且收盤接近日高」策略，與上影線創高比較風險與續航。 |
| `upper_shadow_new_high` | 出場與風險調整濾網 | 日K不支持「創高上影線必然看空」，但弱於無上影線創高；分K失敗率偏高。 | 不直接做空，也不自動停利。若遇壓力區、隔日轉弱或午盤後跌回開盤下方，降低持倉分數。 |
| `intraday_strong_attack` / `below_open_after_1130` | 分K攻擊品質濾網 | 分K抽樣支持突破訊號常有強攻；午盤後跌破開盤可作為攻擊失敗特徵。 | 有分K資料時，用於突破策略的日內確認與剔除弱攻擊個股。 |
| `doji_cluster_high` / `doji_cluster_low` | 位置工具 | 十字線方向回測不明顯，但連續十字線高低點可作為區間邊界。 | 只拿來定義箱型上緣、下緣、停損與確認價，不把十字線本身當方向預測。 |

## 還要繼續驗證

這一組目前只能放在候選指標或人工標註工作，不應直接變成交易策略。

| 指標 | 為什麼還不能策略化 | 下一步需要補什麼 |
| --- | --- | --- |
| `doji_at_pressure`、`doji_break_up`、`doji_break_down`、`long_doji`、`short_doji` | 日K回測方向差異不明顯，單看十字線或突破十字線區間不足以形成穩定邊。 | 加上前段漲幅、壓力區、長短十字線、量能、隔日確認與圖例標註。 |
| `real_breakdown_after_range` | 目前簡化代理不支持課程情境；單用 60 日前低與長黑不足以捕捉「整理後跌破頸線」。 | 標註箱型、頸線、整理時間、跌破後是否反彈不過頸線。 |
| `overhead_supply_layer`、`multi_layer_supply`、`supply_zone_absorbed` | 壓力與層層套牢需要成本分布或人工圖形判讀，現有 OHLCV 代理太粗。 | 建立 volume profile、成交密集區、前高套牢區與壓力被消化的標籤。 |
| `supply_vacuum_zone`、`supply_vacuum_end` | 「賣壓中空」是空間結構，不是單根K線可判斷；目前沒有可靠欄位。 | 需要區間套牢量、缺口區、前方成交密度與圖片標註。 |
| `lower_shadow_at_low_area` | 課程提醒下影線不等於支撐；目前沒有證據支持單靠下影線進場。 | 驗證隔日是否續強、是否站回關鍵價、是否出現量縮止跌或主力籌碼承接。 |
| `gap_up_new_high`、`limit_up_line`、`gap_down` | 缺口與漲停容易受除權息、事件、公告與買不到影響，直接回測會失真。 | 補事件排除、漲跌停價、可成交性、隔日開盤與分K延伸。 |
| 均線多頭、均線扣抵、均線糾結 | 均線可當背景，但目前還沒證明單獨使用有足夠優勢。 | 用作 regime filter，測試是否改善突破與假跌破策略，而不是獨立訊號。 |
| 頭部、底部、肩頭、頸線、箱型 | 這些是圖形結構，需要定義 pivot、 neckline、右肩、回測不過等事件；目前文件多為人工規則。 | 建立圖形標註資料集，再回測各型態的確認K、停損與目標價。 |
| 放空、回補、空方續弱 | 台股放空有券源、禁空、注意處置、融券回補與漲跌停限制。 | 補可放空性、借券成本、強制回補、注意處置與市場空頭 regime。 |
| 停利、停損、出場規則 | 目前回測多為固定 5/10/20 日觀察，還不是完整交易系統。 | 加入實際進出場、交易成本、滑價、停損觸價、移動停利與部位控管。 |
| 江波、高低點墊高、盤中換手 | 需要分K連續資料與 pivot 偵測，現階段只有小樣本抽樣。 | 擴大 FinMind 分K樣本，標註盤中波段高低點、午盤後守開盤與尾盤攻擊。 |

## 後續工作順序

1. 已完成第一輪 `false_breakdown_reclaim` 策略原型：交易成本、注意/處置排除、流動性、隔日確認、ATR/箱型停損與失敗樣本歸因，詳見 `backtests/false_breakdown_strategy_check.md` 與 `backtests/false_breakdown_failure_analysis.md`。
2. 已完成第一輪 daily scanner：`backtests/false_breakdown_daily_scanner.md`、`false_breakdown_daily_scanner.csv`、`false_breakdown_daily_scanner_recent20d.csv`。
3. 已完成 `breakout_attack` 可交易版第一輪驗證：詳見 `backtests/breakout_attack_strategy_check.md`。
4. 已完成 `breakout_next_not_low_open` 的 execution-aware 驗證：詳見 `backtests/breakout_next_open_quality_check.md`。全樣本日K結果不支持它成為通用交易濾網。
5. 已完成第一輪 breakout 分K攻擊品質驗證：詳見 `backtests/breakout_intraday_quality_check.md`。近期市場的 regime 分層樣本顯示 `next_not_low_open` 具備較佳分K攻擊品質，且在 `range regime` 的 10 日表現更強。
6. 已完成第一輪 breakout watchlist：詳見 `backtests/breakout_daily_scanner.md`、`breakout_daily_scanner.csv`、`breakout_daily_scanner_recent20d.csv`。`breakout_next_not_low_open`、`intraday_strong_attack`、`below_open_after_1130` 已納入排序加權。
7. 把 `upper_shadow_new_high` 放進突破策略的風險調整，不把它直接做成反向訊號。
8. 建立壓力區、箱型、頸線、頭底型態的人工標註格式，再回來驗證 `real_breakdown_after_range` 與供給壓力類指標。
9. 擴大 FinMind 分K樣本，只針對已經有日K優勢的策略做日內確認，避免先把分K規則做得太複雜。

## 策略化邊界

- 任何指標要升級為策略，至少要區分它是「進場訊號」、「濾網」、「出場訊號」還是「位置工具」。
- 未通過交易成本、滑價、注意/處置、流動性與樣本外檢查前，只能稱為策略原型。
- 課程中的圖形語意要先轉成明確標籤，再做回測；不能直接用粗略 OHLCV 代理取代所有型態判斷。
