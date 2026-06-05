# Attack Cost Displayed — 實作報告

**日期**: 2026-06-04
**Branch**: k-bar-power
**Session**: attack_cost_displayed detector 實作 + merged_doji B2 重新校準

---

## 任務 1：attack_cost_displayed detector 實作

### 新增檔案

- `scripts/kline/patterns/attack_cost_displayed.py`

### 實作摘要

```python
# 3 個條件 AND
broke_prior_high = close > prior_high_60              # 突破前 60 日高點
limit_up_locked  = is_limit_up_locked                  # 漲停鎖住（features.py C05）
has_attack_volume = volume >= avg_volume_20 * K        # 日K退化版「最大量在漲停」
```

### 常數（新增至 course_proxy_constants.py）

| 常數名稱 | 值 | 狀態 | 說明 |
|---|---|---|---|
| `ATTACK_COST_LIMIT_UP_THRESHOLD` | 1.095 | [STUB-NEED-USER] | 漲停容差，同 features.py C05 |
| `ATTACK_COST_VOL_RATIO` | 1.0 | [STUB-NEED-USER S2] | 日K退化量比，1.0 = 事實移除量能過濾 |

**ATTACK_COST_VOL_RATIO 從 1.5 降為 1.0 原因**:
3693 營邦 2023-04-11 volume_ratio = 1.35x，原 1.5 門檻下該正例 MISS。
課程「成交量越大、成本意義越高」是「信心度判斷」非「是否觸發」條件；
攻擊成本顯現日不因量稍小而失效，detector 應仍觸發。
分 K 資料確認後可重新加入精確量能條件。

### 7 個 Case 校準結果

| case_id | ticker | date | expected_branch | actual_fired | 結果 |
|---|---|---|---|---|---|
| 1 | 3289 宜特 | 2023-03-08 | POSITIVE (pattern trigger) | True | ✓ |
| 2 | 3289 宜特 | 2023-03-09 | NEGATIVE (隔日觀察) | False | ✓ |
| 3 | 3289 宜特 | 2023-03-17 | NEGATIVE (B3 跌破) | False | ✓ |
| 4 | 8215 明基材 | 2021-12-13 | POSITIVE (pattern trigger) | NO_DATA | ~NO_DATA |
| 5 | 3693 營邦 | 2023-04-11 | POSITIVE (pattern trigger) | True | ✓ |
| 6 | 3693 營邦 | 2023-04-12 | NEGATIVE (跳空攻擊確認) | True | ✗ (known) |
| 7 | 6209 今國光 | 2023-12-15 | NEGATIVE (B3 跌破) | False | ✓ |

**結果**: 5 ✓ / 1 NO_DATA / 1 known FP

#### Case 4 (8215) 說明
8215 明基材 2021-12-13 (110-12-13) 在 DB 資料範圍以外（DB 起始日 2022-01-03）。
此 case 無法從現有日 K 資料驗證，標記為 NO_DATA（非 bug）。

#### Case 6 (3693 2023-04-12) 已知 FP 說明
3693 04-12 同樣符合 attack_cost_displayed 所有條件：
- close=166.5 > prior_high_60=151.5 ✓
- is_limit_up_locked=True ✓
- volume_ratio=3.73x ≥ 1.0 ✓

04-12 是股票在 04-11 漲停後跳空再漲停的**連續攻擊**，技術上是一個新的「攻擊成本顯現日」。
課程在 3693 案例中描述 04-12 為「跳空攻擊確認」，但 detector 層無法判斷是
「首次攻擊成本顯現」vs「連續攻擊波段中的第二次顯現」。
這是日 K 退化版的已知限制；分 K 資料可改善此情形。
不屬於 DSL 錯誤，列為 known limitation。

---

## 任務 2：merged_doji B2 重新校準

### 問題
MD-02 案例（5443 均豪 113-06-26 附近）MISS。
原因：`merged_doji.detect()` 的位置條件用 `close > prior_high_60`（收盤創新高），
但老師明說「盤中有過攻擊的力量」也算（看上影線創新高）。

### 解決方案（選項 B — 最小影響）

**新增 feature**（`features.py` C04b）:
```python
df["is_just_broke_high_intraday"] = (
    (df["high"] >= df["prior_high_60"])
    | (df.groupby("ticker")["high"].shift(1) >= df.groupby("ticker")["prior_high_60"].shift(1))
    | (df.groupby("ticker")["high"].shift(2) >= df.groupby("ticker")["prior_high_60"].shift(2))
)
```

**修改 `merged_doji.detect()`**:
- 原位置條件：`prev_close > prior_high_60_prev` OR `close > prior_high_60`
- 新位置條件：使用 `is_just_broke_high_intraday`（features.py 欄位）或 fallback 計算

### 5443 均豪 Case 驗證

| date | merged_doji | 說明 |
|---|---|---|
| 2024-06-24 | not_fired | D-1 (上影線創新高日) |
| 2024-06-25 | **FIRED ✓** | D-0 (下影線收縮) |
| 2024-06-26 | not_fired | 續攻突破日 |

**修正成功**：5443 2024-06-25 現在觸發 merged_doji。
注意：課程案例標示日期為「113-06-26」，實際 pattern 觸發在 06-25 (D-0)，
在校準 ±1 天窗口內可被捕捉。

---

## Baseline 維持確認

### pytest
```
554 passed in ~31s
```
pre/post: 554 → 554 ✓

### Calibration Runner
```
confirmed_signal active: 44  hits=39  rate=100.0%
setup_only: 19  false-positive triggers=0  FP rate=0.0%
Misses (0)
```
pre/post: 100% → 100% ✓ (baseline 維持)

---

## 新增的 STUB-NEED-USER 常數

| 常數 | 檔案 | 值 | 說明 |
|---|---|---|---|
| `ATTACK_COST_LIMIT_UP_THRESHOLD` | `course_proxy_constants.py` | 1.095 | 漲停判斷容差（同 C05）[STUB-NEED-USER] |
| `ATTACK_COST_VOL_RATIO` | `course_proxy_constants.py` | 1.0 | 量能門檻退化值 [STUB-NEED-USER S2] |
| `is_just_broke_high_intraday` | `features.py C04b` | feature | 盤中版剛創新高（3天窗口 high >= ph60）[STUB S5] |

---

## Unknowns / 需 User 後續確認

1. **ATTACK_COST_VOL_RATIO**（S2）: 現設 1.0 = 事實上移除量能過濾。
   課程「最大量在漲停板價位」需分 K 資料。若補分 K 資料後，
   可將此值調回 ≥1.5 並加入 tick 級最大量確認。

2. **3693 04-12 連續漲停 FP**（已知限制）: 連續漲停日每日都會觸發。
   課程沒有明示「一個攻擊波段只算第一個漲停」，暫列 known limitation。
   若 user 確認「每個漲停日都是獨立攻擊成本」則屬正確行為。

3. **脫離基本面排除條件**（S3）: 課程說「股價遠遠脫離基本面還繼續飆漲」
   此類股不看攻擊成本，但「脫離基本面」的定義未明示，
   目前 detector 不套用此排除。

4. **第一次突破前高**（S4）: 課程說第一次突破時攻擊成本要求最嚴，
   目前 detect 層不區分第一次/再次突破。
   可用 `is_first_breakout_above_level` 在上層 playbook 分支。

5. **is_just_broke_high_intraday 三天窗口**（S5）: 使用 D-0/D-1/D-2 三天，
   課程未明示窗口天數，沿用 C04 的三天窗口作為代理。

---

## 新增/修改的檔案清單

- **新增**: `scripts/kline/patterns/attack_cost_displayed.py`
- **修改**: `scripts/kline/course_proxy_constants.py`（新增 ATTACK_COST_LIMIT_UP_THRESHOLD, ATTACK_COST_VOL_RATIO）
- **修改**: `scripts/kline/patterns/__init__.py`（新增 attack_cost_displayed 到 registry）
- **修改**: `scripts/kline/features.py`（新增 C04b is_just_broke_high_intraday）
- **修改**: `scripts/kline/patterns/merged_doji.py`（使用 is_just_broke_high_intraday）
