# Phase 3b — FinMind 資料源 audit

> Date: 2026-06-14
> 目的：盤點 FinMind 可用 dataset、看哪些能對應到老師教的「主力 / 散戶 / 集保戶 / 分點」四軸

---

## 可用 Datasets (實測 2026-06-14、Sponsor tier)

### 1. `TaiwanStockHoldingSharesPer` — 大戶/散戶分級持股 ✅

實測 `data_id=2330, 2026-05-01~06-10`：

- **粒度：週**（每週一筆 snapshot、共 5 個日期：5/8, 5/15, 5/22, 5/29, 6/5）
- **欄位：** `date / stock_id / HoldingSharesLevel / people / percent / unit`
- **HoldingSharesLevel 15 級**（張 = 股 / 1000）：
  - `1-999` shares（< 1 張）→ 純散戶
  - `1,000-5,000`、`5,001-10,000`、`10,001-15,000`、`15,001-20,000`、`20,001-30,000`、`30,001-40,000`、`40,001-50,000`
  - `50,001-100,000`（50-100 張）、`100,001-200,000`（100-200 張）
  - `200,001-400,000`、`400,001-600,000`、`600,001-800,000`、`800,001-1,000,000`
  - **`more than 1,000,001`**（> 1000 張）→ 大戶（含主力）
  - `total` 跟 `差異數調整（說明4）` 是 metadata

範例（2330 在 2026-05-08）：
- 散戶 (1-999): 2,046,777 人 / 0.94% 持股
- 大戶 (>1000 張): 1,504 人 / **85.58% 持股**
- 集保戶總數: 2,553,783 人

### 2. `TaiwanStockTradingDailyReport` — 分點日報 ✅

實測 `data_id=2330, date=2026-06-10`：

- **粒度：日**
- **欄位：** `date / stock_id / securities_trader / securities_trader_id / price / buy / sell`
- 一檔股票一日 ~7,508 列（broker × price points）
- 需要 aggregate by `securities_trader_id` 拿到「每個分點當日 net buy/sell」

範例（2330 在 2026-06-10）：
- TOP 買: 永豐匯立 (786,959 股 = ~787 張)、國泰敦南 (761 張)、永豐金 (527 張)
- TOP 賣: 港麥格理 (-4,248 張)、凱基台北 (-3,166 張)、台灣摩根 (-2,844 張)

### 3. `TaiwanStockShareholding` — 僑外投資持股（不是集保戶）⚠️

實測：欄位是 `ForeignInvestmentShares / ForeignInvestmentRemainRatio` 等、**只跟外資相關、不是集保戶數**。
名字容易誤導、本 audit 已校正。

### 4. 不存在的 dataset
- `TaiwanStockShareholdingClassPer` → 422 (dataset 不存在)
- `TaiwanStockShareholdingThousandsChart` → 422 (dataset 不存在)

---

## 對應老師三軸

| 老師說 | 可用資料 | 粒度 | 來源 |
|---|---|---|---|
| 主力買超（前 15 名買賣超）| `TaiwanStockTradingDailyReport` + 自己 aggregate | 日 | FinMind |
| 散戶賣超（< 100 張持股 / 1-999 shares）| `TaiwanStockHoldingSharesPer` 級距 `1-999` 比例變化 | **週** | FinMind |
| 集保戶數下降 | `TaiwanStockHoldingSharesPer` total people 變化 | **週** | FinMind |
| 大戶買超（> 1000 張）| `TaiwanStockHoldingSharesPer` 級距 `more than 1,000,001` 比例變化 | **週** | FinMind |

**已不再缺資料**。

---

## 實作優先級

### 高（detector 2 v2 — Phase 3b 主菜）
- 用 `TaiwanStockHoldingSharesPer` 補進 detector 2 的「散戶賣 + 集保戶降 + 大戶買」
- 粒度週、daily detector 用「最近一週 snapshot」對齊

### 中（detector 4 — 後續）
- `TaiwanStockTradingDailyReport` 抓 + cache + aggregate to broker-net
- 為每檔股票建立「關鍵分點池」（持續低買高賣的分點）
- 每日 scanner 比對池內分點今日 buy/sell

### 低（已用 DB 機構代理）
- DB `main_force_5d` 已涵蓋「主力買超」維度、Phase 3a 已驗證 +1.65% / 47% win

---

## 既有 FinMind client

位置：`/Users/howard/Repository/stock-analysis-system/clients/finmind_client.py`

關鍵函數：
- `get_data(dataset, stock_id, start_date, end_date)` — 通用、自帶 NDJSON cache
- `get_broker_buysell(date_str, token)` — 全市場 broker 聚合
- `get_broker_trading_daily_report(date_str, token, stock_id=None)` — 分點細節

**沿用既有 client、不重造**。

---

## Rate limit 規劃

- Sponsor 600 req/hour
- detector 2 v2：抓 `TaiwanStockHoldingSharesPer` 全市場 × 5 週 → 約 11,500 列、可一次 API call (不指定 data_id) 取全市場
- detector 4：抓 `TaiwanStockTradingDailyReport` × 30 日 → 30 次 API call

---

## 待 user 拍板

1. ⏳ detector 4 的「關鍵分點池」自動建立 vs 人工驗證？
2. ⏳ 集保戶數週粒度 → daily detector 是否接受 staleness（最舊 5 天）？
3. ⏳ 是否要為了 detector 4 跑全市場 30 日的分點 batch（500MB+）？
