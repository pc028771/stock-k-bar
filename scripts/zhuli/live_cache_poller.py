#!/usr/bin/env python3
"""背景輪詢即時報價 → 寫 cache 檔、讓 Claude 讀檔不用呼叫 API。
資料源: Fubon get_snapshot_quotes_map (整市場 ~1s、真即時)、FinMind fallback。
盤中每 ~30s、盤後每 10min。輸出:
  /tmp/zhuli_cache/snapshot.json   — 整市場即時價 (ticker → {...})、任何股都查得到 (用 python filter、別整檔 dump)
  /tmp/zhuli_cache/positions.json  — HELD 預算好的損益/距停損/破停損
  /tmp/zhuli_cache/watchlist.json  — HELD + WATCH + scanner watchlist 的即時價/漲跌
"""
import os, sys, time, json, glob
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from zhuli.positions import HELD, WATCH

CACHE = '/tmp/zhuli_cache'
os.makedirs(CACHE, exist_ok=True)

def write_atomic(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)

def scanner_watchlist():
    """最新 daily_watchlist 的 candidates ticker。"""
    fs = sorted(glob.glob(os.path.join(os.path.dirname(__file__), '../../docs/主力大課程/daily_watchlist/*.json')))
    if not fs:
        return set()
    try:
        d = json.load(open(fs[-1]))
        return {str(c.get('ticker')) for c in d.get('candidates', []) if c.get('ticker')}
    except Exception:
        return set()

# Fubon client (主)
_fc = None
def fubon_map():
    global _fc
    if _fc is None:
        from common.clients.fubon_client import FubonClient
        _fc = FubonClient()
    m = _fc.get_snapshot_quotes_map(markets=('TSE', 'OTC'))
    return {str(k): v for k, v in m.items()}

def finmind_map():  # fallback
    import requests
    tok = os.environ.get('FINMIND_TOKEN')
    r = requests.get('https://api.finmindtrade.com/api/v4/taiwan_stock_tick_snapshot', params={'token': tok}, timeout=30)
    out = {}
    for x in r.json().get('data', []):
        tk = str(x.get('stock_id', ''))
        out[tk] = {'close': x.get('close'), 'open': x.get('open'), 'high': x.get('high'),
                   'low': x.get('low'), 'change_rate': x.get('change_rate'), 'total_volume': x.get('total_volume')}
    return out

def poll_once():
    src = 'fubon'
    try:
        snap = fubon_map()
        if not snap:
            raise RuntimeError('fubon empty')
    except Exception:
        snap = finmind_map(); src = 'finmind'
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    write_atomic(f'{CACHE}/snapshot.json', {'ts': ts, 'src': src, 'count': len(snap), 'data': snap})

    def px(tk):
        s = snap.get(tk, {})
        return float(s.get('close') or 0), float(s.get('change_rate') or 0)

    # HELD
    rows, tot = [], 0.0
    for h in HELD:
        cl, cr = px(h['ticker'])
        cost = h.get('cost', 0); stop = h.get('stop', 0); sh = h.get('shares', 0)
        pnl = (cl - cost) * sh if cl else 0; tot += pnl
        rows.append({'ticker': h['ticker'], 'name': h['name'], 'close': cl, 'change_rate': cr,
                     'cost': cost, 'shares': sh, 'pnl': round(pnl), 'stop': stop,
                     'dist_stop_pct': round((cl - stop) / stop * 100, 1) if stop and cl else None,
                     'broke_stop': bool(stop and cl and cl < stop)})
    write_atomic(f'{CACHE}/positions.json', {'ts': ts, 'src': src, 'total_pnl': round(tot), 'holdings': rows})

    # watchlist = HELD + WATCH + scanner
    wl = []
    seen = set()
    for tag, items in (('HELD', HELD), ('WATCH', WATCH)):
        for it in items:
            tk = it['ticker']
            if tk in seen: continue
            seen.add(tk); cl, cr = px(tk)
            wl.append({'ticker': tk, 'name': it.get('name', ''), 'tag': tag, 'close': cl, 'change_rate': cr})
    for tk in scanner_watchlist():
        if tk in seen: continue
        seen.add(tk); cl, cr = px(tk)
        wl.append({'ticker': tk, 'name': '', 'tag': 'scanner', 'close': cl, 'change_rate': cr})
    write_atomic(f'{CACHE}/watchlist.json', {'ts': ts, 'src': src, 'count': len(wl), 'items': wl})
    return len(snap), round(tot), src

def in_market_hours():
    lt = time.localtime()
    if lt.tm_wday >= 5:
        return False
    hm = lt.tm_hour * 60 + lt.tm_min
    return 9 * 60 <= hm <= 13 * 60 + 35

if __name__ == '__main__':
    while True:
        live = in_market_hours()
        try:
            n, tot, src = poll_once()
            print(f'{time.strftime("%H:%M:%S")} [{src}] {n}檔 持倉{tot:+,} {"盤中" if live else "盤後"}', flush=True)
        except Exception as e:
            print(f'{time.strftime("%H:%M:%S")} ERR {e}', flush=True)
        time.sleep(30 if live else 600)
