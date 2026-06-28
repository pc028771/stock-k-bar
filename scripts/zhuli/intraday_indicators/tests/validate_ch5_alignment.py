"""Ch5 補強 indicator 對齊測 — 跑歷史日老師案例、看 indicator 是否在合理時點觸發。

用法:
    python -m zhuli.intraday_indicators.tests.validate_ch5_alignment \
        --ticker 2481 --date 2026-05-19 \
        --teacher-action "9:16 賣、後段站回再買回 130附近、跌 700 點大盤"

每根 5K 跑一次所有 Ch5 補強 indicator、輸出時間軸表格。
"""
from __future__ import annotations

import argparse
import sys
from datetime import date as date_cls
from pathlib import Path

import pandas as pd

# Path
_HERE = Path(__file__).parent
_REPO = _HERE.parent.parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common.clients.finmind_client import get_client


def fetch_data(ticker: str, target_date: str) -> tuple[pd.DataFrame, pd.DataFrame, float]:
    """抓 5m K + 1m K + 前日收盤。"""
    # 抓 1m K (target date)
    df_raw = get_client().fetch_dataset(
        dataset="TaiwanStockKBar",
        data_id=ticker,
        start_date=target_date,
        end_date=target_date,
        bypass_cache=True,
    )
    d = df_raw.to_dict("records") if not df_raw.empty else []
    if not d:
        raise SystemExit(f"無 1m K 資料：{ticker} {target_date}")
    k1m = pd.DataFrame(d)
    k1m["datetime"] = pd.to_datetime(k1m["date"].astype(str) + " " + k1m["minute"].astype(str))
    k1m = k1m.sort_values("datetime").set_index("datetime")
    for c in ("open", "high", "low", "close", "volume"):
        if c in k1m.columns:
            k1m[c] = pd.to_numeric(k1m[c], errors="coerce")

    # resample 5m
    k5m = k1m.resample("5min", label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"),
    ).dropna(subset=["open", "close"])

    # 前一交易日收盤
    from datetime import datetime, timedelta
    d_dt = datetime.strptime(target_date, "%Y-%m-%d")
    prev_close = 0.0
    for back in range(1, 10):
        d_prev = (d_dt - timedelta(days=back)).strftime("%Y-%m-%d")
        df_p = get_client().fetch_dataset(
            dataset="TaiwanStockPrice",
            data_id=ticker,
            start_date=d_prev,
            end_date=d_prev,
            bypass_cache=True,
        )
        dd = df_p.to_dict("records") if not df_p.empty else []
        if dd:
            prev_close = float(dd[0]["close"])
            break

    return k5m, k1m, prev_close


def run_indicators_at(
    k5_so_far: pd.DataFrame,
    k1m_so_far: pd.DataFrame,
    prev_close: float,
    prev_was_limit_up: bool,
    daily_closes: pd.Series,
) -> dict:
    """跑所有 Ch5 補強 indicator、回傳 {name: result_dict}。"""
    from zhuli.intraday_indicators import (
        check_first5min_skip, check_ma_divergence,
        check_b5_1_stop_profit, check_b5_2_limit_up_pattern,
        check_b5_3_quarterly_ma_short_filter,
    )

    out = {}
    out["紅線#9 前 5 分 >5%"] = check_first5min_skip(k1m_so_far)
    out["B5-1 5K 大紅棒 ≥5%"] = check_b5_1_stop_profit(k5_so_far, timeframe="5m")
    if prev_was_limit_up:
        out["B5-2 漲停隔日 A/B 型"] = check_b5_2_limit_up_pattern(
            k5_so_far, prev_close, True
        )
    if not daily_closes.empty:
        out["B5-3 季線往上不空"] = check_b5_3_quarterly_ma_short_filter(daily_closes)
    out["均線發散 > 3%"] = check_ma_divergence(k5_so_far)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ticker", required=True)
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--teacher-action", default="", help="老師當天動作描述（記錄用）")
    p.add_argument("--check-every", type=int, default=15,
                   help="每 N 分鐘輸出一次 indicator 狀態（預設 15）")
    p.add_argument("--prev-was-limit-up", action="store_true",
                   help="昨日是否漲停（B5-2 用）")
    args = p.parse_args()

    print(f"=== Ch5 補強對齊測 {args.ticker} {args.date} ===")
    if args.teacher_action:
        print(f"老師動作：{args.teacher_action}")
    print()

    k5m, k1m, prev_close = fetch_data(args.ticker, args.date)
    print(f"5K bars: {len(k5m)} / 1m bars: {len(k1m)} / 前日收 {prev_close:.2f}")
    print()

    # 取近 80 天日 K（給 B5-3）
    from datetime import datetime, timedelta
    d_dt = datetime.strptime(args.date, "%Y-%m-%d")
    start = (d_dt - timedelta(days=140)).strftime("%Y-%m-%d")
    df_d = get_client().fetch_dataset(
        dataset="TaiwanStockPrice",
        data_id=args.ticker,
        start_date=start,
        end_date=args.date,
        bypass_cache=True,
    )
    dd = df_d.to_dict("records") if not df_d.empty else []
    daily_closes = pd.Series(
        [float(x["close"]) for x in dd],
        index=pd.to_datetime([x["date"] for x in dd]),
    ).sort_index()
    print(f"日 K bars: {len(daily_closes)} (近 ~6 個月)")
    print()

    # 時間軸 walk-through
    # 每 args.check_every 分鐘輸出一次（基於 1m K index）
    print(f"=== 時間軸 walk (每 {args.check_every} 分一筆) ===")
    print(f"{'時間':<10} {'價':>7} {'indicator':<25} {'trigger':<10} reason")
    print("-" * 90)

    fired_times: list[tuple[str, str, str]] = []
    for i in range(args.check_every, len(k1m) + 1, args.check_every):
        t = k1m.index[i - 1]
        k1m_so_far = k1m.iloc[:i]
        k5m_so_far = k5m[k5m.index <= t]
        if k5m_so_far.empty:
            continue
        price = float(k5m_so_far["close"].iloc[-1])

        results = run_indicators_at(
            k5m_so_far, k1m_so_far, prev_close,
            args.prev_was_limit_up, daily_closes,
        )
        first_print = True
        for name, r in results.items():
            tag = "🔴 fire" if r["triggered"] else "—"
            reason = r["reason"][:50]
            if r["triggered"]:
                fired_times.append((t.strftime("%H:%M"), name, reason))
            ts = t.strftime("%H:%M") if first_print else ""
            pr = f"{price:.2f}" if first_print else ""
            print(f"{ts:<10} {pr:>7} {name:<25} {tag:<10} {reason}")
            first_print = False
        print()

    # 觸發摘要
    print("=== 觸發摘要 ===")
    if not fired_times:
        print("無 indicator 觸發、整日靜")
    else:
        for ts, name, reason in fired_times:
            print(f"  {ts}  {name}  → {reason}")

    print()
    if args.teacher_action:
        print(f"老師動作：{args.teacher_action}")
        print(f"→ 比對是否在合理時點觸發？")


if __name__ == "__main__":
    main()
