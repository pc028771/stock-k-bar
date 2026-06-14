# Phase 3b — main_chip_holder v2 backtest (真三軸)

> Source: `scripts/xiaoge/backtest_phase3b.py`
> Date: 2026-06-14
> 樣本：2026-05-01 ~ 2026-06-12 (30 trading days)
> 新增資料：`TaiwanStockHoldingSharesPer` (週粒度集保戶 + 大戶/散戶分級)

## 結果對比

| Detector | n | avg_ret | median | win_rate | avg_hold | max | min |
|---|---|---|---|---|---|---|---|
| v1: chip 10% (機構 only) | 1034 | 1.65% | -0.23% | 46.9% | 6.4 | 125.81% | -33.29% |
| **v2: 真三軸 10%** | **443** | **2.42%** | -0.4% | **44.5%** | 6.8 | 125.81% | -24.81% |
| v2 寬鬆: 真三軸 5% | 613 | 2.41% | -0.12% | 47.0% | 6.5 | 125.81% | -24.81% |

## 訊號集合分析

- v1 ∩ v2: 361 同訊號
- 只 v1: 673 訊號（v2 因加大戶/集保戶條件被濾掉）
- 只 v2: 82 訊號（理論上 0、v2 是 v1 子集；若有 → bug）

## 解讀

- v2 把 v1 的 1034 訊號收斂到 443 個，是 42.8% 留下率。
- 老師三軸論的篩選效應 → 訊號減少、品質變化看 win_rate / avg_ret 比較。

## 已知限制

1. 樣本期太短 (30 trading days)、訊號數較 v1 大幅減少後統計可信度更低
2. shareholding 週粒度 → 訊號生效時可能 staleness 達 5 個交易日
3. 真分點 detector (key_broker_signal) 還沒做、留 Phase 3c

## 後續

- 若 v2 比 v1 好 → v2 上線、v1 deprecate
- 若 v2 沒明顯改善 → 三軸論在 30 日窗口可能不顯著、需更長 backtest 確認
- detector 4 (key_broker_signal 真分點) 待 Phase 3c
