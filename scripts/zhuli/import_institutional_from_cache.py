"""從 stock-analysis-system 的 FinMind ndjson cache 匯入法人資料至 SQLite DB。

⚠️ 不呼叫 FinMind API — 完全走本機 cache。

資料來源：
    /Users/howard/Repository/stock-analysis-system/data/raw/
        TaiwanStockInstitutionalInvestorsBuySell/<ticker>/<YYYY>.ndjson
        TaiwanStockInstitutionalInvestorsBuySell/<ticker>/<YYYY-MM>.ndjson

ndjson schema（每行）：
    {"date": "YYYY-MM-DD [00:00:00]", "stock_id": "xxxx",
     "buy": N, "sell": N, "name": "Foreign_Investor|Investment_Trust|..."}

目標表 institutional_investors：
    ticker     TEXT
    trade_date DATE        (YYYY-MM-DD)
    sitc_buy   REAL        Investment_Trust.buy  / 1000（張）
    sitc_sell  REAL        Investment_Trust.sell / 1000
    sitc_net   REAL        sitc_buy - sitc_sell
    foreign_buy  REAL      Foreign_Investor.buy  / 1000
    foreign_sell REAL      Foreign_Investor.sell / 1000
    foreign_net  REAL      foreign_buy - foreign_sell
    UNIQUE(ticker, trade_date)

Usage:
    python scripts/zhuli/import_institutional_from_cache.py
    python scripts/zhuli/import_institutional_from_cache.py --tickers 2330 2317
    python scripts/zhuli/import_institutional_from_cache.py --dry-run
    python scripts/zhuli/import_institutional_from_cache.py --db /path/to/other.sqlite
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

# ── 路徑設定 ──────────────────────────────────────────────────────────────────
_WORKTREE = Path(__file__).parent.parent.parent   # phase1-scanner/
_SCRIPTS_DIR = _WORKTREE / "scripts"
for _p in [str(_WORKTREE), str(_SCRIPTS_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kline.bars import DEFAULT_DB_PATH  # noqa: E402

# ── 常數 ──────────────────────────────────────────────────────────────────────
CACHE_ROOT = Path(
    "/Users/howard/Repository/stock-analysis-system/data/raw/"
    "TaiwanStockInstitutionalInvestorsBuySell"
)

# 只聚合這兩種 name
TARGET_NAMES = {
    "sitc": "Investment_Trust",
    "foreign": "Foreign_Investor",
}

# ── DB 工具 ───────────────────────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS institutional_investors (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker       TEXT    NOT NULL,
    trade_date   DATE    NOT NULL,
    sitc_buy     REAL    DEFAULT 0,
    sitc_sell    REAL    DEFAULT 0,
    sitc_net     REAL    DEFAULT 0,
    foreign_buy  REAL    DEFAULT 0,
    foreign_sell REAL    DEFAULT 0,
    foreign_net  REAL    DEFAULT 0,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, trade_date)
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_inst_inv_ticker_date
    ON institutional_investors (ticker, trade_date);
"""

MIGRATE_COLS_SQL = [
    "ALTER TABLE institutional_investors ADD COLUMN foreign_buy  REAL DEFAULT 0",
    "ALTER TABLE institutional_investors ADD COLUMN foreign_sell REAL DEFAULT 0",
    "ALTER TABLE institutional_investors ADD COLUMN foreign_net  REAL DEFAULT 0",
]


def ensure_table(conn: sqlite3.Connection) -> None:
    """建立 institutional_investors 表（若不存在），並補齊欄位。"""
    conn.execute(CREATE_TABLE_SQL)
    conn.execute(CREATE_INDEX_SQL)
    existing_cols = {c[1] for c in conn.execute(
        "PRAGMA table_info(institutional_investors)"
    ).fetchall()}
    for alter_sql in MIGRATE_COLS_SQL:
        col_name = alter_sql.split("ADD COLUMN")[1].strip().split()[0]
        if col_name not in existing_cols:
            conn.execute(alter_sql)
    conn.commit()


def upsert_rows(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """INSERT OR REPLACE 多筆資料；回傳寫入筆數。"""
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT OR REPLACE INTO institutional_investors
            (ticker, trade_date, sitc_buy, sitc_sell, sitc_net,
             foreign_buy, foreign_sell, foreign_net)
        VALUES (:ticker, :trade_date, :sitc_buy, :sitc_sell, :sitc_net,
                :foreign_buy, :foreign_sell, :foreign_net)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


# ── 資料讀取與轉換 ──────────────────────────────────────────────────────────

def read_ndjson_file(path: Path) -> pd.DataFrame:
    """讀取單一 .ndjson 檔，回傳 DataFrame（遇到解析錯誤的行略過）。"""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records)


def normalize_date(date_str: str) -> str:
    """把 '2024-05-13 00:00:00' 或 '2024-05-13' 統一轉為 'YYYY-MM-DD'。"""
    return str(date_str).split(" ")[0]


def parse_ticker_cache(ticker_dir: Path) -> list[dict]:
    """讀取某 ticker 下所有 .ndjson，聚合成 DB 要的格式。

    - 只取 Foreign_Investor 與 Investment_Trust
    - buy/sell 單位：股 → 張（/ 1000）
    - buy=0 且 sell=0 的日期略過
    - 回傳每日一筆的 dict list

    Returns:
        list of dict with keys:
            ticker, trade_date, sitc_buy, sitc_sell, sitc_net,
            foreign_buy, foreign_sell, foreign_net
    """
    ticker = ticker_dir.name
    ndjson_files = sorted(ticker_dir.glob("*.ndjson"))
    if not ndjson_files:
        return []

    all_frames = []
    for f in ndjson_files:
        df = read_ndjson_file(f)
        if df.empty:
            continue
        # 確保必要欄位存在
        if not {"date", "name", "buy", "sell"}.issubset(df.columns):
            continue
        all_frames.append(df)

    if not all_frames:
        return []

    raw = pd.concat(all_frames, ignore_index=True)

    # 標準化日期格式
    raw["date"] = raw["date"].apply(normalize_date)

    # 只保留目標法人種類
    sitc_df = raw[raw["name"] == TARGET_NAMES["sitc"]][["date", "buy", "sell"]].copy()
    foreign_df = raw[raw["name"] == TARGET_NAMES["foreign"]][["date", "buy", "sell"]].copy()

    # 同一 ticker 同日可能出現多筆（不同檔案重疊）→ groupby sum
    if not sitc_df.empty:
        sitc_df = (
            sitc_df.groupby("date")[["buy", "sell"]].sum()
            .rename(columns={"buy": "sitc_buy", "sell": "sitc_sell"})
            .reset_index()
        )
    else:
        sitc_df = pd.DataFrame(columns=["date", "sitc_buy", "sitc_sell"])

    if not foreign_df.empty:
        foreign_df = (
            foreign_df.groupby("date")[["buy", "sell"]].sum()
            .rename(columns={"buy": "foreign_buy", "sell": "foreign_sell"})
            .reset_index()
        )
    else:
        foreign_df = pd.DataFrame(columns=["date", "foreign_buy", "foreign_sell"])

    # 合併投信與外資
    merged = pd.merge(sitc_df, foreign_df, on="date", how="outer").fillna(0)

    # 過濾全零日（所有欄位 = 0）
    merged = merged[
        ~(
            (merged.get("sitc_buy", 0) == 0)
            & (merged.get("sitc_sell", 0) == 0)
            & (merged.get("foreign_buy", 0) == 0)
            & (merged.get("foreign_sell", 0) == 0)
        )
    ]

    if merged.empty:
        return []

    # 單位換算：股 → 張（1 張 = 1000 股）
    for col in ("sitc_buy", "sitc_sell", "foreign_buy", "foreign_sell"):
        merged[col] = merged[col] / 1000.0

    merged["sitc_net"] = merged["sitc_buy"] - merged["sitc_sell"]
    merged["foreign_net"] = merged["foreign_buy"] - merged["foreign_sell"]
    merged["ticker"] = ticker
    merged = merged.rename(columns={"date": "trade_date"})

    return merged[[
        "ticker", "trade_date",
        "sitc_buy", "sitc_sell", "sitc_net",
        "foreign_buy", "foreign_sell", "foreign_net",
    ]].to_dict("records")


# ── 主流程 ────────────────────────────────────────────────────────────────────

def import_all(
    db_path: Path = DEFAULT_DB_PATH,
    tickers: list[str] | None = None,
    dry_run: bool = False,
    verbose: bool = False,
    batch_size: int = 500,
) -> dict:
    """掃描所有 ticker 的 ndjson cache 並 upsert 至 DB。

    Args:
        db_path:    SQLite DB 路徑
        tickers:    指定 ticker 清單；None = 掃描 CACHE_ROOT 下所有子目錄
        dry_run:    True = 只顯示統計，不寫入 DB
        verbose:    True = 每 ticker 輸出詳細訊息
        batch_size: 每批 commit 的 ticker 數量（降低記憶體壓力）

    Returns:
        dict: {processed, inserted, skipped, errors}
    """
    if not CACHE_ROOT.exists():
        raise FileNotFoundError(f"Cache 目錄不存在：{CACHE_ROOT}")

    # 決定要處理哪些 ticker 目錄
    if tickers:
        ticker_dirs = [CACHE_ROOT / t for t in tickers if (CACHE_ROOT / t).is_dir()]
        missing = [t for t in tickers if not (CACHE_ROOT / t).is_dir()]
        if missing:
            print(f"[警告] 以下 ticker 在 cache 中找不到：{missing}")
    else:
        ticker_dirs = sorted([d for d in CACHE_ROOT.iterdir() if d.is_dir()])

    total = len(ticker_dirs)
    print(f"待處理 ticker 數：{total}")

    if dry_run:
        print("[dry-run] 不寫入 DB，僅顯示統計。")

    conn: sqlite3.Connection | None = None
    if not dry_run:
        conn = sqlite3.connect(str(db_path), timeout=60)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        ensure_table(conn)

    stats = {"processed": 0, "inserted": 0, "skipped": 0, "errors": 0}

    # 進度條
    iterator = (
        tqdm(ticker_dirs, desc="匯入法人資料", unit="ticker")
        if HAS_TQDM else ticker_dirs
    )

    for ticker_dir in iterator:
        ticker = ticker_dir.name
        try:
            rows = parse_ticker_cache(ticker_dir)
            stats["processed"] += 1

            if not rows:
                stats["skipped"] += 1
                if verbose:
                    print(f"  [{ticker}] 無可用資料，略過")
                continue

            if dry_run:
                stats["inserted"] += len(rows)
                if verbose:
                    print(f"  [{ticker}] {len(rows)} 筆 (dry-run)")
            else:
                n = upsert_rows(conn, rows)
                stats["inserted"] += n
                if verbose:
                    print(f"  [{ticker}] upsert {n} 筆")

        except Exception as exc:
            stats["errors"] += 1
            print(f"  [錯誤] {ticker}: {exc}")

    if conn:
        conn.close()

    print(
        f"\n完成！processed={stats['processed']}, "
        f"inserted={stats['inserted']}, "
        f"skipped={stats['skipped']}, "
        f"errors={stats['errors']}"
    )
    return stats


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="import_institutional_from_cache",
        description="從 FinMind ndjson cache 匯入法人資料至 institutional_investors 表（不呼叫 API）",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH,
                        help=f"SQLite DB 路徑（預設：{DEFAULT_DB_PATH}）")
    parser.add_argument("--tickers", nargs="*", metavar="TICKER",
                        help="只匯入指定 ticker；不填 = 全部 2494 檔")
    parser.add_argument("--dry-run", action="store_true",
                        help="只統計，不寫入 DB")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="每 ticker 輸出詳細訊息")

    args = parser.parse_args()

    import_all(
        db_path=args.db,
        tickers=args.tickers,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
