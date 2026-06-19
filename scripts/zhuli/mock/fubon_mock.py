"""MockFubonClient — drop-in replacement for FubonClient.

Surface 兼容:
  - get_realtime_snapshot(stock_id) → SnapshotDict
  - subscribe_quotes(stock_ids, callback) → 模擬 WS push (用 ReplayEngine 驅動)
  - stats() → (subscribed_count, ws_msgs_recv, ws_msgs_sent)

時間透過 set_clock(time) 切換、不是 datetime.now()、確保測試 deterministic。
"""
from __future__ import annotations
from datetime import datetime, time
from typing import Callable, Optional

from .data_provider import DataProvider, TickerDayData, TickSnapshot


class MockFubonClient:
    """Mimics FubonClient public API、但資料來自 DataProvider replay。"""

    def __init__(self, data_provider: DataProvider, target_date: str):
        self.dp = data_provider
        self.target_date = target_date
        self._current_time: time = time(9, 0)
        self._subscribed: set[str] = set()
        self._callbacks: list[Callable] = []
        self._ws_recv = 0
        self._ws_sent = 0
        self._day_cache: dict[str, Optional[TickerDayData]] = {}

    def set_clock(self, t: time) -> None:
        """Advance simulated clock。"""
        self._current_time = t

    def now(self) -> time:
        return self._current_time

    def _day(self, ticker: str) -> Optional[TickerDayData]:
        if ticker not in self._day_cache:
            self._day_cache[ticker] = self.dp.get_day(ticker, self.target_date)
        return self._day_cache[ticker]

    def get_realtime_snapshot(self, stock_id: str) -> Optional[dict]:
        """Return SnapshotDict cumulative up to current time."""
        stock_id = str(stock_id)
        # TAIEX 特殊處理 (用 daily K + simulated intraday curve)
        if stock_id == 'TAIEX':
            return self._taiex_snapshot()
        day = self._day(stock_id)
        if not day:
            return None
        snap = day.snapshot_at(self._current_time)
        if not snap:
            return None
        return {
            'close': snap.close,
            'open': snap.open,
            'high': snap.high,
            'low': snap.low,
            'change_price': snap.change_price,
            'change_rate': snap.change_rate,
            'total_volume': snap.total_volume,
            'total_amount': snap.total_amount,
        }

    def _taiex_snapshot(self) -> Optional[dict]:
        """簡化 TAIEX snapshot: 用 daily close (跑完整天當作 close、否則用 prev_close)。"""
        bar = self.dp.get_daily_bar('TAIEX', self.target_date)
        if not bar:
            return None
        prev = self.dp._conn().execute(
            "SELECT close FROM standard_daily_bar WHERE ticker='TAIEX' AND trade_date<? "
            "ORDER BY trade_date DESC LIMIT 1", (self.target_date,)
        ).fetchone()
        prev_close = prev[0] if prev else bar['open']
        # 簡化: 13:30 後返回真實 close、否則線性插值
        if self._current_time >= time(13, 30):
            close = bar['close']
            high = bar['high']
            low = bar['low']
        else:
            # 簡化線性: open → close 隨時間
            mins_total = (13 * 60 + 30) - 9 * 60  # 270
            mins_now = (self._current_time.hour * 60 + self._current_time.minute) - 9 * 60
            t = max(0, min(1, mins_now / mins_total))
            close = bar['open'] + (bar['close'] - bar['open']) * t
            high = max(bar['open'], close)
            low = min(bar['open'], close)
        chg_p = close - prev_close
        chg_r = chg_p / prev_close * 100 if prev_close else 0
        return {
            'close': close, 'open': bar['open'], 'high': high, 'low': low,
            'change_price': chg_p, 'change_rate': chg_r,
            'total_volume': 0, 'total_amount': 0,
        }

    def subscribe_quotes(self, stock_ids: list[str], callback: Optional[Callable] = None) -> None:
        """Register subscribed tickers。ReplayEngine 驅動推送。"""
        for tk in stock_ids:
            self._subscribed.add(str(tk))
        if callback:
            self._callbacks.append(callback)

    def _emit_tick(self, ticker: str) -> None:
        """ReplayEngine 呼叫: 推送一個 tick 給 callbacks。"""
        snap = self.get_realtime_snapshot(ticker)
        if not snap:
            return
        self._ws_sent += 1
        for cb in self._callbacks:
            try:
                cb(ticker, snap)
            except Exception:
                pass

    def stats(self) -> tuple[int, int, int]:
        return (len(self._subscribed), self._ws_recv, self._ws_sent)

    # 其他可能 surface (返回 None / no-op 即可)
    def get_price(self, *a, **kw):
        return None

    def get_institutional(self, *a, **kw):
        return None
