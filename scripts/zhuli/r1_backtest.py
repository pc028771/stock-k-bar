"""R1 backtest — 6/16 全市場 (watchlist 80 檔) 「首攻 10 分鐘 rule」驗證.

R1 spec (老師 6/16 復盤分K):
  「必須要 10 分鐘之內拉上去漲停、不然就是很容易被出貨」

簡化定義 (近似 Ch5-3 首攻):
  - 9:10 ~ 9:30 內某根 5K open 過 9:00-9:09 區間高點 = 首攻 fire
  - fire 後 10 分內 5K high ≥ 漲停價 (prev_close * 1.095) = 鎖漲停
  - 沒鎖漲停 = R1 predict「被出貨」、看當日 close

Outcome (R1 對/錯/中性):
  - 對: 收盤 vs fire 後 10 分高 跌 ≥ -3%
  - 中性: -1% ~ -3% 或 0~+3%
  - 錯: 收盤 ≥ fire 高 +3% (or 鎖漲停收盤)
"""
import sqlite3
import json
from pathlib import Path

DATE = "2026-06-16"
DB = Path.home() / ".four_seasons" / "data.sqlite"

WL = json.load(open(
    "/Users/howard/Repository/stock-k-bar/docs/主力大課程/"
    f"daily_watchlist/{DATE}.json"))
TICKERS = [c['ticker'] for c in WL['candidates']]

con = sqlite3.connect(str(DB))

# Get prev_close (6/13 Fri)
prev_closes = dict(con.execute(
    "SELECT ticker, close FROM standard_daily_bar "
    "WHERE ticker IN ({}) AND trade_date='2026-06-15'".format(
        ','.join(['?']*len(TICKERS))), TICKERS).fetchall())

results = []
fire_count = 0
limit_hit_count = 0
correct = 0
wrong = 0
neutral = 0
no_prev_close = 0
no_fire = 0

for tk in TICKERS:
    prev_c = prev_closes.get(tk)
    if not prev_c:
        no_prev_close += 1
        continue
    rows = con.execute(
        "SELECT trade_datetime, open, high, low, close FROM stock_minute_kbar "
        "WHERE ticker=? AND trade_datetime LIKE ? ORDER BY trade_datetime",
        (tk, f"{DATE}%")).fetchall()
    if not rows or len(rows) < 30:
        continue
    # Build 1-min bars dict by HH:MM
    bars = {r[0][-5:]: r for r in rows}
    # 0900-0909 high
    early_high = max((r[2] for r in rows if r[0][-5:] < "09:10"),
                     default=None)
    if early_high is None:
        continue
    # Find first 1-min bar in 09:10-09:30 with high > early_high (首攻 proxy)
    fire_t = None
    fire_high = None
    for r in rows:
        hhmm = r[0][-5:]
        if hhmm < "09:10" or hhmm > "09:30":
            continue
        if r[2] > early_high:
            fire_t = hhmm
            fire_high = r[2]
            break
    if not fire_t:
        no_fire += 1
        continue
    fire_count += 1

    # 10 分內鎖漲停?
    limit_price = prev_c * 1.095
    fire_hh, fire_mm = int(fire_t[:2]), int(fire_t[3:])
    fire_min_total = fire_hh * 60 + fire_mm
    locked = False
    high_after_fire = fire_high
    for r in rows:
        hhmm = r[0][-5:]
        hh, mm = int(hhmm[:2]), int(hhmm[3:])
        mt = hh * 60 + mm
        if mt < fire_min_total or mt > fire_min_total + 10:
            continue
        if r[2] >= limit_price:
            locked = True
        if r[2] > high_after_fire:
            high_after_fire = r[2]
    if locked:
        limit_hit_count += 1
        continue  # R1 不 fire (鎖漲停 = 沒被出貨)
    # R1 predict 被出貨 → 看當日收盤 vs fire 後高
    close_row = rows[-1]
    close_p = close_row[4]
    drop_pct = (close_p / high_after_fire - 1) * 100
    if drop_pct <= -3:
        verdict = "對"
        correct += 1
    elif drop_pct >= 3:
        verdict = "錯"
        wrong += 1
    else:
        verdict = "中性"
        neutral += 1
    results.append((tk, fire_t, prev_c, fire_high, high_after_fire,
                    close_p, round(drop_pct, 2), verdict))

con.close()

print(f"\n=== R1 6/16 backtest (watchlist {len(TICKERS)} 檔) ===")
print(f"prev_close missing: {no_prev_close}")
print(f"no fire (09:10-09:30 未過 09:00-09:09 高): {no_fire}")
print(f"Fire 數: {fire_count}")
print(f"  - 10 分內鎖漲停 (R1 不適用): {limit_hit_count}")
print(f"  - 未鎖漲停 (R1 predict 被出貨): {len(results)}")
print(f"    對 (跌 ≥ -3%): {correct}")
print(f"    中性 (-3%~+3%): {neutral}")
print(f"    錯 (漲 ≥ +3%): {wrong}")
if results:
    rate = correct / len(results) * 100
    print(f"    R1 命中率: {rate:.1f}%")

print("\n=== 明細 (sorted by drop_pct) ===")
print(f"{'tk':6s} {'fire':6s} {'prev_c':>8s} {'fire_h':>8s} "
      f"{'后高':>8s} {'收盤':>8s} {'跌幅%':>8s} {'判':4s}")
for r in sorted(results, key=lambda x: x[6]):
    print(f"{r[0]:6s} {r[1]:6s} {r[2]:8.2f} {r[3]:8.2f} {r[4]:8.2f} "
          f"{r[5]:8.2f} {r[6]:8.2f} {r[7]}")
