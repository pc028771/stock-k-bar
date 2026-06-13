"""統一 SQLite 存取通道（spec v1.7、2026-06-13）。

設計原則：
1. 唯一 DB 路徑常數：MAIN_DB（symlink → ~/four_seasons_local/data.sqlite）
2. 預設 readonly=True — 讀取路徑不必 opt-in、**寫入路徑必須明確 readonly=False**
   防的就是 office 機誤寫 iCloud snapshot 引發 SQLite 鎖檔
3. 接受 db_path override — backtest worker / CLI --db 旗標仍可用
4. timeout 預設 10s
5. 統一 stale-cache 失效 key：latest_trade_date()（用 DB file mtime 當 cache key）
   + assert_fresh()（fail-fast 護欄）防的就是 6/11 4939 假燈 / 6/12 office 6/8 殭屍

呼叫範例：
    from zhuli.db import get_conn, MAIN_DB, latest_trade_date, write_tx

    # 讀（最常見）
    with get_conn() as con:
        rows = con.execute("SELECT ... FROM standard_daily_bar").fetchall()

    # 讀 + 指定其他 DB（backtest worker）
    with get_conn(worker_db_path) as con: ...

    # 寫（必須 explicit、含 commit/rollback/close + lock retry）
    with write_tx() as con:
        con.execute("INSERT ...")

    # cache 失效 key（DB mtime 變了會自動失效）
    if data_version != latest_trade_date():
        cache.clear()

    # 進場前護欄（office 機 / fetcher 沒跑會在這擋下）
    assert_fresh(today)

注意：`get_conn()` 回傳的 `sqlite3.Connection` 在 `with` 區塊離開時會 commit /
rollback、但 **不會 close**（sqlite3 模組設計）。長 running 程序（monitor）應該
重用同一個 connection 而不是每次新開；或用 `contextlib.closing(get_conn())`
明確 close。
"""
from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

MAIN_DB: Path = Path.home() / ".four_seasons" / "data.sqlite"

DBLockError = sqlite3.OperationalError  # 給上游 except 用、未來換 driver 不必動


def get_conn(
    db_path: Path | str | None = None,
    *,
    readonly: bool = True,
    timeout: float = 10.0,
) -> sqlite3.Connection:
    """統一 SQLite 連線入口。

    Args:
        db_path: 不傳 = MAIN_DB；傳入時用於 backtest worker / CLI --db override
        readonly: True (預設) = `?mode=ro` URI；寫入必須明確設 False
        timeout: 鎖定等待秒數

    Returns:
        sqlite3.Connection。`with` 區塊離開時 commit/rollback 但 **不 close**。
    """
    path = Path(db_path) if db_path else MAIN_DB
    if readonly:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=timeout)
    return sqlite3.connect(str(path), timeout=timeout)


@contextmanager
def write_tx(
    db_path: Path | str | None = None,
    *,
    timeout: float = 30.0,
    retries: int = 3,
    retry_sleep: float = 1.0,
) -> Iterator[sqlite3.Connection]:
    """寫入 transaction：自動 commit/rollback/close + 鎖定重試。

    寫入 path 用這個、不用裸 `get_conn(readonly=False)` 才不會漏 close、
    遇到「database is locked」也會自動 retry。
    """
    last_err: Exception | None = None
    for attempt in range(retries):
        conn = get_conn(db_path, readonly=False, timeout=timeout)
        try:
            yield conn
            conn.commit()
            return
        except DBLockError as e:
            conn.rollback()
            last_err = e
            if "locked" not in str(e).lower() or attempt == retries - 1:
                raise
            time.sleep(retry_sleep)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    assert last_err is not None
    raise last_err


# ─── stale-cache 失效機制（用 DB file mtime 當 cache key、比 TTL 精準）─────
_mtime_cache: dict[str, tuple[float, str]] = {}


def latest_trade_date(db_path: Path | str | None = None) -> str:
    """`SELECT MAX(trade_date) FROM standard_daily_bar`、用 DB file mtime 當 cache key。

    DB 補新日後 mtime 變、cache 自動失效；monitor / scanner 不必自己管 TTL。
    """
    path = Path(db_path).resolve() if db_path else MAIN_DB.resolve()
    key = str(path)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return ""
    cached_mtime, value = _mtime_cache.get(key, (0.0, ""))
    if value and cached_mtime == mtime:
        return value
    try:
        with get_conn(db_path) as con:
            r = con.execute("SELECT MAX(trade_date) FROM standard_daily_bar").fetchone()
            value = str(r[0]) if r and r[0] else ""
    except sqlite3.Error:
        value = ""
    _mtime_cache[key] = (mtime, value)
    return value


def invalidate_latest_trade_date(db_path: Path | str | None = None) -> None:
    """手動清掉 latest_trade_date cache（給 monitor 切日時用）。"""
    key = str(Path(db_path).resolve() if db_path else MAIN_DB.resolve())
    _mtime_cache.pop(key, None)


def assert_fresh(target_date: str, db_path: Path | str | None = None) -> None:
    """DB 最新日 ≥ target_date、否則 raise RuntimeError。

    fail-fast 護欄：office 機 / stale snapshot / fetcher 沒跑 都會在這擋下。
    """
    latest = latest_trade_date(db_path)
    if not latest or latest < target_date:
        raise RuntimeError(
            f"DB 資料過期: 最新 {latest!r} < 要求 {target_date!r}。"
            " 請先跑 scripts/zhuli/sync_missing_daily_bars.py 補資料。"
        )


__all__ = [
    "MAIN_DB",
    "DBLockError",
    "get_conn",
    "write_tx",
    "latest_trade_date",
    "invalidate_latest_trade_date",
    "assert_fresh",
]
