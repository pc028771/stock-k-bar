"""每日盤後 broker cache 預熱 — evening_fetch 21:30 觸發.

職責：
  1. 載入老師 universe (~428 檔、teacher_sector_tickers.json)
  2. 對每個 ticker 呼叫 _fetch_broker_daily → 寫 disk cache
  3. 隔日 scanner / 當日 scanner 都直接 hit cache

設計改變 (vs 舊版)：
  - 舊：讀 /tmp/scanner_candidates_<date>.md（循環依賴、scanner 不跑就無 tickers）
  - 新：讀老師 universe（固定清單、不依賴 scanner）

Usage:
  python scripts/zhuli/daily_fetcher.py [--date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

_REPO = Path(__file__).parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.chip_broker import _fetch_broker_daily  # noqa: E402
from zhuli.entry.small_structure.watchlist import _load_sector_all  # noqa: E402

_CACHE_DIR = Path.home() / ".zhuli_cache" / "broker"


def main() -> None:
    parser = argparse.ArgumentParser(description="盤後 broker cache 預熱 (老師 universe)")
    parser.add_argument("--date", default=date.today().isoformat(),
                        help="目標日期 YYYY-MM-DD（default: 今天）")
    parser.add_argument("--sleep", type=float, default=0.3,
                        help="每筆間隔秒數 (rate-limit、default 0.3)")
    args = parser.parse_args()
    target_date: str = args.date

    tickers = sorted(_load_sector_all())
    print(f"[daily_fetcher] date={target_date}  universe={len(tickers)} 檔")
    if not tickers:
        print("[daily_fetcher] universe 為空、結束。")
        return

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    ok = empty = err = skip = 0
    for i, ticker in enumerate(tickers, 1):
        cache_file = _CACHE_DIR / f"{ticker}_{target_date}.json"
        if cache_file.exists():
            skip += 1
            continue
        try:
            df = _fetch_broker_daily(ticker, target_date)
            if df.empty:
                empty += 1
            else:
                ok += 1
        except Exception as exc:
            print(f"  [{i:>3}/{len(tickers)}] {ticker}  ERR  {exc}")
            err += 1
        time.sleep(args.sleep)
        if i % 50 == 0:
            print(f"  [{i:>3}/{len(tickers)}] 進度 ok={ok} empty={empty} err={err} skip={skip}")

    day_files = list(_CACHE_DIR.glob(f"*_{target_date}.json"))
    print(f"\n[daily_fetcher] done — ok={ok} empty={empty} err={err} skip={skip}")
    print(f"[daily_fetcher] cache files for {target_date}: {len(day_files)}")


if __name__ == "__main__":
    main()
