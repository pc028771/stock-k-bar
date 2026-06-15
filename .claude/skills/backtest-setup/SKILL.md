---
name: backtest-setup
description: Use when running backtests, evaluating setups, or grid-searching detector variants. Triggers on "backtest", "回測", "跑 setup", "grid search", "驗證 detector", "測試策略", "篩選變體". Enforces user methodology — small sample is feature, 65% WR / 5+ tickers / 2+ months three-axis filter, reverse signals counted.
---

# Backtest Setup Methodology Enforcement

🔴 任何 backtest 工作開工前、必先讀 `references/methodology.md`。違反 = 重做。

## Trigger 範圍

- 寫新 detector
- Grid search 變體（多 condition stack 組合）
- 評估 setup 表現
- 修改既有 detector 條件
- 「跑 backtest」「驗證 setup」「測試策略」

## Step 1: Read Methodology

Read `references/methodology.md` 並 acknowledge 三條鐵則：
1. 條件 stack 越多 → 樣本越小 → 訊號越乾淨（**小樣本是 feature、不扣分**）
2. 跨股 ≥ 5 / 跨月 ≥ 2 三維 robustness 取代統計顯著
3. 反向訊號（WR ≤ 35% + n ≥ 10）等價值、寫進 skip 清單

## Step 2: Confirm 物理意義

每個 detector / 變體必須有「一句話講清楚」的物理意義。講不清楚 = 過擬合、不做。

用 user 的語言問：「這個 stack 的物理意義是什麼？」
不能回答 → 取消這個變體。

## Step 3: Schema 模板

Backtest 結果 schema 必須含：
```yaml
required:
  - variant_id
  - n_hits
  - n_unique_tickers
  - n_unique_months
  - fwd5_wr / fwd5_avg
  - fwd10_wr / fwd10_avg
  - fwd20_wr / fwd20_avg
  - passes_methodology  # WR≥65% (任一窗口) AND tickers≥5 AND months≥2
  - reason  # 一句中文
optional:
  - sample_size_judgement  # actionable / watch_only_n_lt_10 / too_noisy_n_gt_200
  - top_5_hits
```

`passes_methodology` 判準 hard-coded、不可放鬆。

## Step 4: 跑 Backtest

可選方式（按複雜度）：

### 4a. 單一 detector / 變體（簡單）
寫單檔 Python script、跑 + CSV + summary。
範本: `/tmp/foreign_lead_backtest.py`

### 4b. 多變體 grid search（複雜）
用 **Workflow tool** 4 phases:
- Phase Grid: 設計 12-15 個變體（覆蓋寬鬆 → 嚴格 stack）
- Phase Backtest: pipeline 跑每個變體
- Phase Filter: 套三條方法論硬規則
- Phase Pick: 挑 top 3-5（嚴格優先、不挑 n_hits 多）

範本: `references/workflow-template.js`

## Step 5: Pick 階段紀律

挑變體時：
- ✅ WR 越高越好（target 70%+）
- ✅ 條件 stack 越嚴格越好（物理意義清楚 + n=10-30 即可）
- ✅ 跨股/跨月廣度足夠（≥5 / ≥2）
- ❌ **不要因為 n 小就降排名** — 違反原則
- ❌ **不要因為 fwd_20d_avg 不夠高就跳過** — 短期 detector 也有用
- ✅ 也要列反向訊號（WR ≤ 35% + n ≥ 10、可用於 skip 警示）

## Step 6: 報告階段

給 user 報告時：
- **白話**、不要 jargon（WR / EV / PF 都要解釋）
- 一句話 recommendation 在前
- top 3-5 變體列出、每個物理意義一句話
- 反向訊號獨立區塊
- next_steps 給「直接部署 / 還要疊條件 / 整合 daily_scanner」三選一

## Step 7: 部署前 sanity check

如果決定部署到 production：
- entry detector 寫進 `scripts/zhuli/entry/` 或 `scripts/zhuli/chip/`
- 整合進 `daily_scanner_job.py` 排序
- 加 memory `experiments_index.md` 記錄（pass/fail 都記）

## ⚠️ 常見違規

歷史上違反過的：
1. ❌ 用 `n_hits 適中即可、太少不可執行` 排除小樣本（違反「樣本小是 feature」）
2. ❌ 用 5d / 10d 收盤當實際出場（memory: 5d 報酬會 over-estimate、實戰用 C6 Rule A）
3. ❌ 沒讀 methodology memory 就開跑、結果 schema 不對齊
4. ❌ 只列正面訊號、漏列反向訊號

任何回報出現以上跡象 → user 提醒「想想方法論」即 trigger 重做。

## Reference Files

- `references/methodology.md`：三條鐵則 + 報酬計算 + 篩選流程（user memory 的本地化版本）
- `references/workflow-template.js`：grid search workflow JS 範本、含 schema + phase 結構
