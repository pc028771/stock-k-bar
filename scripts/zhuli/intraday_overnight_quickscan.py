"""13:10 隔日沖 overnight quick-scan — 用現價估算今日收盤、預判 overnight 訊號。

Spec: Part 1 of intraday_overnight_quickscan task.

流程:
1. FubonClient 一次抓全市場快照 (TSE + OTC)
2. 對每 ticker:
   - 從 DB standard_daily_bar 讀歷史 200 天
   - 構造「今日 bar」: open/high/low/volume 用 Fubon snap、close 用現價
   - 計算 BB / MA20 / slope / vol_ratio
   - 跑 overnight_swing.detect() 4 條件評估
3. 輸出 data/analysis/zhuli/overnight_swing_scanner_intraday.csv
   - 覆蓋寫、標記 is_intraday=True
4. is_strong = close 超 BB_upper ≥ 2%（估算可信）

限制:
  - 不寫入 standard_daily_bar（只讀 DB）
  - FubonClient 失敗（假日/夜間）→ 寫空 CSV、graceful exit

Usage:
  uv run python scripts/zhuli/intraday_overnight_quickscan.py [--test] [--date YYYY-MM-DD]
"""
from __future__ import annotations

from zhuli.db import get_conn, MAIN_DB

import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

# ── Path setup ────────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent.parent
_SYS  = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_REPO), str(_REPO / "scripts"), str(_SYS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.config import OvernightSwingConfig                            # noqa
from zhuli.entry.overnight_swing import _compute_bbands                  # noqa

# ── Paths ──────────────────────────────────────────────────────────────────────
_DB = MAIN_DB
_OUT_CSV   = _REPO / "data" / "analysis" / "zhuli" / "overnight_swing_scanner_intraday.csv"
_OUT_CSV.parent.mkdir(parents=True, exist_ok=True)

# is_strong 門檻: close 超 BB_upper 幅度 ≥ 2%
IS_STRONG_EXCESS = 0.02

# ── Output schema (align with overnight_swing_scanner.csv) ────────────────────
_OUTPUT_COLS = [
    "ticker", "signal_date", "close", "prev_close", "body_pct",
    "bb_upper", "bandwidth_prev", "volume_lots", "volume_ratio_prev",
    "ma20_slope", "market_pass", "stop_loss", "entry_note",
    "is_intraday", "is_strong",
]


# ── Helpers (reuse pattern from intraday_scanner.py) ─────────────────────────

def _safe_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def fetch_all_snapshots(client) -> dict[str, dict]:
    """一次抓 TSE + OTC 全市場快照，回傳 {ticker: snap_dict}。"""
    print("[quickscan] 抓 TSE 快照…", flush=True)
    tse = client.get_snapshot_quotes("TSE") or []
    print(f"  TSE: {len(tse)} 檔", flush=True)
    print("[quickscan] 抓 OTC 快照…", flush=True)
    otc = client.get_snapshot_quotes("OTC") or []
    print(f"  OTC: {len(otc)} 檔", flush=True)

    snap_map: dict[str, dict] = {}
    for q in tse + otc:
        ticker = (
            q.get("symbol") or q.get("ticker") or q.get("stockId") or
            q.get("stock_id") or q.get("code") or ""
        )
        if not ticker:
            continue
        close = (
            _safe_float(q.get("closePrice"))  or _safe_float(q.get("close_price")) or
            _safe_float(q.get("lastPrice"))   or _safe_float(q.get("last_price"))
        )
        if not close:
            continue
        total = q.get("total") or {}
        shares = _safe_int(
            q.get("totalVolume") or q.get("total_volume") or
            total.get("tradeVolume") or total.get("trade_volume")
        ) or 0
        snap_map[ticker] = {
            "close":        close,
            "open":  _safe_float(q.get("openPrice") or q.get("open_price"))  or close,
            "high":  _safe_float(q.get("highPrice") or q.get("high_price"))  or close,
            "low":   _safe_float(q.get("lowPrice")  or q.get("low_price"))   or close,
            "total_volume": shares // 1000,   # 股→張
        }
    return snap_map


def load_hist_bars(ticker: str, ref_date: str, con: sqlite3.Connection) -> pd.DataFrame:
    """從 DB 取最近 200 日歷史 bars（不含 ref_date 當日）。"""
    return pd.read_sql("""
        SELECT trade_date, open, high, low, close, volume,
               vol_ratio_20, ma5, ma10, ma20, ma60, vol_ma20,
               bb_upper, bb_lower, bb_mid, ma20_slope, ma20_slope_proxy
        FROM standard_daily_bar
        WHERE ticker=? AND trade_date >= date(?, '-200 days') AND trade_date < ?
        ORDER BY trade_date
    """, con, params=(ticker, ref_date, ref_date))


def build_today_bar(snap: dict, hist: pd.DataFrame, ticker: str) -> pd.Series:
    """用快照構造今日 bar，close 為現價。"""
    close = snap["close"]
    vol_ma20 = float(hist["volume"].iloc[-20:].mean()) if len(hist) >= 20 else None
    vol_raw  = snap.get("total_volume", 0) * 1000   # 張→股

    prev_row = hist.iloc[-1] if len(hist) > 0 else None
    return pd.Series({
        "ticker":     ticker,
        "trade_date": "today",
        "open":  snap.get("open",  close),
        "high":  snap.get("high",  close),
        "low":   snap.get("low",   close),
        "close": close,
        "volume": vol_raw,
        "vol_ratio_20": round(vol_raw / vol_ma20, 1) if vol_ma20 and vol_ma20 > 0 else None,
        "ma5":  None, "ma10": None, "ma20": None, "ma60": None,
        "vol_ma20": vol_ma20,
        "bb_upper": None, "bb_lower": None, "bb_mid": None,
        "ma20_slope": None, "ma20_slope_proxy": None,
        "prev_close": float(prev_row["close"]) if prev_row is not None else close,
        "prev_open":  float(prev_row["open"])  if prev_row is not None else close,
        "prev_high":  float(prev_row["high"])  if prev_row is not None else close,
        "prev_low":   float(prev_row["low"])   if prev_row is not None else close,
    })


def build_feature_df(hist: pd.DataFrame, today_bar: pd.Series, ticker: str) -> pd.DataFrame:
    """串接歷史 + 今日 bar，補 MA / prev 欄位 (overnight_swing.detect 所需)。"""
    today_df = pd.DataFrame([today_bar])
    df = pd.concat([hist, today_df], ignore_index=True)
    df["ticker"] = ticker

    # MAs
    df["ma5"]  = df["close"].rolling(5, min_periods=1).mean()
    df["ma10"] = df["close"].rolling(10, min_periods=1).mean()
    df["ma20"] = df["close"].rolling(20, min_periods=1).mean()
    df["ma60"] = df["close"].rolling(60, min_periods=1).mean()

    # prev fields
    df["prev_close"] = df["close"].shift(1)
    df["prev_open"]  = df["open"].shift(1)
    df["prev_high"]  = df["high"].shift(1)
    df["prev_low"]   = df["low"].shift(1)
    df["prev_volume"]= df["volume"].shift(1)

    # ma20 slope (simple 5-bar diff / ma20)
    df["ma20_slope"] = df["ma20"].diff(5) / df["ma20"].replace(0, np.nan)

    # vol_ma20 for BB bandwidth check
    df["vol_ma20"] = df["volume"].rolling(20, min_periods=1).mean()

    # trade_date alias
    df["date"] = df["trade_date"]
    return df


def evaluate_overnight_signal(
    df: pd.DataFrame,
    cfg: OvernightSwingConfig,
    ticker: str,
) -> dict | None:
    """對單一 ticker 的完整 df 評估 overnight_swing 4 條件。
    回傳 signal dict 或 None（未命中）。
    """
    if len(df) < 25:
        return None

    # Inline BB 計算（重用 overnight_swing._compute_bbands logic for single ticker）
    close_s = df["close"]
    bb_mid   = close_s.rolling(20, min_periods=20).mean()
    bb_std   = close_s.rolling(20, min_periods=20).std(ddof=0)
    bb_upper = bb_mid + 2 * bb_std
    bandwidth= (4 * bb_std) / bb_mid.replace(0, np.nan)
    bw_prev  = bandwidth.shift(1)

    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else last

    close_val   = float(last["close"])
    upper_val   = float(bb_upper.iloc[-1]) if not np.isnan(bb_upper.iloc[-1]) else None
    bw_prev_val = float(bw_prev.iloc[-1])  if not np.isnan(bw_prev.iloc[-1])  else None

    if upper_val is None or bw_prev_val is None:
        return None

    # Condition 1: close > BB_upper + bandwidth squeeze
    c1 = (close_val > upper_val) and (bw_prev_val < cfg.bandwidth_max)

    # Condition 2: K棒 + 量
    prev_close_val = float(last["prev_close"]) if not np.isnan(last["prev_close"]) else close_val
    body_pct = (close_val - prev_close_val) / prev_close_val if prev_close_val > 0 else 0.0
    vol_lots = float(last["volume"]) / 1000.0
    prev_vol = float(last["prev_volume"]) if not np.isnan(last["prev_volume"]) else 0.0
    vol_ratio_prev = (float(last["volume"]) / prev_vol) if prev_vol > 0 else 0.0
    c2 = (
        body_pct >= cfg.body_min
        and vol_lots >= cfg.min_volume_lots
        and float(last["volume"]) > prev_vol * cfg.prev_volume_multiplier
    )

    # Condition 3: MA20 斜率
    ma20_slope_val = float(last["ma20_slope"]) if pd.notna(last["ma20_slope"]) else 0.0
    c3 = ma20_slope_val > cfg.ma20_slope_min

    # Condition 4: price >= min_close
    c4 = close_val >= cfg.min_close

    pass_count = sum([c1, c2, c3, c4])

    # 4 條件全過才視為信號輸出
    if not (c1 and c2 and c3 and c4):
        return None

    is_strong = (close_val - upper_val) / upper_val >= IS_STRONG_EXCESS

    entry_note = (
        f"[intraday] close={close_val:.2f} > upper={upper_val:.2f}; "
        f"bw_prev={bw_prev_val:.3f}; "
        f"body={body_pct*100:+.2f}%; "
        f"vol={vol_lots:.0f}張×{vol_ratio_prev:.2f}"
    )

    return {
        "ticker":            ticker,
        "signal_date":       date.today().isoformat(),
        "close":             round(close_val, 2),
        "prev_close":        round(prev_close_val, 2),
        "body_pct":          round(body_pct, 4),
        "bb_upper":          round(upper_val, 2),
        "bandwidth_prev":    round(bw_prev_val, 4),
        "volume_lots":       round(vol_lots, 0),
        "volume_ratio_prev": round(vol_ratio_prev, 2),
        "ma20_slope":        round(ma20_slope_val, 6),
        "market_pass":       True,   # 13:10 沒跑大盤過濾（只評估個股）
        "stop_loss":         round(float(last["prev_low"]), 2) if pd.notna(last.get("prev_low")) else None,
        "entry_note":        entry_note,
        "is_intraday":       True,
        "is_strong":         is_strong,
    }


def write_empty_csv() -> None:
    """快照失敗時寫空 CSV（帶 header）。"""
    pd.DataFrame(columns=_OUTPUT_COLS).to_csv(_OUT_CSV, index=False)
    print(f"⚠️ 快照失敗 → 空 CSV 寫入 {_OUT_CSV}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="13:10 overnight quick-scan (intraday 預估版)")
    ap.add_argument("--test",  action="store_true", help="測試模式：快照失敗時用 DB 最後收盤價代替")
    ap.add_argument("--date",  default=None, help="目標日期 YYYY-MM-DD（預設今天）")
    ap.add_argument("--db",    default=str(_DB))
    args = ap.parse_args()

    target_date = args.date or date.today().isoformat()
    db_path     = Path(args.db)
    cfg         = OvernightSwingConfig()

    print(f"=== 13:10 overnight quick-scan ===")
    print(f"目標日期: {target_date} | 測試模式: {args.test}")

    # ── Step 1: 全市場快照 ────────────────────────────────────────────────────
    snap_map: dict[str, dict] = {}
    fubon_ok = False

    try:
        from clients.fubon_client import FubonClient
        client   = FubonClient()
        snap_map = fetch_all_snapshots(client)
        fubon_ok = True
        print(f"✅ 全市場快照: {len(snap_map)} 檔", flush=True)
        client.disconnect()
    except Exception as e:
        print(f"⚠️ FubonClient 快照失敗: {e}", flush=True)
        if not args.test:
            write_empty_csv()
            return

    # ── Step 2: 載入 DB ───────────────────────────────────────────────────────
    if not db_path.exists():
        print(f"❌ DB 不存在: {db_path}", flush=True)
        write_empty_csv()
        return

    con = get_conn(db_path, timeout=15)

    # 候選 tickers：有現價快照 + 有歷史資料
    if fubon_ok:
        candidate_tickers = list(snap_map.keys())
    else:
        # 測試模式：從 DB 撈最近有資料的 tickers（快照改用 DB 最後一筆）
        rows = con.execute(
            "SELECT DISTINCT ticker FROM standard_daily_bar "
            "ORDER BY trade_date DESC LIMIT 3000"
        ).fetchall()
        candidate_tickers = [r[0] for r in rows]

    print(f"候選池: {len(candidate_tickers)} 檔", flush=True)

    # ── Step 3: 逐 ticker 評估 ────────────────────────────────────────────────
    signals: list[dict] = []
    processed = 0

    for ticker in candidate_tickers:
        hist = load_hist_bars(ticker, target_date, con)
        if len(hist) < 25:
            continue

        snap = snap_map.get(ticker)
        if not snap and args.test:
            # 測試模式 fallback：用 DB 最後一筆
            last = hist.iloc[-1]
            snap = {
                "close": float(last["close"]),
                "open":  float(last["open"]),
                "high":  float(last["high"]),
                "low":   float(last["low"]),
                "total_volume": int(last["volume"] // 1000) if last["volume"] else 0,
            }

        if not snap:
            continue

        try:
            today_bar = build_today_bar(snap, hist, ticker)
            df        = build_feature_df(hist.copy(), today_bar, ticker)
            sig       = evaluate_overnight_signal(df, cfg, ticker)
            if sig is not None:
                signals.append(sig)
        except Exception as ex:
            pass  # 單檔失敗不阻斷全市場掃描

        processed += 1

    con.close()

    # ── Step 4: 輸出 CSV ──────────────────────────────────────────────────────
    if signals:
        out_df = pd.DataFrame(signals, columns=_OUTPUT_COLS)
        out_df.sort_values("ticker", inplace=True)
        out_df.to_csv(_OUT_CSV, index=False)
        strong_count = out_df["is_strong"].sum()
        print(f"\n✅ 信號: {len(signals)} 檔 (其中 {strong_count} 強訊號)")
        print(f"→ {_OUT_CSV}")
        print(out_df[["ticker", "signal_date", "close", "bb_upper", "is_strong"]].to_string(index=False))
    else:
        # 寫空 CSV（有 header）
        pd.DataFrame(columns=_OUTPUT_COLS).to_csv(_OUT_CSV, index=False)
        print(f"\n⚪ 無信號（處理 {processed} 檔）→ 空 CSV 已寫入")
        print(f"→ {_OUT_CSV}")


if __name__ == "__main__":
    main()
