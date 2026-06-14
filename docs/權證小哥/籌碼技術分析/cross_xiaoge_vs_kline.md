# Phase 4 — xiaoge vs kline_course 同期 detector 對比

> 產出日期：2026-06-14
> 對比工具：`scripts/xiaoge/compare_with_kline.py`
> 任務目標：找出兩套 detector 命中股票的重疊 / 互補關係，回答「cross_xiaoge_kline」是否值得工程化。

## 1. 樣本

| 來源 | n trades | 唯一 ticker | signal/entry 區間 | 平均報酬 | 勝率 |
|---|---|---|---|---|---|
| xiaoge_chip_tight (detector 2 tight) | 1034 | 745 | signal 2026-05-04 ~ 05-22 | +1.65% | 46.9% |
| xiaoge_bb_squeeze (detector 1) | 67 | 67 | signal 2026-05-04 ~ 05-22 | — | — |
| kline_course (tweezer + combined union) | 635 | 365 | entry 2026-05-04 ~ 06-04 | +1.24% | 44.3% |

> 注意：kline backtest 因為 `hold_days` 出場需要、最末端訊號（>6/4）尚未收尾、不出現在 trades CSV。

兩邊都覆蓋的「對齊區間」=`2026-05-01 ~ 2026-05-25`（xiaoge 受 hold-window 限制 entry_date 最晚到 5/25、kline 在區間內可全給）。對齊後 xiaoge=1034、kline=425。

### kline detector 組合
本次 kline 側用 `tweezer_top_breakout`（默認）+ `combined_pattern_or_tweezer`（含 bull_engulfing/morning_star_harami/rising_falling/outside_three_black 等多個 pattern）的 union，是 `scripts/kline/entry/` 既有 entry 中涵蓋最廣的 2 個。沒跑 `breakout_attack` / `shoulder_gap_up_pullback` 之類其它 entry，可能讓 kline 命中面再寬一些、但不影響本次對比結論。

## 2. Overlap 統計表

### 嚴格重疊（ticker × entry_date 完全相同）

| 集合 | n | 唯一 ticker | avg_ret | median | win_rate | max | min |
|---|---|---|---|---|---|---|---|
| **∩ cross (xiaoge perf side)** | **36** | 34 | **+5.70%** | +1.23% | **58.3%** | +125.81% | -21.64% |
| ∩ cross (kline perf side) | 36 | 34 | +0.35% | -1.59% | 33.3% | +34.83% | -8.15% |
| xiaoge only | 998 | 726 | +1.50% | -0.24% | 46.5% | +97.93% | -33.29% |
| kline only | 389 | 251 | +2.25% | 0.00% | 48.8% | +235.40% | -19.29% |
| xiaoge total | 1034 | 745 | +1.65% | -0.23% | 46.9% | +125.81% | -33.29% |
| kline total | 425 | 267 | +2.08% | -0.27% | 47.5% | +235.40% | -19.29% |

### 寬鬆重疊（ticker × entry_date ±5 日）

| 集合 | n | 唯一 ticker | avg_ret | win_rate |
|---|---|---|---|---|
| ∩ cross ±5d (xiaoge side) | 144 | 123 | **+5.14%** | **59.0%** |
| ∩ cross ±5d (kline side) | 136 | 123 | +2.08% | 50.0% |

### 觀察

1. **cross signal 對 xiaoge side 有顯著 lift**：avg_ret +5.70% vs xiaoge total +1.65%（Δ +4.05%、約 3.5× 倍率）、win_rate 58.3% vs 46.9%。
2. **cross signal 對 kline side 反而拉低報酬**：+0.35% vs +2.08% kline total。原因是 kline 出場機制（reversal_k / breakout / sunrise_attack_end）持有日數短（中位數 1-2 日）、xiaoge 持 14-19 日；同樣的 trigger，kline 短期出場剛好碰上震盪、xiaoge 抱到後續飆段。**這不是 detector 差異、是 exit 規則差異**。
3. **兩套 detector universe 重疊度很低**：嚴格 36/1023 ≈ 3.5%、寬鬆 ±5d 144/1023 ≈ 14%。互補性極高。

## 3. Top winners 對照

### xiaoge Top 20 winners（kline 是否抓到？）

| ticker | xg_entry | xg_ret | kline_exact | kline_±5d | kline_曾掃到 |
|---|---|---|---|---|---|
| 2478 | 05-18 | **+125.81%** | ✅ | ✅ | ✅ |
| 3026 | 05-19 | +97.93% | ❌ | ✅ | ✅ |
| 3147 | 05-19 | +86.59% | ❌ | ❌ | ❌ |
| 6173 | 05-20 | +68.60% | ❌ | ✅ | ✅ |
| 6548 | 05-25 | +68.11% | ❌ | ❌ | ❌ |
| 5426 | 05-25 | +63.05% | ❌ | ❌ | ❌ |
| 5464 | 05-05 | +62.70% | ❌ | ❌ | ✅ |
| 5321 | 05-18 | +60.62% | ❌ | ❌ | ❌ |
| 6182 | 05-19 | +59.61% | ❌ | ❌ | ❌ |
| 3624 | 05-15 | +58.57% | ❌ | ✅ | ✅ |
| 8042 | 05-20 | +53.60% | ❌ | ❌ | ❌ |
| 1714 | 05-19 | +53.33% | ❌ | ❌ | ❌ |
| 2483 | 05-19 | +51.02% | ❌ | ❌ | ❌ |
| 2911 | 05-18 | +50.17% | ❌ | ❌ | ❌ |
| 2492 | 05-25 | +49.51% | ❌ | ✅ | ✅ |
| 1409 | 05-25 | +46.69% | ❌ | ❌ | ❌ |
| 4916 | 05-19 | +44.87% | ❌ | ❌ | ❌ |
| 9136 | 05-20 | +40.09% | ❌ | ❌ | ❌ |
| 8162 | 05-19 | +37.97% | ❌ | ✅ | ✅ |
| 6449 | 05-12 | +37.36% | ❌ | ❌ | ❌ |

**統計**：xiaoge Top 20 winners 中、kline exact 1/20、±5d 6/20、任意期間 7/20。**kline 漏掉 65% xiaoge 大贏家**（13 檔在整個對齊區間都沒掃到）。

### kline Top 20 winners（xiaoge 是否抓到？）

| ticker | kl_entry | kl_ret | xg_exact | xg_±5d | xg_曾掃到 |
|---|---|---|---|---|---|
| 8291 | 05-06 | **+235.40%** | ❌ | ❌ | ❌ |
| 3090 | 05-14 | +73.78% | ❌ | ❌ | ✅ |
| 3026 | 05-20 | +39.95% | ❌ | ✅ | ✅ |
| 1568 | 05-25 | +36.61% | ❌ | ❌ | ✅ |
| 6834 | 05-19 | +35.46% | ❌ | ❌ | ❌ |
| 2478 | 05-18 | +34.83% | ✅ | ✅ | ✅ |
| 3236 | 05-20 | +34.06% | ❌ | ❌ | ✅ |
| 6166 | 05-07 | +33.53% | ❌ | ❌ | ✅ |
| 2492 | 05-20 | +32.95% | ❌ | ✅ | ✅ |
| 2472 | 05-25 | +30.84% | ❌ | ❌ | ❌ |
| 8455 | 05-15 | +29.64% | ❌ | ❌ | ❌ |
| 3577 | 05-19 | +25.30% | ❌ | ❌ | ❌ |
| 2395 | 05-04 | +24.55% | ❌ | ✅ | ✅ |
| 3498 | 05-12 | +23.89% | ❌ | ✅ | ✅ |
| 3624 | 05-14 | +23.75% | ❌ | ✅ | ✅ |
| 1595 | 05-04 | +23.31% | ❌ | ❌ | ❌ |
| 2395 | 05-05 | +21.60% | ✅ | ✅ | ✅ |
| 4127 | 05-20 | +20.80% | ❌ | ❌ | ❌ |
| 2492 | 05-11 | +20.00% | ❌ | ✅ | ✅ |
| 2472 | 05-07 | +18.89% | ❌ | ❌ | ❌ |

**統計**：kline Top 20 winners 中、xiaoge exact 2/20、±5d 8/20、任意期間 12/20。kline 也有 8 檔大贏家是 xiaoge 完全沒抓到。**8291 +235% 連續漲停股 kline 抓得到、xiaoge 完全沒掃到**（已查 DB raw bars 確認是真實連續漲停、不是還原誤差）。

## 4. 各自的盲點清單

### xiaoge 完全沒抓 / kline 抓到的好股（ret ≥ 5%、xiaoge 整個對齊區間都沒掃到）

| ticker | kl entry | ret_pct |
|---|---|---|
| **8291** | 05-06 | **+235.40%** |
| 6834 | 05-19 | +35.46% |
| 2472 | 05-25 | +30.84% |
| 8455 | 05-15 | +29.64% |
| 3577 | 05-19 | +25.30% |
| 1595 | 05-04 | +23.31% |
| 4127 | 05-20 | +20.80% |
| 2472 | 05-07 | +18.89% |
| 6239 | 05-22 | +18.81% |
| 8091 | 05-14 | +17.87% |

完整 41 筆見 `compare_with_kline.py` Section 5 輸出。**8291 是最大盲點**：連續漲停股、籌碼/BB squeeze 條件都不符（屬於 momentum / pattern breakout）。

### kline 完全沒抓 / xiaoge 抓到的好股（ret ≥ 20%、kline 整個對齊區間都沒掃到）

| ticker | xg entry | ret_pct |
|---|---|---|
| 3147 | 05-19 | +86.59% |
| 6548 | 05-25 | +68.11% |
| 5426 | 05-25 | +63.05% |
| 5321 | 05-18 | +60.62% |
| 6182 | 05-19 | +59.61% |
| 8042 | 05-20 | +53.60% |
| 1714 | 05-19 | +53.33% |
| 2483 | 05-19 | +51.02% |
| 2911 | 05-18 | +50.17% |
| 1409 | 05-25 | +46.69% |
| 4916 | 05-19 | +44.87% |
| 9136 | 05-20 | +40.09% |
| 6449 | 05-12 | +37.36% |
| 1563 | 05-20 | +36.20% |
| 5227 | 05-15 | +36.12% |
| 6585 | 05-25 | +35.51% |
| 9105 | 05-25 | +34.77% |
| 2491 | 05-05 | +33.13% |
| 3290 | 05-25 | +31.00% |
| 2881 | 05-20 | +30.79% |

完整 32 筆見輸出。觀察：xiaoge 不需要 K 線 pattern（tweezer/bull engulfing 等）即可命中、籌碼壓縮先發生 → 抓到很多「籌碼集中但 K 線尚未發力」的標的。

## 5. cross signal 細節（32 個嚴格重疊全表）

最強配合（兩套都觸發、xiaoge 抱到大段、kline 短出場）：

| ticker | entry | xg_ret | kl_ret | kl_entry | kl_exit_reason | xg_hold | kl_hold |
|---|---|---|---|---|---|---|---|
| 2478 | 05-18 | +125.81% | +34.83% | tweezer | bearish_engulfing | 19 | 5 |
| 2428 | 05-20 | +36.98% | +7.74% | tweezer | gap_attack_filled | 17 | 3 |
| 2891 | 05-20 | +20.21% | -0.69% | tweezer | supply_zone_reach | 17 | 1 |
| 2395 | 05-05 | +17.90% | +21.60% | combined_pattern | sunrise_attack_end | 7 | 4 |
| 8926 | 05-11 | +15.76% | +4.38% | combined_pattern | sunrise_attack_end | 6 | 1 |
| 6414 | 05-25 | +14.73% | -1.51% | tweezer | bearish_engulfing | 14 | 1 |

兩套同 trigger 時、**33/36 是 tweezer/combined pattern**（K 線 pattern entry）、**沒有出現 breakout_attack 或 sunrise_attack** 同步 — 反映兩套對「K 線 reversal pattern + 籌碼壓縮」這個 setup 有一致 detection。

## 6. 結論

### 6a. 是否互補？

**答：高度互補**。

證據：
- 嚴格 overlap 僅 36/1023 ≈ 3.5%、寬鬆 ±5d 144/1023 ≈ 14%、絕大多數訊號都是各自獨有。
- xiaoge Top 20 大贏家、kline 漏掉 13 檔（65%）。
- kline Top 20 大贏家、xiaoge 漏掉 8 檔（40%）、含 +235% 的 8291。
- 兩套捕捉不同型態：
  - xiaoge → 籌碼集中（主力持股、BB squeeze）優先、不需 K 線 pattern
  - kline → K 線 reversal pattern（tweezer/engulfing/morning_star）+ 突破

### 6b. cross_xiaoge_kline 工程化是否值得？

**答：值得做、但要注意 hold/exit 規則差異**。

證據：
- cross signal 在 xiaoge exit rules 下 avg_ret +5.70% / wr 58.3%（vs xiaoge total +1.65% / 46.9%）→ **3.5× lift on return, +11.4pp on win rate**。
- cross signal n=36，雖小但勝率穩定、若擴大 ±5d 視窗 n=144 仍維持 +5.14% / wr 59.0%。
- **但 cross signal 在 kline exit rules 下反而拖低（+0.35%）** → 工程化時必須採用 xiaoge style hold（或設計新的 exit 機制能抱到後續飆段）。

### 6c. 不該做 cross 的情境

- 如果用 kline 的 short-hold exit（中位數 1-2 日）、cross signal 沒任何 edge。
- 36 筆嚴格 cross 樣本偏小、單一區間結論不能直接外推到 2026 全年；需擴大 backtest 至 2025 全年再驗證。

### 6d. 建議下一步

1. **擴大樣本驗證**：把 xiaoge backtest 拉長到 2025-01 ~ 2026-05 並重跑 kline merged，看 cross signal lift 是否穩定（>200 筆樣本以上才有信心）。
2. **設計 cross-aware exit 規則**：cross 訊號出現時、延長 hold（如 ≥10 日 vs kline default 1-5 日）；可參考 xiaoge `simulate_trades` 的 hold/exit 邏輯。
3. **盲點補強策略**：
   - kline 不該漏 8291 這種連續漲停 — 看 `breakout_attack` entry 是否能補（本次未測）。
   - xiaoge 不該漏 3147/6548 等 — 看是否是 chip_ratio 0.10 太嚴、寬鬆到 0.05 (`phase3_chip_only.csv`) 是否能補。
4. **不要先做 cross scanner**：先把兩套各自盲點補完、再回頭評估 cross 是否仍有獨立 edge。同 trigger 但兩套都漏的好股（如 8291）是更大的 edge 來源。

## 7. 原始輸出

- `data/analysis/xiaoge/backtest/phase3_chip_tight.csv` — xiaoge source
- `/tmp/kline_bt_fresh.csv` — kline tweezer_top_breakout（fresh 2026-06-14）
- `/tmp/kline_bt_combined.csv` — kline combined_pattern_or_tweezer
- `/tmp/kline_bt_merged.csv` — 上述兩者 union, dedupe by (ticker, entry_date)
- `scripts/xiaoge/compare_with_kline.py` — 對比腳本

Reproduce:
```bash
cd /Users/howard/Repository/stock-k-bar/scripts
python3 backtest.py --entry tweezer_top_breakout --out /tmp/kline_bt_fresh.csv
python3 backtest.py --entry combined_pattern_or_tweezer --out /tmp/kline_bt_combined.csv
# Merge step in compare_with_kline.py
cd /Users/howard/Repository/stock-k-bar
python3 -m scripts.xiaoge.compare_with_kline
```
