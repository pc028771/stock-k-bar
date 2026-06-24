# Phase 4 long-sample — D5 + ch13 teacher combo backtest

> Source: `scripts/xiaoge/backtest_phase4_long.py`
> Detector: `scripts/xiaoge/entry/flying_stock_screener.py`
> Date: 2026-06-25
> Universe: teacher 99 (99 tickers, with 2024 lookahead)
> Exit: C6 (MA10 trail)

## 🔴 重點摘要

**長 sample 把所有 detector 砍到 ~37% WR、確認 D5 整套不是 edge：**

| Detector | 短 sample WR | 長 sample WR | 變化 |
|---|---|---|---|
| M3 主力連 3 天買 | 57.5% | **37.8%** | **-19.7pp** |
| M4 外資連 3 天買 | 49.7% | 37.5% | -12.2pp |
| M5 投信連 3 天買 | 50.0% | 39.8% | -10.2pp |
| M6 波動度↑強勢 | 25.6% | 37.7% | +12.1pp |
| M7 20 日新高 | 43.2% | 36.2% | -7.0pp |
| KD 黃金交叉 | 45.5% | 37.2% | -8.3pp |
| combinator ≥3 | 47.9% | 37.9% | -10.0pp |
| combinator ≥4 | 48.8% | 37.6% | -11.2pp |

**老師 ch13 示範組合 (M3 ∩ M6 ∩ KD) 長 sample 結果：**
- 30 個月只 n=15、WR 33.3%、avg -0.03% → **reverse-signal 候選**
- 老師示範的「超眾、亞光」是 hindsight 案例、非統計 edge

**所有 short 跨 30 個月都 WR ~33% < 35%** → 全部反向訊號、teacher universe 在 2024-2026 整體 trending up

## 🔴 結論

1. **D5 整套 detector 都不該落地 scanner/monitor** — 跨 30 個月 sample WR 一致 ~37%（隨機略好、不是 edge）
2. **ch13 老師示範組合不可靠** — 樣本稀少 + WR 低於隨機
3. **跨年驗證的重要性** — 短 sample 看到 WR 57% (M3) 是 2026 Q2 regime conditional 假象
4. **方法論教訓記入 [[feedback-detector-regime-conditional]]**：5-6 月小 sample 跑出來的 high WR 必須拉長到 2+ 年驗證

對應 user memory `feedback_detector_regime_conditional` 親身驗證：
> 部署前必跑 2023+2024+當年、regime-conditional 要加 regime gate

D5 跑長 sample 後 WR 從 50%+ 降到 37%、跟 memory 警告完全一致。

## Short sample (2026-05-01 ~ 2026-06-12, ~30 days)

| Detector | n | WR | avg | median | hold | tickers | months | Verdict |
|---|---|---|---|---|---|---|---|---|
| M3 main_buy_streak3 | 87 | 57.5% | 9.65% | 1.94% | 10.0 | 80 | 1 | insufficient diversity |
| M4 foreign_buy_streak3 | 169 | 49.7% | 4.32% | 0.0% | 7.8 | 96 | 2 | watch-only |
| M5 invest_trust_buy_streak3 | 92 | 50.0% | 2.66% | 0.08% | 6.4 | 55 | 2 | watch-only |
| M6 vol_rising_strong (2pp) | 78 | 25.6% | 4.7% | -2.79% | 7.8 | 67 | 2 | reverse-signal candidate |
| M7 break_20d_high | 148 | 43.2% | 6.05% | -0.79% | 10.1 | 98 | 2 | watch-only |
| KD golden_cross | 165 | 45.5% | 6.86% | -0.13% | 9.2 | 99 | 2 | watch-only |
| ch13 teacher combo: M3 ∩ M6 ∩ KD | 1 | 0.0% | -5.37% | -5.37% | 1.0 | 1 | 1 | insufficient diversity |
| combinator score>=2 | 164 | 49.4% | 5.83% | 0.0% | 9.1 | 97 | 2 | watch-only |
| combinator score>=3 | 94 | 47.9% | 5.58% | 0.0% | 9.5 | 78 | 2 | watch-only |
| combinator score>=4 | 41 | 48.8% | 9.08% | 0.0% | 11.1 | 41 | 1 | insufficient diversity |
| S3 main_sell_streak3 (short) | 55 | 16.4% | -5.23% | -5.55% | 3.1 | 49 | 1 | insufficient diversity |
| S6 vol_rising_weak (short) | 56 | 32.1% | -1.61% | -2.02% | 3.6 | 49 | 2 | reverse-signal candidate |
| KD death_cross (short) | 233 | 33.0% | -1.25% | -2.05% | 2.9 | 99 | 2 | reverse-signal candidate |
| ch13 short combo: S3 ∩ S6 ∩ KDdx | 0 | None% | None% | None% | None | 0 | 0 | no signals |
| short combinator score>=3 | 30 | 20.0% | -2.6% | -3.33% | 3.8 | 25 | 2 | reverse-signal candidate |

## Long sample (2024-01-01 ~ 2026-06-12, ~600 days)

| Detector | n | WR | avg | median | hold | tickers | months | Verdict |
|---|---|---|---|---|---|---|---|---|
| M3 main_buy_streak3 | 2767 | 37.8% | 1.52% | -0.93% | 6.6 | 99 | 29 | watch-only |
| M4 foreign_buy_streak3 | 2986 | 37.5% | 1.26% | -0.89% | 6.2 | 99 | 30 | watch-only |
| M5 invest_trust_buy_streak3 | 901 | 39.8% | 1.03% | -0.87% | 5.5 | 82 | 29 | watch-only |
| M6 vol_rising_strong (2pp) | 852 | 37.7% | 2.58% | -1.9% | 8.9 | 99 | 30 | watch-only |
| M7 break_20d_high | 1774 | 36.2% | 2.06% | -1.91% | 9.2 | 99 | 30 | watch-only |
| KD golden_cross | 4021 | 37.2% | 1.43% | -0.94% | 6.5 | 99 | 30 | watch-only |
| ch13 teacher combo: M3 ∩ M6 ∩ KD | 15 | 33.3% | -0.03% | -4.57% | 6.6 | 13 | 10 | reverse-signal candidate |
| combinator score>=2 | 3152 | 37.3% | 1.58% | -1.09% | 6.9 | 99 | 30 | watch-only |
| combinator score>=3 | 1423 | 37.9% | 2.28% | -1.14% | 8.3 | 99 | 30 | watch-only |
| combinator score>=4 | 396 | 37.6% | 3.06% | -1.78% | 9.5 | 97 | 29 | watch-only |
| S3 main_sell_streak3 (short) | 3062 | 33.7% | -0.85% | -1.3% | 5.9 | 99 | 29 | reverse-signal candidate |
| S6 vol_rising_weak (short) | 511 | 31.3% | -1.75% | -2.87% | 6.8 | 98 | 30 | reverse-signal candidate |
| KD death_cross (short) | 4225 | 33.7% | -0.58% | -1.25% | 5.7 | 99 | 30 | reverse-signal candidate |
| ch13 short combo: S3 ∩ S6 ∩ KDdx | 26 | 19.2% | -3.9% | -4.98% | 7.1 | 20 | 14 | reverse-signal candidate |
| short combinator score>=3 | 1468 | 33.8% | -0.83% | -1.62% | 7.4 | 99 | 30 | reverse-signal candidate |

## Short vs Long 對比

| Detector | Short WR | Long WR | Δ WR | Short avg | Long avg |
|---|---|---|---|---|---|
| M3 main_buy_streak3 | 57.5% | 37.8% | -19.7pp | +9.65% | +1.52% |
| M4 foreign_buy_streak3 | 49.7% | 37.5% | -12.2pp | +4.32% | +1.26% |
| M5 invest_trust_buy_streak3 | 50.0% | 39.8% | -10.2pp | +2.66% | +1.03% |
| M6 vol_rising_strong (2pp) | 25.6% | 37.7% | +12.1pp | +4.70% | +2.58% |
| M7 break_20d_high | 43.2% | 36.2% | -7.0pp | +6.05% | +2.06% |
| KD golden_cross | 45.5% | 37.2% | -8.3pp | +6.86% | +1.43% |
| ch13 teacher combo: M3 ∩ M6 ∩ KD | 0.0% | 33.3% | +33.3pp | -5.37% | -0.03% |
| combinator score>=2 | 49.4% | 37.3% | -12.1pp | +5.83% | +1.58% |
| combinator score>=3 | 47.9% | 37.9% | -10.0pp | +5.58% | +2.28% |
| combinator score>=4 | 48.8% | 37.6% | -11.2pp | +9.08% | +3.06% |
| S3 main_sell_streak3 (short) | 16.4% | 33.7% | +17.3pp | -5.23% | -0.85% |
| S6 vol_rising_weak (short) | 32.1% | 31.3% | -0.8pp | -1.61% | -1.75% |
| KD death_cross (short) | 33.0% | 33.7% | +0.7pp | -1.25% | -0.58% |
| ch13 short combo: S3 ∩ S6 ∩ KDdx | 0.0% | 19.2% | +19.2pp | +0.00% | -3.90% |
| short combinator score>=3 | 20.0% | 33.8% | +13.8pp | -2.60% | -0.83% |
