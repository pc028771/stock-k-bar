# Phase 3c — key_broker_signal (detector 4) 建置 + backtest

> Source code: `scripts/xiaoge/{fetch_broker_trades,build_key_broker_pool,backtest_phase3c}.py`
>              `scripts/xiaoge/entry/key_broker_signal.py`
> Date: 2026-06-14
> 目標：實作老師「關鍵分點」detector + 三維交叉 (bb ∩ chip_v2 ∩ broker) 驗證

## 狀態：⚠️ 程式碼已完成、IP 被 FinMind 封鎖中（試過兩種抓法都觸發）

### 嘗試紀錄

| 嘗試 | 方法 | 結果 |
|---|---|---|
| 1 | `FinMind.DataLoader.taiwan_stock_trading_daily_report(date=X, use_async=True)` 全市場單日 | Day 1 成功 (513k rows, 62s)、Day 2 起卡死、內部反覆 TaiwanStockInfo + login、累積 200+ 內部 call、把 6000/hr 配額用光 |
| 2 | 直接 HTTP `/api/v4/data` per (ticker, date)、aiohttp concurrency=8 | 抓了 3 個交易日 (12022 rows, 37 tickers) 後變 `402 quota exceeded` → 接著 IP `403 ip banned` |

**現況**：IP 被 ban、無法繼續、需等 FinMind 解封（通常 1-24 小時）。

partial 資料 (3 dates: 2026-04-02, 04-07, 04-10) 已存在 `data/analysis/xiaoge/broker_trades/2026-04-01_2026-06-12.parquet`、共 12022 rows。

### 已完成

1. **Fetcher** `scripts/xiaoge/fetch_broker_trades.py`
   - 用 aiohttp 對候選 ticker 集 (bb_squeeze ∪ chip_v2 觸發過的 ~408 檔，篩 4 碼純數字後約 ~330 檔) 並行抓 `TaiwanStockTradingDailyReport`
   - aggregate by (date, ticker, broker_id) → net_shares, buy_shares, sell_shares
   - 輸出 `data/analysis/xiaoge/broker_trades/{start}_{end}.parquet`
   - **架構備註**：原本要走「1 API call 全市場單日」的方案、實測發現
     - 直接 HTTP 端點 (`/api/v4/data`) 不允許 `data_id` 為空（400 too large）
     - FinMind DataLoader 的 `taiwan_stock_trading_daily_report(date=X, use_async=True)` 第一天 OK (62s, 513k rows)，第二天起會反覆觸發內部 `TaiwanStockInfo` lookup + login，1 小時內打爆 6000/hr 配額
     - 因此改成「候選 ticker × 單日」精準 fan-out

2. **Pool builder** `scripts/xiaoge/build_key_broker_pool.py`
   - 規則：對每檔股票每個分點計算
     - 出場次數 = 該分點 ≥ 10 張動作的天數
     - 低買次數 = net > 0 + close ≤ 過去 30 日 25 percentile
     - 高賣次數 = net < 0 + close ≥ 過去 30 日 75 percentile
     - 分數 = (低買 + 高賣) / 出場次數
   - 取每股 top 5，出場次數 ≥ 3 天
   - 輸出 `data/analysis/xiaoge/key_broker_pool.parquet`
   - **單元測試已通過**：合成假資料驗證低買 + 高賣計數 + 分數計算邏輯正確

3. **Detector** `scripts/xiaoge/entry/key_broker_signal.py`
   - 多頭 `detect()`：池內任一分點淨買 ≥ 50 張 + 月線上揚 + 收盤站上月線
   - 空頭 `detect_short()`：池內任一分點淨賣 ≥ 50 張 + 月線下彎
   - **單元測試已通過**：合成資料驗證 long 訊號正確命中

4. **Backtest** `scripts/xiaoge/backtest_phase3c.py`
   - **出場規則 C6**（feedback_exit_rules_v3）：
     - 收盤 ≥ MA10 → 不出
     - 收 < MA10 by ≥ 2% (深破) → 隔日開盤出
     - 收 < MA10 by < 2% + 量比 ≥ 1.0 → 隔日開盤出
     - 容忍區 -2% ~ 0% 連 2 天 → 隔日開盤出
   - 跑 7 個變體：
     - detector 1 single (bb_squeeze)
     - detector 2 v2 single (chip_v2)
     - detector 4 long
     - detector 4 short（鏡像 C6）
     - cross 2way: bb ∩ broker (5d window)
     - cross 2way: chip ∩ broker (5d window)
     - **cross 3way: bb ∩ chip ∩ broker (5d window)** — 主要 hypothesis
   - 三維 robustness 判定（feedback_backtest_strategy_filtering）
     - 跨股 ≥ 5 + 跨月 ≥ 2 + win_rate ≥ 65% = actionable
     - 50-65% = watch-only
     - ≤ 35% = 反向訊號 skip 清單

### 阻塞：FinMind hourly quota 已用盡

`/api/v4/data` 任何 dataset 都回 `402 - Requests reach the upper limit`。

**原因**：第一次嘗試的 DataLoader 全市場 fetch 在第二天就觸發內部反覆 TaiwanStockInfo 查詢 + 重新 login 的 bug、單日累積 200+ 內部 call、第二天還沒完成就把 6000/hr 配額用光。

**復原方式**：等下一小時 quota 重置（FinMind sponsor tier 每小時 6000 calls reset）。

### 待執行（IP 解封 + quota 恢復後）

Fetcher 已加上保守 pacing（concurrency=3、per-call sleep 0.5s、between-day sleep 10s）+ resume 機制（parquet 已 cache 的日期跳過）+ 403 hard-abort（自動停 + 不再硬撞）：

```bash
# 1. 抓 broker_trades (402 候選 × 50 日 = 20100 calls、concurrency=3 預計 ~3 小時)
python3 -m scripts.xiaoge.fetch_broker_trades \
    --start 2026-04-01 --end 2026-06-12 \
    --universe-start 2026-05-01 --universe-end 2026-06-12 \
    --concurrency 3 --per-call-sleep 0.5 --between-day-sleep 10

# 2. 建關鍵分點池 (用 4 月資料、避免 lookahead)
python3 -m scripts.xiaoge.build_key_broker_pool --pool-end 2026-04-30

# 3. backtest
python3 -m scripts.xiaoge.backtest_phase3c
```

**抓取預估**：402 ticker × 50 day = 20100 calls。concurrency=3、per_call_sleep=0.5s、
between_day_sleep=10s → 每日 ~(402 × 0.5 / 3) = 67s + 10s sleep ≈ 77s/day。
50 day × 77s = 64 分鐘。Sponsor 6000/hr 配額：50 day × 402 = 20100 / 60 min = 335/min = 20100/hr。**會超出 6000/hr**！

**修正策略**：跨小時段執行 — fetcher 內建 resume，可分批跑：
```bash
# 先抓前 15 日（~6000 calls 1 小時內）
python3 -m scripts.xiaoge.fetch_broker_trades --start 2026-04-01 --end 2026-04-21 ...
# 過一小時再跑下個 batch
python3 -m scripts.xiaoge.fetch_broker_trades --start 2026-04-22 --end 2026-05-12 ...
# ... 再下個 batch
python3 -m scripts.xiaoge.fetch_broker_trades --start 2026-05-13 --end 2026-06-12 ...
```
或縮 ticker universe（例如只取 bb_squeeze 觸發過的 67 檔）= 3350 calls = 1 小時搞定。

## 設計決策摘要

### Universe scope (330 vs 全市場 2300)

老師原本要求「對每檔股票拉 800–2000 天分點買賣超歷史」(detector_spec.md §4)、但
1. FinMind sponsor tier 6000 calls/hr、全市場 2300 ticker × 50 day = 115K calls = 19 小時純抓資料
2. 實際只關心 cross detector candidate ticker → 縮到 bb_squeeze ∪ chip_v2 觸發過的 ~330 檔

**Trade-off**：universe bias — cross-detector 候選池本身是先驗篩過的（強勢股集中），會讓 pool 的「低買」signature 偏向強勢股的低點。對 cross 驗證 ok，獨立 detector 4 結論可能 over-fit。

### 50 張閾值（detector 進場）vs 10 張（pool 計入）

- pool 用 10 張寬鬆收集分點 signature（避免雜訊但留住中小型股的池）
- 訊號用 50 張嚴格（老師「量做很大」原話、避免散戶級小量誤判）

### MA20 上揚 + 站上 MA20（多頭趨勢 filter）

跟 detector 2 v2 一致、保持戰術一致性。短期 detector 4 訊號要過 MA20 雙重 filter 才當多頭。

### C6 不依賴 BB upper

detector 4 本身不用 BB，所以原 `leave_upper_band` 出場規則不適用。改用 MA10 trail 是按使用者 `feedback_exit_rules_v3` 鎖定的 production default。

## 風險與盲區

1. **Pool window 太短**：4 月只有 ~22 個交易日、判定「持續低買高賣」的統計力有限。老師原話要 800-2000 天歷史。
2. **不排除外資 / 自營分點**：老師說「排除外資、self-loop」(spec §4)、但 FinMind 分點 ID 跟「外資/自營」標記沒有顯式對應、用「分數自然篩」代替顯式排除。
3. **庫藏股分點權重 ×2 未實作**：spec §4 提到「庫藏股分點 = 粉紅色標記 = 權重 ×2」、目前沒做、需要額外 dataset。
4. **訊號分級 A+/A/B 未實作**：spec §4 的 Phase C 分級（殺低大買 = A+ etc.）、目前只做 binary boolean。

## 後續

- quota 恢復 → 跑完三步驟、把實際數字寫進這份 doc
- 若 detector 4 結果 actionable → 加入 daily scanner、升 cross_xiaoge_swing 三維 A+ 等級
- 若是反向訊號（win_rate ≤ 35%）→ 寫入 skip 清單而不是強推
- 若樣本不足 → 等更長期間（3-6 個月）broker_trades 再評估
