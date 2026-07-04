#!/usr/bin/env python3
"""無聊股 scanner — 老師「不能盯盤就做、順均線無聊緩漲」那種。

課程依據 (老師原話):
- 大前提: 「貴買需要在所有均線之上、均線要上揚」(11/9 直播 / 6/28 市場資訊報)
- 「軍線糾結在最接近的地方了、很適合去攻擊」(4/29 法人籌碼) → 糾結=攻擊setup、不是轉弱
- 「站上所有均線、代表踩住了、低點不能跌破、外資也有進來買」(6/21)

設計 (user 2026-07-02 校正):
- HARD: 收盤站在所有均線之上 (老師大前提) — 不要求 MA5>MA10>MA20 嚴格排列
- 嚴格多頭排列改「加分項」；均線糾結 + 外資買 = 加分 (洗盤蓄勢)
- 位階不高 (距季<20%) + 低波動 (無聊) + 流動性 + 排除處置

用法: python3 scripts/zhuli/scan_boring_stocks.py [--all]  (預設老師universe、--all 全市場)
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).parent.parent.parent
for _p in (str(_REPO), str(_REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import json
import sqlite3
import statistics

from zhuli.db import MAIN_DB

# 門檻 (課程外自訂數值、可調)
MAX_DIST_MA60 = 0.20      # 距季線 < 20% (位階不高)
MAX_VOL_STD = 4.0         # 近20日日漲跌幅 std < 4% (無聊/低波動)
MAX_SINGLE_DAY = 7.0      # 近20日無單日 > +7% (不暴衝)
MIN_VOL_LOT = 1000        # 日均量 > 1000張 (流動性)
CLUSTER_PCT = 0.03        # 均線糾結: max-min(MA5,10,20)/現價 < 3%


def _teacher_universe() -> set[str]:
    tks: set[str] = set()
    p = _REPO / "docs/主力大課程/teacher_sector_tickers.json"
    if p.exists():
        for v in json.loads(p.read_text(encoding="utf-8")).values():
            if isinstance(v, list):
                tks.update(str(t) for t in v)
    return tks


def scan(universe: set[str] | None = None) -> list[dict]:
    c = sqlite3.connect(str(MAIN_DB))
    latest = c.execute("SELECT MAX(trade_date) FROM standard_daily_bar").fetchone()[0]
    teacher = _teacher_universe()
    tickers = universe if universe is not None else teacher
    if not tickers:  # fallback 全市場
        tickers = {r[0] for r in c.execute("SELECT DISTINCT ticker FROM stock_info")}

    out: list[dict] = []
    for tk in tickers:
        rows = c.execute(
            "SELECT trade_date,open,high,low,close,volume,ma5,ma10,ma20,ma60 "
            "FROM standard_daily_bar WHERE ticker=? ORDER BY trade_date DESC LIMIT 21",
            (tk,)).fetchall()
        if len(rows) < 21:
            continue
        dt, o, h, l, cl, vol, m5, m10, m20, m60 = rows[0]
        if not all((cl, m5, m10, m20, m60)):
            continue

        # HARD 1: 收盤站在所有均線之上 (老師大前提)
        if not (cl > m5 and cl > m10 and cl > m20 and cl > m60):
            continue
        # HARD 2: 位階不高
        if (cl / m60 - 1) > MAX_DIST_MA60:
            continue
        # HARD 3: MA20 斜率 > 0 (趨勢向上/整理沒破)
        m20_prev = rows[5][8]
        if not m20_prev or m20 <= m20_prev:
            continue
        # HARD 4: 低波動 + 無暴衝 (近20日日漲跌幅)
        chgs = [(rows[i][4] / rows[i + 1][4] - 1) * 100 for i in range(20) if rows[i + 1][4]]
        if not chgs:
            continue
        vol_std = statistics.pstdev(chgs)
        if vol_std >= MAX_VOL_STD or max(chgs) > MAX_SINGLE_DAY:
            continue
        # HARD 5: 流動性
        avg_vol = sum(r[5] for r in rows[:5]) / 5 / 1000
        if avg_vol < MIN_VOL_LOT:
            continue

        # ── 加分項 (排序用、非門檻) ──
        score = 0
        tags = []
        if m5 > m10 > m20:                      # 嚴格多頭排列 (加分、非必要)
            score += 2; tags.append("多頭排列")
        cluster = (max(m5, m10, m20) - min(m5, m10, m20)) / cl
        if cluster < CLUSTER_PCT:               # 均線糾結=攻擊setup (老師4/29)
            score += 2; tags.append(f"均線糾結{cluster*100:.1f}%")
        # 外資近5日 (加分、籌碼支撐)
        fnet = None
        try:
            from zhuli.chip_data import get_institutional
            import datetime as _d
            start = (_d.date.fromisoformat(dt) - _d.timedelta(days=9)).isoformat()
            inst = get_institutional(tk, start, dt)
            fnet = sum(x[1] or 0 for x in inst[-5:])
            if fnet > 0:
                score += 2; tags.append(f"外資5d+{fnet:.0f}")
        except Exception:
            pass
        if tk in teacher:
            score += 1; tags.append("老師族群")
        dist5 = (cl / m5 - 1) * 100
        if dist5 < 2:                            # 越貼MA5越好
            score += 1
        if vol_std < 2:                          # 越無聊越好
            score += 1
        # 波段趨勢向上 (user 2026-07-02: 2-4週穩穩向上、期望~8%、元大金型)
        # = 近20日漲幅 +2~+20% (穩漲非暴衝非跌) + 低點墊高 (近10低 > 前10低)
        seg_up = False
        c20 = rows[19][4] if len(rows) >= 20 else None
        if c20:
            ret20 = (cl / c20 - 1) * 100
            recent_low = min(r[3] for r in rows[:10])
            prior_low = min(r[3] for r in rows[10:20])
            if 2 <= ret20 <= 20 and recent_low > prior_low:
                seg_up = True
                score += 2
                tags.append(f"波段向上{ret20:+.0f}%")

        out.append({
            "ticker": tk, "close": cl, "dist_ma5": dist5,
            "dist_ma20": (cl / m20 - 1) * 100, "dist_ma60": (cl / m60 - 1) * 100,
            "vol_std": vol_std, "score": score, "fnet5": fnet, "tags": tags,
        })
    c.close()
    # 排序: score desc, 波動 asc
    out.sort(key=lambda x: (-x["score"], x["vol_std"]))
    return out


if __name__ == "__main__":
    if "--all" in sys.argv:
        _cc = sqlite3.connect(str(MAIN_DB))
        uni = {r[0] for r in _cc.execute("SELECT DISTINCT ticker FROM stock_info")}
        _cc.close()
    else:
        uni = _teacher_universe()
    res = scan(uni)
    nm = {}
    _c = sqlite3.connect(str(MAIN_DB))
    for r in _c.execute("SELECT ticker,stock_name FROM stock_info"):
        nm[r[0]] = r[1]
    _c.close()
    print(f"無聊股 {len(res)} 檔 (站均線上+位階低+低波動、糾結/外資/多頭排列=加分)")
    print(f"{'代號名稱':<14}{'現價':>8}{'距MA5':>7}{'距季':>6}{'波動':>6}{'分':>4}  加分")
    for r in res[:20]:
        print(f"{r['ticker']} {nm.get(r['ticker'],'?'):<8}{r['close']:>8.1f}"
              f"{r['dist_ma5']:>+6.1f}%{r['dist_ma60']:>+5.0f}%{r['vol_std']:>5.1f}%"
              f"{r['score']:>4}  {'/'.join(r['tags'])}")
