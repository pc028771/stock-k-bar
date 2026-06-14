# cross_xiaoge_kline backtest（延長期 2 月）

> 區間: 2026-04-01 ~ 2026-06-12（vs Phase 4 只用 5/1-6/12）
> 出場: `leave_upper_band`（待 C6 simulator 完成後升級）
> 模組: `scripts/cross_courses/xiaoge_kline_cross.py` + `backtest_cross_xiaoge_kline.py`

## 結果

| Detector | n | 跨股 | 跨月 | avg_ret | 勝率 | hold |
|---|---|---|---|---|---|---|
| xiaoge alone (v2 真三軸) | 745 | 490 | 2 | +1.68% | 44.0% | 5.0d |
| kline alone (breakout) | 1681 | 1027 | 3 | +1.30% | 43.6% | 5.2d |
| CROSS strict (同日)| 120 | 104 | 2 | +1.35% | 43.3% | 4.4d |
| CROSS 5d window | 354 | 213 | 2 | +1.99% | 47.7% | 5.3d |

## 三維 robustness 結論（新方法論 user 6/14 拍板）

| Setup | 勝率 ≥ 65%？| 跨股 ≥ 5？| 跨月 ≥ 2？| 結論 |
|---|---|---|---|---|
| xiaoge v2 | ✗ (44%) | ✓ | ✓ | ⚠️ 未達標 |
| kline breakout | ✗ (44%) | ✓ | ✓ | ⚠️ 未達標 |
| cross strict | ✗ (43%) | ✓ | ✓ | ⚠️ 未達標 |
| cross 5d window | ✗ (48%) | ✓ | ✓ | ⚠️ 未達標 |

**沒有 actionable setup**（勝率全部 < 65%）。
**也沒有反向訊號**（勝率全部 > 35%）。
全部落在「未達標」灰區。

## 跟 Phase 4 對比

| 來源 | xiaoge 變體 | kline 變體 | cross n | cross avg | cross wr |
|---|---|---|---|---|---|
| Phase 4 (5/1-6/12) | chip_tight (機構 only 10%) | tweezer + combined | 36 | +5.70% | 58.3% |
| 本次 (4/1-6/12) | v2 真三軸 | breakout (簡化) | 120 | +1.35% | 43.3% |

**差距原因（追查）**：
1. Phase 4 用更選擇性的 kline 組合（tweezer + combined）、本次用較寬鬆的 breakout、訊號質地差
2. 延長 1 個月（4 月）後加進大量訊號、整體 wr 拉低
3. xiaoge v2 比 chip_tight 嚴格、扣掉 ~57% 訊號、跟 kline 交集時 base rate 降低

## 後續

待 C6 出場規則 simulator（agent `af5ef8db70966e8e6` 跑中）完成後：
1. 用 C6 重跑這四種 setup
2. 嘗試 Phase 4 原版組合（chip_tight + tweezer combined）+ C6 exit + 三維檢驗
3. 若仍未達標 → 確認 cross_xiaoge_kline 是 watch-only、不上 production

## 重現

```bash
PYTHONPATH=scripts python3 -m scripts.cross_courses.backtest_cross_xiaoge_kline
```

輸出: `data/analysis/xiaoge/backtest/cross_xiaoge_kline_extended.csv`
