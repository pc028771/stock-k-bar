# `extras/` — 課程外條件隔離區

**本目錄所有檔案皆非課程內容。** 全部 default OFF，必須由 CLI `--extras` 明確啟用。

## 為什麼需要這個目錄

CLAUDE.md 規定：個股操作分析只能用課程教過的概念。但回測過程中我們會觀察到一些**非課程定義**的改進候選（例如 attack_intensity ≥ N 作硬過濾、持有天數上限）。

這些東西不該污染 `entry/`、`exit/`、`scoring/`（那些只放課程內容），但又值得實驗——所以放在這裡，做物理隔離。

## 命名規則

- 每個 extra 對外名稱以 `extras.` 為前綴（例：`extras.intensity_floor`、`extras.hold_days_cap`）
- backtest/scanner 輸出的 `exit_reason`、`extras_used` 欄位都會帶 `extras.` 前綴，audit 一眼可辨

## 三種類型

| 類型 | 註冊在 | 行為 |
|---|---|---|
| `ENTRY_FILTER_REGISTRY` | `extras/__init__.py` | bool mask，AND 套用到課程 entry signal 之上 |
| `EXIT_REGISTRY` | `extras/__init__.py` | 接到 `kline.exit.simulator` 的 priority 末端 |
| `SCORING_REGISTRY` | `extras/__init__.py` | scanner ranking 額外加分（不影響進出場） |

## CLI 使用

```bash
# 純課程 baseline
uv run python -m scripts.backtest --entry tweezer_top_breakout

# 加 extras（多個用逗號）
uv run python -m scripts.backtest --entry tweezer_top_breakout \
    --extras intensity_floor=2,hold_days_cap=20
```

`name[=arg]` 形式。arg 解析交給各 extra 自己。

## 輸出隔離

- 純課程：`backtest_<entry>.csv`
- 含 extras：`backtest_<entry>__<extras-slug>.csv`
- 每筆 trade 新增欄位 `extras_used`（逗號分隔）

→ 永遠可以拿純課程當 baseline 對照。

## 維護紀律

- 任何「我們自己定義」的條件**必須**放這裡，禁止偷渡進 `entry/`、`exit/`、`scoring/`
- 每個 extra 的 module docstring 要寫明：(a) 課程立場是什麼 (b) 我們為什麼覺得有用 (c) 觀察證據出處
- 若 audit 發現課程其實有教某個 extra，再把它「升格」搬到課程目錄
