# Frank Detector 實作狀態
Updated: 2026-07-06

## ✅ 已實作（scripts/frank/detectors.py、含 self-check）

| Detector | 函式 | 資料需求 | 掛載點 |
|---|---|---|---|
| 戰法二進場（中軌分歧）| `frank_2_entry` | daily | backtest / advisor |
| 戰法分數（城牆/頭高/布頂/量）| `frank_score` | daily | 排序 |
| 分層出場（守5日/月線層）| `frank_exit_layer` | daily | backtest / advisor |
| 飆股 3・5 法則 | `frank_hot_stock_3_5_rule` | daily | advisor 持倉警示 |
| 日出線 | `frank_sunrise_line` | daily OHLC | advisor 持倉警示 |
| 日落線 | `frank_sunset_line` | daily OHLC | advisor 持倉警示 |
| KD 背離（近2波）| `frank_kd_divergence` | closes + K 值 | 待掛（需 KD 欄位）|
| 頸線 2 步驟 | `frank_daily_neckline` | daily OHLC | 可掛 advisor |
| 底部紅三兵 | `frank_bottom_3_soldiers` | daily + vol_ratio | advisor 持倉警示 |
| 券資比趨勢 | `frank_credit_ratio_trend` | 融資券序列 | 待掛（margin 欄位）|
| 鎖漲停隔日 SOP | `frank_lock_limit_up_next_day` | 昨收+今開+今低 | 盤中 monitor |
| 5m 戰法一 | `frank_1_5m` | 5m closes | stock_minute_kbar / 盤中 |
| 開盤 5 分 K 關鍵價 | `frank_open_5m_key_level` | 開盤前2根5m+昨高 | 盤中 monitor |
| 炸板 2m 檢查 | `frank_pop_check_2m` | 2m closes | 盤中 monitor |
| 緩漲緩跌警戒 | `frank_slow_move_alert` | 開盤%+分鐘+緩漲跌flag | 盤中 monitor |
| 五檔假掛單 | `frank_5tick_fake_order` | 即時五檔 | 盤中 monitor（需五檔源）|

## 📋 純人工 / 外部資料（spec-only、不程式化）

| Detector | 原因 |
|---|---|
| 常勝分點查找 | 半自動、已有 broker_tracker.py 覆蓋 |
| 權證三件組（識別大戶/樂透/進階）| 需權證發行/流通資料源、未接 |
| 台指期系列 + 對鎖 | 期貨帳戶/大數據方案、人工 |
| 模擬單試單 | 行為訓練、非訊號 |
| 假急殺修 KD（indicator_reset_shakeout）| 需盤中小時K+情境判讀、留人工（spec 有完整 SOP）|

## 回測 / 工具鏈

| 檔案 | 用途 |
|---|---|
| `scripts/frank/detectors.py` | detector 純函式全集 + demo self-check |
| `scripts/frank/frank_daily_backtest.py` | (e)(f) 回測 + 跨年 regime 驗證 |
| `scripts/frank/frank_regime_gate_test.py` | 加權 20MA gate 測試 |
| `scripts/frank/frank_portfolio_sim.py` | v1 portfolio（MAX_CHG 環境變數）|
| `scripts/frank/frank_portfolio_sim_v2.py` | v2 乾淨版（timeline+score）⭐ 部署版 |
| `scripts/frank/frank_portfolio_sim_v3.py` | v3 +籌碼 gate（結論：不掛）|
| `scripts/frank/frank_advisor.py` | 每日尾盤：復盤+持倉檢查+下週訊號 |
| `scripts/frank/replay_broker_statement*.py` | 對帳單復盤 v1/v2 |
