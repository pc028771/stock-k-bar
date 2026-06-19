"""Normalized data contracts for market data clients.

僅保留 `SnapshotDict` TypedDict — stock-k-bar 程式碼到處 hardcode 假設這個
schema (見 `intraday_scanner.py` / `watchlist_intraday.py` 註解)、新 client 必
須完全相同 schema、不能改 key 名稱、不能改單位。

  - `total_volume` 單位 = 張 (1 張 = 1000 股)、Fubon 原始回傳是股、需 ÷1000
  - `change_rate` 單位 = %（e.g. -1.5 = -1.5%）

舊版 `MarketDataClient` ABC 與 `FailoverClient` 從未在 stock-k-bar 被 import、
故不保留 (見 decoupling plan §3 audit 結果)。
"""
from __future__ import annotations

from typing import TypedDict


class SnapshotDict(TypedDict, total=False):
    """即時快照 normalized 契約。所有 client (Fubon / Mock / FinMind) 須對齊。"""
    close: float
    open: float
    high: float
    low: float
    change_price: float    # 漲跌金額
    change_rate: float     # 漲跌幅 %（e.g. -1.5 = -1.5%）
    total_volume: int      # 當日累積量（張、1 張 = 1000 股）
    total_amount: float    # 當日累積金額
    volume_ratio: float    # 量比 (optional)
