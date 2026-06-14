# Entry Mode 比較：next_day_open vs close_session_disciplined

**日期範圍：** 2026-05-19 ~ 2026-06-05（分鐘 K 棒有資料的最早日期）  
**產出日期：** 2026-06-08  
**程式：** `scripts/zhuli/backtest.py --entry-mode close_session_disciplined`

---

## 方法論

### `next_day_open`（現有預設）
- Entry = 訊號日 D+1 開盤價
- 沒有任何過濾條件

### `close_session_disciplined`（新模式，對應 user 實際紀律）
依 memory `feedback_close_session_only_entry.md` / `feedback_short_swing_entry_discipline.md` 實作：

| Filter | 條件 | 若觸發 |
|--------|------|--------|
| 1. 跳空 | D+1 open vs D close gap ≥ +5% | Skip |
| 2. 前 5 分 K 暴衝 | D+1 首 5 根 K 收盤 vs D+1 open ≥ +5% | Skip |
| 3. 進場時間窗口 | 只用 13:00–13:25 最後一根 K 的 close | 作為進場價 |
| 4. 無分鐘資料 | ticker 在 `stock_minute_kbar` 無當日資料 | Skip |

Exit 邏輯與 `next_day_open` 完全相同（收盤跌破 stop_loss → 隔日開盤出；max_hold 到期）。

> **注意：** G 隔日沖（overnight_swing）與 F 當沖（intraday）為 `signal_day_close` 模式，屬於不同策略設計，不受此 override 影響，結果兩模式完全相同。

---

## ⚠️ 分鐘資料覆蓋度限制

| 日期 | 有分鐘資料的 ticker 數 |
|------|----------------------|
| 2026-05-19 ~ 2026-06-03 | 15 支（人工 watchlist） |
| 2026-06-04 ~ 2026-06-05 | 332 支（全市場） |

**重大影響：** 在 2026-05-19 ~ 2026-06-03 期間，大多數 signal（top-5 rank 過後）因對應 ticker 不在那 15 支中，全部被歸類為 `skip_no_minute_data`。導致 `close_session_disciplined` 模式在這 12 個交易日的有效樣本數極低（每個 scanner 僅剩 1~4 筆交易）。

**結論：目前分鐘資料不足以做有統計意義的 entry mode 比較。** 需要等 `stock_minute_kbar` 回填至少 2026-01-01 後才能得出可信的結論。

---

## 比較結果（2026-05-19 ~ 2026-06-05）

> **警告：** CSD 欄位樣本數極小（多數 scanner 僅 1~4 筆），不具統計意義。

| Scanner | 訊號數（top-5後）| NDO 交易數 | NDO Hit% | NDO EV% | CSD 交易數 | CSD Hit% | CSD EV% | 被跳過 |
|---------|----------------|-----------|---------|---------|-----------|---------|---------|--------|
| H 窒息量 | 70 | 65 | 41.5% | +2.69% | 3 | 33.3% | +0.56% | 62 |
| A 大波段 | 56 | 56 | 50.0% | +3.21% | 1 | 100% | +17.80% | 55 |
| C 反轉形態 | 70 | 61 | 24.6% | -2.37% | 4 | 0% | -1.67% | 57 |
| B 旗形 | 70 | 65 | 38.5% | -0.16% | 2 | 100% | +13.33% | 63 |
| J 投信首買 | 8 | 8 | 50.0% | +1.71% | 1 | 0% | -4.34% | 7 |
| I 投信跟單 | 5 | 5 | 60.0% | +12.75% | 0 | — | — | 5 |
| G 隔日沖 | 17 | 17 | 29.4% | +0.96% | 17 | 29.4% | +0.96% | 0 |
| F 當沖 | 70 | 65 | 66.2% | +1.65% | 65 | 66.2% | +1.65% | 0 |

### Skip 原因分析（2026-05-19 ~ 2026-06-05，全 scanner 合計）

| 原因 | 數量 |
|------|------|
| `no_minute_data`（ticker 無分鐘 K 棒） | 208 |
| `gap_5pct`（D+1 跳空 ≥ +5%） | 50 |
| `first5min_surge`（前 5 分 K 暴衝 ≥ +5%） | 2 |
| `no_closing_window_bar` | 0 |

**跳空過濾器觸發率：** 50 / (50+208+2) = 19.2%（在有分鐘資料的 signal 中佔比更高）

---

## 2026-06-04/05 完整覆蓋日驗證（332 tickers）

| Scanner | NDO 交易數 | NDO Hit% | CSD 交易數 | CSD Hit% | 被跳過 |
|---------|-----------|---------|-----------|---------|--------|
| H 窒息量 | 5 | 60.0% | 1 | 0% | 4 (2×first5min + 2×no_data) |
| A 大波段 | 5 | 20.0% | 0 | — | 5 (all no_data) |
| C 反轉形態 | 5 | 40.0% | 0 | — | 5 (all no_data) |
| B 旗形 | 5 | 0% | 1 | 100% | 4 (no_data) |
| G 隔日沖 | 2 | 0% | 2 | 0% | 0 |
| F 當沖 | 5 | 0% | 5 | 0% | 0 |

---

## 結論與建議

**統計可信度：過低，目前無法得出有效結論。**

理由：
1. 分鐘 K 棒資料只回到 2026-05-19，前 12 天只有 15 支 ticker，導致 CSD 模式每個 scanner 僅有 1~4 筆有效交易，遠低於最小統計樣本（30+ 筆）。
2. 2026-06-04/05 只有 2 個完整覆蓋日，交易數更少。
3. NDO 模式的 May 19 ~ Jun 5 樣本（65 筆）雖然數字像樣，但也只是 2.5 週資料，同樣偏少。

**跳空過濾器（Filter 1）的觀察：** 在 May 19 ~ Jun 5 有分鐘資料的交易中，有 50 筆被跳空 ≥ 5% 過濾掉，約佔 19%。這與 memory 記錄的「漲停隔日跳空是高風險情境」一致。

**建議後續動作：**
1. **回填分鐘 K 棒** 至 2026-01-01（或至少 2026-03-01），讓 `close_session_disciplined` 能對照 NDO 的完整 YTD 樣本（1000+ 筆）
2. 回填後重跑：`python scripts/zhuli/backtest.py --all --start 2026-01-01 --end 2026-06-07 --entry-mode close_session_disciplined`
3. 屆時才能分析：尾盤進場 + 跳空過濾是否真的提高 win rate 或降低 max drawdown

---

## 技術實作說明

**新增函式：**
- `_load_minute_bars()` — 載入 `~/.four_seasons/data.sqlite` 的 `stock_minute_kbar`
- `_check_close_session_entry()` — 對單日分鐘資料執行 filter 2/3/4，回傳 (entry_price, reason)
- `_get_trade_outcome()` — 新增 `close_session_disciplined` 分支，接受 `minute_bars`、`prev_close`、`skip_stats`

**新增 CLI 旗標：**
```
python scripts/zhuli/backtest.py --all --entry-mode close_session_disciplined \
  --start 2026-01-01 --end 2026-06-07 \
  --out data/analysis/zhuli/backtest_csd_ytd
```

**G/F scanner 不受 override 影響**（`signal_day_close` 模式保持不變）。

**相容性：** 不影響現有 `next_day_open` 預設行為。
