# 權證小哥 detector 規格書 v0.1

> 目的：把權證小哥課程中「可量化規則」翻成 detector / scanner 用得到的條件。
> 命名前綴：`xiaoge_`（避免跟 `kline_course_` / `zhuli_` / `four_seasons_` 衝突）
> 來源：`docs/權證小哥課程/快速上手筆記.md` + `data/analysis/xiaoge/transcripts/ch01.txt ~ ch19.txt`
> 涵蓋：Lesson 2-5（布林 + 籌碼 + 分點）— 跟 swing scanner 直接相關。ch01/ch04/ch16-ch19 不在本 spec 範圍。

---

## 命名規範 + 隔離規則

### 課程內 vs 課程外
- 純課程內條件 → `scripts/xiaoge/{entry,exit,scoring}/`
- 自行 backtest 校正的閾值 / 補充條件 → `scripts/xiaoge/extras/`（預設 OFF、`--extras` 啟用）
- 升格 / 降格規則參考 `scripts/kline/extras/README.md`

### Prefix 一致性
- 個別 detector：`xiaoge_<name>`
- 跨課程 cross detector：`cross_xiaoge_<name>` 或 `cross_<scope>_<name>`

---

## 主要 detector

### 1. xiaoge_bb_squeeze_breakout（布林軌道收斂後突破）

**來源：** ch06-ch08, ch12（飆股口袋名單做多策略 #8 #9）

**老師說法：**
> 「布林軌道打開…短期有整理完畢往上攻擊的態勢，那這種呢通常壓縮的越久，之後的漲勢拉就越驚人。」(ch12 06:44–07:08)
> 「布林昇龍拳…先沿下軌洗清浮額…連續二根紅K或三根紅K，從下通道一下就打到上通道，這種是多頭表態。」(ch07 00:21–01:16)

**量化條件（多頭）：**

1. **收斂前提**：今日布林帶寬 `bandwidth = (upper - lower) / lower * 100` ≤ **10**（小哥定義「正常」是 10、< 5 算很窄、≥ 20 算寬）。
2. **收斂期間**：過去 N 日（建議 N = 10）帶寬持續 ≤ 12。
3. **突破訊號（擇一）**：
   - (a) 連續 2-3 根紅 K 從接近下軌 (`close < bb_mid`) 一口氣穿到上軌 (`close > bb_upper`) — 升龍拳。
   - (b) 單根大紅 K + 收盤站上上軌 + 量增（量 ≥ 5 日均量 × 1.5）— 開布林表態。
4. **filter（建議）**：5MA 上揚 + 站上 5MA（出自 ch12 策略 #6）。

**量化條件（空頭、降龍掌）：** 鏡像。

**universe：** 全市場、可加 「有發行權證/股期」作為流動性過濾（小哥常用）。

**進場時點：** 突破當天（小哥說「第一根 K 表態」）。

**停利條件：** **K 棒收盤離開上軌（往右下方偏離 upper band）→ 找短線停利。** (ch07 04:58, ch13 02:38)

**停損條件：** 課程未明說具體 stop loss %，**⚠️ 推測** 跌破布林中軌（20MA）或跌破突破當天 K 棒低點。**需 backtest 自定義**。

**參數需驗證：**
- 帶寬閾值 10 / 5 / 20 是否合適台股目前環境
- 連續紅 K 根數 (2 vs 3)
- 是否要加量能 filter

---

### 2. xiaoge_main_chip_holder（主力買超 + 集保戶數三軸多頭）

**來源：** ch11, ch14

**老師說法：**
> 「多頭是主力買超，散戶賣超，集保戶數下降。」(ch11 00:14–00:25)
> 「主力數字…0 到 10 算小買，10 到 20 算中買，20 以上算大買。」(ch11 02:34–02:39)
> 「大戶持股的比率持續性的上升…散戶呢 100 張以下的這持股比率持續性的下降。」(ch14 02:55–03:11)

**量化條件：**

1. **主力買超**：前 15 名買超分點總量 − 前 15 名賣超分點總量 ≥ **20 張**（=「大買」門檻）。
2. **散戶賣超**：（資料定義：< 100 張為散戶；如有可得欄位則用之；否則用「集保戶數變化」代理）
3. **集保戶數環比下降**：對比上週/上月、`shareholding_count` 下降。
4. **趨勢確認**：月線上揚（避免「主力買在跌勢中」的陷阱）。

**universe：** 全市場 / teacher_picks 子集。

**訊號分級（建議）：**
- A 級：4 條全對
- B 級：1-3 條全對 + 月線上揚
- C 級：只主力買超 → 不獨立成訊號

**停損：** 未明說，**⚠️ 推測** 主力轉賣超 + 集保戶數轉增 → 出場。

**參數需驗證：** 「20 張大買」門檻在台股流動性差異大的股上不一致 — 可能要按 5MA 量比例化（例如 ≥ 5MA × 2%）。

---

### 3. xiaoge_main_chip_distribution（曲終人散、主力賣超三軸空頭）

**來源：** ch07 (曲終人散)、ch11

**老師說法：**
> 「在高檔的時候主力在這邊大幅地賣超，散戶大幅地買超，集保戶數大幅地增加…很容易第一根出現之後後面就崩跌了。」(ch07 09:13–09:35)

**量化條件：**

1. 個股在 60 日 / 120 日相對高檔（如 close ≥ MA60 × 1.15）。
2. 主力賣超 ≥ 20 張 連續 N 天。
3. 集保戶數大增（環比 + N% 以上）。
4. 布林帶寬寬（≥ 20）+ 高檔震盪（高低差大但收 K 不破）。
5. 出現第一根明顯黑 K（收盤 < 開盤、振幅 ≥ 3%）→ 觸發。

**用途：** **不是進場 detector，是 exit / warn detector**（持倉警示）。

---

### 4. xiaoge_key_broker_signal（關鍵分點動作）

**來源：** ch09-ch10, ch15

**老師說法：**
> 「關鍵分點…就是它會低買高賣的分點，而且它量做很大。」(ch09 01:50)
> 「關鍵分點先買，主力後面買；關鍵分點先賣，主力後面才賣。」(ch09 02:43)
> 「在殺低大買的分點呢，就是我們喜歡的分點。」(ch15 11:00)

**Phase A — 建立每檔股票的「關鍵分點池」**（前置作業、離線）：

1. 對每檔股票拉 800–2000 天分點買賣超歷史。
2. 對每個分點計算「區間獲利」= ∑(賣均價 − 買均價) × 量。
3. 排序、取國內分點 top 5-10 名（**排除外資、self-loop**）。
4. **加分項**：是「庫藏股分點」（粉紅色標記、公司派出手）= 權重 ×2。

**Phase B — 每日掃描：**

- 今日是否有任一池中分點是該股 top 3 買方或賣方？
- 該分點動作方向（買/賣）、量（張數 / 占成交量 %）。

**Phase C — 訊號分級：**
- A+：關鍵分點殺低大買（股價跌 + 該分點是當日 top 1-3 買方）
- A：關鍵分點高檔大賣（股價漲 + top 1-3 賣方）
- B：關鍵分點同步買進（不是殺低、但是順勢）
- 警告：**只有「不曾低買高賣」的單向買進分點 → 不算關鍵分點**（ch15 06:33 凱基台中案例）。

**universe：** 全市場（但需有分點層級資料 — **這是最大依賴**）。

---

### 5. xiaoge_flying_stock_screener（飆股口袋名單 — 多策略 combinator）

**來源：** ch12, ch13

**設計思路：** 把 ch12 的 9 條多頭策略 + 6 條空頭策略每條都做成獨立 sub-detector，最終 score = 命中條件數。**越多條件交集、出來的股票越少、精準度越高。**

**多頭 sub-detectors（9 條）：**

| 編號 | sub-detector | 量化條件 |
|---|---|---|
| M1 | xiaoge_top10_main_buying | 前 10 大買超分點均量 / 前 10 大賣超分點均量 ≥ 閾值 + 5 日均量 ↑ + 量 > 500 張 |
| M2 | xiaoge_max_broker_loading | 最大買超分點量佔成交量 ≥ 20% + 量 > 1000 張 + **排除隔日沖慣性分點** |
| M3 | xiaoge_main_buy_streak_N | 主力買超連續 N 天（N 可調 3/5/10/20）|
| M4 | xiaoge_foreign_buy_streak_N | 外資連續買超 N 天 + 交叉 check 關鍵分點是否在賣 |
| M5 | xiaoge_invest_trust_buy_streak_N | 投信連續買超 N 天 |
| M6 | xiaoge_volatility_rising_strong | 短期波動度 ↑ 2% + 5MA 上揚 + 站上 5MA |
| M7 | xiaoge_break_20d_high | 收盤創 20 日新高 |
| M8 | xiaoge_bb_open | 布林軌道打開（上軌斜率正） |
| M9 | xiaoge_bb_squeeze | 布林軌道壓縮（帶寬 < 10） |

**空頭 sub-detectors（6 條，鏡像）：**

| 編號 | sub-detector | 量化條件 |
|---|---|---|
| S1 | xiaoge_top10_main_selling | 前 10 大賣超分點均量 / 前 10 大買超分點均量 ≥ 閾值 |
| S2 | xiaoge_max_broker_dumping | 最大賣超分點量佔成交量 ≥ 20% + 量 > 1000 張 |
| S3 | xiaoge_main_sell_streak_N | 主力賣超連續 N 天 |
| S4 | xiaoge_foreign_sell_streak_N | 外資連續賣超 N 天 + 交叉 check 關鍵分點是否在買（避免空在低點）|
| S5 | xiaoge_invest_trust_sell_streak_N | 投信連續賣超 N 天 |
| S6 | xiaoge_volatility_rising_weak | 波動度 ↑ + 5MA 下彎 + 跌破 5MA + 跌破 20 日低 |

**用法：** CLI 接受 `--strategies M1,M3,M6,M8` 這種組合 → 輸出交集結果。Score = 命中數。

---

### 6. cross_xiaoge_swing（多策略交叉、波段多空主訊號）

**來源：** ch13 直接示範

**邏輯：** 升等規則 = **「布林 ∩ 籌碼 ∩ 分點」三維對齊**：

- **三維對齊（A+）：**
  - 布林：bb_squeeze_breakout 或 bb_open（M8/M9）
  - 籌碼：main_chip_holder（主力 20 ↑ + 集保戶 ↓）
  - 分點：key_broker_signal A 級以上
- **二維對齊（A）：** 任二個
- **單一訊號（B）：** 只一個
- **C：** 不獨立成訊號

**對應 daily_brief：** A+ 推主筆、A 列 watchlist、B 觀察、C 不顯示。

**整合「鎖 Plan + 只執行不決策」紀律：** 跑出 A+ 不代表自動進場 — 還是要走 stage 1/2/3 entry SOP。

---

## 跟現有 system 的整合點

### 既有資料可用
- **5MA / 20MA / 布林軌道**：`stock-analysis-system` 應已有日 K + 技術指標、可直接算布林帶寬。
- **外資 / 投信 / 自營商買賣超**：FinMind `TaiwanStockInstitutionalInvestorsBuySell`、daily 粒度有。
- **集保戶數**：FinMind `TaiwanStockShareholding`（每週更新、week-level）— 可用，但粒度比日 K 粗。
- **大戶持股比率**：FinMind `TaiwanStockHoldingSharesPer`（週/月粒度）。

### 缺資料（待 audit / 補抓）
- **個股 × 日 × 分點買賣超**（最關鍵、缺它整個 detector 4 / 5 都做不出來）
  - FinMind 有 `TaiwanStockDispositionSecuritiesPeriod` 等 dispositon 表，但沒有「個股 × 日 × 分點」買賣超表
  - CMoney 籌碼 K 線軟體有（付費商業軟體）
  - **方案 A：** 找 user 付費取得分點資料 API
  - **方案 B：** 用「外資 / 投信 / 自營商 / 主力買賣超合計」代理「主力買賣超」（精度損失但可先做）
  - **方案 C：** 跟 user 確認是否要爬 [neoStock.tw](https://neostock.tw) / [Goodinfo](https://goodinfo.tw) 分點資料（須評估 ToS + rate limit）

### 跟 zhuli_* / kline_course_* dedup
- **不重做的部分：**
  - 位階高度判定（kline_course 已有）
  - 5MA/10MA/20MA/60MA + 扣抵值（kline_course 已有）
  - 拉高出貨 / 試撮陷阱 / 短線進場三鐵（zhuli/kline_course 已有）
- **新增的部分（xiaoge 獨有 edge）：**
  - 布林帶寬量化（兩課程都沒明確定義帶寬數字）
  - 升龍拳 / 降龍掌 / 曲終人散 K 棒型態命名（兩課程都沒有）
  - 分點層級籌碼動作（兩課程都沒做到分點粒度、只到「站前哥/館前哥」這種口語化分點別名）
  - 主力 / 散戶 / 集保戶三軸打分

---

## 待 user 決策的開放問題

| # | 問題 | 影響 |
|---|---|---|
| 1 | 是否花錢取得分點層級資料？（CMoney / 神秘券商 / 其他付費 API） | detector 4/5 是否能落地 |
| 2 | 布林帶寬「正常 10 / 寬 20 / 窄 5」門檻直接套用、還是要按台股 2024-2026 環境 backtest 重校？ | detector 1 精度 |
| 3 | 「主力大買 ≥ 20 張」門檻是否要按股票流動性比例化？ | detector 2 在低流動性股的有效性 |
| 4 | 集保戶數只有週粒度，detector 2/3 是否接受 weekly resolution？ | detector 觸發頻率 |
| 5 | 關鍵分點池建立是否要由人工驗證（user 確認）？還是純自動排序？ | detector 4 信號品質 |
| 6 | xiaoge prefix 的 detector 是否要單獨進 daily_brief、還是 merge 進 cross_scanner 既有 pipeline？ | 工程整合方式 |

---

## 課程外條件隔離

### 純課程內條件 → `scripts/xiaoge/`

```
scripts/xiaoge/
├── entry/
│   ├── bb_squeeze_breakout.py   # detector 1
│   ├── main_chip_holder.py      # detector 2
│   └── key_broker_signal.py     # detector 4
├── exit/
│   ├── bb_walk_band_exit.py     # K 棒離開上軌
│   └── chip_distribution_warn.py # detector 3
└── scoring/
    ├── flying_stock_screener.py  # detector 5
    └── cross_xiaoge_swing.py     # detector 6
```

### 課程外條件（backtest 校正、自定義門檻） → `scripts/xiaoge/extras/`

```
scripts/xiaoge/extras/
├── README.md                     # 寫明每個 extra 是 user/backtest 加的、不是課程明文
├── extras.bandwidth_dynamic.py   # 帶寬閾值按環境動態調整
├── extras.atr_stop_loss.py       # 用 ATR 補課程沒講的停損
└── extras.broker_blacklist.py    # 處置股 / 隔日沖分點黑名單
```

任何「我自己加的、課程沒明說」的邏輯一律進 `extras/`、預設 OFF、`--extras` 啟用。
