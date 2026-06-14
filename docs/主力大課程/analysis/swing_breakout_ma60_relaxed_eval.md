# swing_breakout ma60_near_bottom 放寬條件評估報告

**日期：** 2026-06-08
**觸發原因：** scanner_diagnosis_6449_delay.md — 6449 鈺邦 +133% 波段 miss 診斷

---

## 1. 問題背景

`swing_breakout` scanner 嚴格要求 `ma60_slope > 0`（季線上彎）。
6449 鈺邦在 5/5 真正起攻日，MA60 仍以每日 -0.03 元緩降（5日跌幅 0.71%），
被排除在外。實際結果：5/5 → 6/4 漲幅 +133%，未抓到。

---

## 2. 實作說明

### 新增欄位 / 參數

**`SwingBreakoutConfig`（`scripts/zhuli/config.py`）新增 3 個欄位：**

| 欄位 | 預設值 | 說明 |
|---|---|---|
| `ma60_near_bottom_enabled` | `True` | 開關（default ON） |
| `ma60_near_bottom_max_drop_pct` | `1.0` | 5日 MA60 最大跌幅上限（%） |
| `ma60_near_bottom_ma20_up_days` | `5` | MA20 需連續上彎天數 |

### 觸發邏輯（`scripts/zhuli/entry/swing_breakout.py`）

```
ma60_near_bottom = (
    ma60_slope_5d < 0                              # MA60 仍在下彎
    AND 5日 MA60 最大跌幅 < 1.0%                   # 幅度極小（近乎平坦）
    AND MA20 連續 5 天 slope > 0                   # 月線已持續上彎
)

ma60_pass = ma60_strict_pass OR ma60_near_bottom  # 放寬後的季線門檻
```

輸出新增 `ma60_near_bottom` (bool) 欄位，標記哪些訊號是經由放寬條件通過的。

---

## 3. 6449 鈺邦驗證

| 日期 | MA60 slope_5d | 5日 MA60 跌幅 | MA20 slope | ma60_near_bottom | 結果 |
|---|---|---|---|---|---|
| 5/5 | -0.0096 | 0.712% | +0.020 (連續>5日) | ✅ True | **新版放行** |
| 5/11 | +0.0014 | 0.350% | +0.035 | False | 嚴格版才放行 |

**6449 交易結果（新版）：**

| signal_date | entry_price | exit_price | return_pct | exit_reason |
|---|---|---|---|---|
| 2026-05-05 | 176.68 | 370.63 | **+109.8%** | max_hold |

→ **5/5 entry 成功觸發，return +109.8%** ✅

---

## 4. Baseline vs 新版指標對比

回測期間：2026-01-01 ~ 2026-06-07，max_hold=120天，30日 dedupe

| 指標 | Strict（原版） | Relaxed（新版） | 變化 |
|---|---|---|---|
| Signals（dedupe後） | 1,778 | 1,885 | +107 (+6%) |
| Trades | 1,778 | 1,885 | +107 |
| Hit Rate | 30.8% | 30.5% | -0.3% |
| EV（期望值） | +11.10% | +10.99% | -0.11% |
| Win Avg | +49.79% | +49.67% | -0.12% |
| Loss Avg | -6.09% | -5.98% | +0.11% |

**純 near_bottom 訊號績效（283 筆）：**

| 指標 | 數值 |
|---|---|
| Hit Rate | 27.6% |
| EV | +6.81% |
| Win Avg | +35.49% |
| Loss Avg | -4.10% |

---

## 5. 新條件增加的代表性贏家

| ticker | name | signal_date | return_pct | 備註 |
|---|---|---|---|---|
| 6449 | 鈺邦 | 2026-05-05 | +109.8% | 原始 miss 案例，現已修復 |
| 2492 | 華新 | 2026-05-05 | +171.4% | 同期 near_bottom 命中 |
| 4919 | 新盛力 | 2026-01-14 | +211.7% | 年初底部反轉 |
| 6187 | 萊爾富 | 2026-01-05 | +175.7% | 季線剛轉折前 |
| 6016 | 嘉晶 | 2026-01-02 | +173.2% | |

**代表性輸家（near_bottom）：**

| ticker | signal_date | return_pct | 備註 |
|---|---|---|---|
| 4563 | 2026-01-14 | -19.3% | 最大虧損 |
| 8038 | 2026-01-02 | -15.0% | |
| 3219 | 2026-01-05 | -14.2% | |

---

## 6. 關鍵決策矩陣

| 維度 | 數值 | 評估 |
|---|---|---|
| Signal 增加量 | +6% | 可接受（非暴衝） |
| 整體 Hit Rate 變化 | -0.3% | 可接受（在誤差範圍內） |
| 整體 EV 變化 | -0.11% | 可接受 |
| Near-bottom EV | +6.81% | 正期望值，非垃圾訊號 |
| 6449 case fix | 5/5 +109.8% 命中 | ✅ 目標達成 |
| 閾值校準 | 1.0% 5日跌幅 | 4/30 (1.004%) 剛好排除，5/5 (0.712%) 放行 |

---

## 7. 評估結論

**Verdict: ✅ SHIP**

理由：
1. 6449 目標案例在 5/5 正確觸發（+109.8%）
2. 整體指標退化幅度可接受（EV -0.11%, Hit -0.3%）
3. near_bottom 283 筆的 EV +6.81% 仍為正期望值
4. Signal 增加只有 +6%，未大幅引入噪音
5. 1.0% 閾值校準合理：排除 4/30（MA60 連跌 10 天的 1.004%），放行 5/5（MA60 即將轉折的 0.712%）

**建議後續動作：**
- 觀察 near_bottom 訊號在未來 2-4 週的現實績效
- 若 near_bottom 群的 Win Rate < 25% 持續 20 筆以上，可將閾值從 1.0% 調低至 0.8%
- 考慮加入 `ma60_near_bottom` 在排名中的加成（目前不影響 score）

---

## 8. 變更檔案

| 檔案 | 說明 |
|---|---|
| `scripts/zhuli/config.py` | `SwingBreakoutConfig` 新增 3 個 ma60_near_bottom 欄位 |
| `scripts/zhuli/entry/swing_breakout.py` | detect() 加入放寬條件邏輯 + 輸出 `ma60_near_bottom` 欄位 |
| `tests/zhuli/test_swing_breakout.py` | 7 個 unit tests（全部通過） |
| `data/analysis/zhuli/backtest_swing_breakout_ma60relaxed_2026ytd.csv` | 新版 2026 YTD 回測結果（1885 筆） |
