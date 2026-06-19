"""Tiered DB connector — Turso (cloud) for state, local SQLite for bulk K-line data.

# Tiered architecture

Tables live in two places:

  Cloud (Turso)  →  cross-device shared state, small/medium tables
  Local SQLite   →  bulk price/volume data, rebuilt from APIs anyway

`LOCAL_ONLY_TABLES` is the source of truth for "stays local."

# API

    from scripts.common.db import get_conn

    conn = get_conn()                # → Turso embedded replica (default)
    conn_local = get_conn("local")   # → local data.sqlite
    conn_for(table)                  # → routes by table name

# Env vars (loaded from .env if present)

    TURSO_DATABASE_URL  libsql://...turso.io  (if unset → all queries go local)
    TURSO_AUTH_TOKEN    JWT for above
    LOCAL_DB_PATH       override local SQLite path
                        default: ~/.four_seasons/data.sqlite
    TURSO_MODE          "replica" (default) | "cloud"
                        replica = local file mirror + background sync (fast reads)
                        cloud   = direct HTTP every query (slower, no local cache)
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# Tables that MUST stay on local SQLite (too big for free Turso tier,
# or rebuilt frequently from APIs so cross-device sync is wasted).
LOCAL_ONLY_TABLES: frozenset[str] = frozenset({
    "standard_daily_bar",
    "institutional_investors",
    "stock_shareholding",
})


def _local_path() -> str:
    return os.getenv("LOCAL_DB_PATH", str(Path.home() / ".four_seasons/data.sqlite"))


class _CtxConn:
    """Wrap libsql Connection so `with get_conn() as c:` works like sqlite3."""

    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            try:
                self._conn.commit()
            except Exception:
                pass
        return False

    def __getattr__(self, item):
        return getattr(self._conn, item)


def _get_local_conn():
    import sqlite3
    return sqlite3.connect(_local_path(), timeout=15)


def _get_cloud_conn(local_replica_path: str | None = None, sync_interval: float = 60.0):
    url = os.getenv("TURSO_DATABASE_URL")
    token = os.getenv("TURSO_AUTH_TOKEN")
    mode = os.getenv("TURSO_MODE", "replica").lower()

    if not url:
        return _get_local_conn()

    import libsql_experimental as libsql

    if mode == "cloud":
        return _CtxConn(libsql.connect(database=url, auth_token=token))

    replica = local_replica_path or str(
        Path.home() / ".four_seasons" / "turso_replica.db"
    )
    raw = libsql.connect(
        replica,
        sync_url=url,
        auth_token=token,
        sync_interval=sync_interval,
    )
    raw.sync()
    return _CtxConn(raw)


def get_conn(target: str = "cloud", **kw):
    """Get a DB connection.

        target="cloud" (default) → Turso (or local fallback if env unset)
        target="local"           → always local SQLite
    """
    if target == "local":
        return _get_local_conn()
    return _get_cloud_conn(**kw)


def conn_for(table: str, **kw):
    """Route by table name — bulk tables go local, everything else cloud."""
    if table in LOCAL_ONLY_TABLES:
        return _get_local_conn()
    return _get_cloud_conn(**kw)
