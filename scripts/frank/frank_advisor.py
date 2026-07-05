#!/usr/bin/env python3
"""Frank v2 engine → (1) 近一個月操作復盤 (2) 下週標的掃描 (3) 現有持倉檢查

Recommendation 採用版: teacher timeline universe + 戰法二 entry + score>=1 + 買綠<5% + 分層出場
"""
from __future__ import annotations

import sys
import json
from pathlib import Path
from collections import defaultdict

_REPO = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO / "scripts"))
from zhuli.db import get_conn

REVIEW_START = "2026-06-01"


def load_eligibility():
    elig = {}
    picks = json.loads((_REPO / "docs/主力大課程/teacher_picks_2026.json").read_text())
    for tk, v in picks.items():
        if tk == "_meta" or not tk.isdigit():
            continue
        dates = [m.get("date") for m in v.get("mentions", []) if m.get("date")]
        if dates:
            elig[tk] = min(dates)
    for js in (_REPO / "docs/主力大課程").glob("teacher_sectors_2026*.json"):
        stamp = js.stem.split("_")[-1]
        fd = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"
        def walk(x):
            if isinstance(x, str) and x.isdigit() and len(x) >= 4:
                elig.setdefault(x, fd)
            elif isinstance(x, dict):
                for v in x.values(): walk(v)
            elif isinstance(x, list):
                for v in x: walk(v)
        try:
            walk(json.loads(js.read_text()))
        except Exception:
            pass
    return elig


def get_bars(conn, tk, start, end):
    return conn.execute("""SELECT trade_date, close, high, volume, ma5, ma20, ma20_slope,
                                  bb_position, vol_ratio_20
                           FROM standard_daily_bar
                           WHERE ticker=? AND trade_date BETWEEN ? AND ? AND close>0
                           ORDER BY trade_date""", (tk, start, end)).fetchall()


def eval_day(bars, i):
    """回傳 (bo2_ok, chg, score, detail) — bars[i] 為訊號日."""
    if i < 1:
        return None
    d, c, hi, vol, ma5, ma20, slope, bpos, vr = bars[i]
    _, pc, phi, pvol, pma5, *_ = bars[i - 1]
    if None in (c, ma5, ma20, slope) or pc is None or pma5 is None:
        return None
    bo2 = slope > 0 and c > ma20 and pc <= pma5 and c > ma5
    chg = (c / pc - 1) * 100
    # score
    wall_high = None
    lo = max(0, i - 20)
    if i > lo:
        w = max(bars[lo:i], key=lambda x: x[2] or 0)
        wall_high = w[1]  # 注意: index 1 = close... 用 high
        wall_high = w[2] if False else w[1]
    # 正確取 high: bars row = (d, close, high, volume, ...)
    w = max(bars[lo:i], key=lambda x: x[3] or 0)  # max volume
    wall_high = w[2]
    score = 0
    detail = []
    if wall_high and c > wall_high:
        score += 2; detail.append("過城牆+2")
    if phi and c > phi:
        score += 1; detail.append("頭頭高+1")
    if bpos and bpos >= 80:
        score += 1; detail.append("壓布林頂+1")
    if vr and vr >= 1.5:
        score += 1; detail.append("出量+1")
    return {"date": d, "close": c, "bo2": bo2, "chg": chg, "score": score,
            "detail": "/".join(detail) or "無加分", "ma5": ma5, "ma20": ma20,
            "slope": slope, "bpos": bpos}


def main():
    conn = get_conn()
    elig = load_eligibility()
    names = dict(conn.execute("SELECT ticker, name FROM stock_name"))

    lines = ["# Frank v2 Engine — 近月操作復盤 + 下週標的",
             "資料截至 2026-07-03 收盤 / Engine: teacher timeline + 戰法二 + score≥1 + 買綠<5%", ""]

    # ---------- (1) 近一個月操作復盤 ----------
    trades = conn.execute("""SELECT trade_date, ticker, stock_name, action, price, shares
                             FROM broker_statement
                             WHERE trade_date >= ? ORDER BY trade_date""",
                          (REVIEW_START,)).fetchall()
    lines += ["## (1) 近一個月操作復盤（6/1 起）", "",
              "| 日期 | 標的 | 動作 | 價格 | Engine 判定 |", "|---|---|---|---|---|"]
    for d, tk, nm, act, px, sh in trades:
        if act not in ("現買", "沖買"):
            continue
        verdict = []
        e_date = elig.get(tk)
        if not e_date:
            verdict.append("❌ 非老師名單")
        elif d < e_date:
            verdict.append(f"❌ 點名日 {e_date} 之前")
        bars = get_bars(conn, tk, "2026-04-01", d)
        ev = eval_day(bars, len(bars) - 1) if bars and bars[-1][0] == d else None
        if ev:
            if not ev["bo2"]:
                verdict.append("❌ 非戰法二訊號日（追價/無回測5MA再上）")
            elif ev["chg"] >= 5:
                verdict.append(f"❌ 追紅 +{ev['chg']:.1f}%")
            elif ev["score"] == 0:
                verdict.append("❌ score 0（反向訊號 skip）")
            else:
                verdict.append(f"✅ 合格 score {ev['score']}（{ev['detail']}）")
        elif not verdict:
            verdict.append("⚠️ 無法評（資料缺）")
        lines.append(f"| {d} | {tk} {nm or names.get(tk,'')} | {act} | {px} | {'; '.join(verdict)} |")

    # ---------- (2) 現有持倉檢查（source of truth: scripts/zhuli/positions.py HELD）----------
    from zhuli.positions import HELD
    lines += ["", "## (2) 現有持倉 Frank 出場層檢查（7/3 收盤、source: positions.py）", "",
              "| 標的 | 股數 | 成本 | 自設 stop | 7/3 收 | Frank 層次 | Frank 狀態 | vs 自設 stop |",
              "|---|---|---|---|---|---|---|---|"]
    for pos in HELD:
        tk, nm = pos["ticker"], pos["name"]
        sh, cost, stop = pos["shares"], pos["cost"], pos["stop"]
        bars = get_bars(conn, tk, "2026-05-01", "2026-07-03")
        if not bars:
            lines.append(f"| {tk} {nm} | {sh:,} | {cost} | {stop} | 無資料 | | | |")
            continue
        d, c, hi, vol, ma5, ma20, slope, bpos, vr = bars[-1]
        opened_bb = any(b[7] and b[7] > 100 for b in bars[-15:])
        if opened_bb:
            layer = "飆股守5日"
            status = "🟢 守住" if c >= (ma5 or 0) else "🔴 破5日"
        else:
            layer = "月線層"
            below2 = len(bars) >= 2 and bars[-1][1] < (bars[-1][5] or 0) and bars[-2][1] < (bars[-2][5] or 0)
            if slope is not None and slope < 0:
                status = "🔴 月線下彎"
            elif below2:
                status = "🔴 連2日破月線"
            elif c < (ma20 or 0):
                status = "🟡 破月線1日"
            else:
                status = "🟢 守住"
        vs_stop = f"{'🟢' if c > stop else '🔴'} {c} vs {stop}（{(c/stop-1)*100:+.1f}%）"
        pnl = (c / cost - 1) * 100
        # detector 警示 (3・5法則 / 日出日落 / 紅三兵)
        from frank import detectors as det
        dbars = [{"date": b[0], "close": b[1], "high": b[2], "volume": b[3],
                  "open": None, "low": None, "ma5": b[4], "ma20": b[5],
                  "ma20_slope": b[6], "bb_position": b[7], "vol_ratio_20": b[8]}
                 for b in bars]
        # open/low 需另查
        ohlc = conn.execute("""SELECT trade_date, open, low FROM standard_daily_bar
                               WHERE ticker=? AND trade_date BETWEEN '2026-05-01' AND '2026-07-03'
                               AND close>0 ORDER BY trade_date""", (tk,)).fetchall()
        om = {r[0]: (r[1], r[2]) for r in ohlc}
        for b in dbars:
            b["open"], b["low"] = om.get(b["date"], (None, None))
        warns = []
        r35 = det.frank_hot_stock_3_5_rule(dbars)
        if r35["alert"]:
            warns.append(f"3・5:{r35['alert']}")
        if det.frank_sunset_line(dbars)["signal"]:
            warns.append("日落⚠️")
        if det.frank_sunrise_line(dbars)["signal"]:
            warns.append("日出🟢")
        b3 = det.frank_bottom_3_soldiers(dbars)
        if b3["formed"] is False:
            warns.append("紅三兵失敗⚠️")
        wtxt = " ".join(warns) if warns else "—"
        lines.append(f"| {tk} {nm} | {sh:,} | {cost}（{pnl:+.1f}%）| {stop} | {c} | {layer} | {status} {wtxt} | {vs_stop} |")

    # ---------- (3) 下週標的掃描 ----------
    lines += ["", "## (3) 下週標的（7/3 訊號日 → 7/6 開盤週觀察）", ""]
    signals, watch = [], []
    for tk, e_date in elig.items():
        if e_date > "2026-07-03":
            continue
        bars = get_bars(conn, tk, "2026-05-01", "2026-07-03")
        if len(bars) < 25 or bars[-1][0] != "2026-07-03":
            continue
        ev = eval_day(bars, len(bars) - 1)
        if not ev:
            continue
        if ev["bo2"] and ev["chg"] < 5 and ev["score"] >= 1:
            signals.append((ev["score"], ev["chg"], tk, ev))
        else:
            # watch: ma20 上揚 + 在月線上 + 現在正回測 5MA (close <= ma5*1.02、還沒站回)
            d, c, hi, vol, ma5, ma20, slope, bpos, vr = bars[-1]
            if slope and slope > 0 and ma20 and c > ma20 and ma5 and c <= ma5 * 1.02:
                watch.append((tk, c, ma5, ma20))
    signals.sort(reverse=True)
    lines += ["### ✅ 7/3 收盤合格訊號（score≥1、買綠）", "",
              "| Rank | 標的 | 7/3 收 | 漲幅 | Score | 加分項 |", "|---|---|---|---|---|---|"]
    for i, (sc, chg, tk, ev) in enumerate(signals[:10], 1):
        lines.append(f"| {i} | {tk} {names.get(tk,'')} | {ev['close']} | {chg:+.1f}% | {sc} | {ev['detail']} |")
    if not signals:
        lines.append("| - | 7/3 無合格訊號 | | | | |")
    lines += ["", "### 👀 Watch（月線上揚、正回測 5MA、等站回訊號）", "",
              "| 標的 | 7/3 收 | 5MA | 月線 |", "|---|---|---|---|"]
    for tk, c, ma5, ma20 in sorted(watch)[:15]:
        lines.append(f"| {tk} {names.get(tk,'')} | {c} | {ma5:.1f} | {ma20:.1f} |")

    out = _REPO / "docs" / "frank" / "backtest" / "advisor_20260705.md"
    out.write_text("\n".join(lines))
    print(f"→ {out}")


if __name__ == "__main__":
    main()
