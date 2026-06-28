"""Pre-compute overnight_swing static features for全 universe (約 332 檔).

設計目的
=========
把「跟今日 close 無關」的靜態 feature 預先算好寫檔，
讓 live_position_monitor_v2 在 13:20 只需要結合 Fubon snap 即時 eval
4 條件（BB / K棒 / MA20 斜率 / 大盤）。

跑時機 (launchd):
- 08:30 (盤前先算一份、含昨日 close)
- 12:30 (中盤 refresh、確保 universe 有更新)
- 手動隨時可跑

Output:
  data/analysis/zhuli/overnight_static_features.json

Schema:
  {
    "_meta": {"generated_at": "...", "asof_date": "YYYY-MM-DD",
              "universe_size": 332, "ok": 320, "partial": 12,
              "db": "...", "duration_sec": 4.5},
    "TAIEX": { ... market features ... },
    "<ticker>": {
        "asof_date": "YYYY-MM-DD",       # 用哪一日 close 算的
        "prev_close":  39.1,             # 該 asof_date 的 close
        "prev_volume": 12345000,         # 該日 volume (shares)
        "vol_20d_avg": 9876543.0,        # 近 20 日均量 (shares)
        "bb_upper":    41.2,             # 20MA + 2*std (用 asof_date 為基準)
        "bb_middle":   38.5,
        "bandwidth_prev": 0.058,         # 4*std/mid (asof_date — eval 時拿這值)
        "ma5":  39.5,
        "ma10": 38.8,
        "ma20": 38.5,
        "ma20_slope_5d": 0.0072,         # (ma20[-1] - ma20[-6]) / ma20[-6]
        "stock_name": "..."
    },
    ...
  }

備註
=====
- 「bandwidth_prev」命名沿用 spec 用詞：eval 時拿這個值做 cfg.bandwidth_max 比較
  （我們是 13:20 在判斷「今日突破上軌時、昨日通道是否夠窄」，所以拿 asof_date 的
  bandwidth 直接當 bw_prev 用）。
- 缺資料的 ticker → 寫入 `{"error": "..."}` 不 skip，monitor 才能顯示「無資料」。
- TAIEX 也算一份，monitor eval 大盤條件時可拿來當 fallback（live 仍會優先用 Fubon snap）。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.db import get_conn, MAIN_DB

import numpy as np
import pandas as pd

# ── path ─────────────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent.parent
_DB = MAIN_DB
_OUT  = _REPO / "data" / "analysis" / "zhuli" / "overnight_static_features.json"
_TEACHER_DIR = _REPO / "docs" / "主力大課程"


# ── universe loader (老師 sector tickers ∪ picks_2026) ──────────────────────
def load_universe() -> list[str]:
    tickers: set[str] = set()
    try:
        with open(_TEACHER_DIR / "teacher_sector_tickers.json",
                  encoding="utf-8") as fh:
            d = json.load(fh)
        for v in d.values():
            if isinstance(v, list):
                tickers.update(str(t) for t in v)
    except Exception as e:
        print(f"[warn] sector tickers 載入失敗: {e}", file=sys.stderr)
    try:
        with open(_TEACHER_DIR / "teacher_picks_2026.json",
                  encoding="utf-8") as fh:
            d = json.load(fh)
        for k in d:
            if isinstance(k, str) and k.isdigit() and len(k) == 4:
                tickers.add(k)
    except Exception as e:
        print(f"[warn] picks_2026 載入失敗: {e}", file=sys.stderr)
    return sorted(tickers)


# ── 單檔 feature 計算 ───────────────────────────────────────────────────────
def compute_features_for_ticker(
    ticker: str, con: sqlite3.Connection, asof_date: str | None = None,
) -> dict:
    """讀近 60 日 bar、算靜態 feature dict。

    asof_date: 給定時 (exclusive) 只取 trade_date < asof_date、用於歷史重播。
    失敗時回傳 {"error": "..."}，不 raise。
    """
    try:
        _where = "WHERE ticker=?" + (" AND trade_date < ?" if asof_date else "")
        df = pd.read_sql_query(
            f"SELECT trade_date, open, close, low, high, volume "
            f"FROM standard_daily_bar {_where} "
            f"ORDER BY trade_date DESC LIMIT 60",
            con, params=((ticker, asof_date) if asof_date else (ticker,)),
        )
    except Exception as e:
        return {"error": f"db_read_fail:{e!s}[:40]"}

    if df.empty:
        return {"error": "no_data"}
    if len(df) < 22:
        # 仍嘗試填部分欄位
        df = df.sort_values("trade_date").reset_index(drop=True)
        last = df.iloc[-1]
        return {
            "error": f"insufficient_bars:{len(df)}",
            "asof_date":  str(last["trade_date"]),
            "prev_close": float(last["close"]),
            "prev_volume": float(last["volume"]),
        }

    df = df.sort_values("trade_date").reset_index(drop=True)
    last = df.iloc[-1]
    asof = str(last["trade_date"])
    close_s = df["close"].astype(float)

    bb_mid = close_s.rolling(20, min_periods=20).mean()
    bb_std = close_s.rolling(20, min_periods=20).std(ddof=0)
    bb_up  = bb_mid + 2 * bb_std
    bandwidth = (4 * bb_std) / bb_mid.replace(0, np.nan)

    ma5  = close_s.rolling(5,  min_periods=5).mean()
    ma10 = close_s.rolling(10, min_periods=10).mean()
    ma20 = close_s.rolling(20, min_periods=20).mean()

    slope_5d = None
    if len(ma20.dropna()) >= 6:
        m_now  = float(ma20.iloc[-1])
        m_prev = float(ma20.iloc[-6])
        if m_prev:
            slope_5d = (m_now - m_prev) / m_prev

    vol_s = df["volume"].astype(float)
    vol_20d_avg = (
        float(vol_s.tail(20).mean()) if len(vol_s) >= 20 else float(vol_s.mean())
    )

    def _f(x):
        try:
            v = float(x)
            return v if (v == v and v not in (float("inf"), float("-inf"))) else None
        except Exception:
            return None

    out = {
        "asof_date":       asof,
        "prev_close":      _f(last["close"]),
        "prev_volume":     _f(last["volume"]),
        "vol_20d_avg":     _f(vol_20d_avg),
        "bb_upper":        _f(bb_up.iloc[-1]),
        "bb_middle":       _f(bb_mid.iloc[-1]),
        "bandwidth_prev":  _f(bandwidth.iloc[-1]),
        "ma5":             _f(ma5.iloc[-1]),
        "ma10":            _f(ma10.iloc[-1]),
        "ma20":            _f(ma20.iloc[-1]),
        "ma20_slope_5d":   _f(slope_5d),
    }
    return out


# ── 大盤 features (TAIEX) — 給 monitor 當大盤條件 fallback ──────────────────
def compute_market_features(con: sqlite3.Connection, asof_date: str | None = None) -> dict:
    out = {}
    for sym in ("TAIEX", "TPEX"):
        try:
            _where = "WHERE ticker=?" + (" AND trade_date < ?" if asof_date else "")
            df = pd.read_sql_query(
                f"SELECT trade_date, open, close, volume "
                f"FROM standard_daily_bar {_where} "
                f"ORDER BY trade_date DESC LIMIT 30",
                con, params=((sym, asof_date) if asof_date else (sym,)),
            )
        except Exception:
            continue
        if df.empty:
            continue
        df = df.sort_values("trade_date").reset_index(drop=True)
        last = df.iloc[-1]
        close_s = df["close"].astype(float)
        ma5 = close_s.rolling(5, min_periods=5).mean()
        out[sym] = {
            "asof_date":   str(last["trade_date"]),
            "prev_close":  float(last["close"]),
            "prev_open":   float(last["open"]),
            "prev_volume": float(last["volume"]),
            "ma5":         (float(ma5.iloc[-1])
                            if not pd.isna(ma5.iloc[-1]) else None),
        }
    return out


def fetch_stock_names(con: sqlite3.Connection, tickers: list[str]) -> dict:
    if not tickers:
        return {}
    try:
        placeholders = ",".join("?" * len(tickers))
        rows = con.execute(
            f"SELECT ticker, stock_name FROM stock_info "
            f"WHERE ticker IN ({placeholders})",
            tickers,
        ).fetchall()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}


# ── main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Pre-compute overnight static features for monitor v2",
    )
    ap.add_argument("--out", type=Path, default=_OUT,
                    help=f"輸出 JSON 路徑 (default: {_OUT})")
    ap.add_argument("--db",  type=Path, default=_DB,
                    help=f"DB 路徑 (default: {_DB})")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"[error] DB 不存在: {args.db}", file=sys.stderr)
        return 1

    universe = load_universe()
    n_univ = len(universe)
    if not args.quiet:
        print(f"[info] universe: {n_univ} 檔")

    t0 = time.time()
    con = get_conn(args.db, timeout=10)

    names = fetch_stock_names(con, universe)
    market = compute_market_features(con)

    out: dict = {}
    ok = 0
    partial = 0
    bad = 0
    for tk in universe:
        feat = compute_features_for_ticker(tk, con)
        feat["stock_name"] = names.get(tk, "")
        out[tk] = feat
        if feat.get("error"):
            if "asof_date" in feat:
                partial += 1
            else:
                bad += 1
        else:
            ok += 1

    con.close()
    dur = time.time() - t0

    asof_date = ""
    for v in out.values():
        if v.get("asof_date"):
            asof_date = max(asof_date, str(v["asof_date"]))

    out["_meta"] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "asof_date":    asof_date,
        "universe_size": n_univ,
        "ok":           ok,
        "partial":      partial,
        "bad":          bad,
        "db":           str(args.db),
        "duration_sec": round(dur, 2),
    }
    out["_market"] = market

    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(args.out)

    if not args.quiet:
        print(f"[ok] {ok} 檔 / partial {partial} / bad {bad} / "
              f"asof={asof_date} / {dur:.2f}s → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
