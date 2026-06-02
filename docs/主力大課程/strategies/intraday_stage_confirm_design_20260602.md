# 盤中即時 Stage 確認 SOP 設計 (2026-06-02)

> 目的: 把 Stage SOP 的「等隔日才能確認」壓縮到「盤中即時可判」
> 課程根據: Ch5-3 當沖 SOP (5/19 老師當沖實戰課)
> 限制: 此 SOP 用於「結構訊號日」(scanner 命中) 的當日尾盤確認 Stage 1 進場、不是當沖 entry

## 1. 信心分級 sizing (源自 user 6/2 自述)

### 訊號透明度分類

| 訊號類型 | 透明度 | sizing |
|---|---|---|
| 老師明示 (黑盒、不知背後研究) | 低 | Stage 1 試水 30-40% |
| 外部消息單 (黑盒) | 極低 | 混合判讀 B (技術派 exit) |
| 館前哥/站前哥大買 (白盒可驗證) | 高 | 可 all-in |
| 小結構噴發 (scanner 白盒) | 高 | 可 all-in |
| K 線結構 (型態學) | 高 | 可 all-in |
| 自己抓的 shakeout | 極高 | 可重壓 + 持續追 |

詳見 memory: [[feedback_confidence_based_sizing]]

## 2. Ch5-3 6 條件 (原始版、20 個 case backtest 100% 勝率)

```
1. 紅 K (close > open)
2. 跳空 < +4%
3. 收 ≥ 昨收
4. 收 ≥ 開 (雙錨守住)
5. 實體 > 上影
6. 量 ≥ 1.5x 5d avg
```

### Backtest 結果

| 規則 | 命中 | 平均報酬 (3 日) | 勝率 (>+3%) |
|---|---|---|---|
| 6/6 全中 | 8/20 | +11.1% | 100% |
| 5/6 (跳空大但其他中) | 2/20 | +14.8% | 100% |
| 4/6 (其他組合) | 4/20 | +10.4% | 100% |
| 紅K + 收≥昨 (2 條件) | 17/20 | +10.7% | 100% |

**結論**: 6 條件全中過嚴、會漏好 case；最簡 2 條件 (紅K + 收≥昨) 已有 100% 精度。

## 3. 量條件深度分析 (21 個 case 含失敗對照組)

### 不同量級的表現

| 量級 | 案例 | 隔日平均 | 隔日最大回測 | 殺破率 (<-3%) |
|---|---|---|---|---|
| 量爆 v20 ≥ 2.0x | 4 | **+5.8%** | +0.6% | **0%** ✅ |
| 量平 v20 1.0-1.5x | 5 | +3.1% | -0.9% | 0% ✅ |
| 量增 1.5-2.0x (邊緣) | 2 | **-5.2%** | -8.2% | **100%** 🚨 |
| 量縮 + 跳空 >3% | 3 | +1.6% | +0.5% | 33% ⚠️ |
| 量縮 + 沒跳空 | 3 | -1.6% | -3.7% | 33% ❌ |

### 三個出乎意料的發現

1. **量增 1.5-2.0x 邊緣量反而最危險 (100% 殺破)**
   - 案例: 2303 5/12 (-5.8%)、6207 5/26 (-4.6%)
   - 可能訊號: 「拉抬中段、主力試探出貨」
   - 樣本小、待驗證、但需警惕

2. **量爆 ≥ 2.0x 最穩 (0% 殺破、平均最大回測 +0.6%)**
   - 主力真正進場確認
   - 信心最高、可重壓

3. **量縮 + 跳空 >3% 是「強勢縮量續攻」型**
   - 跳空後試撮已消化、剩餘量小但延續
   - 案例: 3481 5/22 跳空 +6.4% + v5 0.5x → +17%
   - R/R 合理、但 33% 殺破風險

## 4. 整合 SOP — 量條件 + sizing + 停損

### 進場決策樹

```
【基本門檻】(必要):
  ✅ 紅 K (close > open)
  ✅ 收 ≥ 昨收
  → 無此兩條件、一律不進

【量條件 + sizing + 停損 對照】:

🟢 量爆 v20 ≥ 2.0x:
  Sizing: Stage 1 可進 1-2 張 (高信心)
  停損: -3%
  策略: 突破確認、可重壓

🟢 量平 v20 1.0-1.5x:
  Sizing: Stage 1 進 1 張 (中高信心)
  停損: -3%
  策略: 標準 Stage SOP

⚠️ 量增 1.5-2.0x 邊緣:
  Sizing: Stage 1 進 1 張、降至 50% (中信心)
  停損: -2% (緊)
  策略: 警惕「拉抬中段」、樣本小待驗證

🟡 量縮 + 跳空 >3% (試撮消化型):
  Sizing: Stage 1 降 sizing 50% (中信心)
  停損: -2.5%
  策略: 強勢續攻、但 33% 殺破風險、不重壓

🔴 量縮 + 沒跳空 (純弱訊號):
  Sizing: 不建議進、或 30%
  停損: -2%
  策略: 等量起來再說
```

## 5. 盤中時點分配 (4 小時逐步確認)

| 時點 | 可確認條件 |
|---|---|
| 9:00 開盤 | 跳空幅度 (條件 2) |
| 9:00-11:00 | 量比累積 (預判條件 6) |
| 11:00-12:00 | 量比中段確認、走勢方向 |
| 12:00-13:00 | 守昨收？(條件 3) |
| 13:00-13:20 | 守開盤?(條件 4) + 實體比例 (條件 5) |
| 13:20-13:25 | 試撮終結價 = 紅K確認 (條件 1) |

→ 13:20 試撮可預判 ≥ 4 條件、13:25 全確認

## 6. 對應工具建議

### A. live_position_monitor 即時 panel

```python
class IntradayStageScore:
    def evaluate(self, ticker, snap, db):
        prev_close = load_prev_close(db, ticker)
        v20_avg = load_v20_avg(db, ticker)
        
        red_k_pred = snap['close'] > snap['open']
        above_prev = snap['close'] >= prev_close
        gap = (snap['open'] - prev_close) / prev_close
        v20_ratio = snap['total_volume'] / v20_avg
        
        # 13:00 後判定可信
        # 13:25 試撮 = 最終判定
        
        if red_k_pred and above_prev:
            if v20_ratio >= 2.0:
                return ('🟢 量爆突破', 'all-in 可 1-2 張', '-3%')
            elif v20_ratio >= 1.5:
                return ('⚠️ 邊緣量', '降 sizing 50% + 停損 -2%', '-2%')
            elif v20_ratio >= 1.0:
                return ('🟢 量平延續', 'Stage 1 1 張', '-3%')
            elif gap > 3:
                return ('🟡 量縮跳空型', 'Stage 1 sizing 50%', '-2.5%')
            else:
                return ('🔴 量縮弱訊號', '不建議進', None)
        else:
            return ('❌ 基本門檻沒過', 'skip', None)
```

### B. daily_scanner_job 收盤後 Stage 2/3 trigger

```python
def check_stage2_trigger(ticker, db):
    """收盤後判定隔日是否符合 Stage 2 加碼."""
    bars = load_bars(db, ticker, n=5)
    today = bars[-1]
    prev_low = min(b['low'] for b in bars[-5:-1])  # 近 5 日前低
    
    return (
        today['low'] <= prev_low  # 跌破前波低
        and today['close'] > today['open']  # 紅 K 收回
        and today['close'] >= bars[-2]['close']  # 收高於前日
    )
```

## 7. 樣本限制 + 待驗證項

```
⚠️ 樣本限制:
  - 20 個 case (太小、selection bias 偏強勢日)
  - 4/15-6/2 = 大牛市階段
  - 震盪 / 熊市環境、量縮 + 紅K 可能更危險

⚠️ 待驗證:
  - 量增 1.5-2.0x 殺破率 100% 是否 robust (現只 2 case)
  - 量縮 + 跳空大 33% 殺破率是否在更大樣本穩定
  - 不同族群 (AI vs 傳產 vs 金融) 是否有差異

📊 累積更多樣本後優化:
  - 上線後每 50 個 trigger case 重新計算
  - 失敗 case 加標籤分析 (族群 / 大盤環境 / 量態類型)
  - 建立「失敗特徵庫」做反向過濾
```

## 8. 對 6/2 啟碁早盤 312 接的反省

```
6/2 早盤 6285:
  跳空 +0.3% (沒明顯跳空)
  v20 ratio: 估 ~0.8x (量比平均偏少)
  紅 K? 6/2 收盤 305 < 開 315 = 黑 K
  收 ≥ 昨? 6/2 收 305 < 6/1 收 314 = 沒守住
  
→ 基本門檻 (紅K + 收≥昨) 兩條件都沒過
→ 應該 skip、不該早盤接
→ 工具能自動阻止這次失誤
```

## 9. 相關 memory

- [[feedback_scaling_in_entry]] — Stage 1+1+1 SOP
- [[feedback_confidence_based_sizing]] — 黑盒 vs 白盒訊號分級
- [[feedback_structure_floor_entry_rr]] — 結構底回測 R/R
- [[feedback_chip_trend_not_aggregate]] — 三軸 (K 線 + MA + 籌碼) 必查
- [[feedback_check_market_regime_before_entry]] — 拉積盤檢查
- [[feedback_external_news_trade_category]] — 消息單獨立類別
- 5/19 當沖實戰 = Ch5-3 規則來源
- 5/1 (4/30) 復盤 = B5-1~B5-5 補強規則

## 10. 下次擴充計劃

1. **建 intraday_stage_confirm.py 模組** (3-4 小時)
2. **整合 live_position_monitor 顯示 panel**
3. **累積 50+ 真實 case 後驗證**
4. **加 daily_scanner_job 收盤後 Stage 2/3 trigger**
