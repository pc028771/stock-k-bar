"""
reverse_engineer_uniform_ma.py
從老師 44 檔 snapshot vs 全市場 434 均線順向
找出基本指標差異特徵、推回老師選股條件

用法:
    python3 scripts/zhuli/tools/reverse_engineer_uniform_ma.py

DB: ~/.four_seasons/data.sqlite
Target date: 2026-06-03
"""

import sqlite3
import json
from pathlib import Path
from collections import Counter, defaultdict

DB_PATH = Path.home() / ".four_seasons/data.sqlite"
TEACHER_JSON = Path("docs/主力大課程/teacher_44_uniform_ma_20260604.json")
TARGET_DATE = "2026-06-03"


def load_teacher_tickers():
    with open(TEACHER_JSON) as f:
        data = json.load(f)
    return set(data["tickers"])


def connect():
    return sqlite3.connect(str(DB_PATH))


def get_trading_dates(conn, n=65):
    c = conn.cursor()
    c.execute(f"""
        SELECT DISTINCT trade_date FROM standard_daily_bar
        WHERE trade_date <= ? ORDER BY trade_date DESC LIMIT {n}
    """, (TARGET_DATE,))
    return [r[0] for r in c.fetchall()]


def get_universe(conn):
    """全市場 434 均線順向"""
    c = conn.cursor()
    c.execute("""
        SELECT ticker FROM standard_daily_bar
        WHERE trade_date=?
        AND ma5 IS NOT NULL AND ma10 IS NOT NULL AND ma20 IS NOT NULL AND ma60 IS NOT NULL
        AND ma5>ma10 AND ma10>ma20 AND ma20>ma60
        AND close>=ma5
    """, (TARGET_DATE,))
    return {r[0] for r in c.fetchall()}


def get_daily_data(conn, tickers):
    """取得 6/3 當日基本資料"""
    ph = ",".join(["?"] * len(tickers))
    c = conn.cursor()
    c.execute(f"""
        SELECT s.ticker, s.close, s.volume, s.ma5, s.ma10, s.ma20, s.ma60, s.ma240,
               s.ma20_slope, s.pb_ratio, s.dividend_yield_pct, s.vol_ratio_20,
               s.main_force_5d, s.main_force_20d,
               i.industry_category, i.type
        FROM standard_daily_bar s
        LEFT JOIN stock_info i ON s.ticker=i.ticker
        WHERE s.trade_date=? AND s.ticker IN ({ph})
    """, [TARGET_DATE] + list(tickers))
    cols = ["ticker", "close", "volume", "ma5", "ma10", "ma20", "ma60", "ma240",
            "ma20_slope", "pb_ratio", "div_yield", "vol_ratio_20",
            "mf5d", "mf20d", "industry", "mtype"]
    return {r[0]: dict(zip(cols, r)) for r in c.fetchall()}


def get_hist_closes(conn, tickers, dates):
    """取得指定日期的收盤價 (pivot query，避免 LIMIT 問題)"""
    ph_tickers = ",".join(["?"] * len(tickers))
    ph_dates = ",".join(["?"] * len(dates))
    c = conn.cursor()
    c.execute(f"""
        SELECT ticker, trade_date, close FROM standard_daily_bar
        WHERE ticker IN ({ph_tickers}) AND trade_date IN ({ph_dates})
    """, list(tickers) + list(dates))
    # {ticker: {date: close}}
    result = defaultdict(dict)
    for ticker, date, close in c.fetchall():
        result[ticker][date] = close
    return result


def get_inst_5d(conn, tickers, dates_5d):
    """取得近 5 交易日法人累計"""
    ph = ",".join(["?"] * len(tickers))
    ph_d = ",".join(["?"] * len(dates_5d))
    c = conn.cursor()
    c.execute(f"""
        SELECT ticker, SUM(foreign_net), SUM(sitc_net)
        FROM institutional_investors
        WHERE ticker IN ({ph}) AND trade_date IN ({ph_d})
        GROUP BY ticker
    """, list(tickers) + list(dates_5d))
    return {r[0]: {"foreign_5d": r[1] or 0, "sitc_5d": r[2] or 0} for r in c.fetchall()}


def get_uniform_days_seq(conn, tickers, dates_10d):
    """計算連續均線順向天數 (從最近一天往前數)"""
    ph = ",".join(["?"] * len(tickers))
    ph_d = ",".join(["?"] * len(dates_10d))
    c = conn.cursor()
    c.execute(f"""
        SELECT ticker, trade_date,
               CASE WHEN ma5>ma10 AND ma10>ma20 AND ma20>ma60 AND close>=ma5 THEN 1 ELSE 0 END
        FROM standard_daily_bar
        WHERE ticker IN ({ph}) AND trade_date IN ({ph_d})
        ORDER BY ticker, trade_date DESC
    """, list(tickers) + list(dates_10d))
    by_ticker = defaultdict(list)
    for ticker, date, ok in c.fetchall():
        by_ticker[ticker].append(ok)
    result = {}
    for t, flags in by_ticker.items():
        cnt = 0
        for f in flags:
            if f:
                cnt += 1
            else:
                break
        result[t] = cnt
    return result


def percentile_stats(values, name=""):
    arr = sorted(v for v in values if v is not None)
    if not arr:
        return {"name": name, "n": 0}
    n = len(arr)
    def p(pct):
        idx = max(0, min(n - 1, int(pct / 100 * (n - 1))))
        return round(arr[idx], 2)
    return {
        "name": name, "n": n,
        "min": p(0), "p10": p(10), "p25": p(25), "median": p(50),
        "p75": p(75), "p90": p(90), "max": p(100),
        "mean": round(sum(arr) / n, 2),
    }


def print_stat(ts, os_, label):
    print(f"\n  [{label}]")
    print(f"    老師組 (n={ts['n']}): median={ts.get('median','N/A'):>10}  "
          f"p25={ts.get('p25','N/A'):>10}  p75={ts.get('p75','N/A'):>10}  mean={ts.get('mean','N/A'):>10}")
    print(f"    其他組 (n={os_['n']}): median={os_.get('median','N/A'):>10}  "
          f"p25={os_.get('p25','N/A'):>10}  p75={os_.get('p75','N/A'):>10}  mean={os_.get('mean','N/A'):>10}")
    if ts.get("median") is not None and os_.get("median") is not None and os_["median"] != 0:
        diff = ts["median"] - os_["median"]
        ratio = ts["median"] / os_["median"]
        print(f"    差異: Δmedian={round(diff,2):>8}  ratio={round(ratio,3):>6}x")


def try_filter(data, teacher_set, name, fn):
    hits = set(t for t, r in data.items() if _safe_call(fn, r))
    overlap = hits & teacher_set
    miss = teacher_set - hits
    n_total = len(hits)
    precision = len(overlap) / n_total if n_total else 0
    recall = len(overlap) / len(teacher_set)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    print(f"\n  [{name}]")
    print(f"    命中={n_total:4d} | ∩老師={len(overlap):2d}/44 | 漏老師={len(miss):2d} | 非老師入={n_total - len(overlap):3d}")
    print(f"    Precision={precision:.3f}  Recall={recall:.3f}  F1={f1:.3f}")
    if miss and len(miss) <= 15:
        print(f"    漏掉: {sorted(miss)}")
    return hits, overlap, f1


def _safe_call(fn, r):
    try:
        return fn(r)
    except Exception:
        return False


def main():
    print("=" * 70)
    print("老師 44 檔 vs 全市場 434 — 基本指標反向工程")
    print(f"Target date: {TARGET_DATE}")
    print("=" * 70)

    teacher_tickers = load_teacher_tickers()
    conn = connect()

    universe = get_universe(conn)
    teacher_in = teacher_tickers & universe
    teacher_not_in = teacher_tickers - universe

    print(f"\n Universe: {len(universe)} 檔")
    print(f" 老師 44 ∩ universe(嚴格): {len(teacher_in)} 檔")
    print(f" 老師寬鬆 3 檔 (不在嚴格 universe): {teacher_not_in}")

    all_tickers = universe | teacher_tickers

    # 取得交易日序列
    print("\n[抓取資料...]")
    dates = get_trading_dates(conn, 65)
    date_today = dates[0]          # 2026-06-03
    date_5d = dates[5] if len(dates) > 5 else None
    date_20d = dates[20] if len(dates) > 20 else None
    date_60d = dates[60] if len(dates) > 60 else None

    print(f" 今日={date_today}, 5d前={date_5d}, 20d前={date_20d}, 60d前={date_60d}")

    # 取得當日資料
    daily = get_daily_data(conn, all_tickers)

    # 取得歷史收盤 (今日, 5d, 20d, 60d)
    key_dates = [d for d in [date_today, date_5d, date_20d, date_60d] if d]
    hist_close = get_hist_closes(conn, all_tickers, key_dates)

    # 取得法人 5d
    dates_5d_list = dates[:5]
    inst_5d = get_inst_5d(conn, all_tickers, dates_5d_list)

    # 計算均線順向連續天數 (近 10 天)
    dates_10d_list = dates[:10]
    uniform_days = get_uniform_days_seq(conn, all_tickers, dates_10d_list)

    # 計算衍生指標
    for ticker, row in daily.items():
        c_today = row["close"] or 0
        row["turnover"] = round(c_today * (row["volume"] or 0) / 1e8, 4)

        # 漲幅
        def ret(date_past):
            if date_past:
                past = hist_close.get(ticker, {}).get(date_past)
                if past and past > 0:
                    return round((c_today / past - 1) * 100, 2)
            return None

        row["ret5d"] = ret(date_5d)
        row["ret20d"] = ret(date_20d)
        row["ret60d"] = ret(date_60d)

        # 距均線 %
        def dev_ma(ma_val):
            if ma_val and ma_val > 0 and c_today > 0:
                return round((c_today / ma_val - 1) * 100, 2)
            return None

        row["dev_ma5_pct"] = dev_ma(row.get("ma5"))
        row["dev_ma20_pct"] = dev_ma(row.get("ma20"))
        row["dev_ma60_pct"] = dev_ma(row.get("ma60"))
        row["dev_ma240_pct"] = dev_ma(row.get("ma240"))

        # 法人
        inst = inst_5d.get(ticker, {})
        row["foreign_5d"] = inst.get("foreign_5d", 0)
        row["sitc_5d"] = inst.get("sitc_5d", 0)

        # 均線順向天數
        row["uniform_days"] = uniform_days.get(ticker, 0)

    # 分組 (老師44 vs 其他393)
    teacher_set = teacher_tickers
    other_set = universe - teacher_tickers

    teacher_data = {t: daily[t] for t in teacher_set if t in daily}
    other_data = {t: daily[t] for t in other_set if t in daily}
    all_data = {**teacher_data, **other_data}

    print(f" 老師組={len(teacher_data)}, 其他組={len(other_data)}")

    # ─── Section 1: 分布對比 ───
    print("\n" + "=" * 70)
    print("Section 1: 各指標分布對比")
    print("=" * 70)

    metrics = [
        ("turnover",      "成交額 (億)"),
        ("close",         "股價"),
        ("ret5d",         "5d 漲幅 %"),
        ("ret20d",        "20d 漲幅 %"),
        ("ret60d",        "60d 漲幅 %"),
        ("dev_ma5_pct",   "距 MA5 %"),
        ("dev_ma20_pct",  "距 MA20 %"),
        ("dev_ma60_pct",  "距 MA60 %"),
        ("dev_ma240_pct", "距 MA240 %"),
        ("vol_ratio_20",  "量比 (5d/20d)"),
        ("pb_ratio",      "PB ratio"),
        ("div_yield",     "殖利率 %"),
        ("ma20_slope",    "MA20 slope"),
        ("foreign_5d",    "外資 5d net (張)"),
        ("sitc_5d",       "投信 5d net (張)"),
        ("uniform_days",  "均線順向連續天數"),
    ]

    diff_scores = []
    for key, label in metrics:
        tv = [r.get(key) for r in teacher_data.values()]
        ov = [r.get(key) for r in other_data.values()]
        ts = percentile_stats(tv, label)
        os_ = percentile_stats(ov, label)
        print_stat(ts, os_, label)
        tm, om = ts.get("median"), os_.get("median")
        if tm is not None and om is not None and om != 0:
            diff_scores.append((abs(tm / om - 1), key, label, tm, om))

    # ─── Section 2: 差異排名 ───
    print("\n" + "=" * 70)
    print("Section 2: 差異最大指標排名 (abs median ratio - 1)")
    print("=" * 70)
    diff_scores.sort(reverse=True)
    for rank, (ratio, key, label, tm, om) in enumerate(diff_scores[:12], 1):
        direction = "老師HIGH" if tm > om else "老師LOW "
        print(f"  #{rank:2d} {direction} {label:25s}  老師={tm:>10.2f}  其他={om:>10.2f}  ratio={ratio:.3f}")

    # ─── 產業分布 ───
    print("\n[產業類別分布 (老師超代表/低代表)]")
    t_ind = Counter(r.get("industry") for r in teacher_data.values())
    o_ind = Counter(r.get("industry") for r in other_data.values())
    all_inds = set(t_ind) | set(o_ind)
    rows_ind = sorted(
        [(t_ind.get(i, 0) / len(teacher_data) * 100 - o_ind.get(i, 0) / len(other_data) * 100, i,
          t_ind.get(i, 0) / len(teacher_data) * 100,
          o_ind.get(i, 0) / len(other_data) * 100)
         for i in all_inds],
        reverse=True
    )
    print(f"  {'產業':30s} {'老師%':>7s}  {'其他%':>7s}  {'差異':>6s}")
    for diff, ind, tp, op in rows_ind:
        if abs(diff) >= 1.5:
            marker = "▲" if diff > 2 else "▼"
            print(f"  {marker} {str(ind):28s} {tp:>6.1f}%  {op:>6.1f}%  {diff:>+.1f}%")

    # ─── type 分布 ───
    print("\n[掛牌類型]")
    t_type = Counter(r.get("mtype") for r in teacher_data.values())
    o_type = Counter(r.get("mtype") for r in other_data.values())
    for t in ["twse", "tpex", "emerging"]:
        tp = t_type.get(t, 0) / len(teacher_data) * 100
        op = o_type.get(t, 0) / len(other_data) * 100
        print(f"  {t}: 老師={tp:.1f}%  其他={op:.1f}%  diff={tp - op:+.1f}%")

    # ─── Section 3: 條件組合嘗試 ───
    print("\n" + "=" * 70)
    print("Section 3: 條件組合嘗試 (目標: 命中≈44 ∩老師≥38)")
    print("=" * 70)

    combos = []

    # 基本面: 成交額是最強分隔符
    # 老師組 median 成交額 5.8億, 其他 1.72億 (3.37x差異)
    # 老師組 60d漲 median 偏高, 但非老師組也有很多高漲
    # 關鍵: 老師組距MA20 較小 (7.3 vs 11.6) => 相對早期
    # 老師組 uniform_days 較短 (2 vs 3) => 不要求連續很多天

    # Combo 1: 成交額篩選 (低門檻)
    def c1(r): return r.get("turnover", 0) >= 2.0
    combos.append(("成交額≥2億", c1))

    def c1b(r): return r.get("turnover", 0) >= 1.0
    combos.append(("成交額≥1億", c1b))

    def c1c(r): return r.get("turnover", 0) >= 0.5
    combos.append(("成交額≥5000萬", c1c))

    def c1d(r): return r.get("turnover", 0) >= 0.3
    combos.append(("成交額≥3000萬", c1d))

    # Combo 2: 成交額 + 距MA20 (老師選較「早期」)
    def c2(r):
        return (r.get("turnover", 0) >= 1.0
                and r.get("dev_ma20_pct") is not None
                and r.get("dev_ma20_pct") <= 20)
    combos.append(("成交額≥1億 + 距MA20≤20%", c2))

    def c2b(r):
        return (r.get("turnover", 0) >= 0.5
                and r.get("dev_ma20_pct") is not None
                and r.get("dev_ma20_pct") <= 25)
    combos.append(("成交額≥5000萬 + 距MA20≤25%", c2b))

    def c2c(r):
        return (r.get("turnover", 0) >= 0.5
                and r.get("dev_ma60_pct") is not None
                and r.get("dev_ma60_pct") <= 35)
    combos.append(("成交額≥5000萬 + 距MA60≤35%", c2c))

    # Combo 3: 成交額 + 60d漲幅範圍
    def c3(r):
        ret60 = r.get("ret60d")
        return (r.get("turnover", 0) >= 1.0
                and ret60 is not None
                and ret60 >= 5)
    combos.append(("成交額≥1億 + 60d漲≥5%", c3))

    def c3b(r):
        ret60 = r.get("ret60d")
        return (r.get("turnover", 0) >= 0.5
                and ret60 is not None
                and 5 <= ret60 <= 200)
    combos.append(("成交額≥5000萬 + 60d漲5-200%", c3b))

    # Combo 4: 成交額 + MA20 slope 向上
    def c4(r):
        return (r.get("turnover", 0) >= 1.0
                and r.get("ma20_slope") is not None
                and r.get("ma20_slope") > 0.1)
    combos.append(("成交額≥1億 + MA20 slope>0.1", c4))

    # Combo 5: 成交額 + 外資正
    def c5(r):
        return (r.get("turnover", 0) >= 1.0
                and r.get("foreign_5d", 0) > 0)
    combos.append(("成交額≥1億 + 外資5d>0", c5))

    # Combo 6: 成交額 + 60d漲 + 距MA20 (三合一)
    def c6(r):
        ret60 = r.get("ret60d")
        return (r.get("turnover", 0) >= 0.5
                and ret60 is not None and ret60 >= 5
                and r.get("dev_ma20_pct") is not None
                and r.get("dev_ma20_pct") <= 30)
    combos.append(("成交額≥5000萬 + 60d≥5% + 距MA20≤30%", c6))

    def c6b(r):
        ret60 = r.get("ret60d")
        return (r.get("turnover", 0) >= 1.0
                and ret60 is not None and ret60 >= 5
                and r.get("dev_ma20_pct") is not None
                and r.get("dev_ma20_pct") <= 30)
    combos.append(("成交額≥1億 + 60d≥5% + 距MA20≤30%", c6b))

    def c6c(r):
        ret60 = r.get("ret60d")
        return (r.get("turnover", 0) >= 1.0
                and ret60 is not None and ret60 >= 5
                and r.get("dev_ma60_pct") is not None
                and r.get("dev_ma60_pct") <= 40)
    combos.append(("成交額≥1億 + 60d≥5% + 距MA60≤40%", c6c))

    # Combo 7: 成交額 + 20d漲
    def c7(r):
        ret20 = r.get("ret20d")
        return (r.get("turnover", 0) >= 1.0
                and ret20 is not None and ret20 >= 5)
    combos.append(("成交額≥1億 + 20d漲≥5%", c7))

    def c7b(r):
        ret20 = r.get("ret20d")
        return (r.get("turnover", 0) >= 0.5
                and ret20 is not None and ret20 >= 3)
    combos.append(("成交額≥5000萬 + 20d漲≥3%", c7b))

    # Combo 8: 只用均線排列 + 成交額（理解老師邏輯: 全順向+流動性）
    def c8(r):
        return r.get("turnover", 0) >= 0.5
    combos.append(("成交額≥5000萬 (只看流動性)", c8))

    # Combo 9: 成交額 + 投信正買
    def c9(r):
        return (r.get("turnover", 0) >= 0.5
                and r.get("sitc_5d", 0) > 0)
    combos.append(("成交額≥5000萬 + 投信5d>0", c9))

    # Combo 10: 組合最強分隔指標
    def c10(r):
        return (r.get("turnover", 0) >= 1.0
                and r.get("dev_ma20_pct") is not None
                and r.get("dev_ma20_pct") <= 25
                and r.get("ret60d") is not None
                and r.get("ret60d") >= 5)
    combos.append(("成交額≥1億 + 距MA20≤25% + 60d≥5%", c10))

    # Run combos
    results = []
    for name, fn in combos:
        hits, overlap, f1 = try_filter(all_data, teacher_set, name, fn)
        results.append((f1, len(hits), len(overlap), name))

    # ─── Section 4: Top 3 ───
    print("\n" + "=" * 70)
    print("Section 4: 最佳條件組合 Top 5 (by F1)")
    print("=" * 70)
    results.sort(reverse=True)
    for rank, (f1, total, overlap, name) in enumerate(results[:5], 1):
        precision = overlap / total if total else 0
        recall = overlap / len(teacher_set)
        print(f"\n  #{rank} {name}")
        print(f"     命中總數={total:3d} | ∩老師={overlap:2d}/44 | 漏={len(teacher_set)-overlap:2d} | 非老師入={total-overlap:3d}")
        print(f"     P={precision:.3f}  R={recall:.3f}  F1={f1:.3f}")

    # ─── 補充分析: 老師組分布摘要 ───
    print("\n" + "=" * 70)
    print("Section 5: 老師組 vs 其他組 關鍵快速摘要")
    print("=" * 70)

    def quick_compare(key, label):
        tv = sorted(v for r in teacher_data.values() if (v := r.get(key)) is not None)
        ov = sorted(v for r in other_data.values() if (v := r.get(key)) is not None)
        if not tv or not ov:
            return
        def med(arr): return arr[len(arr) // 2]
        def p25(arr): return arr[len(arr) // 4]
        def p75(arr): return arr[3 * len(arr) // 4]
        print(f"\n  {label} (老師n={len(tv)}, 其他n={len(ov)})")
        print(f"    老師: p25={p25(tv):>8.2f}  med={med(tv):>8.2f}  p75={p75(tv):>8.2f}")
        print(f"    其他: p25={p25(ov):>8.2f}  med={med(ov):>8.2f}  p75={p75(ov):>8.2f}")
        ratio = med(tv) / med(ov) if med(ov) != 0 else float("inf")
        print(f"    ratio={ratio:.3f}x")

    for key, label in [
        ("turnover",      "成交額 (億)"),
        ("ret20d",        "20d 漲幅 %"),
        ("ret60d",        "60d 漲幅 %"),
        ("dev_ma20_pct",  "距 MA20 %"),
        ("dev_ma60_pct",  "距 MA60 %"),
        ("dev_ma240_pct", "距 MA240 %"),
        ("vol_ratio_20",  "量比 5d/20d"),
        ("ma20_slope",    "MA20 slope"),
        ("foreign_5d",    "外資 5d net (張)"),
        ("sitc_5d",       "投信 5d net (張)"),
        ("uniform_days",  "均線順向連續天數"),
        ("close",         "股價"),
    ]:
        quick_compare(key, label)

    conn.close()
    print("\n" + "=" * 70)
    print("分析完成")
    print("=" * 70)


if __name__ == "__main__":
    main()
