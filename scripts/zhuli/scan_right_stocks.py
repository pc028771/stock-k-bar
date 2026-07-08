#!/usr/bin/env python3
"""「對的股票」掃描 — 尼克 7/8 法人籌碼課原話:
「大盤漲的時候它有跟著漲、大盤跌的時候它有跌但很快就V了、或者大盤跌的時候他沒跌
  = 你買到正確東西的特性、以股價來說話」
「櫃買止穩的時候、他們可以第一個跳回所有均線之上、那就是對的東西、你可以這樣去記錄」

用法:
  python3 scripts/zhuli/scan_right_stocks.py                # 跑全部殺盤測試日、輸出累積排行
  python3 scripts/zhuli/scan_right_stocks.py --add 2026-07-09   # 新增殺盤測試日後跑

每個「殺盤測試日 T」的通過條件 (T+1 收盤判定):
  (T日抗跌: 跌幅 > -1%)  OR  (T+1 V回: 收盤 >= T-1 收盤×0.998)
  AND 站回所有均線 (T+1 收 > MA5/MA10/MA20)
  AND 趨勢向上 (收 > MA20 > MA60)、距季線 < +50% (排噴過頭)、量 > 1500 張
輸出: docs/主力大課程/right_stocks_report.md (排行=過測次數、附最新位階)
"""
import json
import sqlite3
import sys
from pathlib import Path

_REPO = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO / 'scripts'))
from zhuli.db import MAIN_DB

STATE = _REPO / 'docs/主力大課程/right_stocks_tests.json'   # 殺盤測試日清單
REPORT = _REPO / 'docs/主力大課程/right_stocks_report.md'


def load_tests() -> list[str]:
    if STATE.exists():
        return json.loads(STATE.read_text())
    return ['2026-07-07']  # 第一次殺盤測試日 (大盤 -2.7%)


def trading_days(c, around: str, n_before=1, n_after=1):
    """回傳 (前一交易日, 測試日, 後一交易日)、以 DB 實際日期為準。"""
    days = [r[0] for r in c.execute(
        "SELECT DISTINCT trade_date FROM standard_daily_bar WHERE ticker='2330' ORDER BY trade_date")]
    if around not in days:
        return None
    i = days.index(around)
    if i < n_before or i + n_after >= len(days):
        return None
    return days[i - 1], around, days[i + 1]


def scan_one_test(c, test_date: str) -> set[str]:
    tri = trading_days(c, test_date)
    if not tri:
        return set()
    d_prev, d_t, d_next = tri
    rows = c.execute(
        "SELECT ticker,trade_date,close,volume,ma5,ma10,ma20,ma60 FROM standard_daily_bar "
        "WHERE trade_date IN (?,?,?)", (d_prev, d_t, d_next)).fetchall()
    data: dict[str, dict] = {}
    for tk, dt, cl, v, m5, m10, m20, m60 in rows:
        data.setdefault(tk, {})[dt] = (cl, v, m5, m10, m20, m60)
    passed = set()
    for tk, d in data.items():
        if len(d) < 3:
            continue
        c0 = d[d_prev][0]
        c1 = d[d_t][0]
        c2, v2, m5, m10, m20, m60 = d[d_next]
        if not all((c0, c1, c2, m5, m10, m20, m60)) or (v2 or 0) / 1000 < 1500:
            continue
        抗跌 = (c1 / c0 - 1) > -0.01
        v回 = c2 >= c0 * 0.998
        站回 = c2 > m5 and c2 > m10 and c2 > m20
        趨勢 = c2 > m20 > m60 and (c2 / m60 - 1) < 0.5
        if (抗跌 or v回) and 站回 and 趨勢:
            passed.add(tk)
    return passed


def main():
    if '--add' in sys.argv:
        d = sys.argv[sys.argv.index('--add') + 1]
        tests = load_tests()
        if d not in tests:
            tests.append(d)
            STATE.write_text(json.dumps(sorted(tests), ensure_ascii=False))
            print(f'新增殺盤測試日 {d}')
    tests = load_tests()
    STATE.write_text(json.dumps(sorted(tests), ensure_ascii=False))

    c = sqlite3.connect(str(MAIN_DB))
    nm = {r[0]: r[1] for r in c.execute('SELECT ticker,stock_name FROM stock_info')}
    try:
        sec = json.loads((_REPO / 'docs/主力大課程/teacher_sector_tickers.json').read_text())
        tuni = {str(x) for v in sec.values() if isinstance(v, list) for x in v}
    except Exception:
        tuni = set()

    score: dict[str, int] = {}
    valid_tests = []
    for t in tests:
        p = scan_one_test(c, t)
        if p:
            valid_tests.append(t)
            for tk in p:
                score[tk] = score.get(tk, 0) + 1

    # 最新位階
    latest = c.execute("SELECT MAX(trade_date) FROM standard_daily_bar").fetchone()[0]
    pos = {r[0]: (r[1], r[2]) for r in c.execute(
        "SELECT ticker, close, ma20 FROM standard_daily_bar WHERE trade_date=?", (latest,))}

    ranked = sorted(score.items(), key=lambda x: (-x[1], x[0]))
    lines = [f'# 「對的股票」記錄 (尼克 7/8 判別法、自動掃描)',
             f'- 殺盤測試日: {", ".join(valid_tests)} | 更新至 {latest}',
             f'- 條件: 殺盤日抗跌或隔日V回 + 站回所有均線 + 趨勢向上',
             '',
             '| 過測 | 標的 | 收盤 | 距MA20 | 尼克池 |',
             '|---|---|---|---|---|']
    for tk, sc in ranked[:40]:
        cl, m20 = pos.get(tk, (None, None))
        d20 = f'{(cl / m20 - 1) * 100:+.0f}%' if cl and m20 else '—'
        lines.append(f'| {sc}/{len(valid_tests)} | {tk} {nm.get(tk, "?")} | {cl} | {d20} | {"★" if tk in tuni else ""} |')
    REPORT.write_text('\n'.join(lines), encoding='utf-8')
    print(f'{len(score)} 檔過至少1次 | 測試日 {len(valid_tests)} 個 | 報告: {REPORT}')
    for tk, sc in ranked[:15]:
        print(f'  {sc}/{len(valid_tests)} {tk} {nm.get(tk, "?")} {"★" if tk in tuni else ""}')
    c.close()


if __name__ == '__main__':
    main()
