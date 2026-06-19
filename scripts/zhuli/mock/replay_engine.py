"""ReplayEngine — drive simulated clock through trading day、push tick events.

Tick interval:
  - real-time: 1 tick / 5 sec (近似 FubonClient 5-10 秒延遲)
  - test mode: 1 tick / 1 ms (1 day in < 1 sec、超快測試)

Sequence:
  09:00 → 09:01 → ... → 13:30

每 tick:
  1. 推進 mock client clock
  2. 對 subscribed tickers 觸發 callback
  3. 給 monitor 機會 evaluate trigger
"""
from __future__ import annotations
import time as _time
from datetime import time, timedelta, datetime
from typing import Callable, Optional

from .fubon_mock import MockFubonClient


class ReplayEngine:
    """Drive simulated time through a trading day."""

    def __init__(self, mock_client: MockFubonClient,
                 start_time: time = time(9, 0),
                 end_time: time = time(13, 30),
                 tick_seconds: int = 60,
                 sleep_ms: float = 0):
        """
        Args:
            mock_client: MockFubonClient instance
            start_time: replay start (09:00 default)
            end_time: replay end (13:30 default)
            tick_seconds: simulated seconds per tick (60 = minute-level)
            sleep_ms: real-world ms to sleep between ticks (0 = max speed)
        """
        self.client = mock_client
        self.start_time = start_time
        self.end_time = end_time
        self.tick_seconds = tick_seconds
        self.sleep_ms = sleep_ms
        self._tick_callbacks: list[Callable[[time], None]] = []
        self._post_tick_callbacks: list[Callable[[time], None]] = []

    def on_tick(self, cb: Callable[[time], None]):
        """Register callback called BEFORE push (e.g. update monitor state)."""
        self._tick_callbacks.append(cb)

    def on_post_tick(self, cb: Callable[[time], None]):
        """Register callback called AFTER push (e.g. record trigger state)."""
        self._post_tick_callbacks.append(cb)

    def run(self) -> int:
        """Run replay loop. Return tick count."""
        current = datetime.combine(datetime.today(), self.start_time)
        end = datetime.combine(datetime.today(), self.end_time)
        tick_delta = timedelta(seconds=self.tick_seconds)
        n_ticks = 0

        while current.time() <= self.end_time:
            self.client.set_clock(current.time())

            # pre-tick callbacks (e.g. monitor update)
            for cb in self._tick_callbacks:
                try:
                    cb(current.time())
                except Exception as e:
                    print(f"[replay] tick callback error: {e}")

            # push to subscribed callbacks via mock client
            for tk in list(self.client._subscribed):
                self.client._emit_tick(tk)

            # post-tick callbacks (e.g. snapshot trigger state)
            for cb in self._post_tick_callbacks:
                try:
                    cb(current.time())
                except Exception as e:
                    print(f"[replay] post-tick callback error: {e}")

            n_ticks += 1
            if self.sleep_ms > 0:
                _time.sleep(self.sleep_ms / 1000)

            current += tick_delta
            if current > end:
                break

        return n_ticks
