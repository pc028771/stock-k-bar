"""Compute main_force_{1,5,10,20}d from FinMind NDJSON cache and write to standard_daily_bar.

Uses the exact fsi formula (four_seasons_investment/indicators/chip.py):
  daily_net = sum over 5 INSTITUTIONAL_INVESTOR_NAMES of (buy - sell)
  main_force_Nd = rolling sum of last N trading-day daily_net values up to as_of_date

Only updates rows where main_force_{N}d IS NULL — never overwrites existing values.

This is NOT inline imputation: NDJSON is genuine API raw data, and the formula
replicates fsi's authoritative compute_main_force exactly.
"""
import json
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

DB = "/Users/howard/.four_seasons/data.sqlite"
NDJSON_DIR = Path("/Users/howard/Repository/stock-k-bar/.claude/worktrees/four-seasons-redesign/data/raw/TaiwanStockInstitutionalInvestorsBuySell")

# Exact 5 names from fsi chip.py — 'Dealer' (合計) deliberately excluded to avoid double-count
INVESTOR_NAMES = {
    "Foreign_Investor",
    "Investment_Trust",
    "Dealer_self",
    "Dealer_Hedging",
    "Foreign_Dealer_Self",
}
WINDOWS = (1, 5, 10, 20)


def load_daily_nets(ticker: str) -> dict[str, float]:
    """Return {trade_date_10ch: daily_net_shares} aggregated across the 5 investor types."""
    daily_net: dict[str, float] = defaultdict(float)
    tdir = NDJSON_DIR / ticker
    if not tdir.is_dir():
        return {}
    for ndjson_path in sorted(tdir.glob("*.ndjson")):
        with ndjson_path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                name = row.get("name")
                if name not in INVESTOR_NAMES:
                    continue
                d = row.get("date", "")[:10]
                if not d:
                    continue
                buy = row.get("buy") or 0
                sell = row.get("sell") or 0
                try:
                    daily_net[d] += float(buy) - float(sell)
                except (TypeError, ValueError):
                    continue
    return dict(daily_net)


def compute_rolling(daily_nets: dict[str, float], as_of: str) -> dict[str, float | None]:
    """Compute main_force_Nd for as_of from trading-day rolling sum."""
    ordered = sorted(d for d in daily_nets if d <= as_of)
    nets = [daily_nets[d] for d in ordered]
    out: dict[str, float | None] = {}
    for w in WINDOWS:
        out[f"main_force_{w}d"] = sum(nets[-w:]) if len(nets) >= w else None
    return out


def main() -> None:
    t0 = time.time()
    with sqlite3.connect(DB, timeout=60) as conn:
        tickers = [r[0] for r in conn.execute(
            "select distinct ticker from standard_daily_bar where is_usable=1 order by ticker"
        )]
    print(f"[start] tickers={len(tickers)}", flush=True)

    def with_retry(fn, *args, retries=8, base_sleep=2.0):
        """Retry on database is locked. iCloud sync can hold the file briefly."""
        for attempt in range(retries):
            try:
                return fn(*args)
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < retries - 1:
                    sleep_s = base_sleep * (2 ** attempt)
                    print(f"  [retry {attempt+1}/{retries}] DB locked, sleep {sleep_s:.0f}s",
                          flush=True)
                    time.sleep(sleep_s)
                    continue
                raise

    total_updated = 0
    processed = 0
    for tkr in tickers:
        processed += 1
        daily_nets = load_daily_nets(tkr)
        if not daily_nets:
            continue

        def do_ticker():
            nonlocal total_updated
            with sqlite3.connect(DB, timeout=60) as conn:
                cur = conn.cursor()
                rows = cur.execute(
                    """select trade_date, main_force_1d, main_force_5d, main_force_10d, main_force_20d
                       from standard_daily_bar
                       where ticker=? and is_usable=1
                         and (main_force_1d is null or main_force_5d is null
                              or main_force_10d is null or main_force_20d is null)""",
                    (tkr,),
                ).fetchall()
                if not rows:
                    return 0
                cur.execute("begin immediate")
                local = 0
                for trade_date, mf1, mf5, mf10, mf20 in rows:
                    d_str = str(trade_date)[:10]
                    vals = compute_rolling(daily_nets, d_str)
                    sets, params = [], []
                    cur_vals = {"main_force_1d": mf1, "main_force_5d": mf5,
                                "main_force_10d": mf10, "main_force_20d": mf20}
                    for fld in ("main_force_1d", "main_force_5d", "main_force_10d", "main_force_20d"):
                        if cur_vals[fld] is None and vals[fld] is not None:
                            sets.append(f"{fld}=?")
                            params.append(vals[fld])
                    if not sets:
                        continue
                    params.extend([tkr, trade_date])
                    cur.execute(
                        f"update standard_daily_bar set {', '.join(sets)} where ticker=? and trade_date=?",
                        params,
                    )
                    local += 1
                conn.commit()
                return local

        try:
            updated = with_retry(do_ticker)
            total_updated += updated
        except sqlite3.OperationalError as e:
            print(f"  [skip] {tkr} after retries exhausted: {e}", flush=True)
            continue

        if processed % 100 == 0:
            elapsed = time.time() - t0
            print(f"[{processed:4d}/{len(tickers)}] {tkr} updated_rows={total_updated:,} "
                  f"({elapsed:.0f}s)", flush=True)

    elapsed = time.time() - t0
    print(f"\n[done] updated {total_updated:,} rows in {elapsed:.0f}s", flush=True)


if __name__ == "__main__":
    main()
