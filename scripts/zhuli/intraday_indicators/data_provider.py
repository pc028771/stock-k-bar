"""compose_trigger 用的資料 provider — cached 1m K / daily / 昨日漲停。

設計目標：
- 1m K 抓取昂貴（FinMind API）、必須 cache
- daily closes 從本地 DB 快、但仍 cache 減少 sqlite 開銷
- 黃大 60m DIF 需 ≥ 5 個交易日 1m K（EMA-26）、所以 trailing 抓 7 天

cache 策略：
- 1m K today：30 秒 TTL（盤中持續更新）
- 1m K prev N days：當日不變、無 TTL（首次抓後 lock）
- daily closes：30 分鐘 TTL（盤中只用收盤、變化慢）
- 昨日漲停旗標：當日不變、無 TTL
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

# Reuse intraday_stage_helper's path setup
_HERE = Path(__file__).parent
_REPO = _HERE.parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ── 內部 cache ──────────────────────────────────────────────────────────────


_k1m_today_cache: dict[str, tuple[datetime, pd.DataFrame]] = {}
_k1m_prev_cache: dict[str, pd.DataFrame] = {}
_daily_cache: dict[str, tuple[datetime, pd.Series]] = {}
_limit_up_cache: dict[str, bool] = {}

K1M_TODAY_TTL_SEC = 30
DAILY_TTL_SEC = 30 * 60


def _now() -> datetime:
    return datetime.now()


# ── 1m K 抓取 ────────────────────────────────────────────────────────────────


def get_k1m_today(ticker: str, target_date: Optional[date] = None) -> pd.DataFrame:
    """抓當日 1m K、30 秒 cache。"""
    target_date = target_date or date.today()
    key = f"{ticker}:{target_date.isoformat()}"
    now = _now()
    cached = _k1m_today_cache.get(key)
    if cached and (now - cached[0]).total_seconds() < K1M_TODAY_TTL_SEC:
        return cached[1]

    try:
        from zhuli.intraday_stage_helper import _fetch_finmind_1m
        df = _fetch_finmind_1m(ticker, target_date.isoformat())
    except Exception:
        df = pd.DataFrame()

    _k1m_today_cache[key] = (now, df)
    return df


def get_k1m_prev_days(
    ticker: str,
    target_date: Optional[date] = None,
    days: int = 7,
) -> pd.DataFrame:
    """抓 N 個交易日（trailing）的 1m K、當日不變、無 TTL。

    用於 60m / 30m DIF 的 EMA 暖機。
    """
    target_date = target_date or date.today()
    key = f"{ticker}:{target_date.isoformat()}:{days}"
    if key in _k1m_prev_cache:
        return _k1m_prev_cache[key]

    frames = []
    try:
        from zhuli.intraday_stage_helper import _fetch_finmind_1m
        d = target_date - timedelta(days=1)
        fetched = 0
        # 容許週末 / 假日跳過、最多 days * 2 個日歷日嘗試
        for _ in range(days * 2):
            if fetched >= days:
                break
            if d.weekday() < 5:  # mon-fri
                df = _fetch_finmind_1m(ticker, d.isoformat())
                if not df.empty:
                    frames.append(df)
                    fetched += 1
            d -= timedelta(days=1)
    except Exception:
        pass

    result = pd.concat(frames).sort_index() if frames else pd.DataFrame()
    _k1m_prev_cache[key] = result
    return result


# ── 日 K 收盤 ────────────────────────────────────────────────────────────────


def get_daily_closes(ticker: str, n: int = 80) -> pd.Series:
    """抓近 N 日日 K 收盤、30 分鐘 cache。

    用於 B5-3 季線（MA60）方向判斷。
    """
    key = f"{ticker}:{n}"
    now = _now()
    cached = _daily_cache.get(key)
    if cached and (now - cached[0]).total_seconds() < DAILY_TTL_SEC:
        return cached[1]

    try:
        from zhuli.intraday_stage_helper import load_daily_closes, _DB
        s = load_daily_closes(ticker, _DB, n=n)
    except Exception:
        s = pd.Series(dtype=float)

    _daily_cache[key] = (now, s)
    return s


# ── 昨日是否漲停 ─────────────────────────────────────────────────────────────


LIMIT_UP_THRESHOLD = 9.5  # %


def was_prev_limit_up(ticker: str, prev_close: float, target_date: Optional[date] = None) -> bool:
    """判斷昨日是否漲停（用前一交易日漲幅 ≥ 9.5%）。

    當日不變、無 TTL。
    """
    target_date = target_date or date.today()
    key = f"{ticker}:{target_date.isoformat()}"
    if key in _limit_up_cache:
        return _limit_up_cache[key]

    result = False
    try:
        closes = get_daily_closes(ticker, n=3)
        if len(closes) >= 2:
            prev = float(closes.iloc[-1])
            prev_prev = float(closes.iloc[-2])
            if prev_prev > 0:
                pct = (prev / prev_prev - 1) * 100
                result = pct >= LIMIT_UP_THRESHOLD
    except Exception:
        pass

    _limit_up_cache[key] = result
    return result


# ── 清除 cache（測試 / 換日用）──────────────────────────────────────────────


def clear_cache():
    """清除所有 cache（測試、跨日重啟用）。"""
    _k1m_today_cache.clear()
    _k1m_prev_cache.clear()
    _daily_cache.clear()
    _limit_up_cache.clear()
