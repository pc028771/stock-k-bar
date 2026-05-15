---
name: FinMind API Reference
description: FinMind API 結構、所有 dataset 名稱、認證方式與 rate limit（Sponsor tier）
type: reference
originSessionId: d7e91495-e51b-49b5-ad3a-99d9db94b659
---
## 文件來源
https://finmind.github.io/llms-full.txt
（每 session 更新一次）

## 用戶權限
**Sponsor tier** — 可存取所有 Backer/Sponsor 限定資料集

## Base URL
`https://api.finmindtrade.com/api/v4`

## 認證
Header: `Authorization: Bearer {token}`
Env var: `FINMIND_TOKEN`

## Rate Limits
- Sponsor: 600 req/hour
- 超過回傳 HTTP 402

## 核心 Endpoints
- `GET /data` — 取資料（params: dataset, data_id, start_date, end_date）
- `GET /datalist` — 列出可用 data_id
- `POST /login` — 取 token

## 重要 Datasets

### 盤中 / 逐筆
- `TaiwanStockKBar` — 分K（Sponsor）
- `TaiwanStockPriceTick` — 逐筆成交（Sponsor）— **可按價格聚合成分價量表**
- `TaiwanStockStatisticsOfOrderBookAndTrade` — 每5秒委託統計（Free）

### 日K / 技術
- `TaiwanStockPrice` — 日K OHLCV
- `TaiwanStockPriceAdj` — 還原日K

### 籌碼
- `TaiwanStockInstitutionalInvestorsBuySell` — 法人買賣超
- `TaiwanStockMarginPurchaseShortSale` — 融資融券

### 分價量表
**文件中無明確 dataset 名稱。** 用戶說 FinMind 晚間有當日分價量表。
推測來源：`TaiwanStockPriceTick` 逐筆資料按價格聚合。
⚠️ 需確認實際 dataset 名稱。

## 現有 finmind_client 位置
`/Users/howard/Repository/stock-analysis-system/clients/finmind_client.py`
