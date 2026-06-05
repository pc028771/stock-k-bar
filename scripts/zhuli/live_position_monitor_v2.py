"""即時持倉 + Screener 監控 — Textual TUI v2.

Textual 版、平行於 v1 (Rich-only)、解決 UX 痛點:
- WATCH 太長看不到 footer → 分 5 個 Tab、各自獨立捲動
- 無法搜尋 → / 快速搜尋 + highlight
- Pin 標的不便 → a/u 鍵 InputDialog
- Section 視覺混淆 → CSS border + 顏色
- 鍵盤反應慢 → Textual binding < 10ms

架構:
  Tab: 持倉(HELD) / 可進場(Confirmed) / 觀察(Watching) / Pinned / Scanner(全顯)
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
import sys
import threading
import time
from datetime import date, datetime, timedelta
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
TAB_SCANNER   = "tab-scanner"

TAB_LABELS = {
    TAB_HELD:      "📊 持倉",
    TAB_CONFIRMED: "🎯 可進場",
    TAB_WATCHING:  "🔍 觀察",
    TAB_PINNED:    "📌 Pinned",
    TAB_SCANNER:   "📈 Scanner",
}

# ── Column specs ─────────────────────────────────────────────────────────────
# (key, label, width)
COLS_HELD = [
    ("ticker",  "代號",    6),
    ("name",    "股名",    8),
    ("cost",    "均",      7),
    ("gap",     "跳空",    7),
    ("price",   "現價(%)", 16),
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
        Binding("2",       "switch_tab_2",    "可進場", show=False),
        Binding("3",       "switch_tab_3",    "觀察", show=False),
        Binding("4",       "switch_tab_4",    "Pinned", show=False),
        Binding("5",       "switch_tab_5",    "Scanner", show=False),
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

    # ── compose ──────────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Header()
        yield StatusBar(id="status-bar")

        with TabbedContent(id="main-tabs"):
            with TabPane(TAB_LABELS[TAB_HELD], id=TAB_HELD,
                         classes="held-pane"):
                yield DataTable(id="dt-held", zebra_stripes=True,
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
        """切 tab 後自動 focus 新 tab 的 DataTable。"""
        self.call_after_refresh(self._focus_active_table)

    def _setup_tables(self) -> None:
        """初始化所有 DataTable 的 columns。"""
        for table_id, cols in [
            ("dt-held",      COLS_HELD),
            ("dt-confirmed", COLS_WATCH),
            ("dt-watching",  COLS_WATCH),
            ("dt-pinned",    COLS_HELD),
            ("dt-scanner",   COLS_WATCH),
        ]:
            dt: DataTable = self.query_one(f"#{table_id}", DataTable)
            for key, label, width in cols:
                # Trigger 欄 (width=0 or last col) 不限寬、自動延伸到畫面右
                if key == "trigger":
                    dt.add_column(label, key=key)
                else:
                    dt.add_column(label, key=key, width=width)

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

        all_items = self._held + self._watch + self._plan
        for item in all_items:
            tk = str(item.get('ticker', ''))
            if not tk:
                continue
            try:
                snap = client.get_realtime_snapshot(tk) or {}
                close_ = float(snap.get('close') or 0)
                open_  = float(snap.get('open')  or 0)
                vol_   = snap.get('total_volume')
                vol_ratio = compute_vol_ratio(tk, float(vol_) if vol_ else None)
                ma10   = load_ma10(tk)

                # trigger (demo: mock override)
                if self._demo_mode:
                    trig_key, trig_reason = _v1.check_trigger_inline(tk, item.get('tactic', '核心'))
                else:
                    trig_key, trig_reason = check_trigger_inline(tk, item.get('tactic', '核心'))

                record_trigger_fire(tk, trig_key)

                # P&L (held only)
                cost   = float(item.get('cost') or 0)
                shares = int(item.get('shares') or 0)
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
                    }
            except Exception:
                pass

    # ── tick (1s 更新 UI) ────────────────────────────────────────────────────
    def _tick(self) -> None:
        self._update_status_bar()
        self._update_all_tables()

    def _update_status_bar(self) -> None:
        now = datetime.now()
        regime_label, _ = _get_market_regime_chip()
        session_label, _ = _get_session_chip(now)
        teacher_tag = "[t:ON]" if self.teacher_only else "[t:OFF]"
        failed_tag  = "[f:ON]" if self.show_failed  else ""
        pinned_tag  = f"[pin:{len(self.pinned_tickers)}]" if self.pinned_tickers else ""
        mode_tag    = "[DEMO]" if self._demo_mode else ""
        bar = self.query_one("#status-bar", StatusBar)
        text = (f"{mode_tag} {regime_label} | {session_label} | "
                f"{teacher_tag} {failed_tag} {pinned_tag} | "
                f"{now.strftime('%H:%M:%S')}")
        bar.status_text = text

    # ── table refresh ─────────────────────────────────────────────────────────
    def _update_all_tables(self) -> None:
        with self._data_lock:
            ld = dict(self._live_data)

        self._refresh_held_table(ld)
        self._refresh_confirmed_table(ld)
        self._refresh_watching_table(ld)
        self._refresh_pinned_table(ld)
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
            trig  = self._fmt_trigger(d.get('trigger', 'none'), d.get('trig_reason', ''))
            cost  = item.get('cost', 0)
            prev_close = d.get('prev_close', 0)
            gap_str   = self._fmt_gap(open_, prev_close)
            price_str = self._fmt_price(close_, prev_close)
            row   = (tk, item.get('name', ''), f"{cost:.1f}" if cost else "—",
                     gap_str, price_str,
                     vol, pnl_str, dist_str, stat, trig)
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

    def _refresh_watch_table(self, table_id: str, items: list[dict], ld: dict) -> None:
        dt: DataTable = self.query_one(f"#{table_id}", DataTable)
        saved_cursor, saved_scroll = self._save_table_state(dt)
        if self.search_term:
            items = [i for i in items if self._match_search(i)]
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
                if '老師' in str(i.get('source', ''))]

    def _refresh_confirmed_table(self, ld: dict) -> None:
        # 可進場 = WATCH 中 classify → 'confirmed'
        items = self._filter_watch_items(self._watch)
        items = [i for i in items
                 if self._classify_watch(
                     i, ld.get(str(i.get('ticker', '')), {})) == 'confirmed']
        self._refresh_watch_table("dt-confirmed", items, ld)

    def _refresh_watching_table(self, ld: dict) -> None:
        items = self._filter_watch_items(self._watch)
        # show_failed → 顯示 excluded (破底/TC); 否則過濾掉
        if not self.show_failed:
            items = [i for i in items
                     if self._classify_watch(
                         i, ld.get(str(i.get('ticker', '')), {})) != 'excluded']
        self._refresh_watch_table("dt-watching", items, ld)

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
            trig  = self._fmt_trigger(d.get('trigger', 'none'), d.get('trig_reason', ''))
            cost  = item.get('cost', 0)
            prev_close = d.get('prev_close', 0)
            gap_str   = self._fmt_gap(open_, prev_close)
            price_str = self._fmt_price(close_, prev_close)
            row   = (tk, item.get('name', ''), f"{cost:.1f}" if cost else "—",
                     gap_str, price_str,
                     vol, pnl_str, dist_str, stat, trig)
            dt.add_row(*row, key=tk)
        self._restore_table_state(dt, saved_cursor, saved_scroll)

    def _refresh_scanner_table(self, ld: dict) -> None:
        # Scanner tab: 全顯 WATCH (不過濾 teacher_only)
        items = list(self._watch)
        if self.search_term:
            items = [i for i in items if self._match_search(i)]
        self._refresh_watch_table("dt-scanner", items, ld)

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

    def action_switch_tab_1(self) -> None:
        self._switch_to_tab(TAB_HELD)

    def action_switch_tab_2(self) -> None:
        self._switch_to_tab(TAB_CONFIRMED)

    def action_switch_tab_3(self) -> None:
        self._switch_to_tab(TAB_WATCHING)

    def action_switch_tab_4(self) -> None:
        self._switch_to_tab(TAB_PINNED)

    def action_switch_tab_5(self) -> None:
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
    """嘗試建立真實 FubonClient。"""
    try:
        from clients.fubon_client import FubonClient
        return FubonClient()
    except Exception as e:
        print(f"[警告] FubonClient 初始化失敗: {e}", file=sys.stderr)
        return None


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
