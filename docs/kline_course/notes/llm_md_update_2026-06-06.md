# k-bar-power-llm.md 更新報告 — 2026-06-06

## 涵蓋範圍

涵蓋 49 個 commits（`4120767..HEAD`）— 自 2026-06-03 以來、之前 llm.md 全未同步。

## 更新的既有章節

| 章節 | 修改重點 |
|---|---|
| Header / Pipeline 總覽 | 加 27 patterns / 27 lights / 30 playbooks / formatter / CLI / manual_hints / Phase 4.3 |
| §2 目錄結構 | 加 `scripts/run_advisor.py`、`formatter.py`、`manual_hints.py`、`simulator.py`、`minute_bars.py`、`playbooks/(30)`、`lights/(27)` |
| §3.1 `load_bars` | 新增 `tickers=` param、共用 mtime cache (`/tmp/kline_bars_snapshot.sqlite`)、atomic `os.replace()` race-safe；CLI 30s → 5s warm |
| §3.2 `add_features` | 加 12 個新衍生欄位（含逐項課程出處）：`attack_cost`、`defensive_low`、`merged_high/low`、`ma*_kou`、`ma*_will_rise`、`at_pressure_retest`、`is_just_broke_high_intraday`、`low_price_flag`、`same_level_red_count_5d`、`taiex_down_today`、`is_after_negative_news_taiex` |
| §4 Patterns | 26 → 27；加 `attack_cost_displayed`（§20 state-machine）+ `self_rescue_breakout`（入門§34）|
| §6 Extras | 註記 `LOW_PRICE` 已搬回 `course_proxy_constants.py` |
| §15 DB 路徑 | 加 Phase 4.3 backtest DB、minute_bars、TAIEX history、limit-down history |
| §19 References | 加 phase4 v3/v4 report、branch_hit_rates.csv、入門 58 篇抓取報告、lights audit/fix batch、attack_cost state-machine、5 課程資料夾完備度表 |
| Footer | 更新到 2026-06-06、註明 49 commits 範圍 |

## 新增章節

| § | 標題 | 來源 commits |
|---|---|---|
| §7 | Scenario Advisor — Playbook Layer 主入口 | `08b445f`、`f1c452a` |
| §8 | Lights System — 27 個 lights（含 Phase 4.3 v4 完整 fire rate 表 + 4 個 `lt_*` advanced wiring）| `0db266d`、`c937c03`、`a7380cc` |
| §9 | Playbooks — 30 個應變劇本（含 Top 3 / 9 hit rate）+ action_type 色碼 | `a7380cc`（phase4_report）|
| §10 | Manual-judgment Hints — `defensive_stance` + `record_decline_rebound` | `3346bc5` + `f1c452a`（AND 修正）|
| §11 | Formatter + CLI（emoji + 距 MA% + 扣抵 + forward-fill UX）| `08b445f`、`296504d` |
| §12 | Phase 4.3 Backtest Infrastructure（simulator + v3/v4 統計 + 4 STUB fix + minute_bars）| `62f21dd`、`a7380cc`、`4c9ba79`、`245edbe`、`b87537e` |
| §13 | Scenarios — Internals（原 §7 拆過來、保留 DSL / Loader / Context / Persistence）| 既有 |

舊 §7 拆解：主入口部分挪到新 §7、其餘（YAML Loader / Condition DSL / Context Snapshot / Persistence）改編號為 §13.1–§13.4。原 §8–§13 依序 +6 → §14–§19。

## 數據來源

| 內容 | 來源檔案 |
|---|---|
| 27 light fire rates | `data/analysis/kline_patterns/phase4_report.md`（v4） |
| Top 3 / 9 high-hit branches | `data/analysis/kline_patterns/phase4_report.md` |
| v3 → v4 4 STUB fix 對比 | commit `a7380cc` body + `phase4_v3_report.md` |
| 12 個新 features 列表 | `scripts/kline/features.py`（grep `df["..."] =`）|
| 27 lights 名單 | `scripts/kline/scenarios/lights/*.yaml` (ls) |
| 30 playbooks 名單 | `scripts/kline/scenarios/playbooks/*.yaml` (ls) |
| Phase 4.3 統計（115,182 / 127,513 / 0 NULL / 97 min）| `phase4_report.md` Scope 區塊 |
| 5 課程篇數 | `ls docs/K線力量判斷入門/articles/`（58）+ 其他四夾 |
| `load_bars` 變動 | `scripts/kline/bars.py` head + commit `3b42e09` |
| Manual hints AND 修正 | `scripts/kline/scenarios/manual_hints.py` body |
| Forward-fill UX | `scripts/kline/scenarios/formatter.py` `_FORWARD_FILL_NOTES` |

## Anomaly / Unknown

1. **5 lights 無 phase4_report 數據** — `bottom_break_struggle` / `high_pushup_next_step` / `just_high_doji_attack` / `same_level_red_then_black` / `taiex_down_stock_new_high`：前兩個未列 v4 表（可能 fire 數 < 報告閾值），後三個是 commit `1a20d8e`（晚於 v4 報告）新增。已標註說明，未瞎填數字。
2. **v3 vs v4 `pressure_layer_no_support` 38.9% → 3.5%** — 是 fix 3 結果，非 bug；llm.md 註記了。
3. **Self-rescue / attack_cost playbook hit rate** — `attack_cost_displayed` 已列（B3 78.2%、B4 57.0%）；`self_rescue_breakout` playbook 太新、無 backtest 數據。

## 最終 llm.md 規模

- 行數：1,008（原 714、+294 行 / +41%）
- 一級章節：19（原 13、+6）
- 二級章節（含新 §7–§12 + 既有 §13 拆分）：增加 ~25 個子章節
