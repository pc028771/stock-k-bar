"""xiaoge_key_broker_signal — detector 4 (關鍵分點動作).

Course source: 權證小哥 ch09-ch10, ch15.

> 「關鍵分點…就是它會低買高賣的分點，而且它量做很大。」(ch09 01:50)
> 「關鍵分點先買，主力後面買；關鍵分點先賣，主力後面才賣。」(ch09 02:43)
> 「在殺低大買的分點呢，就是我們喜歡的分點。」(ch15 11:00)

訊號（多頭）：今日該股「關鍵分點池」內任一分點淨買 ≥ 50 張 + 月線上揚 + 站上月線。
訊號（空頭）：今日該股「關鍵分點池」內任一分點淨賣 ≥ 50 張 + 月線下彎。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[3]
DEFAULT_BROKER_PATH = REPO / "data/analysis/xiaoge/broker_trades/2026-04-01_2026-06-12.parquet"
DEFAULT_POOL_PATH = REPO / "data/analysis/xiaoge/key_broker_pool.parquet"

# 進場門檻：≥ 50 張 = 50_000 股
MIN_SIGNAL_SHARES = 50_000


def _load_pool_action_per_day(broker_path: Path, pool_path: Path,
                              direction: str = "long") -> pd.DataFrame:
    """Return one row per (ticker, date) with whether any pool broker fired.

    direction='long'  → 任一分點 net ≥ MIN_SIGNAL_SHARES
    direction='short' → 任一分點 net ≤ -MIN_SIGNAL_SHARES
    """
    if not broker_path.exists():
        raise FileNotFoundError(f"Broker trades missing: {broker_path}")
    if not pool_path.exists():
        raise FileNotFoundError(f"Key broker pool missing: {pool_path}")

    bdf = pd.read_parquet(broker_path)
    pool = pd.read_parquet(pool_path)

    # 只看池內 (ticker, broker_id) pair
    bdf["broker_id"] = bdf["broker_id"].astype(str)
    pool["broker_id"] = pool["broker_id"].astype(str)
    pool_pairs = pool[["ticker", "broker_id"]].drop_duplicates()
    bdf_filtered = bdf.merge(pool_pairs, on=["ticker", "broker_id"], how="inner")

    if direction == "long":
        fired = bdf_filtered[bdf_filtered["net_shares"] >= MIN_SIGNAL_SHARES]
    else:
        fired = bdf_filtered[bdf_filtered["net_shares"] <= -MIN_SIGNAL_SHARES]

    out = fired.groupby(["ticker", "date"], as_index=False).agg(
        pool_brokers_fired=("broker_id", "count"),
        max_abs_net=("net_shares", lambda s: s.abs().max()),
    )
    out["date"] = pd.to_datetime(out["date"])
    return out


def detect(df: pd.DataFrame,
           broker_path: Path = DEFAULT_BROKER_PATH,
           pool_path: Path = DEFAULT_POOL_PATH) -> pd.Series:
    """Return bool Series; True = xiaoge_key_broker_signal long signal.

    多頭：池內任一分點淨買 ≥ 50 張 + 月線 (ma20) 上揚 + 收盤站上 ma20.

    Required df columns: ticker, trade_date, close, ma20.
    """
    action = _load_pool_action_per_day(broker_path, pool_path, direction="long")
    action = action.rename(columns={"date": "trade_date"})
    action["pool_long_fired"] = True

    merged = df.merge(action[["ticker", "trade_date", "pool_long_fired"]],
                      on=["ticker", "trade_date"], how="left")
    pool_long = merged["pool_long_fired"].fillna(False).astype(bool).values

    close = df["close"]
    ma20 = df["ma20"]
    ma20_prev = ma20.groupby(df["ticker"]).shift(1)
    ma20_rising = (ma20 > ma20_prev).fillna(False)
    above_ma20 = (close >= ma20).fillna(False)

    sig = pd.Series(pool_long, index=df.index) & ma20_rising & above_ma20
    return sig.fillna(False).astype(bool)


def detect_short(df: pd.DataFrame,
                 broker_path: Path = DEFAULT_BROKER_PATH,
                 pool_path: Path = DEFAULT_POOL_PATH) -> pd.Series:
    """空頭：池內任一分點淨賣 ≥ 50 張 + 月線 (ma20) 下彎.

    Required df columns: ticker, trade_date, close, ma20.
    """
    action = _load_pool_action_per_day(broker_path, pool_path, direction="short")
    action = action.rename(columns={"date": "trade_date"})
    action["pool_short_fired"] = True

    merged = df.merge(action[["ticker", "trade_date", "pool_short_fired"]],
                      on=["ticker", "trade_date"], how="left")
    pool_short = merged["pool_short_fired"].fillna(False).astype(bool).values

    ma20 = df["ma20"]
    ma20_prev = ma20.groupby(df["ticker"]).shift(1)
    ma20_falling = (ma20 < ma20_prev).fillna(False)

    sig = pd.Series(pool_short, index=df.index) & ma20_falling
    return sig.fillna(False).astype(bool)
