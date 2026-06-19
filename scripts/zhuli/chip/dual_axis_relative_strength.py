"""雙軸籌碼相對強勢 — 大盤跌日守均線、外資中買、投信沒大賣。

User 拍板門檻 (2026-06-04):
  - TAIEX 當日 ≤ -1% (close vs 前一交易日 close)
  - 外資 5d net ≥ +3,000 張
  - 投信 5d net ≥ -500 張  (寬容、只擋大賣)
  - close > MA5 OR > MA10 OR > MA20 (守均線、任一即可)

注意: DB institutional_investors 已是張 (FinMind shares 匯入時已 /1000)、不需再除。

來源: memory/feedback_dual_axis_relative_strength.md
"""
from __future__ import annotations

from zhuli.db import get_conn, MAIN_DB

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

_common_parent = Path(__file__).parent.parent.parent  # scripts/
if str(_common_parent) not in sys.path:
    sys.path.insert(0, str(_common_parent))
from common.clients.finmind_client import get_client

DB = MAIN_DB
_REPO = Path(__file__).parent.parent.parent.parent  # stock-k-bar root

FOREIGN_5D_MIN: float = 3000.0   # 張
SITC_5D_MIN: float = -500.0      # 張 (寬容)
TAIEX_DROP_THRESHOLD: float = -1.0  # %


@dataclass
class Signal:
    ticker: str
    date: str
    close: float
    foreign_5d: float
    sitc_5d: float
    above_ma5: bool
    above_ma10: bool
    above_ma20: bool
    taiex_pct: float
    name: str = ""

    @property
    def ma_label(self) -> str:
        parts = []
        if self.above_ma5:
            parts.append(">MA5 ✓")
        else:
            parts.append(">MA5 ✗")
        if self.above_ma10:
            parts.append(">MA10 ✓")
        else:
            parts.append(">MA10 ✗")
        if self.above_ma20:
            parts.append(">MA20 ✓")
        else:
            parts.append(">MA20 ✗")
        return " ".join(parts)


def _get_taiex_pct(con: sqlite3.Connection, date: str) -> float | None:
    """取 TAIEX 當日收盤漲跌幅 (vs 前一交易日 close)。
    先查 DB，若 DB 無資料則 fallback 到 FinMind API。
    """
    # Layer 1: DB
    row = con.execute(
        "SELECT close FROM standard_daily_bar WHERE ticker='TAIEX' AND trade_date=?",
        (date,),
    ).fetchone()
    prev = con.execute(
        "SELECT close FROM standard_daily_bar "
        "WHERE ticker='TAIEX' AND trade_date<? ORDER BY trade_date DESC LIMIT 1",
        (date,),
    ).fetchone()

    if row and prev:
        return (row[0] / prev[0] - 1) * 100

    # Layer 2: FinMind API (DB 沒有最新資料時)
    try:
        df = get_client().fetch_dataset(
            dataset="TaiwanStockPrice",
            data_id="TAIEX",
            start_date=_prev_month(date),
            end_date=date,
            bypass_cache=True,
        )
        rows = df.to_dict("records") if not df.empty else []
        if len(rows) < 2:
            return None
        rows.sort(key=lambda x: x["date"])
        # find the row for `date` and the one before it
        for i, row in enumerate(rows):
            if row["date"] == date and i > 0:
                prev_close = rows[i - 1]["close"]
                curr_close = row["close"]
                return (curr_close / prev_close - 1) * 100
        return None
    except Exception:
        return None


def _prev_month(date: str) -> str:
    """YYYY-MM-DD → 前 30 天."""
    from datetime import datetime, timedelta
    d = datetime.strptime(date, "%Y-%m-%d")
    return (d - timedelta(days=30)).strftime("%Y-%m-%d")


def _get_stock_data(
    con: sqlite3.Connection,
    tickers: list[str],
    date: str,
) -> dict[str, dict]:
    """取 standard_daily_bar 當日 close/MA。"""
    if not tickers:
        return {}
    ph = ",".join("?" * len(tickers))
    rows = con.execute(
        f"SELECT ticker, close, ma5, ma10, ma20 FROM standard_daily_bar "
        f"WHERE ticker IN ({ph}) AND trade_date=?",
        tickers + [date],
    ).fetchall()
    return {r[0]: {"close": r[1], "ma5": r[2], "ma10": r[3], "ma20": r[4]} for r in rows}


def _get_chip_5d(
    con: sqlite3.Connection,
    tickers: list[str],
    date: str,
) -> dict[str, dict]:
    """取 institutional_investors 近 5 個交易日累計 (含當日往前 7 日曆日以捕捉週末)。
    DB 單位已是張、不再 /1000。
    """
    if not tickers:
        return {}
    ph = ",".join("?" * len(tickers))
    rows = con.execute(
        f"""SELECT ticker, SUM(foreign_net) AS f5d, SUM(sitc_net) AS s5d
            FROM institutional_investors
            WHERE ticker IN ({ph})
              AND trade_date >= date(?, '-7 days')
              AND trade_date <= ?
            GROUP BY ticker""",
        tickers + [date, date],
    ).fetchall()
    return {
        r[0]: {"foreign_5d": float(r[1] or 0), "sitc_5d": float(r[2] or 0)}
        for r in rows
    }


def _load_universe(db: Path) -> list[str]:
    """從 teacher_picks_2026.json 載入 universe。"""
    p = _REPO / "docs" / "主力大課程" / "teacher_picks_2026.json"
    if not p.exists():
        return []
    raw = json.loads(p.read_text())
    return [k for k in raw.keys() if k != "_meta"]


def _load_names(db: Path) -> dict[str, str]:
    """從 stock_info / stock_name 取名稱。"""
    try:
        con = get_conn(db, timeout=10)
        rows = con.execute("SELECT ticker, name FROM stock_info").fetchall()
        con.close()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}


def detect(
    date: str,
    universe: list[str] | None = None,
    db: Path = DB,
) -> list[Signal]:
    """偵測指定日的相對強勢標的。

    Args:
        date: 目標收盤日 YYYY-MM-DD
        universe: 待掃描 ticker 清單；None = teacher_picks_2026 全部
        db: SQLite DB 路徑

    Returns:
        命中 🛡️ 相對強勢的 Signal 清單
    """
    if universe is None:
        universe = _load_universe(db)

    names = _load_names(db)
    con = get_conn(db, timeout=15)

    try:
        taiex_pct = _get_taiex_pct(con, date)
    finally:
        con.close()

    if taiex_pct is None:
        return []

    # 大盤未跌 -1%，不觸發
    if taiex_pct > TAIEX_DROP_THRESHOLD:
        return []

    con = get_conn(db, timeout=15)
    try:
        stock_data = _get_stock_data(con, universe, date)
        chip_data = _get_chip_5d(con, universe, date)
    finally:
        con.close()

    signals: list[Signal] = []
    for ticker in universe:
        sd = stock_data.get(ticker)
        cd = chip_data.get(ticker)
        if not sd or not cd:
            continue

        close = sd["close"]
        ma5 = sd.get("ma5")
        ma10 = sd.get("ma10")
        ma20 = sd.get("ma20")
        foreign_5d = cd["foreign_5d"]
        sitc_5d = cd["sitc_5d"]

        # 條件 1: 外資 5d net ≥ +3,000 張
        if foreign_5d < FOREIGN_5D_MIN:
            continue

        # 條件 2: 投信 5d net ≥ -500 張
        if sitc_5d < SITC_5D_MIN:
            continue

        # 條件 3: 守均線 (close > MA5 OR MA10 OR MA20)
        above_ma5 = bool(ma5 and close > ma5)
        above_ma10 = bool(ma10 and close > ma10)
        above_ma20 = bool(ma20 and close > ma20)
        if not (above_ma5 or above_ma10 or above_ma20):
            continue

        signals.append(Signal(
            ticker=ticker,
            date=date,
            close=close,
            foreign_5d=foreign_5d,
            sitc_5d=sitc_5d,
            above_ma5=above_ma5,
            above_ma10=above_ma10,
            above_ma20=above_ma20,
            taiex_pct=taiex_pct,
            name=names.get(ticker, ""),
        ))

    return signals


def backtest(
    start: str,
    end: str,
    universe: list[str] | None = None,
    db: Path = DB,
    extra_tickers: list[str] | None = None,
) -> dict:
    """跑 start~end 期間每個 TAIEX -1% 日的偵測結果。

    Args:
        start: 開始日 YYYY-MM-DD
        end:   結束日 YYYY-MM-DD
        universe: 基礎 ticker 清單；None = teacher_picks_2026
        db: SQLite DB 路徑
        extra_tickers: 額外要追蹤的 ticker (會加入 universe)

    Returns:
        {
          "taiex_drop_days": [...],
          "results": {date: [Signal, ...]},
          "hit_counts": {ticker: int},
          "total_signals": int,
        }
    """
    if universe is None:
        universe = _load_universe(db)
    if extra_tickers:
        universe = list(set(universe) | set(extra_tickers))

    # 取 TAIEX 全期資料計算漲跌幅
    con = get_conn(db, timeout=15)
    taiex_rows = con.execute(
        "SELECT trade_date, close FROM standard_daily_bar "
        "WHERE ticker='TAIEX' AND trade_date >= date(?, '-7 days') AND trade_date <= ? "
        "ORDER BY trade_date",
        (start, end),
    ).fetchall()
    con.close()

    # 取 FinMind API 補 DB 沒有的最新資料
    taiex_map: dict[str, float] = {}
    for r in taiex_rows:
        taiex_map[r[0]] = r[1]

    # 如果 DB 缺 end 之後的資料，嘗試 API 補
    db_max = max(taiex_map.keys()) if taiex_map else "1970-01-01"
    if db_max < end:
        try:
            df = get_client().fetch_dataset(
                dataset="TaiwanStockPrice",
                data_id="TAIEX",
                start_date=_prev_month(start) if start > _prev_month(start) else start,
                end_date=end,
                bypass_cache=True,
            )
            api_data = df.to_dict("records") if not df.empty else []
            for row in api_data:
                taiex_map[row["date"]] = row["close"]
        except Exception as e:
            print(f"  [TAIEX API fallback] 失敗: {e}")

    # 計算每日漲跌幅
    sorted_dates = sorted(taiex_map.keys())
    taiex_pct_map: dict[str, float] = {}
    for i, d in enumerate(sorted_dates):
        if i == 0:
            continue
        prev_c = taiex_map[sorted_dates[i - 1]]
        curr_c = taiex_map[d]
        if prev_c > 0:
            taiex_pct_map[d] = (curr_c / prev_c - 1) * 100

    # 找 start~end 內 TAIEX <= -1% 的日期
    taiex_drop_days = [
        d for d, pct in taiex_pct_map.items()
        if start <= d <= end and pct <= TAIEX_DROP_THRESHOLD
    ]
    taiex_drop_days.sort()

    results: dict[str, list[Signal]] = {}
    hit_counts: dict[str, int] = {}

    for date in taiex_drop_days:
        taiex_pct = taiex_pct_map[date]
        con = get_conn(db, timeout=15)
        try:
            stock_data = _get_stock_data(con, universe, date)
            chip_data = _get_chip_5d(con, universe, date)
        finally:
            con.close()

        names = _load_names(db)
        day_signals: list[Signal] = []

        for ticker in universe:
            sd = stock_data.get(ticker)
            cd = chip_data.get(ticker)
            if not sd or not cd:
                continue

            close = sd["close"]
            ma5 = sd.get("ma5")
            ma10 = sd.get("ma10")
            ma20 = sd.get("ma20")
            foreign_5d = cd["foreign_5d"]
            sitc_5d = cd["sitc_5d"]

            if foreign_5d < FOREIGN_5D_MIN:
                continue
            if sitc_5d < SITC_5D_MIN:
                continue

            above_ma5 = bool(ma5 and close > ma5)
            above_ma10 = bool(ma10 and close > ma10)
            above_ma20 = bool(ma20 and close > ma20)
            if not (above_ma5 or above_ma10 or above_ma20):
                continue

            sig = Signal(
                ticker=ticker,
                date=date,
                close=close,
                foreign_5d=foreign_5d,
                sitc_5d=sitc_5d,
                above_ma5=above_ma5,
                above_ma10=above_ma10,
                above_ma20=above_ma20,
                taiex_pct=taiex_pct,
                name=names.get(ticker, ""),
            )
            day_signals.append(sig)
            hit_counts[ticker] = hit_counts.get(ticker, 0) + 1

        results[date] = day_signals

    total = sum(len(v) for v in results.values())
    return {
        "taiex_drop_days": taiex_drop_days,
        "results": results,
        "hit_counts": hit_counts,
        "total_signals": total,
    }


def _print_backtest(result: dict, extra_tickers: list[str] | None = None) -> None:
    """格式化輸出 backtest 結果。"""
    drop_days = result["taiex_drop_days"]
    print(f"\n{'='*60}")
    print(f"大盤跌日 (TAIEX ≤ -1%) 共 {len(drop_days)} 天: {drop_days}")
    print(f"{'='*60}\n")

    for date in drop_days:
        hits = result["results"].get(date, [])
        if not hits:
            pct = 0.0  # can't easily get here but fine
            first = hits[0].taiex_pct if hits else 0
        else:
            first = hits[0].taiex_pct
        # get taiex_pct from first signal or fallback
        taiex_pct_display = hits[0].taiex_pct if hits else "N/A"
        print(f"{date} TAIEX {taiex_pct_display:+.2f}% (大盤跌觸發)")
        if hits:
            for sig in sorted(hits, key=lambda x: -x.foreign_5d):
                name_str = f" {sig.name}" if sig.name else ""
                print(
                    f"  🛡️ {sig.ticker}{name_str}  "
                    f"close={sig.close} ({sig.ma_label})  "
                    f"外資5d {sig.foreign_5d:+,.0f}  投信5d {sig.sitc_5d:+,.0f}"
                )
        else:
            print("  (無命中)")
        print()

    # 命中次數統計
    hit_counts = result["hit_counts"]
    if hit_counts:
        print(f"\n--- 命中次數排行 (共 {result['total_signals']} 次訊號) ---")
        for ticker, cnt in sorted(hit_counts.items(), key=lambda x: -x[1])[:20]:
            print(f"  {ticker}: {cnt} 次")

    # 如果有 extra_tickers，獨立統計
    if extra_tickers:
        print(f"\n--- Validation Group 個別命中 ({len(extra_tickers)} 檔) ---")
        for t in extra_tickers:
            cnt = hit_counts.get(t, 0)
            print(f"  {t}: {cnt}/{len(drop_days)} 大盤跌日命中")


def main() -> None:
    ap = argparse.ArgumentParser(description="雙軸籌碼相對強勢 Backtest")
    ap.add_argument("--start", default="2026-05-01")
    ap.add_argument("--end", default="2026-06-03")
    ap.add_argument("--db", default=str(DB))
    ap.add_argument(
        "--tickers",
        nargs="*",
        help="指定 ticker (不指定則用 teacher_picks_2026 全部)",
    )
    args = ap.parse_args()

    db_path = Path(args.db)

    # Validation group
    validation_group = ["6282", "2449", "4967", "6147", "3211", "6209"]

    universe = args.tickers if args.tickers else None

    print(f"Backtest {args.start} ~ {args.end}")
    print(f"Universe: {'指定 ' + str(len(args.tickers)) + ' 檔' if args.tickers else 'teacher_picks_2026 全部 + validation group'}")
    print(f"Validation group: {validation_group}")
    print(f"門檻: TAIEX ≤ {TAIEX_DROP_THRESHOLD}% | 外資5d ≥ {FOREIGN_5D_MIN:,.0f}張 | "
          f"投信5d ≥ {SITC_5D_MIN:,.0f}張 | close > MA5/MA10/MA20 任一")

    result = backtest(
        start=args.start,
        end=args.end,
        universe=universe,
        db=db_path,
        extra_tickers=validation_group,
    )
    _print_backtest(result, extra_tickers=validation_group)


if __name__ == "__main__":
    main()
