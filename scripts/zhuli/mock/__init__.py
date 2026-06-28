"""Mock server for FubonClient + FinMind API.

替代真實 client、replay historical data 給 monitor 收、用於自動化測試 detector 燈號。

Components:
  data_provider.py    - 從 DB 讀 historical bar、resample tick stream
  fubon_mock.py       - MockFubonClient (drop-in for FubonClient)
  replay_engine.py    - tick-by-tick replay、speed control
  scenario_loader.py  - 讀 catalog scenarios + expected outcomes
  trigger_recorder.py - log monitor 各 trigger 燈號 fire time
  test_runner.py      - CLI: run scenario + 比對 actual vs expected
"""
from .fubon_mock import MockFubonClient
from .replay_engine import ReplayEngine
from .data_provider import DataProvider

__all__ = ['MockFubonClient', 'ReplayEngine', 'DataProvider']

