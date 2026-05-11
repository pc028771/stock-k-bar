# 台股放空可交易性處理（Task 20）

本文件處理台股放空的實務限制，明確區分課程涵蓋範圍與台股實務規範，並以實際 FinMind API 查詢結果為依據說明資料可用性。

---

## 重要聲明：課程語意與台股實務的邊界

本文件以下「台股實務限制」標記的所有內容，均為**【課程未涵蓋】**。

課程（K線力量判斷入門）僅教導以 K 線訊號判斷放空進場與回補的策略邏輯，不涉及任何台股交易制度、券商規定或監管機制。本文件中凡屬台股實務規範的章節，均以「【課程未涵蓋】」明確標示，不可將這些條件混入課程框架的訊號判斷邏輯。

---

## 1. 課程語意範圍（課程明確涵蓋）

### 1.1 放空進場邏輯

課程 `strategy-indicators.md` §8 L163 說明放空必須同時確認：

- **弱勢**：中期趨勢偏空（收盤低於季線、季線下彎）
- **跌破**：收盤跌破關鍵價（頸線、前波低點），隔日收盤確認
- **反彈遇壓**：跌破後反彈至關鍵價附近，收盤站不回
- **買盤不繼**：收黑K，實體偏大，收盤位置偏低

課程同時強調：

> 「放空邏輯與多方攻擊**不是簡單鏡像**，需確認弱勢、跌破、反彈遇壓、買盤不繼。」

### 1.2 回補訊號

課程 `strategy-indicators.md` §8 L164：

> 「回補可用**趨勢改變**、**跌勢攻擊消失**、**假跌破收回**或**關鍵K線確認**。」

### 1.3 課程框架內可執行的規則

| 規則 | 課程依據 |
| --- | --- |
| 進場時機：收盤訊號確認後隔日開盤進場 | `strategy-indicators.md` §7：「訊號通常先以收盤成立，再用隔日開盤進場」 |
| 回補：假跌破收回觸發即回補 | `strategy-indicators.md` §8 L164 `cover_signal = false_breakdown_reclaim or ...` |
| 所有跌破與站回以**收盤**為準，不以盤中價格判斷 | `CLAUDE.md` 課程框架範圍點 1 |
| **停損**：課程沒有明確說明放空停損位置 | `short_strategy_spec.md` §4「課程未涵蓋、不可自行補完的項目」 |

---

## 2. 台股放空實務限制（課程未涵蓋）

> 以下各節**【課程未涵蓋】**。內容為台股交易制度與監管規範的實務說明，非課程教學內容，不可混入課程框架的訊號判斷邏輯。

### 2.1 券源限制【課程未涵蓋】

台股放空有兩種機制，可用性和成本結構不同：

| 機制 | 說明 | 可用限制 |
| --- | --- | --- |
| **融券放空**（信用交易） | 向券商借券，透過信用帳戶賣出 | 需開立信用帳戶；個股需有融券資格並有可用額度；注意股、處置股通常停止融券 |
| **借券放空**（有價證券借貸） | 透過台灣證券交易所有價證券借貸系統向出借方借券 | 費率隨供需浮動（年化約 0.01%~30%+）；不保證隨時借得到；需單獨申請 |

**融券資格限制實務**：

- 上市股票需同時在 TSE 有融資融券業務資格，上櫃股票需在 TPEx 登記。
- 個股融券使用率接近上限（`ShortSaleLimit`）時，不接受新的融券委託。
- 注意股（公告為注意有價證券）停止融券；處置股停止融券且限制下單次數。

### 2.2 強制回補日【課程未涵蓋】

台股融券有以下法規規定的強制回補時機：

| 情境 | 說明 | 時間點 |
| --- | --- | --- |
| **除息強制回補** | 現金股利除息前，融券持有人需強制回補 | 通常為除息基準日前 6 個交易日停止融券，並於基準日前完成回補 |
| **除權強制回補** | 股票股利除權前，同上 | 同上 |
| **股東會強制回補** | 股東會停過戶基準日前，融券需強制回補 | 通常為停過戶開始日前 6 個交易日 |
| **減資強制回補** | 公司辦理減資時，需強制回補 | 依公告時程 |

**實務注意**：強制回補日通常落在除息（除權）交易日的**前 5～6 個交易日**開始停止融券，並要求持有者在**最後停止融券交易日**前完成回補。

FinMind `TaiwanStockMarginShortSaleSuspension` 資料集記錄各股暫停融券賣出的日期區間與原因，欄位如下（以台積電 2330 為例）：

```
stock_id | date       | end_date   | reason
2330     | 2024-03-12 | 2024-03-15 | 除息
2330     | 2024-03-27 | 2024-04-01 | 股東常會
2330     | 2024-06-06 | 2024-06-12 | 除息
2330     | 2024-09-06 | 2024-09-11 | 除息
2330     | 2024-12-06 | 2024-12-11 | 除息
```

`date` 為暫停融券賣出的首日，`end_date` 為最後停止日（含）。實務上在 `date` 前即需回補，放空策略應在 `date` 前至少 1 個交易日完成回補或避免在 `date - N 日` 前進場。

### 2.3 漲跌停無法平倉【課程未涵蓋】

台股有 ±10% 漲跌停限制，對放空策略有以下直接風險：

| 情境 | 影響 |
| --- | --- |
| **放空後個股漲停** | 漲停板無賣方對手，無法以市價買回，停損無法執行；若連續漲停，損失持續累積 |
| **融券軋空** | 融券使用率過高的股票，遇到利多消息或大資金拉抬，放空者集體回補形成正回饋，價格急速上漲且常伴隨漲停鎖死 |
| **跌停後無法平倉（對多方）** | 跌停板無買方對手，若已持有放空部位想獲利回補，反而無法成交 |

**漲跌停機率與放空風險的關係**：個股最近交易日出現過漲停，代表近期多方力道強、軋空潛在風險高，為最直接的可行過濾條件。

### 2.4 FinMind 資料可用性確認

以下為 Task 20 實際查詢後確認的 FinMind 資料集狀態：

#### 2.4.1 `TaiwanStockMarginPurchaseShortSale`（融資融券）

- **可用**：Free tier，需指定 `data_id`
- **實際欄位**（查詢確認）：

| 欄位 | 說明 |
| --- | --- |
| `date` | 交易日 |
| `stock_id` | 股票代碼 |
| `ShortSaleTodayBalance` | 融券今日餘額（張） |
| `ShortSaleYesterdayBalance` | 融券昨日餘額（張） |
| `ShortSaleBuy` | 融券回補（張） |
| `ShortSaleSell` | 融券賣出（張） |
| `ShortSaleLimit` | 融券限額（股，非張） |
| `ShortSaleCashRepayment` | 融券現金償還 |
| `MarginPurchaseTodayBalance` | 融資今日餘額（張） |
| `MarginPurchaseBuy` | 融資買進（張） |
| `MarginPurchaseSell` | 融資賣出（張） |
| `MarginPurchaseLimit` | 融資限額 |
| `OffsetLoanAndShort` | 資券相抵 |
| `Note` | 備註 |

- **可計算的衍生欄位**：
  - 融券使用率 = `ShortSaleTodayBalance * 1000 / ShortSaleLimit`（注意 `TodayBalance` 單位是張，`Limit` 單位是股，需乘以 1000）

#### 2.4.2 `TaiwanDailyShortSaleBalances`（信用額度總量管制餘額）

- **可用**：Free tier，需指定 `data_id`
- **實際欄位**（查詢確認）：

| 欄位 | 說明 |
| --- | --- |
| `stock_id` | 股票代碼 |
| `date` | 交易日 |
| `MarginShortSalesPreviousDayBalance` | 信用融券前日餘額（股） |
| `MarginShortSalesShortSales` | 信用融券賣出（股） |
| `MarginShortSalesShortCovering` | 信用融券回補（股） |
| `MarginShortSalesStockRedemption` | 信用融券現券償還（股） |
| `MarginShortSalesCurrentDayBalance` | 信用融券今日餘額（股） |
| `MarginShortSalesQuota` | 信用融券額度（股） |
| `SBLShortSalesPreviousDayBalance` | 借券賣出前日餘額（股） |
| `SBLShortSalesShortSales` | 借券賣出（股） |
| `SBLShortSalesReturns` | 借券還券（股） |
| `SBLShortSalesAdjustments` | 借券調整（股） |
| `SBLShortSalesCurrentDayBalance` | 借券賣出今日餘額（股） |
| `SBLShortSalesQuota` | 借券賣出額度（股） |
| `SBLShortSalesShortCovering` | 借券回補（股） |

- **說明**：此資料集整合了「信用融券」與「借券賣出（SBL, Securities Borrowing and Lending）」兩種放空機制的每日餘額，比 `TaiwanStockMarginPurchaseShortSale` 更完整，直接以股為單位。

#### 2.4.3 `TaiwanStockSecuritiesLending`（借券成交）

- **可用**：Free tier，需指定 `data_id`
- **實際欄位**（查詢確認）：

| 欄位 | 說明 |
| --- | --- |
| `date` | 交易日 |
| `stock_id` | 股票代碼 |
| `transaction_type` | 交易方式（`議借`、`競價`） |
| `volume` | 借券成交量（股） |
| `fee_rate` | 借券費率（年化 %） |
| `close` | 當日收盤價 |
| `original_return_date` | 原始到期歸還日 |
| `original_lending_period` | 借券期間（天） |

- **說明**：此資料集記錄每日**成交的借券筆數與費率**，但為個別借券交易記錄，非累計餘額。費率可用來評估借券成本，但每筆費率不同，需取當日加權平均。

#### 2.4.4 `TaiwanStockDividend`（股利政策）

- **可用**：Free tier，需指定 `data_id`
- **實際欄位**（查詢確認，含除息相關欄位）：

| 欄位 | 說明 |
| --- | --- |
| `date` | 公告/股東會日期 |
| `stock_id` | 股票代碼 |
| `year` | 配息年度（如「113年第2季」） |
| `CashEarningsDistribution` | 現金股利（元） |
| `CashExDividendTradingDate` | **現金除息交易日**（YYYY-MM-DD） |
| `CashDividendPaymentDate` | 現金股利發放日 |
| `StockEarningsDistribution` | 股票股利（元） |
| `StockExDividendTradingDate` | 股票除權交易日 |
| `AnnouncementDate` | 董事會/股東會公告日 |
| `AnnouncementTime` | 公告時間 |

- **重要**：`CashExDividendTradingDate` 即為除息交易日本身（當天股價已調整），融券的強制回補期間從此日前數個交易日開始，需搭配 `TaiwanStockMarginShortSaleSuspension` 確認精確停止日期。

#### 2.4.5 `TaiwanStockDividendResult`（除權除息結果）

- **可用**：Free tier，需指定 `data_id`
- **實際欄位**（查詢確認）：

| 欄位 | 說明 |
| --- | --- |
| `date` | 除權息交易日 |
| `stock_id` | 股票代碼 |
| `before_price` | 除前收盤價 |
| `after_price` | 除後參考價 |
| `stock_and_cache_dividend` | 股利總額 |
| `stock_or_cache_dividend` | 類型（`息`/`權`/`息權`） |
| `max_price` | 當日漲停板 |
| `min_price` | 當日跌停板 |
| `open_price` | 除權息日開盤價 |
| `reference_price` | 除權息參考價 |

#### 2.4.6 `TaiwanStockMarginShortSaleSuspension`（暫停融券賣出）

- **可用**：Free tier，需指定 `data_id`
- **實際欄位**（查詢確認）：

| 欄位 | 說明 |
| --- | --- |
| `stock_id` | 股票代碼 |
| `date` | 暫停融券賣出開始日 |
| `end_date` | 暫停融券賣出結束日 |
| `reason` | 原因（`除息`、`除權`、`股東常會`、`減資`等） |

- **說明**：此資料集直接記錄每次暫停融券的日期區間與原因，是判斷強制回補期間最直接的依據。

#### 2.4.7 FinMind 未提供的資料（資料缺口）

| 項目 | 說明 |
| --- | --- |
| **借券即時可用餘額** | FinMind 的 `TaiwanStockSecuritiesLending` 記錄**已成交**的借券，不提供「目前可借」的即時餘額。實際可用餘額需透過台灣集中保管結算所（TDCC）或各券商系統取得，無公開免費日頻 API |
| **借券費率即時報價** | `TaiwanStockSecuritiesLending` 記錄的是**已成交**費率（事後），不是報價費率。借券前的議價費率無法從 FinMind 事先取得 |
| **借券出借意願/餘量** | 哪些機構或個人願意出借多少股，FinMind 無此資料 |
| **信用帳戶限制條件** | 各券商自行設定的信用帳戶門檻（如：開戶未滿 3 個月、資產不足等），FinMind 無此資料 |

---

## 3. 可交易性過濾建議

> 以下過濾邏輯均為**【課程未涵蓋】**的台股實務補充，不可混入 `short_entry` 的課程訊號判斷。

### 3.1 必要過濾（直接影響可執行性）

若不過濾以下條件，放空訂單可能直接被券商拒絕或持倉強制平倉：

| 過濾條件 | 資料來源 | 實作說明 |
| --- | --- | --- |
| 排除注意股、處置股 | DB `strategy_ticker_ineligibility` | 現有掃描器已實作；注意/處置股禁止融券 |
| 融券今日餘額 > 0 (`ShortSaleTodayBalance > 0`) | FinMind `TaiwanStockMarginPurchaseShortSale` | 確認個股有融券可用；為 0 代表無融券資格或已全數借出 |
| 距下一個暫停融券開始日 > 5 個交易日 | FinMind `TaiwanStockMarginShortSaleSuspension` | 避免進場後不久即遭強制回補（取 `date` 最近未來日，計算工作日距離） |

### 3.2 建議過濾（降低軋空與流動性風險）

| 過濾條件 | 資料來源 | 建議門檻 | 說明 |
| --- | --- | --- | --- |
| 融券使用率偏低 | `TaiwanDailyShortSaleBalances` `MarginShortSalesCurrentDayBalance / MarginShortSalesQuota` | < 0.6（即低於 60%） | 使用率過高代表放空者已擁擠，軋空風險大 |
| 借券賣出餘額佔流通股比例偏低 | `TaiwanDailyShortSaleBalances` `SBLShortSalesCurrentDayBalance` + 流通股數 | < 5% | SBL 持倉過大同樣有軋空風險 |
| 最近 5 日內無漲停 | OHLCV `close ≥ limit_up` | 最近 5 日均無漲停 | 漲停代表多方力道集中，近期軋空風險高；可用 `TaiwanStockPriceLimit` 取漲停板價格比對 |
| 20 日均量 ≥ 1,000 張 | OHLCV `volume` | ≥ 1,000,000 股（即 1,000 張） | 放空回補需要買盤承接，流動性要求比做多更嚴格 |
| 個股最近 20 日無停牌 | DB `is_usable = 1` | — | 停牌期間無法回補 |

### 3.3 回補前的強制回補日提前出場

進場後持倉期間，若下一個 `TaiwanStockMarginShortSaleSuspension.date` 距今 ≤ 3 個交易日，應強制觸發回補，不等 `cover_signal` 訊號。

此邏輯與課程回補條件（趨勢改變、跌勢攻擊消失、假跌破收回）**並行**：

- 課程回補條件先行（只要課程訊號觸發即回補）
- 強制回補日作為**硬性截止**：即使課程訊號未觸發，也必須在截止日前出場

---

## 4. 本專案現況與資料缺口摘要

| 項目 | 現況 |
| --- | --- |
| Task 19 回測 | 未加入任何 §2 的實務限制，以固定持有計算報酬 |
| FinMind 融券資料 | `TaiwanStockMarginPurchaseShortSale` 與 `TaiwanDailyShortSaleBalances` 均可取得，但尚未整合進掃描器 |
| 強制回補日資料 | `TaiwanStockMarginShortSaleSuspension` 可直接取得暫停融券日期區間，尚未整合 |
| 除息日資料 | `TaiwanStockDividend` 提供 `CashExDividendTradingDate`，可與 `TaiwanStockMarginShortSaleSuspension` 交叉驗證 |
| 借券即時可用餘額 | **無法從 FinMind 取得**；`TaiwanStockSecuritiesLending` 只記錄已成交借券，不代表當下可借量 |
| 借券費率報價 | **無法從 FinMind 事先取得**；成交後費率可從 `TaiwanStockSecuritiesLending.fee_rate` 取得歷史參考值 |
| 課程說明 | **課程對以上所有實務限制完全沒有說明**，本文件內容屬於「台股實務補充」，不應混入課程框架的 K 線訊號判斷邏輯 |

---

## 5. 與下游 Task 21 的銜接

Task 21（`short_daily_scanner`）應依以下方式整合本規格：

1. 掃描器進場候選清單在通過課程訊號（`short_entry`）篩選後，額外套用 §3.1 必要過濾。
2. §3.2 建議過濾可作為掃描器評分項目（非二元過濾），協助排序候選清單。
3. 掃描器輸出欄位應包含：
   - `short_suspension_start`：下一個暫停融券開始日（來自 `TaiwanStockMarginShortSaleSuspension`）
   - `days_to_suspension`：距暫停融券開始的工作日數
   - `short_sale_balance`：融券今日餘額（張）
   - `short_sale_utilization`：融券使用率
   - `recent_limit_up`：最近 5 日是否有漲停（布林）
4. 掃描器報告必須在輸出欄位說明中標明：「以上可交易性欄位均屬【課程未涵蓋】的台股實務補充，與課程 K 線訊號條件分開列示。」
