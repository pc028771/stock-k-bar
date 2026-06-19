"""PoC — write to Turso from one conn, read from a separate replica path
(simulates two machines via two independent embedded replicas).
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.common.db import get_conn


def main() -> int:
    # Machine A — default replica path
    print("→ [machine-A] connect + insert sentinel row")
    a = get_conn()
    sentinel = f"POC_SYNC_TEST_{int(time.time())}"
    a.execute(
        "INSERT INTO trade_history (ticker, name, trade_date, trade_type, shares, price) "
        "VALUES (?, ?, DATE('now'), 'POC', 1, 0.0)",
        ("0000", sentinel),
    )
    a.commit()
    print(f"  inserted sentinel name={sentinel}")

    # force push to cloud
    a.sync()
    print("  pushed to cloud")

    # Machine B — different replica file (fresh download from cloud)
    with tempfile.TemporaryDirectory() as tmp:
        replica_b = os.path.join(tmp, "replica_b.db")
        print(f"\n→ [machine-B] connect to fresh replica at {replica_b}")
        b = get_conn(local_replica_path=replica_b)

        cur = b.execute(
            "SELECT name, trade_date FROM trade_history WHERE name = ?",
            (sentinel,),
        )
        row = cur.fetchone()
        if row:
            print(f"  ✅ machine-B sees sentinel: {row}")
        else:
            print("  ❌ machine-B did NOT see sentinel — sync failed")
            return 1

    # Clean up sentinel
    print("\n→ cleanup sentinel from machine-A")
    a.execute("DELETE FROM trade_history WHERE name = ?", (sentinel,))
    a.commit()
    a.sync()
    print("  done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
