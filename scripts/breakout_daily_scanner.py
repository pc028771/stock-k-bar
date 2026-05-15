from __future__ import annotations

import argparse
import os
import sqlite3
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from breakout_attack_strategy_check import MIN_AVG_VOLUME_20, MIN_CLOSE, add_trade_fields
from false_breakdown_strategy_check import add_market_regime
from finmind_intraday_kline_check import fetch_kbar, intraday_features
from kline_course_backtest import add_features, add_signals, load_bars


def _fetch_vp_finmind(
    ticker: str,
    trade_date: str,
    token: str,
    sleep_seconds: float,
) -> "pd.DataFrame":
    """FinMind TaiwanStockKBar → 分價量表 [price, volume]。"""
    try:
        from finmind_intraday_kline_check import fetch_kbar
        import sys as _sys
        _vp_dir = str(__file__).replace("breakout_daily_scanner.py", "")
        if _vp_dir not in _sys.path:
            _sys.path.insert(0, _vp_dir)
        from volume_profile import build_vp_from_kbar
        kbar = fetch_kbar(ticker, trade_date, token, sleep_seconds)
        if kbar.empty:
            return pd.DataFrame(columns=["price", "volume"])
        df = kbar.copy()
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["high", "low", "volume"])
        return build_vp_from_kbar(df)
    except Exception:
        return pd.DataFrame(columns=["price", "volume"])


def _compute_vp_features_safe(
    vp: "pd.DataFrame",
    current_close: float,
) -> dict:
    """compute_vp_features with fallback to NaN dict on any error."""
    try:
        import sys as _sys
        import os as _os
        _vp_dir = _os.path.dirname(_os.path.abspath(__file__))
        if _vp_dir not in _sys.path:
            _sys.path.insert(0, _vp_dir)
        from volume_profile import compute_vp_features
        return compute_vp_features(vp, current_close)
    except Exception:
        return {
            "vp_overhead_pct": float("nan"),
            "vp_dense_above": False,
            "vp_supply_vacuum": False,
            "vp_nearest_resistance_pct": float("nan"),
        }


OUT_DIR = Path("data/analysis/kline_course_backtest")
REPORT_PATH = Path("docs/K線力量判斷入門/backtests/breakout_daily_scanner.md")
TOPN_SUMMARY_PATH = OUT_DIR / "breakout_daily_scanner_topn_summary.csv"
ARCHIVE_DIR = OUT_DIR / "archive" / "breakout_daily_scanner"
DB_PATH = "/Users/howard/.four_seasons/data.sqlite"
FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"
STOCK_INFO_CACHE_PATH = OUT_DIR / "finmind_stock_info_cache.csv"


def load_exclusion_tickers_from_db(db_path: str = DB_PATH) -> set[str]:
    try:
        conn = sqlite3.connect(db_path, timeout=10)
    except Exception:
        return set()
    try:
        base_exclusion = pd.read_sql_query(
            """
            select distinct ticker
            from screening_exclusion
            where status = 'active'
            """,
            conn,
        )
        ineligible = pd.read_sql_query(
            """
            select distinct ticker
            from strategy_ticker_ineligibility
            where status = 'active'
            """,
            conn,
        )
        construction = pd.read_sql_query(
            """
            select distinct ticker
            from strategy_ticker_ineligibility
            where status = 'active'
              and (
                reason like '%營建%'
                or reason like '%建材%'
              )
            """,
            conn,
        )
    except Exception:
        return set()
    finally:
        conn.close()

    ticks = set(base_exclusion["ticker"].dropna().astype(str).str.strip())
    ticks.update(ineligible["ticker"].dropna().astype(str).str.strip())
    ticks.update(construction["ticker"].dropna().astype(str).str.strip())
    return {t for t in ticks if t}


def load_finmind_stock_info(force_refresh: bool = False, max_cache_age_hours: int = 24) -> pd.DataFrame:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if STOCK_INFO_CACHE_PATH.exists() and not force_refresh:
        age_hours = (time.time() - STOCK_INFO_CACHE_PATH.stat().st_mtime) / 3600
        if age_hours <= max_cache_age_hours:
            return pd.read_csv(STOCK_INFO_CACHE_PATH, dtype=str)

    token = os.environ.get("FINMIND_TOKEN")
    if not token:
        if STOCK_INFO_CACHE_PATH.exists():
            return pd.read_csv(STOCK_INFO_CACHE_PATH, dtype=str)
        return pd.DataFrame(columns=["stock_id", "market_category", "industry_category"])

    headers = {"Authorization": f"Bearer {token}"}
    params = {"dataset": "TaiwanStockInfo"}
    response = requests.get(FINMIND_API_URL, params=params, headers=headers, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != 200:
        raise RuntimeError(f"FinMind TaiwanStockInfo error: {payload.get('msg')}")
    info = pd.DataFrame(payload.get("data") or [])
    if info.empty:
        if STOCK_INFO_CACHE_PATH.exists():
            return pd.read_csv(STOCK_INFO_CACHE_PATH, dtype=str)
        return pd.DataFrame(columns=["stock_id", "market_category", "industry_category"])
    info.to_csv(STOCK_INFO_CACHE_PATH, index=False)
    return info.astype(str)


def prepare_finmind_filters(info: pd.DataFrame) -> tuple[set[str], set[str]]:
    if info.empty:
        return set(), set()
    stock_id_col = "stock_id" if "stock_id" in info.columns else "ticker"
    market_col = "market_category" if "market_category" in info.columns else ""
    type_col = "type" if "type" in info.columns else ""
    industry_col = "industry_category" if "industry_category" in info.columns else ""
    tmp = info.copy()
    tmp[stock_id_col] = tmp[stock_id_col].astype(str).str.strip()
    if market_col:
        market_text = tmp[market_col].astype(str)
        is_listed_otc = market_text.str.contains("上市|上櫃", regex=True, na=False)
    elif type_col:
        type_text = tmp[type_col].astype(str).str.lower()
        is_listed_otc = type_text.isin(["twse", "tpex"])
    else:
        is_listed_otc = tmp[stock_id_col].str.fullmatch(r"\d{4}")
    if industry_col:
        industry_text = tmp[industry_col].astype(str)
        is_construction = industry_text.str.contains("營建|建材", regex=True, na=False)
    else:
        is_construction = pd.Series(False, index=tmp.index)
    listed_otc = set(tmp.loc[is_listed_otc, stock_id_col])
    construction = set(tmp.loc[is_construction, stock_id_col])
    return listed_otc, construction


def tradable_breakout_mask(
    df: pd.DataFrame,
    excluded_tickers: set[str],
    listed_otc_tickers: set[str],
    construction_tickers: set[str],
) -> pd.Series:
    attention = pd.to_numeric(df["is_attention_stock"], errors="coerce").fillna(0).astype(int)
    disposition = pd.to_numeric(df["is_disposition_stock"], errors="coerce").fillna(0).astype(int)
    ticker_str = df["ticker"].astype(str)
    listed_otc_like = ticker_str.isin(listed_otc_tickers) if listed_otc_tickers else ticker_str.str.fullmatch(r"\d{4}")
    not_construction = ~ticker_str.isin(construction_tickers)
    not_excluded = ~ticker_str.isin(excluded_tickers)
    return (
        df["breakout_attack"].fillna(False)
        & listed_otc_like
        & not_construction
        & not_excluded
        & (df["avg_volume_20"] >= MIN_AVG_VOLUME_20)
        & (df["close"] >= MIN_CLOSE)
    )


def _init_intraday_cols(rows: pd.DataFrame) -> pd.DataFrame:
    rows = rows.copy()
    rows["intraday_rows"] = np.nan
    rows["intraday_strong_attack"] = np.nan
    rows["below_open_after_1130"] = np.nan
    rows["intraday_attack_failure"] = np.nan
    rows["intraday_close_pos"] = np.nan
    rows["intraday_return_pct"] = np.nan
    rows["vp_overhead_pct"] = np.nan
    rows["vp_dense_above"] = np.nan
    rows["vp_supply_vacuum"] = np.nan
    rows["vp_nearest_resistance_pct"] = np.nan
    return rows


def enrich_intraday(rows: pd.DataFrame, sleep_seconds: float) -> pd.DataFrame:
    token = os.environ.get("FINMIND_TOKEN")
    if rows.empty:
        return _init_intraday_cols(rows)
    if not token:
        return _init_intraday_cols(rows)

    enriched = []
    for row in rows.itertuples(index=False):
        trade_date = pd.Timestamp(row.trade_date).strftime("%Y-%m-%d")
        kbar = fetch_kbar(str(row.ticker), trade_date, token, sleep_seconds)
        rec = row._asdict()
        rec.update(intraday_features(kbar))
        vp = _fetch_vp_finmind(str(row.ticker), trade_date, token, sleep_seconds)
        rec.update(_compute_vp_features_safe(vp, float(row.close)))
        rec["trade_date"] = trade_date
        enriched.append(rec)
    return pd.DataFrame(enriched)


def add_rolloff_pressure(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Per-ticker MA rolloff pressure (easing / rising / neutral).

    easing: 低價扣抵 → MA 有向上動能 → 有利進場
    rising: 高價扣抵 → MA 面臨阻力 → 風險較高
    """
    df = df.copy().sort_values(["ticker", "trade_date"]).reset_index(drop=True)
    g = df.groupby("ticker")["close"]
    baseline = g.transform(lambda x: x.rolling(period).mean())
    rolloff = g.transform(lambda x: x.shift(period - 1))
    rolloff_a = g.transform(lambda x: x.shift(period - 2))
    easing = (rolloff < baseline) & (rolloff_a < baseline)
    rising = (rolloff > baseline) & (rolloff_a > baseline)
    df["rolloff_pressure"] = np.where(easing, "easing", np.where(rising, "rising", "neutral"))
    return df


def add_pre_rank_score(rows: pd.DataFrame) -> pd.DataFrame:
    rows = rows.copy()
    rows["breakout_strength_pct"] = (rows["close"] / rows["prior_high_60"] - 1) * 100
    rows["pre_rank_score"] = 50.0
    rows["pre_rank_score"] += np.where(rows["market_regime"] == "range", 10, 0)
    rows["pre_rank_score"] += np.where(rows["market_regime"] == "bull", 3, 0)
    # 回測驗證：不開低為反訊號，移除加分；開低（shakeout）為正訊號，但需次日才確認，不列入當日計分
    rows["pre_rank_score"] += np.where(rows["close_pos"] >= 0.85, 8, 0)
    rows["pre_rank_score"] += np.where(rows["volume_ratio"] >= 1.5, 8, 0)
    # 突破強度門檻對齊回測驗證基準（>=5% 對應 shakeout_strong signal）
    rows["pre_rank_score"] += np.where(rows["breakout_strength_pct"] >= 5.0, 8, 0)
    rows["pre_rank_score"] += np.where(
        (rows["breakout_strength_pct"] >= 2.0) & (rows["breakout_strength_pct"] < 5.0), 3, 0
    )
    # Task 13：overhead_supply_layer 評分
    # 依據 supply_zone_spec_report.md §3.1：layer ≤ 1 時 10 日 close-basis +3.83%（vs 基準 +2.90%）
    #           layer ≥ 4 時 10 日 close-basis +1.31%，明顯弱於基準
    # 設計：layer ≤ 1 → 加 8 分；layer ≥ 4 → 扣 8 分；其餘不調整
    if "overhead_supply_layer" in rows.columns:
        layer = pd.to_numeric(rows["overhead_supply_layer"], errors="coerce")
        rows["pre_rank_score"] += np.where(layer.fillna(np.nan).le(1), 8, 0)
        rows["pre_rank_score"] -= np.where(layer.fillna(np.nan).ge(4), 8, 0)
    # MA rolloff 壓力：easing（低價扣抵，均線有上升動能）+5；rising（高價扣抵）-5
    if "rolloff_pressure" in rows.columns:
        rows["pre_rank_score"] += np.where(rows["rolloff_pressure"] == "easing", 5, 0)
        rows["pre_rank_score"] -= np.where(rows["rolloff_pressure"] == "rising", 5, 0)
    return rows


def score_rows(rows: pd.DataFrame) -> pd.DataFrame:
    rows = rows.copy()
    rows = add_pre_rank_score(rows)
    rows["scanner_score"] = rows["pre_rank_score"]

    has_intraday = rows["intraday_rows"].fillna(0) > 0
    strong_attack = rows["intraday_strong_attack"].eq(True)
    below_open_noon = rows["below_open_after_1130"].eq(True)
    attack_failure = rows["intraday_attack_failure"].eq(True)
    rows["scanner_score"] += np.where(has_intraday & strong_attack, 10, 0)
    rows["scanner_score"] += np.where(has_intraday & below_open_noon, -10, 0)
    rows["scanner_score"] += np.where(has_intraday & attack_failure, -10, 0)
    rows["scanner_score"] += np.where(has_intraday & (rows["intraday_close_pos"] >= 0.9), 4, 0)
    has_vp = rows["vp_overhead_pct"].notna()
    rows["scanner_score"] += np.where(has_vp & rows["vp_supply_vacuum"].eq(True), 10, 0)
    rows["scanner_score"] += np.where(has_vp & rows["vp_dense_above"].eq(True), -10, 0)
    rows["scanner_score"] += np.where(has_vp & (rows["vp_overhead_pct"].fillna(1) < 0.15), 5, 0)
    rows["scanner_score"] += np.where(has_vp & (rows["vp_overhead_pct"].fillna(0) > 0.40), -5, 0)
    rows["scanner_score"] = rows["scanner_score"].clip(lower=0, upper=100).round(2)

    return rows


def apply_strict_profile(rows: pd.DataFrame, profile: str) -> pd.DataFrame:
    rows = rows.copy()
    if profile == "off":
        return rows
    if profile == "balanced":
        return rows[
            (rows["breakout_strength_pct"] >= 1.0)
            & (rows["close_pos"] >= 0.85)
            & (rows["volume_ratio"] >= 1.5)
            & (rows["avg_volume_20"] >= 800_000)
            & (rows["close"] >= 15)
        ].copy()
    if profile == "aggressive":
        return rows[
            (rows["breakout_strength_pct"] >= 1.5)
            & (rows["close_pos"] >= 0.9)
            & (rows["volume_ratio"] >= 2.0)
            & (rows["avg_volume_20"] >= 1_200_000)
            & (rows["close"] >= 20)
            & rows["breakout_next_not_low_open"].fillna(False)
        ].copy()
    raise ValueError(f"unknown strict profile: {profile}")


def summarize_topn(scanner: pd.DataFrame) -> pd.DataFrame:
    if scanner.empty:
        return pd.DataFrame(columns=["bucket", "n", "mean_10d_net_pct", "win_rate_10d_pct", "mean_20d_net_pct", "win_rate_20d_pct"])
    valid = scanner.dropna(subset=["ret_10d_net", "ret_20d_net"]).copy()
    if valid.empty:
        return pd.DataFrame(columns=["bucket", "n", "mean_10d_net_pct", "win_rate_10d_pct", "mean_20d_net_pct", "win_rate_20d_pct"])
    out = []
    all_bucket = valid
    for name, rows in (
        ("all", all_bucket),
        ("top5", valid[valid["rank_in_date"] <= 5]),
        ("top10", valid[valid["rank_in_date"] <= 10]),
        ("top20", valid[valid["rank_in_date"] <= 20]),
    ):
        if rows.empty:
            continue
        out.append(
            {
                "bucket": name,
                "n": int(len(rows)),
                "mean_10d_net_pct": round(float(rows["ret_10d_net"].mean() * 100), 3),
                "win_rate_10d_pct": round(float((rows["ret_10d_net"] > 0).mean() * 100), 2),
                "mean_20d_net_pct": round(float(rows["ret_20d_net"].mean() * 100), 3),
                "win_rate_20d_pct": round(float((rows["ret_20d_net"] > 0).mean() * 100), 2),
            }
        )
    return pd.DataFrame(out)


def build_scanner(
    df: pd.DataFrame,
    sleep_seconds: float,
    max_intraday_per_date: int,
    strict_filter_profile: str,
    as_of_date: str | None,
    excluded_tickers: set[str],
    listed_otc_tickers: set[str],
    construction_tickers: set[str],
) -> pd.DataFrame:
    if as_of_date:
        cutoff = pd.Timestamp(as_of_date)
        df = df[pd.to_datetime(df["trade_date"]) <= cutoff].copy()
    mask = tradable_breakout_mask(df, excluded_tickers, listed_otc_tickers, construction_tickers)
    rows = df[mask].copy()
    # 計算回測對齊旗標
    if "overhead_supply_layer" in df.columns:
        layer = df["overhead_supply_layer"].fillna(999)
        df["breakout_vol_capped"] = (layer == 0) & (df["volume_ratio"] < 4.5)
    else:
        df["breakout_vol_capped"] = False

    # shakeout_strong：vol_capped + 隔天開低（次日確認）+ 突破強度 ≥ 5%
    # 對歷史資料可計算；當日最新候選的 breakout_next_low_open 為 NaN（待確認）
    bs_pct = (df["close"] - df["prior_high_60"]) / df["prior_high_60"].replace(0, float("nan")) * 100
    df["shakeout_strong"] = (
        df["breakout_vol_capped"]
        & df["breakout_next_low_open"].fillna(False)
        & (bs_pct >= 5.0)
    )

    optional_cols = [
        c for c in ["overhead_supply_layer", "breakout_vol_capped", "shakeout_strong",
                    "is_attention_stock", "is_disposition_stock", "rolloff_pressure"]
        if c in df.columns
    ]
    rows = df[mask].copy()
    rows = rows[
        [
            "ticker",
            "trade_date",
            "market_regime",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "avg_volume_20",
            "volume_ratio",
            "close_pos",
            "prior_high_60",
            "breakout_next_not_low_open",
            "breakout_next_low_open",
            "ret_10d_net",
            "ret_20d_net",
        ] + optional_cols
    ]
    rows["trade_date"] = pd.to_datetime(rows["trade_date"]).dt.strftime("%Y-%m-%d")
    rows = add_pre_rank_score(rows)
    rows = apply_strict_profile(rows, strict_filter_profile)
    if rows.empty:
        return rows
    rows = _init_intraday_cols(rows)
    recent_dates = sorted(rows["trade_date"].dropna().unique())[-20:]
    enrich_mask = rows["trade_date"].isin(recent_dates)
    if enrich_mask.any():
        base_recent = rows[enrich_mask].copy()
        base_recent = (
            base_recent.sort_values(["trade_date", "pre_rank_score", "volume"], ascending=[False, False, False])
            .groupby("trade_date", as_index=False, group_keys=False)
            .head(max_intraday_per_date)
        )
        enriched_recent = enrich_intraday(base_recent, sleep_seconds=sleep_seconds)
        merge_cols = ["ticker", "trade_date"]
        intraday_cols = [
            "intraday_rows",
            "intraday_strong_attack",
            "below_open_after_1130",
            "intraday_attack_failure",
            "intraday_close_pos",
            "intraday_return_pct",
            "vp_overhead_pct",
            "vp_dense_above",
            "vp_supply_vacuum",
            "vp_nearest_resistance_pct",
        ]
        rows = rows.merge(
            enriched_recent[merge_cols + intraday_cols],
            on=merge_cols,
            how="left",
            suffixes=("", "_new"),
        )
        for col in intraday_cols:
            rows[col] = rows[f"{col}_new"].combine_first(rows[col])
            rows = rows.drop(columns=[f"{col}_new"])
    rows = score_rows(rows)
    rows = rows.sort_values(["trade_date", "scanner_score", "volume"], ascending=[False, False, False])
    rows["rank_in_date"] = rows.groupby("trade_date")["scanner_score"].rank(method="first", ascending=False).astype(int)
    return rows


def enrich_shakeout_institutional(df: pd.DataFrame, token: str) -> pd.DataFrame:
    """對 shakeout_strong 訊號列取投信/外資當日淨買超（張）。

    透過 stock-analysis-system finmind_client.get_institutional（含 rate limit）。
    新增欄位：sitc_lots（投信張數）、foreign_lots（外資萬股）。
    """
    if df.empty or not token:
        df["sitc_lots"] = float("nan")
        df["foreign_lots"] = float("nan")
        return df

    try:
        import sys as _sys
        _sas = Path(__file__).parent.parent.parent / "stock-analysis-system"
        if str(_sas.resolve()) not in _sys.path:
            _sys.path.insert(0, str(_sas.resolve()))
        os.environ.setdefault("FINMIND_API_TOKEN", token)
        from clients import finmind_client as _fm
    except Exception:
        df["sitc_lots"] = float("nan")
        df["foreign_lots"] = float("nan")
        return df

    cache: dict[tuple, dict] = {}

    def _fetch(ticker: str, date: str) -> dict:
        key = (ticker, date)
        if key in cache:
            return cache[key]
        result = {"sitc_lots": float("nan"), "foreign_lots": float("nan")}
        try:
            inst = _fm.get_institutional(ticker, date, date)
            day = inst[inst["date"] == date] if not inst.empty else pd.DataFrame()
            if not day.empty:
                result["sitc_lots"]    = round(float(day["sitc_net"].iloc[0]) / 1000)
                result["foreign_lots"] = round(float(day["foreign_net"].iloc[0]) / 10000)
        except Exception:
            pass
        cache[key] = result
        return result

    records = df[["ticker", "trade_date"]].drop_duplicates()
    enriched = {
        (str(r["ticker"]), str(r["trade_date"])): _fetch(str(r["ticker"]), str(r["trade_date"]))
        for _, r in records.iterrows()
    }

    df = df.copy()
    df["sitc_lots"]    = df.apply(lambda r: enriched.get((str(r["ticker"]), str(r["trade_date"])), {}).get("sitc_lots",    float("nan")), axis=1)
    df["foreign_lots"] = df.apply(lambda r: enriched.get((str(r["ticker"]), str(r["trade_date"])), {}).get("foreign_lots", float("nan")), axis=1)
    return df


def markdown_table(rows: pd.DataFrame, cols: list[str]) -> str:
    out = rows[cols].copy()
    header = "| " + " | ".join(cols) + " |"
    divider = "| " + " | ".join(["---"] * len(cols)) + " |"
    lines = [header, divider]
    for row in out.itertuples(index=False):
        lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |")
    return "\n".join(lines)


def write_report(
    scanner: pd.DataFrame,
    latest_rows: pd.DataFrame,
    recent_rows: pd.DataFrame,
    topn_summary: pd.DataFrame,
    max_intraday_per_date: int,
    strict_filter_profile: str,
    as_of_date: str | None,
    excluded_ticker_count: int,
    listed_otc_count: int,
    construction_count: int,
    shakeout_filter: bool = True,
) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if scanner.empty:
        md = """# Breakout Daily Scanner

可交易 breakout 樣本為空，無法生成 watchlist。
"""
        REPORT_PATH.write_text(md, encoding="utf-8")
        return

    sample_start = str(pd.to_datetime(scanner["trade_date"]).min().date())
    sample_end = str(pd.to_datetime(scanner["trade_date"]).max().date())
    latest_trade_date = str(pd.to_datetime(scanner["trade_date"]).max().date())
    scan_date = as_of_date or latest_trade_date
    intraday_coverage = float((scanner["intraday_rows"].fillna(0) > 0).mean() * 100)

    _latest_cols_base = [
        "rank_in_date",
        "ticker",
        "scanner_score",
        "breakout_vol_capped",
        "shakeout_strong",
        "market_regime",
        "overhead_supply_layer",
        "breakout_next_low_open",
        "intraday_strong_attack",
        "below_open_after_1130",
        "close_pos",
        "volume_ratio",
        "breakout_strength_pct",
        "is_attention_stock",
        "is_disposition_stock",
        "vp_supply_vacuum",
        "vp_dense_above",
        "vp_overhead_pct",
        "vp_nearest_resistance_pct",
    ]
    _latest_cols = [c for c in _latest_cols_base if c in latest_rows.columns]
    latest_preview = (
        "_當日無候選，請改看近 20 交易日清單。_"
        if latest_rows.empty
        else markdown_table(latest_rows.head(15), _latest_cols)
    )

    recent_preview = (
        "_近 20 交易日無候選。_"
        if recent_rows.empty
        else markdown_table(
            recent_rows.head(20),
            [c for c in ["trade_date", "rank_in_date", "ticker", "scanner_score",
                         "breakout_vol_capped", "shakeout_strong", "market_regime",
                         "breakout_next_low_open", "intraday_strong_attack",
                         "below_open_after_1130", "breakout_strength_pct",
                         "is_attention_stock", "is_disposition_stock"] if c in recent_rows.columns],
        )
    )

    # Shakeout strong 區塊（default enabled）
    shakeout_section = ""
    if shakeout_filter:
        # 歷史已確認的 shakeout_strong 候選（近 20 交易日），附投信資料
        if "shakeout_strong" in recent_rows.columns:
            confirmed = recent_rows[recent_rows["shakeout_strong"].fillna(False)].copy()
            inst_token = os.environ.get("FINMIND_TOKEN", "")
            if not confirmed.empty and inst_token:
                confirmed = enrich_shakeout_institutional(confirmed, inst_token)
        else:
            confirmed = pd.DataFrame()

        # 今日 vol_capped 候選（等待明日確認）
        pending_cols_base = ["rank_in_date", "ticker", "scanner_score", "overhead_supply_layer",
                             "volume_ratio", "close_pos", "breakout_strength_pct"]
        if "breakout_vol_capped" in latest_rows.columns:
            pending = latest_rows[
                latest_rows["breakout_vol_capped"].fillna(False) &
                latest_rows["breakout_strength_pct"].fillna(0).ge(5.0)
            ].copy()
        else:
            pending = pd.DataFrame()

        confirmed_preview = (
            "_近期無已確認的 shakeout_strong 訊號。_"
            if confirmed.empty
            else markdown_table(confirmed.head(10),
                [c for c in ["trade_date", "ticker", "scanner_score", "breakout_strength_pct",
                             "sitc_lots", "foreign_lots",
                             "overhead_supply_layer", "volume_ratio"] if c in confirmed.columns])
        )
        pending_preview = (
            "_今日無等待確認的 shakeout 候選（需 score≥85 + breakout_vol_capped + strength≥5%）。_"
            if pending.empty
            else markdown_table(pending.head(10),
                [c for c in pending_cols_base if c in pending.columns])
        )

        shakeout_section = f"""
## 🌊 Shakeout Strong（開低震倉確認）

> **策略說明**：`breakout_vol_capped`（overhead=0 + 量比<4.5）+ 突破強度≥5% + **隔天開低撐住**
> 回測績效：20 日勝率 **62.4%**，20 日均報 **+12.7%**（樣本 298，2025Q2–2026Q2）
> ⚠️ 隔天開低為**次日確認型**訊號，今日候選須等明日開盤確認後方可進場。

### 近期已確認訊號（歷史）

{confirmed_preview}

### 今日候選（等待明日開盤確認）

若以下股票明日**開低且撐住**，即升格為 shakeout_strong 進場訊號：

{pending_preview}
"""

    md = f"""# Breakout Daily Scanner

資料庫：`/Users/howard/.four_seasons/data.sqlite`

回放日期：{scan_date}

樣本：{sample_start} 至 {sample_end}

最新交易日：{latest_trade_date}

分K覆蓋率：{intraday_coverage:.2f}%（近 20 交易日每日期最多補 {max_intraday_per_date} 檔分K）

排除清單筆數（DB）：{excluded_ticker_count}
FinMind 上市/上櫃清單筆數：{listed_otc_count}
FinMind 營建類股排除筆數：{construction_count}
硬過濾 profile：`{strict_filter_profile}`

## 排序邏輯（v3 對齊回測基準）

- **85 分**：`overhead=0` + `vol<4.5` + `close_pos≥0.85` + `vol_ratio≥1.5` + `strength≥5%`（對應回測 shakeout_strong 基礎）
- **80 分**：同上但 `strength` 在 2–5% 之間
- **overhead 加分**：`layer≤1` → +8；`layer≥4` → -8
- **分K加權**：`intraday_strong_attack` +10；`below_open_after_1130` / `attack_failure` -10
- 移除「不開低」加分（回測驗證為反訊號）

## Top-N 歷史命中摘要

{markdown_table(topn_summary, ["bucket", "n", "mean_10d_net_pct", "win_rate_10d_pct", "mean_20d_net_pct", "win_rate_20d_pct"]) if not topn_summary.empty else "_樣本不足，無法計算 Top-N 摘要。_"}

## 最新交易日候選

{latest_preview}
{shakeout_section}
## 近 20 交易日候選

{recent_preview}

輸出檔：

- `data/analysis/kline_course_backtest/breakout_daily_scanner.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_recent20d.csv`
- `data/analysis/kline_course_backtest/breakout_daily_scanner_topn_summary.csv`
- `data/analysis/kline_course_backtest/archive/breakout_daily_scanner/YYYY-MM-DD/*`
"""
    REPORT_PATH.write_text(md, encoding="utf-8")


def archive_outputs(
    scanner: pd.DataFrame,
    recent_rows: pd.DataFrame,
    topn_summary: pd.DataFrame,
    archive_date: str | None,
) -> tuple[Path, Path, Path, Path]:
    if archive_date:
        day_key = archive_date
    elif scanner.empty:
        day_key = pd.Timestamp.today().strftime("%Y-%m-%d")
    else:
        day_key = str(pd.to_datetime(scanner["trade_date"]).max().date())

    archive_path = ARCHIVE_DIR / day_key
    archive_path.mkdir(parents=True, exist_ok=True)

    scanner_path = archive_path / "breakout_daily_scanner.csv"
    recent_path = archive_path / "breakout_daily_scanner_recent20d.csv"
    topn_path = archive_path / "breakout_daily_scanner_topn_summary.csv"
    report_path = archive_path / "breakout_daily_scanner.md"

    scanner.to_csv(scanner_path, index=False)
    recent_rows.to_csv(recent_path, index=False)
    topn_summary.to_csv(topn_path, index=False)
    report_path.write_text(REPORT_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    return scanner_path, recent_path, topn_path, report_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sleep-seconds", type=float, default=0.2)
    parser.add_argument("--max-intraday-per-date", type=int, default=15)
    parser.add_argument("--strict-filter-profile", choices=["off", "balanced", "aggressive"], default="balanced")
    parser.add_argument("--as-of-date", type=str, default=None, help="Run scanner with data up to YYYY-MM-DD")
    parser.add_argument("--no-shakeout", action="store_true", default=False,
                        help="Disable shakeout_strong section in report")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    excluded_tickers = load_exclusion_tickers_from_db()
    finmind_info = load_finmind_stock_info()
    listed_otc_tickers, construction_tickers = prepare_finmind_filters(finmind_info)
    df = add_rolloff_pressure(add_market_regime(add_trade_fields(add_signals(add_features(load_bars())))))
    scanner = build_scanner(
        df,
        sleep_seconds=args.sleep_seconds,
        max_intraday_per_date=args.max_intraday_per_date,
        strict_filter_profile=args.strict_filter_profile,
        as_of_date=args.as_of_date,
        excluded_tickers=excluded_tickers,
        listed_otc_tickers=listed_otc_tickers,
        construction_tickers=construction_tickers,
    )

    if scanner.empty:
        latest_rows = scanner.copy()
        recent_rows = scanner.copy()
    else:
        latest_trade_date = scanner["trade_date"].max()
        latest_rows = scanner[scanner["trade_date"] == latest_trade_date].copy()
        recent_dates = sorted(scanner["trade_date"].dropna().unique())[-20:]
        recent_rows = scanner[scanner["trade_date"].isin(recent_dates)].copy()
    topn_summary = summarize_topn(scanner)

    scanner.to_csv(OUT_DIR / "breakout_daily_scanner.csv", index=False)
    recent_rows.to_csv(OUT_DIR / "breakout_daily_scanner_recent20d.csv", index=False)
    topn_summary.to_csv(TOPN_SUMMARY_PATH, index=False)
    write_report(
        scanner,
        latest_rows,
        recent_rows,
        topn_summary,
        max_intraday_per_date=args.max_intraday_per_date,
        strict_filter_profile=args.strict_filter_profile,
        as_of_date=args.as_of_date,
        excluded_ticker_count=len(excluded_tickers),
        listed_otc_count=len(listed_otc_tickers),
        construction_count=len(construction_tickers),
        shakeout_filter=not args.no_shakeout,
    )
    archive_scanner, archive_recent, archive_topn, archive_report = archive_outputs(
        scanner=scanner,
        recent_rows=recent_rows,
        topn_summary=topn_summary,
        archive_date=args.as_of_date,
    )
    print(REPORT_PATH)
    print(OUT_DIR / "breakout_daily_scanner.csv")
    print(OUT_DIR / "breakout_daily_scanner_recent20d.csv")
    print(TOPN_SUMMARY_PATH)
    print(archive_scanner)
    print(archive_recent)
    print(archive_topn)
    print(archive_report)


if __name__ == "__main__":
    main()
