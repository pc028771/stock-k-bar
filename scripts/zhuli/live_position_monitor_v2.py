"""即時持倉 + Screener 監控 — Textual TUI v2.

Textual 版、平行於 v1 (Rich-only)、解決 UX 痛點:
- WATCH 太長看不到 footer → 分 5 個 Tab、各自獨立捲動
- 無法搜尋 → / 快速搜尋 + highlight
- Pin 標的不便 → a/u 鍵 InputDialog
- Section 視覺混淆 → CSS border + 顏色
- 鍵盤反應慢 → Textual binding < 10ms

架構:
  Tab: 持倉(HELD) / 可進場(Confirmed) / 觀察(Watching) / Pinned / 🌅隔日沖 / Scanner(全顯)
  Header: 固定頂部 (大盤狀態 + 時間)
  Footer: 固定底部 (永遠看得到)
  DataTable: 每個 Tab 一個 DataTable

Demo 模式:
  --demo  → 使用 v1 的 mock client + 36 scenarios、不需真實券商
  1-9     → 直接跳到 scenario N
  g + NN  → 跳 scenario 10-36 (e.g. g13)
  space   → 切 auto-cycle
  ← →     → 上/下一個

啟動:
  pip install textual
  python3 scripts/zhuli/live_position_monitor_v2.py --demo
  python3 scripts/zhuli/live_position_monitor_v2.py         # 真實模式
"""
from __future__ import annotations

import argparse
import math
import sqlite3
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# ── path setup (同 v1) ──────────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent.parent
_SYS  = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_REPO), str(_REPO / "scripts"), str(_SYS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── textual imports ─────────────────────────────────────────────────────────
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.reactive import reactive
from textual.widgets import (
    DataTable, Footer, Header, Input, Label,
    Static, Tab, TabbedContent, TabPane,
)
from textual.screen import ModalScreen

# ── import v1 data layer ────────────────────────────────────────────────────
# 重用 v1 的資料清單、helpers，不重寫 data layer
try:
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location(
        "live_position_monitor_v1",
        Path(__file__).parent / "live_position_monitor.py",
    )
    assert _spec and _spec.loader
    _v1 = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_v1)  # type: ignore[union-attr]
except Exception as _e:
    raise ImportError(f"無法 import live_position_monitor v1: {_e}") from _e

# v1 exports 快取
HELD        = _v1.HELD
WATCH       = _v1.WATCH
PLAN_PRIMARY= _v1.PLAN_PRIMARY

# helpers
compute_vol_ratio    = _v1.compute_vol_ratio
fmt_vol_ratio        = _v1.fmt_vol_ratio
mk_chip_signal_text  = _v1.mk_chip_signal_text
mk_sizing_suggestion = _v1.mk_sizing_suggestion
DataCache            = _v1.DataCache
check_trigger_inline = _v1.check_trigger_inline
_normalize_held      = _v1._normalize_held
_normalize_watch     = _v1._normalize_watch
_normalize_plan      = _v1._normalize_plan
_classify_watch_source = getattr(_v1, '_classify_watch_source', None)
_classify_watch_item   = getattr(_v1, '_classify_watch_item',   None)
load_ma10            = _v1.load_ma10
load_5d_avg_volume   = _v1.load_5d_avg_volume
load_prev_close      = _v1.load_prev_close
TRIGGER_DISPLAY      = _v1.TRIGGER_DISPLAY
TRIGGER_RANK         = _v1.TRIGGER_RANK
_get_market_regime_chip = _v1._get_market_regime_chip
_get_session_chip    = _v1._get_session_chip
_merge_scanner_watchlist = _v1._merge_scanner_watchlist

# Demo / mock
MockClient           = _v1.MockClient
_build_scenarios     = _v1._build_scenarios
_mk_snap             = _v1._mk_snap
PREV_CLOSES          = getattr(_v1, 'PREV', {})
record_trigger_fire  = _v1.record_trigger_fire

import logging as _logging
_logging.getLogger('zhuli.intraday_stage_helper').setLevel(_logging.ERROR)
_logging.getLogger('intraday_stage_helper').setLevel(_logging.ERROR)
_logging.getLogger('clients.fubon_client').setLevel(_logging.ERROR)

# ── dump signals (持倉拉高出貨即時警示) ────────────────────────────────────
from scripts.zhuli.dump_signals import (
    DumpStateTracker,
    evaluate_dump_signals,
    load_baseline,
)

_BASELINE_PATH = _REPO / "docs" / "主力大課程" / "baseline_snapshot.json"

# ── CSS ─────────────────────────────────────────────────────────────────────
CSS = """
Screen {
    background: #0a0a0a;
}

#main-tabs {
    height: 1fr;
}

TabbedContent {
    height: 1fr;
}

TabPane {
    padding: 0 1;
}

DataTable {
    height: 1fr;
    scrollbar-size: 0 0;
}

#detail-panel {
    height: 6;
    background: #14141e;
    color: #d0d0d8;
    border: solid #2a2a3a;
    padding: 0 1;
}

/* Bug 2 fix: 統一 focused/unfocused header + cursor 顏色，避免首次 click 後突兀 */
DataTable > .datatable--header {
    background: #1a1a1a;
    color: cyan;
    text-style: bold;
}

DataTable:focus > .datatable--header {
    background: #1a1a1a;
    color: cyan;
    text-style: bold;
}

DataTable > .datatable--cursor {
    background: #002030;
    color: white;
}

DataTable:focus > .datatable--cursor {
    background: #003050;
    color: white;
}

.held-pane DataTable {
    border: solid green;
}

.confirmed-pane DataTable {
    border: heavy green;
    background: rgb(0, 30, 0);
}

.watching-pane DataTable {
    border: solid yellow;
}

.pinned-pane DataTable {
    border: solid magenta;
}

.overnight-pane DataTable {
    border: solid magenta;
    background: rgb(20, 0, 20);
}

.scanner-pane DataTable {
    border: solid cyan;
}

#search-bar {
    height: 3;
    dock: bottom;
    display: none;
    border: solid yellow;
    padding: 0 1;
    background: #1a1a00;
}

#search-bar.visible {
    display: block;
}

#status-bar {
    height: 1;
    dock: top;
    background: #111;
    color: #aaa;
    padding: 0 1;
}

#pin-dialog {
    align: center middle;
    background: rgba(0,0,0,0.8);
}

.dialog-container {
    background: #1a1a1a;
    border: solid yellow;
    padding: 1 2;
    width: 50;
    height: 10;
}

.dialog-container Label {
    margin-bottom: 1;
}
"""


# ── Tab IDs ─────────────────────────────────────────────────────────────────
TAB_HELD      = "tab-held"
TAB_CONFIRMED = "tab-confirmed"
TAB_WATCHING  = "tab-watching"
TAB_PINNED    = "tab-pinned"
TAB_OVERNIGHT = "tab-overnight"
TAB_SCANNER   = "tab-scanner"

TAB_LABELS = {
    TAB_HELD:      "📊 持倉",
    TAB_OVERNIGHT: "🌅 隔日沖",
    TAB_CONFIRMED: "🎯 可進場",
    TAB_WATCHING:  "🔍 觀察",
    TAB_PINNED:    "📌 Pinned",
    TAB_SCANNER:   "📈 Scanner",
}

# Tab order: 1=持倉 2=隔日沖 3=可進場 4=觀察 5=Pinned 6=Scanner
_TAB_ORDER = [TAB_HELD, TAB_OVERNIGHT, TAB_CONFIRMED, TAB_WATCHING, TAB_PINNED, TAB_SCANNER]

# ── Column specs ─────────────────────────────────────────────────────────────
# (key, label, width)
COLS_HELD = [
    ("ticker",  "代號",    6),
    ("name",    "股名",    8),
    ("cost",    "均",      7),
    ("gap",     "跳空",    7),
    ("price",   "現價%",   16),
    ("vol_ratio",   "量比",    9),
    ("pnl",     "P&L",    14),
    ("dist_stop","距停",    8),
    ("status",  "狀",      4),
    ("trigger", "Trigger", 40),
]

COLS_WATCH = [
    ("ticker",   "代號",    6),
    ("stars",    "⭐",      4),
    ("name",     "股名",    8),
    ("tactic",   "策略",    6),
    ("gap",      "跳空",    7),
    ("price",    "現價(%)", 16),
    ("vol_ratio",  "量比",   9),
    ("dist_ma10",  "距MA10", 8),
    ("sector",   "族群",   14),
    ("source",   "來源",   12),
    ("trigger",  "Trigger",35),
]

COLS_OVERNIGHT = [
    ("ticker",  "代號",  6),
    ("name",    "股名",  8),
    ("price",   "現價", 10),
    ("bb",      "布林",  5),   # ✅ / ❌
    ("kbar",    "K棒",   5),   # ✅ / ❌
    ("slope",   "斜率",  5),   # ✅ / ❌
    ("market",  "大盤",  5),   # ✅ / ❌
    ("pass",    "通過",  6),   # "3/4" / "4/4"
    ("asof",    "資料時間", 10),  # Fubon snap timestamp HH:MM:SS
    ("status",  "狀態", 22),   # "等斜率" / "✅ 可進場" etc.
]

# ── overnight universe loader (保留備用) ─────────────────────────────────────
def _load_overnight_universe_unused() -> list[str]:
    """讀取老師 332 檔 universe (sector_tickers + picks_2026 dedup union)。
    注意: 已改用 _load_overnight_candidates()，此函式保留供未來參考。
    """
    tickers: set[str] = set()
    base = _REPO / "docs" / "主力大課程"
    try:
        import json
        with open(base / "teacher_sector_tickers.json", encoding="utf-8") as fh:
            s1 = json.load(fh)
        for v in s1.values():
            if isinstance(v, list):
                tickers.update(str(t) for t in v)
    except Exception:
        pass
    try:
        import json
        with open(base / "teacher_picks_2026.json", encoding="utf-8") as fh:
            s2 = json.load(fh)
        for k in s2:
            if k.isdigit() and len(k) == 4:
                tickers.add(k)
    except Exception:
        pass
    return sorted(tickers)


# ── overnight universe + static features ─────────────────────────────────────
# 新架構: 不再讀 candidates CSV、而是 332 檔 universe live eval (Fubon snap + static cache)
# static cache 由 scripts/zhuli/precompute_overnight_static.py 每天 08:30 / 12:30 預算
_OVERNIGHT_STATIC_JSON  = _REPO / "data" / "analysis" / "zhuli" / "overnight_static_features.json"

# 舊 CSV 路徑保留為 fallback / 歷史檔（不再讀進 monitor）
_OVERNIGHT_CSV          = _REPO / "data" / "analysis" / "zhuli" / "overnight_swing_scanner.csv"


def _load_overnight_static() -> dict:
    """讀 precomputed static features JSON、回傳 dict.

    Returns: dict (含 _meta / _market / {ticker: features...})
             若 JSON 不存在或無法 parse、回傳 {}.
    """
    try:
        import json as _json
        if not _OVERNIGHT_STATIC_JSON.exists():
            return {}
        with open(_OVERNIGHT_STATIC_JSON, encoding="utf-8") as fh:
            return _json.load(fh)
    except Exception:
        return {}


def _load_overnight_universe() -> list[str]:
    """讀老師 universe (sector_tickers ∪ picks_2026 ≈ 332 檔)。"""
    import json as _json
    tickers: set[str] = set()
    base = _REPO / "docs" / "主力大課程"
    try:
        with open(base / "teacher_sector_tickers.json", encoding="utf-8") as fh:
            d = _json.load(fh)
        for v in d.values():
            if isinstance(v, list):
                tickers.update(str(t) for t in v)
    except Exception:
        pass
    try:
        with open(base / "teacher_picks_2026.json", encoding="utf-8") as fh:
            d = _json.load(fh)
        for k in d:
            if isinstance(k, str) and k.isdigit() and len(k) == 4:
                tickers.add(k)
    except Exception:
        pass
    return sorted(tickers)


# ── legacy: 舊 candidate-based loader (已停用、僅保留供將來參考) ──────────
def _load_overnight_candidates_legacy() -> tuple[list[dict], str]:
    """讀兩個 CSV 並合併，回傳 (candidate_list, signal_date_str)。

    每個 candidate dict 包含 {"ticker": str, "source": "✅ 確認" | "⚡ 預估"}.
    dedup by (signal_date, ticker)，確認版優先（相同 ticker 確認版覆蓋預估版）。
    signal_date 以確認版最新日期為準（若無，用預估版）。

    Returns:
        (candidate_list, signal_date_str) — 若兩個 CSV 皆不存在或空，回傳 ([], "")
    """
    try:
        import pandas as pd

        rows: list[dict] = []   # {"ticker", "source", "signal_date"}

        # ── 確認版 ────────────────────────────────────────────────────────────
        confirmed_date = ""
        if _OVERNIGHT_CSV.exists():
            df_c = pd.read_csv(_OVERNIGHT_CSV, dtype={"ticker": str})
            if not df_c.empty and "signal_date" in df_c.columns and "ticker" in df_c.columns:
                confirmed_date = str(df_c["signal_date"].max())
                latest_c = df_c[df_c["signal_date"] == confirmed_date]
                for tk in latest_c["ticker"].dropna().astype(str).unique():
                    rows.append({"ticker": tk, "source": "✅ 確認", "signal_date": confirmed_date})

        # ── 預估版 ────────────────────────────────────────────────────────────
        intraday_date = ""
        if _OVERNIGHT_INTRADAY_CSV.exists():
            df_i = pd.read_csv(_OVERNIGHT_INTRADAY_CSV, dtype={"ticker": str})
            if not df_i.empty and "signal_date" in df_i.columns and "ticker" in df_i.columns:
                intraday_date = str(df_i["signal_date"].max())
                latest_i = df_i[df_i["signal_date"] == intraday_date]
                for tk in latest_i["ticker"].dropna().astype(str).unique():
                    rows.append({"ticker": tk, "source": "⚡ 預估", "signal_date": intraday_date})

        if not rows:
            return [], ""

        # dedup: 同 ticker 確認版優先
        seen: dict[str, dict] = {}
        for r in rows:
            tk = r["ticker"]
            if tk not in seen or r["source"] == "✅ 確認":
                seen[tk] = r

        candidates = sorted(seen.values(), key=lambda r: r["ticker"])
        signal_date = confirmed_date or intraday_date
        return candidates, signal_date

    except Exception:
        return [], ""


# ── overnight condition evaluator (live: static cache + Fubon snap) ─────────
def _evaluate_overnight_live(
    ticker: str,
    static: dict,
    snap: dict | None,
    market_static: dict,
    market_snap: dict | None,
) -> dict:
    """Live 評估 4 條件：用 static cache 提供 BB/MA/斜率/量基線、用 snap 提供今日 close/open/volume.

    static: 該 ticker 在 overnight_static_features.json 內的 dict (含 bb_upper / bandwidth_prev /
            ma20_slope_5d / prev_close / prev_volume / vol_20d_avg ...)
    snap:   Fubon get_realtime_snapshot 結果 (close/open/total_volume) — 可能為 None
    market_static: static["_market"]["TAIEX"] 或 ["TPEX"]
    market_snap:   Fubon snap for TAIEX (可能為 None)

    Returns dict 同舊 _evaluate_overnight_conditions schema、外加 "asof": HH:MM:SS.
    """
    result = {
        "ticker": ticker, "price": 0.0,
        "bb": False, "kbar": False, "slope": False, "market": False,
        "pass_count": 0, "strength_score": 0.0, "fails": [],
        "error": None, "asof": "",
    }
    try:
        if not static or static.get("error") and "asof_date" not in static:
            result["error"] = static.get("error") if static else "no_static"
            return result

        from zhuli.config import OvernightSwingConfig
        cfg = OvernightSwingConfig()

        bb_upper       = static.get("bb_upper")
        bandwidth_prev = static.get("bandwidth_prev")
        slope_5d       = static.get("ma20_slope_5d")
        ma20           = static.get("ma20")
        prev_close_v   = static.get("prev_close") or 0.0
        prev_vol       = static.get("prev_volume") or 0.0

        # snap → today close/volume；無 snap (盤前) 則 fallback 用 static prev_close 不評估
        close_ = 0.0
        vol_   = 0.0
        if snap:
            try:
                close_ = float(snap.get("close") or 0)
                vol_   = float(snap.get("total_volume") or 0)
            except Exception:
                pass
            ts = snap.get("ts") or snap.get("timestamp") or ""
            if ts:
                # ts 可能是 datetime 物件或 str；取 HH:MM:SS
                try:
                    if hasattr(ts, "strftime"):
                        result["asof"] = ts.strftime("%H:%M:%S")
                    else:
                        s = str(ts)
                        result["asof"] = s[-8:] if len(s) >= 8 else s
                except Exception:
                    pass
            if not result["asof"]:
                result["asof"] = datetime.now().strftime("%H:%M:%S")

        result["price"] = close_

        # ── 條件 1: BB ────────────────────────────────────────────────────
        bb_pass = False
        if close_ and bb_upper and bandwidth_prev is not None:
            bb_pass = (close_ > float(bb_upper)) and (
                float(bandwidth_prev) < cfg.bandwidth_max
            )
        result["bb"] = bb_pass

        # ── 條件 2: K棒 (body / 量 / 量增) ───────────────────────────────
        body_pct = ((close_ - prev_close_v) / prev_close_v
                    if prev_close_v and close_ else 0.0)
        vol_lots = vol_ / 1000.0 if vol_ else 0.0
        kbar_pass = (
            body_pct >= cfg.body_min
            and vol_lots >= cfg.min_volume_lots
            and vol_ > prev_vol * cfg.prev_volume_multiplier
        )
        result["kbar"] = kbar_pass

        # ── 條件 3: MA20 斜率 (純 static) ────────────────────────────────
        slope_pass = (slope_5d is not None
                      and float(slope_5d) > cfg.ma20_slope_min)
        result["slope"] = slope_pass

        # ── 條件 4: 大盤 (snap-based + static MA5 fallback) ──────────────
        market_pass = False
        try:
            if market_snap and market_static:
                m_close = float(market_snap.get("close") or 0)
                m_open  = float(market_snap.get("open")  or 0)
                m_vol   = float(market_snap.get("total_volume") or 0)
                prev_v  = float(market_static.get("prev_volume") or 0)
                ma5     = market_static.get("ma5")
                if m_close and m_open and ma5:
                    market_pass = (
                        m_close > m_open                # 紅 K
                        and m_vol > prev_v              # 量增
                        and m_close > float(ma5)        # > 5MA
                    )
            elif market_static:
                # 無 live snap → 用 static prev (asof_date 那天的結果) 當 fallback
                m_close = float(market_static.get("prev_close") or 0)
                m_open  = float(market_static.get("prev_open")  or 0)
                ma5     = market_static.get("ma5")
                if m_close and m_open and ma5:
                    market_pass = (m_close > m_open and m_close > float(ma5))
        except Exception:
            pass
        result["market"] = market_pass

        result["pass_count"] = sum([bb_pass, kbar_pass, slope_pass, market_pass])
        result["fails"] = [k for k in ("bb", "kbar", "slope", "market") if not result[k]]

        # strength score: distance above ma20 + vol ratio (capped 5) + body size
        try:
            ma20_val = float(ma20) if ma20 else 0.0
            dist_ma20 = (max(0.0, (close_ - ma20_val) / ma20_val)
                         if ma20_val and close_ else 0.0)
            vol_ratio_prev = (vol_ / prev_vol) if prev_vol else 1.0
            result["strength_score"] = (
                dist_ma20
                + min(vol_ratio_prev, 5.0)
                + abs(body_pct)
            )
        except Exception:
            result["strength_score"] = 0.0

    except Exception as e:
        result["error"] = str(e)[:40]

    return result


def _overnight_status_text(r: dict) -> str:
    """Generate status column text from evaluation result dict (spec §6)."""
    if r.get("error"):
        return "無資料"
    pc = r["pass_count"]
    fails = r.get("fails") or [k for k in ("bb", "kbar", "slope", "market") if not r[k]]
    if pc == 4:
        return "✅ 可進場"
    if pc == 3:
        label_map = {"bb": "布林", "kbar": "K棒", "slope": "斜率", "market": "大盤"}
        f = label_map.get(fails[0], fails[0]) if fails else "?"
        return f"⭐ 接近 (差 {f})"
    if pc == 2:
        label_map = {"bb": "布林", "kbar": "K棒", "slope": "斜率", "market": "大盤"}
        f0 = label_map.get(fails[0], fails[0]) if len(fails) > 0 else "?"
        f1 = label_map.get(fails[1], fails[1]) if len(fails) > 1 else "?"
        return f"🟡 監控 ({f0}+{f1})"
    if pc == 1:
        return "⚪ 監控 (差 3)"
    return "⚫ 完全不符"


# ── Pin dialog ────────────────────────────────────────────────────────────────
class PinDialog(ModalScreen[str | None]):
    """輸入 4 位數 ticker 加入/移除 Pin。"""

    CSS = """
    PinDialog {
        align: center middle;
        background: rgba(0,0,0,0.7);
    }
    .dialog-box {
        background: #1a1a1a;
        border: solid yellow;
        padding: 1 2;
        width: 44;
        height: 9;
    }
    """

    def __init__(self, title_text: str = "Pin 標的"):
        super().__init__()
        self._title_text = title_text

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog-box"):
            yield Label(self._title_text)
            yield Input(placeholder="輸入代號 (4位數、Enter確認、Esc取消)",
                        id="pin-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)


# ── Search bar widget ─────────────────────────────────────────────────────────
class SearchBar(Static):
    """底部搜尋欄 (/ 鍵叫出、Esc 關閉)。"""

    def compose(self) -> ComposeResult:
        yield Input(placeholder="輸入代號或股名搜尋 (Enter 跳到、Esc 關閉)",
                    id="search-input")


# ── Status bar widget ─────────────────────────────────────────────────────────
class StatusBar(Static):
    """頂部一行狀態列 (大盤 + 時間 + filter 狀態)。"""

    status_text: reactive[str] = reactive("")

    def render(self) -> str:
        return self.status_text


# ── Detail panel widget ──────────────────────────────────────────────────────
class DetailPanel(Static):
    """tab 與 table 之間的 detail 區、跟著 cursor 顯示完整 trigger + 出貨警示。"""

    detail_text: reactive[str] = reactive("(↑↓ 選 row 看詳情)")

    def render(self) -> str:
        return self.detail_text


# ──────────────────────────────────────────────────────────────────────────────
# Main App
# ──────────────────────────────────────────────────────────────────────────────
class MonitorApp(App[None]):
    """Textual TUI v2 主應用。"""

    TITLE = "🚀 Trading Monitor v2"
    CSS = CSS

    BINDINGS = [
        Binding("t",       "toggle_teacher",  "老師only"),
        Binding("f",       "toggle_failed",   "顯失敗"),
        Binding("a",       "pin_add",         "Pin"),
        Binding("u",       "pin_remove",       "Unpin"),
        Binding("slash",   "search_open",     "搜尋"),
        Binding("ctrl+r",  "refresh_data",    "重整"),
        Binding("q",       "quit",            "退出"),
        Binding("1",       "switch_tab_1",    "持倉", show=False),
        Binding("2",       "switch_tab_2",    "隔日沖", show=False),
        Binding("3",       "switch_tab_3",    "可進場", show=False),
        Binding("4",       "switch_tab_4",    "觀察", show=False),
        Binding("5",       "switch_tab_5",    "Pinned", show=False),
        Binding("6",       "switch_tab_6",    "Scanner", show=False),
        Binding("shift+left",  "page_up",   "↑頁"),
        Binding("shift+right", "page_down", "↓頁"),
    ]

    # ── reactive state ───────────────────────────────────────────────────────
    teacher_only: reactive[bool] = reactive(True)
    show_failed:  reactive[bool] = reactive(False)
    search_active: reactive[bool] = reactive(False)
    search_term:   reactive[str]  = reactive("")
    pinned_tickers: reactive[frozenset] = reactive(frozenset())

    def __init__(self, client=None, demo_mode: bool = False,
                 demo_client=None, demo_scenarios=None, **kwargs):
        super().__init__(**kwargs)
        self._client = client
        self._demo_mode = demo_mode
        self._demo_client = demo_client
        self._demo_scenarios = demo_scenarios or []
        self._demo_idx = 0
        self._demo_paused = True
        self._demo_goto_mode = False
        self._demo_goto_buf = ""
        self._demo_total = len(self._demo_scenarios)

        # 資料快取
        self._live_data: dict[str, dict] = {}   # ticker → {close, open, vol_ratio, pnl, trigger…}
        self._data_lock = threading.Lock()
        self._refresh_thread: threading.Thread | None = None
        self._quit = False

        # Normalize lists (重用 v1 normalizers)
        self._held   = _normalize_held(HELD[:])
        self._watch  = _normalize_watch(WATCH[:])
        self._plan   = _normalize_plan(PLAN_PRIMARY[:])

        # merge scanner watchlist
        try:
            _merge_scanner_watchlist()
            self._watch = _normalize_watch(_v1.WATCH[:])
        except Exception:
            pass

        # ── 真分頁 state ────────────────────────────────────────────────────
        self._current_page: dict[str, int] = {}   # tab_id → page (1-indexed)
        self._page_size_default: int = 40

        # ── overnight live evaluation cache ─────────────────────────────────
        self._overnight_signals: list[dict] = []
        self._overnight_cache_ts: float = 0.0  # last eval time (monotonic)
        self._overnight_cache_ttl: float = 60.0  # 1 minute
        self._overnight_candidate_date: str = ""  # signal_date of last loaded candidates

        # ── 出貨訊號 tracker + baseline ─────────────────────────────────────
        held_tickers = [str(i.get('ticker', '')) for i in self._held
                        if i.get('ticker')]
        self._dump_tracker = DumpStateTracker(tickers=held_tickers)
        try:
            self._dump_baseline = load_baseline(_BASELINE_PATH)
        except Exception:
            self._dump_baseline = {}

    # ── compose ──────────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Header()
        yield StatusBar(id="status-bar")
        yield DetailPanel(id="detail-panel")

        with TabbedContent(id="main-tabs"):
            with TabPane(TAB_LABELS[TAB_HELD], id=TAB_HELD,
                         classes="held-pane"):
                yield DataTable(id="dt-held", zebra_stripes=True,
                                cursor_type="row")

            with TabPane(TAB_LABELS[TAB_OVERNIGHT], id=TAB_OVERNIGHT,
                         classes="overnight-pane"):
                yield Static("(載入中…)", id="overnight-header")
                yield DataTable(id="dt-overnight", zebra_stripes=True,
                                cursor_type="row")

            with TabPane(TAB_LABELS[TAB_CONFIRMED], id=TAB_CONFIRMED,
                         classes="confirmed-pane"):
                yield DataTable(id="dt-confirmed", zebra_stripes=True,
                                cursor_type="row")

            with TabPane(TAB_LABELS[TAB_WATCHING], id=TAB_WATCHING,
                         classes="watching-pane"):
                yield DataTable(id="dt-watching", zebra_stripes=True,
                                cursor_type="row")

            with TabPane(TAB_LABELS[TAB_PINNED], id=TAB_PINNED,
                         classes="pinned-pane"):
                yield DataTable(id="dt-pinned", zebra_stripes=True,
                                cursor_type="row")

            with TabPane(TAB_LABELS[TAB_SCANNER], id=TAB_SCANNER,
                         classes="scanner-pane"):
                yield DataTable(id="dt-scanner", zebra_stripes=True,
                                cursor_type="row")

        yield SearchBar(id="search-bar")
        yield Footer()

    # ── lifecycle ────────────────────────────────────────────────────────────
    def on_mount(self) -> None:
        self._setup_tables()
        self._start_data_refresh()
        # 每秒更新 status bar + table
        self.set_interval(1.0, self._tick)
        # Bug 1 fix: 啟動後自動 focus 第一個 tab 的 DataTable
        self.call_after_refresh(self._focus_active_table)

    def _focus_active_table(self) -> None:
        """Focus 當前 tab 的 DataTable，讓鍵盤 ↑↓ 立即生效（不需先 click）。"""
        try:
            active_pane = self.query_one(TabbedContent).active_pane
            if active_pane:
                table = active_pane.query_one(DataTable)
                table.focus()
        except Exception:
            pass

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """切 tab 後自動 focus 新 tab 的 DataTable + 重新計算 detail。"""
        self.call_after_refresh(self._focus_active_table)
        self.call_after_refresh(self._update_detail_panel)

    def on_data_table_row_highlighted(
        self, event: DataTable.RowHighlighted
    ) -> None:
        """游標移到某 row、更新 detail panel 顯示完整 trigger + 出貨警示。"""
        self._update_detail_panel()

    _tables_ready: bool = False  # guard against on_resize before on_mount

    def _update_detail_panel(self) -> None:
        """讀取當前 active tab cursor row 對應 ticker、寫入 detail panel。"""
        try:
            panel = self.query_one("#detail-panel", DetailPanel)
        except Exception:
            return
        try:
            active_pane = self.query_one(TabbedContent).active_pane
            dt = active_pane.query_one(DataTable) if active_pane else None
            if not dt or dt.row_count == 0:
                panel.detail_text = "(↑↓ 選 row 看詳情)"
                return
            cursor = dt.cursor_row or 0
            row_key = dt.coordinate_to_cell_key((cursor, 0)).row_key
            tk = str(row_key.value) if row_key else ""
            if not tk:
                panel.detail_text = "(↑↓ 選 row 看詳情)"
                return
            with self._data_lock:
                d = dict(self._live_data.get(tk, {}))
            name = ""
            source = ""
            sector = ""
            for src in (self._held, self._watch, self._plan):
                for i in src:
                    if str(i.get('ticker', '')) == tk:
                        name = i.get('name', '')
                        source = str(i.get('source', '') or '')
                        sector = str(i.get('sector', '') or '')
                        break
                if name:
                    break
            trig_key = d.get('trigger', 'none')
            trig_reason = d.get('trig_reason', '') or ""
            trig_label = TRIGGER_DISPLAY.get(trig_key, "⚪ 無訊號")
            trig_line = f"Trigger: {trig_label}"
            if trig_reason:
                trig_line += f"  ({trig_reason})"
            dump_full = d.get('dump_warn_full', '') or ""
            dump_line = f"出貨:    {dump_full}" if dump_full else "出貨:    —"
            src_parts = []
            if source:
                src_parts.append(source)
            if sector:
                src_parts.append(sector)
            source_line = f"來源:    {' | '.join(src_parts)}" if src_parts else "來源:    —"
            panel.detail_text = f"[{tk} {name}]\n{trig_line}\n{dump_line}\n{source_line}"
        except Exception:
            pass

    def _setup_tables(self) -> None:
        """初始化所有 DataTable 的 columns。"""
        for table_id, cols in [
            ("dt-held",      COLS_HELD),
            ("dt-confirmed", COLS_WATCH),
            ("dt-watching",  COLS_WATCH),
            ("dt-pinned",    COLS_HELD),
            ("dt-overnight", COLS_OVERNIGHT),
            ("dt-scanner",   COLS_WATCH),
        ]:
            dt: DataTable = self.query_one(f"#{table_id}", DataTable)
            for key, label, width in cols:
                if key == "trigger":
                    dt.add_column(label, key=key)
                else:
                    dt.add_column(label, key=key, width=width)
        self._tables_ready = True

    # ── data refresh ─────────────────────────────────────────────────────────
    def _start_data_refresh(self) -> None:
        """啟動背景 thread 定期抓報價 + 計算 trigger / vol_ratio。"""
        self._refresh_thread = threading.Thread(
            target=self._refresh_loop, daemon=True
        )
        self._refresh_thread.start()

    def _refresh_loop(self) -> None:
        while not self._quit:
            try:
                self._fetch_all()
            except Exception:
                pass
            try:
                self._overnight_cache_refresh()
            except Exception:
                pass
            # demo: 0.5s cycle 快一點、real: 3s
            interval = 0.5 if self._demo_mode else 3.0
            t_end = time.time() + interval
            while time.time() < t_end and not self._quit:
                time.sleep(0.1)

    def _fetch_all(self) -> None:
        """抓所有 ticker 的 snapshot + 計算衍生欄位。"""
        client = self._demo_client if self._demo_mode else self._client
        if client is None:
            return

        # dedup ticker (held 優先)、避免同 ticker 在 held + watch/plan 被跑 2 次、
        # 第二次拿 watch item (沒 cost/shares) 蓋掉 held 的 P&L
        held_tickers = {str(i.get('ticker', '')) for i in self._held}
        held_by_ticker = {str(i.get('ticker', '')): i for i in self._held}
        seen: set[str] = set()
        all_items = []
        for src in (self._held, self._watch, self._plan):
            for it in src:
                tk_ = str(it.get('ticker', ''))
                if not tk_ or tk_ in seen:
                    continue
                seen.add(tk_)
                all_items.append(it)
        for item in all_items:
            tk = str(item.get('ticker', ''))
            if not tk:
                continue
            try:
                snap = client.get_realtime_snapshot(tk) or {}
                close_ = float(snap.get('close') or 0)
                open_  = float(snap.get('open')  or 0)
                # snap 失敗 (close=0) → 完全 skip、不寫入 0 (寧可顯示「—」)
                # 包含首次失敗、避免後續 race 出 0 P&L (HELD 看到 0 會誤判已停損)
                if not close_:
                    continue
                vol_   = snap.get('total_volume')
                vol_ratio = compute_vol_ratio(tk, float(vol_) if vol_ else None)
                ma10   = load_ma10(tk)

                # ── dump signals: only for HELD tickers ─────────────────────
                dump_warn = ""
                dump_warn_full = ""
                # prev_close 取「前一交易日收盤」(不是今天 partial、不是 stale baseline)
                # DB 直查、用 trade_date < today、避免 backfill 的當日 partial 污染
                prev_close = 0.0
                try:
                    import sqlite3 as _sql
                    from datetime import date as _date
                    _today = _date.today().isoformat()
                    _con = _sql.connect(f"file:{str(_v1.DB)}?mode=ro", uri=True, timeout=3)
                    _row = _con.execute(
                        "SELECT close FROM standard_daily_bar WHERE ticker=? AND trade_date < ? ORDER BY trade_date DESC LIMIT 1",
                        (tk, _today)
                    ).fetchone()
                    _con.close()
                    if _row:
                        prev_close = float(_row[0])
                except Exception:
                    prev_close = 0.0
                # baseline fallback (只取 ≤ 3 天前的、避免 stale)
                if not prev_close and tk in held_tickers and self._dump_baseline:
                    b = self._dump_baseline.get(tk, {})
                    _yd = b.get('yesterday_date', '')
                    try:
                        from datetime import datetime as _dt, date as _dt_date
                        if _yd and (_dt_date.fromisoformat(_dt.strptime(_yd, "%Y-%m-%d").strftime("%Y-%m-%d")) -
                                   _dt_date.fromisoformat(_today)).days >= -3:
                            prev_close = float(b.get('yesterday_close') or 0)
                    except Exception:
                        pass
                if tk in held_tickers:
                    try:
                        self._dump_tracker.update_tick(
                            tk, close_ if close_ else None,
                            cum_volume=float(vol_) if vol_ else None,
                        )
                        d_state = self._dump_tracker.get_state(tk)
                        d_spike = self._dump_tracker.get_volume_spike(tk)
                        warns = evaluate_dump_signals(
                            tk, d_state, held_by_ticker.get(tk, item),
                            self._dump_baseline,
                            current_close=close_ if close_ else None,
                            volume_spike=d_spike,
                        )
                        if warns:
                            dump_warn_full = " | ".join(warns)
                            crit = sum(1 for w in warns if "🚨" in w)
                            warn = sum(1 for w in warns if "⚠️" in w)
                            if crit:
                                dump_warn = f"🔴×{crit}" if crit > 1 else "🔴"
                            elif warn:
                                dump_warn = f"🟡×{warn}" if warn > 1 else "🟡"
                    except Exception:
                        pass

                # trigger (demo: mock override)
                if self._demo_mode:
                    trig_key, trig_reason = _v1.check_trigger_inline(tk, item.get('tactic', '核心'))
                else:
                    trig_key, trig_reason = check_trigger_inline(tk, item.get('tactic', '核心'))

                record_trigger_fire(tk, trig_key)

                # P&L (held only) — 永遠從 held_by_ticker 查、不靠 item (避免 watch/plan 蓋掉)
                _held_item = held_by_ticker.get(tk, {})
                cost   = float(_held_item.get('cost') or 0)
                shares = int(_held_item.get('shares') or 0)
                pnl    = (close_ - cost) * shares if cost and shares and close_ else 0.0
                pnl_pct= (close_ - cost) / cost * 100 if cost and close_ else 0.0

                # 距停
                stop   = item.get('stop')
                dist_stop = ((close_ - float(stop)) / float(stop) * 100
                             if stop and close_ else 999.0)

                # 距 MA10
                dist_ma10 = ((close_ - ma10) / ma10 * 100
                             if ma10 and close_ else None)

                # open→now pct
                otn_pct = ((close_ - open_) / open_ * 100
                           if open_ and close_ else None)

                with self._data_lock:
                    self._live_data[tk] = {
                        'close':      close_,
                        'open':       open_,
                        'vol_ratio':  vol_ratio,
                        'pnl':        pnl,
                        'pnl_pct':    pnl_pct,
                        'dist_stop':  dist_stop,
                        'dist_ma10':  dist_ma10,
                        'otn_pct':    otn_pct,
                        'trigger':    trig_key,
                        'trig_reason': trig_reason,
                        'dump_warn':  dump_warn,
                        'dump_warn_full': dump_warn_full,
                        'prev_close': prev_close,
                    }
            except Exception:
                pass

    # ── tick (1s 更新 UI) ────────────────────────────────────────────────────
    def _tick(self) -> None:
        self._update_status_bar()
        self._update_all_tables()
        self._update_detail_panel()

    def _update_status_bar(self) -> None:
        now = datetime.now()
        regime_label, _ = _get_market_regime_chip()
        session_label, _ = _get_session_chip(now)
        teacher_tag = "[t:ON]" if self.teacher_only else "[t:OFF]"
        failed_tag  = "[f:ON]" if self.show_failed  else ""
        pinned_tag  = f"[pin:{len(self.pinned_tickers)}]" if self.pinned_tickers else ""
        mode_tag    = "[DEMO]" if self._demo_mode else ""
        pagination  = self._fmt_pagination()
        bar = self.query_one("#status-bar", StatusBar)
        text = (f"{mode_tag} {regime_label} | {session_label} | "
                f"{teacher_tag} {failed_tag} {pinned_tag} | "
                f"{pagination} | "
                f"{now.strftime('%H:%M:%S')}")
        bar.status_text = text

    def _fmt_pagination(self) -> str:
        """當前 tab 的「row X/Y | page N/M (K列)」。K = 最後一頁實際列數。"""
        try:
            tab_id = self._get_active_tab_id()
            if not tab_id:
                return ""
            total  = self._get_total_items_for_tab(tab_id)
            if total == 0:
                return "row 0/0"
            ps          = self._calc_page_size()
            page        = self._current_page.get(tab_id, 1)
            total_pages = max(1, math.ceil(total / ps))
            # 頁內 row 數 (最後一頁可能不滿)
            page_rows   = total - (page - 1) * ps
            page_rows   = max(0, min(page_rows, ps))
            # cursor 相對於所有資料的絕對位置
            try:
                active_pane = self.query_one(TabbedContent).active_pane
                dt = active_pane.query_one(DataTable) if active_pane else None
                cursor_in_page = (dt.cursor_row or 0) if dt else 0
            except Exception:
                cursor_in_page = 0
            abs_cursor = (page - 1) * ps + cursor_in_page + 1
            abs_cursor = min(abs_cursor, total)
            suffix = f" ({page_rows}列)" if page == total_pages and total_pages > 1 else ""
            return f"row {abs_cursor}/{total} | page {page}/{total_pages}{suffix}"
        except Exception:
            return ""

    def on_resize(self, event) -> None:
        """terminal 大小改變時、重算 pagination、確保 current_page 不超出、重繪 table。"""
        if not self._tables_ready:
            return  # on_mount 還沒跑、columns 未 setup、skip
        for tab_id in list(self._current_page.keys()):
            total = self._get_total_items_for_tab(tab_id)
            ps    = self._calc_page_size()
            total_pages = max(1, math.ceil(total / ps))
            self._current_page[tab_id] = min(
                self._current_page.get(tab_id, 1), total_pages
            )
        self._update_all_tables()
        self._update_status_bar()

    # ── 真分頁 helpers ────────────────────────────────────────────────────────
    def _calc_page_size(self) -> int:
        """從當前 active tab 的 DataTable viewport 高度算出每頁列數。"""
        try:
            tabbed = self.query_one(TabbedContent)
            active = tabbed.active_pane
            if active:
                dt = active.query_one(DataTable)
                h = max(1, int(dt.size.height) - 1)  # 扣 header
                return h
        except Exception:
            pass
        return self._page_size_default

    def _get_active_tab_id(self) -> str | None:
        try:
            return self.query_one(TabbedContent).active
        except Exception:
            return None

    def _get_total_items_for_tab(self, tab_id: str) -> int:
        """回傳 tab 對應的 filtered item 總數。"""
        with self._data_lock:
            ld = dict(self._live_data)

        if tab_id == TAB_HELD:
            items = self._held
            if self.search_term:
                items = [i for i in items if self._match_search(i)]
            return len(items)

        if tab_id == TAB_CONFIRMED:
            items = self._filter_watch_items(self._watch)
            items = [i for i in items
                     if self._classify_watch(
                         i, ld.get(str(i.get('ticker', '')), {})) == 'confirmed']
            if self.search_term:
                items = [i for i in items if self._match_search(i)]
            return len(items)

        if tab_id == TAB_WATCHING:
            items = self._filter_watch_items(self._watch)
            if not self.show_failed:
                items = [i for i in items
                         if self._classify_watch(
                             i, ld.get(str(i.get('ticker', '')), {})) != 'excluded']
            if self.search_term:
                items = [i for i in items if self._match_search(i)]
            return len(items)

        if tab_id == TAB_PINNED:
            all_items = {str(i.get('ticker', '')): i
                         for i in (self._held + self._watch + self._plan)}
            items = []
            for tk in self.pinned_tickers:
                items.append(all_items.get(tk, {'ticker': tk}))
            if self.search_term:
                items = [i for i in items if self._match_search(i)]
            return len(items)

        if tab_id == TAB_OVERNIGHT:
            # 只算 4/4 合格的
            return sum(1 for r in self._overnight_signals if r.get("pass_count") == 4)

        if tab_id == TAB_SCANNER:
            items = list(self._watch)
            if self.search_term:
                items = [i for i in items if self._match_search(i)]
            return len(items)

        return 0

    def _paginate(self, items: list, tab_id: str) -> list:
        """依 _current_page[tab_id] 切出當頁的 items。"""
        ps    = self._calc_page_size()
        page  = self._current_page.get(tab_id, 1)
        start = (page - 1) * ps
        end   = start + ps
        return items[start:end]

    # ── table refresh ─────────────────────────────────────────────────────────
    def _update_all_tables(self) -> None:
        if not self._tables_ready:
            return  # on_mount 還沒跑、columns 未 setup、skip
        with self._data_lock:
            ld = dict(self._live_data)

        self._refresh_held_table(ld)
        self._refresh_confirmed_table(ld)
        self._refresh_watching_table(ld)
        self._refresh_pinned_table(ld)
        self._refresh_overnight_table()
        self._refresh_scanner_table(ld)

    def _fmt_otn(self, otn_pct: float | None) -> str:
        if otn_pct is None:
            return "—"
        sign = "+" if otn_pct >= 0 else ""
        return f"{sign}{otn_pct:.1f}%"

    def _fmt_gap(self, open_: float, prev_close: float) -> str:
        """跳空 % (open vs prev_close)、e.g., '+1.2%' / '-1.8%' / '—'。"""
        if not open_ or not prev_close:
            return "—"
        pct = (open_ - prev_close) / prev_close * 100
        sign = "+" if pct >= 0 else ""
        return f"{sign}{pct:.1f}%"

    def _fmt_price(self, close_: float, prev_close: float) -> str:
        """現價 (4 位左空白 + 2 小數) + 漲跌% e.g., '  39.10 (-2.5%)'。"""
        if not close_:
            return "—"
        price = f"{close_:7.2f}"  # 4 位整數 + . + 2 位小數
        if prev_close:
            pct = (close_ - prev_close) / prev_close * 100
            sign = "+" if pct >= 0 else ""
            return f"{price} ({sign}{pct:.1f}%)"
        return price

    def _fmt_vol(self, vol_ratio: float | None) -> str:
        if vol_ratio is None:
            return "—"
        if vol_ratio >= 3.0:
            return f"🚀{vol_ratio:.1f}x"
        if vol_ratio >= 2.0:
            return f"🟢{vol_ratio:.1f}x"
        if vol_ratio >= 1.5:
            return f"🟡{vol_ratio:.1f}x"
        return f"⚪{vol_ratio:.1f}x"

    def _fmt_pnl(self, pnl: float, pct: float) -> str:
        sign = "+" if pnl >= 0 else ""
        return f"{sign}{pnl:,.0f} ({sign}{pct:.1f}%)"

    def _fmt_dist(self, dist: float) -> str:
        if dist >= 999:
            return "—"
        sign = "+" if dist >= 0 else ""
        return f"{sign}{dist:.1f}%"

    def _fmt_trigger(self, trig_key: str, reason: str = "") -> str:
        label = TRIGGER_DISPLAY.get(trig_key, "⚪ 無訊號")
        if reason and trig_key not in ("none", None, ""):
            return f"{label} ({reason[:35]})"
        return label

    def _get_status_icon(self, item: dict, ld: dict) -> str:
        tk = str(item.get('ticker', ''))
        d  = ld.get(tk, {})
        dist = d.get('dist_stop', 999.0)
        trig = d.get('trigger', 'none')
        if dist < 0:
            return "🔴"
        if dist < 1:
            return "⚠️"
        if trig in ("首攻", "續攻", "反彈", "Ch5-3", "T1", "T2",
                    "尾盤_confirmed", "Closing_confirmed"):
            return "🟢"
        return "⚪"

    def _match_search(self, item: dict) -> bool:
        """搜尋過濾：ticker 或 name 含 search_term。"""
        if not self.search_term:
            return True
        term = self.search_term.lower()
        return (term in str(item.get('ticker', '')).lower() or
                term in str(item.get('name', '')).lower())

    def _refresh_held_table(self, ld: dict) -> None:
        dt: DataTable = self.query_one("#dt-held", DataTable)
        saved_cursor, saved_scroll = self._save_table_state(dt)
        items = self._held
        if self.search_term:
            items = [i for i in items if self._match_search(i)]
        items = self._paginate(items, TAB_HELD)
        dt.clear()
        for item in items:
            tk    = str(item.get('ticker', ''))
            d     = ld.get(tk, {})
            close_= d.get('close', 0)
            open_ = d.get('open', 0)
            otn   = self._fmt_otn(d.get('otn_pct'))
            vol   = self._fmt_vol(d.get('vol_ratio'))
            pnl_str = (self._fmt_pnl(d.get('pnl', 0), d.get('pnl_pct', 0))
                       if close_ else "—")
            dist_str = self._fmt_dist(d.get('dist_stop', 999.0))
            stat  = self._get_status_icon(item, ld)
            trig  = self._fmt_trigger(d.get('trigger', 'none'), "")
            cost  = item.get('cost', 0)
            prev_close = d.get('prev_close', 0)
            gap_str   = self._fmt_gap(open_, prev_close)
            price_str = self._fmt_price(close_, prev_close)
            dump_warn = d.get('dump_warn', '') or ""
            trig_combined = f"{dump_warn} {trig}".strip() if dump_warn else trig
            row   = (tk, item.get('name', ''), f"{cost:.1f}" if cost else "—",
                     gap_str, price_str,
                     vol, pnl_str, dist_str, stat, trig_combined)
            dt.add_row(*row, key=tk)
        self._restore_table_state(dt, saved_cursor, saved_scroll)

    def _classify_watch(self, item: dict, d: dict) -> str:
        """分類 WATCH item: confirmed / watching / excluded。
        重用 v1 _classify_watch_item 邏輯 (依 trigger key)。
        """
        if _classify_watch_item:
            try:
                return _classify_watch_item(item, d)
            except Exception:
                pass
        # fallback
        trig = d.get('trigger', 'none')
        if trig in ('首攻', '續攻', '反彈', 'Ch5-3', 'T1', 'T2',
                    '尾盤_confirmed', 'Closing_confirmed'):
            return 'confirmed'
        if trig in ('破底', 'TC'):
            return 'excluded'
        return 'watching'

    def _refresh_watch_table(self, table_id: str, items: list[dict], ld: dict,
                              tab_id: str | None = None) -> None:
        dt: DataTable = self.query_one(f"#{table_id}", DataTable)
        saved_cursor, saved_scroll = self._save_table_state(dt)
        if self.search_term:
            items = [i for i in items if self._match_search(i)]
        if tab_id:
            items = self._paginate(items, tab_id)
        dt.clear()
        for item in items:
            tk   = str(item.get('ticker', ''))
            d    = ld.get(tk, {})
            close_ = d.get('close', 0)
            open_  = d.get('open', 0)
            otn    = self._fmt_otn(d.get('otn_pct'))
            vol    = self._fmt_vol(d.get('vol_ratio'))
            dist_ma10 = d.get('dist_ma10')
            dist_str  = self._fmt_dist(dist_ma10) if dist_ma10 is not None else "—"
            trig   = self._fmt_trigger(d.get('trigger', 'none'), d.get('trig_reason', ''))
            pri    = item.get('priority', 2)
            stars  = "⭐" * max(0, pri)
            name   = item.get('name', '')
            tactic = item.get('tactic', '')
            sector = item.get('sector', '')
            source = str(item.get('source', ''))[:10]
            prev_close = d.get('prev_close', 0)
            gap_str  = self._fmt_gap(open_, prev_close)
            price_str = self._fmt_price(close_, prev_close)
            row = (tk, stars, name, tactic, gap_str, price_str, vol,
                   dist_str, sector, source, trig)
            dt.add_row(*row, key=tk)
        self._restore_table_state(dt, saved_cursor, saved_scroll)

    def _filter_watch_items(self, items: list[dict]) -> list[dict]:
        """依 teacher_only 過濾 WATCH items。"""
        if not self.teacher_only:
            return items
        return [i for i in items
                if '老師' in str(i.get('source', '')) or '黃大' in str(i.get('source', ''))]

    def _refresh_confirmed_table(self, ld: dict) -> None:
        # 可進場 = WATCH 中 classify → 'confirmed'
        items = self._filter_watch_items(self._watch)
        items = [i for i in items
                 if self._classify_watch(
                     i, ld.get(str(i.get('ticker', '')), {})) == 'confirmed']
        self._refresh_watch_table("dt-confirmed", items, ld, tab_id=TAB_CONFIRMED)

    def _refresh_watching_table(self, ld: dict) -> None:
        items = self._filter_watch_items(self._watch)
        # show_failed → 顯示 excluded (破底/TC); 否則過濾掉
        if not self.show_failed:
            items = [i for i in items
                     if self._classify_watch(
                         i, ld.get(str(i.get('ticker', '')), {})) != 'excluded']
        self._refresh_watch_table("dt-watching", items, ld, tab_id=TAB_WATCHING)

    def _refresh_pinned_table(self, ld: dict) -> None:
        if not self.pinned_tickers:
            dt: DataTable = self.query_one("#dt-pinned", DataTable)
            dt.clear()
            return
        all_items = {str(i.get('ticker', '')): i
                     for i in (self._held + self._watch + self._plan)}
        items = []
        for tk in self.pinned_tickers:
            if tk in all_items:
                items.append(all_items[tk])
            else:
                # ticker 不在任何清單，建假 item
                items.append({'ticker': tk, 'name': '?', 'tactic': '—',
                               'priority': 2, 'source': 'pinned',
                               'sector': '—', 'note': ''})
        # 使用 held 格式顯示 pinned
        dt: DataTable = self.query_one("#dt-pinned", DataTable)
        saved_cursor, saved_scroll = self._save_table_state(dt)
        if self.search_term:
            items = [i for i in items if self._match_search(i)]
        items = self._paginate(items, TAB_PINNED)
        dt.clear()
        for item in items:
            tk    = str(item.get('ticker', ''))
            d     = ld.get(tk, {})
            close_= d.get('close', 0)
            open_ = d.get('open', 0)
            otn   = self._fmt_otn(d.get('otn_pct'))
            vol   = self._fmt_vol(d.get('vol_ratio'))
            pnl_str = (self._fmt_pnl(d.get('pnl', 0), d.get('pnl_pct', 0))
                       if close_ and item.get('cost') else "—")
            dist_str = self._fmt_dist(d.get('dist_stop', 999.0))
            stat  = self._get_status_icon(item, ld)
            trig  = self._fmt_trigger(d.get('trigger', 'none'), "")
            cost  = item.get('cost', 0)
            prev_close = d.get('prev_close', 0)
            gap_str   = self._fmt_gap(open_, prev_close)
            price_str = self._fmt_price(close_, prev_close)
            dump_warn = d.get('dump_warn', '') or ""
            trig_combined = f"{dump_warn} {trig}".strip() if dump_warn else trig
            row   = (tk, item.get('name', ''), f"{cost:.1f}" if cost else "—",
                     gap_str, price_str,
                     vol, pnl_str, dist_str, stat, trig_combined)
            dt.add_row(*row, key=tk)
        self._restore_table_state(dt, saved_cursor, saved_scroll)

    def _overnight_cache_refresh(self) -> None:
        """Live eval 全 universe (≈332 檔) 的隔日沖 4 條件，結果存入 _overnight_signals。

        資料來源:
          - static features: overnight_static_features.json (precompute_overnight_static.py
            每天 08:30 / 12:30 跑、cron 在 launchd plist 設定)
          - live snap: FubonClient.get_realtime_snapshot(ticker) — 13:20 後才有意義

        Cache TTL = 60s。每次 _refresh_loop 末尾呼叫一次。
        永不 drop — 332 檔全顯，依 pass_count desc + strength_score desc 排序。
        """
        now_mono = time.monotonic()
        if (self._overnight_signals and
                now_mono - self._overnight_cache_ts < self._overnight_cache_ttl):
            return  # still fresh

        static_all = _load_overnight_static()
        meta       = static_all.get("_meta", {}) if static_all else {}
        market_static = (static_all.get("_market", {}) or {}).get("TAIEX", {})

        if not static_all:
            self._overnight_signals = [{
                "ticker": "—", "name": "無 static cache、請跑 precompute_overnight_static.py",
                "price": 0.0, "bb": False, "kbar": False, "slope": False,
                "market": False, "pass_count": 0, "strength_score": 0.0,
                "fails": [], "error": "no_static_cache", "asof": "",
            }]
            self._overnight_candidate_date = ""
            self._overnight_cache_ts = now_mono
            return

        universe = _load_overnight_universe()
        self._overnight_candidate_date = meta.get("asof_date", "")

        # 拿 client (real / demo 都有 get_realtime_snapshot)
        client = self._demo_client if self._demo_mode else self._client

        # TAIEX live snap
        market_snap = None
        try:
            if client is not None:
                market_snap = client.get_realtime_snapshot("TAIEX") or None
        except Exception:
            market_snap = None

        results: list[dict] = []
        for tk in universe:
            static_tk = static_all.get(tk, {}) or {}
            snap = None
            try:
                if client is not None:
                    snap = client.get_realtime_snapshot(tk) or None
            except Exception:
                snap = None
            r = _evaluate_overnight_live(
                tk, static_tk, snap, market_static, market_snap,
            )
            r["name"] = static_tk.get("stock_name", "") or ""
            results.append(r)

        # 排序: pass_count desc → strength_score desc (永不 drop)
        results.sort(key=lambda r: (-r["pass_count"], -r["strength_score"]))

        self._overnight_signals = results
        self._overnight_cache_ts = now_mono

    def _get_overnight_signals(self) -> list[dict]:
        """回傳已 cache 的 overnight 評估結果。若 cache 空則觸發同步更新。"""
        if not self._overnight_signals:
            self._overnight_cache_refresh()
        return self._overnight_signals

    def _refresh_overnight_table(self) -> None:
        """刷新 🌅 隔日沖 tab 的 DataTable（live eval 全 universe）。

        資料來源:
          - static cache: overnight_static_features.json (precompute_overnight_static.py)
          - live snap:    FubonClient.get_realtime_snapshot (13:20 後才有意義)

        只顯示 4/4 全過、按 strength_score desc 排序。
        """
        dt: DataTable = self.query_one("#dt-overnight", DataTable)
        try:
            header_widget = self.query_one("#overnight-header", Static)
        except Exception:
            header_widget = None
        saved_cursor, saved_scroll = self._save_table_state(dt)
        all_results = self._get_overnight_signals()
        dt.clear()
        if not all_results:
            if header_widget:
                header_widget.update("(載入中…)")
            dt.add_row("—", "載入中…", "—", "—", "—", "—", "—", "—", "—", "—",
                       key="__loading__")
            self._restore_table_state(dt, saved_cursor, saved_scroll)
            return

        # 只留 4/4 全過 (隱藏不合格)
        results = [r for r in all_results if r.get("pass_count") == 4]

        cache_age = int(time.monotonic() - self._overnight_cache_ts) if self._overnight_cache_ts else 0
        asof_date = self._overnight_candidate_date or "—"
        n_univ    = len([r for r in all_results if r.get("ticker", "—") != "—"])
        n_pass4   = len(results)
        n_pass3   = sum(1 for r in all_results if r.get("pass_count") == 3)
        header_info = (
            f"static asof: {asof_date}  universe {n_univ} 檔  "
            f"(顯示 4/4: {n_pass4} 檔 | 隱藏 3/4: {n_pass3} 檔)  [eval {cache_age}s前]"
        )
        if header_widget:
            header_widget.update(header_info)

        if not results:
            dt.add_row("—", "(目前無 4/4 合格)", "—", "—", "—", "—", "—", "—", "—", "—",
                       key="__no_match__")
            self._restore_table_state(dt, saved_cursor, saved_scroll)
            return

        for i, r in enumerate(results):
            ticker  = r.get("ticker", "")
            name    = r.get("name", "")
            price   = r.get("price", 0.0)
            price_s = f"{price:.2f}" if price else "—"
            bb_s    = "✅" if r.get("bb") else "❌"
            kbar_s  = "✅" if r.get("kbar") else "❌"
            slope_s = "✅" if r.get("slope") else "❌"
            mkt_s   = "✅" if r.get("market") else "❌"
            pc      = r.get("pass_count", 0)
            pass_s  = f"{pc}/4"
            asof_s  = r.get("asof", "") or "—"
            status  = _overnight_status_text(r)
            dt.add_row(ticker, name, price_s, bb_s, kbar_s, slope_s, mkt_s,
                       pass_s, asof_s, status, key=ticker or f"__r{id(r)}__")
        self._restore_table_state(dt, saved_cursor, saved_scroll)

    def _refresh_scanner_table(self, ld: dict) -> None:
        # Scanner tab: 全顯 WATCH (不過濾 teacher_only)
        items = list(self._watch)
        if self.search_term:
            items = [i for i in items if self._match_search(i)]
        self._refresh_watch_table("dt-scanner", items, ld, tab_id=TAB_SCANNER)

    # ── table cursor/scroll preservation ─────────────────────────────────────
    def _save_table_state(self, dt: DataTable) -> tuple[int, float]:
        """儲存 cursor row + scroll_y，回傳 (cursor_row, scroll_y)。"""
        try:
            cursor = dt.cursor_row
        except Exception:
            cursor = 0
        try:
            scroll_y = dt.scroll_y
        except Exception:
            scroll_y = 0.0
        return cursor, scroll_y

    def _restore_table_state(self, dt: DataTable, cursor: int, scroll_y: float) -> None:
        """還原 cursor row + scroll_y。"""
        try:
            if dt.row_count > 0 and cursor < dt.row_count:
                dt.move_cursor(row=cursor)
        except Exception:
            pass
        try:
            dt.scroll_to(y=scroll_y, animate=False)
        except Exception:
            pass

    def _refresh_all_tables(self) -> None:
        """立即重整所有 table (toggle 後呼叫)。"""
        with self._data_lock:
            ld = dict(self._live_data)
        self._refresh_held_table(ld)
        self._refresh_confirmed_table(ld)
        self._refresh_watching_table(ld)
        self._refresh_pinned_table(ld)
        self._refresh_overnight_table()
        self._refresh_scanner_table(ld)

    # ── actions ──────────────────────────────────────────────────────────────
    def action_toggle_teacher(self) -> None:
        self.teacher_only = not self.teacher_only
        self._refresh_all_tables()
        state = "ON" if self.teacher_only else "OFF"
        self.notify(f"[t:{state}] 老師 only 過濾 {'開啟' if self.teacher_only else '關閉'}")

    def action_toggle_failed(self) -> None:
        self.show_failed = not self.show_failed
        self._refresh_all_tables()
        state = "ON" if self.show_failed else "OFF"
        self.notify(f"[f:{state}] 顯示失敗 {'開啟' if self.show_failed else '關閉'}")

    def action_pin_add(self) -> None:
        self.push_screen(PinDialog("Pin 標的 (加入)"),
                         callback=self._on_pin_add_result)

    def _on_pin_add_result(self, ticker: str | None) -> None:
        if ticker and ticker.isdigit():
            self.pinned_tickers = self.pinned_tickers | frozenset([ticker])
            self.notify(f"📌 {ticker} 已加入 Pinned")

    def action_pin_remove(self) -> None:
        self.push_screen(PinDialog("Unpin 標的 (移除)"),
                         callback=self._on_pin_remove_result)

    def _on_pin_remove_result(self, ticker: str | None) -> None:
        if ticker and ticker in self.pinned_tickers:
            self.pinned_tickers = self.pinned_tickers - frozenset([ticker])
            self.notify(f"📌 {ticker} 已移除 Pinned")

    def action_search_open(self) -> None:
        bar = self.query_one("#search-bar", SearchBar)
        bar.add_class("visible")
        self.search_active = True
        inp = self.query_one("#search-input", Input)
        inp.value = ""
        inp.focus()

    def action_search_close(self) -> None:
        bar = self.query_one("#search-bar", SearchBar)
        bar.remove_class("visible")
        self.search_active = False
        self.search_term = ""

    def action_refresh_data(self) -> None:
        """強制觸發一輪資料刷新。"""
        if self._demo_mode and self._demo_client:
            pass  # demo mode: refresh_loop 已在跑
        self._fetch_all()
        self._update_all_tables()
        self.notify("🔄 資料已重整")

    def action_page_up(self) -> None:
        """當前 tab 上一頁：_current_page - 1、重繪 table。"""
        tab_id = self._get_active_tab_id()
        if not tab_id:
            return
        current = self._current_page.get(tab_id, 1)
        if current > 1:
            self._current_page[tab_id] = current - 1
            self._update_all_tables()
            self._update_status_bar()

    def action_page_down(self) -> None:
        """當前 tab 下一頁：_current_page + 1、重繪 table。"""
        tab_id = self._get_active_tab_id()
        if not tab_id:
            return
        current     = self._current_page.get(tab_id, 1)
        total_items = self._get_total_items_for_tab(tab_id)
        ps          = self._calc_page_size()
        total_pages = max(1, math.ceil(total_items / ps))
        if current < total_pages:
            self._current_page[tab_id] = current + 1
            self._update_all_tables()
            self._update_status_bar()

    def action_switch_tab_1(self) -> None:
        self._switch_to_tab(TAB_HELD)

    def action_switch_tab_2(self) -> None:
        self._switch_to_tab(TAB_OVERNIGHT)

    def action_switch_tab_3(self) -> None:
        self._switch_to_tab(TAB_CONFIRMED)

    def action_switch_tab_4(self) -> None:
        self._switch_to_tab(TAB_WATCHING)

    def action_switch_tab_5(self) -> None:
        self._switch_to_tab(TAB_PINNED)

    def action_switch_tab_6(self) -> None:
        self._switch_to_tab(TAB_SCANNER)

    def _switch_to_tab(self, tab_id: str) -> None:
        tabs = self.query_one("#main-tabs", TabbedContent)
        tabs.active = tab_id

    # ── search input events ──────────────────────────────────────────────────
    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input":
            term = event.value.strip()
            self.search_term = term
            self._update_all_tables()
            if term:
                self.notify(f"🔍 搜尋: {term}")
                # 跳到含有該 ticker 的第一個 tab (持倉 > 觀察 > Scanner)
                self._jump_to_search_result(term)
            else:
                self.action_search_close()

    def on_key(self, event) -> None:
        if self.search_active and event.key == "escape":
            self.action_search_close()
            event.stop()
        # Demo mode keys
        if self._demo_mode:
            if event.key == "space":
                self._demo_paused = not self._demo_paused
                self.notify("⏸ Demo paused" if self._demo_paused else "▶ Demo auto-cycle")
                event.stop()
            elif event.key == "left":
                self._demo_idx = (self._demo_idx - 1) % max(1, self._demo_total)
                self._apply_demo_scenario()
                event.stop()
            elif event.key == "right":
                self._demo_idx = (self._demo_idx + 1) % max(1, self._demo_total)
                self._apply_demo_scenario()
                event.stop()
            elif event.key == "home":
                self._demo_idx = 0
                self._apply_demo_scenario()
                event.stop()
            elif event.key == "end":
                self._demo_idx = max(0, self._demo_total - 1)
                self._apply_demo_scenario()
                event.stop()
            elif event.character and event.character in "123456789":
                target = int(event.character) - 1
                if target < self._demo_total:
                    self._demo_idx = target
                    self._apply_demo_scenario()
                    event.stop()
            elif event.key == "g":
                self._demo_goto_mode = True
                self._demo_goto_buf = ""
                event.stop()
            elif self._demo_goto_mode and event.character and event.character.isdigit():
                self._demo_goto_buf += event.character
                if len(self._demo_goto_buf) >= 2:
                    try:
                        target = int(self._demo_goto_buf) - 1
                        if 0 <= target < self._demo_total:
                            self._demo_idx = target
                            self._apply_demo_scenario()
                    except ValueError:
                        pass
                    self._demo_goto_mode = False
                    self._demo_goto_buf = ""
                event.stop()

    def _jump_to_search_result(self, term: str) -> None:
        """搜尋後自動跳到含該 ticker 的第一個 tab。"""
        term_lower = term.lower()
        def _matches(item: dict) -> bool:
            return (term_lower in str(item.get('ticker', '')).lower() or
                    term_lower in str(item.get('name', '')).lower())

        if any(_matches(i) for i in self._held):
            self._switch_to_tab(TAB_HELD)
        elif any(_matches(i) for i in self._watch):
            self._switch_to_tab(TAB_WATCHING)
        else:
            self._switch_to_tab(TAB_SCANNER)

    # ── Demo mode ─────────────────────────────────────────────────────────────
    def _apply_demo_scenario(self) -> None:
        """套用目前 demo scenario 到 mock client。"""
        if not self._demo_scenarios or not self._demo_client:
            return
        idx = self._demo_idx % self._demo_total
        sc  = self._demo_scenarios[idx]
        # scenario tuple: (name, phase, snaps, sort, min_pri, trigs [, age_override])
        name  = sc[0]
        snaps = sc[2] if len(sc) > 2 else {}
        trigs = sc[5] if len(sc) > 5 else {}
        age_ov= sc[6] if len(sc) > 6 else {}

        self._demo_client.scenario          = snaps
        self._demo_client.trigger_overrides = trigs

        # patch v1.check_trigger_inline to use mock overrides
        def _mock_check(ticker: str, tactic: str = '核心'):
            return trigs.get(ticker, ('none', ''))
        _v1.check_trigger_inline = _mock_check

        # record trigger fires
        now = datetime.now()
        for tk, (tkey, _r) in trigs.items():
            if tk not in age_ov:
                record_trigger_fire(tk, tkey, now)

        self.notify(f"[DEMO {idx+1}/{self._demo_total}] {name}", timeout=2)
        # force data fetch
        self._fetch_all()

    def _start_demo_cycle(self) -> None:
        """Demo auto-cycle 背景 thread。"""
        def _loop():
            while not self._quit:
                if not self._demo_paused:
                    self._demo_idx = (self._demo_idx + 1) % max(1, self._demo_total)
                    self._apply_demo_scenario()
                time.sleep(5.0)
        threading.Thread(target=_loop, daemon=True).start()

    # ── cleanup ───────────────────────────────────────────────────────────────
    def on_unmount(self) -> None:
        self._quit = True


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def _build_real_client():
    """建立真實 FubonClient + 連線探測。

    分步驟列印進度、讓 user 看清楚是 VPN 卡 / SDK init 卡 / probe 卡，
    避免「Textual 起來看到一片空白搞不清楚問題在哪」。
    """
    import time as _t
    t0 = _t.monotonic()

    print("[1/4] import FubonClient…", flush=True)
    try:
        from clients.fubon_client import FubonClient
    except Exception as e:
        print(f"  ❌ import 失敗: {e}", file=sys.stderr, flush=True)
        return None
    print(f"  ✅ {_t.monotonic()-t0:.1f}s", flush=True)

    t1 = _t.monotonic()
    print("[2/4] FubonClient() 建構 (讀 cred / 認證)…", flush=True)
    try:
        client = FubonClient()
    except Exception as e:
        print(f"  ❌ 建構失敗 (常見原因: cred 缺 / VPN 沒開): {e}", file=sys.stderr, flush=True)
        return None
    print(f"  ✅ {_t.monotonic()-t1:.1f}s", flush=True)

    t2 = _t.monotonic()
    print("[3/4] 探測連線 (2330 snap)…", flush=True)
    try:
        snap = client.get_realtime_snapshot("2330")
        if snap and snap.get("close"):
            print(f"  ✅ {_t.monotonic()-t2:.1f}s — 2330 close={snap.get('close')} vol={snap.get('total_volume')}",
                  flush=True)
        else:
            print(f"  ⚠️  {_t.monotonic()-t2:.1f}s — snap 回空 (盤前試撮無資料 / 連線異常)",
                  flush=True)
    except Exception as e:
        print(f"  ❌ probe 失敗 (VPN 阻擋? 認證過期?): {e}", file=sys.stderr, flush=True)
        # 不 return None — client 物件有效、後續可能恢復、讓 monitor 自己 retry
    print(f"[4/4] 啟動 Textual…  總計 {_t.monotonic()-t0:.1f}s", flush=True)
    return client


def main():
    p = argparse.ArgumentParser(
        description="Trading Monitor v2 — Textual TUI"
    )
    p.add_argument("--demo", action="store_true",
                   help="Demo 模式 (mock client + 36 scenarios)")
    p.add_argument("--interval", type=float, default=5.0,
                   help="Demo auto-cycle 秒 (預設 5)")
    args = p.parse_args()

    if args.demo:
        mock = MockClient()
        scenarios = _build_scenarios()
        app = MonitorApp(
            demo_mode=True,
            demo_client=mock,
            demo_scenarios=scenarios,
        )
        # 套用 scenario 0 後啟動
        if scenarios:
            sc = scenarios[0]
            mock.scenario          = sc[2] if len(sc) > 2 else {}
            mock.trigger_overrides = sc[5] if len(sc) > 5 else {}
            # patch v1 check
            def _mock_check(ticker: str, tactic: str = '核心'):
                return mock.trigger_overrides.get(ticker, ('none', ''))
            _v1.check_trigger_inline = _mock_check

        app._start_demo_cycle()
        app.run()
    else:
        client = _build_real_client()
        app = MonitorApp(client=client)
        app.run()


if __name__ == "__main__":
    main()
