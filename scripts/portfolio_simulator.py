from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

OUT_DIR = Path("data/analysis/kline_course_backtest")
MKTCAP_PATH = OUT_DIR / "market_cap_monthly.csv"

INITIAL_CAPITAL = 3_000_000  # TWD
MAX_POSITIONS = 5
ROUND_TRIP_COST = 0.00585

# 最低流動性門檻（日均成交量，股）
MIN_AVG_VOLUME = 500_000


def load_market_cap() -> pd.DataFrame | None:
    """載入月度市值快照，回傳 [ticker, date, market_value]。

    用 forward-fill 填補缺失月份（以最近已知市值代替）。
    """
    if not MKTCAP_PATH.exists():
        return None
    mc = pd.read_csv(MKTCAP_PATH, parse_dates=["date"])
    mc["market_value"] = pd.to_numeric(mc["market_value"], errors="coerce")
    return mc.dropna(subset=["market_value"])


def build_market_cap_lookup(mc: pd.DataFrame) -> dict[str, dict]:
    """建立 {ticker: [(date, market_value), ...]} 查詢表（依日期排序）。"""
    result: dict[str, list] = {}
    for row in mc.sort_values("date").itertuples(index=False):
        result.setdefault(row.ticker, []).append((row.date, row.market_value))
    return result


def get_market_cap(lookup: dict, ticker: str, as_of: pd.Timestamp) -> float:
    """取 as_of 當日或之前最近的市值快照。"""
    entries = lookup.get(str(ticker), [])
    if not entries:
        return 0.0
    # 找最接近且 <= as_of 的快照
    val = 0.0
    for date, mv in entries:
        if pd.Timestamp(date) <= as_of:
            val = mv
        else:
            break
    return val


# ---------------------------------------------------------------------------
# 選股策略
# ---------------------------------------------------------------------------

def _add_selection_features(
    candidates: pd.DataFrame,
    mc_lookup: dict | None = None,
    as_of: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """補充選股用衍生欄位，包含真實市值（若有）。"""
    c = candidates.copy()
    # 代理市值（備用）
    if "avg_volume_20" in c.columns and "close" in c.columns:
        c["market_cap_proxy"] = c["avg_volume_20"] * c["close"]
    # 真實市值
    if mc_lookup is not None and as_of is not None:
        c["market_cap"] = c["ticker"].apply(
            lambda t: get_market_cap(mc_lookup, t, as_of)
        )
        # 有真實市值時以 market_cap 為主，否則 fallback 到代理
        c["market_cap_final"] = np.where(
            c["market_cap"] > 0, c["market_cap"], c.get("market_cap_proxy", 0)
        )
    else:
        c["market_cap_final"] = c.get("market_cap_proxy", 0)
    if "close" in c.columns and "prior_high_60" in c.columns:
        c["breakout_strength_pct"] = (c["close"] / c["prior_high_60"].replace(0, np.nan) - 1) * 100
    return c


def select_random(candidates: pd.DataFrame, n: int, rng: np.random.Generator) -> pd.DataFrame:
    k = min(n, len(candidates))
    return candidates.sample(k, random_state=int(rng.integers(1 << 30)))


def select_by_volume(candidates: pd.DataFrame, n: int, **_) -> pd.DataFrame:
    return candidates.nlargest(n, "avg_volume_20")


def select_by_market_cap(candidates: pd.DataFrame, n: int, **_) -> pd.DataFrame:
    col = "market_cap_final" if "market_cap_final" in candidates.columns else "market_cap_proxy"
    return candidates.nlargest(n, col)


def select_by_attack_quality(candidates: pd.DataFrame, n: int, **_) -> pd.DataFrame:
    return candidates.nlargest(n, "attack_quality_score")


def select_by_breakout_strength(candidates: pd.DataFrame, n: int, **_) -> pd.DataFrame:
    return candidates.nlargest(n, "breakout_strength_pct")


def select_composite(candidates: pd.DataFrame, n: int, **_) -> pd.DataFrame:
    """課程指標複合排序：先過流動性，再依 attack_quality → volume → overhead(少)。"""
    pool = candidates[candidates["avg_volume_20"] >= MIN_AVG_VOLUME].copy()
    if pool.empty:
        pool = candidates.copy()
    # overhead_supply_layer 越少越好 → 轉為負值升序
    pool["_oh"] = -pool["overhead_supply_layer"].fillna(999)
    return pool.sort_values(
        ["attack_quality_score", "avg_volume_20", "_oh"],
        ascending=[False, False, False],
    ).head(n)


def _mcap_percentile_filter(candidates: pd.DataFrame, pct: float) -> pd.DataFrame:
    """保留市值（真實或代理）在前 pct% 的標的。"""
    col = "market_cap_final" if "market_cap_final" in candidates.columns else "market_cap_proxy"
    if col not in candidates.columns or candidates.empty:
        return candidates
    threshold = candidates[col].quantile(1 - pct)
    filtered = candidates[candidates[col] >= threshold]
    return filtered if not filtered.empty else candidates


def select_mcap_then_attack(candidates: pd.DataFrame, n: int, **_) -> pd.DataFrame:
    """先過市值前 50%，再用 attack_quality 排序。"""
    pool = _mcap_percentile_filter(candidates, 0.50)
    return pool.nlargest(n, "attack_quality_score")


def select_mcap30_then_attack(candidates: pd.DataFrame, n: int, **_) -> pd.DataFrame:
    """先過市值前 30%（更嚴），再用 attack_quality 排序。"""
    pool = _mcap_percentile_filter(candidates, 0.30)
    return pool.nlargest(n, "attack_quality_score")


def select_mcap_then_composite(candidates: pd.DataFrame, n: int, **_) -> pd.DataFrame:
    """先過市值前 50%，再依 attack_quality → volume → overhead 複合排序。"""
    pool = _mcap_percentile_filter(candidates, 0.50)
    pool = pool.copy()
    pool["_oh"] = -pool["overhead_supply_layer"].fillna(999)
    return pool.sort_values(
        ["attack_quality_score", "avg_volume_20", "_oh"],
        ascending=[False, False, False],
    ).head(n)


def select_volume_then_attack(candidates: pd.DataFrame, n: int, **_) -> pd.DataFrame:
    """先過流動性前 50%，再用 attack_quality 排序。"""
    if candidates.empty:
        return candidates
    vol_threshold = candidates["avg_volume_20"].quantile(0.50)
    pool = candidates[candidates["avg_volume_20"] >= vol_threshold]
    if pool.empty:
        pool = candidates
    return pool.nlargest(n, "attack_quality_score")


STRATEGIES: dict[str, Callable] = {
    "random":               select_random,
    "volume":               select_by_volume,
    "market_cap_proxy":     select_by_market_cap,
    "attack_quality":       select_by_attack_quality,
    "breakout_strength":    select_by_breakout_strength,
    "composite":            select_composite,
    # 新增組合策略
    "mcap50_attack":        select_mcap_then_attack,
    "mcap30_attack":        select_mcap30_then_attack,
    "mcap50_composite":     select_mcap_then_composite,
    "vol50_attack":         select_volume_then_attack,
}


# ---------------------------------------------------------------------------
# 主模擬引擎
# ---------------------------------------------------------------------------

def simulate_portfolio(
    trades: pd.DataFrame,
    signals_df: pd.DataFrame,
    strategy_name: str = "composite",
    initial_capital: float = INITIAL_CAPITAL,
    max_positions: int = MAX_POSITIONS,
    random_seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """模擬固定資金的組合操作。

    Args:
        trades:          simulate_exits() 的輸出（含 signal_date, ticker, entry_open,
                         exit_date, exit_price, trade_return_net）
        signals_df:      完整的 add_signals(add_features(...)) DataFrame，用於取選股欄位
        strategy_name:   STRATEGIES 的 key
        initial_capital: 初始資金（TWD）
        max_positions:   最大持倉檔數

    Returns:
        executed_trades: 實際執行的交易明細
        capital_curve:   每日資金曲線
    """
    selection_fn = STRATEGIES[strategy_name]
    rng = np.random.default_rng(random_seed)
    pos_size = initial_capital / max_positions  # 每檔固定金額

    # 建立訊號特徵查詢表（ticker × signal_date → 特徵列）
    sig_cols = [
        "ticker", "trade_date",
        "avg_volume_20", "close", "prior_high_60",
        "attack_quality_score", "overhead_supply_layer",
        "close_pos", "volume_ratio",
    ]
    available_cols = [c for c in sig_cols if c in signals_df.columns]
    sig_features = (
        signals_df[signals_df["breakout_attack"]][available_cols]
        .copy()
        .rename(columns={"trade_date": "signal_date"})
    )
    sig_features["signal_date"] = pd.to_datetime(sig_features["signal_date"])

    # 合併出場資料與特徵
    trades_aug = trades.merge(
        sig_features,
        on=["ticker", "signal_date"],
        how="left",
    )
    # 載入真實市值 lookup
    mc_data = load_market_cap()
    mc_lookup = build_market_cap_lookup(mc_data) if mc_data is not None else None

    trades_aug = _add_selection_features(trades_aug)  # 先算代理市值
    trades_aug["signal_date"] = pd.to_datetime(trades_aug["signal_date"])
    trades_aug["exit_date"] = pd.to_datetime(trades_aug["exit_date"])

    # 所有交易日（排序）
    all_dates = sorted(
        pd.to_datetime(signals_df["trade_date"].unique())
    )

    open_positions: dict[str, dict] = {}  # ticker → trade info
    executed_rows: list[dict] = []
    capital_curve: list[dict] = []

    cash = initial_capital

    for date in all_dates:
        # 1. 結算今日出場的部位
        to_close = [
            t for t, info in open_positions.items()
            if info["exit_date"] <= date
        ]
        for ticker in to_close:
            info = open_positions.pop(ticker)
            realized = pos_size * (1 + info["trade_return_net"])
            cash += realized
            executed_rows.append({
                **info,
                "actual_pnl_twd": round(realized - pos_size, 0),
                "strategy": strategy_name,
            })

        # 2. 計算今日帳面資產（未實現 + 現金）
        # 簡化：未實現按出場訊號前一交易日收盤估算（此處略，只記錄現金）
        capital_curve.append({
            "date": date,
            "cash": round(cash, 0),
            "open_positions": len(open_positions),
            "capital_deployed": len(open_positions) * pos_size,
        })

        # 3. 查今日可進場的新訊號（昨日收盤後形成，今日開盤進場）
        prev_date = date - pd.tseries.offsets.BDay(1)
        pending = trades_aug[
            (trades_aug["signal_date"] >= prev_date)
            & (trades_aug["signal_date"] < date)
        ].copy()

        # 排除已持有同一檔的訊號
        pending = pending[~pending["ticker"].isin(open_positions)]
        pending = pending.dropna(subset=["entry_open"])

        # 補上真實市值（以訊號日為 as_of）
        if mc_lookup is not None and not pending.empty:
            pending = _add_selection_features(pending, mc_lookup=mc_lookup, as_of=date)

        available_slots = max_positions - len(open_positions)
        if available_slots <= 0 or pending.empty:
            continue

        # 4. 依策略選股
        selected = selection_fn(pending, available_slots, rng=rng)

        # 5. 開倉
        for _, row in selected.iterrows():
            open_positions[row["ticker"]] = {
                "ticker": row["ticker"],
                "signal_date": row["signal_date"],
                "entry_open": row["entry_open"],
                "exit_date": row["exit_date"],
                "exit_price": row["exit_price"],
                "exit_reason": row["exit_reason"],
                "hold_days": row["hold_days"],
                "trade_return_net": row["trade_return_net"],
                "pos_size_twd": pos_size,
            }
            cash -= pos_size

    # 結算未平倉（期末以出場模擬結果計算）
    for ticker, info in open_positions.items():
        realized = pos_size * (1 + info["trade_return_net"])
        cash += realized
        executed_rows.append({
            **info,
            "actual_pnl_twd": round(realized - pos_size, 0),
            "strategy": strategy_name,
        })

    executed = pd.DataFrame(executed_rows) if executed_rows else pd.DataFrame()
    curve = pd.DataFrame(capital_curve)
    if not curve.empty:
        curve["total_capital"] = curve["cash"] + curve["capital_deployed"]

    return executed, curve


# ---------------------------------------------------------------------------
# 策略比較
# ---------------------------------------------------------------------------

def compare_strategies(
    trades: pd.DataFrame,
    signals_df: pd.DataFrame,
    strategies: list[str] | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    max_positions: int = MAX_POSITIONS,
    n_random_seeds: int = 20,
) -> pd.DataFrame:
    """比較多個選股策略的組合績效。"""
    if strategies is None:
        strategies = list(STRATEGIES.keys())

    rows = []
    for name in strategies:
        seeds = range(n_random_seeds) if name == "random" else [42]
        results_for_strategy = []
        for seed in seeds:
            executed, curve = simulate_portfolio(
                trades, signals_df,
                strategy_name=name,
                initial_capital=initial_capital,
                max_positions=max_positions,
                random_seed=seed,
            )
            if executed.empty:
                continue
            final_cap = (
                executed["actual_pnl_twd"].sum() + initial_capital
            )
            total_return = (final_cap - initial_capital) / initial_capital
            win_rate = (executed["actual_pnl_twd"] > 0).mean()
            n_trades = len(executed)
            avg_hold = executed["hold_days"].mean()
            results_for_strategy.append({
                "total_return": total_return,
                "final_capital": final_cap,
                "win_rate": win_rate,
                "n_trades": n_trades,
                "avg_hold_days": avg_hold,
            })

        if not results_for_strategy:
            continue
        agg = pd.DataFrame(results_for_strategy)
        rows.append({
            "strategy": name,
            "total_return_pct": round(float(agg["total_return"].mean() * 100), 2),
            "final_capital": round(float(agg["final_capital"].mean()), 0),
            "win_rate_pct": round(float(agg["win_rate"].mean() * 100), 2),
            "n_trades_avg": round(float(agg["n_trades"].mean()), 1),
            "avg_hold_days": round(float(agg["avg_hold_days"].mean()), 1),
            # random 策略額外顯示分布
            "p10_return_pct": round(float(agg["total_return"].quantile(0.10) * 100), 2),
            "p90_return_pct": round(float(agg["total_return"].quantile(0.90) * 100), 2),
        })

    return pd.DataFrame(rows).sort_values("total_return_pct", ascending=False)


# ---------------------------------------------------------------------------
# 進入點
# ---------------------------------------------------------------------------

def main() -> None:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from kline_course_backtest import add_features, add_signals, load_bars
    from exit_simulation import simulate_exits

    import warnings
    warnings.filterwarnings("ignore")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("載入資料與出場模擬...")
    df = add_signals(add_features(load_bars()))
    trades = simulate_exits(df)

    print(f"訊號數：{len(trades)}，比較 {len(STRATEGIES)} 種選股策略...")
    comparison = compare_strategies(trades, df)

    out_path = OUT_DIR / "portfolio_strategy_comparison.csv"
    comparison.to_csv(out_path, index=False)

    print("\n=== 選股策略比較（初始資金 300萬，最多 5 檔）===")
    print(comparison.to_string(index=False))
    print(f"\n{out_path}")


if __name__ == "__main__":
    main()
