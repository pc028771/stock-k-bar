"""xiaoge_flying_stock_screener — D5 多策略 combinator (ch12 飆股口袋名單).

Course source: 權證小哥 ch12 (飆股口袋名單條件解析), ch13 (運用多種策略交叉).
Reference: docs/權證小哥/籌碼技術分析/detector_spec.md §5.

> 「越多條件交集、出來的股票越少、精準度越高。」 (ch12 老師反覆強調)

## D5 sub-detector 範圍（audit + 6/19 ch13 補完）

| sub | 條件 | 資料源 |
|---|---|---|
| **M3** main_buy_streak_N | 主力連 N 天買 | `standard_daily_bar.main_force_1d` |
| **M4** foreign_buy_streak_N | 外資連 N 天買 | `institutional_investors.foreign_net` |
| **M5** invest_trust_buy_streak_N | 投信連 N 天買 | `institutional_investors.sitc_net` |
| **M6** volatility_rising_strong | 波動度上升 + 5MA 上揚 + 站上 5MA | bar high/low/close/ma5 |
| **M7** break_20d_high | 收盤創 20 日新高 | bar close |
| **KD** kd_golden_cross | 9 日 KD 黃金交叉 (K 上穿 D) | bar high/low/close |

S3-S7 為鏡像空頭版本（無 KD short — 死叉設計另外）。

### M6 公式 (老師閾值「波動度 ↑ 2%」課程未明確、本實作為近似)

老師原話 (ch12 05:39–06:14):
> 「短期波動度上升 2% 以上 + 5 日均線上揚 + 站上 5 日均價」

「短期波動度」公式課程未定義。本實作用「日內波動度」近似：
- `intraday_vol = (high - low) / close × 100` (每日 1 個百分點 value)
- `short_avg = rolling(5).mean()` 當天
- `prev_avg = rolling(5).mean().shift(5)` 5 天前
- M6 fires when `short_avg - prev_avg ≥ 2.0 pp` AND `close > ma5` AND `ma5 today > ma5 yesterday`

→ 屬於課程「2% ↑」的近似、文件留 audit 標記、user 可後續調公式。

### KD 標準 9 日 stochastic
- `RSV = (close - low_9) / (high_9 - low_9) × 100`
- `K = 2/3 K_prev + 1/3 RSV`、`D = 2/3 D_prev + 1/3 K` (初值 50)
- 黃金交叉 = `K_today > D_today AND K_yesterday ≤ D_yesterday`

### 刻意排除
- **M1/M2** 真分點主力 — 已有 D4 `key_broker_signal` 涵蓋
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


def m6_volatility_rising_strong(df: pd.DataFrame,
                                vol_rise_pp: float = 2.0) -> pd.Series:
    """波動度上升 + 5MA 上揚 + 站上 5MA (long signal).

    波動度公式（課程未定義、近似）：
        intraday_vol = (high - low) / close * 100  (pp)
        short_avg = 5d 平均
        prev_avg = 5d 平均 shifted 5d 前
        rises when short_avg - prev_avg >= vol_rise_pp

    搭配 close > ma5 + ma5 上揚。
    """
    intraday_vol = (df["high"] - df["low"]) / df["close"] * 100
    g_vol = intraday_vol.groupby(df["ticker"])
    short_avg = g_vol.transform(lambda s: s.rolling(5, min_periods=5).mean())
    prev_avg = short_avg.groupby(df["ticker"]).shift(5)
    vol_up = (short_avg - prev_avg) >= vol_rise_pp

    ma5 = df["ma5"]
    ma5_prev = ma5.groupby(df["ticker"]).shift(1)
    ma5_rising = (ma5 > ma5_prev).fillna(False)
    above_ma5 = (df["close"] > ma5).fillna(False)

    return (vol_up & ma5_rising & above_ma5).fillna(False)


def _compute_kd(df: pd.DataFrame, period: int = 9) -> tuple[pd.Series, pd.Series]:
    """Standard 9-day stochastic (Taiwan-style: 1/3 SMA smoothing, init=50).

    Returns (K, D) Series, same index as df. Per-ticker isolated via positional
    loop over groupby indices.
    """
    g = df.groupby("ticker")
    low_n = g["low"].transform(lambda s: s.rolling(period, min_periods=period).min())
    high_n = g["high"].transform(lambda s: s.rolling(period, min_periods=period).max())
    rsv = ((df["close"] - low_n) / (high_n - low_n) * 100).where(high_n != low_n)

    rsv_arr = rsv.to_numpy()
    n = len(df)
    K_arr = [float("nan")] * n
    D_arr = [float("nan")] * n
    for _ticker, positions in g.indices.items():
        prev_K = 50.0
        prev_D = 50.0
        for pos in positions:
            r = rsv_arr[pos]
            if pd.isna(r):
                continue
            cur_K = (2 / 3) * prev_K + (1 / 3) * r
            cur_D = (2 / 3) * prev_D + (1 / 3) * cur_K
            K_arr[pos] = cur_K
            D_arr[pos] = cur_D
            prev_K = cur_K
            prev_D = cur_D
    return pd.Series(K_arr, index=df.index), pd.Series(D_arr, index=df.index)


def kd_golden_cross(df: pd.DataFrame, period: int = 9) -> pd.Series:
    """KD 黃金交叉: K 上穿 D (今日 K > D 且昨日 K ≤ D)."""
    K, D = _compute_kd(df, period)
    K_prev = K.groupby(df["ticker"]).shift(1)
    D_prev = D.groupby(df["ticker"]).shift(1)
    cross = (K > D) & (K_prev <= D_prev)
    return cross.fillna(False)


def kd_death_cross(df: pd.DataFrame, period: int = 9) -> pd.Series:
    """KD 死亡交叉: K 下穿 D (今日 K < D 且昨日 K ≥ D)."""
    K, D = _compute_kd(df, period)
    K_prev = K.groupby(df["ticker"]).shift(1)
    D_prev = D.groupby(df["ticker"]).shift(1)
    cross = (K < D) & (K_prev >= D_prev)
    return cross.fillna(False)


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


def s6_volatility_rising_weak(df: pd.DataFrame,
                              vol_rise_pp: float = 2.0) -> pd.Series:
    """波動度上升 + 5MA 下彎 + 跌破 5MA (short mirror of M6)."""
    intraday_vol = (df["high"] - df["low"]) / df["close"] * 100
    g_vol = intraday_vol.groupby(df["ticker"])
    short_avg = g_vol.transform(lambda s: s.rolling(5, min_periods=5).mean())
    prev_avg = short_avg.groupby(df["ticker"]).shift(5)
    vol_up = (short_avg - prev_avg) >= vol_rise_pp

    ma5 = df["ma5"]
    ma5_prev = ma5.groupby(df["ticker"]).shift(1)
    ma5_falling = (ma5 < ma5_prev).fillna(False)
    below_ma5 = (df["close"] < ma5).fillna(False)

    return (vol_up & ma5_falling & below_ma5).fillna(False)


def s7_break_low(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    low_excl_today = df.groupby("ticker")["close"].transform(
        lambda s: s.rolling(lookback, min_periods=lookback).min().shift(1)
    )
    return (df["close"] < low_excl_today).fillna(False)


# ── combinator ─────────────────────────────────────────────────────────────

def long_score(df: pd.DataFrame, n_streak: int = 3, n_high: int = 20,
               vol_rise_pp: float = 2.0, kd_period: int = 9) -> pd.DataFrame:
    """Return DataFrame with columns m3..kd (bool) + score (int)."""
    out = pd.DataFrame(index=df.index)
    out["m3"] = m3_main_buy_streak(df, n_streak)
    out["m4"] = m4_foreign_buy_streak(df, n_streak)
    out["m5"] = m5_invest_trust_buy_streak(df, n_streak)
    out["m6"] = m6_volatility_rising_strong(df, vol_rise_pp)
    out["m7"] = m7_break_high(df, n_high)
    out["kd"] = kd_golden_cross(df, kd_period)
    out["score"] = out[["m3", "m4", "m5", "m6", "m7", "kd"]].sum(axis=1).astype(int)
    return out


def short_score(df: pd.DataFrame, n_streak: int = 3, n_high: int = 20,
                vol_rise_pp: float = 2.0, kd_period: int = 9) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["s3"] = s3_main_sell_streak(df, n_streak)
    out["s4"] = s4_foreign_sell_streak(df, n_streak)
    out["s5"] = s5_invest_trust_sell_streak(df, n_streak)
    out["s6"] = s6_volatility_rising_weak(df, vol_rise_pp)
    out["s7"] = s7_break_low(df, n_high)
    out["kd_dx"] = kd_death_cross(df, kd_period)
    out["score"] = out[["s3", "s4", "s5", "s6", "s7", "kd_dx"]].sum(axis=1).astype(int)
    return out


def screener_long(df: pd.DataFrame, n_streak: int = 3,
                  n_high: int = 20, vol_rise_pp: float = 2.0,
                  kd_period: int = 9, min_score: int = 2) -> pd.Series:
    """Final long signal: True iff long_score.score >= min_score."""
    return long_score(df, n_streak, n_high, vol_rise_pp, kd_period)["score"] >= min_score


def screener_short(df: pd.DataFrame, n_streak: int = 3,
                   n_high: int = 20, vol_rise_pp: float = 2.0,
                   kd_period: int = 9, min_score: int = 2) -> pd.Series:
    return short_score(df, n_streak, n_high, vol_rise_pp, kd_period)["score"] >= min_score
