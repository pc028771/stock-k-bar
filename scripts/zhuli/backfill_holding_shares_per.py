"""Backfill TaiwanStockHoldingSharesPer from FinMind into local SQLite DB.

Usage:
    python scripts/zhuli/backfill_holding_shares_per.py

Env:
    FINMIND_TOKEN — FinMind API JWT token
    DB_PATH       — 可選, 預設 ~/.four_seasons/data.sqlite (symlink)

資料源：FinMind TaiwanStockHoldingSharesPer
週度發布（每周五後更新）
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import requests

# === 設定 ===
_DB_PATH = Path(os.environ.get("DB_PATH", "~/.four_seasons/data.sqlite")).expanduser()
_FINMIND_TOKEN = os.environ.get("FINMIND_TOKEN", "")
_FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
_START_DATE = "2024-01-01"
_END_DATE = "2026-05-20"
_SLEEP_PER_CALL = 0.3  # 保守 throttle (sponsor tier ~600 calls/hr)

# Ticker pool：watchlist 5 檔 + _GROUP_TICKERS 所有 ticker + 主力大老師當日焦點
_WATCHLIST_TICKERS = {"2472", "6139", "3663", "8064", "8027", "3149"}

_GROUP_TICKERS_MAP = {
    "半導體": {"2330", "2454", "8110", "3583", "6770", "6669", "3260", "3017", "3711", "6488", "2308", "6451"},
    "被動元件": {"2327", "2492", "2472", "3026", "6173", "2375", "2456", "2354", "2308", "2317"},
    "機器人": {"4540", "1597", "2464", "4576", "2049", "8027", "3552", "2233", "3041", "2059"},
    "記憶體": {"2344", "2337", "2408", "3006", "8150", "2351", "3105", "2329", "8048"},
    "玻璃基板": {"8064", "3055", "3580", "3663", "4916", "6139", "1560", "3481"},
}

# 主力大老師當日焦點（2026-05-21 line/直播）
_TEACHER_FOCUS_MAP = {
    "大錢":     {"2454", "2327", "8299", "2376"},
    "光":       {"3008", "3406", "6209"},
    "玻璃設備": {"8064", "8027", "6207", "1595", "3580", "3663"},
    "面板":     {"3481", "3615", "6405", "3149"},
    "機器人":   {"2464", "1597", "4576", "2233", "4540", "2049"},
    "記憶體":   {"2344", "3006", "4973", "6531"},
    "CPO":      {"3374", "6451", "6789"},
    "功率":     {"8261", "3317"},
    "工業電腦": {"4916", "6166", "2395"},
    "網通":     {"4906", "3704"},
    "BBU":      {"3211", "4931"},
    "被動元件": {"6173", "3026", "2327", "2492", "6449", "6284"},
    "單兵":     {"7788", "3162"},
    "成熟":     {"2303"},
    "矽晶圓":   {"3532", "3016"},
    "通路":     {"3033", "3028", "3702", "3128", "3036", "6227", "8096", "3209"},
}

_ALL_TICKERS = sorted(
    _WATCHLIST_TICKERS
    | {t for ts in _GROUP_TICKERS_MAP.values() for t in ts}
    | {t for ts in _TEACHER_FOCUS_MAP.values() for t in ts}
)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS stock_holding_shares_per (
    date      TEXT    NOT NULL,
    stock_id  TEXT    NOT NULL,
    level     TEXT    NOT NULL,
    people    INTEGER,
    percent   REAL,
    unit      INTEGER,
    PRIMARY KEY (date, stock_id, level)
)
"""

_INSERT_SQL = """
INSERT OR REPLACE INTO stock_holding_shares_per
    (date, stock_id, level, people, percent, unit)
VALUES (?, ?, ?, ?, ?, ?)
"""


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_TABLE_SQL)
    conn.commit()


def fetch_one_ticker(ticker: str) -> list[dict]:
    """從 FinMind 拉一檔完整期間持股集中度資料."""
    if not _FINMIND_TOKEN:
        raise ValueError("FINMIND_TOKEN 環境變數未設定")
    r = requests.get(
        _FINMIND_URL,
        params={
            "dataset": "TaiwanStockHoldingSharesPer",
            "data_id": ticker,
            "start_date": _START_DATE,
            "end_date": _END_DATE,
            "token": _FINMIND_TOKEN,
        },
        timeout=60,
    )
    r.raise_for_status()
    payload = r.json()
    if payload.get("status") != 200:
        msg = payload.get("msg", "unknown error")
        raise RuntimeError(f"FinMind API error: {msg}")
    return payload.get("data", [])


def upsert_ticker_data(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """插入 / 更新一檔資料，回傳 inserted row count."""
    params = [
        (
            row["date"],
            row["stock_id"],
            row["HoldingSharesLevel"],
            row.get("people"),
            row.get("percent"),
            row.get("unit"),
        )
        for row in rows
    ]
    conn.executemany(_INSERT_SQL, params)
    conn.commit()
    return len(params)


def main() -> None:
    if not _FINMIND_TOKEN:
        print("❌ 請設定環境變數 FINMIND_TOKEN")
        return

    print(f"DB: {_DB_PATH}")
    print(f"Ticker pool: {len(_ALL_TICKERS)} 檔 (watchlist 5 + group tickers)")
    print(f"期間: {_START_DATE} ~ {_END_DATE}")
    print(f"Throttle: sleep {_SLEEP_PER_CALL}s / call")
    print()

    with sqlite3.connect(str(_DB_PATH), timeout=30) as conn:
        ensure_table(conn)

    total_rows = 0
    errors: list[str] = []

    for i, ticker in enumerate(_ALL_TICKERS, start=1):
        try:
            rows = fetch_one_ticker(ticker)
            with sqlite3.connect(str(_DB_PATH), timeout=30) as conn:
                inserted = upsert_ticker_data(conn, rows)
            total_rows += inserted
            if i % 10 == 0 or i == len(_ALL_TICKERS):
                print(
                    f"  [{i:>3}/{len(_ALL_TICKERS)}] {ticker} — "
                    f"{inserted} rows  (cumulative {total_rows})"
                )
            else:
                print(f"  {ticker} {inserted}r", end="  ", flush=True)
        except Exception as exc:
            errors.append(f"{ticker}: {exc}")
            print(f"\n  ⚠️  {ticker} 失敗: {exc}")
        time.sleep(_SLEEP_PER_CALL)

    print()
    print(f"完成！共寫入 {total_rows} rows，{len(errors)} 個失敗")
    if errors:
        print("失敗清單：")
        for e in errors:
            print(f"  {e}")


if __name__ == "__main__":
    main()
