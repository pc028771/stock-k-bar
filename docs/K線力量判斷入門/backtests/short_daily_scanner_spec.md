# 放空每日掃描清單實作規格（Task 21）

本文件說明放空每日掃描清單（`short_daily_scanner.py`）的設計、輸出欄位與可交易性過濾邏輯。

---

## 0. 銜接關係

| 文件 | 用途 | 內容 |
| --- | --- | --- |
| `short_strategy_spec.md` | 課程訊號定義 | `short_entry`、`cover_signal` 的四要素量化 |
| `short_tradability_spec.md` | 台股實務限制 | 融券資格、暫停日期、漲跌停、流動性過濾 |
| **`short_daily_scanner_spec.md`** | **本文件** | **掃描器輸出欄位、評分邏輯、使用說明** |

---

## 1. 掃描器輸出檔案

掃描器生成三份輸出檔：

| 檔案 | 說明 |
| --- | --- |
| `short_daily_scanner.csv` | 完整歷史掃描結果（所有訊號日期） |
| `short_daily_scanner_recent20d.csv` | 最近 20 個交易日的候選 |
| `short_daily_scanner.md` | 掃描報告（含 Top-N 摘要、最新與近期候選預覽） |

以及存檔版本：
- `archive/short_daily_scanner/YYYY-MM-DD/` — 該日期的完整掃描結果快照

---

## 2. 輸出欄位說明

### 2.1 K 線與交易資料

| 欄位 | 型態 | 說明 |
| --- | --- | --- |
| `ticker` | string | 股票代碼（4 位數字） |
| `trade_date` | string | 交易日期（YYYY-MM-DD） |
| `open` | float | 開盤價 |
| `high` | float | 最高價 |
| `low` | float | 最低價 |
| `close` | float | 收盤價 |
| `volume` | int | 成交量（股） |
| `avg_volume_20` | float | 過去 20 日平均成交量（股） |

### 2.2 課程訊號品質指標

| 欄位 | 型態 | 說明 | 來源 |
| --- | --- | --- | --- |
| `volume_ratio` | float | 成交量倍數（今日成交量 / 20日均量） | `short_strategy_spec.md` 買盤不繼代理 |
| `close_pos` | float | 收盤位置百分比（0~1）<br/>0 = 最低，1 = 最高 | 買盤不繼代理：值越低代表收盤位置越低（買盤不願護盤） |
| `body_pct` | float | K 線實體比例<br/>= abs(close - open) / open | 買盤不繼代理：`long_black_k` 需 body_pct ≥ 0.015 |
| `prior_low_20` | float | 過去 20 日低點（頸線代理） | 跌破條件：`close < prior_low_20` |
| `ma60` | float | 60 日均線（季線） | 弱勢條件：`close < ma60` |

### 2.3 未來報酬（回測用）

| 欄位 | 型態 | 說明 | 計算 |
| --- | --- | --- | --- |
| `ret_10d` | float | 未來 10 交易日報酬<br/>（放空方向） | = (進場價 - 10日後價格) / 進場價<br/>正值表示股價下跌、放空獲利 |
| `ret_20d` | float | 未來 20 交易日報酬<br/>（放空方向） | 同上，但用 20 日後價格 |

**注意**：這兩欄用於回測評估掃描器品質，實盤交易時通常為 NaN（因為未來資料尚未確定）。

### 2.4 風險與可交易性標誌【課程未涵蓋】

| 欄位 | 型態 | 說明 | 資料來源 |
| --- | --- | --- | --- |
| `is_attention_stock` | int | 注意股標誌（1 = 是） | DB `standard_daily_bar.is_attention_stock` |
| `is_disposition_stock` | int | 處置股標誌（1 = 是） | DB `standard_daily_bar.is_disposition_stock` |
| `short_suspension_start` | string | 下一個融券暫停開始日（YYYY-MM-DD） | FinMind `TaiwanStockMarginShortSaleSuspension` |
| `days_to_suspension` | float | 距下一個融券暫停開始的工作日數 | 根據 `short_suspension_start` 計算（粗略） |
| `short_sale_balance` | float | 融券今日餘額（張） | FinMind `TaiwanDailyShortSaleBalances.MarginShortSalesCurrentDayBalance` |
| `short_sale_utilization` | float | 融券使用率（%） | = `short_sale_balance` / 融券額度 × 100 |

---

## 3. 評分邏輯

### 3.1 計算流程

```
基礎分數 = 50
加分（課程訊號品質）：
  + 收盤位置低 (close_pos <= 0.3) → +8 分
  + 成交量倍數高 (volume_ratio >= 1.2) → +8 分
  + K線實體大 (body_pct >= 0.02) → +6 分

風險扣分【課程未涵蓋】：
  - 距融券暫停日 <= 5 工作日 → -15 分
  - 融券使用率 > 60% → -10 分

最終分數 = 基礎分數 + 加分 - 風險扣分
           裁切至 [0, 100]
```

### 3.2 分數分布

根據掃描結果：
- 基礎分數 50 分：未通過課程訊號篩選或無加分（少見）
- 66 分：基礎 50 + 課程加分 8 + 風險扣分 -2（部分股票風險較高）
- 72 分：基礎 50 + 課程加分 22（無風險扣分，為高品質候選）

**建議用法**：按 `scanner_score` 由高到低排序，優先考慮 72 分候選。

---

## 4. 可交易性過濾【課程未涵蓋】

掃描器應用以下二元過濾，**僅通過該等條件的訊號才會出現在輸出**：

| 過濾條件 | 說明 | 實作 |
| --- | --- | --- |
| 非注意股/處置股 | 法規禁止融券 | `is_attention_stock == 0 and is_disposition_stock == 0` |
| 上市/上櫃 | 非興櫃市場（無融券資格） | 根據股票代碼或 FinMind 市場分類 |
| 非排除清單 | 排除特定股票（如停牌長期、公告下市等） | DB `screening_exclusion` + `strategy_ticker_ineligibility` |
| 20 日均量 ≥ 800,000 股 | 流動性底線 | `avg_volume_20 >= 800_000` |
| 股價 ≥ 10 元 | 低價股風險排除 | `close >= 10` |

若所有條件均通過，該訊號才被納入掃描清單。

---

## 5. 排序邏輯（每日內排名）

在同一交易日內，掃描器按以下優先順序排序：

1. **主要排序**：`scanner_score`（由高到低）
2. **次級排序**：`volume`（成交量由高到低，同分時用於破局）

每日內排名欄位 `rank_in_date` 從 1 開始遞增。

---

## 6. 課程訊號與實務限制的邊界

### 6.1 課程框架部分

以下全部來自 `short_strategy_spec.md`，與課程教學完全對應：

- **弱勢**：`close < ma60` 且季線下彎
- **跌破**：`close < prior_low_20` 且隔日確認
- **反彈遇壓**：用季線下彎作背景代理
- **買盤不繼**：長黑K（黑K + body_pct ≥ 1.5%）

### 6.2 實務補充部分【課程未涵蓋】

以下內容為台股融券交易制度規範，**不屬於課程範圍**：

- 注意股 / 處置股排除
- 融券暫停日期與天數
- 融券使用率與軋空風險評估
- 漲跌停買不到的風險（目前未在掃描器實作，但 `short_tradability_spec.md` 有建議）

使用者應當理解：
- **課程教的是 K 線判斷邏輯**，不涉及任何台股制度細節
- **掃描器的實務過濾是額外加值**，幫助提升可執行性，但非課程必要內容
- **若想驗證課程訊號本身的有效性**，應忽略實務過濾欄位，僅看 `short_entry` 訊號成立的日期與股票

---

## 7. 使用範例

### 7.1 查看最新一個交易日的高分候選

```python
import pandas as pd

scanner = pd.read_csv("data/analysis/kline_course_backtest/short_daily_scanner.csv")
latest_date = scanner['trade_date'].max()
latest = scanner[scanner['trade_date'] == latest_date].sort_values('scanner_score', ascending=False)
print(latest[['ticker', 'scanner_score', 'close_pos', 'volume_ratio', 'days_to_suspension']])
```

### 7.2 篩選避免強制回補的候選

```python
# 只看距暫停日 > 5 工作日的股票
candidates = scanner[
    (scanner['days_to_suspension'].isna()) | 
    (scanner['days_to_suspension'] > 5)
].sort_values('scanner_score', ascending=False)
```

### 7.3 評估掃描器品質（回測用）

```python
# 查看歷史 10 日平均報酬與勝率
valid = scanner.dropna(subset=['ret_10d'])
print(f"Mean 10d return: {valid['ret_10d'].mean() * 100:.3f}%")
print(f"Win rate: {(valid['ret_10d'] > 0).mean() * 100:.2f}%")
```

---

## 8. 限制與注意

1. **融券暫停日期計算粗略**：
   - 使用簡單的 `days_diff * 5 / 7` 估算工作日（未考慮假日）
   - 建議搭配 `short_suspension_start` 欄位自行驗證精確日期

2. **融券餘額與使用率資料延遲**：
   - FinMind 資料通常延遲 1~2 個交易日
   - 若該日期無最新資料，欄位呈現 NaN

3. **評分不代表確定獲利**：
   - 評分邏輯基於回測統計，但市場環境變化時可能失效
   - 務必搭配基本面、技術面其他確認

4. **未考慮漲跌停風險**：
   - 目前掃描器未排除最近有漲停的股票
   - `short_tradability_spec.md` §3.2 建議過濾「最近 5 日無漲停」，日後可加入

5. **放空報酬計算（回測用）**：
   - 假設當日訊號成立隔日開盤進場
   - 実際執行可能有滑點、券源可用性等偏差

---

## 9. 與相關文件的關係

```
課程內容（K線力量判斷入門）
  ↓
short_strategy_spec.md（課程訊號量化）
  ↓
short_tradability_spec.md（台股實務限制）
  ↓
short_daily_scanner.py（實作掃描器）
  ↓
short_daily_scanner_spec.md（本文件 ← 輸出欄位與評分說明）
```

使用掃描器時，建議按此順序閱讀，確保理解課程訊號與實務限制的邊界。

---

## 10. 修訂與改進方向

可考慮的日後優化：

1. **加入漲停風險過濾**：排除最近 5 日內有漲停的股票
2. **精確工作日計算**：使用 `pandas.tseries.offsets.BDay` 計算真正的工作日距
3. **分K增強**：對最近幾日的高分候選取得分K訊號品質評估
4. **融券成本評估**：加入 FinMind `TaiwanStockSecuritiesLending` 的借券費率參考
5. **動態閾值調整**：根據市場 regime（上升 / 盤整 / 下降）動態調整評分權重
