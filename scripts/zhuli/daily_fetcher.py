"""每日盤後 broker cache 預熱 — 17:00 launchd 觸發.

職責：
  1. 讀當日 scanner 候選清單 /tmp/scanner_candidates_<date>.md
  2. 解析 ticker（table 第一欄 4 位數字）
  3. 對每個 ticker 呼叫 _fetch_broker_daily → 寫 disk cache
  4. 讓隔日 daily_scanner_job 跑 broker_warnings 時直接 hit cache、不用 rate-limit 等

Usage:
  python scripts/zhuli/daily_fetcher.py [--date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

# ── Path setup (抄 daily_scanner_job.py 慣例) ──────────────────────────────
_REPO = Path(__file__).parent.parent.parent
_SYS = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_REPO), str(_REPO / "scripts"), str(_SYS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.chip_broker import _fetch_broker_daily  # noqa: E402

# ── Constants ──────────────────────────────────────────────────────────────
_CACHE_DIR = Path.home() / ".zhuli_cache" / "broker"
_TICKER_RE = re.compile(r"^\|?\s*(\d{4})\b")   # table row 第一欄


def _parse_tickers(md_path: Path) -> list[str]:
    """從 scanner candidates markdown 抽出不重複 ticker 清單."""
    tickers: set[str] = set()
    for line in md_path.read_text(encoding="utf-8").splitlines():
        m = _TICKER_RE.match(line)
        if m:
            tickers.add(m.group(1))
    return sorted(tickers)


def main() -> None:
    parser = argparse.ArgumentParser(description="盤後 broker cache 預熱")
    parser.add_argument(
        "--date", default=date.today().isoformat(),
        help="目標日期 YYYY-MM-DD（default: 今天）"
    )
    args = parser.parse_args()
    target_date: str = args.date

    # ── 1. 讀 scanner candidates ───────────────────────────────────────────
    md_path = Path(f"/tmp/scanner_candidates_{target_date}.md")
    if not md_path.exists():
        raise FileNotFoundError(
            f"Scanner candidates 不存在：{md_path}\n"
            "請先執行 daily_scanner_job.py 再跑 daily_fetcher.py。"
        )

    tickers = _parse_tickers(md_path)
    print(f"[daily_fetcher] date={target_date}  candidates={len(tickers)}  "
          f"tickers={tickers}")

    if not tickers:
        print("[daily_fetcher] 找不到任何 ticker，結束。")
        return

    # ── 2. 對每個 ticker fetch broker daily ───────────────────────────────
    ok_count = 0
    empty_count = 0
    err_count = 0

    for i, ticker in enumerate(tickers, 1):
        cache_file = _CACHE_DIR / f"{ticker}_{target_date}.json"
        if cache_file.exists():
            print(f"  [{i:>2}/{len(tickers)}] {ticker}  skip (already cached)")
            ok_count += 1
            continue

        try:
            df = _fetch_broker_daily(ticker, target_date)
            if df.empty:
                print(f"  [{i:>2}/{len(tickers)}] {ticker}  empty (no data)")
                empty_count += 1
            else:
                print(f"  [{i:>2}/{len(tickers)}] {ticker}  ok  rows={len(df)}")
                ok_count += 1
        except Exception as exc:  # ConnectionError / RuntimeError / etc.
            print(f"  [{i:>2}/{len(tickers)}] {ticker}  ERR  {exc}")
            err_count += 1

    # ── 3. 統計 ───────────────────────────────────────────────────────────
    print(
        f"\n[daily_fetcher] done — ok={ok_count}  empty={empty_count}  err={err_count}"
    )

    # cache dir 當天總檔數
    day_files = list(_CACHE_DIR.glob(f"*_{target_date}.json"))
    print(f"[daily_fetcher] cache dir files for {target_date}: {len(day_files)}")


if __name__ == "__main__":
    main()
