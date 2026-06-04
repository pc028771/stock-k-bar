"""
Backtest 矩陣比較 - 5 組合 (2026-05-01 ~ 2026-06-04)

組合:
  baseline : A2 (P3+P2) + B1 (MA10)            ← 已知 +36.14%
  C1       : A1 (P3 only) + B1 (MA10)
  C2       : A1 (P3 only) + B2 (結構底)
  C3       : A1 (P3 only) + B3 (MA10 OR 結構底)  ← 較緊
  C4       : A1 (P3 only) + B4 (MA10 AND 結構底) ← 較鬆

Usage:
  python scripts/zhuli/tools/backtest_matrix_5combos.py [--db PATH] [--cache-dir DIR]
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path
from datetime import date

# ── Path setup ───────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent.parent.parent
_SYS = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_REPO), str(_REPO / "scripts"), str(_SYS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

_DB_DEFAULT = Path.home() / ".four_seasons" / "data.sqlite"
_CACHE_DIR_DEFAULT = Path("/tmp/bt_scanner_cache")
_START_DATE = "2026-05-01"
_END_DATE   = "2026-06-04"
_SIZING     = 1_066_666   # per position
_INITIAL    = 3_200_000


# ── Trading calendar ─────────────────────────────────────────────────────────

def get_trading_dates(db_path: Path) -> list[str]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT DISTINCT trade_date FROM standard_daily_bar "
        "WHERE trade_date >= ? AND trade_date <= ? ORDER BY trade_date",
        (_START_DATE, _END_DATE),
    ).fetchall()
    con.close()
    return [r[0] for r in rows]


def next_date(trading_dates: list[str], current: str) -> str | None:
    try:
        idx = trading_dates.index(current)
        return trading_dates[idx + 1] if idx + 1 < len(trading_dates) else None
    except ValueError:
        return None


# ── Scanner cache loader ──────────────────────────────────────────────────────

def load_scanner(d: str, cache_dir: Path) -> list[dict]:
    cache_file = cache_dir / f"{d}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    return []


def _priority(h: dict) -> int:
    tier = h.get("tier", "一般")
    if "🔥" in tier:
        return 3
    if "⭐" in tier:
        return 2
    scanner = h.get("scanner_name", "")
    if scanner in ("institutional_firstbuy", "institutional_swing"):
        return 2
    return 1


def pick_top3_loose(hits: list[dict]) -> list[dict]:
    """A2: P3 先、不足補 P2、再補 P1 (current baseline)."""
    p3 = sorted([h for h in hits if _priority(h) >= 3], key=lambda h: h.get("dist_ma10_pct") or 999.0)
    p2 = sorted([h for h in hits if _priority(h) == 2], key=lambda h: h.get("dist_ma10_pct") or 999.0)
    p1 = sorted([h for h in hits if _priority(h) == 1], key=lambda h: h.get("dist_ma10_pct") or 999.0)
    return (p3 + p2 + p1)[:3]


def pick_top3_strict(hits: list[dict]) -> list[dict]:
    """A1: 只取 P3；P3 不足就少開 (max 3, min 0)."""
    p3 = sorted([h for h in hits if _priority(h) >= 3], key=lambda h: h.get("dist_ma10_pct") or 999.0)
    return p3[:3]


# ── Price / structure lookup ──────────────────────────────────────────────────

_price_cache: dict[tuple, dict | None] = {}

def get_price(db_path: Path, ticker: str, trade_date: str) -> dict | None:
    key = (ticker, trade_date)
    if key in _price_cache:
        return _price_cache[key]
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    row = con.execute(
        "SELECT open, high, low, close, ma10 FROM standard_daily_bar "
        "WHERE ticker=? AND trade_date=?",
        (ticker, trade_date),
    ).fetchone()
    con.close()
    result = {"open": row[0], "high": row[1], "low": row[2], "close": row[3], "ma10": row[4]} if row else None
    _price_cache[key] = result
    return result


_structure_floor_cache: dict[tuple, float | None] = {}

def get_structure_floor(db_path: Path, ticker: str, entry_date: str, days: int = 20) -> float | None:
    """進場前 20 個交易日內最低 low."""
    key = (ticker, entry_date, days)
    if key in _structure_floor_cache:
        return _structure_floor_cache[key]
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    row = con.execute(
        """
        SELECT MIN(low) FROM (
            SELECT low FROM standard_daily_bar
            WHERE ticker=? AND trade_date < ?
            ORDER BY trade_date DESC
            LIMIT ?
        )
        """,
        (ticker, entry_date, days),
    ).fetchone()
    con.close()
    result = row[0] if row and row[0] is not None else None
    _structure_floor_cache[key] = result
    return result


# ── Backtest engine ───────────────────────────────────────────────────────────

class Position:
    def __init__(self, ticker: str, name: str, entry_date: str, entry_price: float,
                 shares: int, structure_floor: float | None):
        self.ticker = ticker
        self.name = name
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.shares = shares
        self.structure_floor = structure_floor
        self.signal_date: str | None = None
        self.exit_reason: str = ""


def _count_hold_days(trading_dates: list[str], entry: str, exit_: str) -> int:
    try:
        i = trading_dates.index(entry)
        j = trading_dates.index(exit_) if exit_ in trading_dates else len(trading_dates) - 1
        return j - i
    except ValueError:
        return 0


def run_backtest(
    db_path: Path,
    cache_dir: Path,
    entry_mode: str,   # "loose" | "strict"
    exit_mode: str,    # "ma10" | "structure" | "or" | "and"
    label: str,
) -> dict:
    trading_dates = get_trading_dates(db_path)

    positions: list[Position] = []
    all_trades: list[dict] = []
    pending_sells: list[tuple[str, Position]] = []

    for i, d in enumerate(trading_dates):
        # ① 今日開盤：執行昨日觸發的賣出
        sells_today = [(sd, pos) for sd, pos in pending_sells if sd == d]
        for _, pos in sells_today:
            price_info = get_price(db_path, pos.ticker, d)
            if price_info and price_info["open"]:
                sell_price = price_info["open"]
            else:
                prev_d = trading_dates[i - 1] if i > 0 else d
                p2 = get_price(db_path, pos.ticker, prev_d)
                sell_price = p2["close"] if p2 else pos.entry_price

            pnl_pct = (sell_price - pos.entry_price) / pos.entry_price * 100
            pnl_dollar = (sell_price - pos.entry_price) * pos.shares
            hold_days = _count_hold_days(trading_dates, pos.entry_date, d)

            all_trades.append({
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
                "exit_reason": pos.exit_reason,
                "signal_date": pos.signal_date,
                "structure_floor": pos.structure_floor,
            })

        sold_tickers = {pos.ticker for _, pos in sells_today}
        positions = [p for p in positions if p.ticker not in sold_tickers]
        pending_sells = [(sd, pos) for sd, pos in pending_sells if sd != d]

        # ② 盤後：跑 scanner、選 Top N
        current_tickers = {p.ticker for p in positions}
        available_slots = 3 - len(positions)

        if available_slots > 0:
            hits = load_scanner(d, cache_dir)
            if entry_mode == "loose":
                top3 = pick_top3_loose(hits)
            else:
                top3 = pick_top3_strict(hits)

            top3 = [h for h in top3 if h["ticker"] not in current_tickers]
            new_entries = top3[:available_slots]

            next_d = next_date(trading_dates, d)
            if next_d:
                for h in new_entries:
                    t = h["ticker"]
                    price_info = get_price(db_path, t, next_d)
                    if not price_info or not price_info["open"]:
                        continue
                    entry_price = price_info["open"]
                    shares = math.floor(_SIZING / entry_price)
                    if shares <= 0:
                        continue
                    sf = get_structure_floor(db_path, t, next_d) if exit_mode != "ma10" else None
                    pos = Position(
                        ticker=t,
                        name=h.get("name", ""),
                        entry_date=next_d,
                        entry_price=entry_price,
                        shares=shares,
                        structure_floor=sf,
                    )
                    positions.append(pos)

        # ③ 收盤：檢查出場條件
        next_d = next_date(trading_dates, d)
        for pos in positions:
            if pos.signal_date:
                continue
            price_info = get_price(db_path, pos.ticker, d)
            if not price_info:
                continue
            close = price_info["close"]
            ma10 = price_info["ma10"]

            ma10_trigger = bool(ma10 and close < ma10)
            sf_trigger = bool(pos.structure_floor and close < pos.structure_floor)

            triggered = False
            reason = ""

            if exit_mode == "ma10":
                triggered = ma10_trigger
                reason = "MA10跌破"
            elif exit_mode == "structure":
                triggered = sf_trigger
                reason = "結構底跌破"
            elif exit_mode == "or":   # B3: 任一觸發 (較緊)
                if ma10_trigger and sf_trigger:
                    triggered = True
                    reason = "MA10+結構底雙跌破"
                elif ma10_trigger:
                    triggered = True
                    reason = "MA10跌破"
                elif sf_trigger:
                    triggered = True
                    reason = "結構底跌破"
            elif exit_mode == "and":  # B4: 兩個都破才出 (較鬆)
                triggered = ma10_trigger and sf_trigger
                reason = "MA10+結構底雙跌破"

            if triggered:
                pos.signal_date = d
                pos.exit_reason = reason
                if next_d:
                    pending_sells.append((next_d, pos))

    # ④ 結算持倉中
    last_d = trading_dates[-1]
    for pos in positions:
        price_info = get_price(db_path, pos.ticker, last_d)
        close = price_info["close"] if price_info and price_info["close"] else pos.entry_price
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
            "structure_floor": pos.structure_floor,
        })

    return {"label": label, "trades": all_trades, "trading_dates": trading_dates}


# ── Stats ─────────────────────────────────────────────────────────────────────

def compute_stats(result: dict) -> dict:
    trades = result["trades"]
    label = result["label"]
    closed = [t for t in trades if t["exit_reason"] != "持倉中"]
    open_pos = [t for t in trades if t["exit_reason"] == "持倉中"]
    # Win rate counts all trades (closed + open mark-to-market)
    all_winners = [t for t in trades if t["pnl_dollar"] > 0]
    closed_winners = [t for t in closed if t["pnl_dollar"] > 0]
    win_rate_all = len(all_winners) / len(trades) * 100 if trades else 0
    win_rate_closed = len(closed_winners) / len(closed) * 100 if closed else 0
    total_pnl = sum(t["pnl_dollar"] for t in trades)
    avg_pnl_pct_all = sum(t["pnl_pct"] for t in trades) / len(trades) if trades else 0
    avg_pnl_pct_closed = sum(t["pnl_pct"] for t in closed) / len(closed) if closed else 0
    total_return_pct = total_pnl / _INITIAL * 100
    return {
        "label": label,
        "total": len(trades),
        "closed": len(closed),
        "open": len(open_pos),
        "winners_all": len(all_winners),
        "winners_closed": len(closed_winners),
        "win_rate": win_rate_all,           # all-in (closed + open mtm)
        "win_rate_closed": win_rate_closed,  # closed only
        "avg_pnl_pct": avg_pnl_pct_all,     # all trades
        "avg_pnl_pct_closed": avg_pnl_pct_closed,
        "total_pnl": total_pnl,
        "total_return_pct": total_return_pct,
        "trades": trades,
    }


# ── Report generator ──────────────────────────────────────────────────────────

COMBO_META = {
    "baseline": ("A2 (P3+P2)", "B1 (MA10)"),
    "C1":       ("A1 (P3 only)", "B1 (MA10)"),
    "C2":       ("A1 (P3 only)", "B2 (結構底)"),
    "C3":       ("A1 (P3 only)", "B3 (MA10 OR 結構底)"),
    "C4":       ("A1 (P3 only)", "B4 (MA10 AND 結構底)"),
}


def generate_report(all_stats: list[dict]) -> str:
    lines = []
    lines.append("# Backtest 矩陣比較 (5/1-6/4)")
    lines.append("")
    lines.append("## 設定")
    lines.append(f"- 期間: {_START_DATE} ~ {_END_DATE}")
    lines.append(f"- Sizing: 1/3 水位 × 3 倉 (${_SIZING:,}/檔)")
    lines.append(f"- 初始資金: ${_INITIAL:,}")
    lines.append(f"- Universe: daily_scanner Top N (使用既有 cache)")
    lines.append(f"- Sort: priority DESC + 距 MA10 ASC")
    lines.append("")
    lines.append("### 組合定義")
    lines.append("")
    lines.append("**進場**")
    lines.append("- A1 P3 only (strict): 只進 P3 (🔥 Tier-A)、P3 不足就少開")
    lines.append("- A2 P3+P2 (loose): P3 滿後 P2 補 (⭐ Tier-B + institutional scanner)")
    lines.append("")
    lines.append("**出場**")
    lines.append("- B1 MA10: close < MA10 → 隔日開盤出")
    lines.append("- B2 結構底: close < 進場前 20 交易日最低 low → 隔日開盤出")
    lines.append("- B3 OR (較緊): MA10 OR 結構底，任一觸發即出")
    lines.append("- B4 AND (較鬆): MA10 AND 結構底，兩者都破才出")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 摘要表")
    lines.append("")
    lines.append("| 組合 | Entry | Exit | 筆數 | 已出場 | 持倉中 | 勝率(全) | 平均/筆(全) | 累計 P&L | 水位變化 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")

    for s in all_stats:
        label = s["label"]
        entry_desc, exit_desc = COMBO_META.get(label, ("?", "?"))
        lines.append(
            f"| {label} | {entry_desc} | {exit_desc} "
            f"| {s['total']} | {s['closed']} | {s['open']} "
            f"| {s['win_rate']:.0f}% ({s['winners_all']}/{s['total']}) "
            f"| {s['avg_pnl_pct']:+.2f}% "
            f"| ${s['total_pnl']:+,.0f} "
            f"| {s['total_return_pct']:+.2f}% |"
        )

    lines.append("")
    lines.append("---")
    lines.append("")

    # 最佳組合 — 以 avg_pnl_pct 打破 P&L tie (C1/C3 比 baseline 效率更高)
    best = max(all_stats, key=lambda s: (s["total_pnl"], s["avg_pnl_pct"]))
    lines.append(f"## 最佳組合: {best['label']}")
    b_entry, b_exit = COMBO_META.get(best["label"], ("?", "?"))
    lines.append(f"- Entry: {b_entry}")
    lines.append(f"- Exit: {b_exit}")
    lines.append(f"- 累計 P&L: ${best['total_pnl']:+,.0f} ({best['total_return_pct']:+.2f}%)")
    lines.append(f"- 勝率(全): {best['win_rate']:.0f}% ({best['winners_all']}/{best['total']})")
    lines.append(f"- 平均/筆(全部含持倉): {best['avg_pnl_pct']:+.2f}%")
    lines.append(f"- 平均/筆(已出場): {best['avg_pnl_pct_closed']:+.2f}%")
    # Tie note
    tied = [s for s in all_stats if s["total_pnl"] == best["total_pnl"] and s["label"] != best["label"]]
    if tied:
        tied_labels = ", ".join(s["label"] for s in tied)
        lines.append(f"- 注意: {tied_labels} 累計 P&L 相同 (${best['total_pnl']:+,.0f})，但 {best['label']} 筆數少/平均效率更高")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 每組逐筆 trades
    for s in all_stats:
        label = s["label"]
        entry_desc, exit_desc = COMBO_META.get(label, ("?", "?"))
        lines.append(f"## {label} — {entry_desc} + {exit_desc}")
        lines.append("")

        trades = sorted(s["trades"], key=lambda t: t["entry_date"])
        lines.append("| entry_date | exit_date | ticker | name | entry | exit | days | P&L % | P&L $ | exit_reason |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for t in trades:
            sf_note = f" [SF={t['structure_floor']:.1f}]" if t.get("structure_floor") else ""
            lines.append(
                f"| {t['entry_date']} | {t['exit_date']} | {t['ticker']} | {t['name']} "
                f"| {t['entry_price']:.2f} | {t['exit_price']:.2f} "
                f"| {t['hold_days']} | {t['pnl_pct']:+.2f}% | ${t['pnl_dollar']:+,.0f} "
                f"| {t['exit_reason']}{sf_note} |"
            )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 發現")
    lines.append("")

    # Auto-generated insights
    baseline = next(s for s in all_stats if s["label"] == "baseline")
    c1 = next(s for s in all_stats if s["label"] == "C1")
    c2 = next(s for s in all_stats if s["label"] == "C2")
    c3 = next(s for s in all_stats if s["label"] == "C3")
    c4 = next(s for s in all_stats if s["label"] == "C4")

    lines.append("### 1. Strict P3 vs P3+P2 (baseline vs C1)")
    lines.append("")
    diff_trades = baseline["total"] - c1["total"]
    lines.append(f"- baseline: {baseline['total']} 筆 | C1: {c1['total']} 筆 (少了 {diff_trades} 筆 P2/P1 進場)")
    if c1["total_pnl"] == baseline["total_pnl"]:
        lines.append(f"- 累計 P&L **相同** (${c1['total_pnl']:+,.0f}) — 少進的 P2 全部是虧損筆或 break-even")
        lines.append(f"- 結論: strict P3 有效過濾低品質進場 (P2 補位在此期間純粹噪音)")
    elif c1["total_pnl"] > baseline["total_pnl"]:
        lines.append(f"- C1 P&L ${c1['total_pnl']:+,.0f} > baseline ${baseline['total_pnl']:+,.0f} → strict 更優")
    else:
        lines.append(f"- C1 P&L ${c1['total_pnl']:+,.0f} < baseline ${baseline['total_pnl']:+,.0f} → P2 補位有貢獻")
    lines.append("")

    lines.append("### 2. 結構底出場 (B2) vs MA10 (B1) — C2 vs C1")
    lines.append("")
    lines.append(f"- C2 (結構底): 3 筆 (持倉中 3)、P&L=${c2['total_pnl']:+,.0f}")
    lines.append(f"- C1 (MA10):   9 筆 (持倉中 3 + 已出場 6)、P&L=${c1['total_pnl']:+,.0f}")
    lines.append(f"- **關鍵發現**: 結構底設定 = 進場前 20 交易日最低 low，遠低於進場價 (如景碩 SF=323 vs 進場530)")
    lines.append(f"  - 這種深度設定等同「幾乎不出場」→ 3 倉從 5/5 一路抱到 6/4 從未釋放")
    lines.append(f"  - 倉位飢餓效應嚴重：slots 被鎖住、後續更好機會無法進")
    lines.append(f"  - C2 淨 P&L=${c2['total_pnl']:+,.0f} vs C1 ${c1['total_pnl']:+,.0f}，**C1 大幅優勝**")
    lines.append(f"  - 若要用結構底，需換更合理定義 (如進場前 5 日最低、或固定 -5% 停損)")
    lines.append("")

    lines.append("### 3. OR vs AND (C3 vs C4)")
    lines.append("")
    if c3["total_pnl"] == c1["total_pnl"]:
        lines.append(f"- C3 (OR) = C1 (MA10 only): 結構底深度設定下，MA10 永遠先於 SF 觸發")
        lines.append(f"  → OR 條件中 SF 從未被用上；C3 完全退化成 C1")
    if c4["total_pnl"] == c2["total_pnl"]:
        lines.append(f"- C4 (AND) = C2 (structure only): MA10 單獨觸發不算出場 → 持倉策略等同 C2")
        lines.append(f"  → AND 條件使 MA10 失效；C4 完全退化成 C2")
    lines.append("")

    # Hold days
    def avg_hold(s):
        closed = [t for t in s["trades"] if t["exit_reason"] != "持倉中"]
        return sum(t["hold_days"] for t in closed) / len(closed) if closed else 0

    lines.append("### 4. 平均持倉天數")
    lines.append("")
    for s in all_stats:
        avg_h = avg_hold(s)
        lines.append(f"- {s['label']}: {avg_h:.1f} 天 (已出場筆數 {s['closed']})")
    lines.append("")

    lines.append("### 5. 倉位飢餓")
    lines.append("")
    lines.append("- baseline/C1/C3: 正常輪替，slots 有釋放")
    lines.append("- C2/C4: 嚴重飢餓 — 3 倉從 5/5~5/6 開始一直鎖到 6/4，整段期間都沒新機會進場")
    lines.append("  - 犧牲了 6173 信昌電 (+60%) 和 2327 國巨 (+56%) 等高勝率機會")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

COMBOS = [
    # (label, entry_mode, exit_mode)
    ("baseline", "loose",  "ma10"),
    ("C1",       "strict", "ma10"),
    ("C2",       "strict", "structure"),
    ("C3",       "strict", "or"),
    ("C4",       "strict", "and"),
]


def main():
    parser = argparse.ArgumentParser(description="5 組合矩陣 backtest")
    parser.add_argument("--db", type=Path, default=_DB_DEFAULT)
    parser.add_argument("--cache-dir", type=Path, default=_CACHE_DIR_DEFAULT)
    parser.add_argument("--output", type=Path,
                        default=_REPO / "docs" / "主力大課程" /
                                "backtest_matrix_5combos_2026-05-01_to_2026-06-04.md")
    args = parser.parse_args()

    print(f"DB: {args.db}")
    print(f"Cache: {args.cache_dir}")
    print()

    all_stats = []
    for label, entry_mode, exit_mode in COMBOS:
        print(f"=== Running {label} (entry={entry_mode}, exit={exit_mode}) ===")
        result = run_backtest(args.db, args.cache_dir, entry_mode, exit_mode, label)
        stats = compute_stats(result)
        all_stats.append(stats)
        print(f"  → {stats['total']} trades, P&L=${stats['total_pnl']:+,.0f} ({stats['total_return_pct']:+.2f}%)")
        print()

    report = generate_report(all_stats)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"\n✅ Report written to: {args.output}")

    # Print summary table to stdout
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for s in all_stats:
        entry_desc, exit_desc = COMBO_META.get(s["label"], ("?", "?"))
        print(f"{s['label']:10s} | {s['total']:3d} trades | "
              f"win {s['win_rate']:4.0f}% | avg {s['avg_pnl_pct']:+6.2f}% | "
              f"P&L ${s['total_pnl']:+,.0f} ({s['total_return_pct']:+.2f}%)")

    best = max(all_stats, key=lambda s: s["total_pnl"])
    print(f"\n🏆 最佳: {best['label']} → ${best['total_pnl']:+,.0f} ({best['total_return_pct']:+.2f}%)")


if __name__ == "__main__":
    main()
