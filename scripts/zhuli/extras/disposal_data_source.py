"""extras.disposal_data_source — 抓 TWSE/TPEx 處置股公告清單（課程外資料源）.

預設 OFF，由 daily_scanner_job.py --enable-disposal 啟用。

公開 API 不需要帳號：
  TWSE: https://www.twse.com.tw/rwd/zh/announcement/punish
  TPEx: 目前以 TWSE 為主（TPEx 沒有穩定 JSON endpoint）

回傳格式:
  {
    "3189": {
        "ticker": "3189",
        "name": "景碩",
        "start_date": "2026-05-28",   # 處置生效日
        "end_date": "2026-06-10",     # 處置到期日
        "announce_date": "2026-05-27",
        "t_minus_1": "2026-05-27",    # 處置前一天（= announce_date）
        "times": 1,                   # 第幾次進處置（累計）
        "reason": "連續三次",
        "source": "TWSE",
    },
    ...
  }
"""
from __future__ import annotations

import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

_common_parent = Path(__file__).parent.parent.parent  # scripts/
if str(_common_parent) not in sys.path:
    sys.path.insert(0, str(_common_parent))
from common.finmind_client import get_client

# TWSE 公告端點（免登入 JSON）
_TWSE_URL = "https://www.twse.com.tw/rwd/zh/announcement/punish"
_TIMEOUT = 10  # seconds
_MAX_RETRIES = 3

# FinMind fallback (sponsor tier)
_FINMIND_DATASET = "TaiwanStockDispositionSecuritiesPeriod"

_CHINESE_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _parse_times_from_measure(measure: str) -> int:
    """從 '第二次處置' / '第一次處置' 解出整數."""
    m = re.search(r"第([一二三四五六七八九]|\d+)次", measure or "")
    if not m:
        return 1
    s = m.group(1)
    if s.isdigit():
        return int(s)
    return _CHINESE_NUM.get(s, 1)


def _fetch_finmind_raw(start_date: str, end_date: str) -> list[dict]:
    """從 FinMind 抓處置股 (TWSE fallback).

    Returns: list of normalized dicts (same shape as _fetch_twse_raw output).
    Raises RuntimeError on failure.
    """
    try:
        df = get_client().fetch_dataset(
            dataset=_FINMIND_DATASET,
            start_date=start_date,
            end_date=end_date,
            bypass_cache=True,
        )
    except Exception as exc:
        raise RuntimeError(f"FinMind 處置股 API 失敗: {exc}")

    rows = []
    for row in (df.to_dict("records") if not df.empty else []):
        try:
            rows.append({
                "announce_date": row["date"],
                "ticker":        str(row["stock_id"]).strip(),
                "name":          str(row.get("stock_name", "")).strip(),
                "times":         _parse_times_from_measure(row.get("measure", "")),
                "reason":        str(row.get("condition", "")).strip(),
                "start_date":    row["period_start"],
                "end_date":      row["period_end"],
            })
        except Exception:
            continue
    return rows


def _roc_to_iso(roc_date_str: str) -> str:
    """將民國年日期 '115/05/28' 轉成西元 '2026-05-28'."""
    parts = roc_date_str.strip().split("/")
    if len(parts) != 3:
        raise ValueError(f"無法解析民國日期: {roc_date_str!r}")
    year = int(parts[0]) + 1911
    return f"{year}-{int(parts[1]):02d}-{int(parts[2]):02d}"


def _parse_range(range_str: str) -> tuple[str, str]:
    """解析 '115/05/28～115/06/10' → ('2026-05-28', '2026-06-10')."""
    parts = range_str.strip().split("～")
    if len(parts) != 2:
        raise ValueError(f"無法解析處置起迄: {range_str!r}")
    return _roc_to_iso(parts[0]), _roc_to_iso(parts[1])


def _fetch_twse_raw(start_date: str, end_date: str) -> list[dict]:
    """從 TWSE 抓原始處置股清單.

    Args:
        start_date: 'YYYY-MM-DD'
        end_date:   'YYYY-MM-DD'

    Returns:
        list of raw row dicts with keys:
          announce_date, ticker, name, times, reason, start_date, end_date
    """
    # TWSE 接受 startDate=YYYYMMDD endDate=YYYYMMDD
    params = {
        "startDate": start_date.replace("-", ""),
        "endDate":   end_date.replace("-", ""),
    }
    _HEADERS = {
        "Accept": "application/json, text/javascript, */*",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.twse.com.tw/",
    }
    last_exc: Optional[Exception] = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(
                _TWSE_URL, params=params, timeout=_TIMEOUT,
                headers=_HEADERS,
            )
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES - 1:
                import time; time.sleep(2 ** attempt)
    else:
        raise RuntimeError(f"TWSE 處置股 API 失敗（{_MAX_RETRIES} 次重試）: {last_exc}")

    if data.get("stat") != "OK":
        raise RuntimeError(f"TWSE stat != OK: {data.get('stat')}")

    # fields: ['編號','公布日期','證券代號','證券名稱','累計','處置條件','處置起迄時間','處置措施','處置內容','備註']
    rows = []
    for row in data.get("data", []):
        if len(row) < 7:
            continue
        try:
            announce = _roc_to_iso(str(row[1]))
            ticker   = str(row[2]).strip()
            name     = str(row[3]).strip()
            times    = int(row[4]) if row[4] else 1
            reason   = str(row[5]).strip()
            s_date, e_date = _parse_range(str(row[6]))
            rows.append({
                "announce_date": announce,
                "ticker":        ticker,
                "name":          name,
                "times":         times,
                "reason":        reason,
                "start_date":    s_date,
                "end_date":      e_date,
            })
        except Exception:
            continue

    return rows


def fetch_disposal_list(
    target_date: str,
    lookback_days: int = 30,
) -> dict[str, dict]:
    """取得目標日期當天「處置中」的所有股票.

    處置中 = start_date <= target_date <= end_date

    Args:
        target_date:    'YYYY-MM-DD'，通常是今天盤後
        lookback_days:  往前查幾天的公告（確保抓到尚在有效期的舊公告）

    Returns:
        dict[ticker, info_dict]，ticker 為字串代號。
        若 TWSE API 不可用則 raise RuntimeError（主流程需 catch）。
    """
    target = datetime.strptime(target_date, "%Y-%m-%d").date()
    start_query = (target - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end_query   = target.strftime("%Y-%m-%d")

    # 先試 TWSE、失敗 fallback 到 FinMind
    source = "TWSE"
    try:
        raw_rows = _fetch_twse_raw(start_query, end_query)
    except RuntimeError as twse_exc:
        try:
            raw_rows = _fetch_finmind_raw(start_query, end_query)
            source = "FinMind"
            print(f"  [disposal] ⚠️ TWSE 失敗、改用 FinMind fallback ({len(raw_rows)} rows): {twse_exc}")
        except RuntimeError as fm_exc:
            raise RuntimeError(f"TWSE + FinMind 都失敗: TWSE={twse_exc} | FinMind={fm_exc}")

    result: dict[str, dict] = {}
    for row in raw_rows:
        try:
            s = datetime.strptime(row["start_date"], "%Y-%m-%d").date()
            e = datetime.strptime(row["end_date"],   "%Y-%m-%d").date()
        except ValueError:
            continue

        # 只保留目標日期仍在處置期間的
        if not (s <= target <= e):
            continue

        ticker = row["ticker"]
        # 重複 ticker（同一期）只保留最新公告（announce_date 最大）
        if ticker in result:
            existing_announce = result[ticker]["announce_date"]
            if row["announce_date"] <= existing_announce:
                continue

        # t_minus_1 = 處置生效日前一個日曆日
        # 注意：TWSE announce_date 就是公告日，通常等於 T-1（處置前一天）
        t_minus_1 = row["announce_date"]

        result[ticker] = {
            "ticker":        ticker,
            "name":          row["name"],
            "start_date":    row["start_date"],
            "end_date":      row["end_date"],
            "announce_date": row["announce_date"],
            "t_minus_1":     t_minus_1,
            "times":         row["times"],
            "reason":        row["reason"],
            "source":        source,
        }

    return result
