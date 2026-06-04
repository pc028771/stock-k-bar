# `scripts/zhuli/extras/` — 課程外條件隔離區（zhuli 篇）

**本目錄所有檔案皆非主力大課程內容。** 全部 default OFF、必須由 CLI `--extras` 明確啟用。

## 為什麼需要這個目錄

CLAUDE.md 規定：個股操作分析只能用課程教過的概念。但：

1. 回測過程中觀察到一些**非課程定義**的改進候選
2. **其他老師的方法論**（例如黃大 MACD DIF 多框架共振）user 想拿來當輔助、但不混入主力大 spec

這些東西不該污染 `zhuli/entry/`、`zhuli/exit/`、`zhuli/scoring/`、`zhuli/intraday_indicators/`（那些只放主力大課程內容），但又值得實驗 — 所以放在這裡、做物理隔離。

## 命名規則

- 每個 extra 以 `extras.` 為前綴（例：`extras.macd_diff_huangda`）
- 其他老師方法以「extras.{method}_{teacher_alias}」格式（例：`extras.macd_diff_huangda` = 黃大 MACD DIF）
- backtest / scanner / monitor 輸出的 `trigger`、`extras_used` 欄位都會帶 `extras.` 前綴、audit 一眼可辨

## 三種類型（與 kline/extras 一致）

| 類型 | 註冊在 | 行為 |
|---|---|---|
| `ENTRY_FILTER_REGISTRY` | `extras/__init__.py` | bool mask、AND 套用到課程 entry signal 之上 |
| `EXIT_REGISTRY` | `extras/__init__.py` | 接到 exit priority 的末端 |
| `SCORING_REGISTRY` | `extras/__init__.py` | scanner / monitor 排序額外加分（不影響進出場）|

## CLI 使用

```bash
# 純主力大課程 baseline
uv run python scripts/zhuli/live_position_monitor.py

# 加黃大 MACD DIF 共振
uv run python scripts/zhuli/live_position_monitor.py --extras macd_diff_huangda
```

## 紀律守護

- ✋ extras 條件**永不升格進主力大課程 spec**（即使 user 覺得有效）
- ✋ extras 訊號**永遠標 `extras.` 前綴**、不混進 Ch5 / Ch6 等課程 trigger
- ✋ 其他老師方法獨立檔頭、必須註明老師姓名與來源（如 `docs/huangda/`）
- ✋ default OFF、不加 `--extras` 開關 = 純課程 baseline

## 現有 extras

| 名稱 | 來源 | 用途 |
|---|---|---|
| `extras.macd_diff_huangda` | 黃大（`docs/huangda/`）| 60m + 30m + 5m MACD DIF 多框架共振、空方 entry filter + 強制回補 hint |
