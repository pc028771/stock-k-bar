"""FinMind 抓資料策略 planner — 決定走單筆 (data_id) 還是全市場 (無 data_id).

使用：
    from zhuli.finmind_fetch_planner import decide_strategy
    plan = decide_strategy(n_tickers=85, n_days=1, dataset="TaiwanStockPrice")
    print(plan)
    # → {'mode': 'whole_market', 'calls': 1, 'est_seconds': 1.4, 'reason': '...'}

CLI:
    python scripts/zhuli/finmind_fetch_planner.py 85 1 TaiwanStockPrice
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

# 各 dataset 是否支援全市場 (無 data_id) mode
# True = 可全市場；False = 只能 single-ticker；None = 未驗證
DATASET_CAPS = {
    "TaiwanStockPrice": True,
    "TaiwanStockInstitutionalInvestorsBuySell": True,
    "TaiwanStockHoldingSharesPer": None,        # 待驗證
    "TaiwanStockTradingDailyReport": False,     # 強制 data_id + single day
    "TaiwanStockKBar": False,                   # 通常 data_id
    "TaiwanStockShareholding": True,
    "TaiwanStockMarginPurchaseShortSale": True,
}

# 單筆 call 估計時間 (秒)
PER_TICKER_CALL_SECONDS = 0.5
# 全市場 call 估計時間 (秒)
WHOLE_MARKET_CALL_SECONDS = 1.4
# 保守 throttle (every 10 calls sleep 1s)
THROTTLE_EVERY = 10
THROTTLE_SECONDS = 1.0


@dataclass
class FetchPlan:
    mode: str               # "single" / "whole_market" / "forced_single"
    calls: int
    est_seconds: float
    reason: str

    def __str__(self) -> str:
        m = int(self.est_seconds // 60)
        s = self.est_seconds - m * 60
        time_str = f"{m}m {s:.1f}s" if m > 0 else f"{s:.1f}s"
        return (f"mode={self.mode}  calls={self.calls}  est={time_str}\n  reason: {self.reason}")


def _est_single(n_tickers: int, n_days: int) -> float:
    """每 ticker 1 call (date range)；含 throttle."""
    calls = n_tickers
    throttle_pauses = calls // THROTTLE_EVERY
    return calls * PER_TICKER_CALL_SECONDS + throttle_pauses * THROTTLE_SECONDS


def _est_whole(n_days: int) -> float:
    """每日 1 call 全市場."""
    return n_days * WHOLE_MARKET_CALL_SECONDS


def decide_strategy(n_tickers: int, n_days: int, dataset: str = "TaiwanStockPrice") -> FetchPlan:
    """依 ticker 數 + 天數 + dataset 能力，回傳建議 strategy."""
    cap = DATASET_CAPS.get(dataset)
    if cap is False:
        # 強制 single-ticker
        return FetchPlan(
            mode="forced_single",
            calls=n_tickers * max(1, n_days),
            est_seconds=_est_single(n_tickers, n_days),
            reason=f"{dataset} 不支援全市場 mode，強制 single-ticker × {n_tickers} 檔",
        )
    if cap is None:
        return FetchPlan(
            mode="single",
            calls=n_tickers,
            est_seconds=_est_single(n_tickers, n_days),
            reason=f"{dataset} 全市場 mode 未驗證，保守用 single-ticker",
        )

    # cap is True — 比較兩 mode
    t_single = _est_single(n_tickers, n_days)
    t_whole = _est_whole(n_days)

    if t_whole < t_single:
        savings = (t_single - t_whole) / t_single * 100
        return FetchPlan(
            mode="whole_market",
            calls=n_days,
            est_seconds=t_whole,
            reason=f"全市場省 {savings:.0f}%（single 估 {t_single:.1f}s vs whole {t_whole:.1f}s）",
        )
    else:
        return FetchPlan(
            mode="single",
            calls=n_tickers,
            est_seconds=t_single,
            reason=f"ticker 少天數多，single 較快（single {t_single:.1f}s vs whole {t_whole:.1f}s）",
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("n_tickers", type=int)
    ap.add_argument("n_days", type=int)
    ap.add_argument("dataset", nargs="?", default="TaiwanStockPrice")
    args = ap.parse_args()

    plan = decide_strategy(args.n_tickers, args.n_days, args.dataset)
    print(plan)


if __name__ == "__main__":
    main()
