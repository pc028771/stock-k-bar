# K線行進ing — 課程原則參考文件

**Source:** PressPlay 課程「林家洋｜K 線力量：透過多空力量的改變發現未來」→「K線行進ing」子分類（39 articles）
**Project ID:** `55DE90EBFBB634BE864F75703AB654DE`
**Subcategory tag:** `803A884FEA50E0A617A1D8408FC8E6B9`
**Captured:** 2026-05-15

**Per-article notes:** `docs/K線行進ing/NN-*.md` (39 files)

---

# Part 1: Complete Course Rules (Mapping to System)

## 1.1 關鍵K線（Key K-line）

Source: 【關鍵K線延伸篇】關鍵K線的定義與使用目的

**Definition (重複入門 + 強調):**
> 改變趨勢的第一根K線（在這根K線之前與之後，趨勢不一樣）

**Critical rules:**
1. **形狀不重要**：並非長紅或長黑才算
2. **確認方式因 context 而異**：
   - 頸線型態 → 盤中突破即算
   - 季線扣抵 → 開盤跳上去即算
   - 轉折K線（大敵當前）→ 盤中碰到中值即算
3. **個股 vs 大盤**：
   - 大盤：判斷「趨勢改變與否」即可
   - 個股：「進場 vs 出場意義不同」
4. **K線意義 > 形狀**：相同形狀在不同位置意義不同（同入門 §7）

## 1.2 關鍵K線 × 移動平均線（精確頸線）

Source: 【關鍵K線延伸篇】與移動平均線的連結判斷

> **頸線的精確定義**：
> - 多方頸線 = **季線上揚後的前一個高點**
> - 空方頸線 = **季線下彎後的前一個低點**

**季線扣抵預判**：
- `ma60_rolling_off_close` < 今日 close → 隔天 MA60 上揚
- `ma60_rolling_off_close` > 今日 close → 隔天 MA60 下彎

**個股關鍵K線可比型態學/均線提早 1-2 天**——這就是 `ma60_neckline.py` STUB 的設計目的。

**「不破季線是事後論」**：禁止用「目前未破季線」作為買入理由。

## 1.3 關鍵K線 × 型態學

Source: 【關鍵K線延伸篇】與型態學的連結判斷

- **型態學突破不需等收盤**（盤中突破即算）
- 多方頸線突破 = 攻擊的「意圖」階段；還需有「攻擊上去的力量」才行
- 空方頸線跌破 = 賣壓實質存在
- **不能碰觸的股價型態**：頸線浮現但尚未跌破 → 多方不能進場

## 1.4 轉折組合K線（補完入門缺）

Source: 【關鍵K線延伸篇】與轉折K線的連結判斷 + 跳空篇(四) + 事件(九)

### 暗夜雙星（精確定義）
> **長黑摜破兩根形狀相似的併排 K 線**

入門代理（「黑K + open<prev_low + body>=4%」）**缺少了「兩根併排相似K線」的前置條件**。

### 夜星棄嬰
> 高檔遇壓紅K → 十字線 → **長黑跌破紅K的中值，且回補跳空缺口**

### 大敵當前
> **連續紅K拉不出距離 + 隔天長黑跌破第一根紅K的中值**

精確結構：
- K1, K2, K3：三根紅K（攻擊嘗試）
- 紅K幅度小（無拉開）
- K4：長黑跌破 K1 的中值（mid = (open+close)/2）

### 跳空反轉
> **長紅K 或創新高 → 隔日走低收黑 → 再隔日向下跳空**

### 雙鴉躍空
> **高檔壓力區附近，跳空開高收黑 → 隔日小黑K → 再隔日開盤向下跳空**

### 島狀反轉
> **先跳空向上 → 中間孤島 → 跳空向下，回補左邊跳空力量**

### 黑K吞噬（補入門）
> 紅K → 黑K **實體完全包覆**前一根紅K → **獲利了結賣壓的呈現**

### 多頭吞噬（trend_reversal 用）
> 空方趨勢中跌深之後的**創新低價黑K**被**一根紅K完全實體包覆**
> ⚠ 多頭吞噬本身只是空方出場，**不是多方買點**

### 母子晨星
> 破底黑K → 短K → 越過黑K中值的紅K（**那根紅K才是空方力竭的確認**）

**鐵則**：
- 轉折組合的運用**向來是出場使用**
- 一開盤就確認（不必等收盤）
- 空方力竭 ≠ 多方買點

## 1.5 紅K行進判斷

Source: 紅K篇 (一)-(八)

### 紅K四種類型不必細分
> 「重點往往是價格而不是形狀。」

### 三連紅（紅三兵）三類
1. **明顯三連紅**（拉開價格）= 強勢攻擊
2. **緩慢階梯上升型** = 判斷標準「低點推升」（昨低不破）
3. **日出反轉型** = 大敵當前的雛形

### 創新高紅K 隔日的三種訊號

紅K 之後出現的下一根K：
- **十字線（短）= 多空對峙**
- **長十字線 = 多空交戰**
- **上影線創新高 = 攻擊力量曾出現**

→ 三者都代表「攻擊的醞釀」，用「該根的低點」作為續抱標準（前提：必須在攻擊階段）

### 紅K 隔日黑K（弱勢層級）

1. **跌破突破價（前高）→ 短線者立即停損**
2. **未跌破突破價但跳空缺口被回補 → 攻擊失敗**
3. **未跌破任何關鍵價但後續十字線低點被跌破**

### 上升三法
> **一根紅K → 兩到三天整理 → 再拉一根長紅**
- 整理形式：紅K緩慢推 / 十字 / 上影線
- 失敗 = 整理低點被跌破
- **「N字戰法是錯誤觀念」**

### 跳空漲停一條線
- **量小才是強**（籌碼已集中）
- 必要前置：前一天是「關鍵位置的紅K」（突破創新高）
- 有利多消息的一條線 = 大家都買了 → 弱

### 隨機漫步
- 突破紅K 後股價上下無方向 + 無做量 = 沒人要拉
- **應對：找個有漲的紅K 出場**

### 日出攻擊（核心）
> **日出 = K 線的高點與低點都比前一日高**
> 連續日出 + 突破新高 = 日出攻擊

- 強（漂亮）日出：每根 K 實體拉開
- 弱（醜陋）日出：實體萎縮 → 可能演變成大敵當前

行進判斷順序：**突破 → 日出 → 日出攻擊 → 力量辨別 → 力竭**

### 低檔紅K
- 不是多方買點（除非殖利率/價值投資 + 趨勢已改變）
- 多頭吞噬 = 空單回補 + 殖利率投資進場
- 必須有停損 = 再破底

## 1.6 黑K行進判斷

Source: 黑K篇 (一)-(七)

### 黑K vs 紅K 的根本不對稱
> 紅K 需要追高買盤；**黑K 只要沒人買就可形成**——是「沒力量」不是「力量」

→ 不能對稱看待，不能因為「多方紅K買進」就鏡像成「空方黑K放空」

### 黑K = 力竭 ≠ 放空訊號
> 「轉折組合 K 線是出場使用，不能認為空頭結束之後可以直接翻多。」

### 利多 + 長黑（重要警示）
> 利多出長黑 → **未來中期走勢中這根黑K是明顯的壓力區**

### 高檔長黑判斷
- 只看一點：**最高價後來有沒有再突破**
- 沒突破 → 視為套牢區，介入需謹慎
- 「高檔」無法用數字定義，只能回顧過去

不必有黑K吞噬條件——只要高檔長黑（包含未創新高的）就是訊號。

### 一般頸線跌破
> 不一定要是長黑；季線下彎 + 頸線跌破 → 頭部已形成

確認：**跌破後有沒有站回**頸線。

**頸線完整定義（事件七補強）**：
> 季線下彎後的前一個低點，**且此低點上方有 3 個月套牢**

### 區間整理 + 季線下彎 → 頸線跌破
箱型整理 + 箱底跌破 + 季線下彎 = 頸線跌破

### 假性跌破（限制範圍）
> **「只有假性跌破，沒有假性突破。」**
> **「假性跌破只有出現在大盤，個股並不適用。」**

- 條件：連續急跌後跌破 + 反彈馬上站回
- 「打第N隻腳」是話術 → 禁止

### 破底之後的黑K
- 「**空中掉下來的刀子不要接**」
- 例外：「人去樓空」型態——過去拉抬過後跌回原點 → 即使有母子晨星也不應介入
- 空方力竭 = 母子晨星（紅K才算）

### 賣壓中空（精確定義）
> 頸線之下 + **連續黑K 或連續跌停**（不是上下盤跌）

vs **層層套牢**：跌破後上下盤跌 → 每個價位都套牢

「**急跌比慢跌好**」——急跌後形成賣壓中空，反彈空間大。

### 低檔黑K 注意事項
- 一般情況：**不可進場**
- 例外：價值投資/殖利率
- 停損 = 再破底
- **「正常的交易狀況不選擇低檔黑K 後轉折出現來當作進場點」**

## 1.7 跳空行進判斷

Source: 跳空篇 (一)-(五)

### 跳空 = 力量的起點
- vs 十字線（醞釀/中繼）
- **位置 > 大小**：向上 + 創新高、向下 + 創新低 才有特殊意義

### 跳空力量的不對稱性
- 向上跳空：**不計代價的買進** = 力量
- 向下跳空：**沒人承接** ≠ 空方力量發揮

### 缺口理論禁用
「突破缺口、逃逸缺口、竭盡缺口」**沒有使用效果**——不能用「第幾個缺口」判斷。

### 一般跳空 vs 攻擊跳空
**攻擊跳空**：股價突破之後出現的跳空，且該價位過去沒有成交過

**攻擊跳空的精確範圍**：缺口中**過去沒有成交過的價位區段**才算（不是整個跳空缺口）

**判斷規則**：
- 「**這個缺口不能回補**」（攻擊缺口）
- 攻擊缺口下緣 = 短線停損點

**突破跳空 vs 跳空突破**：
- 突破跳空（先突破後跳空）= 強
- 跳空突破（一日內完成）= **不理想**（不必讓游離籌碼覺得強而續抱）

### 攻擊跳空被消除（出場訊號）
過去有攻擊跳空 → 後續向下跳空把攻擊跳空力量消除 → 出場

### 轉折組合中的跳空
跳空反轉、雙鴉躍空、島狀反轉 → 都是**開盤即確認**

### 空方趨勢的向下跳空
- 規避方法：**不買進、不持有**空方趨勢的股票
- 連續跳空下跌 + 沒回補 → **不應認定跌勢結束**
- 例外：總賣出現象（事後才能確認）
- **跌停一條線抄底禁止**

## 1.8 影線行進判斷

Source: 上影線(一)(二) + 下影線

### 上影線真正定義
> 上影線代表盤中「**有出現過拉抬的力量**」（不是壓力）

### 四種位置
1. **一般上影線**
2. **遇壓上影線**（套牢區附近）= 壓力
3. **剛創新高上影線** = 攻擊
4. **攻擊過後上影線** = 不同於剛創新高

### 剛創新高上影線的兩種子類型
- **子類型 A**：低點未破頸線 → 攻擊未失敗
- **子類型 B**：突破又當天跌破頸線但有上影線 → 出場後等隔日不破上影線低點再進

### 核心規則
> 「**當股價低於剛創新高的上影線低點就沒有攻擊的意義**。」

### 「型態突破」vs「單純破前高」
- 型態突破：3 個月整理後突破 → 攻擊起點
- 單純破前高：用攻擊角度判斷 → 中繼

### 上影線 vs 下影線（核心對比）
| 影線 | 收盤狀態 | 動作可預期性 |
|---|---|---|
| 上影線 | 拉抬力量被套 | **被套必拉**（可預期） |
| 下影線 | 拉抬力量賺錢 | **無從判斷**（不可預期） |

### 下影線：完全沒有支撐意義
- 「打第二隻腳」、「收腳」是話術
- 法人出貨線：高檔下影線 + 日落確認

## 1.9 K線事件判斷

Source: 事件 (一)-(十)

### 利空的真正定義

**真正利空**：對經濟面有影響的事件
- 突發性利空：來不及反應（地震、武漢肺炎）
- 可預期利空：知道有事件（總統大選）

**不算利空**：美股下跌（只是新聞，不影響本質）

### 利空當日攻擊股的判斷
- 攻擊股遇大盤大跌會自己拉
- **大跌當日 K 線的低點 = 隔日停損點**
- 隔日跌破當日低 → 攻擊失敗（環境不是因素）

### 利多/利空伴隨的紅K

**利多 + 紅K**：
- 後續不應該回拉 → 攻擊持續
- 後續遇壓或黑K → 沒有期待

**利空 + 紅K（止跌）**：
- 投資角度：不進場
- 交易角度：停損明確 → 可考慮
- 連續跌停跳空段 = 賣壓中空

### 多空循環是錯誤概念
> 「**多空循環只是一種說法**……股價在隨機漫步狀態沒有多空循環。」

→ 禁止用均值回歸、KD 黃金死叉、乖離率等基於循環的概念

### 「沒人要 = 隨機漫步」
攻擊股不會是隨機漫步，隨機漫步股不會被預測。

### 高本益比公司三類
1. 曾經高速成長產業（**避免放空**）
2. 穩定配發股利公司（價差難賺但跌不深）
3. 不可動搖地位（台積電、鴻海）

### 非主流個股的注意事項
- 攻擊不乾脆
- 除權息旺季主力退卻
- 短線交易應專注熱門股

### 缺乏基本面的多方趨勢四種類型
1. 短期看似有基本面（業外收益）
2. 中期沒有營運轉機
3. 突發事件讓本質下降
4. 純題材拉抬

> **「獲利趨勢就是股價的趨勢」**

> **「價穩量縮」= 禁止使用的成語**

### 中期持有 vs 短線交易

**多空波動原理**：多方狀態 = 每段高低點都比前一次高

**真正挑戰**：第一次回檔的幅度無法預測

**「下一個買點」= 突破前高**：給之前有做到第一段的人使用的

### 攻擊階段的大小事件
- **「注意股」不是訊號**（反指標）
- **「主流話題成形 → 攻勢告一段落」**
- 分盤交易出場價會滑（接受跌停價）
- 「攻擊股遇利多」**唯一條件：股價不能回檔**
- 「真正出貨是殺下來出的」

### 兩大壓力類型
- **獲利了結賣壓**：黑K吞噬、高檔長黑、暗夜雙星
  - 比套牢賣壓嚴重
- **套牢賣壓**：層層套牢、頸線之上的賣壓
  - K 線可量化

### 操作起點 vs 結束
- **起點 = 型態突破**（>= 3 個月整理後）
- 不到 3 個月但有低點推升 = 「中繼」（不是起點）
- **結束 = 日出攻擊結束**
- 「**不要看新聞**，不要等反彈賣」

---

# Part 2: Immutable Core Principles (增補自行進ing)

## 🔴 入門已有，行進ing 強化

P1. **K 線意義 > 形狀** — 「相同形狀在不同位置意義不同」
P2. **頸線完整定義**：季線下彎後的前一個低點 + **上方有 3 個月套牢**
P3. **三連紅不是強訊號本身**——要看是否拉開幅度
P4. **下影線無支撐意義**（再次強調）
P5. **不能事後論判定關鍵K線**

## 🔴 行進ing 新增

P6. **力量越大 = 越強，力量不大 = 警示**（醜陋日出可能演變大敵當前）

P7. **黑K 與紅K 不對稱**——不能鏡像看待（多方紅K買 vs 空方黑K空）

P8. **轉折K線只能用於出場**——不可作為翻多翻空依據

P9. **個股不適用假性跌破**——個股頸線跌破即真跌破

P10. **獲利了結賣壓 > 套牢賣壓**——更難量化但更嚴重

P11. **「型態突破」（>= 3 個月整理）才是起點**——突破前高已是中繼

P12. **攻擊跳空的精確下緣** = 過去未成交的價位區段下緣

P13. **跳空突破不理想**——一天完成突破 + 跳空，弱於「先突破再跳空」

P14. **下一根 K 的低點作為停損**：**僅在攻擊階段、且該根 K 有攻擊意義時**才用

P15. **「美股下跌不算台股利空」**——禁止把美股當 regime indicator

P16. **「多空循環」是錯誤概念**——禁止均值回歸 / KD / 乖離

P17. **價穩量縮 = 話術**——禁止這類成語式判斷

P18. **量越來越低 + 股價持續創高 = 警示**——主力被套等出貨

P19. **「主流話題成形 → 攻勢結束」**

P20. **獲利的股票不應回拉讓人有低點可買**——攻擊資金不會給散戶低買機會

---

# Part 3: System Implementation Map（精確補完入門 STUB）

## 3.1 替換 `kline/exit/ma60_neckline.py`（STUB → 實作）

**Course source**: 1.2 + 1.3 + 黑K篇(三) + 事件(七)

```python
def mark(df, entries=None):
    """精確頸線跌破 (vs neckline_break 的 prior_low_20 proxy)"""
    g = df.groupby("ticker")
    
    # 季線斜率變化
    ma60_slope = df["ma60"] / g["ma60"].shift(5) - 1
    ma60_just_turned_down = (ma60_slope < 0) & (g.shift(1)["ma60_slope_5d"] >= 0)
    
    # 季線下彎後的前一個低點：取最近的 swing low (5-bar local min)
    # 這個 swing low 上方必須有 3 個月以上的套牢
    swing_low = ...  # 需 swing-low detector
    
    # 頸線跌破
    return df["close"] < swing_low
```

## 3.2 替換 `kline/entry/sunrise.py`（STUB → 實作）

**Course source**: 紅K篇(七)

```python
def detect(df):
    """日出攻擊 = 突破新高 + 連續日出"""
    g = df.groupby("ticker")
    
    is_breakout = (df["close"] > df["prior_high_60"]) & (df["close"] > df["ma60"])
    is_sunrise = (df["high"] > df["prev_high"]) & (df["low"] > df["prev_low"])
    
    # 連續 3 天日出 + 起點為 breakout
    sunrise_count = is_sunrise.groupby(df["ticker"]).rolling(3, min_periods=3).sum().values
    return (sunrise_count >= 3) & ...
```

## 3.3 替換 `kline/scoring/shadow_position.py`（STUB → 實作）

**Course source**: 上影線(一)(二)

```python
def score(df):
    s = pd.Series(0.0, index=df.index)
    
    is_new_high = df["high"] > df["prior_high_60"]
    has_upper = df["upper_shadow_ratio"] >= 1.0
    is_at_overhead = df["overhead_supply_layer"] >= 1
    
    # 剛創新高上影線 = 攻擊
    s += np.where(is_new_high & has_upper & df["is_red"], 10, 0)
    
    # 套牢區上影線 = 壓力
    s -= np.where(is_at_overhead & has_upper & ~is_new_high, 10, 0)
    
    # 下影線：完全忽略（不加不扣）
    return s
```

## 3.4 替換 `kline/exit/reversal_k/dark_double_star.py`（修正 STUB）

**Course source**: 1.4 暗夜雙星

```python
def mark(df, entries=None):
    """暗夜雙星 = 長黑摜破兩根併排相似紅K"""
    g = df.groupby("ticker")
    
    # 前兩根 K 並排相似（high/low 接近、實體紅K）
    similar_pair = (
        (df["high"] / g["high"].shift(1) - 1).abs() < 0.02
        & (df["low"] / g["low"].shift(1) - 1).abs() < 0.02
        & df["is_red"]
        & g["is_red"].shift(1)
    )
    
    # 今日是長黑 + 跌破前一根低點
    is_long_black = df["is_black"] & (df["body_pct"] >= 0.04)
    breaks_below_pair = df["close"] < g["low"].shift(1)
    
    return (g.shift(1, similar_pair) & is_long_black & breaks_below_pair).fillna(False)
```

## 3.5 替換 `kline/exit/reversal_k/bearish_engulfing.py`

**Course source**: 1.4 黑K吞噬 + 事件(九)

```python
def mark(df, entries=None):
    """黑K吞噬 = 紅K 後黑K 完全包覆前紅K 實體"""
    g = df.groupby("ticker")
    prev_red = g["is_red"].shift(1)
    prev_open = g["open"].shift(1)
    prev_close = g["close"].shift(1)
    
    is_black = df["is_black"]
    engulfs = (df["open"] >= prev_close) & (df["close"] <= prev_open)
    
    return (prev_red & is_black & engulfs).fillna(False)
```

## 3.6 替換 `kline/exit/reversal_k/enemy_at_gate.py`

**Course source**: 1.4 大敵當前 + 紅K篇(一)

```python
def mark(df, entries=None):
    """大敵當前 = 三根紅K拉不開 + 第四根長黑跌破第一根紅K中值"""
    g = df.groupby("ticker")
    
    # 前三根都是小紅K
    three_small_reds = (
        g["is_red"].shift(1) & g["is_red"].shift(2) & g["is_red"].shift(3)
        & (g["body_pct"].shift(1) < 0.02)
        & (g["body_pct"].shift(2) < 0.02)
        & (g["body_pct"].shift(3) < 0.02)
    )
    
    # 第一根紅K 的中值
    k3_mid = (g["open"].shift(3) + g["close"].shift(3)) / 2
    
    # 今日長黑跌破 K3 中值
    today_breaks = df["is_black"] & (df["body_pct"] >= 0.03) & (df["close"] < k3_mid)
    
    return (three_small_reds & today_breaks).fillna(False)
```

## 3.7 替換 `kline/exit/reversal_k/evening_star.py`

**Course source**: 1.4 夜星棄嬰 + 關鍵K線(四)

```python
def mark(df, entries=None):
    """夜星棄嬰 = 遇壓紅K → 十字線 → 長黑跌破紅K中值 + 回補跳空缺口"""
    g = df.groupby("ticker")
    
    # K1: 遇壓紅K (overhead_supply_layer >= 1) 創新高紅K
    k1_red_at_pressure = (
        g["is_red"].shift(2)
        & (g["overhead_supply_layer"].shift(2) >= 1)
    )
    
    # K2: 十字線
    k2_doji = g["is_doji"].shift(1)
    
    # K3: 長黑跌破 K1 中值 + 回補跳空（如果 K1 與 K2 有缺口）
    k1_mid = (g["open"].shift(2) + g["close"].shift(2)) / 2
    today_breaks = df["is_black"] & (df["body_pct"] >= 0.03) & (df["close"] < k1_mid)
    
    return (k1_red_at_pressure & k2_doji & today_breaks).fillna(False)
```

## 3.8 替換 `kline/exit/reversal_k/two_crows.py`

**Course source**: 1.4 雙鴉躍空

```python
def mark(df, entries=None):
    """雙鴉躍空 = 高檔壓力區跳空開高收黑 → 隔日小黑 → 開盤向下跳空"""
    g = df.groupby("ticker")
    
    # K1: 高檔壓力區 + 跳空開高 + 黑K
    k1 = (
        (g["overhead_supply_layer"].shift(2) >= 1)
        & (g["open"].shift(2) > g["high"].shift(3))
        & g["is_black"].shift(2)
    )
    
    # K2: 小黑K
    k2 = g["is_black"].shift(1) & (g["body_pct"].shift(1) < 0.02)
    
    # K3: 開盤向下跳空
    k3 = df["open"] < g["low"].shift(1)
    
    return (k1 & k2 & k3).fillna(False)
```

## 3.9 替換 `kline/exit/reversal_k/gap_reversal.py`

**Course source**: 1.4 跳空反轉

```python
def mark(df, entries=None):
    """跳空反轉 = 長紅或創新高 → 隔日走低收黑 → 再隔日向下跳空"""
    g = df.groupby("ticker")
    
    # K1: 長紅K 或創新高
    k1 = g["is_red"].shift(2) & (
        (g["body_pct"].shift(2) >= 0.03) | (g["high"].shift(2) >= g["prior_high_60"].shift(2))
    )
    
    # K2: 黑K，且 close 低於 K1 close
    k2 = g["is_black"].shift(1) & (g["close"].shift(1) < g["close"].shift(2))
    
    # K3: 向下跳空
    k3 = df["open"] < g["low"].shift(1)
    
    return (k1 & k2 & k3).fillna(False)
```

## 3.10 補入門系統的新出場條件（行進ing 新增）

### `gap_attack_filled` （攻擊跳空被消除）

```python
def mark(df, entries):
    """攻擊跳空缺口被回補 → 攻擊失效"""
    # 進場後的攻擊跳空缺口下緣記錄
    # 跌破此下緣 → 出場
    ...
```

### `breakout_price_break` （突破價跌破，比 breakout_low_break 更早）

**Course source**: 紅K篇(五)

```python
def mark(df, entries):
    """跌破突破價（prior_high_60）→ 比突破K低點跌破早"""
    breakout_price = df["prior_high_60"].where(entries).groupby(df["ticker"]).ffill()
    return df["close"] < breakout_price
```

### `prev_day_low_break_gated` （前一日低點跌破，加 gate）

**Course source**: 紅K篇(二)

```python
def mark(df, entries):
    """僅在『前一根 K 有攻擊意義』時才觸發"""
    g = df.groupby("ticker")
    
    # 前一根 K 是「攻擊意義」：紅K創新高 / 創新高上影線 / 紅K隔日十字
    prev_attack = (
        (g["is_red"].shift(1) & (g["high"].shift(1) > g["prior_high_60"].shift(1)))
        | (g["upper_shadow_ratio"].shift(1) >= 1.0) & (g["high"].shift(1) > g["prior_high_60"].shift(1))
        | g["is_doji"].shift(1)  # 紅K隔日的十字
    )
    
    return prev_attack & (df["close"] < df["prev_low"])
```

### `sunrise_attack_end` （日出攻擊結束）

**Course source**: 紅K篇(七) + 事件(十)

```python
def mark(df, entries):
    """連續日出後第一根非日出 → 攻擊結束"""
    g = df.groupby("ticker")
    
    in_sunrise = ((df["high"] > df["prev_high"]) & (df["low"] > df["prev_low"]))
    was_sunrise = g["high"].shift(1) > g["prev_high"].shift(1) & g["low"].shift(1) > g["prev_low"].shift(1)
    
    return was_sunrise & ~in_sunrise
```

### `prev_low_break_swing` （多空波動：前次低點跌破）

**Course source**: 事件(七)

```python
def mark(df, entries):
    """進場後第一個 swing low 被跌破 → 中期趨勢改變"""
    # 需 swing low detector
    ...
```

### `high_long_black` （高檔長黑，無需有吞噬）

**Course source**: 黑K篇(二) + 事件(九)

```python
def mark(df, entries):
    """高檔長黑——不必有吞噬，只要在拉抬過後出現長黑就算"""
    g = df.groupby("ticker")
    
    # 過去 60 日內有過明顯拉抬（high / low > 1.3）
    is_high_zone = g["high"].shift(1).rolling(60).max() / g["low"].shift(1).rolling(60).min() >= 1.3
    
    is_long_black = df["is_black"] & (df["body_pct"] >= 0.04)
    
    return is_high_zone & is_long_black
```

## 3.11 補入門系統的新 Scoring 因子

### `is_pattern_breakout` vs `is_high_breakout`

**Course source**: 事件(十)

```python
def score(df):
    """型態突破 (>= 3 個月整理) 加分高於單純破前高"""
    s = pd.Series(0.0, index=df.index)
    
    # 過去 60 日（~ 3 個月）箱型整理
    is_in_range = (df["prior_high_60"] / df["prior_low_60"] - 1) < 0.15
    is_breakout = df["close"] > df["prior_high_60"]
    
    is_pattern = is_breakout & is_in_range
    is_simple = is_breakout & ~is_in_range
    
    s += np.where(is_pattern, 15, 0)
    s += np.where(is_simple, 5, 0)
    return s
```

### `is_attack_gap_clean` （攻擊跳空 + 左側無套牢）

**Course source**: 跳空篇(三)

```python
def score(df):
    """攻擊跳空 + 上方無套牢 = 強訊號"""
    s = pd.Series(0.0, index=df.index)
    
    is_gap = df["open"] > df["prev_high"]
    is_new_high = df["close"] > df["prior_high_60"]
    is_clean = df["overhead_supply_layer"].fillna(0) <= 0
    
    s += np.where(is_gap & is_new_high & is_clean, 15, 0)
    
    # 「跳空突破」（一日內完成）扣分
    is_one_day_breakout = is_gap & is_new_high & (df["prev_close"] < df["prior_high_60"].shift(1))
    s -= np.where(is_one_day_breakout, 5, 0)
    
    return s
```

### `volume_trend_warning` （量縮 + 股價創新高）

**Course source**: 事件(六)

```python
def score(df):
    """量越來越低 + 股價持續創高 → 警示扣分"""
    g = df.groupby("ticker")
    
    is_volume_shrinking = df["avg_volume_20"] / g["avg_volume_20"].shift(20) < 0.7
    is_at_new_high = df["close"] > df["prior_high_60"]
    
    return -10 * (is_volume_shrinking & is_at_new_high).astype(float)
```

---

# Part 4: Forbidden Patterns (禁止項清單)

依本系列課程**明確禁止**：

| 禁止 | 來源章節 |
|---|---|
| 「N 字戰法」 | 紅K篇(三) |
| 「打第二/三/四隻腳」 | 黑K篇(四) + 下影線 |
| 「裸K戰法」 | 認知篇 |
| RSI / KD / MACD / 乖離 / 黃金交叉 / 死亡交叉 | 認知篇 |
| 「箱底買進、箱頂賣出」 | 前言篇 |
| 「假性突破」（無此概念） | 黑K篇(四) |
| 「下影線收腳」 = 支撐 | 下影線 + 黑K篇(四) |
| 個股「假性跌破」 | 黑K篇(四) |
| 「拉回布局」、「逢低承接」（攻擊狀態外） | 多處 |
| 「美股下跌 = 台股利空」 | 事件(一) |
| 「多空循環」 | 事件(二) |
| 「價穩量縮」 | 事件(六) |
| 多頭吞噬作為純多方買點 | 紅K篇(八) + 黑K篇(七) |
| 「來回操作」（基於過去獲利賺價差） | 黑K篇(五) |
| 「公告注意股 = 飆股」 | 事件(八) |
| 缺口理論計數（突破/逃逸/竭盡） | 跳空篇(一) |
| 摸頭、摸底 | 多處 |
| 攤平 | 多處 |

---

# Part 5: Quantitative Proxy Limitations (新增)

| 課程概念 | 我們的代理 | 限制 |
|---|---|---|
| 「3 個月套牢」型態突破 | 「過去 60 日 range < 15%」 | 不精確；不到 60 日的箱型也合理但被忽略 |
| 「過去從未成交的價位」（攻擊跳空下緣） | `prior_high_60` | 60 日太短；應該用 `prior_high_240` 或 `historical_max` |
| 「資金力量大」 | `volume_ratio` | 量大可能是做量假象，無法直接區分 |
| 「攻擊已久 vs 剛突破」 | 比較 `prior_high_60` vs `prior_high_240` | 粗代理 |
| 「主流話題」 | 無 | 需外部產業 / 新聞資料 |
| 「資訊不對稱」（內線資訊） | 無 | 無法量化 |
| 「主力意圖」 | 量 + 籌碼變化 | 籌碼資料需外部來源 |
| 「3 個月整理 + 季線下彎」頸線 | `prior_low_20` | 缺少 MA60 方向 + 套牢時長確認 |

---

# Part 6: Review Checklist (基於行進ing 補充)

每次系統變更後檢視：

## 行進判斷
- [ ] 條件是否限定在「攻擊階段」？（避免低檔錯誤套用）
- [ ] 「前一根 K 有攻擊意義」的 gate 是否設置？（紅K篇二）
- [ ] 是否區分「型態突破」vs「單純破前高」？

## 跳空
- [ ] 攻擊跳空 vs 一般跳空是否區分？
- [ ] 攻擊跳空下緣是否用「未成交價位下緣」而非「整個缺口下緣」？
- [ ] 是否區分「突破跳空」vs「跳空突破」？

## 影線
- [ ] 上影線是否依位置區分意義？
- [ ] 下影線是否完全不加分？

## 轉折組合
- [ ] 暗夜雙星是否有「兩根併排相似K線」前置？
- [ ] 夜星棄嬰是否有「十字線」中間？
- [ ] 大敵當前是否要求「三根紅K拉不開」？
- [ ] 跳空反轉是否「3 根 K 線結構」完整？

## 出場
- [ ] 「跌破突破價」是否早於「跌破突破K低」觸發？
- [ ] 「攻擊跳空被消除」是否在系統中？
- [ ] 「日出攻擊結束」是否實作？
- [ ] 「上影線低點跌破」是否在系統中？
- [ ] 「前次低點跌破（多空波動）」是否實作？

## 禁忌
- [ ] 系統是否未引入禁止項（見 Part 4）？
- [ ] 是否避免事後論的判定？

---

# Part 7: Past Mistakes（補充自行進ing）

1. **`dark_double_star` 缺少「兩根併排相似 K 線」前置** — 課程明確要求
2. **`gap_fill` 用 `excess_gap >= 2%` 是粗代理** — 應該用「攻擊跳空 + 缺口下緣」精確判定
3. **`neckline_break` 用 `prior_low_20`** — 應該用「季線下彎後前低 + 上方 3 個月套牢」
4. **`prev_day_low_break` 無條件套用** — 必須有「前一根 K 攻擊意義」gate
5. **未實作「攻擊跳空被消除」出場** — 課程明確的攻擊失效訊號
6. **未實作「上影線低點跌破」出場** — 攻擊力量消失的明確訊號
7. **未實作「日出攻擊結束」出場** — 課程明確的攻擊結束判斷
8. **未實作「跌破突破價」出場** — 比 `breakout_low_break` 更早
9. **shadow_position 是 STUB** — 課程在上影線(一)(二) 給了完整邏輯
10. **未區分「型態突破」vs「單純破前高」** — 影響起點 vs 中繼的判斷

---

# Part 8: Future Implementation Roadmap

讀完 K線行進ing 後，下一個子分類：

## 多空轉折組合K線 (26 articles, ID: `C99F5AC7CA9FED14A557A7A4A5592AA5`)

- 補完轉折組合的所有結構定義
- 包含：包覆線（吞噬）、孕線、晨星、母子雙星、突破雙星、孤島型態、三黑兵、外側三黑、單日反轉
- 行進ing 已經給了一些結構（暗夜雙星、夜星棄嬰、大敵當前、雙鴉躍空、跳空反轉、母子晨星），多空轉折會給更精細的定義
- 預估補完後系統可達 90-95%

## 期望實作優先序

1. **HIGH（行進ing 已給足）**：
   - `sunrise.py`、`shadow_position.py` 完成 STUB 替換
   - `dark_double_star.py` 修正
   - `breakout_price_break.py` 新增
   - `gap_attack_filled.py` 新增
   - `sunrise_attack_end.py` 新增

2. **MEDIUM（需要更多技術判斷）**：
   - `ma60_neckline.py` 完整實作（需 swing-low detector）
   - 5 個 reversal_k STUB 替換（雙鴉、夜星、大敵當前、跳空反轉、空頭吞噬）
   - `is_pattern_breakout` feature

3. **LOW（依賴外部資料）**：
   - 主流產業熱度
   - 月營收成長率整合
   - 內線資訊識別（不可能）

---

# Appendix: 行進ing 39 篇文章索引

完整列表見 `docs/K線行進ing/index.json`

| Section | Articles | Files |
|---|---|---|
| 關鍵K線延伸篇 | 4 | 01-04 |
| 行進判斷-前言/認知 | 2 | 05-06 |
| 紅K篇 | 8 | 07-14 |
| 黑K篇 | 7 | 15-21 |
| 跳空篇 | 5 | 22-26 |
| 影線篇 | 3 | 27-29 |
| K線事件判斷 | 10 | 30-39 |
| **總計** | **39** | |
