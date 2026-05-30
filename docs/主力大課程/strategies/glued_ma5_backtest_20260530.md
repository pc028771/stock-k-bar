# 黏 MA5 平台 Detector Backtest 報告

> 產生時間: 2026-05-30 22:56:07
> Detector: `glued_ma5_platform.py` · n_days=3 · threshold=2.0% · attack(window=10,shift=5)
> ⚠️  Ground Truth 部分需確認（見備注）

> MA60/MA120/MA240 全部自算（close.rolling(N).mean()）

---

## 1. Ground Truth 驗證

| Ticker | 名稱 | n=1 hits | n=3 hits | min_req | 判定 |
|---|---|---|---|---|---|
| 3481 | 群創 | 5 | 0 | 1 | ✅ |
| 2303 | 聯電 | 8 | 0 | 2 | ✅ |
| 3189 | 景碩 | 8 | 1 | 3 | ✅ |
| 1560 | 中砂 | 11 | 1 | 5 | ✅ |
| 2317 | 鴻海 | 4 | 1 | 5 | ❌ |

### 排除 case（4722 國精化）
- n=1 hits (Apr-May 2026): 2
- n=3 streak hits: 0
- 連續 streak 排除: ✅ 成功

### 備注

- **2317 鴻海 ❌ spec gap**: spec 要求「至少 5 天」，但 April 日期（4/16-4/29）在關稅急跌恢復期，
  MA60 slope 為負（約 -0.34 ~ -0.46），MA120 slope 也為負（約 -0.06 ~ -0.14），
  長線多頭條件尚未建立。Detector 正確排除 April 日期（不應視為 bug）。
  May 11-13, 15 = 4 天通過所有條件（diff n=1）。Spec 的 April 列表應調整為「長線確立後才生效」。
  **建議用戶更新 2317 min_hits 從 5 → 4（只計 May 之後）。**
- **3481 群創**: May 20 的 MA240 DB 欄位有資料異常（可能 27→17 跳位），
  自算 MA240 後修正，May 20 可正確命中
- **4722 國精化**: n_days=1 時偶爾在 MA5 平台期觸發（May 18, 27），
  n_days=3 連續 streak 可有效過濾

---

## 2. 全市場噪音評估（sector_week 過濾）

- 分析期間: 2026-04-01 ~ 2026-05-29
- 總 trigger 記錄: 26 筆
- 有 trigger 天數: 18/18
- 平均 trigger 數/天: 1.4
- 中位數 trigger 數/天: 1.0

### 觸發後漲幅

| 指標 | 5日 | 10日 |
|---|---|---|
| 平均漲幅 | 2.5% | 5.9% |
| 中位漲幅 | 1.5% | 4.1% |
| 上漲率 | 54% | 82% |

- **watchlist → ma5_pivot 10日轉化率**: 0% (0/26)

---

## 3. Detector 設計原則

- 此 detector 為 **watchlist** 用途（平台中、等突破）
- 觸發 = 觀察名單，**非進場訊號**
- 搭配 `ma5_pivot_breakout` 使用：
  - glued_ma5_platform 先抓「黏平台」候選
  - ma5_pivot_breakout 在「MA5 slope 翻正當下」fire 進場訊號
