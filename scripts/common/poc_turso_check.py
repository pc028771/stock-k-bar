"""PoC — verify Turso connection and read broker_statement / trade_history."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.common.db import get_conn


def main() -> int:
    print("→ connecting (embedded replica mode)...")
    t0 = time.time()
    conn = get_conn()
    print(f"  connected in {time.time()-t0:.2f}s")

    for tbl in ("broker_statement", "trade_history"):
        cur = conn.execute(f"SELECT COUNT(*) FROM {tbl}")
        (n,) = cur.fetchone()
        print(f"  {tbl}: {n} rows")

    print("\n→ broker_statement last 5 trades:")
    cur = conn.execute(
        "SELECT trade_date, stock_name, ticker, action, shares, price "
        "FROM broker_statement ORDER BY trade_date DESC, id DESC LIMIT 5"
    )
    for row in cur.fetchall():
        print(f"  {row}")

    print("\n→ trade_history schema:")
    cur = conn.execute("PRAGMA table_info(trade_history)")
    for col in cur.fetchall():
        print(f"  {col}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
