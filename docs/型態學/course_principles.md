# 型態學 — 課程原則參考文件

**Source:** PressPlay 課程「林家洋｜K 線力量：透過多空力量的改變發現未來」→「型態學」子分類（18 articles）
**Project ID:** `55DE90EBFBB634BE864F75703AB654DE`
**Captured:** 2026-05-16

**Per-article notes:** `docs/型態學/01-18.md` (18 files)

---

# Part 1: Core Definitions

## 1.1 頸線（Neckline）— 完整定義

**Source:** 頭部型態 + 移動平均線連結（K線力量入門/行進ing）+ 事件(七) 中期持有

> **頸線指的是：季線下彎之後，波動狀態之下的前一個低點，同時畫下頸線之後，上方必須要有至少三個月以上的套牢區。**

三個必要條件：
1. 季線下彎之後（MA60 方向轉空）
2. 波動狀態下的**前一個 swing low**
3. **該 low 上方必須有至少 3 個月的套牢區**

對應的多方版本：季線上揚後的前一個高點 + 下方有 3 個月堆積。

**判定的兩種變形**：
- 短期大幅下跌使前低上方<3個月套牢 → 再往前找前低
- 三個月範圍模糊 → 需謹慎

**鐵則**：錯判頸線會是交易災難。

## 1.2 攻擊型態（Attack Patterns）

四種攻擊型態，依強度排序：

| 強度 | 型態 | 辨識依據 |
|---|---|---|
| 🔴 最強 | **日出攻擊** | high > prev_high AND low > prev_low 連續 |
| 🟠 次強 | **跳空攻擊** | 突破紅K隔日跳空且收盤未補 |
| 🟡 中 | **推升攻擊** | 連續 K 線**低點**逐步推升 |
| 🟢 最弱 | **波動前進** | 連續 K 線**高點**逐步推升 + 多數重疊 |

**辨識規則總結**：
- 波動前進：**看高點**是否持續創新高
- 推升攻擊：**看低點**是否有推升意義
- 楔形：**幅度大**的波動前進

## 1.3 套牢結構（Supply Structure）

| 結構 | 定義 | 系統 column |
|---|---|---|
| 套牢區 | K 線圖上實質成交的高價位 | `overhead_supply_layer` |
| 賣壓中空 | 急跌段中無大量套牢 | `supply_vacuum_zone` |
| 缺口壓力 | 向下跳空未被回補的價位 | （新增：`unfilled_gap_down_resistance`）|
| 層層套牢 | 跌破頸線後上下盤跌形成 | `overhead_supply_layer >= 4` 代理 |
| 破底型態 | 連續創新低 + 每次又增一層套牢 | （新增：`is_in_breakdown_pattern`）|

---

# Part 2: Pattern Types and Their Operational Meaning

## 2.1 基礎篇

### 底部型態 — 沒有意義
- 必須事後辨識
- 套牢壓力才是阻礙
- 「一字底」是穿鑿附會
- **重點只看頸線**

### 頭部型態 — 完整套牢結構
- 名詞是形狀說法，實務 = 整個套牢區段
- M頭 / 頭肩頂 / 複合頭肩頂 = 都是頭部
- **頸線跌破才有交易意義**
- 頸線本身**不是好的賣點**（已離高點太遠）

### 箱型整理型態
- 嚴謹定義：≥ 3 個月 + 高低點不變
- 有越來越高/低 → 屬楔形（不同處理）
- **位置決定意義**：
  - 過去拉抬過 → 箱底跌破 = 頭部；箱底突破 = 多方再次型態突破
  - 過去無拉抬 → 可能是築底
- 「箱底買進、箱底跌破停損」**矛盾**

### 楔形型態
- 上升楔形：唯一用途 = **加碼點輔助**
- 下降楔形：完全雞肋
- 短期趨勢線可替代

### 三角收斂型態
- 拼湊出來（上 = 壓力線、下 = 短期趨勢線）
- **「不宜邏輯」**：跌破下緣 = 不宜作多；突破上緣 = 不宜放空
- 不是買賣訊號

### 中樞型態 — 中繼與過渡
- 多方強勢 = 高檔狹幅整理
- 空方弱勢 = 弱勢延續
- **不能用於買賣點**
- 真正用途：**避免錯誤的賣出時機**
- 「高檔狹幅整理 = 推升攻擊的一種」

## 2.2 延伸篇

### 反轉型態
- = 多空轉折組合（**力竭原理**）
- 只用於**出場**，不是入場
- 一眼必會：**黑K吞噬 + 高檔長黑**（空方）
- 「反轉型態 ≠ 立即價格反轉」
- 多方反轉：不是買點，需賣壓中空 + 環境氣氛

### 騙線型態（陷阱）
- 三大類：
  - 上有壓力的突破（最常見）
  - 看似攻擊的回頭（利多陷阱）
  - 假性跌破（**限大盤**）
- 「沒有騙線型態，只有陷阱」
- 個股不適用假性跌破

### 背離型態
- = 現象，**不是訊號**
- 不能作為買賣依據
- 與乖離率不同（乖離率是「虛幻說法」）
- 籌碼背離：作為持有警示可，買賣訊號不可
- 指標背離：**完全不採用**（淺碟市場不可靠）

### 缺口壓力型態
- 向下跳空 + 未回補 = 型態壓力
- 多方下跳空 vs 空方下跳空：嚴重度不同
- **「離現在最近的一個缺口壓力還沒越過之前，都不宜對股價樂觀」**
- 缺口未補 + 缺乏賣壓中空 = 無法反彈

### 缺口支撐型態
- **K 線圖上沒有「支撐」**（只有壓力）
- 「壓力是用來被突破的、支撐是用來被跌破的」
- 跳空缺口的「支撐」要看：是否利多帶上來
- **攻擊跳空 = 不可被回補**（不是支撐）

## 2.3 應用篇

### 日出攻擊
- 定義：high > prev_high AND low > prev_low
- 連續日出 + 創新高 = 日出攻擊
- **學習目的：看得懂，不是找股票買**
- 出場：跌破前一日低點（移動停利）

### 跳空攻擊
- 定義：突破紅K隔日跳空 + **收盤未補**
- 失敗：盤中回補缺口
- 「**回測不破**」是無稽之談
- 「真正攻擊不從低檔起算」

### 推升攻擊（最常見、最重要）
- 兩個層次：盤中江波 + 多日 K 線
- K 線層次 = 低點推升型態
- 「高檔狹幅整理」也是推升攻擊的一種
- 是攻擊型態中最重要的環節

### 波動前進
- 最容易誤判，最讓人失去耐心
- = 壓縮的上升楔形
- 辨識：高點推升
- 「股性混亂」型不適用任何型態學

### 破底型態
- = 中樞型態空方版 + 區間放大
- 必有原因（基本面或環境）
- **離最近壓力越過、或空方趨勢結束之前都不能摸底**

### 上下肩缺口
- 上肩缺口（罕見）= **第一次型態突破** + 跳空 + 日落 + 缺口未補
  - 唯一「拉回承接」的攻擊型態
- 下肩缺口 = 對稱但**不對等**意義
- 「K 線理論不存在向下攻擊」

### 鑷頂與鑷底
- 鑷頂 = 高點價位相同 + 低點變化（兩種）
  - 強鑷頂：高點同、低點升
  - 弱鑷頂：高點同、低點降
- **必須等突破才考慮意義**
- 鑷底**無實務意義**（沒有支撐）

---

# Part 3: System Implementation Map

## 3.1 立即補完的 STUB

### `ma60_neckline.py` 完整實作

```python
def detect_neckline(df, supply_lookback=60):
    """
    課程精確頸線：
      1. 季線下彎 (ma60_slope_5d < 0)
      2. 季線下彎當日的前一個 swing low
      3. 該 swing low 上方有 ≥ 3 個月套牢
    """
    g = df.groupby("ticker")
    
    # MA60 下彎
    ma60_down = df["ma60_slope_5d"] < 0
    ma60_just_turned_down = ma60_down & ~g["ma60_slope_5d"].shift(1).lt(0)
    
    # 找前一個 swing low (5-bar local min)
    is_swing_low = (df["low"] < g["low"].shift(1)) \
                  & (df["low"] < g["low"].shift(-1)) \
                  & ...  # 5-bar local min full definition
    
    # 該 swing low 上方有 N 天套牢 (overhead_supply_layer 累積)
    ...
```

## 3.2 新增 entry filter / scoring

### `is_pattern_breakout` 精確化

```python
def is_pattern_breakout_strict(df):
    """
    型態突破 (真攻擊起點) vs 單純破前高 (中繼)
    
    條件：
      - 過去 60 (約3個月) 日 high/low 比 < 1.15 (箱型/中樞)
      - 不能有越來越高/低的趨勢 (排除楔形)
      - 今日 close > prior_high_60
      - MA60 已上揚
    """
```

### `is_clean_breakout` 過濾騙線

```python
def is_clean_breakout(df):
    """突破上方無套牢、無未補向下缺口"""
    is_breakout = df["close"] > df["prior_high_60"]
    is_clean_overhead = df["overhead_supply_layer"].fillna(0) <= 0
    has_no_unfilled_gap = ...  # 沒有上方未補向下缺口
    return is_breakout & is_clean_overhead & has_no_unfilled_gap
```

### `attack_intensity_level` ranking

```python
def attack_intensity(df, lookback=10):
    """
    攻擊強度：4 日出 / 3 跳空 / 2 推升 / 1 波動前進 / 0 無
    用於 scanner 加分
    """
```

### `is_in_breakdown_pattern` exclude

```python
def is_in_breakdown_pattern(df):
    """破底型態 = 連續創新低 + MA60 下彎 → 排除候選"""
    ...
```

### `tweezer_top_breakout` entry

```python
def tweezer_top_breakout(df, lookback=5):
    """鑷頂突破：多根 K 線高點接近 + 突破"""
    ...
```

### `shoulder_gap_up` entry (toggle)

```python
def is_shoulder_gap_up_pullback(df):
    """
    上肩缺口拉回承接 (僅 toggle 啟用)
    K-2: 第一次型態突破紅K
    K-1: 跳空紅K
    K0:  日落黑K + 缺口未補
    """
```

## 3.3 新增 exit conditions

### `consolidation_breakdown`

```python
def consolidation_breakdown(df):
    """
    中樞型態時間過久 + 黑K跌破 = 強警示
    """
```

### `unfilled_gap_down_resistance`

```python
def unfilled_gap_down_resistance(df):
    """
    上方有未補向下跳空缺口 → 反彈到此位置即遇阻
    """
```

## 3.4 Scoring 改進

### 缺口壓力扣分強化

```python
def overhead_supply_with_gaps(df):
    """
    overhead_supply_layer 計算需加入 unfilled gap-down
    """
    layer = df["overhead_supply_layer"].fillna(0)
    unfilled_gap_above = ...  # 上方未補向下缺口計數
    return layer + unfilled_gap_above
```

### 高檔狹幅整理 = 加分

```python
def high_zone_narrow_consolidation_bonus(df, lookback=6):
    """
    突破紅K後 N 天狹幅 + 低點不破突破點 = 加分
    """
```

---

# Part 4: Forbidden Patterns (Updated)

依型態學課程**明確禁止**：

| 禁止 | 來源章節 |
|---|---|
| 「底部型態」作為買進判斷 | 前言與底部型態 |
| 「一字底」 | 前言與底部型態 |
| 「W底、頭肩底等」型態名稱套用 | 前言與底部型態 |
| 「箱底買進、箱頂賣出」 | 箱型整理型態 |
| 「均線支撐」（5日、季線等）| 缺口支撐型態 + 多處 |
| 「N字戰法」、「拉回不破突破點再買」| 行進ing 紅K篇(三) + 跳空攻擊 |
| 「乖離率」（過大/過小）| 背離型態 |
| 指標背離作為訊號（MACD、KD、RSI 等）| 背離型態 |
| 「打第N隻腳」、「縮腳」、「下影線支撐」| 鑷底 + 下影線 |
| 「個股假性跌破」 | 騙線型態 |
| 「比較效應低就買」 | 破底型態 |
| 「過去操作過所以低接」 | 破底型態 |
| 「楔形突破買進」（特別下降楔形）| 楔形型態 |
| **「向下攻擊」鏡像放空邏輯** | 上下肩缺口 + 多處 |

---

# Part 5: Known Limitations / Quantitative Proxies

| 課程概念 | 系統代理 | 限制 |
|---|---|---|
| 「3 個月套牢」（頸線必要條件）| `overhead_supply_layer >= N` | N 取值待校準 |
| 「波動狀態前低」(swing low) | 簡單 5-bar local min | 不夠魯棒（同行進ing） |
| 「股性混亂」識別 | 高頻趨勢翻轉的代理 | 主觀 threshold |
| 「主力洗盤」 | 量縮 + 環境震盪 | 籌碼資料未整合 |
| 「題材股」基本面 | 無 | 需 EPS / 月營收整合 |
| 「環境背景」（大盤多空）| 大盤 trend column | 已有部分（market_open_ret） |

---

# Part 6: Implementation Priority (After 型態學)

| 優先級 | 任務 | 預期 ROI |
|---|---|---|
| 🔴 P0 | `ma60_neckline` 完整實作（含 swing-low detector）| 解鎖 trend_change.py + neckline_break 精確版 |
| 🔴 P0 | `is_pattern_breakout` entry filter | 估計信號降 70%、勝率 +15% |
| 🔴 P0 | `is_in_breakdown_pattern` 排除 | 估計避開 20-30% 失敗交易 |
| 🟠 P1 | `is_clean_breakout` 過濾騙線 | 估計勝率 +5-10% |
| 🟠 P1 | `attack_intensity` ranking | scanner ranking 改善 |
| 🟠 P1 | `unfilled_gap_down_resistance` | 補強上方壓力評估 |
| 🟡 P2 | `tweezer_top_breakout` entry | 罕見但有用 |
| 🟡 P2 | `shoulder_gap_up_pullback` (toggle) | 唯一拉回承接型態 |
| 🟢 P3 | `consolidation_breakdown` exit | 補強現有出場 |
| 🟢 P3 | `high_zone_narrow_consolidation` scoring | 持有期間加分 |

預期完整補完後系統指標：
- 信號數：12,161/年 → 3,000-5,000/年
- 勝率：37% → 估 50-55%
- 平均報酬：0% → 估 +2-3%

---

# Appendix: 18 篇文章索引

完整列表見 `docs/型態學/index.json`

| 篇章 | 數量 | 檔案 |
|---|---:|---|
| 基礎篇 | 6 | 01-06 |
| 延伸篇 | 5 | 07-11 |
| 應用篇 | 7 | 12-18 |
| **總計** | **18** | |
