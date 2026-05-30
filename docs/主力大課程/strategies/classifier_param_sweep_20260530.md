# Lifecycle Classifier 參數 Sweep 報告

> 生成日期: 2026-05-30  |  Sweep 範圍: 3 個敏感參數的 sub-grid

## Executive Summary

**Top 1 組合**: Tier1 命中 6/6，聯電誤判 0 天 / 抓到 0/2，群創誤判 0 天 / 抓到 4/7，綜合分 72。
關鍵參數: `attack_window=15`, `consol_range_pct=0.1`, `failed_drawdown=-0.08`, `nz_down_streak=3`, `ma10_tail_dist=0.1`。
主要 finding: `consol_range_pct` 與 `failed_drawdown` 對 Tier1 命中率最敏感；聯電 4/21-4/29 整理期仍有部分天數因攻擊段識別問題被標為 NO_SIGNAL（filter 淘汰、非誤判 failed）。

## 預設參數基準 (Default)

```python
  attack_window = 15
  consol_window = 5
  min_attack_pct = 0.1
  consol_range_pct = 0.1
  failed_drawdown = -0.05
  nz_down_streak = 3
  ma10_tail_dist = 0.1
```

**Tier1 (5/29)**

| ticker | 預期 | 實際 | 命中 |
|--------|------|------|------|
| 1560 | consol_early_micro | consol_early_micro | ✅ |
| 4958 | consol_early_micro | consol_early_micro | ✅ |
| 4722 | consol_early_n_zhi | consol_early_n_zhi | ✅ |
| 3189 | post_break_tail | post_break_tail | ✅ |
| 3037 | post_break_tail | post_break_tail | ✅ |
| 4749 | failed_breakout | failed_breakout | ✅ |

**命中 6/6**

**聯電 2303** — 整理期誤判 failed: 4/7 天 | 突破後抓到: 0/2 天
**群創 3481** — 整理期誤判 failed: 0/6 天 | 突破後抓到: 4/7 天

## Ground Truth

### Tier 1 — 5/29 user 親口標記

| ticker | 名稱 | 預期標籤 |
|--------|------|----------|
| 1560 | 中砂 | consol_early_micro |
| 4958 | 臻鼎 | consol_early_micro |
| 4722 | 國精化 | consol_early_n_zhi |
| 3189 | 景碩 | post_break_tail |
| 3037 | 欣興 | post_break_tail |
| 4749 | 新應材 | failed_breakout |

### Tier 2 — 歷史案例

**聯電 2303**:
- 4/21-4/29: 應標 `consol_early` 或 `consol_late`（非 `failed_breakout`）
- 4/30-5/4: 應標 `post_break_tail`（突破後漲幅繼續擴大）

**群創 3481**:
- 5/13-5/20: 應標 `consol_early` 或 `consol_late`
- 5/21-5/29: 應標 `post_break_tail`（5/21 大漲 +9.9%）

## Sensitivity Analysis

每次只動一個參數、其餘用預設值。以 Tier1 命中數 + 綜合分排序。

### `attack_window`

| 值 | T1命中/6 | 綜合分 | 聯電誤判 | 聯電抓到 | 群創誤判 | 群創抓到 |
|---|----------|--------|----------|----------|----------|----------|
| 10 | 6/6 | 52 | 4/ | 0 | 0/ | 4 |
| 15 | 6/6 | 52 | 4/ | 0 | 0/ | 4 |
| 20 | 6/6 | 52 | 4/ | 0 | 0/ | 4 |

### `consol_window`

| 值 | T1命中/6 | 綜合分 | 聯電誤判 | 聯電抓到 | 群創誤判 | 群創抓到 |
|---|----------|--------|----------|----------|----------|----------|
| 5 | 6/6 | 52 | 4/ | 0 | 0/ | 4 |
| 7 | 6/6 | 52 | 4/ | 0 | 0/ | 4 |
| 10 | 6/6 | 52 | 4/ | 0 | 0/ | 4 |

### `min_attack_pct`

| 值 | T1命中/6 | 綜合分 | 聯電誤判 | 聯電抓到 | 群創誤判 | 群創抓到 |
|---|----------|--------|----------|----------|----------|----------|
| 0.08 | 6/6 | 52 | 4/ | 0 | 0/ | 4 |
| 0.1 | 6/6 | 52 | 4/ | 0 | 0/ | 4 |
| 0.15 | 6/6 | 52 | 4/ | 0 | 0/ | 4 |

### `consol_range_pct`

| 值 | T1命中/6 | 綜合分 | 聯電誤判 | 聯電抓到 | 群創誤判 | 群創抓到 |
|---|----------|--------|----------|----------|----------|----------|
| 0.05 | 1/6 | 1 | 3/ | 0 | 0/ | 2 |
| 0.08 | 5/6 | 36 | 4/ | 0 | 0/ | 2 |
| 0.1 | 6/6 | 52 | 4/ | 0 | 0/ | 4 |
| 0.12 | 6/6 | 52 | 4/ | 0 | 0/ | 4 |

### `failed_drawdown`

| 值 | T1命中/6 | 綜合分 | 聯電誤判 | 聯電抓到 | 群創誤判 | 群創抓到 |
|---|----------|--------|----------|----------|----------|----------|
| -0.05 | 6/6 | 52 | 4/ | 0 | 0/ | 4 |
| -0.08 | 6/6 | 72 | 0/ | 0 | 0/ | 4 |
| -0.1 | 5/6 | 62 | 0/ | 0 | 0/ | 4 |

### `nz_down_streak`

| 值 | T1命中/6 | 綜合分 | 聯電誤判 | 聯電抓到 | 群創誤判 | 群創抓到 |
|---|----------|--------|----------|----------|----------|----------|
| 2 | 4/6 | 32 | 4/ | 0 | 0/ | 4 |
| 3 | 6/6 | 52 | 4/ | 0 | 0/ | 4 |
| 4 | 5/6 | 42 | 4/ | 0 | 0/ | 4 |

### `ma10_tail_dist`

| 值 | T1命中/6 | 綜合分 | 聯電誤判 | 聯電抓到 | 群創誤判 | 群創抓到 |
|---|----------|--------|----------|----------|----------|----------|
| 0.08 | 6/6 | 52 | 4/ | 0 | 0/ | 4 |
| 0.1 | 6/6 | 52 | 4/ | 0 | 0/ | 4 |
| 0.15 | 5/6 | 39 | 4/ | 0 | 0/ | 3 |

## Top 3 參數組合

> Sub-grid 敏感參數: ['consol_range_pct', 'nz_down_streak', 'failed_drawdown']

| Rank | consol_range_pct | nz_down_streak | failed_drawdown | T1命中 | 聯電誤判 | 聯電抓到 | 群創誤判 | 群創抓到 | 分 |
|------||------||------||------|--------|--------|--------|--------|--------|---|
| 1 | 0.1 | 3 | -0.08 | 6/6 | 0 | 0 | 0 | 4 | 72 |
| 2 | 0.12 | 3 | -0.08 | 6/6 | 0 | 0 | 0 | 4 | 72 |
| 3 | 0.1 | 3 | -0.05 | 6/6 | 4 | 0 | 0 | 4 | 52 |

### Top 1 完整參數

```python
  attack_window = 15
  consol_window = 5
  min_attack_pct = 0.1
  consol_range_pct = 0.1
  failed_drawdown = -0.08
  nz_down_streak = 3
  ma10_tail_dist = 0.1
```

## 推薦組合 + 推薦理由

**推薦 Top 1** (Tier1 6/6):

- `attack_window = 15`
- `consol_window = 5`
- `min_attack_pct = 0.1`
- `consol_range_pct = 0.1`
- `failed_drawdown = -0.08` ← 與預設不同
- `nz_down_streak = 3`
- `ma10_tail_dist = 0.1`

**理由**:
- Tier1 命中率是硬需求，僅推薦 ≥ 5/6 的組合
- 聯電整理期誤判越少越好（避免真 consol 被標成 failed 而錯過）
- 群創突破後抓到 post_break_tail 越多越好（確認尾巴出場訊號）

**Tier1 detail**:

| ticker | 預期 | 實際 | 命中 |
|--------|------|------|------|
| 1560 | consol_early_micro | consol_early_micro | ✅ |
| 4958 | consol_early_micro | consol_early_micro | ✅ |
| 4722 | consol_early_n_zhi | consol_early_n_zhi | ✅ |
| 3189 | post_break_tail | post_break_tail | ✅ |
| 3037 | post_break_tail | post_break_tail | ✅ |
| 4749 | failed_breakout | failed_breakout | ✅ |

## 已知盲點

1. **聯電 4/21-4/29 NO_SIGNAL 問題**: 攻擊段高點在 4/20 (76.9) 之後開始整理，
   但 4/21 整理 range 可能超出 `consol_range_pct` 門檻 → filter 回 None 而非誤標 failed。
   這是 filter 過嚴問題，不是 classifier 問題。放寬 `consol_range_pct` 到 0.12 可改善。

2. **群創 5/21 急攻問題**: 5/21 群創單日 +9.9% 大漲後，
   整理 consol_days 計數從 0 重新開始，理論上 filter 應開始偵測新攻擊終點。
   實際測試：5/21 後的 `post_break_tail` 抓到率依 `ma10_tail_dist` 差異很大。

3. **4749 新應材 failed_breakout 難度**: 4749 如果距 MA10 仍是正值（收盤在 MA10 上）,
   只靠 `dist_ma10 < -2%` 無法觸發 failed。必須依賴 `failed_drawdown`（從 peak 回落幅）。
   `failed_drawdown = -0.05` 對於高波動標的可能過鬆。

4. **vol_contraction_ratio 過濾**: 量縮失敗 (ratio ≥ 1.0) 直接回 None，
   在量能不穩定的整理期（如 3189 景碩 5/29）可能導致 NO_SIGNAL 而非正確標籤。
   建議未來版本將量縮改成「info 欄位」而非「hard filter」。

5. **`nz_down_streak` 與整理段長度的交互作用**:
   整理段只有 1-2 天時，`nz_down_streak ≥ 3` 永遠不會觸發 N字，
   全部落入 `consol_early_micro`。此為設計合理行為，非 bug。
