"""Context snapshot builder — Task 1.5.

Responsibility
--------------
Build a ``ContextSnapshot`` from a features-enriched DataFrame row + optional
overrides dict.  This module is the single source of truth for:

1. Which feature columns map to which ContextSnapshot fields.
2. Fail-loud behaviour for missing fields: each ``None`` field appended to
   ``warn_notes`` but does NOT crash (per feedback_no_silent_imputation,
   missing fields must be reported, not silently patched).

Public API
----------
::

    snapshot, warn_notes = build_context_snapshot(bars_df, today_date, ticker)
    snapshot, warn_notes = build_context_snapshot(bars_df, today_date, ticker,
                                                   overrides={"ma5_will_rise": True})

Notes
-----
- Fields absent from ``bars_df`` → ``None`` (with warn).
- NaN values are treated as missing → ``None`` (with warn).
- ``overrides`` always wins over the df value; no warn is emitted for
  override-injected fields (the caller is responsible for providing them).
- Do NOT add computation / inference for missing values — that violates
  ``feedback_no_silent_imputation``.
- 大盤創紀錄跌點欄位（taiex_record_drop_point / taiex_record_drop_pct /
  taiex_record_limit_down_count / taiex_no_new_low_next_day）由
  ``_TaiexContext`` 從 taiex_history.sqlite + limit_down_history.sqlite 讀取；
  亦可透過 overrides 注入（測試用）。若 DB 不存在，欄位為 None + warn（fail-loud，不 crash）。
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from ._schema import ContextSnapshot

# ---------------------------------------------------------------------------
# TAIEX / Limit-down DB paths
# ---------------------------------------------------------------------------
_WORKTREE = Path(__file__).resolve().parents[3]
_TAIEX_DB = _WORKTREE / "data/analysis/kline_patterns/taiex_history.sqlite"
_LIMIT_DOWN_DB = _WORKTREE / "data/analysis/kline_patterns/limit_down_history.sqlite"


class _TaiexContext:
    """Lazy-loaded helper that computes the four §30 大盤欄位.

    Loads taiex_daily + limit_down_daily once per process and caches them in
    class-level attributes.  If either DB is missing, the corresponding fields
    return None.
    """

    _taiex_df: "pd.DataFrame | None" = None
    _ld_df: "pd.DataFrame | None" = None
    _loaded: bool = False
    # Per-date precomputed result cache. Built on first compute() call and
    # reused for every subsequent date — avoids per-call df.copy / shift /
    # mask scan on the full TAIEX history (was ~3ms × N calls in profiling).
    _per_date_cache: "dict[str, dict[str, Optional[bool]]] | None" = None

    @classmethod
    def _default_result(cls) -> dict[str, "Optional[bool]"]:
        return {
            "taiex_record_drop_point": None,
            "taiex_record_drop_pct": None,
            "taiex_record_limit_down_count": None,
            "taiex_record_any_criterion": None,
            "taiex_no_new_low_next_day": None,
            "taiex_down_today": None,
            "is_after_negative_news_taiex": None,
            "taiex_false_breakdown_recovered": None,
            "taiex_v_sunrise": None,
        }

    @classmethod
    def _build_cache(cls) -> None:
        """Precompute every per-date result vectorized — done once per process."""
        cls._per_date_cache = {}

        if cls._taiex_df is None or cls._taiex_df.empty:
            ld_only = cls._build_limit_down_only()
            cls._per_date_cache = ld_only
            return

        tdf = cls._taiex_df.copy()
        tdf["prev_close"] = tdf["close"].shift(1)
        tdf["drop_point"] = tdf["prev_close"] - tdf["close"]
        tdf["drop_pct"] = tdf["drop_point"] / tdf["prev_close"]

        # Historical max EXCLUDING current row → shift(1) then cummax.
        prev_max_point = tdf["drop_point"].shift(1).cummax()
        prev_max_pct = tdf["drop_pct"].shift(1).cummax()

        # Lazy import to avoid module-load-time cycles.
        from ..course_proxy_constants import (
            SELF_RESCUE_NEGATIVE_NEWS_LOOKBACK,
            SELF_RESCUE_TAIEX_DROP_PCT,
        )
        # is_after_negative_news_taiex: any drop_pct ≥ threshold in trailing window
        # (window INCLUDES today — matches old `tdf.loc[start:idx]` semantics).
        big_drop = (tdf["drop_pct"] >= SELF_RESCUE_TAIEX_DROP_PCT).astype(int)
        any_big_drop = (
            big_drop.rolling(SELF_RESCUE_NEGATIVE_NEWS_LOOKBACK + 1, min_periods=1)
            .max()
            .astype(bool)
        )

        # §33 假性跌破：昨日 close < 過去 60 日最低 close（不含昨日當天）+
        # 今日 open > 昨日 close + 今日 close > 昨日 close
        prior_low_close_60 = (
            tdf["close"].shift(1).rolling(60, min_periods=60).min()
        )
        # Aligned to today's index: yesterday's close < yesterday's prior-60-low.
        y_close = tdf["close"].shift(1)
        y_prior_low_60 = prior_low_close_60.shift(1)
        broke_yesterday = y_close < y_prior_low_60
        gap_up_today = tdf["open"] > y_close
        recovered = tdf["close"] > y_close
        false_breakdown = (broke_yesterday & gap_up_today & recovered).fillna(False)
        # §33 has 60-day warmup; values where prior_low_close_60 is NaN → None semantic
        # but we report False as the legacy code did once history was sufficient.

        # §58 V 型反彈：昨日為強彈日（close > open + (close-open)/open > 1%）+
        # 今日日出（high > yesterday.high AND low > yesterday.low）
        y_open = tdf["open"].shift(1)
        y_high = tdf["high"].shift(1)
        y_low = tdf["low"].shift(1)
        with np.errstate(divide="ignore", invalid="ignore"):
            y_pct_up = (y_close - y_open) / y_open
        strong_bounce = (y_close > y_open) & (y_pct_up > 0.01)
        sunrise = (tdf["high"] > y_high) & (tdf["low"] > y_low)
        v_sunrise = (strong_bounce & sunrise).fillna(False)

        # taiex_no_new_low_next_day: tomorrow's low > today's low
        next_low = tdf["low"].shift(-1)
        no_new_low = next_low > tdf["low"]
        # Only emit a value when next_low is present.
        no_new_low_mask = next_low.notna() & tdf["low"].notna()

        # Limit-down record (max excluding today).
        ld_max_excl: "pd.Series | None" = None
        ld_lookup: "dict[str, float] | None" = None
        if cls._ld_df is not None and not cls._ld_df.empty:
            ld = cls._ld_df.copy()
            ld_max_excl = ld["limit_down_count"].shift(1).cummax()
            ld_lookup = dict(zip(ld["trade_date"].astype(str), ld["limit_down_count"]))
            ld_max_lookup = dict(zip(ld["trade_date"].astype(str), ld_max_excl))
        else:
            ld_max_lookup = {}

        # Build per-date result dict.
        dates_arr = tdf["trade_date"].astype(str).to_numpy()
        n = len(tdf)
        for i in range(n):
            d = dates_arr[i]
            r = cls._default_result()
            drop_pt = tdf["drop_point"].iat[i]
            drop_pc = tdf["drop_pct"].iat[i]

            # Historical-record flags (require non-NaN prev_max).
            if pd.notna(drop_pt) and pd.notna(prev_max_point.iat[i]):
                r["taiex_record_drop_point"] = bool(drop_pt > prev_max_point.iat[i])
            if pd.notna(drop_pc) and pd.notna(prev_max_pct.iat[i]):
                r["taiex_record_drop_pct"] = bool(drop_pc > prev_max_pct.iat[i])

            if pd.notna(drop_pt):
                r["taiex_down_today"] = bool(drop_pt > 0)
            r["is_after_negative_news_taiex"] = bool(any_big_drop.iat[i])

            # §33 / §58 — require 60-day / 1-day warmup respectively.
            if i >= 60 and pd.notna(prior_low_close_60.iat[i]):
                r["taiex_false_breakdown_recovered"] = bool(false_breakdown.iat[i])
            elif i >= 60:
                r["taiex_false_breakdown_recovered"] = False
            if i >= 1:
                r["taiex_v_sunrise"] = bool(v_sunrise.iat[i])

            if no_new_low_mask.iat[i]:
                r["taiex_no_new_low_next_day"] = bool(no_new_low.iat[i])

            # Limit-down record
            if d in ld_max_lookup and ld_lookup is not None:
                hist_max = ld_max_lookup[d]
                today_ct = ld_lookup.get(d)
                if pd.notna(hist_max) and pd.notna(today_ct):
                    r["taiex_record_limit_down_count"] = bool(today_ct > hist_max)

            # Composite any-of-three
            three = [
                r["taiex_record_drop_point"],
                r["taiex_record_drop_pct"],
                r["taiex_record_limit_down_count"],
            ]
            if any(v is True for v in three):
                r["taiex_record_any_criterion"] = True
            elif all(v is False for v in three):
                r["taiex_record_any_criterion"] = False

            cls._per_date_cache[d] = r

    @classmethod
    def _build_limit_down_only(cls) -> dict[str, dict[str, "Optional[bool]"]]:
        """Cache for the rare path where only limit-down DB exists."""
        out: dict[str, dict[str, "Optional[bool]"]] = {}
        if cls._ld_df is None or cls._ld_df.empty:
            return out
        ld = cls._ld_df.copy()
        ld_max = ld["limit_down_count"].shift(1).cummax()
        dates_arr = ld["trade_date"].astype(str).to_numpy()
        for i in range(len(ld)):
            r = cls._default_result()
            today_ct = ld["limit_down_count"].iat[i]
            hist_max = ld_max.iat[i]
            if pd.notna(today_ct) and pd.notna(hist_max):
                r["taiex_record_limit_down_count"] = bool(today_ct > hist_max)
                r["taiex_record_any_criterion"] = r["taiex_record_limit_down_count"] or None
                if r["taiex_record_any_criterion"] is False:
                    r["taiex_record_any_criterion"] = False
            out[dates_arr[i]] = r
        return out

    @classmethod
    def _load(cls) -> None:
        if cls._loaded:
            return
        cls._loaded = True  # mark early to avoid re-entrant loads
        cls._per_date_cache = None  # invalidate cache when DBs are re-loaded (tests reset _loaded)
        # TAIEX
        if _TAIEX_DB.exists():
            try:
                conn = sqlite3.connect(str(_TAIEX_DB))
                df = pd.read_sql_query(
                    "SELECT trade_date, open, high, low, close FROM taiex_daily ORDER BY trade_date",
                    conn,
                )
                conn.close()
                cls._taiex_df = df
            except Exception as e:
                cls._taiex_df = None
                print(f"WARN: _TaiexContext failed to load taiex DB: {e}")
        # Limit-down
        if _LIMIT_DOWN_DB.exists():
            try:
                conn = sqlite3.connect(str(_LIMIT_DOWN_DB))
                df = pd.read_sql_query(
                    "SELECT trade_date, limit_down_count FROM limit_down_daily ORDER BY trade_date",
                    conn,
                )
                conn.close()
                cls._ld_df = df
            except Exception as e:
                cls._ld_df = None
                print(f"WARN: _TaiexContext failed to load limit_down DB: {e}")

    @classmethod
    def compute(cls, today_date: str) -> dict[str, Optional[bool]]:
        """Return the per-date taiex/§30 fields for *today_date* (O(1) lookup).

        Lazy-builds a per-date cache on first call (vectorized over the full
        TAIEX history); subsequent calls are dict lookups. Old implementation
        copied the TAIEX df and ran a date-filter scan on every call — ~3ms ×
        N calls dominated build_context_snapshot for large backtests.
        """
        cls._load()
        if cls._per_date_cache is None:
            cls._build_cache()
        cached = cls._per_date_cache.get(today_date) if cls._per_date_cache else None
        if cached is not None:
            return dict(cached)  # defensive copy — caller may mutate
        return cls._default_result()

    @classmethod
    def _compute_legacy(cls, today_date: str) -> dict[str, Optional[bool]]:
        """Original per-call implementation, kept for reference/tests."""
        cls._load()
        result: dict[str, Optional[bool]] = {
            "taiex_record_drop_point": None,
            "taiex_record_drop_pct": None,
            "taiex_record_limit_down_count": None,
            "taiex_no_new_low_next_day": None,
            # INTRO-3 / INTRO-1 new fields
            "taiex_down_today": None,                  # 大盤今日下跌（close < prev_close）
            "is_after_negative_news_taiex": None,      # 近 N 日內大盤曾單日跌幅 ≥ proxy（利空背景）
            # INTRO-tier-2 (2026-06-06) — 大盤層級訊號
            "taiex_false_breakdown_recovered": None,   # §33 假性跌破：急跌破關鍵點後隔日跳空站回
            "taiex_v_sunrise": None,                   # §58 V 型反彈 → V 型反轉：第一天強彈 + 隔日日出
        }

        if cls._taiex_df is not None and not cls._taiex_df.empty:
            tdf = cls._taiex_df.copy()
            tdf["prev_close"] = tdf["close"].shift(1)
            tdf["drop_point"] = tdf["prev_close"] - tdf["close"]  # positive = drop
            tdf["drop_pct"] = tdf["drop_point"] / tdf["prev_close"]

            today_mask = tdf["trade_date"] == today_date
            if today_mask.any():
                idx = tdf.index[today_mask][0]
                today_row = tdf.loc[idx]

                # All historical rows BEFORE today
                hist = tdf.loc[:idx - 1] if idx > 0 else tdf.iloc[0:0]

                # taiex_record_drop_point: today drop_point > historical max drop_point
                if pd.notna(today_row["drop_point"]) and not hist.empty and hist["drop_point"].notna().any():
                    result["taiex_record_drop_point"] = bool(
                        today_row["drop_point"] > hist["drop_point"].max()
                    )

                # taiex_record_drop_pct: today drop_pct > historical max drop_pct
                if pd.notna(today_row["drop_pct"]) and not hist.empty and hist["drop_pct"].notna().any():
                    result["taiex_record_drop_pct"] = bool(
                        today_row["drop_pct"] > hist["drop_pct"].max()
                    )

                # INTRO-3: taiex_down_today (大盤今日下跌)
                if pd.notna(today_row["drop_point"]):
                    result["taiex_down_today"] = bool(today_row["drop_point"] > 0)

                # INTRO-1: is_after_negative_news_taiex (近 N 日大盤曾大跌)
                from ..course_proxy_constants import (
                    SELF_RESCUE_NEGATIVE_NEWS_LOOKBACK,
                    SELF_RESCUE_TAIEX_DROP_PCT,
                )
                start = max(0, idx - SELF_RESCUE_NEGATIVE_NEWS_LOOKBACK)
                window = tdf.loc[start:idx]
                if not window.empty and window["drop_pct"].notna().any():
                    result["is_after_negative_news_taiex"] = bool(
                        (window["drop_pct"] >= SELF_RESCUE_TAIEX_DROP_PCT).any()
                    )

                # INTRO-tier-2: taiex_false_breakdown_recovered (§33 假性跌破)
                # 老師原話 (§33):「當股價指數遇到了某個利空事件、短期之內快速的
                #   跌破了足以影響趨勢的關鍵點位、卻因為急跌之後的反彈又馬上站回
                #   到這個關鍵價位之上...辨識關鍵當然是隔天的往上跳空」
                # 退化版判定:
                #   昨日大盤 close 跌破過去 60 日最低收盤（急跌破關鍵點）
                #   且今日往上跳空 (today.open > yesterday.close)
                #   且今日 close 站回昨日 close 之上（吃回急跌段）
                if idx >= 60:
                    hist_60 = tdf.loc[idx - 60:idx - 1]
                    if len(hist_60) >= 60:
                        prior_low_close = hist_60["close"].min()
                        yesterday = tdf.loc[idx - 1]
                        if (
                            pd.notna(yesterday["close"])
                            and pd.notna(prior_low_close)
                            and pd.notna(today_row["open"])
                            and pd.notna(today_row["close"])
                        ):
                            broke_yesterday = yesterday["close"] < prior_low_close
                            gap_up_today = today_row["open"] > yesterday["close"]
                            recovered = today_row["close"] > yesterday["close"]
                            result["taiex_false_breakdown_recovered"] = bool(
                                broke_yesterday and gap_up_today and recovered
                            )
                        else:
                            result["taiex_false_breakdown_recovered"] = False
                    else:
                        result["taiex_false_breakdown_recovered"] = False

                # INTRO-tier-2: taiex_v_sunrise (§58 V 型反彈 → V 型反轉)
                # 老師原話 (§58):「第一天強彈出現之後、第二天開始的重點則是大盤
                #   得要繼續日出型態」「3月20日K線的低點8816不能破、高點9264要越過、
                #   這樣才是日出」「如果沒有保持日出型態、就不是V型反彈」
                # 退化版判定:
                #   昨日為強彈日（昨日 close > 昨日 open 且漲幅 > 1%）
                #   且今日為日出（today.high > yesterday.high 且 today.low > yesterday.low）
                if idx >= 1:
                    yesterday = tdf.loc[idx - 1]
                    if (
                        pd.notna(yesterday["open"]) and pd.notna(yesterday["close"])
                        and pd.notna(yesterday["high"]) and pd.notna(yesterday["low"])
                        and pd.notna(today_row["high"]) and pd.notna(today_row["low"])
                    ):
                        y_open = yesterday["open"]
                        y_pct_up = (yesterday["close"] - y_open) / y_open if y_open else 0
                        strong_bounce = (yesterday["close"] > y_open) and (y_pct_up > 0.01)
                        sunrise = (
                            today_row["high"] > yesterday["high"]
                            and today_row["low"] > yesterday["low"]
                        )
                        result["taiex_v_sunrise"] = bool(strong_bounce and sunrise)
                    else:
                        result["taiex_v_sunrise"] = False

                # taiex_no_new_low_next_day: next trading day low > today low
                next_rows = tdf.loc[idx + 1:]
                if not next_rows.empty:
                    next_row = next_rows.iloc[0]
                    if pd.notna(today_row["low"]) and pd.notna(next_row["low"]):
                        result["taiex_no_new_low_next_day"] = bool(
                            next_row["low"] > today_row["low"]
                        )

        if cls._ld_df is not None and not cls._ld_df.empty:
            ld = cls._ld_df.copy()
            today_ld_mask = ld["trade_date"] == today_date
            if today_ld_mask.any():
                idx = ld.index[today_ld_mask][0]
                today_count = ld.loc[idx, "limit_down_count"]
                hist_ld = ld.loc[:idx - 1] if idx > 0 else ld.iloc[0:0]
                if not hist_ld.empty and hist_ld["limit_down_count"].notna().any():
                    result["taiex_record_limit_down_count"] = bool(
                        today_count > hist_ld["limit_down_count"].max()
                    )

        # Composite: any one of the three record flags is True
        # 老師原話：「只要有其中一項」
        three = [
            result["taiex_record_drop_point"],
            result["taiex_record_drop_pct"],
            result["taiex_record_limit_down_count"],
        ]
        if any(v is True for v in three):
            result["taiex_record_any_criterion"] = True
        elif all(v is False for v in three):
            result["taiex_record_any_criterion"] = False
        # else: at least one is None → composite remains None

        return result

# ---------------------------------------------------------------------------
# Fields sourced from features.py columns (extracted, NOT re-computed)
# ---------------------------------------------------------------------------

# These fields come from features.py enriched df.
# If absent or NaN → None + warn.
_FEATURES_FIELDS: list[str] = [
    "attack_cost",
    "attack_intent_zone_high",
    "attack_intent_zone_low",
    "defensive_low",
    "ma5_will_rise",
    "ma10_will_rise",
    "ma20_will_rise",
    "ma60_will_rise",
    "prior_high_60",
    "prior_low_60",
    "is_just_broke_high",
    "is_limit_up_locked",
    "is_anomalous_volume",
    # merged_* fields (variable set depending on features.py version)
    # included dynamically via _MERGED_PREFIX below
]

_MERGED_PREFIX = "merged_"


def _scalar(val: object) -> object:
    """Convert numpy scalar / NaN → Python None; pass through other values."""
    if val is None:
        return None
    try:
        if math.isnan(float(val)):  # type: ignore[arg-type]
            return None
    except (TypeError, ValueError):
        pass
    return val


def build_context_snapshot(
    bars_df: pd.DataFrame,
    today_date: str,
    ticker: str,
    overrides: dict | None = None,
) -> tuple[ContextSnapshot, list[str]]:
    """Build a ContextSnapshot for *ticker* on *today_date*.

    Parameters
    ----------
    bars_df:
        Features-enriched DataFrame.  Must contain a ``ticker`` column (or be
        pre-filtered to a single ticker) and a ``trade_date`` column (or a
        DatetimeIndex).
    today_date:
        Target date as ``'YYYY-MM-DD'`` string.
    ticker:
        Ticker symbol.
    overrides:
        Optional dict of ``ContextSnapshot`` field → value.  These values
        take priority over anything found in ``bars_df``.

    Returns
    -------
    tuple[ContextSnapshot, list[str]]
        ``(snapshot, warn_notes)``  where ``warn_notes`` contains a ``WARN:``
        line for every field that resolved to ``None`` from the df (not from
        overrides).

    Raises
    ------
    ValueError
        If *ticker* is not found in *bars_df*, or *today_date* is not found
        for that ticker.  (fail loud — caller must ensure data is present.)
    """
    overrides = overrides or {}
    warn_notes: list[str] = []

    # ------------------------------------------------------------------
    # 1. Filter to ticker
    # ------------------------------------------------------------------
    if "ticker" in bars_df.columns:
        ticker_df = bars_df[bars_df["ticker"] == ticker]
    else:
        ticker_df = bars_df

    if ticker_df.empty:
        raise ValueError(f"ticker {ticker!r} not found in bars_df")

    # ------------------------------------------------------------------
    # 2. Extract today's row
    # ------------------------------------------------------------------
    if "trade_date" in ticker_df.columns:
        today_rows = ticker_df[ticker_df["trade_date"] == today_date]
    else:
        today_rows = ticker_df[ticker_df.index.astype(str) == today_date]

    if today_rows.empty:
        raise ValueError(
            f"today_date {today_date!r} not found for ticker {ticker!r}"
        )

    row: pd.Series = today_rows.iloc[0]

    # ------------------------------------------------------------------
    # 3. Helper: resolve a field (overrides > df > None+warn)
    # ------------------------------------------------------------------
    def _get(field: str, *, warn_if_missing: bool = True) -> object:
        """Resolve field value: overrides > row > None (+warn)."""
        if field in overrides:
            return overrides[field]
        val = _scalar(row.get(field))
        if val is None and warn_if_missing:
            warn_notes.append(
                f"WARN: ContextSnapshot field '{field}' is missing from "
                f"features df for ticker={ticker!r} date={today_date!r}"
            )
        return val

    # ------------------------------------------------------------------
    # 4b. Resolve taiex §30 fields (from DB or overrides)
    # ------------------------------------------------------------------
    _TAIEX_FIELDS = [
        "taiex_record_drop_point",
        "taiex_record_drop_pct",
        "taiex_record_limit_down_count",
        "taiex_record_any_criterion",
        "taiex_no_new_low_next_day",
        # INTRO concepts impl (2026-06-05)
        "taiex_down_today",
        "is_after_negative_news_taiex",
        # INTRO-tier-2 (2026-06-06): §33 假性跌破 / §58 V 型反彈
        "taiex_false_breakdown_recovered",
        "taiex_v_sunrise",
    ]

    # If any of the four taiex fields is in overrides, use overrides only
    # (test injection path — no DB load needed).
    _taiex_all_in_overrides = all(f in overrides for f in _TAIEX_FIELDS)
    if _taiex_all_in_overrides:
        taiex_vals = {f: overrides[f] for f in _TAIEX_FIELDS}
    else:
        # Load from DB; overrides can still override individual fields
        db_vals = _TaiexContext.compute(today_date)
        taiex_vals = {}
        for f in _TAIEX_FIELDS:
            if f in overrides:
                taiex_vals[f] = overrides[f]
            else:
                val = db_vals.get(f)
                if val is None:
                    warn_notes.append(
                        f"WARN: ContextSnapshot field '{f}' is None "
                        f"(taiex/limit_down DB missing or date not found for {today_date!r})"
                    )
                taiex_vals[f] = val

    # ------------------------------------------------------------------
    # 4c. Resolve §26 防守姿態 manual-hint fields (overrides only)
    #     STUB-NEED-USER: 課程未給量化標準，只能由呼叫端透過 overrides 注入
    # ------------------------------------------------------------------
    taiex_recent_weak = overrides.get("taiex_recent_weak", None)
    stock_outperforms_taiex = overrides.get("stock_outperforms_taiex", None)

    # ------------------------------------------------------------------
    # 5. Build snapshot
    # ------------------------------------------------------------------
    snapshot = ContextSnapshot(
        # --- MA 扣抵 (features.py columns, may be absent pre-Phase 3) ---
        ma5_will_rise=_get("ma5_will_rise"),
        ma10_will_rise=_get("ma10_will_rise"),
        ma20_will_rise=_get("ma20_will_rise"),
        ma60_will_rise=_get("ma60_will_rise"),
        # --- Attack zone / defensive low (C03/C04/C05 features) ---
        attack_cost=_get("attack_cost"),
        defensive_low=_get("defensive_low"),
        attack_intent_zone_high=_get("attack_intent_zone_high"),
        attack_intent_zone_low=_get("attack_intent_zone_low"),
        # --- Current bar status flags ---
        is_just_broke_high=_get("is_just_broke_high"),
        is_limit_up_locked=_get("is_limit_up_locked"),
        is_anomalous_volume=_get("is_anomalous_volume"),
        # --- 大盤創紀錄跌點 §30 (taiex DB) ---
        taiex_record_drop_point=taiex_vals["taiex_record_drop_point"],
        taiex_record_drop_pct=taiex_vals["taiex_record_drop_pct"],
        taiex_record_limit_down_count=taiex_vals["taiex_record_limit_down_count"],
        taiex_record_any_criterion=taiex_vals["taiex_record_any_criterion"],
        taiex_no_new_low_next_day=taiex_vals["taiex_no_new_low_next_day"],
        # --- INTRO concepts impl (2026-06-05) ---
        taiex_down_today=taiex_vals["taiex_down_today"],
        is_after_negative_news_taiex=taiex_vals["is_after_negative_news_taiex"],
        # --- INTRO-tier-2 (2026-06-06) ---
        taiex_false_breakdown_recovered=taiex_vals["taiex_false_breakdown_recovered"],
        taiex_v_sunrise=taiex_vals["taiex_v_sunrise"],
        # --- §26 防守姿態 manual-hint fields (STUB-NEED-USER) ---
        taiex_recent_weak=taiex_recent_weak,
        stock_outperforms_taiex=stock_outperforms_taiex,
    )

    return snapshot, warn_notes
