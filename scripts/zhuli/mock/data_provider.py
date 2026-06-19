"""Data provider — 從 DB 讀 historical 1分K、模擬 tick-by-tick snapshot stream.

每個 ticker 對應一個 day 的 1分K bars (e.g. 9:00-13:30 = 270 個 1分 bars)、
轉為 cumulative snapshot (累加 high/low/close/volume) 模擬實時 API 回傳。
"""
from __future__ import annotations
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Optional

_DB = Path.home() / ".four_seasons" / "data.sqlite"


@dataclass
class TickSnapshot:
    """模擬 FubonClient.get_realtime_snapshot return."""
    ticker: str
    timestamp: datetime
    open: float
    high: float        # cumulative high (max so far this day)
    low: float         # cumulative low
    close: float       # latest close (last bar)
    change_price: float
    change_rate: float
    total_volume: int  # cumulative volume (lots)
    total_amount: float  # cumulative amount


@dataclass
class TickerDayData:
    """一個 ticker 一天的 minute bars + prev_close."""
    ticker: str
    target_date: str
    prev_close: float
    bars: list[dict] = field(default_factory=list)  # [{minute, open, high, low, close, volume}, ...]

    def snapshot_at(self, target_time: time) -> Optional[TickSnapshot]:
        """模擬到 target_time 為止的累加 snapshot (cumulative high/low/vol)."""
        relevant = [b for b in self.bars if _parse_time(b['minute']) <= target_time]
        if not relevant:
            return None
        opens = relevant[0]['open']
        highs = max(b['high'] for b in relevant)
        lows = min(b['low'] for b in relevant)
        close = relevant[-1]['close']
        vol = sum(b['volume'] for b in relevant)
        amount = sum(b['close'] * b['volume'] for b in relevant)
        chg_p = close - self.prev_close
        chg_r = chg_p / self.prev_close * 100 if self.prev_close else 0
        return TickSnapshot(
            ticker=self.ticker,
            timestamp=datetime.combine(_parse_date(self.target_date), target_time),
            open=opens, high=highs, low=lows, close=close,
            change_price=chg_p, change_rate=chg_r,
            total_volume=vol // 1000,
            total_amount=amount * 1000,
        )


def _parse_time(s: str) -> time:
    """Parse 'HH:MM' or '13:30' or full datetime str."""
    if ' ' in s:
        s = s.split(' ')[1]
    parts = s.split(':')
    return time(int(parts[0]), int(parts[1]))


def _parse_date(s: str):
    from datetime import date
    return date.fromisoformat(s)


class DataProvider:
    """從 DB 讀 historical data、build TickerDayData。"""

    def __init__(self, db_path: Path = _DB):
        self.db_path = db_path
        self._con: Optional[sqlite3.Connection] = None
        self._cache: dict[tuple[str, str], TickerDayData] = {}

    def _conn(self):
        if self._con is None:
            self._con = sqlite3.connect(str(self.db_path))
        return self._con

    def get_day(self, ticker: str, target_date: str) -> Optional[TickerDayData]:
        """Load 1分K bars for ticker on target_date + prev_close."""
        key = (ticker, target_date)
        if key in self._cache:
            return self._cache[key]
        con = self._conn()
        # prev_close from daily
        r = con.execute(
            "SELECT close FROM standard_daily_bar WHERE ticker=? AND trade_date<? "
            "ORDER BY trade_date DESC LIMIT 1", (ticker, target_date)
        ).fetchone()
        if not r:
            return None
        prev_close = r[0]
        # 1m bars
        rows = con.execute(
            "SELECT trade_datetime, open, high, low, close, volume FROM stock_minute_kbar "
            "WHERE ticker=? AND trade_datetime LIKE ? ORDER BY trade_datetime",
            (ticker, f"{target_date}%")
        ).fetchall()
        if not rows:
            return None
        bars = [
            {'minute': r[0], 'open': r[1], 'high': r[2], 'low': r[3], 'close': r[4], 'volume': r[5]}
            for r in rows
        ]
        d = TickerDayData(ticker=ticker, target_date=target_date, prev_close=prev_close, bars=bars)
        self._cache[key] = d
        return d

    def get_daily_bar(self, ticker: str, target_date: str) -> Optional[dict]:
        """Get full daily bar for date (for daily detectors)."""
        con = self._conn()
        r = con.execute(
            "SELECT open, high, low, close, volume, ma5, ma10, ma20, ma60 "
            "FROM standard_daily_bar WHERE ticker=? AND trade_date=?",
            (ticker, target_date)
        ).fetchone()
        if not r:
            return None
        return {'open': r[0], 'high': r[1], 'low': r[2], 'close': r[3],
                'volume': r[4], 'ma5': r[5], 'ma10': r[6], 'ma20': r[7], 'ma60': r[8]}

    def close(self):
        if self._con:
            self._con.close()
            self._con = None
