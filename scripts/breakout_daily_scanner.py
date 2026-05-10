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


OUT_DIR = Path("data/analysis/kline_course_backtest")
REPORT_PATH = Path("docs/K線力量判斷入門/backtests/breakout_daily_scanner.md")
TOPN_SUMMARY_PATH = OUT_DIR / "breakout_daily_scanner_topn_summary.csv"
ARCHIVE_DIR = OUT_DIR / "archive" / "breakout_daily_scanner"
DB_PATH = "/Users/howard/.four_seasons/data.sqlite"
FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"
STOCK_INFO_CACHE_PATH = OUT_DIR / "finmind_stock_info_cache.csv"


def load_exclusion_tickers_from_db(db_path: str = DB_PATH) -> set[str]:
    conn = sqlite3.connect(db_path)
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
        & (attention == 0)
        & (disposition == 0)
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
        rec["trade_date"] = trade_date
        enriched.append(rec)
    return pd.DataFrame(enriched)


def add_pre_rank_score(rows: pd.DataFrame) -> pd.DataFrame:
    rows = rows.copy()
    rows["breakout_strength_pct"] = (rows["close"] / rows["prior_high_60"] - 1) * 100
    rows["pre_rank_score"] = 50.0
    rows["pre_rank_score"] += np.where(rows["market_regime"] == "range", 10, 0)
    rows["pre_rank_score"] += np.where(rows["market_regime"] == "bull", 3, 0)
    rows["pre_rank_score"] += np.where(rows["breakout_next_not_low_open"].fillna(False), 10, 0)
    rows["pre_rank_score"] += np.where(rows["close_pos"] >= 0.85, 8, 0)
    rows["pre_rank_score"] += np.where(rows["volume_ratio"] >= 1.5, 8, 0)
    rows["pre_rank_score"] += np.where(rows["breakout_strength_pct"] >= 1.5, 6, 0)
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
    rows["scanner_score"] = rows["scanner_score"].clip(lower=0, upper=100).round(2)

    return rows


def apply_strict_profile(rows: pd.DataFrame, profile: str) -> pd.DataFrame:
    rows = rows.copy()
    if profile == "off":
        return rows
    if profile == "balanced":
        return rows[
            rows["market_regime"].isin(["bull", "range"])
            & (rows["breakout_strength_pct"] >= 1.0)
            & (rows["close_pos"] >= 0.85)
            & (rows["volume_ratio"] >= 1.5)
            & (rows["avg_volume_20"] >= 800_000)
            & (rows["close"] >= 15)
        ].copy()
    if profile == "aggressive":
        return rows[
            rows["market_regime"].isin(["bull", "range"])
            & (rows["breakout_strength_pct"] >= 1.5)
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
        ]
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

    latest_preview = (
        "_當日無候選，請改看近 20 交易日清單。_"
        if latest_rows.empty
        else markdown_table(
            latest_rows.head(15),
            [
                "rank_in_date",
                "ticker",
                "scanner_score",
                "market_regime",
                "breakout_next_not_low_open",
                "intraday_strong_attack",
                "below_open_after_1130",
                "close_pos",
                "volume_ratio",
            ],
        )
    )

    recent_preview = (
        "_近 20 交易日無候選。_"
        if recent_rows.empty
        else markdown_table(
            recent_rows.head(20),
            [
                "trade_date",
                "rank_in_date",
                "ticker",
                "scanner_score",
                "market_regime",
                "breakout_next_not_low_open",
                "intraday_strong_attack",
                "below_open_after_1130",
            ],
        )
    )

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

## 排序邏輯

- 基礎分數：可交易 breakout 候選（排除注意/處置、低量、低價）
- 加分：`range regime`、`breakout_next_not_low_open`、`close_pos` 高、`volume_ratio` 高、突破幅度高
- 分K加權：`intraday_strong_attack` 加分；`below_open_after_1130` 和 `intraday_attack_failure` 扣分

## Top-N 歷史命中摘要

{markdown_table(topn_summary, ["bucket", "n", "mean_10d_net_pct", "win_rate_10d_pct", "mean_20d_net_pct", "win_rate_20d_pct"]) if not topn_summary.empty else "_樣本不足，無法計算 Top-N 摘要。_"}

## 最新交易日候選

{latest_preview}

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
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    excluded_tickers = load_exclusion_tickers_from_db()
    finmind_info = load_finmind_stock_info()
    listed_otc_tickers, construction_tickers = prepare_finmind_filters(finmind_info)
    df = add_market_regime(add_trade_fields(add_signals(add_features(load_bars()))))
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
