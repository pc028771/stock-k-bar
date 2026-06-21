# Phase 4 — D5 flying_stock_screener backtest

> Source: `scripts/xiaoge/backtest_phase4.py`
> Detector: `scripts/xiaoge/entry/flying_stock_screener.py`
> Date: 2026-06-19
> Universe: teacher 99 (99 tickers — 老師 picks_2026 ∪ teacher_sector_tickers ∩ bb/chip 候選)
> Sample: 2026-05-01 ~ 2026-06-12 (30 trading days)
> 進場閾值: streak n=3, 新高 lookback=20
> 出場規則: **C6** (MA10 容忍 + 量比 + 連 2 天容忍 → 隔日開盤出)

## 🔴 重點摘要

- **沒有 sub-detector 達 actionable 65% WR**、全部 long 落在 43-58%
- **M3 主力連 3 天買最強**：WR 57.5% / avg +9.65% / n=87、但 cross-month=1 (5 月集中、6 月也只 12 天 holdout 抓不到 streak)
- **combinator score≥3 最 selective**：WR 52.9% / avg +7.50% / n=68 / 2 months 跨度
- **所有 short 都是反向訊號** (WR 10-24%)、teacher universe 「機構/外資/投信賣超」反而強勢、空頭加進 skip-list
- 對比 D4 (WR 41.9% / +6.58% / n=62)、M3 + combinator 表現略勝、但都未達標
- **結論**: 跟 D4 一樣 watch-only、不落地 scanner/monitor

## 結果

| Detector | n | avg_ret | median | win_rate | avg_hold | tickers | months | max | min |
|---|---|---|---|---|---|---|---|---|---|
| M3 main_buy_streak3 (long) | 87 | 9.65% | 1.94% | 57.5% | 10.0 | 80 | 1 | 172.0% | -15.43% |
| M4 foreign_buy_streak3 (long) | 156 | 4.89% | 0.31% | 51.9% | 8.3 | 96 | 2 | 172.0% | -21.53% |
| M5 invest_trust_buy_streak3 (long) | 78 | 3.4% | 0.36% | 52.6% | 7.2 | 51 | 2 | 121.14% | -19.21% |
| M7 break_20d_high (long) | 148 | 6.05% | -0.79% | 43.2% | 10.1 | 98 | 2 | 155.8% | -19.31% |
| combinator long: score>=2 | 131 | 6.58% | 1.2% | 53.4% | 9.8 | 94 | 2 | 172.0% | -19.21% |
| combinator long: score>=3 | 68 | 7.5% | 0.2% | 52.9% | 10.6 | 61 | 2 | 155.8% | -14.13% |
| S3 main_sell_streak3 (short) | 55 | -5.23% | -5.55% | 16.4% | 3.1 | 49 | 1 | 13.33% | -26.61% |
| S4 foreign_sell_streak3 (short) | 128 | -2.98% | -2.78% | 24.2% | 2.8 | 76 | 2 | 20.96% | -35.86% |
| S5 invest_trust_sell_streak3 (short) | 108 | -3.52% | -2.64% | 23.1% | 2.4 | 54 | 2 | 17.34% | -16.48% |
| S7 break_20d_low (short) | 44 | -3.48% | -3.25% | 20.5% | 3.6 | 39 | 2 | 8.69% | -14.68% |
| combinator short: score>=2 | 64 | -4.85% | -5.12% | 10.9% | 3.1 | 51 | 2 | 20.96% | -26.61% |


## Robustness Verdicts

> 跨股 ≥ 5 + 跨月 ≥ 2 + win_rate ≥ 65% = actionable
> 50-65% = watch-only
> ≤ 35% = 反向訊號 skip 清單

- **M3 main_buy_streak3 (long)**: insufficient diversity (tickers=80, months=1, win_rate=57.5%) → not robust
- **M4 foreign_buy_streak3 (long)**: watch-only (tickers=96, months=2, win_rate=51.9%)
- **M5 invest_trust_buy_streak3 (long)**: watch-only (tickers=51, months=2, win_rate=52.6%)
- **M7 break_20d_high (long)**: watch-only (tickers=98, months=2, win_rate=43.2%)
- **combinator long: score>=2**: watch-only (tickers=94, months=2, win_rate=53.4%)
- **combinator long: score>=3**: watch-only (tickers=61, months=2, win_rate=52.9%)
- **S3 main_sell_streak3 (short)**: insufficient diversity (tickers=49, months=1, win_rate=16.4%) → not robust
- **S4 foreign_sell_streak3 (short)**: reverse-signal candidate (tickers=76, months=2, win_rate=24.2%) — skip-list
- **S5 invest_trust_sell_streak3 (short)**: reverse-signal candidate (tickers=54, months=2, win_rate=23.1%) — skip-list
- **S7 break_20d_low (short)**: reverse-signal candidate (tickers=39, months=2, win_rate=20.5%) — skip-list
- **combinator short: score>=2**: reverse-signal candidate (tickers=51, months=2, win_rate=10.9%) — skip-list
