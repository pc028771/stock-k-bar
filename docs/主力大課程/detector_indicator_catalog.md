# Detector / Indicator / Trigger Catalog

> **用途**: Mock server test scenarios SSOT。每個 detector/trigger 必標：
> - 物理意義 (一句話)
> - 核心條件
> - 課程來源 (chapter + line ref)
> - API 資料依賴 (daily / 1m / 5m / inst / TAIEX)
> - 範例個股 (歷史命中) + 預期 trigger 時點

---

## §1 Entry Detectors (Daily-level, EOD)

### 1.1 small_structure 小結構整理末端
- **物理意義**: N字攻擊後高位整理末端、準備二次上攻
- **核心條件 (6 AND)**:
  1. 過去 10-20 天 +10% 漲幅 (前段攻擊)
  2. 近 5 天 close range < 10% (高位整理)
  3. 近 3 天均量 < 1.5 且當日 < 前 3 天均 (量縮)
  4. MA5 / close > 0.93
  5. close >= MA10 × 0.95
  6. close / 10日 high >= 0.85
- **課程**: 主力大 5/21 群創 N 字上攻教學、`5_21_資訊統整培訓_講稿.md`
- **Spec**: `system_spec.md` R-ENT-001 (已驗證、不可調整)
- **API**: daily K (close/high/MA5/MA10/vol_ratio_20)
- **範例**:
  - **3481 群創** 5/20 trigger → 5/21 漲停 (+9.9%)、1 天提前
  - **3042 晶技** 5/19 trigger → 5/22 漲停 (+17%、4 天)、3 天提前
  - **6770 力積電** 5/13, 5/18, 5/21 trigger → 5/22 三陽開泰、4-9 天提前

### 1.2 w_bottom_launch W 底起漲
- **物理意義**: 大跌 → 反彈未過前高 → 二次拉回守住 → 準備突破反彈高
- **核心條件 (6 AND)**:
  1. 60 天高 → 30 天內最低、跌幅 ≥ 20%
  2. 反彈 H2 ≥ H1 × 0.85
  3. 二次拉回 > L1 × 0.95 (不破第一次低點)
  4. close ≥ H2 × 0.88
  5. 5d 均量比 < 1.5
  6. close ≥ MA20 × 0.95
- **課程**: 5/22 老師「完美複製 4958 起漲前長相」教學、案例 6239 力成 5/22 漲停
- **Spec**: `system_spec.md` R-ENT-002
- **API**: daily K (60d high/low、ma20、vol_ratio_5d)
- **範例**:
  - **4958 臻鼎-KY** 2026/03/23 起漲前命中
  - **6239 力成** 5/22 漲停

### 1.3 uniform_ma_above 均線全順向
- **物理意義**: 4 均線嚴格上排 (5>10>20>60) + close ≥ MA5、多頭結構確立
- **核心條件**:
  - MA5 > MA10 > MA20 > MA60 (嚴格排序)
  - close >= MA5
  - 成交額 ≥ 25,000,000
  - 距 MA20 < 12%
  - 距 MA60 < 40%
  - 20d 漲幅 ≤ 25% (反直覺、不追)
- **課程**: 老師選股軟體反向工程 6/4 拍板、F1 最佳組合
- **Spec**: `system_spec.md` R-ENT-003
- **API**: daily K (ma5/10/20/60、20d ret、成交額)
- **範例**: 6/4 全市場 434 → 145 (套濾網) → ∩老師44=35 (F1 0.370)

### 1.4 foreign_lead 外資 lead 5 variants
- **物理意義**: 外資連 N 日買超 + 黑K + 守關鍵均線 = last-mile 加碼共識
- **5 variants**:
  | ID | 條件 | Priority | Note |
  |---|---|---|---|
  | v06 | 連 3 黑K + 寬鬆閾值 | 3 | 放寬版 |
  | v07 | 連 3 + 5d 跌 3% + 守 MA20 | 2 | 拉回承接 |
  | **v08** | 連 3 + 黑K + 守 MA10 | 3 | **主訊號** |
  | v15 | 連 5 + 量 2x + 黑K | 3 | 重押旗標 |
  | v12_skip | 外資買 + 投信背離大賣 | -1 | 反向警示 |
- **Regime gate**: regime != strong_bull → priority 自動降一級 (P3→P2、2026-06-18 fix)
- **課程**: 主力大 6/2-6/3 法人籌碼 + 6/14 直播
- **Spec**: `system_spec.md` R-ENT-009
- **API**: daily K + institutional (3 日 foreign_net + sitc_net)
- **範例**: 2026 H1 WR 70-83%、2024/2025 跨年 fail 36-49%

### 1.5 foreign_buy_on_black_k 外資大買黑K連 N 天
- **物理意義**: 外資連 2 天淨買超 + K 線黑K = 升等「圈起來」、隔日尾盤評估
- **核心條件**:
  - Day -1: 外資 ≥ tier threshold (500/2000/5000 張、依流動性) + close < open
  - Day 0: 同上
- **課程**: 6/3 法人籌碼 2303 聯電案例、`feedback_foreign_buy_on_black_k`
- **API**: daily K + institutional + vol_ma20
- **範例**: 2303 聯電 6/3+

### 1.6 dual_axis_relative_strength 雙軸籌碼相對強勢
- **物理意義**: 大盤跌時、雙軸籌碼仍強 = 相對強勢
- **核心條件**:
  - TAIEX 當日跌幅 ≤ -1%
  - 外資 5d 累計 ≥ +3000 張
  - 投信 5d 累計 ≥ -500 張
  - close > MA5/MA10/MA20 任一
- **課程**: User 6/4 拍板、`feedback_dual_axis_relative_strength`
- **Spec**: R-ENT-011
- **API**: TAIEX daily + ticker daily + institutional 5d
- **範例**: 6282 康舒 5/13+5/28 命中

### 1.7 composite_2026 4 條 stack super signal
- **物理意義**: 5 條 stack — 老師 universe + 籌碼共識 + 大盤健康 + 位階不過熱 + last-mile 未轉空
- **核心條件 (5 AND)**:
  1. 老師明示族群 / picks
  2. foreign_lead 任一 / institutional_swing 命中
  3. TAIEX 20d ret ≥ -10%
  4. 距 MA60 < +30%
  5. 近 2 天外資累計 ≥ -500 張
- **課程**: 2026-06-16 deploy、regime-specialized 2026 H1
- **Spec**: R-ENT-008
- **API**: daily K + TAIEX + institutional 2d/5d
- **預期**: 6/12 整理盤可能 0 hit、強多升段 2-3 檔/週

### 1.8 institutional_swing (I 策略)
- **物理意義**: 5d 投信買進 ≥ 1.5% 股本 + 前 30d 首次達標 (剛上榜) + MA5/10/20 全上彎
- **課程**: Ex2-1 + Ex2-2 + strategy-indicators §I
- **Spec**: R-ENT-006
- **API**: daily K + institutional + 股本

### 1.9 institutional_firstbuy (J 策略)
- **物理意義**: 投信首買 ≥ 200 張 + 前 N 天乾淨無買超 + 流動性過
- **課程**: Ex2-3 字幕 01:23 + 01:53 + strategy-indicators §J
- **Spec**: R-ENT-006
- **API**: daily K + institutional

### 1.10 suffocation (H 策略) 窒息量
- **物理意義**: 前一根窒息量 + MA20 上彎 + 今日出量 K (紅K 或長下影綠K)
- **核心條件**:
  - prev_vol / max_vol_20d < 0.10
  - MA20 slope > 0
  - 今日 vol > prev_vol
  - K 棒類型: 紅K 或下影線 > 實體
- **課程**: 主力大 Ex1-1~1-3 + course_principles §16
- **Spec**: R-ENT-006
- **API**: daily K + max_vol_20d + ma20_slope
- **2026-06-18 fix**: 加 disposal_tickers 排除參數 (處置股量縮被動)

### 1.11 swing_breakout (A 策略)
- **物理意義**: 籌碼 (外資/投信 ≥ 1/3 量 或 ≥ 2 萬張) + MA20/MA60 雙上彎 + 同產業 ≥3 檔上榜
- **課程**: Ch3-1 + Ch3-2 + strategy-indicators §A
- **Spec**: R-ENT-006

### 1.12 pennant_flag (B 策略)
- **物理意義**: t-2 紅K旗杆 + t-1, t 兩根 close > ma5 + 量縮 + close > pole mid
- **課程**: Ch4-2 line 9-216 + strategy-indicators §B

### 1.13 reversal_breakout (C 策略)
- **物理意義**: 紅K + ma5/10/20 在實體下方 + ma5 上彎 + 均線發散 <5% + 前 60d 下降 ≥10%
- **課程**: Ch4-2 line 217-356 + strategy-indicators §C

### 1.14 bbands_upper_break (D 策略)
- **物理意義**: 20D 布林、收盤站上軌 + 出量 + 通道窄 + MA60 不下彎
- **課程**: 主力大 Ch4-2 + strategy-indicators §D + HD vision 32:07

### 1.15 bollinger_pullback (E 策略)
- **物理意義**: 前置近 N 日 close > BB_upper + 回測 MA20 量縮 + 第二波啟動
- **課程**: Ch4-2 形態四 + PDF p.127 + L1 Sprite ch4-2 48:05

### 1.16 overnight_swing (G 策略) 隔日沖
- **物理意義**: Phase 1 個股速篩 (布林上軌 + 通道窄 + 紅K + 量增 + MA20 上彎) + Phase 2 大盤過濾 (TAIEX/OTC 雙紅K)
- **課程**: Ch6-1 + Ch6-2
- **Memory**: `project_strategy_overnight_swing` (+1.85%/筆 主推)
- **API**: daily K + TAIEX + OTC

### 1.17 teacher_swing 老師 5/28 9 條件
- **物理意義**: 4 均線多頭 + 月線斜率 >0.4 + 量價 (10K張/300張/周轉 >1.3%) + 距 5MA<5%
- **課程**: 老師 5/28 晚課截圖

### 1.18 small_structure 子模組
- **glued_ma5_platform**: MA5 平台 + 4 條均線黏合 (5/30 老師)
- **ma5_pivot_breakout**: MA5 pivot 突破 (5/30 老師)
- **post_attack_filter**: 攻擊後 watchlist filter
- **Spec**: R-ENT-013

### 1.19 intraday (F 策略) 當沖
- **🔴 DEPRECATED**: backtest 全負 (-0.80%)、僅 T+0 限制時用
- **物理意義**: MA5/10/20 全上彎 + 近 2 日量 >2 萬張 + 近 3 日振幅 >8% + 周轉 >20%
- **課程**: Ch5-1/5-2/5-3 + strategy-indicators §F

### 1.20 open_signal_filter (M 策略)
- **3 signal types**:
  - bearish_exit: 前日收最高 + 今日開低/開平 (主力試空)
  - bullish_entry: 前日收最低 + 今日開高 (主力試多)
  - limit_up_flat_warning: 漲停板平盤警示
- **課程**: 主力大 Ch7-3 + course_principles §15

### 1.21 shakeout_strong (extras、課程外)
- **物理意義**: 主力震出散戶後強勢
- **EV**: +10.1% (老師常駐族群) vs +5.1% baseline

---

## §2 Setup Detectors (TAIEX + DIF/KD)

### 2.1 F1-F4 強多盤 (regime = strong_bull, TAIEX 5d ≤ -2% 殺盤觸發)
| Setup | 條件 | WR | n | 持有 | Exit |
|---|---|---|---|---|---|
| **F1** | F+ 殺盤 + 健康回檔 (日上 60m上 30m下 5m下) | **81%** | 21 | 5.4d | K 線 playbook |
| **F2** | F+ 殺盤 + DIF_d streak ≥ 11 | **82%** | 33 | 4.5d | 同 |
| **F3** | F+ 殺盤 + 反轉型 (日 DIF down + 60m up) | **81%** | 36 | 3.3d | 同 |
| **F4** | F+ 殺盤 + 5m K < 30 | **80%** | 25 | - | 同 |

- **Memory**: `feedback_multitf_diff_kd_setups`
- **Spec**: R-ENT-012
- **API**: TAIEX 5d + ticker daily DIF + 60m/30m/5m DIF + 5m K
- **🔴 2026-06-18 fix**: regime stale → 整批 skip

### 2.2 S1-S3 震盪盤 (regime = chop)
| Setup | 條件 | WR | n |
|---|---|---|---|
| **S1** | Leader 殺盤 + 雙超賣 | 83% | 12 |
| **S2** | Laggard 對齊 + 5mK ≥ 80 | 87% | 23 |
| **S3** | Laggard 對齊 + 大盤微弱 | **94%** | 17 |

- **Memory**: `feedback_chop_regime_setups`
- **反向訊號**: Leader 對齊 + 過熱 + streak 剛起 = 震盪盤 17% WR / 強多 100% WR

---

## §3 Intraday Stage Triggers (5-min K real-time)

### 3.1 R1 首攻 (Ch5-3)
- **物理意義**: 早盤首段攻擊、守住進場
- **3 states**: 首攻 (confirmed) / 首攻_pullback (回踩中) / 首攻_signal (訊號、等回踩)
- **API**: 5m K (open/high/low/close/vol) + MA10
- **R1 dual condition (2026-06-18 fix)**: age > 10min AND 距高 ≤ -2% → 自動降級

### 3.2 R2 續攻 (T1)
- **物理意義**: 09:45 後續攻 confirmed
- **2 states**: 續攻 / 續攻_watch (等 9:45+)
- **API**: 5m K + day_high

### 3.3 R3 反彈 (T2)
- **物理意義**: 殺盤後反彈 confirmed
- **2 states**: 反彈 / 反彈_watch

### 3.4 R4 破底 (TC)
- **物理意義**: 跌破前波低 + 距 MA10 -3% + 量爆下行 = 結構失敗
- **API**: 5m K + MA10 + 前波低

### 3.5 Closing Panel 尾盤 5 項確認 (13:00-13:25)
- **5 cond**:
  1. **結構守住**: close > MA10 (🔴 cond1 過嚴 issue、見 `feedback_closing_panel_ma10_flexibility`)
  2. **殺盤考驗過**: 12:00 後最低 < 早盤最高 -2% 或 < MA5 -1%
  3. **反彈確認**: 13:00 後連 2 紅K
  4. **量縮**: 13:00 後 per-bar 量 < 早盤 × 1.2
  5. **未追高**: close 距日高 ≥ 1.5%
- **Levels**:
  - 5/5 = 尾盤_過熱 (Win 40%、別追)
  - 3-4/5 = 尾盤_confirmed (Win 82%、最佳進場)
  - <3/5 = 尾盤_skip
- **API**: 5m K (whole day)

### 3.6 R9 紅K吞噬 (2026-06-18 calibrated)
- **物理意義**: 跳空/漲停 → 第 2-3 根紅K吞噬 entry pattern
- **校正後條件**:
  - red_close > green_open × 0.99 (tolerance)
  - red_body ≥ green_body × 0.9
  - vol > rolling baseline
- **Memory**: `feedback_red_engulfing_entry` (老師 6/16 教學亮點)
- **API**: 5m K (3 根)

### 3.7 R11 漲停隔日昨開低紅線 (regime gated)
- **物理意義**: 昨漲停今開低 = 老師亞翔案例「非常恐怖、直接丟」、自動降 watching
- **Regime gate** (2026-06-18 fix): 弱市 3 條件 OR (TAIEX 5d ≤ -1% / 距MA20 < +1% / 綠K)
- **Memory**: `feedback_prev_limit_up_open_low`
- **API**: daily K (昨日漲停) + intraday open

### 3.8 R15 (extras、課程外、已決策不自創)
- **Memory**: `feedback_no_self_invented_detectors` — 看到漏抓不自創 detector、必先查課程

---

## §4 Intraday Indicators (Ch5 補強)

### 4.1 first5min_skip 前 5 分 >5%
- **紅線 #9**: 前 5 分鐘漲幅 >5% = skip 一票否決
- **API**: 5m K 第 1 根

### 4.2 ma_divergence_filter 均線發散過濾
- **物理意義**: 5/10/20 ma 發散度 > 5% = 過濾

### 4.3 B5-1 大紅棒必停利
- **物理意義**: 大紅棒出現必停利

### 4.4 B5-2 B 型隔日沖出貨
- **物理意義**: B 型 pattern = 主力隔日沖出貨、skip

### 4.5 B5-3 季線往上不空
- **物理意義**: 季線往上 = 不放空

---

## §5 Exit Detectors

### 5.1 umbrella_exit (掀傘)
- **物理意義**: 大紅大綠倒 T 字 K 棒 = 主力倒貨、出場
- **2 modes**: 5min real-time + daily EOD
- **Course**: 主力大 5/29

### 5.2 high_long_black 高檔長黑
- **物理意義**: 高檔長黑 -7% + 量 1.3x + 2 個前波高 + 距 MA20 > 0
- **Course**: 主力大 5/28

### 5.3 profit_milestone 利潤里程碑
- **物理意義**: +20% 部分鎖利、+50% 加碼鎖利

### 5.4 gap_down_emergency 跳空殺
- **物理意義**: 開盤跳空 -3% + 早盤族群整跌 = 殺盤日、09:00-09:05 立即出
- **Memory**: `feedback_sell_off_day_exit_within_5min`

---

## §6 Discipline Filters (紅線)

| 紅線 | 規則 | Memory |
|---|---|---|
| #1 | 漲停隔日跳空 ≥ +3% → 不推 | `feedback_locked_limit_up_next_day_entry` |
| #2 | 距 MA10 +10% 過熱 (conditional) | `feedback_ma10_distance_conditional` |
| #3 | 09:00-12:00 不推快追、13:00 後評估 | `feedback_close_session_only_entry` |
| #4 | Core 停損用結構底、非 MA5 | `feedback_stoploss_core_stocks` |
| #5 | 出清前必跑 checklist | `feedback_past_premature_exits` |
| #6 | 加碼必先脫離成本 +10% + 回測支撐 | `feedback_5347_add_position_condition` |
| #7 | 雙錨停損 = 開盤價 + 昨收 + 第一根 5m低 | `feedback_short_swing_entry_discipline` |
| #8 | 前 10 分鐘不切入 | 同上 |
| #9 | 前 5 分鐘漲幅 >5% = skip | 同上 |

---

## §7 Example Stocks (歷史命中庫)

### 老師明示驅動的真實案例

| Ticker | 日期 | 老師動作 | 對應 detector | 預期 trigger 時點 |
|---|---|---|---|---|
| 3481 群創 | 5/20-5/22 | 「群創幫請+1」「我手在抖大部位 L5」 | small_structure 5/20 → R1 5/22 | 5/22 早盤首攻 |
| 6239 力成 | 5/22 / 6/12 | W底 5/22 / OSAT 6/13 | w_bottom_launch / R9 紅K吞噬 | 漲停日 |
| 1303 南亞 | 6/5 / 6/12 | Stage 1 試水 / 漲停 +9.9% | 老師明示 / 漲停隔日跳空 | 6/12 sell at open |
| 3042 晶技 | 5/19 / 6/12 | small_structure / 隔日拉高賣 | small_structure / morning dump | 5/22 漲停 / 6/12 09:15-09:45 |
| 1605 華新 | 6/7 | broker tier 1「飆股們的媽媽」 | broker confirm | - |
| 2404 漢唐 | 6/15 | 廠務工程 6/9 → 6/15 隔日拉高賣 | 老師明示 → morning dump | 6/15 09:15-09:45 +5.3% |
| 5536 聖暉 | 6/15 | 廠務工程 → 6/15 隔日拉高賣 | 同上 | 6/15 +3.4% |
| 4958 臻鼎 | 6/16-6/17 | ABF 升戰略 watchlist 主推 | 老師明示 + R9 紅K吞噬 | 6/16+ |
| 2454 聯發科 | 6/5 | 全資股 6/2 brief | uniform_ma_above + 殺盤 stop | 6/5 sell-off -5.4% |

### 反向 case (假訊號、預期 skip)

| Ticker | 日期 | 問題 | 預期 filter | 預期燈號 |
|---|---|---|---|---|
| 2327 國巨 | 6/12 | 漲停 + 隔日跳空 +9.1% | 紅線 #1 | skip |
| 4919 新唐 | 6/4-6/10 | 處置股期間 | 處置股 filter | skip |
| 8064 東捷 | 5/19 | 破底股 (Ch2 警示) | Ch2 warning score | exit |
| 4526 東台 | 5/19 | 雙錨停損案例 | 紅線 #7 | exit -12,860 |
| 拉雞盤/出中小 | 6/2 警告 | 主力拉台積出中小型 | 大型權值 vs 中小型分流 | watch only |

### 反向訊號 (Leader 對齊 + 過熱)
- **強多盤**: 100% WR (正向)
- **震盪盤**: 17% WR (反向、最劇 regime 翻轉)

---

## §8 API 資料依賴對照

| API endpoint | 用於 | 重播頻率建議 |
|---|---|---|
| `standard_daily_bar` | 全 daily detector | 每日 1 tick |
| `institutional_investors` | foreign_lead / dual_axis / firstbuy / swing / black_k | 每日 1 tick |
| `stock_minute_kbar` | 5m K resample → intraday triggers | 1 分鐘級 |
| FubonClient `get_realtime_snapshot` | live snap 09:00-13:30 | 5-10 秒 / tick |
| FubonClient `subscribe_quotes` | tick-by-tick 報價 | 真實 tick |
| TAIEX daily K | regime gate / setup detect | 每日 1 tick |
| TAIEX 1m (futures) | 多盤 regime live | 1 分鐘級 |

## §9 Mock server scenarios 對應

| Scenario name | 重播 historical day | 主要驗證 trigger | Expected outcome |
|---|---|---|---|
| `scenario_6_12_sell_off_dump` | 2026-06-12 | morning dump (3042 09:15-09:45) | sell 50% @ +4% |
| `scenario_6_12_setup_fire` | 2026-06-12 | F1-F4 setups (taiex_5d=-2%) | 229 hits |
| `scenario_6_15_pump_open` | 2026-06-15 | morning dump (2404/5536) | sell 50% |
| `scenario_6_17_locked_limit_up` | 2026-06-17 | R11 跳空 + 紅線 #1 | skip |
| `scenario_5_22_w_bottom_launch` | 2026-05-22 | w_bottom_launch + R9 | confirm fire |
| `scenario_5_20_n_attack_smallstr` | 2026-05-20 | small_structure | R1 5/22 confirm |
| `scenario_6_5_sell_off_chip_strong` | 2026-06-05 | chip-aware exit (relax MA10) | hold |
| `scenario_6_8_sell_off_disposal` | 2026-06-08 | suffocation + disposal filter | skip 處置股 |

---

## Changelog
| Version | Date | Notes |
|---|---|---|
| v1.0 | 2026-06-19 | 初版、總結 22 detector + 7 setup + 15+ trigger + 5 exit detector + 9 紅線 + 例 stocks |
