"""
標準 workflow backtest (2026-05-01 ~ 2026-06-04)

Entry:  每日 scanner Top 3 (priority desc, dist_ma10 asc) 隔日開盤買
Exit:   收盤 < MA10 → 隔日開盤賣 (僅 MA10 出場，不處理 structural_low — 太複雜)
Sizing: 1/3 水位 / stock = $1,066,666

Usage:
  python scripts/zhuli/tools/backtest_standard_workflow.py [--db PATH] [--cache-dir DIR]
  python scripts/zhuli/tools/backtest_standard_workflow.py --cached-only   # 讀現有快取不重跑 scanner

快取:
  每日 scanner 結果存 /tmp/bt_scanner_cache/<DATE>.json
  避免重複跑 68s × 24 days
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path
from datetime import date

import pandas as pd

# ── Path setup ───────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent.parent.parent
_SYS = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_REPO), str(_REPO / "scripts"), str(_SYS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.daily_scanner_job import run_scanners  # noqa

_DB_DEFAULT = Path.home() / ".four_seasons" / "data.sqlite"
_CACHE_DIR_DEFAULT = Path("/tmp/bt_scanner_cache")
_START_DATE = "2026-05-01"
_END_DATE   = "2026-06-04"
_SIZING     = 1_066_666   # per position

# ── Trading calendar ─────────────────────────────────────────────────────────

def get_trading_dates(db_path: Path, start: str, end: str) -> list[str]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT DISTINCT trade_date FROM standard_daily_bar "
        "WHERE trade_date >= ? AND trade_date <= ? ORDER BY trade_date",
        (start, end),
    ).fetchall()
    con.close()
    return [r[0] for r in rows]


def next_trading_date(trading_dates: list[str], current: str) -> str | None:
    """回傳 current 之後的下一個交易日."""
    try:
        idx = trading_dates.index(current)
        return trading_dates[idx + 1] if idx + 1 < len(trading_dates) else None
    except ValueError:
        return None


# ── Scanner runner with cache ─────────────────────────────────────────────────

def _scanner_cache_path(cache_dir: Path, d: str) -> Path:
    return cache_dir / f"{d}.json"


def load_or_run_scanner(
    d: str,
    db_path: Path,
    cache_dir: Path,
    force: bool = False,
) -> list[dict]:
    """回傳 hit list (只含進場相關 scanners: w_bottom_launch + small_structure，排除加碼用 shakeout)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = _scanner_cache_path(cache_dir, d)

    if not force and cache_file.exists():
        data = json.loads(cache_file.read_text())
        return data

    print(f"  Running scanner for {d}...", flush=True)
    try:
        results = run_scanners(d, db_path)
    except Exception as e:
        print(f"  ⚠️  scanner {d} 失敗: {e}")
        cache_file.write_text("[]")
        return []

    hits: list[dict] = []
    for scanner_name, scanner_hits in results.items():
        # 只保留進場用 scanner、排除 shakeout_strong (加碼用) 和 DataFrame 型結果
        if scanner_name in (
            "post_attack_watchlist", "uniform_ma_above",
            "shakeout_strong",       # 加碼用、不做首次進場
        ):
            continue
        if not isinstance(scanner_hits, list):
            continue
        for h in scanner_hits:
            h2 = dict(h)
            h2["scanner_name"] = scanner_name
            hits.append(h2)

    # Deduplicate by ticker (同一 ticker 多 scanner 命中、取最高 priority)
    dedup: dict[str, dict] = {}
    for h in hits:
        t = h["ticker"]
        if t not in dedup or _priority(h) > _priority(dedup[t]):
            dedup[t] = h
    hits = list(dedup.values())

    cache_file.write_text(json.dumps(hits, ensure_ascii=False, default=str))
    return hits


def _priority(h: dict) -> int:
    """Tier → priority number (P3=3 最高, P2=2, P1=1)."""
    tier = h.get("tier", "一般")
    if "🔥" in tier:  # Tier-A
        return 3
    if "⭐" in tier:  # Tier-B
        return 2
    # institutional_firstbuy / institutional_swing 也算 P2
    scanner = h.get("scanner_name", "")
    if scanner in ("institutional_firstbuy", "institutional_swing"):
        return 2
    return 1


def pick_top3(hits: list[dict]) -> list[dict]:
    """選 Top 3: 嚴格 P3 only、tie-break 距 MA10 升冪.

    Strict P3 = 5/1-6/4 backtest C1 最佳組合 (vs baseline 用 P3+P2 噪音多)
    P3 < 3 檔 → 少開 / 不開、不 fallback 到 P2.
    """
    p3 = [h for h in hits if _priority(h) >= 3]

    def dist_key(h):
        d = h.get("dist_ma10_pct")
        return d if d is not None else 999.0

    return sorted(p3, key=dist_key)[:3]


# ── Price lookup ──────────────────────────────────────────────────────────────

def get_price(db_path: Path, ticker: str, trade_date: str) -> dict | None:
    """回傳 {open, high, low, close, ma10} for ticker on trade_date."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    row = con.execute(
        "SELECT open, high, low, close, ma10 FROM standard_daily_bar "
        "WHERE ticker=? AND trade_date=?",
        (ticker, trade_date),
    ).fetchone()
    con.close()
    if not row:
        return None
    return {"open": row[0], "high": row[1], "low": row[2], "close": row[3], "ma10": row[4]}


# ── Backtest engine ───────────────────────────────────────────────────────────

class Position:
    def __init__(self, ticker: str, name: str, entry_date: str, entry_price: float, shares: int):
        self.ticker = ticker
        self.name = name
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.shares = shares
        self.signal_date: str | None = None  # 觸發出場訊號的日期


def run_backtest(
    db_path: Path,
    cache_dir: Path,
    cached_only: bool = False,
) -> dict:
    trading_dates = get_trading_dates(db_path, _START_DATE, _END_DATE)
    print(f"Trading dates: {len(trading_dates)} ({trading_dates[0]} ~ {trading_dates[-1]})")

    positions: list[Position] = []   # 最多 3 個
    all_trades: list[dict] = []
    pending_sells: list[tuple[str, Position]] = []  # (sell_date, position)

    # 逐日執行
    for i, d in enumerate(trading_dates):
        print(f"\n--- {d} ---", flush=True)

        # ① 今日開盤：執行昨日觸發的賣出
        sells_today = [(sd, pos) for sd, pos in pending_sells if sd == d]
        for _, pos in sells_today:
            price_info = get_price(db_path, pos.ticker, d)
            if price_info and price_info["open"]:
                sell_price = price_info["open"]
            else:
                # 找不到開盤價、用前一日收盤 (fallback)
                prev_d = trading_dates[i - 1] if i > 0 else d
                p2 = get_price(db_path, pos.ticker, prev_d)
                sell_price = p2["close"] if p2 else pos.entry_price

            pnl_pct = (sell_price - pos.entry_price) / pos.entry_price * 100
            pnl_dollar = (sell_price - pos.entry_price) * pos.shares
            hold_days = _count_hold_days(trading_dates, pos.entry_date, d)

            trade = {
                "entry_date": pos.entry_date,
                "exit_date": d,
                "ticker": pos.ticker,
                "name": pos.name,
                "entry_price": round(pos.entry_price, 2),
                "exit_price": round(sell_price, 2),
                "shares": pos.shares,
                "hold_days": hold_days,
                "pnl_pct": round(pnl_pct, 2),
                "pnl_dollar": round(pnl_dollar),
                "exit_reason": "MA10跌破",
                "signal_date": pos.signal_date,
            }
            all_trades.append(trade)
            print(f"  賣出 {pos.ticker} @ {sell_price:.2f} P&L={pnl_dollar:+,.0f} ({pnl_pct:+.2f}%)")

        # 移除已售出的倉位
        sold_tickers = {pos.ticker for _, pos in sells_today}
        positions = [p for p in positions if p.ticker not in sold_tickers]
        pending_sells = [(sd, pos) for sd, pos in pending_sells if sd != d]

        # ② 盤後：跑 scanner 選 Top 3、若有空倉則進場 (隔日 D+1 開盤)
        current_tickers = {p.ticker for p in positions}
        available_slots = 3 - len(positions)

        if available_slots > 0:
            hits = load_or_run_scanner(d, db_path, cache_dir, force=not cached_only if not cached_only else False)
            top3 = pick_top3(hits)

            # 排除已持有 ticker
            top3 = [h for h in top3 if h["ticker"] not in current_tickers]

            # 只補足空倉數量
            new_entries = top3[:available_slots]

            next_d = next_trading_date(trading_dates, d)
            if next_d:
                for h in new_entries:
                    t = h["ticker"]
                    price_info = get_price(db_path, t, next_d)
                    if not price_info or not price_info["open"]:
                        print(f"  ⚠️  {t} 在 {next_d} 無開盤價、跳過")
                        continue
                    entry_price = price_info["open"]
                    shares = math.floor(_SIZING / entry_price)
                    if shares <= 0:
                        continue
                    pos = Position(
                        ticker=t,
                        name=h.get("name", ""),
                        entry_date=next_d,
                        entry_price=entry_price,
                        shares=shares,
                    )
                    positions.append(pos)
                    print(f"  新倉 {t} ({pos.name}) @ {entry_price:.2f} × {shares} 股 (進場 {next_d})")
        else:
            print(f"  倉位滿 ({len(positions)}/3)、跳過 scanner")

        # ③ 收盤：檢查持倉是否 close < MA10 → 觸發出場訊號 (隔日開盤賣)
        next_d = next_trading_date(trading_dates, d)
        for pos in positions:
            if pos.signal_date:
                continue  # 已有信號、等待執行
            price_info = get_price(db_path, pos.ticker, d)
            if not price_info:
                continue
            close = price_info["close"]
            ma10 = price_info["ma10"]
            if ma10 and close < ma10:
                pos.signal_date = d
                if next_d:
                    pending_sells.append((next_d, pos))
                    print(f"  觸發出場 {pos.ticker} 收盤 {close:.2f} < MA10 {ma10:.2f} → 隔日 {next_d} 賣")

    # ④ 結算：尚未出場的持倉用最後一日收盤價計算浮動損益
    last_d = trading_dates[-1]
    for pos in positions:
        price_info = get_price(db_path, pos.ticker, last_d)
        if price_info and price_info["close"]:
            close = price_info["close"]
        else:
            close = pos.entry_price
        pnl_pct = (close - pos.entry_price) / pos.entry_price * 100
        pnl_dollar = (close - pos.entry_price) * pos.shares
        hold_days = _count_hold_days(trading_dates, pos.entry_date, last_d)
        all_trades.append({
            "entry_date": pos.entry_date,
            "exit_date": f"{last_d}(持倉中)",
            "ticker": pos.ticker,
            "name": pos.name,
            "entry_price": round(pos.entry_price, 2),
            "exit_price": round(close, 2),
            "shares": pos.shares,
            "hold_days": hold_days,
            "pnl_pct": round(pnl_pct, 2),
            "pnl_dollar": round(pnl_dollar),
            "exit_reason": "持倉中",
            "signal_date": None,
        })
        print(f"  持倉中 {pos.ticker} @ {pos.entry_price:.2f} → {close:.2f} P&L={pnl_dollar:+,.0f}")

    return {"trades": all_trades, "trading_dates": trading_dates}


def _count_hold_days(trading_dates: list[str], entry: str, exit_: str) -> int:
    try:
        i = trading_dates.index(entry)
        j = trading_dates.index(exit_) if exit_ in trading_dates else len(trading_dates) - 1
        return j - i
    except ValueError:
        return 0


# ── Report generator ──────────────────────────────────────────────────────────

def generate_report(result: dict) -> str:
    trades = result["trades"]
    if not trades:
        return "# 無交易紀錄"

    total = len(trades)
    closed = [t for t in trades if t["exit_reason"] != "持倉中"]
    open_pos = [t for t in trades if t["exit_reason"] == "持倉中"]
    winners = [t for t in closed if t["pnl_dollar"] > 0]
    win_rate = len(winners) / len(closed) * 100 if closed else 0
    total_pnl = sum(t["pnl_dollar"] for t in trades)
    avg_pnl_pct = sum(t["pnl_pct"] for t in closed) / len(closed) if closed else 0
    avg_pnl_dollar = sum(t["pnl_dollar"] for t in closed) / len(closed) if closed else 0
    initial_capital = 3_200_000
    final_capital = initial_capital + total_pnl
    total_return_pct = total_pnl / initial_capital * 100

    # Sort by pnl_dollar
    trades_sorted_asc = sorted(trades, key=lambda t: t["pnl_dollar"])
    trades_sorted_desc = sorted(trades, key=lambda t: t["pnl_dollar"], reverse=True)

    lines = []
    lines.append("# 標準 workflow backtest (2026-05-01 ~ 2026-06-04)")
    lines.append("")
    lines.append("## 設定")
    lines.append(f"- Entry: Top 3 per day (priority desc, dist_ma10 asc)、隔日開盤進")
    lines.append(f"- Exit: 收盤 < MA10 → 隔日開盤出 (MA10 出場；結構底出場略過 — 實作複雜度高)")
    lines.append(f"- Sizing: 1/3 水位 / stock (${_SIZING:,})")
    lines.append(f"- 初始資金: ${initial_capital:,}")
    lines.append(f"- 最大持倉: 3 檔同時")
    lines.append("")
    lines.append("## 摘要")
    lines.append(f"- 總交易筆數: {total} 筆 (已出場 {len(closed)} + 持倉中 {len(open_pos)})")
    lines.append(f"- 勝率 (已出場): {win_rate:.1f}% ({len(winners)}/{len(closed)})")
    lines.append(f"- 平均 / 筆報酬 (已出場): {avg_pnl_pct:+.2f}% / ${avg_pnl_dollar:+,.0f}")
    lines.append(f"- 累計 P&L: ${total_pnl:+,.0f}")
    lines.append(f"- 最終水位: ${final_capital:,.0f} ({total_return_pct:+.2f}%)")
    lines.append("")

    lines.append("## Top 5 Winners")
    lines.append("| entry_date | exit_date | ticker | name | entry | exit | days | P&L % | P&L $ |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for t in trades_sorted_desc[:5]:
        lines.append(
            f"| {t['entry_date']} | {t['exit_date']} | {t['ticker']} | {t['name']} "
            f"| {t['entry_price']:.2f} | {t['exit_price']:.2f} "
            f"| {t['hold_days']} | {t['pnl_pct']:+.2f}% | ${t['pnl_dollar']:+,.0f} |"
        )
    lines.append("")

    lines.append("## Top 5 Losers")
    lines.append("| entry_date | exit_date | ticker | name | entry | exit | days | P&L % | P&L $ |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for t in trades_sorted_asc[:5]:
        lines.append(
            f"| {t['entry_date']} | {t['exit_date']} | {t['ticker']} | {t['name']} "
            f"| {t['entry_price']:.2f} | {t['exit_price']:.2f} "
            f"| {t['hold_days']} | {t['pnl_pct']:+.2f}% | ${t['pnl_dollar']:+,.0f} |"
        )
    lines.append("")

    lines.append("## 逐日 trades")
    lines.append("| entry_date | exit_date | ticker | name | entry | exit | days | P&L % | P&L $ | exit_reason |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    trades_chrono = sorted(trades, key=lambda t: t["entry_date"])
    for t in trades_chrono:
        lines.append(
            f"| {t['entry_date']} | {t['exit_date']} | {t['ticker']} | {t['name']} "
            f"| {t['entry_price']:.2f} | {t['exit_price']:.2f} "
            f"| {t['hold_days']} | {t['pnl_pct']:+.2f}% | ${t['pnl_dollar']:+,.0f} "
            f"| {t['exit_reason']} |"
        )
    lines.append("")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="標準 workflow backtest")
    parser.add_argument("--db", type=Path, default=_DB_DEFAULT)
    parser.add_argument("--cache-dir", type=Path, default=_CACHE_DIR_DEFAULT)
    parser.add_argument("--cached-only", action="store_true",
                        help="只讀現有快取、不重跑 scanner (快取不存在的日期會空白)")
    parser.add_argument("--output", type=Path,
                        default=_REPO / "docs" / "主力大課程" / "backtest_production_workflow_2026-05-01_to_2026-06-04.md")
    args = parser.parse_args()

    result = run_backtest(args.db, args.cache_dir, cached_only=args.cached_only)
    report = generate_report(result)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"\n✅ Report written to: {args.output}")
    print("\n" + "=" * 60)
    print(report[:2000])


if __name__ == "__main__":
    main()
