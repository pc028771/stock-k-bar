# Volume Profile 壓力區 + 攻擊品質分數 設計文件

日期：2026-05-15

## 背景

現有 `overhead_supply_layer` 用日 K OHLCV 的 peak-count 代理壓力區，精準度不足。
攻擊品質目前只看突破隔日是否開低（單點），缺乏對突破前結構和盤中行為的完整評估。
本次目標：照著課程（K線力量判斷入門）的實際判斷邏輯實作這兩個指標。

## 範圍

**實作項目：**
1. `volume_profile.py` — VP 特徵計算（共用模組）
2. `kline_course_backtest.py` — 攻擊品質特徵 + 回測分析腳本
3. `breakout_daily_scanner.py` — 資料抓取整合（FinMind 歷史 / Fubon 即時）

**不在範圍內：**
- 十字線區間箱型（另一個待辦項目）
- 放空策略修改
- WebSocket 即時推播

## 設計原則

1. **不看未來**：攻擊品質分數的輸入特徵只能用突破當下已知資料，回測與即時掃描用同一套邏輯。
2. **先篩再抓**：FinMind `TaiwanStockKBar` 一次只能一檔一天，必須先用日 K 限縮 top N 再抓取。
3. **資料來源抽象**：VP 特徵計算和資料來源解耦，同一個 `compute_vp_features()` 接兩種來源。

---

## 模組 1：`scripts/volume_profile.py`（新增）

### 輸入

```python
def compute_vp_features(
    vp: pd.DataFrame,   # columns: price (float), volume (int/float)
    current_close: float,
    band_pct: float = 0.10,  # 觀察帶寬：現價上方 0–10%
    dense_threshold_pct: float = 0.20,  # 密集定義：該帶量 > 全體 top 20%
) -> dict[str, float | bool]:
```

### 輸出欄位

| 欄位 | 型別 | 說明 |
|------|------|------|
| `vp_overhead_pct` | float | 現價以上成交量 / 全日總量（層層套牢程度）|
| `vp_dense_above` | bool | 現價上方 band 內有密集成交區（賣壓就在頭頂）|
| `vp_supply_vacuum` | bool | 現價上方 band 內密度 < 20th percentile（賣壓中空）|
| `vp_nearest_resistance_pct` | float | 最近密集成交區距現價的距離（%），無則 NaN |

### 從分 K 建 VP（FinMind 來源）

```python
def build_vp_from_kbar(kbar: pd.DataFrame) -> pd.DataFrame:
    """把 1分K OHLCV 聚合成 [price, volume]。
    每根 bar 的 volume 均勻分配到 high-low 之間的 tick 格子（tick=0.01 元）。
    """
```

### 從 Fubon 分價量表建 VP

Fubon `intraday/volumes/{symbol}` 直接回傳 `[price, volume, volumeAtBid, volumeAtAsk]`，
轉換為標準格式即可：`df.rename(columns={"volume": "volume"})[["price", "volume"]]`。

---

## 模組 2：攻擊品質特徵（`kline_course_backtest.py`）

### 新增特徵（加入 `add_features`）

所有特徵**只用突破當下已知資料**（不看未來）：

| 欄位 | 計算方式 | 對應課程概念 |
|------|---------|------------|
| `higher_low_count` | 突破前 10 日，`low > low.shift(1)` 的天數 | 低點持續墊高 |
| `gap_open` | `open > prev_close`（突破日跳空開高）| 攻擊不給低買 |
| `pre_breakout_trend_days` | 突破前 20 日內，close > ma60 的連續天數 | 趨勢背景 |

`body_pct`、`close_pos`、`volume_ratio` 已存在，直接使用。

### 攻擊品質分析腳本（新增 `scripts/attack_quality_analysis.py`）

**目的**：用歷史回測找出上述特徵對 `ret_10d` 的預測力，產出權重建議。

**流程**：
1. 取所有 `breakout_attack == True` 的樣本
2. 計算每個特徵與 `ret_10d` 的 Spearman 相關係數
3. 輸出相關係數表 → 人工決定 `attack_quality_score` 的加權公式
4. 結果寫入 `docs/K線力量判斷入門/backtests/attack_quality_analysis.md`

分析完成後，把確定的加權公式硬寫進 `add_signals` 裡的 `attack_quality_score`（0–100）。

---

## 模組 3：資料抓取整合（`breakout_daily_scanner.py`）

### 歷史模式（回測 / 昨日以前）

```python
def fetch_vp_finmind(ticker: str, trade_date: str, token: str) -> pd.DataFrame:
    """呼叫 FinMind TaiwanStockKBar，回傳 [price, volume]。
    快取路徑：~/.four_seasons/finmind_kbar_cache/{ticker}_{trade_date}.csv（已有）
    """
```

呼叫 `build_vp_from_kbar(kbar)` 再 `compute_vp_features(vp, close)`。

### 即時模式（當日盤中或盤後）

```python
def fetch_vp_fubon(ticker: str, client: FubonClient) -> pd.DataFrame:
    """呼叫 Fubon intraday/volumes/{ticker}，回傳 [price, volume]。
    FubonClient 需新增 get_intraday_volumes(symbol) 方法。
    """
```

### 整合到 `enrich_intraday`

現有函式改名為 `enrich_intraday_vp`，新增 VP 欄位：

```python
intraday_cols = [
    "intraday_rows",
    "intraday_strong_attack",
    "below_open_after_1130",
    "intraday_attack_failure",
    "intraday_close_pos",
    "intraday_return_pct",
    # 新增
    "vp_overhead_pct",
    "vp_dense_above",
    "vp_supply_vacuum",
    "vp_nearest_resistance_pct",
]
```

### 限縮邏輯

延續現有 `max_intraday_per_date`（預設 15），只對每日前 N 名候選抓分 K，避免超出 API 配額。

---

## `FubonClient` 新增方法

```python
def get_intraday_volumes(self, symbol: str) -> pd.DataFrame:
    """呼叫 /intraday/volumes/{symbol}，回傳 [price, volume] DataFrame。
    返回空 DataFrame 時不 raise，由呼叫方處理。
    """
```

位置：`/Users/howard/Repository/stock-analysis-system/clients/fubon_client.py`

---

## 評分整合（`score_rows`）

VP 特徵加入現有 `scanner_score` 計算：

| 條件 | 分數（初始值，待 VP 回測驗證後調整）|
|------|------|
| `vp_supply_vacuum == True` | +10 |
| `vp_dense_above == True` | -10 |
| `vp_overhead_pct < 0.15` | +5 |
| `vp_overhead_pct > 0.40` | -5 |

`attack_quality_score` 作為獨立欄位顯示在報告中，不直接加入 `scanner_score`，等分析腳本跑完結果後再決定權重。

---

## 實作順序

1. `volume_profile.py` — 核心 VP 計算（可單獨測試）
2. `fubon_client.py` — 新增 `get_intraday_volumes`
3. `kline_course_backtest.py` — 新增攻擊品質特徵
4. `attack_quality_analysis.py` — 回測分析腳本
5. `breakout_daily_scanner.py` — 整合 VP 資料抓取與評分

## 檔案異動清單

| 檔案 | 異動類型 |
|------|---------|
| `scripts/volume_profile.py` | 新增 |
| `scripts/attack_quality_analysis.py` | 新增 |
| `scripts/kline_course_backtest.py` | 修改（新增特徵）|
| `scripts/breakout_daily_scanner.py` | 修改（整合 VP）|
| `stock-analysis-system/clients/fubon_client.py` | 修改（新增方法）|
