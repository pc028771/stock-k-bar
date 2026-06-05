"""F 當沖前夜篩 top 10 backtest — 驗證 confidence score 是否預測勝率.

對過去 N 個交易日：
1. 跑 entry/intraday + confidence score、取 top 10
2. 對每檔 pick: 抓隔日 1m K、模擬簡化 Ch5 當沖出場
3. 統計: 整體勝率、score bucket 分組勝率、teacher tier 對照

簡化出場規則（避免複雜 cascade、聚焦驗證 picking quality）:
- 進場: 隔日 9:10 後第 1 根 5K 過第 1 根高、price = 當下 close
- 停損: max(第 1 根 5K 低、開盤、昨收)
- 達標: +1.5% 走 / 5K 大紅棒 ≥5% 強制出
- 強平: 13:25 收盤

Usage:
    PYTHONPATH=scripts python -m zhuli.intraday_indicators.tests.backtest_top10_intraday \
        --start 2026-05-26 --end 2026-06-04
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

_HERE = Path(__file__).parent
_REPO = _HERE.parent.parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


_CACHE_DIR = Path("/tmp/backtest_1m_cache")
_CACHE_DIR.mkdir(exist_ok=True)


def _fetch_1m(ticker: str, target_date: str) -> pd.DataFrame:
    """抓 FinMind 1m K、本地 parquet cache。"""
    cache = _CACHE_DIR / f"{ticker}_{target_date}.parquet"
    if cache.exists():
        try:
            return pd.read_parquet(cache)
        except Exception:
            cache.unlink(missing_ok=True)

    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        raise SystemExit("FINMIND_TOKEN 未設定")
    r = requests.get(
        "https://api.finmindtrade.com/api/v4/data",
        params={"dataset": "TaiwanStockKBar", "data_id": ticker,
                "start_date": target_date, "end_date": target_date,
                "token": token},
        timeout=30,
    )
    d = r.json().get("data", [])
    if not d:
        # Cache empty result too (parquet with empty rows)
        empty = pd.DataFrame(columns=["open","high","low","close","volume"])
        try:
            empty.to_parquet(cache)
        except Exception:
            pass
        return empty
    df = pd.DataFrame(d)
    df["datetime"] = pd.to_datetime(df["date"].astype(str) + " " + df["minute"].astype(str))
    df = df.sort_values("datetime").set_index("datetime")
    for c in ("open", "high", "low", "close", "volume"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    try:
        df.to_parquet(cache)
    except Exception:
        pass
    return df


def _to_5m(k1m: pd.DataFrame) -> pd.DataFrame:
    return k1m.resample("5min", label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"),
    ).dropna(subset=["open", "close"])


def simulate_daytrade(
    k1m_next: pd.DataFrame, prev_close: float,
    target_pct: float = 1.5,
    stop_variant: str = "A",
) -> dict:
    """簡化 Ch5 當沖出場模擬、回傳 {entered, exit_reason, pnl_pct}.

    Args:
        target_pct: 達標 % (Ch5 範圍 1.5-3.0)
        stop_variant:
            'A' = 雙錨 max(第1根5K低, 開盤, 昨收)
            'B' = 單錨 第1根5K低 (Ch5-3 字面)
            'C' = MA trail 跌破 5K 5MA 出
            'D' = A + C 任一觸發
    """
    if k1m_next.empty or prev_close <= 0:
        return {"entered": False, "exit_reason": "no_data", "pnl_pct": 0.0}

    k5m = _to_5m(k1m_next)
    if len(k5m) < 3:
        return {"entered": False, "exit_reason": "insufficient_5k", "pnl_pct": 0.0}

    open_p = float(k5m["open"].iloc[0])
    first_5k_high = float(k5m["high"].iloc[0])
    first_5k_low  = float(k5m["low"].iloc[0])

    # 5K 5MA (Ch5-3 trailing 用)
    k5m = k5m.copy()
    k5m["ma5"] = k5m["close"].rolling(5, min_periods=1).mean()

    # 靜態 stop (A / B 用、C / D 在 loop 中算 MA)
    if stop_variant == "B":
        stop_static = first_5k_low                          # 單錨
    else:  # A / D 共用雙錨
        stop_static = max(first_5k_low, open_p, prev_close)

    # 找 entry: 9:10 後第一根 5K close > first_5k_high
    entry_price = None
    entry_idx = None
    for i in range(2, len(k5m)):  # i >= 2 對應 9:10 後（5K bar 0=9:00、1=9:05、2=9:10 開始）
        bar = k5m.iloc[i]
        if float(bar["close"]) > first_5k_high:
            entry_price = float(bar["close"])
            entry_idx = i
            break

    if entry_price is None:
        return {"entered": False, "exit_reason": "no_breakout", "pnl_pct": 0.0}

    # 從 entry_idx+1 開始模擬出場
    for j in range(entry_idx + 1, len(k5m)):
        bar = k5m.iloc[j]
        bar_open  = float(bar["open"])
        bar_high  = float(bar["high"])
        bar_low   = float(bar["low"])
        bar_close = float(bar["close"])

        # 停損邏輯依 stop_variant
        bar_ma5 = float(k5m["ma5"].iloc[j]) if not pd.isna(k5m["ma5"].iloc[j]) else None

        triggered_stop = None
        if stop_variant in ("A", "B", "D") and bar_low <= stop_static:
            triggered_stop = (stop_static, "stop_loss")
        if stop_variant in ("C", "D") and bar_ma5 is not None and bar_close < bar_ma5:
            # MA trail：收盤 < 5K 5MA
            if triggered_stop is None:
                triggered_stop = (bar_close, "ma5_trail")

        if triggered_stop is not None:
            exit_px, reason = triggered_stop
            pnl = (exit_px - entry_price) / entry_price * 100
            return {"entered": True, "exit_reason": reason,
                    "pnl_pct": round(pnl, 2),
                    "entry_price": entry_price, "exit_price": exit_px,
                    "entry_idx": entry_idx, "exit_idx": j}

        # 達標 +target_pct: bar high 觸到
        target_price = entry_price * (1 + target_pct / 100)
        if bar_high >= target_price:
            return {"entered": True, "exit_reason": f"target_{target_pct}",
                    "pnl_pct": round(target_pct, 2),
                    "entry_price": entry_price, "exit_price": target_price,
                    "entry_idx": entry_idx, "exit_idx": j}

        # B5-1 5K 大紅棒 >= 5%: 立即出
        bar_change = (bar_close - bar_open) / bar_open * 100 if bar_open > 0 else 0
        if bar_change >= 5.0:
            pnl = (bar_close - entry_price) / entry_price * 100
            return {"entered": True, "exit_reason": "b5_1_exit",
                    "pnl_pct": round(pnl, 2),
                    "entry_price": entry_price, "exit_price": bar_close,
                    "entry_idx": entry_idx, "exit_idx": j}

    # 收盤強平
    last_close = float(k5m["close"].iloc[-1])
    pnl = (last_close - entry_price) / entry_price * 100
    return {"entered": True, "exit_reason": "close",
            "pnl_pct": round(pnl, 2),
            "entry_price": entry_price, "exit_price": last_close,
            "entry_idx": entry_idx, "exit_idx": len(k5m) - 1}


def _score_pure_course(h: dict, today_close: float, prev_close: float | None) -> int:
    """純課程版 scoring — 只用 Ch5-2 距前高、線性遞減 (字面解讀).

    Ch5 課程明示 selection ranking 只有 Ch5-2「距前高越近越好」。
    其他 (MA 結構/量/振幅/周轉/距月線) 都是 entry filter binary pass/fail。
    「右下量 > 左前高量」(Ch5-2) 也是 ranking 因子但未實作。
    """
    d = h.get('dist_prev_high_pct', 99)
    if d > 10:
        return 0
    return round(100 * (1 - d / 10))


def _score_v3_2(h: dict, today_close: float, prev_close: float | None) -> int:
    """v3.2 嚴格課程 + Ch5 範圍內 backtest 細化.

    移除 v3 自編因子：
    - vol_ratio sweet spot (課程沒教)
    - 今日漲幅 +20/-15 (課程沒這個 selection rule、混淆跳空/前 5 分概念)

    保留 (Ch5 範圍內細化):
    - 距前高 3-7% peak (30) — Ch5-2 「<10%」內 sweet spot
    - 距前高 > 7% penalty (-15) — backtest finding (Ch5-2 範圍邊緣)
    - 振幅 8-15% peak (15) — Ch5-1-1 「>8%」內
    - 周轉率 25-50% peak (10) — Ch5-1-1 「>20%」內
    - 老師 tier (5) — info、非主導
    """
    score = 0.0

    # 1. 距前高 — Ch5-2 範圍內 peak at 5%, > 7% penalty
    d = h.get('dist_prev_high_pct', 99)
    if d > 7:
        score -= 15
    elif d <= 7:
        score += 30 * max(0, 1 - abs(d - 5) / 4)

    # 2. 振幅 — Ch5-1-1 「> 8%」內、peak at 12%
    r = h.get('range_3d_pct', 0)
    if r > 25:
        score += 5
    elif r >= 5:
        score += 15 * max(0, 1 - abs(r - 12) / 8)

    # 3. 周轉率 — Ch5-1-1 「> 20%」內、peak at 35%
    turn = h.get('turnover_3d_pct', 0)
    if turn > 80:
        score += 3
    elif turn >= 15:
        score += 10 * max(0, 1 - abs(turn - 35) / 30)

    # 4. 老師 tier (info)
    tt = h.get('teacher_tier', '')
    if tt in ('core', 'frequent'):
        score += 5
    elif tt:
        score += 2

    return round(score)


def _filter_pure_course(intra_hits: list[dict], top_n: int = 10) -> list[dict]:
    """純課程版過濾排序、不額外加 penalty。"""
    enriched = []
    for h in intra_hits:
        h2 = dict(h)
        h2['confidence_score'] = _score_pure_course(
            h2, h2.get('close', 0), h2.get('prev_close'),
        )
        enriched.append(h2)
    enriched.sort(key=lambda x: -x['confidence_score'])
    return enriched[:top_n]


def _filter_v3_2(intra_hits: list[dict], top_n: int = 10) -> list[dict]:
    """v3.2 嚴格課程版過濾排序。"""
    enriched = []
    for h in intra_hits:
        h2 = dict(h)
        h2['confidence_score'] = _score_v3_2(
            h2, h2.get('close', 0), h2.get('prev_close'),
        )
        enriched.append(h2)
    enriched.sort(key=lambda x: -x['confidence_score'])
    return enriched[:top_n]


def get_top10_for_date(target_date: str, db_path: Path, scoring: str = 'v3') -> list[dict]:
    """跑 entry/intraday + filter + score、取 top 10.

    Args:
        scoring: 'v3' (預設、含跳空 penalty) 或 'pure_course' (僅 Ch5-2 距前高)
    """
    from zhuli.entry.intraday import detect as detect_intraday
    from zhuli.daily_scanner_job import (
        _intraday_confidence_score, _filter_and_rank_intraday,
    )

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
    all_tickers = [r[0] for r in con.execute(
        "SELECT DISTINCT ticker FROM standard_daily_bar WHERE trade_date=?",
        (target_date,)
    ).fetchall()]

    ticker_dfs = []
    for t in all_tickers:
        df = pd.read_sql("""
            SELECT ? as ticker, trade_date, trade_date as date,
                   open, high, low, close, volume, vol_ratio_20,
                   ma5, ma10, ma20
            FROM standard_daily_bar
            WHERE ticker=? AND trade_date >= date(?, '-200 days') AND trade_date <= ?
            ORDER BY trade_date
        """, con, params=(t, t, target_date, target_date))
        if len(df) < 100:
            continue
        df["ma5_slope_5d"]  = df["ma5"].diff(5)
        df["ma10_slope_5d"] = df["ma10"].diff(5)
        df["ma20_slope_5d"] = df["ma20"].diff(5)
        ticker_dfs.append(df)
    con.close()

    if not ticker_dfs:
        return []

    combined = pd.concat(ticker_dfs, ignore_index=True)
    sigs = detect_intraday(combined, db_path=db_path)
    if sigs.empty:
        return []

    today_sigs = sigs[sigs["signal_date"].astype(str).str[:10] == target_date]
    if today_sigs.empty:
        return []

    # Build intra_hits format
    intra_hits = []
    for _, row in today_sigs.iterrows():
        t = row["ticker"]
        df_t = next((d for d in ticker_dfs if str(d["ticker"].iloc[0]) == str(t)), None)
        close_val = float(row.get("close") or 0)
        prev_close = None
        last_vr = 0.0
        if df_t is not None and len(df_t) >= 2:
            prev_close = float(df_t.iloc[-2]["close"])
            last_vr = float(df_t.iloc[-1]["vol_ratio_20"]) if pd.notna(df_t.iloc[-1].get("vol_ratio_20")) else 0
        today_change_pct = (close_val / prev_close - 1) * 100 if prev_close else 0.0
        intra_hits.append({
            "ticker": t,
            "close": close_val,
            "prev_close": prev_close,
            "today_change_pct": round(today_change_pct, 1),
            "vol_ratio": round(last_vr, 1),
            "dist_prev_high_pct": round(float(row.get("dist_from_prev_high", 0)) * 100, 1),
            "range_3d_pct": round(float(row.get("range_3d", 0)) * 100, 1),
            "turnover_3d_pct": round(float(row.get("turnover_3d", 0)) * 100, 1),
            "teacher_tier": "",  # not from db, leave blank for pure structural test
        })

    if scoring == 'pure_course':
        return _filter_pure_course(intra_hits, top_n=10)
    if scoring == 'v3_2':
        return _filter_v3_2(intra_hits, top_n=10)
    return _filter_and_rank_intraday(intra_hits, top_n=10)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--csv", default=None, help="輸出 CSV 路徑 (預設 /tmp/backtest_top10_<start>_<end>.csv)")
    p.add_argument("--target", type=float, default=1.5, help="達標 % (Ch5 範圍 1.5-3.0)")
    p.add_argument("--scoring", choices=['v3', 'pure_course', 'v3_2'], default='v3',
                   help="v3=有自編 penalty / pure_course=純 Ch5-2 距前高 / v3_2=嚴格課程+範圍內細化")
    p.add_argument("--stop", choices=['A', 'B', 'C', 'D'], default='A',
                   help="A=雙錨(現) / B=單錨 / C=MA5 trail / D=A+C")
    args = p.parse_args()

    from kline.bars import DEFAULT_DB_PATH

    # 列出範圍內交易日
    con = sqlite3.connect(f"file:{DEFAULT_DB_PATH}?mode=ro", uri=True, timeout=15)
    trade_dates = [r[0] for r in con.execute(
        "SELECT DISTINCT trade_date FROM standard_daily_bar "
        "WHERE trade_date >= ? AND trade_date <= ? ORDER BY trade_date",
        (args.start, args.end)
    ).fetchall()]
    con.close()
    print(f"交易日 ({args.start} ~ {args.end}): {trade_dates}")

    all_results = []
    for i in range(len(trade_dates) - 1):
        sig_date = trade_dates[i]
        next_date = trade_dates[i + 1]
        print(f"\n=== Signal {sig_date} → Next {next_date} ===")
        top10 = get_top10_for_date(sig_date, DEFAULT_DB_PATH, scoring=args.scoring)
        if not top10:
            print(f"  無候選")
            continue

        for rank, pick in enumerate(top10, 1):
            t = pick["ticker"]
            score = pick.get("confidence_score", 0)
            prev_close = pick.get("close", 0)  # 隔日的 prev_close = sig date 收盤
            k1m = _fetch_1m(t, next_date)
            sim = simulate_daytrade(k1m, prev_close, target_pct=args.target,
                                    stop_variant=args.stop)

            all_results.append({
                "sig_date": sig_date, "next_date": next_date, "rank": rank,
                "ticker": t, "score": score,
                "today_change_at_sig": pick.get("today_change_pct", 0),
                "dist_prev_high": pick.get("dist_prev_high_pct", 0),
                "vol_ratio": pick.get("vol_ratio", 0),
                **sim,
            })
            tag = "✅" if sim.get("entered") and sim.get("pnl_pct", 0) > 0 else (
                "❌" if sim.get("entered") and sim.get("pnl_pct", 0) <= 0 else "⏸"
            )
            print(f"  {rank:2} {tag} {t} score={score} {sim['exit_reason']:12} pnl={sim.get('pnl_pct', 0):+.2f}%")

    # 統計
    print("\n=== 統計 ===")
    df_r = pd.DataFrame(all_results)
    if df_r.empty:
        print("無資料")
        return

    csv_path = args.csv or f"/tmp/backtest_top10_{args.start}_{args.end}.csv"
    df_r.to_csv(csv_path, index=False)
    print(f"CSV 輸出: {csv_path}")

    entered = df_r[df_r["entered"] == True]
    print(f"\n總候選: {len(df_r)}、有進場: {len(entered)} ({len(entered)/len(df_r)*100:.1f}%)")
    if not entered.empty:
        wins = entered[entered["pnl_pct"] > 0]
        print(f"進場中勝率: {len(wins)}/{len(entered)} = {len(wins)/len(entered)*100:.1f}%")
        print(f"平均報酬: {entered['pnl_pct'].mean():+.2f}%")
        print(f"中位數: {entered['pnl_pct'].median():+.2f}%")
        print(f"EV (含未進場 = 0): {df_r['pnl_pct'].mean():+.2f}%")

        print(f"\n按 rank 分組:")
        for r in [1, 2, 3]:
            sub = df_r[df_r["rank"] == r]
            sub_e = sub[sub["entered"] == True]
            if not sub.empty:
                ev = sub["pnl_pct"].mean()
                wr = (sub_e["pnl_pct"] > 0).sum() / len(sub_e) * 100 if not sub_e.empty else 0
                print(f"  rank {r}: n={len(sub)}, 進場 {len(sub_e)}, win {wr:.0f}%, EV {ev:+.2f}%")

        print(f"\n按 score bucket 分組:")
        for label, lo, hi in [("🔥 score≥75", 75, 999), ("⭐ 60-74", 60, 75),
                              ("• 45-59", 45, 60), ("- <45", 0, 45)]:
            sub = df_r[(df_r["score"] >= lo) & (df_r["score"] < hi)]
            sub_e = sub[sub["entered"] == True]
            if not sub.empty:
                ev = sub["pnl_pct"].mean()
                wr = (sub_e["pnl_pct"] > 0).sum() / len(sub_e) * 100 if not sub_e.empty else 0
                print(f"  {label}: n={len(sub)}, 進場 {len(sub_e)}, win {wr:.0f}%, EV {ev:+.2f}%")

        print(f"\nexit_reason 分布:")
        print(entered["exit_reason"].value_counts().to_string())


if __name__ == "__main__":
    main()
