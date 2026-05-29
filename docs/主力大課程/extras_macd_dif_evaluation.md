# Chihming MACD DIF 外掛模組評估

> **目的：** 評估 MACD DIF 能否作為**外掛 (extras)**、改進主力大框架的勝率 / 出場機制
> **範圍：** 外掛 only、不取代主力大、預設 OFF
> **重要前提：** 主力大老師在 Ch1 明示「不使用 MACD/KD/RSI」、本評估是另一位 Chihming 老師教法的整合可行性
> **產出日期：** 2026-05-29 (Opus xhigh)

---

## 0. 重要前提

### 0.1 主力大老師「不看 MACD」原話

**來源 1：** `docs/主力大課程/course_map_from_scripts.md` L24 / L35
> 「進出場規劃會用**均線、量價、缺口**（最重要 3 個）+ **型態**（次要）。**不使用 MACD / KD / RSI（互相抵觸時無法決斷）**。」

**來源 2：** `docs/主力大課程/course_principles.md` L18, L249
> 「🔴 **不使用 MACD / KD / RSI**（互相抵觸無法決斷，違反**大道至簡**原則）。」

**反對理由摘要：**
1. 指標互衝、無法決斷
2. 違反「大道至簡」哲學
3. 勝率拆解：選股 50% / 進出場 30% / 運氣 20% — 進出場只是 30%、不需要靠指標精細化
4. 主力大已用「均線 + 量價 + 缺口」夠用

### 0.2 Chihming 老師教法定位

**核心：** 多時間框架 MACD DIF 共振 (週/日/60m/5m)、60m 為主信號

**時間框架：** **盤中即時** (60m DIF crossover 當下立刻執行)、非盤後

**選股池：** Q1 2026 集中在記憶體 / 權值股 (6770 力積電、2408 南亞科、2330 台積電、3481 群創)

**對話原話：**
- 「macd 的 dif」(被問主要看什麼指標，3/4)
- 「小時最重要」「小時翻正 我就 全補 賺賠都補」(4/1)
- 「等五分鐘」(4/1 開盤等待)
- 「周決定未來三到六個月」(3/31)
- 「看到 kd 高檔鈍化 就是噴；越長越要買」(2/25)
- 「強反彈 不是買跌深的 是買沒跌的」(3/11)

### 0.3 為何「外掛」而非「整合」

| 因素 | 說明 |
|---|---|
| 鐵則 | CLAUDE.md「禁止以常識或一般交易慣例補完課程沒有說的部分」 |
| 框架衝突 | Chihming = 盤中即時、主力大 = 收盤確認 |
| 選股池差 | Chihming 在權值大型股；主力大在中小型強勢族群 |
| 哲學衝突 | Chihming 用 4 個指標分層、主力大「大道至簡」 |
| **解法** | 寫成 extras + 預設 OFF + opt-in、保留實驗空間、不污染主線 |

---

## 1. MACD DIF 核心邏輯 (簡明)

| 元件 | 公式 | 用途 |
|---|---|---|
| DIF | EMA(close, 12) − EMA(close, 26) | 趨勢動能差 |
| DEA (signal) | EMA(DIF, 9) | 平滑線 |
| OSC (柱狀體) | DIF − DEA | 動能擴張/收斂 |
| 零軸 | DIF = 0 | DIF > 0 多方、< 0 空方 |
| 金叉/死叉 | DIF cross DEA | 短期動能轉折 |
| 背離 | price 新高 / DIF 不新高 | 警訊 |

**Chihming 多時間框架角色：**

| TF | 角色 | 用途 |
|---|---|---|
| 週 DIF | 大方向偏向 | 「決定未來 3-6 月」 |
| 日 DIF | 趨勢確認 | 不逆勢 |
| **60m DIF** | **主操作信號** | **進出場時機、強制執行** |
| 5m DIF | 加碼 / 沖差價節奏 | 局部 |

**KD 角色：** 早出場 trigger (KD≥80 + ΔK<0 = 71.2% 勝率)

---

## 2. Combo 機會 (4 個、表格化)

### Combo 1：小結構整理 + 日 DIF > 0 (進場過濾)

| 項目 | 內容 |
|---|---|
| 主力大 baseline | `scripts/zhuli/entry/small_structure.py` — N 字攻擊後高位整理末端、量縮、MA 追上 |
| MACD DIF 加成 | `(週 DIF > 0) AND (日 DIF > 0) AND (日 ΔDIF > 0)` |
| 加成 logic | 過濾掉「整理但大趨勢空方」的假突破；對應 Chihming 假說 1 |
| Backtest evidence | Chihming Q1 2026 (251 筆、100 大)：多單 baseline 勝率 48.1%、E[R] +3.33%；2408 1 月底案例 (日 DIF 正但 ΔDIF 負) -29.49% 多單，假說 1 預期可過濾 |
| 預期 lift | E[R] 從 +3.33% 預期提升 (待自家回測量化) |
| Risk | shakeout_strong (底部突破) 不適用 — 此時日 DIF 多半仍負；不可全 entry scanner 套用 |
| 評等 | 🟡 **試** (限 small_structure / w_bottom_launch 高位整理型 scanner) |

### Combo 2：「沿均線操作」+ 週 DIF 方向 (持倉健康度)

| 項目 | 內容 |
|---|---|
| 主力大 baseline | 老師 5/28 L304-308「你就沿著這個均線就好了」(`2026-05-28_觀盤重點與課後檢討.md` L103) |
| MACD DIF 加成 | 週 DIF 方向向上 = 月以上方向健康 |
| 加成 logic | 過濾掉「日線健康但週線轉空」的標的 (避免追在大級別頭部) |
| Backtest evidence | Chihming 3/31 原話「周決定未來三到六個月」；2408 1/30 多單週 DIF 已轉弱、3/9 衝突出場 -29% |
| 預期 lift | 持倉健康度量化、可作 daily SOP 警示 |
| Risk | 週 DIF 反應慢 (約 1-2 週滯後)、可能錯過趨勢初期；台股小型股週 DIF 波動大 |
| 評等 | 🟡 **試** (僅作 sanity warning、不否決進場) |

### Combo 3：「先停利」改進 + KD≥80 出場 (出場 timing)

| 項目 | 內容 |
|---|---|
| 主力大 baseline | 老師 5/23-5/28 連 6 天「先停利」鐵則：紅 K 丟 / 衝高拉回鎖利 (`feedback_teacher_signal_continuity.md`) |
| MACD DIF 加成 | KD_K ≥ 80 且 ΔK < 0 (寬鬆版：前日 KD≥80 + 今日 ΔK<-5) |
| 加成 logic | 提供量化出場時點 (替代「紅 K 一兩根」主觀判斷) |
| Backtest evidence | Chihming Q1 2026：**`kd_overbought` 出場 80 筆、71.2% 勝率、E[R] +9.40%** (最強 alpha 來源)；6770 2/2→3/2 +15.45% 完美捕捉；群創 3/12 KD=82.6 峰值與用戶實際出場吻合 |
| 預期 lift | 71.2% 勝率 vs 衝突出場 27.3% (E[R] 差距 +13.7%)；最強候選 |
| Risk | (1) 主力大「指標未翻轉一路抱」哲學衝突；(2) 趨勢盤 KD 高檔鈍化可能 false trigger (老師 2/25「越長越要買」反義訊號)；(3) 樣本期 Q1 2026 為空頭環境、可能 over-fit |
| 評等 | 🟡 **試** (作為「先停利」的客觀補槍、不取代主力大結構出場) |

### Combo 4：當沖 / 沖差價 + 60m DIF 翻正 (強制回補)

| 項目 | 內容 |
|---|---|
| 主力大 baseline | Ch5 當沖：尾盤動作 / 雙錨停損 / 9:10 後切入 |
| MACD DIF 加成 | 60m DIF 由負轉正 = 無條件全補 (Chihming「小時翻正 我就 全補 賺賠都補」) |
| 加成 logic | 為「拉高出貨 / 9:20 高峰」鐵則 (`feedback_dump_signal_is_market_level.md`) 提供量化的「強制回補」trigger |
| Backtest evidence | 6770 盤中回測：3 筆 / 勝率 66.7% / 累計 +42.81% / 最大回落 -0.18% (極小)；2330 對齊率 100% |
| 預期 lift | 對當沖出場 timing 量化、減少「該補沒補」的猶豫 |
| Risk | (1) 需 Sponsor tier FinMind (60m K 線、有 API cost)；(2) Chihming 樣本只有 4 檔股票、樣本太集中；(3) 主力大選股池 (中小型) 上 60m DIF 可能太雜訊 |
| 評等 | 🔴 **拒** (除非取得 Sponsor + 自家回測證明在主力大選股池有效) |

---

## 3. 外掛模組設計 (見 README 詳細 spec)

`scripts/kline/extras/extras_macd_dif/` 規劃：

```
extras_macd_dif/
├── README.md                          ← 已產出 (本任務)
├── extras.macd_dif_trend_filter.py    ← 待實作 (Combo 1)
├── extras.macd_dif_exit_signal.py     ← 待實作 (Combo 3)
└── extras.macd_dif_confirmation.py    ← 待實作 (Combo 2 + sanity check)
```

| 模組 | Input | Output | Trigger | 預期 lift |
|---|---|---|---|---|
| trend_filter | scanner 候選 DF | bool mask | 盤前 | 過濾日 DIF 負的多單 |
| exit_signal | core 持倉 + KD | (sym, "extras.macd_dif.kd_overbought") | 收盤後 / 13:00 後 | 71.2% 勝率出場 trigger |
| confirmation | sym + intent | warnings[] | 推薦個股 / 出清前 | 警示與 Chihming 框架衝突的標的 |

---

## 4. 風險評估

### 4.1 結構性風險

| Risk | 描述 | 嚴重度 |
|---|---|---|
| 哲學衝突 | 主力大「大道至簡」vs Chihming「4 框架共振」、易增決策複雜度 | 🔴 高 |
| Over-fit | Chihming 回測樣本 = 4 檔權值股 × 2 個月空頭、樣本期偏窄 | 🔴 高 |
| 選股池不匹配 | Chihming 在 6770/2408 有效、主力大 typically 在中小型強勢族群 | 🟡 中 |
| 規則漂移 | 引入 MACD 後可能無感「越用越多」、最後實質取代主力大 | 🔴 高 |
| 資料成本 | 60m DIF 需 Sponsor tier FinMind | 🟡 中 |

### 4.2 Mitigation

1. **嚴格 extras + 預設 OFF + opt-in** (CLI `--extras` 明示)
2. **個股推薦標註** `[extras.macd_dif ON]`、不混入主力大推薦
3. **定期 audit** (每月) — 若 extras 持續無 lift 或引發決策混亂、立即下架
4. **回測必比較純 baseline** — 任何 extras 版本都要對比純主力大版本

### 4.3 不可踩的紅線

- ✋ 不可寫進 `course_map_from_scripts.md` 或 `strategy-indicators.md`
- ✋ 不可修改 `scripts/kline/{entry,exit,scoring}/` 或 `scripts/zhuli/{entry,exit}/`
- ✋ 不可在主力大 daily SOP 變成「必跑」
- ✋ 不可把 KD/MACD 寫進 memory 的「必跑 checklist」

---

## 5. 推薦 trial 方案

### 5.1 優先順序

**第 1 個 prototype：Combo 3 (`extras.macd_dif_exit_signal`)**
- 理由：(a) 證據最強 (71.2% 勝率、80 筆樣本)；(b) 與主力大「先停利」精神方向一致 (差異是量化 vs 主觀)；(c) 出場場景比進場 safer (錯了少賺、不會錯虧)

### 5.2 第 2 個 prototype：Combo 1 (`extras.macd_dif_trend_filter`)
- 限 small_structure / w_bottom_launch 高位整理型 scanner、不全 entry scanner 套

### 5.3 第 3 個 (僅實驗、不上線)：Combo 2 (`extras.macd_dif_confirmation`)
- 純警示、不阻擋

### 5.4 暫不做：Combo 4 (60m DIF)
- 等 Sponsor tier + 主力大選股池自家回測證據

### 5.5 怎麼 measure 勝率提升

**回測 harness：**
```bash
# Baseline (純主力大)
uv run python -m scripts.backtest --entry small_structure --period 2y
  → backtest_small_structure.csv

# +extras.macd_dif_exit_signal
uv run python -m scripts.backtest --entry small_structure --period 2y \
    --extras macd_dif_exit_signal
  → backtest_small_structure__macd_dif_exit_signal.csv

# 比較指標：勝率、E[R]、平均持倉天數、出場原因分布
```

**驗證標準 (3 個月 trial)：**
- 勝率提升 ≥ +5%
- E[R] 提升 ≥ +2%
- 無「KD 鈍化出場但隔日續飆」案例 > 20% (避免老師 2/25「越長越要買」陷阱)

### 5.6 Opt-in 機制

- CLI `--extras macd_dif_exit_signal` (現有 extras 框架已支援)
- 個股報告 footer：`Extras used: extras.macd_dif_exit_signal`
- daily SOP 不自動跑、需 user 明示「跑 extras 版」

---

## 6. 結論

### 整體推薦：🟡 **試** (限 Combo 3 為第一優先)

| 維度 | 評估 |
|---|---|
| 證據強度 | Chimming Q1 2026 KD 出場 71.2% 勝率、E[R] +9.40% (80 筆樣本、最強 alpha) |
| 與主力大相容性 | Combo 3 與「先停利」精神相容、Combo 1/2 部分相容、Combo 4 不相容 |
| 實作成本 | 中 (3 個模組 + 回測 harness、~2-3 day 工作量) |
| 紀律風險 | 高 — 需嚴格 extras 隔離、避免漂移取代主力大 |
| 預期 lift | 出場勝率 +5~10% (若 Chimming 數字在主力大選股池複現)、E[R] +2~5% |

### 預期 lift / risk trade-off

**Best case (Combo 3 在主力大選股池可複現)：**
- 「先停利」這條鐵則從主觀「紅 K 一兩根」量化為 KD≥80 + ΔK<0
- E[R] +2-5%、勝率 +5%
- 避免「該停沒停」的猶豫 (5/23-5/28 連 6 天教學的執行端強化)

**Worst case (Q1 2026 是 over-fit)：**
- KD 出場在趨勢盤 false trigger、踩老師 2/25「越長越要買」陷阱
- 違反主力大「指標未翻轉一路抱」哲學
- **Mitigation：3 個月 trial、表現不佳立即下架**

### Decision Point (需 user 確認)

1. **是否先 prototype Combo 3 `extras.macd_dif_exit_signal`？** (建議先試)
2. **是否同意 Sponsor tier 暫不投資、Combo 4 跳過？**
3. **是否同意 3 個月 trial、不通過驗證標準即下架？**
4. **是否需 Combo 2 confirmation 作 sanity check (即使 lift 不明顯)？**

---

## 附錄：證據來源

- `stock-analysis-system/notes/macd_dif_strategy_research_2026Q1.md` (Chihming 回測主檔)
- `stock-analysis-system/notes/intraday_strategy.md` (盤中 SOP)
- `stock-analysis-system/notes/intraday_rules_for_ai.md` (規則化)
- `stock-analysis-system/notes/trading_signals.md` (訊號日誌 + Q1 老師對話)
- `stock-analysis-system/backtest_report_6770.md` (6770 盤中回測)
- `stock-analysis-system/docs/stock-analysis-system-spec.md` L87-265 (MACD/short_sell spec)
- `docs/主力大課程/course_map_from_scripts.md` L24, L35 (主力大反 MACD)
- `docs/主力大課程/course_principles.md` L18, L249 (大道至簡)
- `docs/主力大課程/全方位培訓筆記/2026-05-28_觀盤重點與課後檢討.md` L103, L155 (沿均線)
- memory `feedback_teacher_signal_continuity.md` (5/23-5/28 先停利 6 天)
- memory `feedback_dump_signal_is_market_level.md` (拉高出貨 9:20 高峰)
