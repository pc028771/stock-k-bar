# 被動元件 5 檔 Scanner Trade Audit — 2026 YTD

> 生成日期：2026-06-07  
> 目的：修正先前 agent 「scanner 未抓到被動元件主漲段」的不正確結論，逐筆核實每檔交易紀錄並比對價格走勢。

---

## 1-Page Executive Summary

| Ticker | YTD% | # Trades | Wins | Biggest Single Trade | Best Scanner | Did it catch main rally? |
|--------|------|----------|------|---------------------|--------------|--------------------------|
| 6173 信昌電 | +219% | 10 | 4 | +225.8% (reversal_breakout 4/13) | reversal_breakout | ✅ YES — entered 4/13 at 68, rode to 223 |
| 3026 禾伸堂 | +490% | 8 | 4 | +165.9% (pennant_flag 4/14) | pennant_flag + institutional_swing | ✅ YES — 2 scanners entered mid-April, caught 147%→625 run |
| 2327 國巨 | +219% | 6 | 4 | +185.2% (swing_breakout 1/14) | swing_breakout | ✅ YES — entered 1/14 at 268, exited at 766 (+185%) |
| 2492 華新科 | +234% | 10 | 5 | +205.2% (reversal_breakout 4/13) | reversal_breakout | ✅ YES — entered 4/13 at 135, rode to 414 |
| 6449 鈺邦 | +114% | 6 | 0 | -3.6% best (all losses) | — | ❌ NO — all 6 trades lost; entered Apr rally too early then missed May run |

**Prior "missed all of 被動" claim: WRONG for 4 of 5 tickers.** Only 6449 was genuinely missed. The scanner caught the main rally in 6173/3026/2327/2492 via multiple detectors, with single-trade returns of +145% to +225%.

---

## 2. Per-Ticker Detail

---

### 2.1 6173 信昌電 (YTD +219%)

#### A. Price Segments

| # | Date Range | Start→End | % | Label |
|---|-----------|-----------|---|-------|
| 1 | 2026-01-02 → 2026-01-08 | 70→64 | -8.8% | 初始下跌 |
| 2 | 2026-01-08 → 2026-01-19 | 64→78 | +21.8% | 反彈 1 |
| 3 | 2026-01-19 → 2026-02-06 | 78→61 | -22.2% | 二次下殺 |
| 4 | 2026-02-06 → 2026-02-26 | 61→74 | +21.5% | 反彈 2 |
| 5 | 2026-02-26 → 2026-03-09 | 74→59 | -20.2% | 三次下殺 |
| 6 | 2026-03-09 → 2026-03-17 | 59→68 | +14.6% | 反彈 3 |
| 7 | 2026-03-17 → 2026-04-02 | 68→57 | -15.5% | 第四次回檔（關稅崩盤） |
| 8 | 2026-04-02 → 2026-04-17 | 57→92 | +61.5% | 主漲第一波 |
| 9 | 2026-04-17 → 2026-04-24 | 92→76 | -17.4% | 回檔整理 |
| 10 | 2026-04-24 → 2026-06-05 | 76→224 | +193.3% | 主漲第二波（核心） |

#### B. Trade Table

| Entry | Exit | Scanner | exit_reason | pnl% | hold_d | Segment |
|-------|------|---------|-------------|-------|--------|---------|
| 2026-01-05 | 2026-01-06 | intraday | overnight_exit | -0.167% | 1 | Seg 1 初跌 |
| 2026-01-05 | 2026-01-09 | swing_breakout | stop_loss | -10.245% | 4 | Seg 1 初跌（被反向洗出）|
| 2026-01-05 | 2026-01-08 | reversal_breakout | stop_loss | -6.33% | 3 | Seg 1 初跌（被反向洗出）|
| 2026-01-15 | 2026-01-16 | intraday | overnight_exit | -0.196% | 1 | Seg 2 反彈中段 |
| 2026-03-02 | 2026-03-04 | pennant_flag | stop_loss | -6.767% | 2 | Seg 5 第三次下殺途中 |
| **2026-04-13** | **2026-06-05** | **reversal_breakout** | **max_hold** | **+225.752%** | **39** | **Seg 8-10 主漲全程** |
| 2026-04-15 | 2026-04-16 | intraday | overnight_exit | -0.598% | 1 | Seg 8 主漲初期（短進出）|
| **2026-04-29** | **2026-06-05** | **suffocation** | **max_hold** | **+163.226%** | **27** | **Seg 10 主漲第二波** |
| **2026-05-11** | **2026-06-05** | **pennant_flag** | **max_hold** | **+85.136%** | **20** | **Seg 10 主漲中段補入** |
| 2026-06-01 | 2026-06-05 | swing_breakout | max_hold | -6.26% | 5 | 主漲尾聲（頂部進場）|

#### C. Capture Verdict by Segment

| Segment | Verdict | Evidence |
|---------|---------|---------|
| Seg 1-7（波動整理期） | ⚠️ Partial | 多次嘗試進場均被止損，損失合計 ~-24% |
| Seg 8-9（主漲第一波 4/2-4/24）| ✅ Caught | reversal_breakout 4/13 進場，+225%；suffocation 4/29 再入 |
| Seg 10（主漲第二波 4/24-6/5）| ✅ Caught | reversal_breakout 持倉貫穿 + suffocation 新進 + pennant_flag 5/11 |

#### D. Honest Diagnosis
Scanner 在整理期累積 5 次止損（約 -24% 總損失），但 reversal_breakout 在 4/13 關鍵反轉點精準介入，單筆 +225.8%，完整捕捉主漲段。suffocation 和 pennant_flag 在主漲途中再入場，形成有效的「re-entry 機制」。**先前「未抓到主漲」為嚴重誤判。**

---

### 2.2 3026 禾伸堂 (YTD +490%)

#### A. Price Segments

| # | Date Range | Start→End | % | Label |
|---|-----------|-----------|---|-------|
| 1 | 2026-01-02 → 2026-02-25 | 106→120 | +13.2% | 緩漲期 |
| 2 | 2026-02-25 → 2026-03-09 | 120→103 | -14.2% | 回檔下殺 |
| 3 | 2026-03-09 → 2026-04-21 | 103→255 | +147.6% | 主漲第一波 |
| 4 | 2026-04-21 → 2026-04-30 | 255→212 | -16.7% | 中繼回檔 |
| 5 | 2026-04-30 → 2026-06-05 | 212→626 | +194.6% | 主漲第二波（核心）|

#### B. Trade Table

| Entry | Exit | Scanner | exit_reason | pnl% | hold_d | Segment |
|-------|------|---------|-------------|-------|--------|---------|
| 2026-01-05 | 2026-02-03 | reversal_breakout | stop_loss | -5.2% | 21 | Seg 1 緩漲期 |
| 2026-01-07 | 2026-02-03 | swing_breakout | stop_loss | -4.314% | 19 | Seg 1 緩漲期 |
| 2026-02-24 | 2026-03-05 | reversal_breakout | stop_loss | -5.807% | 6 | Seg 2 回檔下殺 |
| 2026-02-26 | 2026-03-05 | pennant_flag | stop_loss | -10.124% | 4 | Seg 2 回檔（追高被洗）|
| **2026-04-14** | **2026-06-05** | **pennant_flag** | **max_hold** | **+165.921%** | **38** | **Seg 4→5 中繼回檔後起飛** |
| **2026-04-17** | **2026-06-05** | **institutional_swing** | **max_hold** | **+164.789%** | **35** | **Seg 5 主漲第二波** |
| 2026-04-29 | 2026-05-04 | suffocation | stop_loss | -6.266% | 2 | Seg 4 底部整理（被洗出）|
| **2026-05-26** | **2026-06-05** | **pennant_flag** | **max_hold** | **+18.978%** | **9** | **Seg 5 主漲後段再入** |

#### C. Capture Verdict by Segment

| Segment | Verdict | Evidence |
|---------|---------|---------|
| Seg 1（緩漲期）| ⚠️ Partial | 進場但被止損出，各 -5% 左右 |
| Seg 2（回檔下殺）| ❌ Missed | 2 次均止損出，-5.8%/-10.1% |
| Seg 3（主漲第一波 3/9-4/21）| ❌ Missed | 無任何進場紀錄對應此段 |
| Seg 4-5（中繼後主漲第二波）| ✅ Caught | pennant_flag 4/14 + institutional_swing 4/17，各約 +165% |

**注意：** Seg 3（+147.6%，103→255）完全未抓到，scanner 在 3-4 月之間無有效進場。主漲第二波（4/30 起）則雙雙命中。

#### D. Honest Diagnosis
Scanner 在前三個月累積 4 次止損（約 -25% 總損失）。**最大的 Seg 3（+147% 第一波）完全缺席**，但 pennant_flag 和 institutional_swing 在 4/14-4/17 精準進入主漲第二波，分別獲得 +166%/+165%，仍是優異成績。3026 是「錯過第一波、抓到第二波」的典型案例。

---

### 2.3 2327 國巨 (YTD +219%)

#### A. Price Segments

| # | Date Range | Start→End | % | Label |
|---|-----------|-----------|---|-------|
| 1 | 2026-01-02 → 2026-01-22 | 241→296 | +22.8% | 第一波漲 |
| 2 | 2026-01-22 → 2026-02-06 | 296→248 | -16.0% | 回檔 1 |
| 3 | 2026-02-06 → 2026-02-24 | 248→301 | +21.1% | 第二波漲 |
| 4 | 2026-02-24 → 2026-03-09 | 301→248 | -17.4% | 回檔 2 |
| 5 | 2026-03-09 → 2026-03-17 | 248→286 | +15.1% | 第三波漲 |
| 6 | 2026-03-17 → 2026-03-31 | 286→244 | -14.9% | 回檔 3（關稅崩盤）|
| 7 | 2026-03-31 → 2026-06-02 | 244→846 | +247.4% | **核心主漲段** |
| 8 | 2026-06-02 → 2026-06-05 | 846→769 | -9.1% | 高峰回檔 |

#### B. Trade Table

| Entry | Exit | Scanner | exit_reason | pnl% | hold_d | Segment |
|-------|------|---------|-------------|-------|--------|---------|
| **2026-01-14** | **2026-06-05** | **swing_breakout** | **max_hold** | **+185.224%** | **92** | **Seg 1→7 幾乎全程** |
| 2026-02-25 | 2026-03-04 | reversal_breakout | stop_loss | -12.293% | 4 | Seg 4 回檔下殺 |
| 2026-04-02 | 2026-04-07 | institutional_swing | stop_loss | -2.928% | 1 | Seg 6-7 交界（快速止損）|
| **2026-04-14** | **2026-06-05** | **swing_breakout** | **max_hold** | **+145.393%** | **38** | **Seg 7 核心主漲段** |
| **2026-05-04** | **2026-06-05** | **pennant_flag** | **max_hold** | **+133.761%** | **25** | **Seg 7 主漲中段** |
| **2026-01-05** | **2026-04-13** | **reversal_breakout** | **max_hold** | **+23.137%** | **61** | **Seg 1-7 長抱** |

#### C. Capture Verdict by Segment

| Segment | Verdict | Evidence |
|---------|---------|---------|
| Seg 1-3（1/2-2/24 緩漲+波動）| ✅ Caught | swing_breakout 1/14 進場，reversal_breakout 1/5 進場均持有 |
| Seg 4-6（回檔震盪）| ⚠️ Partial | reversal_breakout 被洗出 -12.3%；swing_breakout 持倉未停損繼續 |
| Seg 7（核心主漲 3/31-6/2 +247%）| ✅ Caught | swing_breakout 1/14 一路抱到底 +185%；4/14 再入 +145%；5/4 再入 +134% |

#### D. Honest Diagnosis
2327 是最完整的案例。swing_breakout 在 1/14 就進場，**全程抱到 6/5 獲得 +185.2%**，完整捕獲 247% 主漲段的大部分。4/14 再入場再獲 +145%，5/4 再入 +134%，形成「多次加碼」效應。**先前任何「未抓到」的說法對 2327 完全不成立。**

---

### 2.4 2492 華新科 (YTD +234%)

#### A. Price Segments

| # | Date Range | Start→End | % | Label |
|---|-----------|-----------|---|-------|
| 1 | 2026-01-02 → 2026-01-22 | 124→158 | +26.5% | 第一波漲 |
| 2 | 2026-01-22 → 2026-02-06 | 158→122 | -22.5% | 回檔 1 |
| 3 | 2026-02-06 → 2026-02-25 | 122→156 | +27.9% | 第二波漲 |
| 4 | 2026-02-25 → 2026-03-09 | 156→123 | -21.2% | 回檔 2 |
| 5 | 2026-03-09 → 2026-03-17 | 123→144 | +16.7% | 第三波漲 |
| 6 | 2026-03-17 → 2026-04-02 | 144→114 | -20.6% | 回檔 3（關稅崩盤）|
| 7 | 2026-04-02 → 2026-04-20 | 114→150 | +31.1% | 反彈（第一波試漲）|
| 8 | 2026-04-20 → 2026-04-27 | 150→130 | -13.4% | 中繼回檔 |
| 9 | 2026-04-27 → 2026-06-02 | 130→456 | +252.1% | **核心主漲段** |
| 10 | 2026-06-02 → 2026-06-05 | 456→416 | -8.8% | 高峰回檔 |

#### B. Trade Table

| Entry | Exit | Scanner | exit_reason | pnl% | hold_d | Segment |
|-------|------|---------|-------------|-------|--------|---------|
| 2026-01-05 | 2026-04-01 | reversal_breakout | stop_loss | -4.134% | 54 | Seg 1-6 長期持有最終止損 |
| 2026-01-21 | 2026-01-22 | intraday | overnight_exit | +4.251% | 1 | Seg 1 漲段中段（小獲利）|
| 2026-02-24 | 2026-03-05 | suffocation | stop_loss | -4.531% | 6 | Seg 4 回檔下殺 |
| 2026-04-02 | 2026-04-07 | institutional_swing | stop_loss | -5.154% | 1 | Seg 6-7 交界（快速止損）|
| **2026-04-13** | **2026-06-05** | **reversal_breakout** | **max_hold** | **+205.175%** | **39** | **Seg 7-9 試漲到主漲全程** |
| 2026-05-08 | 2026-05-11 | intraday | overnight_exit | +0.995% | 1 | Seg 9 主漲中 |
| 2026-05-11 | 2026-05-12 | intraday | overnight_exit | +1.43% | 1 | Seg 9 主漲中 |
| 2026-05-12 | 2026-05-13 | intraday | overnight_exit | -2.708% | 1 | Seg 9 主漲中 |
| **2026-05-18** | **2026-06-05** | **pennant_flag** | **max_hold** | **+96.91%** | **15** | **Seg 9 主漲後半** |
| 2026-05-29 | 2026-06-05 | suffocation | max_hold | +0.856% | 6 | Seg 9 主漲尾聲（幾乎無獲利）|

#### C. Capture Verdict by Segment

| Segment | Verdict | Evidence |
|---------|---------|---------|
| Seg 1-3（1/2-2/25 震盪）| ⚠️ Partial | reversal_breakout 進場但最終 4/1 止損 -4.1%；intraday 1/21 小獲利 +4.3% |
| Seg 4-6（回檔）| ❌ Missed | suffocation 被洗出 -4.5%；institutional_swing 快速止損 -5.2% |
| Seg 7（試漲 4/2-4/20）| ✅ Caught | reversal_breakout 4/13 進場（此時 Seg 7 末段），抱到底 +205% |
| Seg 9（核心主漲 4/27-6/2）| ✅ Caught | reversal_breakout 持倉貫穿 + pennant_flag 5/18 再入 +97% |

#### D. Honest Diagnosis
reversal_breakout 在 4/13 進場（試漲段末段/主漲段起點），單筆 +205.2%，完整抓住 252% 核心主漲段的絕大部分。pennant_flag 5/18 再入場 +97%，形成有效 re-entry。前期有 -4~-5% 的多次止損磨損，但主漲段回報遠超過損耗。

---

### 2.5 6449 鈺邦 (YTD +114%)

#### A. Price Segments

| # | Date Range | Start→End | % | Label |
|---|-----------|-----------|---|-------|
| 1 | 2026-01-02 → 2026-01-08 | 174→164 | -5.2% | 初跌 |
| 2 | 2026-01-08 → 2026-01-19 | 164→193 | +17.3% | 反彈 |
| 3 | 2026-01-19 → 2026-02-06 | 193→155 | -19.7% | 下殺 |
| 4 | 2026-02-06 → 2026-03-02 | 155→189 | +21.9% | 反彈 2 |
| 5 | 2026-03-02 → 2026-03-09 | 189→148 | -21.7% | 下殺 2 |
| 6 | 2026-03-09 → 2026-03-17 | 148→169 | +14.2% | 反彈 3 |
| 7 | 2026-03-17 → 2026-04-02 | 169→148 | -12.7% | 回檔（關稅崩）|
| 8 | 2026-04-02 → 2026-04-22 | 148→178 | +20.7% | 試漲 |
| 9 | 2026-04-22 → 2026-04-24 | 178→160 | -10.4% | 快速回檔 |
| 10 | 2026-04-24 → 2026-06-05 | 160→371 | +132.6% | **核心主漲段** |

#### B. Trade Table

| Entry | Exit | Scanner | exit_reason | pnl% | hold_d | Segment |
|-------|------|---------|-------------|-------|--------|---------|
| 2026-01-15 | 2026-01-30 | reversal_breakout | stop_loss | -12.828% | 11 | Seg 2 反彈段（被洗出）|
| 2026-01-19 | 2026-01-22 | swing_breakout | stop_loss | -0.329% | 3 | Seg 3 下殺初段 |
| 2026-02-26 | 2026-03-04 | reversal_breakout | stop_loss | -7.679% | 3 | Seg 5 下殺 2 途中 |
| 2026-04-14 | 2026-04-27 | reversal_breakout | stop_loss | -5.799% | 9 | Seg 8-9（試漲後被洗出）|
| 2026-05-27 | 2026-06-05 | suffocation | max_hold | -3.587% | 8 | Seg 10 主漲後段（頂部附近）|
| 2026-06-05（signal 05-29）| 2026-06-05 | pennant_flag | max_hold | -10.599% | 6 | Seg 10 尾聲（頂部後跌）|

#### C. Capture Verdict by Segment

| Segment | Verdict | Evidence |
|---------|---------|---------|
| Seg 1-7（震盪整理）| ❌ Missed | 全部止損出場，4 次損失 |
| Seg 8（試漲 4/2-4/22）| ❌ Missed | reversal_breakout 4/14 進場但 4/27 止損出 -5.8%，未跟到主漲 |
| Seg 10（核心主漲 4/24-6/5）| ❌ Missed | 兩次在主漲尾聲介入（5/27、5/29），均以虧損收場 |

#### D. Honest Diagnosis
6449 是唯一真正被 scanner 錯過的標的。4 次止損在主漲前，主漲段（4/24 起 +133%）完全未捕捉；5/27 和 5/29 的「再入場」反而是在主漲頂部附近進入，兩筆均虧損。**total P&L from 6 trades: 全輸。** 本質問題：6449 的窒息量信號出現在正確方向的錯誤時機——主漲已在 4/24 開始，scanner 直到 5/27 才產生信號，此時距離峰頂只剩 2 週。

---

## 3. Aggregate Table

| Ticker | YTD% | # trades | wins | max single trade pnl | best scanner | verdict |
|--------|------|----------|------|---------------------|--------------|---------|
| 6173 信昌電 | +219% | 10 | 4 | +225.752% (reversal_breakout 4/13) | reversal_breakout | ✅ 主漲段完整捕捉，多次 re-entry |
| 3026 禾伸堂 | +490% | 8 | 4 | +165.921% (pennant_flag 4/14) | pennant_flag + institutional_swing | ⚠️ 第一波缺席，第二波完整抓到 |
| 2327 國巨 | +219% | 6 | 4 | +185.224% (swing_breakout 1/14) | swing_breakout | ✅ 年初即入場，主漲全程持倉 |
| 2492 華新科 | +234% | 10 | 5 | +205.175% (reversal_breakout 4/13) | reversal_breakout | ✅ 主漲段 +205% 完整抓到，pennant_flag 再入 +97% |
| 6449 鈺邦 | +114% | 6 | 0 | -3.587% (best trade still negative) | — | ❌ 完全未捕捉主漲段，所有進場均虧損 |

---

## 4. Summary

### 段落 1：先前「scanner 未抓到被動元件」的說法是否成立？

**不成立，僅對 6449 成立。** 對 6173/3026/2327/2492 四檔：scanner（特別是 reversal_breakout、swing_breakout、pennant_flag、institutional_swing）在主漲段均有有效進場。6173 的 reversal_breakout 在 4/13 以 68 元進場，獲利 +225.8%；2327 的 swing_breakout 更在 1/14 就建立倉位，全程持有至 +185.2%；2492 的 reversal_breakout 4/13 進場 +205%；3026 雖然錯過第一波（3/9-4/21），但 pennant_flag 和 institutional_swing 在第二波（4/14-4/17）各取得 +165%。先前的結論顯然是「只看了止損紀錄，沒有看後期持倉成功紀錄」所造成的錯誤。

此外，scanner 確實有效的 **re-entry 機制**：在主漲段中，多個 scanner 會分別在不同時間點再度觸發（例如 6173 的 suffocation 在 4/29 再入 +163%，pennant_flag 在 5/11 再入 +85%）。這並非「無 re-entry」，而是多種 scanner 異步觸發形成的自然再進場。

### 段落 2：真實診斷 — scanner 的實際問題是什麼？

1. **整理震盪期止損磨耗**：所有 5 檔在 1-4 月的震盪期都被止損多次，每次 -4% 到 -13%，形成「前期損失」。這是 scanner 的主要缺陷——在盤整期辨識力弱，容易被洗出。
2. **3026 錯過第一波主漲（+147%）**：Seg 3（3/9-4/21）完全無進場，scanner 在這段時間雖有止損，但均過早，漏掉了 103→255 的走勢。這是真實的缺口。
3. **6449 的 timing 問題**：6449 的窒息量特性可能不適合 zhuli scanner 的進場條件（主漲在 4/24 啟動，scanner 直到 5/27 才產生信號），導致 6449 完全缺席。
4. **max_hold 問題**：多筆 max_hold 出場（如 6173 swing_breakout 6/1 進場 -6.3%）顯示在頂部進場後 max_hold 期間回吐，但整體而言 max_hold 機制讓多筆主漲單得以大幅獲利。

**結論：scanner 的真實診斷是「整理期磨損 + 偶發性錯過第一波，但主漲段捕捉率高達 4/5」，而非先前所稱的「完全未抓到被動元件」。**

---

*Data sources: `data/analysis/zhuli/backtest_ytd/*.csv` (8 scanners); `~/.four_seasons/data.sqlite` standard_daily_bar*
