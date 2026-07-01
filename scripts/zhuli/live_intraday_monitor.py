#!/usr/bin/env python3
"""即時當沖監控 — Fubon WebSocket + REST 輪詢。

功能:
  1. 訂閱 WebSocket (aggregates) 取得即時報價 (HELD + WATCH + 老師8族群)
  2. 每 60s 輪詢 REST 5分K candles 偵測「第一根5分K大量黑K」
  3. 依照課程規則偵測當沖訊號：
       🔴 放空候選：昨漲停今開弱 + 第一根5分K大量黑K + 收破昨收
       🟢 做多候選：日線均線多頭排列 + 漲幅<5%
       🚨 HELD警報：持倉破昨收/破停損/拉高/大量黑K
  4. 警報原子寫入 /tmp/zhuli_cache/intraday_alerts.json
  5. 終端機每30s列印摘要

⚠️ 規則來源 (唯一): docs/主力大課程/全方位培訓筆記/2026-06-29_復盤分K操作策略課_解讀.md
禁止自創規則。

WebSocket 技術說明:
  fubon_neo SDK ws.connect() 在 SDK 內部啟動背景 thread。
  為避免阻塞主程式、此腳本在獨立 daemon thread 呼叫 subscribe_quotes()。
  on_message callback 由 SDK 的 WS 執行緒呼叫、透過 threading.Lock 更新共用狀態。

執行:
  python3 scripts/zhuli/live_intraday_monitor.py
  python3 scripts/zhuli/live_intraday_monitor.py --demo   # 不連 WS、用 REST snapshot 輪詢
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

# ── path setup ──────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.db import get_conn, MAIN_DB
from zhuli.positions import HELD, WATCH

# ── 設定 ────────────────────────────────────────────────────────────────────
CACHE_DIR = Path("/tmp/zhuli_cache")
CACHE_DIR.mkdir(exist_ok=True)
ALERT_FILE = CACHE_DIR / "intraday_alerts.json"

# 5日均量倍數門檻：第一根5分K被視為「大量」時
LARGE_VOL_RATIO = 0.3   # 5分K成交量 >= 5日日均量 * 0.3 = 大量
# 昨漲停判斷門檻 (%)
LIMIT_UP_THRESHOLD = 9.5
# 開弱判斷：open/prev_close -1 <= 此值表示「開低或開平」
WEAK_OPEN_PCT = 0.5     # ≤ +0.5% 為開弱
# 做多漲幅門檻：前5分鐘漲幅 > 此值 → 一票否決
LONG_MAX_CHG = 5.0      # %

# 市場時間 (台灣標準時間、本機為 Asia/Taipei)
MARKET_OPEN_HM  = (9, 0)
MARKET_CLOSE_HM = (13, 30)

# WS 訂閱批次大小 (富邦限制: 200檔/連線、最多5連線)
WS_BATCH_SIZE = 180     # 保留緩衝

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("intraday_monitor")


# ── Universe ─────────────────────────────────────────────────────────────────

def _load_teacher_universe() -> set[str]:
    """從 teacher_sector_tickers.json 載入老師8族群標的。"""
    path = _REPO / "docs/主力大課程/teacher_sector_tickers.json"
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        tickers: set[str] = set()
        for v in d.values():
            if isinstance(v, list):
                tickers.update(str(t) for t in v)
        return tickers
    except Exception as e:
        log.warning("無法載入 teacher_sector_tickers.json: %s", e)
        return set()


def build_universe() -> list[str]:
    """合併 HELD + WATCH + 老師族群 → 去重排序後的 ticker 清單。"""
    s: set[str] = set()
    for h in HELD:
        s.add(str(h["ticker"]))
    for w in WATCH:
        s.add(str(w["ticker"]))
    s.update(_load_teacher_universe())
    return sorted(s)


# ── DB 靜態資料載入 ──────────────────────────────────────────────────────────

def load_static_for_ticker(ticker: str) -> dict:
    """從 DB 載入單一 ticker 靜態資料 (昨收、均線、5日均量)。

    回傳:
        prev_close: float | None
        prev_limit_up: bool
        ma5, ma10, ma20, ma60: float | None
        avg5d_vol: float | None   (張)
    """
    result: dict[str, Any] = {
        "prev_close": None,
        "prev_limit_up": False,
        "ma5": None, "ma10": None, "ma20": None, "ma60": None,
        "avg5d_vol": None,
    }
    today = date.today().isoformat()
    try:
        con = get_conn(MAIN_DB, timeout=5)
        # 最近兩個交易日 (排除今天)
        rows = con.execute(
            "SELECT close, ma5, ma10, ma20, ma60 FROM standard_daily_bar "
            "WHERE ticker=? AND trade_date < ? "
            "ORDER BY trade_date DESC LIMIT 2",
            (ticker, today)
        ).fetchall()
        # 5日均量
        vol_rows = con.execute(
            "SELECT volume FROM standard_daily_bar "
            "WHERE ticker=? AND trade_date < ? "
            "ORDER BY trade_date DESC LIMIT 5",
            (ticker, today)
        ).fetchall()
        con.close()

        if rows:
            r0 = rows[0]
            result["prev_close"] = float(r0[0]) if r0[0] else None
            result["ma5"]  = float(r0[1]) if r0[1] else None
            result["ma10"] = float(r0[2]) if r0[2] else None
            result["ma20"] = float(r0[3]) if r0[3] else None
            result["ma60"] = float(r0[4]) if r0[4] else None

            # 昨漲停 = 昨收 vs 前日收 漲幅 >= 9.5%
            if len(rows) >= 2:
                r1 = rows[1]
                prev2_close = float(r1[0]) if r1[0] else 0.0
                if prev2_close > 0 and result["prev_close"]:
                    pct = (result["prev_close"] / prev2_close - 1) * 100
                    result["prev_limit_up"] = pct >= LIMIT_UP_THRESHOLD

        if vol_rows:
            vols = [r[0] / 1000.0 for r in vol_rows if r[0]]
            if vols:
                result["avg5d_vol"] = sum(vols) / len(vols)

    except Exception as e:
        log.debug("load_static_for_ticker(%s) 失敗: %s", ticker, e)

    return result


def load_held_meta() -> dict[str, dict]:
    """從 positions.HELD 載入 cost/shares/stop，方便 P&L 計算。"""
    meta: dict[str, dict] = {}
    for h in HELD:
        tk = str(h["ticker"])
        meta[tk] = {
            "name": h.get("name", ""),
            "cost": float(h.get("cost", 0)),
            "shares": int(h.get("shares", 0)),
            "stop": float(h.get("stop", 0)),
        }
    return meta


# ── 共用狀態 (thread-safe) ───────────────────────────────────────────────────

class TickerState:
    """每個 ticker 的即時狀態 + 靜態資料 + 訊號。"""
    __slots__ = (
        "ticker", "tag",
        # 靜態 (DB)
        "prev_close", "prev_limit_up",
        "ma5", "ma10", "ma20", "ma60",
        "avg5d_vol",
        # 即時 (WS / REST)
        "last_price", "open_price", "change_rate", "total_volume",
        "last_ts",
        # 5分K (REST 輪詢)
        "first_5m_open", "first_5m_close", "first_5m_low", "first_5m_vol",
        "first_5m_loaded",
        # 訊號 (每輪偵測)
        "signals",
    )

    def __init__(self, ticker: str, tag: str, static: dict) -> None:
        self.ticker = ticker
        self.tag = tag  # "HELD" / "WATCH" / "universe"
        self.prev_close     = static["prev_close"]
        self.prev_limit_up  = static["prev_limit_up"]
        self.ma5   = static["ma5"]
        self.ma10  = static["ma10"]
        self.ma20  = static["ma20"]
        self.ma60  = static["ma60"]
        self.avg5d_vol = static["avg5d_vol"]
        # 即時
        self.last_price: float | None = None
        self.open_price: float | None = None
        self.change_rate: float | None = None
        self.total_volume: int | None = None
        self.last_ts: float = 0.0
        # 5分K
        self.first_5m_open:   float | None = None
        self.first_5m_close:  float | None = None
        self.first_5m_low:    float | None = None
        self.first_5m_vol:    float | None = None
        self.first_5m_loaded: bool = False
        # 訊號
        self.signals: list[str] = []


class MonitorState:
    """全域共用狀態 (lock 保護)。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: dict[str, TickerState] = {}
        self._alerts: list[dict] = []
        self._ws_msg_count: int = 0
        self._ws_connected: bool = False

    # ── 狀態存取 ────────────────────────────────────────────────────────────

    def init_ticker(self, ticker: str, tag: str, static: dict) -> None:
        with self._lock:
            if ticker not in self._states:
                self._states[ticker] = TickerState(ticker, tag, static)

    def on_ws_message(self, msg: str) -> None:
        """WS on_message callback — 在 SDK 背景 thread 呼叫、需 lock。"""
        try:
            data = json.loads(msg)
        except Exception:
            return
        # aggregates channel: {"event":"...", "data":{...}} 或直接 {"symbol":..., ...}
        if isinstance(data, list):
            for item in data:
                self._process_ws_item(item)
        elif isinstance(data, dict):
            self._process_ws_item(data)

    def _process_ws_item(self, item: dict) -> None:
        """解析 WS 訊息 item。

        實測 Fubon WS 格式 (trades/aggregates channel):
            {"event": "data", "data": {"symbol": "3481", "price": 59.1,
             "volume": 532557, "isOpen": false, "isTrial": false, ...}}
        heartbeat / authenticated / subscribed → event != "data" → 忽略。
        aggregates 可能額外含 openPrice / closePrice / tradeVolume 欄位。
        """
        # 處理巢狀格式 {event, data} — trades channel 實測格式
        event = item.get("event")
        if event is not None:
            if event != "data":
                return  # heartbeat / subscribed / authenticated → 忽略
            payload = item.get("data")
            if not isinstance(payload, dict):
                return
        else:
            # 有些 aggregates channel 直接傳 flat dict
            payload = item

        sym = str(payload.get("symbol", payload.get("code", ""))).strip()
        if not sym:
            return

        # 試撮不算真實成交 (feedback_premarket_match_fomo_trap 教訓)
        if payload.get("isTrial"):
            return

        # price 欄位: trades="price", aggregates 可能是 closePrice/lastPrice
        price = _sf(
            payload.get("price")
            or payload.get("closePrice") or payload.get("close_price")
            or payload.get("lastPrice") or payload.get("last_price")
        )
        if price is None:
            return

        # open: isOpen 旗標時 price = 開盤價
        open_p = None
        if payload.get("isOpen"):
            open_p = price
        elif payload.get("openPrice") or payload.get("open"):
            open_p = _sf(payload.get("openPrice") or payload.get("open"))

        # change_rate: aggregates channel 可能有
        chg_r = _sf(
            payload.get("changePercent") or payload.get("change_percent")
            or payload.get("changeRate")
        )

        # volume (股數)
        vol_raw = _si(
            payload.get("tradeVolume") or payload.get("trade_volume")
            or payload.get("volume")
        )

        with self._lock:
            self._ws_msg_count += 1
            self._ws_connected = True
            if sym in self._states:
                st = self._states[sym]
                st.last_price = price
                if open_p is not None:
                    st.open_price = open_p
                if chg_r is not None:
                    st.change_rate = chg_r
                if vol_raw is not None:
                    # 股數 → 張 (÷1000)、aggregates 累積股數通常 > 10000
                    st.total_volume = vol_raw // 1000 if vol_raw > 10000 else vol_raw
                st.last_ts = time.monotonic()

    def update_from_snapshot(self, snap_map: dict) -> None:
        """REST snapshot 更新 (WS fallback)。"""
        with self._lock:
            for sym, snap in snap_map.items():
                if sym in self._states:
                    st = self._states[sym]
                    if snap.get("close"):
                        st.last_price  = float(snap["close"])
                        st.change_rate = float(snap.get("change_rate") or 0)
                    if snap.get("open"):
                        st.open_price  = float(snap["open"])
                    if snap.get("total_volume"):
                        st.total_volume = int(snap["total_volume"])
                    st.last_ts = time.monotonic()

    def update_5m_candle(self, ticker: str, candles: list[dict]) -> None:
        """更新第一根5分K資料。candles 按時間升冪排列。"""
        if not candles:
            return
        c0 = candles[0]  # 第一根 (09:00-09:05)
        with self._lock:
            if ticker in self._states:
                st = self._states[ticker]
                st.first_5m_open  = _sf(c0.get("open"))
                st.first_5m_close = _sf(c0.get("close"))
                st.first_5m_low   = _sf(c0.get("low"))
                # volume: Fubon intraday.candles 的 volume 已是「張」
                # (實測 2026-07-01: 2330 全日5分K加總 ~12090 = 張、非股數)。
                # 與 avg5d_vol(張) 同單位、不可再 /1000。
                st.first_5m_vol   = _sf(c0.get("volume"))
                st.first_5m_loaded = True

    def add_alert(self, alert: dict) -> None:
        with self._lock:
            self._alerts.append(alert)

    def get_snapshot(self) -> tuple[dict[str, TickerState], list[dict], int, bool]:
        """回傳當前快照 (複製、避免 hold lock 太久)。"""
        with self._lock:
            states_copy = dict(self._states)
            alerts_copy = list(self._alerts)
            n = self._ws_msg_count
            connected = self._ws_connected
        return states_copy, alerts_copy, n, connected


# ── 訊號偵測 (純課程規則) ───────────────────────────────────────────────────

def detect_signals(
    st: TickerState,
    held_meta: dict[str, dict],
) -> list[dict]:
    """
    只使用 2026-06-29 課程明確說明的規則。
    回傳 list[{"type": str, "ticker": str, "msg": str, "ts": str}]
    """
    signals: list[dict] = []
    ticker = st.ticker
    now_str = datetime.now().strftime("%H:%M:%S")
    price = st.last_price
    if price is None or price <= 0:
        return signals

    prev_close = st.prev_close or 0.0
    open_price = st.open_price or 0.0
    # change_rate: trades channel 不帶漲跌幅、由 price/prev_close 自算為主
    # (feed 提供的 change_rate 僅供 REST fallback、自算更可靠且不受 WS 覆寫影響)
    if prev_close > 0:
        change_rate = (price / prev_close - 1) * 100
    else:
        change_rate = st.change_rate or 0.0

    # ── 🚨 HELD 警報 ────────────────────────────────────────────────────────
    if ticker in held_meta:
        meta = held_meta[ticker]
        stop = meta["stop"]
        name = meta["name"]

        # 破停損
        if stop > 0 and price < stop:
            signals.append({
                "type": "HELD_BROKE_STOP",
                "ticker": ticker,
                "msg": f"🚨 [{name}] 破停損 {price:.1f} < 止損 {stop:.1f}",
                "ts": now_str,
                "priority": 1,
            })

        # 破昨收 (課程：收破昨日收盤價 = 出貨訊號)
        if prev_close > 0 and price < prev_close:
            signals.append({
                "type": "HELD_BROKE_PREV_CLOSE",
                "ticker": ticker,
                "msg": (f"⚠️  [{name}] 現價 {price:.1f} 破昨收 {prev_close:.1f} "
                        f"({(price/prev_close-1)*100:+.2f}%) — 課程: 收破昨收=出貨訊號"),
                "ts": now_str,
                "priority": 2,
            })

        # 拉高 ≥ 5% (賣點提示：課程「拉高出貨」)
        if change_rate >= 5.0:
            signals.append({
                "type": "HELD_PULL_HIGH",
                "ticker": ticker,
                "msg": (f"📈 [{name}] 拉高 {change_rate:+.2f}% "
                        f"({price:.1f}) — 課程：拉高是賣點、考慮鎖利"),
                "ts": now_str,
                "priority": 3,
            })

        # 第一根5分K 大量黑K (HELD持倉警報)
        if st.first_5m_loaded:
            if _is_large_vol_black_k(st):
                signals.append({
                    "type": "HELD_FIRST_5M_BLACK",
                    "ticker": ticker,
                    "msg": (f"🔴 [{name}] 第一根5分K 大量黑K "
                            f"(開={st.first_5m_open:.1f} 收={st.first_5m_close:.1f} "
                            f"量={st.first_5m_vol:.0f}張 vs 5日均量={st.avg5d_vol:.0f}張) "
                            f"— 課程：大量黑K=主力倒貨訊號"),
                    "ts": now_str,
                    "priority": 2,
                })

    # ── 🔴 放空候選 (純當沖、非持倉操作) ───────────────────────────────────
    # 條件 (課程 §2.1 / §2.2 / §5.3):
    #   1. 昨漲停 (≥9.5%)
    #   2. 今開弱 (開低 or 開平, ≤ +0.5%)
    #   3. 第一根5分K 大量黑K
    #   4. 收破昨收
    #   5. 標示「等第三根黑K確認 (50/50)」
    if st.prev_limit_up and ticker not in held_meta:
        # 開弱
        weak_open = (open_price > 0 and prev_close > 0 and
                     (open_price / prev_close - 1) * 100 <= WEAK_OPEN_PCT)
        # 收破昨收
        broke_prev_close = prev_close > 0 and price < prev_close
        # 第一根5分K 大量黑K
        has_large_black = st.first_5m_loaded and _is_large_vol_black_k(st)

        # 雙錨停損 (做空 cover stop): min(今開, 昨收, 第一根5分K高)
        # 課程：「雙錨停損 = 開盤價 / 昨收 / 第一根5分K低、取最高」是做多的。
        # 做空的 cover stop = 第一根5分K的高點
        cover_stop = st.first_5m_open if st.first_5m_open else open_price

        if weak_open:
            conds = []
            if broke_prev_close:
                conds.append("破昨收")
            if has_large_black:
                conds.append("第一根大量黑K")
            if len(conds) >= 1:
                open_pct = (open_price / prev_close - 1) * 100 if prev_close > 0 else 0
                signals.append({
                    "type": "SHORT_SETUP",
                    "ticker": ticker,
                    "msg": (
                        f"🔴 [{ticker}] 放空候選 ({'+'.join(conds)}) | "
                        f"昨漲停→今開{open_pct:+.1f}%({open_price:.1f}) "
                        f"現價{price:.1f} 昨收{prev_close:.1f} | "
                        f"⚠️  課程: 不搶第一根、等第三根黑K確認(50/50才大增) | "
                        f"空單 cover stop 參考 {cover_stop:.1f} (第一根高點附近)"
                    ),
                    "ts": now_str,
                    "priority": 2,
                })

    # ── 🟢 做多候選 (日線均線多頭排列) ────────────────────────────────────
    # 條件 (課程 §1.1):
    #   1. 日線均線多頭排列: 現價 > MA5 > MA10 > MA20 > MA60 (季線)
    #   2. 漲幅 < 5% (≤ 5%)
    #   3. 前5分鐘漲幅 > 5% → 一票否決 (CLAUDE.md 紀律 §短線進場三鐵)
    # 注意: 課程主判據是5分K均線順向、此處用日線MA多頭排列近似、標示「近似」
    if (ticker not in held_meta              # 持倉另外看、不重複
        and st.ma5 and st.ma10 and st.ma20 and st.ma60
        and price > 0):

        ma_bull = (price > st.ma5 > st.ma10 > st.ma20 > st.ma60)

        # 前5分鐘漲幅近似：開盤到現在漲幅
        open_chg_pct = ((price / open_price - 1) * 100) if open_price > 0 else 0.0
        first_5m_too_hot = open_chg_pct > 5.0  # 一票否決

        if ma_bull and not first_5m_too_hot and change_rate < LONG_MAX_CHG:
            # 雙錨停損 (課程：取開盤/昨收/第一根5分K低 最高者)
            anchors = [a for a in [open_price, prev_close, st.first_5m_low] if a and a > 0]
            dual_anchor = max(anchors) if anchors else open_price
            signals.append({
                "type": "LONG_SETUP",
                "ticker": ticker,
                "msg": (
                    f"🟢 [{ticker}] 做多候選 | "
                    f"現={price:.1f} MA5={st.ma5:.1f} MA10={st.ma10:.1f} "
                    f"MA20={st.ma20:.1f} MA60={st.ma60:.1f} "
                    f"漲{change_rate:+.2f}% | "
                    f"雙錨stop={dual_anchor:.1f} "
                    f"(開{open_price:.1f}/昨收{prev_close:.1f}/5mK低{st.first_5m_low or '—'}) | "
                    f"⚠️  日線MA近似、務必肉眼確認5分K均線順向未發散"
                ),
                "ts": now_str,
                "priority": 3,
            })

    return signals


def _is_large_vol_black_k(st: TickerState) -> bool:
    """第一根5分K 是否為「大量黑K」。
    條件: close < open (黑K) + 量 >= avg5d_vol * LARGE_VOL_RATIO
    """
    if not st.first_5m_loaded:
        return False
    o = st.first_5m_open
    c = st.first_5m_close
    v = st.first_5m_vol
    avg = st.avg5d_vol
    if o is None or c is None or v is None:
        return False
    is_black = c < o   # 收 < 開 = 黑K
    if avg and avg > 0:
        is_large = v >= avg * LARGE_VOL_RATIO
    else:
        is_large = True  # 無均量資料 → 保守判定為大量 (避免漏警)
    return is_black and is_large


# ── Fubon Client 取得 ────────────────────────────────────────────────────────

_fc_lock = threading.Lock()
_fc = None


def get_fubon_client():
    global _fc
    with _fc_lock:
        if _fc is None:
            from common.clients.fubon_client import FubonClient
            _fc = FubonClient()
        return _fc


# ── WebSocket 訂閱 (背景 thread) ─────────────────────────────────────────────

def _start_ws_thread(universe: list[str], state: MonitorState) -> threading.Thread:
    """在背景 daemon thread 訂閱 WebSocket。

    批次處理: 每 WS_BATCH_SIZE 個 symbol 一個連線 (富邦 200/連線限制)。
    若 subscribe_quotes 失敗或阻塞 → thread 結束、主程式 fallback 到 REST snapshot。
    """
    def _run() -> None:
        try:
            fc = get_fubon_client()
            # ⚠️ fubon_client.subscribe_quotes 內部用「單一 SDK websocket 單例」、
            # 每次呼叫都 ws.connect() 同一個連線 → 多批次會觸發
            # "socket is already opened" (實測 2026-07-01)。故一次全訂閱、
            # 超過 200/連線上限只警告 (同 live_position_monitor.py 策略、接受部分漏訂)。
            if len(universe) > 200:
                log.warning("訂閱 %d 檔 > 200/連線上限、SDK 單例僅 1 連線、"
                            "可能漏訂閱部分 (依賴 REST snapshot 補)", len(universe))
            # ⚠️ Fubon Speed mode 不支援 aggregates/candles channel、只能用 trades
            # (實測 2026-07-01: aggregates → "Speed mode doesn't support aggregates
            #  channel"、WS 收 0 tick。參考 live_position_monitor.py:869)
            log.info("WS 訂閱 %d 檔 (trades channel)...", len(universe))
            ws = fc.subscribe_quotes(
                symbols=universe,
                on_message=state.on_ws_message,
                channel="trades",
            )
            ws_clients = [ws] if ws else []
            if ws:
                log.info("WS 訂閱完成 (%d 檔)", len(universe))
            else:
                log.warning("WS 訂閱回傳 None、fallback REST snapshot")

            log.info("WebSocket %d 連線已建立、等待 tick ...", len(ws_clients))
            # 保持 thread 存活 (WS 在 SDK 背景 thread 跑)
            while True:
                time.sleep(60)

        except Exception as e:
            log.error("WS 背景 thread 例外: %s", e)
            log.warning("WS 失敗、主程式將 fallback 到 REST snapshot 輪詢")

    t = threading.Thread(target=_run, name="ws-subscribe", daemon=True)
    t.start()
    return t


# ── 5分K 輪詢 (REST) ─────────────────────────────────────────────────────────

def poll_5m_candles(tickers: list[str], state: MonitorState) -> None:
    """輪詢所有 ticker 的今日5分K candles、更新 state。
    每次呼叫、逐一 REST 查詢 (批次、避免單次打爆 rate limit)。
    只取第一根 (09:00-09:05)。
    """
    try:
        fc = get_fubon_client()
        fc._ensure_connected()
        reststock = fc._reststock
    except Exception as e:
        log.warning("poll_5m_candles: 無法取得 FubonClient: %s", e)
        return

    # 取今日5分K (批次逐一、小 sleep 避免 rate limit)
    for ticker in tickers:
        try:
            resp = reststock.intraday.candles(symbol=ticker, timeframe="5")
            rows = _extract_data_simple(resp)
            if rows:
                # 按時間排序、取第一根
                rows_sorted = sorted(rows, key=lambda r: str(r.get("date", "")))
                state.update_5m_candle(ticker, rows_sorted)
        except Exception as e:
            log.debug("poll_5m_candles(%s) 失敗: %s", ticker, e)
        time.sleep(0.05)  # 50ms 間隔


def _extract_data_simple(resp) -> list[dict]:
    """從 SDK response 抽 list[dict]。"""
    if resp is None:
        return []
    if hasattr(resp, "data") and resp.data is not None:
        data = resp.data
    elif isinstance(resp, dict) and "data" in resp:
        data = resp["data"]
    elif isinstance(resp, list):
        data = resp
    else:
        data = [resp]
    if not data:
        return []
    out = []
    for item in data:
        if isinstance(item, dict):
            out.append(item)
        else:
            try:
                out.append({k: v for k, v in vars(item).items() if not k.startswith("_")})
            except Exception:
                out.append({})
    return out


# ── 輸出 ─────────────────────────────────────────────────────────────────────

def write_alerts(alerts: list[dict], extra: dict | None = None) -> None:
    """原子寫入警報到 /tmp/zhuli_cache/intraday_alerts.json。"""
    payload = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "alert_count": len(alerts),
        "alerts": sorted(alerts, key=lambda x: (x.get("priority", 9), x.get("ts", ""))),
        **(extra or {}),
    }
    tmp = str(ALERT_FILE) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, str(ALERT_FILE))


def print_summary(
    states: dict[str, TickerState],
    alerts: list[dict],
    ws_msg_count: int,
    ws_connected: bool,
    held_meta: dict[str, dict],
    cycle: int,
) -> None:
    """終端機摘要輸出。"""
    now = datetime.now().strftime("%H:%M:%S")
    print(f"\n{'─'*70}")
    print(f"  📊 當沖監控 | {now} | 第 {cycle} 輪 | "
          f"WS {'🟢' if ws_connected else '⚪️'} {ws_msg_count} 則 | "
          f"監控 {len(states)} 檔")

    # HELD 狀態
    print(f"\n  【持倉快照】")
    for tk, meta in held_meta.items():
        st = states.get(tk)
        if not st:
            continue
        price = st.last_price or 0
        prev  = st.prev_close or 0
        stop  = meta["stop"]
        chg   = (price / prev - 1) * 100 if prev > 0 else 0
        broke_stop = price > 0 and stop > 0 and price < stop
        broke_prev = price > 0 and prev > 0 and price < prev
        flag = " 🚨停損" if broke_stop else (" ⚠️昨收" if broke_prev else "")
        print(f"    {tk} {meta['name']:6s}  "
              f"現={price:>7.1f}  昨={prev:>7.1f}  漲={chg:+5.2f}%  "
              f"停={stop:>7.1f}{flag}")

    # 訊號
    if alerts:
        print(f"\n  【訊號 ({len(alerts)})】")
        # 優先度排序、只印前 20
        for a in sorted(alerts, key=lambda x: x.get("priority", 9))[:20]:
            print(f"    [{a['ts']}] {a['msg']}")
    else:
        print(f"\n  【訊號】暫無")

    print(f"\n  警報已寫入: {ALERT_FILE}")


# ── 市場時間判斷 ─────────────────────────────────────────────────────────────

def in_market_hours() -> bool:
    lt = time.localtime()
    if lt.tm_wday >= 5:   # 週六、日
        return False
    hm = (lt.tm_hour, lt.tm_min)
    return MARKET_OPEN_HM <= hm <= MARKET_CLOSE_HM


def after_market() -> bool:
    lt = time.localtime()
    if lt.tm_wday >= 5:
        return False
    return (lt.tm_hour, lt.tm_min) > MARKET_CLOSE_HM


# ── 型別工具 ─────────────────────────────────────────────────────────────────

def _sf(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _si(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ── 主程式 ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="即時當沖監控")
    parser.add_argument("--demo", action="store_true",
                        help="Demo 模式：不連 WS、只用 REST snapshot 輪詢")
    parser.add_argument("--universe-only", action="store_true",
                        help="只監控老師族群 (不含 HELD/WATCH)")
    parser.add_argument("--candle-interval", type=int, default=60,
                        help="5分K REST 輪詢間隔 (秒, 預設60)")
    parser.add_argument("--signal-interval", type=int, default=30,
                        help="訊號偵測 + 輸出間隔 (秒, 預設30)")
    args = parser.parse_args()

    log.info("=== 當沖監控啟動 ===")
    log.info("模式: %s", "Demo (REST only)" if args.demo else "Live (WS + REST)")

    # ── 1. 建立 universe ────────────────────────────────────────────────────
    universe = build_universe()
    log.info("Universe: %d 檔", len(universe))

    # ── 2. 標記 HELD / WATCH ────────────────────────────────────────────────
    held_set  = {str(h["ticker"]) for h in HELD}
    watch_set = {str(w["ticker"]) for w in WATCH}
    held_meta = load_held_meta()

    # ── 3. 載入靜態資料 ─────────────────────────────────────────────────────
    log.info("載入靜態資料 (prev_close / MA / 均量) ...")
    state = MonitorState()
    for tk in universe:
        tag = "HELD" if tk in held_set else ("WATCH" if tk in watch_set else "universe")
        static = load_static_for_ticker(tk)
        state.init_ticker(tk, tag, static)
    log.info("靜態資料載入完成 (prev_close 有資料: %d 檔)",
             sum(1 for tk in universe
                 if state._states[tk].prev_close is not None))

    # ── 4. 啟動 WS (非 Demo) ────────────────────────────────────────────────
    ws_thread = None
    if not args.demo:
        ws_thread = _start_ws_thread(universe, state)
        log.info("WS 訂閱 thread 已啟動 (daemon)、等候 tick ...")
        time.sleep(3)  # 給 WS 連線時間

    # ── 4b. REST warm (一次) ────────────────────────────────────────────────
    # trades channel 不帶 open、且盤中啟動會錯過 isOpen tick → 先用 REST snapshot
    # warm 一次補齊 open/price (WS 之後只覆寫 last_price)。
    if not args.demo and in_market_hours():
        try:
            fc = get_fubon_client()
            warm_map = fc.get_snapshot_quotes_map(markets=("TSE", "OTC"))
            state.update_from_snapshot(warm_map)
            log.info("REST warm 完成 (%d 檔快照、補 open/price)", len(warm_map))
        except Exception as e:
            log.warning("REST warm 失敗: %s", e)

    # ── 5. 主循環 ───────────────────────────────────────────────────────────
    cycle = 0
    last_candle_poll = 0.0
    last_signal_check = 0.0

    log.info("進入主循環 (每 %ds 偵測訊號、每 %ds 輪詢5分K)",
             args.signal_interval, args.candle_interval)

    # 盤前或盤後
    if not in_market_hours():
        log.info("目前非盤中時間。等待盤中或 Demo 模式輸出。")

    try:
        while True:
            now_ts = time.monotonic()
            market_live = in_market_hours()

            # ── REST snapshot fallback (Demo 模式 或 WS 靜止 > 60s) ────────
            if args.demo or (not state._ws_connected and market_live):
                try:
                    fc = get_fubon_client()
                    snap_map = fc.get_snapshot_quotes_map(markets=("TSE", "OTC"))
                    state.update_from_snapshot(snap_map)
                    log.debug("REST snapshot 更新 %d 檔", len(snap_map))
                except Exception as e:
                    log.warning("REST snapshot 失敗: %s", e)

            # ── 5分K 輪詢 ───────────────────────────────────────────────────
            if market_live and now_ts - last_candle_poll >= args.candle_interval:
                log.info("輪詢5分K candles (%d 檔)...", len(universe))
                poll_5m_candles(universe, state)
                last_candle_poll = now_ts

            # ── 訊號偵測 + 輸出 ─────────────────────────────────────────────
            if now_ts - last_signal_check >= args.signal_interval:
                cycle += 1
                cur_states, _, ws_count, ws_conn = state.get_snapshot()

                all_signals: list[dict] = []
                for tk, st in cur_states.items():
                    sigs = detect_signals(st, held_meta)
                    all_signals.extend(sigs)

                # 去重 (同 type+ticker 只保最新)
                seen_keys: set[str] = set()
                deduped: list[dict] = []
                for sig in sorted(all_signals, key=lambda x: x.get("ts", "")):
                    k = f"{sig['type']}:{sig['ticker']}"
                    if k not in seen_keys:
                        seen_keys.add(k)
                        deduped.append(sig)

                write_alerts(deduped, extra={
                    "universe_count": len(universe),
                    "ws_connected": ws_conn,
                    "ws_msg_count": ws_count,
                    "market_live": market_live,
                })
                print_summary(cur_states, deduped, ws_count, ws_conn, held_meta, cycle)
                last_signal_check = now_ts

            # ── 盤後 auto-idle ───────────────────────────────────────────────
            if after_market():
                log.info("盤後 (13:30 後)、進入 idle 模式 (10min 輪詢)")
                time.sleep(600)
            elif not market_live:
                log.debug("非盤中、等待 60s ...")
                time.sleep(60)
            else:
                time.sleep(5)

    except KeyboardInterrupt:
        log.info("使用者中斷、結束監控")


if __name__ == "__main__":
    main()
