"""Trailing stop adjuster for HELD positions — structure-based, not daily T-1.

per memory feedback_direct_cut_with_stop_loss:
  - 不每天 T-1 low (太緊、會被一根洗盤洗掉)
  - 不固定原始值 (太鬆、強勢股後續會被迫扛回吐)
  - 用「結構底 trailing」、3 條件任一觸發才上移:
    1. 新黑K低點出現 (close<open + low > 現停損)
    2. 回踩 MA10 守住 (close > MA10 + 前一日 close < MA10)
    3. 連 3 天 low 墊高 (3 個 low 嚴格遞增)

per memory feedback_5347_add_position_condition:
  - 停損只上移不下移
  - 鎖 Plan 紀律: 不自動 apply、出建議讓 user 決定

Output:
  - docs/主力大課程/stop_review/YYYY-MM-DD.md (建議報告)
  - print summary to scanner log
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).parent.parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.db import get_conn, MAIN_DB

HOLDINGS_JSON = _REPO / "docs" / "主力大課程" / "holdings.json"
REVIEW_DIR = _REPO / "docs" / "主力大課程" / "stop_review"


def _get_bars(con: sqlite3.Connection, ticker: str, asof: str, n: int = 10) -> list[dict]:
    """近 n 個交易日的 bar (含 asof)、按 trade_date asc."""
    rows = con.execute(
        """SELECT trade_date, open, high, low, close, ma10
           FROM standard_daily_bar
           WHERE ticker=? AND trade_date <= ?
           ORDER BY trade_date DESC LIMIT ?""",
        (ticker, asof, n),
    ).fetchall()
    return [
        {"trade_date": r[0], "open": r[1], "high": r[2], "low": r[3],
         "close": r[4], "ma10": r[5]}
        for r in reversed(rows)
    ]


def suggest_new_stop(
    bars: list[dict], current_stop: float
) -> tuple[Optional[float], str]:
    """三條件 check、回傳 (new_stop or None, reason)。

    回傳的 new_stop 只會 > current_stop (不下移)。
    """
    if len(bars) < 4 or not current_stop:
        return None, "資料不足"

    candidates: list[tuple[float, str]] = []

    # 條件 1: 新黑K低點出現 (近 5 天)
    for b in bars[-5:]:
        if b["close"] and b["open"] and b["close"] < b["open"]:
            if b["low"] > current_stop:
                candidates.append((
                    float(b["low"]),
                    f"新黑K {b['trade_date']} 低 {b['low']}",
                ))

    # 條件 2: 回踩 MA10 守住 (今日 close > ma10 AND 前一日 close < ma10)
    if len(bars) >= 2:
        today = bars[-1]
        yest = bars[-2]
        if (today["close"] and today["ma10"] and
                yest["close"] and yest["ma10"]):
            if today["close"] > today["ma10"] and yest["close"] < yest["ma10"]:
                # 回踩 confirmed、停損抓回踩段最低
                retrace_lows = [b["low"] for b in bars[-3:] if b["low"]]
                if retrace_lows:
                    low = min(retrace_lows)
                    if low > current_stop:
                        candidates.append((
                            float(low),
                            f"回踩 MA10 守住 (今 {today['trade_date']})、回踩段最低 {low}",
                        ))

    # 條件 3: 連 3 天 low 墊高 (嚴格遞增)
    if len(bars) >= 3:
        lows = [b["low"] for b in bars[-3:] if b["low"]]
        if len(lows) == 3 and lows[0] < lows[1] < lows[2]:
            if lows[0] > current_stop:
                candidates.append((
                    float(lows[0]),
                    f"連 3 天 low 墊高 ({lows[0]}→{lows[1]}→{lows[2]})、抓最低 {lows[0]}",
                ))

    if not candidates:
        return None, "三條件皆未觸發、結構未上移"

    # 取最高 candidate (最近積極 trailing)
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0]


def run(target_date: str, db_path: Path = MAIN_DB) -> dict:
    """掃所有 HELD 持倉、suggest trailing stop adjustments。

    Returns:
        {'reviewed': N, 'suggested': M, 'review_path': str, 'items': [...]}
    """
    if not HOLDINGS_JSON.exists():
        return {"reviewed": 0, "suggested": 0, "review_path": "", "items": []}

    holdings = json.loads(HOLDINGS_JSON.read_text(encoding="utf-8"))
    active = holdings.get("holdings", {})

    items = []
    with get_conn(db_path) as con:
        for key, h in active.items():
            # skip meta keys + closed positions
            if key.startswith("_") or "_CLOSED" in key:
                continue
            if not isinstance(h, dict):
                continue
            ticker = key.split("_")[0]
            shares = h.get("shares", 0)
            if not shares or shares == 0:
                continue
            current_stop = h.get("stop_loss")
            if not current_stop:
                continue

            bars = _get_bars(con, ticker, target_date)
            if not bars:
                continue

            new_stop, reason = suggest_new_stop(bars, float(current_stop))
            today_close = bars[-1]["close"] if bars else None

            item = {
                "ticker": ticker,
                "name": h.get("name", ""),
                "cost": h.get("cost"),
                "shares": shares,
                "current_stop": float(current_stop),
                "today_close": today_close,
                "stop_source": h.get("stop_loss_source", ""),
                "entry_method": h.get("entry_method", "(未標)"),
            }
            if new_stop and new_stop > current_stop:
                lift_pct = (new_stop - current_stop) / current_stop * 100
                item.update({
                    "suggested_stop": new_stop,
                    "lift_pct": round(lift_pct, 1),
                    "reason": reason,
                    "action": "✏️ 建議上移",
                })
            else:
                item.update({
                    "suggested_stop": None,
                    "reason": reason,
                    "action": "✅ 維持",
                })
            items.append(item)

    suggested = [i for i in items if i.get("suggested_stop")]

    # 寫 review markdown
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    review_path = REVIEW_DIR / f"{target_date}.md"
    lines = [
        f"# 停損 trailing 建議 — {target_date}",
        "",
        f"- 持倉檢視: {len(items)} 檔",
        f"- 建議上移: **{len(suggested)} 檔**",
        f"- 規則來源: `feedback_direct_cut_with_stop_loss`（3 條件結構底 trailing）",
        f"- 紀律: **不自動 apply、user review 後決定**",
        "",
        "## 建議上移清單",
        "",
    ]
    if suggested:
        lines += [
            "| 股 | 名 | 現停 | 建議停 | 上移 % | 理由 |",
            "|---|---|---|---|---|---|",
        ]
        for i in suggested:
            lines.append(
                f"| {i['ticker']} | {i['name']} | "
                f"{i['current_stop']:.2f} | **{i['suggested_stop']:.2f}** | "
                f"+{i['lift_pct']}% | {i['reason']} |"
            )
    else:
        lines.append("（本日無建議上移、所有持倉結構未變化）")
    lines += [
        "",
        "## 全 HELD 檢視 (含維持不動)",
        "",
        "| 股 | 名 | 持股 | 成本 | 今收 | 現停 | 動作 | 說明 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i in items:
        cost_s = f"{i['cost']:.2f}" if i['cost'] else "-"
        close_s = f"{i['today_close']:.2f}" if i['today_close'] else "-"
        stop_s = f"→ {i['suggested_stop']:.2f}" if i.get("suggested_stop") else "-"
        lines.append(
            f"| {i['ticker']} | {i['name']} | {i['shares']} | "
            f"{cost_s} | {close_s} | {i['current_stop']:.2f} | "
            f"{i['action']} | {i['reason']} |"
        )

    lines += [
        "",
        "## 套用方式 (user 同意後)",
        "",
        "- 跟 AI 說「apply 6/12 停損建議」",
        "- AI 用 Edit 更新 holdings.json + monitor HELD list",
        "- commit + sync 三方 worktree + push",
        "",
        "## 規則參考",
        "",
        "- 條件 1: 新黑K低點 (close<open + low > 現停損)",
        "- 條件 2: 回踩 MA10 守住 (今 close>MA10 + 昨 close<MA10、用回踩段最低當新停)",
        "- 條件 3: 連 3 天 low 墊高 (嚴格遞增、抓最低當新停)",
        "- 只上移、不下移",
    ]
    review_path.write_text("\n".join(lines), encoding="utf-8")

    return {
        "reviewed": len(items),
        "suggested": len(suggested),
        "review_path": str(review_path),
        "items": items,
    }


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True)
    args = p.parse_args()

    out = run(args.date)
    print(f"\n=== Trailing stop 建議 ({args.date}) ===")
    print(f"  檢視: {out['reviewed']} 檔")
    print(f"  建議上移: {out['suggested']} 檔")
    print(f"  報告: {out['review_path']}")
    if out["suggested"]:
        print("\n  上移清單:")
        for i in out["items"]:
            if i.get("suggested_stop"):
                print(f"    {i['ticker']} {i['name']}: "
                      f"{i['current_stop']:.2f} → {i['suggested_stop']:.2f} "
                      f"(+{i['lift_pct']}%、{i['reason']})")
