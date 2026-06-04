"""Phase 3 v12 — Deep Dive: <3/5 樣本高勝率 (88%) 原因分析

研究問題:
  v10 backtest 發現 <3/5 那 58 個樣本 Win 88%，比 confirmed (3-4/5) 的 82% 還高。
  這很反直覺 — 意思是「條件最差的樣本最賺」？

深入分析 5 個面向:
  1. Ticker 分布 — 是同一檔重複出現、還是廣泛分布？
  2. 觸發時段分布 — 集中在 13:00 / 13:10 / 13:25？
  3. 條件 fail/pass 分布 — 哪幾條最常 fail？
  4. 進場價特徵 — 距日高 % / 距 MA10 % / 量比
  5. 隔日跳空特徵 — 強力跳空拉開 vs 持平慢漲？

結論:
  - <3/5 Win 88% 的「隱藏特徵」是什麼？
  - 指標選錯（Closing_check 本來就有問題）還是市場特殊期間？
  - 是否應調整 Closing_check 邏輯來 capture 這些案例？

期間: 2026-05-19 → 2026-06-03

Usage:
    python scripts/zhuli/phase3_v12_deep_dive_low_score.py
    python scripts/zhuli/phase3_v12_deep_dive_low_score.py --no-report
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

_REPO = Path(__file__).parent.parent.parent
_SYS = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_REPO), str(_REPO / "scripts"), str(_SYS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.intraday_stage_helper import StageTrigger, _get_ma10, _DB as _HELPER_DB  # noqa

_DB = Path.home() / ".four_seasons" / "data.sqlite"
_TMP = Path("/tmp")
_CACHE_DIR = _TMP / "finmind_kbar_cache"
_CACHE_DIR.mkdir(exist_ok=True)

FEE_PCT = 0.6

TRADING_DATES_FULL = [
    "2026-05-19", "2026-05-20", "2026-05-21", "2026-05-22",
    "2026-05-25", "2026-05-26", "2026-05-27", "2026-05-28", "2026-05-29",
    "2026-06-01", "2026-06-02", "2026-06-03",
]

_REGIME_EMOJI = {"strong": "🟢強", "weak": "🔴弱", "normal": "⚪平"}

COND_KEYS = [
    "structure_hold",
    "kill_test_passed",
    "rebound_confirmed",
    "volume_calm",
    "not_chasing_high",
]
COND_LABELS = {
    "structure_hold":    "#1 結構守住 (close>MA10)",
    "kill_test_passed":  "#2 殺盤考驗過",
    "rebound_confirmed": "#3 反彈 2 紅K",
    "volume_calm":       "#4 量縮",
    "not_chasing_high":  "#5 未追高",
}


def next_trading_day(d: str, dates: list[str]) -> Optional[str]:
    idx = dates.index(d) if d in dates else -1
    if idx < 0 or idx + 1 >= len(dates):
        return None
    return dates[idx + 1]


# ── Scanner 解析 ──────────────────────────────────────────────────────────────

def parse_scanner_candidates(md_path: Path) -> list[str]:
    text = md_path.read_text()
    tickers: list[str] = []
    seen: set[str] = set()
    in_entry = False
    in_teacher = False
    in_observation = False

    for line in text.splitlines():
        if line.startswith("## 🎯 可進場"):
            in_entry = True; in_teacher = False; in_observation = False; continue
        elif line.startswith("## ⚠️ 後續觀察"):
            in_entry = False; in_teacher = False; in_observation = True; continue
        elif line.startswith("## 📋 老師 core 級指名"):
            in_entry = False; in_teacher = True; in_observation = False; continue
        elif line.startswith("## "):
            in_entry = False; in_teacher = False; in_observation = False; continue
        if in_observation:
            continue
        if in_entry or in_teacher:
            m = re.match(r'\|\s*\*?\*?(\d{4})\*?\*?\s*', line)
            if m:
                t = m.group(1)
                if t not in seen:
                    seen.add(t)
                    tickers.append(t)
    return tickers


# ── FinMind 抓取 ──────────────────────────────────────────────────────────────

_finmind_calls = 0
_finmind_call_ts = time.time()


def _rate_limit():
    global _finmind_calls, _finmind_call_ts
    _finmind_calls += 1
    if _finmind_calls % 100 == 0:
        time.sleep(1.0)
    else:
        time.sleep(0.12)


def fetch_finmind_kbar_5m(ticker: str, target_date: str) -> pd.DataFrame:
    cache_file = _CACHE_DIR / f"{ticker}_{target_date}.json"
    if cache_file.exists():
        try:
            raw = json.loads(cache_file.read_text())
            if not raw:
                return pd.DataFrame()
            df = pd.DataFrame(raw)
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.set_index("datetime")
            for col in ("open", "high", "low", "close", "volume"):
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            return df
        except Exception:
            pass

    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        return pd.DataFrame()

    _rate_limit()
    for attempt in range(3):
        try:
            import requests
            r = requests.get(
                "https://api.finmindtrade.com/api/v4/data",
                params={
                    "dataset": "TaiwanStockKBar",
                    "data_id": ticker,
                    "start_date": target_date,
                    "end_date": target_date,
                    "token": token,
                },
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            if data.get("status") != 200 or not data.get("data"):
                cache_file.write_text("[]")
                return pd.DataFrame()
            break
        except Exception as e:
            if attempt == 2:
                print(f"  [ERR] FinMind {ticker} {target_date}: {e}")
                return pd.DataFrame()
            time.sleep(2 ** attempt)
    else:
        return pd.DataFrame()

    df = pd.DataFrame(data["data"])
    if df.empty:
        cache_file.write_text("[]")
        return pd.DataFrame()

    if "minute" in df.columns:
        df["datetime"] = pd.to_datetime(df["date"].astype(str) + " " + df["minute"].astype(str))
    else:
        df["datetime"] = pd.to_datetime(df["date"])

    df = df.sort_values("datetime").set_index("datetime")
    td = date.fromisoformat(target_date)
    df = df[df.index.date == td]
    if df.empty:
        cache_file.write_text("[]")
        return pd.DataFrame()

    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df5 = df.resample("5min", label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna(subset=["open", "close"])

    df5_save = df5.reset_index()
    df5_save["datetime"] = df5_save["datetime"].astype(str)
    cache_file.write_text(json.dumps(df5_save.to_dict("records"), ensure_ascii=False))
    return df5


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_prev_levels(ticker: str, d: str) -> dict:
    for attempt in range(3):
        try:
            con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=10)
            rows = con.execute(
                "SELECT trade_date, close, high, low FROM standard_daily_bar "
                "WHERE ticker=? AND trade_date<? ORDER BY trade_date DESC LIMIT 10",
                (ticker, d),
            ).fetchall()
            con.close()
            if not rows:
                return {}
            prev_close = float(rows[0][1])
            highs = [float(r[2]) for r in rows[:5] if r[2] is not None]
            lows  = [float(r[3]) for r in rows[:5] if r[3] is not None]
            recent_high = max(highs) if highs else prev_close * 1.02
            recent_low  = min(lows)  if lows  else prev_close * 0.98
            return {"prev_close": prev_close, "prev_high": recent_high, "prev_low": recent_low}
        except sqlite3.OperationalError:
            if attempt == 2:
                return {}
            time.sleep(1)
    return {}


def get_open_price_next_day(ticker: str, d: str) -> Optional[float]:
    for attempt in range(3):
        try:
            con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=10)
            row = con.execute(
                "SELECT open FROM standard_daily_bar WHERE ticker=? AND trade_date=?",
                (ticker, d),
            ).fetchone()
            con.close()
            if row and row[0] is not None:
                return float(row[0])
            return None
        except sqlite3.OperationalError:
            if attempt == 2:
                return None
            time.sleep(1)
    return None


# ── 完整計算 5 條件 scores ────────────────────────────────────────────────────

def compute_v10_scores_full(ticker: str, k5_full: pd.DataFrame, ma10: float) -> dict:
    """計算 v10 原 5 條件 scores，同時抓取盤中特徵供 deep dive 使用。"""
    k5_1305 = k5_full[k5_full.index.strftime("%H:%M") <= "13:05"]
    if k5_1305.empty or len(k5_1305) < 2:
        return {
            "scores": {k: False for k in COND_KEYS},
            "pass_count": 0,
            "entry_time_actual": "13:00",
            "dist_from_high_pct": 99.0,
            "dist_from_ma10_pct": 0.0,
            "vol_ratio": 1.0,
            "gap_next_pct": None,
        }

    # ma10 fallback
    if ma10 is None or ma10 <= 0:
        ma10_raw = k5_1305["close"].rolling(10, min_periods=3).mean()
        ma10 = float(ma10_raw.iloc[-1]) if not ma10_raw.empty else 0.0

    ma5_raw = k5_1305["close"].rolling(5, min_periods=3).mean()
    ma5 = float(ma5_raw.iloc[-1]) if not ma5_raw.empty else 0.0

    current_close = float(k5_1305["close"].iloc[-1])
    day_high = float(k5_1305["high"].max())

    # entry time = last bar before or at 13:00
    k5_1300 = k5_1305[k5_1305.index.strftime("%H:%M") <= "13:00"]
    entry_time_actual = k5_1300.index[-1].strftime("%H:%M") if not k5_1300.empty else "13:00"

    # cond1
    cond1 = (ma10 > 0 and current_close > ma10)

    # cond2
    afternoon_k5 = k5_1305[k5_1305.index.strftime("%H:%M") >= "12:00"]
    morning_k5 = k5_1305[k5_1305.index.strftime("%H:%M") < "12:00"]
    morning_high = float(morning_k5["high"].max()) if not morning_k5.empty else day_high
    after_12_low = float(afternoon_k5["low"].min()) if not afternoon_k5.empty else current_close
    cond2 = (after_12_low < morning_high * 0.98) or (ma5 > 0 and after_12_low < ma5 * 0.99)

    # cond3
    after_13_k5 = k5_1305[k5_1305.index.strftime("%H:%M") >= "13:00"]
    cond3 = False
    if len(after_13_k5) >= 2:
        last2 = after_13_k5.tail(2)
        cond3 = bool((last2["close"] > last2["open"]).all())

    # cond4
    morning_k5_alt = k5_1305[k5_1305.index.strftime("%H:%M") < "13:00"]
    n_after_13 = len(after_13_k5)
    after_13_vol = float(after_13_k5["volume"].sum()) if not after_13_k5.empty else 0.0
    afternoon_per_bar = after_13_vol / max(1, n_after_13)
    if not morning_k5_alt.empty:
        morning_per_bar = float(morning_k5_alt["volume"].mean())
        cond4 = afternoon_per_bar < morning_per_bar * 1.2
        vol_ratio = round(afternoon_per_bar / morning_per_bar, 3) if morning_per_bar > 0 else 1.0
    else:
        cond4 = True
        vol_ratio = 1.0

    # cond5
    dist_below_high_pct = (day_high - current_close) / day_high * 100 if day_high > 0 else 99
    cond5 = dist_below_high_pct >= 1.5

    scores = {
        "structure_hold":    cond1,
        "kill_test_passed":  cond2,
        "rebound_confirmed": cond3,
        "volume_calm":       cond4,
        "not_chasing_high":  cond5,
    }
    pass_count = sum(scores.values())

    # dist from MA10
    dist_from_ma10_pct = ((current_close / ma10 - 1) * 100) if ma10 > 0 else 0.0

    return {
        "scores":             scores,
        "pass_count":         pass_count,
        "entry_time_actual":  entry_time_actual,
        "dist_from_high_pct": round(dist_below_high_pct, 2),
        "dist_from_ma10_pct": round(dist_from_ma10_pct, 2),
        "vol_ratio":          vol_ratio,
    }


# ── 主掃描 ────────────────────────────────────────────────────────────────────

def scan_all_samples(
    engine: StageTrigger,
    entry_date: str,
    watchlist: list[str],
    regime: str,
) -> list[dict]:
    results = []

    for ticker in watchlist:
        k5_full = fetch_finmind_kbar_5m(ticker, entry_date)
        if k5_full.empty:
            continue

        prev_levels = get_prev_levels(ticker, entry_date)
        prev_close = prev_levels.get("prev_close", 0.0)
        if not prev_close:
            continue

        ma10 = _get_ma10(ticker, entry_date)

        k5_1300 = k5_full[k5_full.index.strftime("%H:%M") <= "13:00"]
        if k5_1300.empty:
            continue
        entry_price = float(k5_1300.iloc[-1]["close"])

        scored = compute_v10_scores_full(ticker, k5_full, ma10)

        next_date = next_trading_day(entry_date, TRADING_DATES_FULL)
        if not next_date:
            continue
        exit_price = get_open_price_next_day(ticker, next_date)
        if exit_price is None or not entry_price:
            continue

        raw_ret = (exit_price / entry_price - 1) * 100
        net_ret = round(raw_ret - FEE_PCT, 3)
        gap_next_pct = round(raw_ret, 3)  # 隔日跳空 (從進場價到隔日開盤)

        rec = {
            "entry_date":         entry_date,
            "ticker":             ticker,
            "entry_price":        entry_price,
            "entry_time":         scored["entry_time_actual"],
            "exit_date":          next_date,
            "exit_price":         exit_price,
            "net_ret_pct":        net_ret,
            "win":                net_ret > 0,
            "pass_count":         scored["pass_count"],
            "scores":             scored["scores"],
            "dist_from_high_pct": scored["dist_from_high_pct"],
            "dist_from_ma10_pct": scored["dist_from_ma10_pct"],
            "vol_ratio":          scored["vol_ratio"],
            "gap_next_pct":       gap_next_pct,
            "market_regime":      regime,
        }
        results.append(rec)

    return results


# ── 統計函式 ──────────────────────────────────────────────────────────────────

def calc_stats(records: list[dict]) -> dict:
    if not records:
        return {"n": 0, "win_rate": None, "avg_ret": None, "median_ret": None}
    n = len(records)
    rets = [r["net_ret_pct"] for r in records if r["net_ret_pct"] is not None]
    wins = [r for r in records if r.get("win")]
    win_rate = len(wins) / n * 100
    avg_ret = sum(rets) / len(rets) if rets else 0
    sorted_rets = sorted(rets)
    median_ret = sorted_rets[len(sorted_rets) // 2] if sorted_rets else 0
    return {
        "n":          n,
        "win_rate":   round(win_rate, 1),
        "avg_ret":    round(avg_ret, 3),
        "median_ret": round(median_ret, 3),
    }


def _win_emoji(win_rate: Optional[float]) -> str:
    if win_rate is None:
        return "—"
    if win_rate >= 80:
        return f"🟢{win_rate:.0f}%"
    if win_rate >= 65:
        return f"🟡{win_rate:.0f}%"
    return f"🔴{win_rate:.0f}%"


def _pct_bucket(val: float, thresholds: list[float]) -> str:
    """把百分比 val 分桶。thresholds 升序。"""
    for t in thresholds:
        if val <= t:
            return f"≤{t:.0f}%"
    return f">{thresholds[-1]:.0f}%"


# ── 主 Backtest ───────────────────────────────────────────────────────────────

def run_v12_backtest() -> dict:
    engine = StageTrigger()
    all_records: list[dict] = []

    for scan_date in TRADING_DATES_FULL:
        md_path = _TMP / f"scanner_candidates_{scan_date}.md"
        if not md_path.exists():
            print(f"[SKIP] 無 scanner file: {scan_date}")
            continue

        watchlist = parse_scanner_candidates(md_path)
        next_date = next_trading_day(scan_date, TRADING_DATES_FULL)
        if not next_date:
            continue

        regime = engine._detect_market_regime(next_date, db_path=_DB)
        print(f"[{scan_date} → {next_date}] watchlist={len(watchlist)} "
              f"regime={_REGIME_EMOJI.get(regime, regime)}")

        day_records = scan_all_samples(engine, next_date, watchlist, regime)
        all_records.extend(day_records)
        print(f"  → {len(day_records)} 樣本")

    low_score = [r for r in all_records if r["pass_count"] < 3]
    confirmed = [r for r in all_records if 3 <= r["pass_count"] <= 4]
    overheat  = [r for r in all_records if r["pass_count"] == 5]

    return {
        "all":        all_records,
        "low_score":  low_score,
        "confirmed":  confirmed,
        "overheat":   overheat,
    }


# ── Deep Dive 分析函式 ────────────────────────────────────────────────────────

def analyze_low_score(records: list[dict]) -> dict:
    """深入分析 <3/5 樣本特徵。"""
    if not records:
        return {}

    # 1. Ticker 分布
    ticker_wins: dict[str, list[float]] = {}
    for r in records:
        tk = r["ticker"]
        if tk not in ticker_wins:
            ticker_wins[tk] = []
        ticker_wins[tk].append(r["net_ret_pct"])
    ticker_freq = Counter(r["ticker"] for r in records)
    top_tickers = ticker_freq.most_common(15)

    # 2. 觸發時段分布
    time_dist = Counter(r["entry_time"] for r in records)

    # 3. 條件 fail/pass 分布
    cond_fail_rate: dict[str, float] = {}
    for ck in COND_KEYS:
        fail_count = sum(1 for r in records if not r["scores"].get(ck, False))
        cond_fail_rate[ck] = round(fail_count / len(records) * 100, 1)

    # pass_count 分布 (0/1/2)
    pass_count_dist = Counter(r["pass_count"] for r in records)

    # 4. 進場價特徵
    dist_high = [r["dist_from_high_pct"] for r in records]
    dist_ma10 = [r["dist_from_ma10_pct"] for r in records]
    vol_ratios = [r["vol_ratio"] for r in records]

    def avg(lst): return round(sum(lst) / len(lst), 2) if lst else 0
    def median(lst):
        s = sorted(lst)
        return s[len(s)//2] if s else 0

    # 距日高分桶
    high_buckets = Counter(_pct_bucket(v, [0.5, 1.5, 3.0, 5.0]) for v in dist_high)

    # 距 MA10 分桶 (可能負值)
    ma10_buckets = Counter()
    for v in dist_ma10:
        if v < -2:
            ma10_buckets["< -2% (破 MA10)"] += 1
        elif v < 0:
            ma10_buckets["-2%~0% (略低)"] += 1
        elif v < 3:
            ma10_buckets["0~3% (近 MA10)"] += 1
        elif v < 8:
            ma10_buckets["3~8% (略高)"] += 1
        else:
            ma10_buckets["> 8% (拉遠)"] += 1

    # 5. 隔日跳空特徵
    gap_vals = [r["gap_next_pct"] for r in records if r["gap_next_pct"] is not None]
    wins_gap = [r["gap_next_pct"] for r in records if r["win"] and r["gap_next_pct"] is not None]
    loss_gap = [r["gap_next_pct"] for r in records if not r["win"] and r["gap_next_pct"] is not None]

    gap_buckets = Counter()
    for v in gap_vals:
        if v < -1:
            gap_buckets["< -1% (大跌)"] += 1
        elif v < 0:
            gap_buckets["-1%~0% (小跌)"] += 1
        elif v < 1:
            gap_buckets["0~1% (持平)"] += 1
        elif v < 3:
            gap_buckets["1~3% (小漲)"] += 1
        else:
            gap_buckets["> 3% (強拉)"] += 1

    # Win/Loss 樣本的條件分布
    wins_recs  = [r for r in records if r["win"]]
    losses_recs = [r for r in records if not r["win"]]

    # 哪幾條件在 win vs loss 中差異最大
    cond_win_rate: dict[str, float] = {}
    for ck in COND_KEYS:
        win_pass = sum(1 for r in wins_recs if r["scores"].get(ck, False))
        total_pass = sum(1 for r in records if r["scores"].get(ck, False))
        cond_win_rate[ck] = round(win_pass / total_pass * 100, 1) if total_pass else 0

    # 市場 regime 分布
    regime_dist = Counter(r["market_regime"] for r in records)
    regime_win: dict[str, dict] = {}
    for reg in ["strong", "normal", "weak"]:
        sub = [r for r in records if r["market_regime"] == reg]
        if sub:
            w = sum(1 for r in sub if r["win"])
            regime_win[reg] = {"n": len(sub), "win_rate": round(w/len(sub)*100, 1)}

    return {
        "n":               len(records),
        "win_rate":        calc_stats(records)["win_rate"],
        "avg_ret":         calc_stats(records)["avg_ret"],
        "ticker_freq":     top_tickers,
        "ticker_wins":     {k: round(sum(v)/len(v), 2) for k, v in ticker_wins.items()},
        "time_dist":       dict(time_dist.most_common()),
        "cond_fail_rate":  cond_fail_rate,
        "pass_count_dist": dict(pass_count_dist),
        "avg_dist_high":   avg(dist_high),
        "med_dist_high":   median(dist_high),
        "avg_dist_ma10":   avg(dist_ma10),
        "med_dist_ma10":   median(dist_ma10),
        "avg_vol_ratio":   avg(vol_ratios),
        "med_vol_ratio":   median(vol_ratios),
        "high_buckets":    dict(high_buckets),
        "ma10_buckets":    dict(ma10_buckets),
        "avg_gap":         avg(gap_vals),
        "avg_win_gap":     avg(wins_gap),
        "avg_loss_gap":    avg(loss_gap),
        "gap_buckets":     dict(gap_buckets),
        "cond_win_rate":   cond_win_rate,
        "regime_win":      regime_win,
    }


def _compare_analysis(low: dict, conf: dict, oh: dict) -> dict:
    """比較三組的特徵差異。"""
    return {
        "low":  low,
        "conf": conf,
        "oh":   oh,
    }


# ── 報告輸出 ──────────────────────────────────────────────────────────────────

def print_summary(results: dict, analysis: dict) -> str:
    lines = []
    all_r     = results["all"]
    low_score = results["low_score"]
    confirmed = results["confirmed"]
    overheat  = results["overheat"]
    A         = analysis["low"]
    A_conf    = analysis["conf"]

    def _h(title: str):
        lines.append(f"\n{'='*70}")
        lines.append(f"  {title}")
        lines.append(f"{'='*70}")

    _h("Phase 3 v12 — Deep Dive: <3/5 高勝率樣本分析 (5/19-6/3)")
    lines.append(f"  總樣本: {len(all_r)}  <3/5: {len(low_score)}  confirmed: {len(confirmed)}  過熱: {len(overheat)}")

    st_all  = calc_stats(all_r)
    st_low  = calc_stats(low_score)
    st_conf = calc_stats(confirmed)
    st_oh   = calc_stats(overheat)

    lines.append(f"\n  各組 Win rate 對比:")
    lines.append(f"    全體:     n={st_all['n']:>3}  Win={_win_emoji(st_all['win_rate'])}  avg={st_all['avg_ret']:+.2f}%")
    lines.append(f"    <3/5:     n={st_low['n']:>3}  Win={_win_emoji(st_low['win_rate'])}  avg={st_low['avg_ret']:+.2f}%  ← 分析主體")
    lines.append(f"    confirmed:n={st_conf['n']:>3}  Win={_win_emoji(st_conf['win_rate'])}  avg={st_conf['avg_ret']:+.2f}%")
    lines.append(f"    過熱:     n={st_oh['n']:>3}  Win={_win_emoji(st_oh['win_rate'])}  avg={st_oh['avg_ret']:+.2f}%")

    if not A:
        lines.append("\n  <3/5 樣本為空，無法分析")
        text = "\n".join(lines)
        print(text)
        return text

    # ── 1. Ticker 分布 ─────────────────────────────────────────────────────────
    _h("1. Ticker 分布 (前 15 名出現頻率)")
    unique_tickers = len(set(r["ticker"] for r in low_score))
    lines.append(f"  總出現 {len(low_score)} 次、{unique_tickers} 檔不同標的")
    repeat = [(tk, cnt) for tk, cnt in A["ticker_freq"] if cnt > 1]
    one_time = [(tk, cnt) for tk, cnt in A["ticker_freq"] if cnt == 1]
    lines.append(f"  重複出現 (>=2 次): {len(repeat)} 檔")
    lines.append(f"  只出現 1 次: {len(one_time)} 檔")
    lines.append("")
    for tk, cnt in A["ticker_freq"][:10]:
        avg_ret = A["ticker_wins"].get(tk, 0)
        lines.append(f"    {tk}  出現 {cnt:>2} 次  avg_ret={avg_ret:+.2f}%")

    if len(repeat) < 5:
        lines.append("\n  → 結論: 廣泛分布 (非單一標的重複貢獻)")
    else:
        lines.append("\n  → 結論: 有集中現象 (少數標的重複出現)")

    # ── 2. 觸發時段 ─────────────────────────────────────────────────────────────
    _h("2. 觸發時段分布")
    time_sorted = sorted(A["time_dist"].items(), key=lambda x: x[0])
    for t, cnt in time_sorted:
        pct = cnt / len(low_score) * 100
        lines.append(f"  {t}  {cnt:>3} 次 ({pct:.0f}%)")

    # 找最集中時段
    if time_sorted:
        peak_time = max(time_sorted, key=lambda x: x[1])[0]
        peak_cnt  = max(time_sorted, key=lambda x: x[1])[1]
        lines.append(f"\n  → 尖峰時段: {peak_time} ({peak_cnt} 次, {peak_cnt/len(low_score)*100:.0f}%)")

    # ── 3. 條件 fail/pass 分布 ─────────────────────────────────────────────────
    _h("3. 條件 fail/pass 分布 (<3/5 樣本)")
    lines.append(f"  Pass count 分布: {dict(sorted(A['pass_count_dist'].items()))}")
    lines.append("")
    lines.append(f"  {'條件':<30} {'Fail 率':>8}")
    lines.append("  " + "-" * 40)
    for ck in COND_KEYS:
        fail_pct = A["cond_fail_rate"].get(ck, 0)
        label = COND_LABELS.get(ck, ck)
        bar = "█" * int(fail_pct // 5)
        lines.append(f"  {label:<30} {fail_pct:>6.0f}% {bar}")

    # 最常 fail 的條件
    most_fail = max(COND_KEYS, key=lambda k: A["cond_fail_rate"].get(k, 0))
    lines.append(f"\n  → 最常 fail: {COND_LABELS[most_fail]} ({A['cond_fail_rate'][most_fail]:.0f}%)")

    # ── 4. 進場價特徵 ───────────────────────────────────────────────────────────
    _h("4. 進場價特徵")

    lines.append(f"\n  距日高:")
    lines.append(f"    平均: {A['avg_dist_high']:+.2f}%  中位數: {A['med_dist_high']:+.2f}%")
    for bucket, cnt in sorted(A["high_buckets"].items()):
        pct = cnt / len(low_score) * 100
        lines.append(f"    {bucket:<15} {cnt:>3} 次 ({pct:.0f}%)")

    lines.append(f"\n  距 MA10:")
    lines.append(f"    平均: {A['avg_dist_ma10']:+.2f}%  中位數: {A['med_dist_ma10']:+.2f}%")
    for bucket, cnt in A["ma10_buckets"].items():
        pct = cnt / len(low_score) * 100
        lines.append(f"    {bucket:<22} {cnt:>3} 次 ({pct:.0f}%)")

    lines.append(f"\n  量比 (尾盤 vs 早盤 per-bar):")
    lines.append(f"    平均: {A['avg_vol_ratio']:.2f}x  中位數: {A['med_vol_ratio']:.2f}x")

    # conf 對比
    lines.append(f"\n  對比 confirmed 組:")
    A_c = A_conf
    if A_c:
        lines.append(f"    confirmed 距日高 avg={A_c['avg_dist_high']:+.2f}%  vs <3/5 {A['avg_dist_high']:+.2f}%")
        lines.append(f"    confirmed 距MA10 avg={A_c['avg_dist_ma10']:+.2f}%  vs <3/5 {A['avg_dist_ma10']:+.2f}%")
        lines.append(f"    confirmed 量比  avg={A_c['avg_vol_ratio']:.2f}x  vs <3/5 {A['avg_vol_ratio']:.2f}x")

    # ── 5. 隔日跳空特徵 ────────────────────────────────────────────────────────
    _h("5. 隔日跳空特徵")
    lines.append(f"  平均跳空: {A['avg_gap']:+.2f}%")
    lines.append(f"  Win 樣本平均跳空: {A['avg_win_gap']:+.2f}%")
    lines.append(f"  Loss 樣本平均跳空: {A['avg_loss_gap']:+.2f}%")
    lines.append("")
    for bucket, cnt in sorted(A["gap_buckets"].items()):
        pct = cnt / len(low_score) * 100
        lines.append(f"  {bucket:<20} {cnt:>3} 次 ({pct:.0f}%)")

    strong_gap = A["gap_buckets"].get("> 3% (強拉)", 0)
    strong_pct = strong_gap / len(low_score) * 100
    lines.append(f"\n  → 強力跳空 >3% 比例: {strong_pct:.0f}%")
    if strong_pct > 30:
        lines.append("    → 主因是「跳空拉開型」隔日大漲、不是慢慢漲")
    else:
        lines.append("    → 不是靠大幅跳空、多數是小漲或平開")

    # ── 市場 Regime ──────────────────────────────────────────────────────────
    _h("市場 Regime 分布")
    for reg, d in A.get("regime_win", {}).items():
        emoji = _REGIME_EMOJI.get(reg, reg)
        lines.append(f"  {emoji}  n={d['n']:>3}  Win={_win_emoji(d['win_rate'])}")

    # ── 綜合結論 ─────────────────────────────────────────────────────────────
    _h("綜合結論")

    lines.append("")
    lines.append("  Q1. <3/5 Win 88% 的「隱藏特徵」是什麼？")

    # 歸納
    findings = []
    if len(repeat) < 5:
        findings.append("廣泛標的分布 (非單一標的驅動)")
    if A["avg_dist_ma10"] < 5:
        findings.append(f"多數在 MA10 附近 (avg +{A['avg_dist_ma10']:.1f}%)、結構尚可")
    if strong_pct > 25:
        findings.append(f"大比例靠隔日強力跳空拉開 ({strong_pct:.0f}% > +3%)")
    else:
        findings.append("跳空不是主因、漲法較為穩健")
    if A["cond_fail_rate"].get("rebound_confirmed", 0) > 60:
        findings.append("#3 反彈條件 fail 率高 → 主要就是因為缺反彈確認")

    for f in findings:
        lines.append(f"    • {f}")

    lines.append("")
    lines.append("  Q2. 指標選錯 vs 市場特殊期間？")
    if A["cond_fail_rate"].get("rebound_confirmed", 0) > 70:
        lines.append("    → #3「反彈 2 紅K」是主要問題條件")
        lines.append("      這條件太嚴、刷掉了真實的強勢標的 → 指標設計問題")
        lines.append("      v11 移除 #3 後、這批樣本預期升為 confirmed → 合理")
    else:
        lines.append("    → 多個條件均有高 fail 率、可能是市場特殊期間短期強勢")
        lines.append("      需更長時間驗證才能確定是系統性問題")

    lines.append("")
    lines.append("  Q3. 是否應將 <3/5 獨立成新 trigger 類別？")

    conf_wr = st_conf.get("win_rate") or 0
    low_wr  = st_low.get("win_rate") or 0
    if low_wr >= conf_wr:
        lines.append("    → ⚠️  <3/5 Win rate 不低於 confirmed、但樣本量可能偏少")
        lines.append("       建議: 先採 v11 (移除 #3) 觀察 2-3 週")
        lines.append("       若 2/4 watch 仍 Win≥70%、再考慮獨立為「低條件觸發」類別")
    else:
        lines.append("    → <3/5 Win rate 低於 confirmed、不建議獨立")
        lines.append("       維持 skip 分類、專注 confirmed 樣本即可")

    text = "\n".join(lines)
    print(text)
    return text


def write_report(summary_text: str, results: dict, analysis: dict) -> Path:
    report_dir = _REPO / "docs" / "主力大課程" / "strategies"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "phase3_v12_deep_dive_low_score_5_19_to_6_3.md"

    low_score = results["low_score"]
    confirmed = results["confirmed"]
    A = analysis["low"]

    lines = [
        "# Phase 3 v12 — Deep Dive: <3/5 高勝率樣本分析 (5/19-6/3)",
        "",
        "## 背景",
        "",
        "v10 backtest 發現 <3/5 那批樣本 Win rate 異常高、比 confirmed (3-4/5) 還高。",
        "本報告深入分析這批樣本的特徵、找出高勝率的隱藏原因。",
        "",
        "## 執行摘要",
        "",
        "```",
        summary_text,
        "```",
        "",
        "## <3/5 完整樣本明細",
        "",
        "| 進場日 | Ticker | 進場 | 出場 | 淨報酬 | Win | Pass | 缺條件 | 距日高% | 距MA10% | 量比 |",
        "|--------|--------|------|------|--------|-----|------|--------|---------|---------|------|",
    ]

    for r in sorted(low_score, key=lambda x: (x["entry_date"], x["ticker"])):
        win_tag = "✅" if r["win"] else "❌"
        missing = [COND_LABELS[k].split(" ")[0] for k in COND_KEYS if not r["scores"].get(k, False)]
        missing_str = ",".join(missing[:3]) if missing else "—"
        lines.append(
            f"| {r['entry_date']} | {r['ticker']} | {r['entry_price']:.2f} "
            f"| {r['exit_price']:.2f} | {r['net_ret_pct']:+.2f}% | {win_tag} "
            f"| {r['pass_count']}/5 | {missing_str} "
            f"| {r['dist_from_high_pct']:+.1f}% | {r['dist_from_ma10_pct']:+.1f}% "
            f"| {r['vol_ratio']:.2f}x |"
        )

    lines.append("")

    if A:
        # 條件 fail 率表
        lines.append("## 條件 Fail 率分析")
        lines.append("")
        lines.append("| 條件 | <3/5 Fail率 |")
        lines.append("|------|------------|")
        for ck in COND_KEYS:
            label = COND_LABELS.get(ck, ck)
            fail_pct = A["cond_fail_rate"].get(ck, 0)
            lines.append(f"| {label} | {fail_pct:.0f}% |")
        lines.append("")

        # 隔日跳空分布
        lines.append("## 隔日跳空分布")
        lines.append("")
        lines.append("| 跳空區間 | 次數 | 比例 |")
        lines.append("|----------|------|------|")
        for bucket, cnt in sorted(A["gap_buckets"].items()):
            pct = cnt / len(low_score) * 100 if low_score else 0
            lines.append(f"| {bucket} | {cnt} | {pct:.0f}% |")
        lines.append("")

        # Ticker 頻率
        lines.append("## Ticker 出現頻率 (前 15 名)")
        lines.append("")
        lines.append("| Ticker | 出現次數 | 平均報酬 |")
        lines.append("|--------|----------|---------|")
        for tk, cnt in A["ticker_freq"][:15]:
            avg_r = A["ticker_wins"].get(tk, 0)
            lines.append(f"| {tk} | {cnt} | {avg_r:+.2f}% |")
        lines.append("")

        # 市場 Regime
        lines.append("## 市場 Regime 分布")
        lines.append("")
        lines.append("| Regime | 樣本 | Win% |")
        lines.append("|--------|------|------|")
        for reg, d in A.get("regime_win", {}).items():
            emoji = _REGIME_EMOJI.get(reg, reg)
            lines.append(f"| {emoji} | {d['n']} | {_win_emoji(d['win_rate'])} |")
        lines.append("")

    # 對 monitor 建議
    lines.append("## 對 Monitor 建議")
    lines.append("")
    st_low  = calc_stats(low_score)
    st_conf = calc_stats(confirmed)
    low_wr  = st_low.get("win_rate") or 0
    conf_wr = st_conf.get("win_rate") or 0

    if A and A["cond_fail_rate"].get("rebound_confirmed", 0) > 70:
        lines.append("1. **採用 v11 (移除 #3 反彈條件)**：<3/5 主要是因為缺 #3 而被降級，")
        lines.append("   移除後這批樣本升為 v11 的 2/4 watch 或 3/4 confirmed。")
    if low_wr >= conf_wr - 5:
        lines.append("2. **暫不獨立「低分觸發」類別**：先觀察 v11 2 週，若 2/4 watch Win≥70%，")
        lines.append("   再考慮正式納入 confirmed 範疇。")
    else:
        lines.append("2. **維持 skip 分類**：<3/5 Win 不穩定，不建議額外操作。")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  報告寫入: {report_path}")
    return report_path


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Phase 3 v12 Deep Dive <3/5 高勝率分析")
    p.add_argument("--no-report", action="store_true", default=False)
    args = p.parse_args()

    print("Phase 3 v12 — Deep Dive: <3/5 高勝率樣本分析")
    print(f"期間: {TRADING_DATES_FULL[0]} → {TRADING_DATES_FULL[-1]}")
    print()

    results = run_v12_backtest()

    low_score = results["low_score"]
    confirmed = results["confirmed"]
    overheat  = results["overheat"]

    A_low  = analyze_low_score(low_score)
    A_conf = analyze_low_score(confirmed)
    A_oh   = analyze_low_score(overheat)

    analysis = _compare_analysis(A_low, A_conf, A_oh)

    report_text = print_summary(results, analysis)

    if not args.no_report:
        write_report(report_text, results, analysis)


if __name__ == "__main__":
    main()
