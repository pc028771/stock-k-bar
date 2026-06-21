"""xiaoge_flying_stock_screener — D5 多策略 combinator (ch12 飆股口袋名單).

Course source: 權證小哥 ch12 (飆股口袋名單條件解析), ch13 (運用多種策略交叉).
Reference: docs/權證小哥/籌碼技術分析/detector_spec.md §5.

> 「越多條件交集、出來的股票越少、精準度越高。」 (ch12 老師反覆強調)

## D5 sub-detector 範圍（audit 後保留 4 條 + 鏡像）

依 audit (CLAUDE 對話 6/16) 篩出 4 條獨立可做的 sub:

| sub | 條件 | 資料源 |
|---|---|---|
| **M3** main_buy_streak_N | 主力連 N 天買 | `standard_daily_bar.main_force_1d` |
| **M4** foreign_buy_streak_N | 外資連 N 天買 | `institutional_investors.foreign_net` |
| **M5** invest_trust_buy_streak_N | 投信連 N 天買 | `institutional_investors.sitc_net` |
| **M7** break_20d_high | 收盤創 20 日新高 | bar close |

S3-S7 為鏡像空頭版本。

刻意排除：
- **M1/M2** 真分點主力 — 已有 D4 `key_broker_signal` 涵蓋
- **M6** 波動度↑ — 課程「波動度 ↑ 2%」沒給明確閾值、不工程化
- **M8/M9** bb_open / bb_squeeze — 已被 D1 `bb_squeeze_breakout` 內建為 filter/precondition

## combinator
score(row) = 各 sub 命中數總和、`screener_long(min_score=2)` = 至少 2 條同時亮。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd


DEFAULT_DB_PATH = Path("/Users/howard/.four_seasons/data.sqlite")


# ── helpers ────────────────────────────────────────────────────────────────

def _streak_positive(series: pd.Series, ticker_series: pd.Series, n: int) -> pd.Series:
    """True if last n bars all > 0 per ticker."""
    return series.groupby(ticker_series).transform(
        lambda s: s.rolling(n, min_periods=n).min() > 0
    ).fillna(False)


def _streak_negative(series: pd.Series, ticker_series: pd.Series, n: int) -> pd.Series:
    """True if last n bars all < 0 per ticker."""
    return series.groupby(ticker_series).transform(
        lambda s: s.rolling(n, min_periods=n).max() < 0
    ).fillna(False)


def load_institutional(start_date: str, end_date: str,
                       db_path: Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    """Load institutional_investors for window (with 30-day warmup for streak)."""
    warmup = (pd.Timestamp(start_date) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    con = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        f"""
        SELECT ticker, trade_date, foreign_net, sitc_net
        FROM institutional_investors
        WHERE trade_date >= '{warmup}' AND trade_date <= '{end_date}'
        """,
        con,
    )
    con.close()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["foreign_net"] = pd.to_numeric(df["foreign_net"], errors="coerce").fillna(0)
    df["sitc_net"] = pd.to_numeric(df["sitc_net"], errors="coerce").fillna(0)
    return df


def attach_institutional(df: pd.DataFrame,
                         db_path: Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    """Left-join foreign_net + sitc_net onto bars df.

    Missing values filled with 0 (no institutional activity recorded).
    """
    start = df["trade_date"].min().strftime("%Y-%m-%d")
    end = df["trade_date"].max().strftime("%Y-%m-%d")
    inst = load_institutional(start, end, db_path)
    out = df.merge(inst, on=["ticker", "trade_date"], how="left")
    out["foreign_net"] = out["foreign_net"].fillna(0)
    out["sitc_net"] = out["sitc_net"].fillna(0)
    return out


# ── sub-detectors (long) ───────────────────────────────────────────────────

def m3_main_buy_streak(df: pd.DataFrame, n: int = 3) -> pd.Series:
    """主力（機構代理）連 N 天買超。資料源 `main_force_1d`."""
    return _streak_positive(df["main_force_1d"], df["ticker"], n)


def m4_foreign_buy_streak(df: pd.DataFrame, n: int = 3) -> pd.Series:
    """外資連 N 天買超。要求 df 已 attach_institutional."""
    return _streak_positive(df["foreign_net"], df["ticker"], n)


def m5_invest_trust_buy_streak(df: pd.DataFrame, n: int = 3) -> pd.Series:
    """投信連 N 天買超。要求 df 已 attach_institutional."""
    return _streak_positive(df["sitc_net"], df["ticker"], n)


def m7_break_high(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """收盤創 lookback 日新高（含今天、不含 lookback 起點前一天）.

    定義：close == max(close 過去 lookback 天含今天).
    為避免「平高」也亮、要求 > 過去 lookback-1 天的高（嚴格新高）.
    """
    high_excl_today = df.groupby("ticker")["close"].transform(
        lambda s: s.rolling(lookback, min_periods=lookback).max().shift(1)
    )
    return (df["close"] > high_excl_today).fillna(False)


# ── sub-detectors (short, 鏡像) ────────────────────────────────────────────

def s3_main_sell_streak(df: pd.DataFrame, n: int = 3) -> pd.Series:
    return _streak_negative(df["main_force_1d"], df["ticker"], n)


def s4_foreign_sell_streak(df: pd.DataFrame, n: int = 3) -> pd.Series:
    return _streak_negative(df["foreign_net"], df["ticker"], n)


def s5_invest_trust_sell_streak(df: pd.DataFrame, n: int = 3) -> pd.Series:
    return _streak_negative(df["sitc_net"], df["ticker"], n)


def s7_break_low(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    low_excl_today = df.groupby("ticker")["close"].transform(
        lambda s: s.rolling(lookback, min_periods=lookback).min().shift(1)
    )
    return (df["close"] < low_excl_today).fillna(False)


# ── combinator ─────────────────────────────────────────────────────────────

def long_score(df: pd.DataFrame, n_streak: int = 3, n_high: int = 20) -> pd.DataFrame:
    """Return DataFrame with columns m3, m4, m5, m7 (bool) + score (int)."""
    out = pd.DataFrame(index=df.index)
    out["m3"] = m3_main_buy_streak(df, n_streak)
    out["m4"] = m4_foreign_buy_streak(df, n_streak)
    out["m5"] = m5_invest_trust_buy_streak(df, n_streak)
    out["m7"] = m7_break_high(df, n_high)
    out["score"] = out[["m3", "m4", "m5", "m7"]].sum(axis=1).astype(int)
    return out


def short_score(df: pd.DataFrame, n_streak: int = 3, n_high: int = 20) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["s3"] = s3_main_sell_streak(df, n_streak)
    out["s4"] = s4_foreign_sell_streak(df, n_streak)
    out["s5"] = s5_invest_trust_sell_streak(df, n_streak)
    out["s7"] = s7_break_low(df, n_high)
    out["score"] = out[["s3", "s4", "s5", "s7"]].sum(axis=1).astype(int)
    return out


def screener_long(df: pd.DataFrame, n_streak: int = 3,
                  n_high: int = 20, min_score: int = 2) -> pd.Series:
    """Final long signal: True iff long_score.score >= min_score."""
    return long_score(df, n_streak, n_high)["score"] >= min_score


def screener_short(df: pd.DataFrame, n_streak: int = 3,
                   n_high: int = 20, min_score: int = 2) -> pd.Series:
    return short_score(df, n_streak, n_high)["score"] >= min_score
