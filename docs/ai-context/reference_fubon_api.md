---
name: Fubon API Reference
description: Fubon Neo API (fbs.com.tw) 的結構、分價量表 endpoint、認證方式與 rate limit
type: reference
originSessionId: d7e91495-e51b-49b5-ad3a-99d9db94b659
---
## 文件來源
https://www.fbs.com.tw/TradeAPI/llms-full.txt

## Client 位置
`/Users/howard/Repository/stock-analysis-system/clients/fubon_client.py`

## Base URL 結構
- Intraday:   `/intraday/*`
- Snapshot:   `/snapshot/*`
- Historical: `/historical/*`
- Technical:  `/technical/*`

## 關鍵 Endpoint：分價量表
`GET /intraday/volumes/{symbol}`

Response 欄位：
- `price`: 成交價格
- `volume`: 該價位累計成交量
- `volumeAtBid`: 買方成交量
- `volumeAtAsk`: 賣方成交量

用途：即時 volume profile，可計算 overhead density、supply vacuum

限制：**只有今日即時資料，無法回測歷史**（/historical/ 路徑下無 volumes endpoint）

## Rate Limits
- Intraday:   300 req/min
- Snapshot:   300 req/min
- Historical: 60 req/min
- WebSocket:  200 symbols/connection, max 5 connections

## 認證方式
A. API Key login (>= v2.2.7, 推薦):
   `sdk.apikey_login(FUBON_ACCOUNT_ID, FUBON_API_KEY, FUBON_CERT_PATH, FUBON_CERT_PW)`

B. Password login:
   `sdk.login(FUBON_ACCOUNT_ID, FUBON_PASSWORD, FUBON_CERT_PATH, FUBON_CERT_PW)`

## 環境變數
- `FUBON_PID` / `FUBON_ACCOUNT_ID`
- `FUBON_API_KEY`
- `FUBON_PWD` / `FUBON_PASSWORD`
- `FUBON_CREDENTIAL_FILE` / `FUBON_CERT_PATH`
- `FUBON_CREDENTIAL_PWD` / `FUBON_CERT_PW`

## 現有 FubonClient 方法
- `get_price(stock_id, start, end)` → 日K OHLCV
- `get_realtime_snapshot(stock_id)` → 即時報價
- `load_kbar(stock_id, days)` → 1分K
- `load_60m_kbar(stock_id, days)` → 60分K
- `load_kbar_tf(stock_id, timeframe, days)` → 任意 timeframe 歷史K
- `fetch_intraday_candles(symbols, timeframes)` → 今日分K（非同步）
- `fetch_macd_dif(symbols, timeframes)` → MACD DIF（非同步）
- `get_institutional(stock_id, start, end)` → 法人買賣超
- `get_snapshot_quotes(market)` → 整市場快照
- **缺少**: `get_intraday_volumes(symbol)` → 分價量表（待實作）
