# xiaoge extras — 課程外條件隔離區

> 規則來自 CLAUDE.md：課程內 vs 課程外邏輯**物理隔離**。本目錄只放「我們自己定義／backtest 校正／非權證小哥老師明說」的條件。

## 何時放進來

- backtest 校正出來的具體閾值（如「bandwidth 收斂改 ≤ 9」）
- 老師沒明說、但實務需要的條件（如結構停損 = 跌破突破當天 K 棒低點）
- 跨課程融合的規則（融合 K 線力量結構底等）

## 何時搬出去

- 經 audit 發現某 extra 其實有課程依據 → 升格搬到 `scripts/xiaoge/{entry,exit,scoring}/`
- 反之，原本當課程內的 condition 經 audit 發現是我們自己腦補 → 降格搬到此

## 啟用方式

- 預設 OFF
- backtest / scanner 加 `--extras <name1>,<name2>` 才會啟用
- 任何 extra 必須在 commit 訊息或變更紀錄裡有 backtest 證據

## 目前內容

（無）

待後續 Phase 加：
- `structural_stop_loss.py` — 推測停損（跌破突破當天 K 棒低點）
- `bandwidth_tuning_*.py` — backtest 校正出的 bandwidth 變體
