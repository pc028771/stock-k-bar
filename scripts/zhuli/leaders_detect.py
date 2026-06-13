"""Leaders 強勢股 detector + MACD diff 方向性 metrics.

Leaders 判定（純結構 + 籌碼軸、主力大課程框架）:
  - 收 > MA5 + 收 > MA10 + 收 > MA20  → 三軸全綠（均線多頭排列）
  - 外資 5 日淨買 > 0                 → 籌碼軸
  排除（laggards）:
  - 三軸全紅（收 < MA5/MA10/MA20）
  - 或 收 < MA20 × 0.97（明顯跌破 MA20）

MACD diff 方向性（黃大方法、課程外、enrichment-only）:
  - 日 DIF(12,26,9) 數值 / 1 日變化 / 5 日 slope / 連續上行天數 / trend
  - 60m DIF EOD 數值 / 1 日變化 / trend
  ⚠️ 不參與 leaders 篩、只作為 leader 物件的 metadata、給盤中接刀燈號用。
"""
from __future__ import annotations

import pandas as pd

FAST, SLOW, SIG = 12, 26, 9


def _macd_dif(close: pd.Series) -> pd.Series:
    """MACD DIF = EMA(FAST) - EMA(SLOW)、不含訊號線。"""
    return close.ewm(span=FAST, adjust=False).mean() - close.ewm(span=SLOW, adjust=False).mean()


def _trend_label(slope: float | None) -> str:
    """5 日 slope 符號判定。|slope| < 0.05 視為 flat、避免逐根抖動。"""
    if slope is None:
        return "flat"
    if slope > 0.05:
        return "up"
    if slope < -0.05:
        return "down"
    return "flat"


def compute_dif_metrics(close: pd.Series) -> dict:
    """日級 MACD DIF + 方向性。close 至少 30 根。"""
    if len(close) < 30:
        return {}
    dif = _macd_dif(close)
    chg = dif.diff()
    cur = float(dif.iloc[-1])
    chg_1d = float(chg.iloc[-1]) if pd.notna(chg.iloc[-1]) else None
    slope_5d = float(dif.iloc[-1] - dif.iloc[-6]) if len(dif) > 6 else None
    streak = 0
    for v in reversed([x for x in chg.tolist() if pd.notna(x)]):
        if v > 0:
            streak += 1
        else:
            break
    return {
        "dif_d": round(cur, 3),
        "dif_d_chg_1d": round(chg_1d, 3) if chg_1d is not None else None,
        "dif_d_slope_5d": round(slope_5d, 3) if slope_5d is not None else None,
        "dif_d_up_streak": streak,
        "dif_d_trend": _trend_label(slope_5d),
    }


def compute_dif_metrics_60m(b60_close: pd.Series) -> dict:
    """60 分 K MACD DIF EOD + 方向性。

    b60_close: 60 分 K 收盤序列、index 為 datetime；
    每日最後一根代表 EOD。需 ≥30 根、跨 ≥2 個交易日。
    """
    if len(b60_close) < 30:
        return {}
    dif = _macd_dif(b60_close)
    df = pd.DataFrame({"dif": dif})
    df["date"] = df.index.strftime("%Y-%m-%d")
    eod = df.groupby("date")["dif"].last()
    if len(eod) < 2:
        return {}
    cur = float(eod.iloc[-1])
    chg_1d = float(eod.iloc[-1] - eod.iloc[-2])
    return {
        "dif_60m": round(cur, 3),
        "dif_60m_chg_1d": round(chg_1d, 3),
        "dif_60m_trend": "up" if chg_1d > 0 else ("down" if chg_1d < 0 else "flat"),
    }


def detect_leader(df: pd.DataFrame, foreign_5d: float | None) -> bool:
    """Leaders 判定。df 最後一根 = 目標日。"""
    last = df.iloc[-1]
    c, ma5, ma10, ma20 = last.get("close"), last.get("ma5"), last.get("ma10"), last.get("ma20")
    if any(pd.isna(x) or x is None for x in (c, ma5, ma10, ma20)):
        return False
    if not (c > ma5 and c > ma10 and c > ma20):
        return False
    if foreign_5d is None or foreign_5d <= 0:
        return False
    return True


def detect_laggard(df: pd.DataFrame) -> bool:
    """Laggards 判定。df 最後一根 = 目標日。"""
    last = df.iloc[-1]
    c, ma5, ma10, ma20 = last.get("close"), last.get("ma5"), last.get("ma10"), last.get("ma20")
    if any(pd.isna(x) or x is None for x in (c, ma5, ma10, ma20)):
        return False
    if c < ma5 and c < ma10 and c < ma20:
        return True
    if c < ma20 * 0.97:
        return True
    return False


def build_leader_info(
    ticker: str,
    df: pd.DataFrame,
    foreign_5d: float | None,
    b60_close: pd.Series | None = None,
    name: str = "",
) -> dict | None:
    """整合 detect + diff metrics。

    Returns:
        dict 包含 ticker + is_leader/is_laggard 旗標 + 結構/籌碼/diff 欄位；
        ticker 無 MA 資料時回 None。
    """
    last = df.iloc[-1]
    if pd.isna(last.get("close")):
        return None

    is_lead = detect_leader(df, foreign_5d)
    is_lag = detect_laggard(df)

    ret20 = None
    if len(df) >= 21:
        c0 = df["close"].iloc[-21]
        if pd.notna(c0) and c0 > 0:
            ret20 = round((last["close"] / c0 - 1) * 100, 2)

    dist10 = None
    if pd.notna(last.get("ma10")) and last["ma10"]:
        dist10 = round((last["close"] / last["ma10"] - 1) * 100, 2)

    dm = compute_dif_metrics(df["close"])
    dm60 = compute_dif_metrics_60m(b60_close) if b60_close is not None and len(b60_close) >= 30 else {}

    return {
        "ticker": ticker,
        "name": name,
        "is_leader": bool(is_lead),
        "is_laggard": bool(is_lag),
        "close": round(float(last["close"]), 2),
        "ma5": round(float(last["ma5"]), 2) if pd.notna(last.get("ma5")) else None,
        "ma10": round(float(last["ma10"]), 2) if pd.notna(last.get("ma10")) else None,
        "ma20": round(float(last["ma20"]), 2) if pd.notna(last.get("ma20")) else None,
        "ret20": ret20,
        "dist_ma10_pct": dist10,
        "foreign_5d": round(float(foreign_5d), 1) if foreign_5d is not None else None,
        **dm,
        **dm60,
    }
