# Backtest 方法論（本地化版本、源自 memory feedback_backtest_strategy_filtering）

User 追求的是**實際買賣可重複的型態**、不是統計理論驗證。

## 三條鐵則（不可違反）

### 1. 條件 stack 越多 → 樣本越小 → 訊號越乾淨

不用追求 n ≥ 50 / 100。**能用嚴格條件 stack 篩到 n=10-30 但勝率 70%+ 的 setup 比 n=500 勝率 55% 強得多**。

- 對任何掃描、優先看「最嚴格的條件疊加版本」、不是 baseline
- n < 10 也可以記錄（標 watch-only、累積到 n>=10 再升等）
- 條件 stack 後勝率 ≥ 65% 就算 actionable

### 2. 三維 robustness 取代統計顯著

不用 Wilson CI / t-test。改用：

| 維度 | 標準 | 反例 |
|---|---|---|
| 跨個股 | ≥ 5 檔 | 集中在 1-2 檔 = 單股 fluke |
| 跨月份 | ≥ 2 個月 | 同一週連中 = regime fluke |
| 跨 regime（若適用）| 強多 + 震盪都有 | 只在強多盤出現 = regime-conditional |

第 3 點看 setup 物理：例如「殺低日底背離」物理上需要殺低、震盪盤裡樣本本來就少、不要求跨 regime 一樣強。

### 3. 反向訊號跟正面訊號等價值

「勝率 ≤ 35% + n ≥ 10 + 跨股 ≥ 5」也是可用 setup、用來 **skip 進場 / 警示減倉**、跟正面訊號一樣寫進策略。

## 完整篩選流程

```
1. 想到一個 setup 假設（物理意義清楚的條件組合）
2. 把條件 stack 到最嚴格、看樣本是否還 >= 5
3. 看樣本的勝率（隔日 + 5d 兩個視角）
   勝率 >= 65% → actionable
   勝率 50-65% → watch-only、再加條件
   勝率 <= 35% → 反向訊號、寫進 skip 清單
4. 驗證跨股 >= 5、跨月 >= 2
5. 物理意義能否一句話講清楚（講不清楚 = 過擬合）
6. 若 setup 物理上應 regime-agnostic、就跑強多 + 震盪兩 regime 驗
```

## 報酬計算紀律（2026-06-14 user 補充）

之前用「隔日收 / 5d 收」算 setup 報酬是過簡化。實戰報酬必須：

### 規則
1. **進場單位 = 固定 1 張（1,000 股）**、不用 sizing 比例
2. **進場時點 = 訊號日隔日開盤**（real-world 執行）
3. **出場機制 = 現有 production C6 規則**（feedback_exit_rules_v3 Rule A）：
   - 收盤 ≥ MA10 → 不出
   - 收 < MA10 by ≥ 2%（深破）→ 隔日開盤出
   - 收 < MA10 by < 2% + 量比 ≥ 1.0（放量小破）→ 隔日開盤出
   - 容忍區（-2% ~ 0%）連 2 天 → 隔日開盤出
4. **加碼也按 1 張單位**（不是 sizing 倍數）
5. **報酬 = (exit_price − entry_price) / entry_price × 100%**、不扣手續費（或統一扣 0.4% baseline）

### 為什麼這樣算

5d / 10d / 20d 報酬會 over-estimate：實戰 Rule A 平均持有 6-12 天、但波峰不一定在第 5 天、5d 算出來是「最有利位置的偷看」。

**N 日報酬作為 ranking / grid search 比較 OK、作為實際出場機制不行。**

### 工程接點

- 模擬函式: `/tmp/sim_c6_exit.py`（Rule A only 簡化版、跑遍 chop setup 用）
- Production 完整版: `scripts/zhuli/tools/backtest_standard_workflow.py`（含 C6 轉倉、partial trim、掀傘、長黑、里程碑、跳空 -5%）

## 常見違規（歷史教訓）

1. ❌ 用「n_hits 適中即可、太少不可執行」排除小樣本（違反「樣本小是 feature」）
2. ❌ 用 5d / 10d 收盤當實際出場（memory: N 日報酬 over-estimate）
3. ❌ 沒讀 methodology memory 就開跑、結果 schema 不對齊
4. ❌ 只列正面訊號、漏列反向訊號
5. ❌ 互斥條件 stack（e.g. 5d 跌-3% + 投信同向買）→ n=0 但沒提前 sanity check
