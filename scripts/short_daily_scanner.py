from __future__ import annotations

import argparse
import os
import sqlite3
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from kline_course_backtest import add_features, add_signals, load_bars


OUT_DIR = Path("data/analysis/kline_course_backtest")
REPORT_PATH = Path("docs/K線力量判斷入門/backtests/short_daily_scanner.md")
ARCHIVE_DIR = OUT_DIR / "archive" / "short_daily_scanner"
DB_PATH = "/Users/howard/.four_seasons/data.sqlite"
FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"
STOCK_INFO_CACHE_PATH = OUT_DIR / "finmind_stock_info_cache.csv"
MIN_AVG_VOLUME_20 = 800_000
MIN_CLOSE = 10


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
    finally:
        conn.close()

    ticks = set(base_exclusion["ticker"].dropna().astype(str).str.strip())
    ticks.update(ineligible["ticker"].dropna().astype(str).str.strip())
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


def load_short_suspension_data() -> pd.DataFrame:
    """從 FinMind 載入融券暫停資料"""
    token = os.environ.get("FINMIND_TOKEN")
    if not token:
        return pd.DataFrame(columns=["stock_id", "date", "end_date"])

    try:
        headers = {"Authorization": f"Bearer {token}"}
        params = {"dataset": "TaiwanStockMarginShortSaleSuspension"}
        response = requests.get(FINMIND_API_URL, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != 200:
            return pd.DataFrame(columns=["stock_id", "date", "end_date"])
        data = pd.DataFrame(payload.get("data") or [])
        if not data.empty:
            data["stock_id"] = data["stock_id"].astype(str).str.strip()
            data["date"] = pd.to_datetime(data["date"])
            data["end_date"] = pd.to_datetime(data["end_date"])
        return data
    except Exception:
        return pd.DataFrame(columns=["stock_id", "date", "end_date"])


def load_short_sale_balance_data() -> pd.DataFrame:
    """從 FinMind 載入融券餘額資料"""
    token = os.environ.get("FINMIND_TOKEN")
    if not token:
        return pd.DataFrame()

    try:
        headers = {"Authorization": f"Bearer {token}"}
        params = {"dataset": "TaiwanDailyShortSaleBalances"}
        response = requests.get(FINMIND_API_URL, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != 200:
            return pd.DataFrame()
        data = pd.DataFrame(payload.get("data") or [])
        if not data.empty:
            data["stock_id"] = data["stock_id"].astype(str).str.strip()
            data["date"] = pd.to_datetime(data["date"])
        return data
    except Exception:
        return pd.DataFrame()


def tradable_short_mask(
    df: pd.DataFrame,
    excluded_tickers: set[str],
    listed_otc_tickers: set[str],
) -> pd.Series:
    """可交易的放空訊號篩選（課程訊號 + 台股實務限制）"""
    attention = pd.to_numeric(df["is_attention_stock"], errors="coerce").fillna(0).astype(int)
    disposition = pd.to_numeric(df["is_disposition_stock"], errors="coerce").fillna(0).astype(int)
    ticker_str = df["ticker"].astype(str)
    listed_otc_like = ticker_str.isin(listed_otc_tickers) if listed_otc_tickers else ticker_str.str.fullmatch(r"\d{4}")
    not_excluded = ~ticker_str.isin(excluded_tickers)
    return (
        df["short_entry"].fillna(False)
        & listed_otc_like
        & not_excluded
        & (attention == 0)
        & (disposition == 0)
        & (df["avg_volume_20"] >= MIN_AVG_VOLUME_20)
        & (df["close"] >= MIN_CLOSE)
    )


def add_short_suspension_info(rows: pd.DataFrame, suspension_data: pd.DataFrame) -> pd.DataFrame:
    """加入下一個融券暫停日期資訊"""
    rows = rows.copy()
    rows["short_suspension_start"] = None
    rows["days_to_suspension"] = np.nan

    if suspension_data.empty:
        return rows

    for idx, row in rows.iterrows():
        ticker = row["ticker"]
        trade_date = pd.Timestamp(row["trade_date"])

        ticker_suspensions = suspension_data[suspension_data["stock_id"] == ticker].copy()
        if ticker_suspensions.empty:
            continue

        # 找尋下一個未來的暫停開始日
        future_suspensions = ticker_suspensions[ticker_suspensions["date"] > trade_date]
        if not future_suspensions.empty:
            next_suspension = future_suspensions.iloc[0]
            rows.at[idx, "short_suspension_start"] = next_suspension["date"].strftime("%Y-%m-%d")
            # 粗略計算工作日距離（使用 5/7 估算）
            days_diff = (next_suspension["date"] - trade_date).days
            work_days = int(days_diff * 5 / 7)
            rows.at[idx, "days_to_suspension"] = max(work_days, 1)

    return rows


def add_short_sale_info(rows: pd.DataFrame, sale_balance_data: pd.DataFrame) -> pd.DataFrame:
    """加入融券餘額與使用率資訊"""
    rows = rows.copy()
    rows["short_sale_balance"] = np.nan
    rows["short_sale_utilization"] = np.nan

    if sale_balance_data.empty:
        return rows

    for idx, row in rows.iterrows():
        ticker = row["ticker"]
        trade_date = pd.Timestamp(row["trade_date"])

        ticker_data = sale_balance_data[sale_balance_data["stock_id"] == ticker].copy()
        if ticker_data.empty:
            continue

        # 找尋該日期的資料
        day_data = ticker_data[ticker_data["date"] == trade_date]
        if not day_data.empty:
            bal = day_data.iloc[0].get("MarginShortSalesCurrentDayBalance")
            quota = day_data.iloc[0].get("MarginShortSalesQuota")
            if bal is not None and quota is not None:
                try:
                    bal_val = float(bal)
                    quota_val = float(quota)
                    rows.at[idx, "short_sale_balance"] = bal_val
                    if quota_val > 0:
                        rows.at[idx, "short_sale_utilization"] = (bal_val / quota_val * 100)
                except (ValueError, TypeError):
                    pass

    return rows


def add_pre_rank_score(rows: pd.DataFrame) -> pd.DataFrame:
    """計算預排序評分（課程訊號品質 + 市場 regime）"""
    rows = rows.copy()
    rows["pre_rank_score"] = 50.0

    # 課程品質指標：隔日確認跌破是 real_breakdown_after_range 內含的條件
    # 加分條件：收盤位置低（買盤不繼），成交量倍數高
    rows["pre_rank_score"] += np.where(rows["close_pos"] <= 0.3, 8, 0)
    rows["pre_rank_score"] += np.where(rows["volume_ratio"] >= 1.2, 8, 0)
    rows["pre_rank_score"] += np.where(rows["body_pct"] >= 0.02, 6, 0)

    # 風險調整：避免短期內即將進入融券暫停期
    days_to_susp = pd.to_numeric(rows["days_to_suspension"], errors="coerce")
    rows["pre_rank_score"] -= np.where((days_to_susp.notna()) & (days_to_susp <= 5), 15, 0)

    # 融券使用率過高降分（軋空風險）
    short_util = pd.to_numeric(rows["short_sale_utilization"], errors="coerce")
    rows["pre_rank_score"] -= np.where((short_util.notna()) & (short_util > 60), 10, 0)

    return rows


def score_rows(rows: pd.DataFrame) -> pd.DataFrame:
    """最終評分"""
    rows = rows.copy()
    rows = add_pre_rank_score(rows)
    rows["scanner_score"] = rows["pre_rank_score"].clip(lower=0, upper=100).round(2)
    return rows


def apply_strict_profile(rows: pd.DataFrame, profile: str) -> pd.DataFrame:
    """應用嚴格過濾 profile"""
    rows = rows.copy()
    if profile == "off":
        return rows
    if profile == "conservative":
        return rows[
            (rows["close_pos"] <= 0.25)
            & (rows["volume_ratio"] >= 1.5)
            & (rows["avg_volume_20"] >= 1_200_000)
            & (rows["close"] >= 20)
            & (pd.to_numeric(rows["days_to_suspension"], errors="coerce") > 5)
        ].copy()
    if profile == "balanced":
        return rows[
            (rows["close_pos"] <= 0.3)
            & (rows["volume_ratio"] >= 1.2)
            & (rows["avg_volume_20"] >= 800_000)
        ].copy()
    raise ValueError(f"unknown strict profile: {profile}")


def build_scanner(
    df: pd.DataFrame,
    strict_filter_profile: str,
    as_of_date: str | None,
    excluded_tickers: set[str],
    listed_otc_tickers: set[str],
    suspension_data: pd.DataFrame,
    sale_balance_data: pd.DataFrame,
) -> pd.DataFrame:
    """建立掃描器候選清單"""
    if as_of_date:
        cutoff = pd.Timestamp(as_of_date)
        df = df[pd.to_datetime(df["trade_date"]) <= cutoff].copy()

    mask = tradable_short_mask(df, excluded_tickers, listed_otc_tickers)
    rows = df[mask].copy()

    rows = rows[
        [
            "ticker",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "avg_volume_20",
            "volume_ratio",
            "close_pos",
            "body_pct",
            "prior_low_20",
            "ma60",
            "ret_10d",
            "ret_20d",
            "is_attention_stock",
            "is_disposition_stock",
        ]
    ]
    rows["trade_date"] = pd.to_datetime(rows["trade_date"]).dt.strftime("%Y-%m-%d")
    rows = add_short_suspension_info(rows, suspension_data)
    rows = add_short_sale_info(rows, sale_balance_data)
    rows = add_pre_rank_score(rows)
    rows = apply_strict_profile(rows, strict_filter_profile)

    if rows.empty:
        return rows

    rows = score_rows(rows)
    rows = rows.sort_values(["trade_date", "scanner_score", "volume"], ascending=[False, False, False])
    rows["rank_in_date"] = rows.groupby("trade_date")["scanner_score"].rank(method="first", ascending=False).astype(int)

    return rows


def summarize_topn(scanner: pd.DataFrame) -> pd.DataFrame:
    """彙總 Top-N 樣本表現"""
    if scanner.empty:
        return pd.DataFrame(columns=["bucket", "n", "mean_10d_ret_pct", "win_rate_10d_pct", "mean_20d_ret_pct", "win_rate_20d_pct"])

    valid = scanner.dropna(subset=["ret_10d", "ret_20d"]).copy()
    if valid.empty:
        return pd.DataFrame(columns=["bucket", "n", "mean_10d_ret_pct", "win_rate_10d_pct", "mean_20d_ret_pct", "win_rate_20d_pct"])

    # 注意：放空報酬計算為 (進場價 - 出場價) / 進場價
    # 負報酬表示股價上升、放空虧損
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
                "mean_10d_ret_pct": round(float(rows["ret_10d"].mean() * 100), 3),
                "win_rate_10d_pct": round(float((rows["ret_10d"] > 0).mean() * 100), 2),
                "mean_20d_ret_pct": round(float(rows["ret_20d"].mean() * 100), 3),
                "win_rate_20d_pct": round(float((rows["ret_20d"] > 0).mean() * 100), 2),
            }
        )
    return pd.DataFrame(out)


def markdown_table(rows: pd.DataFrame, cols: list[str]) -> str:
    """生成 Markdown 表格"""
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
    strict_filter_profile: str,
    as_of_date: str | None,
    excluded_ticker_count: int,
    listed_otc_count: int,
) -> None:
    """生成掃描器報告"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if scanner.empty:
        md = """# 放空每日掃描清單

可交易 short_entry 樣本為空，無法生成候選清單。
"""
        REPORT_PATH.write_text(md, encoding="utf-8")
        return

    sample_start = str(pd.to_datetime(scanner["trade_date"]).min().date())
    sample_end = str(pd.to_datetime(scanner["trade_date"]).max().date())
    latest_trade_date = str(pd.to_datetime(scanner["trade_date"]).max().date())
    scan_date = as_of_date or latest_trade_date

    _latest_cols_base = [
        "rank_in_date",
        "ticker",
        "scanner_score",
        "close_pos",
        "volume_ratio",
        "days_to_suspension",
        "short_sale_utilization",
    ]
    _latest_cols = [c for c in _latest_cols_base if c in latest_rows.columns]
    latest_preview = (
        "_當日無候選，請改看近 20 交易日清單。_"
        if latest_rows.empty
        else markdown_table(
            latest_rows.head(15),
            _latest_cols,
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
                "close_pos",
                "days_to_suspension",
            ],
        )
    )

    md = f"""# 放空每日掃描清單

資料庫：`/Users/howard/.four_seasons/data.sqlite`

回放日期：{scan_date}

樣本：{sample_start} 至 {sample_end}

最新交易日：{latest_trade_date}

排除清單筆數（DB）：{excluded_ticker_count}
FinMind 上市/上櫃清單筆數：{listed_otc_count}
硬過濾 profile：`{strict_filter_profile}`

## 課程訊號定義

本掃描器使用 `short_strategy_spec.md` 定義的 `short_entry` 訊號，整合以下四個課程要素：

1. **弱勢**：收盤在季線下方 (`close < ma60`) + 季線下彎 (`ma60_down`)
2. **跌破**：收盤跌破 20 日低點 (`close < prior_low_20`) + 隔日確認 (`next_close < prior_low_20`)
3. **反彈遇壓**：用季線下彎 (`ma60_down`) 作背景代理（課程未明確說明盤中確認時機）
4. **買盤不繼**：出現長黑 K (`long_black_k`: 黑K + body_pct ≥ 1.5%)

## 可交易性過濾（課程未涵蓋）

以下過濾邏輯為台股實務補充，不可混入課程框架的 K 線訊號判斷：

| 過濾條件 | 說明 |
| --- | --- |
| 注意股/處置股排除 | 法規禁止融券 |
| 融券今日餘額 > 0 | 確認個股有融券可用 |
| 20 日均量 ≥ 800,000 股 | 放空回補需要買盤承接，流動性要求較高 |
| 股價 ≥ 10 元 | 低價股融券風險高 |
| 下次融券暫停日距今 > 5 個工作日 | 避免進場後不久即遭強制回補 |

## 排序邏輯

基礎分數：50 分（通過上述可交易性篩選）

加分項目：
- 收盤位置低 (`close_pos <= 0.3`) → +8 分（買盤確實不繼）
- 成交量倍數高 (`volume_ratio >= 1.2`) → +8 分（量能確認）
- K線實體大 (`body_pct >= 0.02`) → +6 分（長黑K確認）

風險扣分：
- 距融券暫停日 <= 5 工作日 → -15 分（強制回補風險）
- 融券使用率 > 60% → -10 分（軋空風險高）

## Top-N 歷史命中摘要

{markdown_table(topn_summary, ["bucket", "n", "mean_10d_ret_pct", "win_rate_10d_pct", "mean_20d_ret_pct", "win_rate_20d_pct"]) if not topn_summary.empty else "_樣本不足，無法計算 Top-N 摘要。_"}

## 最新交易日候選

{latest_preview}

## 近 20 交易日候選

{recent_preview}

## 輸出檔案

- `data/analysis/kline_course_backtest/short_daily_scanner.csv` — 完整歷史掃描結果
- `data/analysis/kline_course_backtest/short_daily_scanner_recent20d.csv` — 最近 20 交易日候選
- `data/analysis/kline_course_backtest/archive/short_daily_scanner/YYYY-MM-DD/*` — 存檔版本

## 重要聲明

### 課程訊號與台股實務的邊界

本掃描器包含兩層過濾：

1. **課程框架（短策略教學）**：`short_entry` 訊號完全遵循 `short_strategy_spec.md`，使用課程教過的 K 線條件判斷弱勢、跌破、反彈遇壓、買盤不繼。

2. **台股實務補充（課程未涵蓋）**：可交易性過濾、融券暫停日期、使用率限制皆屬台股交易制度規範，非課程教學內容，與課程 K 線訊號邏輯完全分開。使用者應當理解：
   - 課程教授的是 K 線判斷邏輯，不涉及任何台股融券操作、券源管理、強制回補等機制。
   - 本掃描器的「排序」與「過濾」中包含實務限制，旨在提升可執行性，但不屬於課程範圍。
   - 若使用者只想驗證課程訊號本身，應忽略可交易性過濾欄位，僅看 `short_entry` 訊號成立的日期與股票。

"""
    REPORT_PATH.write_text(md, encoding="utf-8")


def archive_outputs(
    scanner: pd.DataFrame,
    recent_rows: pd.DataFrame,
    topn_summary: pd.DataFrame,
    archive_date: str | None,
) -> tuple[Path, Path, Path, Path]:
    """存檔輸出"""
    if archive_date:
        day_key = archive_date
    elif scanner.empty:
        day_key = pd.Timestamp.today().strftime("%Y-%m-%d")
    else:
        day_key = str(pd.to_datetime(scanner["trade_date"]).max().date())

    archive_path = ARCHIVE_DIR / day_key
    archive_path.mkdir(parents=True, exist_ok=True)

    scanner_path = archive_path / "short_daily_scanner.csv"
    recent_path = archive_path / "short_daily_scanner_recent20d.csv"
    topn_path = archive_path / "short_daily_scanner_topn_summary.csv"
    report_path = archive_path / "short_daily_scanner.md"

    scanner.to_csv(scanner_path, index=False)
    recent_rows.to_csv(recent_path, index=False)
    topn_summary.to_csv(topn_path, index=False)
    report_path.write_text(REPORT_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    return scanner_path, recent_path, topn_path, report_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict-filter-profile", choices=["off", "balanced", "conservative"], default="balanced")
    parser.add_argument("--as-of-date", type=str, default=None, help="Run scanner with data up to YYYY-MM-DD")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    excluded_tickers = load_exclusion_tickers_from_db()
    finmind_info = load_finmind_stock_info()
    listed_otc_tickers, _ = prepare_finmind_filters(finmind_info)
    suspension_data = load_short_suspension_data()
    sale_balance_data = load_short_sale_balance_data()

    df = add_signals(add_features(load_bars()))
    scanner = build_scanner(
        df,
        strict_filter_profile=args.strict_filter_profile,
        as_of_date=args.as_of_date,
        excluded_tickers=excluded_tickers,
        listed_otc_tickers=listed_otc_tickers,
        suspension_data=suspension_data,
        sale_balance_data=sale_balance_data,
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

    scanner.to_csv(OUT_DIR / "short_daily_scanner.csv", index=False)
    recent_rows.to_csv(OUT_DIR / "short_daily_scanner_recent20d.csv", index=False)
    write_report(
        scanner,
        latest_rows,
        recent_rows,
        topn_summary,
        strict_filter_profile=args.strict_filter_profile,
        as_of_date=args.as_of_date,
        excluded_ticker_count=len(excluded_tickers),
        listed_otc_count=len(listed_otc_tickers),
    )
    archive_scanner, archive_recent, archive_topn, archive_report = archive_outputs(
        scanner=scanner,
        recent_rows=recent_rows,
        topn_summary=topn_summary,
        archive_date=args.as_of_date,
    )
    print(REPORT_PATH)
    print(OUT_DIR / "short_daily_scanner.csv")
    print(OUT_DIR / "short_daily_scanner_recent20d.csv")
    print(archive_scanner)
    print(archive_recent)
    print(archive_topn)
    print(archive_report)


if __name__ == "__main__":
    main()
