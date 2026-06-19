"""stock-k-bar 自管的 market data client 套件。

從 stock-analysis-system/clients/ vendor 過來、只保留 stock-k-bar 真實用到的
API surface。設計目標：
  - Fubon Securities (fubon_neo SDK) — realtime / kbar / snapshot / WS subscription
  - FinMind v4 API — 透過 scripts/common/finmind_client.py 的 quota-aware client

Symbol 入口:
    from common.clients.fubon_client import FubonClient
    from common.clients.finmind_compat import (
        FinMindClient,        # class wrapper
        get_data, get_price,  # module-level helper
        fetch_kbar, fetch_stock_info, get_institutional,
    )
    from common.clients.base import SnapshotDict
"""
from common.clients.base import SnapshotDict  # noqa: F401
