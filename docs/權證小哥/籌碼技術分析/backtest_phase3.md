# Phase 3a — main_chip_holder + cross detector backtest

> Source: `scripts/xiaoge/backtest_phase3.py`
> Date: 2026-06-14
> 樣本：2026-05-01 ~ 2026-06-12 (30 trading days)

## 結果對比

| Detector | n | avg_ret | median | win_rate | avg_hold | max | min |
|---|---|---|---|---|---|---|---|
| detector 1: bb_squeeze (升龍拳)| 67 | +1.02% | -0.87% | 37.3% | 6.0 | +43.72% | -10.71% |
| detector 2: main_chip_holder (5% ratio) | 1600 | +1.26% | -0.30% | 45.6% | 6.1 | +125.81% | -33.29% |
| **detector 2 tight (10% ratio)** | **1034** | **+1.65%** | -0.23% | **46.9%** | 6.4 | +125.81% | -33.29% |
| cross (bb ∩ chip, 1d 同日) | 32 | -0.77% | -1.23% | 34.4% | 3.5 | +8.50% | -10.71% |
| cross (bb ∩ chip, 5d window) | 68 | +0.62% | -1.06% | 39.7% | 5.4 | +43.72% | -14.93% |

## 觀察

### 1. detector 2 (10% ratio) 是目前最好
- 1034 訊號 / +1.65% avg / 46.9% win rate
- 比 detector 1 提升 +0.63% avg、+9.6% win rate
- 樣本夠大 (1034) → 統計可信度比 detector 1 (67) 高很多
- 但訊號量太多、需要 universe filter 或加分機制收斂

### 2. cross 邏輯反而拖累、不是加分
- 1d 同日交叉: -0.77% / 34.4% — **比兩個 detector 單獨用都差**
- 5d window: 0.62% / 39.7% — 介於兩者之間
- **結論：** bb 跟 chip 不是 reinforcing 訊號、是不同來源的訊號（bb=技術突破、chip=持續累積）
- 兩個同時觸發時、價格已經過了 sweet spot

### 3. detector 2 抓到一堆好股
exit_price=0 已過濾 (3 筆 data 異常)、剩下 winners:

| ticker | signal | hold | ret_pct |
|---|---|---|---|
| 2478 | 5/15 | 19 | +125.81% |
| 2492 | 5/19 | 17 | +104.24% |
| 3147 | 5/18 | 18 | +86.59% |
| 3624 | 5/12 | 22 | +80.21% |
| 6173 | 5/19 | 17 | +68.60% |
| 6548 | 5/22 | 14 | +68.11% |
| 5426 | 5/22 | 14 | +63.05% |
| 5464 | 5/4 | 8 | +62.70% |
| 5321 | 5/15 | 19 | +60.62% |
| 4916 | 5/15 | 19 | +60.57% |

含群創 (6173)、好幾檔大漲股都抓到。

## 資料限制

- **集保戶數**：DB `custody_accounts` 全 None、未匯入。detector 2 缺第 3 軸 (老師三軸論的關鍵)。
- **散戶賣超**：DB 無對應欄位、detector 2 缺第 2 軸。
- 目前 detector 2 = 主力買超（用 `main_force_5d` 機構代理）+ 月線上揚 + 站上月線。**只有一軸 + 兩個 trend filter**。
- 真正的「主力 ≥ 20 張」分點門檻待 FinMind 分點 audit。

## Phase 3 結論

- ✅ detector 2 跑得起來、品質比 detector 1 好
- ❌ cross (bb ∩ chip) **無效**、不採用
- ⚠️ 真三軸 (主力 + 散戶 + 集保戶) 必須等資料補齊
- ✅ 已 commit 進 main、可入 daily scanner 但需 universe filter

## 待辦 (Phase 3b)

1. **資料 audit**:
   - FinMind 是否有 `custody_accounts` 對應 dataset (`TaiwanStockShareholding`)
   - FinMind 分點 dataset 完整度
2. **detector 4**: 真正的 `key_broker_signal` (關鍵分點低買高賣)
3. **detector 2 升級**: 集保戶數補進來、做真三軸

## 重現

```bash
python3 -m scripts.xiaoge.backtest_phase3
```

輸出檔：
- `data/analysis/xiaoge/backtest/phase3_bb_only.csv`
- `data/analysis/xiaoge/backtest/phase3_chip_only.csv`
- `data/analysis/xiaoge/backtest/phase3_chip_tight.csv`
- `data/analysis/xiaoge/backtest/phase3_cross_1d.csv`
- `data/analysis/xiaoge/backtest/phase3_cross_5d.csv`
- 本報告
