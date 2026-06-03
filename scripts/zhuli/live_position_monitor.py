"""即時持倉 + 開盤進場 screener (整合版 v3).

兩階段:
- Phase 1 (9:00-9:25): 開盤 entry screening、判主候選 / 備案
- Phase 2 (9:25 後): 已持倉 P&L + 停損監控

用法:
    python scripts/zhuli/live_position_monitor.py
    python scripts/zhuli/live_position_monitor.py --sort status
    python scripts/zhuli/live_position_monitor.py --sort priority
    python scripts/zhuli/live_position_monitor.py --sort risk
    python scripts/zhuli/live_position_monitor.py --sort trigger
    python scripts/zhuli/live_position_monitor.py --sort pnl
    python scripts/zhuli/live_position_monitor.py --sort sector

編輯下方:
- HELD: 已持倉部位 (Phase 2 監控)
- PLAN_PRIMARY: 鎖定的主候選 (Phase 1 開盤評估)
- PLAN_BACKUP: 備案 (主候選被 skip 時遞補)
- WATCH: 監控但已 skip 的標的

特性:
- dict-based 資料結構（兼容舊 tuple 格式、自動 convert）
- 9:00-9:25 自動 entry screening、紅線 #9 (前 5 分 >5% skip) 內建
- 9:25+ 切到持倉 P&L 監控
- 停損突破 macOS 通知
- 30s 更新、彩色 console
- priority 摘要 panel (⭐⭐⭐/⭐⭐/⭐)
- 即時 intraday StageTrigger 偵測 (T1/T2/TC)
- 排序模式: priority / risk / trigger / pnl / sector
- 快捷鍵: 1=priority 2=risk 3=trigger 4=pnl 5=sector q=退出
"""
from __future__ import annotations

import argparse
import subprocess
import sqlite3
import sys
import termios
import tty
import threading
import select
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

# rich: display 層 (取代手刻 ANSI + alt-screen)
from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

_REPO = Path(__file__).parent.parent.parent
_SYS  = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_REPO), str(_REPO / "scripts"), str(_SYS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from clients.fubon_client import FubonClient  # noqa

DB = Path.home() / ".four_seasons" / "data.sqlite"

# ─────────────────────────────────────────────────────────────────────────
# 編輯區 (每天晚上鎖 plan 時改)
# ─────────────────────────────────────────────────────────────────────────

# 已進場部位 (Phase 2 P&L 監控)
# 格式: dict (必填: ticker, name, cost, shares, stop; 選填: tactic, priority, source, sector, note)
# 舊 tuple (ticker, name, cost, shares, stop) 自動 convert
HELD = [
    {
        'ticker': '6285', 'name': '啟碁',
        'cost': 315.0, 'shares': 1000, 'stop': 301.0,
        'tactic': '核心', 'priority': 2,
        'source': '老師明示',
        'sector': '低軌衛星',
        'note': '老師明示「兩檔選啟碁」、停損 MA10 動態'
    },
    {
        'ticker': '1605', 'name': '華新',
        'cost': 40.23, 'shares': 12000, 'stop': 38.75,
        'tactic': '核心', 'priority': 3,
        'source': '老師重壓',
        'sector': '紅海第二棒',
        'note': '6/2 8 張 @ $40.1 + 6/3 加 4 張 @ $40.5、均 $40.23'
    },
    {
        'ticker': '2885', 'name': '元大金',
        'cost': 58.0, 'shares': 10000, 'stop': 55.71,
        'tactic': '配置', 'priority': 1,
        'source': '配置部位',
        'sector': '金融',
        'note': '6/2 收 $59.60 (+$16k 浮動)、停損 $55.71 結構底'
    },
    {
        'ticker': '3481', 'name': '群創',
        'cost': 58.7, 'shares': 2000, 'stop': 56.2,
        'tactic': '短打', 'priority': 3,
        'source': '老師明示 6/3 (夜盤訊號)',
        'sector': '面板/族群補漲',
        'note': '6/3 進 2 張 @ $58.7、老師夜盤訊號、停損 6/2 收 $56.2'
    },
]

# 已實現 (今日累計、每日歸零)
REALIZED = 0

# 鎖定主候選 (Phase 1 開盤 entry screening)
# 格式: dict (必填: ticker, name, shares, stop; 選填: tactic, priority, source, sector, note, reason)
# 舊 tuple (ticker, name, shares, stop, reason) 自動 convert
PLAN_PRIMARY = [
    {
        'ticker': '1605', 'name': '華新',
        'shares': 1000, 'stop': 38.75,
        'tactic': '核心 Stage 2', 'priority': 3,
        'source': '老師重壓 + Trigger 1',
        'sector': '紅海第二棒',
        'note': '6/3 開盤 ≥ 40.0 + 跳空 ≤+3% 加 1 張',
        'reason': '🟢 EOD Trigger 1 確認 (外資 +16k + 管錢 +1067)、加 1 張',
    },
]

# 備案 (Phase 1 主候選被 skip 時遞補)
# 6/3 全 skip、結構壞 + 籌碼弱
PLAN_BACKUP: list = []

# 觀察清單 (dict 格式、兼容舊 tuple)
WATCH = [
    # 老師明示重壓 / 第二棒 / GT 基底
    {
        'ticker': '2303', 'name': '聯電',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 3,
        'source': '老師明示',
        'sector': 'GT基底/成熟製程',
        'note': '⭐ GT 基底、「直接參與最大組」、user 提醒'
    },
    {
        'ticker': '6770', 'name': '力積電',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 3,
        'source': '老師明示',
        'sector': 'GT基底/成熟製程',
        'note': '⭐ 老師「立即店」、GT 基底、距 MA10 +15% 偏遠等回測'
    },
    {
        'ticker': '3702', 'name': '大聯大',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示',
        'sector': 'IC通路',
        'note': '⭐ IC 通路「那個大科」、user 提醒'
    },
    {
        'ticker': '3036', 'name': '文曄',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示',
        'sector': 'IC通路',
        'note': '⭐ IC 通路、user 提醒 (注意 5/26 排除清單翻轉?)'
    },
    {
        'ticker': '2376', 'name': '技嘉',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 3,
        'source': '老師明示',
        'sector': 'AI PC/全資股',
        'note': '⭐⭐ 老師原話「我這波壓的」、AI PC 主流'
    },
    {
        'ticker': '8064', 'name': '東捷',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 3,
        'source': '老師明示',
        'sector': '玻璃',
        'note': '⭐ 玻璃明示、frequent tier'
    },
    {
        'ticker': '6116', 'name': '彩晶',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 3,
        'source': '老師明示',
        'sector': '紅海第二棒',
        'note': '⭐⭐ 紅海第二棒、管錢哥重押、外資挺'
    },
    # IC 設計 / 記憶體相關 (老師主流框架)
    {
        'ticker': '6147', 'name': '頎邦',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': 'scanner',
        'sector': '記憶體封測',
        'note': '⭐ 記憶體封測、user 提醒'
    },
    {
        'ticker': '5351', 'name': '鈺創',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': 'scanner',
        'sector': 'IC設計',
        'note': '⭐ IC 設計 / 記憶體、user 提醒'
    },
    {
        'ticker': '3006', 'name': '晶豪科',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': 'scanner',
        'sector': '記憶體',
        'note': '⭐ 記憶體 IC、user 提醒'
    },
    {
        'ticker': '2344', 'name': '華邦電',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示',
        'sector': '記憶體',
        'note': '⚠️ 主流但「已 50%、不要再追」、觀察回測'
    },
    # 6/2 收盤後三軸狀態追蹤
    {
        'ticker': '6207', 'name': '雷科',
        'ref_close': 127.0, 'stop': 115.0,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示',
        'sector': '玻璃',
        'note': '🟡 老師 [25:08]「壓著、尾盤關注、跟東捷類似」、距 MA10 +9.4%'
    },
    {
        'ticker': '8046', 'name': '南電',
        'ref_close': 862.0, 'stop': 834.0,
        'tactic': '短打', 'priority': 1,
        'source': '老師明示',
        'sector': 'ABF',
        'note': '🔴 老師「ABF 需要洗牌」、MA5/10/20 全破、外資 -3,125'
    },
    # 6/3 scanner 新增 (Tier-B 打擊區、籌碼/型態符合)
    {
        'ticker': '1717', 'name': '長興',
        'ref_close': 78.70, 'stop': 75.50,
        'tactic': '短打', 'priority': 2,
        'source': 'scanner (small_structure)',
        'sector': '封測/特化',
        'note': '🟡 投信 5d +1,726 + ⭐管錢哥、距 MA10 -2.7% 打擊區、首提後 79d (二波期)'
    },
    {
        'ticker': '4722', 'name': '國精化',
        'ref_close': 279.0, 'stop': 268.0,
        'tactic': '題材', 'priority': 2,
        'source': '處置框架',
        'sector': '化工',
        'note': '🔒A D+6 觀察中、出關前 4 天、等 6/5 (D-2 出關前 2 天) 切入時機'
    },
    {
        'ticker': '4526', 'name': '東台',
        'ref_close': 42.15, 'stop': 40.16,
        'tactic': '短打', 'priority': 2,
        'source': 'scanner (w_bottom_launch)',
        'sector': '電機機械',
        'note': '🟢 W底 + 量比 2.2x + ⭐站前哥、距 MA10 +5.0%、MA10 停利 ~40.16'
    },
    {
        'ticker': '4540', 'name': '全球傳動',
        'ref_close': 77.30, 'stop': 70.84,
        'tactic': '題材', 'priority': 2,
        'source': 'scanner (w_bottom_launch)',
        'sector': '機器人',
        'note': '🟢 機器人主流 + W底 量比 2.0x、距 MA10 +9.1%、MA10 停利 ~70.84'
    },
]

# 老師 6/2 明示族群框架 (大方向、scanner 命中後加分):
TEACHER_SECTORS_20260602 = {
    'IC 通路': '⭐⭐ 6/2 主流 (3702 大聯大 / 3036 文曄)',
    'IC 設計': '⭐⭐ 6/2 主流 (5351 鈺創 / 3034 聯詠 / 2454 聯發科)',
    '模組': '⭐ 6/2 主流 (實權 / 威剛 / 宇瞻 / 林行 / 光罩)',
    '記憶體': '⭐⭐ 6/2 主流 (2344 華邦電[漲多] / 2408 南亞科 / 3006 晶豪科)',
    '記憶體封測': '⭐ 6/2 主流 (6147 頎邦)',
    '記憶體周邊': '⭐ 6/2 主流',
    'GT 基底/成熟製程': '⭐⭐⭐ 6/2 核心 (2303 聯電 / 2330 台積電)',
    'AI PC / 全資股': '⭐⭐ (2376 技嘉 [重壓] / 3231 緯創 / 2382 廣達 / 2379 瑞昱)',
    '紅海第二棒': '⭐⭐ (1605 華新 / 6116 彩晶)',
    '玻璃': '⭐ (8064 東捷)',
}

# ─────────────────────────────────────────────────────────────────────────
# 排序模式
# ─────────────────────────────────────────────────────────────────────────

SORT_MODES = ['status', 'priority', 'risk', 'trigger', 'pnl', 'sector']
SORT_KEY_LABEL = {
    'status':   '🎯 狀態分段',
    'priority': '⭐ 優先級',
    'risk':     '⚠️  停損距離',
    'trigger':  '🟢 Trigger',
    'pnl':      '💰 P&L',
    'sector':   '🏷️  族群',
}

# Trigger 顯示格式
TRIGGER_DISPLAY = {
    'Ch5-3':  '🟡 Ch5-3 當沖 SOP',
    'T1':     '🟢 T1 confirmed',
    'T2':     '🎯 T2 confirmed',
    'TC':     '🔴 TC confirmed',
    'T2_watch': '🟡 T2 watch',
    'none': '⚪ 無訊號',
    None: '⚪ 無訊號',
}

# sort by trigger 優先順序: Ch5-3 > T2 > T1 > TC (warning) > none
TRIGGER_RANK = {
    'Ch5-3': 0,
    'T2':    1,
    'T1':    2,
    'TC':    3,
    'T2_watch': 4,
    'none': 5,
    None: 6,
}

# 全域排序切換（快捷鍵 1-6 更新這個）
_current_sort: list[str] = ['status']
_quit_flag: list[bool] = [False]
_watch_min_priority: list[int] = [2]
_watch_limit: list[int] = [8]

# Demo mode 全域 state
_demo_idx: list[int] = [0]
_demo_paused: list[bool] = [True]  # 預設暫停 auto-cycle、手動切
_demo_jump: list[bool] = [False]   # set 後主迴圈立刻 re-render
_demo_total: list[int] = [0]

# Trigger cooldown 避免重複通知 (key: "{ticker}_{T1/T2/TC}")
_trigger_cooldown: dict[str, datetime] = {}
TRIGGER_COOLDOWN_MIN = 30

# ─────────────────────────────────────────────────────────────────────────
# Tuple → dict 自動 convert (向後相容)
# ─────────────────────────────────────────────────────────────────────────

def _normalize_held(items: list) -> list[dict]:
    out = []
    for item in items:
        if isinstance(item, dict):
            out.append(item)
        else:
            tk, name, cost, shares, stop = item
            out.append({'ticker': tk, 'name': name, 'cost': cost,
                        'shares': shares, 'stop': stop,
                        'tactic': '核心', 'priority': 2,
                        'source': '?', 'sector': '?', 'note': ''})
    return out


def _normalize_plan(items: list) -> list[dict]:
    out = []
    for item in items:
        if isinstance(item, dict):
            out.append(item)
        else:
            tk, name, shares, stop, reason = item
            out.append({'ticker': tk, 'name': name, 'shares': shares,
                        'stop': stop, 'reason': reason,
                        'tactic': '核心', 'priority': 2,
                        'source': '?', 'sector': '?', 'note': reason})
    return out


def _normalize_watch(items: list) -> list[dict]:
    out = []
    for item in items:
        if isinstance(item, dict):
            out.append(item)
        else:
            tk, name, ref_close, stop, kind = item
            out.append({'ticker': tk, 'name': name,
                        'ref_close': ref_close, 'stop': stop,
                        'tactic': '短打', 'priority': 2,
                        'source': '?', 'sector': '?', 'note': kind})
    return out


# ─────────────────────────────────────────────────────────────────────────
# Intraday StageTrigger 即時偵測
# ─────────────────────────────────────────────────────────────────────────

def _load_stage_trigger():
    """Lazy import StageTrigger。"""
    try:
        from zhuli.intraday_stage_helper import StageTrigger, fetch_5min_kbar, _get_prev_levels
        return StageTrigger(), fetch_5min_kbar, _get_prev_levels
    except ImportError:
        try:
            # fallback: 直接從同目錄 import
            _here = Path(__file__).parent
            if str(_here) not in sys.path:
                sys.path.insert(0, str(_here))
            from intraday_stage_helper import StageTrigger, fetch_5min_kbar, _get_prev_levels
            return StageTrigger(), fetch_5min_kbar, _get_prev_levels
        except Exception as e:
            return None, None, None


_stage_engine, _fetch_5min, _get_prev = _load_stage_trigger()

# 抑制 stage_helper 的 log 訊息、避免噴到 monitor alt-screen 破版
import logging as _logging
_logging.getLogger('zhuli.intraday_stage_helper').setLevel(_logging.ERROR)
_logging.getLogger('intraday_stage_helper').setLevel(_logging.ERROR)
_logging.getLogger('clients.fubon_client').setLevel(_logging.ERROR)


# ─────────────────────────────────────────────────────────────────────────
# WebSocket 即時報價快取 (取代 sequential REST snapshot)
# ─────────────────────────────────────────────────────────────────────────

class WSPriceCache:
    """訂閱 Fubon WebSocket aggregates channel、cache 最新報價。

    monitor 每次 refresh 從 cache 拿、O(1)、不再 sequential REST。
    REST 用於初始 warm-up + WS 失敗時 fallback。
    """
    STALE_SEC = 30  # cache 超過 30 秒沒 update → REST fallback

    def __init__(self, client, tickers: list[str]):
        self.client = client
        self.tickers = list(set(tickers))
        self.cache: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.last_update: dict[str, float] = {}
        self.ws = None
        self.ws_ok = False
        self.errors = 0
        self._warm()
        self._connect()

    def _warm(self):
        """REST 初始抓一輪、確保 cache 有資料 + 記錄 _warm_close 供反推 prev_close."""
        for tk in self.tickers:
            try:
                snap = self.client.get_realtime_snapshot(tk)
                if snap:
                    with self.lock:
                        entry = dict(snap)
                        # 留底用於反推 prev_close (close - change_price)
                        if 'close' in entry:
                            entry['_warm_close'] = entry['close']
                        self.cache[tk] = entry
                        self.last_update[tk] = time.time()
            except Exception:
                pass

    def _connect(self):
        """Connect WebSocket、subscribe 全部 tickers (trades channel — Speed mode 支援)."""
        try:
            # 注意: Fubon Speed mode 不支援 aggregates/candles、只能用 trades/books
            self.ws = self.client.subscribe_quotes(
                self.tickers, self._on_message, channel='trades'
            )
            self.ws_ok = self.ws is not None
        except Exception:
            self.ws_ok = False

    def _on_message(self, msg):
        """WS 推送 callback。實測 trades channel 訊息格式 (Fubon Speed mode)：
            {"event": "data", "data": {
                "symbol": "3481", "type": "EQUITY", "exchange": "TWSE", "market": "TSE",
                "price": 59.1, "size": 5, "bid": 59, "ask": 59.1, "volume": 532557,
                "isContinuous": true, "session": "Regular",
                "time": 1780454658908318, "serial": 11214722
            }}
        其他事件: authenticated / pong / heartbeat / subscribed → 忽略。
        trades stream 沒有 OHLC、只有逐筆 price + 當日累積 volume (股數).
        我們本地維護 high/low (max/min seen)、close=最新 price、volume=cumulative/1000 (張).
        open / change_price / change_rate 由 REST warm 初始化、WS 不覆寫.
        """
        try:
            data = msg
            if isinstance(msg, str):
                import json as _json
                data = _json.loads(msg)
            if not isinstance(data, dict):
                return
            # 只處理 data event、忽略 authenticated/pong/heartbeat/subscribed
            event = data.get('event')
            if event != 'data':
                return
            payload = data.get('data')
            if not isinstance(payload, dict):
                return
            symbol = payload.get('symbol')
            if not symbol:
                return
            symbol = str(symbol)
            price = payload.get('price')
            if price is None:
                return
            price = float(price)
            volume_shares = payload.get('volume')  # 累積成交股數
            bid = payload.get('bid')
            ask = payload.get('ask')
            with self.lock:
                existing = self.cache.get(symbol) or {}
                # close = 最新成交價
                existing['close'] = price
                # high/low 本地維護 (trades stream 沒有 OHLC)
                cur_high = existing.get('high') or 0
                cur_low = existing.get('low') or 0
                if not cur_high or price > cur_high:
                    existing['high'] = price
                if not cur_low or price < cur_low:
                    existing['low'] = price
                # volume: cumulative shares → 張 (÷1000)
                if volume_shares is not None:
                    try:
                        existing['total_volume'] = int(volume_shares) // 1000
                    except Exception:
                        pass
                # bid/ask 補充欄位
                if bid is not None:
                    try:
                        existing['bid'] = float(bid)
                    except Exception:
                        pass
                if ask is not None:
                    try:
                        existing['ask'] = float(ask)
                    except Exception:
                        pass
                # change_price / change_rate 由 prev_close 推算
                # REST warm 給的 close + change_price → prev_close = close_at_warm - change_at_warm
                # 用 cached prev_close 推 new change
                prev_close = existing.get('_prev_close')
                if prev_close is None:
                    # 首次: 從 warm cache 反推 prev_close
                    warm_close = existing.get('_warm_close')
                    warm_change = existing.get('change_price')
                    if warm_close is not None and warm_change is not None:
                        try:
                            prev_close = float(warm_close) - float(warm_change)
                            existing['_prev_close'] = prev_close
                        except Exception:
                            prev_close = None
                if prev_close:
                    try:
                        existing['change_price'] = price - float(prev_close)
                        existing['change_rate'] = (price - float(prev_close)) / float(prev_close) * 100
                    except Exception:
                        pass
                self.cache[symbol] = existing
                self.last_update[symbol] = time.time()
        except Exception:
            self.errors += 1

    def get_realtime_snapshot(self, ticker: str) -> dict | None:
        """模擬 FubonClient.get_realtime_snapshot 介面、回傳 cached snapshot.

        若 cache stale > STALE_SEC、用 REST 補一筆。
        """
        ticker = str(ticker)
        with self.lock:
            snap = self.cache.get(ticker)
            ts   = self.last_update.get(ticker, 0)
        if snap and (time.time() - ts) < self.STALE_SEC:
            return dict(snap)
        # Stale or missing → REST fallback
        try:
            fresh = self.client.get_realtime_snapshot(ticker)
            if fresh:
                with self.lock:
                    self.cache[ticker] = dict(fresh)
                    self.last_update[ticker] = time.time()
                return fresh
        except Exception:
            pass
        return snap  # 回傳舊資料總比 None 好

    def stats(self) -> tuple[int, int, int]:
        """回傳 (cached_count, stale_count, error_count)."""
        now = time.time()
        with self.lock:
            total = len(self.cache)
            stale = sum(1 for ts in self.last_update.values()
                        if (now - ts) > self.STALE_SEC)
        return total, stale, self.errors


def check_trigger_inline(ticker: str, tactic: str = '核心') -> tuple[str, str]:
    """即時跑 composite_check cascade，回傳 (trigger_key, reason)。

    trigger_key: 'Ch5-3' / 'T1' / 'T2' / 'TC' / 'none'
    category 依 tactic 決定: 核心/題材 → HELD；其他 → WATCH
    向後相容: 舊 TRIGGER_DISPLAY / TRIGGER_RANK 保持不變。
    """
    if _stage_engine is None or _fetch_5min is None or _get_prev is None:
        return 'none', '(StageTrigger unavailable)'

    try:
        now = datetime.now()
        k5 = _fetch_5min(ticker, now.date())
        if k5 is None or k5.empty:
            return 'none', '(無 5K 資料)'

        prev = _get_prev(ticker, DB) if _get_prev else {}
        prev_close = float(prev.get('prev_close') or 0)

        # 紀律過濾
        pass_disc, disc_reason = _stage_engine.check_discipline_filter(
            ticker, k5, now, prev_close or None
        )

        # category 決定
        category = 'HELD' if tactic in ('核心', '題材') else 'WATCH'

        # Cascade composite_check
        result = _stage_engine.composite_check(
            ticker=ticker,
            k5=k5,
            prev_close=prev_close,
            prev_levels=prev,
            category=category,
        )

        det = result.get('detector', 'none')
        reason = result.get('reason', '')
        triggered = result.get('triggered', False)

        if not triggered:
            # 若紀律擋住也回報
            if not pass_disc:
                return 'none', disc_reason
            return 'none', reason

        return det, reason

    except Exception as e:
        return 'none', f'(err: {e})'


def maybe_notify_trigger(ticker: str, name: str, trig_key: str, reason: str, do_notify: bool):
    """Trigger 觸發時、30 分鐘 cooldown 通知。"""
    if not do_notify:
        return
    if trig_key not in ('Ch5-3', 'T1', 'T2', 'TC'):
        return
    cd_key = f"{ticker}_{trig_key}"
    now = datetime.now()
    if now <= _trigger_cooldown.get(cd_key, datetime.min):
        return
    _trigger_cooldown[cd_key] = now + timedelta(minutes=TRIGGER_COOLDOWN_MIN)

    titles = {
        'Ch5-3': f"🟡 {ticker} {name} Ch5-3 當沖 SOP",
        'T1': f"🟢 {ticker} {name} T1 強勢延續",
        'T2': f"🎯 {ticker} {name} T2 反彈訊號",
        'TC': f"🚨 {ticker} {name} TC 結構失敗",
    }
    sounds = {'Ch5-3': 'Glass', 'T1': 'Glass', 'T2': 'Glass', 'TC': 'Sosumi'}
    try:
        subprocess.run(
            ['osascript', '-e',
             f'display notification "{reason[:80]}" with title "{titles[trig_key]}" '
             f'sound name "{sounds[trig_key]}"'],
            check=False, timeout=3
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────
# 排序 helper
# ─────────────────────────────────────────────────────────────────────────

def sort_items(items: list[dict], mode: str, live_data: dict | None = None) -> list[dict]:
    ld = live_data or {}

    def key(x: dict):
        tk = x.get('ticker', '')
        d = ld.get(tk, {})
        if mode == 'priority':
            return (-x.get('priority', 2), x.get('sector', ''), tk)
        elif mode == 'risk':
            dist = d.get('dist_to_stop', 999.0)
            return (dist,)
        elif mode == 'trigger':
            trig = d.get('trigger') or 'none'
            return (TRIGGER_RANK.get(trig, 5), -x.get('priority', 2))
        elif mode == 'pnl':
            return (-d.get('pnl_pct', 0),)
        elif mode == 'sector':
            return (x.get('sector', '?'), -x.get('priority', 2), tk)
        return (tk,)

    return sorted(items, key=key)


# ─────────────────────────────────────────────────────────────────────────
# 顏色 / 格式 helper
# ─────────────────────────────────────────────────────────────────────────

class C:
    R = '\033[91m'; G = '\033[92m'; Y = '\033[93m'; B = '\033[94m'
    BOLD = '\033[1m'; DIM = '\033[2m'; END = '\033[0m'
    HOME = '\033[H'
    EOL  = '\033[K'
    ALT_ON  = '\033[?1049h'
    ALT_OFF = '\033[?1049l'
    HIDE = '\033[?25l'
    SHOW = '\033[?25h'
    CLR = HOME


def notify_mac(title: str, msg: str):
    try:
        subprocess.run(['osascript', '-e',
                       f'display notification "{msg}" with title "{title}" sound name "Glass"'],
                       check=False, timeout=3)
    except Exception:
        print('\a', end='', flush=True)


def fmt_pnl(pnl: float, pct: float = 0) -> str:
    color = C.G if pnl >= 0 else C.R
    sign = '+' if pnl >= 0 else ''
    if pct != 0:
        return f"{color}{sign}{pnl:,.0f} ({sign}{pct:.1f}%){C.END}"
    return f"{color}{sign}{pnl:,.0f}{C.END}"


def fmt_dist(dist: float) -> str:
    if dist < 0: return f"{C.R}{dist:+.1f}%{C.END}"
    if dist < 1: return f"{C.Y}{dist:+.1f}%{C.END}"
    return f"{C.G}{dist:+.1f}%{C.END}"


def stars(priority: int) -> str:
    return '⭐' * max(0, priority)


# ─────────────────────────────────────────────────────────────────────────
# rich helper (新 display 層)
# ─────────────────────────────────────────────────────────────────────────

def r_pnl(pnl: float, pct: float = 0) -> Text:
    """rich 版的 fmt_pnl、回傳 Text。"""
    style = 'green' if pnl >= 0 else 'red'
    sign = '+' if pnl >= 0 else ''
    if pct != 0:
        return Text(f"{sign}{pnl:,.0f} ({sign}{pct:.1f}%)", style=style)
    return Text(f"{sign}{pnl:,.0f}", style=style)


def r_dist(dist: float) -> Text:
    """距停損百分比、依危險度上色。"""
    if dist >= 999:
        return Text("—", style="dim")
    if dist < 0:
        return Text(f"{dist:+.1f}%", style="red")
    if dist < 1:
        return Text(f"{dist:+.1f}%", style="yellow")
    return Text(f"{dist:+.1f}%", style="green")


def r_trigger(trig_key: str, reason: str = '', short: int = 40) -> Text:
    """Trigger label + reason、rich Text。"""
    label = TRIGGER_DISPLAY.get(trig_key, '⚪ 無訊號')
    if trig_key == 'Ch5-3':
        style = 'yellow'
    elif trig_key in ('T1', 'T2'):
        style = 'green'
    elif trig_key == 'TC':
        style = 'red'
    elif trig_key == 'T2_watch':
        style = 'yellow'
    else:
        style = 'dim'
    t = Text(label, style=style)
    if reason and trig_key != 'none' and trig_key is not None:
        t.append(f" ({reason[:short]})", style='dim')
    return t


def r_change_pct(chg: float) -> Text:
    """漲跌幅 % 上色。"""
    style = 'red' if chg < 0 else 'green'
    return Text(f"{chg:+.1f}%", style=style)


# ─────────────────────────────────────────────────────────────────────────
# DB helper
# ─────────────────────────────────────────────────────────────────────────

def load_prev_close(ticker: str) -> float | None:
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
        r = con.execute(
            "SELECT close FROM standard_daily_bar WHERE ticker=? ORDER BY trade_date DESC LIMIT 1",
            (ticker,)
        ).fetchone()
        con.close()
        return float(r[0]) if r else None
    except Exception:
        return None


def classify_open(open_price: float, prev_close: float) -> tuple[str, str, str]:
    """回 (level_emoji, msg, severity)."""
    if open_price <= 0 or prev_close <= 0:
        return ('?', '無資料', 'unknown')
    chg = (open_price - prev_close) / prev_close * 100
    if open_price >= prev_close * 1.095:
        return ('❌', f'接近漲停 ({chg:+.1f}%)、鎖死買不到', 'skip')
    if chg > 5.0:
        return ('❌', f'開盤 {chg:+.1f}% > +5% (紅線 #9)', 'skip')
    if chg > 3.0:
        return ('⚠️', f'開盤 {chg:+.1f}% (gap-up 警示)', 'warn')
    if chg >= 0:
        return ('✅', f'開盤 {chg:+.1f}% (穩定強、可進)', 'ok')
    if chg >= -3.0:
        return ('🟡', f'開盤 {chg:+.1f}% (小弱)', 'neutral')
    return ('🔴', f'開盤 {chg:+.1f}% (顯著弱、慎入)', 'weak')


# ─────────────────────────────────────────────────────────────────────────
# Trigger 欄位 格式化
# ─────────────────────────────────────────────────────────────────────────

def fmt_trigger(trig_key: str, reason: str = '') -> str:
    label = TRIGGER_DISPLAY.get(trig_key, '⚪ 無訊號')
    short = reason[:40] if reason else ''
    if trig_key == 'Ch5-3':
        return f"{C.Y}{label}{C.END}" + (f" {C.DIM}({short}){C.END}" if short else '')
    if trig_key in ('T1', 'T2'):
        return f"{C.G}{label}{C.END}" + (f" {C.DIM}({short}){C.END}" if short else '')
    if trig_key == 'TC':
        return f"{C.R}{label}{C.END}" + (f" {C.DIM}({short[:40]}){C.END}" if reason else '')
    if trig_key == 'T2_watch':
        return f"{C.Y}{label}{C.END}" + (f" {C.DIM}({reason[:30]}){C.END}" if reason else '')
    return f"{C.DIM}{label}{C.END}"


# ─────────────────────────────────────────────────────────────────────────
# Priority panel summary
# ─────────────────────────────────────────────────────────────────────────

def render_priority_panel(held: list[dict], watch: list[dict],
                          live_data: dict) -> Table:
    """高/中/低優先級摘要 panel — rich.Table (3 列)。"""
    def group(items):
        p3 = [x for x in items if x.get('priority', 2) == 3]
        p2 = [x for x in items if x.get('priority', 2) == 2]
        p1 = [x for x in items if x.get('priority', 2) == 1]
        return p3, p2, p1

    held_p3, held_p2, held_p1 = group(held)
    watch_p3, watch_p2, watch_p1 = group(watch)

    triggered_map: dict[str, str] = {}
    for x in held + watch:
        tk = x.get('ticker', '')
        trig = live_data.get(tk, {}).get('trigger', 'none')
        if trig in ('T1', 'T2', 'TC'):
            triggered_map[tk] = trig

    warnings: list[str] = []
    for x in held:
        tk = x.get('ticker', '')
        dist = live_data.get(tk, {}).get('dist_to_stop', 999)
        if dist < 1:
            warnings.append(f"{tk}({dist:+.1f}%)")

    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1), expand=False)
    table.add_column("優先級", style="bold", no_wrap=True)
    table.add_column("數", justify="right", no_wrap=True)
    table.add_column("持倉", no_wrap=False)
    table.add_column("候選/觀察", no_wrap=False)
    table.add_column("Trigger/警示", no_wrap=False)

    def _row(label: str, h_list: list, w_list: list):
        all_list = h_list + w_list
        if not all_list:
            return
        h_tks = [x['ticker'] for x in h_list]
        w_tks = [x['ticker'] for x in w_list]
        all_tks = h_tks + w_tks
        trig_info = [f"{tk}({triggered_map[tk]})" for tk in all_tks if tk in triggered_map]
        warn_info = [w for w in warnings if any(w.startswith(x['ticker']) for x in h_list)]
        right = Text()
        if trig_info:
            right.append("🟢 " + "/".join(trig_info), style="green")
        if warn_info:
            if trig_info:
                right.append("  ")
            right.append("⚠️ " + ",".join(warn_info), style="red")
        table.add_row(
            label,
            str(len(all_list)),
            "/".join(h_tks),
            "/".join(w_tks),
            right,
        )

    _row("🎯 P3", held_p3, watch_p3)
    _row("⚠️  P2", held_p2, watch_p2)
    _row("🟢 P1", held_p1, watch_p1)
    return table


# ─────────────────────────────────────────────────────────────────────────
# Phase 1: 開盤 Entry Screening
# ─────────────────────────────────────────────────────────────────────────

def render_phase1_screener(client, now_str: str, sort_mode: str,
                           do_notify: bool) -> Group:
    """Phase 1 開盤 entry screening (9:00-9:25)、回傳 rich Group。"""
    held   = _normalize_held(HELD)
    plan   = _normalize_plan(PLAN_PRIMARY)
    backup = _normalize_plan(PLAN_BACKUP)

    # --- collect live data including triggers ---
    live_data: dict = {}
    for item in held + plan:
        tk = item.get('ticker', '')
        try:
            snap = client.get_realtime_snapshot(tk) or {}
            c = float(snap.get('close') or 0)
            entry = item.get('cost') or 0
            stop  = item.get('stop')  or 0
            pnl_pct = (c - entry)/entry*100 if entry and c else 0
            dist    = (c - stop)/c*100 if c and stop else 999
            trig_key, trig_reason = check_trigger_inline(tk, item.get('tactic', '核心'))
            maybe_notify_trigger(tk, item.get('name', tk), trig_key, trig_reason, do_notify)
            live_data[tk] = {
                'c': c, 'pnl_pct': pnl_pct, 'dist_to_stop': dist,
                'trigger': trig_key, 'trigger_reason': trig_reason,
            }
        except Exception:
            live_data[tk] = {}

    watch_norm = _normalize_watch(WATCH)

    renderables: list = []
    # Priority panel
    renderables.append(render_priority_panel(held, watch_norm, live_data))

    # 已持倉開盤健康度
    if held:
        t_held = Table(
            title="📊 已持倉開盤健康度",
            title_style="bold",
            box=box.SIMPLE,
            expand=True,
            show_lines=False,
        )
        t_held.add_column("Lv", no_wrap=True)
        t_held.add_column("⭐", no_wrap=True)
        t_held.add_column("Ticker", no_wrap=True)
        t_held.add_column("Name", no_wrap=True)
        t_held.add_column("開→現", no_wrap=True)
        t_held.add_column("入", justify="right", no_wrap=True)
        t_held.add_column("P&L", justify="right", no_wrap=True)
        t_held.add_column("停", justify="right", no_wrap=True)
        t_held.add_column("Trigger / 開盤評語")
        for item in sort_items(held, sort_mode, live_data):
            tk     = item['ticker']
            name   = item['name']
            entry  = item.get('cost', 0)
            shares = item.get('shares', 0)
            stop   = item.get('stop', 0)
            pri    = item.get('priority', 2)
            d      = live_data.get(tk, {})
            trig_key    = d.get('trigger', 'none')
            trig_reason = d.get('trigger_reason', '')
            try:
                snap = client.get_realtime_snapshot(tk) or {}
                o    = float(snap.get('open') or 0)
                c    = float(snap.get('close') or 0)
                prev = load_prev_close(tk)
                level, msg, _sev = classify_open(o, prev) if prev else ('?', '無前收', 'unknown')
                entry_vs_open = (entry - o)/o*100 if o else 0
                if entry_vs_open < -1:
                    entry_tag = Text(f"🎯 進得好 ({entry_vs_open:.1f}%)", style="green")
                elif entry_vs_open > 1:
                    entry_tag = Text(f"⚠️ 追高 ({entry_vs_open:+.1f}%)", style="yellow")
                else:
                    entry_tag = Text("入價貼開盤", style="dim")
                pnl = (c - entry)*shares
                pnl_pct = (c - entry)/entry*100 if entry else 0
                detail = Text()
                detail.append_text(r_trigger(trig_key, trig_reason, short=30))
                detail.append("  ")
                detail.append(msg, style="dim")
                detail.append(" | ")
                detail.append_text(entry_tag)
                t_held.add_row(
                    level,
                    stars(pri),
                    tk,
                    name,
                    f"{o:.1f}→{c:.1f}",
                    f"{entry:.1f}",
                    r_pnl(pnl, pnl_pct),
                    f"{stop}",
                    detail,
                )
            except Exception as e:
                t_held.add_row("?", "", tk, name, "err", "", Text(str(e), style="red"), "", "")
        renderables.append(t_held)

    # 待進場主候選
    if plan:
        t_plan = Table(
            title="🎯 待進場主候選",
            title_style="bold",
            box=box.SIMPLE,
            expand=True,
        )
        t_plan.add_column("Lv", no_wrap=True)
        t_plan.add_column("⭐", no_wrap=True)
        t_plan.add_column("Ticker", no_wrap=True)
        t_plan.add_column("Name", no_wrap=True)
        t_plan.add_column("前→開 (%)", no_wrap=True)
        t_plan.add_column("現", justify="right", no_wrap=True)
        t_plan.add_column("停", justify="right", no_wrap=True)
        t_plan.add_column("Sizing", no_wrap=True)
        t_plan.add_column("Trigger / 評語 / reason")

        skipped = []
        for item in sort_items(plan, sort_mode, live_data):
            tk     = item['ticker']
            name   = item['name']
            shares = item.get('shares', 0)
            stop   = item.get('stop', 0)
            reason = item.get('reason') or item.get('note', '')
            pri    = item.get('priority', 2)
            d      = live_data.get(tk, {})
            trig_key    = d.get('trigger', 'none')
            trig_reason = d.get('trigger_reason', '')
            try:
                snap = client.get_realtime_snapshot(tk) or {}
                o    = float(snap.get('open') or 0)
                c    = float(snap.get('close') or 0)
                prev = load_prev_close(tk)
                level, msg, sev = classify_open(o, prev) if prev else ('?', '無前收', 'unknown')
                chg_open = (o - prev)/prev*100 if prev else 0
                cost = o * shares
                detail = Text()
                detail.append_text(r_trigger(trig_key, trig_reason, short=25))
                detail.append("  ")
                detail.append(msg, style="dim")
                if reason:
                    detail.append(" | ")
                    detail.append(reason[:50], style="dim")
                t_plan.add_row(
                    level,
                    stars(pri),
                    tk,
                    name,
                    f"{prev or 0:.1f}→{o:.1f} ({chg_open:+.1f}%)",
                    f"{c:.1f}",
                    f"{stop}",
                    f"{shares}股 ${cost:,.0f}",
                    detail,
                )
                if sev in ('skip', 'warn'):
                    skipped.append(tk)
            except Exception as e:
                t_plan.add_row("?", "", tk, name, "err", "", "", "", Text(str(e), style="red"))
        renderables.append(t_plan)

        # 備案推薦
        if skipped and backup:
            sev_order = {'ok': 0, 'neutral': 1, 'warn': 2, 'weak': 3, 'skip': 4, 'unknown': 5}
            backup_evaluated = []
            for item in backup:
                tk     = item['ticker']
                name   = item['name']
                shares = item.get('shares', 0)
                stop   = item.get('stop', 0)
                reason = item.get('reason') or item.get('note', '')
                try:
                    snap = client.get_realtime_snapshot(tk) or {}
                    o    = float(snap.get('open') or 0)
                    c    = float(snap.get('close') or 0)
                    prev = load_prev_close(tk)
                    level, msg, sev = classify_open(o, prev) if prev else ('?', 'no prev', 'unknown')
                    chg_open = (o-prev)/prev*100 if prev else 0
                    backup_evaluated.append(
                        (sev, -chg_open, tk, name, shares, prev, o, c, level, msg, reason, stop)
                    )
                except Exception:
                    pass
            backup_evaluated.sort(key=lambda x: (sev_order.get(x[0], 9), x[1]))
            t_bk = Table(
                title=f"⚠️  {len(skipped)} 主候選 skip / 備案推薦",
                title_style="bold yellow",
                box=box.SIMPLE,
                expand=True,
            )
            t_bk.add_column("Lv")
            t_bk.add_column("Ticker")
            t_bk.add_column("Name")
            t_bk.add_column("前→開")
            t_bk.add_column("現", justify="right")
            t_bk.add_column("停", justify="right")
            t_bk.add_column("Sizing")
            t_bk.add_column("評語")
            for bitem in backup_evaluated[:3]:
                sev, _, tk, name, shares, prev, o, c, level, msg, reason, stop = bitem
                chg_open = (o - (prev or 1))/(prev or 1)*100
                cost = o * shares
                t_bk.add_row(
                    level, tk, name,
                    f"{prev or 0:.1f}→{o:.1f} ({chg_open:+.1f}%)",
                    f"{c:.1f}", f"{stop}",
                    f"{shares}股 ${cost:,.0f}",
                    Text(f"{msg} | {reason[:40]}", style="dim"),
                )
            renderables.append(t_bk)
        elif not skipped:
            renderables.append(Text("✅ 主候選全部 OK、無需備案", style="green"))
    elif not held:
        renderables.append(Text("PLAN_PRIMARY 空、編輯腳本開頭設定", style="dim"))

    # Phase 1: WATCH 分段 (status mode 才顯示、避免干擾 entry focus)
    if sort_mode == 'status' and watch_norm:
        watch_live: dict = {}
        for item in watch_norm:
            tk     = item['ticker']
            tactic = item.get('tactic', '短打')
            ref    = item.get('ref_close') or 0
            stop   = item.get('stop')
            try:
                snap = client.get_realtime_snapshot(tk) or {}
                c = float(snap.get('close') or 0) or (load_prev_close(tk) or ref)
                chg = (c - ref)/ref*100 if ref else 0
                dist = (c - stop)/c*100 if (c and stop) else 999
                trig_key, trig_reason = check_trigger_inline(tk, tactic)
                maybe_notify_trigger(tk, item.get('name', tk), trig_key, trig_reason, do_notify)
                watch_live[tk] = {
                    'c': c, 'pnl_pct': chg, 'dist_to_stop': dist,
                    'trigger': trig_key, 'trigger_reason': trig_reason,
                }
            except Exception:
                watch_live[tk] = {}

        confirmed_p1, watching_p1 = [], []
        for item in watch_norm:
            tk = item['ticker']
            d  = watch_live.get(tk, {})
            bucket = _classify_watch_item(item, d)
            if bucket == 'confirmed':
                confirmed_p1.append((item, d))
            elif bucket == 'watching':
                watching_p1.append((item, d))
        confirmed_p1.sort(key=lambda x: (
            -x[0].get('priority', 1),
            TRIGGER_RANK.get(x[1].get('trigger', 'none'), 6),
        ))
        watching_p1.sort(key=lambda x: -x[0].get('priority', 1))

        if confirmed_p1:
            t_wc = Table(title="🎯 WATCH 可進場 (confirmed)",
                         title_style="bold green", box=box.SIMPLE, expand=True)
            t_wc.add_column("⭐"); t_wc.add_column("Ticker"); t_wc.add_column("Name")
            t_wc.add_column("現", justify="right")
            t_wc.add_column("Trigger")
            for item, d in confirmed_p1:
                trig = d.get('trigger', 'none'); reason = d.get('trigger_reason', '')
                c = d.get('c', 0); pri = item.get('priority', 1)
                t_wc.add_row(
                    stars(pri), item['ticker'], item['name'],
                    f"{c:.1f}" if c else "—",
                    r_trigger(trig, reason, short=50),
                )
            renderables.append(t_wc)

        if watching_p1:
            t_ww = Table(title="🔍 WATCH 觀察中",
                         title_style="bold", box=box.SIMPLE, expand=True)
            t_ww.add_column("⭐"); t_ww.add_column("Ticker"); t_ww.add_column("Name")
            t_ww.add_column("現", justify="right")
            t_ww.add_column("Note")
            for item, d in watching_p1:
                c = d.get('c', 0); pri = item.get('priority', 1)
                t_ww.add_row(
                    stars(pri), item['ticker'], item['name'],
                    f"{c:.1f}" if c else "—",
                    Text(item.get('note', '')[:60], style="dim"),
                )
            renderables.append(t_ww)

    panel = Panel(
        Group(*renderables),
        title=f"PHASE 1: 開盤 ENTRY SCREENING  {now_str}  (排序: {SORT_KEY_LABEL.get(sort_mode, sort_mode)})",
        border_style="cyan",
    )
    return Group(panel)


# ─────────────────────────────────────────────────────────────────────────
# WATCH 3-section 分類邏輯
# ─────────────────────────────────────────────────────────────────────────

def _classify_watch_item(item: dict, d: dict) -> str:
    """依 composite_check 結果分流: confirmed / watching / excluded."""
    trig_key = d.get('trigger', 'none')
    pri      = item.get('priority', 1)

    if trig_key in ('T1', 'T2', 'Ch5-3'):
        return 'confirmed'
    if trig_key == 'TC':
        return 'excluded'
    if trig_key == 'T2_watch':
        return 'watching'
    # 無訊號: 依 priority 分
    if pri >= 2:
        return 'watching'
    return 'excluded'


def _pre_market_mode() -> bool:
    now = datetime.now()
    return not ((now.hour, now.minute) >= (9, 0))


def render_watch_sectioned(
    watch_enriched: list[dict],
    live_data: dict,
    sort_mode: str,
) -> list:
    """WATCH 分 3 段顯示 (status mode)、回傳 rich renderables list。"""
    confirmed: list[tuple] = []
    watching:  list[tuple] = []
    excluded:  list[tuple] = []

    pre_mkt = _pre_market_mode()

    for item in watch_enriched:
        tk = item['ticker']
        d  = live_data.get(tk, {})
        bucket = _classify_watch_item(item, d)
        if bucket == 'confirmed':
            confirmed.append((item, d))
        elif bucket == 'watching':
            watching.append((item, d))
        else:
            excluded.append((item, d))

    confirmed.sort(key=lambda x: (
        -x[0].get('priority', 1),
        TRIGGER_RANK.get(x[1].get('trigger', 'none'), 6),
    ))
    watching.sort(key=lambda x: -x[0].get('priority', 1))
    excluded.sort(key=lambda x: -x[0].get('priority', 1))

    out: list = []

    if pre_mkt:
        out.append(Text("⏳ 開盤前、5K 累積中 — Trigger 判定尚未啟動", style="dim"))

    # --watch-min-priority 過濾 watching (confirmed 永遠顯示、不過濾)
    min_pri = _watch_min_priority[0]
    pre_filter_count = len(watching)
    watching = [(it, d) for (it, d) in watching if it.get('priority', 1) >= min_pri]
    filtered_out = pre_filter_count - len(watching)

    if pre_mkt:
        excluded_count = len(excluded)
        excluded = []  # 開盤前不顯示排除清單、開盤後再判
        if excluded_count or filtered_out:
            hidden = excluded_count + filtered_out
            out.append(Text(f"({hidden} 檔低優先/排除暫不顯示)", style="dim"))
    elif filtered_out:
        out.append(Text(f"({filtered_out} 檔 priority < {min_pri} 過濾)", style="dim"))

    # --watch-limit 限制 watching 顯示行數 (confirmed/excluded 不受限)
    limit = _watch_limit[0]
    watching_overflow = 0
    if limit > 0 and len(watching) > limit:
        watching_overflow = len(watching) - limit
        watching = watching[:limit]

    if confirmed:
        t = Table(title="🎯 WATCH 可進場 (confirmed)",
                  title_style="bold green", box=box.SIMPLE, expand=True)
        t.add_column("⭐"); t.add_column("Ticker"); t.add_column("Name")
        t.add_column("現", justify="right"); t.add_column("距停", justify="right")
        t.add_column("Trigger"); t.add_column("族群")
        for item, d in confirmed:
            pri = item.get('priority', 1)
            trig = d.get('trigger', 'none'); reason = d.get('trigger_reason', '')
            c = d.get('c', 0); stop = item.get('stop')
            dist = d.get('dist_to_stop', 999)
            dist_t = r_dist(dist) if stop else Text("—", style="dim")
            price_s = f"{c:.1f}" if c else "—"
            t.add_row(
                stars(pri), item['ticker'], item['name'],
                price_s, dist_t,
                r_trigger(trig, reason, short=40),
                item.get('sector', '?'),
            )
        out.append(t)

    if watching:
        t = Table(title="🔍 WATCH 觀察可能",
                  title_style="bold", box=box.SIMPLE, expand=True)
        t.add_column("⭐"); t.add_column("Ticker"); t.add_column("Name")
        t.add_column("現", justify="right"); t.add_column("漲跌", justify="right")
        t.add_column("Trigger"); t.add_column("Note")
        for item, d in watching:
            pri = item.get('priority', 1)
            trig = d.get('trigger', 'none')
            c = d.get('c', 0); chg = d.get('pnl_pct', 0)
            price_s = f"{c:.1f}" if c else "—"
            trig_t = r_trigger(trig) if trig not in ('none', None) else Text("—", style="dim")
            t.add_row(
                stars(pri), item['ticker'], item['name'],
                price_s, r_change_pct(chg),
                trig_t,
                Text(item.get('note', '')[:28], style="dim"),
            )
        out.append(t)
        if watching_overflow:
            out.append(Text(
                f"({watching_overflow} 檔暫不顯示、--watch-limit 加大)",
                style="dim",
            ))

    if excluded:
        t = Table(title="⛔ WATCH 排除/低優先",
                  title_style="dim", box=box.SIMPLE, expand=True)
        t.add_column("Ticker"); t.add_column("Name"); t.add_column("原因")
        for item, d in excluded:
            trig = d.get('trigger', 'none')
            reason_s = ''
            if trig == 'TC':
                reason_s = 'TC 結構壞'
            elif item.get('note', '').startswith('🔴'):
                reason_s = item['note'][:30]
            elif item.get('priority', 1) == 1:
                reason_s = '低優先'
            t.add_row(item['ticker'], item['name'], Text(reason_s, style="dim"))
        out.append(t)

    return out


# ─────────────────────────────────────────────────────────────────────────
# Phase 2: 持倉 P&L 監控
# ─────────────────────────────────────────────────────────────────────────

def render_phase2_holdings(client, now_str: str, prev_prices: dict,
                           notified: set, sort_mode: str,
                           do_notify: bool) -> Group:
    """Phase 2 持倉 P&L 監控 (9:25 後)、回傳 rich Group。"""
    held  = _normalize_held(HELD)
    watch = _normalize_watch(WATCH)

    from datetime import datetime as _dt
    _now = _dt.now()
    _market_open = (_now.hour, _now.minute) >= (9, 0) and (_now.hour, _now.minute) < (13, 30)

    live_data: dict = {}
    total_pnl = 0.0
    held_enriched: list[dict] = []

    for item in held:
        tk     = item['ticker']
        entry  = item['cost']
        shares = item['shares']
        stop   = item['stop']
        tactic = item.get('tactic', '核心')
        try:
            snap = client.get_realtime_snapshot(tk)
            no_data = snap is None or not snap.get('close')
            if no_data:
                c = load_prev_close(tk) or entry
            else:
                c = float(snap['close'])
            prev_prices[tk] = c
            pnl     = (c - entry) * shares
            pnl_pct = (c - entry)/entry*100 if entry else 0
            dist    = (c - stop)/c*100 if c else 0
            if not no_data:
                total_pnl += pnl
            trig_key, trig_reason = check_trigger_inline(tk, tactic)
            maybe_notify_trigger(tk, item.get('name', tk), trig_key, trig_reason, do_notify)
            live_data[tk] = {
                'c': c, 'pnl': pnl, 'pnl_pct': pnl_pct,
                'dist_to_stop': dist, 'no_data': no_data,
                'trigger': trig_key, 'trigger_reason': trig_reason,
            }
            held_enriched.append(item)
        except Exception as e:
            live_data[tk] = {'error': str(e)}
            held_enriched.append(item)

    renderables: list = []
    renderables.append(render_priority_panel(held_enriched, watch, live_data))

    if not held_enriched:
        renderables.append(Text("未進場、無持倉監控", style="dim"))
    else:
        t_h = Table(title="📊 持倉", title_style="bold",
                    box=box.SIMPLE, expand=True)
        t_h.add_column("戰術", no_wrap=True)
        t_h.add_column("⭐", no_wrap=True)
        t_h.add_column("Ticker", no_wrap=True)
        t_h.add_column("Name", no_wrap=True)
        t_h.add_column("現", justify="right", no_wrap=True)
        t_h.add_column("P&L", justify="right", no_wrap=True)
        t_h.add_column("距停", justify="right", no_wrap=True)
        t_h.add_column("Trigger")
        t_h.add_column("族群")
        t_h.add_column("狀", no_wrap=True)
        for item in sort_items(held_enriched, sort_mode, live_data):
            tk     = item['ticker']
            name   = item['name']
            entry  = item['cost']
            stop   = item['stop']
            tactic = item.get('tactic', '—')
            pri    = item.get('priority', 2)
            sector = item.get('sector', '?')
            d = live_data.get(tk, {})
            if 'error' in d:
                t_h.add_row(tactic, stars(pri), tk, name,
                            Text(f"err {d['error']}", style="red"),
                            "", "", "", sector, "?")
                continue
            c        = d.get('c', entry)
            pnl      = d.get('pnl', 0)
            pnl_pct  = d.get('pnl_pct', 0)
            dist     = d.get('dist_to_stop', 0)
            no_data  = d.get('no_data', False)
            trig_key    = d.get('trigger', 'none')
            trig_reason = d.get('trigger_reason', '')

            # 停損 alert
            key = f"{tk}_break"
            if dist < 0:
                if key not in notified:
                    notified.add(key)
                    notify_mac(f"🚨 {tk} {name} 跌破停損 ${stop}",
                               f"現 ${c:.1f}、損 ${pnl:,.0f}")
            else:
                notified.discard(key)

            stop_tag = '🔴' if dist < 0 else ('⚠️' if dist < 1 else '🟢')
            # 欄位本身已是「現」、無 WS 資料才特別標「昨」、平常不加前綴
            price_label = (f"昨{c:.1f}" if no_data else f"{c:.1f}")
            t_h.add_row(
                tactic, stars(pri), tk, name,
                Text(price_label, style="dim" if no_data else ""),
                r_pnl(pnl, pnl_pct),
                r_dist(dist),
                r_trigger(trig_key, trig_reason, short=30),
                sector,
                stop_tag,
            )
        renderables.append(t_h)

    today = total_pnl + REALIZED
    summary = Text()
    summary.append("帳面 ")
    summary.append_text(r_pnl(total_pnl))
    summary.append(" | 已實現 ")
    summary.append_text(r_pnl(REALIZED))
    summary.append(" | 💰 今日 ")
    summary.append_text(r_pnl(today))
    renderables.append(summary)

    # Watchlist
    if watch:
        watch_enriched = []
        for item in watch:
            tk   = item['ticker']
            ref  = item.get('ref_close') or 0
            stop = item.get('stop')
            tactic = item.get('tactic', '短打')
            try:
                snap = client.get_realtime_snapshot(tk) or {}
                c = float(snap.get('close') or 0)
                pre = False
                if c == 0:
                    c = load_prev_close(tk) or ref
                    pre = True
                # 漲跌計算優先用 snapshot.change_rate (WS/REST 已基於真實前收計算)
                # 否則 fallback ref_close 或 DB prev (DB 可能含今日 bar、會 = c → 0%)
                snap_chg = snap.get('change_rate')
                if snap_chg is not None:
                    try:
                        chg = float(snap_chg)
                    except Exception:
                        chg = 0
                else:
                    if not ref:
                        ref = load_prev_close(tk) or 0
                    chg = (c - ref)/ref*100 if ref else 0
                dist = (c - stop)/c*100 if (c and stop) else 999
                trig_key, trig_reason = check_trigger_inline(tk, tactic)
                maybe_notify_trigger(tk, item.get('name', tk), trig_key, trig_reason, do_notify)
                live_data[tk] = {
                    'c': c, 'pnl_pct': chg, 'dist_to_stop': dist,
                    'pre': pre, 'trigger': trig_key, 'trigger_reason': trig_reason,
                }
            except Exception:
                live_data[tk] = {}
            watch_enriched.append(item)

        if sort_mode == 'status':
            renderables.extend(render_watch_sectioned(watch_enriched, live_data, sort_mode))
        else:
            t_w = Table(title=f"Watchlist (排序: {SORT_KEY_LABEL.get(sort_mode, sort_mode)})",
                        title_style="dim", box=box.SIMPLE, expand=True)
            t_w.add_column("⭐"); t_w.add_column("戰術")
            t_w.add_column("Ticker"); t_w.add_column("Name")
            t_w.add_column("現", justify="right"); t_w.add_column("漲跌", justify="right")
            t_w.add_column("距停", justify="right")
            t_w.add_column("Trigger"); t_w.add_column("族群"); t_w.add_column("狀")
            for item in sort_items(watch_enriched, sort_mode, live_data):
                tk     = item['ticker']
                name   = item['name']
                ref    = item.get('ref_close') or 0
                stop   = item.get('stop')
                pri    = item.get('priority', 2)
                tactic = item.get('tactic', '—')
                sector = item.get('sector', '?')
                d = live_data.get(tk, {})
                c    = d.get('c', ref)
                chg  = d.get('pnl_pct', 0)
                dist = d.get('dist_to_stop', 999)
                pre  = d.get('pre', True)
                trig_key    = d.get('trigger', 'none')
                trig_reason = d.get('trigger_reason', '')
                wall_tag = '盤前' if pre else ('🔴' if (stop and dist < 0) else '🟡')
                t_w.add_row(
                    stars(pri), tactic, tk, name,
                    f"{c:.1f}" if c else "—",
                    r_change_pct(chg),
                    r_dist(dist),
                    r_trigger(trig_key, trig_reason, short=30),
                    sector,
                    wall_tag,
                )
            renderables.append(t_w)

    panel = Panel(
        Group(*renderables),
        title=f"PHASE 2: 持倉 P&L  {now_str}  (排序: {SORT_KEY_LABEL.get(sort_mode, sort_mode)})",
        border_style="magenta",
    )
    return Group(panel)


# ─────────────────────────────────────────────────────────────────────────
# 快捷鍵 stdin 偵測 (non-blocking)
# ─────────────────────────────────────────────────────────────────────────

def _kb_listener(demo_mode: bool = False):
    """Background thread: 讀 stdin single char、更新 _current_sort。

    demo_mode=True 時、額外處理 arrow/home/end/space 控制 scenario。
    """
    mode_map = {'1': 'status', '2': 'priority', '3': 'risk', '4': 'trigger', '5': 'pnl', '6': 'sector'}
    try:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        tty.setcbreak(fd)  # cbreak 保留 NL→CRNL 輸出翻譯、避免 rich 階梯狀
    except Exception:
        return

    def _advance(delta: int):
        total = _demo_total[0] or 1
        _demo_idx[0] = (_demo_idx[0] + delta) % total
        _demo_jump[0] = True

    try:
        while not _quit_flag[0]:
            try:
                r, _, _ = select.select([sys.stdin], [], [], 0.3)
                if not r:
                    continue
                ch = sys.stdin.read(1)
                if ch == 'q':
                    _quit_flag[0] = True
                    break
                if ch == '\x1b':
                    # escape sequence — 讀後續 2 字元 (e.g. [D / [C / [H / [F)
                    r2, _, _ = select.select([sys.stdin], [], [], 0.05)
                    if not r2:
                        continue
                    ch2 = sys.stdin.read(1)
                    if ch2 != '[':
                        continue
                    r3, _, _ = select.select([sys.stdin], [], [], 0.05)
                    if not r3:
                        continue
                    ch3 = sys.stdin.read(1)
                    if not demo_mode:
                        continue
                    if ch3 == 'D':       # ← 左
                        _advance(-1)
                    elif ch3 == 'C':     # → 右
                        _advance(1)
                    elif ch3 == 'H':     # home
                        _demo_idx[0] = 0
                        _demo_jump[0] = True
                    elif ch3 == 'F':     # end
                        _demo_idx[0] = max(0, (_demo_total[0] or 1) - 1)
                        _demo_jump[0] = True
                    continue
                if demo_mode:
                    if ch == ' ':
                        _demo_paused[0] = not _demo_paused[0]
                        _demo_jump[0] = True
                        continue
                    if ch == '0':
                        _demo_idx[0] = 0
                        _demo_jump[0] = True
                        continue
                if ch in mode_map:
                    _current_sort[0] = mode_map[ch]
            except Exception:
                break
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────
# Demo mode: mock client + scenario 循環
# ─────────────────────────────────────────────────────────────────────────

class MockClient:
    """模擬 FubonClient.get_realtime_snapshot 介面、回傳 scenario 設計好的 snapshot."""

    def __init__(self):
        # tk -> snapshot dict (含 open/close/high/low/change_price/change_rate)
        self.scenario: dict[str, dict] = {}
        # tk -> trigger override: (key, reason)
        self.trigger_overrides: dict[str, tuple[str, str]] = {}

    def get_realtime_snapshot(self, ticker: str) -> dict | None:
        ticker = str(ticker)
        snap = self.scenario.get(ticker)
        return dict(snap) if snap else None

    # 給 WSPriceCache 介面相容性 (demo 不會用、但避免 attr error)
    def subscribe_quotes(self, *_a, **_kw):
        return None

    def stats(self):
        return (len(self.scenario), 0, 0)


def _mk_snap(prev: float, open_: float, close: float,
             high: float | None = None, low: float | None = None) -> dict:
    """生 snapshot dict、含 change_price/change_rate."""
    h = high if high is not None else max(open_, close)
    l = low  if low  is not None else min(open_, close)
    chg_p = close - prev
    chg_r = (chg_p / prev * 100) if prev else 0
    return {
        'open': open_, 'close': close, 'high': h, 'low': l,
        'change_price': chg_p, 'change_rate': chg_r,
        'total_volume': 5000,
    }


def _demo_load_prev_close_patch(orig_load_prev):
    """Monkey-patch load_prev_close 用 scenario 的 _prev 欄位."""
    def patched(ticker: str):
        # demo 模式統一從 mock client 拿; 找不到時回 None
        snap = _demo_mock_ref.get(str(ticker)) if _demo_mock_ref else None
        if snap and '_prev' in snap:
            return float(snap['_prev'])
        return orig_load_prev(ticker)
    return patched


# 全域 ref 給 patch 用
_demo_mock_ref: dict | None = None


def _build_scenarios() -> list[tuple]:
    """設計 21+ 個 scenarios、覆蓋所有 layout 狀態。

    每個 tuple: (name, force_phase, snaps_dict_with_prev, sort_mode, watch_min_pri,
                trigger_overrides_dict)
    snaps_dict: tk -> {'_prev': float, ...snap fields}
    trigger_overrides: tk -> (trig_key, reason)
    """
    # 預設 prev_close 對照 (來自 HELD/PLAN/WATCH 編輯區附近的合理值)
    PREV = {
        '6285': 312.0, '1605': 40.5, '2885': 59.6, '3481': 58.7,
        '2303': 51.0, '6770': 24.0, '3702': 92.0, '3036': 78.0,
        '2376': 380.0, '8064': 65.0, '6116': 19.5, '6147': 88.0,
        '5351': 42.0, '3006': 110.0, '2344': 28.0, '6207': 127.0,
        '8046': 862.0, '1717': 78.7, '4722': 279.0, '4526': 42.15,
        '4540': 77.3,
    }

    def base(adjust: dict[str, tuple[float, float]] | None = None,
             highlow: dict[str, tuple[float, float]] | None = None) -> dict:
        """生 baseline snapshot dict。adjust: tk -> (open_pct, close_pct) 相對 prev."""
        adjust = adjust or {}
        highlow = highlow or {}
        out: dict[str, dict] = {}
        for tk, prev in PREV.items():
            op_pct, cl_pct = adjust.get(tk, (0.0, 0.0))
            op = round(prev * (1 + op_pct/100), 2)
            cl = round(prev * (1 + cl_pct/100), 2)
            hi, lo = highlow.get(tk, (None, None))
            snap = _mk_snap(prev, op, cl, hi, lo)
            snap['_prev'] = prev
            out[tk] = snap
        return out

    scenarios = []

    # 1. Pre-market: open=close=prev
    snaps = base()
    for tk in snaps:
        snaps[tk]['open'] = 0  # 無開盤
        snaps[tk]['close'] = PREV[tk]
        snaps[tk]['change_price'] = 0
        snaps[tk]['change_rate'] = 0
    scenarios.append(("1. Pre-market 盤前無報價", 1, snaps, 'status', 2, {}))

    # 2. Open normal: 全部 +1~2%
    adj = {tk: (1.0 + (i % 3) * 0.5, 1.5 + (i % 3) * 0.5)
           for i, tk in enumerate(PREV)}
    scenarios.append(("2. Open +1~2% 健康延續", 1, base(adj), 'status', 2, {}))

    # 3. Open gap-up warn: 1605 主候選跳空 +4%
    adj = {tk: (0.5, 1.0) for tk in PREV}
    adj['1605'] = (4.0, 4.2)
    scenarios.append(("3. Gap-up +4% 警示 (紅線#1 邊緣)", 1, base(adj), 'status', 2, {}))

    # 4. Open gap-up skip: 1605 主候選跳空 +6%
    adj = {tk: (0.3, 0.8) for tk in PREV}
    adj['1605'] = (6.0, 6.5)
    scenarios.append(("4. Gap-up +6% Skip (紅線#1 觸發)", 1, base(adj), 'status', 2, {}))

    # 5. Held stop loss approach: 1605 距停損 +0.5%
    # stop=38.75, want close ~ 38.94 → close/prev = 38.94/40.5 ≈ -3.85%
    adj = {tk: (0.5, 0.8) for tk in PREV}
    adj['1605'] = (-2.0, -3.85)
    scenarios.append(("5. 1605 接近停損 (距停 +0.5%)", 2, base(adj), 'status', 2, {}))

    # 6. Held stop loss breach: 1605 跌破停損 38.75 → close=38.5
    adj = {tk: (0.2, 0.5) for tk in PREV}
    adj['1605'] = (-2.5, -4.94)  # 38.5
    scenarios.append(("6. 1605 跌破停損 🔴", 2, base(adj), 'status', 2, {}))

    # 7. Trigger fired: 2885 T1 confirmed (mock override)
    adj = {tk: (0.5, 1.2) for tk in PREV}
    adj['2885'] = (1.0, 3.5)
    trig = {'2885': ('T1', '🟢 強勢延續、外資 +16k 確認')}
    scenarios.append(("7. 2885 T1 confirmed (Stage 2 加碼訊號)", 2, base(adj), 'trigger', 2, trig))

    # 8. TC structure fail: 8064 watch TC 觸發 → excluded
    adj = {tk: (0.3, 0.6) for tk in PREV}
    adj['8064'] = (-1.0, -3.5)
    trig = {'8064': ('TC', '結構底跌破、出場')}
    scenarios.append(("8. 8064 TC 結構失敗 (excluded)", 2, base(adj), 'status', 2, trig))

    # 9. Mixed PnL: 1605 +5% / 2885 +8% / 6285 -2% / 3481 平
    adj = {tk: (0.0, 0.0) for tk in PREV}
    adj['1605'] = (1.0, 5.0)
    adj['2885'] = (2.0, 8.0)
    adj['6285'] = (-0.5, -2.0)
    adj['3481'] = (0.0, 0.2)
    scenarios.append(("9. Mixed PnL (有賺有賠)", 2, base(adj), 'pnl', 2, {}))

    # 10. All green
    adj = {tk: (1.5 + (i % 4), 3.0 + (i % 5)) for i, tk in enumerate(PREV)}
    scenarios.append(("10. 全部綠 (強勢盤)", 2, base(adj), 'pnl', 2, {}))

    # 11. All red
    adj = {tk: (-1.0 - (i % 3), -2.5 - (i % 4)) for i, tk in enumerate(PREV)}
    scenarios.append(("11. 全部紅 (弱勢盤)", 2, base(adj), 'pnl', 2, {}))

    # 12. Watchlist cascade: 3-4 watch 同時 Ch5-3 confirmed
    adj = {tk: (0.5, 1.5) for tk in PREV}
    trig = {
        '2303': ('Ch5-3', '當沖 SOP 確認'),
        '3702': ('Ch5-3', '量價齊揚、突破近 5 日高'),
        '6116': ('Ch5-3', '紅海第二棒、管錢哥進場'),
        '6147': ('Ch5-3', '記憶體封測續強'),
    }
    scenarios.append(("12. Watchlist cascade (4 檔 Ch5-3)", 2, base(adj), 'status', 2, trig))

    # 13. 各 trigger 級別並列
    adj = {tk: (0.3, 0.8) for tk in PREV}
    trig = {
        '2303': ('T1', 'T1 強勢延續'),
        '3702': ('T2', 'T2 反彈訊號'),
        '6116': ('Ch5-3', 'Ch5-3 當沖 SOP'),
        '6147': ('T2_watch', 'T2 watch 觀察中'),
        '8064': ('TC', 'TC 結構失敗'),
    }
    scenarios.append(("13. 各 Trigger 級別並列", 2, base(adj), 'trigger', 2, trig))

    # 14-19. 排序模式輪播
    adj = {tk: (0.5, 1.5 + (i % 5) * 0.6) for i, tk in enumerate(PREV)}
    adj['1605'] = (1.0, 3.0)
    adj['6285'] = (-0.5, -1.5)
    trig_mix = {
        '2885': ('T1', 'T1'),
        '6116': ('Ch5-3', 'Ch5-3'),
        '3702': ('T2', 'T2'),
    }
    for sort in SORT_MODES:
        scenarios.append((f"14-19. 排序模式: {SORT_KEY_LABEL[sort]}",
                          2, base(adj), sort, 2, trig_mix))

    # 20a/b/c. WATCH min priority 1/2/3
    adj = {tk: (0.5, 1.2) for tk in PREV}
    for mp in [1, 2, 3]:
        scenarios.append((f"20. WATCH min priority = {mp}",
                          2, base(adj), 'status', mp, {}))

    # 21. STALE data 警示 — 用 phase2、scenarios 大部分為空模擬 cache stale
    snaps = base({tk: (0.5, 1.0) for tk in PREV})
    # 只保留少數 ticker 有資料、其他清空模擬 stale
    keep = {'1605', '2885'}
    for tk in list(snaps):
        if tk not in keep:
            snaps[tk] = {'_prev': PREV[tk]}  # 無 close
    scenarios.append(("21. STALE data 警示 (大部分 ticker 無報價)",
                      2, snaps, 'status', 2, {}))

    return scenarios


def _run_demo(args):
    """Demo mode entry: 循環顯示所有 scenarios、每 interval 秒切一個。"""
    global _demo_mock_ref

    mock = MockClient()
    scenarios = _build_scenarios()

    # Monkey-patch check_trigger_inline 用 mock.trigger_overrides
    global check_trigger_inline
    orig_check = check_trigger_inline

    def mock_check(ticker: str, tactic: str = '核心') -> tuple[str, str]:
        if ticker in mock.trigger_overrides:
            return mock.trigger_overrides[ticker]
        return 'none', ''
    check_trigger_inline = mock_check

    # Monkey-patch load_prev_close 用 scenario 的 _prev 欄位
    global load_prev_close
    orig_load = load_prev_close
    load_prev_close = _demo_load_prev_close_patch(orig_load)

    # Monkey-patch notify (demo 不真的通知)
    global maybe_notify_trigger, notify_mac
    maybe_notify_trigger = lambda *a, **kw: None
    notify_mac = lambda *a, **kw: None

    # 啟動 keyboard listener (q 退出 + arrow key 切 scenario)
    _demo_total[0] = len(scenarios)
    _demo_idx[0] = 0
    _demo_paused[0] = True  # 預設暫停 auto-cycle
    kb_thread = threading.Thread(target=_kb_listener, kwargs={'demo_mode': True}, daemon=True)
    kb_thread.start()

    console = Console()
    do_notify = False
    prev_prices: dict = {}
    notified: set = set()

    def _build_demo_frame() -> Group:
        idx = _demo_idx[0]
        name, phase, snaps, sort_mode, _min_pri, _trig = scenarios[idx]
        now = datetime.now()
        now_str = now.strftime('%H:%M:%S')

        pause_tag = "⏸ paused" if _demo_paused[0] else f"▶ auto {args.interval}s"
        header = Text()
        header.append(f"=== DEMO MODE  {now_str} === ", style="bold magenta")
        header.append(f"[Scenario {idx+1}/{len(scenarios)}: {name}]  ", style="bold yellow")
        header.append(f"({pause_tag})", style="cyan")
        hint = Text(
            "← → 切換 | home/0 首個 | end 末個 | space 切 auto-cycle | q 退出 | "
            f"Phase {phase}",
            style="dim",
        )

        if phase == 1:
            content = render_phase1_screener(mock, now_str, sort_mode, do_notify)
        else:
            content = render_phase2_holdings(
                mock, now_str, prev_prices, notified, sort_mode, do_notify
            )

        footer = Text(
            f"sort={sort_mode} | watch-limit={_watch_limit[0]}",
            style="dim",
        )
        return Group(header, hint, content, footer)

    def _apply_current():
        idx = _demo_idx[0]
        name, phase, snaps, sort_mode, min_pri, trig = scenarios[idx]
        global _demo_mock_ref
        mock.scenario = snaps
        mock.trigger_overrides = trig
        _demo_mock_ref = snaps
        _watch_min_priority[0] = min_pri
        _current_sort[0] = sort_mode

    # 預先套用第一個 scenario、避免初始 frame 顯示空資料
    _apply_current()

    try:
        with Live(
            _build_demo_frame(),
            console=console,
            screen=not args.no_clear,
            refresh_per_second=2,
            transient=False,
            redirect_stdout=False,
            redirect_stderr=False,
        ) as live:
            while not _quit_flag[0]:
                _apply_current()
                live.update(_build_demo_frame())

                _elapsed = 0.0
                _step = 0.3
                while not _quit_flag[0]:
                    time.sleep(_step)
                    _elapsed += _step
                    # 手動切換 (左/右/home/end/space) → 立刻 re-render + 重設 timer
                    if _demo_jump[0]:
                        _demo_jump[0] = False
                        break
                    # auto-cycle (非 paused) → 到 interval 推下一個
                    if (not _demo_paused[0]) and _elapsed >= args.interval:
                        _demo_idx[0] = (_demo_idx[0] + 1) % len(scenarios)
                        break
                    # 持續刷新時鐘
                    live.update(_build_demo_frame())
    finally:
        _quit_flag[0] = True
        # 還原 patch (測試友善)
        check_trigger_inline = orig_check
        load_prev_close = orig_load
        print(f"Demo 結束 (跑了 {_scenario_idx[0]+1} / {len(scenarios)} scenarios)")


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--interval',    type=int, default=30)
    p.add_argument('--no-clear',    action='store_true')
    p.add_argument('--no-notify',   action='store_true')
    p.add_argument('--force-phase', choices=['1', '2'], help='強制階段、debug 用')
    p.add_argument('--sort', choices=SORT_MODES, default='status',
                   help='初始排序模式 (status/priority/risk/trigger/pnl/sector)')
    p.add_argument('--watch-min-priority', type=int, default=2,
                   choices=[1, 2, 3],
                   help='開盤前 WATCH 顯示門檻 (1=全顯/2=預設/3=只看核心)')
    p.add_argument('--demo', action='store_true',
                   help='Demo 模式: 循環顯示所有 mock scenarios、驗證 layout')
    p.add_argument('--watch-limit', type=int, default=8,
                   help='WATCH 觀察可能段最多顯示 N 檔 (預設 8、超過 collapse、0=不限)')
    args = p.parse_args()
    _watch_min_priority[0] = args.watch_min_priority
    _watch_limit[0] = args.watch_limit

    _current_sort[0] = args.sort
    do_notify = not args.no_notify

    # Demo 模式: 不連 Fubon、跑 mock scenarios
    if args.demo:
        _run_demo(args)
        return

    # StageTrigger 載入狀態
    trigger_ok = _stage_engine is not None

    rest_client = FubonClient()

    # 收集所有 tickers (HELD + PLAN_PRIMARY + PLAN_BACKUP + WATCH) 給 WS 訂閱
    _all_tk = set()
    for src in [HELD, PLAN_PRIMARY, PLAN_BACKUP, WATCH]:
        for it in src:
            if isinstance(it, dict) and it.get('ticker'):
                _all_tk.add(str(it['ticker']))
            elif isinstance(it, (tuple, list)) and len(it) > 0:
                _all_tk.add(str(it[0]))

    print(f"初始化 WSPriceCache、訂閱 {len(_all_tk)} 檔...", flush=True)
    _cache = WSPriceCache(rest_client, list(_all_tk))
    print(f"  WS 連線: {'OK' if _cache.ws_ok else 'FAIL — 將全程 REST fallback'}", flush=True)
    print(f"  Warm cache: {len(_cache.cache)} 檔", flush=True)

    # client 給 render 用、實際走 cache (內含 stale fallback)
    client = _cache
    prev_prices: dict = {}
    notified:    set  = set()

    use_alt = not args.no_clear

    kb_thread = threading.Thread(target=_kb_listener, daemon=True)
    kb_thread.start()

    console = Console()

    def _build_frame() -> Group:
        """組整個 frame: header + content panel + footer。"""
        now = datetime.now()
        now_str = now.strftime('%H:%M:%S')
        h, m = now.hour, now.minute

        in_phase1 = h == 9 and m <= 25
        if args.force_phase == '1':
            in_phase1 = True
        elif args.force_phase == '2':
            in_phase1 = False

        sort_mode = _current_sort[0]

        # Header
        header = Text()
        header.append(f"=== 即時 monitor (interval {args.interval}s)  {now_str} === ",
                      style="bold blue")
        if trigger_ok:
            header.append("StageTrigger OK", style="green")
        else:
            header.append("StageTrigger unavailable", style="red")
        # WS cache stats
        try:
            tot, stale, errs = _cache.stats()
            header.append(f"  [WS cache {tot}, stale {stale}, err {errs}]",
                          style="dim")
        except Exception:
            pass

        hint = Text(
            "快捷鍵: 1=status(分段) 2=priority 3=risk 4=trigger 5=pnl 6=sector q=退出",
            style="dim",
        )

        if in_phase1:
            content = render_phase1_screener(client, now_str, sort_mode, do_notify)
        else:
            content = render_phase2_holdings(
                client, now_str, prev_prices, notified, sort_mode, do_notify
            )

        footer = Text(
            f"下次 {args.interval}s | 排序 [{sort_mode}] | Ctrl+C 或 q 結束",
            style="dim",
        )
        return Group(header, hint, content, footer)

    try:
        # rich.Live: refresh_per_second 控制 render 頻率、screen=True 用 alt-screen
        with Live(
            _build_frame(),
            console=console,
            screen=use_alt,
            refresh_per_second=2,
            transient=False,
            redirect_stdout=False,
            redirect_stderr=False,
        ) as live:
            while not _quit_flag[0]:
                try:
                    live.update(_build_frame())
                    # 細粒度 sleep、q 鍵 / sort 切換立即跳出
                    _elapsed = 0.0
                    _step = 0.3
                    _prev_sort = _current_sort[0]
                    while _elapsed < args.interval and not _quit_flag[0]:
                        time.sleep(_step)
                        _elapsed += _step
                        if _current_sort[0] != _prev_sort:
                            break
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    # 錯誤直接 log 到 frame、不退出
                    try:
                        live.update(Text(f"[ERROR] {e}", style="red"))
                    except Exception:
                        pass
                    time.sleep(5)
    finally:
        _quit_flag[0] = True
        print("結束")


if __name__ == '__main__':
    main()
