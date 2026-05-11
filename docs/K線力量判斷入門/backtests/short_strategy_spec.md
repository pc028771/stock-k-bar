# 課程放空教學萃取與量化代理設計（Task 17）

本文件針對「K線力量判斷入門」課程中與放空、回補有關的條文，逐條萃取課程語意並轉為可在日K OHLCV 資料上計算的量化代理。本文件遵循專案 `CLAUDE.md` 的核心限制：**只能用課程明確教過的概念**，凡課程未明確說明量化標準者，必須明白標註「課程沒有明確說明量化標準」，禁止以常識或一般交易慣例補完。

---

## 0. 來源與限制聲明

### 主要課程來源

| 編號 | 文章 | 課程位置 |
| --- | --- | --- |
| 第 50 篇 | `📝【買點賣點】放空與回補的要點講解` | `index.json` order=50；URL=`/articles/D8EBCA38C98B0BD5285CFD3E4E2D2FCE` |
| 第 7 篇 | `📝【單一K線】高檔區域的長黑K` | `index.json` order=7；URL=`/articles/C838747B22625440D61F5EA1DD18DFFB` |
| 第 33 篇 | `📝【突破跌破】假性跌破的實務意義` | `index.json` order=33 |
| 第 36 篇 | `📝【突破跌破】整理趨勢進入型態判斷的關鍵-假性跌破之後` | `index.json` order=36 |
| 第 16 篇 | `📝【關鍵K線】趨勢改變的關鍵K線` | `index.json` order=16 |
| 第 18/19 篇 | `📝【型態判斷】頭部底部型態合併要點(一)(二)` | `index.json` order=18, 19 |

### 課程文字摘要檔（在本 repo 的二次來源）

第 50 篇本身的課程內文與圖例**未在本 repo `images/` 內保存**（`manual-images-needed.md` 低優先區清單第 125 行，狀態為「可回補但未補」）。因此本文件對第 50 篇的引用，使用本 repo 內已彙整的官方策略摘要：

- `docs/K線力量判斷入門/strategy-indicators.md` §8「放空與回補」（L161-171）
- `docs/K線力量判斷入門/strategy-indicators.md` §10「圖例補強後的規則 / 假性跌破與真正跌破」（L283-311）
- `docs/K線力量判斷入門/strategy-indicators.md` §10「頭部/底部型態與箱型切換」（L346-379）
- `docs/K線力量判斷入門/backtests/pattern_labeling_spec.md` §2「頸線」（L111-163）

第 7 篇「高檔區域的長黑K」與第 33/36 篇「假性跌破」之圖例存在於 `images/` 內，可直接取用。

### 課程核心警示（不可違反）

`strategy-indicators.md` §8 L163 明文：

> 「放空邏輯與多方攻擊**不是簡單鏡像**，需確認弱勢、跌破、反彈遇壓、買盤不繼。」

由此延伸的禁制：

1. 不能把 `breakout_attack`（突破攻擊）反向直接當作放空訊號。
2. 假跌破收回（`false_breakdown_reclaim`）是**回補訊號**，不是放空進場訊號（同條 L164）。
3. 課程未說明的執行細節（盤中時機、倉位比例、停損百分比、加碼節奏），一律標註為「課程沒有明確說明量化標準」，不自行補完。

---

## 1. 放空進場（short_entry）：四要素萃取

`strategy-indicators.md` §8 L163 明確列出放空進場必須同時觀察四個要素：「弱勢、跌破、反彈遇壓、買盤不繼」。以下逐項展開。

### 1.1 弱勢

**課程出處**：

- `strategy-indicators.md` §8 L163：「放空…需確認**弱勢**…」
- `strategy-indicators.md` §5 L112：「季線與K線高低點可用來判斷中期多空背景。」
- `strategy-indicators.md` §10「頭部/底部型態與箱型切換」L356-358：「跌破頸線後反彈，若反彈進不回頸線，則進入新的下降箱型。」
- `pattern_labeling_spec.md` §2 L122：「`ma60_rollover` 點：`ma60` 由上升轉為下降的第一根 K 線。」

**課程語意**：弱勢不是急跌後短暫超賣，而是指**中期趨勢已偏空**——具體表現為股價跌至季線下方、季線方向由上轉下、頸線跌破後反彈站不回。

**可量化代理**：

| 代理欄位 | 公式 | 說明 |
| --- | --- | --- |
| `close < ma60` | 收盤價低於季線 | 直接對應 §5 L112「季線判斷中期多空背景」 |
| `ma60_down` | `ma60(t) / ma60(t-5) - 1 < 0` | 對應 `pattern_labeling_spec.md` §2 L122 的 `ma60_slope`；視窗 5 日為 spec 預設 |

**無法量化的部分**：

- 課程提到「弱勢」可包含「頸線跌破後反彈站不回」與「跌勢中高低點規律改變」，但未指定**反彈次數**、**站不回的天數**、**高低點規律失效的判定窗格**。此部分**課程沒有明確說明量化標準**，本規格僅以 `close < ma60` 與 `ma60_down` 為背景代理，未強制加入「反彈站不回頸線」的計次條件。

### 1.2 跌破

**課程出處**：

- `strategy-indicators.md` §8 L163：「放空…需確認…**跌破**…」
- `strategy-indicators.md` §10「假性跌破與真正跌破」L308-310：
  ```
  key_level = min(prior_swing_low, neckline, range_low)
  real_breakdown = close < key_level and close_next < key_level and rebound_high_next_m <= key_level
  ```
- `pattern_labeling_spec.md` §2 L138-144：頸線跌破需「收盤跌破 + 隔日確認 + M 日內反彈站不回」。
- 課程第 33 篇「假性跌破的實務意義」與第 36 篇「整理趨勢進入型態判斷的關鍵」的圖例（已收錄在 `images/【突破跌破】假性跌破的實務意義-*.jpg`、`images/【突破跌破】整理趨勢進入型態判斷的關鍵-假性跌破之後-*.jpg`）：真正跌破發生於「整理之後」，由「長黑K」完成，且反彈站不回。

**課程語意**：跌破要件——「整理後」+「收盤跌破關鍵價（頸線／前波低點／區間下緣）」+「隔日收盤仍在關鍵價下方」+「反彈高點未站回關鍵價」。判定一律以**收盤**為準，不以盤中價格為準（`CLAUDE.md` 課程框架點 1；`strategy-indicators.md` §6 L131）。

**可量化代理**：

| 代理欄位 | 公式 | 對應課程出處 |
| --- | --- | --- |
| `neckline_proxy` | `prior_low_20`（最近 20 日低點） | `pattern_labeling_spec.md` §2 L122-123 將頸線定義為「`ma60_rollover` 前最近的 swing_low」；專案 `kline_course_backtest.py` L249 採用 `prior_low_20` 作為粗略代理 |
| `neckline_break` | `close(t) < neckline_proxy` | §10 L308 |
| `neckline_break_confirm` | `close(t+1) < neckline_proxy` | §10 L310；`pattern_labeling_spec.md` §2 L142 |
| `in_range_20` | 過去 20 日 `(high - low) / low ≤ 0.15` | `pattern_labeling_spec.md` §1「箱型存在」L77-101 |
| `long_black_k` | `close < open` 且 `body_pct ≥ 0.015` | 課程第 7 篇「高檔區域的長黑K」+ §10 L307「真正跌破由整理後長黑完成」 |

**無法量化的部分**：

- 課程定義的 `key_level = min(prior_swing_low, neckline, range_low)`（§10 L308），其中 `swing_low` 嚴格需用「左右各 k 根 K 棒的低點極值」識別，且頸線需嚴格綁定「`ma60_rollover` 前最近的 swing_low」。本規格採 `prior_low_20` 作為粗略代理，並未嚴格實作 `swing_low` 與 `ma60_rollover` 配對；嚴格版的 `key_level` 量化未在現有 add_signals 內實作，**課程沒有明確說明 `prior_low_20` 與 `swing_low` 何者應為標準窗格**。
- 「反彈高點未站回關鍵價」的觀察視窗 `m`：§10 L310 寫成 `rebound_high_next_m`，但 m 的具體日數**課程沒有明確說明量化標準**。本規格未強制加入「未來 m 日反彈未站回」條件，因為這屬於前瞻資訊；改以「隔日收盤仍在關鍵價下方」作為弱化的後驗確認。

### 1.3 反彈遇壓

**課程出處**：

- `strategy-indicators.md` §8 L163：「放空…需確認…**反彈遇壓**…」
- `strategy-indicators.md` §10「頭部/底部型態與箱型切換」L357：「正常多空易位是跌破頸線後轉空，**若反彈回頸線但無法站回，反彈是離場機會而不是支撐成立**。」
- `pattern_labeling_spec.md` §2 L150：`neckline_retest_fail = high(t) >= neckline_price and close(t) < open(t) and close(t) < neckline_price`

**課程語意**：跌破發生後，股價反彈回到關鍵價（頸線、前波套牢區、季線等壓力區），但**收盤無法站回**，此為「反彈遇壓」的確認形式。

**可量化代理**（嚴格版）：

| 代理欄位 | 公式 | 課程出處 |
| --- | --- | --- |
| `neckline_retest_fail` | 跌破後某日 `high ≥ neckline_proxy` 且 `close < neckline_proxy` 且 `close < open` | `pattern_labeling_spec.md` §2 L150 與 `strategy-indicators.md` §10 L379 直接給出 |

**現行 `kline_course_backtest.py` 的弱化代理**：

現有實作（`kline_course_backtest.py` L281）在 `short_entry` 中，因為「`real_breakdown_after_range` 內已包含『隔日收盤仍跌破』」，並未強制要求 `neckline_retest_fail` 出現過。L281 註解明白寫：「『反彈遇壓』→ 無法精確量化（課程未說明盤中確認時機），此處用 `ma60_down` 作背景代理」。

**結論**：

- **嚴格代理（建議升級方向）**：在 `short_entry` 條件中加入「**跌破發生後 1～M 日內出現至少一次 `neckline_retest_fail`**」。這部分與 `pattern_labeling_spec.md` 一致，課程語意完整。
- **目前實作（粗略代理）**：以 `ma60_down` + `close < ma60` 作為「整體偏空、反彈空間有限」的背景代理，並非課程意義上「反彈到壓力區無法站回」的直接量化。
- **無法量化的部分**：「反彈到何種價位才算遇壓」（除頸線外，是否也含季線、前高、密集套牢區）以及「M 日的具體值」**課程沒有明確說明量化標準**。

### 1.4 買盤不繼

**課程出處**：

- `strategy-indicators.md` §8 L163：「放空…需確認…**買盤不繼**。」
- `strategy-indicators.md` §1 L16：「`black_k_weakness`：黑K不一定是賣壓沉重，也可能是低檔買盤不繼。」
- 課程第 7 篇「高檔區域的長黑K」（`images/【單一K線】高檔區域的長黑K-*.jpg`）：高檔出現長黑K代表前段攻擊力量消失、買盤無法延續。
- `strategy-indicators.md` §1 L23：`close_position = (close - low) / (high - low)`。

**課程語意**：「買盤不繼」指的是**買方無力護盤** — 表現為收黑K、收盤位置偏低、量縮或反彈後無人接手。第 7 篇的長黑K圖例則是此語意在高檔的具體形式。

**可量化代理**：

| 代理欄位 | 公式 | 課程出處 |
| --- | --- | --- |
| `black_k` | `close < open` | §1 L14 |
| `long_black_k` | `black_k` 且 `body_pct ≥ 0.015` | 課程第 7 篇「長黑K」配合 §10 L307「真正跌破由整理後長黑完成」 |
| `close_position_low` | `(close - low) / (high - low) ≤ 0.3` | §1 L23 提供 `close_position`，但低位門檻**課程沒有明確說明量化標準**；0.3 為實作參考 |

**無法量化的部分**：

- **量縮**：課程多處提到「量縮」是買盤不繼的特徵之一（§6 L129「區間整理要觀察上下緣、量縮…」），但**課程沒有明確說明量縮的量化標準**（例如：「成交量低於 20 日均量 70%」、「連續 N 日縮量」等門檻皆未在課程內出現）。本規格不加入成交量代理。
- **連續黑K日數**：「買盤不繼」是否要求連續 N 日黑K、或是反彈段內紅K比例下降，**課程沒有明確說明量化標準**。

### 1.5 short_entry 量化定義（整合 1.1–1.4）

對應 `kline_course_backtest.py` L289-293 的現行實作：

```python
short_entry = (
    real_breakdown_after_range          # = (1.2 跌破) + (1.4 買盤不繼: long_black_k) + (1.1 弱勢: in_range_20 + ma60_down)
    and close < ma60                    # 1.1 弱勢：收盤在季線下方
)

# 其中：
real_breakdown_after_range = (
    ~panic_drop                         # 排除急跌情境（→ 急跌後跌破易屬假跌破，§10 L292）
    and black                           # 1.4 黑K
    and body_pct >= 0.015               # 1.4 長黑K（實體 ≥ 1.5%）
    and close < prior_low_20            # 1.2 跌破頸線代理
    and next_close < prior_low_20       # 1.2 隔日確認（§10 L310）
    and in_range_20                     # 1.1 + 1.2 前段箱型整理（pattern_labeling_spec.md §1）
    and ma60_down                       # 1.1 季線下彎（pattern_labeling_spec.md §2 L122）
)
```

**已量化的課程條件**：弱勢（季線下方 + 季線下彎）、跌破（收盤跌破 prior_low_20 + 隔日確認）、買盤不繼（長黑K）。

**未嚴格量化、現行用粗略代理替代的課程條件**：

- **反彈遇壓**：用 `ma60_down + close < ma60` 替代，非課程直接定義。嚴格升級方向：加入 `neckline_retest_fail` 觀察。
- **頸線**：用 `prior_low_20` 替代嚴格的 `swing_low + ma60_rollover` 配對。
- **未來反彈站不回（`rebound_high_next_m ≤ key_level`）**：未加入（避免前瞻），以 `next_close < neckline_proxy` 作弱化後驗。

---

## 2. 回補訊號（cover_signal）：四要素萃取

`strategy-indicators.md` §8 L164：

> 「回補可用**趨勢改變**、**跌勢攻擊消失**、**假跌破收回**或**關鍵K線確認**。」

四個回補依據逐項展開。

### 2.1 趨勢改變

**課程出處**：

- `strategy-indicators.md` §8 L164：「回補可用**趨勢改變**…」
- `strategy-indicators.md` §5 L122：`ma_reclaim = close > ma_60 and prior_close < ma_60`
- 課程第 16 篇「趨勢改變的關鍵K線」（`index.json` order=16）。

**課程語意**：放空持倉後，若中期趨勢結構改變（季線方向由下轉上、收盤站回季線），即視為趨勢改變、回補時機。

**可量化代理**：

| 代理欄位 | 公式 | 課程出處 |
| --- | --- | --- |
| `close > ma60` | 收盤站回季線 | §5 L122 `ma_reclaim` |

**無法量化的部分**：

- 「站回幾天才算站穩」、「是否需要季線斜率同步翻揚」**課程沒有明確說明量化標準**。本規格使用單日 `close > ma60` 即觸發回補（偏保守，傾向早回補）。

### 2.2 跌勢攻擊消失

**課程出處**：

- `strategy-indicators.md` §8 L164：「回補可用…**跌勢攻擊消失**…」
- `strategy-indicators.md` §8 L171：`cover_signal = false_breakdown_reclaim or close > prior_reversal_high`
- `strategy-indicators.md` §8 L170：`lower_high_count`（高點越來越低的計數，反向即攻擊消失）。

**課程語意**：放空期間下跌的攻擊力道停止——具體表現為「下跌過程中的反彈高點被突破」（不再形成 lower high）。

**可量化代理**：

| 代理欄位 | 公式 | 課程出處 |
| --- | --- | --- |
| `close > prior_high_20` | 收盤突破近期高點 | §8 L171 `close > prior_reversal_high`（`prior_reversal_high` 課程未指定窗格，本規格以 `prior_high_20` 作為近期反彈高點代理） |

**無法量化的部分**：

- 嚴格的 `prior_reversal_high` 應為「跌勢中最近一個反彈波段的 swing_high」，需要 `swing_high` 演算法（左右 k 根 K 棒）。本規格用 `prior_high_20` 粗略代理，**課程沒有明確說明窗格 k 的具體值**。

### 2.3 假跌破收回（**這是回補訊號，不是放空進場訊號**）

**課程出處**：

- `strategy-indicators.md` §8 L164：「回補可用…**假跌破收回**…」
- `strategy-indicators.md` §6 L140：`false_breakdown_reclaim = low < range_low and close > range_low`
- `strategy-indicators.md` §10 L308-311：
  ```
  false_breakdown = low < key_level and close >= key_level
  false_breakdown_confirm = false_breakdown and close_next > key_level
  ```
- 課程第 33 篇「假性跌破的實務意義」、第 36 篇「整理趨勢進入型態判斷的關鍵-假性跌破之後」。

**課程語意**：放空後若關鍵價跌破為「假性跌破」（盤中跌破但收盤收回，或隔日重新站回），代表先前的跌破訊號失效、應回補。

**重要邊界（不可違反）**：

- 假跌破收回是**回補**訊號，**不是放空進場**訊號。`CLAUDE.md` 不可自行混用。
- 與 `false_breakdown_reclaim` 的長方向策略（用作做多進場）為不同方向應用。

**可量化代理**：

| 代理欄位 | 公式 | 課程出處 |
| --- | --- | --- |
| `false_breakdown_reclaim` | `panic_drop and low < prior_low_60 and close ≥ prior_low_60` | `kline_course_backtest.py` L205-209；對應 §6 L140 與 §10 L308 |

**無法量化的部分**：

- 課程的 `false_breakdown_confirm` 還要求「隔日收盤站回」（§10 L309），現行 `kline_course_backtest.py` 的 `false_breakdown_reclaim` 只用當日 close 站回，未加入隔日確認；這屬於現行實作的弱化版本，課程本身已有定義，未做進一步加嚴的決定屬於工程選擇。

### 2.4 關鍵K線確認

**課程出處**：

- `strategy-indicators.md` §8 L164：「回補可用…**關鍵K線確認**。」
- `strategy-indicators.md` §1 L18：「`key_k_line`：能改變前後趨勢的K線，而不是單純顏色或長短。」
- 課程第 16 篇「趨勢改變的關鍵K線」、第 17 篇「關鍵K線的意義與用途」。

**課程語意**：出現轉折性 K 線（如長下影線守住關鍵價、跳空缺口被快速回補、長紅K突破反彈高點等）即可回補。

**可量化代理**：

| 代理欄位 | 公式 | 課程出處 |
| --- | --- | --- |
| **無單一明確代理** | — | 課程把「關鍵K線」定義為「能改變前後趨勢的K線」（§1 L18），其形式不限於單一型態 |

**無法量化的部分**：

- **「關鍵K線」是一個泛指的概念，課程沒有明確說明量化標準**。第 16/17 篇明確指出關鍵K線需要結合「前後趨勢」判斷，無法用單根K線特徵直接量化。
- 本規格**不**將「關鍵K線確認」獨立加入 `cover_signal`，因為這違反「禁止以常識或一般交易慣例補完課程沒有說的部分」（`CLAUDE.md`）。可間接透過 2.1（趨勢改變）、2.2（跌勢攻擊消失）、2.3（假跌破收回）三項代理涵蓋大部分情境。

### 2.5 cover_signal 量化定義（整合 2.1–2.4）

對應 `kline_course_backtest.py` L295-299 的現行實作：

```python
cover_signal = (
    false_breakdown_reclaim                                   # 2.3 假跌破收回（明確）
    or (ma60.notna() and close > ma60)                        # 2.1 趨勢改變（站回季線）
    or (prior_high_20.notna() and close > prior_high_20)      # 2.2 跌勢攻擊消失（突破近期高點）
)
# 2.4 關鍵K線確認：課程沒有明確說明量化標準，故不在此處列入。
```

---

## 3. 課程明確的禁制與邊界（再次強調）

| 邊界 | 課程出處 | 在量化代理上的意義 |
| --- | --- | --- |
| 放空不是多方鏡像 | §8 L163 | 不可將 `breakout_attack` 反向當作 `short_entry` |
| 假跌破收回是回補、不是進場 | §8 L164 | `false_breakdown_reclaim` 只能進入 `cover_signal`，不可進入 `short_entry` |
| 跌破要看收盤 | §6 L131、CLAUDE.md 課程框架點 1 | 量化使用 `close < key_level`，不使用 `low < key_level` 作為跌破依據 |
| 跌破要有隔日確認 | §6 L132、§10 L310 | 量化使用 `next_close < key_level`（注意：這是後驗確認，進場日為 t+2） |
| 急跌後跌破易屬假跌破 | §10 L292 | `short_entry` 必須排除 `panic_drop`（已實作） |

---

## 4. 課程未涵蓋、不可自行補完的項目

下列在實務上會被問到、但**課程沒有明確說明量化標準**的項目，本規格一律不下定義。若回測或策略運行時需要這些項目，應於該下游文件明白標註「課程未涵蓋」並交由使用者選擇。

| 項目 | 課程未涵蓋的具體點 |
| --- | --- |
| 進場時點 | 課程提到「跌破當天收盤確認」+「隔日確認」，但未說明 t+1 開盤、t+2 開盤、t+2 收盤哪一個是建議進場時點 |
| 倉位大小 | 放空倉位佔總部位的比例、單筆放空金額、加碼節奏皆未在課程內出現 |
| 停損點 | 課程針對放空僅提及「回補可用趨勢改變…」，**未針對放空提出明確的停損位置設定**（多方停損的 §7 與第 54/55 篇皆以做多為主） |
| 強制回補 / 券源限制 | 屬於台股實務限制，課程完全未涵蓋（→ Task 20 `short_tradability_spec.md` 已標註「課程未涵蓋」） |
| 反彈遇壓的視窗 M | §10 L310 的 `rebound_high_next_m` 中 m 的具體值未指定 |
| 反彈站回頸線後的處理 | §10 L373 提到「站回則切換為箱型模式」，但放空時是否在「進入箱型模式」當下立刻回補，課程未明說 |
| 量縮的量化標準 | 「買盤不繼」常引用量縮，但量縮的具體門檻（量價比、均量百分比）未在課程內定義 |
| 「關鍵K線」的單一型態判定 | §1 L18 定義為「能改變前後趨勢的K線」，無單一型態量化 |
| 連續 N 日失效條件 | 例如「連續 N 日站回頸線才確認失效」此類規則，課程沒有明確說明量化標準 |

---

## 5. 課程語意 ↔ 量化代理 對照總表

| 課程語意 | 來源 | 量化代理（現行實作） | 嚴格代理（建議升級） | 是否前瞻 |
| --- | --- | --- | --- | --- |
| 弱勢（中期偏空） | §8 L163、§5 L112 | `close < ma60` + `ma60_down` | 加入「頸線跌破後反彈站不回」計次 | 否 |
| 跌破（收盤跌破關鍵價） | §8 L163、§10 L308-310 | `close < prior_low_20 and next_close < prior_low_20` | 用嚴格 `swing_low` + `ma60_rollover` 配對 | 隔日確認，t+2 才能執行 |
| 跌破前處於整理 | §6 L129、`pattern_labeling_spec.md` §1 | `in_range_20`（20 日 high-low ≤ 15%） | 加入觸碰次數 ≥ 2 | 否 |
| 跌破由長黑完成 | 第 7 篇、§10 L307 | `black_k and body_pct ≥ 0.015` | — | 否 |
| 季線下彎 | `pattern_labeling_spec.md` §2 L122 | `ma60 / ma60.shift(5) - 1 < 0` | — | 否 |
| 排除急跌假跌破情境 | §10 L292、L306 | `~(ret_5d_past ≤ -0.07)` | — | 否 |
| 反彈遇壓 | §8 L163、§10 L357、`pattern_labeling_spec.md` §2 L150 | （現行未直接量化，以 `ma60_down + close < ma60` 替代） | `neckline_retest_fail`：跌破後出現 `high ≥ neckline and close < open and close < neckline` | 否 |
| 買盤不繼 | §8 L163、§1 L16、第 7 篇 | `long_black_k`（黑K + body_pct ≥ 0.015） | — | 否 |
| 回補：趨勢改變 | §8 L164、§5 L122 | `close > ma60` | 同時要求季線斜率翻揚 | 否 |
| 回補：跌勢攻擊消失 | §8 L164、§8 L170-171 | `close > prior_high_20` | 嚴格 `swing_high` | 否 |
| 回補：假跌破收回 | §8 L164、§6 L140、§10 L308-309 | `panic_drop and low < prior_low_60 and close ≥ prior_low_60` | 加入隔日 `close > key_level` 確認 | 隔日確認版為前瞻 |
| 回補：關鍵K線確認 | §8 L164、§1 L18 | **不列入**（課程沒有明確說明量化標準） | — | — |

---

## 6. 與下游 Task 18–21 的銜接

- **Task 18（`kline_course_backtest.py` 訊號實作）**：已依本規格實作 `short_entry`、`cover_signal`（L289-299）。本規格與既有實作對齊。
- **Task 19（回測）**：放空進場應使用 t+1 開盤（沿用現有 `entry_open_1d` 慣例）；但本規格的 `short_entry` 依賴 `next_close`，導致實質上要等到 t+2 開盤才能進場。Task 19 報告需明白標註此時序。
- **Task 20（可交易性）**：券源、強制回補、漲跌停無法平倉，**課程未涵蓋**，依規格在 `short_tradability_spec.md` 內以「課程未涵蓋」標註。
- **Task 21（每日掃描）**：每日掃描的進場價、回補價、結構失效條件應直接引用本規格的代理欄位；排序加權邏輯若引入「分K」或「成交量分位」等條件，需在掃描器報告內明白標註「課程未涵蓋」。
