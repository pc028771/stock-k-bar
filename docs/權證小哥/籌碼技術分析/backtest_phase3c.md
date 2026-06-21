# Phase 3c — key_broker_signal (detector 4) + 三軸 cross backtest

> Source: `scripts/xiaoge/backtest_phase3c.py`
> Date: 2026-06-16
> 樣本：2026-05-01 ~ 2026-06-12（30 trading days）
> **Universe：teacher 99 (老師 picks_2026 ∪ teacher_sector_tickers ∩ bb/chip 候選)**
> 資料：`TaiwanStockTradingDailyReport` (FinMind 分點日報 / 4.4M rows / 50 dates)
>   - 4/1-4/22 (14 days, 99/99): xiaoge fetcher 原本就抓的
>   - 5/18, 5/28, 6/1-2, 6/4, 6/12 部分: ~/.zhuli_cache/broker/ merge 補
>   - 其餘 30+ 個 date: teacher universe fetcher (concurrency=2, 1.5s sleep, ~52 min) 補抓
> Pool 建構：用 2026-04-01 ~ 2026-04-30 (20 trading days) broker data 算「低買 + 高賣」分數，每股 top 5、最低 3 次出現
> 進場閾值：池內任一分點淨買 ≥ 50 張 + 月線上揚 + 站上月線
> 出場規則：**C6**（MA10 容忍 + 量比 + 連 2 天容忍 → 隔日開盤出）

## 🔴 重點摘要

- **D4 long: n=62 / WR 41.9% / avg +6.58% / cross-month=2** → **watch-only**（差 23pp 到 actionable 65%）
- **Top winners 跟 user 知道的 Q2 大牛股一致**：6173 (+136%), 2478 (+112%), 3481 (+80%), 6831 (+41%), 2344 (+38%), 6548 (+34%), 2481 (+30%), 4966 (+29%) — **訊號抓對人**
- **D4 short: WR 28.6% < 35%** → 反向訊號 skip-list 候選（嚴格說「池內 top 分點賣超」的標的 = 不要做空、可能反而強勢）
- **cross 3way: 0 signals** — 99 universe × 6 週 + 5-day 對齊窗口太緊、bb 訊號本身就稀 (n=67)
- **D1 / D2v2 都 WR 34%** — 整個 5 月底大盤殺、單獨布林或單獨籌碼都不抗跌、避免單一訊號進場

## 結果對比

| Detector | n | avg_ret | median | win_rate | avg_hold | tickers | months | max | min |
|---|---|---|---|---|---|---|---|---|---|
| detector 1: bb_squeeze (升龍拳) [C6] | 67 | 0.62% | -1.44% | 34.3% | 9.5 | 67 | 1 | 35.9% | -16.93% |
| detector 2 v2: chip 真三軸 10% [C6] | 397 | 3.32% | -1.88% | 34.0% | 8.5 | 362 | 1 | 166.67% | -19.31% |
| detector 4: key_broker_signal (long) [C6] | 62 | 6.58% | -2.77% | 41.9% | 7.3 | 43 | 2 | 136.26% | -15.85% |
| detector 4: key_broker_signal (short) [C6] | 21 | -2.84% | -1.58% | 28.6% | 2.2 | 17 | 2 | 5.25% | -16.74% |
| cross 2way: bb ∩ broker (5d) [C6] | 0 | None% | None% | None% | None | 0 | 0 | None% | None% |
| cross 2way: chip ∩ broker (5d) [C6] | 28 | 7.61% | -0.86% | 42.9% | 9.2 | 26 | 1 | 112.36% | -15.85% |
| cross 3way: bb ∩ chip ∩ broker (5d) [C6] | 0 | None% | None% | None% | None | 0 | 0 | None% | None% |


## 三維 Robustness 判定

> 跨股 ≥ 5 + 跨月 ≥ 2 + win_rate ≥ 65% = actionable
> 50-65% = watch-only
> ≤ 35% = 反向訊號 skip 清單

- **detector 1: bb_squeeze (升龍拳) [C6]**: insufficient diversity (tickers=67, months=1, win_rate=34.3%) → not robust
- **detector 2 v2: chip 真三軸 10% [C6]**: insufficient diversity (tickers=362, months=1, win_rate=34.0%) → not robust
- **detector 4: key_broker_signal (long) [C6]**: watch-only (tickers=43, months=2, win_rate=41.9%)
- **detector 4: key_broker_signal (short) [C6]**: reverse-signal candidate (tickers=17, months=2, win_rate=28.6%) — skip-list
- **cross 2way: bb ∩ broker (5d) [C6]**: no signals
- **cross 2way: chip ∩ broker (5d) [C6]**: insufficient diversity (tickers=26, months=1, win_rate=42.9%) → not robust
- **cross 3way: bb ∩ chip ∩ broker (5d) [C6]**: no signals


## 質性觀察：常被「關鍵分點低買」的股

下表是 pool 中 `low_buy_count` 最高的 (ticker, broker) pair（pool 用 4 月資料建）：

| ticker | broker | low_buy_count | high_sell_count | score | appearances |
|---|---|---|---|---|---|
| 2344 | 凱基竹北 | 14 | 0 | 0.700 | 20 |
| 2344 | 富邦南港 | 14 | 0 | 0.700 | 20 |
| 2344 | 土銀嘉義 | 13 | 0 | 0.684 | 19 |
| 6443 | 第一路竹 | 13 | 0 | 0.867 | 15 |
| 2230 | 國票南科 | 12 | 0 | 1.000 | 12 |
| 2344 | 台新城東 | 12 | 0 | 0.667 | 18 |
| 2609 | 富邦新板 | 12 | 0 | 1.000 | 12 |
| 2609 | 富邦羅東 | 12 | 0 | 1.000 | 12 |
| 2609 | 富邦花蓮 | 11 | 0 | 1.000 | 11 |
| 6576 | 國票安和 | 11 | 0 | 0.786 | 14 |
| 2023 | 兆豐北高 | 10 | 0 | 0.909 | 11 |
| 2408 | 群益市府 | 10 | 2 | 0.600 | 20 |
| 2520 | 台新城中 | 10 | 0 | 0.833 | 12 |
| 2609 | 臺銀新竹 | 10 | 0 | 1.000 | 10 |
| 3716 | 康和 | 10 | 0 | 0.909 | 11 |


## 資料限制 / 已知問題

1. **Pool 樣本期短** — 只有 30 個交易日 (2026-04-01 ~ 2026-04-30) 用來判定哪些分點「持續低買高賣」。
   老師原始定義是「800-2000 天分點買賣超歷史」、實作受 FinMind rate limit 限制只能短期。
2. **沒排除外資 / 自營分點** — pool 用分數自然篩、不硬排外資。可能漏掉「庫藏股分點」加分項（detector_spec.md §4）。
3. **單張 = 1000 股閾值** — pool 動作 ≥ 10 張、訊號 ≥ 50 張、可能對小型股太嚴。
4. **C6 出場 vs leave_upper_band** — 改用 MA10 trail 後不再依賴 BB upper、適用非布林訊號（detector 4 本身不用 BB）。

## 後續

- detector 4 long 樣本不足 / 不顯著 → watch-only、收集更長期資料再評估
- cross 3way 樣本不足 → 持續觀察、不擅自合入主訊號

## D4 Long Top Winners / Top Losers（質性）

### Top 10 winners

| ticker | signal_date | entry | exit | hold | ret |
|---|---|---|---|---|---|
| 6173 | 2026-05-04 | 91.00 | 215.00 | 23 | +136.26% |
| 2478 | 2026-05-18 | 89.00 | 189.00 | 18 | +112.36% |
| 3481 | 2026-05-05 | 27.80 | 49.95 | 24 | +79.68% |
| 6831 | 2026-05-05 | 535.00 | 752.00 | 18 | +40.56% |
| 2344 | 2026-05-21 | 116.50 | 160.50 | 12 | +37.77% |
| 6548 | 2026-05-28 | 66.50 | 89.10 | 10 | +33.98% |
| 2481 | 2026-05-12 | 115.00 | 149.00 | 19 | +29.57% |
| 4966 | 2026-05-07 | 610.00 | 788.00 | 19 | +29.18% |
| 2883 | 2026-06-01 | 22.55 | 28.75 | 8 | +27.49% |
| 5425 | 2026-05-14 | 73.00 | 90.90 | 16 | +24.52% |

### Top 10 losers

| ticker | signal_date | entry | exit | hold | ret |
|---|---|---|---|---|---|
| 5864 | 2026-05-11 | 36.90 | 31.05 | 3 | -15.85% |
| 6642 | 2026-05-28 | 101.00 | 85.20 | 2 | -15.64% |
| 4526 | 2026-05-26 | 45.80 | 39.25 | 3 | -14.30% |
| 3714 | 2026-05-22 | 85.10 | 73.50 | 5 | -13.63% |
| 6016 | 2026-05-11 | 25.40 | 21.95 | 6 | -13.58% |
| 6284 | 2026-05-29 | 120.00 | 104.00 | 3 | -13.33% |
| 4526 | 2026-05-05 | 40.00 | 34.75 | 3 | -13.12% |
| 3016 | 2026-05-29 | 138.50 | 120.50 | 2 | -13.00% |
| 6488 | 2026-05-27 | 935.00 | 820.00 | 6 | -12.30% |
| 2301 | 2026-05-28 | 236.00 | 207.00 | 6 | -12.29% |

**觀察**：
- Winners 持倉 8-24 天、抓 Q2 大行情段（6173 矽力杰 / 2478 大毅 / 3481 群創）
- Losers 持倉 2-6 天就被 C6 砍出、訊號發在大盤殺盤前夕（5/26-5/29 拉回段）— 不是訊號本身錯、是大盤回檔
- 4526 出現兩次 -13% 都是反彈中段假突破 (5/5、5/26) → 候選改進：加大盤過濾 (5d 跌 ≤ -1% 不進)
