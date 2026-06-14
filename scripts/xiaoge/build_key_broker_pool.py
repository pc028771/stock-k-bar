"""Build 「關鍵分點池」 per ticker from broker trades parquet.

老師定義（ch09-ch10, ch15）：
> 「關鍵分點…就是它會低買高賣的分點，而且它量做很大。」(ch09 01:50)
> 「在殺低大買的分點呢，就是我們喜歡的分點。」(ch15 11:00)

實作邏輯：
  1. 對每檔股票，用 broker_trades parquet 的歷史資料
  2. 對每個分點：
     - 看該分點淨買的「股價分位」分布（用 ascending percentile of close in past 30d window）
     - 「低買次數」= 該分點淨買 ≥ 10 張 + 收盤 ≤ 過去 30 日 25 percentile 的天數
     - 「高賣次數」= 該分點淨賣 ≥ 10 張 + 收盤 ≥ 過去 30 日 75 percentile 的天數
  3. 分數 = (低買次數 + 高賣次數) / 總出場次數（出場次數 = 該分點在該股至少有過 ≥ 10 張動作的天數）
  4. 對每檔股票挑 top 5 關鍵分點：
     - 出場次數 ≥ 3 天（避免單次偶然）
     - 分數最高的前 5 名

Output: data/analysis/xiaoge/key_broker_pool.parquet
Schema: ticker, broker_id, broker_name, score, total_appearances,
        low_buy_count, high_sell_count
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[2]
DEFAULT_BROKER_PATH = REPO / "data/analysis/xiaoge/broker_trades/2026-04-01_2026-06-12.parquet"
DEFAULT_DB_PATH = Path("/Users/howard/.four_seasons/data.sqlite")
DEFAULT_OUT = REPO / "data/analysis/xiaoge/key_broker_pool.parquet"


# 量門檻：≥ 10 張 = 10_000 股、避免雜訊
MIN_ACTION_SHARES = 10_000
# 至少有 3 個交易日的動作才視為「常見分點」、避免單次偶然
MIN_APPEARANCES = 3
# 每檔取 top N 分點
TOP_N_PER_TICKER = 5


def _load_close_percentiles(broker_df: pd.DataFrame,
                            db_path: Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    """Get close + rolling 30d percentile of close for each (ticker, date)."""
    tickers = broker_df["ticker"].unique().tolist()
    # broker_df has a `trade_date` column at this point
    start = pd.to_datetime(broker_df["trade_date"]).min() - pd.Timedelta(days=60)
    end = pd.to_datetime(broker_df["trade_date"]).max() + pd.Timedelta(days=1)

    placeholders = ",".join(f"'{t}'" for t in tickers)
    conn = sqlite3.connect(db_path)
    bars = pd.read_sql_query(
        f"""
        SELECT ticker, trade_date, close
        FROM standard_daily_bar
        WHERE ticker IN ({placeholders})
          AND trade_date >= '{start.strftime('%Y-%m-%d')}'
          AND trade_date <= '{end.strftime('%Y-%m-%d')}'
          AND is_usable = 1
        ORDER BY ticker, trade_date
        """,
        conn,
    )
    conn.close()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars["close"] = pd.to_numeric(bars["close"], errors="coerce")

    # 30 日 rolling p25 / p75
    bars["p25_30d"] = bars.groupby("ticker")["close"].transform(
        lambda s: s.rolling(30, min_periods=10).quantile(0.25)
    )
    bars["p75_30d"] = bars.groupby("ticker")["close"].transform(
        lambda s: s.rolling(30, min_periods=10).quantile(0.75)
    )
    return bars[["ticker", "trade_date", "close", "p25_30d", "p75_30d"]]


def build_pool(broker_path: Path = DEFAULT_BROKER_PATH,
               db_path: Path = DEFAULT_DB_PATH,
               pool_end_date: str | None = None) -> pd.DataFrame:
    """Build key broker pool.

    Args:
        broker_path: parquet path with date, ticker, broker_id, broker_name, net_shares
        db_path: four-seasons DB for close percentiles
        pool_end_date: if set, only use broker data ≤ this date (warmup window)
            for pool building. None = use all available data.

    Returns:
        DataFrame: ticker, broker_id, broker_name, score,
                   total_appearances, low_buy_count, high_sell_count
    """
    if not broker_path.exists():
        raise FileNotFoundError(f"Broker trades parquet missing: {broker_path}")

    bdf = pd.read_parquet(broker_path)
    bdf["date"] = pd.to_datetime(bdf["date"])
    if pool_end_date:
        bdf = bdf[bdf["date"] <= pd.Timestamp(pool_end_date)]
    print(f"Broker trades: {len(bdf)} rows, {bdf['ticker'].nunique()} tickers, "
          f"{bdf['date'].nunique()} days")

    # 排除 self-loop / 外資相關分點：FinMind 給的 securities_trader_id 都是國內券商
    # （外資是統一歸到 9100~9200 區段、不是分點概念）。這邊用一個保守 filter：
    # 排除 broker_id 開頭 "9" 之外的所有國內分點。
    # 實測 broker_id 是 4 位數字 string、外資分點通常 9 開頭 (e.g. 9100 港麥格理)。
    # 為了保留「凱基 / 永豐 / 元大」等真正本土分點、用 startswith filter。
    bdf["broker_id"] = bdf["broker_id"].astype(str)
    # 不過濾外資（老師教法是「分點」、含外資也可、本地分點才是核心但不強制排除）。
    # → 留待 pool 分數判定時自然篩出低買高賣的。

    # 篩出量 ≥ MIN_ACTION_SHARES 的 broker-day
    bdf["abs_action"] = bdf[["buy_shares", "sell_shares"]].max(axis=1)
    actions = bdf[bdf["abs_action"] >= MIN_ACTION_SHARES].copy()
    print(f"Actions ≥ {MIN_ACTION_SHARES//1000} 張: {len(actions)} rows")

    # Attach close + percentiles
    px = _load_close_percentiles(actions.rename(columns={"date": "trade_date"})[["ticker", "trade_date"]],
                                  db_path)
    actions["trade_date"] = pd.to_datetime(actions["date"])
    actions = actions.merge(px, on=["ticker", "trade_date"], how="left")

    # 標記 low_buy / high_sell
    # 低買: net > 0 + close ≤ p25
    # 高賣: net < 0 + close ≥ p75
    actions["is_low_buy"] = (
        (actions["net_shares"] > 0) &
        (actions["close"] <= actions["p25_30d"])
    ).fillna(False)
    actions["is_high_sell"] = (
        (actions["net_shares"] < 0) &
        (actions["close"] >= actions["p75_30d"])
    ).fillna(False)

    # Aggregate per (ticker, broker_id)
    pool = actions.groupby(["ticker", "broker_id", "broker_name"], as_index=False).agg(
        total_appearances=("date", "count"),
        low_buy_count=("is_low_buy", "sum"),
        high_sell_count=("is_high_sell", "sum"),
    )
    pool["score"] = (
        (pool["low_buy_count"] + pool["high_sell_count"]) / pool["total_appearances"]
    )

    # Filter min appearances + sort + take top N per ticker
    pool = pool[pool["total_appearances"] >= MIN_APPEARANCES].copy()
    pool = pool.sort_values(["ticker", "score", "total_appearances"],
                            ascending=[True, False, False])
    pool["rank"] = pool.groupby("ticker").cumcount() + 1
    pool = pool[pool["rank"] <= TOP_N_PER_TICKER].drop(columns=["rank"])

    return pool


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default=str(DEFAULT_BROKER_PATH))
    ap.add_argument("--pool-end", default="2026-04-30",
                    help="只用此日期及之前的 broker_trades 建池（避免 lookahead）")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    pool = build_pool(Path(args.broker), pool_end_date=args.pool_end)
    print(f"\nPool: {len(pool)} (ticker, broker) pairs across "
          f"{pool['ticker'].nunique()} tickers")
    print(f"Avg score: {pool['score'].mean():.3f}, max: {pool['score'].max():.3f}")
    print(f"Top 10 pairs by score:")
    print(pool.nlargest(10, "score")[
        ["ticker", "broker_name", "score", "total_appearances", "low_buy_count", "high_sell_count"]
    ].to_string(index=False))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pool.to_parquet(out, index=False)
    print(f"\nSaved → {out}")


if __name__ == "__main__":
    main()
