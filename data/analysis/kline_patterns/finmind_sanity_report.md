# FinMind Sanity Backtest Report

生成時間：2026-06-03 22:08

## 說明

- Entry signal：Phase 4.3 advisor_branches，兩個高命中率 branch（exhaust_invalid）
- Entry timing：signal_date 隔日開盤（next_open）
- Exit rules：課程事件驅動（禁用固定 N 日報酬）
  - **Cond1**：收盤跌破進場日 low → 隔日開盤出場
  - **Cond2**：大黑K包覆（today.open ≥ entry.high AND today.close < entry.open AND today.close < today.open）→ 隔日開盤出場
  - **Cond3**：攻擊失敗（gap-up open 當日收盤回補）→ 當日收盤出場
  - **Timeout**：持有 60 交易日未觸發 → 強制結算（不計勝負）
- 資料來源：`~/.four_seasons/data.sqlite` standard_daily_bar（FinMind）
- 同一 (ticker, signal_date) 兩個 branch 都觸發 → 視為一筆 trade

---

## Phase 4.3 命中率 vs 實際勝率對比

| Branch | Phase 4.3 hit_rate | 實際 win_rate | 差異方向 |
|---|---|---|---|
| B1_next_day_gap_fills_up | 83.0% (n=3949) | 36.2% | ⚠️ 劇本≠賺錢 |
| B2_next_day_gap_filled | 84.2% (n=2737) | 36.0% | ⚠️ 劇本≠賺錢 |

> Phase 4.3 hit_rate = 「劇本在 matched_after_n_days 內成真」的比率（非獲利勝率）。
> 本 backtest win_rate = 依課程出場後實際報酬 > 0 的比率。

---

## 各 Branch 統計


### B1_next_day_gap_fills_up

| 指標 | 值 |
|---|---|
| n_total (trades) | 3277 |
| n_timeout (60d cap) | 0 |
| n_evaluated (non-timeout) | 3277 |
| **win_rate** | **36.2%** |
| avg_return | 0.08% |
| median_return | -1.07% |
| std_return | 7.95% |
| max_DD | -20.47% |
| max_gain | 114.22% |
| avg_hold_days | 2.5 d |
| median_hold_days | 1.0 d |

**出場條件分布：**
    - cond3_attack_fail: 2484
    - cond1_break_low: 738
    - cond2_black_engulf: 55



### B2_next_day_gap_filled

| 指標 | 值 |
|---|---|
| n_total (trades) | 2302 |
| n_timeout (60d cap) | 0 |
| n_evaluated (non-timeout) | 2302 |
| **win_rate** | **36.0%** |
| avg_return | 0.17% |
| median_return | -1.15% |
| std_return | 7.77% |
| max_DD | -20.47% |
| max_gain | 66.51% |
| avg_hold_days | 2.5 d |
| median_hold_days | 1.0 d |

**出場條件分布：**
    - cond3_attack_fail: 1772
    - cond1_break_low: 480
    - cond2_black_engulf: 50



### all_trades

| 指標 | 值 |
|---|---|
| n_total (trades) | 4544 |
| n_timeout (60d cap) | 0 |
| n_evaluated (non-timeout) | 4544 |
| **win_rate** | **36.3%** |
| avg_return | 0.19% |
| median_return | -1.06% |
| std_return | 7.79% |
| max_DD | -20.47% |
| max_gain | 114.22% |
| avg_hold_days | 2.6 d |
| median_hold_days | 1.0 d |

**出場條件分布：**
    - cond3_attack_fail: 3476
    - cond1_break_low: 984
    - cond2_black_engulf: 84


---

## 輸出檔案

- Trades CSV: `data/analysis/kline_patterns/finmind_sanity_trades.csv`
- Report: `data/analysis/kline_patterns/finmind_sanity_report.md`
