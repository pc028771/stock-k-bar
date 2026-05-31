"""盤中即時 MA5 pivot 翻正偵測器 — 6/2 開盤實戰用.

每 N 秒 (預設 30s) 查 Fubon API live price，對監控標的計算「今日預估 MA5」：
1. 取現時最新成交價 = today_estimated_close
2. 從 DB 取過去 4 日收盤 (D-4 to D-1)
3. 算 estimated_ma5 = mean(last 4 closes + estimated_close)
4. 若 estimated_ma5 slope 今日 > 0 且昨日 ≤ 0（pivot 翻正）
   + MA60/MA120/MA240 全🟢
   + 過去有平台期（動態 platform，≥1 天 MA5 slope ≤ 0）
   → 發出警示

紅線保護:
- 09:00 前不跑（sleep 等開盤）
- 09:00–09:10 跑但印警告「前 10 分鐘不切入」
- 警示後 30 min cooldown（避免洗版）

Backtest 模式:
  --backtest --date YYYY-MM-DD --tickers XXXX
  用 DB 歷史資料模擬當日收盤價，驗證是否能在正確日期觸發。

Usage:
  python scripts/zhuli/intraday_ma5_pivot_monitor.py
  python scripts/zhuli/intraday_ma5_pivot_monitor.py --tickers 2449,3010,1560
  python scripts/zhuli/intraday_ma5_pivot_monitor.py --interval 60
  python scripts/zhuli/intraday_ma5_pivot_monitor.py --until 13:30
  python scripts/zhuli/intraday_ma5_pivot_monitor.py --notify-imessage
  python scripts/zhuli/intraday_ma5_pivot_monitor.py --backtest --date 2026-05-21 --tickers 3481
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# ── Path setup ────────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent.parent
_SYS  = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_REPO), str(_REPO / "scripts"), str(_SYS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

_DB = Path.home() / ".four_seasons" / "data.sqlite"

# ── 預設監控池 ─────────────────────────────────────────────────────────────────
PRIMARY_WATCHLIST: list[str] = [
    # 5/29 黏 MA5 3 天
    "2449", "3010",

    # Tier-B 可進場
    "8046", "4772", "1717", "1560", "4722", "4958", "8021", "4749",

    # 老師 core 未抓到的
    "1605", "6664", "6217", "6207", "1785",
]

# ── 參數 ──────────────────────────────────────────────────────────────────────
COOLDOWN_MINUTES  = 30       # 警示後冷卻分鐘
MARKET_OPEN_HOUR  = 9
MARKET_OPEN_MIN   = 0
MARKET_CLOSE_HOUR = 13
MARKET_CLOSE_MIN  = 30
CAUTION_MIN_LIMIT = 10       # 前 N 分鐘印警告

# 連線共用（整個程式生命週期只 init 一次）
_fubon_client = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _db_con(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)


def _safe_float(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_stock_names(con: sqlite3.Connection) -> dict[str, str]:
    rows = con.execute("SELECT ticker, stock_name FROM stock_info").fetchall()
    return {r[0]: r[1] for r in rows}


def load_hist_bars(ticker: str, ref_date: str, con: sqlite3.Connection,
                   days: int = 500) -> pd.DataFrame:
    """取最近 days 日歷史 bars（不含 ref_date 當日）."""
    df = pd.read_sql("""
        SELECT trade_date, open, high, low, close, volume,
               ma5, ma10, ma60, ma240, vol_ma20
        FROM standard_daily_bar
        WHERE ticker=? AND trade_date >= date(?, ?)
              AND trade_date < ?
        ORDER BY trade_date
    """, con, params=(ticker, ref_date, f"-{days} days", ref_date))
    return df


def compute_mas(df: pd.DataFrame) -> pd.DataFrame:
    """重算 MA5/MA10/MA60/MA120/MA240（用 close rolling）."""
    c = df["close"]
    df = df.copy()
    df["ma5"]   = c.rolling(5,   min_periods=1).mean()
    df["ma10"]  = c.rolling(10,  min_periods=1).mean()
    df["ma60"]  = c.rolling(60,  min_periods=1).mean()
    df["ma120"] = c.rolling(120, min_periods=1).mean()
    df["ma240"] = c.rolling(240, min_periods=1).mean()
    return df


def append_estimated_bar(hist: pd.DataFrame, estimated_close: float,
                         ref_date: str) -> pd.DataFrame:
    """串接 estimated today bar，重算 MA。"""
    # 取前一日 bar 的 open/high/low 保守填入
    if len(hist) > 0:
        prev = hist.iloc[-1]
        today_open = float(prev["close"])
    else:
        today_open = estimated_close

    today_row = pd.DataFrame([{
        "trade_date": ref_date,
        "open":   today_open,
        "high":   max(today_open, estimated_close),
        "low":    min(today_open, estimated_close),
        "close":  estimated_close,
        "volume": 0,
        "ma5":    None, "ma10": None, "ma60": None, "ma240": None,
        "vol_ma20": None, "ma120": None,
    }])
    df = pd.concat([hist, today_row], ignore_index=True)
    df = compute_mas(df)
    return df


# ── Platform detector (inline 精簡版，不 import ma5_pivot_breakout) ─────────────

def _has_platform(ma5_slope_arr: np.ndarray, lookback: int = 60) -> bool:
    """對最後一天，判斷過去 lookback 天內是否有有效 platform.

    邏輯同 ma5_pivot_breakout._compute_platform_flag:
    - 找最後一次「MA5 連續 🟢 ≥ 3 天」結束位置
    - 之後到今日前有 ≥1 天 MA5 slope ≤ 0
    """
    window = ma5_slope_arr[-lookback - 1: -1]  # 不含今日
    if len(window) < lookback:
        window = ma5_slope_arr[:-1]
    if len(window) == 0:
        return False

    green = (window > 0).astype(int)
    platform_start_idx = None
    j = len(window) - 1
    while j >= 0:
        if green[j] == 1:
            streak_end = j
            k = j
            while k >= 0 and green[k] == 1:
                k -= 1
            streak_start = k + 1
            streak_len = streak_end - streak_start + 1
            if streak_len >= 3:
                platform_start_idx = streak_end
                break
            j = k - 1
        else:
            j -= 1

    if platform_start_idx is None:
        return False

    platform_window = window[platform_start_idx + 1:]
    if len(platform_window) == 0:
        return False
    return bool(np.any(platform_window <= 0))


def check_pivot_signal(df_with_today: pd.DataFrame) -> dict:
    """偵測最後一天（estimated today）是否符合 MA5 pivot 翻正條件.

    回傳 dict:
        triggered: bool
        estimated_ma5: float
        yesterday_ma5: float
        slope: float
        long_trend: bool
        has_platform: bool
        dist_ma10_pct: float | None
        diagnostics: dict
    """
    if len(df_with_today) < 5:
        return {"triggered": False, "diagnostics": {"reason": "歷史資料不足 5 天"}}

    c = df_with_today["close"]
    ma5 = df_with_today["ma5"]
    ma60 = df_with_today["ma60"]
    ma120 = df_with_today["ma120"]
    ma240 = df_with_today["ma240"]
    ma10 = df_with_today["ma10"]

    ma5_slope  = ma5.diff()
    ma60_slope = ma60.diff()
    ma120_slope = ma120.diff()
    ma240_slope = ma240.diff()

    idx = len(df_with_today) - 1  # 今日（estimated）

    today_ma5_slope = float(ma5_slope.iloc[idx]) if pd.notna(ma5_slope.iloc[idx]) else 0.0
    prev_ma5_slope  = float(ma5_slope.iloc[idx - 1]) if idx >= 1 and pd.notna(ma5_slope.iloc[idx - 1]) else 0.0

    # 條件 4: MA5 slope 翻正
    cond_pivot = today_ma5_slope > 0 and prev_ma5_slope <= 0

    # 條件 1-3: 三條長線全🟢
    cond_ma60  = bool(pd.notna(ma60_slope.iloc[idx])  and ma60_slope.iloc[idx] > 0)
    cond_ma120 = bool(pd.notna(ma120_slope.iloc[idx]) and ma120_slope.iloc[idx] > 0)
    cond_ma240 = bool(pd.notna(ma240_slope.iloc[idx]) and ma240_slope.iloc[idx] > 0)
    cond_long  = cond_ma60 and cond_ma120 and cond_ma240

    # 條件 5: platform
    slope_arr = ma5_slope.values.astype(float)
    cond_platform = _has_platform(slope_arr)

    # 距 MA10
    current_close = float(c.iloc[idx])
    ma10_val = float(ma10.iloc[idx]) if pd.notna(ma10.iloc[idx]) else None
    dist_ma10_pct = None
    if ma10_val and ma10_val > 0:
        dist_ma10_pct = round((current_close - ma10_val) / ma10_val * 100, 1)

    triggered = cond_pivot and cond_long and cond_platform

    yesterday_ma5 = float(ma5.iloc[idx - 1]) if idx >= 1 and pd.notna(ma5.iloc[idx - 1]) else 0.0

    return {
        "triggered":      triggered,
        "estimated_ma5":  round(float(ma5.iloc[idx]), 3),
        "yesterday_ma5":  round(yesterday_ma5, 3),
        "slope":          round(today_ma5_slope, 3),
        "long_trend":     cond_long,
        "has_platform":   cond_platform,
        "dist_ma10_pct":  dist_ma10_pct,
        "diagnostics": {
            "cond_pivot":    cond_pivot,
            "cond_ma60":     cond_ma60,
            "cond_ma120":    cond_ma120,
            "cond_ma240":    cond_ma240,
            "cond_long":     cond_long,
            "cond_platform": cond_platform,
            "today_ma5_slope": round(today_ma5_slope, 3),
            "prev_ma5_slope":  round(prev_ma5_slope, 3),
        }
    }


# ── Fubon 快照 ────────────────────────────────────────────────────────────────

def get_fubon_client():
    global _fubon_client
    if _fubon_client is None:
        from clients.fubon_client import FubonClient
        _fubon_client = FubonClient()
    return _fubon_client


def fetch_snapshot(ticker: str) -> Optional[dict]:
    """用 FubonClient.get_realtime_snapshot 取單一標的快照."""
    try:
        client = get_fubon_client()
        snap = client.get_realtime_snapshot(ticker)
        return snap
    except Exception as e:
        print(f"  [WARN] fetch_snapshot({ticker}) 失敗: {e}", flush=True)
        return None


# ── iMessage 通知 ─────────────────────────────────────────────────────────────

def send_imessage(msg: str) -> None:
    """透過 osascript 發 iMessage 到 user self-chat."""
    import subprocess
    script = f'''
    tell application "Messages"
        set targetService to 1st service whose service type = iMessage
        set targetBuddy to buddy "pc028771@gmail.com" of targetService
        send "{msg}" to targetBuddy
    end tell
    '''
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
    except Exception as e:
        print(f"  [WARN] iMessage 通知失敗: {e}")


# ── 核心 monitor loop ─────────────────────────────────────────────────────────

def run_monitor(
    tickers: list[str],
    interval_sec: int,
    until_str: Optional[str],
    notify_imessage: bool,
    db_path: Path,
    verbose: bool = False,
) -> None:
    print(f"=== Intraday MA5 Pivot Monitor ===", flush=True)
    print(f"監控標的: {', '.join(tickers)}", flush=True)
    print(f"Polling interval: {interval_sec}s", flush=True)
    print(f"DB: {db_path}", flush=True)
    if until_str:
        print(f"到期時間: {until_str}", flush=True)
    print(flush=True)

    today = date.today().isoformat()
    con = _db_con(db_path)
    stock_names = load_stock_names(con)

    # cooldown 追蹤: {ticker: last_trigger_time}
    cooldown_map: dict[str, datetime] = {}

    # 一次預載所有標的的歷史 (連 DB 太頻繁會慢)
    print("[init] 預載歷史資料...", flush=True)
    hist_cache: dict[str, pd.DataFrame] = {}
    for t in tickers:
        h = load_hist_bars(t, today, con, days=500)
        hist_cache[t] = h
        print(f"  {t}: {len(h)} 天", flush=True)

    con.close()
    print(flush=True)

    loop_count = 0
    while True:
        now = datetime.now()

        # ── 到期檢查 ─────────────────────────────────────────────────────────
        if until_str:
            until_time = datetime.strptime(f"{today} {until_str}", "%Y-%m-%d %H:%M")
            if now >= until_time:
                print(f"[{now:%H:%M:%S}] 到達 {until_str} 結束監控", flush=True)
                break

        # ── 市場時段判斷 ─────────────────────────────────────────────────────
        market_open  = now.replace(hour=MARKET_OPEN_HOUR,  minute=MARKET_OPEN_MIN,  second=0, microsecond=0)
        market_close = now.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MIN, second=0, microsecond=0)
        caution_end  = now.replace(hour=MARKET_OPEN_HOUR,  minute=CAUTION_MIN_LIMIT, second=0, microsecond=0)

        if now < market_open:
            secs_to_open = int((market_open - now).total_seconds())
            print(f"[{now:%H:%M:%S}] 等待開盤 ({secs_to_open}s)...", flush=True)
            time.sleep(min(interval_sec, secs_to_open + 1))
            continue

        if now >= market_close:
            print(f"[{now:%H:%M:%S}] 收盤後，停止監控", flush=True)
            break

        in_caution = (now < caution_end)

        # ── 每個標的偵測 ─────────────────────────────────────────────────────
        loop_count += 1
        print(f"[{now:%H:%M:%S}] Loop #{loop_count}", flush=True)

        for ticker in tickers:
            # cooldown 檢查
            last_trigger = cooldown_map.get(ticker)
            if last_trigger:
                elapsed = (now - last_trigger).total_seconds() / 60
                if elapsed < COOLDOWN_MINUTES:
                    if verbose:
                        print(f"  {ticker}: cooldown ({elapsed:.0f}/{COOLDOWN_MINUTES} min)", flush=True)
                    continue

            # 取快照
            snap = fetch_snapshot(ticker)
            if not snap:
                if verbose:
                    print(f"  {ticker}: 快照失敗 skip", flush=True)
                continue

            estimated_close = snap.get("close")
            if not estimated_close:
                continue

            # 串接 estimated bar
            hist = hist_cache.get(ticker, pd.DataFrame())
            if len(hist) < 5:
                if verbose:
                    print(f"  {ticker}: 歷史不足 skip", flush=True)
                continue

            df_full = append_estimated_bar(hist, estimated_close, today)
            result = check_pivot_signal(df_full)

            if result.get("triggered"):
                name = stock_names.get(ticker, ticker)
                trigger_time = now.strftime("%H:%M:%S")

                # 距 MA10
                dist_str = ""
                if result.get("dist_ma10_pct") is not None:
                    dist_str = f"距MA10: {result['dist_ma10_pct']:+.1f}%"

                # iMessage 文字
                alert_msg = (
                    f"[{trigger_time}] MA5 PIVOT 翻正!\n"
                    f"{ticker} {name}\n"
                    f"現價: {estimated_close:.2f}\n"
                    f"estimated MA5: {result['estimated_ma5']:.2f}\n"
                    f"昨日 MA5: {result['yesterday_ma5']:.2f}\n"
                    f"slope: {result['slope']:+.3f}\n"
                    f"三長線全🟢: {'✓' if result['long_trend'] else '✗'}\n"
                    f"平台確認: {'✓' if result['has_platform'] else '✗'}\n"
                    f"{dist_str}"
                )

                # Console 印警示
                print(flush=True)
                print("=" * 60, flush=True)
                if in_caution:
                    print(f"[{trigger_time}] ⚠️  前 {CAUTION_MIN_LIMIT} 分鐘不切入 (紅線 #8)", flush=True)
                print(f"[{trigger_time}] 🎯 {ticker} {name} MA5 PIVOT 翻正!", flush=True)
                print(f"  現價:             {estimated_close:.2f}", flush=True)
                print(f"  estimated MA5:    {result['estimated_ma5']:.2f}", flush=True)
                print(f"  昨日 MA5:         {result['yesterday_ma5']:.2f}", flush=True)
                print(f"  slope:            {result['slope']:+.3f}", flush=True)
                print(f"  三長線全🟢:        {'✓' if result['long_trend'] else '✗'}", flush=True)
                print(f"  平台確認:          {'✓' if result['has_platform'] else '✗'}", flush=True)
                if result.get("dist_ma10_pct") is not None:
                    print(f"  距MA10:           {result['dist_ma10_pct']:+.1f}%", flush=True)
                if in_caution:
                    print(f"  → ⚠️  前 {CAUTION_MIN_LIMIT} 分鐘不切入，列 watchlist 等 09:10+", flush=True)
                else:
                    print(f"  → 確認 close > 高點 + 量增 可試進場", flush=True)
                print("=" * 60, flush=True)
                print(flush=True)

                # iMessage
                if notify_imessage:
                    send_imessage(alert_msg)

                # 進入 cooldown
                cooldown_map[ticker] = now

            else:
                if verbose:
                    diag = result.get("diagnostics", {})
                    print(
                        f"  {ticker}: close={estimated_close:.2f} "
                        f"est_ma5={result.get('estimated_ma5', '?')} "
                        f"pivot={diag.get('cond_pivot')} "
                        f"long={diag.get('cond_long')} "
                        f"plat={diag.get('cond_platform')}",
                        flush=True,
                    )

        # ── 等待下一個 cycle ─────────────────────────────────────────────────
        print(f"[{datetime.now():%H:%M:%S}] next poll in {interval_sec}s", flush=True)
        time.sleep(interval_sec)


# ── Backtest 模式 ─────────────────────────────────────────────────────────────

def run_backtest(tickers: list[str], backtest_date: str, db_path: Path) -> None:
    """用 DB 歷史資料模擬：對 backtest_date 當天，看 detector 是否觸發.

    模擬方式：
    - 取 backtest_date 當天的 DB 收盤 = "today_estimated_close"
    - 用 backtest_date 前的歷史資料建構 df（不含當天）
    - 串接當天 bar，跑 check_pivot_signal
    - 若觸發 → 印 TRIGGERED（驗證 ground truth）
    """
    print(f"=== Backtest 模式: {backtest_date} ===", flush=True)
    print(f"標的: {', '.join(tickers)}", flush=True)
    print(flush=True)

    con = _db_con(db_path)
    stock_names = load_stock_names(con)

    for ticker in tickers:
        name = stock_names.get(ticker, ticker)
        print(f"── {ticker} {name} ──", flush=True)

        # 取當天的真實收盤（作為 estimated_close）
        row = con.execute(
            "SELECT close FROM standard_daily_bar WHERE ticker=? AND trade_date=?",
            (ticker, backtest_date)
        ).fetchone()
        if not row:
            print(f"  ✗ DB 無 {backtest_date} 收盤資料", flush=True)
            continue
        estimated_close = float(row[0])
        print(f"  當日收盤 (estimated_close): {estimated_close:.2f}", flush=True)

        # 取 backtest_date 前的歷史
        hist = load_hist_bars(ticker, backtest_date, con, days=500)
        print(f"  歷史 bars: {len(hist)} 天", flush=True)

        if len(hist) < 5:
            print(f"  ✗ 歷史不足，skip", flush=True)
            continue

        # 串接 estimated bar
        df_full = append_estimated_bar(hist, estimated_close, backtest_date)
        result = check_pivot_signal(df_full)

        diag = result.get("diagnostics", {})
        print(f"  estimated MA5:   {result.get('estimated_ma5', 'N/A')}", flush=True)
        print(f"  昨日 MA5:        {result.get('yesterday_ma5', 'N/A')}", flush=True)
        print(f"  slope:           {result.get('slope', 'N/A')}", flush=True)
        print(f"  cond_pivot:      {diag.get('cond_pivot')} (today={diag.get('today_ma5_slope')}, prev={diag.get('prev_ma5_slope')})", flush=True)
        print(f"  cond_long_trend: {diag.get('cond_long')} (MA60={diag.get('cond_ma60')} MA120={diag.get('cond_ma120')} MA240={diag.get('cond_ma240')})", flush=True)
        print(f"  cond_platform:   {diag.get('cond_platform')}", flush=True)
        if result.get("dist_ma10_pct") is not None:
            print(f"  距MA10:          {result['dist_ma10_pct']:+.1f}%", flush=True)

        if result["triggered"]:
            print(f"  ✅ TRIGGERED — {backtest_date} MA5 pivot 翻正 (close={estimated_close:.2f})", flush=True)
        else:
            print(f"  ✗ 未觸發", flush=True)
        print(flush=True)

    con.close()


# ── 找最近 N 天內觸發日期（backtest 搜尋模式）────────────────────────────────

def run_backtest_scan(tickers: list[str], db_path: Path, lookback_days: int = 30) -> None:
    """掃過去 lookback_days 天，找每個 ticker 的 pivot 觸發日期."""
    print(f"=== Backtest Scan (過去 {lookback_days} 天) ===", flush=True)
    con = _db_con(db_path)
    stock_names = load_stock_names(con)
    today = date.today().isoformat()

    for ticker in tickers:
        name = stock_names.get(ticker, ticker)
        print(f"── {ticker} {name} ──", flush=True)

        # 取所有交易日
        rows = con.execute(
            "SELECT trade_date FROM standard_daily_bar "
            "WHERE ticker=? AND trade_date >= date(?, ?) AND trade_date <= ? "
            "ORDER BY trade_date",
            (ticker, today, f"-{lookback_days} days", today)
        ).fetchall()

        for (trade_date,) in rows:
            hist = load_hist_bars(ticker, trade_date, con, days=500)
            if len(hist) < 5:
                continue
            row_actual = con.execute(
                "SELECT close FROM standard_daily_bar WHERE ticker=? AND trade_date=?",
                (ticker, trade_date)
            ).fetchone()
            if not row_actual:
                continue
            estimated_close = float(row_actual[0])
            df_full = append_estimated_bar(hist, estimated_close, trade_date)
            result = check_pivot_signal(df_full)
            if result["triggered"]:
                print(f"  ✅ {trade_date}: close={estimated_close:.2f} MA5={result['estimated_ma5']:.2f} slope={result['slope']:+.3f}", flush=True)

        print(flush=True)

    con.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="盤中即時 MA5 pivot 翻正偵測器"
    )
    ap.add_argument(
        "--tickers", default="",
        help="指定監控標的（逗號分隔，e.g. 2449,3010,1560），預設用 PRIMARY_WATCHLIST"
    )
    ap.add_argument(
        "--interval", type=int, default=30,
        help="Polling interval 秒數（預設 30）"
    )
    ap.add_argument(
        "--until", default=None,
        help="監控到指定時間後停止，格式 HH:MM（e.g. 13:30）"
    )
    ap.add_argument(
        "--notify-imessage", action="store_true",
        help="觸發時同時發 iMessage 通知"
    )
    ap.add_argument(
        "--verbose", action="store_true",
        help="印出每個 ticker 的診斷資訊（不只印觸發）"
    )
    ap.add_argument(
        "--db", default=str(_DB),
        help="DB 路徑"
    )

    # Backtest 參數
    ap.add_argument(
        "--backtest", action="store_true",
        help="Backtest 模式（不跑 live，用 DB 歷史資料驗證）"
    )
    ap.add_argument(
        "--date", default=None,
        help="Backtest 目標日期 YYYY-MM-DD"
    )
    ap.add_argument(
        "--scan", action="store_true",
        help="Backtest scan 模式：掃過去 N 天找所有觸發日"
    )
    ap.add_argument(
        "--scan-days", type=int, default=30,
        help="--scan 回看天數（預設 30）"
    )

    args = ap.parse_args()

    # 解析 tickers
    if args.tickers.strip():
        tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = PRIMARY_WATCHLIST

    db_path = Path(args.db)

    if args.backtest:
        if args.scan:
            run_backtest_scan(tickers, db_path, lookback_days=args.scan_days)
        else:
            backtest_date = args.date or date.today().isoformat()
            run_backtest(tickers, backtest_date, db_path)
    else:
        run_monitor(
            tickers=tickers,
            interval_sec=args.interval,
            until_str=args.until,
            notify_imessage=args.notify_imessage,
            db_path=db_path,
            verbose=args.verbose,
        )


if __name__ == "__main__":
    main()
