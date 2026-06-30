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


def backfill_institutional(d, conn=None):
    """確保某日(d)全市場三大法人在 DB；缺就抓 FinMind 寫入。回傳新增檔數。"""
    own = conn is None
    c = conn or sqlite3.connect(str(MAIN_DB))
    have = c.execute("SELECT COUNT(*) FROM institutional_investors WHERE trade_date=?", (d,)).fetchone()[0]
    if have > 100:  # 已完整載入
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
    rows = c.execute(
        "SELECT trade_date,foreign_net,sitc_net FROM institutional_investors "
        "WHERE ticker=? AND trade_date BETWEEN ? AND ? ORDER BY trade_date",
        (ticker, start, end)).fetchall()
    c.close()
    return rows


if __name__ == '__main__':
    # CLI: python chip_data.py backfill 2026-06-30   /   python chip_data.py 2885 2026-06-23 2026-06-30
    if len(sys.argv) >= 3 and sys.argv[1] == 'backfill':
        print('新增', backfill_institutional(sys.argv[2]), '檔')
    elif len(sys.argv) >= 4:
        for d, f, s in get_institutional(sys.argv[1], sys.argv[2], sys.argv[3]):
            print(f'{d} 外{f:+,.0f} 投{s:+,.0f}')
