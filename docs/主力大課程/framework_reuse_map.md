# Stock-K-Bar 框架可複用結構盤點

> **目的：** 評估「主力大課程」整理能借用 stock-k-bar repo 哪些既有「容器/結構」，避免重新造輪子。
> **範圍：** 只盤點結構（命名/檔案 schema/目錄佈局），**不引用 K線力量課程的教學內容**。
> **抓取日期：** 2026-05-17

---

## 1. 課程文件骨架（docs/{課程名}/）

K線力量現有檔案類型 → 主力大可直接平行套用：

| 檔案 | 角色 | 主力大適用性 |
|---|---|---|
| `index.json` | 課程文章索引（`articles[].order/category/title/url`） | ✅ 直接套：PressPlay 索引可轉成同 schema；scripts/ 講稿也可用同表 |
| `course_principles.md` | 三段式：①完整規則 ②🔴不可違背的核心主軸 ③命名/來源追溯規範 | ✅ 直接套：主力大也有「三大原則」+「進出場規則」+「形態定義」可填 |
| `strategy-indicators.md` | 策略定義與關鍵指標 | ✅ 直接套：當沖 vs 隔日沖 vs 波段三套指標分節 |
| `strategy-readiness.md` | 「已成熟原型 / 待驗證 / 後續工作 / 策略化邊界」四分流 | ✅ 直接套：主力大各形態（奇形/窒息量/投信跟單）按成熟度分流 |
| `strategy-validation-plan.md(+html)` | 驗證流程 + 視覺化 | ✅ 套：每個形態都需要這個 |
| `manual-images-needed.md` | 需要的圖檔清單 | ✅ 套 |
| `backtests/*.md` | 各 strategy 的回測報告 | ✅ 套（見下方 §3） |
| `images/*.jpg` | 課程截圖（命名格式：`【主題】子標題-NN.jpg`） | ✅ 套：截 PressPlay 影片畫面用同命名 |

**結論：整套 docs/ 容器 100% 可複用，只要建 `docs/主力大課程/` 平行目錄即可。**

---

## 2. course_principles.md 內部結構（三段式可直接複製）

```
# {課程名} — 課程主軸與規則總覽
## 第一部分：課程完整規則
### {形態/概念 1}
### {形態/概念 2}
### {停損規則}
### {攻擊判斷}
### {觀念性原則}
## 第二部分：🔴 不可違背的核心主軸
### 進場側
### 出場側
### 力量判斷
### 趨勢與型態
## 第三部分：命名與來源追溯規範
### 命名規則
### 程式碼註解格式
```

主力大可以直接套：
- ①「完整規則」放：三大原則 / 大波段選股方程式 / 飆股基因 / 四大短線形態 / 當沖 SOP / 隔日沖 / 停損 / 加碼（窒息量/投信跟單）
- ②「核心主軸」放：那些「絕對不能違反」的東西（如「股票占 50%、買賣占 30%、運氣占 20%」、「不用 MACD/KD/RSI」之類的鐵則）
- ③ 命名規範可沿用 stock-k-bar 既有的（節省思考）

---

## 3. backtests/*.md 結構（一致的 4-section 模式）

```
# {Strategy Name}
## 排序邏輯（v? 對齊回測基準）
## Top-N 歷史命中摘要
## 最新交易日候選
## 近 20 交易日候選
```

主力大每一個進場形態（奇形、窒息量攻擊、投信跟單）都能用這個模板做 daily scanner 報告。

---

## 4. scripts/ Python 慣例

現有 21 個 Python 檔的命名與 import 慣例：

```
scripts/
├── {strategy}_daily_scanner.py        ← 每日掃描
├── {strategy}_strategy_check.py       ← 策略條件檢查
├── {strategy}_attack_strategy_check.py ← 進場質量
├── {strategy}_intraday_quality_check.py ← 盤中品質
├── {strategy}_next_open_quality_check.py ← 隔日開盤
├── kline_course_backtest.py            ← 統一回測引擎（被各 scanner import）
├── exit_simulation.py                  ← 出場模擬
├── portfolio_simulator.py              ← 組合模擬
├── monitor_watchlist.py                ← 自選股監控
├── daily_review.py                     ← 每日回顧
├── finmind_intraday_kline_check.py     ← 共用資料來源（FinMind 分鐘 K）
├── volume_profile.py                   ← 分價量表
└── warmup_finemind_intraday_cache.py   ← 快取暖機
```

**底層基礎建設（直接複用，不重寫）：**
- `kline_course_backtest.py` 的 `load_bars / add_features / add_signals` — 任何形態都能掛上去
- `finmind_intraday_kline_check.fetch_kbar` / `volume_profile` — 資料層
- `breakout_attack_strategy_check` 的 `add_trade_fields / MIN_AVG_VOLUME_20 / MIN_CLOSE` — 共用 trade 欄位 + 流動性過濾
- `false_breakdown_strategy_check.add_market_regime` — 市場狀態標籤
- DB throttle / FinMind client 等 — 都已封裝在 stock-analysis-system

**對應「主力大」需新增的 strategy 檔（命名建議）：**
- `zhuli_breakout_daily_scanner.py` — 奇形（短線突破形態一）
- `zhuli_breakout_form2_3_4_scanner.py` — 形態二/三/四（講稿待補後）
- `zhuli_suffocation_scanner.py` — 窒息量加碼
- `zhuli_institutional_follow_scanner.py` — 投信跟單
- `zhuli_intraday_strategy.py` — 當沖（5/10 均、量價）
- `zhuli_overnight_strategy.py` — 隔日沖

每個 scanner 都能 import 共用基礎建設，**自己只寫條件**。

---

## 5. 資料輸出慣例（data/analysis/）

```
data/analysis/{strategy}/
├── {strategy}.csv
├── {strategy}_recent20d.csv
├── {strategy}_topn_summary.csv
└── archive/{strategy}/{YYYY-MM-DD}/...
```

主力大每個 scanner 沿用同模式即可。

---

## 6. 整合風險與衝突點

**無衝突區（直接複用）：**
- docs/ 骨架 / index.json schema / backtest md 模板 / scripts/ 共用底層 / data/analysis 慣例

**需區隔的（隔離原則）：**
- `course_principles.md` 內容**完全獨立**，K線力量的條目絕不可混入主力大版本
- 形態名稱可能撞名（如「型態一」），命名要加 `zhuli_` 前綴避免混淆
- `manual-images-needed.md` / `images/` 各自獨立目錄

**待釐清：**
- `index.json` 的 `category` 欄位在 K線力量是用「子分類」（如入門/行進ing/型態學），主力大要不要用同字段 or 改成「ch1 / ch2-1 ...」對應講稿章節？
- 主力大同時有「影片講稿（scripts/）」+「PressPlay 線上文章」+「PressPlay 影片但無內文（多數）」三種來源，索引要不要分三張表還是統一一張？
