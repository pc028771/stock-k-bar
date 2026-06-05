"""
標準 workflow backtest (2026-05-01 ~ 2026-06-04)

Entry:  每日 scanner Top 3 (priority desc, dist_ma10 asc) 隔日開盤買
Exit:
  --mode C1 (baseline): 收盤 < MA10 → 隔日開盤賣
  --mode C5 (A+C):      MA10 容忍+量縮例外 (rule A) + sizing-based partial exit (rule C)

Sizing: 1/3 水位 / stock = $1,066,666

Usage:
  python scripts/zhuli/tools/backtest_standard_workflow.py [--db PATH] [--cache-dir DIR]
  python scripts/zhuli/tools/backtest_standard_workflow.py --cached-only   # 讀現有快取不重跑 scanner
  python scripts/zhuli/tools/backtest_standard_workflow.py --mode C5       # C5 出場機制

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
    """回傳 {open, high, low, close, ma10, vol_ratio_20} for ticker on trade_date."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    row = con.execute(
        "SELECT open, high, low, close, ma10, vol_ratio_20 FROM standard_daily_bar "
        "WHERE ticker=? AND trade_date=?",
        (ticker, trade_date),
    ).fetchone()
    con.close()
    if not row:
        return None
    return {
        "open": row[0], "high": row[1], "low": row[2], "close": row[3],
        "ma10": row[4], "vol_ratio_20": row[5],
    }


# ── Exit rules ────────────────────────────────────────────────────────────────

def should_exit_ma10_tolerant(
    close: float,
    ma10: float,
    vol_ratio: float,
    days_below: int,
) -> bool:
    """Rule A: MA10 容忍 + 量縮例外.

    - close >= MA10                            → 不出
    - close < MA10 by < 2% AND 量縮 (vol<1.0) → 觀察、不出
    - close < MA10 by < 2% AND 放量 (vol>=1.0) → 出場
    - close < MA10 by >= 2% (深破)             → 出場
    - 容忍區連 2 天 (days_below >= 2)           → 出場 (避免無限抱)
    """
    dist_pct = (close - ma10) / ma10 * 100  # negative if below
    if dist_pct >= 0:
        return False
    if dist_pct <= -2.0:
        return True   # 深破
    # 容忍區 (-2% ~ 0%)
    if vol_ratio >= 1.0:
        return True   # 放量小破
    if days_below >= 2:
        return True   # 容忍連 2 天
    return False      # 量縮第一天、觀察


def is_odd_lot_eligible(ticker: str, db_path: Path) -> bool:
    """twse/tpex 可零股交易; emerging (興櫃) 只能整張."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    row = con.execute("SELECT type FROM stock_info WHERE ticker=?", (ticker,)).fetchone()
    con.close()
    if not row:
        return True  # 查不到預設可零股
    return row[0] in ("twse", "tpex")


def calc_exit_action(
    ticker: str,
    position_shares: int,
    position_water_pct: float,
    db_path: Path,
) -> tuple[str, int]:
    """Rule C: Sizing-based partial exit (含零股可執行性).

    Returns:
        ('partial', sell_shares)  — 部分出場
        ('full', position_shares) — 全出
        ('forced_full', position_shares) — 興櫃不可零股、強制全出
    """
    if position_water_pct > 15.0:
        target_pct = 13.0
        sell_fraction = (position_water_pct - target_pct) / position_water_pct
        sell_shares_target = int(position_shares * sell_fraction)

        if is_odd_lot_eligible(ticker, db_path):
            # TWSE/TPEx: 精準 trim (零股可執行)
            if sell_shares_target <= 0:
                return "full", position_shares
            if sell_shares_target >= position_shares:
                return "full", position_shares
            return "partial", sell_shares_target
        else:
            # 興櫃: 只能整張 (1000 股/張)
            sell_lots = round(sell_shares_target / 1000)
            sell_shares = sell_lots * 1000
            if sell_shares <= 0:
                return "forced_full", position_shares
            if sell_shares >= position_shares:
                return "forced_full", position_shares
            return "partial", sell_shares

    return "full", position_shares


# ── Backtest engine ───────────────────────────────────────────────────────────

class Position:
    def __init__(self, ticker: str, name: str, entry_date: str, entry_price: float, shares: int):
        self.ticker = ticker
        self.name = name
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.shares = shares
        self.signal_date: str | None = None  # 觸發出場訊號的日期 (C1 用)
        # C5 專用
        self.days_below_ma10: int = 0        # 連續收盤 < MA10 天數 (容忍計數)
        self.partial_trimmed: bool = False   # 是否已 partial trim


def run_backtest(
    db_path: Path,
    cache_dir: Path,
    cached_only: bool = False,
    mode: str = "C1",
) -> dict:
    """mode: 'C1' = baseline MA10 出場; 'C5' = A+C 出場."""
    trading_dates = get_trading_dates(db_path, _START_DATE, _END_DATE)
    print(f"Trading dates: {len(trading_dates)} ({trading_dates[0]} ~ {trading_dates[-1]})")
    print(f"Mode: {mode}")

    positions: list[Position] = []   # 最多 3 個
    all_trades: list[dict] = []
    pending_sells: list[tuple[str, Position, int, str]] = []
    # pending_sells item: (sell_date, pos, sell_shares, exit_type)
    # exit_type: 'full' | 'partial' | 'forced_full'

    _TOTAL_CAPITAL = 3_200_000

    # 逐日執行
    for i, d in enumerate(trading_dates):
        print(f"\n--- {d} ---", flush=True)

        # ① 今日開盤：執行昨日觸發的賣出
        sells_today = [(sd, pos, ss, et) for sd, pos, ss, et in pending_sells if sd == d]
        for _, pos, sell_shares, exit_type in sells_today:
            price_info = get_price(db_path, pos.ticker, d)
            if price_info and price_info["open"]:
                sell_price = price_info["open"]
            else:
                prev_d = trading_dates[i - 1] if i > 0 else d
                p2 = get_price(db_path, pos.ticker, prev_d)
                sell_price = p2["close"] if p2 else pos.entry_price

            pnl_pct = (sell_price - pos.entry_price) / pos.entry_price * 100
            pnl_dollar = (sell_price - pos.entry_price) * sell_shares
            hold_days = _count_hold_days(trading_dates, pos.entry_date, d)

            exit_label = {
                "full": "MA10跌破",
                "partial": "C5-partial_trim",
                "forced_full": "C5-興櫃強制全出",
            }.get(exit_type, "MA10跌破")

            trade = {
                "entry_date": pos.entry_date,
                "exit_date": d,
                "ticker": pos.ticker,
                "name": pos.name,
                "entry_price": round(pos.entry_price, 2),
                "exit_price": round(sell_price, 2),
                "shares": sell_shares,
                "hold_days": hold_days,
                "pnl_pct": round(pnl_pct, 2),
                "pnl_dollar": round(pnl_dollar),
                "exit_reason": exit_label,
                "signal_date": pos.signal_date,
            }
            all_trades.append(trade)
            print(f"  賣出 {pos.ticker} {exit_type} @ {sell_price:.2f} P&L={pnl_dollar:+,.0f} ({pnl_pct:+.2f}%)")

            # 若是 partial，更新剩餘持股；若 full/forced_full，標記完全出場
            if exit_type == "partial":
                pos.shares -= sell_shares
                pos.signal_date = None   # 清除信號、繼續持有
                pos.days_below_ma10 = 0  # 重置計數
                pos.partial_trimmed = True
                print(f"    剩餘 {pos.ticker} {pos.shares} 股 (partial trim 完成)")
            else:
                pos.shares = 0  # 標記已全出

        # 移除已全出的倉位 (shares == 0)
        full_sold_tickers = {pos.ticker for _, pos, _, et in sells_today if et != "partial"}
        positions = [p for p in positions if p.ticker not in full_sold_tickers]
        pending_sells = [(sd, pos, ss, et) for sd, pos, ss, et in pending_sells if sd != d]

        # ② 盤後：跑 scanner 選 Top 3、若有空倉則進場 (隔日 D+1 開盤)
        current_tickers = {p.ticker for p in positions}
        available_slots = 3 - len(positions)

        if available_slots > 0:
            hits = load_or_run_scanner(d, db_path, cache_dir, force=not cached_only if not cached_only else False)
            top3 = pick_top3(hits)

            top3 = [h for h in top3 if h["ticker"] not in current_tickers]
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

        # ③ 收盤：檢查持倉出場訊號
        next_d = next_trading_date(trading_dates, d)

        for pos in positions:
            # 已有 full-exit 信號排隊中、跳過
            already_queued_full = any(
                pos.ticker == p.ticker and et != "partial"
                for _, p, _, et in pending_sells
            )
            if already_queued_full:
                continue

            price_info = get_price(db_path, pos.ticker, d)
            if not price_info:
                continue
            close = price_info["close"]
            ma10 = price_info["ma10"]
            vol_ratio = price_info.get("vol_ratio_20") or 1.0

            if not ma10:
                continue

            if mode == "C1":
                # baseline: close < MA10 → 隔日出
                if close < ma10:
                    pos.signal_date = d
                    if next_d:
                        pending_sells.append((next_d, pos, pos.shares, "full"))
                        print(f"  [C1] 觸發出場 {pos.ticker} 收盤 {close:.2f} < MA10 {ma10:.2f} → {next_d}")

            elif mode == "C5":
                # Rule A: MA10 容忍 + 量縮例外
                if close >= ma10:
                    pos.days_below_ma10 = 0  # 站回 MA10 重置
                    continue

                # 進入 MA10 以下邏輯
                pos.days_below_ma10 += 1
                days_below = pos.days_below_ma10

                trigger_exit = should_exit_ma10_tolerant(
                    close=close, ma10=ma10,
                    vol_ratio=vol_ratio, days_below=days_below,
                )
                dist_pct = (close - ma10) / ma10 * 100
                print(f"    [C5-A] {pos.ticker} 收{close:.2f} MA10{ma10:.2f} dist{dist_pct:+.1f}% "
                      f"vol_ratio{vol_ratio:.2f} days_below={days_below} trigger={trigger_exit}")

                if trigger_exit:
                    # Rule C: sizing-based partial vs full
                    position_value = close * pos.shares
                    position_water_pct = position_value / _TOTAL_CAPITAL * 100
                    exit_type, sell_shares = calc_exit_action(
                        ticker=pos.ticker,
                        position_shares=pos.shares,
                        position_water_pct=position_water_pct,
                        db_path=db_path,
                    )
                    pos.signal_date = d
                    if next_d:
                        pending_sells.append((next_d, pos, sell_shares, exit_type))
                        print(f"  [C5] 觸發出場 {pos.ticker} dist{dist_pct:+.1f}% vol{vol_ratio:.2f} "
                              f"days_below={days_below} water={position_water_pct:.1f}% "
                              f"→ {exit_type} {sell_shares}股 → {next_d}")

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

    return {"trades": all_trades, "trading_dates": trading_dates, "mode": mode}


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
    mode = result.get("mode", "C1")
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

    # C5 partial exit stats
    partial_exits = [t for t in closed if t["exit_reason"] == "C5-partial_trim"]
    full_exits = [t for t in closed if t["exit_reason"] == "MA10跌破"]
    forced_full_exits = [t for t in closed if t["exit_reason"] == "C5-興櫃強制全出"]

    # Sort by pnl_dollar
    trades_sorted_asc = sorted(trades, key=lambda t: t["pnl_dollar"])
    trades_sorted_desc = sorted(trades, key=lambda t: t["pnl_dollar"], reverse=True)

    exit_desc = {
        "C1": "收盤 < MA10 → 隔日開盤出",
        "C5": "Rule A: MA10 容忍+量縮例外 + Rule C: sizing-based partial exit",
    }.get(mode, mode)

    lines = []
    lines.append(f"# 標準 workflow backtest [{mode}] (2026-05-01 ~ 2026-06-04)")
    lines.append("")
    lines.append("## 設定")
    lines.append(f"- Mode: {mode}")
    lines.append(f"- Entry: Top 3 per day (priority desc, dist_ma10 asc)、隔日開盤進")
    lines.append(f"- Exit: {exit_desc}")
    if mode == "C5":
        lines.append(f"  - Rule A: 容忍區 < 2% + 量縮 → 觀察；連 2 天或放量或深破 >= 2% → 出")
        lines.append(f"  - Rule C: 倉位水位 > 15% → trim 到 13%；否則全出")
        lines.append(f"  - 零股可執行性: TWSE/TPEx 精準 trim；興櫃整張 or 強制全出")
    lines.append(f"- Sizing: 1/3 水位 / stock (${_SIZING:,})")
    lines.append(f"- 總資金: $3,200,000 (水位計算基準)")
    lines.append(f"- 最大持倉: 3 檔同時")
    lines.append("")
    lines.append("## 摘要")
    lines.append(f"- 總交易筆數: {total} 筆 (已出場 {len(closed)} + 持倉中 {len(open_pos)})")
    lines.append(f"- 勝率 (已出場): {win_rate:.1f}% ({len(winners)}/{len(closed)})")
    lines.append(f"- 平均 / 筆報酬 (已出場): {avg_pnl_pct:+.2f}% / ${avg_pnl_dollar:+,.0f}")
    lines.append(f"- 累計 P&L: ${total_pnl:+,.0f}")
    lines.append(f"- 最終水位: ${final_capital:,.0f} ({total_return_pct:+.2f}%)")
    if mode == "C5":
        lines.append("")
        lines.append("### C5 出場分類")
        lines.append(f"- full 全出 (MA10跌破): {len(full_exits)} 筆")
        lines.append(f"- partial trim (水位>15%): {len(partial_exits)} 筆")
        lines.append(f"- forced_full (興櫃整張): {len(forced_full_exits)} 筆")
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
    lines.append("| entry_date | exit_date | ticker | name | entry | exit | shares | days | P&L % | P&L $ | exit_reason |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    trades_chrono = sorted(trades, key=lambda t: t["entry_date"])
    for t in trades_chrono:
        lines.append(
            f"| {t['entry_date']} | {t['exit_date']} | {t['ticker']} | {t['name']} "
            f"| {t['entry_price']:.2f} | {t['exit_price']:.2f} "
            f"| {t['shares']} | {t['hold_days']} | {t['pnl_pct']:+.2f}% | ${t['pnl_dollar']:+,.0f} "
            f"| {t['exit_reason']} |"
        )
    lines.append("")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

_DEFAULT_OUTPUT = {
    "C1": _REPO / "docs" / "主力大課程" / "backtest_production_workflow_2026-05-01_to_2026-06-04.md",
    "C5": _REPO / "docs" / "主力大課程" / "backtest_C5_AC_exit_2026-05-01_to_2026-06-04.md",
}


def main():
    parser = argparse.ArgumentParser(description="標準 workflow backtest")
    parser.add_argument("--db", type=Path, default=_DB_DEFAULT)
    parser.add_argument("--cache-dir", type=Path, default=_CACHE_DIR_DEFAULT)
    parser.add_argument("--cached-only", action="store_true",
                        help="只讀現有快取、不重跑 scanner (快取不存在的日期會空白)")
    parser.add_argument("--mode", choices=["C1", "C5"], default="C1",
                        help="C1=baseline MA10; C5=MA10容忍+量縮例外+sizing partial exit")
    parser.add_argument("--output", type=Path, default=None,
                        help="輸出路徑 (預設依 mode 自動選)")
    args = parser.parse_args()

    output_path = args.output or _DEFAULT_OUTPUT.get(args.mode, _DEFAULT_OUTPUT["C1"])

    result = run_backtest(args.db, args.cache_dir, cached_only=args.cached_only, mode=args.mode)
    report = generate_report(result)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"\n✅ Report written to: {output_path}")
    print("\n" + "=" * 60)
    print(report[:3000])


if __name__ == "__main__":
    main()
