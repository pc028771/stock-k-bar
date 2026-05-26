"""Contrarian scanner 回測 — 4/01 ~ 5/25 每日跑一次，追蹤後續表現.

驗證假設：
1. 只用 teacher_picks 標的 → 能否抓到當日/隔日漲停？
2. 大盤跌日（≤-0.3%）→ scanner 標的平均表現好過大盤？
3. 命中率隨時間穩定？

跑法：
    python scripts/zhuli/contrarian_backtest.py [--start 2026-04-01] [--end 2026-05-25]

Output:
    /tmp/contrarian_backtest_report.md
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

_REPO = Path(__file__).parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts"), "/Users/howard/Repository/stock-analysis-system"]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.contrarian_strong_scanner import run_scan

_DB = Path.home() / ".four_seasons" / "data.sqlite"
_PICKS = _REPO / "docs" / "主力大課程" / "teacher_picks_2026.json"


def get_trading_dates(start: str, end: str, conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT trade_date FROM standard_daily_bar WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date",
        (start, end),
    ).fetchall()
    return [r[0] for r in rows]


def market_index_change(conn: sqlite3.Connection, d: str) -> float:
    """0050 當日漲跌幅 % (vs 前日)."""
    rows = conn.execute(
        """SELECT close FROM standard_daily_bar
           WHERE ticker='0050' AND trade_date<=? ORDER BY trade_date DESC LIMIT 2""",
        (d,),
    ).fetchall()
    if len(rows) < 2:
        return 0
    return (rows[0][0] - rows[1][0]) / rows[1][0] * 100


def next_n_day_max_gain(conn: sqlite3.Connection, ticker: str, base_date: str, n: int = 5) -> tuple[float, str]:
    """從 base_date 隔日起、未來 n 個交易日最大漲幅 (vs base_date 收盤)."""
    base = conn.execute(
        "SELECT close FROM standard_daily_bar WHERE ticker=? AND trade_date=?",
        (ticker, base_date),
    ).fetchone()
    if not base:
        return 0, ""
    base_c = base[0]
    rows = conn.execute(
        """SELECT trade_date, close, high FROM standard_daily_bar
           WHERE ticker=? AND trade_date > ? ORDER BY trade_date LIMIT ?""",
        (ticker, base_date, n),
    ).fetchall()
    if not rows:
        return 0, ""
    max_gain = -100
    max_d = ""
    for d, c, h in rows:
        gain = (h - base_c) / base_c * 100
        if gain > max_gain:
            max_gain = gain
            max_d = d
    return max_gain, max_d


def next_n_day_lu_hit(conn: sqlite3.Connection, ticker: str, base_date: str, n: int = 5) -> bool:
    """隔日起 n 天內是否漲停過 (close >= prev_close × 1.099)."""
    rows = conn.execute(
        """SELECT trade_date, close FROM standard_daily_bar
           WHERE ticker=? AND trade_date >= ? ORDER BY trade_date LIMIT ?""",
        (ticker, base_date, n + 1),
    ).fetchall()
    for i in range(1, len(rows)):
        # 9.5% 抓 tick rounding 後仍算漲停的（如 +9.70%、+9.73%）
        if rows[i][1] >= rows[i-1][1] * 1.094:
            return True
    return False


def run_backtest(start: str, end: str, score_threshold: int = 10, top_n: int = 10) -> dict:
    conn = sqlite3.connect(_DB)
    dates = get_trading_dates(start, end, conn)
    print(f"回測 {len(dates)} 個交易日: {dates[0]} → {dates[-1]}")

    day_results = []
    all_picks = []  # 每個被選中的標的的結果

    for i, d in enumerate(dates):
        mkt_chg = market_index_change(conn, d)
        try:
            raw = run_scan(d, min_score=score_threshold, include_broker=False)
            # 只取 🟢 可進場 zone (bias ≤ +15%)
            results = [r for r in raw if r.get("zone") == "🟢可進場"][:top_n]
        except Exception as exc:
            print(f"  {d}: scan error {exc}")
            continue

        day_picks = []
        for r in results:
            max_gain, max_d = next_n_day_max_gain(conn, r["ticker"], d, n=5)
            lu_hit = next_n_day_lu_hit(conn, r["ticker"], d, n=5)
            day_picks.append({
                "ticker": r["ticker"],
                "name": r["name"],
                "score": r["score"],
                "bias10": r["bias10"],
                "next5d_max_gain": max_gain,
                "next5d_lu_hit": lu_hit,
            })
            all_picks.append({**day_picks[-1], "scan_date": d, "mkt_chg": mkt_chg})

        if day_picks:
            avg_gain = sum(p["next5d_max_gain"] for p in day_picks) / len(day_picks)
            lu_hits = sum(1 for p in day_picks if p["next5d_lu_hit"])
            day_results.append({
                "date": d,
                "mkt_chg": mkt_chg,
                "n_picks": len(day_picks),
                "avg_next5d_max_gain": avg_gain,
                "lu_hits": lu_hits,
                "lu_rate": lu_hits / len(day_picks) * 100,
            })
            if i % 5 == 0:
                print(f"  {d} 大盤{mkt_chg:+.2f}% n={len(day_picks)} avg_gain={avg_gain:+.1f}% LU={lu_hits}/{len(day_picks)}")

    conn.close()
    return {"day_results": day_results, "all_picks": all_picks, "dates": dates}


def summarize(backtest: dict, score_threshold: int) -> str:
    days = backtest["day_results"]
    picks = backtest["all_picks"]
    if not picks:
        return "無候選"

    total_picks = len(picks)
    lu_hits = sum(1 for p in picks if p["next5d_lu_hit"])
    avg_gain = sum(p["next5d_max_gain"] for p in picks) / total_picks
    win_5pct = sum(1 for p in picks if p["next5d_max_gain"] >= 5)
    win_10pct = sum(1 for p in picks if p["next5d_max_gain"] >= 10)

    # 大盤跌日表現
    down_days = [p for p in picks if p["mkt_chg"] <= -0.3]
    if down_days:
        down_avg_gain = sum(p["next5d_max_gain"] for p in down_days) / len(down_days)
        down_lu_hits = sum(1 for p in down_days if p["next5d_lu_hit"])
    else:
        down_avg_gain = 0; down_lu_hits = 0

    up_days = [p for p in picks if p["mkt_chg"] >= 0.3]
    if up_days:
        up_avg_gain = sum(p["next5d_max_gain"] for p in up_days) / len(up_days)
    else:
        up_avg_gain = 0

    lines = [
        f"# Contrarian Scanner 回測報告 (score ≥ {score_threshold})",
        "",
        f"## 整體",
        f"- 回測期: {backtest['dates'][0]} → {backtest['dates'][-1]} ({len(backtest['dates'])} 天)",
        f"- 候選總數: **{total_picks}** 個 pick × day",
        f"- 隔日起 5 日內漲停命中: **{lu_hits} ({lu_hits/total_picks*100:.1f}%)**",
        f"- 平均 5 日最大漲幅: **{avg_gain:+.2f}%**",
        f"- ≥+5% 大勝率: {win_5pct/total_picks*100:.1f}%",
        f"- ≥+10% 飆股率: {win_10pct/total_picks*100:.1f}%",
        "",
        f"## 大盤跌日（≤-0.3%）抗跌能力",
        f"- 大盤跌日的 picks: {len(down_days)}",
        f"- 5 日內漲停命中: {down_lu_hits} ({down_lu_hits/len(down_days)*100 if down_days else 0:.1f}%)",
        f"- 平均 5 日最大漲幅: **{down_avg_gain:+.2f}%**",
        "",
        f"## 大盤漲日（≥+0.3%）順勢表現",
        f"- 大盤漲日的 picks: {len(up_days)}",
        f"- 平均 5 日最大漲幅: {up_avg_gain:+.2f}%",
        "",
        f"## 逐日明細",
        f"| 日期 | 大盤% | n | LU命中 | 平均漲幅 |",
        f"|---|---|---|---|---|",
    ]
    for d in days:
        lines.append(
            f"| {d['date']} | {d['mkt_chg']:+.2f}% | {d['n_picks']} | "
            f"{d['lu_hits']}/{d['n_picks']} ({d['lu_rate']:.0f}%) | "
            f"{d['avg_next5d_max_gain']:+.2f}% |"
        )
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-04-01")
    ap.add_argument("--end", default="2026-05-25")
    ap.add_argument("--score", type=int, default=10)
    ap.add_argument("--top-n", type=int, default=10)
    args = ap.parse_args()

    bt = run_backtest(args.start, args.end, score_threshold=args.score, top_n=args.top_n)
    report = summarize(bt, args.score)
    out = Path("/tmp/contrarian_backtest_report.md")
    out.write_text(report, encoding="utf-8")
    print()
    print(report.split("## 逐日明細")[0])  # 印整體摘要
    print(f"\n→ 完整報告: {out}")


if __name__ == "__main__":
    main()
