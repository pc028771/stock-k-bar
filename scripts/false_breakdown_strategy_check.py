from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from kline_course_backtest import add_features, add_signals, load_bars


OUT_DIR = Path("data/analysis/kline_course_backtest")
REPORT_PATH = Path("docs/K線力量判斷入門/backtests/false_breakdown_strategy_check.md")
FAILURE_REPORT_PATH = Path("docs/K線力量判斷入門/backtests/false_breakdown_failure_analysis.md")
SCANNER_REPORT_PATH = Path("docs/K線力量判斷入門/backtests/false_breakdown_daily_scanner.md")
HYBRID_STOP_REPORT_PATH = Path("docs/K線力量判斷入門/backtests/false_breakdown_hybrid_stop_analysis.md")

ROUND_TRIP_COST = 0.00585
MIN_AVG_VOLUME_20 = 500_000
MIN_CLOSE = 10
ATR_MULTIPLIER = 1.0


def add_market_regime(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    market = (
        df.dropna(subset=["prev_close"])
        .assign(stock_ret_1d=lambda x: x["close"] / x["prev_close"] - 1)
        .groupby("trade_date", as_index=False)
        .agg(
            eq_ret_1d=("stock_ret_1d", "mean"),
            med_ret_1d=("stock_ret_1d", "median"),
            up_ratio=("stock_ret_1d", lambda s: float((s > 0).mean())),
        )
        .sort_values("trade_date")
    )
    market["market_index"] = (1 + market["eq_ret_1d"]).cumprod() * 100
    market["market_ma20"] = market["market_index"].rolling(20, min_periods=20).mean()
    market["market_ma60"] = market["market_index"].rolling(60, min_periods=60).mean()
    market["market_regime"] = np.where(
        (market["market_index"] > market["market_ma20"]) & (market["market_ma20"] > market["market_ma60"]),
        "bull",
        np.where(
            (market["market_index"] < market["market_ma20"]) & (market["market_ma20"] < market["market_ma60"]),
            "bear",
            "range",
        ),
    )
    regime_cols = [
        "trade_date",
        "market_regime",
        "market_index",
        "market_ma20",
        "market_ma60",
        "eq_ret_1d",
        "med_ret_1d",
        "up_ratio",
    ]
    return df.merge(market[regime_cols], on="trade_date", how="left")


def add_future_paths(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    g = df.groupby("ticker", group_keys=False)
    df["entry_open_2d"] = g["open"].shift(-2)
    df["next_day_close"] = g["close"].shift(-1)
    df["key_level"] = df["prior_low_60"]
    df["stop_price"] = np.minimum(df["low"], df["key_level"]) * 0.995
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["prev_close"]).abs(),
            (df["low"] - df["prev_close"]).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["atr14"] = tr.groupby(df["ticker"]).transform(lambda s: s.rolling(14, min_periods=14).mean())
    df["atr14_pct"] = df["atr14"] / df["close"]
    df["stop_price_atr14"] = np.minimum(df["low"], df["key_level"]) - ATR_MULTIPLIER * df["atr14"]
    df["stop_price_box20"] = df["prior_low_20"] * 0.995
    df["reclaim_pct"] = df["close"] / df["key_level"] - 1
    df["close_vs_ma20_pct"] = df["close"] / df["ma20"] - 1

    for h in (5, 10, 20):
        lows = [g["low"].shift(-i) for i in range(1, h + 1)]
        future_low = pd.concat(lows, axis=1).min(axis=1)
        confirm_lows = [g["low"].shift(-i) for i in range(2, h + 2)]
        confirm_future_low = pd.concat(confirm_lows, axis=1).min(axis=1)
        df[f"future_low_{h}d"] = future_low
        df[f"stop_hit_{h}d"] = future_low <= df["stop_price"]
        df[f"confirm_future_low_{h}d"] = confirm_future_low
        df[f"confirm_stop_hit_{h}d"] = confirm_future_low <= df["stop_price"]
        df[f"confirm_future_close_{h}d"] = g["close"].shift(-(h + 1))
        df[f"confirm_ret_{h}d"] = df[f"confirm_future_close_{h}d"] / df["entry_open_2d"] - 1
        df[f"ret_{h}d_stop"] = np.where(
            df[f"stop_hit_{h}d"],
            df["stop_price"] / df["entry_open_1d"] - 1,
            df[f"ret_{h}d"],
        )
        df[f"confirm_ret_{h}d_stop"] = np.where(
            df[f"confirm_stop_hit_{h}d"],
            df["stop_price"] / df["entry_open_2d"] - 1,
            df[f"confirm_ret_{h}d"],
        )
        df[f"ret_{h}d_net"] = df[f"ret_{h}d"] - ROUND_TRIP_COST
        df[f"ret_{h}d_stop_net"] = df[f"ret_{h}d_stop"] - ROUND_TRIP_COST
        df[f"confirm_ret_{h}d_net"] = df[f"confirm_ret_{h}d"] - ROUND_TRIP_COST
        df[f"confirm_ret_{h}d_stop_net"] = df[f"confirm_ret_{h}d_stop"] - ROUND_TRIP_COST
        for model, stop_col in (("atr14", "stop_price_atr14"), ("box20", "stop_price_box20")):
            df[f"stop_hit_{model}_{h}d"] = future_low <= df[stop_col]
            df[f"confirm_stop_hit_{model}_{h}d"] = confirm_future_low <= df[stop_col]
            df[f"ret_{h}d_stop_{model}"] = np.where(
                df[f"stop_hit_{model}_{h}d"],
                df[stop_col] / df["entry_open_1d"] - 1,
                df[f"ret_{h}d"],
            )
            df[f"confirm_ret_{h}d_stop_{model}"] = np.where(
                df[f"confirm_stop_hit_{model}_{h}d"],
                df[stop_col] / df["entry_open_2d"] - 1,
                df[f"confirm_ret_{h}d"],
            )
            df[f"ret_{h}d_stop_{model}_net"] = df[f"ret_{h}d_stop_{model}"] - ROUND_TRIP_COST
            df[f"confirm_ret_{h}d_stop_{model}_net"] = df[f"confirm_ret_{h}d_stop_{model}"] - ROUND_TRIP_COST

    return df


def variant_masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    base = df["false_breakdown_reclaim"].fillna(False)
    attention = pd.to_numeric(df["is_attention_stock"], errors="coerce").fillna(0).astype(int)
    disposition = pd.to_numeric(df["is_disposition_stock"], errors="coerce").fillna(0).astype(int)
    tradable = (
        base
        & (attention == 0)
        & (disposition == 0)
        & (df["avg_volume_20"] >= MIN_AVG_VOLUME_20)
        & (df["close"] >= MIN_CLOSE)
    )
    confirmed = tradable & (df["next_day_close"] >= df["key_level"])
    strong_close = tradable & (df["close_pos"] >= 0.7)
    panic_10pct = tradable & (df["ret_5d_past"] <= -0.10)
    volume_confirmed = tradable & (df["volume_ratio"] >= 1.2)
    return {
        "base_signal": base,
        "tradable_filter": tradable,
        "tradable_next_close_confirm": confirmed,
        "tradable_close_pos_ge_0_7": strong_close,
        "tradable_panic_drop_ge_10pct": panic_10pct,
        "tradable_volume_ratio_ge_1_2": volume_confirmed,
    }


def summarize_variant(df: pd.DataFrame, name: str, mask: pd.Series) -> dict[str, float | int | str]:
    rows = df[mask].replace([np.inf, -np.inf], np.nan)
    confirmed_entry = name == "tradable_next_close_confirm"
    entry_col = "entry_open_2d" if confirmed_entry else "entry_open_1d"
    ret_prefix = "confirm_ret" if confirmed_entry else "ret"
    stop_prefix = "confirm_stop_hit" if confirmed_entry else "stop_hit"
    rows = rows.dropna(subset=[entry_col, f"{ret_prefix}_5d", f"{ret_prefix}_10d", f"{ret_prefix}_20d"])
    rows = rows[rows[entry_col] > 0]
    out: dict[str, float | int | str] = {"variant": name, "n": int(len(rows))}
    if rows.empty:
        return out
    attention = pd.to_numeric(rows["is_attention_stock"], errors="coerce").fillna(0).astype(int)
    out["attention_n"] = int((attention == 1).sum())
    out["avg_volume_20_median"] = int(rows["avg_volume_20"].median())
    for h in (5, 10, 20):
        gross = rows[f"{ret_prefix}_{h}d"]
        net = rows[f"{ret_prefix}_{h}d_net"]
        stop_net = rows[f"{ret_prefix}_{h}d_stop_net"]
        out[f"mean_{h}d_net_pct"] = round(float(net.mean() * 100), 3)
        out[f"median_{h}d_net_pct"] = round(float(net.median() * 100), 3)
        out[f"win_rate_{h}d_net_pct"] = round(float((net > 0).mean() * 100), 2)
        out[f"mean_{h}d_stop_net_pct"] = round(float(stop_net.mean() * 100), 3)
        out[f"win_rate_{h}d_stop_net_pct"] = round(float((stop_net > 0).mean() * 100), 2)
        out[f"stop_hit_{h}d_pct"] = round(float(rows[f"{stop_prefix}_{h}d"].mean() * 100), 2)
        out[f"mean_{h}d_gross_pct"] = round(float(gross.mean() * 100), 3)
    return out


def summarize_variant_regime(df: pd.DataFrame, name: str, mask: pd.Series) -> pd.DataFrame:
    rows = df[mask].replace([np.inf, -np.inf], np.nan)
    confirmed_entry = name == "tradable_next_close_confirm"
    entry_col = "entry_open_2d" if confirmed_entry else "entry_open_1d"
    ret_prefix = "confirm_ret" if confirmed_entry else "ret"
    stop_prefix = "confirm_stop_hit" if confirmed_entry else "stop_hit"
    rows = rows.dropna(subset=[entry_col, f"{ret_prefix}_10d", f"{ret_prefix}_20d", "market_regime"])
    rows = rows[rows[entry_col] > 0]
    if rows.empty:
        return pd.DataFrame(
            columns=[
                "variant",
                "market_regime",
                "n",
                "mean_10d_net_pct",
                "win_rate_10d_net_pct",
                "mean_10d_stop_net_pct",
                "stop_hit_10d_pct",
                "mean_20d_net_pct",
                "win_rate_20d_net_pct",
            ]
        )

    out = []
    for regime, g in rows.groupby("market_regime", dropna=False):
        rec: dict[str, float | int | str] = {
            "variant": name,
            "market_regime": str(regime),
            "n": int(len(g)),
        }
        for h in (10, 20):
            net = g[f"{ret_prefix}_{h}d_net"]
            stop_net = g[f"{ret_prefix}_{h}d_stop_net"]
            rec[f"mean_{h}d_net_pct"] = round(float(net.mean() * 100), 3)
            rec[f"win_rate_{h}d_net_pct"] = round(float((net > 0).mean() * 100), 2)
            rec[f"mean_{h}d_stop_net_pct"] = round(float(stop_net.mean() * 100), 3)
        rec["stop_hit_10d_pct"] = round(float(g[f"{stop_prefix}_10d"].mean() * 100), 2)
        out.append(rec)
    return pd.DataFrame(out)


def summarize_stop_models(df: pd.DataFrame, name: str, mask: pd.Series) -> pd.DataFrame:
    rows = df[mask].replace([np.inf, -np.inf], np.nan)
    confirmed_entry = name == "tradable_next_close_confirm"
    entry_col = "entry_open_2d" if confirmed_entry else "entry_open_1d"
    prefix = "confirm_" if confirmed_entry else ""
    rows = rows.dropna(subset=[entry_col, f"{prefix}ret_10d", f"{prefix}ret_20d"])
    rows = rows[rows[entry_col] > 0]
    if rows.empty:
        return pd.DataFrame(
            columns=[
                "variant",
                "stop_model",
                "n",
                "mean_10d_stop_net_pct",
                "win_rate_10d_stop_net_pct",
                "stop_hit_10d_pct",
                "mean_20d_stop_net_pct",
                "win_rate_20d_stop_net_pct",
                "stop_hit_20d_pct",
            ]
        )

    out: list[dict[str, float | int | str]] = []
    for model, ret10_col, hit10_col, ret20_col, hit20_col in (
        ("simple", f"{prefix}ret_10d_stop_net", f"{prefix}stop_hit_10d", f"{prefix}ret_20d_stop_net", f"{prefix}stop_hit_20d"),
        ("atr14", f"{prefix}ret_10d_stop_atr14_net", f"{prefix}stop_hit_atr14_10d", f"{prefix}ret_20d_stop_atr14_net", f"{prefix}stop_hit_atr14_20d"),
        ("box20", f"{prefix}ret_10d_stop_box20_net", f"{prefix}stop_hit_box20_10d", f"{prefix}ret_20d_stop_box20_net", f"{prefix}stop_hit_box20_20d"),
    ):
        valid = rows.dropna(subset=[ret10_col, hit10_col, ret20_col, hit20_col])
        if valid.empty:
            continue
        out.append(
            {
                "variant": name,
                "stop_model": model,
                "n": int(len(valid)),
                "mean_10d_stop_net_pct": round(float(valid[ret10_col].mean() * 100), 3),
                "win_rate_10d_stop_net_pct": round(float((valid[ret10_col] > 0).mean() * 100), 2),
                "stop_hit_10d_pct": round(float(valid[hit10_col].mean() * 100), 2),
                "mean_20d_stop_net_pct": round(float(valid[ret20_col].mean() * 100), 3),
                "win_rate_20d_stop_net_pct": round(float((valid[ret20_col] > 0).mean() * 100), 2),
                "stop_hit_20d_pct": round(float(valid[hit20_col].mean() * 100), 2),
            }
        )
    return pd.DataFrame(out)


def summarize_hybrid_stop_policies(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(
            columns=[
                "analysis_variant",
                "policy",
                "n",
                "mean_10d_stop_net_pct",
                "win_rate_10d_stop_net_pct",
                "stop_hit_10d_pct",
                "mean_20d_stop_net_pct",
                "win_rate_20d_stop_net_pct",
                "simple_usage_pct",
            ]
        )

    ret_prefix = str(rows["ret_prefix"].iloc[0])
    policies = {
        "atr14_only": rows["close"].isna(),
        "simple_if_non_bull_high_close_and_panic": (
            (rows["market_regime"] != "bull") & (rows["close_pos"] >= 0.7) & (rows["ret_5d_past"] <= -0.10)
        ),
        "simple_if_non_bull_high_close_and_reclaim": (
            (rows["market_regime"] != "bull") & (rows["close_pos"] >= 0.7) & (rows["reclaim_pct"] >= 0.01)
        ),
        "simple_if_bear_regime_only": rows["market_regime"] == "bear",
        "simple_if_non_bull_and_reclaim_ge_1pct": (rows["market_regime"] != "bull") & (rows["reclaim_pct"] >= 0.01),
    }

    def ret_col(model: str, horizon: int) -> str:
        if model == "simple":
            return f"{ret_prefix}_{horizon}d_stop_net"
        return f"{ret_prefix}_{horizon}d_stop_{model}_net"

    def hit_col(model: str, horizon: int) -> str:
        prefix = "confirm_" if ret_prefix == "confirm_ret" else ""
        if model == "simple":
            return f"{prefix}stop_hit_{horizon}d"
        return f"{prefix}stop_hit_{model}_{horizon}d"

    out: list[dict[str, float | int | str]] = []
    for policy, use_simple in policies.items():
        valid = rows.dropna(
            subset=[
                ret_col("simple", 10),
                ret_col("atr14", 10),
                ret_col("simple", 20),
                ret_col("atr14", 20),
                hit_col("simple", 10),
                hit_col("atr14", 10),
            ]
        ).copy()
        if valid.empty:
            continue
        simple_mask = use_simple.loc[valid.index].fillna(False)
        valid["hybrid_ret_10d"] = np.where(simple_mask, valid[ret_col("simple", 10)], valid[ret_col("atr14", 10)])
        valid["hybrid_ret_20d"] = np.where(simple_mask, valid[ret_col("simple", 20)], valid[ret_col("atr14", 20)])
        valid["hybrid_hit_10d"] = np.where(simple_mask, valid[hit_col("simple", 10)], valid[hit_col("atr14", 10)])
        out.append(
            {
                "analysis_variant": str(valid["analysis_variant"].iloc[0]),
                "policy": policy,
                "n": int(len(valid)),
                "mean_10d_stop_net_pct": round(float(valid["hybrid_ret_10d"].mean() * 100), 3),
                "win_rate_10d_stop_net_pct": round(float((valid["hybrid_ret_10d"] > 0).mean() * 100), 2),
                "stop_hit_10d_pct": round(float(valid["hybrid_hit_10d"].mean() * 100), 2),
                "mean_20d_stop_net_pct": round(float(valid["hybrid_ret_20d"].mean() * 100), 3),
                "win_rate_20d_stop_net_pct": round(float((valid["hybrid_ret_20d"] > 0).mean() * 100), 2),
                "simple_usage_pct": round(float(simple_mask.mean() * 100), 2),
            }
        )
    return pd.DataFrame(out).sort_values(["analysis_variant", "mean_10d_stop_net_pct"], ascending=[True, False])


def write_hybrid_stop_report(hybrid_summary: pd.DataFrame) -> None:
    HYBRID_STOP_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "analysis_variant",
        "policy",
        "n",
        "mean_10d_stop_net_pct",
        "win_rate_10d_stop_net_pct",
        "stop_hit_10d_pct",
        "mean_20d_stop_net_pct",
        "win_rate_20d_stop_net_pct",
        "simple_usage_pct",
    ]
    md = f"""# 假跌破收回情境式停損分析

本報告比較 `ATR14` 全域預設與少數幾個可辯護的 hybrid stop policy。

設計原則：

- `ATR14` 作為預設停損
- 只有在高品質情境時才切到較緊的 `simple`
- 暫不把 `box20` 納入主決策樹，等待後續箱型條件更完整

## Hybrid Policy 比較

{markdown_table(hybrid_summary, cols)}

Policy 說明：

- `atr14_only`: 全部使用 `ATR14`
- `simple_if_non_bull_high_close_and_panic`: 非 bull、收盤強、且 5 日跌幅至少 10% 時改用 `simple`
- `simple_if_non_bull_high_close_and_reclaim`: 非 bull、收盤強、且收回關鍵價至少 1% 時改用 `simple`
- `simple_if_bear_regime_only`: 只有 bear regime 改用 `simple`
- `simple_if_non_bull_and_reclaim_ge_1pct`: 非 bull 且收回幅度至少 1% 時改用 `simple`
"""
    HYBRID_STOP_REPORT_PATH.write_text(md, encoding="utf-8")


def prepare_variant_rows(df: pd.DataFrame, name: str, mask: pd.Series) -> pd.DataFrame:
    rows = df[mask].replace([np.inf, -np.inf], np.nan).copy()
    confirmed_entry = name == "tradable_next_close_confirm"
    entry_col = "entry_open_2d" if confirmed_entry else "entry_open_1d"
    ret_prefix = "confirm_ret" if confirmed_entry else "ret"
    rows = rows.dropna(subset=[entry_col, f"{ret_prefix}_10d_net", f"{ret_prefix}_20d_net"])
    rows = rows[rows[entry_col] > 0].copy()
    rows["analysis_variant"] = name
    rows["entry_col"] = entry_col
    rows["ret_prefix"] = ret_prefix
    rows["ret_10d_net_actual"] = rows[f"{ret_prefix}_10d_net"]
    rows["ret_20d_net_actual"] = rows[f"{ret_prefix}_20d_net"]
    rows["is_failure_10d"] = rows["ret_10d_net_actual"] < 0
    rows["is_success_10d"] = rows["ret_10d_net_actual"] > 0
    return rows


def summarize_failure_feature_groups(rows: pd.DataFrame) -> pd.DataFrame:
    features = [
        "close_pos",
        "ret_5d_past",
        "volume_ratio",
        "reclaim_pct",
        "range_pct",
        "atr14_pct",
        "close_vs_ma20_pct",
    ]
    out = []
    for outcome, g in (("failure", rows[rows["is_failure_10d"]]), ("success", rows[rows["is_success_10d"]])):
        if g.empty:
            continue
        rec: dict[str, float | int | str] = {"outcome": outcome, "n": int(len(g))}
        for col in features:
            rec[f"{col}_mean"] = round(float(g[col].mean() * 100), 3)
            rec[f"{col}_median"] = round(float(g[col].median() * 100), 3)
        out.append(rec)
    return pd.DataFrame(out)


def summarize_failure_regime(rows: pd.DataFrame) -> pd.DataFrame:
    regime = (
        rows.groupby(["analysis_variant", "market_regime", "is_failure_10d"], as_index=False)
        .agg(
            n=("ticker", "count"),
            mean_10d_net_pct=("ret_10d_net_actual", lambda s: round(float(s.mean() * 100), 3)),
        )
    )
    regime["outcome"] = np.where(regime["is_failure_10d"], "failure", "success")
    regime = regime.drop(columns=["is_failure_10d"])
    totals = regime.groupby("analysis_variant")["n"].transform("sum")
    regime["share_pct"] = (regime["n"] / totals * 100).round(2)
    return regime.sort_values(["analysis_variant", "market_regime", "outcome"])


def summarize_failure_filter_candidates(rows: pd.DataFrame) -> pd.DataFrame:
    base_n = len(rows)
    base_fail = int(rows["is_failure_10d"].sum())
    base_win = int(rows["is_success_10d"].sum())
    candidates = {
        "exclude_bull_regime": rows["market_regime"] != "bull",
        "bear_regime_only": rows["market_regime"] == "bear",
        "close_pos_ge_0_7": rows["close_pos"] >= 0.7,
        "panic_drop_ge_10pct": rows["ret_5d_past"] <= -0.10,
        "volume_ratio_ge_1_2": rows["volume_ratio"] >= 1.2,
        "reclaim_pct_ge_1pct": rows["reclaim_pct"] >= 0.01,
        "exclude_bull_and_close_pos_ge_0_7": (rows["market_regime"] != "bull") & (rows["close_pos"] >= 0.7),
        "exclude_bull_and_panic_drop_ge_10pct": (rows["market_regime"] != "bull") & (rows["ret_5d_past"] <= -0.10),
    }
    out = []
    for name, mask in candidates.items():
        kept = rows[mask].copy()
        if kept.empty:
            continue
        fail_count = int(kept["is_failure_10d"].sum())
        win_count = int(kept["is_success_10d"].sum())
        out.append(
            {
                "analysis_variant": str(rows["analysis_variant"].iloc[0]),
                "candidate_filter": name,
                "n": int(len(kept)),
                "keep_rate_pct": round(float(len(kept) / base_n * 100), 2),
                "mean_10d_net_pct": round(float(kept["ret_10d_net_actual"].mean() * 100), 3),
                "win_rate_10d_net_pct": round(float((kept["ret_10d_net_actual"] > 0).mean() * 100), 2),
                "failure_rate_10d_pct": round(float((kept["ret_10d_net_actual"] < 0).mean() * 100), 2),
                "failures_removed_pct": round(float((1 - fail_count / base_fail) * 100), 2) if base_fail else 0.0,
                "winners_kept_pct": round(float((win_count / base_win) * 100), 2) if base_win else 0.0,
            }
        )
    return pd.DataFrame(out).sort_values(["analysis_variant", "mean_10d_net_pct"], ascending=[True, False])


def write_failure_report(
    feature_summary: pd.DataFrame,
    regime_summary: pd.DataFrame,
    filter_summary: pd.DataFrame,
    failure_examples: pd.DataFrame,
) -> None:
    FAILURE_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    feature_cols = [
        "analysis_variant",
        "outcome",
        "n",
        "close_pos_mean",
        "ret_5d_past_mean",
        "volume_ratio_mean",
        "reclaim_pct_mean",
        "range_pct_mean",
        "atr14_pct_mean",
        "close_vs_ma20_pct_mean",
    ]
    regime_cols = [
        "analysis_variant",
        "market_regime",
        "outcome",
        "n",
        "share_pct",
        "mean_10d_net_pct",
    ]
    filter_cols = [
        "analysis_variant",
        "candidate_filter",
        "n",
        "keep_rate_pct",
        "mean_10d_net_pct",
        "win_rate_10d_net_pct",
        "failure_rate_10d_pct",
        "failures_removed_pct",
        "winners_kept_pct",
    ]
    md = f"""# 假跌破收回失敗樣本分析

本報告聚焦 `tradable_filter` 與 `tradable_next_close_confirm` 兩個主變體，定義 `10 日淨報酬 < 0` 為失敗樣本，目標是找出可落地的排除條件候選。

## 失敗與成功特徵對比

{markdown_table(feature_summary, feature_cols)}

欄位說明：

- 百分比欄位已換算為 `%`
- `close_pos_mean` 越高表示訊號日越接近日內高點收盤
- `reclaim_pct_mean` 表示收盤高於關鍵價的幅度
- `close_vs_ma20_pct_mean` 表示收盤相對月線的位置

## 失敗樣本的 regime 分布

{markdown_table(regime_summary, regime_cols)}

## 候選排除條件效果

{markdown_table(filter_summary, filter_cols)}

## 初步判讀

- 若某條件能明顯提高 `mean_10d_net_pct`，同時 `winners_kept_pct` 不至於掉太多，就可視為候選排除條件。
- 若某條件主要只是大幅刪減樣本，但未改善 `mean_10d_net_pct` 或 `failure_rate_10d_pct`，就不應直接採用。
- `exclude_bull_regime`、`close_pos_ge_0_7`、`panic_drop_ge_10pct` 是本輪優先比較的條件，因為它們既有課程語意，也已有前面回測支持。

## 失敗樣本範例

輸出檔：

- `data/analysis/kline_course_backtest/false_breakdown_failure_examples.csv`
"""
    FAILURE_REPORT_PATH.write_text(md, encoding="utf-8")


def _build_scanner_rows(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(
            columns=[
                "scan_date",
                "ticker",
                "market_regime",
                "signal_close",
                "key_level",
                "confirm_price",
                "confirm_status",
                "close_pos",
                "ret_5d_past_pct",
                "volume_ratio",
                "reclaim_pct",
                "scanner_score",
                "stop_price_atr14",
                "stop_price_box20",
                "stop_price_simple",
            ]
        )
    rows["is_high_close"] = rows["close_pos"] >= 0.7
    rows["is_panic_drop"] = rows["ret_5d_past"] <= -0.10
    rows["is_high_volume"] = rows["volume_ratio"] >= 1.2
    rows["is_strong_reclaim"] = rows["reclaim_pct"] >= 0.01
    rows["is_non_bull"] = rows["market_regime"] != "bull"
    rows["scanner_score"] = (
        rows["is_non_bull"].astype(int) * 35
        + rows["is_high_close"].astype(int) * 25
        + rows["is_panic_drop"].astype(int) * 20
        + rows["is_high_volume"].astype(int) * 10
        + rows["is_strong_reclaim"].astype(int) * 10
    )
    rows["confirm_status"] = "pending_next_close"
    rows["scan_date"] = rows["trade_date"].dt.date.astype(str)
    rows["confirm_price"] = rows["key_level"]
    rows["ret_5d_past_pct"] = (rows["ret_5d_past"] * 100).round(3)
    rows["reclaim_pct"] = (rows["reclaim_pct"] * 100).round(3)
    rows["close_pos"] = (rows["close_pos"] * 100).round(2)
    out = rows[
        [
            "scan_date",
            "ticker",
            "market_regime",
            "close",
            "key_level",
            "confirm_price",
            "confirm_status",
            "close_pos",
            "ret_5d_past_pct",
            "volume_ratio",
            "reclaim_pct",
            "scanner_score",
            "stop_price_atr14",
            "stop_price_box20",
            "stop_price",
        ]
    ].rename(columns={"close": "signal_close", "stop_price": "stop_price_simple"})
    return out.sort_values(["scanner_score", "volume_ratio", "ret_5d_past_pct"], ascending=[False, False, True])


def build_daily_scanner(df: pd.DataFrame, tradable_mask: pd.Series) -> pd.DataFrame:
    as_of_date = df["trade_date"].max()
    rows = df[(df["trade_date"] == as_of_date) & tradable_mask].copy()
    return _build_scanner_rows(rows)


def build_recent_scanner_history(df: pd.DataFrame, tradable_mask: pd.Series, recent_days: int = 20) -> pd.DataFrame:
    dates = sorted(df["trade_date"].dropna().unique())
    if not dates:
        return pd.DataFrame()
    target_dates = set(dates[-recent_days:])
    rows = df[df["trade_date"].isin(target_dates) & tradable_mask].copy()
    if rows.empty:
        return _build_scanner_rows(rows)
    out = _build_scanner_rows(rows)
    return out.sort_values(["scan_date", "scanner_score", "volume_ratio"], ascending=[False, False, False])


def write_scanner_report(scanner_rows: pd.DataFrame, recent_rows: pd.DataFrame) -> None:
    SCANNER_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if scanner_rows.empty:
        recent_preview = ""
        if not recent_rows.empty:
            preview_cols = [
                "scan_date",
                "ticker",
                "market_regime",
                "signal_close",
                "scanner_score",
                "stop_price_atr14",
            ]
            recent_preview = f"""
## 近 20 個交易日候選（Top 30）

{markdown_table(recent_rows.head(30), preview_cols)}
"""
        md = """# 假跌破收回每日掃描（Task 5）

本次掃描結果為空，代表最新交易日沒有通過 `tradable_filter` 的假跌破收回候選股。
"""
        if recent_preview:
            md = md + recent_preview + "\n輸出檔：\n\n- `data/analysis/kline_course_backtest/false_breakdown_daily_scanner_recent20d.csv`\n"
        SCANNER_REPORT_PATH.write_text(md, encoding="utf-8")
        return
    top_rows = scanner_rows.head(30).copy()
    cols = [
        "scan_date",
        "ticker",
        "market_regime",
        "signal_close",
        "key_level",
        "confirm_status",
        "close_pos",
        "ret_5d_past_pct",
        "volume_ratio",
        "reclaim_pct",
        "scanner_score",
        "stop_price_atr14",
    ]
    md = f"""# 假跌破收回每日掃描（Task 5）

掃描邏輯：

- 基底：`tradable_filter`（排除注意/處置、低流動性、低價）
- 分數加權：`exclude_bull_regime`、`close_pos >= 0.7`、`panic_drop >= 10%`、`volume_ratio >= 1.2`、`reclaim_pct >= 1%`
- 確認規則：隔日收盤需站回 `confirm_price`（此檔為 pending 狀態）
- 停損欄位：預設優先參考 `stop_price_atr14`

本次候選數：{len(scanner_rows)}

## Top 30 候選

{markdown_table(top_rows, cols)}

輸出檔：

- `data/analysis/kline_course_backtest/false_breakdown_daily_scanner.csv`
- `data/analysis/kline_course_backtest/false_breakdown_daily_scanner_recent20d.csv`
"""
    SCANNER_REPORT_PATH.write_text(md, encoding="utf-8")


def markdown_table(rows: pd.DataFrame, cols: list[str]) -> str:
    table_rows = rows[cols].copy()
    header = "| " + " | ".join(cols) + " |"
    divider = "| " + " | ".join(["---"] * len(cols)) + " |"
    lines = [header, divider]
    for row in table_rows.itertuples(index=False):
        values = ["" if pd.isna(v) else str(v) for v in row]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def write_report(summary: pd.DataFrame, regime_summary: pd.DataFrame, stop_model_summary: pd.DataFrame, df: pd.DataFrame) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    sample_start = df["trade_date"].min().date()
    sample_end = df["trade_date"].max().date()

    overview_cols = [
        "variant",
        "n",
        "mean_10d_net_pct",
        "win_rate_10d_net_pct",
        "mean_10d_stop_net_pct",
        "win_rate_10d_stop_net_pct",
        "stop_hit_10d_pct",
        "mean_20d_net_pct",
        "win_rate_20d_net_pct",
    ]
    detail_cols = [
        "variant",
        "n",
        "mean_5d_net_pct",
        "win_rate_5d_net_pct",
        "mean_10d_net_pct",
        "win_rate_10d_net_pct",
        "mean_20d_net_pct",
        "win_rate_20d_net_pct",
        "avg_volume_20_median",
        "attention_n",
    ]
    regime_cols = [
        "variant",
        "market_regime",
        "n",
        "mean_10d_net_pct",
        "win_rate_10d_net_pct",
        "mean_10d_stop_net_pct",
        "stop_hit_10d_pct",
        "mean_20d_net_pct",
        "win_rate_20d_net_pct",
    ]
    stop_cols = [
        "variant",
        "stop_model",
        "n",
        "mean_10d_stop_net_pct",
        "win_rate_10d_stop_net_pct",
        "stop_hit_10d_pct",
        "mean_20d_stop_net_pct",
        "win_rate_20d_stop_net_pct",
        "stop_hit_20d_pct",
    ]

    best = summary.set_index("variant")
    base = best.loc["base_signal"]
    tradable = best.loc["tradable_filter"]
    regime_pivot = regime_summary.set_index(["variant", "market_regime"])

    def regime_val(variant: str, regime: str, col: str) -> float | None:
        key = (variant, regime)
        if key not in regime_pivot.index:
            return None
        return float(regime_pivot.loc[key, col])

    tradable_bull_10d = regime_val("tradable_filter", "bull", "mean_10d_net_pct")
    tradable_range_10d = regime_val("tradable_filter", "range", "mean_10d_net_pct")
    tradable_bear_10d = regime_val("tradable_filter", "bear", "mean_10d_net_pct")

    md = f"""# 假跌破收回策略原型驗證

資料庫：`/Users/howard/.four_seasons/data.sqlite`

樣本：{sample_start} 至 {sample_end}

本次只驗證 `false_breakdown_reclaim`。目標是確認它在加入可交易限制、交易成本與簡單停損後，是否仍值得進入下一步策略開發。

## 假設

- 訊號：5 日跌幅達 7% 以上，盤中跌破 60 日前低，收盤收回 60 日前低。
- 進場：訊號日收盤後成立，隔日開盤買進。
- 隔日確認 variant：隔日收盤仍站回關鍵價後，第 2 天開盤買進。
- 固定持有：第 5/10/20 個交易日收盤出場。
- 交易成本：每筆來回先用 {ROUND_TRIP_COST * 100:.3f}% 扣除，作為手續費與交易稅的保守近似。
- 可交易限制：排除注意股、處置股；20 日均量至少 {MIN_AVG_VOLUME_20:,} 股；收盤價至少 {MIN_CLOSE} 元。
- 簡單停損：跌破 `min(訊號日低點, 60日前低) * 0.995` 視為觸發停損。此版本只用日K低點判斷，尚未處理跳空穿價。

## 10 日核心結果

{markdown_table(summary, overview_cols)}

## 全期間固定持有結果

{markdown_table(summary, detail_cols)}

## 市場環境 regime 分組（Task 2）

Regime 定義（全市場等權代理）：

- `bull`：市場代理指數 > MA20 且 MA20 > MA60
- `bear`：市場代理指數 < MA20 且 MA20 < MA60
- `range`：其餘情況

{markdown_table(regime_summary, regime_cols)}

## 停損模型比較（Task 3）

停損模型：

- `simple`：`min(訊號日低點, 60日前低) * 0.995`
- `atr14`：`min(訊號日低點, 60日前低) - ATR14 * {ATR_MULTIPLIER:.1f}`
- `box20`：`20 日前低 * 0.995`

{markdown_table(stop_model_summary, stop_cols)}

## 判讀

- 原始 `base_signal` 扣除交易成本後，10 日平均仍為 {base["mean_10d_net_pct"]:.3f}%，勝率 {base["win_rate_10d_net_pct"]:.2f}%。
- 加入可交易限制後，`tradable_filter` 10 日平均為 {tradable["mean_10d_net_pct"]:.3f}%，勝率 {tradable["win_rate_10d_net_pct"]:.2f}%，優於原始訊號。這代表目前觀察到的邊際不是由低流動性或注意股撐出來。
- `tradable_next_close_confirm` 不使用隔日開盤進場，而是等隔日收盤確認後第 2 天開盤進場，用來檢查多等一天是否能提升訊號品質。
- `tradable_close_pos_ge_0_7` 與 `tradable_panic_drop_ge_10pct` 表現更好，代表「收盤收得強」與「急跌幅度夠大」可以優先做成策略參數。
- `tradable_filter` 在 bull/range/bear 三種 regime 的 10 日淨報酬分別為 {tradable_bull_10d if tradable_bull_10d is not None else float("nan"):.3f}% / {tradable_range_10d if tradable_range_10d is not None else float("nan"):.3f}% / {tradable_bear_10d if tradable_bear_10d is not None else float("nan"):.3f}%。
- `Task 3` 顯示 ATR 與 box 停損可調整停損觸發率與淨報酬權衡；後續應以主要變體（`tradable_filter`、`tradable_next_close_confirm`）選定預設停損模型。
- `Task 4` 的失敗樣本分析請見 `false_breakdown_failure_analysis.md`；這一版會把失敗樣本歸因獨立整理，避免主報告過重。

## 下一步

1. 將 regime 判斷改為可替換來源（例如未來接上正式加權指數）以檢查代理偏差。
2. 把目前最佳停損模型與排除條件接到 daily scanner 輸出欄位。
"""
    REPORT_PATH.write_text(md, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = add_market_regime(add_future_paths(add_signals(add_features(load_bars()))))
    masks = variant_masks(df)
    rows = [summarize_variant(df, name, mask) for name, mask in masks.items()]
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT_DIR / "false_breakdown_strategy_summary.csv", index=False)
    regime_rows = [summarize_variant_regime(df, name, mask) for name, mask in masks.items()]
    regime_summary = pd.concat(regime_rows, ignore_index=True).sort_values(["variant", "market_regime"])
    regime_summary.to_csv(OUT_DIR / "false_breakdown_strategy_regime_summary.csv", index=False)
    stop_model_rows = [summarize_stop_models(df, name, mask) for name, mask in masks.items()]
    stop_model_summary = pd.concat(stop_model_rows, ignore_index=True).sort_values(["variant", "stop_model"])
    stop_model_summary.to_csv(OUT_DIR / "false_breakdown_strategy_stop_model_summary.csv", index=False)
    failure_variants = ["tradable_filter", "tradable_next_close_confirm"]
    failure_variant_rows = [prepare_variant_rows(df, name, masks[name]) for name in failure_variants]
    failure_rows = pd.concat(failure_variant_rows, ignore_index=True)
    hybrid_stop_summary = pd.concat(
        [summarize_hybrid_stop_policies(rows) for rows in failure_variant_rows],
        ignore_index=True,
    )
    hybrid_stop_summary.to_csv(OUT_DIR / "false_breakdown_hybrid_stop_summary.csv", index=False)
    feature_summary = pd.concat(
        [
            summarize_failure_feature_groups(rows).assign(analysis_variant=name)
            for name, rows in zip(failure_variants, failure_variant_rows)
        ],
        ignore_index=True,
    )[
        [
            "analysis_variant",
            "outcome",
            "n",
            "close_pos_mean",
            "ret_5d_past_mean",
            "volume_ratio_mean",
            "reclaim_pct_mean",
            "range_pct_mean",
            "atr14_pct_mean",
            "close_vs_ma20_pct_mean",
        ]
    ]
    feature_summary.to_csv(OUT_DIR / "false_breakdown_failure_feature_summary.csv", index=False)
    failure_regime_summary = pd.concat(
        [summarize_failure_regime(rows) for rows in failure_variant_rows],
        ignore_index=True,
    )
    failure_regime_summary.to_csv(OUT_DIR / "false_breakdown_failure_regime_summary.csv", index=False)
    failure_filter_summary = pd.concat(
        [summarize_failure_filter_candidates(rows) for rows in failure_variant_rows],
        ignore_index=True,
    )
    failure_filter_summary.to_csv(OUT_DIR / "false_breakdown_failure_filter_candidates.csv", index=False)
    failure_examples = (
        failure_rows[failure_rows["is_failure_10d"]]
        .sort_values(["analysis_variant", "ret_10d_net_actual"])
        .groupby("analysis_variant", as_index=False, group_keys=False)
        .head(50)[
            [
                "analysis_variant",
                "ticker",
                "trade_date",
                "market_regime",
                "close_pos",
                "ret_5d_past",
                "volume_ratio",
                "reclaim_pct",
                "close_vs_ma20_pct",
                "ret_10d_net_actual",
                "ret_20d_net_actual",
            ]
        ]
    )
    failure_examples.to_csv(OUT_DIR / "false_breakdown_failure_examples.csv", index=False)
    scanner_rows = build_daily_scanner(df, masks["tradable_filter"])
    scanner_recent_rows = build_recent_scanner_history(df, masks["tradable_filter"], recent_days=20)
    scanner_rows.to_csv(OUT_DIR / "false_breakdown_daily_scanner.csv", index=False)
    scanner_recent_rows.to_csv(OUT_DIR / "false_breakdown_daily_scanner_recent20d.csv", index=False)

    examples = []
    for name, mask in masks.items():
        rows_df = df[mask].dropna(subset=["ret_10d"]).head(100).copy()
        if name == "tradable_next_close_confirm":
            rows_df["actual_entry_open"] = rows_df["entry_open_2d"]
            rows_df["actual_ret_10d_net"] = rows_df["confirm_ret_10d_net"]
            rows_df["actual_ret_10d_stop_net"] = rows_df["confirm_ret_10d_stop_net"]
            rows_df["actual_stop_hit_10d"] = rows_df["confirm_stop_hit_10d"]
        else:
            rows_df["actual_entry_open"] = rows_df["entry_open_1d"]
            rows_df["actual_ret_10d_net"] = rows_df["ret_10d_net"]
            rows_df["actual_ret_10d_stop_net"] = rows_df["ret_10d_stop_net"]
            rows_df["actual_stop_hit_10d"] = rows_df["stop_hit_10d"]
        rows_df.insert(0, "variant", name)
        examples.append(
            rows_df[
                [
                    "variant",
                    "ticker",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "key_level",
                    "stop_price",
                    "actual_entry_open",
                    "actual_ret_10d_net",
                    "actual_ret_10d_stop_net",
                    "actual_stop_hit_10d",
                ]
            ]
        )
    pd.concat(examples, ignore_index=True).to_csv(OUT_DIR / "false_breakdown_strategy_examples.csv", index=False)
    write_report(summary, regime_summary, stop_model_summary, df)
    write_failure_report(feature_summary, failure_regime_summary, failure_filter_summary, failure_examples)
    write_scanner_report(scanner_rows, scanner_recent_rows)
    write_hybrid_stop_report(hybrid_stop_summary)
    print(REPORT_PATH)
    print(FAILURE_REPORT_PATH)
    print(SCANNER_REPORT_PATH)
    print(HYBRID_STOP_REPORT_PATH)
    print(OUT_DIR / "false_breakdown_strategy_summary.csv")
    print(OUT_DIR / "false_breakdown_strategy_regime_summary.csv")
    print(OUT_DIR / "false_breakdown_strategy_stop_model_summary.csv")
    print(OUT_DIR / "false_breakdown_failure_filter_candidates.csv")
    print(OUT_DIR / "false_breakdown_daily_scanner.csv")
    print(OUT_DIR / "false_breakdown_daily_scanner_recent20d.csv")
    print(OUT_DIR / "false_breakdown_hybrid_stop_summary.csv")


if __name__ == "__main__":
    main()
