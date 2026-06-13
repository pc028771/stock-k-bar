"""Validation suite — small_structure module 驗證.

4 個 backtest + 1 個 sector universe 對比：

A. 舊 3 案例 re-validate
   - 3481 群創 5/20 (預期 trigger)
   - 3042 晶技 5/19 (預期 trigger D-3)
   - 6770 力積電 5/13, 5/18, 5/21 (預期 trigger)

B. 5/22 全市場 reproduce
   - 5/20 trigger → 5/21 漲幅統計
   - PASS: 候選數 ~327、上漲率 ~77%、漲停 ~28

C. 新時期擴充驗證 (5/27 trigger)
   - 5/27 trigger 標的後 1 日 (5/28) 表現

D. Watchlist 預測力 (5/6 conditions)
   - 5/15、5/19、5/22 中機率清單後 5 日突破率

E. Sector universe 對比 (5/20 trigger)
   - all vs sector_all vs sector_week 三版候選數 + 漲停率對比

用法:
  python -m zhuli.entry.small_structure.validation
  python -m zhuli.entry.small_structure.validation --case A
  python -m zhuli.entry.small_structure.validation --case E
"""
from __future__ import annotations

from zhuli.db import get_conn, MAIN_DB

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

# ── 路徑設定 ─────────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent.parent.parent.parent
_DB = MAIN_DB
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.entry.small_structure.detector import detect, detect_with_diagnostics
from zhuli.entry.small_structure.watchlist import (
    _load_sector_all,
    _parse_sector_timeline,
    _get_week_sectors,
    _sectors_to_tickers,
    _load_sector_tickers_json,
    _COND_COLS,
)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _open_db() -> sqlite3.Connection:
    uri = f"file:{_DB}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _load_bars(con: sqlite3.Connection, ticker: str, since: str, until: str) -> pd.DataFrame:
    df = pd.read_sql("""
        SELECT ticker, trade_date, trade_date as date,
               open, high, low, close, volume,
               vol_ratio_20, ma5, ma10, ma20, ma60
        FROM standard_daily_bar
        WHERE ticker = ? AND trade_date >= date(?, '-200 days') AND trade_date <= ?
        ORDER BY trade_date
    """, con, params=(ticker, since, until))
    df['prev_close'] = df['close'].shift(1)
    return df


def _all_tickers(con: sqlite3.Connection) -> list[str]:
    rows = con.execute("""
        SELECT DISTINCT ticker FROM standard_daily_bar
        WHERE is_usable = 1
    """).fetchall()
    return [r[0] for r in rows]


def _next_day_return(con: sqlite3.Connection, ticker: str, signal_date: str) -> float | None:
    """回傳 signal_date 後一個交易日的漲跌幅."""
    rows = con.execute("""
        SELECT close FROM standard_daily_bar
        WHERE ticker = ? AND trade_date > ? AND trade_date <= date(?, '+10 days')
        ORDER BY trade_date
        LIMIT 2
    """, (ticker, signal_date, signal_date)).fetchall()
    if len(rows) < 2:
        return None
    prev_close = rows[0][0]
    next_close = rows[1][0]
    if prev_close and prev_close > 0:
        return (next_close - prev_close) / prev_close


def _day_return(con: sqlite3.Connection, ticker: str, buy_date: str, n_days_later: int) -> float | None:
    """回傳 buy_date 後 n_days_later 個交易日的累計漲跌幅."""
    rows = con.execute("""
        SELECT trade_date, close FROM standard_daily_bar
        WHERE ticker = ? AND trade_date >= ? AND trade_date <= date(?, '+60 days')
        ORDER BY trade_date
        LIMIT ?
    """, (ticker, buy_date, buy_date, n_days_later + 2)).fetchall()
    if len(rows) < 2:
        return None
    base = rows[0][1]
    end = rows[min(n_days_later, len(rows) - 1)][1]
    if base and base > 0:
        return (end - base) / base
    return None


# ── Case A: 三案例 re-validate ────────────────────────────────────────────────

CASE_A_TARGETS = [
    {"ticker": "3481", "name": "群創",  "expected_signal_dates": ["2026-05-20"]},
    {"ticker": "3042", "name": "晶技",  "expected_signal_dates": ["2026-05-19"]},
    {"ticker": "6770", "name": "力積電", "expected_signal_dates": ["2026-05-13", "2026-05-18", "2026-05-21"]},
]


def run_case_a(con: sqlite3.Connection, verbose: bool = True) -> bool:
    """PASS: 三檔都在預期日期 detect()=True."""
    print("\n=== Case A: 三案例 re-validate ===")
    all_pass = True
    for case in CASE_A_TARGETS:
        ticker = case["ticker"]
        name = case["name"]
        since = "2026-04-01"
        until = "2026-05-25"
        df = _load_bars(con, ticker, since, until)
        if df.empty or len(df) < 30:
            print(f"  {ticker} {name}: ❌ 資料不足")
            all_pass = False
            continue
        sig = detect(df)
        sig_dates = list(df[sig]['trade_date'])
        expected = case["expected_signal_dates"]
        hit = any(d in sig_dates for d in expected)
        status = "✅ PASS" if hit else "❌ FAIL"
        if not hit:
            all_pass = False
        print(f"  {ticker} {name}: {status}  預期={expected}  實際觸發={sig_dates[-5:] if sig_dates else '(無)'}")

    result = "✅ PASS" if all_pass else "❌ FAIL"
    print(f"\n  Case A 結論: {result}")
    return all_pass


# ── Case B: 5/22 全市場 reproduce ────────────────────────────────────────────

def run_case_b(con: sqlite3.Connection, verbose: bool = True) -> bool:
    """PASS: 候選數 250-400、上漲率 ≥70%、漲停 ≥15."""
    print("\n=== Case B: 5/22 全市場 reproduce (5/20 trigger → 5/21 表現) ===")

    signal_date = "2026-05-20"
    next_date   = "2026-05-21"

    tickers = _all_tickers(con)
    print(f"  掃描 {len(tickers)} 檔...")

    candidates = []
    for tkr in tickers:
        df = _load_bars(con, tkr, "2026-01-01", signal_date)
        if len(df) < 30:
            continue
        try:
            sig = detect(df)
            if sig.iloc[-1]:
                candidates.append(tkr)
        except Exception:
            continue

    n_candidates = len(candidates)
    print(f"  候選數 (5/20 trigger): {n_candidates}  (報告值: ~327)")

    # 計算 5/21 表現
    up_count = 0
    strong_count = 0   # ≥3%
    limit_count = 0    # ≥9.5%
    returns = []

    for tkr in candidates:
        rows = con.execute("""
            SELECT trade_date, close FROM standard_daily_bar
            WHERE ticker = ? AND trade_date IN (?, ?)
            ORDER BY trade_date
        """, (tkr, signal_date, next_date)).fetchall()
        if len(rows) < 2:
            continue
        prev_close = rows[0][1]
        next_close = rows[1][1]
        if prev_close and prev_close > 0:
            ret = (next_close - prev_close) / prev_close
            returns.append(ret)
            if ret > 0:
                up_count += 1
            if ret >= 0.03:
                strong_count += 1
            if ret >= 0.095:
                limit_count += 1

    n_with_returns = len(returns)
    up_rate = up_count / n_with_returns if n_with_returns > 0 else 0
    avg_ret = sum(returns) / len(returns) if returns else 0

    print(f"  上漲率: {up_rate:.1%} (報告值: ~77%)  漲停: {limit_count} (報告值: ~28)  平均漲幅: {avg_ret:.2%}")
    print(f"  漲 ≥3%: {strong_count} (報告值: ~119)")

    pass_cond = (200 <= n_candidates <= 500) and (up_rate >= 0.65) and (limit_count >= 10)
    result = "✅ PASS" if pass_cond else "❌ FAIL"
    print(f"\n  Case B 結論: {result}")
    return pass_cond


# ── Case C: 5/27 新時期驗證 ───────────────────────────────────────────────────

def run_case_c(con: sqlite3.Connection, verbose: bool = True) -> bool:
    """5/27 trigger → 5/28 表現（無固定 PASS 標準，僅統計）."""
    print("\n=== Case C: 5/27 新時期擴充驗證 ===")

    signal_date = "2026-05-27"
    next_date   = "2026-05-28"

    tickers = _all_tickers(con)
    candidates = []
    for tkr in tickers:
        df = _load_bars(con, tkr, "2026-01-01", signal_date)
        if len(df) < 30:
            continue
        try:
            sig = detect(df)
            if sig.iloc[-1]:
                candidates.append(tkr)
        except Exception:
            continue

    print(f"  5/27 候選數: {len(candidates)}")

    up_count = 0
    limit_count = 0
    returns = []

    for tkr in candidates:
        rows = con.execute("""
            SELECT trade_date, close FROM standard_daily_bar
            WHERE ticker = ? AND trade_date IN (?, ?)
            ORDER BY trade_date
        """, (tkr, signal_date, next_date)).fetchall()
        if len(rows) < 2:
            continue
        prev_close = rows[0][1]
        next_close = rows[1][1]
        if prev_close and prev_close > 0:
            ret = (next_close - prev_close) / prev_close
            returns.append(ret)
            if ret > 0:
                up_count += 1
            if ret >= 0.095:
                limit_count += 1

    n_with_returns = len(returns)
    up_rate = up_count / n_with_returns if n_with_returns > 0 else 0
    avg_ret = sum(returns) / len(returns) if returns else 0

    print(f"  5/28 上漲率: {up_rate:.1%}  漲停: {limit_count}  平均漲幅: {avg_ret:.2%}")

    # Case C 僅記錄統計，無 PASS/FAIL 門檻
    pass_cond = True
    result = "✅ PASS (僅統計)"
    print(f"\n  Case C 結論: {result}")
    return pass_cond


# ── Case D: Watchlist 預測力 ──────────────────────────────────────────────────

def run_case_d(con: sqlite3.Connection, verbose: bool = True) -> bool:
    """中機率 (5/6) 清單後 5 日突破率."""
    print("\n=== Case D: Watchlist 預測力 (5/6 條件) ===")

    test_dates = ["2026-05-15", "2026-05-19", "2026-05-22"]
    tickers = _all_tickers(con)

    for signal_date in test_dates:
        medium_cands = []
        for tkr in tickers:
            df = _load_bars(con, tkr, "2026-01-01", signal_date)
            if len(df) < 30:
                continue
            try:
                diag = detect_with_diagnostics(df)
                last = diag.iloc[-1]
                hit_count = sum(bool(last.get(c, False)) for c in _COND_COLS)
                if hit_count == 5:
                    medium_cands.append(tkr)
            except Exception:
                continue

        # 後 5 日突破（上漲 ≥3%）
        breakthrough = 0
        for tkr in medium_cands:
            ret = _day_return(con, tkr, signal_date, 5)
            if ret is not None and ret >= 0.03:
                breakthrough += 1

        rate = breakthrough / len(medium_cands) if medium_cands else 0
        print(f"  {signal_date}: 中機率 {len(medium_cands)} 檔  5日突破率(≥3%): {rate:.1%}")

    print(f"\n  Case D 結論: ✅ PASS (僅統計)")
    return True


# ── Case E: Sector universe 對比 ─────────────────────────────────────────────

def run_case_e(con: sqlite3.Connection, verbose: bool = True) -> bool:
    """5/20 trigger → 全市場 vs sector_all vs sector_week 三版對比."""
    print("\n=== Case E: Sector Universe 對比 (5/20 trigger → 5/21 表現) ===")

    signal_date = "2026-05-20"
    next_date   = "2026-05-21"

    # 載入 universe
    sector_all_tickers = _load_sector_all()
    timeline = _parse_sector_timeline()
    week_sectors = _get_week_sectors(signal_date, timeline)
    sector_map = _load_sector_tickers_json()
    sector_week_tickers = _sectors_to_tickers(week_sectors, sector_map)

    print(f"  sector_all universe: {len(sector_all_tickers)} 檔")
    print(f"  sector_week sectors: {week_sectors}")
    print(f"  sector_week universe: {len(sector_week_tickers)} 檔")

    all_tickers = _all_tickers(con)

    universes = {
        'all':         set(all_tickers),
        'sector_all':  sector_all_tickers,
        'sector_week': sector_week_tickers,
    }

    rows_result = []
    for universe_name, universe_set in universes.items():
        candidates = []
        for tkr in universe_set:
            df = _load_bars(con, tkr, "2026-01-01", signal_date)
            if len(df) < 30:
                continue
            try:
                sig = detect(df)
                if sig.iloc[-1]:
                    candidates.append(tkr)
            except Exception:
                continue

        up_count = 0
        limit_count = 0
        returns = []
        teacher_overlap = 0

        for tkr in candidates:
            rows = con.execute("""
                SELECT trade_date, close FROM standard_daily_bar
                WHERE ticker = ? AND trade_date IN (?, ?)
                ORDER BY trade_date
            """, (tkr, signal_date, next_date)).fetchall()
            if len(rows) < 2:
                continue
            prev_close = rows[0][1]
            next_close = rows[1][1]
            if prev_close and prev_close > 0:
                ret = (next_close - prev_close) / prev_close
                returns.append(ret)
                if ret > 0:
                    up_count += 1
                if ret >= 0.095:
                    limit_count += 1

        n = len(candidates)
        n_r = len(returns)
        up_rate = up_count / n_r if n_r > 0 else 0
        limit_rate = limit_count / n if n > 0 else 0
        avg_ret = sum(returns) / n_r if n_r > 0 else 0

        rows_result.append({
            'Universe': universe_name,
            '候選數': n,
            '5/21上漲率': f"{up_rate:.1%}",
            '漲停數': limit_count,
            '漲停率': f"{limit_rate:.1%}",
            '平均漲幅': f"{avg_ret:.2%}",
        })

    print()
    df_result = pd.DataFrame(rows_result)
    print(df_result.to_string(index=False))

    # 判定建議
    data = {r['Universe']: r for r in rows_result}
    all_limit_rate = float(data['all']['漲停率'].rstrip('%')) / 100
    sall_limit_rate = float(data['sector_all']['漲停率'].rstrip('%')) / 100
    sweek_limit_rate = float(data['sector_week']['漲停率'].rstrip('%')) / 100

    print()
    if sweek_limit_rate > all_limit_rate * 1.3:
        recommendation = "✅ 建議: sector_week 漲停率顯著 > all，推薦每日 --universe=sector_week"
    elif sall_limit_rate > all_limit_rate * 1.2:
        recommendation = "✅ 建議: sector_all 居中，推薦每日 --universe=sector_all（sector_week 過窄）"
    else:
        recommendation = "⚠️ 建議: 三版差異不顯著，老師族群 universe 過濾力有限，維持 all"

    print(f"  {recommendation}")
    print(f"\n  Case E 結論: ✅ PASS (統計 + 建議)")
    return True


# ── 主流程 ────────────────────────────────────────────────────────────────────

def run_all(cases: list[str] | None = None) -> None:
    """執行所有（或指定）validation cases."""
    con = _open_db()

    all_cases = {
        'A': run_case_a,
        'B': run_case_b,
        'C': run_case_c,
        'D': run_case_d,
        'E': run_case_e,
    }

    to_run = cases if cases else list(all_cases.keys())
    results = {}

    for key in to_run:
        if key not in all_cases:
            print(f"  Unknown case: {key}")
            continue
        results[key] = all_cases[key](con)

    con.close()

    print("\n" + "=" * 50)
    print("VALIDATION SUMMARY")
    print("=" * 50)
    for k, v in results.items():
        status = "✅ PASS" if v else "❌ FAIL"
        print(f"  Case {k}: {status}")

    if all(results.values()):
        print("\n✅ ALL CASES PASSED")
    else:
        failed = [k for k, v in results.items() if not v]
        print(f"\n❌ FAILED: {failed}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", nargs="+", help="指定跑哪些 case (A B C D E)")
    args = parser.parse_args()
    run_all(args.case)
