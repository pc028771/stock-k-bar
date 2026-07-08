#!/usr/bin/env python3
"""小時 K KD 低檔背離 watcher（純讀 poller cache、不打 API）

- 基底: stock_minute_kbar (至 7/3) → 小時 K → KD(9) warmup
- 今日: 每 30s 讀 /tmp/zhuli_cache/snapshot.json、累積小時 OHLC
- 事件(stdout): 每小時收 bar 印 KD + 低檔背離判定; 12:58 印京鼎尾盤判定; 13:35 自動結束
"""
import sys, json, time, datetime
from pathlib import Path

_REPO = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO / "scripts"))
from zhuli.db import get_conn

import os
TICKERS = dict(p.split(":") for p in os.environ.get("WATCH_TICKERS", "2327:國巨,1409:新纖").split(","))
SNAP = "/tmp/zhuli_cache/snapshot.json"
JQ_TRIG, JQ_HEAD = 329.8, 333.0   # 京鼎站回價 / 昨高


def hourly_bars(conn, tk, since="2026-06-10"):
    rows = conn.execute("""SELECT trade_datetime, open, high, low, close FROM stock_minute_kbar
                           WHERE ticker=? AND trade_datetime>=? ORDER BY trade_datetime""",
                        (tk, since)).fetchall()
    bars, cur = [], None
    for ts, o, h, l, c in rows:
        key = ts[:13]  # YYYY-MM-DD HH
        if cur and cur["k"] == key:
            cur["h"] = max(cur["h"], h); cur["l"] = min(cur["l"], l); cur["c"] = c
        else:
            if cur: bars.append(cur)
            cur = {"k": key, "o": o, "h": h, "l": l, "c": c}
    if cur: bars.append(cur)
    return bars


def kd(bars, n=9):
    k = d = 50.0
    out = []
    for i in range(len(bars)):
        lo = min(b["l"] for b in bars[max(0, i-n+1):i+1])
        hi = max(b["h"] for b in bars[max(0, i-n+1):i+1])
        rsv = (bars[i]["c"]-lo)/(hi-lo)*100 if hi > lo else 50
        k = k*2/3 + rsv/3; d = d*2/3 + k/3
        out.append((k, d))
    return out


def check_divergence(bars, kds):
    """近2波低檔背離: 今段創低、K 沒創低."""
    if len(bars) < 12: return None
    half = len(bars)//2 if len(bars) < 24 else len(bars)-12
    lo1 = min(b["l"] for b in bars[:half]); lo2 = min(b["l"] for b in bars[half:])
    k1 = min(k for k, _ in kds[:half]);     k2 = min(k for k, _ in kds[half:])
    if lo2 < lo1 and k2 > k1:
        return f"🟢 低檔背離成立 (價 {lo2}<{lo1}、K {k2:.0f}>{k1:.0f}) → 等日出+分歧"
    return f"未背離 (價低 {lo2} vs {lo1}、K低 {k2:.0f} vs {k1:.0f})"


def synth_fill(conn, tk, bars):
    """分K資料落後於日K時、用日K OHLC 合成小時bar 補洞."""
    last = bars[-1]["k"][:10] if bars else "2000-01-01"
    rows = conn.execute("""SELECT trade_date, open, high, low, close FROM standard_daily_bar
                           WHERE ticker=? AND trade_date>? AND close>0 ORDER BY trade_date""",
                        (tk, last)).fetchall()
    for d, o, h, l, c in rows:
        seq = [o, (o+h)/2, h, l, c] if c >= o else [o, (o+l)/2, l, h, c]
        for i, px in enumerate(seq):
            bars.append({"k": f"{d} {9+i:02d}", "o": px, "h": max(px, seq[min(i+1, 4)]),
                         "l": min(px, seq[min(i+1, 4)]), "c": px})
    return bars


def ema_state(bars):
    cs = [b["c"] for b in bars]
    if len(cs) < 15: return ""
    k10, k60 = 2/11, 2/61
    e10 = e60 = cs[0]
    e60s = []
    for v in cs:
        e10 = v*k10 + e10*(1-k10); e60 = v*k60 + e60*(1-k60)
        e60s.append(e60)
    up = e10 > e60
    slope = e60s[-1] - e60s[max(0, len(e60s)-7)]
    if up and slope > 0: return "🟢小時戰法一守住"
    if up: return "🟡上穿但60EMA未上揚"
    return "🔴小時戰法一破(被壓)"


def main():
    conn = get_conn()
    hist = {tk: synth_fill(conn, tk, hourly_bars(conn, tk))[-60:] for tk in TICKERS}
    live = {tk: None for tk in TICKERS}   # 今日當前小時 bar
    done_hours = {tk: set() for tk in TICKERS}
    jq_done = False
    print(f"armed: 基底 { {tk: len(v) for tk, v in hist.items()} } 根小時K、盯 {'/'.join(TICKERS.values())} + 京鼎12:58", flush=True)

    while True:
        now = datetime.datetime.now()
        if now.hour == 13 and now.minute >= 35:
            print("13:35 收盤、watcher 結束", flush=True); return
        try:
            d = json.load(open(SNAP))
        except Exception:
            time.sleep(10); continue
        hh = now.strftime("%Y-%m-%d %H")
        for tk, nm in TICKERS.items():
            s = d["data"].get(tk)
            if not s: continue
            c = s["close"]
            b = live[tk]
            if b and b["k"] != hh:  # 小時收 bar
                if b["k"] not in done_hours[tk]:
                    hist[tk].append(b); done_hours[tk].add(b["k"])
                    kds = kd(hist[tk])
                    kv, dv = kds[-1]
                    div = check_divergence(hist[tk][-24:], kds[-24:])
                    st = ema_state(hist[tk])
                    print(f"{b['k']}:00 收bar {tk} {nm} c={b['c']} K={kv:.0f} D={dv:.0f} | {st} | {div}", flush=True)
                live[tk] = None
            if live[tk] is None:
                live[tk] = {"k": hh, "o": c, "h": c, "l": c, "c": c}
            else:
                live[tk]["h"] = max(live[tk]["h"], c)
                live[tk]["l"] = min(live[tk]["l"], c)
                live[tk]["c"] = c
        if False and not jq_done and (now.hour, now.minute) >= (12, 58):
            jq = d["data"].get("3413")
            if jq:
                cl = jq["close"]
                if cl > JQ_HEAD:
                    v = f"✅✅ >{JQ_HEAD} 站回+頭頭高 score1 → 尾盤可進、停損314"
                elif cl > JQ_TRIG:
                    v = f"🟡 >{JQ_TRIG} 站回但未過昨高333、score可能0 → 嚴格skip/自行斟酌"
                else:
                    v = f"❌ <{JQ_TRIG} 未站回 → 今日空手、明日觸發價下修"
                print(f"12:58 京鼎判定: 現價 {cl} ({jq['change_rate']:+.2f}%) {v}", flush=True)
            jq_done = True
        time.sleep(30)


if __name__ == "__main__":
    main()
