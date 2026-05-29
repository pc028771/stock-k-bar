# `extras_macd_dif/` — Chihming 老師 MACD DIF 外掛模組

> **這是課程外條件 (extras-only)。** 主力大老師在 Ch1 明示「不使用 MACD/KD/RSI」(`course_principles.md` L18, L249；`course_map_from_scripts.md` L24, L35)。
> 本模組是**另一位 Chihming 老師**教法的整合候選，**預設 OFF**、僅供 opt-in 實驗、不取代主力大框架。

---

## 0. 課程立場 (必讀)

**主力大老師原話：**
> 「不使用 MACD / KD / RSI（互相抵觸時無法決斷）」(Ch1)
> 理由：違反「大道至簡」、指標互衝無法決斷。主力大主操作邏輯只用「均線 / 量價 / 缺口 + 型態」。

**Chihming 老師原話 (Messenger 2026 Q1)：**
- 「macd 的 dif」(被問主要看什麼指標 / 3-4)
- 「小時最重要」「小時翻正 我就 全補 賺賠都補」(4-1)
- 「等五分鐘」(4-1 開盤)
- 「周決定未來三到六個月」(3-31)
- 「強反彈 不是買跌深的 是買沒跌的」(3-11)
- 「看到 kd 高檔鈍化 就是噴；越長越要買」(2-25)

**Chihming 框架核心：** 多時間框架 MACD DIF 共振 (週/日/60m/5m)，60m 為主信號、強制執行；KD 高檔鈍化為早出場 trigger (回測 71.2% 勝率)。

**為何隔離不整合：**
1. 主力大明示反對、整合會違反 CLAUDE.md「不准踩課程外條件」紅線
2. Chihming 框架是「盤中即時」(60m DIF crossover 即時執行)，與主力大「收盤確認」基礎邏輯衝突
3. 兩位老師選股池不同 (Chihming = 記憶體權值股 6770/2408/2330/3481、主力大 = 中小型強勢族群)
4. **作 extras 可以實驗、不污染主線、隨時可關**

---

## 1. 三個外掛模組 spec

### 1.1 `extras.macd_dif_trend_filter` (進場 filter)

**功能：** 對主力大 entry scanner (small_structure / w_bottom_launch / shakeout_strong / pennant_flag) 結果加 MACD 趨勢過濾。

**Logic：**
```
pass = (週 DIF > 0) AND (日 DIF > 0) AND (日 ΔDIF > 0)
     # 等同 Chihming「假說 1」(macd_dif_strategy_research_2026Q1.md §5)
```

**Input：** scanner candidate DataFrame (含 ticker, signal_date, close)
**Output：** bool mask (drop 假設「整理但大趨勢空方」的假突破)
**Trigger：** 盤前 / scanner 完成後一次 batch 計算
**預期 lift：** 從 Chihming 回測 — 加 `ΔDIF > 0` 預期可過濾掉 2408 1 月底案例（-29% 多單）；多單 baseline 勝率 48.1%、E[R] +3.33%，加 filter 預期 E[R] 進一步提升 (待自家回測)
**Risk：** 可能漏掉主力大「底部窒息突破」(此時日 DIF 多半仍負)；shakeout_strong 不適用此 filter

**主力大老師立場：** 強烈反對 (Ch1 鐵則)。本 filter 與「大道至簡」原則衝突。

---

### 1.2 `extras.macd_dif_exit_signal` (出場 trigger)

**功能：** 對主力大持倉提供 KD 高檔鈍化出場警示，可補強主力大「先停利」框架的量化點。

**Logic：**
```
exit_signal = (KD_K ≥ 80) AND (ΔK_K < 0)
            # 或寬鬆版: (昨日 KD_K ≥ 80) AND (今日 ΔK < -5)
            # 等同 Chihming「假說 2」+ 老師 2/25「kd 高檔鈍化就是噴」
```

**Input：** core 持倉清單 + 每檔當前 KD K 值與一日變化
**Output：** `(symbol, exit_reason="extras.macd_dif.kd_overbought", urgency)` 列表
**Trigger：** 盤後一次 + 盤中 13:00 後手動跑一次 (對應「13:00 後評估」鐵則)
**預期 lift：**
- Chihming Q1 2026 回測 (100 大、251 筆)：`kd_overbought` 出場 80 筆、**71.2% 勝率、E[R] +9.40%** (`macd_dif_strategy_research_2026Q1.md` §4.3)
- 力積電 2-2 → 3-2 案例 +15.45% 完美捕捉峰值；群創 3-12 KD 峰值 82.6 與用戶實際出場吻合
- 可量化「紅 K 一兩根」這種主觀判斷，提供「客觀補槍」

**Risk：**
1. 主力大「先停利」5/23-5/28 連 6 天明示是基於「結構/紅 K/沿均線」、非 KD；KD 出場可能與主力大「指標未翻轉一路抱」邏輯衝突 (`feedback_teacher_signal_continuity.md`)
2. 趨勢盤中 KD 可能「高檔鈍化但不轉折」(老師 2/25 原話「越長越要買」)，KD<80 出場規則會踩雷
3. 2026 Q1 是空頭環境、樣本可能偏 over-fit

**主力大老師立場：** 反對 (用 KD = 「指標互衝」)；但「先停利」5/23 教學在精神上與 KD 高檔轉折不衝突。

---

### 1.3 `extras.macd_dif_confirmation` (進/出場 sanity check)

**功能：** 進場/出場前的「另一框架觀點」交叉驗證 (sanity check only、不否決主力大訊號)。

**Logic：**
```
進場 check：
  warn_if (日 DIF < 0) → "Chihming 框架不建議多 (大趨勢負)"
  warn_if (週 DIF < 0) → "Chihming: 週負 = 未來 3-6 月偏空"
出場 check：
  warn_if (60m DIF 由正轉負) → "Chihming: 60m 翻負是主出場"
  warn_if (週 DIF 與日 DIF 反向) → "Chihming: 衝突出場 (E[R] -4.32% 警示)"
```

**Input：** symbol + intent (entry/exit)
**Output：** `(symbol, warnings[])` — **不阻擋執行**、只列警示
**Trigger：** 推薦個股 / 出清前 SOP checklist
**預期 lift：** 防止「主力大訊號好但 Chihming 框架明顯背離」的高風險進場；類似「broker tier 1 override」的反向 sanity check
**Risk：** 警示太多可能成為 noise → 預設只在「兩位老師明顯衝突」時 fire (週 DIF 反向 / 60m DIF 反向)

**主力大老師立場：** Sanity check 形式不違反原則；但需嚴格控制不變成「決策依賴」。

---

## 2. CLI 使用

```bash
# 純主力大 baseline (預設)
uv run python -m scripts.backtest --entry small_structure

# 加單一 extra
uv run python -m scripts.backtest --entry small_structure \
    --extras macd_dif_trend_filter

# 加多個 extras
uv run python -m scripts.backtest --entry small_structure \
    --extras macd_dif_trend_filter,macd_dif_exit_signal
```

輸出檔名自動帶 `__macd_dif_xxx` 後綴 (依 extras/README.md 既有規約)。

---

## 3. 命名前綴

依 CLAUDE.md「課程外條件隔離規則」：
- 目錄：`scripts/kline/extras/extras_macd_dif/`
- 模組對外名稱：`extras.macd_dif_trend_filter` / `extras.macd_dif_exit_signal` / `extras.macd_dif_confirmation`
- `exit_reason` / `extras_used` 輸出欄位帶 `extras.macd_dif.*` 前綴、audit 一眼可辨

---

## 4. 重要限制 (請勿違反)

- ✋ **預設 OFF**、必須 `--extras` 明確啟用
- ✋ **不寫進** `course_map_from_scripts.md` 或 `strategy-indicators.md` (那是主力大 spec)
- ✋ **不修改** `scripts/kline/{entry,exit,scoring}/`、`scripts/zhuli/{entry,exit}/`
- ✋ **個股推薦時若啟用、必須在報告標註** `[extras.macd_dif ON]`、避免使用者誤以為是主力大推薦
- ✋ **回測必須與純 baseline 比較**、不可只看 extras 版本
- ✋ **若 audit 發現此 extra 持續無 lift / 引發決策混亂，立即下架**

---

## 5. 待實作清單 (TODO)

- [ ] `extras.macd_dif_trend_filter.py` — 需先實作週/日 DIF 計算 (參考 `stock-analysis-system/backtesting/macd_dif_backtest.py` `calc_dif()`)
- [ ] `extras.macd_dif_exit_signal.py` — 需 KD(9,3,3) 計算 (台股標準參數)
- [ ] `extras.macd_dif_confirmation.py` — 需 60m K 線資料 (Sponsor tier FinMind 才有)
- [ ] `__init__.py` — 註冊到 `ENTRY_FILTER_REGISTRY` / `EXIT_REGISTRY` / `SCORING_REGISTRY`
- [ ] 回測 harness — 比較「純主力大 vs +trend_filter vs +exit_signal」三組

---

## 6. 觀察證據出處

- Chihming 回測：`stock-analysis-system/notes/macd_dif_strategy_research_2026Q1.md`
- Chihming 盤中 SOP：`stock-analysis-system/notes/intraday_strategy.md` + `intraday_rules_for_ai.md`
- Chihming 訊號日誌：`stock-analysis-system/notes/trading_signals.md`
- 6770 盤中回測：`stock-analysis-system/backtest_report_6770.md` (3 筆 / 勝率 66.7% / 累計 +42.81%)
- 主力大反對立場：`docs/主力大課程/course_map_from_scripts.md` L24, L35；`course_principles.md` L18, L249
- 主力大「先停利」連續 6 天：memory `feedback_teacher_signal_continuity.md` (5/23-5/28)
