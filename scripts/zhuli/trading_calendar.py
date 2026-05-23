"""台股交易日曆工具 — 使用 FinMind TaiwanStockTradingDate."""
from __future__ import annotations

import os
from datetime import date
from functools import lru_cache
from typing import Optional

import requests


FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"


@lru_cache(maxsize=4)
def _fetch_trading_dates(year_month: str) -> list[str]:
    """從 FinMind 抓指定月份附近的交易日，結果快取（同 process 內）."""
    token = os.environ.get("FINMIND_TOKEN", "")
    start = year_month + "-01"
    # 抓前後各一個月，確保跨月邊界也能找到前一個交易日
    from datetime import datetime, timedelta
    dt = datetime.strptime(start, "%Y-%m-%d")
    range_start = (dt - timedelta(days=40)).strftime("%Y-%m-%d")
    range_end   = (dt + timedelta(days=40)).strftime("%Y-%m-%d")
    r = requests.get(FINMIND_URL, params={
        "dataset": "TaiwanStockTradingDate",
        "start_date": range_start,
        "end_date": range_end,
        "token": token,
    }, timeout=15)
    data = r.json().get("data", [])
    return sorted(d["date"] for d in data)


def get_trading_dates(start: str, end: str) -> list[str]:
    """回傳 [start, end] 之間的所有交易日（含頭尾）."""
    token = os.environ.get("FINMIND_TOKEN", "")
    r = requests.get(FINMIND_URL, params={
        "dataset": "TaiwanStockTradingDate",
        "start_date": start,
        "end_date": end,
        "token": token,
    }, timeout=15)
    return sorted(d["date"] for d in r.json().get("data", []))


def is_trading_day(d: str) -> bool:
    """判斷指定日期是否為交易日."""
    dates = get_trading_dates(d, d)
    return d in dates


def prev_trading_day(d: str) -> Optional[str]:
    """回傳 d 之前最近的交易日（不含 d 本身）."""
    from datetime import datetime, timedelta
    dt = datetime.strptime(d, "%Y-%m-%d")
    start = (dt - timedelta(days=14)).strftime("%Y-%m-%d")
    end   = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
    dates = get_trading_dates(start, end)
    return dates[-1] if dates else None


def next_trading_day(d: str) -> Optional[str]:
    """回傳 d 之後最近的交易日（不含 d 本身）."""
    from datetime import datetime, timedelta
    dt = datetime.strptime(d, "%Y-%m-%d")
    start = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
    end   = (dt + timedelta(days=14)).strftime("%Y-%m-%d")
    dates = get_trading_dates(start, end)
    return dates[0] if dates else None


if __name__ == "__main__":
    today = date.today().isoformat()
    print(f"今天 {today} 是交易日: {is_trading_day(today)}")
    print(f"上一個交易日: {prev_trading_day(today)}")
    print(f"下一個交易日: {next_trading_day(today)}")
