"""台股交易日曆工具 — 使用 FinMind TaiwanStockTradingDate."""
from __future__ import annotations

import sys
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Optional

_common_parent = Path(__file__).parent.parent  # scripts/
if str(_common_parent) not in sys.path:
    sys.path.insert(0, str(_common_parent))
from common.finmind_client import get_client


@lru_cache(maxsize=4)
def _fetch_trading_dates(year_month: str) -> list[str]:
    """從 FinMind 抓指定月份附近的交易日，結果快取（同 process 內）."""
    start = year_month + "-01"
    # 抓前後各一個月，確保跨月邊界也能找到前一個交易日
    from datetime import datetime, timedelta
    dt = datetime.strptime(start, "%Y-%m-%d")
    range_start = (dt - timedelta(days=40)).strftime("%Y-%m-%d")
    range_end   = (dt + timedelta(days=40)).strftime("%Y-%m-%d")
    df = get_client().fetch_dataset(
        dataset="TaiwanStockTradingDate",
        start_date=range_start,
        end_date=range_end,
        bypass_cache=True,
    )
    data = df.to_dict("records") if not df.empty else []
    return sorted(d["date"] for d in data)


def get_trading_dates(start: str, end: str) -> list[str]:
    """回傳 [start, end] 之間的所有交易日（含頭尾）."""
    df = get_client().fetch_dataset(
        dataset="TaiwanStockTradingDate",
        start_date=start,
        end_date=end,
        bypass_cache=True,
    )
    data = df.to_dict("records") if not df.empty else []
    return sorted(d["date"] for d in data)


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
