"""disposal_framework — 老師處置股 A/B/C 框架分型邏輯（課程明說）.

來源：2026-04 處置策略大解密（Opus xhigh 解讀）
文件：docs/主力大課程/全方位培訓筆記/2026-04_處置策略大解密_解讀.md

3 種型態（老師推導）:
  A 主升續攻: 處置期間沒過處置前高 + T-1 在所有均線之上 + 第 1/2 次進處置 + 期間守均線
  B 反彈段:   回落 25-30% + 快出關前漲兩根；達標 15% 閃
  C 出貨倒貨: 處置期間已過處置前高 OR 均線往下排 OR 第 3 次以上

使用方式:
    from zhuli.disposal_framework import classify_disposal
    result = classify_disposal("3189", "2026-06-01", db_path)
    # => {'type': 'C', 'reason': '...', 'pre_high': 764.0, ...}
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# ─── 常數（依老師原話） ────────────────────────────────────────────────────────

# 回落達這個比例以上 → 型態 B 候選
_PULLBACK_B_MIN_PCT = 20.0   # line 2206: 超過 20% 進入反彈段觀察
_PULLBACK_B_MAX_PCT = 32.0   # 超過 30-32% 視為過深（老師 "25% 30%"）

# 第幾次進處置仍可做 A 型態
_MAX_TIMES_FOR_A = 2          # line 2052-2065: 第 1 次最香、第 2 次次之

# 型態 A 第 4-5 天切入（從處置生效日起算）
_ENTRY_DAY_MIN = 4
_ENTRY_DAY_MAX = 5

# 出關前 N 天可切入
_PRE_RELEASE_ENTRY_DAYS = 2


def _db_uri(path: Path) -> str:
    return f"file:{path}?mode=ro"


def _trading_days_since(start_date: str, target_date: str, db_path: Path) -> int:
    """計算 start_date 到 target_date（含）之間有幾個交易日.

    用 standard_daily_bar 中的 trade_date 計算，精準反映實際有開盤的天數。
    """
    con = sqlite3.connect(_db_uri(db_path), uri=True, timeout=5)
    row = con.execute(
        """SELECT COUNT(DISTINCT trade_date)
           FROM standard_daily_bar
           WHERE trade_date >= ? AND trade_date <= ?""",
        (start_date, target_date),
    ).fetchone()
    con.close()
    return row[0] if row else 0


def _trading_days_to_end(target_date: str, end_date: str, db_path: Path) -> int:
    """target_date 到 end_date（含 end_date）之間還剩幾個交易日（不含 target）."""
    con = sqlite3.connect(_db_uri(db_path), uri=True, timeout=5)
    row = con.execute(
        """SELECT COUNT(DISTINCT trade_date)
           FROM standard_daily_bar
           WHERE trade_date > ? AND trade_date <= ?""",
        (target_date, end_date),
    ).fetchone()
    con.close()
    return row[0] if row else 0


def _get_price_data(
    ticker: str,
    t_minus_1: str,
    target_date: str,
    db_path: Path,
) -> Optional[dict]:
    """取得分型所需的 OHLCV + 均線資料.

    Returns None 若資料不足。
    回傳:
        pre_high:      T-1 的 high（處置前最高點）
        pre_close:     T-1 的 close
        t1_mas:        T-1 均線 dict {ma5, ma10, ma20, ma60}
        disposal_highs: 處置期間（T 到 target_date）所有 high
        disposal_lows:  處置期間所有 low
        disposal_closes: 處置期間所有 close
        latest_mas:    target_date 均線 dict
    """
    con = sqlite3.connect(_db_uri(db_path), uri=True, timeout=5)

    # T-1 資料
    t1_row = con.execute(
        """SELECT high, close, ma5, ma10, ma20, ma60
           FROM standard_daily_bar
           WHERE ticker=? AND trade_date=?""",
        (ticker, t_minus_1),
    ).fetchone()

    # 處置期間資料（從 T = t_minus_1 後第一個交易日到 target_date）
    period_rows = con.execute(
        """SELECT trade_date, high, low, close, ma5, ma10, ma20, ma60
           FROM standard_daily_bar
           WHERE ticker=? AND trade_date > ? AND trade_date <= ?
           ORDER BY trade_date""",
        (ticker, t_minus_1, target_date),
    ).fetchall()

    con.close()

    if not t1_row or not period_rows:
        return None

    pre_high, pre_close, t1_ma5, t1_ma10, t1_ma20, t1_ma60 = t1_row

    # 均線為 None 表示資料不足
    t1_mas = {
        "ma5":  t1_ma5,
        "ma10": t1_ma10,
        "ma20": t1_ma20,
        "ma60": t1_ma60,
    }

    disposal_highs  = [r[1] for r in period_rows if r[1] is not None]
    disposal_lows   = [r[2] for r in period_rows if r[2] is not None]
    disposal_closes = [r[3] for r in period_rows if r[3] is not None]

    # target_date 均線
    last_row = period_rows[-1]
    latest_mas = {
        "ma5":  last_row[4],
        "ma10": last_row[5],
        "ma20": last_row[6],
        "ma60": last_row[7],
    }

    return {
        "pre_high":        float(pre_high) if pre_high is not None else None,
        "pre_close":       float(pre_close) if pre_close is not None else None,
        "t1_mas":          {k: float(v) for k, v in t1_mas.items() if v is not None},
        "disposal_highs":  [float(x) for x in disposal_highs],
        "disposal_lows":   [float(x) for x in disposal_lows],
        "disposal_closes": [float(x) for x in disposal_closes],
        "latest_mas":      {k: float(v) for k, v in latest_mas.items() if v is not None},
    }


def _t1_above_all_mas(t1_mas: dict, pre_close: float) -> bool:
    """T-1 收盤是否在所有可用均線之上（老師條件：貴買在所有均線之上）."""
    if not t1_mas:
        return False
    return all(pre_close > v for v in t1_mas.values())


def _disposal_holding_ma(latest_mas: dict, disposal_closes: list[float]) -> bool:
    """處置期間最後收盤是否守住均線（MA20 優先，其次 MA10）."""
    if not disposal_closes or not latest_mas:
        return True  # 資料不足時預設為守
    last_close = disposal_closes[-1]
    # 老師主要看月線 (MA20) 和 5/10 日線 (MA5/MA10)
    # 只要收盤在 MA20 之上即視為守
    ma20 = latest_mas.get("ma20")
    if ma20:
        return last_close >= ma20 * 0.97  # 給 3% 容差
    ma10 = latest_mas.get("ma10")
    if ma10:
        return last_close >= ma10 * 0.97
    return True


def _mas_downtrend(t1_mas: dict, latest_mas: dict) -> bool:
    """均線是否呈現往下排（MA5 < MA10 < MA20 or MA20 下斜）.

    用 target_date 的均線判定，輔助 C 型態判定。
    老師原話：「均線在儲置期間它是往下排，這種就不要」
    """
    if not latest_mas:
        return False
    ma5  = latest_mas.get("ma5")
    ma10 = latest_mas.get("ma10")
    ma20 = latest_mas.get("ma20")

    if ma5 and ma10 and ma20:
        # 空頭排列
        return ma5 < ma10 < ma20
    return False


def classify_disposal(
    ticker: str,
    target_date: str,
    db_path: Path,
    disposal_info: Optional[dict] = None,
) -> dict:
    """依老師框架對單一處置股分型.

    Args:
        ticker:        股票代號
        target_date:   今日（盤後）'YYYY-MM-DD'
        db_path:       SQLite DB 路徑
        disposal_info: fetch_disposal_list() 回傳的單檔 info dict，
                       None 時回傳 {type: None}

    Returns:
        {
            'type':         'A' | 'B' | 'C' | None,
            'label':        '🔒A 主升續攻' | '🔒B 反彈段' | '🔒C 出貨倒貨' | '🔒? 需人工判定',
            'reason':       str,          # 判定依據
            'pre_high':     float,        # 處置前最高點
            'disposal_max': float,        # 處置期間最高
            'pullback_pct': float,        # 回落 %（從 T-1 close）
            'times':        int,          # 第幾次進處置
            'disposal_day': int,          # 今天是處置第幾天
            'days_to_end':  int,          # 距出關還有幾天
            'entry_hint':   str,          # 進場時機建議
            'start_date':   str,
            'end_date':     str,
            'name':         str,
        }
    """
    if disposal_info is None:
        return {"type": None, "label": None, "reason": "非處置中"}

    t_minus_1  = disposal_info.get("t_minus_1", "")
    start_date = disposal_info.get("start_date", "")
    end_date   = disposal_info.get("end_date", "")
    times      = disposal_info.get("times", 1)
    name       = disposal_info.get("name", "")

    # 取價格資料
    price = _get_price_data(ticker, t_minus_1, target_date, db_path)
    if price is None or price["pre_high"] is None:
        return {
            "type":         None,
            "label":        "🔒? 需人工判定",
            "reason":       "價格資料不足（T-1 無 K 線）",
            "pre_high":     None,
            "disposal_max": None,
            "pullback_pct": None,
            "times":        times,
            "disposal_day": 0,
            "days_to_end":  0,
            "entry_hint":   "—",
            "start_date":   start_date,
            "end_date":     end_date,
            "name":         name,
        }

    pre_high       = price["pre_high"]
    pre_close      = price["pre_close"] or pre_high
    disposal_highs = price["disposal_highs"]
    disposal_lows  = price["disposal_lows"]
    t1_mas         = price["t1_mas"]
    latest_mas     = price["latest_mas"]

    disposal_max = max(disposal_highs) if disposal_highs else 0.0
    disposal_min = min(disposal_lows)  if disposal_lows  else pre_close

    # 處置天數計算
    disposal_day = _trading_days_since(start_date, target_date, db_path)
    days_to_end  = _trading_days_to_end(target_date, end_date, db_path)

    # 回落 %（從 T-1 close）
    pullback_pct = (pre_close - disposal_min) / pre_close * 100 if pre_close > 0 else 0.0

    # ─── 型態 C 判定 ──────────────────────────────────────────────────────────
    # 優先：處置期間過了處置前高 → 一定是 C
    if disposal_max > pre_high:
        reasons_c = [f"處置期間最高 {disposal_max:.1f} > 處置前高 {pre_high:.1f}"]
        if times > _MAX_TIMES_FOR_A:
            reasons_c.append(f"第 {times} 次進處置（> {_MAX_TIMES_FOR_A} 次）")
        entry_hint_c = "不進場；持有者出關前一天賣一半 → 出關當天開低全出"
        return {
            "type":         "C",
            "label":        "🔒C ❌ 不可進（出貨倒貨）",
            "reason":       "；".join(reasons_c),
            "pre_high":     pre_high,
            "disposal_max": disposal_max,
            "pullback_pct": pullback_pct,
            "times":        times,
            "disposal_day": disposal_day,
            "days_to_end":  days_to_end,
            "entry_hint":   entry_hint_c,
            "start_date":   start_date,
            "end_date":     end_date,
            "name":         name,
        }

    # 均線往下排 → C
    if _mas_downtrend(t1_mas, latest_mas):
        return {
            "type":         "C",
            "label":        "🔒C ❌ 不可進（均線下排）",
            "reason":       "均線空頭排列（MA5 < MA10 < MA20）",
            "pre_high":     pre_high,
            "disposal_max": disposal_max,
            "pullback_pct": pullback_pct,
            "times":        times,
            "disposal_day": disposal_day,
            "days_to_end":  days_to_end,
            "entry_hint":   "不進場",
            "start_date":   start_date,
            "end_date":     end_date,
            "name":         name,
        }

    # ─── 型態 A 判定 ──────────────────────────────────────────────────────────
    is_a = (
        times <= _MAX_TIMES_FOR_A
        and _t1_above_all_mas(t1_mas, pre_close)
        and _disposal_holding_ma(latest_mas, price["disposal_closes"])
        and pullback_pct < _PULLBACK_B_MIN_PCT  # 沒有大幅回落
    )
    if is_a:
        # 進場時機
        if _ENTRY_DAY_MIN <= disposal_day <= _ENTRY_DAY_MAX:
            entry_hint = f"✅ 今天是第 {disposal_day} 天 — 老師第 4-5 天切入時機"
        elif days_to_end <= _PRE_RELEASE_ENTRY_DAYS:
            entry_hint = f"✅ 出關前 {days_to_end} 天 — 出關前 2 天切入時機"
        elif days_to_end == 0:
            entry_hint = "✅ 出關日 — 開盤在均線上直接切入"
        else:
            entry_hint = f"觀察中（第 {disposal_day} 天，出關前 {days_to_end} 天）"

        return {
            "type":         "A",
            "label":        "🔒A 主升續攻",
            "reason":       (
                f"T-1 在均線上 + 第 {times} 次進處置 + 處置期間沒過高 "
                f"({disposal_max:.1f} < {pre_high:.1f}) + 守均線"
            ),
            "pre_high":     pre_high,
            "disposal_max": disposal_max,
            "pullback_pct": pullback_pct,
            "times":        times,
            "disposal_day": disposal_day,
            "days_to_end":  days_to_end,
            "entry_hint":   entry_hint,
            "start_date":   start_date,
            "end_date":     end_date,
            "name":         name,
        }

    # ─── 型態 B 判定 ──────────────────────────────────────────────────────────
    is_b = _PULLBACK_B_MIN_PCT <= pullback_pct <= _PULLBACK_B_MAX_PCT

    if is_b or (pullback_pct >= _PULLBACK_B_MIN_PCT):
        # 型態 B 進場：處置最後一天尾盤 OR 打底在低點 25% 附近
        if days_to_end <= 1:
            entry_hint = "✅ 出關最後一天 — 尾盤觀察進貨訊號；目標 +15% 閃"
        elif pullback_pct >= _PULLBACK_B_MIN_PCT:
            entry_hint = f"觀察低點 {disposal_min:.1f} 附近接（回落 {pullback_pct:.1f}%）；目標 +15%"
        else:
            entry_hint = "等出關前一天尾盤再評估"

        return {
            "type":         "B",
            "label":        "🔒B 反彈段（賺 10-20% 就閃）",
            "reason":       (
                f"回落 {pullback_pct:.1f}%（≥ {_PULLBACK_B_MIN_PCT}%）"
                + (f"；第 {times} 次但回落深" if times > _MAX_TIMES_FOR_A else "")
            ),
            "pre_high":     pre_high,
            "disposal_max": disposal_max,
            "pullback_pct": pullback_pct,
            "times":        times,
            "disposal_day": disposal_day,
            "days_to_end":  days_to_end,
            "entry_hint":   entry_hint,
            "start_date":   start_date,
            "end_date":     end_date,
            "name":         name,
        }

    # ─── 無法分型 ─────────────────────────────────────────────────────────────
    return {
        "type":         None,
        "label":        "🔒? 需人工判定",
        "reason":       (
            f"條件不明確：pullback={pullback_pct:.1f}% < {_PULLBACK_B_MIN_PCT}% "
            f"但 T-1 未在所有均線上或均線異常"
        ),
        "pre_high":     pre_high,
        "disposal_max": disposal_max,
        "pullback_pct": pullback_pct,
        "times":        times,
        "disposal_day": disposal_day,
        "days_to_end":  days_to_end,
        "entry_hint":   "需人工確認均線位置 + 第幾次進處置",
        "start_date":   start_date,
        "end_date":     end_date,
        "name":         name,
    }
