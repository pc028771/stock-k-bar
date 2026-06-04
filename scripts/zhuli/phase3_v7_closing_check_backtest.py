"""Phase 3 v7 — Closing_check 尾盤進場確認 Backtest

研究問題:
  老師「尾盤做事情」時段 (13:00-13:25) 的 5 項條件 filter 是否提升 Win rate？

設計:
  - 期間: 2026-05-19 → 2026-06-03 (12 交易日)
  - 對象: 每日 scanner 候選名單 (同 v5/v6)
  - 時段: 13:00-13:25 進場 (只取 13:00 那根 5K 收盤)
  - 出場: 隔日 9:00 開盤 (策略 D、v5 最佳出場)
  - 對比:
      baseline_D: 13:00 進場、無 closing filter (v6 13:00 結果)
      v7_closing: 13:00 進場、通過 Closing_check ≥ 3/5 (watch + confirmed)
      v7_confirmed_only: 13:00 進場、只取 confirmed (5/5)
  - 手續費: -0.6%
  - Score 排序: score_baseline (同 v5)

Usage:
    python scripts/zhuli/phase3_v7_closing_check_backtest.py
    python scripts/zhuli/phase3_v7_closing_check_backtest.py --no-report
    python scripts/zhuli/phase3_v7_closing_check_backtest.py --top 5
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
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

# 手續費 (買 + 賣 + 證交稅) 約 0.6%
FEE_PCT = 0.6

# 交易日清單
TRADING_DATES_FULL = [
    "2026-05-19", "2026-05-20", "2026-05-21", "2026-05-22",
    "2026-05-25", "2026-05-26", "2026-05-27", "2026-05-28", "2026-05-29",
    "2026-06-01", "2026-06-02", "2026-06-03",
]

_REGIME_EMOJI = {"strong": "🟢強", "weak": "🔴弱", "normal": "⚪平"}


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


# ── FinMind 抓取 (5K) ─────────────────────────────────────────────────────────

_finmind_calls = 0
_finmind_call_ts = time.time()


def _rate_limit():
    global _finmind_calls, _finmind_call_ts
    _finmind_calls += 1
    if _finmind_calls % 100 == 0:
        time.sleep(1.0)
        _finmind_call_ts = time.time()
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
    """取指定日期開盤價 (用 standard_daily_bar.open)。"""
    for attempt in range(3):
        try:
            con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=10)
            row = con.execute(
                "SELECT open FROM standard_daily_bar "
                "WHERE ticker=? AND trade_date=?",
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


# ── Score 函式 ────────────────────────────────────────────────────────────────

_TEACHER_TIER_CACHE: dict[str, str] = {}


def _load_teacher_tier() -> dict[str, str]:
    global _TEACHER_TIER_CACHE
    if _TEACHER_TIER_CACHE:
        return _TEACHER_TIER_CACHE
    tier: dict[str, str] = {}
    try:
        picks_path = _REPO / "docs" / "主力大課程" / "data" / "teacher_picks_2026.json"
        if picks_path.exists():
            data = json.loads(picks_path.read_text())
            for item in data if isinstance(data, list) else data.get("picks", []):
                tk = str(item.get("ticker", ""))
                lvl = item.get("tier", "mentioned")
                if tk:
                    tier[tk] = lvl
    except Exception:
        pass
    _TEACHER_TIER_CACHE = tier
    return tier


def _score_trigger(hit: dict) -> float:
    """與 v5 baseline 相同的分數公式。"""
    score = 0.0
    trigger_base = {"Ch5-3": 30, "T1": 20, "T2": 25, "TC": -100}
    score += trigger_base.get(hit.get("layer", ""), 0)

    fire_time = hit.get("entry_time") or "09:30"
    try:
        h, m = int(fire_time[:2]), int(fire_time[3:5])
        minutes_after_910 = (h - 9) * 60 + (m - 10)
        score -= minutes_after_910 * 0.5
    except Exception:
        pass

    tier_map = _load_teacher_tier()
    tier = tier_map.get(hit.get("ticker", ""), "")
    if tier == "core":
        score += 25
    elif tier == "frequent":
        score += 15
    elif tier == "mentioned":
        score += 8

    if hit.get("market_regime") == "strong":
        score += 5

    return score


# ── 主掃描 ─────────────────────────────────────────────────────────────────────

def scan_closing_candidates(
    engine: StageTrigger,
    entry_date: str,
    watchlist: list[str],
    regime: str,
    top_n: int = 5,
) -> list[dict]:
    """對 entry_date 的 watchlist 跑 13:00 進場 + Closing_check。

    回傳所有 ticker 的評估結果 (含 closing_level、pass_count、score)。
    """
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

        # 取 13:00 進場價 (13:00 那根 5K 的收盤)
        k5_1300 = k5_full[k5_full.index.strftime("%H:%M") <= "13:00"]
        if k5_1300.empty:
            continue
        entry_price_1300 = float(k5_1300.iloc[-1]["close"])
        entry_time_str = k5_1300.index[-1].strftime("%H:%M")

        # 跑 Closing_check (用截至 13:00 的 5K 資料，模擬時段內評估)
        closing_r = engine.check_closing_panel(
            ticker=ticker,
            k5=k5_1300,    # 只傳截至 13:00 的資料
            ma10=ma10,
            target_date=entry_date,
            db_path=_DB,
            _now_override="13:00",  # 強制時段觸發
        )

        closing_level = closing_r.get("level", "skip")
        pass_count = closing_r.get("pass_count", 0)
        scores = closing_r.get("scores", {})

        # 取隔日開盤價 (exit)
        next_date = next_trading_day(entry_date, TRADING_DATES_FULL)
        exit_price = None
        exit_date_used = None
        if next_date:
            exit_price = get_open_price_next_day(ticker, next_date)
            exit_date_used = next_date

        if exit_price is None or not entry_price_1300:
            continue

        # 計算報酬
        raw_ret_pct = (exit_price / entry_price_1300 - 1) * 100
        net_ret_pct = round(raw_ret_pct - FEE_PCT, 3)
        win = net_ret_pct > 0

        # 取觸發 layer (在 13:00 前的最後一個 trigger)
        # 為了分類：掃到 13:00 的 composite_check
        r_composite = engine.composite_check(
            ticker=ticker,
            k5=k5_1300,
            prev_close=prev_close,
            prev_levels=prev_levels,
            category="WATCH",
            target_date=entry_date,
        )
        layer = r_composite.get("detector", "none")
        if layer in ("Closing_confirmed", "Closing_watch", "Closing_skip"):
            # composite_check 在 13:00 時段會跑 closing check，layer 可能是這個
            # 我們在這裡重設為 "none" (以觸發層分類不影響 closing 本體)
            layer = "none"

        rec = {
            "entry_date":     entry_date,
            "ticker":         ticker,
            "entry_price":    entry_price_1300,
            "entry_time":     entry_time_str,
            "exit_date":      exit_date_used,
            "exit_price":     exit_price,
            "raw_ret_pct":    round(raw_ret_pct, 3),
            "net_ret_pct":    net_ret_pct,
            "win":            win,
            "closing_level":  closing_level,
            "pass_count":     pass_count,
            "scores":         scores,
            "market_regime":  regime,
            "layer":          layer,
        }
        rec["score"] = _score_trigger(rec)
        results.append(rec)

    return results


# ── 統計函式 ──────────────────────────────────────────────────────────────────

def calc_stats(records: list[dict]) -> dict:
    if not records:
        return {"n": 0, "win_rate": None, "avg_ret": None, "median_ret": None,
                "avg_win": None, "avg_loss": None}
    n = len(records)
    rets = [r["net_ret_pct"] for r in records if r["net_ret_pct"] is not None]
    wins = [r for r in records if r.get("win")]
    losses = [r for r in records if not r.get("win")]
    win_rate = len(wins) / n * 100 if n > 0 else 0
    avg_ret = sum(rets) / len(rets) if rets else 0
    sorted_rets = sorted(rets)
    median_ret = sorted_rets[len(sorted_rets) // 2] if sorted_rets else 0
    avg_win = sum(r["net_ret_pct"] for r in wins) / len(wins) if wins else 0
    avg_loss = sum(r["net_ret_pct"] for r in losses) / len(losses) if losses else 0
    return {
        "n":          n,
        "win_rate":   round(win_rate, 1),
        "avg_ret":    round(avg_ret, 3),
        "median_ret": round(median_ret, 3),
        "avg_win":    round(avg_win, 3),
        "avg_loss":   round(avg_loss, 3),
    }


# ── 主 Backtest ───────────────────────────────────────────────────────────────

def run_v7_backtest(top_n: int = 5) -> dict:
    """
    回傳:
      {
        'all':          [全部 records],
        'baseline_D':   [無 filter、13:00 進]，
        'v7_closing':   [closing ≥ 3/5]，
        'v7_confirmed': [closing 5/5]，
      }
    """
    engine = StageTrigger()
    dates = TRADING_DATES_FULL

    all_records: list[dict] = []

    for scan_date in dates:
        md_path = _TMP / f"scanner_candidates_{scan_date}.md"
        if not md_path.exists():
            print(f"[SKIP] 無 scanner file: {scan_date}")
            continue

        watchlist = parse_scanner_candidates(md_path)
        next_date = next_trading_day(scan_date, dates)
        if not next_date:
            print(f"[SKIP] {scan_date} 沒有下一交易日")
            continue

        regime = engine._detect_market_regime(next_date, db_path=_DB)
        print(f"[{scan_date} → {next_date}] watchlist={len(watchlist)} "
              f"regime={_REGIME_EMOJI.get(regime, regime)}")

        day_records = scan_closing_candidates(
            engine, next_date, watchlist, regime, top_n=top_n
        )

        if day_records:
            # Score 排序、取 top_n
            day_sorted = sorted(day_records, key=lambda x: x.get("score", 0), reverse=True)
            all_records.extend(day_sorted[:top_n])
            print(f"  → {len(day_sorted)} 候選、取 top {min(top_n, len(day_sorted))}")
        else:
            print(f"  → 0 候選")

    # 分組
    baseline_D  = all_records  # 無 filter
    v7_closing  = [r for r in all_records if r["pass_count"] >= 3]  # watch + confirmed
    v7_confirmed = [r for r in all_records if r["closing_level"] == "confirmed"]  # 5/5 only

    return {
        "all":          all_records,
        "baseline_D":   baseline_D,
        "v7_closing":   v7_closing,
        "v7_confirmed": v7_confirmed,
    }


# ── 報告輸出 ──────────────────────────────────────────────────────────────────

def print_summary(results: dict) -> str:
    lines = []

    def _h(title: str):
        lines.append(f"\n{'='*65}")
        lines.append(f"  {title}")
        lines.append(f"{'='*65}")

    def _stat_row(label: str, records: list[dict]):
        st = calc_stats(records)
        if st["n"] == 0:
            lines.append(f"  {label:30}  n=0 (無樣本)")
            return
        wr = f"{st['win_rate']:.1f}%"
        ar = f"{st['avg_ret']:+.2f}%"
        med = f"{st['median_ret']:+.2f}%"
        aw = f"{st['avg_win']:+.2f}%"
        al = f"{st['avg_loss']:+.2f}%"
        lines.append(
            f"  {label:30}  n={st['n']:3}  Win={wr:7}  Avg={ar:8}  "
            f"Med={med:8}  AvgW={aw:7}  AvgL={al:7}"
        )

    _h("Phase 3 v7 — Closing_check Backtest (5/19-6/3)")
    lines.append("  進場: 13:00 收盤 / 出場: 隔日 9:00 開盤 / Fee: -0.6%")
    lines.append(f"  Top-N 選股: {len(results['all'])} 筆總計")

    _h("策略比較 (全日 13:00 進場)")
    _stat_row("baseline_D (無 filter)",   results["baseline_D"])
    _stat_row("v7_closing (≥3/5 pass)",  results["v7_closing"])
    _stat_row("v7_confirmed (5/5 only)", results["v7_confirmed"])

    # 按 closing_level 分組統計
    _h("按 Closing Level 分組")
    for lvl in ("confirmed", "watch", "skip"):
        grp = [r for r in results["all"] if r["closing_level"] == lvl]
        _stat_row(f"  {lvl}", grp)

    # 按 pass_count 分組
    _h("按 Pass Count 分組 (0-5)")
    for pc in range(6):
        grp = [r for r in results["all"] if r["pass_count"] == pc]
        if grp:
            _stat_row(f"  pass_count={pc}", grp)

    # 按 regime 分組
    _h("按大盤環境分組 (v7_closing ≥3/5)")
    for regime in ("strong", "normal", "weak"):
        grp = [r for r in results["v7_closing"] if r["market_regime"] == regime]
        _stat_row(f"  {_REGIME_EMOJI.get(regime, regime)}", grp)

    # 各條件通過率
    _h("各條件通過率 (全部樣本)")
    all_r = results["all"]
    if all_r:
        cond_names = {
            "structure_hold":    "1. 結構守住 (close > MA10)",
            "kill_test_passed":  "2. 殺盤考驗過",
            "rebound_confirmed": "3. 反彈確認 (13:00 後紅K/站MA5)",
            "volume_calm":       "4. 量縮 (非爆量)",
            "not_chasing_high":  "5. 未追高 (距日高 < 1.5%)",
        }
        for k, label in cond_names.items():
            pass_n = sum(1 for r in all_r if r.get("scores", {}).get(k, False))
            pct = pass_n / len(all_r) * 100
            lines.append(f"  {label:40}  {pass_n:3}/{len(all_r)}  ({pct:.1f}%)")

    # 每條件組合的 Win rate
    _h("各條件 On/Off 邊際 Win rate 貢獻")
    if all_r:
        for k, label in {
            "structure_hold":    "1. 結構守住",
            "kill_test_passed":  "2. 殺盤考驗",
            "rebound_confirmed": "3. 反彈確認",
            "volume_calm":       "4. 量縮",
            "not_chasing_high":  "5. 未追高",
        }.items():
            pass_g = [r for r in all_r if r.get("scores", {}).get(k, False)]
            fail_g = [r for r in all_r if not r.get("scores", {}).get(k, False)]
            st_p = calc_stats(pass_g)
            st_f = calc_stats(fail_g)
            wr_p = f"{st_p['win_rate']:.0f}%" if st_p["n"] else "—"
            wr_f = f"{st_f['win_rate']:.0f}%" if st_f["n"] else "—"
            lines.append(f"  {label:20}  pass={wr_p} (n={st_p['n']:2})  fail={wr_f} (n={st_f['n']:2})")

    # 結論
    _h("結論 & v5 對比")
    base_st = calc_stats(results["baseline_D"])
    cl_st   = calc_stats(results["v7_closing"])
    cf_st   = calc_stats(results["v7_confirmed"])
    lines.append(f"  v5 baseline D (隔日出): 已知 Win ~65%、avg +1.85%")
    lines.append(f"  v7 baseline_D (13:00):  Win={base_st['win_rate']}%  avg={base_st['avg_ret']:+.2f}%  n={base_st['n']}")
    lines.append(f"  v7 closing ≥3/5:        Win={cl_st['win_rate']}%  avg={cl_st['avg_ret']:+.2f}%  n={cl_st['n']}")
    lines.append(f"  v7 confirmed 5/5:       Win={cf_st['win_rate']}%  avg={cf_st['avg_ret']:+.2f}%  n={cf_st['n']}")

    if base_st["n"] and cl_st["n"]:
        win_diff = (cl_st["win_rate"] or 0) - (base_st["win_rate"] or 0)
        ret_diff = (cl_st["avg_ret"] or 0) - (base_st["avg_ret"] or 0)
        sample_pct = cl_st["n"] / base_st["n"] * 100 if base_st["n"] else 0
        lines.append(f"\n  Closing filter 效果:")
        lines.append(f"    Win rate 變化: {win_diff:+.1f}%pt")
        lines.append(f"    Avg ret 變化:  {ret_diff:+.3f}%pt")
        lines.append(f"    保留樣本比率:  {sample_pct:.0f}% ({cl_st['n']}/{base_st['n']})")
        if win_diff > 3 and ret_diff > 0:
            lines.append(f"\n  ✅ 建議保留 Closing_check: Win rate 明顯提升 (+{win_diff:.1f}%pt)")
        elif win_diff < -3:
            lines.append(f"\n  ❌ 不建議: Win rate 反而下降 ({win_diff:+.1f}%pt)")
        else:
            lines.append(f"\n  ⚠️  效果有限 (Win rate 變化 {win_diff:+.1f}%pt)、樣本量需更多驗證")

    text = "\n".join(lines)
    print(text)
    return text


def write_report(text: str, results: dict) -> Path:
    report_dir = _REPO / "docs" / "主力大課程" / "strategies"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "phase3_v7_closing_check_5_19_to_6_3.md"

    all_r = results["all"]
    detail_lines = [
        "# Phase 3 v7 — Closing_check Backtest (5/19-6/3)",
        "",
        "## 執行摘要",
        "",
        text,
        "",
        "## 個別紀錄",
        "",
        "| 進場日 | Ticker | 進場 | 進場時間 | 出場日 | 出場 | 淨報酬 | Win | Closing | Pass | 大盤 |",
        "|--------|--------|------|----------|--------|------|--------|-----|---------|------|------|",
    ]
    for r in sorted(all_r, key=lambda x: (x["entry_date"], x["closing_level"], -x["pass_count"])):
        win_tag = "✅" if r["win"] else "❌"
        lvl_emoji = {"confirmed": "🟢", "watch": "🟡", "skip": "🔴"}.get(r["closing_level"], "⚪")
        row = (
            f"| {r['entry_date']} | {r['ticker']} | {r['entry_price']:.2f} "
            f"| {r['entry_time']} | {r['exit_date']} | {r['exit_price']:.2f} "
            f"| {r['net_ret_pct']:+.2f}% | {win_tag} "
            f"| {lvl_emoji}{r['closing_level']} | {r['pass_count']}/5 "
            f"| {_REGIME_EMOJI.get(r['market_regime'], r['market_regime'])} |"
        )
        detail_lines.append(row)

    report_path.write_text("\n".join(detail_lines), encoding="utf-8")
    print(f"\n  報告寫入: {report_path}")
    return report_path


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Phase 3 v7 Closing_check backtest")
    p.add_argument("--no-report", action="store_true", default=False, help="不寫報告檔")
    p.add_argument("--top", type=int, default=5, help="每日取 top-N 標的 (預設 5)")
    args = p.parse_args()

    print("Phase 3 v7 — Closing_check Backtest 啟動")
    print(f"期間: {TRADING_DATES_FULL[0]} → {TRADING_DATES_FULL[-1]}  Top-N={args.top}")
    print()

    results = run_v7_backtest(top_n=args.top)
    report_text = print_summary(results)

    if not args.no_report:
        write_report(report_text, results)


if __name__ == "__main__":
    main()
