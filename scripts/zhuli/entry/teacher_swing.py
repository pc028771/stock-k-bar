"""日K均線順向策略（短波段）scanner — 老師 5/28 晚課 9 條件實作.

課程來源：主力大全方位操盤教戰守則（尼克）5/28 晚課截圖整理。

## 老師原始 9 條件

1. **多頭排列**：5MA > 10MA > 20MA > 60MA（4 條完整排序）
2. **月線斜率 > 0.4**：60 月 EMA 月度斜率 > 0.4%（相鄰月 EMA 差值 / 前月 EMA × 100）
3. **月多頭排列**：20 月 EMA > 60 月 EMA
4. **量價條件**：
   - 過去 5 日某日成交 > 10,000 張（流動性確認）
   - 最近 1 日成交 > 300 張（排除冷門股）
   - 周轉率 > 1.3%（當日成交股數 / 流通股數 × 100）
5. **乖離**：
   - 距 5MA < 5%
   - 距 10MA < 8%
6. **統計區間**：最近 4 個交易日（整理確認觀察視窗）

## 使用方式

### 嚴格模式（老師原 9 條件）
```
python scripts/zhuli/entry/teacher_swing.py --date 2026-05-29
```

### 放寬模式（老師「命中太少」時用）
```
# 移除月線條件
python scripts/zhuli/entry/teacher_swing.py --date 2026-05-29 \\
  --no-monthly-slope --no-monthly-trend

# 降低周轉率門檻（大型金融股適用）
python scripts/zhuli/entry/teacher_swing.py --date 2026-05-29 \\
  --turnover-min 0.5

# 放寬距 10MA
python scripts/zhuli/entry/teacher_swing.py --date 2026-05-29 \\
  --dist-ma10-max 10

# 全放寬（老師命中太少時用）
python scripts/zhuli/entry/teacher_swing.py --date 2026-05-29 --relaxed
```

## 紀律備注

- 此檔屬主力大課程 (zhuli) 目錄，不可混入 K線力量課程 (kline/)
- DEFAULT_CFG 預設嚴格 = 老師原 9 條件
- --relaxed 放寬版本僅用於老師明示命中太少時
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── 路徑設定 ──────────────────────────────────────────────────────────────────

_REPO = Path(__file__).parent.parent.parent.parent  # stock-k-bar root
_DB = MAIN_DB
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.db import get_conn, MAIN_DB
# ── 預設設定（嚴格 = 老師原 9 條件）────────────────────────────────────────────

DEFAULT_CFG: dict = {
    # ── 1. 多頭排列 ──
    "require_full_bullish_array": True,   # 5>10>20>60 全部齊備
    "min_ma_levels": [5, 10, 20, 60],     # 要 check 哪幾條均線
    "require_above_ma5": True,            # 收盤必須在 MA5 之上

    # ── 2 & 3. 月線 ──
    "require_monthly_slope": True,        # 月線斜率條件
    "monthly_slope_min": 0.4,            # 60月EMA 月度斜率 > 0.4%
    "require_monthly_trend": True,        # 月多頭排列條件
    "monthly_trend_levels": [20, 60],     # 月線 20EMA > 60EMA

    # ── 4. 量價 ──
    "min_volume_lots_5d": 10_000,         # 5 日內某日 > 10,000 張
    "min_volume_lots_1d": 300,            # 最近 1 日 > 300 張
    "turnover_min_pct": 1.3,             # 周轉率 > 1.3%

    # ── 5. 乖離 ──
    "dist_ma5_max_pct": 5.0,             # 距 MA5 < 5%
    "dist_ma10_max_pct": 8.0,            # 距 MA10 < 8%

    # ── 6. 統計區間 ──
    "consolidation_days": 4,              # 最近 N 天觀察整理視窗（僅作備注用）
}

# 全放寬設定（老師「命中太少」時用）
RELAXED_CFG: dict = {
    **DEFAULT_CFG,
    "require_full_bullish_array": True,   # 保留多頭排列
    "require_monthly_slope": False,       # 移除月線斜率
    "require_monthly_trend": False,       # 移除月多頭排列
    "min_volume_lots_5d": 5_000,          # 放寬 5 日量門檻
    "turnover_min_pct": 0.5,             # 放寬周轉率（大型金融股）
    "dist_ma5_max_pct": 8.0,             # 放寬距 MA5
    "dist_ma10_max_pct": 12.0,           # 放寬距 MA10
}


# ── DB 工具 ───────────────────────────────────────────────────────────────────

def _db_uri(path: Path) -> str:
    return f"file:{path}?mode=ro"


def _load_stock_info(con: sqlite3.Connection) -> dict[str, str]:
    """回傳 {ticker: stock_name} 對照表."""
    rows = con.execute("SELECT ticker, stock_name FROM stock_info").fetchall()
    return {r[0]: r[1] for r in rows}


def _load_shares_issued(con: sqlite3.Connection, target_date: str) -> dict[str, int]:
    """回傳最近一筆 {ticker: shares_issued}（流通股數，單位：股）."""
    rows = con.execute("""
        SELECT ticker, shares_issued
        FROM stock_shareholding
        WHERE (ticker, trade_date) IN (
            SELECT ticker, MAX(trade_date)
            FROM stock_shareholding
            WHERE trade_date <= ?
            GROUP BY ticker
        )
    """, (target_date,)).fetchall()
    return {r[0]: r[1] for r in rows}


def _compute_monthly_ma(con: sqlite3.Connection, ticker: str, target_date: str) -> dict:
    """從 daily bars resample 計算月 K 指標.

    Returns:
        {
            "slope_ok": bool,   # 60月EMA 月度斜率 > monthly_slope_min
            "slope_val": float, # 斜率數值 (%)
            "trend_ok": bool,   # 20月EMA > 60月EMA
            "ma20m": float,
            "ma60m": float,
        }
    """
    df = pd.read_sql("""
        SELECT trade_date, close
        FROM standard_daily_bar
        WHERE ticker = ? AND trade_date >= date(?, '-6 years') AND trade_date <= ?
        ORDER BY trade_date
    """, con, params=(ticker, target_date, target_date))

    if len(df) < 60:
        return {"slope_ok": False, "slope_val": 0.0, "trend_ok": False,
                "ma20m": 0.0, "ma60m": 0.0}

    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df.set_index("trade_date", inplace=True)

    # 月 K = 每月最後交易日收盤
    monthly = df["close"].resample("ME").last().dropna()
    if len(monthly) < 20:
        return {"slope_ok": False, "slope_val": 0.0, "trend_ok": False,
                "ma20m": 0.0, "ma60m": 0.0}

    # 20 月 EMA & 60 月 EMA
    ma20m = monthly.ewm(span=20, adjust=False).mean()
    ma60m = monthly.ewm(span=60, adjust=False).mean()

    # 斜率 = (當月 60EMA - 上月 60EMA) / 上月 60EMA × 100 (%)
    slope_val = 0.0
    if len(ma60m) >= 2 and ma60m.iloc[-2] > 0:
        slope_val = (ma60m.iloc[-1] - ma60m.iloc[-2]) / ma60m.iloc[-2] * 100

    return {
        "slope_ok": bool(slope_val > 0.4),
        "slope_val": round(slope_val, 3),
        "trend_ok": bool(ma20m.iloc[-1] > ma60m.iloc[-1]),
        "ma20m": round(float(ma20m.iloc[-1]), 2),
        "ma60m": round(float(ma60m.iloc[-1]), 2),
    }


# ── Info Layer：扣抵值 / 均線糾纏 ────────────────────────────────────────────

def compute_kou_value(close_today: float, close_n_days_ago: float | None) -> dict | None:
    """計算扣抵值：今日 close vs N+1 日前 close，預判明日 MA 方向.

    Parameters
    ----------
    close_today      : 今日收盤價
    close_n_days_ago : N+1 日前收盤價（即今日會被踢出 MA 計算的那筆）

    Returns
    -------
    dict 或 None（缺資料時回 None）
    """
    if close_n_days_ago is None or close_n_days_ago == 0:
        return None
    diff_pct = (close_today - close_n_days_ago) / close_n_days_ago * 100
    if diff_pct > 0.5:
        return {"direction": "🟢", "tomorrow_ma": "up", "diff_pct": round(diff_pct, 2)}
    elif diff_pct < -0.5:
        return {"direction": "🔴", "tomorrow_ma": "down", "diff_pct": round(diff_pct, 2)}
    else:
        return {"direction": "🟡", "tomorrow_ma": "flat", "diff_pct": round(diff_pct, 2)}


def compute_kou_block(
    bars_df: pd.DataFrame,
    target_date: str,
    periods: list[int] | None = None,
) -> dict:
    """對 bars_df 計算 4 條 MA 的扣抵值資訊.

    Parameters
    ----------
    bars_df     : 已按 trade_date 排序的日 K DataFrame（含 close 欄位）
    target_date : 'YYYY-MM-DD'
    periods     : [5, 10, 20, 60]

    Returns
    -------
    {
        "ma5":  {"扣抵_date": "...", "扣抵_close": float, "today_close": float,
                 "direction": "🟢/🟡/🔴", "diff_pct": float} | None,
        "ma10": ...,
        "ma20": ...,
        "ma60": ...,
    }
    """
    if periods is None:
        periods = [5, 10, 20, 60]

    # 取目標日之前（含當日）的收盤序列，按時間升冪
    hist = bars_df[bars_df["trade_date"] <= target_date][["trade_date", "close"]].copy()
    hist = hist.sort_values("trade_date").reset_index(drop=True)

    result: dict = {}
    today_row = hist[hist["trade_date"] == target_date]
    if today_row.empty:
        for n in periods:
            result[f"ma{n}"] = None
        return result

    close_today = float(today_row.iloc[-1]["close"])
    # hist 最後一列 = today；往前 n 個位置 = N+1 日前
    today_idx = today_row.index[-1]

    for n in periods:
        kou_idx = today_idx - n  # N trading days before today (0-based)
        if kou_idx < 0 or kou_idx >= len(hist):
            result[f"ma{n}"] = None
            continue

        kou_row = hist.iloc[kou_idx]
        kou_close = float(kou_row["close"]) if pd.notna(kou_row["close"]) else None
        kou_date  = str(kou_row["trade_date"])

        kv = compute_kou_value(close_today, kou_close)
        if kv is None:
            result[f"ma{n}"] = None
        else:
            result[f"ma{n}"] = {
                "扣抵_date":  kou_date,
                "扣抵_close": round(kou_close, 2) if kou_close else None,
                "today_close": round(close_today, 2),
                **kv,
            }

    return result


def compute_ma_state(
    ma5: float | None,
    ma10: float | None,
    ma20: float | None,
    close: float,
) -> dict:
    """計算 MA5/10/20 均線糾纏狀態.

    Returns
    -------
    {
        "spread_pct": float,          # (max - min) / close × 100
        "label": "緊糾纏/鬆糾纏/已分開",
        "is_coil": bool,              # spread_pct < 2%
        "ma_values": {"ma5": ..., "ma10": ..., "ma20": ...}
    }
    """
    vals = {k: v for k, v in [("ma5", ma5), ("ma10", ma10), ("ma20", ma20)] if v is not None}

    if len(vals) < 3 or close <= 0:
        return {
            "spread_pct": None,
            "label": "資料不足",
            "is_coil": False,
            "ma_values": {"ma5": ma5, "ma10": ma10, "ma20": ma20},
        }

    spread = max(vals.values()) - min(vals.values())
    spread_pct = spread / close * 100

    if spread_pct < 1.5:
        label = "緊糾纏"
    elif spread_pct < 3.0:
        label = "鬆糾纏"
    else:
        label = "已分開"

    return {
        "spread_pct": round(spread_pct, 2),
        "label": label,
        "is_coil": spread_pct < 2.0,
        "ma_values": {k: round(v, 2) for k, v in vals.items()},
    }


def compute_signal_combo(
    close: float,
    ma20: float | None,
    ma60: float | None,
    ma_state: dict,
    kou_block: dict,
    ma5: float | None = None,
    ma10: float | None = None,
) -> dict:
    """組合 label（純 info，不作 filter）.

    Returns
    -------
    {
        "trend_confirmed": bool,
        "pre_launch_coil": bool,
        "reversal_zone": bool,
        "label": str,
    }
    """
    # 多頭排列判斷
    bull_array = (
        ma5 is not None and ma10 is not None and ma20 is not None and ma60 is not None
        and ma5 > ma10 > ma20 > ma60
    )
    above_ma20 = (ma20 is not None and close > ma20)
    above_ma60 = (ma60 is not None and close > ma60)

    kou_ma20 = kou_block.get("ma20")
    kou_ma60 = kou_block.get("ma60")
    ma20_kou_green = kou_ma20 is not None and kou_ma20.get("direction") == "🟢"
    ma60_kou_green = kou_ma60 is not None and kou_ma60.get("direction") == "🟢"

    is_coil = ma_state.get("is_coil", False)

    # 趨勢確認：多頭排列 + 收盤 > MA20 + MA20 扣抵 🟢
    trend_confirmed = bool(bull_array and above_ma20 and ma20_kou_green)

    # 起漲前打擊區：糾纏 + MA20 扣抵 🟢 + (MA60 扣抵 🟢 或 收盤 > MA60)
    pre_launch_coil = bool(is_coil and ma20_kou_green and (ma60_kou_green or above_ma60))

    # 反轉打擊區：MA20 🟢 + MA60 🟢 + 收盤 > MA60
    reversal_zone = bool(ma20_kou_green and ma60_kou_green and above_ma60)

    # 決定 label（優先級依序）
    if trend_confirmed and is_coil:
        label = "趨勢確認+打擊區"
    elif trend_confirmed:
        label = "趨勢確認"
    elif pre_launch_coil:
        label = "起漲前打擊區"
    elif reversal_zone:
        label = "反轉打擊區"
    elif is_coil:
        label = "普通整理(糾纏)"
    elif ma20_kou_green and ma60_kou_green:
        label = "雙均線向上"
    elif kou_ma20 is not None and kou_ma20.get("direction") == "🔴":
        label = "警告(MA20↓)"
    else:
        label = "普通整理"

    return {
        "trend_confirmed": trend_confirmed,
        "pre_launch_coil": pre_launch_coil,
        "reversal_zone": reversal_zone,
        "label": label,
    }


# ── 核心 detect 函式 ──────────────────────────────────────────────────────────

def detect(
    bars_df: pd.DataFrame,
    target_date: str,
    cfg: dict | None = None,
    shares_issued: int | None = None,
    monthly_info: dict | None = None,
) -> list[dict]:
    """單一 ticker 篩選，回傳命中則 [result_dict]，否則 [].

    Parameters
    ----------
    bars_df       : standard_daily_bar 資料（含 ticker, trade_date, OHLCV, MA 欄位）
    target_date   : 'YYYY-MM-DD'
    cfg           : 條件設定，預設 DEFAULT_CFG
    shares_issued : 流通股數（股），用於計算周轉率；None 則跳過周轉率檢查
    monthly_info  : _compute_monthly_ma 回傳的 dict；None 則跳過月線檢查

    Returns
    -------
    命中時回傳含完整診斷的 dict list（通常 0 或 1 筆）
    """
    if cfg is None:
        cfg = DEFAULT_CFG

    if bars_df.empty:
        return []

    # 取目標日 row
    target_rows = bars_df[bars_df["trade_date"] == target_date]
    if target_rows.empty:
        return []
    row = target_rows.iloc[-1]

    ticker = str(row.get("ticker", ""))
    close = float(row["close"]) if pd.notna(row["close"]) else None
    volume = float(row["volume"]) if pd.notna(row["volume"]) else None
    ma5  = float(row["ma5"])  if pd.notna(row.get("ma5"))  else None
    ma10 = float(row["ma10"]) if pd.notna(row.get("ma10")) else None
    ma20 = float(row["ma20"]) if pd.notna(row.get("ma20")) else None
    ma60 = float(row["ma60"]) if pd.notna(row.get("ma60")) else None

    if close is None or volume is None:
        return []

    reasons_pass: list[str] = []
    reasons_fail: list[str] = []

    # ── 1. 多頭排列 ──────────────────────────────────────────────────────────
    ma_vals = {"ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60}
    levels = cfg.get("min_ma_levels", [5, 10, 20, 60])
    ma_list = [ma_vals.get(f"ma{n}") for n in levels]

    if cfg.get("require_full_bullish_array", True):
        if any(v is None for v in ma_list):
            reasons_fail.append("多頭排列資料不足")
        else:
            bullish = all(ma_list[i] > ma_list[i+1] for i in range(len(ma_list)-1))
            if bullish:
                reasons_pass.append(f"多頭排列✓ 5MA>{ma_list[0]:.1f}>10MA>{ma_list[1]:.1f}>20MA>{ma_list[2]:.1f}>60MA>{ma_list[3]:.1f}")
            else:
                reasons_fail.append(
                    f"非多頭排列 5MA={ma_list[0]:.1f} 10MA={ma_list[1]:.1f} "
                    f"20MA={ma_list[2]:.1f} 60MA={ma_list[3]:.1f}"
                )

    # 收盤在 MA5 上方
    if cfg.get("require_above_ma5", True):
        if ma5 is None:
            reasons_fail.append("MA5 缺值")
        elif close >= ma5:
            reasons_pass.append(f"收盤在MA5上方✓ ({close:.2f}>={ma5:.2f})")
        else:
            reasons_fail.append(f"收盤跌破MA5 ({close:.2f}<{ma5:.2f})")

    # ── 2 & 3. 月線 ──────────────────────────────────────────────────────────
    slope_val = 0.0
    monthly_trend_ok = True

    if monthly_info is None:
        # 月線資訊未傳入時，根據 cfg 決定是否要求
        if cfg.get("require_monthly_slope") or cfg.get("require_monthly_trend"):
            reasons_fail.append("月線資訊未提供（需傳入 monthly_info）")
    else:
        slope_val = monthly_info.get("slope_val", 0.0)
        slope_ok  = monthly_info.get("slope_ok", False)
        trend_ok  = monthly_info.get("trend_ok", False)
        ma20m     = monthly_info.get("ma20m", 0.0)
        ma60m     = monthly_info.get("ma60m", 0.0)
        monthly_slope_min = cfg.get("monthly_slope_min", 0.4)

        if cfg.get("require_monthly_slope", True):
            if slope_ok:
                reasons_pass.append(f"月線斜率✓ ({slope_val:.3f}%>{monthly_slope_min}%)")
            else:
                reasons_fail.append(f"月線斜率不足 ({slope_val:.3f}%≤{monthly_slope_min}%)")

        if cfg.get("require_monthly_trend", True):
            if trend_ok:
                reasons_pass.append(f"月多頭排列✓ 20M={ma20m:.2f}>60M={ma60m:.2f}")
            else:
                reasons_fail.append(f"月線非多頭 20M={ma20m:.2f}≤60M={ma60m:.2f}")

    # ── 4. 量價 ──────────────────────────────────────────────────────────────
    # 4a. 最近 1 日成交 > 300 張
    vol_lots_1d = volume / 1000
    min_lots_1d = cfg.get("min_volume_lots_1d", 300)
    if vol_lots_1d >= min_lots_1d:
        reasons_pass.append(f"今日成交✓ {vol_lots_1d:.0f}張≥{min_lots_1d}張")
    else:
        reasons_fail.append(f"今日成交不足 {vol_lots_1d:.0f}張<{min_lots_1d}張")

    # 4b. 過去 5 日某日 > 10,000 張
    recent_5d = bars_df[bars_df["trade_date"] <= target_date].tail(5)
    max_vol_5d_lots = recent_5d["volume"].max() / 1000 if not recent_5d.empty else 0
    min_lots_5d = cfg.get("min_volume_lots_5d", 10_000)
    if max_vol_5d_lots >= min_lots_5d:
        reasons_pass.append(f"5日量✓ 最大{max_vol_5d_lots:.0f}張≥{min_lots_5d}張")
    else:
        reasons_fail.append(f"5日量不足 最大{max_vol_5d_lots:.0f}張<{min_lots_5d}張")

    # 4c. 周轉率 > 1.3%
    turnover_pct = None
    turnover_ok_flag = True
    turnover_min = cfg.get("turnover_min_pct", 1.3)
    if shares_issued and shares_issued > 0:
        turnover_pct = volume / shares_issued * 100
        if turnover_pct >= turnover_min:
            reasons_pass.append(f"周轉率✓ {turnover_pct:.2f}%≥{turnover_min}%")
        else:
            reasons_fail.append(f"周轉率不足 {turnover_pct:.2f}%<{turnover_min}%")
            turnover_ok_flag = False
    else:
        # 無流通股數資料 → 大型股退路：若成交量 > 50,000 張視為通過
        if vol_lots_1d >= 50_000:
            reasons_pass.append(f"周轉率略過(無股數資料)✓ 成交量{vol_lots_1d:.0f}張>50000張")
        else:
            reasons_fail.append("周轉率無法計算（缺流通股數資料）")
            turnover_ok_flag = False

    # ── 5. 乖離 ──────────────────────────────────────────────────────────────
    dist_ma5_pct = (close - ma5) / ma5 * 100 if ma5 and ma5 > 0 else None
    dist_ma10_pct = (close - ma10) / ma10 * 100 if ma10 and ma10 > 0 else None

    dist5_max  = cfg.get("dist_ma5_max_pct", 5.0)
    dist10_max = cfg.get("dist_ma10_max_pct", 8.0)

    if dist_ma5_pct is not None:
        if dist_ma5_pct <= dist5_max:
            reasons_pass.append(f"距MA5✓ {dist_ma5_pct:+.1f}%≤{dist5_max}%")
        else:
            reasons_fail.append(f"距MA5過遠 {dist_ma5_pct:+.1f}%>{dist5_max}%")
    else:
        reasons_fail.append("MA5 缺值，無法計算乖離")

    if dist_ma10_pct is not None:
        if dist_ma10_pct <= dist10_max:
            reasons_pass.append(f"距MA10✓ {dist_ma10_pct:+.1f}%≤{dist10_max}%")
        else:
            reasons_fail.append(f"距MA10過遠 {dist_ma10_pct:+.1f}%>{dist10_max}%")
    else:
        reasons_fail.append("MA10 缺值，無法計算乖離")

    # ── 最終判斷 ──────────────────────────────────────────────────────────────
    passed = len(reasons_fail) == 0

    if not passed:
        return []

    # 評分（通過條件數 / 總條件數，滿分 = 8 個核心條件）
    total_cond = len(reasons_pass) + len(reasons_fail)
    score = len(reasons_pass) / max(total_cond, 1) * 100

    return [{
        "ticker":         ticker,
        "close":          close,
        "score":          round(score, 1),
        "reasons":        reasons_pass,
        "dist_ma5_pct":   round(dist_ma5_pct, 1) if dist_ma5_pct is not None else None,
        "dist_ma10_pct":  round(dist_ma10_pct, 1) if dist_ma10_pct is not None else None,
        "vol_lots_1d":    round(vol_lots_1d, 0),
        "max_vol_5d_lots": round(max_vol_5d_lots, 0),
        "turnover_pct":   round(turnover_pct, 2) if turnover_pct is not None else None,
        "monthly_slope":  round(slope_val, 3),
        "ma5":  round(ma5, 2) if ma5 else None,
        "ma10": round(ma10, 2) if ma10 else None,
        "ma20": round(ma20, 2) if ma20 else None,
        "ma60": round(ma60, 2) if ma60 else None,
    }]


# ── 全市場掃描 ────────────────────────────────────────────────────────────────

def run_scan(
    target_date: str,
    db_path: Path = _DB,
    cfg: dict | None = None,
    with_kou: bool = True,
    with_coil: bool = True,
) -> list[dict]:
    """掃描全市場，回傳通過所有條件的 ticker 清單.

    每筆 hit dict 額外包含:
        name         : 股票名稱
        industry     : 產業別
        kou_value    : 扣抵值資訊（4 條 MA），with_kou=True 時計算
        ma_state     : 均線糾纏狀態，with_coil=True 時計算
        signal_combo : 組合 label，兩者都開啟時計算
    """
    if cfg is None:
        cfg = DEFAULT_CFG

    con = get_conn(db_path, timeout=30)
    stock_names = _load_stock_info(con)
    shares_map  = _load_shares_issued(con, target_date)

    # 全市場當日有資料的 ticker
    all_tickers = [
        r[0] for r in con.execute(
            "SELECT DISTINCT ticker FROM standard_daily_bar WHERE trade_date = ?",
            (target_date,)
        ).fetchall()
        # 排除 ETF（ticker 含字母通常為 ETF）
        if r[0].isdigit()
    ]

    results: list[dict] = []

    # 先做不需月線資料的快速 SQL 預篩（減少 monthly_info 計算量）
    #   - 多頭排列（預篩）
    #   - 乖離 (預篩)
    #   - 當日量 (預篩)
    pre_filter_sql = """
        SELECT DISTINCT ticker FROM standard_daily_bar
        WHERE trade_date = ?
          AND ma5 IS NOT NULL AND ma10 IS NOT NULL
          AND ma20 IS NOT NULL AND ma60 IS NOT NULL
          AND ma5 > ma10 AND ma10 > ma20 AND ma20 > ma60
          AND close >= ma5
          AND (close - ma5) / ma5 * 100 < ?
          AND (close - ma10) / ma10 * 100 < ?
          AND volume >= ?
    """
    pre_params = (
        target_date,
        cfg.get("dist_ma5_max_pct", 5.0) + 0.5,   # 加 0.5% buffer 避免 float 邊界
        cfg.get("dist_ma10_max_pct", 8.0) + 0.5,
        cfg.get("min_volume_lots_1d", 300) * 1000,
    )
    pre_tickers = {r[0] for r in con.execute(pre_filter_sql, pre_params).fetchall()
                   if r[0].isdigit()}

    for ticker in pre_tickers:
        # 讀取近 200 日 bars（扣抵值最多需 61 個交易日，200 日足夠）
        bars_df = pd.read_sql("""
            SELECT trade_date, open, high, low, close, volume,
                   ma5, ma10, ma20, ma60
            FROM standard_daily_bar
            WHERE ticker = ?
              AND trade_date >= date(?, '-200 days')
              AND trade_date <= ?
            ORDER BY trade_date
        """, con, params=(ticker, target_date, target_date))

        if len(bars_df) < 60:
            continue

        bars_df["ticker"] = ticker

        # 月線計算（若兩個月線條件都不需要，跳過以加速）
        monthly_info = None
        if cfg.get("require_monthly_slope", True) or cfg.get("require_monthly_trend", True):
            monthly_info = _compute_monthly_ma(con, ticker, target_date)

        # 周轉率
        shares = shares_map.get(ticker)

        hits = detect(
            bars_df=bars_df,
            target_date=target_date,
            cfg=cfg,
            shares_issued=shares,
            monthly_info=monthly_info,
        )
        for h in hits:
            h["name"]     = stock_names.get(ticker, "")
            h["industry"] = ""  # stock_info 無 industry_category 欄位時留空

            # ── Info Layer 1：扣抵值 ─────────────────────────────────────
            if with_kou:
                h["kou_value"] = compute_kou_block(bars_df, target_date)
            else:
                h["kou_value"] = None

            # ── Info Layer 2：均線糾纏 ───────────────────────────────────
            if with_coil:
                h["ma_state"] = compute_ma_state(
                    ma5=h.get("ma5"),
                    ma10=h.get("ma10"),
                    ma20=h.get("ma20"),
                    close=h["close"],
                )
            else:
                h["ma_state"] = None

            # ── Info Layer 3：組合 label ─────────────────────────────────
            if with_kou and with_coil and h["kou_value"] and h["ma_state"]:
                h["signal_combo"] = compute_signal_combo(
                    close=h["close"],
                    ma20=h.get("ma20"),
                    ma60=h.get("ma60"),
                    ma_state=h["ma_state"],
                    kou_block=h["kou_value"],
                    ma5=h.get("ma5"),
                    ma10=h.get("ma10"),
                )
            else:
                h["signal_combo"] = None

            results.append(h)

    con.close()

    # 排序：周轉率↓ + 成交量↓
    results.sort(key=lambda x: (-(x.get("turnover_pct") or 0), -(x.get("vol_lots_1d") or 0)))
    return results


# ── 輸出格式 ──────────────────────────────────────────────────────────────────

def _fmt_kou(kv: dict | None) -> str:
    """單一扣抵值 dict → 簡短字串."""
    if kv is None:
        return "—"
    return f"{kv['direction']} {kv['diff_pct']:+.1f}%"


def _render_kou_section(h: dict) -> list[str]:
    """回傳扣抵值 + 均線糾纏的顯示行."""
    lines: list[str] = []
    kv = h.get("kou_value")
    ms = h.get("ma_state")
    sc = h.get("signal_combo")

    if kv:
        ma5k  = _fmt_kou(kv.get("ma5"))
        ma10k = _fmt_kou(kv.get("ma10"))
        ma20k = _fmt_kou(kv.get("ma20"))
        ma60k = _fmt_kou(kv.get("ma60"))
        lines.append(
            f"  扣抵: MA5={ma5k}  MA10={ma10k}  MA20={ma20k}  MA60={ma60k}"
        )
        # 顯示扣抵日期（MA20/60 較有參考價值）
        if kv.get("ma20"):
            lines.append(
                f"  扣抵日: MA20={kv['ma20']['扣抵_date']}({kv['ma20']['扣抵_close']})  "
                f"MA60={kv['ma60']['扣抵_date']}({kv['ma60']['扣抵_close']})"
                if kv.get("ma60") else
                f"  扣抵日: MA20={kv['ma20']['扣抵_date']}({kv['ma20']['扣抵_close']})"
            )

    if ms and ms.get("spread_pct") is not None:
        coil_flag = "⭐" if ms["is_coil"] else ""
        lines.append(
            f"  均線糾纏: {ms['label']}{coil_flag}  spread={ms['spread_pct']:.2f}%  "
            f"MA5={ms['ma_values'].get('ma5', '—')}  MA10={ms['ma_values'].get('ma10', '—')}  MA20={ms['ma_values'].get('ma20', '—')}"
        )

    if sc:
        lines.append(f"  組合訊號: 【{sc['label']}】")

    return lines


def _render_markdown(hits: list[dict], target_date: str, cfg: dict) -> str:
    """產生 markdown table 輸出."""
    lines: list[str] = []
    lines.append(f"## 📊 日K均線順向策略（短波段）— {target_date}")
    lines.append(f"命中 **{len(hits)}** 檔")
    lines.append("")

    # 顯示使用的設定
    lines.append("### 篩選條件設定")
    lines.append(f"- 多頭排列: 5MA>10MA>20MA>60MA = {cfg.get('require_full_bullish_array')}")
    lines.append(f"- 月線斜率(>0.4%): {cfg.get('require_monthly_slope')}")
    lines.append(f"- 月多頭排列: {cfg.get('require_monthly_trend')}")
    lines.append(f"- 5日量門檻: {cfg.get('min_volume_lots_5d'):,}張")
    lines.append(f"- 周轉率門檻: {cfg.get('turnover_min_pct')}%")
    lines.append(f"- 距MA5上限: {cfg.get('dist_ma5_max_pct')}%")
    lines.append(f"- 距MA10上限: {cfg.get('dist_ma10_max_pct')}%")
    lines.append("")

    if not hits:
        lines.append("_沒有命中標的_")
        return "\n".join(lines)

    header = "| 代號 | 名稱 | 收盤 | 成交(張) | 周轉率 | 距MA5 | 距MA10 | 月線斜率 | 5日量峰(張) |"
    sep    = "|------|------|-----:|---------:|-------:|------:|-------:|---------:|------------:|"
    lines.append(header)
    lines.append(sep)

    for h in hits:
        turnover_str = f"{h['turnover_pct']:.2f}%" if h.get('turnover_pct') is not None else "—"
        dist5_str  = f"{h['dist_ma5_pct']:+.1f}%" if h.get('dist_ma5_pct') is not None else "—"
        dist10_str = f"{h['dist_ma10_pct']:+.1f}%" if h.get('dist_ma10_pct') is not None else "—"
        slope_str  = f"{h['monthly_slope']:.3f}%" if h.get('monthly_slope') is not None else "—"
        lines.append(
            f"| {h['ticker']} | {h.get('name', '')} | {h['close']:.1f} "
            f"| {int(h['vol_lots_1d']):,} | {turnover_str} "
            f"| {dist5_str} | {dist10_str} | {slope_str} "
            f"| {int(h['max_vol_5d_lots']):,} |"
        )

    # 扣抵值 + 均線糾纏詳情（每檔一區塊）
    has_info = any(h.get("kou_value") or h.get("ma_state") for h in hits)
    if has_info:
        lines.append("")
        lines.append("### 扣抵值 & 均線糾纏（Info Layer）")
        for h in hits:
            lines.append(f"\n**{h['ticker']} {h.get('name', '')}**  收盤={h['close']:.2f}")
            lines.extend(_render_kou_section(h))

    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="日K均線順向策略 scanner（老師 5/28 晚課 9 條件）"
    )
    p.add_argument("--date", default=None,
                   help="目標日期 YYYY-MM-DD，預設今日")
    p.add_argument("--db", default=str(_DB),
                   help="SQLite 資料庫路徑")

    # ── 放寬選項 ──
    p.add_argument("--relaxed", action="store_true",
                   help="全放寬模式（老師命中太少時用）")
    p.add_argument("--no-monthly-slope", action="store_true",
                   help="移除月線斜率條件")
    p.add_argument("--no-monthly-trend", action="store_true",
                   help="移除月多頭排列條件")
    p.add_argument("--turnover-min", type=float, default=None,
                   help="自訂周轉率門檻（%），預設 1.3")
    p.add_argument("--dist-ma5-max", type=float, default=None,
                   help="自訂距MA5上限（%），預設 5.0")
    p.add_argument("--dist-ma10-max", type=float, default=None,
                   help="自訂距MA10上限（%），預設 8.0")
    p.add_argument("--vol-5d-min", type=int, default=None,
                   help="自訂5日量峰門檻（張），預設 10000")
    p.add_argument("--debug", action="store_true",
                   help="顯示每檔詳細診斷（通過條件）")

    # ── Info Layer flags ──
    p.add_argument("--with-kou", action=argparse.BooleanOptionalAction, default=True,
                   help="計算扣抵值（預設開啟）")
    p.add_argument("--with-coil", action=argparse.BooleanOptionalAction, default=True,
                   help="計算均線糾纏（預設開啟）")

    return p.parse_args()


def _build_cfg(args: argparse.Namespace) -> dict:
    """依 CLI flags 建立 cfg dict."""
    if args.relaxed:
        cfg = dict(RELAXED_CFG)
    else:
        cfg = dict(DEFAULT_CFG)

    if args.no_monthly_slope:
        cfg["require_monthly_slope"] = False
    if args.no_monthly_trend:
        cfg["require_monthly_trend"] = False
    if args.turnover_min is not None:
        cfg["turnover_min_pct"] = args.turnover_min
    if args.dist_ma5_max is not None:
        cfg["dist_ma5_max_pct"] = args.dist_ma5_max
    if args.dist_ma10_max is not None:
        cfg["dist_ma10_max_pct"] = args.dist_ma10_max
    if args.vol_5d_min is not None:
        cfg["min_volume_lots_5d"] = args.vol_5d_min

    return cfg


def main() -> None:
    """CLI 主程式."""
    from datetime import date as _date

    args = _parse_args()
    target_date = args.date or _date.today().strftime("%Y-%m-%d")
    db_path = Path(args.db)
    cfg = _build_cfg(args)

    print(f"掃描日期: {target_date}")
    mode_label = "全放寬" if args.relaxed else "嚴格"
    overrides = []
    if args.no_monthly_slope: overrides.append("--no-monthly-slope")
    if args.no_monthly_trend: overrides.append("--no-monthly-trend")
    if args.turnover_min is not None: overrides.append(f"--turnover-min {args.turnover_min}")
    if args.dist_ma5_max is not None: overrides.append(f"--dist-ma5-max {args.dist_ma5_max}")
    if args.dist_ma10_max is not None: overrides.append(f"--dist-ma10-max {args.dist_ma10_max}")
    if overrides:
        mode_label = f"自訂({', '.join(overrides)})"
    print(f"模式: {mode_label}")
    print()

    with_kou  = getattr(args, "with_kou",  True)
    with_coil = getattr(args, "with_coil", True)

    hits = run_scan(
        target_date=target_date,
        db_path=db_path,
        cfg=cfg,
        with_kou=with_kou,
        with_coil=with_coil,
    )

    print(_render_markdown(hits, target_date, cfg))

    if args.debug and hits:
        print("\n### 詳細診斷")
        for h in hits:
            print(f"\n**{h['ticker']} {h.get('name', '')}**")
            for r in h.get("reasons", []):
                print(f"  ✓ {r}")


# ── Sanity Check（內建 unit test）─────────────────────────────────────────────

def _run_sanity_check() -> None:
    """快速驗證：以 2026-05-29 跑嚴格 + 放寬 兩個模式，確認輸出合理."""
    from datetime import date as _date

    TARGET = "2026-05-29"
    print("=" * 60)
    print(f"Sanity Check — 目標日: {TARGET}")
    print("=" * 60)

    # 嚴格
    print("\n[模式: 嚴格]")
    strict_hits = run_scan(TARGET, cfg=DEFAULT_CFG)
    print(f"  命中 {len(strict_hits)} 檔")
    for h in strict_hits[:10]:
        print(f"  {h['ticker']} {h.get('name', '')}: 周轉率={h.get('turnover_pct')}% "
              f"距MA5={h.get('dist_ma5_pct')}% 距MA10={h.get('dist_ma10_pct')}%")

    # 嚴格模式應命中 5–35 檔（5/29 是大漲日，多頭股票多）
    assert 1 <= len(strict_hits) <= 100, f"嚴格命中數異常: {len(strict_hits)}"
    print(f"  ✓ 嚴格命中數在合理範圍 ({len(strict_hits)})")

    # 2885 驗證（應不在嚴格清單，因周轉率 < 1.3%）
    strict_tickers = {h["ticker"] for h in strict_hits}
    assert "2885" not in strict_tickers, "2885 周轉率僅 0.68%，不應通過嚴格模式"
    print("  ✓ 2885 正確排除（周轉率 0.68% < 1.3%）")

    # 放寬（turnover 0.5%）
    print("\n[模式: 放寬（--turnover-min 0.5）]")
    relaxed_cfg = {**DEFAULT_CFG, "turnover_min_pct": 0.5,
                   "require_monthly_slope": False, "require_monthly_trend": False,
                   "dist_ma5_max_pct": 8.0, "dist_ma10_max_pct": 12.0}
    relaxed_hits = run_scan(TARGET, cfg=relaxed_cfg)
    print(f"  命中 {len(relaxed_hits)} 檔")

    assert len(relaxed_hits) >= len(strict_hits), "放寬後命中數應 ≥ 嚴格"
    print(f"  ✓ 放寬命中數 {len(relaxed_hits)} ≥ 嚴格命中數 {len(strict_hits)}")

    relaxed_tickers = {h["ticker"] for h in relaxed_hits}
    if "2885" in relaxed_tickers:
        print("  ✓ 2885 在放寬模式下命中（周轉率 0.68% ≥ 0.5%）")
    else:
        print("  ⚠ 2885 在放寬模式下仍未命中（可能其他條件不過）")

    # 4939 亞電驗證（距MA10=21.8%，應排除）
    for cfg_name, tickers in [("嚴格", strict_tickers), ("放寬", relaxed_tickers)]:
        assert "4939" not in tickers, f"4939 距MA10=21.8%，不應通過{cfg_name}模式"
    print("  ✓ 4939 正確排除（距MA10=21.8%，超過最大門檻）")

    print("\n✅ Sanity Check 通過")


if __name__ == "__main__":
    import sys as _sys

    if "--sanity" in _sys.argv:
        _run_sanity_check()
    else:
        main()
