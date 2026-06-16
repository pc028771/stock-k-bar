"""主力分點異常警示模組.

資料源：FinMind TaiwanStockTradingDailyReport（單日請求）
策略：on-demand fetch 近 N 日，本地 disk cache 避免重複拉

公開 API:
    broker_warnings(ticker, lookback_days=5) -> tuple[int, list[str]]

⚠️ 課程紅線
本警示**不指定**進場/出場價，只標示「主力動向異常 → 應檢核」.
所有最終判斷仍以**收盤確認**為準（課程鐵則）.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

_common_parent = Path(__file__).parent.parent  # scripts/
if str(_common_parent) not in sys.path:
    sys.path.insert(0, str(_common_parent))
from common.finmind_client import get_client

_CACHE_DIR = Path.home() / ".zhuli_cache" / "broker"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 外資券商辨識關鍵字（含外資自營 / 港陸 / 新加坡商等通常被視為外資籌碼）
_FOREIGN_KEYWORDS = (
    "摩根", "瑞銀", "瑞士", "美林", "高盛", "花旗", "麥格理", "巴黎",
    "新加坡商", "野村", "匯豐", "渣打", "港商", "美商", "亞洲",
)


def _is_foreign(broker_name: str) -> bool:
    return any(k in broker_name for k in _FOREIGN_KEYWORDS)


def _fetch_broker_daily(ticker: str, date_str: str) -> pd.DataFrame:
    """單日 broker raw fetch，含 disk cache."""
    cache = _CACHE_DIR / f"{ticker}_{date_str}.json"
    if cache.exists():
        with cache.open() as f:
            data = json.load(f)
        return pd.DataFrame(data)

    try:
        df = get_client().fetch_dataset(
            dataset="TaiwanStockTradingDailyReport",
            data_id=ticker,
            start_date=date_str,
            bypass_cache=True,
        )
    except Exception as exc:
        raise RuntimeError(f"FinMind fetch failed: {exc}") from exc

    data = df.to_dict("records")
    with cache.open("w") as f:
        json.dump(data, f)
    return df


def _aggregate_broker(df_raw: pd.DataFrame) -> pd.DataFrame:
    """raw broker × price level → broker daily summary."""
    if df_raw.empty:
        return df_raw
    g = df_raw.groupby(
        ["securities_trader_id", "securities_trader"], as_index=False
    ).agg(total_buy=("buy", "sum"), total_sell=("sell", "sum"))
    g["net"] = g["total_buy"] - g["total_sell"]
    g["is_foreign"] = g["securities_trader"].apply(_is_foreign)
    return g


def _recent_trading_dates(target_date: str, lookback: int) -> list[str]:
    """從 target_date 倒推 lookback 個交易日（粗略：weekday only）."""
    d = datetime.strptime(target_date, "%Y-%m-%d")
    dates = []
    while len(dates) < lookback:
        if d.weekday() < 5:
            dates.append(d.strftime("%Y-%m-%d"))
        d -= timedelta(days=1)
    return list(reversed(dates))


def broker_warnings(
    ticker: str,
    target_date: str | None = None,
    lookback_days: int = 5,
) -> tuple[int, list[str]]:
    """近 N 日主力分點異常警示.

    Args:
        ticker: 股號
        target_date: 截止日（含），預設昨日（盤後分析）
        lookback_days: 回看天數

    Returns:
        (score, warning_lines)

    警示規則:
      1. 單一券商 lookback 累計賣超 > 50k 張（單檔重大主力出貨）→ +2 分
      2. 外資合計 lookback 累計賣超 > 5k 張（外資集體出貨）→ +2 分
      3. 同一券商「隔日反向」（前段大買後段大賣，net 翻轉 > 30k 張）→ +2 分
      4. 最新交易日 Top 5 賣超佔總賣超 > 40%（籌碼集中賣壓）→ +1 分
      5. 外資 lookback 累計買超 > 5k 張 → -1 分（買盤，警示降）
    """
    if target_date is None:
        target_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    dates = _recent_trading_dates(target_date, lookback_days)
    daily = []
    for d in dates:
        try:
            raw = _fetch_broker_daily(ticker, d)
        except Exception as exc:
            return 0, [f"  ? broker fetch 失敗 {d}: {exc}"]
        if raw.empty:
            continue
        agg = _aggregate_broker(raw)
        agg["date"] = d
        daily.append(agg)

    if not daily:
        return 0, [f"  ? broker 無資料 ({lookback_days} 日)"]

    combined = pd.concat(daily, ignore_index=True)

    # 5 日總成交量 = 各日 sum(total_buy)（每日 buy = sell = 成交張數）
    total_vol = combined.groupby("date")["total_buy"].sum().sum()
    if total_vol <= 0:
        return 0, ["  ? broker 5d 成交量為 0"]

    # === 規則 1: 單一券商 lookback 累計賣超 / 5d 總量 > 1.5% ===
    broker_total = combined.groupby(
        ["securities_trader_id", "securities_trader", "is_foreign"], as_index=False
    ).agg(net=("net", "sum"))
    broker_total["net_ratio"] = broker_total["net"] / total_vol

    triggers = []

    big_seller = broker_total[broker_total["net_ratio"] < -0.015].nsmallest(3, "net")
    if not big_seller.empty:
        names = "/".join(big_seller["securities_trader"].head(3))
        net_sum = big_seller["net"].sum()
        net_ratio_sum = big_seller["net_ratio"].sum() * 100
        triggers.append((
            "主力分點 重大賣超",
            f"{names} 近{lookback_days}日 {net_sum:+,.0f} 張 ({net_ratio_sum:+.1f}% 5d 量)",
            2,
        ))

    # === 規則 2: 外資合計賣超 / 5d 總量 > 1% ===
    foreign_net = broker_total[broker_total["is_foreign"]]["net"].sum()
    foreign_ratio = foreign_net / total_vol
    if foreign_ratio < -0.01:
        triggers.append((
            "外資集體出貨",
            f"近{lookback_days}日外資 {foreign_net:+,.0f} 張 ({foreign_ratio*100:+.1f}%)",
            2,
        ))
    elif foreign_ratio > 0.01:
        triggers.append((
            "外資買盤",
            f"近{lookback_days}日外資 {foreign_net:+,.0f} 張 ({foreign_ratio*100:+.1f}%)",
            -1,  # 買盤訊號 → 警示降
        ))

    # === 規則 3: 隔日反向 (前半 lookback 買 / 後半 lookback 賣) ===
    if len(dates) >= 4:
        mid = len(dates) // 2
        early_dates = dates[:mid]
        late_dates = dates[mid:]
        early = combined[combined["date"].isin(early_dates)].groupby(
            "securities_trader_id", as_index=False
        )["net"].sum().rename(columns={"net": "net_early"})
        late = combined[combined["date"].isin(late_dates)].groupby(
            "securities_trader_id", as_index=False
        )["net"].sum().rename(columns={"net": "net_late"})
        merged = early.merge(late, on="securities_trader_id")
        # 前期買 > 30k，後期賣 < -30k = 反向
        reversed_brokers = merged[
            (merged["net_early"] > 30000) & (merged["net_late"] < -30000)
        ]
        if not reversed_brokers.empty:
            # 拿 broker name
            name_map = combined.set_index("securities_trader_id")["securities_trader"].to_dict()
            names = [name_map.get(bid, bid) for bid in reversed_brokers["securities_trader_id"].head(3)]
            triggers.append((
                "主力反向出貨",
                f"{'/'.join(names)} 前半買→後半賣",
                2,
            ))

    # === 規則 4: 最新日 Top 5 賣超佔比 ===
    latest_date = dates[-1]
    latest = combined[combined["date"] == latest_date]
    if not latest.empty:
        sellers = latest[latest["net"] < 0]
        total_sell_net = sellers["net"].sum()
        if total_sell_net < 0:
            top5_sell_net = sellers.nsmallest(5, "net")["net"].sum()
            ratio = top5_sell_net / total_sell_net
            if ratio > 0.40:
                triggers.append((
                    "賣壓集中",
                    f"{latest_date} Top5 占總賣超 {ratio*100:.0f}%",
                    1,
                ))

    score = sum(t[2] for t in triggers)
    score = max(0, score)  # 不允許負分

    if score == 0:
        return 0, []

    lines = []
    for label, detail, pts in triggers:
        sign = f"+{pts}" if pts > 0 else f"{pts}"
        lines.append(f"      [{sign}分] {label} — {detail}")
    return score, lines


if __name__ == "__main__":
    # Spot check
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "8064"
    date = sys.argv[2] if len(sys.argv) > 2 else "2026-05-19"
    score, lines = broker_warnings(ticker, target_date=date, lookback_days=5)
    print(f"{ticker} {date}: score={score}")
    for ln in lines:
        print(ln)
