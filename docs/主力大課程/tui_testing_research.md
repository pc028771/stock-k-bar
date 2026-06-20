# Textual TUI 測試方法研究 (2026-06-20)

研究對象：`scripts/zhuli/live_position_monitor_v2.py`（`class MonitorApp(App[None])`）。
實測環境：**Textual 8.2.7**（pyenv 3.12.12）。API 簽章皆本機 introspect / 實跑驗證。

## 0. TL;DR
- Textual **內建** headless harness `App.run_test()` + `Pilot`，**對本專案 demo 模式零改造可用**（POC 通過）。
- `demo_mode`（`MockClient` + `_build_scenarios()`，36 scenario）可原封餵進 `run_test()`，app 離線 instantiate 成功（held=7 / watch=133 / plan=3），不需真 broker。
- `pytest-textual-snapshot` 可裝，但本專案上色靠 **emoji 非 Rich style** + 畫面含時間/每日 watchlist → snapshot churn 嚴重，**只挑 ≤3 張穩定版面選擇性用**。
- 主力：**純函式 unit（formatter/sort/classify）+ Pilot 互動 assert app 狀態**，與現有 `mock/monitor_replay.py`（只測邏輯值）互補不重疊。

## 1. 內建測試 (run_test / Pilot) — 已驗證
`App.run_test(*, headless=True, size=(80,24), tooltips=False, notifications=False)` → async ctx 給 `Pilot`。
`Pilot`：`press` / `click` / `hover` / `pause(delay)` / `resize_terminal` / `wait_for_animation` / `exit`（全 async）。
**POC**：`run_test(size=(140,40))` 下 `press("1")`→held row=7 ✅、`press("t")`→teacher_only flip ✅、`press("4")`→active tab=tab-watching ✅。
**async 坑**：Textual 8.2.7 未註冊 pytest11 async runner、pytest-asyncio 也沒裝 → 用 **`asyncio.run(...)` 包一層**（零依賴、符合不裝套件原則）。

## 2. Snapshot — 不建議當主力
emoji 非 style + status bar 含 HH:MM:SS（非 deterministic）+ watch=133 每日變 + UI 高頻演進 → golden 天天爛。最多挑 PinDialog/空狀態/三段 header **結構性**畫面 ≤3 張，須先 freeze 時間 + 固定 inline scenario。**不進 pre-commit**。

## 3. 可測項（含校正）
🔴 **校正**：BINDINGS 裡 **1-7 是 tab 切換、不是排序**；排序是寫死的 `_watch_sort_key`（老師明示族群在前）、無使用者 sort 鍵。

- **純函式（最高 CP、不碰 TUI、約半數）**：`_fmt_vol`/`_fmt_price`/`_fmt_gap`/`_fmt_pnl`（燈號上色邊界 1.5/2.0/3.0）、`_watch_sort_key`、`_classify_watch`、`_get_status_icon`。
- **Pilot 互動**：tab 1-7（`TabbedContent.active`）、`t`/`f` toggle（reactive + row_count）、DetailPanel 內容（Trigger:/出貨:/均線:/警示:）、PinDialog modal、SearchBar `/`、demo `g`+數字。

## 4. 與 demo_mode 整合 — 能直接餵，兩個陷阱
建構：`MonitorApp(demo_mode=True, demo_client=v1.MockClient(), demo_scenarios=v1._build_scenarios())`（實測 run_test 通過）。
1. **monkey-patch 污染**：`_apply_demo_scenario`（line ~2318）直接 `_v1.check_trigger_inline = _mock_check` + patch `load_prev_close` → 測試間污染。**必用 fixture 存原值 + teardown 還原**。
2. **背景 thread + log 噪音**：demo 0.5s 一輪 daemon thread + `set_interval(1.0)`。測 deterministic 前 `app._demo_paused=True` 或直接呼 `_apply_demo_scenario()` 取值、`logging.disable(CRITICAL)` 消噪。

## 5. 落地建議（三層、CP 排序）
- **L1 純函式 unit ~50%**：pytest、不碰 Textual、churn≈零。
- **L2 Pilot 互動 ~45%**：run_test、assert app 狀態/row_count/reactive、churn 低。
- **L3 snapshot ≤3 張 ~5%**：churn 高、需自律、不進 pre-commit。
L1+L2 夠快可進 pre-commit（~0.1-0.3s/case）；async 用 `asyncio.run` 包。
**工作量 ~2-2.5 天**（L1 半天回報最高 / L2 1-1.5 天 / L3 半天）。維護成本 L1≈零 / L2 低 / L3 中高。

## 6. 反模式 + 坑
1. `press` 後不 `await pilot.pause()` 就 assert → `call_after_refresh` 未跑完抓舊值。
2. 背景 thread race（§4-2）。
3. 不給 `size=` → 預設 80×24、`_paginate(40)` 截 row → row_count 假變動。測 row 用大 size。
4. demo monkey-patch 全域污染（§4-1）。
5. snapshot 非 deterministic（時間 + watch 每日變）→ freeze 時間 + 固定 scenario。
6. emoji cell 寬度不定 → assert 用 `in` 子字串、別整 row 精確相等。
7. `logging.disable` 消 log 噪音。
8. 別用 snapshot 測「值」（燈號/數字歸 L1 純函式）。

## 7. 結論 + 下一步
**內建 `run_test()`+`Pilot` 零改造可用、demo_mode 直接當 fixture；主力「純函式 unit + Pilot 互動」兩層、snapshot 選擇性 ≤3 張。**
建議順序：(1) L1 純函式測（`_fmt_*` 邊界 + `_watch_sort_key` + `_classify_watch`、半天最高回報）；(2) 共用 `make_demo_app()` + teardown fixture；(3) L2 Pilot 測用 `asyncio.run` 包（先不裝套件）；(4) L1+L2 進 pre-commit；(5) 要 `@pytest.mark.asyncio` 乾淨寫法再評估裝單一 `pytest-asyncio`（需 user 同意）。

關鍵檔案：`live_position_monitor_v2.py`（MonitorApp / BINDINGS ~628 / formatter ~1341 / `_watch_sort_key` ~1712 / `_classify_watch` ~1444 / demo patch ~2318）、`live_position_monitor.py`（`MockClient` ~3216 / `_build_scenarios` ~3268）、`mock/monitor_replay.py`（既有邏輯測）。
