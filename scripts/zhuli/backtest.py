"""Phase 2 backtest engine — 對 11 scanner 跑歷史模擬.

對任一 scanner，依：
  - Entry: signal_date + 1 day 開盤 (保守模擬，不抓即時尾盤)
  - Exit:
      a) 收盤跌破 stop_loss → 下一個交易日開盤出場
      b) 達 max_hold_days 上限 → 強制出場 (預設 60 天)
  - 報酬 = (exit_price - entry_price) / entry_price

依 CLAUDE.md「禁用 N 日報酬」紅線:
  - 出場必須用 scanner 自帶 stop_loss (課程定義)
  - max_hold 60 天是 operational ceiling，非「N 日報酬法」

Output:
  - trades CSV: 逐筆交易記錄
  - summary stats: hit_rate / avg_return / max_drawdown / sharpe / 持有天數分布

Usage:
    python scripts/zhuli/backtest.py --signal suffocation --start 2024-01-01 --end 2026-05-19
    python scripts/zhuli/backtest.py --all  # 11 scanner 全跑

Course: 主力大全方位操盤教戰守則 + K 線力量入門
"""
from __future__ import annotations

from zhuli.db import get_conn

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

_WORKTREE = Path(__file__).parent.parent.parent
_SCRIPTS_DIR = _WORKTREE / "scripts"
for _p in [str(_WORKTREE), str(_SCRIPTS_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kline.bars import DEFAULT_DB_PATH
from kline.features import load_features_cached
from zhuli.features import add_zhuli_features
from zhuli.entry import ENTRY_REGISTRY, EXIT_ONLY_SCANNERS, MASTER_SCANNERS


# Scanner 對應的 detect args (有些 scanner 要 db_path)
_SCANNER_NEEDS_DB = {"institutional_firstbuy", "institutional_swing", "intraday", "overnight_swing"}

# Scanner default config 對應 — 直接從 ENTRY_REGISTRY detect 用 default config
_SCANNER_NEEDS_INST = {"institutional_firstbuy"}

# Scanner 課程中文名對應 (依 strategy-indicators.md 章節名稱)
SCANNER_DISPLAY_NAMES = {
    "suffocation":              "H 窒息量",
    "open_signal_filter":       "M 主力意圖(master)",
    "open_signal_entry":        "M+ 收低開高(進場)",
    "open_signal_exit":         "M- 收高開低(出場警示)",
    "institutional_firstbuy":   "J 投信首買",
    "swing_breakout":           "A 大波段",
    "bbands_upper_break":       "D 布林上軌",
    "overnight_swing":          "G 隔日沖",
    "reversal_breakout":        "C 反轉形態",
    "pennant_flag":             "B 旗形(奇形)",
    "institutional_swing":      "I 投信跟單",
    "intraday":                 "F 當沖",
    "bollinger_pullback":       "E 布林回測",
}

# Per-scanner backtest 客製化參數
# 課程設計交易期不同 → entry timing + max_hold 必須跟著
# entry_mode:
#   "next_day_open" (預設, 波段 scanner) — entry = signal_date+1 day open
#   "signal_day_close" (G 隔日沖) — entry = signal_date close, exit = next day open
SCANNER_BACKTEST_OVERRIDES = {
    # G 隔日沖: 「今天尾盤買、隔天開盤賣」 — entry close, exit next day open
    "overnight_swing": {"max_hold_days": 1, "entry_mode": "signal_day_close"},
    # F 當沖: 「當日進出」 — 用日 K 近似為 signal_day_close + 1 day
    "intraday": {"max_hold_days": 1, "entry_mode": "signal_day_close"},
    # A 大波段: 課程「波段 = 月以上」, hold > 60 天 trades 87% hit / +31% avg
    "swing_breakout": {"max_hold_days": 120},
    # I 投信跟單: 同樣是中長波段
    "institutional_swing": {"max_hold_days": 120},
    # J 投信首買: 中波段
    "institutional_firstbuy": {"max_hold_days": 90},
}

# Top-N per day ranking — 每個 scanner 用哪個欄位排序「最強」signal
# 統一原則：「攻擊強度」優先 — 出量大 / 漲幅大 / 法人買量大 / 距前高近
# tuple = (column_name, ascending) ; ascending=False = 大 = 強
SCANNER_RANKING = {
    "suffocation":              ("breakout_vol", False),          # 出量越大越強
    "open_signal_entry":        ("today_open_gap_pct", False),     # 開高越多越強
    "institutional_firstbuy":   ("sitc_net", False),               # 投信買越多越強
    "swing_breakout":           ("sector_density", False),         # 族群越大越強
    "bbands_upper_break":       ("volume_ratio_prev", False),      # 量增越多越強 (改)
    "overnight_swing":          ("body_pct", False),               # 漲幅越大越強
    "reversal_breakout":        ("decline_pct_60d", False),        # 跌深越深反轉力越強 (改)
    "pennant_flag":             ("pole_volume", False),            # 旗杆量越大越強 (改, 表示主力進場)
    "institutional_swing":      ("buy_pct_of_shares", False),      # 5d 投本比越大越強
    "intraday":                 ("dist_from_prev_high", True),     # 越接近前高越強 (小)
    "bollinger_pullback":       ("attack_vol_ratio", False),       # 攻擊量越大越強 (改)
}


@dataclass
class BacktestConfig:
    start_date: str = "2024-01-01"
    end_date: str = "2026-05-19"
    max_hold_days: int = 60       # 持有上限
    initial_capital: float = 1_000_000  # 用於 sharpe / drawdown 計算
    # 滑價估計 (進場買貴 / 出場賣便宜)
    slippage_pct: float = 0.003   # 0.3%
    # First appearance dedupe: 同 ticker 在 N 天內只取第一個 signal
    # (避免同事件重複進場稀釋勝率)
    first_appearance_days: int = 30
    # Top-N per day ranking: 每天每 scanner 取 ranking 最強 N 筆 (0 = 不過濾)
    # (取「最高品質」signal,過濾掉勉強過篩的低品質 signal,拉勝率)
    top_n_per_day: int = 5


def _load_minute_bars(db_path_minute: Optional[Path] = None) -> dict:
    """載入 stock_minute_kbar → dict[ticker -> DataFrame(trade_datetime, open, high, low, close)].

    DB: ~/.four_seasons/data.sqlite (stock_minute_kbar)
    """
    minute_db = db_path_minute or Path.home() / ".four_seasons" / "data.sqlite"
    if not minute_db.exists():
        return {}
    try:
        conn = get_conn(minute_db)
        df = pd.read_sql_query(
            "SELECT ticker, trade_datetime, open, high, low, close FROM stock_minute_kbar ORDER BY ticker, trade_datetime",
            conn,
        )
        conn.close()
    except Exception:
        return {}
    df["trade_datetime"] = pd.to_datetime(df["trade_datetime"])
    df["trade_date"] = df["trade_datetime"].dt.date.astype(str)
    result = {t: g.reset_index(drop=True) for t, g in df.groupby("ticker")}
    return result


def _check_close_session_entry(
    ticker: str,
    entry_date: pd.Timestamp,  # D+1 (the day we want to enter)
    minute_bars: dict,
    slippage_pct: float,
) -> tuple[Optional[float], str]:
    """Apply 尾盤進場紀律 4 filters on entry_date (D+1).

    Returns:
        (entry_price, skip_reason) — if entry_price is None → skip
    Filters:
        1. gap_pct = (D+1 open - D close) / D close ≥ +5% → skip
           NOTE: we use D+1 open vs D+1 first bar open as proxy (no D close in minute)
           We detect gap by comparing D+1 open to prev day daily close passed in.
        2. first_5min surge: D+1 first 5 bars close vs D+1 open ≥ +5% → skip
        3. No entry before 09:10 — we only use bars ≥ 13:00
        4. Entry window: 13:00–13:25 last available bar close
    """
    entry_date_str = entry_date.strftime("%Y-%m-%d")
    mbars = minute_bars.get(ticker)
    if mbars is None or mbars.empty:
        return None, "no_minute_data"

    day_bars = mbars[mbars["trade_date"] == entry_date_str].copy()
    if day_bars.empty:
        return None, "no_minute_data"
    day_bars = day_bars.sort_values("trade_datetime").reset_index(drop=True)

    # Filter 2: first 5 bars (09:00-09:25 roughly) surge > 5%
    day_open = day_bars.iloc[0]["open"]
    first5 = day_bars.head(5)
    first5_close = first5.iloc[-1]["close"] if len(first5) > 0 else day_open
    if day_open > 0 and (first5_close - day_open) / day_open >= 0.05:
        return None, "skip_first5min_surge"

    # Entry window: 13:00-13:25
    # Use time string comparison
    window = day_bars[day_bars["trade_datetime"].dt.strftime("%H:%M") >= "13:00"]
    window = window[window["trade_datetime"].dt.strftime("%H:%M") <= "13:25"]
    if window.empty:
        # No bars in window — try last bar before 13:30 as fallback
        late = day_bars[day_bars["trade_datetime"].dt.strftime("%H:%M") <= "13:30"]
        if late.empty:
            return None, "no_closing_window_bar"
        entry_bar = late.iloc[-1]
    else:
        entry_bar = window.iloc[-1]

    entry_price = entry_bar["close"] * (1 + slippage_pct)
    return entry_price, "ok"


def _get_trade_outcome(
    sub: pd.DataFrame,   # 已預過濾且 sorted 的單一 ticker bars
    signal_date: pd.Timestamp,
    stop_loss: float,
    max_hold_days: int,
    slippage_pct: float,
    ticker: str,
    entry_mode: str = "next_day_open",
    minute_bars: Optional[dict] = None,
    prev_close: Optional[float] = None,  # D close (for gap filter)
    skip_stats: Optional[dict] = None,   # mutable dict to accumulate skip reasons
) -> Optional[dict]:
    """模擬單筆交易. Returns trade dict or None if can't enter.

    entry_mode:
        "next_day_open": entry = signal_date+1 day open (波段預設)
        "signal_day_close": entry = signal_date close, exit = next day open (G 隔日沖)
        "close_session_disciplined": entry = D+1 尾盤 13:00-13:25, with 4-filter skip logic
    """
    # === close_session_disciplined: 尾盤進場紀律 ===
    if entry_mode == "close_session_disciplined":
        after = sub[sub["trade_date"] > signal_date].head(1)
        if after.empty:
            return None
        entry_day_row = after.iloc[0]
        entry_date = entry_day_row["trade_date"]

        # Filter 1: Gap ≥ +5% on D+1 open vs D close
        d_close = prev_close if prev_close and prev_close > 0 else None
        if d_close is None:
            # fallback: use signal day close from sub
            sig_row = sub[sub["trade_date"] == signal_date]
            d_close = sig_row.iloc[0]["close"] if not sig_row.empty else None
        if d_close and d_close > 0:
            gap_pct = (entry_day_row["open"] - d_close) / d_close
            if gap_pct >= 0.05:
                if skip_stats is not None:
                    skip_stats["skip_gap_5pct"] = skip_stats.get("skip_gap_5pct", 0) + 1
                return None

        # Filters 2-4 via minute bars
        if minute_bars is None:
            if skip_stats is not None:
                skip_stats["skip_no_minute_data"] = skip_stats.get("skip_no_minute_data", 0) + 1
            return None
        entry_price, reason = _check_close_session_entry(ticker, entry_date, minute_bars, slippage_pct)
        if entry_price is None:
            if skip_stats is not None:
                key = f"skip_{reason}"
                skip_stats[key] = skip_stats.get(key, 0) + 1
            return None

        # Exit: use daily bars from D+1 onward with stop_loss / max_hold (same as next_day_open)
        future = sub[sub["trade_date"] >= entry_date].reset_index(drop=True)
        if future.empty:
            return None

        for i in range(min(len(future), max_hold_days)):
            row = future.iloc[i]
            if row["close"] < stop_loss:
                if i + 1 < len(future):
                    exit_row = future.iloc[i + 1]
                    exit_price = exit_row["open"] * (1 - slippage_pct)
                    exit_date = exit_row["trade_date"]
                    exit_reason = "stop_loss"
                else:
                    exit_price = row["close"] * (1 - slippage_pct)
                    exit_date = row["trade_date"]
                    exit_reason = "stop_loss_eod"
                hold_days = i + 1
                break
        else:
            last_row = future.iloc[min(len(future), max_hold_days) - 1]
            exit_price = last_row["close"] * (1 - slippage_pct)
            exit_date = last_row["trade_date"]
            exit_reason = "max_hold"
            hold_days = min(len(future), max_hold_days)

        ret = (exit_price - entry_price) / entry_price
        return {
            "ticker": ticker,
            "signal_date": signal_date.strftime("%Y-%m-%d") if hasattr(signal_date, "strftime") else str(signal_date),
            "entry_date": entry_date.strftime("%Y-%m-%d") if hasattr(entry_date, "strftime") else str(entry_date),
            "exit_date": exit_date.strftime("%Y-%m-%d") if hasattr(exit_date, "strftime") else str(exit_date),
            "entry_price": round(entry_price, 4),
            "exit_price": round(exit_price, 4),
            "stop_loss": round(stop_loss, 4),
            "hold_days": hold_days,
            "return_pct": round(ret * 100, 3),
            "exit_reason": exit_reason,
        }

    if entry_mode == "signal_day_close":
        # G 隔日沖: 當日尾盤買進 (signal_date close), 隔日 open 賣
        sig_row = sub[sub["trade_date"] == signal_date]
        if sig_row.empty:
            return None
        entry_price = sig_row.iloc[0]["close"] * (1 + slippage_pct)
        entry_date = sig_row.iloc[0]["trade_date"]
        # 隔日 (next day) open 出場
        after = sub[sub["trade_date"] > signal_date].head(1)
        if after.empty:
            return None
        exit_row = after.iloc[0]
        exit_price = exit_row["open"] * (1 - slippage_pct)
        exit_date = exit_row["trade_date"]
        ret = (exit_price - entry_price) / entry_price
        return {
            "ticker": ticker,
            "signal_date": signal_date.strftime("%Y-%m-%d") if hasattr(signal_date, "strftime") else str(signal_date),
            "entry_date": entry_date.strftime("%Y-%m-%d") if hasattr(entry_date, "strftime") else str(entry_date),
            "exit_date": exit_date.strftime("%Y-%m-%d") if hasattr(exit_date, "strftime") else str(exit_date),
            "entry_price": round(entry_price, 4),
            "exit_price": round(exit_price, 4),
            "stop_loss": round(stop_loss, 4),
            "hold_days": 1,
            "return_pct": round(ret * 100, 3),
            "exit_reason": "overnight_exit",
        }

    # === next_day_open 預設模式 (波段 scanner) ===
    after = sub[sub["trade_date"] > signal_date].head(max_hold_days + 1)
    if after.empty:
        return None
    entry_row = after.iloc[0]
    entry_price = entry_row["open"] * (1 + slippage_pct)
    entry_date = entry_row["trade_date"]

    # 找 exit: 收盤跌破 stop_loss 或 max_hold 到
    for i in range(len(after)):
        row = after.iloc[i]
        if row["close"] < stop_loss:
            # 收盤確認跌破 → 下一交易日開盤出場
            if i + 1 < len(after):
                exit_row = after.iloc[i + 1]
                exit_price = exit_row["open"] * (1 - slippage_pct)
                exit_date = exit_row["trade_date"]
                exit_reason = "stop_loss"
            else:
                exit_price = row["close"] * (1 - slippage_pct)
                exit_date = row["trade_date"]
                exit_reason = "stop_loss_eod"
            hold_days = i + 1
            break
    else:
        # max_hold 到
        last_row = after.iloc[-1]
        exit_price = last_row["close"] * (1 - slippage_pct)
        exit_date = last_row["trade_date"]
        exit_reason = "max_hold"
        hold_days = len(after)

    ret = (exit_price - entry_price) / entry_price
    return {
        "ticker": ticker,
        "signal_date": signal_date.strftime("%Y-%m-%d") if hasattr(signal_date, 'strftime') else str(signal_date),
        "entry_date": entry_date.strftime("%Y-%m-%d") if hasattr(entry_date, 'strftime') else str(entry_date),
        "exit_date": exit_date.strftime("%Y-%m-%d") if hasattr(exit_date, 'strftime') else str(exit_date),
        "entry_price": round(entry_price, 4),
        "exit_price": round(exit_price, 4),
        "stop_loss": round(stop_loss, 4),
        "hold_days": hold_days,
        "return_pct": round(ret * 100, 3),
        "exit_reason": exit_reason,
    }


def run_backtest_for_scanner(
    scanner_name: str,
    bars: pd.DataFrame,
    feats: pd.DataFrame,
    cfg: BacktestConfig,
    db_path: Path,
    global_entry_mode_override: Optional[str] = None,  # override ALL scanner entry modes
    minute_bars: Optional[dict] = None,  # for close_session_disciplined mode
) -> tuple[pd.DataFrame, dict]:
    """跑單個 scanner 的 backtest. Returns (trades_df, stats)."""

    detect_fn = ENTRY_REGISTRY[scanner_name]
    display = SCANNER_DISPLAY_NAMES.get(scanner_name, scanner_name)
    print(f"\n--- {display} ({scanner_name}) backtest ---")
    # Apply scanner-specific cfg override
    scanner_cfg = SCANNER_BACKTEST_OVERRIDES.get(scanner_name, {})
    effective_max_hold = scanner_cfg.get("max_hold_days", cfg.max_hold_days)
    effective_entry_mode = scanner_cfg.get("entry_mode", "next_day_open")
    if scanner_cfg:
        print(f"  ⚙️  per-scanner override: max_hold={effective_max_hold}, entry_mode={effective_entry_mode}")

    # Global entry mode override (e.g. close_session_disciplined) overrides per-scanner defaults
    # but NOT signal_day_close scanners (G/F are fundamentally different strategies)
    if global_entry_mode_override and effective_entry_mode != "signal_day_close":
        effective_entry_mode = global_entry_mode_override
        print(f"  🎯 global entry_mode override: {effective_entry_mode}")

    # 跑 scanner on full history
    kwargs = {}
    if scanner_name in _SCANNER_NEEDS_DB:
        kwargs["db_path"] = db_path

    # institutional_firstbuy 要 inst_df
    if scanner_name == "institutional_firstbuy":
        from zhuli.entry.institutional_firstbuy import load_institutional
        kwargs["inst_df"] = load_institutional(db_path)

    try:
        signals = detect_fn(feats, **kwargs)
    except Exception as exc:
        print(f"  detect ERROR: {exc}")
        return pd.DataFrame(), {"error": str(exc)}

    if signals.empty:
        return pd.DataFrame(), {"trades": 0, "note": "no signals"}

    # Filter to date range
    signals["sig_date_dt"] = pd.to_datetime(signals["signal_date"])
    start_dt = pd.Timestamp(cfg.start_date)
    end_dt = pd.Timestamp(cfg.end_date)
    signals = signals[(signals["sig_date_dt"] >= start_dt) & (signals["sig_date_dt"] <= end_dt)]
    n_raw = len(signals)
    print(f"  {n_raw} signals in {cfg.start_date} ~ {cfg.end_date}")
    if signals.empty:
        return pd.DataFrame(), {"trades": 0, "note": "no signals in date range"}

    # First appearance dedupe: 同 ticker N 天內取第一筆
    # (除了 G/F 1 天交易 — 它們不需要 dedupe，本來就是高頻)
    if scanner_name not in {"overnight_swing", "intraday"} and cfg.first_appearance_days > 0:
        signals = signals.sort_values(["ticker", "sig_date_dt"]).reset_index(drop=True)
        signals["prev_sig"] = signals.groupby("ticker")["sig_date_dt"].shift(1)
        signals["days_since"] = (signals["sig_date_dt"] - signals["prev_sig"]).dt.days
        keep = signals["days_since"].isna() | (signals["days_since"] >= cfg.first_appearance_days)
        signals = signals[keep].drop(columns=["prev_sig", "days_since"])
        n_dedup = len(signals)
        print(f"  → after {cfg.first_appearance_days}-day dedupe: {n_dedup} signals (- {n_raw - n_dedup})")

    # Top-N per day ranking — 取每天 ranking 最強 N 名
    rank_cfg = SCANNER_RANKING.get(scanner_name)
    if rank_cfg and cfg.top_n_per_day > 0:
        rank_col, ascending = rank_cfg
        if rank_col in signals.columns:
            before = len(signals)
            signals = signals.sort_values(
                ["sig_date_dt", rank_col], ascending=[True, ascending]
            )
            signals = signals.groupby("sig_date_dt").head(cfg.top_n_per_day).reset_index(drop=True)
            print(f"  → top-{cfg.top_n_per_day} per day (rank by {rank_col}, asc={ascending}): "
                  f"{len(signals)} signals (- {before - len(signals)})")
        else:
            print(f"  ⚠️ rank_col '{rank_col}' not in signals, skip ranking")

    # Identify stop_loss column
    stop_col = "stop_loss" if "stop_loss" in signals.columns else None
    if not stop_col:
        # fallback: 用 signal 日 close × 0.95 (5% 停損)
        signals["stop_loss"] = signals["close"] * 0.95 if "close" in signals.columns else None

    # 預先建立 ticker -> bars dict (避免每筆 signal 都 filter 全表)
    unique_tickers = signals["ticker"].unique()
    print(f"  建立 ticker bars dict ({len(unique_tickers)} tickers)...")
    bars_relevant = bars[bars["ticker"].isin(unique_tickers)][["ticker", "trade_date", "open", "high", "low", "close"]]
    bars_relevant = bars_relevant.sort_values(["ticker", "trade_date"]).reset_index(drop=True)
    ticker_bars: dict = {t: g.reset_index(drop=True) for t, g in bars_relevant.groupby("ticker")}

    # 每筆 signal 模擬交易
    trades = []
    skip_stats: dict = {}  # accumulate skip reasons for close_session_disciplined
    n_sig = len(signals)
    # Pre-build ticker -> prev_close dict for gap filter
    # (signal date close, looked up from daily bars)
    prev_close_map: dict = {}
    if effective_entry_mode == "close_session_disciplined":
        for t, tdf in ticker_bars.items():
            # dict: date_str -> close
            prev_close_map[t] = dict(zip(tdf["trade_date"].astype(str), tdf["close"]))

    for i, sig in enumerate(signals.itertuples(index=False), 1):
        if i % 2000 == 0:
            print(f"    progress {i}/{n_sig}...")
        stop = getattr(sig, "stop_loss", None)
        if stop is None or pd.isna(stop) or stop <= 0:
            continue
        sub = ticker_bars.get(sig.ticker)
        if sub is None:
            continue
        # Get prev_close for gap filter
        prev_close = None
        if effective_entry_mode == "close_session_disciplined":
            sig_date_str = sig.sig_date_dt.strftime("%Y-%m-%d") if hasattr(sig.sig_date_dt, "strftime") else str(sig.sig_date_dt)
            prev_close = prev_close_map.get(sig.ticker, {}).get(sig_date_str)
        trade = _get_trade_outcome(
            sub, sig.sig_date_dt, float(stop), effective_max_hold, cfg.slippage_pct, sig.ticker,
            entry_mode=effective_entry_mode,
            minute_bars=minute_bars,
            prev_close=prev_close,
            skip_stats=skip_stats,
        )
        if trade:
            trade["scanner"] = scanner_name
            trades.append(trade)

    if effective_entry_mode == "close_session_disciplined" and skip_stats:
        print(f"  📊 skip reasons: {skip_stats}")

    if not trades:
        return pd.DataFrame(), {"trades": 0, "note": "no valid trades"}

    df = pd.DataFrame(trades)

    # 計算統計
    n = len(df)
    wins = df[df["return_pct"] > 0]
    losses = df[df["return_pct"] <= 0]
    hit_rate = len(wins) / n if n > 0 else 0
    avg_ret = df["return_pct"].mean()
    avg_win = wins["return_pct"].mean() if len(wins) > 0 else 0
    avg_loss = losses["return_pct"].mean() if len(losses) > 0 else 0
    profit_factor = abs(wins["return_pct"].sum() / losses["return_pct"].sum()) if len(losses) > 0 and losses["return_pct"].sum() != 0 else float("inf")

    # 單筆 worst loss / best win
    worst_loss = df["return_pct"].min()
    best_win = df["return_pct"].max()

    # 最大連續虧損 streak（per-trade level，按 entry_date 序）
    df_sorted = df.sort_values("entry_date").reset_index(drop=True)
    losses = (df_sorted["return_pct"] <= 0).astype(int)
    # 計算連續 1 的最大長度
    max_loss_streak = 0
    cur = 0
    for v in losses:
        cur = cur + 1 if v else 0
        max_loss_streak = max(max_loss_streak, cur)

    # Sharpe (簡化版 — per-trade std + 年化)
    ret_std = df["return_pct"].std()
    sharpe = (avg_ret / ret_std) * np.sqrt(252 / df["hold_days"].mean()) if ret_std > 0 and df["hold_days"].mean() > 0 else 0

    # 期望值 (per trade)
    expected_value = hit_rate * avg_win + (1 - hit_rate) * avg_loss

    # Exit reason 分布
    exit_dist = df["exit_reason"].value_counts().to_dict()

    stats = {
        "trades": n,
        "signals_fired": n_sig,
        "hit_rate_pct": round(hit_rate * 100, 2),
        "avg_return_pct": round(avg_ret, 3),
        "avg_win_pct": round(avg_win, 3),
        "avg_loss_pct": round(avg_loss, 3),
        "worst_loss_pct": round(worst_loss, 2),
        "best_win_pct": round(best_win, 2),
        "expected_value_pct": round(expected_value, 3),
        "profit_factor": round(profit_factor, 2),
        "max_loss_streak": int(max_loss_streak),
        "sharpe": round(sharpe, 2),
        "avg_hold_days": round(df["hold_days"].mean(), 1),
        "exit_distribution": exit_dist,
        "skip_reasons": skip_stats if skip_stats else {},
    }
    print(f"  trades: {n} | hit: {stats['hit_rate_pct']}% | EV: {expected_value:+.2f}% | win: {avg_win:+.2f}% | loss: {avg_loss:+.2f}% | PF: {profit_factor:.2f}")
    return df, stats


def main():
    parser = argparse.ArgumentParser(description="Phase 2 backtest engine")
    parser.add_argument("--signal", type=str, help="specific scanner; omit for --all")
    parser.add_argument("--all", action="store_true", help="run all 11 scanners")
    parser.add_argument("--start", type=str, default="2024-01-01")
    parser.add_argument("--end", type=str, default="2026-05-19")
    parser.add_argument("--max-hold", type=int, default=60)
    parser.add_argument("--top-n", type=int, default=5, help="每天每 scanner 取 top N ranking (0=不過濾)")
    parser.add_argument("--out", type=Path, default=Path("data/analysis/zhuli/backtest"))
    parser.add_argument(
        "--entry-mode",
        type=str,
        default=None,
        choices=["next_day_open", "close_session_disciplined"],
        help=(
            "Global entry mode override. "
            "'next_day_open' = signal+1 day open (default). "
            "'close_session_disciplined' = D+1 尾盤 13:00-13:25 with 4-filter skip "
            "(gap≥5%% / first-5min surge≥5%% / no-minute-data → skip). "
            "NOTE: requires stock_minute_kbar in ~/.four_seasons/data.sqlite. "
            "G/F scanners (signal_day_close) are NOT overridden."
        ),
    )
    args = parser.parse_args()

    cfg = BacktestConfig(
        start_date=args.start, end_date=args.end,
        max_hold_days=args.max_hold,
        top_n_per_day=args.top_n,
    )
    args.out.mkdir(parents=True, exist_ok=True)

    print("Loading bars + features...")
    feats = load_features_cached(db_path=DEFAULT_DB_PATH).copy()
    feats = add_zhuli_features(feats)
    print(f"  bars: {len(feats):,} rows / {feats['ticker'].nunique():,} tickers")

    # Load minute bars if needed
    minute_bars: Optional[dict] = None
    if args.entry_mode == "close_session_disciplined":
        print("Loading minute bars for close_session_disciplined mode...")
        minute_bars = _load_minute_bars()
        n_tickers_with_min = len(minute_bars)
        if n_tickers_with_min == 0:
            print("  ⚠️  No minute data found — close_session_disciplined will skip ALL signals")
        else:
            dates = set()
            for mdf in minute_bars.values():
                dates.update(mdf["trade_date"].unique())
            print(f"  Minute data: {n_tickers_with_min} tickers, {len(dates)} trading days "
                  f"({min(dates)} ~ {max(dates)})")

    if args.all:
        # 排除出場 scanner + master (master 是 wrapper 的源，已被 entry/exit 拆解)
        scanners = [s for s in ENTRY_REGISTRY.keys()
                    if s not in EXIT_ONLY_SCANNERS and s not in MASTER_SCANNERS]
    else:
        scanners = [args.signal]
    if not scanners[0]:
        print("ERROR: --signal or --all required")
        sys.exit(1)

    all_stats = {}
    for sname in scanners:
        if sname not in ENTRY_REGISTRY:
            print(f"  ⚠️ {sname} not in registry, skip")
            continue
        trades_df, stats = run_backtest_for_scanner(
            sname, feats, feats, cfg, DEFAULT_DB_PATH,
            global_entry_mode_override=args.entry_mode,
            minute_bars=minute_bars,
        )
        all_stats[sname] = stats
        if not trades_df.empty:
            trades_df.to_csv(args.out / f"{sname}_trades.csv", index=False)

    # Summary
    print("\n" + "=" * 80)
    print(f"{'策略':<18} {'Trades':>7} {'Hit%':>6} {'EV%':>7} {'Win%':>6} {'Loss%':>7} {'Worst':>7} {'Best':>7} {'PF':>5} {'Sharpe':>7} {'Hold':>5}")
    print("=" * 100)
    # 依 PF 排序顯示（最強到最弱）
    sorted_items = sorted(
        all_stats.items(),
        key=lambda kv: -kv[1].get("profit_factor", 0) if kv[1].get("trades", 0) > 0 else 0,
    )
    for sname, s in sorted_items:
        display = SCANNER_DISPLAY_NAMES.get(sname, sname)
        if "trades" not in s or s.get("trades", 0) == 0:
            note = s.get('note', s.get('error', ''))
            print(f"{display:<18} {'-':>7} {'-':>6} {'-':>7} {'-':>6} {'-':>7} {'-':>7} {'-':>7} {'-':>5} {'-':>7} {'-':>5}  {note}")
            continue
        print(f"{display:<18} {s['trades']:>7} {s['hit_rate_pct']:>6.1f} {s['expected_value_pct']:>+7.2f} {s['avg_win_pct']:>+6.2f} {s['avg_loss_pct']:>+7.2f} {s['worst_loss_pct']:>7.1f} {s['best_win_pct']:>7.1f} {s['profit_factor']:>5.2f} {s['sharpe']:>7.2f} {s['avg_hold_days']:>5.1f}")
    print("=" * 100)

    # Save summary JSON
    import json
    with open(args.out / "summary.json", "w") as f:
        json.dump(all_stats, f, indent=2, default=str, ensure_ascii=False)
    print(f"\nSummary: {args.out / 'summary.json'}")


if __name__ == "__main__":
    main()
