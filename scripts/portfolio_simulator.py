from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

OUT_DIR = Path("data/analysis/kline_course_backtest")
MKTCAP_PATH = OUT_DIR / "market_cap_monthly.csv"
STOCK_INFO_PATH = OUT_DIR / "stock_info.csv"

INITIAL_CAPITAL = 3_000_000  # TWD
MAX_POSITIONS = 5
ROUND_TRIP_COST = 0.00585

# 最低流動性門檻（日均成交量，股）
MIN_AVG_VOLUME = 500_000

# ---------------------------------------------------------------------------
# 大盤模式判斷（用於自動切換策略）
# ---------------------------------------------------------------------------

# 模式定義與操作邏輯說明
REGIME_PLAYBOOK = {
    "bull": {
        "description": "多頭：市場指數 > MA20 > MA60",
        "rationale": "多頭期訊號多、強股多，以分散持有取量",
        "sizing_mode": "equal_1lot_all",
        "max_positions": 20,
        "price_ceiling": None,
    },
    "range": {
        "description": "盤整：市場指數介於多頭與空頭之間",
        "rationale": "盤整期突破股往往是真正的強勢股，繼續用分散但稍微收斂",
        "sizing_mode": "equal_1lot_all",
        "max_positions": 15,
        "price_ceiling": None,
    },
    "crash": {
        "description": "震盪/修正：TAIEX 10 日跌幅 > 8%",
        "rationale": "急跌後反彈力道強，改用 max_lots 集中押便宜彈力股",
        "sizing_mode": "max_lots",
        "max_positions": 5,
        "price_ceiling": 300,
    },
    "bear": {
        "description": "空頭：市場指數 < MA20 < MA60",
        "rationale": "空頭幾乎無突破訊號，保守觀望；有的話用 max_lots 嚴格篩",
        "sizing_mode": "max_lots",
        "max_positions": 3,
        "price_ceiling": 200,
    },
}


def detect_daily_regime(
    market_regime_series: pd.Series,
    taiex: pd.DataFrame,
) -> pd.Series:
    """每日大盤模式判斷，回傳 {date: regime_key}。

    優先級：crash > bear > range > bull
    crash 條件：TAIEX 10 日報酬 < -8%（急跌）
    """
    taiex = taiex.set_index("date").sort_index()
    taiex["ret_10d"] = taiex["close"].pct_change(10)

    regime_map = market_regime_series.copy()  # index = trade_date, value = bull/range/bear

    result: dict[pd.Timestamp, str] = {}
    for date in regime_map.index:
        ts = pd.Timestamp(date)
        base = regime_map.loc[date]

        # 查 TAIEX 10 日報酬
        taiex_slice = taiex[taiex.index <= ts]
        ret_10d = float(taiex_slice["ret_10d"].iloc[-1]) if not taiex_slice.empty else 0.0

        if ret_10d < -0.08:
            result[ts] = "crash"
        else:
            result[ts] = base  # bull / range / bear

    return pd.Series(result)


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


def load_excluded_sectors() -> set[str]:
    """載入需排除的產業類股（建材營造）。"""
    if not STOCK_INFO_PATH.exists():
        return set()
    info = pd.read_csv(STOCK_INFO_PATH, dtype=str)
    excluded = info[
        info["industry_category"].str.contains("建材營造", na=False)
    ]["stock_id"].astype(str).tolist()
    return set(excluded)


def build_rank_lookup(
    mc: pd.DataFrame,
    top_n: int = 100,
    excluded_tickers: set[str] | None = None,
) -> dict[pd.Timestamp, set[str]]:
    """建立每月市值前 N 名的 ticker 集合。

    排除：ETF（00開頭）、指定產業類股（如建材營造）。
    只保留上市/上櫃個股（1-9開頭的4碼數字代號）。
    """
    if excluded_tickers is None:
        excluded_tickers = set()
    mc_stocks = mc[
        mc["ticker"].str.fullmatch(r"[1-9]\d{3}")
        & ~mc["ticker"].isin(excluded_tickers)
    ].copy()
    result: dict[pd.Timestamp, set[str]] = {}
    for date, grp in mc_stocks.groupby("date"):
        ranked = grp.nlargest(top_n, "market_value")
        result[pd.Timestamp(date)] = set(ranked["ticker"].astype(str))
    return result


def get_top_n_set(rank_lookup: dict, as_of: pd.Timestamp) -> set[str]:
    """取 as_of 當日或之前最近的前 N 名集合。"""
    candidates = [d for d in rank_lookup if d <= as_of]
    if not candidates:
        return set()
    return rank_lookup[max(candidates)]


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


def select_top100_attack(candidates: pd.DataFrame, n: int, **_) -> pd.DataFrame:
    """限定市值前百大（已在 simulate_portfolio 用 rank_set 過濾），再依 attack_quality 排序。"""
    return candidates.nlargest(n, "attack_quality_score")


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
    "top100_attack":        select_top100_attack,
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
    max_price_per_share: float | None = None,
    sizing_mode: str = "fixed_amount",
    fixed_lots: int | None = None,
    rank_set: dict | None = None,
    regime_series: pd.Series | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    sizing_mode:
        "fixed_amount"      — 固定金額（initial_capital / max_positions）
        "max_lots"          — 以固定金額預算買最多整張（最多 max_positions 檔）
        "flex_lots"         — 動態預算（剩餘資金 / 剩餘空位），最多 max_positions 檔
        "fixed_lots"        — 固定 fixed_lots 張，買不起就跳過
        "equal_1lot_all"    — 當日全部候選各買 1 張，依序買到資金用完為止（不限檔數）
        "adaptive"          — 依 regime_series 自動切換策略（需傳入 regime_series）
    rank_set: build_rank_lookup() 的輸出，若提供則只允許前 N 名進場
    regime_series: {date: 'bull'/'range'/'crash'/'bear'}，adaptive 模式使用
    """
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
    budget_per_slot = initial_capital / max_positions  # 每檔預算上限

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
            realized = info["pos_size_twd"] * (1 + info["trade_return_net"])
            cash += realized
            executed_rows.append({
                **info,
                "actual_pnl_twd": round(realized - info["pos_size_twd"], 0),
                "strategy": strategy_name,
            })

        # 2. 計算今日帳面資產（未實現 + 現金）
        # 簡化：未實現按出場訊號前一交易日收盤估算（此處略，只記錄現金）
        capital_curve.append({
            "date": date,
            "cash": round(cash, 0),
            "open_positions": len(open_positions),
            "capital_deployed": sum(info["pos_size_twd"] for info in open_positions.values()),
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

        # 市值排名過濾（前 N 大）
        if rank_set is not None:
            allowed = get_top_n_set(rank_set, date)
            if allowed:
                pending = pending[pending["ticker"].astype(str).isin(allowed)]

        # 可負擔過濾：每張（1000股）不超過每檔預算
        if max_price_per_share is not None and "close" in pending.columns:
            pending = pending[pending["close"] <= max_price_per_share]

        if pending.empty:
            continue

        # adaptive 模式：依當日 regime 動態調整 sizing 和 max_positions
        day_sizing = sizing_mode
        day_max_pos = max_positions
        day_price_ceil = max_price_per_share
        if sizing_mode == "adaptive" and regime_series is not None:
            day_regime = regime_series.get(date, "range")
            playbook = REGIME_PLAYBOOK.get(day_regime, REGIME_PLAYBOOK["range"])
            day_sizing = playbook["sizing_mode"]
            day_max_pos = playbook["max_positions"]
            day_price_ceil = playbook["price_ceiling"]
            if day_price_ceil is not None and "close" in pending.columns:
                pending = pending[pending["close"] <= day_price_ceil]
            if pending.empty:
                continue

        if day_sizing == "equal_1lot_all":
            selected = selection_fn(pending, len(pending), rng=rng)
            for _, row in selected.iterrows():
                entry_price = float(row["entry_open"]) if row["entry_open"] > 0 else float(row["close"])
                lot_cost = entry_price * 1000
                if lot_cost <= 0 or lot_cost > cash or len(open_positions) >= day_max_pos:
                    if len(open_positions) >= day_max_pos:
                        break
                    continue
                open_positions[row["ticker"]] = {
                    "ticker": row["ticker"], "signal_date": row["signal_date"],
                    "entry_open": entry_price, "exit_date": row["exit_date"],
                    "exit_price": row["exit_price"], "exit_reason": row["exit_reason"],
                    "hold_days": row["hold_days"], "trade_return_net": row["trade_return_net"],
                    "pos_size_twd": lot_cost, "lots": 1,
                }
                cash -= lot_cost
            continue

        available_slots = day_max_pos - len(open_positions)
        if available_slots <= 0:
            continue

        # 4. 依策略選股
        selected = selection_fn(pending, available_slots, rng=rng)

        # 5. 開倉
        for _, row in selected.iterrows():
            entry_price = float(row["entry_open"]) if row["entry_open"] > 0 else float(row["close"])
            lot_cost = entry_price * 1000  # 每張成本

            if day_sizing == "fixed_amount":
                actual_size = budget_per_slot
                lots = actual_size / lot_cost if lot_cost > 0 else 0
            elif day_sizing in ("max_lots", "adaptive"):
                lots = int(budget_per_slot / lot_cost) if lot_cost > 0 else 0
                if lots == 0:
                    continue
                actual_size = lots * lot_cost
            elif day_sizing == "flex_lots":
                # 動態預算：剩餘現金平分給剩餘空位
                slots_left = max(1, day_max_pos - len(open_positions))
                dynamic_budget = cash / slots_left
                lots = int(dynamic_budget / lot_cost) if lot_cost > 0 else 0
                if lots == 0:
                    continue
                actual_size = lots * lot_cost
            elif day_sizing == "fixed_lots":
                n_lots = fixed_lots or 1
                actual_size = n_lots * lot_cost
                if actual_size > cash or actual_size > budget_per_slot * 2:
                    continue
                lots = n_lots
            else:
                actual_size = budget_per_slot
                lots = actual_size / lot_cost if lot_cost > 0 else 0

            if actual_size > cash:
                continue

            open_positions[row["ticker"]] = {
                "ticker": row["ticker"],
                "signal_date": row["signal_date"],
                "entry_open": entry_price,
                "exit_date": row["exit_date"],
                "exit_price": row["exit_price"],
                "exit_reason": row["exit_reason"],
                "hold_days": row["hold_days"],
                "trade_return_net": row["trade_return_net"],
                "pos_size_twd": actual_size,
                "lots": round(lots, 2),
            }
            cash -= actual_size

    # 結算未平倉（期末以出場模擬結果計算）
    for ticker, info in open_positions.items():
        realized = info["pos_size_twd"] * (1 + info["trade_return_net"])
        cash += realized
        executed_rows.append({
            **info,
            "actual_pnl_twd": round(realized - info["pos_size_twd"], 0),
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

def sweep_sizing_mode(
    trades: pd.DataFrame,
    signals_df: pd.DataFrame,
    strategy_name: str = "mcap50_attack",
    initial_capital: float = INITIAL_CAPITAL,
    max_positions: int = MAX_POSITIONS,
    price_ceiling: float | None = 300,
) -> pd.DataFrame:
    """比較不同倉位規模策略的組合績效。"""
    configs = [
        ("固定金額 60萬",        "fixed_amount",   None),
        ("最多整張（≤預算）",     "max_lots",       None),
        ("全候選各1張買到用完",   "equal_1lot_all", None),
        ("固定 1 張（僅1檔）",   "fixed_lots",     1),
        ("固定 3 張",            "fixed_lots",     3),
        ("固定 5 張",            "fixed_lots",     5),
        ("固定 10 張",           "fixed_lots",     10),
    ]
    rows = []
    for label, mode, lots in configs:
        executed, _ = simulate_portfolio(
            trades, signals_df,
            strategy_name=strategy_name,
            initial_capital=initial_capital,
            max_positions=max_positions,
            max_price_per_share=price_ceiling,
            sizing_mode=mode,
            fixed_lots=lots,
        )
        if executed.empty:
            rows.append({"規模策略": label, "n_trades": 0,
                         "total_return_pct": float("nan"),
                         "final_capital": initial_capital,
                         "win_rate_pct": float("nan"),
                         "avg_hold_days": float("nan"),
                         "avg_lots": float("nan")})
            continue
        final_cap = executed["actual_pnl_twd"].sum() + initial_capital
        rows.append({
            "規模策略": label,
            "n_trades": len(executed),
            "total_return_pct": round((final_cap - initial_capital) / initial_capital * 100, 2),
            "final_capital": round(float(final_cap), 0),
            "win_rate_pct": round(float((executed["actual_pnl_twd"] > 0).mean() * 100), 2),
            "avg_hold_days": round(float(executed["hold_days"].mean()), 1),
            "avg_lots": round(float(executed.get("lots", pd.Series([float("nan")])).mean()), 2),
        })
    return pd.DataFrame(rows)


def sweep_price_ceiling(
    trades: pd.DataFrame,
    signals_df: pd.DataFrame,
    strategy_name: str = "mcap50_attack",
    initial_capital: float = INITIAL_CAPITAL,
    max_positions: int = MAX_POSITIONS,
    ceilings: list[float | None] | None = None,
) -> pd.DataFrame:
    """掃描不同每股價格上限對組合績效的影響。

    ceilings: 每股最高可接受價格列表（None = 不限）。
    預設測試範圍：不限 / 1000 / 800 / 600 / 500 / 300 / 200 / 100
    """
    if ceilings is None:
        ceilings = [None, 1000, 800, 600, 500, 300, 200, 100]

    pos_size = initial_capital / max_positions
    rows = []
    for ceiling in ceilings:
        executed, _ = simulate_portfolio(
            trades, signals_df,
            strategy_name=strategy_name,
            initial_capital=initial_capital,
            max_positions=max_positions,
            max_price_per_share=ceiling,
        )
        if executed.empty:
            label = f"≤{ceiling}" if ceiling else "無限制"
            rows.append({"price_ceiling": label, "n_trades": 0,
                         "total_return_pct": float("nan"),
                         "final_capital": initial_capital,
                         "win_rate_pct": float("nan"),
                         "avg_hold_days": float("nan"),
                         "lots_per_trade_min": float("nan")})
            continue

        final_cap = executed["actual_pnl_twd"].sum() + initial_capital
        total_ret = (final_cap - initial_capital) / initial_capital * 100
        win_rate = (executed["actual_pnl_twd"] > 0).mean() * 100
        # 估算每次進場可買幾張（以進場價格估計）
        if "entry_open" in executed.columns:
            lots = (pos_size / (executed["entry_open"] * 1000)).clip(upper=99)
            lots_min = round(float(lots.min()), 1)
        else:
            lots_min = float("nan")

        rows.append({
            "price_ceiling": f"≤{ceiling}" if ceiling else "無限制",
            "n_trades": int(len(executed)),
            "total_return_pct": round(float(total_ret), 2),
            "final_capital": round(float(final_cap), 0),
            "win_rate_pct": round(float(win_rate), 2),
            "avg_hold_days": round(float(executed["hold_days"].mean()), 1),
            "lots_per_trade_min": lots_min,
        })

    return pd.DataFrame(rows)


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
    import argparse, sys
    sys.path.insert(0, str(Path(__file__).parent))
    from kline_course_backtest import add_features, add_signals, load_bars
    from exit_simulation import simulate_exits

    import warnings
    warnings.filterwarnings("ignore")

    parser = argparse.ArgumentParser()
    parser.add_argument("--price-sweep", action="store_true", help="掃描價格上限")
    parser.add_argument("--sizing-sweep", action="store_true", help="掃描倉位規模策略")
    parser.add_argument("--top-n-sweep", action="store_true", help="比較前 50/100/200/500 大市值策略")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("載入資料與出場模擬...")
    df = add_signals(add_features(load_bars()))
    trades = simulate_exits(df)

    if args.sizing_sweep:
        print("掃描倉位規模策略（mcap50_attack，價格上限 ≤300）...")
        sweep = sweep_sizing_mode(trades, df)
        out = OUT_DIR / "portfolio_sizing_sweep.csv"
        sweep.to_csv(out, index=False)
        print("\n=== 不同倉位規模策略比較（初始資金 300萬，≤300元個股）===")
        print(sweep.to_string(index=False))
        print(f"\n{out}")
        return

    if args.price_sweep:
        print("掃描價格上限（策略：mcap50_attack）...")
        sweep = sweep_price_ceiling(trades, df)
        sweep_path = OUT_DIR / "portfolio_price_ceiling_sweep.csv"
        sweep.to_csv(sweep_path, index=False)
        print("\n=== 不同每股價格上限對組合績效的影響 ===")
        print(sweep.to_string(index=False))
        print(f"\n{sweep_path}")
        return

    if args.top_n_sweep:
        mc_data = load_market_cap()
        excluded = load_excluded_sectors()
        print(f"排除建材營造類股 {len(excluded)} 檔")
        rows = []
        for top_n in [50, 100, 200, 500, None]:  # None = 不限
            label = f"前{top_n}大" if top_n else "不限"
            rank_set = build_rank_lookup(mc_data, top_n=top_n, excluded_tickers=excluded) if top_n else None
            for price_ceil in [500, 1000, None]:
                ceil_label = f"≤{price_ceil}" if price_ceil else "無限制"
                executed, _ = simulate_portfolio(
                    trades, df,
                    strategy_name="top100_attack",
                    max_price_per_share=price_ceil,
                    sizing_mode="equal_1lot_all",
                    rank_set=rank_set,
                )
                if executed.empty:
                    rows.append({"市值範圍": label, "價格上限": ceil_label,
                                 "n_trades": 0, "total_return_pct": float("nan"),
                                 "final_capital": INITIAL_CAPITAL,
                                 "win_rate_pct": float("nan"), "avg_hold_days": float("nan")})
                    continue
                final_cap = executed["actual_pnl_twd"].sum() + INITIAL_CAPITAL
                rows.append({
                    "市值範圍": label,
                    "價格上限": ceil_label,
                    "n_trades": len(executed),
                    "total_return_pct": round((final_cap - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2),
                    "final_capital": round(float(final_cap), 0),
                    "win_rate_pct": round(float((executed["actual_pnl_twd"] > 0).mean() * 100), 2),
                    "avg_hold_days": round(float(executed["hold_days"].mean()), 1),
                })
        result = pd.DataFrame(rows)
        out = OUT_DIR / "portfolio_topn_sweep.csv"
        result.to_csv(out, index=False)
        print("\n=== 市值前 N 大 × 價格上限比較（全候選各1張，attack_quality排序）===")
        print(result.to_string(index=False))
        print(f"\n{out}")
        return

    print(f"訊號數：{len(trades)}，比較 {len(STRATEGIES)} 種選股策略...")
    comparison = compare_strategies(trades, df)
    out_path = OUT_DIR / "portfolio_strategy_comparison.csv"
    comparison.to_csv(out_path, index=False)
    print("\n=== 選股策略比較（初始資金 300萬，最多 5 檔）===")
    print(comparison.to_string(index=False))
    print(f"\n{out_path}")


if __name__ == "__main__":
    main()
