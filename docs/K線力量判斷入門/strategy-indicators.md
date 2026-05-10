# K線力量判斷入門：策略指標摘要

資料來源：PressPlay 已購課程「K線力量判斷入門」右側目錄。  
用途：整理為股票分析系統可量化的候選指標、條件與標籤。  
限制：此文件是策略摘要，不保存付費文章全文與圖片。

策略化分流：哪些指標已可形成策略原型、哪些仍需補標註與驗證，見 `strategy-readiness.md`。

## 1. 單一K線力量

### 紅K與黑K

- `red_k`: 收盤價高於開盤價。
- `black_k`: 收盤價低於開盤價。
- `red_k_strength`: 紅K不只代表上漲，重點是盤中是否有追價買盤。
- `black_k_weakness`: 黑K不一定是賣壓沉重，也可能是低檔買盤不繼。
- `key_k_line`: 能改變前後趨勢的K線，而不是單純顏色或長短。

可量化欄位：

- `body_pct = abs(close - open) / open`
- `close_position = (close - low) / (high - low)`
- `intraday_range_pct = (high - low) / open`
- `is_new_high_n = high >= rolling_high(n)`
- `is_new_low_n = low <= rolling_low(n)`
- `breakout_close = close > prior_resistance`
- `breakdown_close = close < prior_support_or_swing_low`

### 影線

- 上影線不能直接等於壓力；若出現在創新高或攻擊階段，盤中高點代表曾有攻擊力量。
- 下影線不能直接等於支撐；低檔收腳只代表盤中有買盤，不代表後續承接一定延續。
- 影線判斷要加上位置：新高、壓力區、低檔、整理區、攻擊後段。

可量化欄位：

- `upper_shadow_pct = (high - max(open, close)) / open`
- `lower_shadow_pct = (min(open, close) - low) / open`
- `upper_shadow_body_ratio = upper_shadow / body`
- `lower_shadow_body_ratio = lower_shadow / body`
- `upper_shadow_at_new_high = upper_shadow_body_ratio > x and is_new_high_n`
- `lower_shadow_at_low_area = lower_shadow_body_ratio > x and close < ma_60`

### 十字線

- 十字線表示多空對峙或觀望，必須看位置與隔日確認。
- 短十字線偏觀望，若在高檔或壓力區後續轉弱，較偏轉折訊號。
- 長十字線代表盤中多空都用力，若在攻擊階段，多方仍可能有護盤與續攻意圖。
- 連續十字線可用該區間高低點作為短線方向判斷。

可量化欄位：

- `is_doji = body_pct <= x`
- `long_doji = is_doji and intraday_range_pct >= y`
- `short_doji = is_doji and intraday_range_pct < y`
- `doji_cluster_high = max(high over consecutive doji window)`
- `doji_cluster_low = min(low over consecutive doji window)`
- `doji_break_up = close > doji_cluster_high`
- `doji_break_down = close < doji_cluster_low`

## 2. 跳空與漲停

- 向上跳空若發生在創新高與突破位置，偏攻擊缺口。
- 向下跳空通常偏弱勢，不必拘泥是否創新低。
- 除權、減資、庫藏股、突發利多造成的缺口不應直接等同攻擊缺口。
- 跳空漲停一條線是極強攻擊型態，但要區分事件造成與資金攻擊造成。

可量化欄位：

- `gap_up_pct = (open - prior_high) / prior_close`
- `gap_down_pct = (prior_low - open) / prior_close`
- `gap_up_new_high = open > prior_high and high >= rolling_high(n)`
- `limit_up_line = open == high and high == low and close == high and close >= limit_up_price`
- `event_gap_flag`: 需外部事件資料排除除權息、減資、法說、重大公告等。

## 3. 攻擊與突破

- 突破前高後，應假設攻擊成立，但需要後續K線驗證。
- 真正攻擊不應反覆開低給短線客低買；連續紅K若每天開低再拉，可能缺乏攻擊企圖。
- 攻擊階段的低點應持續墊高，若慣性消失要降低多方假設。
- 突破後短期陷阱常來自假突破、開低、跌回突破K低點或跌回整理區。

可量化欄位：

- `breakout_n = close > rolling_high(n) shifted 1`
- `breakout_volume_ratio = volume / avg_volume(n)`
- `open_below_prior_close_after_breakout`
- `breakout_k_low_violation = low < breakout_bar_low`
- `higher_low_count`
- `post_breakout_return_3d`
- `post_breakout_max_drawdown_5d`
- `failed_breakout = breakout_n and close_within_5d < breakout_level`

## 4. 壓力、賣壓與成本

- 壓力來自過往套牢區、密集成交區、前高附近，不是影線本身。
- 賣壓化解要觀察股價是否能有效穿越過往套牢區，且穿越後不快速跌回。
- 層層套牢表示上方不同價位都有潛在賣壓，需要分段評估。
- 賣壓中空表示中間區段籌碼壓力較少，若突破關鍵區可能較容易推升。

可量化欄位：

- `prior_swing_high_distance`
- `overhead_supply_volume = volume_by_price above close`
- `volume_profile_density`
- `resistance_zone_count`
- `break_resistance_and_hold = close > resistance and min(close next m days) > resistance`
- `supply_gap_zone = low volume-by-price density between current price and next resistance`

## 5. 移動平均與趨勢

- 季線與K線高低點可用來判斷中期多空背景。
- 移動平均不是單獨訊號，應作為趨勢背景與預判位置。
- 趨勢判斷需結合K線是否正在攻擊、是否突破、是否遇到壓力。

可量化欄位：

- `ma_20`, `ma_60`, `ma_120`
- `ma_60_slope = ma_60 / ma_60.shift(k) - 1`
- `price_above_ma_60`
- `ma_alignment = ma_20 > ma_60 > ma_120`
- `pullback_to_ma_60`
- `ma_reclaim = close > ma_60 and prior_close < ma_60`

## 6. 型態判斷

- 頭部與底部不可只看形狀，要看多空力量是否改變。
- 築底不是看到下影線或低檔整理就成立，需要確認攻擊或趨勢改變。
- 區間整理要觀察上下緣、量縮、假跌破後收回、突破後是否守住。
- 鑷頂與鑷底重點是特殊價位反覆出現與後續方向確認。
- 課程裡的「確認站穩 / 守住」通常是收盤後才成立，不是盤中碰到就算。
- 實務上常見做法是：當天收盤確認關鍵價，隔日開盤或隔日收盤再確認，才把它視為有效訊號。
- 若跌破後又收回，才算假跌破；若突破後又跌回，則不能算真的站穩。

可量化欄位：

- `range_high`, `range_low`
- `range_width_pct`
- `range_duration`
- `false_breakdown_reclaim = low < range_low and close > range_low`
- `false_breakout_fail = high > range_high and close < range_high`
- `tweezer_top = abs(high - prior_high) / close < x`
- `tweezer_bottom = abs(low - prior_low) / close < x`

## 7. 買點、賣點、停損

- 買點不是低買，而是趨勢改變、突破、攻擊、或空頭轉多的關鍵點。
- 多頭買在攻擊，盤整買在突破，空頭買在趨勢改變。
- 出場依據可分為趨勢性出場、轉折K線出場、攻擊力量消失出場、下一個買點資金配置出場。
- 停損位置應由型態與關鍵K線決定，不宜任意用固定百分比取代全部邏輯。
- 訊號通常先以收盤成立，再用隔日開盤進場；若策略需要更保守，可再多等一個交易日收盤確認。

可量化欄位：

- `entry_type`: `trend_change`, `range_breakout`, `attack_breakout`, `pullback_reclaim`
- `stop_type`: `breakout_bar_low`, `range_low`, `doji_cluster_low`, `ma_break`, `swing_low`
- `exit_type`: `trend_break`, `reversal_k`, `attack_failure`, `capital_rotation`
- `risk_pct = (entry_price - stop_price) / entry_price`
- `reward_to_next_resistance`

## 8. 放空與回補

- 放空邏輯與多方攻擊不是簡單鏡像，需確認弱勢、跌破、反彈遇壓、買盤不繼。
- 回補可用趨勢改變、跌勢攻擊消失、假跌破收回或關鍵K線確認。

可量化欄位：

- `short_breakdown = close < rolling_low(n)`
- `rebound_fail_at_ma`
- `lower_high_count`
- `cover_signal = false_breakdown_reclaim or close > prior_reversal_high`

## 9. 系統設計建議

建議先建立下列資料層：

- 日K資料：OHLCV、漲跌停價、除權息調整、可交易狀態。
- 衍生K線特徵：實體、影線、跳空、十字線、創高創低。
- 趨勢特徵：均線、均線斜率、高低點結構、區間。
- 壓力特徵：前高、成交密集區、volume profile、套牢區。
- 事件過濾：除權息、減資、重大公告、財報、法說、注意股、處置股。
- 策略標籤：突破、跌破、假突破、假跌破、攻擊、攻擊失敗、轉折。

優先回測假設：

- `H1`: 創新高紅K且隔日不開低，後續勝率高於創新高但隔日開低者。
- `H2`: 突破K低點被跌破後，後續報酬顯著轉弱。
- `H3`: 創新高上影線若未遇歷史成交密集壓力，後續不一定偏空。
- `H4`: 長十字線在攻擊階段若低點未破且高點被突破，後續續攻機率提高。
- `H5`: 假跌破後快速收回區間，後續突破成功率高於一般區間整理。
- `H6`: 上方 volume profile 中空的股票，突破後推升效率較高。

## 10. 圖例補強後的規則

以下規則來自 `docs/K線力量判斷入門/images/` 中已補齊的文章圖例。重點不是保存圖片本身，而是把圖中反覆出現的「位置、後續確認、失效」轉為可標註與回測的條件。

### 十字線與夜星/暗夜雙星

圖例來源：

- `【單一K線】十字線蘊含的轉折與延續意義-*`
- `【單一K線】十字線與上影線在攻擊階段的意義(上)-*`
- `【單一K線】十字線與上影線在攻擊階段的意義(下)-*`

觀察補強：

- 十字線不能單看一根，圖例反覆以「前一段是否已拉抬」「是否遇前高壓力」「隔日是否突破/跌破十字線區間」判斷。
- 連續兩根十字線形成一個短線判斷區間，後續方向以該區間高低點為界。
- 短十字線若出現在前波壓力或強勢拉抬後，隔日黑K或跌破十字線低點時，偏轉折。
- 長十字線若出現在攻擊初中段，且低點未破、高點被突破，偏續攻；若高點無法突破且跌破低點，偏攻擊失敗。

可新增標籤：

- `doji_after_rally`
- `doji_at_prior_high`
- `doji_cluster_box`
- `doji_cluster_breakout`
- `doji_cluster_breakdown`
- `evening_star_with_pressure`
- `long_doji_attack_defense`

建議規則：

- `doji_cluster_box_high = max(high over consecutive doji or small-body bars)`
- `doji_cluster_box_low = min(low over consecutive doji or small-body bars)`
- `doji_reversal_confirm = doji_at_prior_high and close_next < doji_cluster_box_low`
- `doji_attack_continue = attack_context and close_next > doji_cluster_box_high`
- `doji_attack_fail = attack_context and close_next < doji_cluster_box_low`

### 上影線、下影線與盤中路徑

圖例來源：

- `【單一K線】上影線與下影線的正確判斷-*`

觀察補強：

- 上影線圖例的重點是盤中曾創高或攻擊，不應直接判定為壓力；要看上影線出現的位置是否真的有過往套牢區。
- 下影線圖例顯示「盤中反彈」不等於支撐成立；若隔日直接轉弱，代表反彈力量消失。
- 圖例中的「假性跌破」比「下影線支撐」更適合作為系統標籤，因為它有明確的關鍵價位與收回條件。

可新增標籤：

- `upper_shadow_attack_attempt`
- `upper_shadow_into_supply`
- `lower_shadow_intraday_rebound`
- `lower_shadow_rebound_failed`
- `false_breakdown_reclaim`

建議規則：

- `upper_shadow_attack_attempt = is_new_high_n and upper_shadow_body_ratio > x and close > prior_close`
- `upper_shadow_into_supply = upper_shadow_attack_attempt and distance_to_supply_zone <= y`
- `lower_shadow_rebound_failed = lower_shadow_body_ratio > x and open_next < close and close_next < low`
- `shadow_signal_valid = shadow_pattern and confirmed_by_next_bar`

### 連續紅K與攻擊真假

圖例來源：

- `【單一K線】紅色誤解：連續紅K的判斷要點-*`

觀察補強：

- 圖例對比了「連續紅K但缺乏攻擊意圖」與「真正快速攻擊」。判斷差異在於是否反覆開低、是否很快跌破平盤或突破K低點。
- 真攻擊通常不給反覆低買機會；若突破後連續多次開低再拉，反而要標記為攻擊品質下降。
- 盤中圖顯示跌破平盤後快速轉弱，適合加入 intraday failure 訊號。

可新增標籤：

- `red_k_attack_quality`
- `repeated_low_open_after_breakout`
- `intraday_attack_failure`
- `fast_limit_up_attack`

建議規則：

- `low_open_count_after_breakout = count(open_i < close_{i-1}, i=1..m)`
- `attack_quality_score = breakout_n + higher_low_count + gap_or_strong_open - low_open_count_after_breakout - breakout_k_low_violation`
- `intraday_attack_failure = breakout_context and intraday_low_after_noon < intraday_open and close < prior_close`
- `fast_attack_candidate = breakout_n and close_near_high and low_open_count_after_breakout == 0`

### 假性跌破與真正跌破

圖例來源：

- `【突破跌破】假性跌破的實務意義-*`
- `【突破跌破】整理趨勢進入型態判斷的關鍵-假性跌破之後-*`

觀察補強：

- 圖例中的假性跌破大多發生在急跌或短期波動後，跌破關鍵價後快速收回。
- 真正跌破通常不是急跌後立刻彈回，而是整理後用長黑跌破，且反彈也站不回頸線或前低。
- 假性跌破之後不能再次自然跌破同一關鍵位；若反彈後再破且站不回，應從假性跌破改標為趨勢轉空。

可新增標籤：

- `neckline_break`
- `panic_break_reclaim`
- `false_breakdown_after_panic`
- `real_breakdown_after_range`
- `reclaim_failed_after_breakdown`

建議規則：

- `panic_drop = return_k_days <= -x and consecutive_down_days >= y`
- `key_level = min(prior_swing_low, neckline, range_low)`
- `false_breakdown = low < key_level and close >= key_level`
- `false_breakdown_confirm = false_breakdown and close_next > key_level`
- `real_breakdown = close < key_level and close_next < key_level and rebound_high_next_m <= key_level`
- `false_breakdown_invalidated = false_breakdown_confirm and close_within_m_days < key_level`

### 賣壓化解、層層套牢、賣壓中空

圖例來源：

- `【賣壓化解】K線圖的第一個研判要點-*`
- `【成本原理】層層套牢的行進研判-*`
- `【成本原理】賣壓中空的結構判斷-*`
- `【成本原理】評估賣壓區段要看當時套了誰-*`

觀察補強：

- 圖例將壓力拆成「過去套牢位置」「前高」「急跌造成的中空區」。這三者應分成不同欄位，不要都叫 resistance。
- 層層套牢表示反彈路上每一層都有解套賣壓；賣壓中空則是破底後急跌，該段低接籌碼少，反彈可能較順，但上方頭部仍是主要出場區。
- 賣壓中空不是買進理由本身，更像是反彈段的推進效率與出場位置估計。

可新增標籤：

- `overhead_supply_layer`
- `multi_layer_supply`
- `supply_vacuum_zone`
- `supply_vacuum_end`
- `supply_zone_absorbed`
- `intraday_wave_higher_low`

建議規則：

- `supply_layer_count = count(prior_swing_high zones above current_price within p%)`
- `supply_vacuum_zone = price_range where volume_profile_density < percentile(q) after breakdown`
- `supply_vacuum_end = first high-volume prior head zone above supply_vacuum_zone`
- `supply_absorbed = close > supply_zone_high and min(close next m days) > supply_zone_high`
- `vacuum_rebound_exit = price enters supply_vacuum_end and intraday_higher_low_breaks`

### 頭部/底部型態與箱型切換

圖例來源：

- `【型態判斷】頭部底部型態合併要點(一)-*`
- `【型態判斷】頭部底部型態合併要點(二)-*`
- `【型態判斷】區間整理走勢應有的認知-*`
- `【型態判斷】築底的應對與實務意義-*`

觀察補強：

- 圖例中「跌破後又站回頸線」會使季線方向判斷暫時失效，應切換成箱型區間模型。
- 正常多空易位是跌破頸線後轉空，若反彈回頸線但無法站回，反彈是離場機會而不是支撐成立。
- 頭部/底部不只是圖形，需要結合頸線、季線方向、是否站回、反彈是否受壓。

可新增標籤：

- `neckline_reclaim_to_box`
- `box_mode_after_neckline_reclaim`
- `neckline_retest_fail`
- `trend_to_box_switch`
- `box_breakout_to_bull`
- `box_breakdown_to_bear`

建議規則：

- `neckline = prior_low_before_ma60_rollover`
- `neckline_break = close < neckline`
- `neckline_reclaim = neckline_break_recent and close > neckline`
- `box_mode = neckline_reclaim and ma60_direction_unclear`
- `box_high = rolling_high_since_reclaim`
- `box_low = rolling_low_since_reclaim`
- `box_breakout_to_bull = box_mode and close > box_high`
- `box_breakdown_to_bear = box_mode and close < box_low`
- `neckline_retest_fail = close < neckline and high >= neckline and close < open`

## 11. 圖像標註資料表建議

若要把這批圖例轉成訓練/回測資料，建議每張圖至少標註以下欄位：

- `image_path`
- `article_title`
- `case_ticker`
- `case_date`
- `timeframe`: `daily`, `intraday`, `mixed`
- `pattern_family`: `doji`, `shadow`, `breakout`, `false_breakdown`, `supply`, `neckline`, `box`
- `key_level_type`: `prior_high`, `prior_low`, `neckline`, `range_high`, `range_low`, `supply_zone`, `ma60`
- `key_level_price`
- `trigger_bar_date`
- `confirm_bar_date`
- `invalidation_level`
- `expected_direction`: `bullish`, `bearish`, `neutral_box`, `exit_only`
- `strategy_usage`: `entry`, `exit`, `stop`, `filter`, `watchlist`

優先標註順序：

- 先標 `假性跌破/真正跌破`，因為關鍵價、收回、失效最容易量化。
- 再標 `十字線區間突破/跌破`，因為高低點明確。
- 接著標 `賣壓中空/層層套牢`，需要 volume profile 或成交密集區輔助。
- 最後標 `上影線/下影線`，因為它最依賴位置與隔日確認，不適合單獨做訊號。
