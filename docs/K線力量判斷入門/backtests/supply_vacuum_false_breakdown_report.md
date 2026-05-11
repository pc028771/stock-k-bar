# supply_vacuum_zone 移植到 false_breakdown 場景（Task 15）

資料庫：`/Users/howard/.four_seasons/data.sqlite`

樣本：2025-01-02 至 2026-05-08

---

## 1. 問題背景

`supply_zone_spec_report.md` §3.2 指出：`supply_vacuum_zone` 在 `breakout_attack` 條件下退化（僅 n=140），原因是突破訊號已要求創 60 日新高，此時「近價 0~10% 帶量極少」的情境極為罕見。

課程（strategy-indicators.md §10 賣壓化解、層層套牢、賣壓中空）指出：

> 「賣壓中空不是買進理由本身，更像是**反彈段的推進效率與出場位置估計**。」

這代表 `supply_vacuum_zone` 更適合套用在**反彈情境**（如假跌破收回），而非突破情境。

Task 15 目標：驗證假跌破收回時，上方賣壓中空是否改善後續報酬。

---

## 2. 設計說明

### 分組定義

| 組別 | 條件 |
| --- | --- |
| `fb_base` | `false_breakdown_reclaim` + 可交易過濾 |
| `fb + vacuum_zone=1` | `false_breakdown_reclaim` + 可交易過濾 + `supply_vacuum_zone = 1`（上方賣壓中空） |
| `fb + vacuum_zone=0` | `false_breakdown_reclaim` + 可交易過濾 + `supply_vacuum_zone = 0`（上方賣壓不中空） |

可交易過濾：排除注意/處置股；20 日均量 ≥ 500,000 股；收盤價 ≥ 10 元。

進場：訊號日收盤後，t+1 開盤進場。出場：第 5/10/20 個交易日收盤。

---

## 3. 回測結果

### 3.1 全樣本對比

| 組別 | n | 5日均%（淨） | 10日均%（淨） | 10日勝率% | 20日均%（淨） |
| --- | ---: | ---: | ---: | ---: | ---: |
| fb_base（全體） | 547 | 0.899 | 1.739 | 57.40 | 5.870 |
| fb + vacuum_zone=1（賣壓中空） | 320 | 1.296 | 2.320 | 62.81 | 7.346 |
| fb + vacuum_zone=0（賣壓不中空） | 227 | 0.339 | 0.921 | 49.78 | 3.789 |

### 3.2 regime 分組（vacuum_zone=1）

| market_regime | n | 10日均%（淨） | 10日勝率% |
| --- | ---: | ---: | ---: |
| bear | 200 | 4.495 | 77.50 |
| bull | 53 | -1.230 | 41.51 |
| range | 67 | -1.364 | 35.82 |

### 3.3 regime 分組（vacuum_zone=0）

| market_regime | n | 10日均%（淨） | 10日勝率% |
| --- | ---: | ---: | ---: |
| bear | 53 | 2.294 | 67.92 |
| bull | 68 | -0.125 | 38.24 |
| range | 106 | 0.905 | 48.11 |

---

## 4. 結論

### 4.1 vacuum_zone=1 整體優於 vacuum_zone=0

全樣本中，`supply_vacuum_zone=1`（賣壓中空）的假跌破候選，10日均報酬 +2.32%（勝率 62.81%），明顯優於 `vacuum_zone=0` 的 +0.92%（勝率 49.78%）。

這與課程語意一致：「賣壓中空的股票，反彈段推進效率較高」。

### 4.2 效果集中在 bear regime

`vacuum_zone=1` 的優勢主要來自 bear regime（n=200，10日 +4.50%，勝率 77.50%）。這在邏輯上合理：熊市中假跌破後若上方賣壓中空，反彈阻力更少，推進更順。

**但在 bull/range regime，vacuum_zone=1 的效果反而轉為負報酬（bull -1.23%、range -1.36%）**，與 vacuum_zone=0 差異不大甚至更差。

### 4.3 限制

1. **vacuum_zone=1 樣本在 bull/range 偏少**：bull 53 筆、range 67 筆，統計顯著性存疑。
2. **`supply_vacuum_zone` 代理精度有限**：日 K 的帶狀重疊量只是 volume profile 的粗略代理，真正的「成交中空區」需要分價成交量。
3. **regime 分類依賴等權市場代理**，bull 或 range 期間的個股 vacuum 狀態可能受到市場整體噪音干擾。

### 4.4 課程語意對照

| 課程描述 | 本次結論 |
| --- | --- |
| 「賣壓中空 → 反彈段推進效率較高」 | bear regime 中明確支持（勝率 77.5% vs 67.9%） |
| 「賣壓中空不是買進理由本身」 | 符合：bull/range 中優勢消失，不能單靠中空條件進場 |
| 「賣壓中空更像是出場位置估計」 | 本次未驗證出場優化，為後續工作 |

---

## 5. 建議

- `supply_vacuum_zone=1` 可作為 `false_breakdown_reclaim` 在 **bear regime** 的加分條件（分數加權），而非強制硬過濾。
- Bull/range 環境不建議使用 vacuum_zone 作為加分，效果不穩定。
- `false_breakdown_daily_scanner` 可考慮加入 `supply_vacuum_zone` 欄位作為參考資訊（不強制過濾），搭配 regime 判斷後由操盤者自行決定。
