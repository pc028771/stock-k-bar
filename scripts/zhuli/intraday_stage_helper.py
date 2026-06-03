"""盤中即時 Stage Trigger 偵測器 — 主力大操作紀律。

每 N 秒抓 5 分 K，偵測四種 Trigger (cascade 優先順序):
  Ch5-3:     第一根 5K SOP (當沖路徑、6 條件全 pass + 9:10 後過高站穩)
  Trigger 1: 強勢延續 (連 2 紅K + 量增 + 站前波高 + 距開盤 >+1%)
  Trigger 2: 跌深反彈 (從盤中最高跌 ≥ 2.5% + 3 紅K 或 5m diff 由負轉正)
  Trigger C: 結構失敗 (跌破前波低或距 MA10 -3% + 量爆下行)

Cascade 邏輯 (composite_check):
  Ch5-3 pass → 走當沖路徑
  → T1 pass → 強勢延續
  → T2 pass → 跌深反彈
  → TC pass → 結構失敗

Per-category action:
  HELD:         T1 → Stage 2 加碼追高 / T2 → Stage 2 反彈低接加碼 / TC → 出 Stage 1 警示
  WATCH:        Ch5-3/T1/T2 → Stage 1 試水 / TC → 不要進
  PLAN_PRIMARY: Ch5-3/T1/T2 → 進場時機 / TC → skip

紀律守則:
  - 09:00-09:10 不觸發任何 entry Trigger
  - 跳空 ≥ +5% 不觸發
  - 距 MA10 > +10% 不觸發

Usage:
  python scripts/zhuli/intraday_stage_helper.py
  python scripts/zhuli/intraday_stage_helper.py --tickers 1605,6207,4722
  python scripts/zhuli/intraday_stage_helper.py --interval 60 --notify
  python scripts/zhuli/intraday_stage_helper.py --simulate-date 2026-05-29 --simulate-ticker 1605
  python scripts/zhuli/intraday_stage_helper.py --simulate-date 2026-06-01 --simulate-ticker 1605
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

# ── Path setup ────────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent.parent
_SYS  = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_REPO), str(_REPO / "scripts"), str(_SYS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

_DB = Path.home() / ".four_seasons" / "data.sqlite"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── 預設持倉與觀察清單 ─────────────────────────────────────────────────────────
# (ticker, name, entry_price, shares, stop_price, tactic)
HELD: list[tuple[str, str, float, int, float, str]] = [
    ("1605", "華新",  40.1,  8000, 38.75, "核心"),
    ("6285", "啟碁",  315.0, 1000, 301.0, "核心"),
]

# (ticker, name, entry_price, stop_price, tactic)
WATCH: list[tuple[str, str, float, float, str]] = [
    ("6207", "雷科",    127.0, 115.0, "短打"),
    ("8046", "南電",    862.0, 834.0, "短打"),
    ("4722", "國精化",  281.0, 268.0, "短打"),
]

# 戰術 → 適用 trigger
TACTICS_TRIGGERS: dict[str, list[str]] = {
    "核心":  ["Trigger_1", "Trigger_2"],
    "短打":  ["Trigger_1", "Trigger_2"],
    "當沖":  ["Ch5-3_entry"],
    "題材":  ["Trigger_1", "Trigger_2"],
}

# ── Fubon client (lazy init) ──────────────────────────────────────────────────
_fubon_client = None


def _get_fubon():
    global _fubon_client
    if _fubon_client is None:
        from clients.fubon_client import FubonClient
        _fubon_client = FubonClient()
    return _fubon_client


# ── 通知 ──────────────────────────────────────────────────────────────────────

def notify_mac(title: str, msg: str, sound: str = "Glass") -> None:
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{msg}" with title "{title}" sound name "{sound}"'],
            capture_output=True, timeout=10,
        )
    except Exception as e:
        log.warning("macOS 通知失敗: %s", e)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _db_con(db: Path) -> sqlite3.Connection:
    for _ in range(3):
        try:
            return sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=15)
        except sqlite3.OperationalError as e:
            log.warning("DB 連線失敗，1s 後重試: %s", e)
            time.sleep(1)
    raise RuntimeError(f"無法開啟 DB: {db}")


def load_stock_names(db: Path) -> dict[str, str]:
    with _db_con(db) as con:
        rows = con.execute("SELECT ticker, stock_name FROM stock_info").fetchall()
    return {r[0]: r[1] for r in rows}


def _get_ma10(ticker: str, target_date: str, db: Path = _DB) -> Optional[float]:
    """從 standard_daily_bar 取 target_date 前一交易日的 MA10。

    Args:
        ticker:      股票代號
        target_date: 當日日期字串 'YYYY-MM-DD'（取其之前最新一筆）
        db:          SQLite DB 路徑

    Returns:
        MA10 浮點數，查無則回 None。
    """
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as con:
            r = con.execute(
                "SELECT ma10 FROM standard_daily_bar "
                "WHERE ticker=? AND trade_date < ? "
                "ORDER BY trade_date DESC LIMIT 1",
                (ticker, target_date),
            ).fetchone()
        return float(r[0]) if r and r[0] else None
    except Exception as e:
        log.warning("_get_ma10(%s, %s) 失敗: %s", ticker, target_date, e)
        return None


def load_daily_closes(ticker: str, db: Path, n: int = 20) -> pd.Series:
    """取最近 n 日收盤，回傳 Series(index=date str, values=float)."""
    try:
        with _db_con(db) as con:
            rows = con.execute(
                "SELECT trade_date, close FROM standard_daily_bar WHERE ticker=? ORDER BY trade_date DESC LIMIT ?",
                (ticker, n),
            ).fetchall()
        if not rows:
            return pd.Series(dtype=float)
        s = pd.Series({r[0]: float(r[1]) for r in rows})
        return s.sort_index()
    except Exception as e:
        log.warning("load_daily_closes(%s) 失敗: %s", ticker, e)
        return pd.Series(dtype=float)


# ── 5 分 K 抓取 ───────────────────────────────────────────────────────────────

def _build_5min_from_1min(df1m: pd.DataFrame, target_date: date) -> pd.DataFrame:
    df = df1m.copy()
    df["datetime"] = pd.to_datetime(df["datetime"])
    today_mask = df["datetime"].dt.date == target_date
    df = df[today_mask].sort_values("datetime").copy()
    if df.empty:
        return pd.DataFrame()

    df = df.set_index("datetime")
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
    return df5


def fetch_5min_kbar(ticker: str, target_date: date) -> pd.DataFrame:
    """從 Fubon 抓 1 分 K，聚合成 5 分 K，只回傳 target_date 當日資料."""
    try:
        client = _get_fubon()
        df1m = client.load_kbar(ticker, days=2)
        if df1m is None or df1m.empty:
            return pd.DataFrame()
        return _build_5min_from_1min(df1m, target_date)
    except Exception as e:
        log.warning("fetch_5min_kbar(%s) 失敗: %s", ticker, e)
        return pd.DataFrame()


def fetch_snapshot_price(ticker: str) -> Optional[float]:
    try:
        client = _get_fubon()
        snap = client.get_realtime_snapshot(ticker)
        if snap is None:
            return None
        for key in ("close", "last", "price", "lastPrice"):
            v = snap.get(key) if isinstance(snap, dict) else getattr(snap, key, None)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        return None
    except Exception as e:
        log.warning("fetch_snapshot_price(%s) 失敗: %s", ticker, e)
        return None


# ── 模擬資料 (--simulate-date) ────────────────────────────────────────────────

def _build_simulated_5k_1605() -> pd.DataFrame:
    """1605 2026-06-02 模擬 5 分 K（精簡版、覆蓋測試案例）."""
    # open_price = 40.5, prev_close = 39.8 → 跳空 +1.75% < 5%  (不觸紅線 #1)
    # 09:05 探底 38.7 → 紅線 #3 阻擋 (前 10 分鐘)
    # 11:30 二次探底 38.7 → 開始 watch
    # 11:35 反彈紅 K → signal (1 根、未 confirmed)
    # 12:50 量爆突破 40.0 → signal 強化
    # 13:00 第 3 根確認 → confirmed ✅
    sim_rows = [
        # ts, open, high, low, close, volume
        ("2026-06-02 09:00", 40.5, 40.6, 40.3, 40.4, 1200),
        ("2026-06-02 09:05", 40.4, 40.5, 38.7, 39.0, 3500),   # 探底、前 10 分鐘
        ("2026-06-02 09:10", 39.0, 39.5, 38.9, 39.2, 2000),
        ("2026-06-02 09:15", 39.2, 39.6, 39.0, 39.5, 1500),
        ("2026-06-02 09:20", 39.5, 39.8, 39.2, 39.3, 1100),
        ("2026-06-02 09:30", 39.3, 39.5, 39.1, 39.2, 900),
        ("2026-06-02 09:35", 39.2, 39.4, 38.9, 39.0, 950),
        ("2026-06-02 09:40", 39.0, 39.3, 38.8, 39.1, 850),
        ("2026-06-02 10:00", 39.1, 39.3, 38.9, 39.0, 750),
        ("2026-06-02 10:05", 39.0, 39.2, 38.8, 38.9, 700),
        ("2026-06-02 10:30", 38.9, 39.1, 38.7, 38.8, 720),
        ("2026-06-02 11:00", 38.8, 39.0, 38.6, 38.9, 700),
        ("2026-06-02 11:30", 38.9, 39.0, 38.7, 38.75, 680),   # 二次探底接近 38.7
        ("2026-06-02 11:35", 38.75, 39.2, 38.7, 39.1, 1900),  # 反彈紅 K (1 根 signal)
        ("2026-06-02 11:40", 39.1, 39.3, 39.0, 39.2, 1600),   # 第 2 根守住
        ("2026-06-02 12:00", 39.2, 39.5, 39.1, 39.3, 1400),
        ("2026-06-02 12:30", 39.3, 39.6, 39.2, 39.4, 1300),
        ("2026-06-02 12:50", 39.4, 40.1, 39.3, 40.0, 4200),   # 量爆突破 40
        ("2026-06-02 12:55", 40.0, 40.3, 39.9, 40.1, 3100),   # 第 2 根守住
        ("2026-06-02 13:00", 40.1, 40.4, 40.0, 40.2, 2800),   # 第 3 根確認 ✅
        ("2026-06-02 13:05", 40.2, 40.5, 40.1, 40.4, 2200),
        ("2026-06-02 13:15", 40.4, 40.6, 40.2, 40.2, 1800),
    ]
    rows = [{"datetime": pd.Timestamp(r[0]), "open": r[1], "high": r[2],
             "low": r[3], "close": r[4], "volume": r[5]} for r in sim_rows]
    df = pd.DataFrame(rows).set_index("datetime")
    return df


# ── Trigger 判斷邏輯 ──────────────────────────────────────────────────────────

class StageTrigger:

    def check_discipline_filter(
        self,
        ticker: str,
        k5: pd.DataFrame,
        now_time: datetime,
        prev_close: Optional[float],
        disable: bool = False,
    ) -> tuple[bool, str]:
        """紅線 #1/#2/#3 過濾。回傳 (pass, reason)。"""
        if disable:
            return True, "紀律過濾已停用 (--no-discipline)"

        if k5.empty:
            return False, "5K 資料為空"

        open_price = float(k5["open"].iloc[0])

        # 紅線 #3: 09:00-09:10 不觸發 entry
        t = now_time.time()
        if t.hour == 9 and t.minute < 10:
            return False, f"紅線 #3: 前 10 分鐘 ({t.strftime('%H:%M')}) 不觸發"

        # 紅線 #1: 跳空 ≥ +5% 不觸發
        if prev_close and prev_close > 0:
            gap_pct = (open_price / prev_close - 1) * 100
            if gap_pct >= 5.0:
                return False, f"紅線 #1: 跳空 +{gap_pct:.1f}% ≥ 5% 不觸發"

        # 紅線 #2: 距 MA10 > +10%
        closes = k5["close"]
        ma10 = closes.rolling(10, min_periods=1).mean().iloc[-1]
        current = float(closes.iloc[-1])
        if ma10 > 0:
            dist_pct = (current / ma10 - 1) * 100
            if dist_pct > 10.0:
                return False, f"紅線 #2: 距 MA10 +{dist_pct:.1f}% > 10% 不觸發"

        return True, "通過紀律過濾"

    def check_trigger_1(
        self,
        ticker: str,
        k5: pd.DataFrame,
        prev_high: Optional[float],
    ) -> dict:
        """強勢延續訊號 (連 2 紅K + 量增 + 站前波高 + 距開盤 >+1%)."""
        result = {"triggered": False, "level": "watch", "reason": "", "price": 0.0, "suggested_size": 0}

        if len(k5) < 5:
            result["reason"] = "5K 資料不足"
            return result

        open_price = float(k5["open"].iloc[0])
        last2 = k5.tail(2)
        current_close = float(k5["close"].iloc[-1])
        result["price"] = current_close

        # 連 2 根紅 K
        last2_red = all(
            float(last2["close"].iloc[i]) > float(last2["open"].iloc[i])
            for i in range(len(last2))
        )
        if not last2_red:
            result["reason"] = "未達連 2 紅K"
            return result

        # 量增：最後 1 根量 ≥ 5 日平均 × 1.5
        vol_5d_avg = k5["volume"].rolling(min(len(k5), 20), min_periods=1).mean().iloc[-1]
        last_vol = float(k5["volume"].iloc[-1])
        vol_ratio = last_vol / vol_5d_avg if vol_5d_avg > 0 else 0
        if vol_ratio < 1.5:
            result["reason"] = f"量增不足 (×{vol_ratio:.2f} < 1.5)"
            return result

        # 距開盤反彈 > +1%
        rebound_pct = (current_close / open_price - 1) * 100
        if rebound_pct <= 1.0:
            result["reason"] = f"距開盤反彈 {rebound_pct:.1f}% ≤ 1%"
            return result

        # 站穩前波高
        if prev_high is not None and current_close < prev_high:
            result["reason"] = f"未站穩前波高 {prev_high:.2f}"
            return result

        result["triggered"] = True
        result["level"] = "confirmed"
        result["reason"] = (
            f"連 2 紅K + 量×{vol_ratio:.1f} + 反彈+{rebound_pct:.1f}%"
            + (f" + 站前波高 {prev_high:.2f}" if prev_high else "")
        )
        result["suggested_size"] = 1
        return result

    def check_trigger_2(
        self,
        ticker: str,
        k5: pd.DataFrame,
        now_time: datetime,
    ) -> dict:
        """中盤反彈訊號 — 改用盤中最高算跌深 (≥ 2.5%)，支援路徑 A (3 紅 K) 和路徑 B (5m diff)。

        舊 now_time 參數保留向後相容，但不再做時段限制 (任何時段均可觸發)。
        prev_levels 已不需要，只依賴當日 k5。
        """
        result = {"triggered": False, "level": "watch", "reason": "", "price": 0.0, "suggested_size": 0}

        if len(k5) < 3:
            result["reason"] = "5K 資料不足"
            return result

        current_close = float(k5["close"].iloc[-1])
        result["price"] = current_close
        last = k5.iloc[-1]

        # 從盤中最高算跌深
        intraday_high = float(k5["high"].max())
        pullback_pct = (float(last["low"]) - intraday_high) / intraday_high * 100
        if pullback_pct > -2.5:
            result["reason"] = f"未跌深 {pullback_pct:.1f}% (需 ≤ -2.5%、盤中高 {intraday_high:.2f})"
            return result

        # 找最低點
        low_idx = k5["low"].idxmin()
        low_price = float(k5.loc[low_idx, "low"])

        # 最低之後的 K 棒
        after_low = k5.loc[low_idx:].iloc[1:]
        if len(after_low) < 2:
            result["level"] = "watch"
            result["reason"] = f"跌深 {pullback_pct:.1f}% (盤中高 {intraday_high:.2f})、低後 K 不足等確認"
            return result

        # 路徑 A: 連續 3 根紅 K + 距低反彈 ≥ 1%
        last_3 = after_low.tail(3)
        if len(last_3) >= 3:
            all_red = (last_3["close"] > last_3["open"]).all()
            rebound = (float(last_3.iloc[-1]["close"]) - low_price) / low_price * 100
            if all_red and rebound >= 1.0:
                result["triggered"] = True
                result["level"] = "confirmed"
                result["reason"] = (
                    f"跌深 {pullback_pct:.1f}% (盤中高 {intraday_high:.2f})"
                    f" + 3 紅K + 反彈 {rebound:.1f}%"
                )
                result["price"] = float(last_3.iloc[-1]["close"])
                result["suggested_size"] = 1
                result["path"] = "A (3 紅K)"
                return result

        # 路徑 B: 5m diff 由負轉正 + 09:10 後 + 紅K + 量 ≥ 5 根平均
        if len(k5) >= 3:
            diff_prev = float(k5.iloc[-2]["close"]) - float(k5.iloc[-3]["close"])
            diff_now  = float(k5.iloc[-1]["close"]) - float(k5.iloc[-2]["close"])
            current_time = k5.index[-1].strftime("%H:%M") if hasattr(k5.index, "strftime") else "09:30"
            vol_mean5 = k5.tail(5)["volume"].mean()
            if (diff_prev < 0 and diff_now > 0
                    and current_time >= "09:10"
                    and float(last["close"]) > float(last["open"])   # 紅K
                    and float(last["volume"]) >= vol_mean5):          # 量 ≥ 5 根平均
                result["triggered"] = True
                result["level"] = "confirmed"
                result["reason"] = (
                    f"跌深 {pullback_pct:.1f}% (盤中高 {intraday_high:.2f})"
                    f" + 5m diff 由負轉正 (early signal)"
                )
                result["price"] = float(last["close"])
                result["suggested_size"] = 1
                result["path"] = "B (5m diff)"
                return result

        result["level"] = "watch"
        result["reason"] = f"跌深 {pullback_pct:.1f}% (盤中高 {intraday_high:.2f})、等確認"
        return result

    def check_trigger_2_legacy(
        self,
        ticker: str,
        k5: pd.DataFrame,
        now_time: datetime,
    ) -> dict:
        """舊版 check_trigger_2 (時段 11:00-12:30、二次探底、3 根確認)。保留供回溯比較。"""
        result = {"triggered": False, "level": "watch", "reason": "", "price": 0.0, "suggested_size": 0}

        if len(k5) < 8:
            result["reason"] = "5K 資料不足"
            return result

        current_close = float(k5["close"].iloc[-1])
        result["price"] = current_close

        t = now_time.time()
        in_window = (t.hour == 11 or (t.hour == 12 and t.minute <= 30))
        confirm_window = (t.hour == 12 and t.minute > 30) or (t.hour == 13 and t.minute <= 10)
        if not (in_window or confirm_window):
            result["reason"] = f"不在中盤反彈時段 ({t.strftime('%H:%M')})"
            return result

        morning_bars = k5.between_time("09:10", "11:00") if hasattr(k5.index, "time") else k5
        if morning_bars.empty:
            result["reason"] = "早盤資料不足、無法找前波低"
            return result
        first_low = float(morning_bars["low"].min())

        recent = k5.tail(6)
        recent_low = float(recent["low"].min())
        low_diff_pct = abs(recent_low - first_low) / first_low * 100
        if low_diff_pct > 1.5:
            result["reason"] = f"二次低點 {recent_low:.2f} 與前波低 {first_low:.2f} 相差 {low_diff_pct:.1f}% > 1.5%"
            return result

        vol_avg = k5["volume"].rolling(min(len(k5), 20), min_periods=1).mean()
        recent_with_avg = recent.copy()
        recent_with_avg["vol_avg"] = vol_avg.reindex(recent.index)
        breakout_bars = recent_with_avg[recent_with_avg["close"] > recent_with_avg["open"]]
        volume_burst = any(
            float(row["volume"]) >= float(row["vol_avg"]) * 2
            for _, row in breakout_bars.iterrows()
            if float(row["vol_avg"]) > 0
        )

        last3 = k5.tail(3)
        if len(last3) < 3:
            result["level"] = "signal"
            result["reason"] = f"二次探底確認中、等 3 根 (現 {len(last3)} 根)"
            return result

        confirmed = True
        for i in range(1, len(last3)):
            if float(last3["close"].iloc[i]) < float(last3["low"].iloc[i - 1]):
                confirmed = False
                break

        first_bar_red = float(last3["close"].iloc[0]) > float(last3["open"].iloc[0])
        if not confirmed or not first_bar_red:
            if recent_low <= first_low * 1.015:
                result["level"] = "signal"
                result["reason"] = f"二次探底 {recent_low:.2f}、等 3 根確認"
            else:
                result["reason"] = "3 根確認條件未成立"
            return result

        vol_x = float(k5["volume"].iloc[-3]) / float(vol_avg.iloc[-3]) if float(vol_avg.iloc[-3]) > 0 else 0
        rebound_pct = (current_close / recent_low - 1) * 100

        result["triggered"] = True
        result["level"] = "confirmed"
        result["reason"] = (
            f"二次探底 {recent_low:.2f} 反彈 +{rebound_pct:.1f}%、3 根確認"
            + (f"、量×{vol_x:.1f}" if volume_burst else "")
        )
        result["suggested_size"] = 1
        return result

    def check_trigger_c(
        self,
        ticker: str,
        k5: pd.DataFrame,
        prev_low: Optional[float],
    ) -> dict:
        """結構失敗 (跌破前波低 + 距 MA10 -3% + 量爆下行)."""
        result = {"triggered": False, "level": "watch", "reason": "", "price": 0.0, "suggested_size": 0}

        if len(k5) < 5:
            result["reason"] = "5K 資料不足"
            return result

        current_close = float(k5["close"].iloc[-1])
        result["price"] = current_close

        ma10 = k5["close"].rolling(10, min_periods=1).mean().iloc[-1]
        dist_ma10_pct = (current_close / float(ma10) - 1) * 100 if float(ma10) > 0 else 0

        vol_avg = k5["volume"].rolling(min(len(k5), 20), min_periods=1).mean().iloc[-1]
        last_vol = float(k5["volume"].iloc[-1])
        vol_ratio = last_vol / float(vol_avg) if float(vol_avg) > 0 else 0
        last_black = float(k5["close"].iloc[-1]) < float(k5["open"].iloc[-1])

        broken_structure = False
        reason_parts = []

        if prev_low is not None and current_close < prev_low:
            broken_structure = True
            reason_parts.append(f"跌破前波低 {prev_low:.2f}")

        if dist_ma10_pct <= -3.0:
            broken_structure = True
            reason_parts.append(f"距 MA10 {dist_ma10_pct:.1f}%")

        if not broken_structure:
            result["reason"] = f"結構未破壞 (距MA10 {dist_ma10_pct:.1f}%)"
            return result

        if not (vol_ratio >= 1.5 and last_black):
            result["level"] = "signal"
            result["reason"] = "、".join(reason_parts) + f" (量×{vol_ratio:.1f}、等量爆確認)"
            return result

        result["triggered"] = True
        result["level"] = "confirmed"
        result["reason"] = "、".join(reason_parts) + f"、量×{vol_ratio:.1f} 恐慌賣壓"
        return result

    # ── Ch5-3 第一根 5K SOP ────────────────────────────────────────────────────

    def check_ch5_3_entry(
        self,
        k5: pd.DataFrame,
        prev_close: float,
        ma10: Optional[float] = None,
        ticker: Optional[str] = None,
        target_date: Optional[str] = None,
    ) -> dict:
        """Ch5-3 第一根 5K SOP 評估 (老師 5/19 實戰課完整版)。

        6 條件 (第一根):
          1. 紅K
          2. 跳空 < 5%
          3. 收盤 ≥ 前日收盤 (close_above_prev)
          4. 收盤 ≥ 開盤 (雙錨)
          5. 實體 > 上影線 (body_gt_shadow)
          6. 5K 漲幅 < 4% (rise_under_4)

        State 機:
          fail      → 第一根 6/6 不過
          watch     → 9:10 前 / 沒過第一根高、純觀察
          signal    → 9:10 後過第一根高 (通知、不直接切入)
          pullback  → 過高後回踩 MA10 附近 (距 -2%~+2%)
          confirmed → pullback 期間 5K 紅K + 收盤 > MA10 → 正式進場

        雙錨停損 = max(第一根 5K 低、昨日收盤)
        """
        # 若未傳 ma10，嘗試從 DB 查
        if ma10 is None and ticker and target_date:
            ma10 = _get_ma10(ticker, target_date)

        result: dict = {
            "triggered": False,
            "level": "watch",
            "reason": "",
            "stop_loss": None,
            "stop_anchors": {},
        }

        if len(k5) < 1:
            result["reason"] = "5K 不足"
            return result

        first   = k5.iloc[0]
        open_p  = float(first["open"])
        high_p  = float(first["high"])
        low_p   = float(first["low"])
        close_p = float(first["close"])

        red_k            = close_p > open_p
        gap_pct          = (open_p - prev_close) / prev_close * 100 if prev_close > 0 else 999
        close_above_prev = close_p >= prev_close
        close_above_open = close_p >= open_p
        body             = abs(close_p - open_p)
        upper            = high_p - max(close_p, open_p)
        body_gt_shadow   = body > upper
        chg_pct          = (close_p - open_p) / open_p * 100 if open_p > 0 else 0
        rise_under_4     = chg_pct < 4.0
        gap_ok           = gap_pct < 5.0

        all_pass = all([red_k, close_above_prev, close_above_open,
                        body_gt_shadow, rise_under_4, gap_ok])

        if not all_pass:
            fails = []
            if not red_k:            fails.append("非紅K")
            if not gap_ok:           fails.append(f"跳空 {gap_pct:.1f}% ≥ 5%")
            if not close_above_prev: fails.append(f"收盤 {close_p:.2f} < 前收 {prev_close:.2f}")
            if not close_above_open: fails.append("收盤 < 開盤 (雙錨失守)")
            if not body_gt_shadow:   fails.append(f"實體 {body:.2f} ≤ 上影 {upper:.2f}")
            if not rise_under_4:     fails.append(f"漲幅 {chg_pct:.1f}% ≥ 4%")
            result["level"] = "fail"
            result["reason"] = "第一根 5K 不符: " + ", ".join(fails)
            return result

        # 雙錨停損：取第一根 5K 低、昨日收盤 兩者最高
        first_low = low_p
        stop_candidates = [first_low, prev_close]
        stop_loss = max(stop_candidates)
        result["stop_loss"] = stop_loss
        result["stop_anchors"] = {
            "first_5k_low": first_low,
            "prev_close": prev_close,
        }

        first_high = high_p

        def _t(ts) -> str:
            """將 index timestamp 轉為 HH:MM 字串。"""
            if hasattr(ts, "strftime"):
                return ts.strftime("%H:%M")
            return str(ts)[11:16]

        # ── 找 signal：9:10 後第一根過第一根高的紅 K ───────────────────────────
        signal_idx: Optional[int] = None
        for i in range(1, len(k5)):
            if _t(k5.index[i]) < "09:10":
                continue
            bar_close = float(k5.iloc[i]["close"])
            bar_open  = float(k5.iloc[i]["open"])
            if bar_close > first_high and bar_close > bar_open:
                signal_idx = i
                break

        if signal_idx is None:
            result["level"] = "watch"
            result["reason"] = f"Ch5-3 第一根全 pass、等 9:10 後過高 {first_high:.2f}"
            return result

        # signal 觸發
        result["level"] = "signal"
        if ma10 is not None:
            result["reason"] = f"訊號觸發 {_t(k5.index[signal_idx])} 過高 {first_high:.2f}、等回踩 MA10 ({ma10:.2f})"
        else:
            result["reason"] = f"訊號觸發 {_t(k5.index[signal_idx])} 過高 {first_high:.2f}、MA10 未知"

        # ── 從 signal_idx 往後找回踩 + 守住 ────────────────────────────────────
        if ma10 is None or ma10 <= 0:
            # 無法判斷回踩、停在 signal
            return result

        MA10_BAND = 0.02  # ±2%
        for i in range(signal_idx + 1, len(k5)):
            bar       = k5.iloc[i]
            bar_low   = float(bar["low"])
            bar_close = float(bar["close"])
            bar_open  = float(bar["open"])

            # 是否回踩（盤中最低觸及 MA10 ±2%）
            touched_ma10 = bar_low <= ma10 * (1 + MA10_BAND) and bar_low >= ma10 * (1 - MA10_BAND)

            if touched_ma10:
                result["level"] = "pullback"
                result["reason"] = f"回踩 MA10 {ma10:.2f} 中、等收紅 K 守住"
                # 守住確認：紅K + 收盤 > MA10
                if bar_close > bar_open and bar_close > ma10:
                    result["triggered"] = True
                    result["level"] = "confirmed"
                    result["reason"] = (
                        f"過高 {first_high:.2f} + 回踩 MA10 {ma10:.2f} 守住 "
                        f"(紅K {_t(k5.index[i])})"
                    )
                    result["entry_price"] = bar_close
                    result["entry_time"]  = _t(k5.index[i])
                    return result

        # 掃完沒 confirmed
        if result["level"] == "pullback":
            result["reason"] = f"回踩 MA10 {ma10:.2f} 中、等收紅 K 守住"
        else:
            result["reason"] = f"訊號觸發、等回踩 MA10 ({ma10:.2f})"
        return result

    # ── Composite Cascade Detector ─────────────────────────────────────────────

    # Per-category action mapping
    _CATEGORY_ACTION: dict[tuple[str, str], str] = {
        ("HELD",         "Ch5-3"): "N/A (已持倉、Ch5-3 不適用)",
        ("HELD",         "T1"):    "Stage 2 加碼追高",
        ("HELD",         "T2"):    "Stage 2 反彈低接加碼",
        ("HELD",         "TC"):    "🚨 出 Stage 1 警示",
        ("WATCH",        "Ch5-3"): "Stage 1 試水進場 (當沖 SOP)",
        ("WATCH",        "T1"):    "Stage 1 試水追高",
        ("WATCH",        "T2"):    "Stage 1 反彈低接",
        ("WATCH",        "TC"):    "⛔ 不要進、結構壞",
        ("PLAN_PRIMARY", "Ch5-3"): "進場時機 (Ch5-3)",
        ("PLAN_PRIMARY", "T1"):    "進場時機 (T1)",
        ("PLAN_PRIMARY", "T2"):    "進場時機 (T2)",
        ("PLAN_PRIMARY", "TC"):    "⛔ skip 該檔",
    }

    def _format_action(self, result: dict, detector_type: str, category: str) -> dict:
        """Per-category action mapping，回傳含 detector / category / action 的 dict。"""
        action = self._CATEGORY_ACTION.get(
            (category, detector_type),
            "N/A",
        )
        return {
            **result,
            "triggered": True,
            "detector": detector_type,
            "category": category,
            "action": action,
        }

    def composite_check(
        self,
        ticker: str,
        k5: pd.DataFrame,
        prev_close: float,
        prev_levels: dict,
        category: str = "WATCH",
    ) -> dict:
        """Cascade detector: Ch5-3 → T1 → T2 → TC。

        Args:
            ticker:      股票代號 (傳給底層 check_ 函式)
            k5:          當日 5 分 K DataFrame
            prev_close:  前日收盤價
            prev_levels: {'prev_close', 'prev_high', 'prev_low'}
            category:    'HELD' / 'WATCH' / 'PLAN_PRIMARY'

        Returns:
            dict with keys: triggered, detector, category, action, reason, [price]
        """
        prev_high = prev_levels.get("prev_high")
        prev_low  = prev_levels.get("prev_low")

        # Layer 1: Ch5-3 當沖 entry
        # 傳 ticker + target_date 讓 check_ch5_3_entry 自動查 MA10
        _today_str = date.today().isoformat()
        r = self.check_ch5_3_entry(
            k5, prev_close,
            ticker=ticker,
            target_date=_today_str,
        )
        if r.get("triggered"):
            return self._format_action(r, "Ch5-3", category)

        # Ch5-3 signal / pullback 也需要上報（不 triggered 但 level 有意義）
        ch53_level = r.get("level", "watch")
        if ch53_level in ("signal", "pullback"):
            # 用 detector key = 'Ch5-3_signal' or 'Ch5-3_pullback'
            return self._format_action(
                {**r, "triggered": True},
                f"Ch5-3_{ch53_level}",
                category,
            )

        # Layer 2: T1 強勢延續
        r = self.check_trigger_1(ticker, k5, prev_high)
        if r.get("triggered"):
            return self._format_action(r, "T1", category)

        # Layer 3: T2 跌深反彈 (新版、盤中高)
        # now_time 傳 datetime.min 表示不做時段限制 (新版已移除時段限制)
        r = self.check_trigger_2(ticker, k5, datetime.min)
        if r.get("triggered"):
            return self._format_action(r, "T2", category)

        # Layer 4: TC 結構失敗
        r = self.check_trigger_c(ticker, k5, prev_low)
        if r.get("triggered"):
            return self._format_action(r, "TC", category)

        return {
            "triggered": False,
            "detector":  "none",
            "category":  category,
            "action":    "—",
            "reason":    r.get("reason", ""),
        }


# ── 主監控邏輯 ────────────────────────────────────────────────────────────────

def _get_prev_levels(ticker: str, db: Path) -> dict:
    """從 DB 取前日收盤、前波高/低."""
    closes = load_daily_closes(ticker, db, n=10)
    if len(closes) < 2:
        return {}
    prev_close = float(closes.iloc[-2]) if len(closes) >= 2 else None
    recent_high = float(closes.tail(5).max())
    recent_low  = float(closes.tail(5).min())
    return {
        "prev_close": prev_close,
        "prev_high":  recent_high,
        "prev_low":   recent_low,
    }


def run_monitor(
    tickers: list[tuple[str, str, str]],  # (ticker, name, tactic)
    interval: int,
    notify: bool,
    no_discipline: bool,
    start_time: str,
    end_time: str,
    log_path: Optional[Path],
    db: Path,
) -> None:
    trigger_engine = StageTrigger()
    cooldown: dict[str, datetime] = {}
    COOLDOWN_MIN = 30

    fh = None
    if log_path:
        fh = open(log_path, "a", buffering=1)

    def _log(msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        log.info(msg)
        if fh:
            fh.write(line + "\n")

    _log(f"Stage Helper 啟動 — 監控 {[t[0] for t in tickers]}、間隔 {interval}s")

    st_h, st_m = (int(x) for x in start_time.split(":"))
    et_h, et_m = (int(x) for x in end_time.split(":"))

    while True:
        now = datetime.now()
        t = now.time()

        if t.hour < st_h or (t.hour == st_h and t.minute < st_m):
            _log(f"等待開盤 ({start_time})…")
            time.sleep(30)
            continue

        if t.hour > et_h or (t.hour == et_h and t.minute >= et_m):
            _log(f"已過收盤時間 ({end_time})，停止監控。")
            break

        for ticker, name, tactic in tickers:
            try:
                k5 = fetch_5min_kbar(ticker, now.date())
                if k5.empty:
                    _log(f"{ticker} {name}: 無 5K 資料")
                    continue

                prev = _get_prev_levels(ticker, db)
                pass_discipline, disc_reason = trigger_engine.check_discipline_filter(
                    ticker, k5, now, prev.get("prev_close"), disable=no_discipline
                )
                if not pass_discipline:
                    _log(f"  [{ticker}] 紀律過濾: {disc_reason}")
                    continue

                # ── Cascade composite_check (新) ──────────────────────────────
                # category: HELD / WATCH / PLAN_PRIMARY 可由呼叫方傳入；
                # 這裡 run_monitor 走 tactic 判斷 category
                category = "HELD" if tactic in ("核心",) else "WATCH"
                prev_close = prev.get("prev_close") or 0.0
                result = trigger_engine.composite_check(
                    ticker=ticker,
                    k5=k5,
                    prev_close=prev_close,
                    prev_levels=prev,
                    category=category,
                )

                detector   = result.get("detector", "none")
                action     = result.get("action", "")
                reason     = result.get("reason", "")
                price      = result.get("price", 0.0)
                cd_key     = f"{ticker}_{detector}"

                if result.get("triggered") and now > cooldown.get(cd_key, datetime.min):
                    cooldown[cd_key] = now + timedelta(minutes=COOLDOWN_MIN)
                    msg = f"現 ${price:.2f}、{action} | {reason[:60]}"

                    if detector == "Ch5-3":
                        _log(f"🟡 Ch5-3 {ticker} {name}: {reason}")
                        if notify:
                            notify_mac(f"🟡 {ticker} {name} Ch5-3 SOP", msg)
                    elif detector == "T1":
                        _log(f"🟢 Trigger 1 {ticker} {name}: {reason}")
                        if notify:
                            notify_mac(f"🟢 {ticker} {name} Trigger 1 強勢延續", msg)
                    elif detector == "T2":
                        _log(f"🎯 Trigger 2 {ticker} {name}: {reason}")
                        if notify:
                            notify_mac(f"🎯 {ticker} {name} Trigger 2 反彈訊號", msg)
                    elif detector == "TC":
                        _log(f"🚨 Trigger C {ticker} {name}: {reason}")
                        if notify:
                            notify_mac(f"🚨 {ticker} {name} 結構失敗", msg, sound="Sosumi")
                elif not result.get("triggered"):
                    _log(f"  [{ticker}] cascade: {detector} — {reason[:60]}")

            except Exception as e:
                _log(f"[ERROR] {ticker}: {e}")

        time.sleep(interval)

    if fh:
        fh.close()


# ── FinMind 真實資料抓取 ──────────────────────────────────────────────────────

def _fetch_finmind_1m(ticker: str, target_date: str) -> pd.DataFrame:
    """用 FinMind TaiwanStockKBar 拉 1 分 K，聚合成 5 分 K。"""
    import os
    import requests

    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        print("[WARN] FINMIND_TOKEN 未設定，無法抓取真實資料")
        return pd.DataFrame()

    try:
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
            print(f"[WARN] FinMind 回傳無資料: {data.get('msg', '')}")
            return pd.DataFrame()
        df = pd.DataFrame(data["data"])
        if df.empty:
            return pd.DataFrame()
        # FinMind KBar 欄位: date (YYYY-MM-DD), minute (HH:MM:SS), stock_id, open, high, low, close, volume
        if "minute" in df.columns:
            df["datetime"] = pd.to_datetime(df["date"].astype(str) + " " + df["minute"].astype(str))
        else:
            df["datetime"] = pd.to_datetime(df["date"])
        df = df.sort_values("datetime").set_index("datetime")
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        # 先過濾目標日期
        td = date.fromisoformat(target_date)
        df = df[df.index.date == td]
        if df.empty:
            return pd.DataFrame()
        # 聚合成 5 分 K
        df5 = df.resample("5min", label="left", closed="left").agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        ).dropna(subset=["open", "close"])
        return df5
    except Exception as e:
        print(f"[ERROR] FinMind 抓取失敗: {e}")
        return pd.DataFrame()


# ── 模擬模式 ──────────────────────────────────────────────────────────────────

# 驗證情境設定
_SIM_CASES: dict[str, dict] = {
    # Case 1: 1605 5/29 → 預期走 Ch5-3 路徑
    # 5/28 收 36.0、5/29 第一根 5K 開 36.65 高 37.70 收 37.55
    "1605_2026-05-29": {
        "ticker": "1605",
        "date": "2026-05-29",
        "prev_close": 36.0,
        "prev_high": 36.5,
        "prev_low": 34.8,
        "expected_detector": "Ch5-3",
        "note": "5/28 收 36.0、5/29 第一根 5K 紅K、全 pass、預期 Ch5-3",
    },
    # Case 2: 1605 6/1 → 預期走 T2 路徑
    # 5/29 收 38.80、6/1 第一根 5K 開 39.30 收 39.15 (黑K、雙錨失守)
    "1605_2026-06-01": {
        "ticker": "1605",
        "date": "2026-06-01",
        "prev_close": 38.80,
        "prev_high": 39.5,
        "prev_low": 37.5,
        "expected_detector": "T2",
        "note": "5/29 收 38.80、6/1 第一根 5K 黑K、Ch5-3 失敗、預期 T2",
    },
}


def run_simulation(sim_date_str: str, sim_ticker: str, notify: bool, no_discipline: bool) -> None:
    """模擬模式: 用 FinMind 真實 5K 跑 composite_check cascade 驗證。"""
    engine = StageTrigger()
    case_key = f"{sim_ticker}_{sim_date_str}"

    # 取 case 設定 (若無則用預設)
    case = _SIM_CASES.get(case_key, {})
    prev_close = case.get("prev_close", 0.0)
    prev_high  = case.get("prev_high", prev_close * 1.02)
    prev_low   = case.get("prev_low",  prev_close * 0.97)
    expected_detector = case.get("expected_detector", "?")
    note = case.get("note", "")

    print(f"\n{'='*60}")
    print(f"  模擬: {sim_ticker} {sim_date_str}")
    if note:
        print(f"  {note}")
    print(f"  前收: {prev_close:.2f}  期望 detector: {expected_detector}")
    print(f"{'='*60}")

    # 嘗試從 FinMind 取真實資料
    k5_full = _fetch_finmind_1m(sim_ticker, sim_date_str)
    if k5_full.empty:
        # fallback: 若是原有模擬資料日期則用 _build_simulated_5k_1605
        if sim_ticker == "1605" and sim_date_str == "2026-06-02":
            print("[INFO] 使用內建 1605 2026-06-02 模擬資料 (FinMind 無資料)")
            k5_full = _build_simulated_5k_1605()
        else:
            print(f"[WARN] FinMind 無 {sim_ticker} {sim_date_str} 資料，無法執行驗證")
            return

    print(f"  5K 資料共 {len(k5_full)} 根  ({k5_full.index[0].strftime('%H:%M')} ~ {k5_full.index[-1].strftime('%H:%M')})")
    print()

    prev_levels = {"prev_close": prev_close, "prev_high": prev_high, "prev_low": prev_low}

    first_triggered: Optional[dict] = None
    print(f"  {'時間':6}  {'紀律':8}  {'detector':10}  action / reason")
    print(f"  {'─'*80}")

    for i in range(1, len(k5_full) + 1):
        k5 = k5_full.iloc[:i]
        ts  = k5_full.index[i - 1]
        ts_str = ts.strftime("%H:%M")
        sim_now = ts.to_pydatetime()

        pass_disc, disc_reason = engine.check_discipline_filter(
            sim_ticker, k5, sim_now, prev_close, disable=no_discipline
        )

        result = engine.composite_check(
            ticker=sim_ticker,
            k5=k5,
            prev_close=prev_close,
            prev_levels=prev_levels,
            category="PLAN_PRIMARY",
        )

        det = result.get("detector", "none")
        act = result.get("action", "")
        rsn = result.get("reason", "")
        triggered = result.get("triggered", False)

        disc_tag = "✅" if pass_disc else "❌"
        if triggered:
            price = result.get("price", 0.0)
            print(f"  {ts_str}  {disc_tag}  {det:10}  {act} | {rsn[:50]}  @ ${price:.2f}")
            if first_triggered is None:
                first_triggered = {**result, "ts": ts_str}
        # 只列有變化的節點，避免輸出過多
        # (非 triggered 只在每 5 根或重要時間列印)
        elif i <= 3 or ts_str in ("09:10", "09:15", "09:30", "10:00", "11:00", "12:00", "13:00"):
            print(f"  {ts_str}  {disc_tag}  {det:10}  {rsn[:55]}")

    print(f"\n  {'─'*80}")
    if first_triggered:
        det = first_triggered.get("detector", "none")
        price = first_triggered.get("price", 0.0)
        ts_str = first_triggered.get("ts", "?")
        action = first_triggered.get("action", "")
        ok = (det == expected_detector) or expected_detector == "?"
        result_tag = "✅ PASS" if ok else f"❌ FAIL (期望 {expected_detector})"
        print(f"  首次觸發: {det} @ {ts_str}  ${price:.2f}  {action}")
        print(f"  驗證: {result_tag}")
    else:
        ok = expected_detector in ("none", "?")
        print(f"  驗證: {'✅ PASS (無訊號如預期)' if ok else f'❌ FAIL (期望 {expected_detector} 但無觸發)'}")

    print(f"{'='*60}\n")

    if notify and first_triggered:
        price = first_triggered.get("price", 0.0)
        det   = first_triggered.get("detector", "")
        notify_mac(
            f"模擬 {sim_ticker} {sim_date_str} {det}",
            f"首次觸發 @ {first_triggered.get('ts', '?')} ${price:.2f}"
        )


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args():
    p = argparse.ArgumentParser(description="盤中 Stage Trigger 偵測器")
    p.add_argument("--tickers", default="", help="逗號分隔 ticker (預設讀 HELD + WATCH)")
    p.add_argument("--interval", type=int, default=60, help="檢查間隔秒數 (預設 60)")
    p.add_argument("--notify", action="store_true", default=True, help="推 macOS 通知 (預設 ON)")
    p.add_argument("--no-notify", dest="notify", action="store_false")
    p.add_argument("--no-discipline", action="store_true", default=False,
                   help="略過紀律過濾 (debug 用)")
    p.add_argument("--start-time", default="09:10", help="開始監控時間 (預設 09:10)")
    p.add_argument("--end-time",   default="13:25", help="停止監控時間 (預設 13:25)")
    p.add_argument("--log", default=None, help="log 寫入路徑 (預設 /tmp/intraday_stage.log)")
    p.add_argument("--db", default=str(_DB), help="DB 路徑")
    p.add_argument("--simulate-date", default=None,
                   help="模擬模式: YYYY-MM-DD (不連線 API、用內建測資)")
    p.add_argument("--simulate-ticker", default="1605",
                   help="模擬 ticker (目前僅支援 1605, 預設 1605)")
    return p.parse_args()


def _build_ticker_list(raw_tickers: str) -> list[tuple[str, str, str]]:
    """回傳 [(ticker, name, tactic)]."""
    name_map: dict[str, str] = {}
    try:
        db = Path(_DB)
        if db.exists():
            name_map = load_stock_names(db)
    except Exception:
        pass

    result: list[tuple[str, str, str]] = []

    if raw_tickers:
        for t in raw_tickers.split(","):
            t = t.strip()
            if t:
                result.append((t, name_map.get(t, t), "核心"))
        return result

    # 預設從 HELD + WATCH 讀
    for ticker, name, *_ in HELD:
        tactic = _[-1] if _ else "核心"
        result.append((ticker, name_map.get(ticker, name), tactic))
    for ticker, name, *_ in WATCH:
        tactic = _[-1] if _ else "短打"
        result.append((ticker, name_map.get(ticker, name), tactic))

    return result


def main():
    args = _parse_args()
    db = Path(args.db)

    if args.simulate_date:
        run_simulation(
            sim_date_str=args.simulate_date,
            sim_ticker=args.simulate_ticker,
            notify=args.notify,
            no_discipline=args.no_discipline,
        )
        return

    tickers = _build_ticker_list(args.tickers)
    log_path = Path(args.log) if args.log else Path("/tmp/intraday_stage.log")

    run_monitor(
        tickers=tickers,
        interval=args.interval,
        notify=args.notify,
        no_discipline=args.no_discipline,
        start_time=args.start_time,
        end_time=args.end_time,
        log_path=log_path,
        db=db,
    )


if __name__ == "__main__":
    main()
