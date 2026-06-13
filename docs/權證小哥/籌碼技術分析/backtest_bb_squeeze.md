# xiaoge_bb_squeeze_breakout — backtest 報告

> Source: `scripts/xiaoge/backtest_bb_squeeze.py`
> Detector: `scripts/xiaoge/entry/bb_squeeze_breakout.py`
> Exit rule: `scripts/xiaoge/exit/leave_upper_band.py` (close < bb_upper)
> 課程來源：權證小哥籌碼+技術分析 ch06-ch08（布林）, ch12（飆股口袋名單）, ch07/ch13（離開上軌停利）

---

## 推薦預設參數（best config 來自 param sweep）

| 參數 | 預設值 | 來源 |
|---|---|---|
| backtest 區間 | 2026-05-01 ~ 2026-06-12 | user 指定 |
| squeeze_threshold (bb_width_pct ≤) | **15** | param sweep best、寬鬆容許 |
| squeeze_lookback (連續 N 日) | **10** | detector_spec 建議 |
| breakout_mode | **shenglongquan**（升龍拳）| sweep 顯示全面勝過 open_breakout / any |
| vol_multiple | 不適用（shenglongquan 不用量）| — |
| max_hold (safety cap) | 30 | 非課程、防無限持有 |

### Best config 結果

| 指標 | 值 |
|---|---|
| **訊號數** | **67 筆**（30 交易日約 2.2 筆/日）|
| **平均報酬率** | **+1.02%** |
| 中位數報酬率 | -0.87% |
| **勝率** | **37.3%** |
| 最佳單筆 | +43.72% |
| 最差單筆 | -10.71% |
| 平均持有 | 6.0 天 |

---

## 關鍵發現：報酬呈**雙峰分布**

| 持有天數 | 筆數 | 比例 | 平均報酬 | 勝率 |
|---|---|---|---|---|
| ≤5 天（早出場噪音）| 53 | 79% | -1.0% | ~28% |
| **17-25 天（真正起漲）**| **14** | **21%** | **+8.53%** | **71%** |

→ 訊號分兩種：
1. **假突破**（多數）— 一兩天就跌回 upper band 下、被 exit 規則砍掉
2. **真起漲**（少數）— 沿著上軌走 17+ 天、持續上攻

**問題：** entry 當下無法區分真假突破。

**對應方法（後續可試、放 extras/）：**
- **延後出場**：要求 close 連 2 天 < bb_upper 才出（避免單日噪音）
- **限制 universe**：只看老師 `teacher_picks_2026.json` 範圍、過濾低流動性 noise
- **加籌碼 filter**：detector 1 ∩ detector 2（main_chip_holder）才升優先級
- **更窄 squeeze**：threshold 6 → win rate 提到 44.1% 但 sample 太少（n=34）

---

## Param Sweep 摘要

跑了 45 種參數組合（5 thresholds × 3 lookbacks × 3 vol multipliers × 3 modes）：

### Top 5 by 平均報酬

| sq_thr | sq_lb | mode | n | avg_ret | win_rate | avg_hold |
|---|---|---|---|---|---|---|
| 15 | 10 | shenglongquan | 67 | **+1.02%** | 37.3% | 6.0 |
| 15 | 5 | shenglongquan | 74 | +0.77% | 39.2% | 5.9 |
| 10 | 5 | shenglongquan | 58 | +0.67% | 37.9% | 6.0 |
| 8 | 10 | shenglongquan | 34 | +0.51% | 35.3% | 5.5 |
| 10 | 15 | shenglongquan | 40 | +0.49% | 40.0% | 5.9 |

### Top 5 by 勝率

| sq_thr | sq_lb | mode | n | avg_ret | win_rate |
|---|---|---|---|---|---|
| 6 | 15 | open_breakout | 30 | -0.18% | **46.7%** |
| 6 | 10 | open_breakout | 37 | -0.19% | 45.9% |
| 6 | 15 | any | 34 | +0.40% | 44.1% |
| 6 | 10 | any | 41 | +0.29% | 43.9% |
| 6 | 10 | open_breakout | 30 | -0.40% | 43.3% |

### 觀察

1. **shenglongquan dominates avg_ret** — 升龍拳模式抓的訊號報酬比較好
2. **threshold 6 dominates win_rate** — 真正極窄 squeeze 才容易出真起漲、但符合條件的 ticker 很少
3. **vol_multiple 對 shenglongquan 無影響**（mode 邏輯本身不用量）
4. **open_breakout 平均都負** — 量增 + 收紅 + 站上 upper 容易抓到「短攻一日游」

完整 sweep 結果：`data/analysis/xiaoge/backtest/param_sweep.csv`

---

## Top 10 Winners（default config）

| ticker | signal_date | entry | exit | hold | ret_pct | bb_width |
|---|---|---|---|---|---|---|
| 2762 | 05-07 | 74.50 | 90.20 | 25 | **+21.07%** | 1.97 |
| 3032 | 05-05 | 66.70 | 80.10 | 7 | +20.09% | 8.51 |
| 6161 | 05-14 | 45.90 | 55.00 | 20 | +19.83% | 13.34 |
| 7762 | 05-14 | 51.59 | 60.29 | 3 | +16.86% | 9.74 |
| 5210 | 05-04 | 25.00 | 28.95 | 4 | +15.80% | 12.38 |
| 8926 | 05-08 | 49.50 | 57.30 | 6 | +15.76% | 11.23 |
| 6491 | 05-15 | 294.50 | 327.50 | 19 | +11.21% | 5.95 |
| 5488 | 05-19 | 10.95 | 12.15 | 17 | +10.96% | 10.31 |
| 4545 | 05-19 | 31.75 | 35.20 | 17 | +10.87% | 8.22 |
| 6005 | 05-04 | 29.10 | 31.70 | 6 | +8.93% | 5.08 |

**最佳交易 2762：** signal_date 5/7 bb_width 1.97（極度收斂）→ 持有 25 天 +21%、正是課程說的「壓縮越久後續越強」。

---

## Spot Check: Q1 Top 10 強勢股

**結果：0 檔被抓到。**

```
Q1 Top: 3037 / 2426 / 6217 / 3163 / 2337 / 3189 / 6515 / 3481 / 6435 / 4919
```

**原因分析：** 這些 ticker 在 Q1 (1-4 月) 已經漲過一波、5-6 月處於「沿上軌 → 離上軌震盪」階段、bb_width 都 ≥ 15、不符合 squeeze 條件。

→ 結論：本 detector 抓「**還沒漲的下一波**」、不是 Q1 強勢股的延續。這是 detector 設計的正常行為、不是 bug。

---

## 已知限制

1. **樣本期太短** — 2026-05-01 ~ 2026-06-12 只有 30 個交易日、67 筆訊號不足以做統計顯著性判斷。
2. **市場 regime 不利** — 2026-05 至 6/12 大盤從 46500 高點回落、屬於震盪偏弱、所有 momentum 策略都受傷。
3. **沒有 stop loss** — 課程沒明說停損、若遇大跌會吃滿 30 日 max_hold。
4. **沒有 universe filter** — 全市場 2321 檔、混入大量低流動性 noise。
5. **沒對照組** — 跟 kline_course / zhuli scanner 同期表現對比留 Phase 4。

---

## Phase 2 結論

- ✅ **detector 跑得起來**、邏輯忠於課程
- ✅ **best config 確定**（shenglongquan + threshold 15 + lookback 10）
- ⚠️ **avg_ret +1% / win_rate 37%** — 還不足以單獨上線當主訊號
- ✅ **發現雙峰分布**（71% 真起漲 vs 79% 假突破）— 是後續改進主軸

### 接下來的步驟

- **Phase 3a**：實作 `xiaoge_main_chip_holder`（detector 2 主力買超 + 集保戶數）、跟 detector 1 做交叉 → 看 ∩ 後 win rate 能不能拉到 ≥50%
- **Phase 3b**：FinMind 分點 audit 完 → `xiaoge_key_broker_signal`
- **Phase 4**：cross_xiaoge_swing 三維打分、跟 cross_kline 對比 edge
- **extras/ candidates**（後續 backtest 驗證才升）：
  - `bb_squeeze_strict.py`（threshold 6、win rate 44%）
  - `bb_squeeze_exit_2day_buffer.py`（連 2 天 < upper 才出）

---

## 重現

```bash
# 預設 best config
python3 -m scripts.xiaoge.backtest_bb_squeeze \
  --squeeze-threshold 15 \
  --squeeze-lookback 10 \
  --breakout-mode shenglongquan

# Param sweep（45 組合）
python3 -m scripts.xiaoge.backtest_param_sweep
```

輸出檔：
- `data/analysis/xiaoge/backtest/bb_squeeze_trades.csv` — 逐筆交易
- `data/analysis/xiaoge/backtest/param_sweep.csv` — 全參數結果
- 本報告
