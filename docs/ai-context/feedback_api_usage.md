---
name: API 呼叫規範
description: 禁止直接用 curl 打 FinMind API，必須走 stock-analysis-system 的 client（含 throttle）
type: feedback
originSessionId: 459253f0-8498-403f-8f43-26625245505a
---
**禁止直接用 curl 或 requests 呼叫 FinMind API。**

必須使用 `/Users/howard/Repository/stock-analysis-system/clients/finmind_client.py` 的函式，例如 `get_price()`、`get_stock_name()`、`get_institutional()` 等，這些函式內建 rate limiter / throttle。

同樣地，Fubon API 必須透過 `clients/fubon_client.py` 的 `FubonClient`，不可直接呼叫 SDK 底層 HTTP。

**Why:** 直接走 HTTP 會繞過 throttle，造成 quota 超用或 429 錯誤。
**How to apply:** 每次需要金融資料時，一律在 `/Users/howard/Repository/stock-analysis-system` 目錄下用 Python 呼叫對應的 client，設好必要的環境變數後執行。
