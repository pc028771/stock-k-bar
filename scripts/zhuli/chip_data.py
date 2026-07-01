#!/usr/bin/env python3
"""籌碼資料存取: DB 先、缺的 fallback FinMind + 寫回 DB。
三大法人 (institutional_investors) — 單位「張」、欄位 foreign_net/sitc_net。

用法:
  from zhuli.chip_data import get_institutional, backfill_institutional
  rows = get_institutional('2885', '2026-06-23', '2026-06-30')  # [(date, foreign_net, sitc_net), ...]
  backfill_institutional('2026-06-30')  # 確保某日全市場法人進 DB
"""
import os, sys, sqlite3
from datetime import date as _date, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from zhuli.db import MAIN_DB


def _api():
    from FinMind.data import DataLoader
    a = DataLoader()
    tok = os.environ.get('FINMIND_TOKEN')
    if tok:
        a.login_by_token(api_token=tok)
    return a


def backfill_institutional(d, conn=None, force=False):
    """確保某日(d)全市場三大法人在 DB；缺就抓 FinMind 寫入。回傳新增檔數。
    force=True: 強制重抓 (三大法人 EOD 有「初步→確定」修正、重抓覆蓋、修正投信等)。"""
    own = conn is None
    c = conn or sqlite3.connect(str(MAIN_DB))
    have = c.execute("SELECT COUNT(*) FROM institutional_investors WHERE trade_date=?", (d,)).fetchone()[0]
    if have > 100 and not force:  # 已完整載入 (force 時仍重抓、蓋掉初步版)
        if own:
            c.close()
        return 0
    df = _api().taiwan_stock_institutional_investors(start_date=d, end_date=d)  # 全市場
    ins = 0
    if df is not None and len(df):
        # 只留 stock_info 裡的股票 (上市櫃主板、~2000)、排除權證/興櫃等垃圾、對齊既有慣例
        universe = {r[0] for r in c.execute("SELECT DISTINCT ticker FROM stock_info")}
        c.execute("DELETE FROM institutional_investors WHERE trade_date=?", (d,))  # 清乾淨避免重複
        for sid, g in df.groupby('stock_id'):
            if str(sid) not in universe:
                continue
            dd = {r['name']: (r['buy'], r['sell']) for _, r in g.iterrows()}
            fb, fs = dd.get('Foreign_Investor', (0, 0))
            ib, isl = dd.get('Investment_Trust', (0, 0))
            c.execute(
                "INSERT INTO institutional_investors "
                "(ticker,trade_date,foreign_buy,foreign_sell,foreign_net,sitc_buy,sitc_sell,sitc_net) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (str(sid), d, fb / 1000, fs / 1000, (fb - fs) / 1000, ib / 1000, isl / 1000, (ib - isl) / 1000))
            ins += 1
        c.commit()
    if own:
        c.close()
    return ins


def get_institutional(ticker, start, end):
    """三大法人 DB 先、end 超過 DB 最新日就補 FinMind + 寫回。回傳 [(date, foreign_net, sitc_net)]。"""
    c = sqlite3.connect(str(MAIN_DB))
    db_max = c.execute("SELECT MAX(trade_date) FROM institutional_investors").fetchone()[0]
    if db_max and end > db_max:  # 只補近期缺口、舊資料 DB 已有
        d = _date.fromisoformat(db_max) + timedelta(days=1)
        e = _date.fromisoformat(end)
        while d <= e:
            if d.weekday() < 5:  # 跳週末 (FinMind 非交易日回空、backfill 自動略過)
                try:
                    backfill_institutional(d.isoformat(), c)
                except Exception:
                    pass
            d += timedelta(days=1)
    # 🔴 三大法人有「初步→確定」修正: end 若在最近 3 天內、每天 force 重抓一次確定版 (flag 檔防重複)
    try:
        import os as _os
        end_d = _date.fromisoformat(end)
        recent = (_date.today() - end_d).days <= 3 if _date.today() >= end_d else False
        if recent:
            flag = f'/tmp/zhuli_cache/instforce_{end}_{_date.today().isoformat()}.flag'
            if not _os.path.exists(flag):
                backfill_institutional(end, c, force=True)
                _os.makedirs('/tmp/zhuli_cache', exist_ok=True)
                open(flag, 'w').close()
    except Exception:
        pass
    rows = c.execute(
        "SELECT trade_date,foreign_net,sitc_net FROM institutional_investors "
        "WHERE ticker=? AND trade_date BETWEEN ? AND ? ORDER BY trade_date",
        (ticker, start, end)).fetchall()
    c.close()
    return rows


# ───────────────────────── 分點 (broker_daily) ─────────────────────────

def _ensure_broker_tables(c):
    c.execute("""CREATE TABLE IF NOT EXISTS broker_daily (
        ticker TEXT, trade_date TEXT, trader_id TEXT, trader_name TEXT,
        buy REAL, sell REAL, net REAL, price REAL,
        UNIQUE(ticker, trade_date, trader_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS broker_fetch_log (
        entity TEXT, trade_date TEXT, PRIMARY KEY(entity, trade_date))""")


def _store_broker(c, df, date):
    """df: securities_trader/_id, stock_id, price, buy, sell (股) → aggregate by trader、寫入 broker_daily (張)。"""
    import pandas as pd
    df = df.copy()
    df['buy'] = df['buy'] / 1000
    df['sell'] = df['sell'] / 1000
    df['vol'] = df['buy'] + df['sell']
    g = df.groupby(['stock_id', 'securities_trader_id', 'securities_trader'], as_index=False).agg(
        buy=('buy', 'sum'), sell=('sell', 'sum'),
        pv=('price', lambda s: 0), vol=('vol', 'sum'))
    # 加權均價另算 (groupby apply 太慢、改用 sum(price*vol)/sum(vol))
    df['pv'] = df['price'] * df['vol']
    pv = df.groupby(['stock_id', 'securities_trader_id'], as_index=False).agg(pv=('pv', 'sum'), vsum=('vol', 'sum'))
    pv['price'] = pv['pv'] / pv['vsum'].clip(lower=1e-9)
    g = g.merge(pv[['stock_id', 'securities_trader_id', 'price']], on=['stock_id', 'securities_trader_id'], how='left')
    for _, r in g.iterrows():
        c.execute("INSERT OR REPLACE INTO broker_daily (ticker,trade_date,trader_id,trader_name,buy,sell,net,price) "
                  "VALUES (?,?,?,?,?,?,?,?)",
                  (str(r['stock_id']), date, str(r['securities_trader_id']), r['securities_trader'],
                   float(r['buy']), float(r['sell']), float(r['buy'] - r['sell']), float(r['price'])))


def get_broker_by_stock(ticker, date):
    """某股某日分點 DB 先、缺補 FinMind+寫回。回傳 [(trader_name, net張, price)] 依淨買超排序。"""
    c = sqlite3.connect(str(MAIN_DB))
    _ensure_broker_tables(c)
    ent = f'stock:{ticker}'
    if not c.execute("SELECT 1 FROM broker_fetch_log WHERE entity=? AND trade_date=?", (ent, date)).fetchone():
        df = _api().taiwan_stock_trading_daily_report(stock_id=ticker, date=date)
        if df is not None and len(df):
            _store_broker(c, df, date)
            c.execute("INSERT OR REPLACE INTO broker_fetch_log VALUES (?,?)", (ent, date))
            c.commit()
    rows = c.execute("SELECT trader_name,net,price FROM broker_daily WHERE ticker=? AND trade_date=? ORDER BY net DESC",
                     (ticker, date)).fetchall()
    c.close()
    return rows


def get_broker_by_trader(trader_id, date):
    """某分點某日買賣 DB 先、缺補 FinMind+寫回。回傳 [(ticker, net張, price)] 依淨買超排序。"""
    c = sqlite3.connect(str(MAIN_DB))
    _ensure_broker_tables(c)
    ent = f'trader:{trader_id}'
    if not c.execute("SELECT 1 FROM broker_fetch_log WHERE entity=? AND trade_date=?", (ent, date)).fetchone():
        df = _api().taiwan_stock_trading_daily_report(securities_trader_id=trader_id, date=date)
        if df is not None and len(df):
            _store_broker(c, df, date)
            c.execute("INSERT OR REPLACE INTO broker_fetch_log VALUES (?,?)", (ent, date))
            c.commit()
    rows = c.execute("SELECT ticker,net,price FROM broker_daily WHERE trader_id=? AND trade_date=? ORDER BY net DESC",
                     (trader_id, date)).fetchall()
    c.close()
    return rows


if __name__ == '__main__':
    # CLI: backfill 2026-06-30 / inst 2885 start end / broker 2885 2026-06-29
    if len(sys.argv) >= 3 and sys.argv[1] == 'backfill':
        print('新增', backfill_institutional(sys.argv[2]), '檔')
    elif len(sys.argv) >= 4 and sys.argv[1] == 'broker':
        for nm, net, px in get_broker_by_stock(sys.argv[2], sys.argv[3])[:10]:
            print(f'  {nm:<12} {net:+,.0f}張 @{px:.1f}')
    elif len(sys.argv) >= 4:
        for d, f, s in get_institutional(sys.argv[1], sys.argv[2], sys.argv[3]):
            print(f'{d} 外{f:+,.0f} 投{s:+,.0f}')
