# attack_cost_displayed — 連續觸發 state-machine v1

**Scope**：3693 營邦 2022-12 連續漲停判讀 + state-machine 抑制邏輯實作
**前置 Opus note**：`docs/kline_course/notes/attack_cost_consecutive_limit_up_interpretation.md`（已解 3693 2023-04-11/04-12 案例 → 答案 B）
**禁區**：純解讀 + detector state-machine；不動 DSL / playbook YAML / 課程明示規則

---

## 1. 2022-12 案例事實

| 日期 | open | high | low | close | volume | prior_high_60 | is_limit_up_locked | 原 detector |
|---|---|---|---|---|---|---|---|---|
| 2022-12-07 | 77.0 | 79.0 | 74.4 | 78.1 | 942,521 | 84.5 | False | False |
| **2022-12-08** | 84.0 | 85.9 | 82.6 | **85.9** | 2,321,587 | 84.5 | **True** | **True** |
| **2022-12-09** | 89.3 | 94.4 | 87.6 | **94.4** | 5,199,201 | 85.9 | **True** | **True** |
| **2022-12-12** | 97.8 | 103.5 | 97.1 | **103.5** | 6,946,280 | 94.4 | **True** | **True** |
| 2022-12-13 | 104.0 | 112.5 | 101.5 | 107.0 | 14,642,795 | 103.5 | False | False |

→ 連續三日 raw_signal=True。需要 state-machine 抑制 12/09、12/12。

---

## 2. 判讀：**答案 B**（12/08 = setup，12/09 + 12/12 = 攻擊企圖確認）

### 老師原話（篇 20，B44741FE824D0798CC91C1521D5B0FF7）逐字摘錄

1. > 「某些狀態之下更不能違反攻擊成本⋯⋯這一點在**股價第一次突破前高時，最為關鍵**，**漲太多已經不是第一次突破前高的，就不在此限**。」

2. > 「**跳空攻擊算得上是攻擊成本浮現之後，明日 K 線是『繼續攻擊』的最佳解答**，交易就希望股價攻擊，這裡當然就是繼續的答案。」

3. > 「至此**已經不用再判斷會不會轉變**，而是開始設定移動停利，**進入了攻擊結束的判別**，攻擊沒有結束，不用考慮出場。」

### 推導

- **2022-12-08**：價格從前 60 日盤整 (high=84.5) 第一次突破鎖漲停、最大量在漲停 → **攻擊成本顯現日 setup**（同 04-11 角色）
- **2022-12-09 / 12/12**：連續漲停 = 「**繼續攻擊**」branch、屬於「攻擊企圖確認」階段（同 04-12 角色）。老師明示「漲太多已經不是第一次突破前高的，就不在此限」→ 第二、三根漲停的攻擊成本意義被排除。
- 即「明天開始就必需得要攻擊」這句話本身、把連續漲停定位為攻擊成本顯現後的 **後續動作**（branch action）、**不是**新的攻擊成本顯現。

### 為什麼不選 A / C

- **A**：每根漲停都當新 attack_cost → 與老師「**第一次突破前高最為關鍵 / 漲太多已經不是第一次突破前高的不在此限**」直接衝突。
- **C**：視位置 / 量能 / 是否第一次突破決定 → 老師原話沒給三維分流規則來把第 2、3 根重新歸類為新 setup。

→ **與前次 04-11/04-12 判讀（答案 B）一致**。

---

## 3. State-machine 實作

### Pseudocode

```python
raw_signal = (close > prior_high_60) & is_limit_up_locked & has_attack_volume

# State-machine: 同段攻擊內只保留首日 setup
N = ATTACK_COST_FIRST_BREAKOUT_LOOKBACK_DAYS  # = 20 [STUB-NEED-USER]

prior_signal_in_window = (
    raw_signal.shift(1)          # 排除今日自己
    .rolling(N, min_periods=1)
    .max()                       # 過去 N 日內是否曾觸發
    .astype(bool)
)

final_signal = raw_signal & ~prior_signal_in_window
```

（按 ticker groupby 跑、跨 ticker 不互相影響。）

### N 的選擇 — 為何 20 而非 60？

- 老師原話「明天開始就必需得要攻擊」+「進入了攻擊結束的判別」表示「攻擊」是**短期狀態**、結束後可重新 setup。
- 若 N=60（對齊 `prior_high_60`）：3693 2023-01-16（攻擊成本）→ 2023-04-11（48 個交易日後、中間經歷 -18% 深回檔再起新攻勢）會被誤殺為「同段攻擊」。
- N=20（≈ 一個月）：
  - 2022-12-08 → 12/09/12（2-4 個交易日內、連續漲停）→ 抑制 ✓
  - 2023-01-16 → 2023-04-11（48 個交易日、跨段）→ 不抑制 ✓
- N=20 較符合課程「短期同段延續」語意。

### 改動範圍

| 檔案 | 改動 |
|---|---|
| `scripts/kline/course_proxy_constants.py` | 新增 `ATTACK_COST_FIRST_BREAKOUT_LOOKBACK_DAYS = 20`（標 [STUB-NEED-USER]） + `__all__` 補加 |
| `scripts/kline/patterns/attack_cost_displayed.py` | `detect()` 加入 state-machine 抑制 block（groupby ticker, rolling 20-day max of shifted raw_signal） |

不動：DSL、playbook YAML、其他 detector、features.py、scoring。

---

## 4. 9 case 驗證表

| # | Ticker | Date | Expected | Actual | 狀態 |
|---|---|---|---|---|---|
| 1 | 3289 | 2023-03-08 | True | True | PASS |
| 2 | 3289 | 2023-03-09 | False | False | PASS |
| 3 | 3289 | 2023-03-17 | False | False | PASS（跌破、非觸發） |
| 4 | 3693 | 2023-04-11 | True | True | PASS |
| 5 | 3693 | 2023-04-12 | False | False | PASS（OHLC `low<prev_close` 已擋；state-machine 雙重保險）|
| 6 | 6209 | 2023-12-15 | False | False | PASS |
| 7 | **3693** | **2022-12-08** | **True** | **True** | **PASS（首日 setup）** |
| 8 | **3693** | **2022-12-09** | **False** | **False** | **PASS（state-machine 抑制）** |
| 9 | **3693** | **2022-12-12** | **False** | **False** | **PASS（state-machine 抑制）** |

→ **9/9 PASS**。

---

## 5. baseline + pytest 結果

### Calibration runner

```
confirmed_signal active: 44  hits=39  rate=100.0%
setup_only:              19  false-positive triggers=0  FP rate=0.0%
context_only (excluded): 24
Misses: 0
```

→ baseline **100% / 0 FP / 0 misses**（與 pre-change 完全一致）。
attack_cost_displayed 目前不在 `CASE_INDEX_v4.csv`、不影響 calibration metrics。

### pytest

```
558 passed in 46.73s
```

→ **554+ baseline 全綠**（558 全過）。

---

## 6. 新增 STUB 清單

| STUB ID | 常數 | 值 | 課程根據 |
|---|---|---|---|
| A20c | `ATTACK_COST_FIRST_BREAKOUT_LOOKBACK_DAYS` | 20 trading days | 老師「漲太多已經不是第一次突破前高的，就不在此限」+「進入了攻擊結束的判別」（語意上是「短期內同一段攻擊」、無具體數字） |

### 既有 STUB（unchanged，本次未碰）

- **STUB S2** `ATTACK_COST_VOL_RATIO = 1.0` — 日K退化版量比門檻
- **STUB S3** 「脫離基本面」定義未明示
- **STUB S4** 「第一次突破前高」邊界（features.py `is_first_breakout_above_level` 用 60 日 lookback）

---

## 7. 已知 limitation

1. **無顯式「攻擊結束」reset 機制**：目前只用固定 20 日 lookback 抑制。若某段攻擊在 20 日內結束（跌破突破點）+ 立刻再起新攻勢，理論上應允許新 setup、但會被誤殺。後續可加入「中途 close < prior_high_60 持續 N 天 → 提前 reset」邏輯。

2. **N=20 是工程提議、非課程明示**：老師只給語意「短期 / 一段攻擊」。20 日（≈ 1 個月）是基於 3693 案例校正；其他標的需更多 case 驗證。

3. **state-machine 不區分 setup-strength**：第 2、3 根漲停一律抑制、不另發「攻擊企圖確認」訊號。若未來要實作 `attack_intent_confirmed_gap_up` / `attack_intent_confirmed_push` 分支訊號（STUB #3 of prior note），需要新 detector + playbook、本次不做。

4. **未處理利空當日突破鎖漲停的高優先級分支**（STUB #4 of prior note）：detector 仍用同一條規則、不區分利空 / 利多。

5. **與 features.py `is_first_breakout_above_level` 的關係**：該 feature 用 60 日 lookback 數所有 `close > prior_high_60` bars、不限漲停；本 state-machine 用 20 日 lookback 數 raw_signal（漲停 + 突破 + 量）。兩者語意不同、不相互替代：
   - 3693 2022-12-08：`is_first_breakout_above_level = False`（因為 2022-09-01 / 11-17 / 11-30 / 12-01 都曾 close > prior_high_60 但都不是漲停 setup）
   - 3693 2022-12-08：state-machine 新規則 → True（過去 20 日無 raw_signal）
   - → 本次選用 state-machine 路線、不用 `is_first_breakout_above_level` 作為 gating（會誤殺 2022-12-08 正例）

---

## 8. 改動檔案清單（絕對路徑）

- `/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/scripts/kline/course_proxy_constants.py`
  - 新增 `ATTACK_COST_FIRST_BREAKOUT_LOOKBACK_DAYS = 20` 區塊（A20c）
  - `__all__` 補加常數名稱
- `/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/scripts/kline/patterns/attack_cost_displayed.py`
  - import 新常數
  - `detect()` return 前加 state-machine block

未動：DSL、playbook YAML、其他 detector、features.py、scoring/、tests/。
